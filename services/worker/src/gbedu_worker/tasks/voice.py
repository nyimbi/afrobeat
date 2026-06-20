from __future__ import annotations

"""Voice model training Celery task.

Downloads user-uploaded audio samples from R2 (via presigned GET URLs stored
in VoiceModel.training_audio_urls), calls the ML service POST /voice/train to
run RVC v2 training on the GPU, then updates the VoiceModel record with the
returned model artifact URLs.

Design decisions:
- Training is delegated to the ML service (which has GPU access).
- The worker does DB bookkeeping and orchestration; the ML service does
  computation.
- Idempotent: a model already in `ready` or `deprecated` status is skipped
  without error.
- Retries on transient network/timeout failures only; schema/logic errors go
  directly to failed.
- Time limits are set generously (4 h soft, 4 h 5 min hard) to accommodate
  large training corpora.
"""

import traceback as tb
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from celery import Task
from celery.exceptions import MaxRetriesExceededError
from opentelemetry import trace

from gbedu_core.config import get_settings
from gbedu_core.models.voice import VoiceModel, VoiceModelStatus
from gbedu_core.telemetry import get_tracer, increment_error_count
from gbedu_worker.celery_app import app
from gbedu_worker.db import get_async_session, run_async

log = structlog.get_logger(__name__)
tracer = get_tracer(__name__)

# RVC v2 training can take up to 4 hours for large corpora
_SOFT_TIME_LIMIT = 14_400   # 4 h
_HARD_TIME_LIMIT = 14_700   # 4 h 5 min — hard kill fires after soft_time_limit

# HTTP timeout for the blocking ML service training call
_ML_TIMEOUT = httpx.Timeout(connect=10.0, read=_SOFT_TIME_LIMIT + 300.0, write=120.0, pool=10.0)

# Exponential back-off delays for retries (seconds)
_RETRY_COUNTDOWN = (60, 300, 900)

# Failures that are worth retrying (transient network/infra faults)
_RETRYABLE = (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError, ConnectionError)


# ── Task ──────────────────────────────────────────────────────────────────────

@app.task(
	bind=True,
	name="gbedu_worker.tasks.voice.train_voice_model",
	max_retries=3,
	acks_late=True,
	reject_on_worker_lost=True,
	queue="generation",
	soft_time_limit=_SOFT_TIME_LIMIT,
	time_limit=_HARD_TIME_LIMIT,
)
def train_voice_model(self: Task, voice_model_id: str) -> dict[str, Any]:
	"""Orchestrate RVC v2 training for a user voice model.

	Args:
		voice_model_id: UUID7 string of the VoiceModel row to train.

	Returns:
		Dict with keys: status, voice_model_id, model_file_url, index_file_url.
	"""
	assert voice_model_id, "voice_model_id must not be empty"

	task_log = log.bind(voice_model_id=voice_model_id, task_id=self.request.id)
	task_log.info("voice.train task received")

	with tracer.start_as_current_span("task.train_voice_model") as span:
		span.set_attribute("voice_model.id", voice_model_id)
		span.set_attribute("celery.task_id", self.request.id or "")

		try:
			result = run_async(_run_training(voice_model_id, self.request.id or ""))
			span.set_attribute("voice_model.final_status", result.get("status", "unknown"))
			task_log.info("voice.train task complete", result_status=result.get("status"))
			return result

		except _RETRYABLE as exc:
			retry_num = self.request.retries
			countdown = _RETRY_COUNTDOWN[min(retry_num, len(_RETRY_COUNTDOWN) - 1)]
			task_log.warning(
				"retryable error — scheduling retry",
				exc_type=type(exc).__name__,
				exc_msg=str(exc),
				retry_num=retry_num,
				countdown_seconds=countdown,
			)
			span.record_exception(exc)
			try:
				raise self.retry(exc=exc, countdown=countdown)
			except MaxRetriesExceededError:
				task_log.error("max retries exceeded — marking model failed")
				increment_error_count(error_code="VOICE_TRAIN_MAX_RETRIES", service="worker.voice")
				try:
					run_async(_mark_failed(voice_model_id, exc))
				except Exception as db_exc:
					task_log.error("failed to write failure status to DB", db_exc=str(db_exc))
				raise

		except Exception as exc:
			task_log.error(
				"unrecoverable error in voice training",
				exc_type=type(exc).__name__,
				exc_msg=str(exc),
				traceback=tb.format_exc(),
			)
			span.record_exception(exc)
			span.set_status(trace.StatusCode.ERROR, str(exc))
			increment_error_count(error_code=type(exc).__name__, service="worker.voice")
			try:
				run_async(_mark_failed(voice_model_id, exc))
			except Exception as db_exc:
				task_log.error("failed to write failure status to DB", db_exc=str(db_exc))
			raise


