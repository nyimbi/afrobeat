from __future__ import annotations

"""Unit tests for gbedu_core.health — health dataclasses and aggregation logic."""

from gbedu_core.health import AggregateHealth, HealthState, HealthStatus


def _make(name: str, state: HealthState, latency: float = 1.0) -> HealthStatus:
	return HealthStatus(name=name, state=state, latency_ms=latency)


# ── HealthStatus ──────────────────────────────────────────────────────────────


def test_health_status_is_healthy_true() -> None:
	s = _make("db", HealthState.healthy)
	assert s.is_healthy is True


def test_health_status_is_healthy_false_degraded() -> None:
	s = _make("db", HealthState.degraded)
	assert s.is_healthy is False


def test_health_status_is_healthy_false_unhealthy() -> None:
	s = _make("db", HealthState.unhealthy)
	assert s.is_healthy is False


def test_health_status_error_field() -> None:
	s = HealthStatus(
		name="cache", state=HealthState.unhealthy, latency_ms=0.0, error="connection refused"
	)
	assert s.error == "connection refused"


# ── AggregateHealth.state ─────────────────────────────────────────────────────


def test_aggregate_all_healthy() -> None:
	agg = AggregateHealth(
		checks=[
			_make("db", HealthState.healthy),
			_make("redis", HealthState.healthy),
		]
	)
	assert agg.state == HealthState.healthy


def test_aggregate_one_degraded() -> None:
	agg = AggregateHealth(
		checks=[
			_make("db", HealthState.healthy),
			_make("redis", HealthState.degraded),
		]
	)
	assert agg.state == HealthState.degraded


def test_aggregate_one_unhealthy_overrides_degraded() -> None:
	agg = AggregateHealth(
		checks=[
			_make("db", HealthState.degraded),
			_make("redis", HealthState.unhealthy),
		]
	)
	assert agg.state == HealthState.unhealthy


def test_aggregate_all_unhealthy() -> None:
	agg = AggregateHealth(
		checks=[
			_make("db", HealthState.unhealthy),
			_make("redis", HealthState.unhealthy),
		]
	)
	assert agg.state == HealthState.unhealthy


# ── AggregateHealth.is_ready ──────────────────────────────────────────────────


def test_aggregate_is_ready_all_healthy() -> None:
	agg = AggregateHealth(checks=[_make("db", HealthState.healthy)])
	assert agg.is_ready is True


def test_aggregate_is_ready_false_if_any_degraded() -> None:
	agg = AggregateHealth(
		checks=[
			_make("db", HealthState.healthy),
			_make("redis", HealthState.degraded),
		]
	)
	assert agg.is_ready is False


def test_aggregate_is_ready_false_if_unhealthy() -> None:
	agg = AggregateHealth(checks=[_make("db", HealthState.unhealthy)])
	assert agg.is_ready is False


def test_aggregate_empty_checks_is_ready() -> None:
	agg = AggregateHealth(checks=[])
	assert agg.is_ready is True
	assert agg.state == HealthState.healthy


# ── AggregateHealth.to_dict ───────────────────────────────────────────────────


def test_aggregate_to_dict_structure() -> None:
	agg = AggregateHealth(
		checks=[
			HealthStatus(name="db", state=HealthState.healthy, latency_ms=2.5, details={"pool": 5}),
			HealthStatus(name="redis", state=HealthState.degraded, latency_ms=15.0, error="slow"),
		]
	)
	d = agg.to_dict()
	assert d["status"] == "degraded"
	assert d["ready"] is False
	assert len(d["checks"]) == 2

	db_check = next(c for c in d["checks"] if c["name"] == "db")
	assert db_check["status"] == "healthy"
	assert db_check["latency_ms"] == 2.5
	assert db_check["details"] == {"pool": 5}

	redis_check = next(c for c in d["checks"] if c["name"] == "redis")
	assert redis_check["status"] == "degraded"
	assert redis_check["error"] == "slow"


def test_aggregate_to_dict_omits_none_error() -> None:
	agg = AggregateHealth(checks=[_make("db", HealthState.healthy)])
	d = agg.to_dict()
	check = d["checks"][0]
	assert "error" not in check or check.get("error") is None


# ── HealthState enum ──────────────────────────────────────────────────────────


