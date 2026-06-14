from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
from opentelemetry import trace

from gbedu_audio._base import AudioFile, AudioProcessingError
from gbedu_audio.analysis import AudioAnalyzer
from gbedu_audio.conversion import AudioConverter
from gbedu_audio.effects import AudioEffectsChain
from gbedu_audio.mastering import AudioMastering
from gbedu_audio.separation import StemSeparator

log = structlog.get_logger(__name__)
_tracer = trace.get_tracer(__name__)


@dataclass
class AudioPipelineResult:
	raw_wav: Path
	mastered_wav: Path
	final_mp3: Path
	watermarked_mp3: Path | None
	preview_mp3: Path
	stems: dict[str, Path] = field(default_factory=dict)
	analysis: dict[str, Any] = field(default_factory=dict)
	errors: dict[str, str] = field(default_factory=dict)


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


class AudioPipeline:
	"""
	Full post-processing pipeline for Gbẹdu tracks.

	Steps (in order):
	  1. Validate input
	  2. Convert to 24-bit WAV 44.1 kHz
	  3. Apply Afrobeats effects chain
	  4. Master against built-in reference profile
	  5. Normalize to -14 LUFS
	  6. Separate stems (demucs)
	  7. Create preview clip (best 15 s)
	  8. Convert to MP3 320k
	  9. Add watermark copy (optional)
	 10. Return AudioPipelineResult

	Partial results are returned even when downstream steps fail.
	"""

	def __init__(self) -> None:
		self._analyzer = AudioAnalyzer()
		self._converter = AudioConverter()
		self._effects = AudioEffectsChain()
		self._mastering = AudioMastering()
		self._separator = StemSeparator()

	async def process(
		self,
		raw_audio_path: Path,
		output_dir: Path,
		watermark: bool = True,
	) -> AudioPipelineResult:
		assert raw_audio_path.is_file(), f"input audio not found: {raw_audio_path}"
		output_dir.mkdir(parents=True, exist_ok=True)

		errors: dict[str, str] = {}
		stems: dict[str, Path] = {}
		analysis: dict[str, Any] = {}

		with _tracer.start_as_current_span("audio.pipeline") as root_span:
			root_span.set_attribute("audio.input", str(raw_audio_path))
			root_span.set_attribute("audio.watermark", watermark)
			t_total = time.perf_counter()

			# ── Step 1: Validate ───────────────────────────────────────────────
			with _tracer.start_as_current_span("pipeline.validate"):
				try:
					await self._validate_input(raw_audio_path)
					log.info("pipeline: input validated", path=str(raw_audio_path))
				except AudioProcessingError as exc:
					# Validation failure is fatal — nothing to process
					root_span.record_exception(exc)
					raise

			# ── Step 2: Convert to 24-bit WAV 44.1 kHz ────────────────────────
			with _tracer.start_as_current_span("pipeline.convert_to_wav"):
				raw_wav = output_dir / (raw_audio_path.stem + "_raw.wav")
				try:
					converted = await self._converter.to_wav(
						raw_audio_path, sample_rate=44100, bit_depth=24,
					)
					converted.rename(raw_wav)
					log.info("pipeline: converted to wav", output=str(raw_wav))
				except AudioProcessingError as exc:
					errors["convert_to_wav"] = str(exc)
					log.error("pipeline: convert_to_wav failed", error=str(exc))
					# Cannot continue without a WAV
					raise

			# ── Step 3: Effects chain ──────────────────────────────────────────
			effects_wav = output_dir / (raw_audio_path.stem + "_fx.wav")
			with _tracer.start_as_current_span("pipeline.effects"):
				try:
					chain = self._effects.afrobeats_chain()
					await self._effects.apply_chain(raw_wav, effects_wav, chain)
					log.info("pipeline: effects chain applied", output=str(effects_wav))
				except AudioProcessingError as exc:
					errors["effects"] = str(exc)
					log.error("pipeline: effects failed, using raw wav", error=str(exc))
					# Fall back to raw wav for mastering
					effects_wav = raw_wav

			# ── Step 4: Master ─────────────────────────────────────────────────
			mastered_wav = output_dir / (raw_audio_path.stem + "_mastered.wav")
			with _tracer.start_as_current_span("pipeline.master"):
				try:
					await self._mastering.master(effects_wav, None, mastered_wav)
					log.info("pipeline: mastering complete", output=str(mastered_wav))
				except AudioProcessingError as exc:
					errors["master"] = str(exc)
					log.error("pipeline: mastering failed, using effects wav", error=str(exc))
					mastered_wav = effects_wav

			# ── Step 5: Normalize loudness ─────────────────────────────────────
			norm_wav = output_dir / (raw_audio_path.stem + "_norm.wav")
			with _tracer.start_as_current_span("pipeline.normalize"):
				try:
					normalized = await self._converter.normalize_loudness(mastered_wav, target_lufs=-14.0)
					normalized.rename(norm_wav)
					log.info("pipeline: loudness normalized", output=str(norm_wav))
				except AudioProcessingError as exc:
					errors["normalize"] = str(exc)
					log.error("pipeline: normalize failed, using mastered wav", error=str(exc))
					norm_wav = mastered_wav

			# ── Step 6: Stem separation ────────────────────────────────────────
			stems_dir = output_dir / "stems"
			with _tracer.start_as_current_span("pipeline.stems"):
				try:
					stems = await self._separator.separate(norm_wav, stems_dir)
					log.info("pipeline: stems separated", count=len(stems))
				except Exception as exc:
					errors["stems"] = str(exc)
					log.error("pipeline: stem separation failed", error=str(exc))

			# ── Step 7: Preview clip ───────────────────────────────────────────
			preview_mp3 = output_dir / (raw_audio_path.stem + "_preview.mp3")
			with _tracer.start_as_current_span("pipeline.preview"):
				try:
					await self._converter.create_preview_clip(norm_wav, preview_mp3, duration=15.0)
					log.info("pipeline: preview clip created", output=str(preview_mp3))
				except AudioProcessingError as exc:
					errors["preview"] = str(exc)
					log.error("pipeline: preview failed", error=str(exc))

			# ── Step 8: Final MP3 320k ─────────────────────────────────────────
			final_mp3 = output_dir / (raw_audio_path.stem + "_final.mp3")
			with _tracer.start_as_current_span("pipeline.to_mp3"):
				try:
					converted_mp3 = await self._converter.to_mp3(norm_wav, bitrate="320k")
					converted_mp3.rename(final_mp3)
					log.info("pipeline: mp3 export complete", output=str(final_mp3))
				except AudioProcessingError as exc:
					errors["to_mp3"] = str(exc)
					log.error("pipeline: mp3 export failed", error=str(exc))

			# ── Step 9: Watermark ──────────────────────────────────────────────
			watermarked_mp3: Path | None = None
			if watermark:
				with _tracer.start_as_current_span("pipeline.watermark"):
					wm_path = output_dir / (raw_audio_path.stem + "_watermarked.mp3")
					try:
						# Watermark the normalized WAV then encode to MP3
						wm_wav = output_dir / (raw_audio_path.stem + "_wm.wav")
						await self._converter.add_watermark(norm_wav, wm_wav)
						wm_mp3 = await self._converter.to_mp3(wm_wav, bitrate="320k")
						wm_mp3.rename(wm_path)
						watermarked_mp3 = wm_path
						log.info("pipeline: watermark copy created", output=str(watermarked_mp3))
						# Clean up intermediate watermarked wav
						try:
							wm_wav.unlink()
						except OSError:
							pass
					except AudioProcessingError as exc:
						errors["watermark"] = str(exc)
						log.error("pipeline: watermark failed", error=str(exc))

			# ── Step 10: Analysis ──────────────────────────────────────────────
			with _tracer.start_as_current_span("pipeline.analysis"):
				try:
					analysis = await self._analyzer.extract_features(norm_wav)
					log.info("pipeline: analysis complete", bpm=analysis.get("bpm"))
				except AudioProcessingError as exc:
					errors["analysis"] = str(exc)
					log.error("pipeline: analysis failed", error=str(exc))

			elapsed = time.perf_counter() - t_total
			log.info(
				"pipeline complete",
				input=str(raw_audio_path),
				elapsed_s=elapsed,
				errors=list(errors.keys()),
			)
			root_span.set_attribute("pipeline.errors", str(list(errors.keys())))
			root_span.set_attribute("pipeline.elapsed_s", elapsed)

			return AudioPipelineResult(
				raw_wav=raw_wav,
				mastered_wav=mastered_wav,
				final_mp3=final_mp3,
				watermarked_mp3=watermarked_mp3,
				preview_mp3=preview_mp3,
				stems=stems,
				analysis=analysis,
				errors=errors,
			)

	async def _validate_input(self, audio_path: Path) -> None:
		"""Check format, minimum duration, and that the file is not silent."""
		import soundfile as sf

		with _tracer.start_as_current_span("pipeline.validate_input"):
			try:
				info = sf.info(str(audio_path))
			except Exception as exc:
				raise AudioProcessingError(
					f"cannot read audio file: {exc}", stage="validate",
				) from exc

			if info.duration < 1.0:
				raise AudioProcessingError(
					f"audio too short: {info.duration:.2f} s (minimum 1 s)", stage="validate",
				)

			# Silence check: sample RMS on first 10 s
			import numpy as np

			frames_to_check = min(int(info.samplerate * 10), info.frames)
			data, _ = sf.read(str(audio_path), frames=frames_to_check, always_2d=True)
			rms = float(np.sqrt(np.mean(data ** 2)))
			if rms < 1e-6:
				raise AudioProcessingError(
					"audio appears to be silent (RMS < 1e-6)", stage="validate",
				)

			log.debug(
				"input validated",
				path=str(audio_path),
				format=info.format,
				duration=info.duration,
				rms=rms,
			)
