from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Literal

import httpx
import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict

from gbedu_api.config import API_VERSION, get_settings
from gbedu_api.deps import get_ml_client, get_redis

log = structlog.get_logger(__name__)

router = APIRouter(tags=["health"])

# Component-check timeout in seconds — must be low enough that the endpoint
# returns before any upstream proxy's own timeout.
_COMPONENT_TIMEOUT = 2.0


class HealthResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")

	status: str
	service: str
	version: str
	timestamp: str


class ReadinessCheck(BaseModel):
	model_config = ConfigDict(extra="forbid")

	status: str
	checks: dict[str, str]
	timestamp: str


# ── Detailed health models ─────────────────────────────────────────────────────

ComponentStatus = Literal["ok", "degraded", "down"]
OverallStatus = Literal["healthy", "degraded", "critical"]


class ComponentHealth(BaseModel):
	model_config = ConfigDict(extra="forbid")

	status: ComponentStatus
	latency_ms: float | None = None
	detail: str | None = None


class DetailedHealthResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")

	status: OverallStatus
	components: dict[str, ComponentHealth]
	# Features that are unavailable because a non-critical component is down.
	degraded_features: list[str]
	# Features that are unavailable because a critical component is down.
	critical_features: list[str]
	timestamp: str


@router.get(
	"/health",
	response_model=HealthResponse,
	status_code=status.HTTP_200_OK,
	summary="Liveness check",
)
async def health() -> HealthResponse:
	return HealthResponse(
		status="ok",
		service="gbedu-api",
		version=API_VERSION,
		timestamp=datetime.now(timezone.utc).isoformat(),
	)


@router.get(
	"/ready",
	response_model=ReadinessCheck,
	status_code=status.HTTP_200_OK,
	summary="Readiness check — verifies DB, Redis, ML service",
)
async def ready(
	redis=Depends(get_redis),
	ml_client=Depends(get_ml_client),
) -> ReadinessCheck:
	from fastapi import HTTPException

	checks: dict[str, str] = {}
	all_ok = True

	# Database — reuse the already-initialised engine from the lifespan
	try:
		from gbedu_core.db import _session_factory
		if _session_factory is None:
			raise RuntimeError("session factory not initialised")
		from sqlalchemy import text
		async with _session_factory() as session:
			import time
			t0 = time.perf_counter()
			await session.execute(text("SELECT 1"))
			latency_ms = (time.perf_counter() - t0) * 1000
		checks["database"] = f"ok ({latency_ms:.1f}ms)"
	except Exception as exc:
		checks["database"] = f"error: {exc}"
		all_ok = False

	# Redis
	try:
		await redis.ping()
		checks["redis"] = "ok"
	except Exception as exc:
		checks["redis"] = f"error: {exc}"
		all_ok = False

	# ML service
	try:
		ml_healthy = await ml_client.get_health()
		checks["ml_service"] = "ok" if ml_healthy else "degraded"
		if not ml_healthy:
			all_ok = False
	except Exception as exc:
		checks["ml_service"] = f"error: {exc}"
		all_ok = False

	resp = ReadinessCheck(
		status="ok" if all_ok else "degraded",
		checks=checks,
		timestamp=datetime.now(timezone.utc).isoformat(),
	)

	if not all_ok:
		raise HTTPException(
			status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
			detail=resp.model_dump(),
		)

	return resp


# ── Detailed health endpoint ───────────────────────────────────────────────────

def _check_db_pool() -> ComponentHealth:
	"""Read pool statistics synchronously — no I/O, safe to call anywhere."""
	try:
		from gbedu_core.db import _engine, get_pool_status
		if _engine is None:
			return ComponentHealth(status="down", detail="engine not initialised")
		stats = get_pool_status(_engine)
		utilization = stats["checked_out"] / max(stats["pool_size"], 1)
		status: ComponentStatus = "ok"
		if utilization >= 0.9:
			status = "degraded"
		detail = (
			f"size={stats['pool_size']} in={stats['checked_in']} "
			f"out={stats['checked_out']} overflow={stats['overflow']} "
			f"invalid={stats['invalid']}"
		)
		return ComponentHealth(status=status, detail=detail)
	except Exception as exc:
		return ComponentHealth(status="down", detail=str(exc))


async def _check_database() -> ComponentHealth:
	"""Probe the DB with SELECT 1, timeout after _COMPONENT_TIMEOUT seconds."""
	try:
		from gbedu_core.db import _session_factory
		from sqlalchemy import text

		if _session_factory is None:
			return ComponentHealth(status="down", detail="session factory not initialised")

		t0 = time.perf_counter()
		async with asyncio.timeout(_COMPONENT_TIMEOUT):
			async with _session_factory() as session:
				await session.execute(text("SELECT 1"))
		latency_ms = (time.perf_counter() - t0) * 1000
		return ComponentHealth(status="ok", latency_ms=round(latency_ms, 2))
	except TimeoutError:
		return ComponentHealth(status="down", detail="timed out")
	except Exception as exc:
		return ComponentHealth(status="down", detail=str(exc))


