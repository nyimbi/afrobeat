"""Unit tests for services/api/src/gbedu_api/services/ml_client.py.

Tests MLServiceClient for:
- Instantiation with MLSettings
- generate_music() success path
- generate_music() 503 triggers HTTPStatusError (retry/raise)
- generate_music() timeout raises MLServiceTimeoutError
- generate_music() HTTP error raises MLServiceError
- generate_music() 4xx raises MLServiceError via raise_for_status
- get_health() returns True on 200, False on error
"""
from __future__ import annotations

import os

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost/gbedu_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("GBEDU_ML_API_KEY", "test-ml-internal-api-key")

from gbedu_core.errors import MLServiceError, MLServiceTimeoutError


def _make_settings():
	settings = MagicMock()
	settings.service_url = "http://localhost:8001"
	settings.service_api_key = "test-key"
	settings.inference_timeout = 300
	settings.circuit_failure_threshold = 5
	settings.circuit_recovery_timeout = 60
	return settings


def _make_client():
	from gbedu_api.services.ml_client import MLServiceClient
	return MLServiceClient(_make_settings())


def _make_request():
	from gbedu_api.services.ml_client import GenerationRequest
	return GenerationRequest(
		prompt="Afrobeat dance track with highlife guitars",
		sub_genre="afrobeats",
		language="english",
		bpm=120,
		energy_level=7,
		duration_seconds=30,
	)


def _make_response(status_code: int, json_data: dict) -> MagicMock:
	resp = MagicMock()
	resp.status_code = status_code
	resp.json.return_value = json_data
	resp.text = str(json_data)
	# Make raise_for_status a no-op for 2xx
	if status_code < 400:
		resp.raise_for_status = MagicMock()
	else:
		error = httpx.HTTPStatusError(
			f"HTTP {status_code}",
			request=MagicMock(),
			response=MagicMock(status_code=status_code, text=str(json_data)),
		)
		resp.raise_for_status = MagicMock(side_effect=error)
	# Need a real request object for 503 path
	resp.request = MagicMock()
	return resp


# ── instantiation ─────────────────────────────────────────────────────────────

def test_ml_client_instantiation():
	client = _make_client()
	from gbedu_api.services.ml_client import MLServiceClient
	assert isinstance(client, MLServiceClient)
	assert client._base_url == "http://localhost:8001"
	assert client._api_key == "test-key"
	assert client._inference_timeout == 300


def test_ml_client_instantiation_trailing_slash_stripped():
	from gbedu_api.services.ml_client import MLServiceClient
	settings = _make_settings()
	settings.service_url = "http://localhost:8001/"
	client = MLServiceClient(settings)
	assert client._base_url == "http://localhost:8001"


def test_ml_client_instantiation_empty_url_raises():
	from gbedu_api.services.ml_client import MLServiceClient
	settings = _make_settings()
	settings.service_url = ""
	with pytest.raises(AssertionError):
		MLServiceClient(settings)


# ── GenerationRequest ─────────────────────────────────────────────────────────

def test_generation_request_to_dict():
	req = _make_request()
	d = req.to_dict()
	assert d["prompt"] == "Afrobeat dance track with highlife guitars"
	assert d["sub_genre"] == "afrobeats"
	assert d["language"] == "english"
	assert d["bpm"] == 120
	assert d["energy_level"] == 7
	assert d["duration_seconds"] == 30
	assert d["voice_model_id"] is None


def test_generation_request_empty_prompt_raises():
	from gbedu_api.services.ml_client import GenerationRequest
	with pytest.raises(AssertionError):
		GenerationRequest(prompt="", sub_genre="afrobeats", language="english")


# ── GenerationResponse ────────────────────────────────────────────────────────

def test_generation_response_parses_data():
	from gbedu_api.services.ml_client import GenerationResponse
	resp = GenerationResponse({"job_id": "j1", "status": "queued", "audio_url": None})
	assert resp.job_id == "j1"
	assert resp.status == "queued"
	assert resp.audio_url is None
	assert resp.stem_urls == {}
	assert resp.metadata == {}


# ── generate_music success ────────────────────────────────────────────────────

async def test_generate_music_success():
	client = _make_client()
	req = _make_request()
	resp = _make_response(200, {"job_id": "j1", "status": "queued"})

	with patch.object(client._http, "post", AsyncMock(return_value=resp)):
		result = await client.generate_music(req)

	assert result.job_id == "j1"
	assert result.status == "queued"


# ── generate_music 503 raises HTTPStatusError ─────────────────────────────────

async def test_generate_music_503_raises_http_status_error():
	client = _make_client()
	req = _make_request()

	mock_request = MagicMock()
	mock_response = MagicMock()
	mock_response.status_code = 503

	resp = MagicMock()
	resp.status_code = 503
	resp.request = mock_request
	resp.raise_for_status = MagicMock()

	with patch.object(client._http, "post", AsyncMock(return_value=resp)):
		# tenacity will retry 3 times then re-raise
		with pytest.raises(httpx.HTTPStatusError):
			await client.generate_music(req)


# ── generate_music timeout ────────────────────────────────────────────────────

async def test_generate_music_timeout_raises_ml_timeout_error():
	client = _make_client()
	req = _make_request()

	with patch.object(
		client._http,
		"post",
		AsyncMock(side_effect=httpx.TimeoutException("timed out")),
	):
		with pytest.raises(MLServiceTimeoutError):
			await client.generate_music(req)


# ── generate_music HTTP error ─────────────────────────────────────────────────

async def test_generate_music_http_error_raises_ml_service_error():
	client = _make_client()
	req = _make_request()

	with patch.object(
		client._http,
		"post",
		AsyncMock(side_effect=httpx.HTTPError("connection refused")),
	):
		with pytest.raises(MLServiceError):
			await client.generate_music(req)


# ── generate_music 4xx raises MLServiceError ──────────────────────────────────

async def test_generate_music_4xx_raises_ml_service_error():
	client = _make_client()
	req = _make_request()
	resp = _make_response(422, {"detail": "invalid input"})

	with patch.object(client._http, "post", AsyncMock(return_value=resp)):
		with pytest.raises(MLServiceError):
			await client.generate_music(req)


# ── get_health ────────────────────────────────────────────────────────────────

async def test_get_health_returns_true_on_200():
	client = _make_client()
	mock_resp = MagicMock()
	mock_resp.status_code = 200

	with patch.object(client._http, "get", AsyncMock(return_value=mock_resp)):
		result = await client.get_health()

	assert result is True


async def test_get_health_returns_false_on_non_200():
	client = _make_client()
	mock_resp = MagicMock()
	mock_resp.status_code = 503

	with patch.object(client._http, "get", AsyncMock(return_value=mock_resp)):
		result = await client.get_health()

	assert result is False


async def test_get_health_returns_false_on_http_error():
	client = _make_client()

	with patch.object(
		client._http,
		"get",
		AsyncMock(side_effect=httpx.HTTPError("unreachable")),
	):
		result = await client.get_health()

	assert result is False


# ── close ─────────────────────────────────────────────────────────────────────

async def test_close_calls_aclose():
	client = _make_client()
	with patch.object(client._http, "aclose", AsyncMock()) as mock_close:
		await client.close()
	mock_close.assert_called_once()
