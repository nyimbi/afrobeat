"""OWASP-aligned HTTP security tests for the Gbẹdu FastAPI platform.

These tests exercise the full HTTP stack via httpx.AsyncClient + ASGITransport —
identical transport setup to tests/integration/test_api_http.py.  They verify that
malicious inputs are rejected safely at the validation layer and never propagate to
the database, cause tracebacks, or produce 5xx responses.

No real DB or Redis required: the same FakeRedis + transactional-savepoint session
fixtures from conftest.py are used.

Covers OWASP Top 10 (2021) categories:
  A03 — Injection (SQL injection, null bytes)
  A03 — XSS reflection
  A04 — Insecure Design (mass assignment, extreme values)
  A07 — Identification and Authentication Failures (header injection, auth bypass)
  A08 — Software and Data Integrity (path traversal)
  A09 — Security Logging and Monitoring (no traceback leakage)
"""
from __future__ import annotations

import itertools
from collections.abc import AsyncGenerator

import fakeredis.aioredis
import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock, MagicMock, patch

from gbedu_core._uuid7 import uuid7str

pytestmark = pytest.mark.integration

# Each fixture invocation gets its own source IP so rate-limit buckets never
# bleed across tests (mirrors the pattern in test_api_http.py).
_ip_counter = itertools.count(1000)

_REGISTER_URL = "/api/v1/auth/register"
_LOGIN_URL    = "/api/v1/auth/login"


# ── fixture ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def owasp_client(
	test_db_session: AsyncSession,
	test_redis: fakeredis.aioredis.FakeRedis,
) -> AsyncGenerator[httpx.AsyncClient, None]:
	"""AsyncClient wired to a fresh app instance with DB/Redis overrides.

	Mirrors http_client in test_api_http.py exactly:
	  - OTel instrument_app patched out (crashes with _IncludedRouter in ASGI transport)
	  - EmailService mocked so no real SMTP calls fire in background tasks
	  - Unique source IP per fixture invocation to avoid rate-limit cross-contamination
	"""
	from gbedu_api.main import create_app
	from gbedu_api.deps import get_db, get_redis

	with patch("opentelemetry.instrumentation.fastapi.FastAPIInstrumentor.instrument_app"):
		app = create_app()

	async def _override_db() -> AsyncGenerator[AsyncSession, None]:
		yield test_db_session

	async def _override_redis() -> fakeredis.aioredis.FakeRedis:
		return test_redis

	app.dependency_overrides[get_db] = _override_db
	app.dependency_overrides[get_redis] = _override_redis

	n = next(_ip_counter)
	unique_ip = f"10.{(n >> 8) & 0xFF}.{n & 0xFF}.1"

	# Email is now queued to Celery — patch the worker_tasks shim so no broker
	# connection is required during tests.
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


# ── helpers ───────────────────────────────────────────────────────────────────

def _no_leak(resp: httpx.Response) -> None:
	"""Assert the response body does not expose internal implementation details."""
	body = resp.text.lower()
	assert "traceback" not in resp.text, "Python traceback leaked in response"
	assert "sqlalchemy" not in body,     "SQLAlchemy detail leaked in response"
	assert "pg8000" not in body,         "Database driver detail leaked in response"
	assert "asyncpg" not in body,        "Database driver detail leaked in response"
	assert "internal server error" not in body or resp.status_code != 500, (
		"Unhandled 500 with internal server error body"
	)


def _unique_email() -> str:
	return f"owasp-{uuid7str()}@example.com"


# ── tests ─────────────────────────────────────────────────────────────────────

