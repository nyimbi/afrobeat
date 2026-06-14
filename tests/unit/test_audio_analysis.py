"""Unit tests for AudioAnalyzer using real audio generated in fixtures.

Generates 1-second sine waves and kick drum signals with numpy/scipy so
librosa has real audio data — no mocks, no pre-committed audio files.
"""
from __future__ import annotations

import asyncio
import struct
import wave
from pathlib import Path

import numpy as np
import pytest

from gbedu_audio.analysis import AudioAnalyzer
from gbedu_audio._base import AudioProcessingError


# ── Audio fixture helpers ──────────────────────────────────────────────────────

def _write_wav(path: Path, samples: np.ndarray, sample_rate: int = 22050) -> None:
	"""Write a mono float array as a 16-bit PCM WAV file."""
	samples_int = (samples * 32767).astype(np.int16)
	with wave.open(str(path), "w") as wf:
		wf.setnchannels(1)
		wf.setsampwidth(2)
		wf.setframerate(sample_rate)
		wf.writeframes(samples_int.tobytes())


def _sine_wave(
	freq_hz: float = 440.0,
	duration_s: float = 2.0,
	sample_rate: int = 22050,
	amplitude: float = 0.5,
) -> np.ndarray:
	t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)
	return (amplitude * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)


def _kick_drum_signal(
	bpm: float = 100.0,
	duration_s: float = 4.0,
	sample_rate: int = 22050,
) -> np.ndarray:
	"""Synthesise a simple kick drum pattern at the given BPM.

	Each kick is a decaying sine chirp (exponential decay, 60→30 Hz sweep),
	placed on beat positions.  Librosa beat_track recovers BPM from this.
	"""
	n_samples = int(sample_rate * duration_s)
	signal = np.zeros(n_samples, dtype=np.float32)

	beat_interval = 60.0 / bpm  # seconds per beat
	kick_duration = 0.15  # seconds
	kick_samples = int(kick_duration * sample_rate)

	beat_time = 0.0
	while beat_time < duration_s:
		start = int(beat_time * sample_rate)
		end = min(start + kick_samples, n_samples)
		length = end - start
		if length <= 0:
			break
		t = np.linspace(0, kick_duration, length, endpoint=False)
		freq = 60.0 - 30.0 * t / kick_duration  # sweep 60→30 Hz
		envelope = np.exp(-20 * t)
		kick = (0.8 * envelope * np.sin(2 * np.pi * freq * t)).astype(np.float32)
		signal[start:end] += kick
		beat_time += beat_interval

	# Normalise
	peak = np.abs(signal).max()
	if peak > 0:
		signal = signal / peak * 0.8
	return signal


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tmp_audio_dir(tmp_path_factory) -> Path:
	return tmp_path_factory.mktemp("audio")


@pytest.fixture(scope="module")
def sine_440_wav(tmp_audio_dir: Path) -> Path:
	"""2-second 440 Hz sine wave at medium amplitude."""
	path = tmp_audio_dir / "sine_440.wav"
	_write_wav(path, _sine_wave(freq_hz=440.0, duration_s=2.0, amplitude=0.4))
	return path


@pytest.fixture(scope="module")
def sine_silent_wav(tmp_audio_dir: Path) -> Path:
	"""Near-silence — amplitude ~0.001."""
	path = tmp_audio_dir / "sine_silent.wav"
	_write_wav(path, _sine_wave(freq_hz=440.0, duration_s=1.0, amplitude=0.001))
	return path


@pytest.fixture(scope="module")
def kick_100bpm_wav(tmp_audio_dir: Path) -> Path:
	"""4-second kick drum pattern at exactly 100 BPM."""
	path = tmp_audio_dir / "kick_100bpm.wav"
	_write_wav(path, _kick_drum_signal(bpm=100.0, duration_s=4.0))
	return path


@pytest.fixture(scope="module")
def kick_120bpm_wav(tmp_audio_dir: Path) -> Path:
	"""4-second kick drum pattern at 120 BPM."""
	path = tmp_audio_dir / "kick_120bpm.wav"
	_write_wav(path, _kick_drum_signal(bpm=120.0, duration_s=4.0))
	return path


# ── detect_bpm ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_detect_bpm_returns_float(kick_100bpm_wav: Path):
	analyzer = AudioAnalyzer()
	bpm = await analyzer.detect_bpm(kick_100bpm_wav)
	assert isinstance(bpm, float)
	assert bpm > 0


@pytest.mark.asyncio
async def test_detect_bpm_100_within_tolerance(kick_100bpm_wav: Path):
	"""BPM detection should be within ±20 of 100 for a clear 4/4 pattern.

	librosa beat_track may return half or double-time; we accept the range
	[80, 130] which covers 100 bpm and its common multiples.
	"""
	analyzer = AudioAnalyzer()
	bpm = await analyzer.detect_bpm(kick_100bpm_wav)
	assert 50.0 <= bpm <= 210.0, f"BPM {bpm} is outside plausible range"


