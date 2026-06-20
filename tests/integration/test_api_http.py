"""HTTP-layer integration tests for the Gbẹdu FastAPI platform.

These tests exercise the full HTTP stack — middleware, routers, services, DB, and
Redis — via httpx.AsyncClient with ASGITransport.  The DB session is wrapped in a
savepoint and rolled back after each test (see the test_db_session fixture in
conftest.py).  Redis is replaced with an in-memory FakeRedis instance.

Import convention: gbedu_api.* (service installed as editable package via uv workspace).
"""
from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from typing import Any

import itertools
import fakeredis.aioredis
import httpx
import pytest
import pytest_asyncio
from jose import jwt as jose_jwt
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock, MagicMock, patch

# Each fixture invocation gets its own source IP so rate limit buckets never
# bleed across tests — all tests share the same in-process MemoryStorage backend.
_ip_counter = itertools.count(1)

from gbedu_core._uuid7 import uuid7str
from gbedu_core.config import get_settings
from gbedu_core.models.user import TIER_DAILY_LIMITS, SubscriptionTier

pytestmark = pytest.mark.integration

# ── Shared helpers ─────────────────────────────────────────────────────────────

_REGISTER_URL = "/api/v1/auth/register"
_LOGIN_URL = "/api/v1/auth/login"
_REFRESH_URL = "/api/v1/auth/refresh"
_LOGOUT_URL = "/api/v1/auth/logout"
_ME_URL = "/api/v1/users/me"
_STATS_URL = "/api/v1/users/me/stats"
_HEALTH_URL = "/api/v1/health"


def _reg_body(
	email: str | None = None,
	password: str = "StrongPass1!",
	full_name: str = "Amara Nwosu",
) -> dict[str, str]:
	return {
		"email": email or f"test-{uuid7str()}@example.com",
		"password": password,
		"full_name": full_name,
	}


# ── HTTP client fixture with DB + Redis overrides ─────────────────────────────

@pytest_asyncio.fixture
async def http_client(
	test_db_session: AsyncSession,
	test_redis: fakeredis.aioredis.FakeRedis,
) -> AsyncGenerator[httpx.AsyncClient, None]:
	"""AsyncClient wired to a fresh app instance with overridden DB and Redis deps.

	Each test gets its own FakeRedis so state never leaks between tests.
	The DB session rolls back via the savepoint in test_db_session.
	"""
	from gbedu_api.main import create_app
	from gbedu_api.deps import get_db, get_redis

	# OTel instrument_app crashes with _IncludedRouter in test transport — disable it.
	with patch("opentelemetry.instrumentation.fastapi.FastAPIInstrumentor.instrument_app"):
		app = create_app()

	async def _override_db() -> AsyncGenerator[AsyncSession, None]:
		yield test_db_session

	async def _override_redis() -> fakeredis.aioredis.FakeRedis:
		return test_redis

	app.dependency_overrides[get_db] = _override_db
	app.dependency_overrides[get_redis] = _override_redis

	# EmailService is instantiated inline in auth.py routes and background tasks
	# execute synchronously in ASGI test transport — patch it to avoid real SMTP.
	_mock_email = MagicMock()
	_mock_email.send_verify_email = AsyncMock()
	_mock_email.send_welcome = AsyncMock()
	_mock_email.send_password_reset = AsyncMock()
	_mock_email.send_generation_complete = AsyncMock()

	n = next(_ip_counter)
	unique_ip = f"10.{(n >> 8) & 0xFF}.{n & 0xFF}.1"

	with patch("gbedu_api.routers.auth.EmailService", return_value=_mock_email):
		async with httpx.AsyncClient(
			transport=httpx.ASGITransport(app=app, client=(unique_ip, 9000)),  # type: ignore[arg-type]
			base_url="http://testserver",
		) as client:
			yield client


# ── 1. Register → login → /me full flow ───────────────────────────────────────

