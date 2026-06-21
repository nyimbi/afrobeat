from __future__ import annotations

"""Unit tests for gbedu_api.routers.health — full route coverage.

Strategy:
- TestClient(app) without lifespan (skip_lifespan not needed; lifespan is
  bypassed automatically when TestClient is used without the context-manager
  form — i.e. no `with TestClient(...)`).
- Dependency overrides on app.dependency_overrides for get_redis / get_ml_client.
- gbedu_core internals (_session_factory, _engine, get_pool_status) patched
  via unittest.mock.patch so no real DB/Redis/GPU is required.
- All tests are plain functions (sync) except where async helpers are called
  directly — asyncio_mode = "auto" handles async def test_* automatically.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from gbedu_api import deps
from gbedu_api.main import app

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_redis(ping_ok: bool = True) -> AsyncMock:
	r = AsyncMock()
	if ping_ok:
		r.ping = AsyncMock(return_value=True)
	else:
		r.ping = AsyncMock(side_effect=ConnectionError("redis unreachable"))
	return r


def _make_ml_client(healthy: bool = True, raises: Exception | None = None) -> AsyncMock:
	ml = AsyncMock()
	if raises is not None:
		ml.get_health = AsyncMock(side_effect=raises)
	else:
		ml.get_health = AsyncMock(return_value=healthy)
	return ml


@pytest.fixture(autouse=True)
def clear_overrides():
	"""Remove all dependency overrides after every test."""
	yield
	app.dependency_overrides.clear()


def _client() -> TestClient:
	return TestClient(app, raise_server_exceptions=False)


# ── /api/v1/health ─────────────────────────────────────────────────────────────


def test_health_returns_200() -> None:
	client = _client()
	resp = client.get("/api/v1/health")
	assert resp.status_code == 200


def test_health_response_schema() -> None:
	client = _client()
	resp = client.get("/api/v1/health")
	body = resp.json()
	assert body["status"] == "ok"
	assert body["service"] == "gbedu-api"
	assert "version" in body
	assert "timestamp" in body


def test_health_timestamp_is_iso_format() -> None:
	from datetime import datetime

	client = _client()
	resp = client.get("/api/v1/health")
	ts = resp.json()["timestamp"]
	# Should parse without raising
	dt = datetime.fromisoformat(ts)
	assert dt.tzinfo is not None


# ── /api/v1/ready — all OK ─────────────────────────────────────────────────────


def _mock_session_factory_ok():
	"""Return a callable async-context-manager factory (i.e. the function itself, not a called instance).

	_check_database and /ready both do: `async with _session_factory() as session`
	so the patch value must be a callable, not an already-entered context manager.
	"""
	mock_session = AsyncMock()
	mock_session.execute = AsyncMock()

	@asynccontextmanager
	async def _factory():
		yield mock_session

	return _factory  # Return the function, not _factory()


def test_ready_all_ok() -> None:
	fake_redis = _make_redis(ping_ok=True)
	fake_ml = _make_ml_client(healthy=True)

	app.dependency_overrides[deps.get_redis] = lambda: fake_redis
	app.dependency_overrides[deps.get_ml_client] = lambda: fake_ml

	with (
		patch("gbedu_api.routers.health._session_factory", _mock_session_factory_ok(), create=True),
		patch("gbedu_core.db._session_factory", _mock_session_factory_ok()),
	):
		client = _client()
		resp = client.get("/api/v1/ready")

	assert resp.status_code == 200
	body = resp.json()
	assert body["status"] == "ok"
	assert "database" in body["checks"]
	assert "redis" in body["checks"]
	assert "ml_service" in body["checks"]
	assert "timestamp" in body


def test_ready_redis_check_ok_value() -> None:
	fake_redis = _make_redis(ping_ok=True)
	fake_ml = _make_ml_client(healthy=True)

	app.dependency_overrides[deps.get_redis] = lambda: fake_redis
	app.dependency_overrides[deps.get_ml_client] = lambda: fake_ml

	with patch("gbedu_core.db._session_factory", _mock_session_factory_ok()):
		resp = _client().get("/api/v1/ready")

	body = resp.json()
	assert body["checks"]["redis"] == "ok"


# ── /api/v1/ready — individual failures ────────────────────────────────────────


def test_ready_db_failure_returns_503() -> None:
	fake_redis = _make_redis(ping_ok=True)
	fake_ml = _make_ml_client(healthy=True)

	app.dependency_overrides[deps.get_redis] = lambda: fake_redis
	app.dependency_overrides[deps.get_ml_client] = lambda: fake_ml

	# Simulate session factory not initialised
	with patch("gbedu_core.db._session_factory", None):
		resp = _client().get("/api/v1/ready")

	assert resp.status_code == 503
	body = resp.json()
	# FastAPI wraps HTTPException detail as-is
	detail = body.get("detail", body)
	if isinstance(detail, dict):
		assert detail["status"] == "degraded"
		assert "database" in detail["checks"]


def test_ready_redis_failure_returns_503() -> None:
	fake_redis = _make_redis(ping_ok=False)
	fake_ml = _make_ml_client(healthy=True)

	app.dependency_overrides[deps.get_redis] = lambda: fake_redis
	app.dependency_overrides[deps.get_ml_client] = lambda: fake_ml

	with patch("gbedu_core.db._session_factory", _mock_session_factory_ok()):
		resp = _client().get("/api/v1/ready")

	assert resp.status_code == 503
	detail = resp.json().get("detail", resp.json())
	if isinstance(detail, dict):
		assert "redis" in detail["checks"]
		assert "error" in detail["checks"]["redis"]


def test_ready_ml_unhealthy_returns_503() -> None:
	"""ML service returning False marks ml_service as degraded → all_ok=False → 503."""
	fake_redis = _make_redis(ping_ok=True)
	fake_ml = _make_ml_client(healthy=False)

	app.dependency_overrides[deps.get_redis] = lambda: fake_redis
	app.dependency_overrides[deps.get_ml_client] = lambda: fake_ml

	with patch("gbedu_core.db._session_factory", _mock_session_factory_ok()):
		resp = _client().get("/api/v1/ready")

	assert resp.status_code == 503
	detail = resp.json().get("detail", resp.json())
	if isinstance(detail, dict):
		assert detail["checks"]["ml_service"] == "degraded"


def test_ready_ml_exception_returns_503() -> None:
	fake_redis = _make_redis(ping_ok=True)
	fake_ml = _make_ml_client(raises=RuntimeError("ml timeout"))

	app.dependency_overrides[deps.get_redis] = lambda: fake_redis
	app.dependency_overrides[deps.get_ml_client] = lambda: fake_ml

	with patch("gbedu_core.db._session_factory", _mock_session_factory_ok()):
		resp = _client().get("/api/v1/ready")

	assert resp.status_code == 503
	detail = resp.json().get("detail", resp.json())
	if isinstance(detail, dict):
		assert "error" in detail["checks"]["ml_service"]


def test_ready_db_execute_raises_returns_503() -> None:
	"""Database session execute raising an exception marks DB as error."""
	mock_session = AsyncMock()
	mock_session.execute = AsyncMock(side_effect=Exception("query failed"))

	@asynccontextmanager
	async def _bad_factory():
		yield mock_session

	fake_redis = _make_redis(ping_ok=True)
	fake_ml = _make_ml_client(healthy=True)

	app.dependency_overrides[deps.get_redis] = lambda: fake_redis
	app.dependency_overrides[deps.get_ml_client] = lambda: fake_ml

	with patch("gbedu_core.db._session_factory", _bad_factory()):
		resp = _client().get("/api/v1/ready")

	assert resp.status_code == 503
	detail = resp.json().get("detail", resp.json())
	if isinstance(detail, dict):
		assert "error" in detail["checks"]["database"]


# ── /api/v1/metrics ────────────────────────────────────────────────────────────


def test_metrics_returns_200() -> None:
	with patch("gbedu_api.routers.health._update_prometheus_gauges"):
		resp = _client().get("/api/v1/metrics")
	assert resp.status_code == 200


def test_metrics_content_type_is_prometheus() -> None:
	with patch("gbedu_api.routers.health._update_prometheus_gauges"):
		resp = _client().get("/api/v1/metrics")
	assert "text/plain" in resp.headers["content-type"]


def test_metrics_body_contains_gauge_names() -> None:
	with patch("gbedu_api.routers.health._update_prometheus_gauges"):
		resp = _client().get("/api/v1/metrics")
	body = resp.text
	# prometheus_client always includes process metrics in the default registry
	assert len(body) > 0


# ── /api/v1/health/detailed — healthy baseline ────────────────────────────────


def _patch_detailed_healthy(fake_redis, fake_ml):
	"""Context patches for a fully healthy detailed health response.

	Pass _good_factory (the callable) not _good_factory() (an already-entered
	context manager). The health code does `async with _session_factory() as …`
	so it needs a callable it can invoke each time.
	"""
	mock_session = AsyncMock()
	mock_session.execute = AsyncMock()

	@asynccontextmanager
	async def _good_factory():
		yield mock_session

	mock_engine = MagicMock()
	pool_stats = {
		"pool_size": 10,
		"checked_in": 9,
		"checked_out": 1,
		"overflow": 0,
		"invalid": 0,
	}

	return (
		patch("gbedu_core.db._session_factory", _good_factory),
		patch("gbedu_core.db._engine", mock_engine),
		patch("gbedu_core.db.get_pool_status", return_value=pool_stats),
		patch("gbedu_api.deps.get_storage", new=AsyncMock(return_value=MagicMock())),
	)


def test_detailed_health_all_healthy() -> None:
	fake_redis = _make_redis(ping_ok=True)
	fake_ml = _make_ml_client(healthy=True)

	app.dependency_overrides[deps.get_redis] = lambda: fake_redis
	app.dependency_overrides[deps.get_ml_client] = lambda: fake_ml

	patches = _patch_detailed_healthy(fake_redis, fake_ml)
	with patches[0], patches[1], patches[2], patches[3]:
		resp = _client().get("/api/v1/health/detailed")

	assert resp.status_code == 200
	body = resp.json()
	assert body["status"] == "healthy"
	assert body["degraded_features"] == []
	assert body["critical_features"] == []
	assert "timestamp" in body


def test_detailed_health_component_keys_present() -> None:
	fake_redis = _make_redis(ping_ok=True)
	fake_ml = _make_ml_client(healthy=True)

	app.dependency_overrides[deps.get_redis] = lambda: fake_redis
	app.dependency_overrides[deps.get_ml_client] = lambda: fake_ml

	patches = _patch_detailed_healthy(fake_redis, fake_ml)
	with patches[0], patches[1], patches[2], patches[3]:
		resp = _client().get("/api/v1/health/detailed")

	components = resp.json()["components"]
	for key in ("database", "db_pool", "redis", "ml_service", "storage"):
		assert key in components, f"missing component: {key}"


def test_detailed_health_component_status_values() -> None:
	fake_redis = _make_redis(ping_ok=True)
	fake_ml = _make_ml_client(healthy=True)

	app.dependency_overrides[deps.get_redis] = lambda: fake_redis
	app.dependency_overrides[deps.get_ml_client] = lambda: fake_ml

	patches = _patch_detailed_healthy(fake_redis, fake_ml)
	with patches[0], patches[1], patches[2], patches[3]:
		resp = _client().get("/api/v1/health/detailed")

	components = resp.json()["components"]
	valid_statuses = {"ok", "degraded", "down"}
	for name, comp in components.items():
		assert comp["status"] in valid_statuses, f"{name} has invalid status: {comp['status']}"


# ── /api/v1/health/detailed — degraded paths ──────────────────────────────────


def test_detailed_health_ml_degraded() -> None:
	"""ML returning False → ml_service=degraded → overall=degraded, voice_models degraded."""
	fake_redis = _make_redis(ping_ok=True)
	fake_ml = _make_ml_client(healthy=False)

	app.dependency_overrides[deps.get_redis] = lambda: fake_redis
	app.dependency_overrides[deps.get_ml_client] = lambda: fake_ml

	patches = _patch_detailed_healthy(fake_redis, fake_ml)
	with patches[0], patches[1], patches[2], patches[3]:
		resp = _client().get("/api/v1/health/detailed")

	assert resp.status_code == 200
	body = resp.json()
	assert body["status"] == "degraded"
	assert "voice_models" in body["degraded_features"]
	assert "real_time_generation" in body["degraded_features"]
	assert body["critical_features"] == []


def test_detailed_health_ml_exception_marks_degraded() -> None:
	fake_redis = _make_redis(ping_ok=True)
	fake_ml = _make_ml_client(raises=RuntimeError("connection refused"))

	app.dependency_overrides[deps.get_redis] = lambda: fake_redis
	app.dependency_overrides[deps.get_ml_client] = lambda: fake_ml

	patches = _patch_detailed_healthy(fake_redis, fake_ml)
	with patches[0], patches[1], patches[2], patches[3]:
		resp = _client().get("/api/v1/health/detailed")

	body = resp.json()
	assert body["status"] == "degraded"
	assert body["components"]["ml_service"]["status"] == "degraded"


def test_detailed_health_storage_degraded_features() -> None:
	"""Storage failure adds 'marketplace' to degraded_features."""
	fake_redis = _make_redis(ping_ok=True)
	fake_ml = _make_ml_client(healthy=True)

	app.dependency_overrides[deps.get_redis] = lambda: fake_redis
	app.dependency_overrides[deps.get_ml_client] = lambda: fake_ml

	mock_session = AsyncMock()
	mock_session.execute = AsyncMock()

	@asynccontextmanager
	async def _good_factory():
		yield mock_session

	mock_engine = MagicMock()
	pool_stats = {"pool_size": 10, "checked_in": 9, "checked_out": 1, "overflow": 0, "invalid": 0}

	with (
		patch("gbedu_core.db._session_factory", _good_factory),
		patch("gbedu_core.db._engine", mock_engine),
		patch("gbedu_core.db.get_pool_status", return_value=pool_stats),
		patch(
			"gbedu_api.deps.get_storage", new=AsyncMock(side_effect=RuntimeError("storage down"))
		),
	):
		resp = _client().get("/api/v1/health/detailed")

	body = resp.json()
	assert body["status"] == "degraded"
	assert "marketplace" in body["degraded_features"]


def test_detailed_health_db_pool_degraded_adds_db_throughput() -> None:
	"""Pool utilisation >= 90% → db_pool=degraded → 'db_throughput' in degraded_features."""
	fake_redis = _make_redis(ping_ok=True)
	fake_ml = _make_ml_client(healthy=True)

	app.dependency_overrides[deps.get_redis] = lambda: fake_redis
	app.dependency_overrides[deps.get_ml_client] = lambda: fake_ml

	mock_session = AsyncMock()
	mock_session.execute = AsyncMock()

	@asynccontextmanager
	async def _good_factory():
		yield mock_session

	mock_engine = MagicMock()
	# 10/10 checked out → utilisation = 1.0 → degraded
	high_util_stats = {
		"pool_size": 10,
		"checked_in": 0,
		"checked_out": 10,
		"overflow": 0,
		"invalid": 0,
	}

	with (
		patch("gbedu_core.db._session_factory", _good_factory),
		patch("gbedu_core.db._engine", mock_engine),
		patch("gbedu_core.db.get_pool_status", return_value=high_util_stats),
		patch("gbedu_api.deps.get_storage", new=AsyncMock(return_value=MagicMock())),
	):
		resp = _client().get("/api/v1/health/detailed")

	body = resp.json()
	assert body["status"] == "degraded"
	assert "db_throughput" in body["degraded_features"]


# ── /api/v1/health/detailed — critical path ───────────────────────────────────


def test_detailed_health_redis_down_is_critical() -> None:
	fake_redis = _make_redis(ping_ok=False)
	fake_ml = _make_ml_client(healthy=True)

	app.dependency_overrides[deps.get_redis] = lambda: fake_redis
	app.dependency_overrides[deps.get_ml_client] = lambda: fake_ml

	patches = _patch_detailed_healthy(fake_redis, fake_ml)
	with patches[0], patches[1], patches[2], patches[3]:
		resp = _client().get("/api/v1/health/detailed")

	body = resp.json()
	assert body["status"] == "critical"
	assert body["components"]["redis"]["status"] == "down"
	assert "generation" in body["critical_features"]
	assert "authentication" in body["critical_features"]
	assert "payments" in body["critical_features"]


def test_detailed_health_db_down_is_critical() -> None:
	fake_redis = _make_redis(ping_ok=True)
	fake_ml = _make_ml_client(healthy=True)

	app.dependency_overrides[deps.get_redis] = lambda: fake_redis
	app.dependency_overrides[deps.get_ml_client] = lambda: fake_ml

	with (
		patch("gbedu_core.db._session_factory", None),
		patch("gbedu_core.db._engine", None),
		patch("gbedu_core.db.get_pool_status", return_value={}),
		patch("gbedu_api.deps.get_storage", new=AsyncMock(return_value=MagicMock())),
	):
		resp = _client().get("/api/v1/health/detailed")

	body = resp.json()
	assert body["status"] == "critical"
	assert body["components"]["database"]["status"] == "down"
	assert "generation" in body["critical_features"]


def test_detailed_health_both_db_and_redis_down_critical() -> None:
	fake_redis = _make_redis(ping_ok=False)
	fake_ml = _make_ml_client(healthy=True)

	app.dependency_overrides[deps.get_redis] = lambda: fake_redis
	app.dependency_overrides[deps.get_ml_client] = lambda: fake_ml

	with (
		patch("gbedu_core.db._session_factory", None),
		patch("gbedu_core.db._engine", None),
		patch("gbedu_core.db.get_pool_status", return_value={}),
		patch("gbedu_api.deps.get_storage", new=AsyncMock(return_value=MagicMock())),
	):
		resp = _client().get("/api/v1/health/detailed")

	body = resp.json()
	assert body["status"] == "critical"
	assert len(body["critical_features"]) >= 3


# ── _check_db_pool unit tests (sync helper, called via run_in_executor) ────────


def test_check_db_pool_ok() -> None:
	from gbedu_api.routers.health import _check_db_pool

	mock_engine = MagicMock()
	stats = {"pool_size": 10, "checked_in": 8, "checked_out": 2, "overflow": 0, "invalid": 0}

	with (
		patch("gbedu_core.db._engine", mock_engine),
		patch("gbedu_core.db.get_pool_status", return_value=stats),
	):
		result = _check_db_pool()

	assert result.status == "ok"
	assert result.detail is not None
	assert "size=10" in result.detail


def test_check_db_pool_degraded_at_high_utilisation() -> None:
	from gbedu_api.routers.health import _check_db_pool

	mock_engine = MagicMock()
	# 9/10 → utilisation = 0.9 → exactly at threshold → degraded
	stats = {"pool_size": 10, "checked_in": 1, "checked_out": 9, "overflow": 0, "invalid": 0}

	with (
		patch("gbedu_core.db._engine", mock_engine),
		patch("gbedu_core.db.get_pool_status", return_value=stats),
	):
		result = _check_db_pool()

	assert result.status == "degraded"


def test_check_db_pool_down_when_engine_none() -> None:
	from gbedu_api.routers.health import _check_db_pool

	with patch("gbedu_core.db._engine", None):
		result = _check_db_pool()

	assert result.status == "down"
	assert "engine not initialised" in (result.detail or "")


def test_check_db_pool_down_on_exception() -> None:
	from gbedu_api.routers.health import _check_db_pool

	mock_engine = MagicMock()
	with (
		patch("gbedu_core.db._engine", mock_engine),
		patch("gbedu_core.db.get_pool_status", side_effect=RuntimeError("pool error")),
	):
		result = _check_db_pool()

	assert result.status == "down"
	assert "pool error" in (result.detail or "")


# ── _check_database async unit tests ──────────────────────────────────────────


async def test_check_database_ok() -> None:
	from gbedu_api.routers.health import _check_database

	mock_session = AsyncMock()
	mock_session.execute = AsyncMock()

	@asynccontextmanager
	async def _good_factory():
		yield mock_session

	with patch("gbedu_core.db._session_factory", _good_factory):
		result = await _check_database()

	assert result.status == "ok"
	assert result.latency_ms is not None
	assert result.latency_ms >= 0


async def test_check_database_down_when_factory_none() -> None:
	from gbedu_api.routers.health import _check_database

	with patch("gbedu_core.db._session_factory", None):
		result = await _check_database()

	assert result.status == "down"
	assert "session factory not initialised" in (result.detail or "")


async def test_check_database_down_on_execute_error() -> None:
	from gbedu_api.routers.health import _check_database

	mock_session = AsyncMock()
	mock_session.execute = AsyncMock(side_effect=Exception("connection refused"))

	@asynccontextmanager
	async def _bad_factory():
		yield mock_session

	with patch("gbedu_core.db._session_factory", _bad_factory):
		result = await _check_database()

	assert result.status == "down"
	assert "connection refused" in (result.detail or "")


# ── _check_redis async unit tests ─────────────────────────────────────────────


async def test_check_redis_ok() -> None:
	from gbedu_api.routers.health import _check_redis

	fake_redis = _make_redis(ping_ok=True)
	result = await _check_redis(fake_redis)

	assert result.status == "ok"
	assert result.latency_ms is not None


async def test_check_redis_down_on_ping_failure() -> None:
	from gbedu_api.routers.health import _check_redis

	fake_redis = _make_redis(ping_ok=False)
	result = await _check_redis(fake_redis)

	assert result.status == "down"
	assert result.detail is not None


# ── _check_ml_service async unit tests ────────────────────────────────────────


async def test_check_ml_service_ok() -> None:
	from gbedu_api.routers.health import _check_ml_service

	fake_ml = _make_ml_client(healthy=True)
	result = await _check_ml_service(fake_ml)

	assert result.status == "ok"
	assert result.latency_ms is not None


async def test_check_ml_service_degraded_when_unhealthy_response() -> None:
	from gbedu_api.routers.health import _check_ml_service

	fake_ml = _make_ml_client(healthy=False)
	result = await _check_ml_service(fake_ml)

	assert result.status == "degraded"
	assert result.detail == "unhealthy response"


async def test_check_ml_service_degraded_on_exception() -> None:
	from gbedu_api.routers.health import _check_ml_service

	fake_ml = _make_ml_client(raises=RuntimeError("ml service crashed"))
	result = await _check_ml_service(fake_ml)

	# ML errors are always degraded, never down
	assert result.status == "degraded"
	assert "ml service crashed" in (result.detail or "")


# ── _check_storage async unit tests ───────────────────────────────────────────


async def test_check_storage_ok() -> None:
	from gbedu_api.routers.health import _check_storage

	with patch("gbedu_api.deps.get_storage", new=AsyncMock(return_value=MagicMock())):
		result = await _check_storage()

	assert result.status == "ok"
	assert result.detail is None


async def test_check_storage_degraded_on_exception() -> None:
	from gbedu_api.routers.health import _check_storage

	with patch(
		"gbedu_api.deps.get_storage",
		new=AsyncMock(side_effect=AssertionError("StorageClient not initialised")),
	):
		result = await _check_storage()

	assert result.status == "degraded"
	assert "StorageClient not initialised" in (result.detail or "")


# ── _update_prometheus_gauges unit tests ──────────────────────────────────────


def test_update_prometheus_gauges_cpu_only() -> None:
	"""Runs without raising on CPU-only host (torch.cuda.is_available → False)."""
	from gbedu_api.routers.health import _update_prometheus_gauges

	mock_torch = MagicMock()
	mock_torch.cuda.is_available.return_value = False

	mock_sync_redis = MagicMock()
	mock_redis_instance = MagicMock()
	mock_redis_instance.llen.return_value = 5
	mock_sync_redis.from_url.return_value = mock_redis_instance

	with (
		patch("gbedu_core.db._engine", None),
		patch("gbedu_api.routers.health.torch", mock_torch, create=True),
		patch("redis.from_url", mock_sync_redis.from_url),
	):
		# Must not raise
		_update_prometheus_gauges("redis://localhost:6379/0")


def test_update_prometheus_gauges_with_gpu() -> None:
	from gbedu_api.routers.health import (
		_update_prometheus_gauges,
	)

	mock_torch = MagicMock()
	mock_torch.cuda.is_available.return_value = True
	mock_torch.cuda.memory_reserved.return_value = 1024**3
	props = MagicMock()
	props.total_memory = 16 * 1024**3
	mock_torch.cuda.get_device_properties.return_value = props

	mock_sync_redis = MagicMock()
	mock_redis_instance = MagicMock()
	mock_redis_instance.llen.return_value = 0
	mock_sync_redis.from_url.return_value = mock_redis_instance

	with (
		patch("gbedu_core.db._engine", None),
		patch("gbedu_api.routers.health.torch", mock_torch, create=True),
		patch("redis.from_url", mock_sync_redis.from_url),
	):
		_update_prometheus_gauges("redis://localhost:6379/0")

	# Gauges should have been set — just verify no exception raised above


def test_update_prometheus_gauges_torch_import_error_is_silent() -> None:
	"""If torch is not installed, the gauge function must not raise."""
	from gbedu_api.routers.health import _update_prometheus_gauges

	mock_sync_redis = MagicMock()
	mock_redis_instance = MagicMock()
	mock_redis_instance.llen.return_value = 3
	mock_sync_redis.from_url.return_value = mock_redis_instance

	with (
		patch("gbedu_core.db._engine", None),
		patch(
			"builtins.__import__",
			side_effect=lambda name, *a, **kw: (
				(_ for _ in ()).throw(ImportError("no torch"))
				if name == "torch"
				else __import__(name, *a, **kw)
			),
		),
		patch("redis.from_url", mock_sync_redis.from_url),
	):
		_update_prometheus_gauges("redis://localhost:6379/0")


def test_update_prometheus_gauges_db_pool_stats() -> None:
	from gbedu_api.routers.health import _update_prometheus_gauges

	mock_engine = MagicMock()
	pool_stats = {"checked_out": 3, "pool_size": 10}

	mock_sync_redis = MagicMock()
	mock_redis_instance = MagicMock()
	mock_redis_instance.llen.return_value = 0
	mock_sync_redis.from_url.return_value = mock_redis_instance

	mock_torch = MagicMock()
	mock_torch.cuda.is_available.return_value = False

	with (
		patch("gbedu_core.db._engine", mock_engine),
		patch("gbedu_core.db.get_pool_status", return_value=pool_stats),
		patch("gbedu_api.routers.health.torch", mock_torch, create=True),
		patch("redis.from_url", mock_sync_redis.from_url),
	):
		_update_prometheus_gauges("redis://localhost:6379/0")


def test_update_prometheus_gauges_redis_error_is_silent() -> None:
	"""Sync Redis errors in gauge update must be swallowed silently."""
	from gbedu_api.routers.health import _update_prometheus_gauges

	mock_torch = MagicMock()
	mock_torch.cuda.is_available.return_value = False

	with (
		patch("gbedu_core.db._engine", None),
		patch("gbedu_api.routers.health.torch", mock_torch, create=True),
		patch("redis.from_url", side_effect=Exception("redis connect failed")),
	):
		# Must not raise
		_update_prometheus_gauges("redis://localhost:6379/0")
