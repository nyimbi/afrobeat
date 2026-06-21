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

_LOAD_RETRY_KWARGS = {
	"stop": stop_after_attempt(3),
	"wait": wait_exponential(multiplier=1, min=2, max=10),
	"retry": retry_if_exception_type((OSError, RuntimeError)),
	"reraise": True,
}


def _load_retry[F: Callable[..., Any]](func: F) -> F:
	retry_factory = cast(Any, retry)
	return cast(F, retry_factory(**_LOAD_RETRY_KWARGS)(func))


class AceStepModel(BaseMusGen):
	"""ACE-Step 1.5 music generation model.

	Primary model in the fallback chain. Supports Afrobeats LoRA adapters.
	Gracefully falls back to CPU on CUDA OOM for short (≤ 60 s) generations.
	"""

	def __init__(self) -> None:
		super().__init__()
		self._pipeline: Any = None
		self._device: str = settings.GPU_DEVICE

	@property
	def model_id(self) -> str:
		return settings.ACE_STEP_MODEL_ID

	@_load_retry
	async def load(self) -> None:  # pragma: no cover
		loop = asyncio.get_event_loop()
		await loop.run_in_executor(None, self._load_sync)

	def _load_sync(self) -> None:  # pragma: no cover
		# Import deferred — torch/transformers not available at import time in tests
		try:
			from acestep.pipeline import ACEStepPipeline as pipeline_cls  # type: ignore[import]
		except ImportError:
			# Fallback: try loading via diffusers-style pipeline if ACE-Step
			# doesn't ship its own entry-point
			from diffusers import DiffusionPipeline as pipeline_cls  # type: ignore[import]

		log.info("ace_step.load.start", model=self.model_id, device=self._device)

		self._pipeline = cast(Any, pipeline_cls).from_pretrained(
			self.model_id,
			cache_dir=str(settings.MODEL_CACHE_DIR),
			torch_dtype=torch.float16 if "cuda" in self._device else torch.float32,
			use_auth_token=settings.HF_TOKEN,
		)
		self._pipeline = self._pipeline.to(self._device)

		# Attach Afrobeats LoRA if configured
		if settings.ACE_STEP_LORA_ID:
			try:
				self._pipeline.load_lora_weights(
					settings.ACE_STEP_LORA_ID,
					cache_dir=str(settings.MODEL_CACHE_DIR),
				)
				log.info("ace_step.lora.loaded", lora=settings.ACE_STEP_LORA_ID)
			except Exception as exc:
				log.warning("ace_step.lora.failed", lora=settings.ACE_STEP_LORA_ID, error=str(exc))

		self._is_loaded = True
		log.info("ace_step.load.done", model=self.model_id)

	async def generate(
		self, prompt: str, duration_seconds: int, **kwargs: Any
	) -> Path:  # pragma: no cover
		assert self._pipeline is not None, "model not loaded — call load() first"
		assert prompt, "prompt must not be empty"
		assert duration_seconds > 0, "duration_seconds must be positive"

		loop = asyncio.get_event_loop()
		return await loop.run_in_executor(
			None, self._generate_sync, prompt, duration_seconds, kwargs
		)

	def _generate_sync(
		self, prompt: str, duration_seconds: int, kwargs: dict[str, Any]
	) -> Path:  # pragma: no cover
		out_path = settings.OUTPUT_DIR / f"ace_{uuid.uuid4().hex}.wav"

		try:
			return self._run_pipeline(prompt, duration_seconds, out_path, kwargs)
		except RuntimeError as exc:
			if "CUDA out of memory" in str(exc) and duration_seconds <= 60:
				log.warning(
					"ace_step.cuda_oom.fallback_cpu",
					duration_seconds=duration_seconds,
					error=str(exc),
				)
				torch.cuda.empty_cache()
				# Move temporarily to CPU for short clips
				self._pipeline = self._pipeline.to("cpu")
				try:
					result = self._run_pipeline(prompt, duration_seconds, out_path, kwargs)
				finally:
					# Restore to original device
					self._pipeline = self._pipeline.to(self._device)
				return result
			raise

	def _run_pipeline(  # pragma: no cover
		self,
		prompt: str,
		duration_seconds: int,
		out_path: Path,
		kwargs: dict[str, Any],
	) -> Path:
		import torchaudio  # type: ignore[import]

		result = self._pipeline(
			prompt=prompt,
			duration=duration_seconds,
			num_inference_steps=kwargs.get("num_inference_steps", 50),
			guidance_scale=kwargs.get("guidance_scale", 7.5),
			generator=torch.Generator(device=self._pipeline.device).manual_seed(
				kwargs.get("seed", torch.randint(0, 2**31, (1,)).item())
			),
		)

		# ACE-Step returns audio as a tensor [channels, samples] or [batch, channels, samples]
		audio = result.audios if hasattr(result, "audios") else result[0]
		if audio.dim() == 3:
			audio = audio[0]

		sample_rate = getattr(result, "sample_rate", 44100)
		cast(Any, torchaudio).save(str(out_path), audio.cpu(), sample_rate)

		torch.cuda.empty_cache()
		log.info("ace_step.generated", path=str(out_path), sample_rate=sample_rate)
		return out_path

	async def unload(self) -> None:  # pragma: no cover
		if self._pipeline is not None:
			del self._pipeline
			self._pipeline = None
			if torch.cuda.is_available():
				torch.cuda.empty_cache()
		await super().unload()
