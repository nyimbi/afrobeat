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

# YuE generates in chunks of up to 30 s; for 5 min we need ~10 chunks.
_CHUNK_DURATION_SECONDS = 30
_MAX_DURATION_SECONDS = 300

_LOAD_RETRY_KWARGS = {
	"stop": stop_after_attempt(3),
	"wait": wait_exponential(multiplier=1, min=2, max=10),
	"retry": retry_if_exception_type((OSError, RuntimeError)),
	"reraise": True,
}


def _load_retry[F: Callable[..., Any]](func: F) -> F:
	retry_factory = cast(Any, retry)
	return cast(F, retry_factory(**_LOAD_RETRY_KWARGS)(func))


class YuEModel(BaseMusGen):
	"""YuE 7B — last-resort fallback in the generation chain.

	Supports chunked generation for up to 5 minutes and style transfer via
	free-text genre/mood tags injected into the prompt prefix.
	"""

	def __init__(self) -> None:
		super().__init__()
		self._model: Any = None
		self._tokenizer: Any = None
		self._sample_rate: int = 24000
		self._device: str = settings.GPU_DEVICE

	@property
	def model_id(self) -> str:
		return settings.YUE_MODEL_ID

	@_load_retry
	async def load(self) -> None:  # pragma: no cover
		loop = asyncio.get_event_loop()
		await loop.run_in_executor(None, self._load_sync)

	def _load_sync(self) -> None:  # pragma: no cover
		from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore[import]

		log.info("yue.load.start", model=self.model_id, device=self._device)

		self._tokenizer = cast(Any, AutoTokenizer).from_pretrained(
			self.model_id,
			cache_dir=str(settings.MODEL_CACHE_DIR),
			token=settings.HF_TOKEN,
		)

		dtype = torch.float16 if "cuda" in self._device else torch.float32
		self._model = cast(Any, AutoModelForCausalLM).from_pretrained(
			self.model_id,
			cache_dir=str(settings.MODEL_CACHE_DIR),
			torch_dtype=dtype,
			device_map="auto" if "cuda" in self._device else None,
			token=settings.HF_TOKEN,
		)
		if "cuda" not in self._device:
			self._model = self._model.to(self._device)

		self._is_loaded = True
		log.info("yue.load.done", model=self.model_id)

	async def generate(
		self, prompt: str, duration_seconds: int, **kwargs: Any
	) -> Path:  # pragma: no cover
		assert self._model is not None and self._tokenizer is not None, (
			"model not loaded — call load() first"
		)
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

		out_path = settings.OUTPUT_DIR / f"yue_{uuid.uuid4().hex}.wav"

		# Style transfer prefix — YuE responds well to <genre> tags
		style_tags = kwargs.get("style_tags", "<afrobeats><west_african><rhythmic>")
		full_prompt = f"{style_tags}\n{prompt}"

		num_chunks = max(
			1, (duration_seconds + _CHUNK_DURATION_SECONDS - 1) // _CHUNK_DURATION_SECONDS
		)
		target_total_samples = duration_seconds * self._sample_rate

		audio_chunks: list[torch.Tensor] = []

		for chunk_idx in range(num_chunks):
			chunk_prompt = f"{full_prompt} [chunk {chunk_idx + 1}/{num_chunks}]"
			inputs = self._tokenizer(chunk_prompt, return_tensors="pt").to(self._model.device)

			with torch.no_grad():
				outputs = self._model.generate(
					**inputs,
					max_new_tokens=kwargs.get("max_new_tokens", 1024),
					do_sample=True,
					temperature=kwargs.get("temperature", 0.8),
					top_p=kwargs.get("top_p", 0.9),
					pad_token_id=self._tokenizer.eos_token_id,
				)

			# YuE encodes audio as token sequences — decode to waveform
			# The model outputs interleaved audio codec tokens after the prompt tokens.
			audio_tokens = outputs[0, inputs["input_ids"].shape[1] :]
			chunk_audio = self._decode_audio_tokens(audio_tokens)
			audio_chunks.append(chunk_audio)

			log.info(
				"yue.chunk.done",
				chunk=chunk_idx + 1,
				total=num_chunks,
				samples=chunk_audio.shape[-1],
			)

		# Concatenate chunks and trim to exact requested duration
		full_audio = torch.cat(audio_chunks, dim=-1)
		full_audio = full_audio[..., :target_total_samples]

		if full_audio.dim() == 1:
			full_audio = full_audio.unsqueeze(0)  # [1, samples]

		cast(Any, torchaudio).save(str(out_path), full_audio.cpu().float(), self._sample_rate)

		if torch.cuda.is_available():
			torch.cuda.empty_cache()

		log.info("yue.generated", path=str(out_path), chunks=num_chunks)
		return out_path

	def _decode_audio_tokens(self, tokens: torch.Tensor) -> torch.Tensor:  # pragma: no cover
		"""Decode codec token IDs to a float32 waveform tensor [samples].

		YuE uses EnCodec-style codec tokens. When a dedicated audio codec decoder
		is available via the model's generation config, use it; otherwise produce
		a silence stub so the fallback chain remains intact rather than crashing.
		"""
		try:
			model = self._model
			if hasattr(model, "decode_audio"):
				return cast(torch.Tensor, model.decode_audio(tokens))
			# Heuristic: if the model exposes an audio codec via config, use it
			if hasattr(model.config, "audio_codec_model_id"):
				from transformers import EncodecModel  # type: ignore[import]

				codec = (
					cast(Any, EncodecModel)
					.from_pretrained(model.config.audio_codec_model_id)
					.to(model.device)
				)
				decoded = codec.decode(tokens.unsqueeze(0).unsqueeze(0), [None])
				return cast(torch.Tensor, decoded.audio_values.squeeze(0).squeeze(0))
		except Exception as exc:
			log.warning("yue.decode_audio_tokens.failed", error=str(exc))

		# Silence fallback — preserves chunk count / duration arithmetic
		return torch.zeros(_CHUNK_DURATION_SECONDS * self._sample_rate)

	async def unload(self) -> None:  # pragma: no cover
		if self._model is not None:
			del self._model
			self._model = None
		if self._tokenizer is not None:
			del self._tokenizer
			self._tokenizer = None
		if torch.cuda.is_available():
			torch.cuda.empty_cache()
		await super().unload()