def test_health_state_values() -> None:
	assert HealthState.healthy == "healthy"
	assert HealthState.degraded == "degraded"
	assert HealthState.unhealthy == "unhealthy"


# ── check_database ────────────────────────────────────────────────────────────


async def test_check_database_healthy() -> None:
	from contextlib import asynccontextmanager
	from unittest.mock import AsyncMock, MagicMock

	from gbedu_core.health import check_database

	mock_conn = AsyncMock()
	mock_conn.execute = AsyncMock()

	@asynccontextmanager
	async def _mock_connect():
		yield mock_conn

	mock_engine = MagicMock()
	mock_engine.connect.return_value = _mock_connect()
	mock_engine.dialect.name = "postgresql"

	result = await check_database(mock_engine)
	assert result.state == HealthState.healthy
	assert result.name == "database"
	assert result.latency_ms >= 0


async def test_check_database_unhealthy_on_error() -> None:
	from contextlib import asynccontextmanager
	from unittest.mock import MagicMock

	from gbedu_core.health import check_database

	@asynccontextmanager
	async def _mock_connect():
		raise ConnectionError("DB unreachable")
		yield  # pragma: no cover

	mock_engine = MagicMock()
	mock_engine.connect.return_value = _mock_connect()

	result = await check_database(mock_engine)
	assert result.state == HealthState.unhealthy
	assert result.error is not None


# ── check_redis ───────────────────────────────────────────────────────────────


async def test_check_redis_healthy() -> None:
	from unittest.mock import AsyncMock, patch

	from gbedu_core.health import check_redis

	mock_client = AsyncMock()
	mock_client.ping.return_value = True
	mock_client.aclose = AsyncMock()

	with patch("redis.asyncio.from_url", return_value=mock_client):
		result = await check_redis("redis://localhost:6379/0")

	assert result.state == HealthState.healthy
	assert result.name == "redis"


async def test_check_redis_unhealthy_on_error() -> None:
	from unittest.mock import patch

	from gbedu_core.health import check_redis

	with patch("redis.asyncio.from_url", side_effect=ConnectionError("refused")):
		result = await check_redis("redis://localhost:6379/0")

	assert result.state == HealthState.unhealthy
	assert "refused" in result.error


# ── check_ml_service ──────────────────────────────────────────────────────────


async def test_check_ml_service_healthy() -> None:
	from unittest.mock import AsyncMock, MagicMock, patch

	from gbedu_core.health import check_ml_service

	mock_resp = MagicMock()
	mock_resp.status_code = 200
	mock_resp.raise_for_status = MagicMock()

	mock_client = AsyncMock()
	mock_client.get = AsyncMock(return_value=mock_resp)
	mock_client.__aenter__ = AsyncMock(return_value=mock_client)
	mock_client.__aexit__ = AsyncMock(return_value=False)

	with patch("httpx.AsyncClient", return_value=mock_client):
		result = await check_ml_service("http://ml:8001", "test-key")

	assert result.state == HealthState.healthy
	assert result.name == "ml_service"


async def test_check_ml_service_unhealthy_on_error() -> None:
	from unittest.mock import AsyncMock, patch

	import httpx
	from gbedu_core.health import check_ml_service

	with patch("httpx.AsyncClient") as mock_cls:
		mock_cls.return_value.__aenter__ = AsyncMock(side_effect=httpx.ConnectError("refused"))
		mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
		result = await check_ml_service("http://ml:8001", "key")

	assert result.state == HealthState.unhealthy


# ── _redact_url ───────────────────────────────────────────────────────────────


def test_redact_url_removes_password() -> None:
	from gbedu_core.health import _redact_url

	# URL with both username and password — function shows user:***@host
	url = "postgresql+asyncpg://myuser:secretpass@db.host:5432/mydb"
	redacted = _redact_url(url)
	assert "secretpass" not in redacted
	assert "***" in redacted


def test_redact_url_no_password_unchanged() -> None:
	from gbedu_core.health import _redact_url

	url = "redis://localhost:6379/0"
	result = _redact_url(url)
	assert "localhost" in result


def test_redact_url_with_username_and_password() -> None:
	from gbedu_core.health import _redact_url

	url = "postgresql+asyncpg://myuser:mypass@db.host:5432/mydb"
	redacted = _redact_url(url)
	assert "mypass" not in redacted
	assert "myuser" in redacted
