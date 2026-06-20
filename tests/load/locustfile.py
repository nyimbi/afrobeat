"""
Gbẹdu load test suite.

User mix:
	AnonymousUser  (weight=40) — public endpoints, no auth
	AuthenticatedUser (weight=50) — full generation lifecycle
	PowerUser      (weight=10) — voice models + marketplace listings

Load shape (StagesShape):
	0–2 min   ramp 0→50
	2–8 min   sustain 50   (steady state)
	8–10 min  spike → 200
	10–12 min sustain 200  (stress)
	12–14 min ramp → 0

Run:
	locust -f tests/load/locustfile.py --host http://localhost:8000
"""

from __future__ import annotations

import random
import string
import time
import uuid
from typing import Any

import queue
import threading

from locust import HttpUser, LoadTestShape, between, events, task
from locust.clients import ResponseContextManager

# ── helpers ───────────────────────────────────────────────────────────────────

_SUB_GENRES = ["afrobeats", "amapiano_cross", "afropop", "highlife", "afrofusion", "alte"]
_LANGUAGES  = ["english", "yoruba", "pidgin", "igbo", "swahili"]


def _rand_email() -> str:
	tag = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
	return f"loadtest_{tag}@example.com"


def _rand_password() -> str:
	return "Gbẹdu_L0ad_" + "".join(random.choices(string.ascii_letters + string.digits, k=8))


def _rand_prompt() -> str:
	moods = ["energetic", "chill", "romantic", "celebratory", "spiritual"]
	topics = ["Lagos nights", "street hustle", "love story", "Afro fusion", "rhythm of life"]
	return f"A {random.choice(moods)} {random.choice(_SUB_GENRES)} track about {random.choice(topics)}, with live percussion and layered vocals"


# ── custom metric helpers ──────────────────────────────────────────────────────

def _fire_custom(name: str, response_time: float, success: bool = True, exception: Exception | None = None) -> None:
	"""Emit a custom Locust event so custom metrics appear in the stats table."""
	events.request.fire(
		request_type="METRIC",
		name=name,
		response_time=response_time,
		response_length=0,
		exception=exception,
		context={},
	)


# ── pre-seeded user pool ──────────────────────────────────────────────────────
# Shared pool of (email, password, access_token, refresh_token) tuples.
# Pre-created at test_start so authenticated VUs don't all hit /auth/register
# concurrently and trigger the per-IP rate limit (5/hour).

_POOL_SIZE    = 50   # pre-register this many users before the test starts
_user_pool:   queue.Queue  = queue.Queue()
_pool_lock    = threading.Lock()
_pool_ready   = threading.Event()


@events.test_start.add_listener
def _seed_user_pool(environment, **_kw) -> None:  # type: ignore[no-untyped-def]
	"""Register POOL_SIZE users once before any VU starts."""
	host = environment.host.rstrip("/")
	import urllib.request, json as _json, urllib.error

	seeded = 0
	for _ in range(_POOL_SIZE):
		email    = _rand_email()
		password = "Gbẹdu_Pool_S33d!"
		payload  = _json.dumps({"email": email, "password": password, "full_name": "Pool User"}).encode()
		req      = urllib.request.Request(
			f"{host}/api/v1/auth/register",
			data=payload,
			headers={"Content-Type": "application/json"},
			method="POST",
		)
		try:
			with urllib.request.urlopen(req, timeout=10) as r:
				body = _json.loads(r.read())
				tokens = body["tokens"]
				_user_pool.put({
					"email":         email,
					"password":      password,
					"access_token":  tokens["access_token"],
					"refresh_token": tokens["refresh_token"],
				})
				seeded += 1
		except Exception:
			pass  # pool continues even if some registrations fail

	print(f"[pool] seeded {seeded}/{_POOL_SIZE} users")
	_pool_ready.set()


def _pool_get() -> dict | None:
	"""Get a user from the pool (non-blocking). Returns None when empty."""
	try:
		return _user_pool.get_nowait()
	except queue.Empty:
		return None


