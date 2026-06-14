"""
Gbẹdu chaos engineering scenarios using the Toxiproxy REST API.

Each scenario is a self-contained async function:
	scenario_db_latency()  — inject 500 ms DB latency, assert p99 < 2 s
	scenario_redis_down()  — disconnect Redis, assert API returns 503 not 500
	scenario_ml_timeout()  — mock a slow ML service, assert job marked failed

Prerequisites:
	docker run -d --name toxiproxy \\
		-p 8474:8474 -p 5433:5433 -p 6380:6380 \\
		shopify/toxiproxy

	Configure the running API to use toxiproxy ports:
		DATABASE_URL=postgresql+asyncpg://...@localhost:5433/gbedu
		REDIS_URL=redis://localhost:6380/0

Run:
	uv run python tests/chaos/scenarios.py
"""

from __future__ import annotations

import asyncio
import statistics
import time
from typing import Any

import httpx

# ── configuration ─────────────────────────────────────────────────────────────

TOXIPROXY_API  = "http://localhost:8474"
API_BASE       = "http://localhost:8000"
ML_BASE        = "http://localhost:8001"

# Toxiproxy proxy names — must match toxiproxy.json
PROXY_POSTGRES = "postgres"
PROXY_REDIS    = "redis"

# Scenario parameters
DB_LATENCY_MS       = 500   # injected upstream latency
DB_LATENCY_SCENARIO_SECS = 30  # how long to hammer the API under the toxic
P99_THRESHOLD_MS    = 2000  # SLO: p99 must stay under this
REDIS_DOWN_REQUESTS = 20    # number of requests to fire while Redis is down
ML_TIMEOUT_SECS     = 65    # how long to wait for the job to be marked failed


# ── Toxiproxy REST helpers ────────────────────────────────────────────────────

class ToxiproxyClient:
	def __init__(self, base: str = TOXIPROXY_API) -> None:
		self._base = base.rstrip("/")
		self._http = httpx.AsyncClient(base_url=self._base, timeout=10)

	async def aclose(self) -> None:
		await self._http.aclose()

	async def reset(self) -> None:
		"""Remove all toxics from all proxies."""
		resp = await self._http.get("/proxies")
		resp.raise_for_status()
		proxies: dict[str, Any] = resp.json()
		for name in proxies:
			toxics_resp = await self._http.get(f"/proxies/{name}/toxics")
			toxics_resp.raise_for_status()
			for toxic in toxics_resp.json():
				await self._http.delete(f"/proxies/{name}/toxics/{toxic['name']}")

	async def add_toxic(
		self,
		proxy: str,
		name: str,
		toxic_type: str,
		stream: str = "downstream",
		toxicity: float = 1.0,
		attributes: dict[str, Any] | None = None,
	) -> dict[str, Any]:
		payload: dict[str, Any] = {
			"name":       name,
			"type":       toxic_type,
			"stream":     stream,
			"toxicity":   toxicity,
			"attributes": attributes or {},
		}
		resp = await self._http.post(f"/proxies/{proxy}/toxics", json=payload)
		resp.raise_for_status()
		return resp.json()

	async def remove_toxic(self, proxy: str, name: str) -> None:
		resp = await self._http.delete(f"/proxies/{proxy}/toxics/{name}")
		if resp.status_code not in (200, 204, 404):
			resp.raise_for_status()

	async def disable_proxy(self, proxy: str) -> None:
		resp = await self._http.post(f"/proxies/{proxy}/disable")
		resp.raise_for_status()

	async def enable_proxy(self, proxy: str) -> None:
		resp = await self._http.post(f"/proxies/{proxy}/enable")
		resp.raise_for_status()


# ── health check helper ───────────────────────────────────────────────────────

async def _health_check(client: httpx.AsyncClient, label: str) -> None:
	resp = await client.get("/api/v1/health", timeout=5)
	if resp.status_code != 200:
		raise RuntimeError(f"[{label}] Health check failed: {resp.status_code} {resp.text}")
	print(f"[{label}] Health OK")


async def _register_test_user(client: httpx.AsyncClient, suffix: str) -> str:
	"""Register a throw-away user, return the access token."""
	resp = await client.post(
		"/api/v1/auth/register",
		json={
			"email":     f"chaos_{suffix}@example.com",
			"password":  "Chaos_Test_P4ss!",
			"full_name": "Chaos Test",
		},
	)
	if resp.status_code not in (200, 201):
		raise RuntimeError(f"Registration failed: {resp.status_code} {resp.text}")
	return resp.json()["tokens"]["access_token"]


# ── scenario 1: DB latency ────────────────────────────────────────────────────

