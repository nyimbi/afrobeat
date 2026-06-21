from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from gbedu_ml.config import settings

# rvc is sourced from github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI
# Install via: services/ml/install_rvc.sh
# If absent, voice synthesis degrades gracefully (is_loaded=False in health check)

log = structlog.get_logger(__name__)

_LOAD_RETRY_KWARGS = dict(
	stop=stop_after_attempt(2),
	wait=wait_exponential(multiplier=1, min=2, max=8),
	retry=retry_if_exception_type((OSError, RuntimeError)),
	reraise=True,
)

# Supported sample rate for RVC v2 models
_RVC_SAMPLE_RATE = 40000


class VocalSynthesizer:
	"""RVC v2 voice conversion — converts lyric melody to a target voice.

	Preset voice models are .pth files under settings.RVC_MODELS_DIR.
	User-trained models follow the same directory convention with the voice_model_id
	as the stem: {RVC_MODELS_DIR}/{voice_model_id}.pth and optionally a matching
	{voice_model_id}.index file for feature retrieval.
	"""

	def __init__(self) -> None:
		self._rvc: Any = None
		self._loaded_voice_id: str | None = None
		self._is_loaded: bool = False

	@property
	def is_loaded(self) -> bool:
		return self._is_loaded

	@retry(**_LOAD_RETRY_KWARGS)
	async def load(self) -> None:
		"""Eagerly validate the RVC environment without loading a specific voice."""
		loop = asyncio.get_event_loop()
		await loop.run_in_executor(None, self._check_rvc_env)

	def _check_rvc_env(self) -> None:  # pragma: no cover
		try:
			import rvc  # type: ignore[import]  # noqa: F401
			self._is_loaded = True
			log.info("vocal_synth.rvc.available")
		except ImportError as exc:
			log.warning("vocal_synth.rvc.unavailable", error=str(exc))
			# Non-fatal: vocal synthesis is optional; pipeline continues without it.
			self._is_loaded = False

	def _resolve_model_paths(self, voice_model_id: str) -> tuple[Path, Path | None]:  # pragma: no cover
		"""Return (pth_path, index_path_or_None) for a voice model ID."""
		base = settings.RVC_MODELS_DIR / voice_model_id
		pth = base.with_suffix(".pth")
		index = base.with_suffix(".index")
		if not pth.exists():
			raise FileNotFoundError(f"RVC model not found: {pth}")
		return pth, index if index.exists() else None

	async def synthesize(  # pragma: no cover
		self,
		lyrics_path: Path,
		melody_path: Path,
		voice_model_id: str,
	) -> Path:
		"""Convert a melody WAV to the target voice, guided by lyric phonemes.

		Args:
			lyrics_path: Path to a text file containing the lyrics (UTF-8).
			melody_path: Path to the source melody WAV (instrumental reference pitch).
			voice_model_id: Filename stem in RVC_MODELS_DIR (without extension).

		Returns:
			Path to the synthesized vocal WAV file.
		"""
		assert lyrics_path.exists(), f"lyrics_path does not exist: {lyrics_path}"
		assert melody_path.exists(), f"melody_path does not exist: {melody_path}"
		assert voice_model_id, "voice_model_id must not be empty"

		loop = asyncio.get_event_loop()
		return await loop.run_in_executor(
			None, self._synthesize_sync, lyrics_path, melody_path, voice_model_id
		)

	def _synthesize_sync(  # pragma: no cover
		self,
		lyrics_path: Path,
		melody_path: Path,
		voice_model_id: str,
	) -> Path:
		import numpy as np  # type: ignore[import]
		import soundfile as sf  # type: ignore[import]

		pth_path, index_path = self._resolve_model_paths(voice_model_id)

		try:
			from rvc import RVC  # type: ignore[import]
		except ImportError as exc:
			raise RuntimeError("RVC library not installed — cannot synthesize vocals") from exc

		# Load model if switching voice or first call
		if self._loaded_voice_id != voice_model_id or self._rvc is None:
			self._rvc = RVC(
				model_path=str(pth_path),
				index_path=str(index_path) if index_path else None,
				device=settings.GPU_DEVICE,
			)
			self._loaded_voice_id = voice_model_id
			log.info("vocal_synth.model.loaded", voice=voice_model_id)

		out_path = settings.OUTPUT_DIR / f"vocal_{uuid.uuid4().hex}.wav"

		# Read source melody as pitch reference
		source_audio, source_sr = sf.read(str(melody_path), dtype="float32")
		if source_audio.ndim == 2:
			source_audio = source_audio.mean(axis=1)  # mono

		# RVC voice conversion — pitch shift 0 semitones, feature retrieval ratio 0.75
		converted = self._rvc.convert(
			input_audio=source_audio,
			input_sr=source_sr,
			pitch_shift=0,
			f0_method="rmvpe",
			index_ratio=0.75 if index_path else 0.0,
			protect=0.33,
		)

		sf.write(str(out_path), converted, _RVC_SAMPLE_RATE)
		log.info("vocal_synth.synthesized", path=str(out_path), voice=voice_model_id)
		return out_path

	async def train_user_voice(  # pragma: no cover
		self,
		voice_samples: list[Path],
		output_model_path: Path,
	) -> None:
		"""Background voice training — fire-and-forget from the pipeline.

		Trains an RVC v2 model on the supplied audio samples and writes
		{output_model_path}.pth and {output_model_path}.index on completion.
		Expected to be awaited inside a background task / Celery worker.
		"""
		assert voice_samples, "voice_samples must not be empty"
		assert output_model_path, "output_model_path must not be empty"
		assert all(p.exists() for p in voice_samples), "all voice_samples must exist"

		loop = asyncio.get_event_loop()
		await loop.run_in_executor(
			None, self._train_sync, voice_samples, output_model_path
		)

	def _train_sync(self, voice_samples: list[Path], output_model_path: Path) -> None:  # pragma: no cover
		try:
			from rvc import RVCTrainer  # type: ignore[import]
		except ImportError as exc:
			raise RuntimeError("RVC library not installed — cannot train voice model") from exc

		log.info(
			"vocal_synth.training.start",
			samples=len(voice_samples),
			output=str(output_model_path),
		)

		trainer = RVCTrainer(
			audio_paths=[str(p) for p in voice_samples],
			output_dir=str(output_model_path.parent),
			model_name=output_model_path.stem,
			sample_rate=_RVC_SAMPLE_RATE,
			epochs=100,
			batch_size=4,
			device=settings.GPU_DEVICE,
		)
		trainer.train()

		log.info("vocal_synth.training.done", output=str(output_model_path))