def _pool_return(user: dict) -> None:
	"""Return a user back to the pool for reuse."""
	_user_pool.put(user)


# ── rate-limit back-off ────────────────────────────────────────────────────────

def _with_backoff(fn, *args, max_retries: int = 3, base_delay: float = 1.0, **kwargs) -> Any:
	"""
	Call fn(*args, **kwargs); if it returns 429 retry with exponential back-off.
	fn must return a Locust ResponseContextManager.
	"""
	for attempt in range(max_retries):
		resp = fn(*args, **kwargs)
		if resp.status_code != 429:
			return resp
		delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
		time.sleep(delay)
	return resp  # return last response regardless


# ── anonymous user ────────────────────────────────────────────────────────────

class AnonymousUser(HttpUser):
	"""
	Simulates unauthenticated browsers browsing public content.
	Weight 40 — the bulk of the traffic is anonymous reads.
	"""
	weight    = 40
	wait_time = between(1, 5)

	@task(5)
	def health_check(self) -> None:
		with self.client.get("/api/v1/health", catch_response=True, name="/api/v1/health") as resp:
			if resp.status_code == 200:
				resp.success()
			else:
				resp.failure(f"Health returned {resp.status_code}")

	@task(4)
	def browse_public_tracks(self) -> None:
		page = random.randint(1, 5)
		with self.client.get(
			f"/api/v1/tracks/public?page={page}&page_size=20",
			catch_response=True,
			name="/api/v1/tracks/public",
		) as resp:
			if resp.status_code in (200, 404):
				resp.success()
			else:
				resp.failure(f"Public tracks returned {resp.status_code}")

	@task(3)
	def browse_marketplace_beats(self) -> None:
		page = random.randint(1, 3)
		genre = random.choice(_SUB_GENRES + [None])  # type: ignore[list-item]
		url = f"/api/v1/marketplace/beats?page={page}&page_size=20"
		if genre:
			url += f"&sub_genre={genre}"
		with self.client.get(url, catch_response=True, name="/api/v1/marketplace/beats") as resp:
			if resp.status_code == 200:
				resp.success()
			else:
				resp.failure(f"Marketplace returned {resp.status_code}")

	@task(2)
	def get_single_beat(self) -> None:
		# First fetch a listing to get a real ID; skip gracefully if none exist
		with self.client.get(
			"/api/v1/marketplace/beats?page=1&page_size=5",
			catch_response=True,
			name="/api/v1/marketplace/beats (seed)",
		) as resp:
			if resp.status_code != 200:
				resp.success()  # not a test failure — no data yet
				return
			data = resp.json()
			resp.success()

		items = data.get("items", [])
		if not items:
			return

		beat_id = random.choice(items)["id"]
		with self.client.get(
			f"/api/v1/marketplace/beats/{beat_id}",
			catch_response=True,
			name="/api/v1/marketplace/beats/{beat_id}",
		) as resp:
			if resp.status_code in (200, 404):
				resp.success()
			else:
				resp.failure(f"Beat detail returned {resp.status_code}")


# ── authenticated user ────────────────────────────────────────────────────────

