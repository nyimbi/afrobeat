"""Unit tests for /api/v1/auth/* route handlers.

Strategy:
- Import `app` from gbedu_api.main (already constructed).
- Override get_db / get_redis via app.dependency_overrides.
- Patch AuthService methods and worker_tasks enqueuers to avoid real I/O.
- Use starlette.testclient.TestClient (sync wrapper around ASGI app).
- No @pytest.mark.asyncio — asyncio_mode = "auto" is set project-wide.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
from starlette.testclient import TestClient

# Ensure env vars are present before the app module is imported
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost/gbedu_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("GBEDU_ML_API_KEY", "test-ml-internal-api-key")

from gbedu_api.services.auth_service import TokenPair
from gbedu_core._uuid7 import uuid7str
from gbedu_core.errors import (
	AuthenticationError,
	ConflictError,
	InvalidCredentialsError,
	TokenInvalidError,
)
from gbedu_core.models.user import SubscriptionStatus, SubscriptionTier, User
from gbedu_core.security import hash_password

# ── App + dependency override helpers ─────────────────────────────────────────


def _build_client() -> tuple[TestClient, MagicMock, fakeredis.aioredis.FakeRedis]:
	"""Return (TestClient, mock_db, fake_redis) with dependency overrides applied."""
	# Import here so env vars are set first
	from gbedu_api.deps import get_db, get_redis
	from gbedu_api.main import app

	mock_db = AsyncMock()
	fake_redis = fakeredis.aioredis.FakeRedis()

	async def _override_db():
		yield mock_db

	async def _override_redis():
		return fake_redis

	app.dependency_overrides[get_db] = _override_db
	app.dependency_overrides[get_redis] = _override_redis

	client = TestClient(app, raise_server_exceptions=False)
	return client, mock_db, fake_redis


def _make_user(
	*,
	email: str = "user@example.com",
	is_active: bool = True,
	is_verified: bool = True,
) -> User:
	user = MagicMock(spec=User)
	user.id = uuid7str()
	user.email = email
	user.full_name = "Test User"
	user.hashed_password = hash_password("Password123!")
	user.is_active = is_active
	user.is_verified = is_verified
	user.subscription_tier = SubscriptionTier.free
	user.subscription_status = SubscriptionStatus.active
	user.oauth_provider = None
	user.oauth_provider_id = None
	user.avatar_url = None
	user.deleted_at = None
	return user


def _token_pair() -> TokenPair:
	return TokenPair(access_token="fake-access-token", refresh_token="fake-refresh-token")


# ── POST /auth/register ────────────────────────────────────────────────────────


@patch("gbedu_api.routers.auth.enqueue_verify_email")
@patch("gbedu_api.routers.auth.enqueue_welcome_email")
def test_register_success(mock_welcome, mock_verify) -> None:
	client, mock_db, _ = _build_client()
	user = _make_user(is_verified=False)
	tokens = _token_pair()

	with patch("gbedu_api.routers.auth.AuthService") as MockSvc:
		instance = MockSvc.return_value
		instance.register = AsyncMock(return_value=(user, tokens))
		instance.create_email_verification_token = AsyncMock(return_value="email-verify-tok")

		resp = client.post(
			"/api/v1/auth/register",
			json={
				"email": "new@example.com",
				"password": "Password123!",
				"full_name": "New User",
			},
		)

	assert resp.status_code == 201
	body = resp.json()
	assert "tokens" in body
	assert body["tokens"]["access_token"] == "fake-access-token"
	mock_verify.assert_called_once()
	mock_welcome.assert_called_once()


@patch("gbedu_api.routers.auth.enqueue_verify_email")
@patch("gbedu_api.routers.auth.enqueue_welcome_email")
def test_register_honeypot_returns_201_without_creating_user(mock_welcome, mock_verify) -> None:
	client, _, _ = _build_client()

	with patch("gbedu_api.routers.auth.AuthService") as MockSvc:
		instance = MockSvc.return_value
		instance.register = AsyncMock()

		resp = client.post(
			"/api/v1/auth/register",
			json={
				"email": "bot@example.com",
				"password": "Password123!",
				"full_name": "Bot",
				"website": "http://spam.example.com",
			},
		)

	assert resp.status_code == 201
	# register was never called — honeypot short-circuits
	instance.register.assert_not_called()
	mock_verify.assert_not_called()
	mock_welcome.assert_not_called()


def test_register_conflict_returns_409() -> None:
	client, _, _ = _build_client()

	with patch("gbedu_api.routers.auth.AuthService") as MockSvc:
		instance = MockSvc.return_value
		instance.register = AsyncMock(side_effect=ConflictError("Email already registered"))

		resp = client.post(
			"/api/v1/auth/register",
			json={
				"email": "dup@example.com",
				"password": "Password123!",
				"full_name": "Dup User",
			},
		)

	assert resp.status_code == 409


def test_register_short_password_returns_422() -> None:
	client, _, _ = _build_client()

	resp = client.post(
		"/api/v1/auth/register",
		json={
			"email": "user@example.com",
			"password": "short",
			"full_name": "User",
		},
	)
	assert resp.status_code == 422


def test_register_invalid_email_returns_422() -> None:
	client, _, _ = _build_client()

	resp = client.post(
		"/api/v1/auth/register",
		json={
			"email": "not-an-email",
			"password": "Password123!",
			"full_name": "User",
		},
	)
	assert resp.status_code == 422


def test_register_extra_field_rejected_returns_422() -> None:
	client, _, _ = _build_client()

	resp = client.post(
		"/api/v1/auth/register",
		json={
			"email": "user@example.com",
			"password": "Password123!",
			"full_name": "User",
			"unexpected_field": "oops",
		},
	)
	assert resp.status_code == 422


# ── POST /auth/login ───────────────────────────────────────────────────────────


def test_login_success() -> None:
	client, _, _ = _build_client()
	tokens = _token_pair()

	with patch("gbedu_api.routers.auth.AuthService") as MockSvc:
		instance = MockSvc.return_value
		instance.login = AsyncMock(return_value=(_make_user(), tokens))

		resp = client.post(
			"/api/v1/auth/login",
			json={
				"email": "user@example.com",
				"password": "Password123!",
			},
		)

	assert resp.status_code == 200
	body = resp.json()
	assert body["access_token"] == "fake-access-token"
	assert body["token_type"] == "bearer"


def test_login_invalid_credentials_returns_401() -> None:
	client, _, _ = _build_client()

	with patch("gbedu_api.routers.auth.AuthService") as MockSvc:
		instance = MockSvc.return_value
		instance.login = AsyncMock(side_effect=InvalidCredentialsError())

		resp = client.post(
			"/api/v1/auth/login",
			json={
				"email": "user@example.com",
				"password": "WrongPassword!",
			},
		)

	assert resp.status_code == 401


def test_login_deactivated_account_returns_401() -> None:
	client, _, _ = _build_client()

	with patch("gbedu_api.routers.auth.AuthService") as MockSvc:
		instance = MockSvc.return_value
		instance.login = AsyncMock(side_effect=AuthenticationError("Account is deactivated"))

		resp = client.post(
			"/api/v1/auth/login",
			json={
				"email": "inactive@example.com",
				"password": "Password123!",
			},
		)

	assert resp.status_code == 401


def test_login_missing_fields_returns_422() -> None:
	client, _, _ = _build_client()

	resp = client.post("/api/v1/auth/login", json={"email": "user@example.com"})
	assert resp.status_code == 422


# ── POST /auth/refresh ─────────────────────────────────────────────────────────


def test_refresh_success() -> None:
	client, _, _ = _build_client()
	new_tokens = TokenPair("new-access", "new-refresh")

	with patch("gbedu_api.routers.auth.AuthService") as MockSvc:
		instance = MockSvc.return_value
		instance.refresh = AsyncMock(return_value=new_tokens)

		resp = client.post("/api/v1/auth/refresh", json={"refresh_token": "some-refresh-token"})

	assert resp.status_code == 200
	body = resp.json()
	assert body["access_token"] == "new-access"
	assert body["refresh_token"] == "new-refresh"


def test_refresh_invalid_token_returns_401() -> None:
	client, _, _ = _build_client()

	with patch("gbedu_api.routers.auth.AuthService") as MockSvc:
		instance = MockSvc.return_value
		instance.refresh = AsyncMock(side_effect=TokenInvalidError())

		resp = client.post("/api/v1/auth/refresh", json={"refresh_token": "bad-token"})

	assert resp.status_code == 401


def test_refresh_missing_body_returns_422() -> None:
	client, _, _ = _build_client()

	resp = client.post("/api/v1/auth/refresh", json={})
	assert resp.status_code == 422


# ── POST /auth/logout ──────────────────────────────────────────────────────────


def test_logout_success() -> None:
	client, _, _ = _build_client()

	with patch("gbedu_api.routers.auth.AuthService") as MockSvc:
		instance = MockSvc.return_value
		instance.logout = AsyncMock(return_value=None)

		resp = client.post("/api/v1/auth/logout", json={"refresh_token": "some-refresh-token"})

	assert resp.status_code == 200
	assert resp.json()["message"] == "Logged out successfully"


def test_logout_missing_token_returns_422() -> None:
	client, _, _ = _build_client()

	resp = client.post("/api/v1/auth/logout", json={})
	assert resp.status_code == 422


# ── POST /auth/verify-email ────────────────────────────────────────────────────


def test_verify_email_success() -> None:
	client, _, _ = _build_client()
	user = _make_user(is_verified=True)

	with patch("gbedu_api.routers.auth.AuthService") as MockSvc:
		instance = MockSvc.return_value
		instance.verify_email = AsyncMock(return_value=user)

		resp = client.post("/api/v1/auth/verify-email", json={"token": "valid-token"})

	assert resp.status_code == 200
	assert "verified" in resp.json()["message"].lower()


def test_verify_email_invalid_token_returns_401() -> None:
	client, _, _ = _build_client()

	with patch("gbedu_api.routers.auth.AuthService") as MockSvc:
		instance = MockSvc.return_value
		instance.verify_email = AsyncMock(side_effect=TokenInvalidError())

		resp = client.post("/api/v1/auth/verify-email", json={"token": "bad-token"})

	assert resp.status_code == 401


def test_verify_email_missing_token_returns_422() -> None:
	client, _, _ = _build_client()

	resp = client.post("/api/v1/auth/verify-email", json={})
	assert resp.status_code == 422


# ── POST /auth/forgot-password ─────────────────────────────────────────────────


def test_forgot_password_known_email_enqueues_email() -> None:
	client, mock_db, _ = _build_client()
	user = _make_user()

	mock_result = MagicMock()
	mock_result.scalar_one_or_none.return_value = user
	mock_db.execute = AsyncMock(return_value=mock_result)

	with (
		patch("gbedu_api.routers.auth.AuthService") as MockSvc,
		patch("gbedu_api.routers.auth.enqueue_password_reset_email") as mock_enqueue,
	):
		instance = MockSvc.return_value
		instance.create_password_reset_token = AsyncMock(return_value="reset-tok-abc")

		resp = client.post("/api/v1/auth/forgot-password", json={"email": "user@example.com"})

	assert resp.status_code == 200
	assert "reset link" in resp.json()["message"].lower()
	mock_enqueue.assert_called_once()


def test_forgot_password_unknown_email_returns_200_no_leak() -> None:
	"""Email enumeration protection: unknown address must return identical 200."""
	client, mock_db, _ = _build_client()

	mock_result = MagicMock()
	mock_result.scalar_one_or_none.return_value = None
	mock_db.execute = AsyncMock(return_value=mock_result)

	with (
		patch("gbedu_api.routers.auth.AuthService") as MockSvc,
		patch("gbedu_api.routers.auth.enqueue_password_reset_email") as mock_enqueue,
	):
		instance = MockSvc.return_value
		instance.create_password_reset_token = AsyncMock(return_value=None)

		resp = client.post("/api/v1/auth/forgot-password", json={"email": "ghost@example.com"})

	assert resp.status_code == 200
	assert "reset link" in resp.json()["message"].lower()
	mock_enqueue.assert_not_called()


# ── POST /auth/reset-password ──────────────────────────────────────────────────


def test_reset_password_success() -> None:
	client, _, _ = _build_client()
	user = _make_user()

	with patch("gbedu_api.routers.auth.AuthService") as MockSvc:
		instance = MockSvc.return_value
		instance.reset_password = AsyncMock(return_value=user)

		resp = client.post(
			"/api/v1/auth/reset-password",
			json={
				"token": "valid-reset-token",
				"new_password": "NewPassword456!",
			},
		)

	assert resp.status_code == 200
	assert "reset" in resp.json()["message"].lower()


def test_reset_password_invalid_token_returns_401() -> None:
	client, _, _ = _build_client()

	with patch("gbedu_api.routers.auth.AuthService") as MockSvc:
		instance = MockSvc.return_value
		instance.reset_password = AsyncMock(side_effect=TokenInvalidError())

		resp = client.post(
			"/api/v1/auth/reset-password",
			json={
				"token": "bad-token",
				"new_password": "NewPassword456!",
			},
		)

	assert resp.status_code == 401


def test_reset_password_short_password_returns_422() -> None:
	client, _, _ = _build_client()

	resp = client.post(
		"/api/v1/auth/reset-password",
		json={
			"token": "some-token",
			"new_password": "short",
		},
	)
	assert resp.status_code == 422


# ── GET /auth/google ───────────────────────────────────────────────────────────


def test_google_oauth_start_redirects() -> None:
	client, _, _ = _build_client()

	resp = client.get("/api/v1/auth/google", follow_redirects=False)

	assert resp.status_code in (302, 307)
	location = resp.headers["location"]
	assert "accounts.google.com" in location
	assert "response_type=code" in location
	assert "scope=" in location


# ── GET /auth/google/callback ──────────────────────────────────────────────────


def test_google_oauth_callback_success() -> None:
	client, _, _ = _build_client()
	user = _make_user()
	tokens = _token_pair()

	mock_token_resp = MagicMock()
	mock_token_resp.status_code = 200
	mock_token_resp.json.return_value = {"access_token": "google-access-tok"}

	mock_userinfo_resp = MagicMock()
	mock_userinfo_resp.status_code = 200
	mock_userinfo_resp.json.return_value = {
		"sub": "google-sub-123",
		"email": "oauth@example.com",
		"name": "OAuth User",
		"picture": "https://example.com/pic.jpg",
	}

	with (
		patch("gbedu_api.routers.auth.httpx.AsyncClient") as MockHttp,
		patch("gbedu_api.routers.auth.AuthService") as MockSvc,
	):
		mock_http_instance = AsyncMock()
		MockHttp.return_value.__aenter__ = AsyncMock(return_value=mock_http_instance)
		MockHttp.return_value.__aexit__ = AsyncMock(return_value=False)
		mock_http_instance.post = AsyncMock(return_value=mock_token_resp)
		mock_http_instance.get = AsyncMock(return_value=mock_userinfo_resp)

		svc_instance = MockSvc.return_value
		svc_instance.oauth_callback = AsyncMock(return_value=(user, tokens))

		resp = client.get("/api/v1/auth/google/callback?code=auth-code-xyz")

	assert resp.status_code == 200
	body = resp.json()
	assert body["access_token"] == "fake-access-token"


def test_google_oauth_callback_google_token_exchange_fails_returns_400() -> None:
	client, _, _ = _build_client()

	mock_token_resp = MagicMock()
	mock_token_resp.status_code = 400
	mock_token_resp.json.return_value = {"error": "invalid_grant"}

	with patch("gbedu_api.routers.auth.httpx.AsyncClient") as MockHttp:
		mock_http_instance = AsyncMock()
		MockHttp.return_value.__aenter__ = AsyncMock(return_value=mock_http_instance)
		MockHttp.return_value.__aexit__ = AsyncMock(return_value=False)
		mock_http_instance.post = AsyncMock(return_value=mock_token_resp)

		resp = client.get("/api/v1/auth/google/callback?code=bad-code")

	assert resp.status_code == 400
	assert resp.json()["detail"]["error_code"] == "AUTHENTICATION_ERROR"


def test_google_oauth_callback_userinfo_fails_returns_400() -> None:
	client, _, _ = _build_client()

	mock_token_resp = MagicMock()
	mock_token_resp.status_code = 200
	mock_token_resp.json.return_value = {"access_token": "google-tok"}

	mock_userinfo_resp = MagicMock()
	mock_userinfo_resp.status_code = 401

	with patch("gbedu_api.routers.auth.httpx.AsyncClient") as MockHttp:
		mock_http_instance = AsyncMock()
		MockHttp.return_value.__aenter__ = AsyncMock(return_value=mock_http_instance)
		MockHttp.return_value.__aexit__ = AsyncMock(return_value=False)
		mock_http_instance.post = AsyncMock(return_value=mock_token_resp)
		mock_http_instance.get = AsyncMock(return_value=mock_userinfo_resp)

		resp = client.get("/api/v1/auth/google/callback?code=code-xyz")

	assert resp.status_code == 400
	assert "Google profile" in resp.json()["detail"]["message"]