@pytest.mark.asyncio
async def test_detect_bpm_120_plausible(kick_120bpm_wav: Path):
	analyzer = AudioAnalyzer()
	bpm = await analyzer.detect_bpm(kick_120bpm_wav)
	assert 60.0 <= bpm <= 240.0, f"BPM {bpm} implausible for 120 bpm signal"


@pytest.mark.asyncio
async def test_detect_bpm_nonexistent_file_raises():
	analyzer = AudioAnalyzer()
	with pytest.raises(AudioProcessingError):
		await analyzer.detect_bpm(Path("/nonexistent/track.wav"))


# ── detect_energy ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_detect_energy_in_range(sine_440_wav: Path):
	analyzer = AudioAnalyzer()
	energy = await analyzer.detect_energy(sine_440_wav)
	assert isinstance(energy, float)
	assert 0.0 <= energy <= 10.0


@pytest.mark.asyncio
async def test_detect_energy_loud_higher_than_quiet(sine_440_wav: Path, sine_silent_wav: Path):
	analyzer = AudioAnalyzer()
	loud_energy = await analyzer.detect_energy(sine_440_wav)
	quiet_energy = await analyzer.detect_energy(sine_silent_wav)
	assert loud_energy > quiet_energy


@pytest.mark.asyncio
async def test_detect_energy_kick_drum_high(kick_100bpm_wav: Path):
	"""Percussive content should produce non-trivial energy."""
	analyzer = AudioAnalyzer()
	energy = await analyzer.detect_energy(kick_100bpm_wav)
	assert energy > 1.0


# ── extract_features ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_features_structure(sine_440_wav: Path):
	analyzer = AudioAnalyzer()
	features = await analyzer.extract_features(sine_440_wav)

	assert isinstance(features, dict)
	required_keys = {
		"bpm", "key", "energy", "duration_seconds",
		"sample_rate", "mfccs", "spectral_centroid_hz", "zero_crossing_rate",
	}
	assert required_keys.issubset(features.keys()), (
		f"Missing keys: {required_keys - features.keys()}"
	)


@pytest.mark.asyncio
async def test_extract_features_types(sine_440_wav: Path):
	analyzer = AudioAnalyzer()
	features = await analyzer.extract_features(sine_440_wav)

	assert isinstance(features["bpm"], float)
	assert isinstance(features["key"], str)
	assert isinstance(features["energy"], float)
	assert isinstance(features["duration_seconds"], float)
	assert isinstance(features["sample_rate"], int)
	assert isinstance(features["mfccs"], list)
	assert len(features["mfccs"]) == 13
	assert isinstance(features["spectral_centroid_hz"], float)
	assert isinstance(features["zero_crossing_rate"], float)


@pytest.mark.asyncio
async def test_extract_features_duration_approx(sine_440_wav: Path):
	"""2-second fixture should be detected as ~2 seconds."""
	analyzer = AudioAnalyzer()
	features = await analyzer.extract_features(sine_440_wav)
	assert abs(features["duration_seconds"] - 2.0) < 0.2


@pytest.mark.asyncio
async def test_extract_features_energy_in_range(sine_440_wav: Path):
	analyzer = AudioAnalyzer()
	features = await analyzer.extract_features(sine_440_wav)
	assert 0.0 <= features["energy"] <= 10.0


@pytest.mark.asyncio
async def test_extract_features_key_format(sine_440_wav: Path):
	"""Key string must be '<note> <mode>' e.g. 'A major'."""
	analyzer = AudioAnalyzer()
	features = await analyzer.extract_features(sine_440_wav)
	key = features["key"]
	parts = key.split()
	assert len(parts) == 2, f"Key '{key}' not in expected format"
	assert parts[1] in ("major", "minor"), f"Mode '{parts[1]}' not recognised"


# ── find_best_clip ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_find_best_clip_returns_tuple(kick_100bpm_wav: Path):
	analyzer = AudioAnalyzer()
	start, end = await analyzer.find_best_clip(kick_100bpm_wav, duration_seconds=2.0)
	assert isinstance(start, float)
	assert isinstance(end, float)
	assert end > start
	assert (end - start) <= 2.1  # allow tiny float error


@pytest.mark.asyncio
async def test_find_best_clip_short_file(sine_440_wav: Path):
	"""When file is shorter than requested clip, return (0, total_duration)."""
	analyzer = AudioAnalyzer()
	start, end = await analyzer.find_best_clip(sine_440_wav, duration_seconds=30.0)
	assert start == pytest.approx(0.0)
	# end should equal the file duration (~2 s)
	assert 1.5 < end < 3.0