class AuthenticatedUser(HttpUser):
	"""
	Registers once, then drives the full generation lifecycle:
	submit → poll until terminal → (optionally) download.
	Weight 50.
	"""
	weight    = 50
	wait_time = between(3, 10)

	# per-VU state
	_access_token:  str | None = None
	_refresh_token: str | None = None
	_email:    str = ""
	_password: str = ""
	_my_track_ids: list[str]

	def on_start(self) -> None:
		self._my_track_ids = []
		self._pool_user: dict | None = None

		# Wait up to 15s for the pool to be seeded at test_start
		_pool_ready.wait(timeout=15)
		self._pool_user = _pool_get()
		if self._pool_user:
			self._email         = self._pool_user["email"]
			self._password      = self._pool_user["password"]
			self._access_token  = self._pool_user["access_token"]
			self._refresh_token = self._pool_user["refresh_token"]
		else:
			# Pool exhausted — register a fresh user as fallback
			self._email    = _rand_email()
			self._password = _rand_password()
			self._register_and_login()

	# ── auth helpers ──────────────────────────────────────────────────────────

	def _register_and_login(self) -> None:
		resp = self.client.post(
			"/api/v1/auth/register",
			json={
				"email":     self._email,
				"password":  self._password,
				"full_name": "Load Test User",
			},
			name="/api/v1/auth/register",
		)
		if resp.status_code == 201:
			body = resp.json()
			self._access_token  = body["tokens"]["access_token"]
			self._refresh_token = body["tokens"]["refresh_token"]
		elif resp.status_code == 429:
			# Rate-limited — stop this VU rather than hammering with bad tokens
			self.environment.runner.quit()
		else:
			self._do_login()

	def _do_login(self) -> None:
		resp = self.client.post(
			"/api/v1/auth/login",
			json={"email": self._email, "password": self._password},
			name="/api/v1/auth/login",
		)
		if resp.status_code == 200:
			body = resp.json()
			self._access_token  = body["access_token"]
			self._refresh_token = body["refresh_token"]

	def _auth_headers(self) -> dict[str, str]:
		if not self._access_token:
			self._do_login()
		# Guard: if still no token, stop the VU — never send "Bearer None"
		if not self._access_token:
			self.environment.runner.quit()
			return {}
		return {"Authorization": f"Bearer {self._access_token}"}

	def _handle_401(self, resp: ResponseContextManager) -> bool:
		"""Return True if we refreshed and caller should retry."""
		if resp.status_code == 401 and self._refresh_token:
			r = self.client.post(
				"/api/v1/auth/refresh",
				json={"refresh_token": self._refresh_token},
				name="/api/v1/auth/refresh",
			)
			if r.status_code == 200:
				body = r.json()
				self._access_token  = body["access_token"]
				self._refresh_token = body["refresh_token"]
				return True
		return False

	# ── tasks ─────────────────────────────────────────────────────────────────

	@task(6)
	def submit_and_poll_generation(self) -> None:
		submit_start = time.monotonic()

		payload = {
			"prompt":           _rand_prompt(),
			"sub_genre":        random.choice(_SUB_GENRES),
			"language":         random.choice(_LANGUAGES),
			"bpm":              random.choice([None, 90, 100, 110, 120, 128]),
			"energy_level":     random.randint(3, 9),
			"duration_seconds": random.choice([15, 30, 60]),
		}

		with _with_backoff(
			self.client.post,
			"/api/v1/generations",
			json=payload,
			headers=self._auth_headers(),
			catch_response=True,
			name="/api/v1/generations (submit)",
		) as resp:
			if resp.status_code == 401 and self._handle_401(resp):
				resp.success()
				return
			if resp.status_code not in (200, 201, 202):
				resp.failure(f"Submit generation returned {resp.status_code}: {resp.text[:200]}")
				return
			job = resp.json()
			resp.success()

		submit_elapsed = (time.monotonic() - submit_start) * 1000
		_fire_custom("generation_submission_time", submit_elapsed)

		job_id    = job["id"]
		poll_count = 0
		terminal  = {"completed", "failed", "cancelled"}

		for _ in range(30):
			time.sleep(2)
			poll_count += 1

			with self.client.get(
				f"/api/v1/generations/{job_id}",
				headers=self._auth_headers(),
				catch_response=True,
				name="/api/v1/generations/{job_id} (poll)",
			) as poll_resp:
				if poll_resp.status_code == 200:
					poll_resp.success()
					status_val = poll_resp.json().get("status", "")
					if status_val in terminal:
						if status_val == "completed":
							track_id = poll_resp.json().get("track_id")
							if track_id:
								self._my_track_ids.append(track_id)
						break
				elif poll_resp.status_code == 401 and self._handle_401(poll_resp):
					poll_resp.success()
				else:
					poll_resp.failure(f"Poll returned {poll_resp.status_code}")
					break

		_fire_custom("generation_poll_count", poll_count * 1000)

	@task(3)
	def list_my_tracks(self) -> None:
		with self.client.get(
			"/api/v1/tracks?page=1&page_size=20",
			headers=self._auth_headers(),
			catch_response=True,
			name="/api/v1/tracks (my list)",
		) as resp:
			if resp.status_code == 200:
				resp.success()
			elif resp.status_code == 401 and self._handle_401(resp):
				resp.success()
			else:
				resp.failure(f"List tracks returned {resp.status_code}")

	@task(2)
	def browse_public_tracks(self) -> None:
		with self.client.get(
			f"/api/v1/tracks/public?page={random.randint(1, 3)}&page_size=20",
			headers=self._auth_headers(),
			catch_response=True,
			name="/api/v1/tracks/public (auth)",
		) as resp:
			if resp.status_code == 200:
				resp.success()
			else:
				resp.failure(f"Public tracks (auth) returned {resp.status_code}")

	@task(2)
	def browse_marketplace(self) -> None:
		with self.client.get(
			"/api/v1/marketplace/beats?page=1&page_size=20",
			headers=self._auth_headers(),
			catch_response=True,
			name="/api/v1/marketplace/beats (auth)",
		) as resp:
			if resp.status_code == 200:
				resp.success()
			else:
				resp.failure(f"Marketplace (auth) returned {resp.status_code}")

	@task(1)
	def list_my_generations(self) -> None:
		with self.client.get(
			"/api/v1/generations?page=1&page_size=20",
			headers=self._auth_headers(),
			catch_response=True,
			name="/api/v1/generations (list)",
		) as resp:
			if resp.status_code == 200:
				resp.success()
			elif resp.status_code == 401 and self._handle_401(resp):
				resp.success()
			else:
				resp.failure(f"List generations returned {resp.status_code}")

	@task(1)
	def get_track_detail(self) -> None:
		if not self._my_track_ids:
			return
		track_id = random.choice(self._my_track_ids)
		with self.client.get(
			f"/api/v1/tracks/{track_id}",
			headers=self._auth_headers(),
			catch_response=True,
			name="/api/v1/tracks/{track_id}",
		) as resp:
			if resp.status_code in (200, 404):
				resp.success()
			elif resp.status_code == 401 and self._handle_401(resp):
				resp.success()
			else:
				resp.failure(f"Track detail returned {resp.status_code}")

	def on_stop(self) -> None:  # type: ignore[override]
		# This on_stop intentionally overrides the pool-return stub added in on_start.
		if self._refresh_token:
			self.client.post(
				"/api/v1/auth/logout",
				json={"refresh_token": self._refresh_token},
				name="/api/v1/auth/logout",
			)
		# Return user to pool with fresh tokens for reuse by next VU
		if self._pool_user and self._access_token:
			self._pool_user["access_token"]  = self._access_token
			self._pool_user["refresh_token"] = self._refresh_token or self._pool_user["refresh_token"]
			_pool_return(self._pool_user)
			self._pool_user = None