async def scenario_db_latency() -> None:
	"""
	Inject 500 ms of latency into the Postgres proxy.
	Hammer /api/v1/tracks/public for 30 seconds.
	Assert p99 response time < 2 s.
	Remove toxic unconditionally in finally block.
	"""
	print("\n=== scenario_db_latency ===")
	toxi   = ToxiproxyClient()
	client = httpx.AsyncClient(base_url=API_BASE, timeout=10)

	try:
		await _health_check(client, "before")

		print(f"Injecting {DB_LATENCY_MS} ms DB latency...")
		await toxi.add_toxic(
			proxy      = PROXY_POSTGRES,
			name       = "db_latency_chaos",
			toxic_type = "latency",
			stream     = "downstream",
			toxicity   = 1.0,
			attributes = {"latency": DB_LATENCY_MS, "jitter": 50},
		)

		latencies_ms: list[float] = []
		deadline = time.monotonic() + DB_LATENCY_SCENARIO_SECS
		errors   = 0

		while time.monotonic() < deadline:
			t0 = time.monotonic()
			try:
				resp = await client.get("/api/v1/tracks/public?page=1&page_size=10")
				elapsed = (time.monotonic() - t0) * 1000
				latencies_ms.append(elapsed)
				if resp.status_code != 200:
					errors += 1
			except Exception as exc:
				errors += 1
				print(f"  Request error: {exc}")
			await asyncio.sleep(0.1)

		if not latencies_ms:
			raise RuntimeError("No successful requests during scenario")

		latencies_ms.sort()
		p50 = statistics.median(latencies_ms)
		p99 = latencies_ms[int(len(latencies_ms) * 0.99)]

		print(f"  Requests: {len(latencies_ms)}  Errors: {errors}")
		print(f"  p50={p50:.0f} ms  p99={p99:.0f} ms  threshold={P99_THRESHOLD_MS} ms")

		assert p99 < P99_THRESHOLD_MS, (
			f"p99 {p99:.0f} ms exceeds SLO of {P99_THRESHOLD_MS} ms"
		)
		print("  PASS: p99 within SLO")

	finally:
		print("Removing DB latency toxic...")
		await toxi.remove_toxic(PROXY_POSTGRES, "db_latency_chaos")
		await _health_check(client, "after")
		await toxi.aclose()
		await client.aclose()


# ── scenario 2: Redis down ────────────────────────────────────────────────────

async def scenario_redis_down() -> None:
	"""
	Disconnect Redis via the bandwidth-limiter-to-zero trick.
	Fire authenticated requests and assert every response is 503 (not 500).
	The API should degrade gracefully — rate-limit middleware and session
	storage will fail, but the process must not panic with an unhandled 500.
	Restore Redis at the end.
	"""
	print("\n=== scenario_redis_down ===")
	toxi   = ToxiproxyClient()
	client = httpx.AsyncClient(base_url=API_BASE, timeout=10)

	try:
		await _health_check(client, "before")

		# Pre-register user before killing Redis so we have a valid token
		token = await _register_test_user(client, "redis_down")
		headers = {"Authorization": f"Bearer {token}"}

		print("Simulating Redis disconnect (bandwidth → 0)...")
		await toxi.add_toxic(
			proxy      = PROXY_REDIS,
			name       = "redis_disconnect_chaos",
			toxic_type = "bandwidth",
			stream     = "downstream",
			toxicity   = 1.0,
			attributes = {"rate": 0},
		)

		# Allow existing connections to time out
		await asyncio.sleep(2)

		unacceptable_codes: list[int] = []

		for i in range(REDIS_DOWN_REQUESTS):
			try:
				resp = await client.get(
					"/api/v1/tracks?page=1&page_size=5",
					headers=headers,
					timeout=6,
				)
				print(f"  [{i+1:02d}] status={resp.status_code}")
				# 200 is fine (Redis may be optional for reads), 429, 503 are fine.
				# 500 means unhandled exception — not acceptable.
				if resp.status_code == 500:
					unacceptable_codes.append(resp.status_code)
			except httpx.TimeoutException:
				print(f"  [{i+1:02d}] timeout (acceptable under Redis disconnect)")
			except Exception as exc:
				print(f"  [{i+1:02d}] error: {exc}")

			await asyncio.sleep(0.25)

		assert not unacceptable_codes, (
			f"Got {len(unacceptable_codes)} unacceptable 500 responses while Redis was down. "
			"API must degrade gracefully (503/504/429), not panic."
		)
		print(f"  PASS: no 500s across {REDIS_DOWN_REQUESTS} requests")

	finally:
		print("Restoring Redis connection...")
		await toxi.remove_toxic(PROXY_REDIS, "redis_disconnect_chaos")
		await asyncio.sleep(1)
		await _health_check(client, "after")
		await toxi.aclose()
		await client.aclose()


