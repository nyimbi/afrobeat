from __future__ import annotations

"""Unit tests for gbedu_ml.main FastAPI routes.

Sets module globals directly (bypassing lifespan model loading) so routes can
be tested without a GPU or real model weights.
"""

import asyncio
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _make_mock_model(is_loaded: bool = True) -> MagicMock:
	m = MagicMock()
	m.is_loaded = is_loaded
	m.health_check.return_value = {"is_loaded": is_loaded, "model_id": "test-model"}
	m.model_id = "test-model"
	return m


def _setup_globals() -> None:
	import gbedu_ml.main as ml_main

	mock_model = _make_mock_model()
	ml_main._startup_time = 0.1
	ml_main._model_load_errors = {}
	ml_main._ace_step = mock_model
	ml_main._stable_audio = mock_model
	ml_main._yue = mock_model
	ml_main._lyric_gen = MagicMock(is_loaded=True)
	ml_main._vocal_synth = MagicMock(is_loaded=True)
	ml_main._music_gen = MagicMock()
	ml_main._generation_semaphore = asyncio.Semaphore(1)
	ml_main._pipeline = MagicMock()


def _client(api_key: str = "test-key") -> tuple[TestClient, types.ModuleType]:
	import gbedu_ml.main as ml_main

	_setup_globals()
	ml_main.settings.API_KEY = api_key
	return TestClient(ml_main.app, raise_server_exceptions=True), ml_main


# ── /health ───────────────────────────────────────────────────────────────────


def test_health_returns_ok() -> None:
	client, _ = _client()
	with patch("gbedu_ml.main.torch") as mock_torch:
		mock_torch.cuda.is_available.return_value = False
		resp = client.get("/health")
	assert resp.status_code == 200
	body = resp.json()
	assert body["status"] == "ok"
	assert "startup_seconds" in body
	assert "models" in body


def test_health_includes_gpu_info_when_cuda_available() -> None:
	client, _ = _client()
	with patch("gbedu_ml.main.torch") as mock_torch:
		mock_torch.cuda.is_available.return_value = True
		mock_torch.cuda.get_device_name.return_value = "NVIDIA A100"
		mock_torch.cuda.memory_allocated.return_value = 1024**3
		mock_torch.cuda.memory_reserved.return_value = 2 * 1024**3
		props = MagicMock()
		props.total_memory = 80 * 1024**3
		mock_torch.cuda.get_device_properties.return_value = props
		resp = client.get("/health")
	assert resp.status_code == 200
	body = resp.json()
	assert body["gpu"]["device"] == "NVIDIA A100"


def test_health_shows_model_load_errors() -> None:
	import gbedu_ml.main as ml_main

	client, _ = _client()
	ml_main._model_load_errors = {"yue": "CUDA OOM"}
	with patch("gbedu_ml.main.torch") as mock_torch:
		mock_torch.cuda.is_available.return_value = False
		resp = client.get("/health")
	assert resp.json()["load_errors"]["yue"] == "CUDA OOM"


# ── /ready ────────────────────────────────────────────────────────────────────


def test_ready_returns_200_when_model_loaded() -> None:
	client, _ = _client()
	resp = client.get("/ready")
	assert resp.status_code == 200
	assert resp.json()["status"] == "ready"


def test_ready_returns_503_when_no_model_loaded() -> None:
	import gbedu_ml.main as ml_main

	client, _ = _client()
	ml_main._ace_step = _make_mock_model(is_loaded=False)
	ml_main._stable_audio = _make_mock_model(is_loaded=False)
	ml_main._yue = _make_mock_model(is_loaded=False)
	resp = client.get("/ready")
	assert resp.status_code == 503


# ── /models (requires API key) ────────────────────────────────────────────────


def test_models_returns_model_list() -> None:
	client, _ = _client(api_key="secret-key")
	resp = client.get("/models", headers={"X-API-Key": "secret-key"})
	assert resp.status_code == 200
	body = resp.json()
	assert "models" in body
	assert len(body["models"]) == 3


def test_models_rejects_wrong_api_key() -> None:
	client, _ = _client(api_key="real-key")
	resp = client.get("/models", headers={"X-API-Key": "wrong-key"})
	assert resp.status_code == 403


