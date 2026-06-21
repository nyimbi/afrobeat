from __future__ import annotations

from datetime import datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from gbedu_core._uuid7 import uuid7str
from gbedu_core.errors import GbeduError
from gbedu_core.models.track import Track, TrackStatus
from gbedu_core.models.user import TIER_DAILY_LIMITS, User
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gbedu_api.config import MAX_UPLOAD_SIZE_BYTES
from gbedu_api.deps import get_current_active_user, get_db, get_redis, get_storage
from gbedu_api.services.storage_service import StorageClient

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


# ── Schemas ────────────────────────────────────────────────────────────────────


class UserProfileResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	id: str
	email: str
	full_name: str
	avatar_url: str | None
	subscription_tier: str
	subscription_status: str
	is_verified: bool
	is_active: bool
	preferred_language: str
	created_at: datetime


class UpdateProfileRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")
	full_name: str | None = Field(default=None, min_length=1, max_length=256)
	preferred_language: str | None = Field(default=None, min_length=2, max_length=8)


class UserStatsResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	total_tracks: int
	tracks_ready: int
	total_generations_today: int
	daily_limit: int
	subscription_tier: str
	subscription_status: str


class DeleteAccountResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	message: str


def _profile(user: User) -> UserProfileResponse:
	return UserProfileResponse(
		id=user.id,
		email=user.email,
		full_name=user.full_name,
		avatar_url=user.avatar_url,
		subscription_tier=user.subscription_tier.value,
		subscription_status=user.subscription_status.value,
		is_verified=user.is_verified,
		is_active=user.is_active,
		preferred_language=user.preferred_language,
		created_at=user.created_at,
	)


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get(
	"/me",
	response_model=UserProfileResponse,
	status_code=status.HTTP_200_OK,
	summary="Get current user profile",
)
async def get_me(
	user: Annotated[User, Depends(get_current_active_user)],
) -> UserProfileResponse:
	return _profile(user)


@router.patch(
	"/me",
	response_model=UserProfileResponse,
	status_code=status.HTTP_200_OK,
	summary="Update current user profile",
)
async def update_me(
	body: UpdateProfileRequest,
	user: Annotated[User, Depends(get_current_active_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> UserProfileResponse:
	if body.full_name is not None:
		user.full_name = body.full_name
	if body.preferred_language is not None:
		user.preferred_language = body.preferred_language

	db.add(user)
	await db.flush()
	return _profile(user)


@router.post(
	"/me/avatar",
	response_model=UserProfileResponse,
	status_code=status.HTTP_200_OK,
	summary="Upload a new avatar image",
)
async def upload_avatar(
	file: UploadFile,
	user: Annotated[User, Depends(get_current_active_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
	storage: Annotated[StorageClient, Depends(get_storage)],
) -> UserProfileResponse:
	allowed_types = {"image/jpeg", "image/png", "image/webp"}
	if file.content_type not in allowed_types:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail={
				"error_code": "VALIDATION_ERROR",
				"message": "Avatar must be JPEG, PNG, or WebP",
			},
		)

	content = await file.read()
	if len(content) > MAX_UPLOAD_SIZE_BYTES:
		raise HTTPException(
			status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
			detail={
				"error_code": "VALIDATION_ERROR",
				"message": f"Avatar exceeds {MAX_UPLOAD_SIZE_BYTES // 1024 // 1024}MB limit",
			},
		)

	ext = file.content_type.split("/")[1]
	key = f"avatars/{user.id}/{uuid7str()}.{ext}"

	import tempfile
	from pathlib import Path

	with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
		tmp.write(content)
		tmp_path = Path(tmp.name)

	try:
		url = await storage.upload_audio(tmp_path, key, content_type=file.content_type)
	except GbeduError as exc:
		raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())
	finally:
		tmp_path.unlink(missing_ok=True)

	user.avatar_url = url
	db.add(user)
	await db.flush()
	return _profile(user)


@router.get(
	"/me/stats",
	response_model=UserStatsResponse,
	status_code=status.HTTP_200_OK,
	summary="Get generation stats and subscription info",
)
async def get_my_stats(
	user: Annotated[User, Depends(get_current_active_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
	redis: Annotated[Redis, Depends(get_redis)],
) -> UserStatsResponse:
	total_tracks_result = await db.execute(
		select(func.count(Track.id)).where(
			Track.user_id == user.id,
			Track.deleted_at.is_(None),
		)
	)
	total_tracks = total_tracks_result.scalar_one()

	ready_tracks_result = await db.execute(
		select(func.count(Track.id)).where(
			Track.user_id == user.id,
			Track.status == TrackStatus.ready,
			Track.deleted_at.is_(None),
		)
	)
	tracks_ready = ready_tracks_result.scalar_one()

	raw = await redis.get(f"gen_quota:{user.id}")
	today_count = int(raw) if raw is not None else 0

	return UserStatsResponse(
		total_tracks=total_tracks,
		tracks_ready=tracks_ready,
		total_generations_today=today_count,
		daily_limit=TIER_DAILY_LIMITS[user.subscription_tier],
		subscription_tier=user.subscription_tier.value,
		subscription_status=user.subscription_status.value,
	)


@router.delete(
	"/me",
	response_model=DeleteAccountResponse,
	status_code=status.HTTP_200_OK,
	summary="Soft-delete account and cancel subscription",
)
async def delete_me(
	user: Annotated[User, Depends(get_current_active_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> DeleteAccountResponse:
	await user.delete(db)
	log.info("user.soft_deleted", user_id=user.id)
	return DeleteAccountResponse(message="Account scheduled for deletion")
