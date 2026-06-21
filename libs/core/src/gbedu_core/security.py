from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt as _bcrypt
import structlog
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError

from gbedu_core.errors import TokenExpiredError, TokenInvalidError

log = structlog.get_logger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")

# Token type claim values
_ACCESS_TOKEN_TYPE = "access"
_REFRESH_TOKEN_TYPE = "refresh"
_API_KEY_PREFIX_LENGTH = 8


# ── Password ───────────────────────────────────────────────────────────────────


def _bcrypt_input(plain: str) -> bytes:
	raw = plain.encode("utf-8")
	if len(raw) <= 72:
		return raw
	return b"gbedu-sha256:" + hashlib.sha256(raw).digest()


def hash_password(plain: str) -> str:
	assert plain, "password must not be empty"
	return _bcrypt.hashpw(_bcrypt_input(plain), _bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
	assert plain and hashed, "both plain and hashed must be non-empty"
	return _bcrypt.checkpw(_bcrypt_input(plain), hashed.encode("utf-8"))


# ── JWT ────────────────────────────────────────────────────────────────────────


def create_access_token(
	subject: str,
	secret_key: str,
	algorithm: str,
	expires_minutes: int,
	extra_claims: dict[str, Any] | None = None,
) -> str:
	assert subject, "subject must not be empty"
	assert secret_key, "secret_key must not be empty"
	assert expires_minutes > 0, "expires_minutes must be positive"

	now = datetime.now(UTC)
	payload: dict[str, Any] = {
		"sub": subject,
		"type": _ACCESS_TOKEN_TYPE,
		"iat": now,
		"exp": now + timedelta(minutes=expires_minutes),
		"jti": secrets.token_hex(16),
	}
	if extra_claims:
		payload.update(extra_claims)

	return jwt.encode(payload, secret_key, algorithm=algorithm)


def create_refresh_token(
	subject: str,
	secret_key: str,
	algorithm: str,
	expires_days: int,
	extra_claims: dict[str, Any] | None = None,
) -> str:
	assert subject, "subject must not be empty"
	assert secret_key, "secret_key must not be empty"
	assert expires_days > 0, "expires_days must be positive"

	now = datetime.now(UTC)
	payload: dict[str, Any] = {
		"sub": subject,
		"type": _REFRESH_TOKEN_TYPE,
		"iat": now,
		"exp": now + timedelta(days=expires_days),
		"jti": secrets.token_hex(16),
	}
	if extra_claims:
		payload.update(extra_claims)

	return jwt.encode(payload, secret_key, algorithm=algorithm)


def decode_token(token: str, secret_key: str, algorithm: str) -> dict[str, Any]:
	"""Decode and return the raw JWT payload without type-checking."""
	assert token, "token must not be empty"
	assert secret_key, "secret_key must not be empty"

	try:
		payload = jwt.decode(token, secret_key, algorithms=[algorithm])
	except ExpiredSignatureError:
		raise TokenExpiredError()
	except JWTError as e:
		raise TokenInvalidError() from e

	return payload


def verify_token(
	token: str,
	secret_key: str,
	algorithm: str,
	expected_type: str = _ACCESS_TOKEN_TYPE,
) -> dict[str, Any]:
	"""Decode JWT and assert the expected token type claim."""
	payload = decode_token(token, secret_key, algorithm)

	actual_type = payload.get("type")
	if actual_type != expected_type:
		raise TokenInvalidError()

	subject = payload.get("sub")
	if not subject:
		raise TokenInvalidError()

	return payload


def verify_access_token(token: str, secret_key: str, algorithm: str) -> dict[str, Any]:
	return verify_token(token, secret_key, algorithm, _ACCESS_TOKEN_TYPE)


def verify_refresh_token(token: str, secret_key: str, algorithm: str) -> dict[str, Any]:
	return verify_token(token, secret_key, algorithm, _REFRESH_TOKEN_TYPE)


# ── API Keys ───────────────────────────────────────────────────────────────────


def generate_api_key() -> tuple[str, str]:
	"""Return (raw_key, hashed_key).

	Store only hashed_key in the database; return raw_key to the user once.
	Format: gbedu_<32 random hex chars>
	The prefix aids grep/audit tooling without revealing entropy.
	"""
	raw = f"gbedu_{secrets.token_hex(32)}"
	hashed = _hash_api_key(raw)
	return raw, hashed


def _hash_api_key(raw: str) -> str:
	"""SHA-256 of the raw key — constant-time comparison safe."""
	return hashlib.sha256(raw.encode()).hexdigest()


def verify_api_key(raw: str, stored_hash: str) -> bool:
	assert raw and stored_hash, "api key and hash must be non-empty"
	candidate_hash = _hash_api_key(raw)
	# hmac.compare_digest prevents timing attacks
	return hmac.compare_digest(candidate_hash, stored_hash)


def get_api_key_prefix(raw: str) -> str:
	"""Return the display prefix (first N chars after 'gbedu_') for UI listing."""
	return raw[: _API_KEY_PREFIX_LENGTH + len("gbedu_")]
