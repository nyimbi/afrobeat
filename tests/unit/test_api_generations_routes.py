"""Unit tests for /api/v1/generations/* route handlers.

Tests submit, get_status, cancel, list endpoints.
GenerationService is mocked to avoid DB/worker dependencies.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost/gbedu_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("GBEDU_ML_API_KEY", "test-ml-internal-api-key")

from starlette.testclient import TestClient

from gbedu_core.models.user import SubscriptionTier, SubscriptionStatus


def _make_user(tier: str = "creator") -> MagicMock:
	user = MagicMock()
	user.id = "user-gen-test-001"
	user.email = "gen@example.com"
	user.full_name = "Gen Tester"
	user.subscription_tier = SubscriptionTier(tier)
	user.subscription_status = SubscriptionStatus.active
	user.is_active = True
	user.is_verified = True
	user.deleted_at = None
	return user


def _make_job(
	job_id: str = "job-001",
	status: str = "queued",
	progress: int = 0,
) -> MagicMock:
	job = MagicMock()
	job.id = job_id
	job.status = MagicMock()
	job.status.value = status
	job.progress_percent = progress
	job.prompt_used = "Afrobeat dance track with highlife guitars"
	job.model_used = None
	job.error_message = None
	job.track_id = None
	job.created_at = MagicMock()
	job.created_at.isoformat.return_value = "2025-01-01T00:00:00+00:00"
	job.started_at = None
	job.completed_at = None
	return job


def _build_client(tier: str = "creator"):
	from gbedu_api.main import app
	from gbedu_api.deps import get_db, get_redis, get_current_active_user

	user = _make_user(tier)
	mock_db = AsyncMock()
	mock_redis = AsyncMock()

	async def _override_db():
		yield mock_db

	async def _override_redis():
		return mock_redis

	app.dependency_overrides[get_db] = _override_db
	app.dependency_overrides[get_redis] = _override_redis
	app.dependency_overrides[get_current_active_user] = lambda: user

	client = TestClient(app, raise_server_exceptions=False)
	return client, mock_db, mock_redis, user


def teardown_function():
	from gbedu_api.main import app
	app.dependency_overrides.clear()


_VALID_BODY = {
	"prompt": "Afrobeat dance track with highlife guitars and talking drum",
	"sub_genre": "afrobeats",
	"language": "english",
	"bpm": 120,
	"energy_level": 7,
	"duration_seconds": 30,
}


# ── POST /generations ─────────────────────────────────────────────────────────

def test_submit_generation_success():
	client, mock_db, mock_redis, user = _build_client()
	job = _make_job("job-001", "queued")

	with patch("gbedu_api.routers.generations.GenerationService") as MockSvc:
		instance = MockSvc.return_value
		instance.submit_job = AsyncMock(return_value=job)
		resp = client.post("/api/v1/generations", json=_VALID_BODY)

	assert resp.status_code == 202
	body = resp.json()
	assert body["id"] == "job-001"
	assert body["status"] == "queued"


def test_submit_generation_prompt_too_short_returns_422():
	client, _, _, _ = _build_client()
	resp = client.post("/api/v1/generations", json={**_VALID_BODY, "prompt": "short"})
	assert resp.status_code == 422


def test_submit_generation_missing_required_fields_returns_422():
	client, _, _, _ = _build_client()
	resp = client.post("/api/v1/generations", json={"prompt": "Afrobeat dance track with highlife guitars"})
	assert resp.status_code == 422


def test_submit_generation_gbedu_error_returns_http_error():
	from gbedu_core.errors import RateLimitError
	client, _, _, _ = _build_client()

	err = RateLimitError("Rate limit exceeded")

	with patch("gbedu_api.routers.generations.GenerationService") as MockSvc:
		instance = MockSvc.return_value
		instance.submit_job = AsyncMock(side_effect=err)
		resp = client.post("/api/v1/generations", json=_VALID_BODY)

	assert resp.status_code == 429


# ── GET /generations/{job_id} ─────────────────────────────────────────────────

def test_get_generation_status_success():
	client, _, _, _ = _build_client()
	job = _make_job("job-002", "processing", 40)

	with patch("gbedu_api.routers.generations.GenerationService") as MockSvc:
		instance = MockSvc.return_value
		instance.get_job_status = AsyncMock(return_value=job)
		resp = client.get("/api/v1/generations/job-002")

	assert resp.status_code == 200
	body = resp.json()
	assert body["id"] == "job-002"
	assert body["status"] == "processing"
	assert body["progress_percent"] == 40


def test_get_generation_status_not_found_returns_404():
	from gbedu_core.errors import NotFoundError
	client, _, _, _ = _build_client()

	err = NotFoundError("job", "nonexistent-job")

	with patch("gbedu_api.routers.generations.GenerationService") as MockSvc:
		instance = MockSvc.return_value
		instance.get_job_status = AsyncMock(side_effect=err)
		resp = client.get("/api/v1/generations/nonexistent-job")

	assert resp.status_code == 404


# ── DELETE /generations/{job_id} ──────────────────────────────────────────────

def test_cancel_generation_success():
	client, _, _, _ = _build_client()

	with patch("gbedu_api.routers.generations.GenerationService") as MockSvc:
		instance = MockSvc.return_value
		instance.cancel_job = AsyncMock(return_value=None)
		resp = client.delete("/api/v1/generations/job-003")

	assert resp.status_code == 200
	assert resp.json()["message"] == "Job cancelled successfully"


def test_cancel_generation_not_found_returns_error():
	from gbedu_core.errors import NotFoundError
	client, _, _, _ = _build_client()

	err = NotFoundError("job", "nonexistent-job")

	with patch("gbedu_api.routers.generations.GenerationService") as MockSvc:
		instance = MockSvc.return_value
		instance.cancel_job = AsyncMock(side_effect=err)
		resp = client.delete("/api/v1/generations/nonexistent-job")

	assert resp.status_code == 404


def test_cancel_generation_wrong_user_returns_403():
	from gbedu_core.errors import AuthorizationError
	client, _, _, _ = _build_client()

	err = AuthorizationError("Not your job")

	with patch("gbedu_api.routers.generations.GenerationService") as MockSvc:
		instance = MockSvc.return_value
		instance.cancel_job = AsyncMock(side_effect=err)
		resp = client.delete("/api/v1/generations/job-004")

	assert resp.status_code == 403


# ── GET /generations ──────────────────────────────────────────────────────────

def test_list_generations_returns_paginated():
	client, _, _, _ = _build_client()
	jobs = [_make_job(f"job-{i}", "completed", 100) for i in range(3)]

	with patch("gbedu_api.routers.generations.GenerationService") as MockSvc:
		instance = MockSvc.return_value
		instance.list_jobs = AsyncMock(return_value=(jobs, 3))
		resp = client.get("/api/v1/generations")

	assert resp.status_code == 200
	body = resp.json()
	assert body["total"] == 3
	assert len(body["items"]) == 3
	assert body["page"] == 1
	assert body["page_size"] == 20


def test_list_generations_custom_page_params():
	client, _, _, _ = _build_client()

	with patch("gbedu_api.routers.generations.GenerationService") as MockSvc:
		instance = MockSvc.return_value
		instance.list_jobs = AsyncMock(return_value=([], 0))
		resp = client.get("/api/v1/generations?page=2&page_size=10")

	assert resp.status_code == 200
	body = resp.json()
	assert body["page"] == 2
	assert body["page_size"] == 10


def test_list_generations_empty():
	client, _, _, _ = _build_client()

	with patch("gbedu_api.routers.generations.GenerationService") as MockSvc:
		instance = MockSvc.return_value
		instance.list_jobs = AsyncMock(return_value=([], 0))
		resp = client.get("/api/v1/generations")

	assert resp.status_code == 200
	assert resp.json()["total"] == 0
	assert resp.json()["items"] == []


def test_list_generations_invalid_page_clamped():
	client, _, _, _ = _build_client()

	with patch("gbedu_api.routers.generations.GenerationService") as MockSvc:
		instance = MockSvc.return_value
		instance.list_jobs = AsyncMock(return_value=([], 0))
		# page=0 should be clamped to 1, page_size=999 clamped to 20
		resp = client.get("/api/v1/generations?page=0&page_size=999")

	assert resp.status_code == 200
	body = resp.json()
	assert body["page"] == 1
	assert body["page_size"] == 20
