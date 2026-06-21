"""Unit tests for /api/v1/users/* route handlers.

Strategy:
- Override get_db / get_current_active_user / get_redis / get_storage via
  app.dependency_overrides.
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

from gbedu_core.models.user import SubscriptionTier, SubscriptionStatus, TIER_DAILY_LIMITS


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_user(tier: str = "free") -> MagicMock:
	user = MagicMock()
	user.id = "user-test-001"
	user.email = "test@example.com"
	user.full_name = "Test User"
	user.avatar_url = None
	user.subscription_tier = SubscriptionTier(tier)
	user.subscription_status = SubscriptionStatus.active
	user.is_verified = True
	user.is_active = True
	user.preferred_language = "en"
	user.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
	user.deleted_at = None
	return user


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


# ── GET /users/me ──────────────────────────────────────────────────────────────

def test_get_me_returns_profile():
	client, _, _ = _build_client()

	resp = client.get("/api/v1/users/me")

	assert resp.status_code == 200
	body = resp.json()
	assert body["id"] == "user-test-001"
	assert body["email"] == "test@example.com"
	assert body["subscription_tier"] == "free"
	assert body["is_verified"] is True
	assert body["is_active"] is True


def test_get_me_unauthenticated_returns_401():
	from gbedu_api.main import app
	from gbedu_api.deps import get_current_active_user
	from fastapi import HTTPException, status

	def _deny():
		raise HTTPException(
			status_code=status.HTTP_401_UNAUTHORIZED,
			detail={"error_code": "AUTHENTICATION_ERROR", "message": "Authentication required"},
		)

	app.dependency_overrides[get_current_active_user] = _deny
	client = TestClient(app, raise_server_exceptions=False)

	resp = client.get("/api/v1/users/me")

	assert resp.status_code == 401


# ── PATCH /users/me ────────────────────────────────────────────────────────────

def test_update_me_full_name_updates_in_place():
	client, mock_db, user = _build_client()
	mock_db.add = MagicMock()
	mock_db.flush = AsyncMock()

	resp = client.patch("/api/v1/users/me", json={"full_name": "Updated Name"})

	assert resp.status_code == 200
	assert user.full_name == "Updated Name"
	mock_db.add.assert_called_once()
	mock_db.flush.assert_called_once()


def test_update_me_preferred_language_accepted():
	client, mock_db, user = _build_client()
	mock_db.add = MagicMock()
	mock_db.flush = AsyncMock()

	resp = client.patch("/api/v1/users/me", json={"preferred_language": "yo"})

	assert resp.status_code == 200
	assert user.preferred_language == "yo"


def test_update_me_empty_full_name_returns_422():
	client, _, _ = _build_client()

	resp = client.patch("/api/v1/users/me", json={"full_name": ""})

	assert resp.status_code == 422


def test_update_me_extra_field_returns_422():
	client, _, _ = _build_client()

	resp = client.patch("/api/v1/users/me", json={"subscription_tier": "pro"})

	assert resp.status_code == 422


def test_update_me_no_body_fields_is_noop():
	client, mock_db, user = _build_client()
	mock_db.add = MagicMock()
	mock_db.flush = AsyncMock()

	resp = client.patch("/api/v1/users/me", json={})

	assert resp.status_code == 200
	assert user.full_name == "Test User"


# ── GET /users/me/stats ────────────────────────────────────────────────────────

def test_get_my_stats_returns_counts():
	from gbedu_api.main import app
	from gbedu_api.deps import get_db, get_current_active_user, get_redis

	user = _make_user(tier="creator")
	mock_db = AsyncMock()
	mock_redis = AsyncMock()
	mock_redis.get = AsyncMock(return_value=b"5")

	total_result = MagicMock()
	total_result.scalar_one.return_value = 10
	ready_result = MagicMock()
	ready_result.scalar_one.return_value = 7
	mock_db.execute = AsyncMock(side_effect=[total_result, ready_result])

	async def _override_db():
		yield mock_db

	async def _override_redis():
		return mock_redis

	app.dependency_overrides[get_db] = _override_db
	app.dependency_overrides[get_current_active_user] = lambda: user
	app.dependency_overrides[get_redis] = _override_redis

	client = TestClient(app, raise_server_exceptions=False)
	resp = client.get("/api/v1/users/me/stats")

	assert resp.status_code == 200
	body = resp.json()
	assert body["total_tracks"] == 10
	assert body["tracks_ready"] == 7
	assert body["total_generations_today"] == 5
	assert body["daily_limit"] == 20  # creator tier limit
	assert body["subscription_tier"] == "creator"


def test_get_my_stats_no_redis_key_defaults_to_zero():
	from gbedu_api.main import app
	from gbedu_api.deps import get_db, get_current_active_user, get_redis

	user = _make_user(tier="free")
	mock_db = AsyncMock()
	mock_redis = AsyncMock()
	mock_redis.get = AsyncMock(return_value=None)

	total_result = MagicMock()
	total_result.scalar_one.return_value = 0
	ready_result = MagicMock()
	ready_result.scalar_one.return_value = 0
	mock_db.execute = AsyncMock(side_effect=[total_result, ready_result])

	async def _override_db():
		yield mock_db

	async def _override_redis():
		return mock_redis

	app.dependency_overrides[get_db] = _override_db
	app.dependency_overrides[get_current_active_user] = lambda: user
	app.dependency_overrides[get_redis] = _override_redis

	client = TestClient(app, raise_server_exceptions=False)
	resp = client.get("/api/v1/users/me/stats")

	assert resp.status_code == 200
	assert resp.json()["total_generations_today"] == 0


# ── POST /users/me/avatar ──────────────────────────────────────────────────────

def test_upload_avatar_invalid_content_type_returns_422():
	from gbedu_api.main import app
	from gbedu_api.deps import get_db, get_current_active_user, get_storage

	user = _make_user()
	mock_db = AsyncMock()
	mock_storage = AsyncMock()

	async def _override_db():
		yield mock_db

	app.dependency_overrides[get_db] = _override_db
	app.dependency_overrides[get_current_active_user] = lambda: user
	app.dependency_overrides[get_storage] = lambda: mock_storage

	client = TestClient(app, raise_server_exceptions=False)
	resp = client.post(
		"/api/v1/users/me/avatar",
		files={"file": ("avatar.gif", b"GIF89a", "image/gif")},
	)

	assert resp.status_code == 422
	assert resp.json()["detail"]["error_code"] == "VALIDATION_ERROR"


def test_upload_avatar_valid_jpeg_updates_avatar_url():
	from gbedu_api.main import app
	from gbedu_api.deps import get_db, get_current_active_user, get_storage

	user = _make_user()
	mock_db = AsyncMock()
	mock_db.add = MagicMock()
	mock_db.flush = AsyncMock()
	mock_storage = AsyncMock()
	mock_storage.upload_audio = AsyncMock(
		return_value="https://cdn.example.com/avatars/user-test-001/new.jpeg"
	)

	async def _override_db():
		yield mock_db

	app.dependency_overrides[get_db] = _override_db
	app.dependency_overrides[get_current_active_user] = lambda: user
	app.dependency_overrides[get_storage] = lambda: mock_storage

	client = TestClient(app, raise_server_exceptions=False)
	resp = client.post(
		"/api/v1/users/me/avatar",
		files={"file": ("avatar.jpg", b"\xff\xd8\xff" + b"x" * 100, "image/jpeg")},
	)

	assert resp.status_code == 200
	assert user.avatar_url == "https://cdn.example.com/avatars/user-test-001/new.jpeg"


# ── DELETE /users/me ───────────────────────────────────────────────────────────

def test_delete_me_soft_deletes_account():
	client, mock_db, user = _build_client()
	user.delete = AsyncMock()

	resp = client.delete("/api/v1/users/me")

	assert resp.status_code == 200
	assert resp.json()["message"] == "Account scheduled for deletion"
	user.delete.assert_called_once_with(mock_db)
