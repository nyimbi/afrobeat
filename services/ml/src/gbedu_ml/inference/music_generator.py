from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
from circuitbreaker import CircuitBreakerError
from pydantic import BaseModel, ConfigDict, Field

from gbedu_core._uuid7 import uuid7str
from gbedu_core.errors import GenerationError
from gbedu_core.schemas import GenerationRequest
from gbedu_ml.models.ace_step import AceStepModel
from gbedu_ml.models.stable_audio import StableAudioModel
from gbedu_ml.models.yue import YuEModel
from gbedu_ml.prompts.afrobeats import AfrobeatsPromptEngine

log = structlog.get_logger(__name__)


class MusicGenerationResult(BaseModel):
	model_config = ConfigDict(extra="forbid")

	id: str = Field(default_factory=uuid7str)
	audio_path: Path
	model_used: str
	duration_seconds: int
	prompt_used: str
	metadata: dict[str, Any] = Field(default_factory=dict)


class MusicGenerator:
	"""Orchestrates the ACE-Step → Stable Audio → YuE fallback chain.

	Each model is tried in order. If a model's circuit breaker is open,
	or it raises any exception, the next model is attempted. All three
	failing raises GenerationError with a summary of all failures.
	"""

	def __init__(
		self,
		ace_step: AceStepModel,
		stable_audio: StableAudioModel,
		yue: YuEModel,
	) -> None:
		self._models = [ace_step, stable_audio, yue]
		self._prompt_engine = AfrobeatsPromptEngine()

	async def generate(self, request: GenerationRequest) -> MusicGenerationResult:
		assert request.prompt, "request.prompt must not be empty"

		prompt = self._prompt_engine.build_music_prompt(request)
		failures: list[dict[str, str]] = []

		for model in self._models:
			if not model.is_loaded:
				log.warning("music_gen.model.skip.not_loaded", model=model.model_id)
				failures.append({"model": model.model_id, "reason": "not loaded"})
				continue

			if model.circuit_open:
				log.warning("music_gen.model.skip.circuit_open", model=model.model_id)
				failures.append({"model": model.model_id, "reason": "circuit breaker open"})
				continue

			# FMEA M01: guard against OOM-kill cascade on GPU.
			# Reject requests when >85% of VRAM is already reserved rather than
			# letting the model allocate and crash the entire process.
			try:
				import torch
				if torch.cuda.is_available():
					reserved = torch.cuda.memory_reserved(0)
					total = torch.cuda.get_device_properties(0).total_memory
					utilization = reserved / total
					if utilization > 0.85:
						log.error(
							"music_gen.vram_budget_exceeded",
							model=model.model_id,
							reserved_gb=round(reserved / 1e9, 2),
							total_gb=round(total / 1e9, 2),
							utilization_pct=round(utilization * 100, 1),
						)
						raise GenerationError(
							f"GPU memory budget exceeded ({utilization:.0%} reserved) — "
							"request rejected to prevent OOM cascade",
							details={"reserved_gb": reserved / 1e9, "total_gb": total / 1e9},
						)
			except ImportError:
				pass

			try:
				log.info("music_gen.trying", model=model.model_id)
				audio_path = await model.generate_safe(
					prompt=prompt,
					duration_seconds=request.duration_seconds,
				)
				log.info(
					"music_gen.success",
					model=model.model_id,
					path=str(audio_path),
				)
				return MusicGenerationResult(
					audio_path=audio_path,
					model_used=model.model_id,
					duration_seconds=request.duration_seconds,
					prompt_used=prompt,
				)
			except CircuitBreakerError as exc:
				log.warning("music_gen.circuit_open", model=model.model_id, error=str(exc))
				failures.append({"model": model.model_id, "reason": f"circuit open: {exc}"})
			except Exception as exc:
				log.error("music_gen.model.failed", model=model.model_id, error=str(exc))
				failures.append({"model": model.model_id, "reason": str(exc)})

		raise GenerationError(
			"All music generation models failed",
			details={"failures": failures},
		)
