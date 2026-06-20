#!/usr/bin/env python3
"""Production smoke test — verifies all critical API paths are reachable and functional.

Exit 0: all checks passed.
Exit 1: one or more checks failed.

Usage:
    uv run python scripts/smoke_test.py
    uv run python scripts/smoke_test.py --base-url https://api.gbedu.io
    uv run python scripts/smoke_test.py --base-url http://localhost:8000 --timeout 10
"""
from __future__ import annotations

import argparse
import random
import string
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

# ── Configuration ──────────────────────────────────────────────────────────────

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT = 15.0


# ── Result tracking ────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
	name: str
	passed: bool
	latency_ms: float
	detail: str = ""

	def __str__(self) -> str:
		icon = "✓" if self.passed else "✗"
		suffix = f"  [{self.detail}]" if self.detail else ""
		return f"  {icon} {self.name:<50} {self.latency_ms:>7.1f}ms{suffix}"


@dataclass
class SmokeTestReport:
	results: list[CheckResult] = field(default_factory=list)

	def add(self, result: CheckResult) -> None:
		self.results.append(result)
		print(result)

	@property
	def failed(self) -> list[CheckResult]:
		return [r for r in self.results if not r.passed]

	@property
	def passed_count(self) -> int:
		return sum(1 for r in self.results if r.passed)

	def summary(self) -> str:
		total = len(self.results)
		passed = self.passed_count
		failed = total - passed
		avg_ms = sum(r.latency_ms for r in self.results) / max(total, 1)
		lines = [
			"",
			f"  {'─' * 60}",
			f"  Passed: {passed}/{total}   Failed: {failed}   Avg: {avg_ms:.0f}ms",
		]
		if self.failed:
			lines.append("  Failed checks:")
			for r in self.failed:
				lines.append(f"    • {r.name}: {r.detail}")
		return "\n".join(lines)


# ── HTTP helpers ───────────────────────────────────────────────────────────────

