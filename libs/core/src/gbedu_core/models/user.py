from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gbedu_core._uuid7 import uuid7str
from gbedu_core.db import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
	from gbedu_core.models.auth import RefreshToken
	from gbedu_core.models.job import GenerationJob
	from gbedu_core.models.marketplace import BeatListing, BeatPurchase
	from gbedu_core.models.payment import Payment, Subscription
	from gbedu_core.models.track import Track
	from gbedu_core.models.voice import VoiceModel


class SubscriptionTier(enum.StrEnum):
	free = "free"
	creator = "creator"
	pro = "pro"
	label = "label"


class SubscriptionStatus(enum.StrEnum):
	active = "active"
	past_due = "past_due"
	cancelled = "cancelled"
	trialing = "trialing"


# Daily generation limits per tier — source of truth for quota enforcement
TIER_DAILY_LIMITS: dict[SubscriptionTier, int] = {
	SubscriptionTier.free: 3,
	SubscriptionTier.creator: 20,
	SubscriptionTier.pro: 100,
	SubscriptionTier.label: 500,
}


class User(Base, TimestampMixin, SoftDeleteMixin):
	__tablename__ = "users"

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)
	email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
	hashed_password: Mapped[str | None] = mapped_column(String(256), nullable=True)
	full_name: Mapped[str] = mapped_column(String(256), nullable=False)
	avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

	subscription_tier: Mapped[SubscriptionTier] = mapped_column(
		Enum(SubscriptionTier, name="subscription_tier"),
		nullable=False,
		default=SubscriptionTier.free,
		server_default=SubscriptionTier.free.value,
	)
	subscription_status: Mapped[SubscriptionStatus] = mapped_column(
		Enum(SubscriptionStatus, name="subscription_status"),
		nullable=False,
		default=SubscriptionStatus.active,
		server_default=SubscriptionStatus.active.value,
	)

	stripe_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
	paystack_customer_code: Mapped[str | None] = mapped_column(
		String(64), nullable=True, index=True
	)

	# OAuth — null for email/password users
	oauth_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
	oauth_provider_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

	is_active: Mapped[bool] = mapped_column(
		Boolean, nullable=False, default=True, server_default="true"
	)
	is_verified: Mapped[bool] = mapped_column(
		Boolean, nullable=False, default=False, server_default="false"
	)

	preferred_language: Mapped[str] = mapped_column(
		String(8), nullable=False, default="en", server_default="en"
	)

	generation_count_today: Mapped[int] = mapped_column(
		Integer, nullable=False, default=0, server_default="0"
	)
	generation_count_reset_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(UTC),
	)

	# ── Relationships ──────────────────────────────────────────────────────────
	tracks: Mapped[list[Track]] = relationship("Track", back_populates="user", lazy="noload")
	jobs: Mapped[list[GenerationJob]] = relationship(
		"GenerationJob", back_populates="user", lazy="noload"
	)
	subscriptions: Mapped[list[Subscription]] = relationship(
		"Subscription", back_populates="user", lazy="noload"
	)
	payments: Mapped[list[Payment]] = relationship("Payment", back_populates="user", lazy="noload")
	voice_models: Mapped[list[VoiceModel]] = relationship(
		"VoiceModel", back_populates="user", lazy="noload"
	)
	beat_listings: Mapped[list[BeatListing]] = relationship(
		"BeatListing", back_populates="seller", lazy="noload"
	)
	purchases: Mapped[list[BeatPurchase]] = relationship(
		"BeatPurchase", foreign_keys="BeatPurchase.buyer_id", back_populates="buyer", lazy="noload"
	)
	refresh_tokens: Mapped[list[RefreshToken]] = relationship(
		"RefreshToken", back_populates="user", lazy="noload"
	)

	__table_args__ = (
		Index(
			"ix_users_oauth",
			"oauth_provider",
			"oauth_provider_id",
			unique=True,
			postgresql_where=mapped_column("oauth_provider_id").is_not(None),
		),
	)

	@property
	def daily_limit(self) -> int:
		return TIER_DAILY_LIMITS[self.subscription_tier]

	@property
	def has_generation_quota(self) -> bool:
		return self.generation_count_today < self.daily_limit

	def __repr__(self) -> str:
		return f"<User id={self.id!r} email={self.email!r} tier={self.subscription_tier.value!r}>"