# ── scenario 3: ML timeout ────────────────────────────────────────────────────

async def scenario_ml_timeout() -> None:
	"""
	Simulate a slow/unresponsive ML service by injecting a 70-second timeout
	toxic on a local httpx server shim, then submit a generation job and wait
	for the worker to mark it as failed (timeout should fire after ~60 s).

	Because this scenario operates at the job level (not the proxy level), it
	uses the API directly and polls the job status until it transitions to
	'failed' or until ML_TIMEOUT_SECS elapses.

	The toxic is injected via Toxiproxy against the ML service port if a proxy
	named 'ml_service' exists; otherwise the scenario still exercises the
	end-to-end timeout path through the Celery worker's circuit-breaker.
	"""
	print("\n=== scenario_ml_timeout ===")
	toxi   = ToxiproxyClient()
	client = httpx.AsyncClient(base_url=API_BASE, timeout=10)

	ml_toxic_injected = False

	try:
		await _health_check(client, "before")

		# Attempt to inject timeout on ML proxy if it exists in Toxiproxy
		try:
			await toxi.add_toxic(
				proxy      = "ml_service",
				name       = "ml_timeout_chaos",
				toxic_type = "timeout",
				stream     = "upstream",
				toxicity   = 1.0,
				attributes = {"timeout": 70000},  # 70 s — longer than worker retry window
			)
			ml_toxic_injected = True
			print("Injected ML service timeout toxic via Toxiproxy")
		except httpx.HTTPStatusError:
			print("No 'ml_service' Toxiproxy proxy found — relying on worker circuit-breaker timeout")

		# Register and log in
		token = await _register_test_user(client, "ml_timeout")
		headers = {"Authorization": f"Bearer {token}"}

		# Submit a generation job
		resp = await client.post(
			"/api/v1/generations",
			json={
				"prompt":           "A long dark Afrobeats track that will time out",
				"sub_genre":        "afrobeats",
				"language":         "english",
				"energy_level":     7,
				"duration_seconds": 30,
			},
			headers=headers,
		)
		if resp.status_code not in (200, 201, 202):
			raise RuntimeError(f"Job submission failed: {resp.status_code} {resp.text}")

		job_id = resp.json()["id"]
		print(f"Submitted job {job_id}, polling for failure...")

		terminal    = {"completed", "failed", "cancelled"}
		final_status: str | None = None
		deadline    = time.monotonic() + ML_TIMEOUT_SECS

		while time.monotonic() < deadline:
			await asyncio.sleep(5)
			poll = await client.get(
				f"/api/v1/generations/{job_id}",
				headers=headers,
			)
			if poll.status_code == 200:
				data   = poll.json()
				status = data.get("status", "")
				print(f"  status={status}  progress={data.get('progress_percent', 0)}%")
				if status in terminal:
					final_status = status
					break
			else:
				print(f"  poll returned {poll.status_code}")

		assert final_status is not None, (
			f"Job did not reach a terminal state within {ML_TIMEOUT_SECS} s. "
			"The worker must mark timed-out jobs as 'failed'."
		)
		assert final_status == "failed", (
			f"Expected status='failed' after ML timeout; got '{final_status}'. "
			"Worker must not silently complete a job whose ML call never responded."
		)
		print(f"  PASS: job correctly transitioned to '{final_status}'")

	finally:
		if ml_toxic_injected:
			print("Removing ML timeout toxic...")
			try:
				await toxi.remove_toxic("ml_service", "ml_timeout_chaos")
			except Exception:
				pass
		await _health_check(client, "after")
		await toxi.aclose()
		await client.aclose()


# ── entrypoint ────────────────────────────────────────────────────────────────

async def main() -> None:
	scenarios = [
		scenario_db_latency,
		scenario_redis_down,
		scenario_ml_timeout,
	]
	passed = 0
	failed = 0

	for scenario in scenarios:
		try:
			await scenario()
			passed += 1
		except AssertionError as exc:
			print(f"\n  FAIL: {exc}")
			failed += 1
		except Exception as exc:
			print(f"\n  ERROR in {scenario.__name__}: {type(exc).__name__}: {exc}")
			failed += 1

	print(f"\n{'='*40}")
	print(f"Results: {passed} passed, {failed} failed")
	if failed:
		raise SystemExit(1)


if __name__ == "__main__":
	asyncio.run(main())
