from __future__ import annotations

"""Unit tests for gbedu_worker.tasks.generation async helpers."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gbedu_core.models.job import JobStatus


# ── helpers ───────────────────────────────────────────────────────────────

def _make_job(job_id: str = "job-1", status: JobStatus = JobStatus.queued) -> MagicMock:
	job = MagicMock()
	job.id = job_id
	job.status = status
	job.is_terminal = status in (JobStatus.failed, JobStatus.complete)
	job.error_message = None
	job.error_traceback = None
	job.completed_at = None
	return job


def _make_session(execute_return: Any = None) -> tuple[MagicMock, Any]:
	session = MagicMock()
	session.add = MagicMock()
	session.commit = AsyncMock()

	result = MagicMock()
	result.scalar_one_or_none.return_value = execute_return
	session.execute = AsyncMock(return_value=result)

	@asynccontextmanager
	async def _ctx():
		yield session

	return session, _ctx


# ── _run_pipeline ─────────────────────────────────────────────────────────

async def test_run_pipeline_delegates_to_orchestrator() -> None:
	from gbedu_worker.tasks.generation import _run_pipeline

	mock_orchestrator = AsyncMock()
	mock_orchestrator.run = AsyncMock(return_value={"status": "complete", "track_id": "t1"})

	session_mock = MagicMock()
	session_mock.add = MagicMock()
	session_mock.commit = AsyncMock()

	@asynccontextmanager
	async def _ctx():
		yield session_mock

	with patch("gbedu_worker.tasks.generation.get_async_session", _ctx):
		with patch(
			"gbedu_worker.tasks.generation.GenerationPipelineOrchestrator",
			return_value=mock_orchestrator,
		):
			result = await _run_pipeline("job-1")

	assert result["status"] == "complete"
	mock_orchestrator.run.assert_awaited_once()


# ── _mark_job_failed ──────────────────────────────────────────────────────

async def test_mark_job_failed_sets_status() -> None:
	from gbedu_worker.tasks.generation import _mark_job_failed

	job = _make_job(status=JobStatus.queued)
	job.is_terminal = False
	_, ctx = _make_session(job)

	with patch("gbedu_worker.tasks.generation.get_async_session", ctx):
		await _mark_job_failed("job-1", RuntimeError("ml exploded"))

	assert job.status == JobStatus.failed
	assert "ml exploded" in job.error_message
	assert job.completed_at is not None


async def test_mark_job_failed_no_op_if_terminal() -> None:
	from gbedu_worker.tasks.generation import _mark_job_failed

	job = _make_job(status=JobStatus.complete)
	job.is_terminal = True
	_, ctx = _make_session(job)

	with patch("gbedu_worker.tasks.generation.get_async_session", ctx):
		await _mark_job_failed("job-1", RuntimeError("irrelevant"))

	# Status must remain complete
	assert job.status == JobStatus.complete


async def test_mark_job_failed_no_op_if_not_found() -> None:
	from gbedu_worker.tasks.generation import _mark_job_failed

	_, ctx = _make_session(None)

	with patch("gbedu_worker.tasks.generation.get_async_session", ctx):
		# Should not raise
		await _mark_job_failed("job-missing", RuntimeError("gone"))


# ── _route_to_dlq ─────────────────────────────────────────────────────────

def test_route_to_dlq_enqueues_dlq_task() -> None:
	from gbedu_worker.tasks.generation import _route_to_dlq
	import structlog
	import gbedu_worker.tasks.dlq as dlq_mod

	mock_task = MagicMock()
	mock_task.apply_async = MagicMock()

	orig = dlq_mod.process_dlq_message
	dlq_mod.process_dlq_message = mock_task
	try:
		_route_to_dlq(
			job_id="job-1",
			original_task_id="task-abc",
			original_queue="default",
			exc=TimeoutError("ml timeout"),
			retry_count=3,
			task_log=structlog.get_logger(),
		)
	finally:
		dlq_mod.process_dlq_message = orig

	mock_task.apply_async.assert_called_once()
	kwargs = mock_task.apply_async.call_args[1]["kwargs"]
	assert kwargs["job_id"] == "job-1"
	assert kwargs["error_type"] == "TimeoutError"


def test_route_to_dlq_dlq_failure_does_not_raise() -> None:
	"""DLQ publish errors must never mask the original exception."""
	from gbedu_worker.tasks.generation import _route_to_dlq
	import structlog
	import gbedu_worker.tasks.dlq as dlq_mod

	mock_task = MagicMock()
	mock_task.apply_async.side_effect = Exception("broker down")

	orig = dlq_mod.process_dlq_message
	dlq_mod.process_dlq_message = mock_task
	try:
		_route_to_dlq(
			job_id="job-1",
			original_task_id="task-abc",
			original_queue="default",
			exc=TimeoutError("ml timeout"),
			retry_count=1,
			task_log=structlog.get_logger(),
		)
	finally:
		dlq_mod.process_dlq_message = orig
	# No exception raised — test passes if we reach here


# ── retry countdowns ───────────────────────────────────────────────────────

def test_retry_countdown_values() -> None:
	from gbedu_worker.tasks.generation import _RETRY_COUNTDOWN

	assert _RETRY_COUNTDOWN == (30, 90, 270)
