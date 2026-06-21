"""Unit tests for gbedu_api.deps — no real DB or Redis needed."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from gbedu_api.deps import (
	get_current_active_user,
	get_current_user,
	get_ml_client,
	get_redis,
	get_storage,
	require_tier,
	set_ml_client,
	set_redis,
	set_storage_client,
)
from gbedu_core._uuid7 import uuid7str
from gbedu_core.errors import TokenExpiredError, TokenInvalidError
from gbedu_core.models.user import SubscriptionTier, User

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_user(*, is_active: bool = True, tier: SubscriptionTier = SubscriptionTier.free) -> User:
	user = MagicMock(spec=User)
	user.id = uuid7str()
	user.email = "test@example.com"
	user.is_active = is_active
	user.subscription_tier = tier
	user.deleted_at = None
	return user


def _make_db(user: User | None = None) -> AsyncMock:
	db = AsyncMock()
	result = MagicMock()
	result.scalar_one_or_none.return_value = user
	db.execute = AsyncMock(return_value=result)
	return db


# ── Setters / getters ─────────────────────────────────────────────────────────


async def test_set_and_get_redis() -> None:
	mock_redis = MagicMock()
	set_redis(mock_redis)
	asyncio.get_event_loop()
	result = await get_redis()
	assert result is mock_redis


async def test_set_and_get_storage() -> None:
	mock_storage = MagicMock()
	set_storage_client(mock_storage)
	asyncio.get_event_loop()
	result = await get_storage()
	assert result is mock_storage


async def test_set_and_get_ml_client() -> None:
	mock_ml = MagicMock()
	set_ml_client(mock_ml)
	asyncio.get_event_loop()
	result = await get_ml_client()
	assert result is mock_ml


# ── get_current_user ───────────────────────────────────────────────────────────


async def test_get_current_user_no_token_raises_401() -> None:
	db = _make_db()
	with pytest.raises(HTTPException) as exc_info:
		await get_current_user(None, db)
	assert exc_info.value.status_code == 401
	assert exc_info.value.detail["error_code"] == "AUTHENTICATION_ERROR"


async def test_get_current_user_expired_token_raises_401() -> None:
	db = _make_db()
	with patch("gbedu_api.deps.verify_access_token", side_effect=TokenExpiredError("expired")):
		with pytest.raises(HTTPException) as exc_info:
			await get_current_user("stale.token.here", db)
	assert exc_info.value.status_code == 401
	assert exc_info.value.detail["error_code"] == "TOKEN_EXPIRED"


async def test_get_current_user_invalid_token_raises_401() -> None:
	db = _make_db()
	with patch("gbedu_api.deps.verify_access_token", side_effect=TokenInvalidError("bad")):
		with pytest.raises(HTTPException) as exc_info:
			await get_current_user("bad.token.here", db)
	assert exc_info.value.status_code == 401
	assert exc_info.value.detail["error_code"] == "TOKEN_INVALID"


async def test_get_current_user_missing_sub_raises_401() -> None:
	db = _make_db()
	with patch("gbedu_api.deps.verify_access_token", return_value={}):
		with pytest.raises(HTTPException) as exc_info:
			await get_current_user("token.no.sub", db)
	assert exc_info.value.status_code == 401
	assert exc_info.value.detail["error_code"] == "TOKEN_INVALID"


async def test_get_current_user_not_found_raises_401() -> None:
	db = _make_db(user=None)
	with patch("gbedu_api.deps.verify_access_token", return_value={"sub": uuid7str()}):
		with pytest.raises(HTTPException) as exc_info:
			await get_current_user("valid.token", db)
	assert exc_info.value.status_code == 401
	assert exc_info.value.detail["error_code"] == "AUTHENTICATION_ERROR"


async def test_get_current_user_success() -> None:
	user = _make_user()
	db = _make_db(user=user)
	with patch("gbedu_api.deps.verify_access_token", return_value={"sub": user.id}):
		result = await get_current_user("valid.token", db)
	assert result is user


# ── get_current_active_user ────────────────────────────────────────────────────


async def test_get_current_active_user_inactive_raises_403() -> None:
	inactive = _make_user(is_active=False)
	with pytest.raises(HTTPException) as exc_info:
		await get_current_active_user(inactive)
	assert exc_info.value.status_code == 403
	assert exc_info.value.detail["error_code"] == "AUTHORIZATION_ERROR"


async def test_get_current_active_user_active_returns_user() -> None:
	user = _make_user(is_active=True)
	result = await get_current_active_user(user)
	assert result is user


# ── require_tier ───────────────────────────────────────────────────────────────


async def test_require_tier_insufficient_raises_403() -> None:
	free_user = _make_user(tier=SubscriptionTier.free)
	check = require_tier(SubscriptionTier.creator)
	with pytest.raises(HTTPException) as exc_info:
		await check(free_user)
	assert exc_info.value.status_code == 403
	assert exc_info.value.detail["error_code"] == "AUTHORIZATION_ERROR"


async def test_require_tier_sufficient_returns_user() -> None:
	pro_user = _make_user(tier=SubscriptionTier.pro)
	check = require_tier(SubscriptionTier.creator)
	result = await check(pro_user)
	assert result is pro_user


async def test_require_tier_exact_match_returns_user() -> None:
	creator_user = _make_user(tier=SubscriptionTier.creator)
	check = require_tier(SubscriptionTier.creator)
	result = await check(creator_user)
	assert result is creator_user
