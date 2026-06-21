from __future__ import annotations

from typing import Annotated, cast

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from gbedu_core.errors import AuthorizationError, GbeduError, NotFoundError
from gbedu_core.models.track import SubGenre, Track, TrackStatus
from gbedu_core.models.user import SubscriptionTier, User
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gbedu_api.config import PRESIGNED_URL_EXPIRES_SECONDS
from gbedu_api.deps import get_current_active_user, get_db, get_storage, require_tier
from gbedu_api.services.storage_service import StorageClient

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/tracks", tags=["tracks"])


# ── Schemas ────────────────────────────────────────────────────────────────────


class TrackResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	id: str
	title: str
	prompt: str
	sub_genre: str
	language: str
	bpm: int | None
	key: str | None
	energy_level: int
	duration_seconds: int | None
	status: str
	audio_url: str | None
	audio_url_watermarked: str | None
	cover_art_url: str | None
	lyrics: str | None
	is_public: bool
	play_count: int
	share_count: int
	created_at: str


class TrackUpdateRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")
	title: str | None = Field(default=None, min_length=1, max_length=256)
	is_public: bool | None = None


class StemsResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	track_id: str
	stems: dict[str, str]


class ShareCardResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	track_id: str
	title: str
	share_count: int
	og_title: str
	og_description: str
	og_image: str | None


class PaginatedTracksResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	items: list[TrackResponse]
	total: int
	page: int
	page_size: int


class DeleteTrackResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	message: str


def _track_response(track: Track) -> TrackResponse:
	return TrackResponse(
		id=track.id,
		title=track.title,
		prompt=track.prompt,
		sub_genre=track.sub_genre.value,
		language=track.language.value,
		bpm=track.bpm,
		key=track.key,
		energy_level=track.energy_level,
		duration_seconds=track.duration_seconds,
		status=track.status.value,
		audio_url=track.audio_url,
		audio_url_watermarked=track.audio_url_watermarked,
		cover_art_url=track.cover_art_url,
		lyrics=track.lyrics,
		is_public=track.is_public,
		play_count=track.play_count,
		share_count=track.share_count,
		created_at=track.created_at.isoformat(),
	)


async def _get_owned_track(track_id: str, user_id: str, db: AsyncSession) -> Track:
	result = await db.execute(
		select(Track).where(
			Track.id == track_id,
			Track.deleted_at.is_(None),
		)
	)
	track = result.scalar_one_or_none()
	if track is None:
		raise NotFoundError("Track", track_id)
	if track.user_id != user_id:
		raise AuthorizationError("You do not own this track")
	return track


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get(
	"/public",
	response_model=PaginatedTracksResponse,
	status_code=status.HTTP_200_OK,
	summary="Public feed of tracks (newest first)",
)
async def list_public_tracks(
	db: Annotated[AsyncSession, Depends(get_db)],
	page: int = 1,
	page_size: int = 20,
) -> PaginatedTracksResponse:
	if page < 1:
		page = 1
	page_size = max(1, min(page_size, 100))

	count_result = await db.execute(
		select(func.count(Track.id)).where(
			Track.is_public.is_(True),
			Track.status == TrackStatus.ready,
			Track.deleted_at.is_(None),
		)
	)
	total = count_result.scalar_one()

	result = await db.execute(
		select(Track)
		.where(
			Track.is_public.is_(True),
			Track.status == TrackStatus.ready,
			Track.deleted_at.is_(None),
		)
		.order_by(desc(Track.created_at))
		.offset((page - 1) * page_size)
		.limit(page_size)
	)
	tracks = list(result.scalars().all())

	return PaginatedTracksResponse(
		items=[_track_response(t) for t in tracks],
		total=total,
		page=page,
		page_size=page_size,
	)


