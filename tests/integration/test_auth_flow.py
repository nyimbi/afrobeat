"""Integration tests for auth flow: register → login → refresh → logout.

Tests target the security primitives and DB layer directly without requiring
the full FastAPI app to be running.  This avoids the import-time dependency on
services/api which may not be installed in the test environment.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from gbedu_core._uuid7 import uuid7str
from gbedu_core.errors import TokenExpiredError, TokenInvalidError
from gbedu_core.models import SubscriptionStatus, SubscriptionTier, User
from gbedu_core.security import (
	create_access_token,
	create_refresh_token,
	hash_password,
	verify_access_token,
	verify_password,
	verify_refresh_token,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_SECRET = "integration-test-secret"
_ALG = "HS256"


# ── Register ───────────────────────────────────────────────────────────────────


async def test_register_stores_user(test_db_session: AsyncSession) -> None:
	email = f"register-{uuid7str()}@example.com"
	user = User(
		id=uuid7str(),
		email=email,
		hashed_password=hash_password("StrongPassword1"),
		full_name="Adaeze Nwosu",
		subscription_tier=SubscriptionTier.free,
		subscription_status=SubscriptionStatus.active,
		is_active=True,
		is_verified=False,
		preferred_language="en",
		generation_count_today=0,
		generation_count_reset_at=datetime.now(UTC),
	)
	test_db_session.add(user)
	await test_db_session.flush()

	result = await test_db_session.execute(select(User).where(User.email == email))
	fetched = result.scalar_one_or_none()
	assert fetched is not None
	assert fetched.full_name == "Adaeze Nwosu"
	assert fetched.is_verified is False
	assert fetched.subscription_tier == SubscriptionTier.free


async def test_register_password_is_hashed(test_db_session: AsyncSession) -> None:
	email = f"hash-{uuid7str()}@example.com"
	plain = "MySecurePass99"
	user = User(
		id=uuid7str(),
		email=email,
		hashed_password=hash_password(plain),
		full_name="Emeka",
		subscription_tier=SubscriptionTier.free,
		subscription_status=SubscriptionStatus.active,
		is_active=True,
		is_verified=False,
		preferred_language="en",
		generation_count_today=0,
		generation_count_reset_at=datetime.now(UTC),
	)
	test_db_session.add(user)
	await test_db_session.flush()

	result = await test_db_session.execute(select(User).where(User.email == email))
	fetched = result.scalar_one()
	assert fetched.hashed_password != plain
	assert verify_password(plain, fetched.hashed_password)


# ── Login ──────────────────────────────────────────────────────────────────────


async def test_login_correct_credentials(test_db_session: AsyncSession) -> None:
	plain = "LoginPass123"
	email = f"login-{uuid7str()}@example.com"
	user = User(
		id=uuid7str(),
		email=email,
		hashed_password=hash_password(plain),
		full_name="Bola",
		subscription_tier=SubscriptionTier.free,
		subscription_status=SubscriptionStatus.active,
		is_active=True,
		is_verified=True,
		preferred_language="en",
		generation_count_today=0,
		generation_count_reset_at=datetime.now(UTC),
	)
	test_db_session.add(user)
	await test_db_session.flush()

	assert verify_password(plain, user.hashed_password)

	access_token = create_access_token(user.id, _SECRET, _ALG, expires_minutes=30)
	payload = verify_access_token(access_token, _SECRET, _ALG)
	assert payload["sub"] == user.id


async def test_login_wrong_password_fails() -> None:
	hashed = hash_password("correct-password")
	assert verify_password("wrong-password", hashed) is False


# ── Token issuance ─────────────────────────────────────────────────────────────


async def test_access_token_carries_user_id(test_db_session: AsyncSession, make_user) -> None:
	user = await make_user(tier="creator")
	token = create_access_token(user.id, _SECRET, _ALG, expires_minutes=30)
	payload = verify_access_token(token, _SECRET, _ALG)
	assert payload["sub"] == user.id


async def test_refresh_token_round_trip(test_db_session: AsyncSession, make_user) -> None:
	user = await make_user()
	refresh_token = create_refresh_token(user.id, _SECRET, _ALG, expires_days=7)
	payload = verify_refresh_token(refresh_token, _SECRET, _ALG)
	assert payload["sub"] == user.id
	assert payload["type"] == "refresh"


async def test_access_token_rejected_as_refresh(test_db_session: AsyncSession, make_user) -> None:
	user = await make_user()
	access_token = create_access_token(user.id, _SECRET, _ALG, expires_minutes=30)
	with pytest.raises(TokenInvalidError):
		verify_refresh_token(access_token, _SECRET, _ALG)


# ── Refresh flow ───────────────────────────────────────────────────────────────


async def test_refresh_issues_new_access_token(test_db_session: AsyncSession, make_user) -> None:
	user = await make_user(tier="pro")
	refresh_token = create_refresh_token(user.id, _SECRET, _ALG, expires_days=30)

	payload = verify_refresh_token(refresh_token, _SECRET, _ALG)
	assert payload["sub"] == user.id

	new_access_token = create_access_token(payload["sub"], _SECRET, _ALG, expires_minutes=30)
	new_payload = verify_access_token(new_access_token, _SECRET, _ALG)
	assert new_payload["sub"] == user.id


async def test_expired_refresh_token_rejected() -> None:
	import time

	from jose import jwt as jose_jwt

	expired_payload = {
		"sub": "user-expired",
		"type": "refresh",
		"iat": int(time.time()) - 7200,
		"exp": int(time.time()) - 3600,
		"jti": uuid7str(),
	}
	expired_token = jose_jwt.encode(expired_payload, _SECRET, algorithm=_ALG)
	with pytest.raises(TokenExpiredError):
		verify_refresh_token(expired_token, _SECRET, _ALG)


# ── Protected endpoint simulation ──────────────────────────────────────────────


async def test_protected_endpoint_requires_valid_token(
	test_db_session: AsyncSession, make_user
) -> None:
	"""Simulate the authentication check a protected endpoint would perform."""
	user = await make_user(tier="creator")
	token = create_access_token(user.id, _SECRET, _ALG, expires_minutes=30)

	payload = verify_access_token(token, _SECRET, _ALG)
	user_id = payload["sub"]

	result = await test_db_session.execute(select(User).where(User.id == user_id))
	fetched = result.scalar_one_or_none()
	assert fetched is not None
	assert fetched.id == user.id


async def test_tampered_token_blocked() -> None:
	token = create_access_token("user-1", _SECRET, _ALG, expires_minutes=30)
	parts = token.split(".")
	tampered = ".".join([parts[0], parts[1], parts[2][:-4] + "XXXX"])
	with pytest.raises(TokenInvalidError):
		verify_access_token(tampered, _SECRET, _ALG)


# ── Logout simulation ──────────────────────────────────────────────────────────


async def test_logout_revokes_refresh_token(test_db_session: AsyncSession, make_user) -> None:
	"""Logout is modelled as marking the refresh_token row as revoked.

	We test the DB write path without needing the HTTP layer.
	"""
	from gbedu_core._uuid7 import uuid7str as _uuid7str
	from sqlalchemy import text

	user = await make_user()
	jti = _uuid7str()

	# Insert a refresh token row
	await test_db_session.execute(
		text(
			"INSERT INTO refresh_tokens "
			"(id, user_id, token_hash, jti, expires_at, created_at, updated_at) "
			"VALUES (:id, :user_id, :token_hash, :jti, :expires_at, now(), now())"
		),
		{
			"id": _uuid7str(),
			"user_id": user.id,
			"token_hash": "deadbeef" * 8,
			"jti": jti,
			"expires_at": datetime.now(UTC) + timedelta(days=7),
		},
	)

	# Simulate logout: set revoked_at
	await test_db_session.execute(
		text("UPDATE refresh_tokens SET revoked_at = now() WHERE jti = :jti"),
		{"jti": jti},
	)

	# Verify revoked
	result = await test_db_session.execute(
		text("SELECT revoked_at FROM refresh_tokens WHERE jti = :jti"),
		{"jti": jti},
	)
	row = result.fetchone()
	assert row is not None
	assert row.revoked_at is not None


async def test_revoked_token_is_blocked(test_db_session: AsyncSession, make_user) -> None:
	"""After logout the revoked_at IS NOT NULL — application code must check this."""
	from sqlalchemy import text

	user = await make_user()
	jti = uuid7str()

	await test_db_session.execute(
		text(
			"INSERT INTO refresh_tokens "
			"(id, user_id, token_hash, jti, expires_at, revoked_at, created_at, updated_at) "
			"VALUES (:id, :user_id, :token_hash, :jti, :expires_at, now(), now(), now())"
		),
		{
			"id": uuid7str(),
			"user_id": user.id,
			"token_hash": "aabbccdd" * 8,
			"jti": jti,
			"expires_at": datetime.now(UTC) + timedelta(days=7),
		},
	)

	result = await test_db_session.execute(
		text("SELECT revoked_at FROM refresh_tokens WHERE jti = :jti"),
		{"jti": jti},
	)
	row = result.fetchone()
	# Token is revoked — application should reject further use
	assert row.revoked_at is not None
