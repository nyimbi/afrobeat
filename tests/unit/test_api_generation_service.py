from __future__ import annotations

"""Unit tests for GenerationService — mocked DB and Redis."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Fixtures ───────────────────────────────────────────────────────────────────


def _mock_user(tier: str = "free", verified: bool = True):
	from gbedu_core.models.user import SubscriptionTier, User

	u = MagicMock(spec=User)
	u.id = "user-aaa-111"
	u.subscription_tier = SubscriptionTier(tier)
	u.is_verified = verified
	u.is_active = True
	u.deleted_at = None
	return u


def _mock_session():
	"""Return an AsyncMock SQLAlchemy session.

	execute() returns a plain MagicMock result so that synchronous methods
	like fetchone() and scalar_one_or_none() return values, not coroutines.
	"""
	db = AsyncMock()
	_result = MagicMock()
	db.execute = AsyncMock(return_value=_result)
	db.flush = AsyncMock()
	db.add = MagicMock()
	db.commit = AsyncMock()
	return db


def _mock_redis():
	r = AsyncMock()
	r.incr = AsyncMock(return_value=1)
	r.expire = AsyncMock()
	r.decr = AsyncMock(return_value=0)
	return r


def _make_service(db=None, redis=None):
	from gbedu_api.services.generation_service import GenerationService

	return GenerationService(db or _mock_session(), redis or _mock_redis())


def _make_request(**kwargs):
	defaults = {
		"prompt": "Afrobeats love song in Yoruba",
		"sub_genre": "afropop",
		"language": "yoruba",
		"bpm": None,
		"energy_level": None,
		"voice_model_id": None,
		"duration_seconds": 30,
	}
	defaults.update(kwargs)
	return MagicMock(**defaults)


def _mock_job(job_id: str = "job-001", user_id: str = "user-aaa-111", status: str = "queued"):
	from gbedu_core.models.job import GenerationJob, JobStatus

	job = MagicMock(spec=GenerationJob)
	job.id = job_id
	job.user_id = user_id
	job.status = JobStatus(status)
	job.celery_task_id = None
	return job


# ── _check_and_increment_quota ─────────────────────────────────────────────────


async def test_check_quota_increments_redis_on_success() -> None:
	db = _mock_session()
	redis = _mock_redis()
	# DB returns a row (quota not exhausted)
	mock_row = MagicMock()
	db.execute.return_value.fetchone.return_value = mock_row

	svc = _make_service(db, redis)
	await svc._check_and_increment_quota(_mock_user("free"))

	redis.incr.assert_awaited_once()
	redis.expire.assert_awaited_once()


async def test_check_quota_raises_when_db_returns_no_row() -> None:
	from gbedu_core.errors import GenerationQuotaError

	db = _mock_session()
	db.execute.return_value.fetchone.return_value = None  # quota exhausted

	svc = _make_service(db)
	with pytest.raises(GenerationQuotaError):
		await svc._check_and_increment_quota(_mock_user("free"))


async def test_check_quota_redis_failure_is_ignored() -> None:
	db = _mock_session()
	redis = _mock_redis()
	redis.incr.side_effect = Exception("redis down")
	db.execute.return_value.fetchone.return_value = MagicMock()

	svc = _make_service(db, redis)
	# Should not raise even when Redis is unavailable
	await svc._check_and_increment_quota(_mock_user("creator"))


async def test_check_quota_skips_redis_expire_when_key_already_exists() -> None:
	db = _mock_session()
	redis = _mock_redis()
	redis.incr.return_value = 5  # key already existed (count > 1)
	db.execute.return_value.fetchone.return_value = MagicMock()

	svc = _make_service(db, redis)
	await svc._check_and_increment_quota(_mock_user("pro"))

	redis.expire.assert_not_awaited()


# ── submit_job ─────────────────────────────────────────────────────────────────


async def test_submit_job_returns_generation_job() -> None:
	db = _mock_session()
	redis = _mock_redis()
	db.execute.return_value.fetchone.return_value = MagicMock()

	svc = _make_service(db, redis)
	user = _mock_user(verified=True)
	request = _make_request()

	with patch("gbedu_api.worker_tasks.enqueue_generation"):
		job = await svc.submit_job(user, request)

	assert job is not None
	db.add.assert_called_once()
	db.flush.assert_awaited_once()


async def test_submit_job_raises_when_unverified() -> None:
	from gbedu_core.errors import AuthorizationError

	svc = _make_service()
	user = _mock_user(verified=False)

	with pytest.raises(AuthorizationError, match="verified"):
		await svc.submit_job(user, _make_request())


async def test_submit_job_enqueue_failure_does_not_raise() -> None:
	"""Enqueue failure must NOT propagate — job is in DB, worker will pick it up."""
	db = _mock_session()
	redis = _mock_redis()
	db.execute.return_value.fetchone.return_value = MagicMock()

	svc = _make_service(db, redis)
	user = _mock_user(verified=True)

	with patch("gbedu_api.worker_tasks.enqueue_generation", side_effect=Exception("celery down")):
		job = await svc.submit_job(user, _make_request())

	assert job is not None


async def test_submit_job_raises_on_null_user() -> None:
	svc = _make_service()
	with pytest.raises(AssertionError):
		await svc.submit_job(None, _make_request())  # type: ignore


# ── get_job_status ─────────────────────────────────────────────────────────────


async def test_get_job_status_returns_job() -> None:
	db = _mock_session()
	job = _mock_job()
	db.execute.return_value.scalar_one_or_none.return_value = job

	svc = _make_service(db)
	result = await svc.get_job_status("job-001", "user-aaa-111")

	assert result.id == "job-001"


async def test_get_job_status_raises_not_found() -> None:
	from gbedu_core.errors import NotFoundError

	db = _mock_session()
	db.execute.return_value.scalar_one_or_none.return_value = None

	svc = _make_service(db)
	with pytest.raises(NotFoundError):
		await svc.get_job_status("job-missing", "user-aaa-111")


async def test_get_job_status_raises_when_wrong_user() -> None:
	from gbedu_core.errors import AuthorizationError

	db = _mock_session()
	job = _mock_job(user_id="other-user")
	db.execute.return_value.scalar_one_or_none.return_value = job

	svc = _make_service(db)
	with pytest.raises(AuthorizationError):
		await svc.get_job_status("job-001", "user-aaa-111")


# ── cancel_job ────────────────────────────────────────────────────────────────


async def test_cancel_job_sets_status_cancelled() -> None:
	db = _mock_session()
	redis = _mock_redis()
	job = _mock_job(status="queued")
	db.execute.return_value.scalar_one_or_none.return_value = job

	svc = _make_service(db, redis)
	with patch("gbedu_api.worker_tasks.revoke_task"):
		await svc.cancel_job("job-001", "user-aaa-111")

	assert job.status.value == "cancelled"
	db.flush.assert_awaited()


async def test_cancel_job_raises_when_already_terminal() -> None:
	from gbedu_core.errors import WorkerError

	db = _mock_session()
	job = _mock_job(status="complete")  # JobStatus.complete is terminal
	db.execute.return_value.scalar_one_or_none.return_value = job

	svc = _make_service(db)
	with pytest.raises(WorkerError, match="terminal"):
		await svc.cancel_job("job-001", "user-aaa-111")


async def test_cancel_job_revokes_celery_task_when_dispatched() -> None:
	db = _mock_session()
	redis = _mock_redis()
	job = _mock_job(status="ml_generating")  # non-terminal, has celery task
	job.celery_task_id = "celery-task-xyz"
	db.execute.return_value.scalar_one_or_none.return_value = job

	svc = _make_service(db, redis)
	with patch("gbedu_api.worker_tasks.revoke_task") as mock_revoke:
		await svc.cancel_job("job-001", "user-aaa-111")

	mock_revoke.assert_called_once_with("celery-task-xyz")


async def test_cancel_job_revoke_failure_is_ignored() -> None:
	db = _mock_session()
	redis = _mock_redis()
	job = _mock_job(status="queued")
	job.celery_task_id = "celery-task-abc"
	db.execute.return_value.scalar_one_or_none.return_value = job

	svc = _make_service(db, redis)
	with patch("gbedu_api.worker_tasks.revoke_task", side_effect=Exception("celery down")):
		await svc.cancel_job("job-001", "user-aaa-111")  # should not raise

	assert job.status.value == "cancelled"


async def test_cancel_job_decrements_redis_quota() -> None:
	db = _mock_session()
	redis = _mock_redis()
	job = _mock_job(status="queued")
	db.execute.return_value.scalar_one_or_none.return_value = job

	svc = _make_service(db, redis)
	with patch("gbedu_api.worker_tasks.revoke_task"):
		await svc.cancel_job("job-001", "user-aaa-111")

	redis.decr.assert_awaited_once()


# ── list_jobs ─────────────────────────────────────────────────────────────────


async def test_list_jobs_returns_jobs_and_total() -> None:
	db = _mock_session()
	job = _mock_job()
	count_result = MagicMock()
	count_result.scalar_one.return_value = 1
	jobs_result = MagicMock()
	jobs_result.scalars.return_value.all.return_value = [job]
	db.execute.side_effect = [count_result, jobs_result]

	svc = _make_service(db)
	jobs, total = await svc.list_jobs("user-aaa-111")

	assert total == 1
	assert len(jobs) == 1


async def test_list_jobs_raises_on_empty_user_id() -> None:
	svc = _make_service()
	with pytest.raises(AssertionError):
		await svc.list_jobs("")


async def test_list_jobs_pagination_defaults() -> None:
	db = _mock_session()
	count_result = MagicMock()
	count_result.scalar_one.return_value = 0
	jobs_result = MagicMock()
	jobs_result.scalars.return_value.all.return_value = []
	db.execute.side_effect = [count_result, jobs_result]

	svc = _make_service(db)
	jobs, total = await svc.list_jobs("user-aaa-111", page=1, page_size=20)

	assert total == 0
	assert jobs == []