@router.get(
	"",
	response_model=PaginatedTracksResponse,
	status_code=status.HTTP_200_OK,
	summary="List current user's tracks",
)
async def list_my_tracks(
	user: Annotated[User, Depends(get_current_active_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
	page: int = 1,
	page_size: int = 20,
	sub_genre: SubGenre | None = None,
	track_status: TrackStatus | None = None,
) -> PaginatedTracksResponse:
	if page < 1:
		page = 1
	page_size = max(1, min(page_size, 100))

	filters = [Track.user_id == user.id, Track.deleted_at.is_(None)]
	if sub_genre is not None:
		filters.append(Track.sub_genre == sub_genre)
	if track_status is not None:
		filters.append(Track.status == track_status)

	count_result = await db.execute(select(func.count(Track.id)).where(*filters))
	total = count_result.scalar_one()

	result = await db.execute(
		select(Track)
		.where(*filters)
		.order_by(desc(Track.created_at))
		.offset((page - 1) * page_size)
		.limit(page_size)
	)
	tracks = list(result.scalars().all())

	return PaginatedTracksResponse(
		items=[_track_response(t) for t in tracks],
		total=total,
		page=page,
		page_size=page_size,
	)


@router.get(
	"/{track_id}",
	response_model=TrackResponse,
	status_code=status.HTTP_200_OK,
	summary="Get track detail",
)
async def get_track(
	track_id: str,
	user: Annotated[User, Depends(get_current_active_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> TrackResponse:
	try:
		track = await _get_owned_track(track_id, user.id, db)
	except GbeduError as exc:
		raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())
	return _track_response(track)


@router.patch(
	"/{track_id}",
	response_model=TrackResponse,
	status_code=status.HTTP_200_OK,
	summary="Update track title or visibility",
)
async def update_track(
	track_id: str,
	body: TrackUpdateRequest,
	user: Annotated[User, Depends(get_current_active_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> TrackResponse:
	try:
		track = await _get_owned_track(track_id, user.id, db)
	except GbeduError as exc:
		raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

	if body.title is not None:
		track.title = body.title
	if body.is_public is not None:
		track.is_public = body.is_public

	db.add(track)
	await db.flush()
	return _track_response(track)


@router.delete(
	"/{track_id}",
	response_model=DeleteTrackResponse,
	status_code=status.HTTP_200_OK,
	summary="Soft-delete a track",
)
async def delete_track(
	track_id: str,
	user: Annotated[User, Depends(get_current_active_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> DeleteTrackResponse:
	try:
		track = await _get_owned_track(track_id, user.id, db)
		await track.delete(db)
	except GbeduError as exc:
		raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

	log.info("track.deleted", track_id=track_id, user_id=user.id)
	return DeleteTrackResponse(message="Track deleted")


@router.get(
	"/{track_id}/stems",
	response_model=StemsResponse,
	status_code=status.HTTP_200_OK,
	summary="Get stem presigned URLs (Creator+ tier only)",
)
async def get_stems(
	track_id: str,
	user: Annotated[User, Depends(require_tier(SubscriptionTier.creator))],
	db: Annotated[AsyncSession, Depends(get_db)],
	storage: Annotated[StorageClient, Depends(get_storage)],
) -> StemsResponse:
	try:
		track = await _get_owned_track(track_id, user.id, db)
	except GbeduError as exc:
		raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

	raw_stems = cast(dict[str, str], track.stem_urls or {})
	presigned: dict[str, str] = {}

	for stem_name, r2_key in raw_stems.items():
		try:
			url = await storage.get_presigned_url(r2_key, expires_in=PRESIGNED_URL_EXPIRES_SECONDS)
			presigned[stem_name] = url
		except GbeduError as exc:
			log.warning("track.stems.presign_failed", stem=stem_name, error=str(exc))

	return StemsResponse(track_id=track_id, stems=presigned)


@router.post(
	"/{track_id}/share",
	response_model=ShareCardResponse,
	status_code=status.HTTP_200_OK,
	summary="Generate share card metadata and increment share count",
)
async def share_track(
	track_id: str,
	user: Annotated[User, Depends(get_current_active_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> ShareCardResponse:
	try:
		track = await _get_owned_track(track_id, user.id, db)
	except GbeduError as exc:
		raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

	track.share_count += 1
	db.add(track)
	await db.flush()

	return ShareCardResponse(
		track_id=track.id,
		title=track.title,
		share_count=track.share_count,
		og_title=f"{track.title} — made with Gbẹdu",
		og_description=(f"A {track.sub_genre.value} track generated by AI. Listen on Gbẹdu."),
		og_image=track.cover_art_url,
	)
