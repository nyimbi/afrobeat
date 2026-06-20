from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import structlog
from circuitbreaker import CircuitBreaker, CircuitBreakerError

log = structlog.get_logger(__name__)

# Circuit breaker: 3 consecutive failures → open for 60 s
_CB_FAILURE_THRESHOLD = 3
_CB_RECOVERY_TIMEOUT = 60
_CB_EXPECTED_EXCEPTION = Exception


def _make_circuit_breaker(model_id: str) -> CircuitBreaker:
	return CircuitBreaker(
		failure_threshold=_CB_FAILURE_THRESHOLD,
		recovery_timeout=_CB_RECOVERY_TIMEOUT,
		expected_exception=_CB_EXPECTED_EXCEPTION,
		name=f"cb_{model_id.replace('/', '_')}",
	)


class BaseMusGen(ABC):
	"""Abstract base for all music generation backends."""

	def __init__(self) -> None:
		self._is_loaded: bool = False
		self._load_error: str | None = None
		self._cb: CircuitBreaker = _make_circuit_breaker(self.model_id)
		self._last_generation_ms: float | None = None

	# ── Abstract interface ─────────────────────────────────────────────────────

	@property
	@abstractmethod
	def model_id(self) -> str:
		"""HuggingFace repo ID or local identifier."""
		...

	@abstractmethod
	async def load(self) -> None:
		"""Load model weights into memory / GPU. Sets self._is_loaded = True on success."""
		...

	@abstractmethod
	async def generate(self, prompt: str, duration_seconds: int, **kwargs: Any) -> Path:
		"""Run inference and return path to a WAV file on disk."""
		...

	# ── Concrete helpers ───────────────────────────────────────────────────────

	@property
	def is_loaded(self) -> bool:
		return self._is_loaded

	@property
	def circuit_open(self) -> bool:
		return self._cb.opened

	async def generate_safe(self, prompt: str, duration_seconds: int, **kwargs: Any) -> Path:
		"""generate() wrapped with circuit-breaker check and timing."""
		assert prompt, "prompt must not be empty"
		assert duration_seconds > 0, "duration_seconds must be positive"

		if self._cb.opened:
			raise CircuitBreakerError(self._cb)

		t0 = time.perf_counter()
		try:
			result = await self._cb.call_async(self.generate, prompt, duration_seconds, **kwargs)
			self._last_generation_ms = (time.perf_counter() - t0) * 1000
			log.info(
				"model.generate.ok",
				model=self.model_id,
				duration_seconds=duration_seconds,
				elapsed_ms=round(self._last_generation_ms, 1),
			)
			return result
		except CircuitBreakerError:
			log.warning("model.circuit_open", model=self.model_id)
			raise
		except Exception as exc:
			self._last_generation_ms = (time.perf_counter() - t0) * 1000
			log.error(
				"model.generate.error",
				model=self.model_id,
				error=str(exc),
				elapsed_ms=round(self._last_generation_ms, 1),
			)
			raise

	async def unload(self) -> None:
		"""Release GPU/CPU memory. Override in subclasses to free torch tensors."""
		self._is_loaded = False
		log.info("model.unloaded", model=self.model_id)

	def health_check(self) -> dict[str, Any]:
		return {
			"model_id": self.model_id,
			"is_loaded": self._is_loaded,
			"load_error": self._load_error,
			"circuit_open": self._cb.opened,
			"circuit_failure_count": self._cb.failure_count,
			"last_generation_ms": self._last_generation_ms,
		}