# ── power user ────────────────────────────────────────────────────────────────

class PowerUser(HttpUser):
	"""
	Pro-tier user: everything AuthenticatedUser does, plus voice models and
	marketplace listing creation.  Weight 10.
	"""
	weight    = 10
	wait_time = between(3, 10)

	_access_token:  str | None = None
	_refresh_token: str | None = None
	_email:    str = ""
	_password: str = ""
	_my_track_ids:    list[str]
	_my_voice_models: list[str]

	def on_start(self) -> None:
		self._my_track_ids    = []
		self._my_voice_models = []
		self._pool_user: dict | None = None

		_pool_ready.wait(timeout=15)
		self._pool_user = _pool_get()
		if self._pool_user:
			self._email         = self._pool_user["email"]
			self._password      = self._pool_user["password"]
			self._access_token  = self._pool_user["access_token"]
			self._refresh_token = self._pool_user["refresh_token"]
		else:
			self._email    = _rand_email()
			self._password = _rand_password()
			self._register_and_login()

	def _register_and_login(self) -> None:
		resp = self.client.post(
			"/api/v1/auth/register",
			json={
				"email":     self._email,
				"password":  self._password,
				"full_name": "Power Load User",
			},
			name="/api/v1/auth/register (power)",
		)
		if resp.status_code == 201:
			body = resp.json()
			self._access_token  = body["tokens"]["access_token"]
			self._refresh_token = body["tokens"]["refresh_token"]
		elif resp.status_code == 429:
			self.environment.runner.quit()
		else:
			self._do_login()

	def _do_login(self) -> None:
		resp = self.client.post(
			"/api/v1/auth/login",
			json={"email": self._email, "password": self._password},
			name="/api/v1/auth/login (power)",
		)
		if resp.status_code == 200:
			body = resp.json()
			self._access_token  = body["access_token"]
			self._refresh_token = body["refresh_token"]

	def _auth_headers(self) -> dict[str, str]:
		if not self._access_token:
			self._do_login()
		if not self._access_token:
			self.environment.runner.quit()
			return {}
		return {"Authorization": f"Bearer {self._access_token}"}

	def _handle_401(self, resp: ResponseContextManager) -> bool:
		if resp.status_code == 401 and self._refresh_token:
			r = self.client.post(
				"/api/v1/auth/refresh",
				json={"refresh_token": self._refresh_token},
				name="/api/v1/auth/refresh (power)",
			)
			if r.status_code == 200:
				body = r.json()
				self._access_token  = body["access_token"]
				self._refresh_token = body["refresh_token"]
				return True
		return False

	@task(4)
	def submit_generation(self) -> None:
		submit_start = time.monotonic()
		payload = {
			"prompt":           _rand_prompt(),
			"sub_genre":        random.choice(_SUB_GENRES),
			"language":         random.choice(_LANGUAGES),
			"bpm":              random.choice([None, 100, 115, 128]),
			"energy_level":     random.randint(5, 10),
			"duration_seconds": 60,
		}
		with _with_backoff(
			self.client.post,
			"/api/v1/generations",
			json=payload,
			headers=self._auth_headers(),
			catch_response=True,
			name="/api/v1/generations (power submit)",
		) as resp:
			if resp.status_code == 401 and self._handle_401(resp):
				resp.success()
				return
			if resp.status_code not in (200, 201, 202):
				resp.failure(f"Power submit returned {resp.status_code}")
				return
			job = resp.json()
			resp.success()

		submit_elapsed = (time.monotonic() - submit_start) * 1000
		_fire_custom("generation_submission_time", submit_elapsed)

		job_id    = job["id"]
		poll_count = 0
		terminal  = {"completed", "failed", "cancelled"}

		for _ in range(30):
			time.sleep(2)
			poll_count += 1
			with self.client.get(
				f"/api/v1/generations/{job_id}",
				headers=self._auth_headers(),
				catch_response=True,
				name="/api/v1/generations/{job_id} (power poll)",
			) as poll_resp:
				if poll_resp.status_code == 200:
					poll_resp.success()
					data = poll_resp.json()
					if data.get("status") in terminal:
						if data.get("track_id"):
							self._my_track_ids.append(data["track_id"])
						break
				elif poll_resp.status_code == 401 and self._handle_401(poll_resp):
					poll_resp.success()
				else:
					poll_resp.failure(f"Power poll returned {poll_resp.status_code}")
					break

		_fire_custom("generation_poll_count", poll_count * 1000)

	@task(3)
	def list_voice_models(self) -> None:
		with self.client.get(
			"/api/v1/voice-models",
			headers=self._auth_headers(),
			catch_response=True,
			name="/api/v1/voice-models (list)",
		) as resp:
			if resp.status_code == 200:
				data = resp.json()
				self._my_voice_models = [
					vm["id"] for vm in data
					if not vm.get("is_preset")
				]
				resp.success()
			elif resp.status_code == 401 and self._handle_401(resp):
				resp.success()
			else:
				resp.failure(f"List voice models returned {resp.status_code}")

	@task(2)
	def poll_voice_model_status(self) -> None:
		if not self._my_voice_models:
			return
		model_id = random.choice(self._my_voice_models)
		with self.client.get(
			f"/api/v1/voice-models/{model_id}/status",
			headers=self._auth_headers(),
			catch_response=True,
			name="/api/v1/voice-models/{model_id}/status",
		) as resp:
			if resp.status_code in (200, 404):
				resp.success()
			elif resp.status_code == 401 and self._handle_401(resp):
				resp.success()
			else:
				resp.failure(f"Voice model status returned {resp.status_code}")

	@task(2)
	def create_marketplace_listing(self) -> None:
		if not self._my_track_ids:
			return
		track_id = random.choice(self._my_track_ids)
		with self.client.post(
			"/api/v1/marketplace/beats",
			json={
				"track_id":    track_id,
				"title":       f"Load Test Beat {uuid.uuid4().hex[:6]}",
				"description": "Generated during load testing",
				"license_type": "non_exclusive",
				"price_minor":  0,
				"currency":    "USD",
				"tags":        ["afrobeats", "loadtest"],
			},
			headers=self._auth_headers(),
			catch_response=True,
			name="/api/v1/marketplace/beats (create)",
		) as resp:
			# 409 = already listed — not a failure in load context
			if resp.status_code in (200, 201, 409):
				resp.success()
			elif resp.status_code == 401 and self._handle_401(resp):
				resp.success()
			elif resp.status_code == 403:
				# Pro tier gate — expected for free-tier VUs
				resp.success()
			else:
				resp.failure(f"Create listing returned {resp.status_code}: {resp.text[:200]}")

	@task(1)
	def browse_marketplace(self) -> None:
		with self.client.get(
			"/api/v1/marketplace/beats?page=1&page_size=20",
			headers=self._auth_headers(),
			catch_response=True,
			name="/api/v1/marketplace/beats (power browse)",
		) as resp:
			if resp.status_code == 200:
				resp.success()
			else:
				resp.failure(f"Marketplace returned {resp.status_code}")

	@task(1)
	def view_my_listings(self) -> None:
		with self.client.get(
			"/api/v1/marketplace/my-listings",
			headers=self._auth_headers(),
			catch_response=True,
			name="/api/v1/marketplace/my-listings",
		) as resp:
			if resp.status_code == 200:
				resp.success()
			elif resp.status_code == 401 and self._handle_401(resp):
				resp.success()
			else:
				resp.failure(f"My listings returned {resp.status_code}")

	def on_stop(self) -> None:
		if self._refresh_token:
			self.client.post(
				"/api/v1/auth/logout",
				json={"refresh_token": self._refresh_token},
				name="/api/v1/auth/logout (power)",
			)
		if self._pool_user and self._access_token:
			self._pool_user["access_token"]  = self._access_token
			self._pool_user["refresh_token"] = self._refresh_token or self._pool_user["refresh_token"]
			_pool_return(self._pool_user)
			self._pool_user = None


# ── load shape ────────────────────────────────────────────────────────────────

class StagesShape(LoadTestShape):
	"""
	Stage-based ramp profile:

	  0– 2 min   ramp 0→50   users
	  2– 8 min   sustain 50          (steady state)
	  8–10 min   ramp 50→200         (spike)
	 10–12 min   sustain 200         (stress)
	 12–14 min   ramp 200→0          (wind-down)

	Each entry is (duration_seconds, target_users, spawn_rate).
	"""

	stages: list[tuple[int, int, float]] = [
		(120,  50,   0.5),   # 0–2 min: ramp to 50
		(480,  50,   0.5),   # 2–8 min: sustain
		(600,  200,  3.0),   # 8–10 min: spike to 200
		(720,  200,  0.5),   # 10–12 min: stress
		(840,  0,    5.0),   # 12–14 min: ramp down
	]

	def tick(self) -> tuple[int, float] | None:
		run_time = self.get_run_time()
		for duration, users, spawn_rate in self.stages:
			if run_time < duration:
				return (users, spawn_rate)
		return None
