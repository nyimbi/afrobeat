from __future__ import annotations

"""Dead Letter Queue handler task.

Any task that exhausts its retries routes here via:

    process_dlq_message.apply_async(
        kwargs={...},
        queue="gbedu.dlq",
    )

The handler is idempotent: if the job is already in a terminal state it logs
and returns without touching the DB.
"""

from datetime import UTC, datetime
from typing import Any

import structlog
from celery import Task
from gbedu_core.models.job import TERMINAL_JOB_STATUSES, GenerationJob, JobStatus
from gbedu_core.telemetry import get_tracer
from sqlalchemy import select

from gbedu_worker.celery_app import celery_task
from gbedu_worker.db import get_async_session, run_async

log = structlog.get_logger(__name__)
tracer = get_tracer(__name__)


@celery_task(
	bind=True,
	name="gbedu_worker.tasks.dlq.process_dlq_message",
	# DLQ handler itself must not retry — that would create an infinite loop.
	max_retries=0,
	acks_late=True,
	reject_on_worker_lost=False,
	queue="gbedu.dlq",
)
def process_dlq_message(
	self: Task,
	*,
	job_id: str,
	original_task_id: str,
	original_queue: str,
	error_type: str,
	error_message: str,
	error_traceback: str,
	retry_count: int,
) -> dict[str, Any]:
	"""Process a message that has been dead-lettered after exhausting retries.

	Idempotent: if the job is already in a terminal state (failed/complete/
	cancelled) the DB update is skipped to avoid overwriting meaningful state.

	Parameters
	----------
	job_id:
	    The ``generation_jobs.id`` that failed.
	original_task_id:
	    Celery task ID of the originating task.
	original_queue:
	    Queue the task was originally routed to.
	error_type:
	    Exception class name of the final error.
	error_message:
	    Human-readable error string.
	error_traceback:
	    Full formatted traceback of the final error.
	retry_count:
	    Number of retries attempted before giving up.
	"""
	assert job_id, "job_id must not be empty"
	assert original_task_id, "original_task_id must not be empty"

	dlq_log = log.bind(
		job_id=job_id,
		original_task_id=original_task_id,
		dlq_task_id=self.request.id,
		original_queue=original_queue,
		error_type=error_type,
		retry_count=retry_count,
	)

	# Emit the structured critical log that PagerDuty / alertmanager can match on.
	dlq_log.critical(
		"dlq.message_received",
		error_message=error_message,
		alert="generation_job_dead_lettered",
	)

	with tracer.start_as_current_span("task.process_dlq_message") as span:
		span.set_attribute("job.id", job_id)
		span.set_attribute("dlq.original_task_id", original_task_id)
		span.set_attribute("dlq.original_queue", original_queue)
		span.set_attribute("dlq.error_type", error_type)
		span.set_attribute("dlq.retry_count", retry_count)

		result = run_async(
			_handle_dlq_message,
			job_id=job_id,
			original_task_id=original_task_id,
			error_type=error_type,
			error_message=error_message,
			error_traceback=error_traceback,
			retry_count=retry_count,
			dlq_log=dlq_log,
		)
		return result


async def _handle_dlq_message(
	*,
	job_id: str,
	original_task_id: str,
	error_type: str,
	error_message: str,
	error_traceback: str,
	retry_count: int,
	dlq_log: Any,
) -> dict[str, Any]:
	"""Async body — updates the DB and returns a summary dict."""
	async with get_async_session() as session:
		result = await session.execute(select(GenerationJob).where(GenerationJob.id == job_id))
		job: GenerationJob | None = result.scalar_one_or_none()

		if job is None:
			dlq_log.error(
				"dlq.job_not_found",
				note="cannot update status — job row missing",
			)
			return {
				"job_id": job_id,
				"action": "skipped",
				"reason": "job_not_found",
			}

		# Idempotency guard — don't overwrite a terminal state with another failed.
		if job.status in TERMINAL_JOB_STATUSES:
			dlq_log.info(
				"dlq.job_already_terminal",
				current_status=job.status.value,
				note="skipping DB update",
			)
			return {
				"job_id": job_id,
				"action": "skipped",
				"reason": "already_terminal",
				"current_status": job.status.value,
			}

		dlq_reason = (
			f"Dead-lettered after {retry_count} retries. "
			f"Final error [{error_type}]: {error_message}"
		)

		job.status = JobStatus.failed
		job.error_message = dlq_reason
		job.error_traceback = error_traceback
		job.completed_at = datetime.now(UTC)
		job.celery_task_id = original_task_id

		# session.commit() is called by get_async_session().__aexit__

		dlq_log.warning(
			"dlq.job_marked_failed",
			previous_status=job.status.value,
			dlq_reason=dlq_reason,
		)

		return {
			"job_id": job_id,
			"action": "marked_failed",
			"dlq_reason": dlq_reason,
		}
