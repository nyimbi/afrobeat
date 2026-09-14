from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, cast

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from gbedu_core._uuid7 import uuid7str
from gbedu_core.errors import GbeduError
from gbedu_core.models.job import GenerationJob
from gbedu_core.models.track import Language, SubGenre
from gbedu_core.models.user import User
from pydantic import BaseModel, ConfigDict, Field, field_validator
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from gbedu_api.config import MAX_UPLOAD_SIZE_BYTES, RATE_LIMIT_FREE
from gbedu_api.deps import get_current_active_user, get_db, get_redis, get_storage, limiter
from gbedu_api.services.generation_service import GenerationService
from gbedu_api.services.ml_client import GenerationRequest
from gbedu_api.services.storage_service import StorageClient

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/generations", tags=["generations"])


def _rate_limit[F: Callable[..., Any]](limit_value: str) -> Callable[[F], F]:
	return cast(Callable[[F], F], cast(Any, limiter).limit(limit_value))


# ── Schemas ────────────────────────────────────────────────────────────────────


class GenerationCreateRequest(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)
	prompt: str = Field(min_length=10, max_length=2048)
	sub_genre: SubGenre = Field(validation_alias="subGenre")
	language: Language
	bpm: int | None = Field(default=None, ge=60, le=200)
	energy_level: int = Field(default=5, ge=1, le=10, validation_alias="energyLevel")
	voice_model_id: str | None = Field(default=None, validation_alias="voiceModelId")
	duration_seconds: int = Field(default=30, ge=10, le=300, validation_alias="durationSeconds")
	# Optional user-supplied lyrics — skips AI lyric generation.
	lyrics: str | None = Field(default=None, min_length=1, max_length=5000)
	# Optional RNG seed — same prompt + same seed reproduces a rendition.
	seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
	# Optional R2 key from POST /generations/reference — steers tempo/key/feel.
	reference_audio_key: str | None = Field(
		default=None, min_length=1, max_length=1024, validation_alias="referenceAudioKey"
	)

	@field_validator("lyrics")
	@classmethod
	def strip_lyrics(cls, v: str | None) -> str | None:
		if v is None:
			return None
		stripped = v.strip()
		if not stripped:
			raise ValueError("lyrics must not be blank — omit the field for AI lyrics")
		return stripped

	@field_validator("reference_audio_key")
	@classmethod
	def strip_reference_audio_key(cls, v: str | None) -> str | None:
		if v is None:
			return None
		stripped = v.strip()
		if not stripped:
			raise ValueError("reference_audio_key must not be blank — omit the field for no reference")
		return stripped


class GenerationJobResponse(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)
	id: str
	status: str
	progress_percent: int = Field(alias="progressPercent")
	prompt_used: str = Field(alias="promptUsed")
	model_used: str | None = Field(default=None, alias="modelUsed")
	error_message: str | None = Field(default=None, alias="errorMessage")
	track_id: str | None = Field(default=None, alias="trackId")
	created_at: str = Field(alias="createdAt")
	started_at: str | None = Field(default=None, alias="startedAt")
	completed_at: str | None = Field(default=None, alias="completedAt")
	status_message: str = Field(default="", alias="statusMessage")
	estimated_seconds: int | None = Field(default=None, alias="estimatedSeconds")


class PaginatedJobsResponse(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)
	items: list[GenerationJobResponse]
	total: int
	page: int
	page_size: int = Field(alias="pageSize")


class CancelResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	message: str


class ReferenceUploadResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	key: str


_REFERENCE_AUDIO_TYPES = {
	"audio/mpeg",
	"audio/wav",
	"audio/flac",
	"audio/x-wav",
	"audio/ogg",
}


_STATUS_MESSAGES: dict[str, str] = {
	"queued": "Your track is queued...",
	"ml_generating": "Composing your track...",
	"audio_processing": "Mastering your track...",
	"uploading": "Uploading your track...",
	"complete": "Your track is ready!",
	"failed": "Generation failed. Please try again.",
	"cancelled": "Generation cancelled.",
}


