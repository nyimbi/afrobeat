from __future__ import annotations

from datetime import datetime, timezone

import structlog
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gbedu_core._uuid7 import uuid7str
from gbedu_core.errors import AuthorizationError, GenerationQuotaError, NotFoundError, WorkerError
from gbedu_core.models.job import GenerationJob, JobStatus, TERMINAL_JOB_STATUSES
from gbedu_core.models.user import TIER_DAILY_LIMITS, User
from gbedu_api.services.ml_client import GenerationRequest, MLServiceClient

log = structlog.get_logger(__name__)

# Redis key for per-user daily generation counter
_QUOTA_KEY_PREFIX = "gen_quota:"
_QUOTA_TTL_SECONDS = 86400  # resets at midnight-ish (rolling 24h window)


class GenerationService:
	def __init__(self, db: AsyncSession, redis: Redis) -> None:
		self._db = db
		self._redis = redis

	async def _check_and_increment_quota(self, user: User) -> None:
		"""Atomically check and increment the daily generation counter in Redis.

		Uses a Redis key with TTL so counters roll over without a cron job.
		Raises GenerationQuotaError if limit is reached.
		"""
		key = f"{_QUOTA_KEY_PREFIX}{user.id}"
		daily_limit = TIER_DAILY_LIMITS[user.subscription_tier]

		# INCR is atomic; set TTL only on first increment (NX flag)
		current = await self._redis.incr(key)
		if current == 1:
			await self._redis.expire(key, _QUOTA_TTL_SECONDS)

		if current > daily_limit:
			# Roll back the counter — user did not consume a generation
			await self._redis.decr(key)
			raise GenerationQuotaError(user.subscription_tier.value, daily_limit)

	async def submit_job(
		self,
		user: User,
		request: GenerationRequest,
	) -> GenerationJob:
		assert user, "user is required"
		assert request, "request is required"

		if not user.is_verified:
			raise AuthorizationError("Email address must be verified before generating tracks")

		await self._check_and_increment_quota(user)

		job = GenerationJob(
			id=uuid7str(),
			user_id=user.id,
			status=JobStatus.queued,
			prompt_used=request.prompt,
			progress_percent=0,
			metadata_={
				"sub_genre": request.sub_genre,
				"language": request.language,
				"bpm": request.bpm,
				"energy_level": request.energy_level,
				"voice_model_id": request.voice_model_id,
				"duration_seconds": request.duration_seconds,
			},
		)
		self._db.add(job)
		await self._db.flush()

		# Enqueue Celery task — import inline to avoid circular dep at module load
		try:
			from gbedu_api.worker_tasks import enqueue_generation
			enqueue_generation(job.id)
		except Exception as exc:
			log.error("generation.enqueue_failed", job_id=job.id, error=str(exc))
			# Do not raise — job is in DB; worker supervisor will pick it up
			# on next sweep. This prevents a failed enqueue from losing the job.

		log.info("generation.submitted", job_id=job.id, user_id=user.id)
		return job

	async def get_job_status(self, job_id: str, user_id: str) -> GenerationJob:
		assert job_id and user_id, "job_id and user_id are required"

		result = await self._db.execute(
			select(GenerationJob).where(GenerationJob.id == job_id)
		)
		job = result.scalar_one_or_none()

		if job is None:
			raise NotFoundError("GenerationJob", job_id)

		if job.user_id != user_id:
			raise AuthorizationError("You do not own this job")

		return job

	async def cancel_job(self, job_id: str, user_id: str) -> None:
		assert job_id and user_id, "job_id and user_id are required"

		job = await self.get_job_status(job_id, user_id)

		if job.status in TERMINAL_JOB_STATUSES:
			raise WorkerError(
				f"Cannot cancel job in terminal state {job.status.value}",
				task_id=job.celery_task_id,
			)

		# Revoke Celery task if it has been dispatched
		if job.celery_task_id:
			try:
				from gbedu_api.worker_tasks import revoke_task
				revoke_task(job.celery_task_id)
			except Exception as exc:
				log.warning("generation.revoke_failed", task_id=job.celery_task_id, error=str(exc))

		job.status = JobStatus.cancelled
		self._db.add(job)
		await self._db.flush()

		# Refund the quota slot
		key = f"{_QUOTA_KEY_PREFIX}{user_id}"
		await self._redis.decr(key)

		log.info("generation.cancelled", job_id=job_id, user_id=user_id)

	async def list_jobs(
		self,
		user_id: str,
		page: int = 1,
		page_size: int = 20,
	) -> tuple[list[GenerationJob], int]:
		assert user_id, "user_id is required"
		assert page >= 1 and page_size >= 1

		from sqlalchemy import func, desc

		count_result = await self._db.execute(
			select(func.count(GenerationJob.id)).where(GenerationJob.user_id == user_id)
		)
		total = count_result.scalar_one()

		result = await self._db.execute(
			select(GenerationJob)
			.where(GenerationJob.user_id == user_id)
			.order_by(desc(GenerationJob.created_at))
			.offset((page - 1) * page_size)
			.limit(page_size)
		)
		jobs = list(result.scalars().all())
		return jobs, total
