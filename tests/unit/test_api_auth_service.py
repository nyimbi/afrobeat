"""Unit tests for AuthService — mocked DB + fakeredis, no real Postgres needed."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

# Module under test
from gbedu_api.services.auth_service import (
	_EMAIL_VERIFY_PREFIX,
	_REFRESH_BLOCKLIST_PREFIX,
	_REFRESH_FAMILY_REVOKED_PREFIX,
	_RESET_TOKEN_PREFIX,
	AuthService,
	TokenPair,
)
from gbedu_core._uuid7 import uuid7str
from gbedu_core.errors import (
	AuthenticationError,
	ConflictError,
	DatabaseIntegrityError,
	InvalidCredentialsError,
	NotFoundError,
	TokenInvalidError,
)
from gbedu_core.models.user import SubscriptionStatus, SubscriptionTier, User
from gbedu_core.security import create_refresh_token, hash_password
from jose import jwt as jose_jwt
from sqlalchemy.exc import IntegrityError

_SECRET = "test-secret-key-not-for-production"
_ALG = "HS256"


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_user(
	*,
	email: str = "test@example.com",
	is_active: bool = True,
	is_verified: bool = True,
	hashed_pw: str | None = None,
) -> User:
	user = MagicMock(spec=User)
	user.id = uuid7str()
	user.email = email.lower()
	user.full_name = "Test User"
	user.hashed_password = hashed_pw or hash_password("Password123!")
	user.is_active = is_active
	user.is_verified = is_verified
	user.subscription_tier = SubscriptionTier.free
	user.subscription_status = SubscriptionStatus.active
	user.oauth_provider = None
	user.oauth_provider_id = None
	user.avatar_url = None
	user.deleted_at = None
	return user


def _make_db(scalar_result: object = None) -> AsyncMock:
	"""Return a mocked AsyncSession whose execute() returns scalar_result."""
	mock_result = MagicMock()
	mock_result.scalar_one_or_none.return_value = scalar_result
	db = AsyncMock()
	db.execute = AsyncMock(return_value=mock_result)
	db.flush = AsyncMock()
	db.add = MagicMock()
	return db


async def _make_redis() -> fakeredis.aioredis.FakeRedis:
	return fakeredis.aioredis.FakeRedis()


def _make_valid_refresh_token(user_id: str) -> str:
	return create_refresh_token(
		subject=user_id,
		secret_key=_SECRET,
		algorithm=_ALG,
		expires_days=7,
	)


def _make_expired_refresh_token(user_id: str) -> str:
	payload = {
		"sub": user_id,
		"type": "refresh",
		"iat": int(time.time()) - 7200,
		"exp": int(time.time()) - 3600,
		"jti": "expired-jti",
	}
	return jose_jwt.encode(payload, _SECRET, algorithm=_ALG)


# ── TokenPair ──────────────────────────────────────────────────────────────────


def test_token_pair_attributes() -> None:
	pair = TokenPair("acc", "ref")
	assert pair.access_token == "acc"
	assert pair.refresh_token == "ref"
	assert pair.token_type == "bearer"


# ── register ───────────────────────────────────────────────────────────────────


async def test_register_success() -> None:
	db = _make_db(scalar_result=None)  # no existing user
	redis = await _make_redis()

	svc = AuthService(db, redis)
	user, tokens = await svc.register("New@Example.com", "Password123!", "New User")

	assert user.email == "new@example.com"
	assert user.is_active is True
	assert user.is_verified is False
	assert isinstance(tokens, TokenPair)
	assert tokens.access_token
	assert tokens.refresh_token
	db.add.assert_called_once()
	db.flush.assert_called_once()


async def test_register_duplicate_email_raises_conflict() -> None:
	existing = _make_user(email="dup@example.com")
	db = _make_db(scalar_result=existing)

	svc = AuthService(db, await _make_redis())
	with pytest.raises(ConflictError, match="already registered"):
		await svc.register("dup@example.com", "Password123!", "Dup User")


async def test_register_integrity_error_raises_database_integrity_error() -> None:
	db = _make_db(scalar_result=None)
	db.flush.side_effect = IntegrityError("stmt", {}, Exception("unique"))

	svc = AuthService(db, await _make_redis())
	with pytest.raises(DatabaseIntegrityError):
		await svc.register("race@example.com", "Password123!", "Race User")


async def test_register_empty_email_raises() -> None:
	svc = AuthService(AsyncMock(), await _make_redis())
	with pytest.raises(AssertionError):
		await svc.register("", "Password123!", "User")


async def test_register_empty_password_raises() -> None:
	svc = AuthService(AsyncMock(), await _make_redis())
	with pytest.raises(AssertionError):
		await svc.register("a@b.com", "", "User")


async def test_register_empty_full_name_raises() -> None:
	svc = AuthService(AsyncMock(), await _make_redis())
	with pytest.raises(AssertionError):
		await svc.register("a@b.com", "Password123!", "")


# ── login ──────────────────────────────────────────────────────────────────────


async def test_login_success() -> None:
	user = _make_user(hashed_pw=hash_password("GoodPass!"))
	db = _make_db(scalar_result=user)

	svc = AuthService(db, await _make_redis())
	returned_user, tokens = await svc.login("test@example.com", "GoodPass!")

	assert returned_user is user
	assert isinstance(tokens, TokenPair)


async def test_login_wrong_password_raises() -> None:
	user = _make_user(hashed_pw=hash_password("CorrectPass!"))
	db = _make_db(scalar_result=user)

	svc = AuthService(db, await _make_redis())
	with pytest.raises(InvalidCredentialsError):
		await svc.login("test@example.com", "WrongPass!")


async def test_login_user_not_found_raises() -> None:
	db = _make_db(scalar_result=None)

	svc = AuthService(db, await _make_redis())
	with pytest.raises(InvalidCredentialsError):
		await svc.login("ghost@example.com", "AnyPass!")


async def test_login_inactive_user_raises() -> None:
	user = _make_user(is_active=False, hashed_pw=hash_password("GoodPass!"))
	db = _make_db(scalar_result=user)

	svc = AuthService(db, await _make_redis())
	with pytest.raises(AuthenticationError, match="deactivated"):
		await svc.login("test@example.com", "GoodPass!")


async def test_login_empty_credentials_raises() -> None:
	svc = AuthService(AsyncMock(), await _make_redis())
	with pytest.raises(AssertionError):
		await svc.login("", "pass")


# ── refresh ────────────────────────────────────────────────────────────────────


async def test_refresh_success_rotates_token() -> None:
	user = _make_user()
	db = _make_db(scalar_result=user)
	redis = await _make_redis()

	refresh_token = _make_valid_refresh_token(user.id)

	svc = AuthService(db, redis)
	new_tokens = await svc.refresh(refresh_token)

	assert isinstance(new_tokens, TokenPair)
	assert new_tokens.refresh_token != refresh_token  # rotated

	# old token is now blocklisted
	blocklist_key = f"{_REFRESH_BLOCKLIST_PREFIX}{refresh_token[:64]}"
	assert await redis.exists(blocklist_key)


async def test_refresh_blocklisted_token_raises_and_revokes_family() -> None:
	user = _make_user()
	db = _make_db(scalar_result=user)
	redis = await _make_redis()

	refresh_token = _make_valid_refresh_token(user.id)
	blocklist_key = f"{_REFRESH_BLOCKLIST_PREFIX}{refresh_token[:64]}"
	await redis.setex(blocklist_key, 3600, "1")

	svc = AuthService(db, redis)
	with pytest.raises(TokenInvalidError):
		await svc.refresh(refresh_token)

	# family revocation key must have been set
	family_key = f"{_REFRESH_FAMILY_REVOKED_PREFIX}{user.id}"
	assert await redis.exists(family_key)


async def test_refresh_family_revoked_raises() -> None:
	user = _make_user()
	db = _make_db(scalar_result=user)
	redis = await _make_redis()

	refresh_token = _make_valid_refresh_token(user.id)
	family_key = f"{_REFRESH_FAMILY_REVOKED_PREFIX}{user.id}"
	await redis.setex(family_key, 3600, "1")

	svc = AuthService(db, redis)
	with pytest.raises(TokenInvalidError):
		await svc.refresh(refresh_token)


async def test_refresh_user_not_found_raises() -> None:
	db = _make_db(scalar_result=None)
	redis = await _make_redis()
	user_id = uuid7str()
	refresh_token = _make_valid_refresh_token(user_id)

	svc = AuthService(db, redis)
	with pytest.raises(TokenInvalidError):
		await svc.refresh(refresh_token)


async def test_refresh_inactive_user_raises() -> None:
	user = _make_user(is_active=False)
	db = _make_db(scalar_result=user)
	redis = await _make_redis()
	refresh_token = _make_valid_refresh_token(user.id)

	svc = AuthService(db, redis)
	with pytest.raises(TokenInvalidError):
		await svc.refresh(refresh_token)


async def test_refresh_invalid_token_raises() -> None:
	db = _make_db(scalar_result=None)
	redis = await _make_redis()

	svc = AuthService(db, redis)
	with pytest.raises(TokenInvalidError):
		await svc.refresh("not.a.valid.jwt")


async def test_refresh_empty_token_raises() -> None:
	svc = AuthService(AsyncMock(), await _make_redis())
	with pytest.raises(AssertionError):
		await svc.refresh("")


# ── logout ─────────────────────────────────────────────────────────────────────


async def test_logout_blocklists_token() -> None:
	user = _make_user()
	redis = await _make_redis()
	refresh_token = _make_valid_refresh_token(user.id)

	svc = AuthService(AsyncMock(), redis)
	await svc.logout(refresh_token)

	blocklist_key = f"{_REFRESH_BLOCKLIST_PREFIX}{refresh_token[:64]}"
	assert await redis.exists(blocklist_key)


async def test_logout_expired_token_still_blocklisted() -> None:
	user = _make_user()
	redis = await _make_redis()
	expired_token = _make_expired_refresh_token(user.id)

	svc = AuthService(AsyncMock(), redis)
	await svc.logout(expired_token)  # must not raise

	blocklist_key = f"{_REFRESH_BLOCKLIST_PREFIX}{expired_token[:64]}"
	assert await redis.exists(blocklist_key)


async def test_logout_garbage_token_still_blocklisted() -> None:
	redis = await _make_redis()
	garbage = "garbage.token.value"

	svc = AuthService(AsyncMock(), redis)
	await svc.logout(garbage)  # must not raise

	blocklist_key = f"{_REFRESH_BLOCKLIST_PREFIX}{garbage[:64]}"
	assert await redis.exists(blocklist_key)


async def test_logout_empty_token_raises() -> None:
	svc = AuthService(AsyncMock(), await _make_redis())
	with pytest.raises(AssertionError):
		await svc.logout("")


# ── create_email_verification_token ───────────────────────────────────────────


async def test_create_email_verification_token_stores_in_redis() -> None:
	redis = await _make_redis()
	user_id = uuid7str()

	svc = AuthService(AsyncMock(), redis)
	token = await svc.create_email_verification_token(user_id)

	assert token
	stored = await redis.get(f"{_EMAIL_VERIFY_PREFIX}{token}")
	assert stored is not None
	stored_id = stored.decode() if isinstance(stored, bytes) else stored
	assert stored_id == user_id


async def test_create_email_verification_token_empty_user_id_raises() -> None:
	svc = AuthService(AsyncMock(), await _make_redis())
	with pytest.raises(AssertionError):
		await svc.create_email_verification_token("")


# ── verify_email ───────────────────────────────────────────────────────────────


async def test_verify_email_success() -> None:
	user = _make_user(is_verified=False)
	db = _make_db(scalar_result=user)
	redis = await _make_redis()

	token = "valid-email-token"
	await redis.setex(f"{_EMAIL_VERIFY_PREFIX}{token}", 3600, user.id)

	svc = AuthService(db, redis)
	returned_user = await svc.verify_email(token)

	assert returned_user.is_verified is True
	# token consumed
	assert not await redis.exists(f"{_EMAIL_VERIFY_PREFIX}{token}")


async def test_verify_email_invalid_token_raises() -> None:
	db = _make_db(scalar_result=None)
	redis = await _make_redis()

	svc = AuthService(db, redis)
	with pytest.raises(TokenInvalidError):
		await svc.verify_email("nonexistent-token")


async def test_verify_email_user_not_found_raises() -> None:
	redis = await _make_redis()
	token = "orphan-token"
	await redis.setex(f"{_EMAIL_VERIFY_PREFIX}{token}", 3600, "missing-user-id")
	db = _make_db(scalar_result=None)

	svc = AuthService(db, redis)
	with pytest.raises(NotFoundError):
		await svc.verify_email(token)


async def test_verify_email_bytes_user_id_decoded() -> None:
	"""Redis may return bytes; verify_email must decode them correctly."""
	user = _make_user()
	user.is_verified = False
	db = _make_db(scalar_result=user)
	redis = await _make_redis()

	token = "bytes-token"
	# Store as bytes explicitly
	await redis.setex(f"{_EMAIL_VERIFY_PREFIX}{token}", 3600, user.id.encode())

	svc = AuthService(db, redis)
	result = await svc.verify_email(token)
	assert result.is_verified is True


# ── create_password_reset_token ────────────────────────────────────────────────


async def test_create_password_reset_token_known_email() -> None:
	user = _make_user()
	db = _make_db(scalar_result=user)
	redis = await _make_redis()

	svc = AuthService(db, redis)
	token = await svc.create_password_reset_token("test@example.com")

	assert token is not None
	stored = await redis.get(f"{_RESET_TOKEN_PREFIX}{token}")
	assert stored is not None


async def test_create_password_reset_token_unknown_email_returns_none() -> None:
	db = _make_db(scalar_result=None)
	redis = await _make_redis()

	svc = AuthService(db, redis)
	token = await svc.create_password_reset_token("nobody@example.com")

	assert token is None


# ── reset_password ─────────────────────────────────────────────────────────────


async def test_reset_password_success() -> None:
	user = _make_user()
	db = _make_db(scalar_result=user)
	redis = await _make_redis()

	token = "reset-token-abc"
	await redis.setex(f"{_RESET_TOKEN_PREFIX}{token}", 3600, user.id)

	svc = AuthService(db, redis)
	returned_user = await svc.reset_password(token, "NewPassword456!")

	# password updated
	from gbedu_core.security import verify_password as vp

	assert vp("NewPassword456!", returned_user.hashed_password)
	# token consumed
	assert not await redis.exists(f"{_RESET_TOKEN_PREFIX}{token}")


async def test_reset_password_invalid_token_raises() -> None:
	redis = await _make_redis()
	svc = AuthService(AsyncMock(), redis)
	with pytest.raises(TokenInvalidError):
		await svc.reset_password("bad-token", "NewPassword456!")


async def test_reset_password_user_not_found_raises() -> None:
	redis = await _make_redis()
	token = "orphan-reset"
	await redis.setex(f"{_RESET_TOKEN_PREFIX}{token}", 3600, "missing-id")
	db = _make_db(scalar_result=None)

	svc = AuthService(db, redis)
	with pytest.raises(NotFoundError):
		await svc.reset_password(token, "NewPassword456!")


async def test_reset_password_empty_args_raises() -> None:
	svc = AuthService(AsyncMock(), await _make_redis())
	with pytest.raises(AssertionError):
		await svc.reset_password("", "NewPassword456!")
	with pytest.raises(AssertionError):
		await svc.reset_password("token", "")


# ── oauth_callback ─────────────────────────────────────────────────────────────


async def test_oauth_callback_creates_new_user_when_no_match() -> None:
	# Both oauth lookup and email lookup return None → create new user
	mock_result = MagicMock()
	mock_result.scalar_one_or_none.side_effect = [None, None]
	db = AsyncMock()
	db.execute = AsyncMock(return_value=mock_result)
	db.flush = AsyncMock()
	db.add = MagicMock()
	redis = await _make_redis()

	svc = AuthService(db, redis)
	user, tokens = await svc.oauth_callback(
		provider="google",
		provider_id="google-sub-123",
		email="oauth@example.com",
		full_name="OAuth User",
		avatar_url="https://example.com/avatar.jpg",
	)

	assert user.email == "oauth@example.com"
	assert user.oauth_provider == "google"
	assert user.is_verified is True
	assert isinstance(tokens, TokenPair)


async def test_oauth_callback_finds_existing_oauth_user() -> None:
	existing = _make_user(email="oauth@example.com")
	existing.oauth_provider = "google"
	existing.oauth_provider_id = "google-sub-123"

	mock_result = MagicMock()
	mock_result.scalar_one_or_none.return_value = existing
	db = AsyncMock()
	db.execute = AsyncMock(return_value=mock_result)
	db.flush = AsyncMock()
	db.add = MagicMock()
	redis = await _make_redis()

	svc = AuthService(db, redis)
	user, tokens = await svc.oauth_callback(
		provider="google",
		provider_id="google-sub-123",
		email="oauth@example.com",
		full_name="OAuth User",
	)

	assert user is existing
	assert isinstance(tokens, TokenPair)


async def test_oauth_callback_falls_back_to_email_match() -> None:
	existing = _make_user(email="preexist@example.com")

	# First execute (oauth lookup) → None; second (email lookup) → existing user
	first_result = MagicMock()
	first_result.scalar_one_or_none.return_value = None
	second_result = MagicMock()
	second_result.scalar_one_or_none.return_value = existing

	db = AsyncMock()
	db.execute = AsyncMock(side_effect=[first_result, second_result])
	db.flush = AsyncMock()
	db.add = MagicMock()
	redis = await _make_redis()

	svc = AuthService(db, redis)
	user, tokens = await svc.oauth_callback(
		provider="google",
		provider_id="new-sub",
		email="preexist@example.com",
		full_name="Pre Exist",
	)

	assert user is existing
	# oauth fields updated
	assert existing.oauth_provider == "google"
	assert existing.oauth_provider_id == "new-sub"


async def test_oauth_callback_empty_args_raises() -> None:
	svc = AuthService(AsyncMock(), await _make_redis())
	with pytest.raises(AssertionError):
		await svc.oauth_callback(provider="", provider_id="x", email="a@b.com", full_name="X")
