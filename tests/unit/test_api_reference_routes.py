"""Unit tests for reference-track upload + submit wiring.

Covers POST /api/v1/generations/reference and the referenceAudioKey
submit path. Storage is mocked; no R2 required.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost/gbedu_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("GBEDU_ML_API_KEY", "test-ml-internal-api-key")

from gbedu_core.models.user import SubscriptionStatus, SubscriptionTier
from starlette.testclient import TestClient


def _make_user() -> MagicMock:
	user = MagicMock()
	user.id = "user-ref-test-001"
	user.email = "ref@example.com"
	user.full_name = "Ref Tester"
	user.subscription_tier = SubscriptionTier.creator
	user.subscription_status = SubscriptionStatus.active
	user.is_active = True
	user.is_verified = True
	user.deleted_at = None
	return user


def _build_client():
	from gbedu_api.deps import get_current_active_user, get_db, get_redis, get_storage
	from gbedu_api.main import app

	user = _make_user()
	mock_db = AsyncMock()
	mock_redis = AsyncMock()
	mock_storage = AsyncMock()
	mock_storage.upload_audio = AsyncMock(return_value="https://cdn.example.com/ref.wav")

	async def _override_db():
		yield mock_db

	async def _override_redis():
		return mock_redis

	app.dependency_overrides[get_db] = _override_db
	app.dependency_overrides[get_redis] = _override_redis
	app.dependency_overrides[get_current_active_user] = lambda: user
	app.dependency_overrides[get_storage] = lambda: mock_storage

	client = TestClient(app, raise_server_exceptions=False)
	return client, mock_db, mock_redis, mock_storage, user


def teardown_function() -> None:
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


def _make_job(job_id: str = "job-001", status: str = "queued") -> MagicMock:
	job = MagicMock()
	job.id = job_id
	job.status = MagicMock()
	job.status.value = status
	job.progress_percent = 0
	job.prompt_used = _VALID_BODY["prompt"]
	job.model_used = None
	job.error_message = None
	job.track_id = None
	job.created_at = MagicMock()
	job.created_at.isoformat.return_value = "2025-01-01T00:00:00+00:00"
	job.started_at = None
	job.completed_at = None
	return job


# ── POST /generations/reference ───────────────────────────────────────────────


def test_reference_upload_success_returns_namespaced_key() -> None:
	client, _, _, _, user = _build_client()
	resp = client.post(
		"/api/v1/generations/reference",
		files={"file": ("beat.mp3", b"ID3" + b"x" * 100, "audio/mpeg")},
	)

	assert resp.status_code == 202
	key = resp.json()["key"]
	assert key.startswith(f"reference-samples/{user.id}/")
	assert key.endswith(".mp3")


def test_reference_upload_unsupported_type_returns_422() -> None:
	client, _, _, _, _ = _build_client()
	resp = client.post(
		"/api/v1/generations/reference",
		files={"file": ("beat.mp4", b"fake-video", "video/mp4")},
	)

	assert resp.status_code == 422
	assert resp.json()["detail"]["error_code"] == "VALIDATION_ERROR"


# ── Submit with referenceAudioKey ─────────────────────────────────────────────


def test_submit_forwards_reference_audio_key() -> None:
	client, _, _, _, user = _build_client()
	job = _make_job()
	key = f"reference-samples/{user.id}/abc/ref.mp3"

	with patch("gbedu_api.routers.generations.GenerationService") as MockSvc:
		instance = MockSvc.return_value
		instance.submit_job = AsyncMock(return_value=job)
		resp = client.post("/api/v1/generations", json={**_VALID_BODY, "referenceAudioKey": key})

	assert resp.status_code == 202
	_, kwargs = instance.submit_job.await_args
	assert kwargs["request"].reference_audio_key == key


def test_submit_rejects_foreign_reference_key() -> None:
	client, _, _, _, _ = _build_client()
	resp = client.post(
		"/api/v1/generations",
		json={**_VALID_BODY, "referenceAudioKey": "reference-samples/someone-else/abc/ref.mp3"},
	)

	assert resp.status_code == 422
