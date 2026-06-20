from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gbedu_core._uuid7 import uuid7str
from gbedu_core.config import get_settings
from gbedu_core.errors import (
	AuthenticationError,
	ConflictError,
	DatabaseIntegrityError,
	InvalidCredentialsError,
	NotFoundError,
	TokenInvalidError,
)
from gbedu_core.models.user import User
from gbedu_core.security import (
	create_access_token,
	create_refresh_token,
	hash_password,
	verify_password,
	verify_refresh_token,
)

log = structlog.get_logger(__name__)

# Valid bcrypt hash used for constant-time comparison when a user is not found,
# preventing timing-based email enumeration. Computed once at module load.
_DUMMY_HASH: str = hash_password("__gbedu_timing_sentinel__")

_REFRESH_BLOCKLIST_PREFIX = "refresh_blocklist:"
_EMAIL_VERIFY_PREFIX = "email_verify:"
_RESET_TOKEN_PREFIX = "password_reset:"
_TOKEN_BYTES = 32

# FMEA S02: token family revocation — if a used (blocklisted) refresh token is
# replayed it indicates theft. Invalidate the entire family for this user.
_REFRESH_FAMILY_REVOKED_PREFIX = "refresh_family_revoked:"
_REFRESH_FAMILY_REVOKE_TTL = 30 * 86400  # 30 days (> max refresh token lifetime)


def _now() -> datetime:
	return datetime.now(timezone.utc)


class TokenPair:
	__slots__ = ("access_token", "refresh_token", "token_type")

	def __init__(self, access_token: str, refresh_token: str) -> None:
		self.access_token = access_token
		self.refresh_token = refresh_token
		self.token_type = "bearer"


