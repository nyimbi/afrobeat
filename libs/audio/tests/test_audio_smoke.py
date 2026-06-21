"""
Smoke tests for gbedu_audio.

These tests verify import surface, class instantiation, and pure-Python logic
without requiring GPU, demucs weights, or real audio files.
Heavy integration tests (actual audio processing) live in tests/ci/.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
import soundfile as sf

# ── Helpers ────────────────────────────────────────────────────────────────────


def _write_sine_wav(
	path: Path, freq: float = 440.0, duration: float = 3.0, sr: int = 44100
) -> None:
	t = np.linspace(0, duration, int(sr * duration), endpoint=False)
	audio = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
	stereo = np.stack([audio, audio], axis=1)
	sf.write(str(path), stereo, sr, subtype="PCM_24")


def _write_click_wav(
	path: Path, bpm: float = 120.0, duration: float = 5.0, sr: int = 44100
) -> None:
	"""Write a click-track WAV at the given BPM so librosa beat_track has rhythmic content."""
	n_samples = int(sr * duration)
	audio = np.zeros(n_samples, dtype=np.float32)
	beat_period = sr * 60.0 / bpm
	click_len = int(sr * 0.02)  # 20ms click envelope
	click_t = np.arange(click_len) / sr
	click = (0.9 * np.sin(2 * np.pi * 1000 * click_t) * np.exp(-click_t * 200)).astype(np.float32)
	pos = 0
	while pos < n_samples:
		end = min(pos + click_len, n_samples)
		audio[pos:end] += click[: end - pos]
		pos += int(beat_period)
	stereo = np.stack([audio, audio], axis=1)
	sf.write(str(path), stereo, sr, subtype="PCM_24")


# ── Import surface ─────────────────────────────────────────────────────────────


def test_imports() -> None:
	from gbedu_audio import (
		AudioPipeline,
		StemSeparator,
	)

	assert AudioPipeline is not None
	assert StemSeparator is not None


# ── _base ──────────────────────────────────────────────────────────────────────


def test_audio_file_dataclass() -> None:
	from gbedu_audio._base import AudioFile

	af = AudioFile(
		path=Path("/tmp/test.wav"),
		duration_seconds=3.0,
		sample_rate=44100,
		channels=2,
		format="WAV",
		size_bytes=500_000,
	)
	assert af.duration_seconds == 3.0
	assert af.channels == 2


def test_audio_processing_error() -> None:
	from gbedu_audio._base import AudioProcessingError

	exc = AudioProcessingError("something went wrong", stage="detect_bpm")
	assert exc.stage == "detect_bpm"
	assert "detect_bpm" in repr(exc)


def test_processing_result_dataclass() -> None:
	from gbedu_audio._base import AudioFile, ProcessingResult

	af = AudioFile(Path("/tmp/a.wav"), 3.0, 44100, 2, "WAV", 1000)
	pr = ProcessingResult(input=af, output=af, processing_time_seconds=0.5, metadata={"x": 1})
	assert pr.metadata["x"] == 1


# ── analysis ───────────────────────────────────────────────────────────────────


async def test_detect_bpm_real() -> None:
	from gbedu_audio.analysis import AudioAnalyzer

	with tempfile.TemporaryDirectory() as td:
		p = Path(td) / "click.wav"
		_write_click_wav(p, bpm=120.0, duration=5.0)
		analyzer = AudioAnalyzer()
		bpm = await analyzer.detect_bpm(p)
		assert isinstance(bpm, float)
		assert 30.0 < bpm < 300.0


async def test_detect_key_real() -> None:
	from gbedu_audio.analysis import AudioAnalyzer

	with tempfile.TemporaryDirectory() as td:
		p = Path(td) / "sine.wav"
		_write_sine_wav(p, freq=261.63, duration=5.0)  # C4 pure tone
		analyzer = AudioAnalyzer()
		key = await analyzer.detect_key(p)
		assert isinstance(key, str)
		assert "major" in key or "minor" in key


async def test_detect_energy_range() -> None:
	from gbedu_audio.analysis import AudioAnalyzer

	with tempfile.TemporaryDirectory() as td:
		p = Path(td) / "sine.wav"
		_write_sine_wav(p, duration=3.0)
		analyzer = AudioAnalyzer()
		energy = await analyzer.detect_energy(p)
		assert 0.0 <= energy <= 10.0


async def test_extract_features_keys() -> None:
	from gbedu_audio.analysis import AudioAnalyzer

	with tempfile.TemporaryDirectory() as td:
		p = Path(td) / "sine.wav"
		_write_sine_wav(p, duration=5.0)
		analyzer = AudioAnalyzer()
		features = await analyzer.extract_features(p)
		required = {
			"bpm",
			"key",
			"energy",
			"duration_seconds",
			"sample_rate",
			"mfccs",
			"spectral_centroid_hz",
			"zero_crossing_rate",
		}
		assert required <= set(features.keys())
		assert isinstance(features["mfccs"], list)
		assert len(cast(list[Any], features["mfccs"])) == 13


async def test_find_best_clip_bounds() -> None:
	from gbedu_audio.analysis import AudioAnalyzer

	with tempfile.TemporaryDirectory() as td:
		p = Path(td) / "sine.wav"
		_write_sine_wav(p, duration=10.0)
		analyzer = AudioAnalyzer()
		start, end = await analyzer.find_best_clip(p, duration_seconds=5.0)
		assert 0.0 <= start < end
		assert (end - start) <= 5.0 + 0.1  # small tolerance for rounding


async def test_find_best_clip_short_file() -> None:
	"""When file is shorter than clip duration, should return full range."""
	from gbedu_audio.analysis import AudioAnalyzer

	with tempfile.TemporaryDirectory() as td:
		p = Path(td) / "short.wav"
		_write_sine_wav(p, duration=2.0)
		analyzer = AudioAnalyzer()
		start, end = await analyzer.find_best_clip(p, duration_seconds=15.0)
		assert start == pytest.approx(0.0)
		assert end == pytest.approx(2.0, abs=0.1)


# ── effects ────────────────────────────────────────────────────────────────────


def test_afrobeats_chain_construction() -> None:
	import pedalboard as pedalboard_module
	from gbedu_audio.effects import AudioEffectsChain

	chain = AudioEffectsChain.afrobeats_chain()
	Pedalboard = cast(Any, pedalboard_module).Pedalboard
	assert isinstance(chain, Pedalboard)
	assert len(chain) == 6


async def test_apply_chain_produces_output() -> None:
	from gbedu_audio.effects import AudioEffectsChain

	with tempfile.TemporaryDirectory() as td:
		inp = Path(td) / "input.wav"
		out = Path(td) / "output.wav"
		_write_sine_wav(inp, duration=2.0)

		fx = AudioEffectsChain()
		chain = fx.afrobeats_chain()
		result = await fx.apply_chain(inp, out, chain)

		assert out.exists()
		assert out.stat().st_size > 0
		assert result.processing_time_seconds > 0


# ── conversion (watermark) ─────────────────────────────────────────────────────


async def test_add_watermark_produces_output() -> None:
	from gbedu_audio.conversion import AudioConverter

	with tempfile.TemporaryDirectory() as td:
		inp = Path(td) / "input.wav"
		out = Path(td) / "watermarked.wav"
		_write_sine_wav(inp, duration=35.0)  # long enough to trigger watermark twice

		conv = AudioConverter()
		result_path = await conv.add_watermark(inp, out)

		assert result_path == out
		assert out.exists()
		# Output should be at least as large as input (sine + tone adds content)
		assert out.stat().st_size > 0


async def test_watermark_modifies_audio() -> None:
	"""Watermarked audio should differ from original at the stamp positions."""
	from gbedu_audio.conversion import AudioConverter

	with tempfile.TemporaryDirectory() as td:
		inp = Path(td) / "input.wav"
		out = Path(td) / "wm.wav"
		_write_sine_wav(inp, duration=5.0)

		conv = AudioConverter()
		await conv.add_watermark(inp, out)

		orig, sr = sf.read(str(inp))
		wm, _ = sf.read(str(out))
		# First 100 ms should differ (tone is added at t=0)
		n = int(0.1 * sr)
		assert not np.allclose(orig[:n], wm[:n], atol=1e-6)


# ── mastering fallback ─────────────────────────────────────────────────────────


async def test_mastering_fallback_produces_output() -> None:
	"""
	Master with no reference triggers built-in profile.
	matchering may fail on synthetic audio — fallback normalisation must still produce output.
	"""
	from gbedu_audio.mastering import AudioMastering

	with tempfile.TemporaryDirectory() as td:
		inp = Path(td) / "input.wav"
		out = Path(td) / "mastered.wav"
		_write_sine_wav(inp, duration=3.0)

		mastering = AudioMastering()
		result = await mastering.master(inp, None, out)

		assert out.exists()
		assert out.stat().st_size > 0
		assert result.processing_time_seconds > 0


# ── pipeline result dataclass ──────────────────────────────────────────────────


def test_pipeline_result_dataclass() -> None:
	from gbedu_audio.pipeline import AudioPipelineResult

	r = AudioPipelineResult(
		raw_wav=Path("/tmp/raw.wav"),
		mastered_wav=Path("/tmp/mastered.wav"),
		final_mp3=Path("/tmp/final.mp3"),
		watermarked_mp3=None,
		preview_mp3=Path("/tmp/preview.mp3"),
		stems={"drums": Path("/tmp/drums.wav")},
		analysis={"bpm": 120.0},
		errors={"stems": "model not loaded"},
	)
	assert r.watermarked_mp3 is None
	assert r.stems["drums"] == Path("/tmp/drums.wav")
	assert r.errors["stems"] == "model not loaded"
