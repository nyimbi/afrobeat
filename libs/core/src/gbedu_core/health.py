from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from importlib import import_module
from typing import Any, cast

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

log = structlog.get_logger(__name__)


def _empty_details() -> dict[str, Any]:
	return {}


class HealthState(StrEnum):
	healthy = "healthy"
	degraded = "degraded"
	unhealthy = "unhealthy"


@dataclass
class HealthStatus:
	name: str
	state: HealthState
	latency_ms: float
	details: dict[str, Any] = field(default_factory=_empty_details)
	error: str | None = None

	@property
	def is_healthy(self) -> bool:
		return self.state == HealthState.healthy


@dataclass
class AggregateHealth:
	checks: list[HealthStatus]

	@property
	def state(self) -> HealthState:
		states = {c.state for c in self.checks}
		if HealthState.unhealthy in states:
			return HealthState.unhealthy
		if HealthState.degraded in states:
			return HealthState.degraded
		return HealthState.healthy

	@property
	def is_ready(self) -> bool:
		"""Service is ready when all critical checks pass."""
		return all(c.is_healthy for c in self.checks)

	def to_dict(self) -> dict[str, Any]:
		return {
			"status": self.state.value,
			"ready": self.is_ready,
			"checks": [
				{
					"name": c.name,
					"status": c.state.value,
					"latency_ms": round(c.latency_ms, 2),
					"details": c.details,
					**({"error": c.error} if c.error else {}),
				}
				for c in self.checks
			],
		}


async def check_database(engine: AsyncEngine) -> HealthStatus:
	start = time.perf_counter()
	try:
		from sqlalchemy import text

		async with engine.connect() as conn:
			await conn.execute(text("SELECT 1"))
		latency_ms = (time.perf_counter() - start) * 1000
		return HealthStatus(
			name="database",
			state=HealthState.healthy,
			latency_ms=latency_ms,
			details={"dialect": engine.dialect.name},
		)
	except Exception as exc:
		latency_ms = (time.perf_counter() - start) * 1000
		log.warning("database health check failed", error=str(exc))
		return HealthStatus(
			name="database",
			state=HealthState.unhealthy,
			latency_ms=latency_ms,
			error=str(exc),
		)


async def check_redis(redis_url: str) -> HealthStatus:
	start = time.perf_counter()
	try:
		import redis.asyncio as aioredis

		client = cast(Any, aioredis).from_url(redis_url, socket_connect_timeout=2)
		pong = await client.ping()
		await client.aclose()
		latency_ms = (time.perf_counter() - start) * 1000
		return HealthStatus(
			name="redis",
			state=HealthState.healthy if pong else HealthState.degraded,
			latency_ms=latency_ms,
			details={"url": _redact_url(redis_url)},
		)
	except Exception as exc:
		latency_ms = (time.perf_counter() - start) * 1000
		log.warning("redis health check failed", error=str(exc))
		return HealthStatus(
			name="redis",
			state=HealthState.unhealthy,
			latency_ms=latency_ms,
			error=str(exc),
		)


async def check_ml_service(ml_url: str, api_key: str) -> HealthStatus:
	start = time.perf_counter()
	try:
		import httpx

		async with httpx.AsyncClient(timeout=5.0) as client:
			resp = await client.get(
				f"{ml_url}/health",
				headers={"X-API-Key": api_key},
			)
			resp.raise_for_status()
		latency_ms = (time.perf_counter() - start) * 1000
		return HealthStatus(
			name="ml_service",
			state=HealthState.healthy,
			latency_ms=latency_ms,
			details={"url": ml_url, "status_code": resp.status_code},
		)
	except Exception as exc:
		latency_ms = (time.perf_counter() - start) * 1000
		log.warning("ml service health check failed", error=str(exc))
		return HealthStatus(
			name="ml_service",
			state=HealthState.unhealthy,
			latency_ms=latency_ms,
			error=str(exc),
		)


async def check_storage(
	r2_endpoint: str, bucket: str, access_key: str, secret_key: str
) -> HealthStatus:
	start = time.perf_counter()
	try:
		aioboto3 = cast(Any, import_module("aioboto3"))

		session = aioboto3.Session()
		async with session.client(
			"s3",
			endpoint_url=r2_endpoint,
			aws_access_key_id=access_key,
			aws_secret_access_key=secret_key,
		) as s3:
			await s3.head_bucket(Bucket=bucket)
		latency_ms = (time.perf_counter() - start) * 1000
		return HealthStatus(
			name="storage",
			state=HealthState.healthy,
			latency_ms=latency_ms,
			details={"bucket": bucket},
		)
	except Exception as exc:
		latency_ms = (time.perf_counter() - start) * 1000
		log.warning("storage health check failed", error=str(exc))
		return HealthStatus(
			name="storage",
			state=HealthState.unhealthy,
			latency_ms=latency_ms,
			error=str(exc),
		)


def _redact_url(url: str) -> str:
	"""Remove password from Redis/DB URLs before logging."""
	from urllib.parse import urlparse, urlunparse

	try:
		parsed = urlparse(url)
		if parsed.password:
			netloc = parsed.hostname or ""
			if parsed.port:
				netloc = f"{netloc}:{parsed.port}"
			if parsed.username:
				netloc = f"{parsed.username}:***@{netloc}"
			replaced = parsed._replace(netloc=netloc)
			return urlunparse(replaced)
	except Exception:
		pass
	return url
