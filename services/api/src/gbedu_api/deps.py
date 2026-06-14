from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Annotated

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gbedu_core.config import get_settings
from gbedu_core.db import get_db as _core_get_db
from gbedu_core.errors import AuthenticationError, AuthorizationError, TokenExpiredError, TokenInvalidError
from gbedu_core.models.user import SubscriptionTier, User
from gbedu_core.security import verify_access_token
from slowapi import Limiter
from slowapi.util import get_remote_address

if TYPE_CHECKING:
	from gbedu_api.services.storage_service import StorageClient
	from gbedu_api.services.ml_client import MLServiceClient

log = structlog.get_logger(__name__)

# ── Rate limiter (module-level singleton — imported by routers) ────────────────

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

# ── OAuth2 scheme ──────────────────────────────────────────────────────────────

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

# ── Module-level singletons initialised at startup ────────────────────────────

_redis: Redis | None = None
_storage_client: "StorageClient | None" = None
_ml_client: "MLServiceClient | None" = None


def set_redis(r: Redis) -> None:
	global _redis
	_redis = r


def set_storage_client(c: "StorageClient") -> None:
	global _storage_client
	_storage_client = c


def set_ml_client(c: "MLServiceClient") -> None:
	global _ml_client
	_ml_client = c


# ── Database ───────────────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
	async for session in _core_get_db():
		yield session


# ── Redis ──────────────────────────────────────────────────────────────────────

async def get_redis() -> Redis:
	assert _redis is not None, "Redis not initialised — call set_redis() at startup"
	return _redis


# ── Storage ────────────────────────────────────────────────────────────────────

async def get_storage() -> "StorageClient":
	assert _storage_client is not None, "StorageClient not initialised"
	return _storage_client


# ── ML client ─────────────────────────────────────────────────────────────────

async def get_ml_client() -> "MLServiceClient":
	assert _ml_client is not None, "MLServiceClient not initialised"
	return _ml_client


# ── Auth dependencies ──────────────────────────────────────────────────────────

async def get_current_user(
	token: Annotated[str | None, Depends(_oauth2_scheme)],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
	if not token:
		raise HTTPException(
			status_code=status.HTTP_401_UNAUTHORIZED,
			detail={"error_code": "AUTHENTICATION_ERROR", "message": "Authentication required"},
			headers={"WWW-Authenticate": "Bearer"},
		)

	settings = get_settings()
	try:
		payload = verify_access_token(
			token,
			settings.jwt.secret_key,
			settings.jwt.algorithm,
		)
	except TokenExpiredError:
		raise HTTPException(
			status_code=status.HTTP_401_UNAUTHORIZED,
			detail={"error_code": "TOKEN_EXPIRED", "message": "Token has expired"},
			headers={"WWW-Authenticate": "Bearer"},
		)
	except TokenInvalidError:
		raise HTTPException(
			status_code=status.HTTP_401_UNAUTHORIZED,
			detail={"error_code": "TOKEN_INVALID", "message": "Token is invalid"},
			headers={"WWW-Authenticate": "Bearer"},
		)

	user_id: str | None = payload.get("sub")
	if not user_id:
		raise HTTPException(
			status_code=status.HTTP_401_UNAUTHORIZED,
			detail={"error_code": "TOKEN_INVALID", "message": "Token missing subject"},
			headers={"WWW-Authenticate": "Bearer"},
		)

	result = await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
	user = result.scalar_one_or_none()

	if user is None:
		raise HTTPException(
			status_code=status.HTTP_401_UNAUTHORIZED,
			detail={"error_code": "AUTHENTICATION_ERROR", "message": "User not found"},
			headers={"WWW-Authenticate": "Bearer"},
		)

	return user


async def get_current_active_user(
	user: Annotated[User, Depends(get_current_user)],
) -> User:
	if not user.is_active:
		raise HTTPException(
			status_code=status.HTTP_403_FORBIDDEN,
			detail={"error_code": "AUTHORIZATION_ERROR", "message": "Account is inactive"},
		)
	return user


def require_tier(min_tier: SubscriptionTier):
	"""Factory returning a FastAPI dependency that enforces a minimum subscription tier.

	Tier order: free < creator < pro < label
	"""
	_tier_order = [
		SubscriptionTier.free,
		SubscriptionTier.creator,
		SubscriptionTier.pro,
		SubscriptionTier.label,
	]

	async def _check(user: Annotated[User, Depends(get_current_active_user)]) -> User:
		user_rank = _tier_order.index(user.subscription_tier)
		required_rank = _tier_order.index(min_tier)
		if user_rank < required_rank:
			raise HTTPException(
				status_code=status.HTTP_403_FORBIDDEN,
				detail={
					"error_code": "AUTHORIZATION_ERROR",
					"message": f"This feature requires {min_tier.value} subscription or higher",
					"details": {
						"required_tier": min_tier.value,
						"current_tier": user.subscription_tier.value,
					},
				},
			)
		return user

	return _check


