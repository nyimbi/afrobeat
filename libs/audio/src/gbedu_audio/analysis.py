from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import librosa
import numpy as np
import structlog
from opentelemetry import trace
from tenacity import retry, stop_after_attempt, wait_exponential

from gbedu_audio._base import AudioFile, AudioProcessingError

log = structlog.get_logger(__name__)
_tracer = trace.get_tracer(__name__)

# Key names indexed by Krumhansl-Schmuckler profile
_PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_KEY_MODES = ["major", "minor"]


def _load_audio(audio_path: Path) -> tuple[np.ndarray, int]:
	assert audio_path.exists(), f"audio file not found: {audio_path}"
	y, sr = librosa.load(str(audio_path), sr=None, mono=True)
	return y, int(sr)


class AudioAnalyzer:
	"""Async audio analysis — BPM, key, energy, features, clip selection."""

	@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
	async def detect_bpm(self, audio_path: Path) -> float:
		if not audio_path.is_file():
			raise AudioProcessingError(f"not a file: {audio_path}", stage="detect_bpm")
		t0 = time.perf_counter()
		with _tracer.start_as_current_span("audio.detect_bpm") as span:
			span.set_attribute("audio.path", str(audio_path))
			try:
				loop = asyncio.get_running_loop()
				bpm = await loop.run_in_executor(None, self._detect_bpm_sync, audio_path)
				elapsed = time.perf_counter() - t0
				log.info("bpm detected", path=str(audio_path), bpm=bpm, elapsed_s=elapsed)
				span.set_attribute("audio.bpm", bpm)
				return bpm
			except Exception as exc:
				span.record_exception(exc)
				raise AudioProcessingError(str(exc), stage="detect_bpm") from exc

	def _detect_bpm_sync(self, audio_path: Path) -> float:
		y, sr = _load_audio(audio_path)
		tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
		# beat_track returns ndarray in newer librosa — coerce to scalar
		if hasattr(tempo, "__len__"):
			tempo = float(tempo[0]) if len(tempo) > 0 else 120.0
		return float(tempo)

	@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
	async def detect_key(self, audio_path: Path) -> str:
		assert audio_path.is_file(), f"not a file: {audio_path}"
		t0 = time.perf_counter()
		with _tracer.start_as_current_span("audio.detect_key") as span:
			span.set_attribute("audio.path", str(audio_path))
			try:
				loop = asyncio.get_running_loop()
				key = await loop.run_in_executor(None, self._detect_key_sync, audio_path)
				elapsed = time.perf_counter() - t0
				log.info("key detected", path=str(audio_path), key=key, elapsed_s=elapsed)
				span.set_attribute("audio.key", key)
				return key
			except Exception as exc:
				span.record_exception(exc)
				raise AudioProcessingError(str(exc), stage="detect_key") from exc

	def _detect_key_sync(self, audio_path: Path) -> str:
		y, sr = _load_audio(audio_path)

		# Chromagram-based key detection (HPCP-like via librosa chroma_cqt)
		chroma = librosa.feature.chroma_cqt(y=y, sr=sr, bins_per_octave=36)
		chroma_mean = chroma.mean(axis=1)  # shape (12,)

		# Krumhansl-Schmuckler key profiles
		major_profile = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
		minor_profile = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

		best_corr = -np.inf
		best_key = "C major"
		for shift in range(12):
			major_corr = float(np.corrcoef(chroma_mean, np.roll(major_profile, shift))[0, 1])
			minor_corr = float(np.corrcoef(chroma_mean, np.roll(minor_profile, shift))[0, 1])
			if major_corr > best_corr:
				best_corr = major_corr
				best_key = f"{_PITCH_CLASSES[shift]} major"
			if minor_corr > best_corr:
				best_corr = minor_corr
				best_key = f"{_PITCH_CLASSES[shift]} minor"

		return best_key

	@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
	async def detect_energy(self, audio_path: Path) -> float:
		assert audio_path.is_file(), f"not a file: {audio_path}"
		t0 = time.perf_counter()
		with _tracer.start_as_current_span("audio.detect_energy") as span:
			span.set_attribute("audio.path", str(audio_path))
			try:
				loop = asyncio.get_running_loop()
				energy = await loop.run_in_executor(None, self._detect_energy_sync, audio_path)
				elapsed = time.perf_counter() - t0
				log.info("energy detected", path=str(audio_path), energy=energy, elapsed_s=elapsed)
				span.set_attribute("audio.energy", energy)
				return energy
			except Exception as exc:
				span.record_exception(exc)
				raise AudioProcessingError(str(exc), stage="detect_energy") from exc

	def _detect_energy_sync(self, audio_path: Path) -> float:
		y, _ = _load_audio(audio_path)
		rms = float(np.sqrt(np.mean(y ** 2)))
		# Map RMS (typ. 0.0–0.5) onto 0–10 scale with logarithmic feel
		# 0.5 RMS == 10, silence == 0
		rms_clamped = np.clip(rms, 1e-9, 0.5)
		energy = 10.0 * (np.log10(rms_clamped / 1e-9) / np.log10(0.5 / 1e-9))
		return float(np.clip(energy, 0.0, 10.0))

	@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
	async def extract_features(self, audio_path: Path) -> dict[str, Any]:
		assert audio_path.is_file(), f"not a file: {audio_path}"
		t0 = time.perf_counter()
		with _tracer.start_as_current_span("audio.extract_features") as span:
			span.set_attribute("audio.path", str(audio_path))
			try:
				loop = asyncio.get_running_loop()
				features = await loop.run_in_executor(None, self._extract_features_sync, audio_path)
				elapsed = time.perf_counter() - t0
				log.info("features extracted", path=str(audio_path), elapsed_s=elapsed)
				return features
			except Exception as exc:
				span.record_exception(exc)
				raise AudioProcessingError(str(exc), stage="extract_features") from exc

	def _extract_features_sync(self, audio_path: Path) -> dict[str, Any]:
		y, sr = _load_audio(audio_path)
		duration = float(librosa.get_duration(y=y, sr=sr))

		tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
		bpm = float(tempo[0]) if hasattr(tempo, "__len__") else float(tempo)

		chroma = librosa.feature.chroma_cqt(y=y, sr=sr, bins_per_octave=36)
		chroma_mean = chroma.mean(axis=1)
		major_profile = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
		minor_profile = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
		best_corr = -np.inf
		key = "C major"
		for shift in range(12):
			for profile, mode in [(major_profile, "major"), (minor_profile, "minor")]:
				c = float(np.corrcoef(chroma_mean, np.roll(profile, shift))[0, 1])
				if c > best_corr:
					best_corr = c
					key = f"{_PITCH_CLASSES[shift]} {mode}"

		rms = float(np.sqrt(np.mean(y ** 2)))
		rms_clamped = np.clip(rms, 1e-9, 0.5)
		energy = float(np.clip(
			10.0 * (np.log10(rms_clamped / 1e-9) / np.log10(0.5 / 1e-9)),
			0.0, 10.0,
		))

		mfccs = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
		mfcc_means = mfccs.mean(axis=1).tolist()

		spec_centroid = float(librosa.feature.spectral_centroid(y=y, sr=sr).mean())
		zcr = float(librosa.feature.zero_crossing_rate(y).mean())

		return {
			"bpm": bpm,
			"key": key,
			"energy": energy,
			"duration_seconds": duration,
			"sample_rate": sr,
			"mfccs": mfcc_means,
			"spectral_centroid_hz": spec_centroid,
			"zero_crossing_rate": zcr,
		}

	@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
	async def find_best_clip(
		self,
		audio_path: Path,
		duration_seconds: float = 15.0,
	) -> tuple[float, float]:
		"""Return (start_s, end_s) of the highest-energy segment of given length."""
		assert audio_path.is_file(), f"not a file: {audio_path}"
		assert duration_seconds > 0, "clip duration must be positive"
		t0 = time.perf_counter()
		with _tracer.start_as_current_span("audio.find_best_clip") as span:
			span.set_attribute("audio.path", str(audio_path))
			span.set_attribute("audio.clip_duration", duration_seconds)
			try:
				loop = asyncio.get_running_loop()
				result = await loop.run_in_executor(
					None, self._find_best_clip_sync, audio_path, duration_seconds,
				)
				elapsed = time.perf_counter() - t0
				log.info("best clip found", path=str(audio_path), start=result[0], end=result[1], elapsed_s=elapsed)
				return result
			except Exception as exc:
				span.record_exception(exc)
				raise AudioProcessingError(str(exc), stage="find_best_clip") from exc

	def _find_best_clip_sync(self, audio_path: Path, duration_seconds: float) -> tuple[float, float]:
		y, sr = _load_audio(audio_path)
		total_duration = len(y) / sr

		if total_duration <= duration_seconds:
			return 0.0, total_duration

		hop_length = 512
		frame_length = 2048
		rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
		times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)

		window_frames = int(duration_seconds * sr / hop_length)
		if window_frames >= len(rms):
			return 0.0, total_duration

		# Sliding-window sum to find highest-energy segment
		cumsum = np.cumsum(rms)
		window_sums = cumsum[window_frames:] - cumsum[:-window_frames]
		best_start_frame = int(np.argmax(window_sums))

		start_s = float(times[best_start_frame])
		end_s = min(start_s + duration_seconds, total_duration)
		return start_s, end_s