# ── Async implementation ───────────────────────────────────────────────────────

async def _run_training(voice_model_id: str, celery_task_id: str) -> dict[str, Any]:
	"""Full training orchestration coroutine."""
	# ── Step 1: Load model and guard idempotency ──────────────────────────────
	async with get_async_session() as session:
		vm = await session.get(VoiceModel, voice_model_id)
		if vm is None:
			raise ValueError(f"VoiceModel {voice_model_id!r} not found in database")

		if vm.status in (VoiceModelStatus.ready, VoiceModelStatus.deprecated):
			log.info(
				"voice.train skipped — already in terminal state",
				voice_model_id=voice_model_id,
				status=vm.status.value,
			)
			return {
				"status": "skipped",
				"reason": "already_terminal",
				"voice_model_id": voice_model_id,
			}

		if not vm.training_audio_urls:
			raise ValueError(f"VoiceModel {voice_model_id!r} has no training_audio_urls")

		# Capture values needed after the session closes
		audio_urls: list[str] = list(vm.training_audio_urls)
		training_config: dict[str, Any] = dict(vm.training_config)

		# Transition to training
		if not vm.training_task_id:
			vm.training_task_id = celery_task_id
		vm.status = VoiceModelStatus.training
		vm.training_progress_percent = 0
		vm.error_message = None
		await session.commit()

	log.info(
		"voice.train.started",
		voice_model_id=voice_model_id,
		audio_count=len(audio_urls),
		training_config=training_config,
	)

	# ── Step 2: Invoke ML service training ────────────────────────────────────
	settings = get_settings()
	ml_url = str(settings.ml.service_url).rstrip("/")
	api_key = settings.ml.service_api_key

	async with httpx.AsyncClient(timeout=_ML_TIMEOUT) as client:
		log.info("voice.train.calling_ml_service", ml_url=ml_url, voice_model_id=voice_model_id)
		resp = await client.post(
			f"{ml_url}/voice/train",
			json={
				"voice_model_id": voice_model_id,
				"training_audio_urls": audio_urls,
				"training_config": training_config,
			},
			headers={"X-API-Key": api_key},
		)

	if resp.status_code != 200:
		error_detail = resp.text[:500]
		raise RuntimeError(
			f"ML service /voice/train returned HTTP {resp.status_code}: {error_detail}"
		)

	ml_result: dict[str, Any] = resp.json()
	model_file_url: str = ml_result["model_file_url"]
	index_file_url: str | None = ml_result.get("index_file_url")
	metrics: dict[str, Any] = ml_result.get("metrics", {})

	log.info(
		"voice.train.ml_complete",
		voice_model_id=voice_model_id,
		model_file_url=model_file_url,
		has_index=index_file_url is not None,
		metrics=metrics,
	)

	# ── Step 3: Persist trained model artifacts ───────────────────────────────
	async with get_async_session() as session:
		vm = await session.get(VoiceModel, voice_model_id)
		if vm is None:
			raise RuntimeError(
				f"VoiceModel {voice_model_id!r} disappeared after training completed"
			)

		vm.status = VoiceModelStatus.ready
		vm.model_file_url = model_file_url
		vm.index_file_url = index_file_url
		vm.training_metrics = metrics
		vm.training_progress_percent = 100
		vm.error_message = None
		await session.commit()

	log.info("voice.train.db_updated", voice_model_id=voice_model_id, status="ready")

	return {
		"status": "complete",
		"voice_model_id": voice_model_id,
		"model_file_url": model_file_url,
		"index_file_url": index_file_url,
	}


async def _mark_failed(voice_model_id: str, exc: Exception) -> None:
	"""Write status=failed to DB. No-op if the model is already in a terminal state."""
	async with get_async_session() as session:
		vm = await session.get(VoiceModel, voice_model_id)
		if vm is not None and vm.status not in (
			VoiceModelStatus.ready,
			VoiceModelStatus.deprecated,
		):
			vm.status = VoiceModelStatus.failed
			vm.error_message = f"{type(exc).__name__}: {exc}"
			await session.commit()
			log.info("voice.train.marked_failed", voice_model_id=voice_model_id)