class AuthService:
	def __init__(self, db: AsyncSession, redis: Redis) -> None:
		self._db = db
		self._redis = redis
		self._settings = get_settings()

	def _make_tokens(self, user_id: str) -> TokenPair:
		cfg = self._settings.jwt
		access = create_access_token(
			subject=user_id,
			secret_key=cfg.secret_key,
			algorithm=cfg.algorithm,
			expires_minutes=cfg.access_token_expire_minutes,
		)
		refresh = create_refresh_token(
			subject=user_id,
			secret_key=cfg.secret_key,
			algorithm=cfg.algorithm,
			expires_days=cfg.refresh_token_expire_days,
		)
		return TokenPair(access, refresh)

	async def register(
		self,
		email: str,
		password: str,
		full_name: str,
	) -> tuple[User, TokenPair]:
		assert email and password and full_name, "email, password, and full_name are required"

		existing = await self._db.execute(select(User).where(User.email == email.lower()))
		if existing.scalar_one_or_none() is not None:
			raise ConflictError(f"Email {email} is already registered")

		user = User(
			id=uuid7str(),
			email=email.lower(),
			hashed_password=hash_password(password),
			full_name=full_name,
			is_active=True,
			is_verified=False,
		)
		self._db.add(user)
		try:
			await self._db.flush()
		except IntegrityError as exc:
			raise DatabaseIntegrityError(
				"Email already registered", constraint="users_email_key"
			) from exc

		tokens = self._make_tokens(user.id)
		log.info("auth.register", user_id=user.id, email=email)
		return user, tokens

	async def login(self, email: str, password: str) -> tuple[User, TokenPair]:
		assert email and password, "email and password are required"

		result = await self._db.execute(
			select(User).where(User.email == email.lower(), User.deleted_at.is_(None))
		)
		user = result.scalar_one_or_none()

		# Evaluate password even when user is None to prevent timing attacks
		hashed = user.hashed_password if user else _DUMMY_HASH
		valid = verify_password(password, hashed) if hashed else False

		if not user or not valid:
			raise InvalidCredentialsError()

		if not user.is_active:
			raise AuthenticationError("Account is deactivated")

		tokens = self._make_tokens(user.id)
		log.info("auth.login", user_id=user.id)
		return user, tokens

	async def refresh(self, refresh_token: str) -> TokenPair:
		assert refresh_token, "refresh_token is required"

		blocklist_key = f"{_REFRESH_BLOCKLIST_PREFIX}{refresh_token[:64]}"
		blocked = await self._redis.exists(blocklist_key)
		if blocked:
			# FMEA S02: a blocklisted (already-rotated) token was replayed.
			# This is a strong signal of token theft — invalidate the entire
			# refresh token family for this user to force re-authentication.
			try:
				cfg = self._settings.jwt
				payload = verify_refresh_token(refresh_token, cfg.secret_key, cfg.algorithm)
				stolen_user_id: str = payload.get("sub", "unknown")
				family_key = f"{_REFRESH_FAMILY_REVOKED_PREFIX}{stolen_user_id}"
				await self._redis.setex(family_key, _REFRESH_FAMILY_REVOKE_TTL, "1")
				log.warning(
					"auth.refresh_token_replay_detected",
					user_id=stolen_user_id,
					action="family_revoked",
				)
			except Exception:
				pass  # best-effort; primary response is still TokenInvalidError
			raise TokenInvalidError()

		cfg = self._settings.jwt
		payload = verify_refresh_token(refresh_token, cfg.secret_key, cfg.algorithm)
		user_id: str = payload["sub"]

		# FMEA S02: check if this user's entire token family has been revoked.
		family_key = f"{_REFRESH_FAMILY_REVOKED_PREFIX}{user_id}"
		if await self._redis.exists(family_key):
			log.warning("auth.refresh_family_revoked", user_id=user_id)
			raise TokenInvalidError()

		result = await self._db.execute(
			select(User).where(User.id == user_id, User.deleted_at.is_(None))
		)
		user = result.scalar_one_or_none()
		if user is None or not user.is_active:
			raise TokenInvalidError()

		# Invalidate old refresh token
		exp: int = payload.get("exp", 0)
		ttl = max(exp - int(_now().timestamp()), 1)
		await self._redis.setex(blocklist_key, ttl, "1")

		return self._make_tokens(user_id)

	async def logout(self, refresh_token: str) -> None:
		assert refresh_token, "refresh_token is required"

		cfg = self._settings.jwt
		try:
			payload = verify_refresh_token(refresh_token, cfg.secret_key, cfg.algorithm)
			exp: int = payload.get("exp", 0)
			ttl = max(exp - int(_now().timestamp()), 1)
		except (TokenInvalidError, Exception):
			# Still blocklist it with a safe TTL
			ttl = cfg.refresh_token_expire_days * 86400

		blocklist_key = f"{_REFRESH_BLOCKLIST_PREFIX}{refresh_token[:64]}"
		await self._redis.setex(blocklist_key, ttl, "1")
		log.info("auth.logout", token_prefix=refresh_token[:8])

	async def create_email_verification_token(self, user_id: str) -> str:
		assert user_id, "user_id is required"
		token = secrets.token_urlsafe(_TOKEN_BYTES)
		ttl = 24 * 3600  # 24 hours
		await self._redis.setex(f"{_EMAIL_VERIFY_PREFIX}{token}", ttl, user_id)
		return token

	async def verify_email(self, token: str) -> User:
		assert token, "token is required"
		key = f"{_EMAIL_VERIFY_PREFIX}{token}"
		user_id_bytes = await self._redis.get(key)
		if not user_id_bytes:
			raise TokenInvalidError()

		user_id = user_id_bytes.decode() if isinstance(user_id_bytes, bytes) else user_id_bytes

		result = await self._db.execute(
			select(User).where(User.id == user_id, User.deleted_at.is_(None))
		)
		user = result.scalar_one_or_none()
		if user is None:
			raise NotFoundError("User", user_id)

		user.is_verified = True
		self._db.add(user)
		await self._db.flush()
		await self._redis.delete(key)

		log.info("auth.email_verified", user_id=user_id)
		return user

	async def create_password_reset_token(self, email: str) -> str | None:
		"""Return a reset token if the email exists, else None (caller must not reveal which)."""
		result = await self._db.execute(
			select(User).where(User.email == email.lower(), User.deleted_at.is_(None))
		)
		user = result.scalar_one_or_none()
		if user is None:
			return None

		token = secrets.token_urlsafe(_TOKEN_BYTES)
		ttl = 1 * 3600  # 1 hour
		await self._redis.setex(f"{_RESET_TOKEN_PREFIX}{token}", ttl, user.id)
		return token

	async def reset_password(self, token: str, new_password: str) -> User:
		assert token and new_password, "token and new_password are required"

		key = f"{_RESET_TOKEN_PREFIX}{token}"
		user_id_bytes = await self._redis.get(key)
		if not user_id_bytes:
			raise TokenInvalidError()

		user_id = user_id_bytes.decode() if isinstance(user_id_bytes, bytes) else user_id_bytes

		result = await self._db.execute(
			select(User).where(User.id == user_id, User.deleted_at.is_(None))
		)
		user = result.scalar_one_or_none()
		if user is None:
			raise NotFoundError("User", user_id)

		user.hashed_password = hash_password(new_password)
		self._db.add(user)
		await self._db.flush()
		await self._redis.delete(key)

		log.info("auth.password_reset", user_id=user_id)
		return user

	async def oauth_callback(
		self,
		provider: str,
		provider_id: str,
		email: str,
		full_name: str,
		avatar_url: str | None = None,
	) -> tuple[User, TokenPair]:
		assert provider and provider_id and email, "provider, provider_id, and email required"

		# Try to find existing OAuth user
		result = await self._db.execute(
			select(User).where(
				User.oauth_provider == provider,
				User.oauth_provider_id == provider_id,
				User.deleted_at.is_(None),
			)
		)
		user = result.scalar_one_or_none()

		if user is None:
			# Fall back to email match (user may have registered with password earlier)
			result = await self._db.execute(
				select(User).where(User.email == email.lower(), User.deleted_at.is_(None))
			)
			user = result.scalar_one_or_none()

		if user is None:
			user = User(
				id=uuid7str(),
				email=email.lower(),
				full_name=full_name,
				oauth_provider=provider,
				oauth_provider_id=provider_id,
				avatar_url=avatar_url,
				is_active=True,
				is_verified=True,
			)
			self._db.add(user)
		else:
			user.oauth_provider = provider
			user.oauth_provider_id = provider_id
			if avatar_url and not user.avatar_url:
				user.avatar_url = avatar_url
			self._db.add(user)

		await self._db.flush()
		tokens = self._make_tokens(user.id)
		log.info("auth.oauth_callback", provider=provider, user_id=user.id)
		return user, tokens
