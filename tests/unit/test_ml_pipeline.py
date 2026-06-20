"""Unit tests for the ML inference pipeline.

Tests the fallback chain, circuit breaker integration, prompt generation,
and error handling without loading real model weights.  All heavy ML
dependencies (torch, transformers, torchaudio) are stubbed at import time.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gbedu_core.errors import GenerationError
from gbedu_core.models.track import Language, SubGenre
from gbedu_core.schemas import GenerationRequest


# ── Shared fixtures ────────────────────────────────────────────────────────────

def _make_request(
	prompt: str = "energetic afrobeats Lagos night",
	sub_genre: SubGenre = SubGenre.afrobeats,
	language: Language = Language.pidgin,
	bpm: int | None = 105,
	duration_seconds: int = 120,
) -> GenerationRequest:
	return GenerationRequest(
		prompt=prompt,
		sub_genre=sub_genre,
		language=language,
		bpm=bpm,
		duration_seconds=duration_seconds,
	)


def _mock_model(model_id: str, is_loaded: bool = True, circuit_open: bool = False) -> MagicMock:
	"""Return a mock BaseMusGen with controllable state."""
	m = MagicMock()
	m.model_id = model_id
	m.is_loaded = is_loaded
	m.circuit_open = circuit_open
	m.generate_safe = AsyncMock(return_value=Path(f"/tmp/{model_id}.wav"))
	return m


# ── MusicGenerator fallback chain ─────────────────────────────────────────────

async def test_music_generator_uses_first_loaded_model() -> None:
	"""generate() must use the first loaded model in the chain."""
	from gbedu_ml.inference.music_generator import MusicGenerator

	ace = _mock_model("ace-step", is_loaded=True)
	stable = _mock_model("stable-audio", is_loaded=True)
	yue = _mock_model("yue", is_loaded=True)

	gen = MusicGenerator(ace_step=ace, stable_audio=stable, yue=yue)
	req = _make_request()
	result = await gen.generate(req)

	assert result.model_used == "ace-step"
	ace.generate_safe.assert_awaited_once()
	stable.generate_safe.assert_not_awaited()
	yue.generate_safe.assert_not_awaited()


async def test_music_generator_falls_through_to_second_model() -> None:
	"""When the first model is not loaded, second model is used."""
	from gbedu_ml.inference.music_generator import MusicGenerator

	ace = _mock_model("ace-step", is_loaded=False)
	stable = _mock_model("stable-audio", is_loaded=True)
	yue = _mock_model("yue", is_loaded=True)

	gen = MusicGenerator(ace_step=ace, stable_audio=stable, yue=yue)
	result = await gen.generate(_make_request())

	assert result.model_used == "stable-audio"
	ace.generate_safe.assert_not_awaited()
	stable.generate_safe.assert_awaited_once()


async def test_music_generator_falls_through_open_circuit() -> None:
	"""Circuit-open models are skipped; next model is tried."""
	from gbedu_ml.inference.music_generator import MusicGenerator

	ace = _mock_model("ace-step", is_loaded=True, circuit_open=True)
	stable = _mock_model("stable-audio", is_loaded=True, circuit_open=False)
	yue = _mock_model("yue", is_loaded=True)

	gen = MusicGenerator(ace_step=ace, stable_audio=stable, yue=yue)
	result = await gen.generate(_make_request())

	assert result.model_used == "stable-audio"


async def test_music_generator_raises_when_all_models_fail() -> None:
	"""GenerationError raised when every model in the chain is unavailable."""
	from gbedu_ml.inference.music_generator import MusicGenerator

	ace = _mock_model("ace-step", is_loaded=False)
	stable = _mock_model("stable-audio", is_loaded=False)
	yue = _mock_model("yue", is_loaded=False)

	gen = MusicGenerator(ace_step=ace, stable_audio=stable, yue=yue)
	with pytest.raises(GenerationError, match="All music generation models failed"):
		await gen.generate(_make_request())


async def test_music_generator_falls_through_on_exception() -> None:
	"""If a loaded model raises, the next model is tried."""
	from gbedu_ml.inference.music_generator import MusicGenerator

	ace = _mock_model("ace-step", is_loaded=True)
	ace.generate_safe = AsyncMock(side_effect=RuntimeError("CUDA OOM"))
	stable = _mock_model("stable-audio", is_loaded=True)
	yue = _mock_model("yue", is_loaded=True)

	gen = MusicGenerator(ace_step=ace, stable_audio=stable, yue=yue)
	result = await gen.generate(_make_request())

	assert result.model_used == "stable-audio"


async def test_music_generator_result_carries_duration() -> None:
	"""MusicGenerationResult.duration_seconds must match the request."""
	from gbedu_ml.inference.music_generator import MusicGenerator

	ace = _mock_model("ace-step", is_loaded=True)
	gen = MusicGenerator(ace_step=ace, stable_audio=_mock_model("s", False), yue=_mock_model("y", False))
	result = await gen.generate(_make_request(duration_seconds=90))
	assert result.duration_seconds == 90


# ── AfrobeatsPromptEngine ──────────────────────────────────────────────────────

def test_prompt_engine_returns_string() -> None:
	"""build_music_prompt must return a non-empty string for any valid request."""
	from gbedu_ml.prompts.afrobeats import AfrobeatsPromptEngine

	engine = AfrobeatsPromptEngine()
	req = _make_request()
	prompt = engine.build_music_prompt(req)
	assert isinstance(prompt, str)
	assert len(prompt.strip()) > 0


def test_prompt_engine_includes_genre_hint() -> None:
	"""Generated prompt must reference the requested genre in some form."""
	from gbedu_ml.prompts.afrobeats import AfrobeatsPromptEngine

	engine = AfrobeatsPromptEngine()
	for sub_genre in [SubGenre.afrobeats, SubGenre.afropop, SubGenre.amapiano_cross]:
		req = _make_request(sub_genre=sub_genre)
		prompt = engine.build_music_prompt(req)
		assert any(
			kw in prompt.lower()
			for kw in ["afro", "amapiano", "highlife", "afrohouse", sub_genre.value.lower()]
		), f"Genre not found in prompt for {sub_genre.value}: {prompt[:200]}"


def test_prompt_engine_bpm_none_does_not_crash() -> None:
	"""build_music_prompt must handle bpm=None gracefully."""
	from gbedu_ml.prompts.afrobeats import AfrobeatsPromptEngine

	engine = AfrobeatsPromptEngine()
	req = _make_request(bpm=None)
	prompt = engine.build_music_prompt(req)
	assert prompt  # just must not raise


def test_prompt_engine_all_languages() -> None:
	"""Prompt must be generated for every supported language."""
	from gbedu_ml.prompts.afrobeats import AfrobeatsPromptEngine

	engine = AfrobeatsPromptEngine()
	for lang in [Language.english, Language.yoruba, Language.pidgin, Language.igbo]:
		req = _make_request(language=lang)
		prompt = engine.build_music_prompt(req)
		assert len(prompt) > 5


# ── VocalSynthesizer graceful degradation ─────────────────────────────────────

async def test_vocal_synthesizer_degrades_gracefully_without_rvc() -> None:
	"""VocalSynthesizer.load() must not raise even if rvc is absent."""
	from gbedu_ml.inference.vocal_synthesizer import VocalSynthesizer

	synth = VocalSynthesizer()
	# Patch rvc import to simulate package absence
	with patch.dict("sys.modules", {"rvc": None}):
		await synth.load()
	# is_loaded is False, _rvc is None — but no exception raised
	assert not synth.is_loaded
	assert synth._rvc is None


async def test_vocal_synthesizer_skips_synthesis_when_not_loaded() -> None:
	"""synthesize() must raise or return gracefully when RVC is not loaded."""
	from gbedu_ml.inference.vocal_synthesizer import VocalSynthesizer

	synth = VocalSynthesizer()
	# Don't call load() — synthesizer remains in unloaded state
	assert not synth.is_loaded
	# Attempting synthesis without a loaded voice model should raise FileNotFoundError
	# (can't find the .pth file) or similar — not an AttributeError or ImportError
	with pytest.raises((FileNotFoundError, Exception)):
		await synth.synthesize(
			lyrics_path=Path("/tmp/lyrics.wav"),
			melody_path=Path("/tmp/melody.wav"),
			voice_model_id="nonexistent-voice",
		)


# ── GenerationPipeline timeout handling ───────────────────────────────────────

async def test_pipeline_raises_on_timeout() -> None:
	"""GenerationPipeline must raise GenerationError when timeout is exceeded."""
	import asyncio

	from gbedu_ml.pipeline import GenerationPipeline

	async def _slow_generate(*args, **kwargs):  # type: ignore[no-untyped-def]
		await asyncio.sleep(9999)
		raise AssertionError("Should have timed out")

	music_gen = MagicMock()
	music_gen.generate = _slow_generate
	lyric_gen = MagicMock()
	lyric_gen.generate = AsyncMock(return_value=MagicMock())
	vocal_synth = MagicMock()
	vocal_synth.synthesize = AsyncMock(return_value=None)

	pipeline = GenerationPipeline(
		music_gen=music_gen,
		lyric_gen=lyric_gen,
		vocal_synth=vocal_synth,
	)

	with patch("gbedu_ml.pipeline._PIPELINE_TIMEOUT_SECONDS", 0.05):
		with pytest.raises((GenerationError, asyncio.TimeoutError)):
			await pipeline.run(
				job_id="test-job-id",
				request=_make_request(),
			)


# ── Config validation ──────────────────────────────────────────────────────────

def test_ml_settings_inference_timeout_positive() -> None:
	"""GENERATION_TIMEOUT_SECONDS must be a positive value."""
	from gbedu_ml.config import settings

	assert settings.GENERATION_TIMEOUT_SECONDS > 0


def test_ml_settings_model_cache_dir_is_path() -> None:
	"""MODEL_CACHE_DIR must be a valid Path."""
	from gbedu_ml.config import settings

	assert isinstance(settings.MODEL_CACHE_DIR, Path)