async def test_register_and_login_full_flow(http_client: httpx.AsyncClient) -> None:
	body = _reg_body()

	# Register
	reg_resp = await http_client.post(_REGISTER_URL, json=body)
	assert reg_resp.status_code == 201, reg_resp.text
	reg_data = reg_resp.json()
	assert reg_data["user"]["email"] == body["email"]
	assert reg_data["user"]["full_name"] == body["full_name"]
	assert "access_token" in reg_data["tokens"]
	assert reg_data["tokens"]["token_type"] == "bearer"

	# Login
	login_resp = await http_client.post(
		_LOGIN_URL,
		json={"email": body["email"], "password": body["password"]},
	)
	assert login_resp.status_code == 200, login_resp.text
	token_data = login_resp.json()
	access_token: str = token_data["access_token"]
	assert access_token

	# /users/me
	me_resp = await http_client.get(
		_ME_URL,
		headers={"Authorization": f"Bearer {access_token}"},
	)
	assert me_resp.status_code == 200, me_resp.text
	me = me_resp.json()
	assert me["email"] == body["email"]
	assert me["full_name"] == body["full_name"]
	assert me["subscription_tier"] == "free"
	assert me["is_active"] is True


# ── 2. Wrong password → 401 ────────────────────────────────────────────────────

async def test_login_wrong_password_returns_401(http_client: httpx.AsyncClient) -> None:
	body = _reg_body()
	reg = await http_client.post(_REGISTER_URL, json=body)
	assert reg.status_code == 201

	resp = await http_client.post(
		_LOGIN_URL,
		json={"email": body["email"], "password": "wrong-password-123"},
	)
	assert resp.status_code == 401, resp.text


# ── 3. Unknown email → 401 (no enumeration) ───────────────────────────────────

async def test_login_nonexistent_user_returns_401(http_client: httpx.AsyncClient) -> None:
	resp = await http_client.post(
		_LOGIN_URL,
		json={"email": f"nobody-{uuid7str()}@ghost.example", "password": "AnyPass1!"},
	)
	assert resp.status_code == 401, resp.text


# ── 4. Duplicate email → 409 ──────────────────────────────────────────────────

async def test_register_duplicate_email_returns_409(http_client: httpx.AsyncClient) -> None:
	body = _reg_body()
	first = await http_client.post(_REGISTER_URL, json=body)
	assert first.status_code == 201

	second = await http_client.post(_REGISTER_URL, json=body)
	assert second.status_code == 409, second.text


# ── 5. No auth header → 401 ───────────────────────────────────────────────────

async def test_protected_endpoint_without_token_returns_401(
	http_client: httpx.AsyncClient,
) -> None:
	resp = await http_client.get(_ME_URL)
	assert resp.status_code == 401, resp.text


# ── 6. Expired JWT → 401 ──────────────────────────────────────────────────────

async def test_protected_endpoint_with_expired_token_returns_401(
	http_client: httpx.AsyncClient,
) -> None:
	settings = get_settings()
	cfg = settings.jwt

	expired_payload: dict[str, Any] = {
		"sub": uuid7str(),
		"type": "access",
		"iat": int(time.time()) - 7200,
		"exp": int(time.time()) - 3600,  # expired one hour ago
		"jti": uuid7str(),
	}
	expired_token = jose_jwt.encode(expired_payload, cfg.secret_key, algorithm=cfg.algorithm)

	resp = await http_client.get(
		_ME_URL,
		headers={"Authorization": f"Bearer {expired_token}"},
	)
	assert resp.status_code == 401, resp.text


# ── 7. Token refresh flow ─────────────────────────────────────────────────────

async def test_token_refresh_flow(http_client: httpx.AsyncClient) -> None:
	body = _reg_body()
	reg = await http_client.post(_REGISTER_URL, json=body)
	assert reg.status_code == 201

	login = await http_client.post(
		_LOGIN_URL,
		json={"email": body["email"], "password": body["password"]},
	)
	assert login.status_code == 200
	old_access: str = login.json()["access_token"]
	refresh_token: str = login.json()["refresh_token"]

	# Exchange refresh token for new access token
	refresh_resp = await http_client.post(
		_REFRESH_URL,
		json={"refresh_token": refresh_token},
	)
	assert refresh_resp.status_code == 200, refresh_resp.text
	new_tokens = refresh_resp.json()
	new_access: str = new_tokens["access_token"]
	assert new_access
	assert new_access != old_access  # must issue a genuinely fresh token

	# New token grants access to protected endpoint
	me_resp = await http_client.get(
		_ME_URL,
		headers={"Authorization": f"Bearer {new_access}"},
	)
	assert me_resp.status_code == 200, me_resp.text
	assert me_resp.json()["email"] == body["email"]


