from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, cast

import numpy as np
import pedalboard as pedalboard_module
import structlog
from opentelemetry import trace
from pedalboard import (
	Compressor,
	HighpassFilter,
	HighShelfFilter,
	Limiter,
	LowShelfFilter,
	PeakFilter,
)

from gbedu_audio._base import AudioFile, AudioProcessingError, ProcessingResult

log = structlog.get_logger(__name__)
_tracer = trace.get_tracer(__name__)


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


class AudioEffectsChain:
	"""Pedalboard-based effects chain for Afrobeats mastering."""

	@staticmethod
	def afrobeats_chain() -> Any:
		"""
		Standard Afrobeats mastering chain:
		  1. High-pass at 40 Hz (remove sub-rumble)
		  2. Compressor (glue, moderate ratio)
		  3. EQ: bass boost 60-120 Hz, presence 2-5 kHz, air 10-16 kHz
		  4. Brickwall limiter at -1 dBFS

		EQ implemented as three pedalboard shelf/peak stages:
		  - LowShelfFilter boost at 80 Hz (centre of 60-120 Hz band)
		  - PeakFilter boost centred at 3.5 kHz (presence)
		  - HighShelfFilter boost at 12 kHz (air)
		"""
		return cast(Any, pedalboard_module).Pedalboard(
			[
				HighpassFilter(cutoff_frequency_hz=40.0),
				Compressor(
					threshold_db=-18.0,
					ratio=4.0,
					attack_ms=5.0,
					release_ms=100.0,
				),
				# Bass: +3 dB shelf centred at 80 Hz
				LowShelfFilter(cutoff_frequency_hz=80.0, gain_db=3.0, q=0.707),
				# Presence: +2 dB peak at 3.5 kHz, wide Q
				PeakFilter(cutoff_frequency_hz=3500.0, gain_db=2.0, q=1.0),
				# Air: +2.5 dB shelf at 12 kHz
				HighShelfFilter(cutoff_frequency_hz=12000.0, gain_db=2.5, q=0.707),
				Limiter(threshold_db=-1.0, release_ms=100.0),
			]
		)

	async def apply_chain(
		self,
		audio_path: Path,
		output_path: Path,
		chain: Any,
	) -> ProcessingResult:
		assert audio_path.is_file(), f"audio file not found: {audio_path}"
		output_path.parent.mkdir(parents=True, exist_ok=True)

		t0 = time.perf_counter()
		with _tracer.start_as_current_span("audio.apply_effects_chain") as span:
			span.set_attribute("audio.path", str(audio_path))
			span.set_attribute("audio.output", str(output_path))
			try:
				loop = asyncio.get_running_loop()
				await loop.run_in_executor(
					None,
					self._apply_chain_sync,
					audio_path,
					output_path,
					chain,
				)
				elapsed = time.perf_counter() - t0
				log.info(
					"effects chain applied",
					input=str(audio_path),
					output=str(output_path),
					elapsed_s=elapsed,
				)
				return ProcessingResult(
					input=_probe_audio_file(audio_path),
					output=_probe_audio_file(output_path),
					processing_time_seconds=elapsed,
					metadata={"chain_plugins": [type(p).__name__ for p in chain]},
				)
			except AudioProcessingError:
				raise
			except Exception as exc:
				raise AudioProcessingError(str(exc), stage="apply_effects_chain") from exc

	def _apply_chain_sync(
		self,
		audio_path: Path,
		output_path: Path,
		chain: Any,
	) -> None:
		import soundfile as sf

		audio, sr = sf.read(str(audio_path), always_2d=True)
		# pedalboard expects (channels, samples) float32
		audio_t = audio.T.astype(np.float32)
		processed = chain(audio_t, sample_rate=sr)
		# Back to (samples, channels) for soundfile
		sf.write(str(output_path), processed.T, sr, subtype="PCM_24")