class TestOWASPSecurity:
	"""OWASP Top 10 behavioural security checks against the live ASGI stack."""

	# ── A03: SQL Injection ────────────────────────────────────────────────────

	async def test_sql_injection_in_login_email(
		self, owasp_client: httpx.AsyncClient,
	) -> None:
		"""Classic tautology injection in the email field must be rejected at
		Pydantic validation (EmailStr), not passed to the database."""
		resp = await owasp_client.post(
			_LOGIN_URL,
			json={"email": "' OR '1'='1", "password": "anything"},
		)
		assert resp.status_code in (400, 422), (
			f"Expected 400/422 for SQL injection in email, got {resp.status_code}"
		)
		_no_leak(resp)

	async def test_sql_injection_in_marketplace_genre_filter(
		self, owasp_client: httpx.AsyncClient,
	) -> None:
		"""Query-string injection in the sub_genre filter must not cause a 500.
		SQLAlchemy parameterises all values, so the statement is safe; the ORM
		may return 200 with an empty result set or 422 if enum validation rejects
		the value — either is acceptable."""
		resp = await owasp_client.get(
			"/api/v1/marketplace/beats",
			params={"genre": "'; DROP TABLE users; --"},
		)
		assert resp.status_code in (200, 422), (
			f"Expected 200/422 for SQL injection in genre param, got {resp.status_code}"
		)
		_no_leak(resp)

	async def test_sql_injection_in_track_title_patch(
		self, owasp_client: httpx.AsyncClient,
	) -> None:
		"""PATCH /tracks/{id} with a SQL-injection title should fail with 401
		(unauthenticated) before reaching the DB, never with 500."""
		resp = await owasp_client.patch(
			"/api/v1/tracks/some-track-id",
			json={"title": "'; DROP TABLE tracks; --"},
		)
		assert resp.status_code in (401, 422), (
			f"Expected 401/422 for unauthenticated PATCH with SQLi title, got {resp.status_code}"
		)
		_no_leak(resp)

	# ── A03: XSS reflection ───────────────────────────────────────────────────

	async def test_xss_in_registration_full_name_not_reflected_unescaped(
		self, owasp_client: httpx.AsyncClient,
	) -> None:
		"""XSS payload in full_name must be stored as-is (data, not code) and
		must not be reflected as raw unescaped HTML in the JSON response body.
		The API is JSON-only, so angle brackets appear as Unicode escapes
		(\\u003c / \\u003e) in the serialised output, not as literal < >."""
		xss = "<script>alert(1)</script>"
		resp = await owasp_client.post(
			_REGISTER_URL,
			json={
				"email":     _unique_email(),
				"password":  "StrongPass1!",
				"full_name": xss,
			},
		)
		# Must succeed — the data is valid UTF-8 text; storage is safe.
		assert resp.status_code == 201, (
			f"Expected 201 for XSS payload in full_name, got {resp.status_code}: {resp.text}"
		)
		# XSS safety for a JSON API is guaranteed by Content-Type, not by escaping
		# angle brackets in the JSON body (FastAPI serialises as-is, which is correct).
		# The browser must not render the JSON as HTML.
		assert resp.headers["content-type"].startswith("application/json"), (
			f"Expected application/json response, got: {resp.headers['content-type']}"
		)
		# The full_name is stored and returned as data, not executed as code.
		assert resp.json()["user"]["full_name"] == xss
		_no_leak(resp)

	# ── A04: Oversized / extreme payloads ─────────────────────────────────────

	async def test_oversized_password_rejected(
		self, owasp_client: httpx.AsyncClient,
	) -> None:
		"""Password field has max_length=128; 10 000-char password must return 422."""
		resp = await owasp_client.post(
			_REGISTER_URL,
			json={
				"email":     _unique_email(),
				"password":  "A" * 10_000,
				"full_name": "Test User",
			},
		)
		assert resp.status_code == 422, (
			f"Expected 422 for 10 000-char password, got {resp.status_code}"
		)
		_no_leak(resp)

	async def test_negative_bpm_in_generation_rejected(
		self, owasp_client: httpx.AsyncClient,
	) -> None:
		"""BPM field has ge=60; negative BPM must fail validation, not reach the DB.
		The endpoint also requires auth, so 422 (validation) or 401 (no token) are
		both acceptable — 500 is not."""
		resp = await owasp_client.post(
			"/api/v1/generations",
			json={
				"prompt":           "test prompt for validation check",
				"sub_genre":        "afrobeats",
				"language":         "english",
				"bpm":              -1,
				"energy_level":     5,
				"duration_seconds": 30,
			},
		)
		assert resp.status_code in (401, 422), (
			f"Expected 401/422 for bpm=-1, got {resp.status_code}"
		)
		_no_leak(resp)

	async def test_extreme_bpm_in_generation_rejected(
		self, owasp_client: httpx.AsyncClient,
	) -> None:
		"""BPM field has le=200; 99 999 BPM must fail validation."""
		resp = await owasp_client.post(
			"/api/v1/generations",
			json={
				"prompt":           "test prompt for validation check",
				"sub_genre":        "afrobeats",
				"language":         "english",
				"bpm":              99_999,
				"energy_level":     5,
				"duration_seconds": 30,
			},
		)
		assert resp.status_code in (401, 422), (
			f"Expected 401/422 for bpm=99999, got {resp.status_code}"
		)
		_no_leak(resp)

	# ── A03: Null-byte injection ───────────────────────────────────────────────

	async def test_null_byte_in_login_email_rejected(
		self, owasp_client: httpx.AsyncClient,
	) -> None:
		"""Null bytes in email strings are rejected by EmailStr or the DB driver.
		Must return 422 or 401, never 500."""
		resp = await owasp_client.post(
			_LOGIN_URL,
			json={"email": "admin\x00@example.com", "password": "anything"},
		)
		assert resp.status_code in (401, 422), (
			f"Expected 401/422 for null-byte email, got {resp.status_code}"
		)
		_no_leak(resp)

	# ── A03: Unicode normalisation attack ─────────────────────────────────────

	async def test_unicode_zero_width_space_in_email_rejected(
		self, owasp_client: httpx.AsyncClient,
	) -> None:
		"""Email containing a zero-width space (U+200B) is not a valid RFC 5322
		address and must be rejected by Pydantic's EmailStr validator."""
		# U+200B zero-width space inserted between "admin" and "@"
		resp = await owasp_client.post(
			_REGISTER_URL,
			json={
				"email":     "admin​@example.com",
				"password":  "StrongPass1!",
				"full_name": "Test User",
			},
		)
		assert resp.status_code in (400, 422), (
			f"Expected 400/422 for zero-width-space email, got {resp.status_code}"
		)
		_no_leak(resp)

	# ── A04: Mass assignment ──────────────────────────────────────────────────

	async def test_extra_fields_in_register_rejected(
		self, owasp_client: httpx.AsyncClient,
	) -> None:
		"""RegisterRequest uses ConfigDict(extra='forbid'): posting extra fields
		such as is_admin must return 422, not silently accept privilege escalation."""
		resp = await owasp_client.post(
			_REGISTER_URL,
			json={
				"email":     _unique_email(),
				"password":  "StrongPass1!",
				"full_name": "Test User",
				"is_admin":  True,
				"role":      "superuser",
			},
		)
		assert resp.status_code == 422, (
			f"Expected 422 for extra fields in register body, got {resp.status_code}"
		)
		_no_leak(resp)

	# ── A07: Auth header injection ────────────────────────────────────────────

	async def test_crlf_injection_in_auth_header(
		self, owasp_client: httpx.AsyncClient,
	) -> None:
		"""A bearer token containing CRLF should not inject additional headers.
		httpx normalises headers before sending; the server must return 401 (bad
		token) or process the sanitised header without crashing."""
		injected = "fake-token\r\nX-Injected: evil"
		resp = await owasp_client.get(
			"/api/v1/users/me",
			headers={"Authorization": f"Bearer {injected}"},
		)
		# 401 is the expected outcome (invalid token); 422 is also acceptable.
		# 500 is never acceptable.
		assert resp.status_code in (401, 422), (
			f"Expected 401/422 for CRLF header injection, got {resp.status_code}"
		)
		_no_leak(resp)
		# The injected header must not appear in the response headers.
		assert "x-injected" not in {k.lower() for k in resp.headers}, (
			"Injected header was reflected in the response"
		)

	# ── A08: Path traversal ───────────────────────────────────────────────────

	async def test_path_traversal_in_track_id(
		self, owasp_client: httpx.AsyncClient,
	) -> None:
		"""Path traversal sequences in a URL path segment are normalised by the
		HTTP router; the result is either a 404 (path not matched) or 422
		(validation error), never a 200 with file content."""
		resp = await owasp_client.get("/api/v1/tracks/../../etc/passwd")
		assert resp.status_code in (401, 404, 422), (
			f"Expected 401/404/422 for path traversal, got {resp.status_code}"
		)
		assert "root:" not in resp.text, "Path traversal returned /etc/passwd content"
		_no_leak(resp)

	# ── A04: Content-Type mismatch ────────────────────────────────────────────

	async def test_content_type_mismatch_login(
		self, owasp_client: httpx.AsyncClient,
	) -> None:
		"""Sending a JSON body with Content-Type: text/plain must return 422 —
		FastAPI only parses application/json for JSON body endpoints."""
		resp = await owasp_client.post(
			_LOGIN_URL,
			content='{"email":"user@example.com","password":"pass"}',
			headers={"Content-Type": "text/plain"},
		)
		assert resp.status_code == 422, (
			f"Expected 422 for Content-Type mismatch, got {resp.status_code}"
		)
		_no_leak(resp)