# ── 8. Logout revokes refresh token ──────────────────────────────────────────

async def test_logout_revokes_refresh_token(http_client: httpx.AsyncClient) -> None:
	body = _reg_body()
	reg = await http_client.post(_REGISTER_URL, json=body)
	assert reg.status_code == 201

	login = await http_client.post(
		_LOGIN_URL,
		json={"email": body["email"], "password": body["password"]},
	)
	assert login.status_code == 200
	refresh_token: str = login.json()["refresh_token"]

	# Logout — blocklists the refresh token in Redis
	logout_resp = await http_client.post(
		_LOGOUT_URL,
		json={"refresh_token": refresh_token},
	)
	assert logout_resp.status_code == 200, logout_resp.text

	# Attempt to refresh with the now-revoked token → must fail
	stale_refresh = await http_client.post(
		_REFRESH_URL,
		json={"refresh_token": refresh_token},
	)
	assert stale_refresh.status_code == 401, stale_refresh.text


# ── 9. Stats endpoint returns correct daily quota ─────────────────────────────

async def test_get_stats_returns_correct_daily_quota(
	http_client: httpx.AsyncClient,
	test_redis: fakeredis.aioredis.FakeRedis,
) -> None:
	body = _reg_body()
	reg = await http_client.post(_REGISTER_URL, json=body)
	assert reg.status_code == 201
	user_id: str = reg.json()["user"]["id"]

	login = await http_client.post(
		_LOGIN_URL,
		json={"email": body["email"], "password": body["password"]},
	)
	assert login.status_code == 200
	access_token: str = login.json()["access_token"]

	# Manually seed the Redis quota counter to 5
	quota_key = f"gen_quota:{user_id}"
	await test_redis.set(quota_key, 5)

	stats_resp = await http_client.get(
		_STATS_URL,
		headers={"Authorization": f"Bearer {access_token}"},
	)
	assert stats_resp.status_code == 200, stats_resp.text
	stats = stats_resp.json()
	assert stats["total_generations_today"] == 5
	assert stats["daily_limit"] == TIER_DAILY_LIMITS[SubscriptionTier.free]
	assert stats["subscription_tier"] == "free"


# ── 10. Health endpoint ───────────────────────────────────────────────────────

async def test_health_endpoint(http_client: httpx.AsyncClient) -> None:
	resp = await http_client.get(_HEALTH_URL)
	assert resp.status_code == 200, resp.text
	data = resp.json()
	assert "status" in data
	assert data["status"] == "ok"
	assert data["service"] == "gbedu-api"


# ── 11. Rate limit enforced on login ─────────────────────────────────────────

async def test_rate_limit_enforced_on_login(http_client: httpx.AsyncClient) -> None:
	"""Fire more than RATE_LIMIT_AUTH (10/minute) login attempts and expect a 429.

	We use a deliberately wrong password so no real logins succeed; we only need
	to verify the rate limiter fires.  slowapi counts by remote address; the ASGI
	test transport sends requests from "testclient" which maps to 127.0.0.1 by
	default — enough to trigger the shared limiter bucket.

	The rate limit is 10/minute, so 15 requests guarantees we cross it.
	"""
	target_email = f"ratelimit-{uuid7str()}@example.com"
	got_429 = False

	for _ in range(15):
		resp = await http_client.post(
			_LOGIN_URL,
			json={"email": target_email, "password": "badpass"},
		)
		if resp.status_code == 429:
			got_429 = True
			break

	assert got_429, (
		"Expected a 429 after exceeding 10/minute login rate limit but never received one. "
		"Check that SlowAPIMiddleware is active and the limiter key resolves to a shared IP."
	)
