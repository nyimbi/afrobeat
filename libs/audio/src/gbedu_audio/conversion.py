from __future__ import annotations

import asyncio
import math
import time
from pathlib import Path

import numpy as np
import structlog
from opentelemetry import trace
from tenacity import retry, stop_after_attempt, wait_exponential

from gbedu_audio._base import AudioFile, AudioProcessingError, ProcessingResult
from gbedu_audio.analysis import AudioAnalyzer

log = structlog.get_logger(__name__)
_tracer = trace.get_tracer(__name__)

_analyzer = AudioAnalyzer()


def _probe_audio_file(path: Path) -> AudioFile:  # pragma: no cover
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


class AudioConverter:
	"""Async audio format conversion, loudness normalization, watermarking, and preview clipping."""

	# ── Format conversion ──────────────────────────────────────────────────────

	@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
	async def to_mp3(self, wav_path: Path, bitrate: str = "320k") -> Path:  # pragma: no cover
		assert wav_path.is_file(), f"WAV file not found: {wav_path}"
		out = wav_path.with_suffix(".mp3")
		t0 = time.perf_counter()
		with _tracer.start_as_current_span("audio.to_mp3") as span:
			span.set_attribute("audio.path", str(wav_path))
			span.set_attribute("audio.bitrate", bitrate)
			try:
				loop = asyncio.get_running_loop()
				await loop.run_in_executor(None, self._to_mp3_sync, wav_path, out, bitrate)
				log.info("converted to mp3", input=str(wav_path), output=str(out), bitrate=bitrate, elapsed_s=time.perf_counter() - t0)
				return out
			except AudioProcessingError:
				raise
			except Exception as exc:
				raise AudioProcessingError(str(exc), stage="to_mp3") from exc

	def _to_mp3_sync(self, wav_path: Path, out: Path, bitrate: str) -> None:  # pragma: no cover
		import ffmpeg

		(
			ffmpeg
			.input(str(wav_path))
			.output(str(out), audio_bitrate=bitrate, acodec="libmp3lame")
			.overwrite_output()
			.run(quiet=True)
		)

	@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
	async def to_wav(  # pragma: no cover
		self,
		mp3_path: Path,
		sample_rate: int = 44100,
		bit_depth: int = 24,
	) -> Path:
		assert mp3_path.is_file(), f"input file not found: {mp3_path}"
		out = mp3_path.with_suffix(".wav")
		t0 = time.perf_counter()
		with _tracer.start_as_current_span("audio.to_wav") as span:
			span.set_attribute("audio.path", str(mp3_path))
			span.set_attribute("audio.sample_rate", sample_rate)
			span.set_attribute("audio.bit_depth", bit_depth)
			try:
				loop = asyncio.get_running_loop()
				await loop.run_in_executor(None, self._to_wav_sync, mp3_path, out, sample_rate, bit_depth)
				log.info("converted to wav", input=str(mp3_path), output=str(out), elapsed_s=time.perf_counter() - t0)
				return out
			except AudioProcessingError:
				raise
			except Exception as exc:
				raise AudioProcessingError(str(exc), stage="to_wav") from exc

	def _to_wav_sync(self, src: Path, out: Path, sample_rate: int, bit_depth: int) -> None:  # pragma: no cover
		import ffmpeg

		subtype_map = {16: "s16le", 24: "s24le", 32: "s32le"}
		aformat = subtype_map.get(bit_depth, "s24le")
		(
			ffmpeg
			.input(str(src))
			.output(
				str(out),
				ar=sample_rate,
				acodec="pcm_" + aformat,
				format="wav",
			)
			.overwrite_output()
			.run(quiet=True)
		)

	# ── Watermarking ───────────────────────────────────────────────────────────

	@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
	async def add_watermark(self, audio_path: Path, output_path: Path) -> Path:
		"""Embed a 1 kHz sine tone at -40 dBFS for 100 ms every 30 s."""
		assert audio_path.is_file(), f"audio file not found: {audio_path}"
		output_path.parent.mkdir(parents=True, exist_ok=True)
		t0 = time.perf_counter()
		with _tracer.start_as_current_span("audio.add_watermark") as span:
			span.set_attribute("audio.path", str(audio_path))
			span.set_attribute("audio.output", str(output_path))
			try:
				loop = asyncio.get_running_loop()
				await loop.run_in_executor(None, self._add_watermark_sync, audio_path, output_path)
				log.info("watermark added", input=str(audio_path), output=str(output_path), elapsed_s=time.perf_counter() - t0)
				return output_path
			except AudioProcessingError:  # pragma: no cover
				raise
			except Exception as exc:  # pragma: no cover
				raise AudioProcessingError(str(exc), stage="add_watermark") from exc

	def _add_watermark_sync(self, audio_path: Path, output_path: Path) -> None:
		import soundfile as sf

		audio, sr = sf.read(str(audio_path), always_2d=True)
		total_samples = audio.shape[0]
		channels = audio.shape[1]

		# 1 kHz tone at -40 dBFS, 100 ms
		amplitude = 10 ** (-40 / 20)
		tone_samples = int(0.1 * sr)
		t = np.linspace(0, 0.1, tone_samples, endpoint=False)
		tone = (amplitude * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)

		# Stamp every 30 s
		interval_samples = int(30 * sr)
		result = audio.copy().astype(np.float32)
		for start in range(0, total_samples, interval_samples):
			end = min(start + tone_samples, total_samples)
			count = end - start
			for ch in range(channels):
				result[start:end, ch] += tone[:count]

		result = np.clip(result, -1.0, 1.0)
		sf.write(str(output_path), result, sr, subtype="PCM_24")

	# ── Loudness normalization ─────────────────────────────────────────────────

	@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
	async def normalize_loudness(  # pragma: no cover
		self,
		audio_path: Path,
		target_lufs: float = -14.0,
	) -> Path:
		"""Normalize to target integrated loudness (EBU R128 / broadcast standard)."""
		assert audio_path.is_file(), f"audio file not found: {audio_path}"
		out = audio_path.parent / (audio_path.stem + "_norm" + audio_path.suffix)
		t0 = time.perf_counter()
		with _tracer.start_as_current_span("audio.normalize_loudness") as span:
			span.set_attribute("audio.path", str(audio_path))
			span.set_attribute("audio.target_lufs", target_lufs)
			try:
				loop = asyncio.get_running_loop()
				await loop.run_in_executor(None, self._normalize_loudness_sync, audio_path, out, target_lufs)
				log.info("loudness normalized", input=str(audio_path), output=str(out), target_lufs=target_lufs, elapsed_s=time.perf_counter() - t0)
				return out
			except AudioProcessingError:
				raise
			except Exception as exc:
				raise AudioProcessingError(str(exc), stage="normalize_loudness") from exc

	def _normalize_loudness_sync(self, audio_path: Path, out: Path, target_lufs: float) -> None:  # pragma: no cover
		import ffmpeg

		# ffmpeg loudnorm filter — two-pass would be ideal but one-pass is accurate enough here
		(
			ffmpeg
			.input(str(audio_path))
			.filter("loudnorm", I=target_lufs, TP=-1.5, LRA=11)
			.output(str(out), acodec="pcm_s24le", format="wav")
			.overwrite_output()
			.run(quiet=True)
		)

	# ── Preview clip ───────────────────────────────────────────────────────────

	@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
	async def create_preview_clip(  # pragma: no cover
		self,
		audio_path: Path,
		output_path: Path,
		duration: float = 15.0,
	) -> Path:
		"""Extract the highest-energy segment as a preview clip."""
		assert audio_path.is_file(), f"audio file not found: {audio_path}"
		output_path.parent.mkdir(parents=True, exist_ok=True)
		t0 = time.perf_counter()
		with _tracer.start_as_current_span("audio.create_preview_clip") as span:
			span.set_attribute("audio.path", str(audio_path))
			span.set_attribute("audio.output", str(output_path))
			span.set_attribute("audio.clip_duration", duration)
			try:
				start_s, end_s = await _analyzer.find_best_clip(audio_path, duration)
				loop = asyncio.get_running_loop()
				await loop.run_in_executor(
					None, self._extract_clip_sync, audio_path, output_path, start_s, end_s,
				)
				log.info(
					"preview clip created",
					input=str(audio_path),
					output=str(output_path),
					start_s=start_s,
					end_s=end_s,
					elapsed_s=time.perf_counter() - t0,
				)
				return output_path
			except AudioProcessingError:
				raise
			except Exception as exc:
				raise AudioProcessingError(str(exc), stage="create_preview_clip") from exc

	def _extract_clip_sync(  # pragma: no cover
		self,
		audio_path: Path,
		output_path: Path,
		start_s: float,
		end_s: float,
	) -> None:
		import ffmpeg

		clip_duration = end_s - start_s
		(
			ffmpeg
			.input(str(audio_path), ss=start_s, t=clip_duration)
			.output(str(output_path), acodec="libmp3lame", audio_bitrate="320k")
			.overwrite_output()
			.run(quiet=True)
		)
