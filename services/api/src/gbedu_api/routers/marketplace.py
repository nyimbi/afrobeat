from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gbedu_api.deps import get_current_active_user, get_db, require_tier
from gbedu_core._uuid7 import uuid7str
from gbedu_core.errors import AuthorizationError, GbeduError, NotFoundError
from gbedu_core.models.marketplace import BeatListing, BeatPurchase, LicenseType, ListingStatus
from gbedu_core.models.payment import Payment, PaymentProvider, PaymentStatus
from gbedu_core.models.track import Track, TrackStatus
from gbedu_core.models.user import SubscriptionTier, User

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class ListingResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	id: str
	track_id: str
	seller_id: str
	title: str
	description: str | None
	status: str
	license_type: str
	price_minor: int
	price_decimal: float
	currency: str
	view_count: int
	purchase_count: int
	tags: list[str]
	preview_url: str | None
	sub_genre: str
	bpm: int | None
	created_at: str


class CreateListingRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")
	track_id: str
	title: str = Field(min_length=1, max_length=256)
	description: str | None = None
	license_type: LicenseType = LicenseType.non_exclusive
	price_minor: int = Field(ge=0)
	currency: str = Field(default="USD", min_length=3, max_length=3)
	tags: list[str] = Field(default_factory=list)


class PurchaseResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	id: str
	listing_id: str
	amount_minor: int
	currency: str
	license_type: str
	download_url: str | None
	created_at: str


class PaginatedListingsResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	items: list[ListingResponse]
	total: int
	page: int
	page_size: int


def _listing_response(listing: BeatListing, track: Track | None = None) -> ListingResponse:
	sub_genre = track.sub_genre.value if track else ""
	bpm = track.bpm if track else None
	return ListingResponse(
		id=listing.id,
		track_id=listing.track_id,
		seller_id=listing.seller_id,
		title=listing.title,
		description=listing.description,
		status=listing.status.value,
		license_type=listing.license_type.value,
		price_minor=listing.price_minor,
		price_decimal=listing.price_decimal,
		currency=listing.currency,
		view_count=listing.view_count,
		purchase_count=listing.purchase_count,
		tags=listing.tags,
		preview_url=listing.preview_url,
		sub_genre=sub_genre,
		bpm=bpm,
		created_at=listing.created_at.isoformat(),
	)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get(
	"/beats",
	response_model=PaginatedListingsResponse,
	status_code=status.HTTP_200_OK,
	summary="Browse marketplace beats",
)
async def browse_beats(
	db: Annotated[AsyncSession, Depends(get_db)],
	page: int = 1,
	page_size: int = 20,
	sub_genre: str | None = None,
	bpm_min: int | None = None,
	bpm_max: int | None = None,
	min_price_minor: int | None = None,
	max_price_minor: int | None = None,
) -> PaginatedListingsResponse:
	page = max(1, page)
	page_size = max(1, min(page_size, 100))

	listing_filters = [
		BeatListing.status == ListingStatus.active,
		BeatListing.deleted_at.is_(None),
	]
	if min_price_minor is not None:
		listing_filters.append(BeatListing.price_minor >= min_price_minor)
	if max_price_minor is not None:
		listing_filters.append(BeatListing.price_minor <= max_price_minor)

	# Build query joining Track for genre/BPM filters
	from sqlalchemy.orm import aliased
	TrackAlias = aliased(Track)

	query = select(BeatListing, TrackAlias).join(
		TrackAlias, BeatListing.track_id == TrackAlias.id
	).where(*listing_filters)

	if sub_genre is not None:
		query = query.where(TrackAlias.sub_genre == sub_genre)
	if bpm_min is not None:
		query = query.where(TrackAlias.bpm >= bpm_min)
	if bpm_max is not None:
		query = query.where(TrackAlias.bpm <= bpm_max)

	count_query = select(func.count()).select_from(query.subquery())
	total = (await db.execute(count_query)).scalar_one()

	paged = query.order_by(desc(BeatListing.created_at)).offset((page - 1) * page_size).limit(page_size)
	rows = (await db.execute(paged)).all()

	items = [_listing_response(listing, track) for listing, track in rows]
	return PaginatedListingsResponse(items=items, total=total, page=page, page_size=page_size)


@router.post(
	"/beats",
	response_model=ListingResponse,
	status_code=status.HTTP_201_CREATED,
	summary="List a beat for sale (Pro+ only)",
)
async def create_listing(
	body: CreateListingRequest,
	user: Annotated[User, Depends(require_tier(SubscriptionTier.pro))],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> ListingResponse:
	track_result = await db.execute(
		select(Track).where(
			Track.id == body.track_id,
			Track.user_id == user.id,
			Track.status == TrackStatus.ready,
			Track.deleted_at.is_(None),
		)
	)
	track = track_result.scalar_one_or_none()
	if track is None:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail={"error_code": "NOT_FOUND", "message": "Track not found or not ready"},
		)

	existing = await db.execute(
		select(BeatListing).where(
			BeatListing.track_id == body.track_id,
			BeatListing.deleted_at.is_(None),
		)
	)
	if existing.scalar_one_or_none() is not None:
		raise HTTPException(
			status_code=status.HTTP_409_CONFLICT,
			detail={"error_code": "CONFLICT", "message": "Track is already listed"},
		)

	listing = BeatListing(
		id=uuid7str(),
		track_id=body.track_id,
		seller_id=user.id,
		title=body.title,
		description=body.description,
		status=ListingStatus.active,
		license_type=body.license_type,
		price_minor=body.price_minor,
		currency=body.currency,
		tags=body.tags,
		preview_url=track.audio_url_watermarked,
	)
	db.add(listing)
	await db.flush()

	log.info("marketplace.listing_created", listing_id=listing.id, user_id=user.id)
	return _listing_response(listing, track)


