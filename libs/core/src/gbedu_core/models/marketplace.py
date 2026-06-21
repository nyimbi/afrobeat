from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gbedu_core._uuid7 import uuid7str
from gbedu_core.db import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
	from gbedu_core.models.track import Track
	from gbedu_core.models.user import User


class ListingStatus(enum.StrEnum):
	draft = "draft"
	active = "active"
	paused = "paused"
	sold_out = "sold_out"
	removed = "removed"


class LicenseType(enum.StrEnum):
	# Non-exclusive — buyer can use commercially, seller retains ownership
	non_exclusive = "non_exclusive"
	# Exclusive — all rights transferred to buyer, listing deactivated after sale
	exclusive = "exclusive"
	# Free download (promotional / free tier)
	free = "free"


class BeatListing(Base, TimestampMixin, SoftDeleteMixin):
	__tablename__ = "beat_listings"

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)
	track_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("tracks.id", ondelete="CASCADE"),
		nullable=False,
		unique=True,
		index=True,
	)
	seller_id: Mapped[str] = mapped_column(
		String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
	)

	title: Mapped[str] = mapped_column(String(256), nullable=False)
	description: Mapped[str | None] = mapped_column(Text, nullable=True)

	status: Mapped[ListingStatus] = mapped_column(
		Enum(ListingStatus, name="listing_status"),
		nullable=False,
		default=ListingStatus.draft,
		server_default=ListingStatus.draft.value,
		index=True,
	)
	license_type: Mapped[LicenseType] = mapped_column(
		Enum(LicenseType, name="license_type"),
		nullable=False,
		default=LicenseType.non_exclusive,
	)

	# Price in minor currency units (cents / kobo). 0 = free.
	price_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
	currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

	# Counts maintained by triggers / application logic
	view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
	purchase_count: Mapped[int] = mapped_column(
		Integer, nullable=False, default=0, server_default="0"
	)

	# Genre/mood tags for discovery
	tags: Mapped[list[str]] = mapped_column(
		JSONB, nullable=False, default=list, server_default="[]"
	)

	# Watermarked preview URL served before purchase
	preview_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

	track: Mapped[Track] = relationship("Track", back_populates="listing", lazy="noload")
	seller: Mapped[User] = relationship("User", back_populates="beat_listings", lazy="noload")
	purchases: Mapped[list[BeatPurchase]] = relationship(
		"BeatPurchase", back_populates="listing", lazy="noload"
	)

	__table_args__ = (
		Index("ix_listings_status_created", "status", "created_at"),
		Index("ix_listings_seller_status", "seller_id", "status"),
	)

	@property
	def price_decimal(self) -> float:
		return self.price_minor / 100

	def __repr__(self) -> str:
		return (
			f"<BeatListing id={self.id!r} title={self.title!r} "
			f"price={self.price_minor} {self.currency} status={self.status.value!r}>"
		)


class BeatPurchase(Base, TimestampMixin):
	__tablename__ = "beat_purchases"

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)
	listing_id: Mapped[str] = mapped_column(
		String(36), ForeignKey("beat_listings.id", ondelete="RESTRICT"), nullable=False, index=True
	)
	buyer_id: Mapped[str] = mapped_column(
		String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
	)
	# Snapshot of seller at purchase time — denormalised to survive seller account deletion
	seller_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

	payment_provider: Mapped[str] = mapped_column(String(32), nullable=False)
	provider_payment_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

	amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
	currency: Mapped[str] = mapped_column(String(3), nullable=False)
	license_type: Mapped[LicenseType] = mapped_column(
		Enum(LicenseType, name="license_type"), nullable=False
	)

	# Signed URL or R2 path to the full-quality download, generated post-payment
	download_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
	download_expires_at: Mapped[datetime | None] = mapped_column(
		DateTime(timezone=True), nullable=True
	)
	download_count: Mapped[int] = mapped_column(
		Integer, nullable=False, default=0, server_default="0"
	)

	metadata_: Mapped[dict[str, Any]] = mapped_column(
		"metadata", JSONB, nullable=False, default=dict, server_default="{}"
	)

	listing: Mapped[BeatListing] = relationship(
		"BeatListing", back_populates="purchases", lazy="noload"
	)
	buyer: Mapped[User] = relationship(
		"User", foreign_keys=[buyer_id], back_populates="purchases", lazy="noload"
	)

	__table_args__ = (Index("ix_purchases_buyer_listing", "buyer_id", "listing_id", unique=True),)

	def __repr__(self) -> str:
		return (
			f"<BeatPurchase id={self.id!r} listing_id={self.listing_id!r} "
			f"buyer_id={self.buyer_id!r} amount={self.amount_minor} {self.currency}>"
		)
