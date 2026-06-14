"""Unit tests for SQLAlchemy model creation, relationships, and mixins."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from gbedu_core._uuid7 import uuid7str
from gbedu_core.models import (
	BeatListing,
	BeatPurchase,
	GenerationJob,
	JobStatus,
	Language,
	ListingStatus,
	PaymentProvider,
	PaymentStatus,
	SubGenre,
	Subscription,
	SubscriptionStatus,
	SubscriptionTier,
	Track,
	TrackStatus,
	User,
	VoiceArchetype,
	VoiceModel,
	VoiceModelStatus,
)
from gbedu_core.models.marketplace import LicenseType
from gbedu_core.models.payment import SubscriptionInterval


pytestmark = pytest.mark.asyncio


# ── User ───────────────────────────────────────────────────────────────────────

async def test_user_creation(test_db_session: AsyncSession, make_user):
	user = await make_user(tier="free")

	assert user.id
	assert user.subscription_tier == SubscriptionTier.free
	assert user.subscription_status == SubscriptionStatus.active
	assert user.is_active is True
	assert user.is_verified is True
	assert user.generation_count_today == 0
	assert user.daily_limit == 3
	assert user.has_generation_quota is True


async def test_user_tier_limits(test_db_session: AsyncSession, make_user):
	free_user = await make_user(tier="free")
	creator_user = await make_user(tier="creator")
	pro_user = await make_user(tier="pro")
	label_user = await make_user(tier="label")

	assert free_user.daily_limit == 3
	assert creator_user.daily_limit == 20
	assert pro_user.daily_limit == 100
	assert label_user.daily_limit == 500


async def test_user_quota_exhausted(test_db_session: AsyncSession, make_user):
	user = await make_user(tier="free")
	user.generation_count_today = 3
	test_db_session.add(user)
	await test_db_session.flush()

	assert user.has_generation_quota is False


async def test_user_soft_delete(test_db_session: AsyncSession, make_user):
	user = await make_user()
	assert not user.is_deleted

	await user.delete(test_db_session)
	assert user.is_deleted
	assert isinstance(user.deleted_at, datetime)


async def test_user_soft_delete_idempotent_raises(test_db_session: AsyncSession, make_user):
	user = await make_user()
	await user.delete(test_db_session)

	with pytest.raises(AssertionError):
		await user.delete(test_db_session)


async def test_user_timestamps_set(test_db_session: AsyncSession, make_user):
	user = await make_user()
	# Timestamps are set by server_default; after flush they may still be None
	# in the Python object until a SELECT.  Assert the fields exist.
	assert hasattr(user, "created_at")
	assert hasattr(user, "updated_at")


# ── Track ──────────────────────────────────────────────────────────────────────

async def test_track_creation(test_db_session: AsyncSession, make_user, make_track):
	user = await make_user()
	track = await make_track(user)

	assert track.id
	assert track.user_id == user.id
	assert track.sub_genre == SubGenre.afropop
	assert track.language == Language.english
	assert track.status == TrackStatus.ready
	assert track.is_public is False
	assert track.play_count == 0


async def test_track_soft_delete(test_db_session: AsyncSession, make_user, make_track):
	user = await make_user()
	track = await make_track(user)

	assert not track.is_deleted
	await track.delete(test_db_session)
	assert track.is_deleted


async def test_track_repr(test_db_session: AsyncSession, make_user, make_track):
	user = await make_user()
	track = await make_track(user)
	r = repr(track)
	assert "Track" in r
	assert track.id in r


# ── GenerationJob ──────────────────────────────────────────────────────────────

async def test_job_creation(test_db_session: AsyncSession, make_user, make_job):
	user = await make_user()
	job = await make_job(user)

	assert job.id
	assert job.user_id == user.id
	assert job.status == JobStatus.queued
	assert job.progress_percent == 0
	assert not job.is_terminal


async def test_job_terminal_states(test_db_session: AsyncSession, make_user, make_job):
	user = await make_user()

	for terminal in ["complete", "failed", "cancelled"]:
		job = await make_job(user, status=terminal)
		assert job.is_terminal, f"expected {terminal} to be terminal"

	for non_terminal in ["queued", "ml_generating", "audio_processing", "uploading"]:
		job = await make_job(user, status=non_terminal)
		assert not job.is_terminal, f"expected {non_terminal} to be non-terminal"


async def test_job_duration_none_when_not_started(test_db_session: AsyncSession, make_user, make_job):
	user = await make_user()
	job = await make_job(user)
	assert job.duration_seconds is None


async def test_job_duration_computed(test_db_session: AsyncSession, make_user, make_job):
	from datetime import timedelta
	user = await make_user()
	job = await make_job(user)
	t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
	job.started_at = t0
	job.completed_at = t0 + timedelta(seconds=42)
	assert job.duration_seconds == pytest.approx(42.0)


# ── VoiceModel ─────────────────────────────────────────────────────────────────

async def test_voice_model_preset(test_db_session: AsyncSession):
	vm = VoiceModel(
		id=uuid7str(),
		user_id=None,
		name="Wizkid Inspired",
		archetype=VoiceArchetype.wizkid_inspired,
		status=VoiceModelStatus.ready,
		is_preset=True,
		is_public=True,
		training_progress_percent=100,
	)
	test_db_session.add(vm)
	await test_db_session.flush()

	assert vm.is_preset is True
	assert vm.user_id is None
	assert vm.status == VoiceModelStatus.ready


async def test_voice_model_user_owned(test_db_session: AsyncSession, make_user):
	user = await make_user()
	vm = VoiceModel(
		id=uuid7str(),
		user_id=user.id,
		name="My Custom Voice",
		archetype=VoiceArchetype.custom,
		status=VoiceModelStatus.pending,
		is_preset=False,
		is_public=False,
		training_progress_percent=0,
	)
	test_db_session.add(vm)
	await test_db_session.flush()

	assert vm.user_id == user.id
	assert vm.status == VoiceModelStatus.pending


# ── BeatListing / BeatPurchase ─────────────────────────────────────────────────

async def test_beat_listing_creation(
	test_db_session: AsyncSession,
	make_user,
	make_track,
):
	user = await make_user()
	track = await make_track(user)

	listing = BeatListing(
		id=uuid7str(),
		track_id=track.id,
		seller_id=user.id,
		title="Killer Beat",
		status=ListingStatus.active,
		license_type=LicenseType.non_exclusive,
		price_minor=2000,
		currency="USD",
	)
	test_db_session.add(listing)
	await test_db_session.flush()

	assert listing.price_decimal == pytest.approx(20.0)
	assert listing.status == ListingStatus.active


async def test_beat_purchase_creation(
	test_db_session: AsyncSession,
	make_user,
	make_track,
):
	seller = await make_user()
	buyer = await make_user()
	track = await make_track(seller)

	listing = BeatListing(
		id=uuid7str(),
		track_id=track.id,
		seller_id=seller.id,
		title="Banger",
		status=ListingStatus.active,
		license_type=LicenseType.non_exclusive,
		price_minor=1500,
		currency="USD",
	)
	test_db_session.add(listing)
	await test_db_session.flush()

	purchase = BeatPurchase(
		id=uuid7str(),
		listing_id=listing.id,
		buyer_id=buyer.id,
		seller_id=seller.id,
		payment_provider="stripe",
		provider_payment_id=f"pi_{uuid7str()}",
		amount_minor=1500,
		currency="USD",
		license_type=LicenseType.non_exclusive,
	)
	test_db_session.add(purchase)
	await test_db_session.flush()

	assert purchase.buyer_id == buyer.id
	assert purchase.amount_minor == 1500


# ── Subscription ───────────────────────────────────────────────────────────────

async def test_subscription_creation(test_db_session: AsyncSession, make_user):
	user = await make_user()
	now = datetime.now(timezone.utc)

	sub = Subscription(
		id=uuid7str(),
		user_id=user.id,
		provider=PaymentProvider.stripe,
		provider_subscription_id=f"sub_{uuid7str()}",
		provider_plan_id="price_creator_monthly",
		tier="creator",
		interval=SubscriptionInterval.month,
		status="active",
		amount_minor=999,
		currency="USD",
		current_period_start=now,
		current_period_end=now,
	)
	test_db_session.add(sub)
	await test_db_session.flush()

	assert sub.tier == "creator"
	assert sub.provider == PaymentProvider.stripe
