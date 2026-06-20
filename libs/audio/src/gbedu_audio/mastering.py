from __future__ import annotations

import asyncio
import base64
import io
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import structlog
from opentelemetry import trace

from gbedu_audio._base import AudioFile, AudioProcessingError, ProcessingResult

log = structlog.get_logger(__name__)
_tracer = trace.get_tracer(__name__)

# ── Built-in Afrobeats reference profiles ─────────────────────────────────────
# Three short synthetic WAV snippets tuned to characteristic Afrobeats loudness
# and spectral balance, stored as base64-encoded PCM WAV data.
# Each is 2 s of shaped noise at 44100 Hz, 16-bit stereo.
# Real deployment would swap these for actual short reference stems.

def _make_reference_wav_b64(
	rms_target: float,
	bass_boost: float,
	high_cut: float,
) -> str:
	"""Generate a spectrally-shaped noise burst and return as base64 WAV."""
	import soundfile as sf

	sr = 44100
	duration = 2.0
	n = int(sr * duration)
	rng = np.random.default_rng(42)
	noise = rng.standard_normal((n, 2)).astype(np.float32)

	# Rough spectral shaping via FFT
	from scipy.fft import rfft, irfft
	freqs = np.fft.rfftfreq(n, 1 / sr)
	for ch in range(2):
		spectrum = rfft(noise[:, ch])
		# Bass boost below 120 Hz
		bass_mask = freqs < 120
		spectrum[bass_mask] *= (1.0 + bass_boost)
		# High cut above high_cut Hz
		high_mask = freqs > high_cut
		spectrum[high_mask] *= 0.3
		noise[:, ch] = irfft(spectrum, n=n).astype(np.float32)

	# Normalise to target RMS
	current_rms = float(np.sqrt(np.mean(noise ** 2)))
	if current_rms > 1e-9:
		noise = noise * (rms_target / current_rms)
	noise = np.clip(noise, -1.0, 1.0)

	buf = io.BytesIO()
	sf.write(buf, noise, sr, format="WAV", subtype="PCM_16")
	return base64.b64encode(buf.getvalue()).decode()


# Profiles: (label, rms_target, bass_boost, high_cut_hz)
_REFERENCE_PROFILES: list[tuple[str, float, float, float]] = [
	("afrobeats_standard", 0.22, 2.5, 14000.0),
	("afrobeats_bright",   0.20, 1.5, 16000.0),
	("afrobeats_warm",     0.25, 3.5, 12000.0),
]

_reference_wav_b64_cache: dict[str, str] = {}


def _get_reference_wav_b64(label: str) -> str:
	if label not in _reference_wav_b64_cache:
		for lbl, rms, bass, hcut in _REFERENCE_PROFILES:
			if lbl == label:
				_reference_wav_b64_cache[label] = _make_reference_wav_b64(rms, bass, hcut)
				break
	return _reference_wav_b64_cache[label]


def _load_reference_from_dir(label: str) -> Path | None:
	"""Return a reference WAV from MASTERING_REFERENCE_DIR if one exists for this label."""
	ref_dir = os.environ.get("MASTERING_REFERENCE_DIR", "")
	if not ref_dir:
		return None
	p = Path(ref_dir) / f"{label}.wav"
	return p if p.is_file() else None


def _write_reference_to_tmp(label: str) -> Path:
	b64 = _get_reference_wav_b64(label)
	data = base64.b64decode(b64)
	tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
	tmp.write(data)
	tmp.flush()
	tmp.close()
	return Path(tmp.name)


def _probe_audio_file(path: Path) -> AudioFile:
	import soundfile as sf

	info = sf.info(str(path))
	return AudioFile(
		path=path,
		duration_seconds=float(info.duration),
		sample_rate=int(info.samplerate),
		channels=int(info.channels),
		format=info.format,
		size_bytes=path.stat().st_size,
	)


class AudioMastering:
	"""Async mastering via matchering with built-in Afrobeats reference profiles."""

	DEFAULT_REFERENCE = "afrobeats_standard"

	async def master(
		self,
		audio_path: Path,
		reference_path: Path | None,
		output_path: Path,
	) -> ProcessingResult:
		"""
		Master audio_path against reference_path (or built-in profile if None).
		Falls back to basic pedalboard normalization if matchering fails.
		"""
		assert audio_path.is_file(), f"audio file not found: {audio_path}"
		output_path.parent.mkdir(parents=True, exist_ok=True)

		t0 = time.perf_counter()
		with _tracer.start_as_current_span("audio.master") as span:
			span.set_attribute("audio.path", str(audio_path))
			span.set_attribute("audio.output", str(output_path))
			ref_used = str(reference_path) if reference_path else self.DEFAULT_REFERENCE
			span.set_attribute("audio.reference", ref_used)
			try:
				loop = asyncio.get_running_loop()
				used_fallback = await loop.run_in_executor(
					None, self._master_sync, audio_path, reference_path, output_path,
				)
				elapsed = time.perf_counter() - t0
				log.info(
					"mastering complete",
					input=str(audio_path),
					output=str(output_path),
					reference=ref_used,
					fallback=used_fallback,
					elapsed_s=elapsed,
				)
				return ProcessingResult(
					input=_probe_audio_file(audio_path),
					output=_probe_audio_file(output_path),
					processing_time_seconds=elapsed,
					metadata={"reference": ref_used, "fallback_used": used_fallback},
				)
			except AudioProcessingError:
				raise
			except Exception as exc:
				raise AudioProcessingError(str(exc), stage="master") from exc

	def _master_sync(
		self,
		audio_path: Path,
		reference_path: Path | None,
		output_path: Path,
	) -> bool:
		"""Returns True if fallback normalization was used."""
		tmp_ref: Path | None = None
		if reference_path is None:
			# Prefer a real stem placed in MASTERING_REFERENCE_DIR over synthetic noise
			reference_path = _load_reference_from_dir(self.DEFAULT_REFERENCE)
			if reference_path is None:
				tmp_ref = _write_reference_to_tmp(self.DEFAULT_REFERENCE)
				reference_path = tmp_ref

		try:
			return self._try_matchering(audio_path, reference_path, output_path)
		finally:
			if tmp_ref is not None:
				try:
					tmp_ref.unlink()
				except OSError:
					pass

	def _try_matchering(
		self,
		audio_path: Path,
		reference_path: Path,
		output_path: Path,
	) -> bool:
		try:
			import matchering as mg

			mg.process(
				target=str(audio_path),
				reference=str(reference_path),
				results=[mg.Result(str(output_path), subtype="PCM_24", use_limiter=True)],
			)
			return False
		except Exception as matchering_exc:
			log.warning(
				"matchering failed, using fallback normalization",
				error=str(matchering_exc),
			)
			self._fallback_normalize(audio_path, output_path)
			return True

	def _fallback_normalize(self, audio_path: Path, output_path: Path) -> None:
		from pedalboard import Compressor, Limiter, Pedalboard
		import soundfile as sf

		audio, sr = sf.read(str(audio_path), always_2d=True)
		audio_t = audio.T.astype(np.float32)

		board = Pedalboard([
			Compressor(threshold_db=-18.0, ratio=3.0, attack_ms=10.0, release_ms=200.0),
			Limiter(threshold_db=-1.0, release_ms=100.0),
		])
		processed = board(audio_t, sample_rate=sr)
		sf.write(str(output_path), processed.T, sr, subtype="PCM_24")