# Rough per-tier estimate used for the ETA hint. Duration-driven: ML generation
# dominates wall time; add fixed overhead for DSP + upload.
def _estimate_seconds(duration_seconds: int) -> int:
	return max(45, int(duration_seconds * 0.6) + 30)


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
	).model_dump(by_alias=True, exclude_none=False)


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.post(
	"",
	response_model=GenerationJobResponse,
	status_code=status.HTTP_202_ACCEPTED,
	summary="Submit a music generation job",
)
@_rate_limit(RATE_LIMIT_FREE)
async def submit_generation(
	request: Request,
	body: GenerationCreateRequest,
	user: Annotated[User, Depends(get_current_active_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
	redis: Annotated[Redis, Depends(get_redis)],
) -> GenerationJobResponse:
	if body.reference_audio_key is not None and not body.reference_audio_key.startswith(
		f"reference-samples/{user.id}/"
	):
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail={
				"error_code": "VALIDATION_ERROR",
				"message": "reference_audio_key must be a key issued to you via POST /generations/reference",
			},
		)

	gen_request = GenerationRequest(
		prompt=body.prompt,
		sub_genre=body.sub_genre.value,
		language=body.language.value,
		bpm=body.bpm,
		energy_level=body.energy_level,
		voice_model_id=body.voice_model_id,
		duration_seconds=body.duration_seconds,
		lyrics=body.lyrics,
		seed=body.seed,
		reference_audio_key=body.reference_audio_key,
	)

	svc = GenerationService(db, redis)
	try:
		job = await svc.submit_job(user=user, request=gen_request)
	except GbeduError as exc:
		raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

	resp = _job_response(job)
	resp["statusMessage"] = _STATUS_MESSAGES.get(job.status.value, "")
	resp["estimatedSeconds"] = _estimate_seconds(body.duration_seconds)
	return resp


@router.post(
	"/reference",
	response_model=ReferenceUploadResponse,
	status_code=status.HTTP_202_ACCEPTED,
	summary="Upload a reference track to steer a generation",
)
@_rate_limit(RATE_LIMIT_FREE)
async def upload_reference_track(
	request: Request,
	file: UploadFile,
	user: Annotated[User, Depends(get_current_active_user)],
	storage: Annotated[StorageClient, Depends(get_storage)],
) -> ReferenceUploadResponse:
	"""Store a user-supplied beat/song; returns a key for `referenceAudioKey`.

	The worker analyses tempo/key/energy from the file at generation time.
	"""
	if file.content_type not in _REFERENCE_AUDIO_TYPES:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail={
				"error_code": "VALIDATION_ERROR",
				"message": f"Unsupported audio type {file.content_type}. Use MP3, WAV, FLAC, or OGG.",
			},
		)

	content = await file.read()
	if len(content) > MAX_UPLOAD_SIZE_BYTES:
		raise HTTPException(
			status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
			detail={
				"error_code": "VALIDATION_ERROR",
				"message": f"File exceeds {MAX_UPLOAD_SIZE_BYTES // 1024 // 1024}MB limit",
			},
		)

	ext = (file.filename or "audio.wav").rsplit(".", 1)[-1].lower()
	key = f"reference-samples/{user.id}/{uuid7str()}/ref.{ext}"

	import tempfile
	from pathlib import Path

	with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
		tmp.write(content)
		tmp_path = Path(tmp.name)

	try:
		await storage.upload_audio(tmp_path, key, content_type=file.content_type)
	except GbeduError as exc:
		raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())
	finally:
		tmp_path.unlink(missing_ok=True)

	log.info("generation.reference.uploaded", key=key, user_id=user.id)
	return ReferenceUploadResponse(key=key)


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
	).model_dump(by_alias=True)
