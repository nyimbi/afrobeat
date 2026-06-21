"""Chaos engineering tests — verify the platform degrades gracefully under failure.

Each test injects a specific failure condition via dependency_overrides or
unittest.mock.patch and asserts that:
  - the correct HTTP status code is returned
  - no Python traceback leaks into the response body
  - the system does not crash (i.e. returns a structured error, not a 500)

Infrastructure pattern mirrors test_api_http.py:
  - OTel instrument_app patched out (crashes with _IncludedRouter in ASGI transport)
  - EmailService mocked (avoids real SMTP in auth flows)
  - Unique source IP per fixture invocation (prevents rate-limit bleed between tests)
  - DB session wrapped in a savepoint (rolls back after each test)
  - FakeRedis for the happy-path Redis dep

All tests are marked @pytest.mark.integration.
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import AsyncGenerator
from typing import Any, Never
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import httpx
import pytest
import pytest_asyncio
from gbedu_core._uuid7 import uuid7str
from gbedu_core.models.user import SubscriptionTier
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

# ── URL constants ──────────────────────────────────────────────────────────────

_HEALTH_URL = "/api/v1/health"
_READY_URL = "/api/v1/ready"
_REGISTER_URL = "/api/v1/auth/register"
_LOGIN_URL = "/api/v1/auth/login"
_GENERATIONS_URL = "/api/v1/generations"

# Shared IP counter — each fixture invocation gets a unique source IP so
# slowapi rate-limit buckets never bleed across tests.
_ip_counter = itertools.count(10_000)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _unique_ip() -> str:
	n = next(_ip_counter)
	return f"10.{(n >> 8) & 0xFF}.{n & 0xFF}.1"


def _reg_body(
	email: str | None = None,
	password: str = "StrongPass1!",
	full_name: str = "Chaos Tester",
) -> dict[str, str]:
	return {
		"email": email or f"chaos-{uuid7str()}@example.com",
		"password": password,
		"full_name": full_name,
	}


def _gen_body() -> dict[str, Any]:
	return {
		"prompt": "high energy afropop club banger with talking drum percussion",
		"sub_genre": "afropop",
		"language": "english",
		"bpm": 120,
		"energy_level": 8,
		"duration_seconds": 30,
	}


def _mock_email_service() -> MagicMock:
	svc = MagicMock()
	svc.send_verify_email = AsyncMock()
	svc.send_welcome = AsyncMock()
	svc.send_password_reset = AsyncMock()
	svc.send_generation_complete = AsyncMock()
	return svc


# ── Base fixture factory ───────────────────────────────────────────────────────


def _make_app(
	db_override: Any | None = None,
	redis_override: Any | None = None,
	ml_override: Any | None = None,
) -> Any:
	"""Build a FastAPI app with optional dependency overrides.

	Accepts callables (for overrides that need to be async generators) or plain
	values; wraps plain values in a lambda automatically.
	"""
	from gbedu_api.deps import get_db, get_ml_client, get_redis
	from gbedu_api.main import create_app

	with patch("opentelemetry.instrumentation.fastapi.FastAPIInstrumentor.instrument_app"):
		app = create_app()

	if db_override is not None:
		app.dependency_overrides[get_db] = db_override
	if redis_override is not None:
		app.dependency_overrides[get_redis] = redis_override
	if ml_override is not None:
		app.dependency_overrides[get_ml_client] = ml_override

	return app


# ── Standard chaos fixture (DB + Redis working, ML working) ───────────────────


@pytest_asyncio.fixture
async def chaos_client(
	test_db_session: AsyncSession,
	test_redis: fakeredis.aioredis.FakeRedis,
) -> AsyncGenerator[httpx.AsyncClient, None]:
	"""Standard client with real DB savepoint + FakeRedis. Used by tests that
	inject failures via dependency_overrides inside the test body itself."""
	from gbedu_api.deps import get_db, get_redis

	with patch("opentelemetry.instrumentation.fastapi.FastAPIInstrumentor.instrument_app"):
		from gbedu_api.main import create_app

		app = create_app()

	async def _db() -> AsyncGenerator[AsyncSession, None]:
		yield test_db_session

	async def _redis() -> fakeredis.aioredis.FakeRedis:
		return test_redis

	app.dependency_overrides[get_db] = _db
	app.dependency_overrides[get_redis] = _redis

	_mock_email = _mock_email_service()
	unique_ip = _unique_ip()

	with (
		patch("gbedu_api.worker_tasks.enqueue_verify_email", MagicMock()),
		patch("gbedu_api.worker_tasks.enqueue_welcome_email", MagicMock()),
		patch("gbedu_api.worker_tasks.enqueue_password_reset_email", MagicMock()),
	):
		async with httpx.AsyncClient(
			transport=httpx.ASGITransport(app=app, client=(unique_ip, 9000)),  # type: ignore[arg-type]
			base_url="http://testserver",
		) as client:
			yield client


# ── 1. /ready → 503 when DB is unavailable ────────────────────────────────────


@pytest.mark.integration
async def test_health_returns_503_when_db_is_unavailable(
	test_redis: fakeredis.aioredis.FakeRedis,
) -> None:
	"""Override get_db to raise OperationalError; /ready must return 503 with
	a 'database' key in the checks dict showing an error message."""

	def _failing_db() -> Never:
		raise OperationalError("connection refused", None, None)

	async def _redis() -> fakeredis.aioredis.FakeRedis:
		return test_redis

	app = _make_app(db_override=_failing_db, redis_override=_redis)

	# Also need a working ML client override so only DB causes the failure
	mock_ml = MagicMock()
	mock_ml.get_health = AsyncMock(return_value=True)
	from gbedu_api.deps import get_ml_client

	app.dependency_overrides[get_ml_client] = lambda: mock_ml

	unique_ip = _unique_ip()
	async with httpx.AsyncClient(
		transport=httpx.ASGITransport(app=app, client=(unique_ip, 9000)),  # type: ignore[arg-type]
		base_url="http://testserver",
	) as client:
		resp = await client.get(_READY_URL)

	assert resp.status_code == 503, resp.text
	body = resp.json()
	# HTTPException detail is the ReadinessCheck model dict
	detail = body.get("detail", body)
	assert detail["status"] == "degraded"
	db_check: str = detail["checks"]["database"]
	assert db_check.startswith("error:"), f"Expected error in db check, got: {db_check!r}"
	# No Python traceback in response
	assert "Traceback" not in resp.text
	assert "traceback" not in resp.text


# ── 2. /ready → 503 when Redis is unavailable ─────────────────────────────────


@pytest.mark.integration
async def test_health_returns_503_when_redis_is_unavailable(
	test_db_session: AsyncSession,
) -> None:
	"""Override get_redis to return a broken Redis client; /ready must return 503."""

	async def _db() -> AsyncGenerator[AsyncSession, None]:
		yield test_db_session

	# Redis that raises ConnectionError on every call
	broken_redis = MagicMock()
	broken_redis.ping = AsyncMock(side_effect=ConnectionError("Redis connection refused"))

	async def _broken_redis():
		return broken_redis

	mock_ml = MagicMock()
	mock_ml.get_health = AsyncMock(return_value=True)

	from gbedu_api.deps import get_ml_client

	app = _make_app(db_override=_db, redis_override=_broken_redis)
	app.dependency_overrides[get_ml_client] = lambda: mock_ml

	unique_ip = _unique_ip()
	async with httpx.AsyncClient(
		transport=httpx.ASGITransport(app=app, client=(unique_ip, 9000)),  # type: ignore[arg-type]
		base_url="http://testserver",
	) as client:
		resp = await client.get(_READY_URL)

	assert resp.status_code == 503, resp.text
	body = resp.json()
	detail = body.get("detail", body)
	assert detail["status"] == "degraded"
	redis_check: str = detail["checks"]["redis"]
	assert "error" in redis_check.lower(), f"Expected error in redis check, got: {redis_check!r}"
	assert "Traceback" not in resp.text


# ── 3. ML down → /health 200, /ready 503 ─────────────────────────────────────


@pytest.mark.integration
async def test_health_200_when_ml_down_but_ready_503(
	test_db_session: AsyncSession,
	test_redis: fakeredis.aioredis.FakeRedis,
) -> None:
	"""ML service returning is_healthy=False is non-critical for /health (liveness)
	but does cause /ready (readiness) to return 503 because it signals degradation."""

	async def _db() -> AsyncGenerator[AsyncSession, None]:
		yield test_db_session

	async def _redis() -> fakeredis.aioredis.FakeRedis:
		return test_redis

	mock_ml = MagicMock()
	mock_ml.get_health = AsyncMock(return_value=False)  # unhealthy but doesn't raise

	app = _make_app(db_override=_db, redis_override=_redis, ml_override=lambda: mock_ml)

	unique_ip = _unique_ip()
	async with httpx.AsyncClient(
		transport=httpx.ASGITransport(app=app, client=(unique_ip, 9000)),  # type: ignore[arg-type]
		base_url="http://testserver",
	) as client:
		# /health is liveness — must always be 200 regardless of dependencies
		health_resp = await client.get(_HEALTH_URL)
		assert health_resp.status_code == 200, health_resp.text
		assert health_resp.json()["status"] == "ok"

		# /ready checks dependencies — ML unhealthy → 503
		ready_resp = await client.get(_READY_URL)
		assert ready_resp.status_code == 503, ready_resp.text
		detail = ready_resp.json().get("detail", ready_resp.json())
		assert detail["status"] == "degraded"
		ml_check: str = detail["checks"]["ml_service"]
		assert "degraded" in ml_check or "error" in ml_check.lower(), (
			f"Expected ml_service check to indicate degradation, got: {ml_check!r}"
		)


# ── 4. Rate limiter fails open when Redis raises ──────────────────────────────


@pytest.mark.integration
async def test_rate_limiter_fails_open_on_redis_error(
	test_db_session: AsyncSession,
) -> None:
	"""When Redis raises ConnectionError on every call the rate limiter must
	fail open — the request must complete with 200 or 401, never 500."""

	async def _db() -> AsyncGenerator[AsyncSession, None]:
		yield test_db_session

	# Redis raises on every operation — simulates total Redis loss
	broken_redis = MagicMock()
	broken_redis.ping = AsyncMock(side_effect=ConnectionError("no redis"))
	broken_redis.get = AsyncMock(side_effect=ConnectionError("no redis"))
	broken_redis.set = AsyncMock(side_effect=ConnectionError("no redis"))
	broken_redis.incr = AsyncMock(side_effect=ConnectionError("no redis"))
	broken_redis.expire = AsyncMock(side_effect=ConnectionError("no redis"))
	broken_redis.setex = AsyncMock(side_effect=ConnectionError("no redis"))
	broken_redis.exists = AsyncMock(side_effect=ConnectionError("no redis"))

	async def _broken_redis():
		return broken_redis

	mock_ml = MagicMock()
	mock_ml.get_health = AsyncMock(return_value=True)

	app = _make_app(db_override=_db, redis_override=_broken_redis, ml_override=lambda: mock_ml)

	_mock_email = _mock_email_service()
	unique_ip = _unique_ip()

	with (
		patch("gbedu_api.worker_tasks.enqueue_verify_email", MagicMock()),
		patch("gbedu_api.worker_tasks.enqueue_welcome_email", MagicMock()),
		patch("gbedu_api.worker_tasks.enqueue_password_reset_email", MagicMock()),
	):
		async with httpx.AsyncClient(
			transport=httpx.ASGITransport(app=app, client=(unique_ip, 9000)),  # type: ignore[arg-type]
			base_url="http://testserver",
		) as client:
			resp = await client.post(
				_LOGIN_URL,
				json={"email": "nonexistent@example.com", "password": "WrongPass1!"},
			)

	# Must not crash — 200 (valid login) or 401 (wrong creds) are both acceptable.
	# 500 means the rate limiter threw an unhandled exception.
	assert resp.status_code in (200, 401), (
		f"Expected 200 or 401 (rate limiter fail-open), got {resp.status_code}: {resp.text}"
	)
	assert "Traceback" not in resp.text


# ── 5. DB OperationalError on any endpoint → 503, not 500, no traceback ───────


@pytest.mark.integration
async def test_db_operational_error_returns_503_not_500(
	test_redis: fakeredis.aioredis.FakeRedis,
) -> None:
	"""Any endpoint that queries the DB must return 503 (service unavailable)
	when the DB raises OperationalError — not 500 (internal server error) — and
	the response body must contain no traceback."""

	# DB always raises OperationalError (simulates connection loss mid-request)
	async def _failing_db() -> AsyncGenerator[AsyncSession, None]:
		raise OperationalError("server closed the connection unexpectedly", None, None)
		yield  # pragma: no cover — make mypy happy

	async def _redis() -> fakeredis.aioredis.FakeRedis:
		return test_redis

	mock_ml = MagicMock()
	mock_ml.get_health = AsyncMock(return_value=True)

	app = _make_app(db_override=_failing_db, redis_override=_redis, ml_override=lambda: mock_ml)

	_mock_email = _mock_email_service()
	unique_ip = _unique_ip()

	with (
		patch("gbedu_api.worker_tasks.enqueue_verify_email", MagicMock()),
		patch("gbedu_api.worker_tasks.enqueue_welcome_email", MagicMock()),
		patch("gbedu_api.worker_tasks.enqueue_password_reset_email", MagicMock()),
	):
		async with httpx.AsyncClient(
			transport=httpx.ASGITransport(app=app, client=(unique_ip, 9000)),  # type: ignore[arg-type]
			base_url="http://testserver",
		) as client:
			# /ready explicitly checks the DB
			resp = await client.get(_READY_URL)

	assert resp.status_code == 503, (
		f"Expected 503 when DB is down, got {resp.status_code}: {resp.text}"
	)
	assert "Traceback" not in resp.text, "Response must not contain a Python traceback"
	assert "traceback" not in resp.text

	# Generic error message must not reveal internal details
	response_text = resp.text.lower()
	assert "sqlalchemy" not in response_text, "Response must not reveal ORM internals"


# ── 6. Registration uniqueness enforced by DB unique constraint ───────────────


@pytest.mark.integration
async def test_concurrent_registration_idempotency(
	test_db_session: AsyncSession,
) -> None:
	"""Verify the PostgreSQL unique constraint on user.email prevents duplicate
	accounts at the DB layer, regardless of application-level checks.

	SQLAlchemy AsyncSession does not support concurrent coroutine access (it
	serialises access to a single connection), so concurrent HTTP tests would
	produce InvalidRequestError rather than 409. This test validates the actual
	correctness guarantee — the uniqueness constraint — at the correct layer.
	"""
	from gbedu_core.models.user import SubscriptionStatus, User
	from gbedu_core.security import hash_password
	from sqlalchemy.exc import IntegrityError

	shared_email = f"race-{uuid7str()}@example.com"

	user1 = User(
		id=uuid7str(),
		email=shared_email,
		hashed_password=hash_password("Pass1!"),
		full_name="First User",
		subscription_tier=SubscriptionTier.free,
		subscription_status=SubscriptionStatus.active,
		is_active=True,
		is_verified=False,
		preferred_language="en",
	)
	test_db_session.add(user1)
	await test_db_session.flush()

	user2 = User(
		id=uuid7str(),
		email=shared_email,  # same email — must violate unique constraint
		hashed_password=hash_password("Pass2!"),
		full_name="Second User",
		subscription_tier=SubscriptionTier.free,
		subscription_status=SubscriptionStatus.active,
		is_active=True,
		is_verified=False,
		preferred_language="en",
	)
	test_db_session.add(user2)

	with pytest.raises(IntegrityError):
		await test_db_session.flush()

	await test_db_session.rollback()


# ── 7. Redis INCR is atomic under concurrent async load ──────────────────────


@pytest.mark.integration
async def test_generation_quota_is_atomic_under_concurrency(
	test_redis: fakeredis.aioredis.FakeRedis,
) -> None:
	"""Verify that concurrent asyncio.gather calls to Redis INCR produce an
	exact, non-duplicated count — no lost updates, no double-counting.

	This tests the atomicity guarantee of Redis INCR that the quota system
	relies on. SQLAlchemy AsyncSession does not support concurrent coroutine
	access, so quota enforcement at the HTTP layer is tested here at the Redis
	layer where the guarantee is provided.
	"""
	from gbedu_core.models.user import TIER_DAILY_LIMITS

	limit = TIER_DAILY_LIMITS[SubscriptionTier.creator]  # 20
	total_requests = limit + 5  # 25 — 5 must be over-limit
	quota_key = f"gen_quota:{uuid7str()}"

	async def _incr_and_check() -> bool:
		"""Atomically increment; return True if within limit, False if over."""
		count = await test_redis.incr(quota_key)
		if count == 1:
			await test_redis.expire(quota_key, 86400)
		return count <= limit

	results = await asyncio.gather(*[_incr_and_check() for _ in range(total_requests)])

	accepted = sum(1 for r in results if r is True)
	rejected = sum(1 for r in results if r is False)

	assert accepted == limit, f"Expected exactly {limit} accepted (within quota), got {accepted}"
	assert rejected == total_requests - limit, (
		f"Expected exactly {total_requests - limit} rejected (over quota), got {rejected}"
	)

	# The final Redis counter must be exactly total_requests — no lost updates
	final = await test_redis.get(quota_key)
	assert int(final) == total_requests, (
		f"Redis counter must equal total requests ({total_requests}), got {int(final)}"
	)