def test_models_rejects_missing_api_key() -> None:
	client, _ = _client()
	resp = client.get("/models")
	# APIKeyHeader with auto_error=True returns 401 when header is absent
	assert resp.status_code in (401, 403)


# ── _require_api_key ──────────────────────────────────────────────────────────


def test_require_api_key_valid() -> None:
	import gbedu_ml.main as ml_main

	ml_main.settings.API_KEY = "valid-key"
	result = ml_main._require_api_key("valid-key")
	assert result == "valid-key"


def test_require_api_key_invalid_raises_403() -> None:
	import gbedu_ml.main as ml_main
	from fastapi import HTTPException

	ml_main.settings.API_KEY = "real-key"
	with pytest.raises(HTTPException) as exc_info:
		ml_main._require_api_key("wrong-key")
	assert exc_info.value.status_code == 403


# ── /generate ─────────────────────────────────────────────────────────────────


def test_generate_returns_200_on_success() -> None:
	import gbedu_ml.main as ml_main

	client, _ = _client(api_key="key")

	# Build a mock result matching what generate() accesses
	mock_music = MagicMock()
	mock_music.model_used = "ace_step"

	mock_lyrics = MagicMock()
	mock_lyrics.model_dump.return_value = {"full_lyrics": "Na me dey"}

	pipeline_result = MagicMock()
	pipeline_result.job_id = "job-1"
	pipeline_result.final_audio_path = "/tmp/out.wav"
	pipeline_result.instrumental_path = "/tmp/instrumental.wav"
	pipeline_result.vocal_path = None
	pipeline_result.lyrics_result = mock_lyrics
	pipeline_result.music_result = mock_music
	pipeline_result.duration_seconds = 180
	pipeline_result.elapsed_seconds = 12.3
	pipeline_result.metadata = {}
	ml_main._pipeline.run = AsyncMock(return_value=pipeline_result)

	# Only required fields — extra="forbid" rejects unknown fields
	payload = {
		"prompt": "Afrobeats love song about Lagos",
		"sub_genre": "afropop",
		"language": "pidgin",
	}
	with patch("gbedu_ml.main.get_tracer") as mock_tracer:
		mock_span = MagicMock()
		mock_span.__enter__ = MagicMock(return_value=mock_span)
		mock_span.__exit__ = MagicMock(return_value=False)
		mock_tracer.return_value.start_as_current_span.return_value = mock_span
		with patch("gbedu_ml.main.record_generation_duration"):
			with patch("gbedu_ml.main.increment_generation_count"):
				resp = client.post(
					"/generate",
					json=payload,
					headers={"X-API-Key": "key"},
				)
	assert resp.status_code == 200


def test_generate_rejects_wrong_api_key() -> None:
	client, _ = _client(api_key="key")
	payload = {
		"title": "T",
		"sub_genre": "afropop",
		"language": "pidgin",
		"duration_seconds": 60,
		"bpm": 100,
		"mood": "energetic",
	}
	resp = client.post("/generate", json=payload, headers={"X-API-Key": "bad"})
	assert resp.status_code == 403


# ── _load_model helper ────────────────────────────────────────────────────────


async def test_load_model_success() -> None:
	import gbedu_ml.main as ml_main
	from gbedu_ml.main import _load_model

	ml_main._model_load_errors = {}
	mock_model = AsyncMock()
	mock_model.load = AsyncMock()
	await _load_model("test_model", mock_model)
	mock_model.load.assert_awaited_once()
	assert "test_model" not in ml_main._model_load_errors


async def test_load_model_failure_logs_not_raises() -> None:
	import gbedu_ml.main as ml_main
	from gbedu_ml.main import _load_model

	ml_main._model_load_errors = {}
	mock_model = AsyncMock()
	mock_model.load = AsyncMock(side_effect=RuntimeError("CUDA OOM"))
	await _load_model("bad_model", mock_model)
	assert "bad_model" in ml_main._model_load_errors
	assert "CUDA OOM" in ml_main._model_load_errors["bad_model"]