class SmokeTester:
	def __init__(self, base_url: str, timeout: float) -> None:
		self._base = base_url.rstrip("/")
		self._client = httpx.Client(timeout=timeout)
		self._report = SmokeTestReport()
		self._access_token: str | None = None
		self._test_user_id: str | None = None

	def _url(self, path: str) -> str:
		return f"{self._base}{path}"

	def _auth_headers(self) -> dict[str, str]:
		assert self._access_token, "no access token — login must run first"
		return {"Authorization": f"Bearer {self._access_token}"}

	def _timed_request(
		self,
		method: str,
		path: str,
		*,
		expected_status: int | list[int],
		**kwargs: Any,
	) -> tuple[httpx.Response | None, float]:
		url = self._url(path)
		t0 = time.perf_counter()
		try:
			resp = self._client.request(method, url, **kwargs)
			latency_ms = (time.perf_counter() - t0) * 1000
			return resp, latency_ms
		except Exception as exc:
			latency_ms = (time.perf_counter() - t0) * 1000
			return None, latency_ms

	def check(
		self,
		name: str,
		method: str,
		path: str,
		*,
		expected_status: int | list[int] = 200,
		extract: str | None = None,
		**kwargs: Any,
	) -> Any:
		"""Run one HTTP check, record result, optionally extract a response field."""
		if isinstance(expected_status, int):
			expected_status = [expected_status]

		t0 = time.perf_counter()
		try:
			resp = self._client.request(method, self._url(path), **kwargs)
			latency_ms = (time.perf_counter() - t0) * 1000
		except Exception as exc:
			latency_ms = (time.perf_counter() - t0) * 1000
			self._report.add(CheckResult(name, False, latency_ms, f"request error: {exc}"))
			return None

		if resp.status_code not in expected_status:
			try:
				body = resp.json()
			except Exception:
				body = resp.text[:200]
			self._report.add(CheckResult(
				name, False, latency_ms,
				f"HTTP {resp.status_code} (expected {expected_status}): {body}",
			))
			return None

		self._report.add(CheckResult(name, True, latency_ms))

		if extract:
			try:
				return resp.json()[extract]
			except Exception:
				return None
		return resp

	def run(self) -> SmokeTestReport:
		print(f"\n  Gbẹdu API smoke test → {self._base}\n")
		print(f"  {'Check':<50} {'Latency':>10}")
		print(f"  {'─' * 60}")

		self._check_health()
		self._check_auth()
		self._check_marketplace()
		self._check_generation()
		self._check_profile()
		self._check_detailed_health()

		print(self._report.summary())
		return self._report

	# ── Check groups ─────────────────────────────────────────────────────────

	def _check_health(self) -> None:
		self.check("GET /health (liveness)", "GET", "/health")
		self.check("GET /ready (readiness)", "GET", "/ready")

	def _check_auth(self) -> None:
		rand = "".join(random.choices(string.ascii_lowercase, k=8))
		email = f"smoke_{rand}@test.gbedu.io"
		password = "SmokeTest123!"
		full_name = "Smoke Tester"

		# Register
		resp = self.check(
			"POST /api/v1/auth/register",
			"POST",
			"/api/v1/auth/register",
			expected_status=201,
			json={"email": email, "password": password, "full_name": full_name},
		)
		if resp is not None:
			data = resp.json()
			self._access_token = data.get("tokens", {}).get("access_token")
			self._test_user_id = data.get("user", {}).get("id")

		# Login (fresh token)
		resp = self.check(
			"POST /api/v1/auth/login",
			"POST",
			"/api/v1/auth/login",
			json={"email": email, "password": password},
		)
		if resp is not None:
			self._access_token = resp.json().get("access_token", self._access_token)

		# Refresh
		if resp is not None:
			refresh_token = resp.json().get("refresh_token")
			if refresh_token:
				self.check(
					"POST /api/v1/auth/refresh",
					"POST",
					"/api/v1/auth/refresh",
					json={"refresh_token": refresh_token},
				)

	def _check_marketplace(self) -> None:
		self.check(
			"GET /api/v1/marketplace/browse (unauthenticated)",
			"GET",
			"/api/v1/marketplace/browse",
		)
		self.check(
			"GET /api/v1/marketplace/browse?sub_genre=afrobeats",
			"GET",
			"/api/v1/marketplace/browse",
			params={"sub_genre": "afrobeats"},
		)
		self.check(
			"GET /api/v1/marketplace/browse?sub_genre=amapiano_cross",
			"GET",
			"/api/v1/marketplace/browse",
			params={"sub_genre": "amapiano_cross"},
		)

	def _check_generation(self) -> None:
		if not self._access_token:
			self._report.add(CheckResult(
				"POST /api/v1/generations/ (skip — no token)", False, 0.0,
				"skipped: auth failed",
			))
			return

		resp = self.check(
			"POST /api/v1/generations/ (queue job)",
			"POST",
			"/api/v1/generations/",
			expected_status=[201, 202],
			headers=self._auth_headers(),
			json={
				"title": "Smoke Test Track",
				"genre": "afrobeats",
				"sub_genre": "afrobeats",
				"bpm": 100,
				"duration_seconds": 15,
				"prompt": "energetic afrobeats with talking drum and guitar",
				"language": "english",
			},
		)
		if resp is not None:
			job_id = resp.json().get("id") or resp.json().get("job_id")
			if job_id:
				self.check(
					f"GET /api/v1/generations/{job_id[:8]}… (status poll)",
					"GET",
					f"/api/v1/generations/{job_id}",
					expected_status=[200, 202],
					headers=self._auth_headers(),
				)

	def _check_profile(self) -> None:
		if not self._access_token:
			return
		self.check(
			"GET /api/v1/users/me",
			"GET",
			"/api/v1/users/me",
			headers=self._auth_headers(),
		)

	def _check_detailed_health(self) -> None:
		resp = self.check(
			"GET /health/detailed",
			"GET",
			"/health/detailed",
		)
		if resp is not None:
			data = resp.json()
			overall = data.get("status", "unknown")
			if overall == "critical":
				# Re-record as failed with detail
				self._report.results[-1] = CheckResult(
					"GET /health/detailed",
					False,
					self._report.results[-1].latency_ms,
					f"overall={overall} critical_features={data.get('critical_features')}",
				)


# ── Entry point ────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
	p = argparse.ArgumentParser(description="Gbẹdu API smoke test")
	p.add_argument("--base-url", default=DEFAULT_BASE_URL)
	p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
	return p.parse_args()


def main() -> int:
	args = _parse_args()
	tester = SmokeTester(base_url=args.base_url, timeout=args.timeout)
	report = tester.run()
	return 0 if not report.failed else 1


if __name__ == "__main__":
	sys.exit(main())
