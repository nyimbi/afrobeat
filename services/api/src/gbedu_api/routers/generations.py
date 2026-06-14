from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from gbedu_api.config import RATE_LIMIT_CREATOR, RATE_LIMIT_FREE
from gbedu_api.deps import get_current_active_user, get_db, get_redis, limiter
from gbedu_api.services.generation_service import GenerationService
from gbedu_api.services.ml_client import GenerationRequest
from gbedu_core.errors import GbeduError
from gbedu_core.models.job import GenerationJob
from gbedu_core.models.track import Language, SubGenre
from gbedu_core.models.user import SubscriptionTier, User

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/generations", tags=["generations"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class GenerationCreateRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")
	prompt: str = Field(min_length=10, max_length=2048)
	sub_genre: SubGenre
	language: Language
	bpm: int | None = Field(default=None, ge=60, le=200)
	energy_level: int = Field(default=5, ge=1, le=10)
	voice_model_id: str | None = None
	duration_seconds: int = Field(default=30, ge=10, le=300)


class GenerationJobResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	id: str
	status: str
	progress_percent: int
	prompt_used: str
	model_used: str | None
	error_message: str | None
	track_id: str | None
	created_at: str
	started_at: str | None
	completed_at: str | None


class PaginatedJobsResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	items: list[GenerationJobResponse]
	total: int
	page: int
	page_size: int


class CancelResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	message: str


def _job_response(job: GenerationJob) -> GenerationJobResponse:
	return GenerationJobResponse(
		id=job.id,
		status=job.status.value,
		progress_percent=job.progress_percent,
		prompt_used=job.prompt_used,
		model_used=job.model_used,
		error_message=job.error_message,
		track_id=job.track_id,
		created_at=job.created_at.isoformat(),
		started_at=job.started_at.isoformat() if job.started_at else None,
		completed_at=job.completed_at.isoformat() if job.completed_at else None,
	)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post(
	"",
	response_model=GenerationJobResponse,
	status_code=status.HTTP_202_ACCEPTED,
	summary="Submit a music generation job",
)
@limiter.limit(RATE_LIMIT_FREE)
async def submit_generation(
	request: Request,
	body: GenerationCreateRequest,
	user: Annotated[User, Depends(get_current_active_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
	redis: Annotated[Redis, Depends(get_redis)],
) -> GenerationJobResponse:
	gen_request = GenerationRequest(
		prompt=body.prompt,
		sub_genre=body.sub_genre.value,
		language=body.language.value,
		bpm=body.bpm,
		energy_level=body.energy_level,
		voice_model_id=body.voice_model_id,
		duration_seconds=body.duration_seconds,
	)

	svc = GenerationService(db, redis)
	try:
		job = await svc.submit_job(user=user, request=gen_request)
	except GbeduError as exc:
		raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

	return _job_response(job)


@router.get(
	"/{job_id}",
	response_model=GenerationJobResponse,
	status_code=status.HTTP_200_OK,
	summary="Poll generation job status",
)
async def get_generation_status(
	job_id: str,
	user: Annotated[User, Depends(get_current_active_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
	redis: Annotated[Redis, Depends(get_redis)],
) -> GenerationJobResponse:
	svc = GenerationService(db, redis)
	try:
		job = await svc.get_job_status(job_id, user.id)
	except GbeduError as exc:
		raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

	return _job_response(job)


@router.delete(
	"/{job_id}",
	response_model=CancelResponse,
	status_code=status.HTTP_200_OK,
	summary="Cancel a queued generation job",
)
async def cancel_generation(
	job_id: str,
	user: Annotated[User, Depends(get_current_active_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
	redis: Annotated[Redis, Depends(get_redis)],
) -> CancelResponse:
	svc = GenerationService(db, redis)
	try:
		await svc.cancel_job(job_id, user.id)
	except GbeduError as exc:
		raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

	return CancelResponse(message="Job cancelled successfully")


@router.get(
	"",
	response_model=PaginatedJobsResponse,
	status_code=status.HTTP_200_OK,
	summary="List current user's generation history",
)
async def list_generations(
	user: Annotated[User, Depends(get_current_active_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
	redis: Annotated[Redis, Depends(get_redis)],
	page: int = 1,
	page_size: int = 20,
) -> PaginatedJobsResponse:
	if page < 1:
		page = 1
	if page_size < 1 or page_size > 100:
		page_size = 20

	svc = GenerationService(db, redis)
	jobs, total = await svc.list_jobs(user.id, page=page, page_size=page_size)

	return PaginatedJobsResponse(
		items=[_job_response(j) for j in jobs],
		total=total,
		page=page,
		page_size=page_size,
	)
