from __future__ import annotations

import enum
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gbedu_core._uuid7 import uuid7str
from gbedu_core.db import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
	from gbedu_core.models.job import GenerationJob
	from gbedu_core.models.marketplace import BeatListing
	from gbedu_core.models.user import User


class SubGenre(enum.StrEnum):
	afropop = "afropop"
	afrofusion = "afrofusion"
	alte = "alte"
	amapiano_cross = "amapiano_cross"
	afrobeats_uk = "afrobeats_uk"
	# Corpus-derived additions
	afrobeats = "afrobeats"
	highlife = "highlife"
	bongo_flava = "bongo_flava"
	soukous = "soukous"
	mbalax = "mbalax"
	# Caribbean
	soca = "soca"
	calypso = "calypso"
	# Kenyan
	gengetone = "gengetone"
	benga = "benga"
	# East African coastal
	taarab = "taarab"
	# Cross-Atlantic fusion
	afro_soca = "afro_soca"


class Language(enum.StrEnum):
	english = "english"
	pidgin = "pidgin"
	yoruba = "yoruba"
	igbo = "igbo"
	mix = "mix"
	# Corpus-derived additions
	swahili = "swahili"
	lingala = "lingala"
	zulu = "zulu"
	twi = "twi"


class TrackStatus(enum.StrEnum):
	generating = "generating"
	processing = "processing"
	ready = "ready"
	failed = "failed"


class Track(Base, TimestampMixin, SoftDeleteMixin):
	__tablename__ = "tracks"

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)
	user_id: Mapped[str] = mapped_column(
		String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
	)
	generation_job_id: Mapped[str] = mapped_column(
		String(36), ForeignKey("generation_jobs.id", ondelete="SET NULL"), nullable=True, index=True
	)

	title: Mapped[str] = mapped_column(String(256), nullable=False)
	prompt: Mapped[str] = mapped_column(Text, nullable=False)

	sub_genre: Mapped[SubGenre] = mapped_column(Enum(SubGenre, name="sub_genre"), nullable=False)
	language: Mapped[Language] = mapped_column(Enum(Language, name="language"), nullable=False)

	bpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
	key: Mapped[str | None] = mapped_column(String(8), nullable=True)
	energy_level: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
	duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

	status: Mapped[TrackStatus] = mapped_column(
		Enum(TrackStatus, name="track_status"),
		nullable=False,
		default=TrackStatus.generating,
		server_default=TrackStatus.generating.value,
		index=True,
	)

	# R2 object URLs — null until generation completes
	audio_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
	audio_url_watermarked: Mapped[str | None] = mapped_column(String(2048), nullable=True)

	# {"drums": url, "bass": url, "melody": url, "vocals": url}
	stem_urls: Mapped[dict[str, Any]] = mapped_column(
		JSONB, nullable=False, default=dict, server_default="{}"
	)

	lyrics: Mapped[str | None] = mapped_column(Text, nullable=True)
	cover_art_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

	is_public: Mapped[bool] = mapped_column(
		Boolean, nullable=False, default=False, server_default="false"
	)
	play_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
	share_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

	# Free-form JSONB bag for distribution metadata, remaster URLs, platform IDs, etc.
	metadata_: Mapped[dict[str, Any]] = mapped_column(
		JSONB, nullable=False, default=dict, server_default="{}"
	)

	# ── Relationships ──────────────────────────────────────────────────────────
	user: Mapped[User] = relationship("User", back_populates="tracks", lazy="noload")
	generation_job: Mapped[GenerationJob | None] = relationship(
		"GenerationJob",
		foreign_keys="[Track.generation_job_id]",
		lazy="noload",
	)
	jobs: Mapped[list[GenerationJob]] = relationship(
		"GenerationJob",
		foreign_keys="[GenerationJob.track_id]",
		back_populates="track",
		lazy="noload",
	)
	listing: Mapped[BeatListing | None] = relationship(
		"BeatListing", back_populates="track", lazy="noload"
	)

	__table_args__ = (
		Index("ix_tracks_user_status", "user_id", "status"),
		Index("ix_tracks_public_created", "is_public", "created_at"),
	)

	def __repr__(self) -> str:
		return f"<Track id={self.id!r} title={self.title!r} status={self.status.value!r}>"