async def _check_redis(redis) -> ComponentHealth:
	"""Ping Redis, timeout after _COMPONENT_TIMEOUT seconds."""
	try:
		t0 = time.perf_counter()
		async with asyncio.timeout(_COMPONENT_TIMEOUT):
			await redis.ping()
		latency_ms = (time.perf_counter() - t0) * 1000
		return ComponentHealth(status="ok", latency_ms=round(latency_ms, 2))
	except TimeoutError:
		return ComponentHealth(status="down", detail="timed out")
	except Exception as exc:
		return ComponentHealth(status="down", detail=str(exc))


async def _check_ml_service(ml_client) -> ComponentHealth:
	"""GET /health on the ML service with a 2 s timeout.

	ML is non-critical: generation pipeline falls back to queuing when ML is
	unreachable, so we mark it degraded rather than down.
	"""
	try:
		t0 = time.perf_counter()
		async with asyncio.timeout(_COMPONENT_TIMEOUT):
			healthy = await ml_client.get_health()
		latency_ms = (time.perf_counter() - t0) * 1000
		if healthy:
			return ComponentHealth(status="ok", latency_ms=round(latency_ms, 2))
		return ComponentHealth(status="degraded", latency_ms=round(latency_ms, 2), detail="unhealthy response")
	except TimeoutError:
		return ComponentHealth(status="degraded", detail="timed out — marked degraded, not critical")
	except Exception as exc:
		return ComponentHealth(status="degraded", detail=str(exc))


async def _check_storage() -> ComponentHealth:
	"""Verify the storage client singleton is initialised.

	A lightweight check — we don't do a live S3/R2 HEAD request here to avoid
	latency; the startup probe already validates connectivity.
	"""
	try:
		from gbedu_api.deps import get_storage
		_ = await get_storage()
		return ComponentHealth(status="ok")
	except Exception as exc:
		return ComponentHealth(status="degraded", detail=str(exc))


@router.get(
	"/health/detailed",
	response_model=DetailedHealthResponse,
	summary="Detailed health — per-component status with graceful degradation",
)
async def detailed_health(
	redis=Depends(get_redis),
	ml_client=Depends(get_ml_client),
) -> DetailedHealthResponse:
	"""Return a per-component health snapshot.

	* ``healthy``  — all components up.
	* ``degraded`` — some non-critical components (ML, storage) are down;
	  core generation still works.
	* ``critical`` — DB or Redis is down; generation is impossible.

	Each component check is capped at 2 s. All four checks run concurrently.
	"""
	(db_health, redis_health, ml_health, storage_health), pool_health = await asyncio.gather(
		asyncio.gather(
			_check_database(),
			_check_redis(redis),
			_check_ml_service(ml_client),
			_check_storage(),
		),
		asyncio.get_event_loop().run_in_executor(None, _check_db_pool),
	)

	components: dict[str, ComponentHealth] = {
		"database": db_health,
		"db_pool": pool_health,
		"redis": redis_health,
		"ml_service": ml_health,
		"storage": storage_health,
	}

	# Critical path: both DB and Redis must be up for any generation to work.
	critical_down = db_health.status == "down" or redis_health.status == "down"

	# Non-critical degradation
	ml_degraded = ml_health.status in ("degraded", "down")
	storage_degraded = storage_health.status in ("degraded", "down")
	pool_degraded = pool_health.status in ("degraded", "down")

	degraded_features: list[str] = []
	critical_features: list[str] = []

	if ml_degraded:
		degraded_features.extend(["voice_models", "real_time_generation"])
	if storage_degraded:
		degraded_features.append("marketplace")
	if pool_degraded:
		degraded_features.append("db_throughput")

	if critical_down:
		critical_features.extend(["generation", "authentication", "payments"])

	if critical_down:
		overall: OverallStatus = "critical"
	elif ml_degraded or storage_degraded or pool_degraded:
		overall = "degraded"
	else:
		overall = "healthy"

	log.info(
		"health.detailed",
		overall=overall,
		db=db_health.status,
		db_pool=pool_health.status,
		redis=redis_health.status,
		ml=ml_health.status,
		storage=storage_health.status,
	)

	return DetailedHealthResponse(
		status=overall,
		components=components,
		degraded_features=degraded_features,
		critical_features=critical_features,
		timestamp=datetime.now(timezone.utc).isoformat(),
	)