@router.get(
	"/beats/{beat_id}",
	response_model=ListingResponse,
	status_code=status.HTTP_200_OK,
	summary="Get beat listing detail",
)
async def get_beat(
	beat_id: str,
	db: Annotated[AsyncSession, Depends(get_db)],
) -> ListingResponse:
	result = await db.execute(
		select(BeatListing).where(
			BeatListing.id == beat_id,
			BeatListing.deleted_at.is_(None),
		)
	)
	listing = result.scalar_one_or_none()
	if listing is None:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail={"error_code": "NOT_FOUND", "message": "Beat listing not found"},
		)

	track_result = await db.execute(select(Track).where(Track.id == listing.track_id))
	track = track_result.scalar_one_or_none()

	listing.view_count += 1
	db.add(listing)
	await db.flush()

	return _listing_response(listing, track)


@router.post(
	"/beats/{beat_id}/purchase",
	response_model=PurchaseResponse,
	status_code=status.HTTP_201_CREATED,
	summary="Purchase a beat",
)
async def purchase_beat(
	beat_id: str,
	user: Annotated[User, Depends(get_current_active_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> PurchaseResponse:
	result = await db.execute(
		select(BeatListing).where(
			BeatListing.id == beat_id,
			BeatListing.status == ListingStatus.active,
			BeatListing.deleted_at.is_(None),
		)
	)
	listing = result.scalar_one_or_none()
	if listing is None:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail={"error_code": "NOT_FOUND", "message": "Beat listing not found or not active"},
		)

	if listing.seller_id == user.id:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail={"error_code": "VALIDATION_ERROR", "message": "Cannot purchase your own beat"},
		)

	existing_purchase = await db.execute(
		select(BeatPurchase).where(
			BeatPurchase.listing_id == beat_id,
			BeatPurchase.buyer_id == user.id,
		)
	)
	if existing_purchase.scalar_one_or_none() is not None:
		raise HTTPException(
			status_code=status.HTTP_409_CONFLICT,
			detail={"error_code": "CONFLICT", "message": "You have already purchased this beat"},
		)

	# For free beats, complete immediately; paid beats require payment flow
	if listing.price_minor > 0:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail={
				"error_code": "PAYMENT_ERROR",
				"message": "Paid beat purchase requires initializing a payment first via /payments/stripe/create-checkout or /payments/paystack/initialize",
			},
		)

	purchase = BeatPurchase(
		id=uuid7str(),
		listing_id=beat_id,
		buyer_id=user.id,
		seller_id=listing.seller_id,
		payment_provider="free",
		provider_payment_id=uuid7str(),
		amount_minor=0,
		currency=listing.currency,
		license_type=listing.license_type,
	)
	db.add(purchase)

	listing.purchase_count += 1
	if listing.license_type == LicenseType.exclusive:
		listing.status = ListingStatus.sold_out
	db.add(listing)

	await db.flush()
	log.info("marketplace.purchase_complete", listing_id=beat_id, buyer_id=user.id)

	return PurchaseResponse(
		id=purchase.id,
		listing_id=purchase.listing_id,
		amount_minor=purchase.amount_minor,
		currency=purchase.currency,
		license_type=purchase.license_type.value,
		download_url=purchase.download_url,
		created_at=purchase.created_at.isoformat(),
	)


@router.get(
	"/my-listings",
	response_model=PaginatedListingsResponse,
	status_code=status.HTTP_200_OK,
	summary="Get current user's beat listings",
)
async def my_listings(
	user: Annotated[User, Depends(get_current_active_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
	page: int = 1,
	page_size: int = 20,
) -> PaginatedListingsResponse:
	page = max(1, page)
	page_size = max(1, min(page_size, 100))

	filters = [BeatListing.seller_id == user.id, BeatListing.deleted_at.is_(None)]

	count_result = await db.execute(select(func.count(BeatListing.id)).where(*filters))
	total = count_result.scalar_one()

	result = await db.execute(
		select(BeatListing)
		.where(*filters)
		.order_by(desc(BeatListing.created_at))
		.offset((page - 1) * page_size)
		.limit(page_size)
	)
	listings = list(result.scalars().all())

	return PaginatedListingsResponse(
		items=[_listing_response(l) for l in listings],
		total=total,
		page=page,
		page_size=page_size,
	)


@router.get(
	"/my-purchases",
	status_code=status.HTTP_200_OK,
	summary="Get current user's purchased beats",
)
async def my_purchases(
	user: Annotated[User, Depends(get_current_active_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
	page: int = 1,
	page_size: int = 20,
) -> dict:
	page = max(1, page)
	page_size = max(1, min(page_size, 100))

	filters = [BeatPurchase.buyer_id == user.id]

	count_result = await db.execute(select(func.count(BeatPurchase.id)).where(*filters))
	total = count_result.scalar_one()

	result = await db.execute(
		select(BeatPurchase)
		.where(*filters)
		.order_by(desc(BeatPurchase.created_at))
		.offset((page - 1) * page_size)
		.limit(page_size)
	)
	purchases = list(result.scalars().all())

	items = [
		{
			"id": p.id,
			"listing_id": p.listing_id,
			"amount_minor": p.amount_minor,
			"currency": p.currency,
			"license_type": p.license_type.value,
			"download_url": p.download_url,
			"created_at": p.created_at.isoformat(),
		}
		for p in purchases
	]

	return {"items": items, "total": total, "page": page, "page_size": page_size}
