"""Unit tests for /api/v1/lyrics/* route handlers.

MLServiceClient is mocked to avoid ML-service dependencies.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost/gbedu_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("GBEDU_ML_API_KEY", "test-ml-internal-api-key")

from gbedu_core.models.user import SubscriptionStatus, SubscriptionTier
from starlette.testclient import TestClient


def _make_user() -> MagicMock:
	user = MagicMock()
	user.id = "user-lyrics-test-001"
	user.email = "lyrics@example.com"
	user.full_name = "Lyrics Tester"
	user.subscription_tier = SubscriptionTier.creator
	user.subscription_status = SubscriptionStatus.active
	user.is_active = True
	user.is_verified = True
	user.deleted_at = None
	return user


_DRAFT = {
	"verse1": "Mo dupe o",
	"prehook": "",
	"hook": "Jaiye ori mi",
	"verse2": "",
	"bridge": "",
	"outro": "",
	"full_lyrics": "Mo dupe o\nJaiye ori mi",
	"language_used": "yoruba",
	"fell_back_to_english": False,
	"structure_retries": 0,
	"language_disclosure": None,
}

_VALID_BODY = {
	"prompt": "grateful Yoruba song about family",
	"sub_genre": "afrobeats",
	"language": "yoruba",
}


def _build_client():
	from gbedu_api.deps import get_current_active_user, get_ml_client
	from gbedu_api.main import app

	user = _make_user()
	mock_ml = MagicMock()
	mock_ml.draft_lyrics = AsyncMock(return_value=dict(_DRAFT))

	async def _override_user():
		return user

	async def _override_ml():
		return mock_ml

	app.dependency_overrides[get_current_active_user] = _override_user
	app.dependency_overrides[get_ml_client] = _override_ml

	client = TestClient(app, raise_server_exceptions=False)
	return client, mock_ml, user


def teardown_function() -> None:
	from gbedu_api.main import app

	app.dependency_overrides.clear()


def test_draft_lyrics_success() -> None:
	client, mock_ml, _ = _build_client()
	resp = client.post("/api/v1/lyrics/draft", json=_VALID_BODY)

	assert resp.status_code == 200
	body = resp.json()
	assert body["fullLyrics"] == "Mo dupe o\nJaiye ori mi"
	assert body["languageUsed"] == "yoruba"
	assert body["fellBackToEnglish"] is False
	mock_ml.draft_lyrics.assert_awaited_once()
	# Prompt passes through to the ML service untouched
	sent = mock_ml.draft_lyrics.await_args.args[0]
	assert sent.prompt == _VALID_BODY["prompt"]


def test_draft_lyrics_prompt_too_short_returns_422() -> None:
	client, _, _ = _build_client()
	resp = client.post("/api/v1/lyrics/draft", json={**_VALID_BODY, "prompt": "short"})
	assert resp.status_code == 422


def test_draft_lyrics_missing_fields_returns_422() -> None:
	client, _, _ = _build_client()
	resp = client.post("/api/v1/lyrics/draft", json={"prompt": "grateful Yoruba song about family"})
	assert resp.status_code == 422
