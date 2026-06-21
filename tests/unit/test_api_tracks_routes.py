"""Unit tests for /api/v1/tracks/* route handlers.

Strategy:
- Override get_db / get_current_active_user via app.dependency_overrides.
- Mock model objects with MagicMock() — avoids SQLAlchemy mapper state issues
  that arise from Model.__new__() in isolated unit tests without a DB session.
- No @pytest.mark.asyncio — asyncio_mode = "auto" is set project-wide.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.testclient import TestClient

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost/gbedu_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("GBEDU_ML_API_KEY", "test-ml-internal-api-key")

from gbedu_core.models.user import SubscriptionTier, SubscriptionStatus
from gbedu_core.models.track import SubGenre, Language, TrackStatus


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_user(tier: str = "free") -> MagicMock:
	user = MagicMock()
	user.id = "user-test-001"
	user.email = "test@example.com"
	user.full_name = "Test User"
	user.subscription_tier = SubscriptionTier(tier)
	user.subscription_status = SubscriptionStatus.active
	user.is_verified = True
	user.is_active = True
	user.deleted_at = None
	return user


def _make_track(user_id: str = "user-test-001", is_public: bool = False) -> MagicMock:
	track = MagicMock()
	track.id = "track-test-001"
	track.user_id = user_id
	track.title = "Test Track"
	track.prompt = "groovy afropop 100bpm"
	track.sub_genre = SubGenre.afropop
	track.language = Language.english
	track.bpm = 100
	track.key = "Cm"
	track.energy_level = 6
	track.duration_seconds = 180
	track.status = TrackStatus.ready
	track.audio_url = "https://cdn.example.com/track.mp3"
	track.audio_url_watermarked = "https://cdn.example.com/track-wm.mp3"
	track.cover_art_url = None
	track.lyrics = None
	track.is_public = is_public
	track.play_count = 0
	track.share_count = 0
	track.stem_urls = {}
	track.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
	track.deleted_at = None
	return track


def _build_client(tier: str = "free"):
	from gbedu_api.main import app
	from gbedu_api.deps import get_db, get_current_active_user

	user = _make_user(tier)
	mock_db = AsyncMock()

	async def _override_db():
		yield mock_db

	app.dependency_overrides[get_db] = _override_db
	app.dependency_overrides[get_current_active_user] = lambda: user

	client = TestClient(app, raise_server_exceptions=False)
	return client, mock_db, user


def teardown_function():
	from gbedu_api.main import app
	app.dependency_overrides.clear()


# ── GET /tracks/public ─────────────────────────────────────────────────────────

def test_list_public_tracks_returns_paginated_response():
	client, mock_db, _ = _build_client()
	track = _make_track(is_public=True)

	count_result = MagicMock()
	count_result.scalar_one.return_value = 1
	tracks_result = MagicMock()
	tracks_result.scalars.return_value.all.return_value = [track]
	mock_db.execute = AsyncMock(side_effect=[count_result, tracks_result])

	resp = client.get("/api/v1/tracks/public")

	assert resp.status_code == 200
	body = resp.json()
	assert body["total"] == 1
	assert body["page"] == 1
	assert len(body["items"]) == 1
	assert body["items"][0]["id"] == "track-test-001"


def test_list_public_tracks_empty_returns_zero_total():
	client, mock_db, _ = _build_client()

	count_result = MagicMock()
	count_result.scalar_one.return_value = 0
	tracks_result = MagicMock()
	tracks_result.scalars.return_value.all.return_value = []
	mock_db.execute = AsyncMock(side_effect=[count_result, tracks_result])

	resp = client.get("/api/v1/tracks/public?page=1&page_size=10")

	assert resp.status_code == 200
	assert resp.json()["total"] == 0
	assert resp.json()["items"] == []


# ── GET /tracks ────────────────────────────────────────────────────────────────

def test_list_my_tracks_returns_user_tracks():
	client, mock_db, _ = _build_client()
	track = _make_track()

	count_result = MagicMock()
	count_result.scalar_one.return_value = 1
	tracks_result = MagicMock()
	tracks_result.scalars.return_value.all.return_value = [track]
	mock_db.execute = AsyncMock(side_effect=[count_result, tracks_result])

	resp = client.get("/api/v1/tracks")

	assert resp.status_code == 200
	body = resp.json()
	assert body["total"] == 1
	assert body["items"][0]["title"] == "Test Track"


def test_list_my_tracks_pagination_clamps_page_size():
	client, mock_db, _ = _build_client()

	count_result = MagicMock()
	count_result.scalar_one.return_value = 0
	tracks_result = MagicMock()
	tracks_result.scalars.return_value.all.return_value = []
	mock_db.execute = AsyncMock(side_effect=[count_result, tracks_result])

	# page_size=999 should be clamped to 100
	resp = client.get("/api/v1/tracks?page_size=999")

	assert resp.status_code == 200
	assert resp.json()["page_size"] == 100


# ── GET /tracks/{track_id} ─────────────────────────────────────────────────────

def test_get_track_owned_returns_200():
	client, mock_db, _ = _build_client()
	track = _make_track()

	result = MagicMock()
	result.scalar_one_or_none.return_value = track
	mock_db.execute = AsyncMock(return_value=result)

	resp = client.get("/api/v1/tracks/track-test-001")

	assert resp.status_code == 200
	assert resp.json()["id"] == "track-test-001"


def test_get_track_not_found_returns_404():
	client, mock_db, _ = _build_client()

	result = MagicMock()
	result.scalar_one_or_none.return_value = None
	mock_db.execute = AsyncMock(return_value=result)

	resp = client.get("/api/v1/tracks/nonexistent-id")

	assert resp.status_code == 404


def test_get_track_not_owned_returns_403():
	client, mock_db, _ = _build_client()
	track = _make_track(user_id="other-user-999")

	result = MagicMock()
	result.scalar_one_or_none.return_value = track
	mock_db.execute = AsyncMock(return_value=result)

	resp = client.get("/api/v1/tracks/track-test-001")

	assert resp.status_code == 403


# ── PATCH /tracks/{track_id} ───────────────────────────────────────────────────

def test_update_track_title_returns_updated_track():
	client, mock_db, _ = _build_client()
	track = _make_track()

	result = MagicMock()
	result.scalar_one_or_none.return_value = track
	mock_db.execute = AsyncMock(return_value=result)
	mock_db.add = MagicMock()
	mock_db.flush = AsyncMock()

	resp = client.patch("/api/v1/tracks/track-test-001", json={"title": "Updated Title"})

	assert resp.status_code == 200
	assert track.title == "Updated Title"


def test_update_track_empty_title_returns_422():
	client, _, _ = _build_client()

	resp = client.patch("/api/v1/tracks/track-test-001", json={"title": ""})

	assert resp.status_code == 422


def test_update_track_not_found_returns_404():
	client, mock_db, _ = _build_client()

	result = MagicMock()
	result.scalar_one_or_none.return_value = None
	mock_db.execute = AsyncMock(return_value=result)

	resp = client.patch("/api/v1/tracks/ghost-id", json={"is_public": True})

	assert resp.status_code == 404


# ── DELETE /tracks/{track_id} ──────────────────────────────────────────────────

def test_delete_track_owned_returns_200():
	client, mock_db, _ = _build_client()
	track = _make_track()
	track.delete = AsyncMock()

	result = MagicMock()
	result.scalar_one_or_none.return_value = track
	mock_db.execute = AsyncMock(return_value=result)

	resp = client.delete("/api/v1/tracks/track-test-001")

	assert resp.status_code == 200
	assert resp.json()["message"] == "Track deleted"


def test_delete_track_not_found_returns_404():
	client, mock_db, _ = _build_client()

	result = MagicMock()
	result.scalar_one_or_none.return_value = None
	mock_db.execute = AsyncMock(return_value=result)

	resp = client.delete("/api/v1/tracks/ghost-id")

	assert resp.status_code == 404


# ── POST /tracks/{track_id}/share ──────────────────────────────────────────────

def test_share_track_increments_share_count():
	client, mock_db, _ = _build_client()
	track = _make_track()
	track.share_count = 5

	result = MagicMock()
	result.scalar_one_or_none.return_value = track
	mock_db.execute = AsyncMock(return_value=result)
	mock_db.add = MagicMock()
	mock_db.flush = AsyncMock()

	resp = client.post("/api/v1/tracks/track-test-001/share")

	assert resp.status_code == 200
	body = resp.json()
	assert body["share_count"] == 6
	assert body["track_id"] == "track-test-001"
	assert "og_title" in body


# ── GET /tracks/{track_id}/stems ───────────────────────────────────────────────

def test_get_stems_requires_creator_tier():
	from gbedu_api.main import app
	from gbedu_api.deps import get_db, get_current_active_user, require_tier
	from fastapi import HTTPException, status

	user = _make_user(tier="free")
	mock_db = AsyncMock()

	async def _override_db():
		yield mock_db

	_tier_dep = require_tier(SubscriptionTier.creator)

	def _deny():
		raise HTTPException(
			status_code=status.HTTP_403_FORBIDDEN,
			detail={
				"error_code": "AUTHORIZATION_ERROR",
				"message": "This feature requires creator subscription or higher",
			},
		)

	app.dependency_overrides[get_db] = _override_db
	app.dependency_overrides[get_current_active_user] = lambda: user
	app.dependency_overrides[_tier_dep] = _deny

	client = TestClient(app, raise_server_exceptions=False)
	resp = client.get("/api/v1/tracks/track-test-001/stems")

	assert resp.status_code == 403


def test_get_stems_creator_tier_returns_presigned_urls():
	from gbedu_api.main import app
	from gbedu_api.deps import get_db, get_current_active_user, get_storage, require_tier

	user = _make_user(tier="creator")
	mock_db = AsyncMock()
	mock_storage = AsyncMock()
	mock_storage.get_presigned_url = AsyncMock(return_value="https://presigned.example.com/drum.wav")

	track = _make_track()
	track.stem_urls = {"drums": "voice-samples/drums.wav"}

	result = MagicMock()
	result.scalar_one_or_none.return_value = track
	mock_db.execute = AsyncMock(return_value=result)

	_tier_dep = require_tier(SubscriptionTier.creator)

	async def _override_db():
		yield mock_db

	app.dependency_overrides[get_db] = _override_db
	app.dependency_overrides[get_current_active_user] = lambda: user
	app.dependency_overrides[get_storage] = lambda: mock_storage
	app.dependency_overrides[_tier_dep] = lambda: user

	client = TestClient(app, raise_server_exceptions=False)
	resp = client.get("/api/v1/tracks/track-test-001/stems")

	assert resp.status_code == 200
	body = resp.json()
	assert body["track_id"] == "track-test-001"
	assert "drums" in body["stems"]
