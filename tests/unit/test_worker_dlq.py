from __future__ import annotations

"""Unit tests for gbedu_worker.tasks.dlq async helpers."""

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from gbedu_core.models.job import GenerationJob, JobStatus

# ── helpers ───────────────────────────────────────────────────────────────


def _make_job(job_id: str = "job-1", status: JobStatus = JobStatus.queued) -> MagicMock:
	from gbedu_core.models.job import TERMINAL_JOB_STATUSES

	job = MagicMock(spec=GenerationJob)
	job.id = job_id
	job.status = status
	job.is_terminal = status in TERMINAL_JOB_STATUSES
	job.error_message = None
	job.error_traceback = None
	job.completed_at = None
	job.celery_task_id = None
	return job


def _make_session(execute_return: Any = None) -> tuple[MagicMock, Any]:
	session = MagicMock()
	session.add = MagicMock()
	session.flush = AsyncMock()
	session.commit = AsyncMock()

	result = MagicMock()
	result.scalar_one_or_none.return_value = execute_return
	session.execute = AsyncMock(return_value=result)

	@asynccontextmanager
	async def _ctx():
		yield session

	return session, _ctx


_DLQ_KWARGS = {
	"job_id": "job-1",
	"original_task_id": "task-abc",
	"error_type": "TimeoutError",
	"error_message": "ML service timed out",
	"error_traceback": "Traceback ...",
	"retry_count": 3,
	"dlq_log": MagicMock(),
}


# ── _handle_dlq_message ───────────────────────────────────────────────────


async def test_handle_dlq_job_not_found() -> None:
	from unittest.mock import patch

	from gbedu_worker.tasks.dlq import _handle_dlq_message

	_, ctx = _make_session(execute_return=None)

	with patch("gbedu_worker.tasks.dlq.get_async_session", ctx):
		result = await _handle_dlq_message(**_DLQ_KWARGS)

	assert result["action"] == "skipped"
	assert result["reason"] == "job_not_found"


async def test_handle_dlq_job_already_terminal() -> None:
	from unittest.mock import patch

	from gbedu_worker.tasks.dlq import _handle_dlq_message

	job = _make_job(status=JobStatus.complete)
	_, ctx = _make_session(execute_return=job)

	with patch("gbedu_worker.tasks.dlq.get_async_session", ctx):
		result = await _handle_dlq_message(**_DLQ_KWARGS)

	assert result["action"] == "skipped"
	assert result["reason"] == "already_terminal"
	# Status must NOT be changed to failed
	assert job.status == JobStatus.complete


async def test_handle_dlq_already_failed_skipped() -> None:
	from unittest.mock import patch

	from gbedu_worker.tasks.dlq import _handle_dlq_message

	job = _make_job(status=JobStatus.failed)
	_, ctx = _make_session(execute_return=job)

	with patch("gbedu_worker.tasks.dlq.get_async_session", ctx):
		result = await _handle_dlq_message(**_DLQ_KWARGS)

	assert result["action"] == "skipped"


async def test_handle_dlq_marks_job_failed() -> None:
	from unittest.mock import patch

	from gbedu_worker.tasks.dlq import _handle_dlq_message

	job = _make_job(status=JobStatus.ml_generating)
	_, ctx = _make_session(execute_return=job)

	with patch("gbedu_worker.tasks.dlq.get_async_session", ctx):
		result = await _handle_dlq_message(**_DLQ_KWARGS)

	assert result["action"] == "marked_failed"
	assert job.status == JobStatus.failed
	assert "TimeoutError" in job.error_message
	assert job.completed_at is not None
	assert job.celery_task_id == "task-abc"


async def test_handle_dlq_includes_retry_count_in_reason() -> None:
	from unittest.mock import patch

	from gbedu_worker.tasks.dlq import _handle_dlq_message

	job = _make_job(status=JobStatus.queued)
	_, ctx = _make_session(execute_return=job)

	kwargs = {**_DLQ_KWARGS, "retry_count": 5}
	with patch("gbedu_worker.tasks.dlq.get_async_session", ctx):
		result = await _handle_dlq_message(**kwargs)

	assert "5 retries" in result["dlq_reason"]
