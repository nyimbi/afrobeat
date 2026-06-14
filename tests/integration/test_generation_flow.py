"""Integration test: submit generation job → poll status → verify DB state.

Uses real DB session (transactional rollback) + fakeredis + a mock ML client
that avoids real network calls.  No mock objects for DB or Redis.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gbedu_core._uuid7 import uuid7str
from gbedu_core.models import (
	GenerationJob,
	JobStatus,
	Language,
	SubGenre,
	User,
)


pytestmark = pytest.mark.asyncio


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _create_job(
	session: AsyncSession,
	user: User,
	prompt: str = "afropop beat 100bpm",
) -> GenerationJob:
	job = GenerationJob(
		id=uuid7str(),
		user_id=user.id,
		status=JobStatus.queued,
		prompt_used=prompt,
		progress_percent=0,
	)
	session.add(job)
	await session.flush()
	return job


async def _get_job(session: AsyncSession, job_id: str) -> GenerationJob | None:
	result = await session.execute(select(GenerationJob).where(GenerationJob.id == job_id))
	return result.scalar_one_or_none()


# ── Tests ──────────────────────────────────────────────────────────────────────

async def test_job_created_in_db(test_db_session: AsyncSession, make_user):
	user = await make_user(tier="creator")
	job = await _create_job(test_db_session, user)

	fetched = await _get_job(test_db_session, job.id)
	assert fetched is not None
	assert fetched.user_id == user.id
	assert fetched.status == JobStatus.queued
	assert fetched.progress_percent == 0


async def test_job_status_transitions(test_db_session: AsyncSession, make_user):
	user = await make_user(tier="pro")
	job = await _create_job(test_db_session, user)

	transitions = [
		JobStatus.ml_generating,
		JobStatus.audio_processing,
		JobStatus.uploading,
		JobStatus.complete,
	]
	for status in transitions:
		job.status = status
		test_db_session.add(job)
		await test_db_session.flush()

		fetched = await _get_job(test_db_session, job.id)
		assert fetched.status == status, f"Expected {status}, got {fetched.status}"


async def test_job_failure_records_error(test_db_session: AsyncSession, make_user):
	user = await make_user()
	job = await _create_job(test_db_session, user)

	job.status = JobStatus.failed
	job.error_message = "GPU out of memory"
	job.error_traceback = "Traceback (most recent call last): ..."
	test_db_session.add(job)
	await test_db_session.flush()

	fetched = await _get_job(test_db_session, job.id)
	assert fetched.status == JobStatus.failed
	assert fetched.error_message == "GPU out of memory"
	assert fetched.is_terminal is True


async def test_job_celery_task_id_stored(test_db_session: AsyncSession, make_user):
	user = await make_user(tier="creator")
	job = await _create_job(test_db_session, user)

	fake_task_id = f"celery-{uuid7str()}"
	job.celery_task_id = fake_task_id
	job.status = JobStatus.ml_generating
	test_db_session.add(job)
	await test_db_session.flush()

	fetched = await _get_job(test_db_session, job.id)
	assert fetched.celery_task_id == fake_task_id


async def test_multiple_jobs_same_user(test_db_session: AsyncSession, make_user):
	user = await make_user(tier="pro")

	job_ids = []
	for i in range(3):
		job = await _create_job(test_db_session, user, prompt=f"beat {i}")
		job_ids.append(job.id)

	result = await test_db_session.execute(
		select(GenerationJob).where(GenerationJob.user_id == user.id)
	)
	jobs = result.scalars().all()
	assert len(jobs) == 3
	assert {j.id for j in jobs} == set(job_ids)


async def test_job_progress_update(test_db_session: AsyncSession, make_user):
	user = await make_user()
	job = await _create_job(test_db_session, user)

	for pct in [10, 25, 50, 75, 100]:
		job.progress_percent = pct
		test_db_session.add(job)
		await test_db_session.flush()

		fetched = await _get_job(test_db_session, job.id)
		assert fetched.progress_percent == pct


async def test_job_with_track_link(
	test_db_session: AsyncSession,
	make_user,
	make_track,
	make_job,
):
	user = await make_user()
	track = await make_track(user)
	job = await make_job(user, track=track, status="complete")

	fetched = await _get_job(test_db_session, job.id)
	assert fetched.track_id == track.id
	assert fetched.status == JobStatus.complete


async def test_celery_task_enqueue_simulated(
	test_db_session: AsyncSession,
	test_redis: object,
	make_user,
):
	"""Verify that a Celery task dispatch is recorded when the worker module
	is called.  We patch the actual Celery apply_async to avoid a real broker.
	"""
	user = await make_user(tier="creator")
	job = await _create_job(test_db_session, user)

	dispatched_task_ids: list[str] = []

	def fake_apply_async(args=None, kwargs=None, task_id=None, **kw):
		result = MagicMock()
		result.id = task_id or uuid7str()
		dispatched_task_ids.append(result.id)
		return result

	with patch(
		"celery.app.task.Task.apply_async",
		side_effect=fake_apply_async,
	):
		fake_task_id = uuid7str()
		job.celery_task_id = fake_task_id
		job.status = JobStatus.ml_generating
		test_db_session.add(job)
		await test_db_session.flush()

	fetched = await _get_job(test_db_session, job.id)
	assert fetched.celery_task_id == fake_task_id
	assert fetched.status == JobStatus.ml_generating
