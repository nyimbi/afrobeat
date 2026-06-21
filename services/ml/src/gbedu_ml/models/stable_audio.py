from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import structlog
import torch
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from gbedu_ml.config import settings
from gbedu_ml.models.base import BaseMusGen

log = structlog.get_logger(__name__)

_MAX_DURATION_SECONDS = 380  # Stable Audio 3.0 Medium: up to ~6:20

_LOAD_RETRY_KWARGS = {
	"stop": stop_after_attempt(3),
	"wait": wait_exponential(multiplier=1, min=2, max=10),
	"retry": retry_if_exception_type((OSError, RuntimeError)),
	"reraise": True,
}


def _load_retry[F: Callable[..., Any]](func: F) -> F:
	retry_factory = cast(Any, retry)
	return cast(F, retry_factory(**_LOAD_RETRY_KWARGS)(func))


class StableAudioModel(BaseMusGen):
	"""Stable Audio 3.0 Medium — secondary fallback in the generation chain.

	Wraps the transformers StableAudioPipeline. Supports up to ~6:20 of audio.
	"""

	def __init__(self) -> None:
		super().__init__()
		self._pipeline: Any = None
		self._sample_rate: int = 44100
		self._device: str = settings.GPU_DEVICE

	@property
	def model_id(self) -> str:
		return settings.STABLE_AUDIO_MODEL_ID

	@_load_retry
	async def load(self) -> None:  # pragma: no cover
		loop = asyncio.get_event_loop()
		await loop.run_in_executor(None, self._load_sync)

	def _load_sync(self) -> None:  # pragma: no cover
		from transformers import StableAudioPipeline  # type: ignore[import]

		log.info("stable_audio.load.start", model=self.model_id, device=self._device)

		dtype = torch.float16 if "cuda" in self._device else torch.float32
		self._pipeline = cast(Any, StableAudioPipeline).from_pretrained(
			self.model_id,
			cache_dir=str(settings.MODEL_CACHE_DIR),
			torch_dtype=dtype,
			token=settings.HF_TOKEN,
		)
		self._pipeline = self._pipeline.to(self._device)

		# Retrieve native sample rate from model config
		pipeline = self._pipeline
		if hasattr(pipeline, "vae") and hasattr(pipeline.vae, "config"):
			sr = getattr(pipeline.vae.config, "sample_rate", None)
			if sr:
				self._sample_rate = int(sr)

		self._is_loaded = True
		log.info("stable_audio.load.done", model=self.model_id, sample_rate=self._sample_rate)

	async def generate(
		self, prompt: str, duration_seconds: int, **kwargs: Any
	) -> Path:  # pragma: no cover
		assert self._pipeline is not None, "model not loaded — call load() first"
		assert prompt, "prompt must not be empty"
		assert 0 < duration_seconds <= _MAX_DURATION_SECONDS, (
			f"duration_seconds must be in (0, {_MAX_DURATION_SECONDS}]"
		)

		loop = asyncio.get_event_loop()
		return await loop.run_in_executor(
			None, self._generate_sync, prompt, duration_seconds, kwargs
		)

	def _generate_sync(
		self, prompt: str, duration_seconds: int, kwargs: dict[str, Any]
	) -> Path:  # pragma: no cover
		import torchaudio  # type: ignore[import]

		out_path = settings.OUTPUT_DIR / f"stable_{uuid.uuid4().hex}.wav"

		generator = torch.Generator(device=self._device).manual_seed(
			kwargs.get("seed", torch.randint(0, 2**31, (1,)).item())
		)

		result = self._pipeline(
			prompt,
			negative_prompt=kwargs.get(
				"negative_prompt", "low quality, noise, distortion, clipping"
			),
			num_inference_steps=kwargs.get("num_inference_steps", 100),
			audio_end_in_s=float(duration_seconds),
			num_waveforms_per_prompt=1,
			generator=generator,
		)

		# Pipeline returns AudioPipelineOutput with .audios shape [batch, channels, samples]
		audio = result.audios[0]  # [channels, samples]

		cast(Any, torchaudio).save(str(out_path), audio.cpu(), self._sample_rate)

		if torch.cuda.is_available():
			torch.cuda.empty_cache()

		log.info("stable_audio.generated", path=str(out_path), sample_rate=self._sample_rate)
		return out_path

	async def unload(self) -> None:  # pragma: no cover
		if self._pipeline is not None:
			del self._pipeline
			self._pipeline = None
			if torch.cuda.is_available():
				torch.cuda.empty_cache()
		await super().unload()
