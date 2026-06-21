"""Unit tests for JWT round-trips, password hashing, token expiry, tampering."""

from __future__ import annotations

import time

import pytest
from gbedu_core.errors import TokenExpiredError, TokenInvalidError
from gbedu_core.security import (
	create_access_token,
	create_refresh_token,
	generate_api_key,
	hash_password,
	verify_access_token,
	verify_api_key,
	verify_password,
	verify_refresh_token,
)

_SECRET = "unit-test-secret-key"
_ALG = "HS256"


# ── Password ───────────────────────────────────────────────────────────────────


def test_hash_password_produces_bcrypt() -> None:
	hashed = hash_password("MyPassword123")
	assert hashed.startswith("$2b$") or hashed.startswith("$2a$")


def test_verify_password_correct() -> None:
	plain = "MyPassword123"
	hashed = hash_password(plain)
	assert verify_password(plain, hashed) is True


def test_verify_password_wrong() -> None:
	hashed = hash_password("correct")
	assert verify_password("wrong", hashed) is False


def test_hash_empty_password_raises() -> None:
	with pytest.raises(AssertionError):
		hash_password("")


def test_verify_empty_args_raises() -> None:
	with pytest.raises(AssertionError):
		verify_password("", "some_hash")

	with pytest.raises(AssertionError):
		verify_password("pass", "")


def test_hashes_are_unique() -> None:
	p = "SamePassword"
	h1 = hash_password(p)
	h2 = hash_password(p)
	# bcrypt salts ensure two hashes of the same password differ
	assert h1 != h2
	assert verify_password(p, h1)
	assert verify_password(p, h2)


# ── Access token ───────────────────────────────────────────────────────────────


def test_access_token_round_trip() -> None:
	token = create_access_token("user-123", _SECRET, _ALG, expires_minutes=30)
	payload = verify_access_token(token, _SECRET, _ALG)
	assert payload["sub"] == "user-123"
	assert payload["type"] == "access"
	assert "jti" in payload
	assert "exp" in payload


def test_access_token_carries_extra_claims() -> None:
	token = create_access_token(
		"user-456",
		_SECRET,
		_ALG,
		expires_minutes=30,
		extra_claims={"tier": "pro", "is_verified": True},
	)
	payload = verify_access_token(token, _SECRET, _ALG)
	assert payload["tier"] == "pro"
	assert payload["is_verified"] is True


# ── Refresh token ──────────────────────────────────────────────────────────────


def test_refresh_token_round_trip() -> None:
	token = create_refresh_token("user-789", _SECRET, _ALG, expires_days=7)
	payload = verify_refresh_token(token, _SECRET, _ALG)
	assert payload["sub"] == "user-789"
	assert payload["type"] == "refresh"


def test_refresh_token_rejected_as_access() -> None:
	token = create_refresh_token("user-x", _SECRET, _ALG, expires_days=1)
	with pytest.raises(TokenInvalidError):
		verify_access_token(token, _SECRET, _ALG)


def test_access_token_rejected_as_refresh() -> None:
	token = create_access_token("user-x", _SECRET, _ALG, expires_minutes=30)
	with pytest.raises(TokenInvalidError):
		verify_refresh_token(token, _SECRET, _ALG)


# ── Tampered token ─────────────────────────────────────────────────────────────


def test_tampered_signature_rejected() -> None:
	token = create_access_token("user-1", _SECRET, _ALG, expires_minutes=30)
	parts = token.split(".")
	# Flip last char of signature
	tampered_sig = parts[2][:-1] + ("A" if parts[2][-1] != "A" else "B")
	tampered = ".".join([parts[0], parts[1], tampered_sig])
	with pytest.raises(TokenInvalidError):
		verify_access_token(tampered, _SECRET, _ALG)


def test_wrong_secret_rejected() -> None:
	token = create_access_token("user-1", _SECRET, _ALG, expires_minutes=30)
	with pytest.raises(TokenInvalidError):
		verify_access_token(token, "wrong-secret", _ALG)


# ── Token expiry ───────────────────────────────────────────────────────────────


def test_expired_token_raises_token_expired_error() -> None:
	# expires_minutes=0 is rejected by assertion; use a tiny positive and then
	# decode raw to confirm expiry behaviour using a past exp via internal
	# construction is tricky — instead use a 1-minute token and mock time.
	# Best approach without freezegun: create a token with expires_minutes=-1
	# by bypassing the assertion check — or use decode_token on a manually
	# crafted expired JWT.
	from jose import jwt as jose_jwt

	past_payload = {
		"sub": "user-exp",
		"type": "access",
		"iat": int(time.time()) - 7200,
		"exp": int(time.time()) - 3600,  # expired 1 hour ago
		"jti": "test-jti",
	}
	expired_token = jose_jwt.encode(past_payload, _SECRET, algorithm=_ALG)
	with pytest.raises(TokenExpiredError):
		verify_access_token(expired_token, _SECRET, _ALG)


# ── create_* assertion guards ──────────────────────────────────────────────────


def test_create_access_token_empty_subject_raises() -> None:
	with pytest.raises(AssertionError):
		create_access_token("", _SECRET, _ALG, expires_minutes=30)


def test_create_access_token_empty_secret_raises() -> None:
	with pytest.raises(AssertionError):
		create_access_token("user-1", "", _ALG, expires_minutes=30)


def test_create_access_token_nonpositive_expiry_raises() -> None:
	with pytest.raises(AssertionError):
		create_access_token("user-1", _SECRET, _ALG, expires_minutes=0)


def test_create_refresh_token_nonpositive_days_raises() -> None:
	with pytest.raises(AssertionError):
		create_refresh_token("user-1", _SECRET, _ALG, expires_days=0)


# ── API keys ───────────────────────────────────────────────────────────────────


def test_api_key_generation_format() -> None:
	raw, hashed = generate_api_key()
	assert raw.startswith("gbedu_")
	assert len(raw) == len("gbedu_") + 64  # 32 hex bytes = 64 chars


def test_api_key_verification_correct() -> None:
	raw, hashed = generate_api_key()
	assert verify_api_key(raw, hashed) is True


def test_api_key_verification_wrong() -> None:
	_, hashed = generate_api_key()
	raw2, _ = generate_api_key()
	assert verify_api_key(raw2, hashed) is False


def test_api_keys_unique() -> None:
	raw1, _ = generate_api_key()
	raw2, _ = generate_api_key()
	assert raw1 != raw2
