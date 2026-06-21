"""Unit tests for /api/v1/voice-models/* route handlers.

Strategy:
- Override get_db / get_current_active_user / get_storage via
  app.dependency_overrides.
- Mock model objects with MagicMock() — avoids SQLAlchemy mapper state issues
  that arise from Model.__new__() in isolated unit tests without a DB session.
- require_tier(pro) is overridden directly when testing upload.
- No @pytest.mark.asyncio — asyncio_mode = "auto" is set project-wide.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.testclient import TestClient

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost/gbedu_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("GBEDU_ML_API_KEY", "test-ml-internal-api-key")

from typing import Never

from gbedu_core.models.user import SubscriptionStatus, SubscriptionTier
from gbedu_core.models.voice import VoiceArchetype, VoiceModelStatus

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_user(tier: str = "pro") -> MagicMock:
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


def _make_voice_model(
	user_id: str = "user-test-001",
	is_preset: bool = False,
	status: VoiceModelStatus = VoiceModelStatus.ready,
) -> MagicMock:
	vm = MagicMock()
	vm.id = "vm-test-001"
	vm.user_id = user_id
	vm.name = "My Custom Voice"
	vm.description = "Test voice model"
	vm.archetype = VoiceArchetype.custom
	vm.status = status
	vm.is_preset = is_preset
	vm.is_public = False
	vm.training_progress_percent = 100
	vm.error_message = None
	vm.training_audio_urls = []
	vm.created_at = datetime(2025, 1, 1, tzinfo=UTC)
	vm.deleted_at = None
	return vm


def _build_client(tier: str = "pro"):
	from gbedu_api.deps import get_current_active_user, get_db
	from gbedu_api.main import app

	user = _make_user(tier)
	mock_db = AsyncMock()

	async def _override_db():
		yield mock_db

	app.dependency_overrides[get_db] = _override_db
	app.dependency_overrides[get_current_active_user] = lambda: user

	client = TestClient(app, raise_server_exceptions=False)
	return client, mock_db, user


def teardown_function() -> None:
	from gbedu_api.main import app

	app.dependency_overrides.clear()


# ── GET /voice-models ──────────────────────────────────────────────────────────


def test_list_voice_models_returns_presets_and_custom() -> None:
	client, mock_db, _ = _build_client()

	preset = _make_voice_model(user_id="system", is_preset=True)
	custom = _make_voice_model()

	preset_result = MagicMock()
	preset_result.scalars.return_value.all.return_value = [preset]
	custom_result = MagicMock()
	custom_result.scalars.return_value.all.return_value = [custom]
	mock_db.execute = AsyncMock(side_effect=[preset_result, custom_result])

	resp = client.get("/api/v1/voice-models")

	assert resp.status_code == 200
	items = resp.json()
	assert len(items) == 2
	assert any(i["is_preset"] for i in items)
	assert any(not i["is_preset"] for i in items)


def test_list_voice_models_no_custom_returns_only_presets() -> None:
	client, mock_db, _ = _build_client()

	preset = _make_voice_model(user_id="system", is_preset=True)

	preset_result = MagicMock()
	preset_result.scalars.return_value.all.return_value = [preset]
	custom_result = MagicMock()
	custom_result.scalars.return_value.all.return_value = []
	mock_db.execute = AsyncMock(side_effect=[preset_result, custom_result])

	resp = client.get("/api/v1/voice-models")

	assert resp.status_code == 200
	assert len(resp.json()) == 1
	assert resp.json()[0]["is_preset"] is True


# ── GET /voice-models/{model_id}/status ───────────────────────────────────────


def test_get_voice_model_status_owned_returns_200() -> None:
	client, mock_db, _ = _build_client()
	vm = _make_voice_model()

	result = MagicMock()
	result.scalar_one_or_none.return_value = vm
	mock_db.execute = AsyncMock(return_value=result)

	resp = client.get("/api/v1/voice-models/vm-test-001/status")

	assert resp.status_code == 200
	body = resp.json()
	assert body["id"] == "vm-test-001"
	assert body["status"] == "ready"


def test_get_voice_model_status_not_found_returns_404() -> None:
	client, mock_db, _ = _build_client()

	result = MagicMock()
	result.scalar_one_or_none.return_value = None
	mock_db.execute = AsyncMock(return_value=result)

	resp = client.get("/api/v1/voice-models/nonexistent/status")

	assert resp.status_code == 404
	assert resp.json()["detail"]["error_code"] == "NOT_FOUND"


def test_get_voice_model_status_other_user_custom_returns_403() -> None:
	client, mock_db, _ = _build_client()
	vm = _make_voice_model(user_id="other-user-999", is_preset=False)

	result = MagicMock()
	result.scalar_one_or_none.return_value = vm
	mock_db.execute = AsyncMock(return_value=result)

	resp = client.get("/api/v1/voice-models/vm-test-001/status")

	assert resp.status_code == 403
	assert resp.json()["detail"]["error_code"] == "AUTHORIZATION_ERROR"


def test_get_voice_model_status_preset_accessible_by_any_user() -> None:
	client, mock_db, _ = _build_client()
	# Preset owned by "system", not the current user — still accessible
	vm = _make_voice_model(user_id="system", is_preset=True)

	result = MagicMock()
	result.scalar_one_or_none.return_value = vm
	mock_db.execute = AsyncMock(return_value=result)

	resp = client.get("/api/v1/voice-models/vm-test-001/status")

	assert resp.status_code == 200


# ── DELETE /voice-models/{model_id} ───────────────────────────────────────────


def test_delete_voice_model_owned_returns_200() -> None:
	client, mock_db, _ = _build_client()
	vm = _make_voice_model()
	vm.delete = AsyncMock()

	result = MagicMock()
	result.scalar_one_or_none.return_value = vm
	mock_db.execute = AsyncMock(return_value=result)

	resp = client.delete("/api/v1/voice-models/vm-test-001")

	assert resp.status_code == 200
	assert resp.json()["message"] == "Voice model deleted"
	vm.delete.assert_called_once()


def test_delete_voice_model_not_found_returns_404() -> None:
	client, mock_db, _ = _build_client()

	result = MagicMock()
	result.scalar_one_or_none.return_value = None
	mock_db.execute = AsyncMock(return_value=result)

	resp = client.delete("/api/v1/voice-models/ghost-vm")

	assert resp.status_code == 404


def test_delete_voice_model_preset_returns_403() -> None:
	client, mock_db, _ = _build_client()
	vm = _make_voice_model(is_preset=True)

	result = MagicMock()
	result.scalar_one_or_none.return_value = vm
	mock_db.execute = AsyncMock(return_value=result)

	resp = client.delete("/api/v1/voice-models/vm-test-001")

	assert resp.status_code == 403
	assert "preset" in resp.json()["detail"]["message"].lower()


def test_delete_voice_model_not_owned_returns_403() -> None:
	client, mock_db, _ = _build_client()
	vm = _make_voice_model(user_id="other-user-999", is_preset=False)

	result = MagicMock()
	result.scalar_one_or_none.return_value = vm
	mock_db.execute = AsyncMock(return_value=result)

	resp = client.delete("/api/v1/voice-models/vm-test-001")

	assert resp.status_code == 403


# ── POST /voice-models/upload ──────────────────────────────────────────────────


def test_upload_voice_sample_unsupported_type_returns_422() -> None:
	from gbedu_api.deps import get_current_active_user, get_db, get_storage, require_tier
	from gbedu_api.main import app

	user = _make_user(tier="pro")
	mock_db = AsyncMock()
	mock_storage = AsyncMock()
	_tier_dep = require_tier(SubscriptionTier.pro)

	async def _override_db():
		yield mock_db

	app.dependency_overrides[get_db] = _override_db
	app.dependency_overrides[get_current_active_user] = lambda: user
	app.dependency_overrides[get_storage] = lambda: mock_storage
	app.dependency_overrides[_tier_dep] = lambda: user

	client = TestClient(app, raise_server_exceptions=False)
	resp = client.post(
		"/api/v1/voice-models/upload?name=MyVoice",
		files={"file": ("voice.mp4", b"fake-video-data", "video/mp4")},
	)

	assert resp.status_code == 422
	assert resp.json()["detail"]["error_code"] == "VALIDATION_ERROR"


def test_upload_voice_sample_free_tier_returns_403() -> None:
	from fastapi import HTTPException, status
	from gbedu_api.deps import get_current_active_user, get_db, require_tier
	from gbedu_api.main import app

	user = _make_user(tier="free")
	mock_db = AsyncMock()
	_tier_dep = require_tier(SubscriptionTier.pro)

	async def _override_db():
		yield mock_db

	def _deny() -> Never:
		raise HTTPException(
			status_code=status.HTTP_403_FORBIDDEN,
			detail={
				"error_code": "AUTHORIZATION_ERROR",
				"message": "This feature requires pro subscription or higher",
			},
		)

	app.dependency_overrides[get_db] = _override_db
	app.dependency_overrides[get_current_active_user] = lambda: user
	app.dependency_overrides[_tier_dep] = _deny

	client = TestClient(app, raise_server_exceptions=False)
	resp = client.post(
		"/api/v1/voice-models/upload?name=MyVoice",
		files={"file": ("voice.wav", b"RIFF" + b"x" * 100, "audio/wav")},
	)

	assert resp.status_code == 403


def test_upload_voice_sample_pro_tier_accepted() -> None:
	from gbedu_api.deps import get_current_active_user, get_db, get_storage, require_tier
	from gbedu_api.main import app

	user = _make_user(tier="pro")
	mock_db = AsyncMock()
	mock_db.add = MagicMock()
	mock_db.flush = AsyncMock()
	mock_storage = AsyncMock()
	mock_storage.upload_audio = AsyncMock(
		return_value="https://cdn.example.com/voice-samples/user-test-001/vm.wav"
	)
	_tier_dep = require_tier(SubscriptionTier.pro)

	# The handler constructs a real VoiceModel() which requires mapper config.
	# Patch it in the router module so we can return our fully-mocked object.
	mock_vm = _make_voice_model()
	mock_vm.name = "MyVoice"
	mock_vm.status = VoiceModelStatus.pending
	mock_vm.archetype = VoiceArchetype.custom
	# created_at is a real datetime in _make_voice_model — isoformat() already
	# returns a valid string, no patching needed.

	async def _override_db():
		yield mock_db

	with (
		patch("gbedu_api.routers.voice_models.VoiceModel", return_value=mock_vm),
		patch("gbedu_api.worker_tasks.enqueue_voice_training", MagicMock()),
	):
		app.dependency_overrides[get_db] = _override_db
		app.dependency_overrides[get_current_active_user] = lambda: user
		app.dependency_overrides[get_storage] = lambda: mock_storage
		app.dependency_overrides[_tier_dep] = lambda: user

		client = TestClient(app, raise_server_exceptions=False)
		resp = client.post(
			"/api/v1/voice-models/upload?name=MyVoice",
			files={"file": ("voice.wav", b"RIFF" + b"x" * 200, "audio/wav")},
		)

	assert resp.status_code == 202
	body = resp.json()
	assert body["name"] == "MyVoice"
	assert body["status"] == "pending"
	assert body["archetype"] == "custom"
