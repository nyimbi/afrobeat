from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

import httpx
import structlog
from circuitbreaker import CircuitBreaker, CircuitBreakerError
from gbedu_core.config import MLSettings
from gbedu_core.errors import MLServiceError, MLServiceTimeoutError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

log = structlog.get_logger(__name__)

_ML_RETRY_KWARGS: dict[str, Any] = {
	"retry": retry_if_exception_type(httpx.HTTPStatusError),
	"wait": wait_exponential(multiplier=2, min=2, max=30),
	"stop": stop_after_attempt(3),
	"reraise": True,
}


def _ml_retry[F: Callable[..., Any]](func: F) -> F:
	return cast(F, retry(**_ML_RETRY_KWARGS)(func))


class GenerationRequest:
	def __init__(
		self,
		prompt: str,
		sub_genre: str,
		language: str,
		bpm: int | None = None,
		energy_level: int = 5,
		voice_model_id: str | None = None,
		duration_seconds: int = 30,
	) -> None:
		assert prompt, "prompt must not be empty"
		self.prompt = prompt
		self.sub_genre = sub_genre
		self.language = language
		self.bpm = bpm
		self.energy_level = energy_level
		self.voice_model_id = voice_model_id
		self.duration_seconds = duration_seconds

	def to_dict(self) -> dict[str, Any]:
		return {
			"prompt": self.prompt,
			"sub_genre": self.sub_genre,
			"language": self.language,
			"bpm": self.bpm,
			"energy_level": self.energy_level,
			"voice_model_id": self.voice_model_id,
			"duration_seconds": self.duration_seconds,
		}


class GenerationResponse:
	def __init__(self, data: dict[str, Any]) -> None:
		self.job_id: str = data["job_id"]
		self.status: str = data.get("status", "queued")
		self.audio_url: str | None = data.get("audio_url")
		self.stem_urls: dict[str, str] = data.get("stem_urls", {})
		self.metadata: dict[str, Any] = data.get("metadata", {})


class MLServiceClient:
	"""Async HTTP client for the Gbẹdu ML inference service.

	Circuit breaker opens after 5 consecutive failures, recovers after 60 s.
	Long-running inference uses a 10-minute timeout.
	"""

	def __init__(self, settings: MLSettings) -> None:
		assert settings.service_url, "ML_SERVICE_URL must be set"

		self._base_url = settings.service_url.rstrip("/")
		self._api_key = settings.service_api_key
		self._inference_timeout = settings.inference_timeout

		self._circuit: Any = CircuitBreaker(
			failure_threshold=settings.circuit_failure_threshold,
			recovery_timeout=settings.circuit_recovery_timeout,
			expected_exception=MLServiceError,
			name="ml_service",
		)

		self._http = httpx.AsyncClient(
			base_url=self._base_url,
			headers={
				"X-API-Key": self._api_key,
				"Content-Type": "application/json",
			},
			timeout=httpx.Timeout(
				connect=10.0,
				read=float(self._inference_timeout),
				write=30.0,
				pool=5.0,
			),
		)

	async def close(self) -> None:
		await self._http.aclose()

	@_ml_retry
	async def generate_music(self, request: GenerationRequest) -> GenerationResponse:
		"""Submit a generation request to the ML service.

		Retries on 503 (service unavailable). Times out after 10 min.
		Raises MLServiceError on circuit breaker open.
		"""
		try:

			async def _call() -> httpx.Response:
				return await self._http.post("/generate", json=request.to_dict())

			protected_call = cast(Callable[[], Awaitable[httpx.Response]], self._circuit(_call))
			resp = await protected_call()
		except CircuitBreakerError as exc:
			log.warning("ml_client.circuit_open", error=str(exc))
			raise MLServiceError("ML service circuit breaker is open — queuing job") from exc
		except httpx.TimeoutException as exc:
			log.error("ml_client.timeout", prompt_len=len(request.prompt))
			raise MLServiceTimeoutError() from exc
		except httpx.HTTPError as exc:
			log.error("ml_client.http_error", error=str(exc))
			raise MLServiceError(f"ML service HTTP error: {exc}") from exc

		if resp.status_code == 503:
			raise httpx.HTTPStatusError(
				"ML service unavailable",
				request=resp.request,
				response=resp,
			)

		try:
			resp.raise_for_status()
		except httpx.HTTPStatusError as exc:
			log.error("ml_client.error_response", status=resp.status_code, body=resp.text[:512])
			raise MLServiceError(
				f"ML service returned {resp.status_code}: {resp.text[:256]}"
			) from exc

		return GenerationResponse(resp.json())

	async def get_health(self) -> bool:
		"""Return True if the ML service is reachable and healthy."""
		try:
			resp = await self._http.get("/health", timeout=5.0)
			return resp.status_code == 200
		except httpx.HTTPError:
			return False
