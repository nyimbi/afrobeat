from __future__ import annotations

"""Generation pipeline Celery task.

The task body is synchronous (Celery default). All async work is driven via
`run_async()` which spins up a fresh event loop per invocation.
"""

import traceback as tb
from datetime import UTC, datetime
from typing import Any, cast

import sqlalchemy as sa
import structlog
from celery import Task
from celery.exceptions import MaxRetriesExceededError
from gbedu_core.models.job import GenerationJob, JobStatus
from gbedu_core.telemetry import get_tracer
from opentelemetry import trace

from gbedu_worker.celery_app import celery_task, retry_task
from gbedu_worker.db import get_async_session, run_async
from gbedu_worker.exceptions import MLServiceError, UploadError
from gbedu_worker.pipelines.generation_pipeline import GenerationPipelineOrchestrator

log = structlog.get_logger(__name__)
tracer = get_tracer(__name__)

# Exceptions worth retrying — everything else is a bug or unrecoverable
_RETRYABLE_EXCEPTIONS = (MLServiceError, UploadError, ConnectionError, TimeoutError)

# Exponential back-off delays in seconds for retries 1, 2, 3
_RETRY_COUNTDOWN = (30, 90, 270)


@celery_task(
	bind=True,
	name="gbedu_worker.tasks.generation.run_generation_pipeline",
	max_retries=3,
	acks_late=True,
	reject_on_worker_lost=True,
	queue="default",
	soft_time_limit=720,
	time_limit=780,
)
def run_generation_pipeline(self: Task, job_id: str) -> dict[str, Any]:
	"""Idempotent generation pipeline task.

	Runs the full ML → DSP → upload → DB write pipeline for a single job.
	Safe to retry: each pipeline stage checks current DB state before acting.
	"""
	assert job_id, "job_id must not be empty"

	task_log = log.bind(job_id=job_id, task_id=self.request.id)
	task_log.info("generation task received")

	with tracer.start_as_current_span("task.run_generation_pipeline") as span:
		span.set_attribute("job.id", job_id)
		span.set_attribute("celery.task_id", self.request.id or "")

		try:
			result = run_async(_run_pipeline, job_id)
			span.set_attribute("job.result_status", result.get("status", "unknown"))
			return result

		except _RETRYABLE_EXCEPTIONS as exc:
			retry_num = int(self.request.retries or 0)
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
				retry_task(self, exc=exc, countdown=countdown)
			except MaxRetriesExceededError:
				task_log.error(
					"max retries exceeded — routing to DLQ",
					exc_type=type(exc).__name__,
				)
				_route_to_dlq(
					job_id=job_id,
					original_task_id=self.request.id or "",
					original_queue=self.request.delivery_info.get("routing_key", "default")
					if self.request.delivery_info
					else "default",
					exc=exc,
					retry_count=retry_num,
					task_log=task_log,
				)
				raise

		except Exception as exc:
			# Non-retryable — mark the DB record failed before letting Celery FAILURE-state the task.
			# Without this the job row stays in its last intermediate state (e.g. ml_generating) forever.
			task_log.error(
				"unrecoverable error in generation pipeline",
				exc_type=type(exc).__name__,
				exc_msg=str(exc),
				traceback=tb.format_exc(),
			)
			span.record_exception(exc)
			span.set_status(trace.StatusCode.ERROR, str(exc))
			try:
				run_async(_mark_job_failed, job_id, exc)
			except Exception as db_exc:
				task_log.error("failed to mark job as failed in DB", db_exc=str(db_exc))
			raise


async def _run_pipeline(job_id: str) -> dict[str, Any]:
	async with get_async_session() as session:
		orchestrator = GenerationPipelineOrchestrator(job_id=job_id, session=session)
		return await orchestrator.run()


async def _mark_job_failed(job_id: str, exc: Exception) -> None:
	async with get_async_session() as session:
		result = await session.execute(sa.select(GenerationJob).where(GenerationJob.id == job_id))
		job = result.scalar_one_or_none()
		if job and not job.is_terminal:
			job.status = JobStatus.failed
			job.error_message = str(exc)
			job.error_traceback = tb.format_exc()
			job.completed_at = datetime.now(UTC)
			await session.commit()


def _route_to_dlq(
	*,
	job_id: str,
	original_task_id: str,
	original_queue: str,
	exc: Exception,
	retry_count: int,
	task_log: Any,
) -> None:
	"""Fire-and-forget: enqueue a DLQ message for a permanently-failed job.

	Failures here are logged but not re-raised so the original MaxRetriesExceededError
	still propagates to let Celery mark the task FAILURE correctly.
	"""
	# Late import to break the circular dependency:
	# generation -> celery_app -> autodiscover -> dlq -> celery_app
	from gbedu_worker.tasks.dlq import process_dlq_message  # noqa: PLC0415

	try:
		cast(Any, process_dlq_message).apply_async(
			kwargs={
				"job_id": job_id,
				"original_task_id": original_task_id,
				"original_queue": original_queue,
				"error_type": type(exc).__name__,
				"error_message": str(exc),
				"error_traceback": tb.format_exc(),
				"retry_count": retry_count,
			},
			queue="gbedu.dlq",
		)
		task_log.info("dlq.message_enqueued", job_id=job_id)
	except Exception as dlq_exc:
		# DLQ publish must never mask the original error
		task_log.error(
			"dlq.publish_failed",
			dlq_exc_type=type(dlq_exc).__name__,
			dlq_exc_msg=str(dlq_exc),
		)
