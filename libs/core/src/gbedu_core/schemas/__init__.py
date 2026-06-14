from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from gbedu_core.models.job import JobStatus
from gbedu_core.models.marketplace import LicenseType, ListingStatus
from gbedu_core.models.payment import InvoiceStatus, PaymentProvider, PaymentStatus
from gbedu_core.models.track import Language, SubGenre, TrackStatus
from gbedu_core.models.user import SubscriptionStatus, SubscriptionTier
from gbedu_core.models.voice import VoiceArchetype, VoiceModelStatus

_BASE_CFG = ConfigDict(from_attributes=True, extra="forbid")
_BASE_INPUT_CFG = ConfigDict(extra="forbid")


# ── User schemas ───────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
	model_config = _BASE_INPUT_CFG

	email: EmailStr
	password: str = Field(min_length=8, max_length=128)
	full_name: str = Field(min_length=1, max_length=256)
	preferred_language: str = Field(default="en", pattern=r"^(en|pidgin|yoruba|igbo)$")


class UserRead(BaseModel):
	model_config = _BASE_CFG

	id: str
	email: str
	full_name: str
	avatar_url: str | None
	subscription_tier: SubscriptionTier
	subscription_status: SubscriptionStatus
	is_active: bool
	is_verified: bool
	preferred_language: str
	generation_count_today: int
	created_at: datetime
	updated_at: datetime


class UserPublic(BaseModel):
	"""Minimal safe projection for public-facing endpoints (e.g. marketplace seller)."""
	model_config = _BASE_CFG

	id: str
	full_name: str
	avatar_url: str | None
	subscription_tier: SubscriptionTier


class UserUpdate(BaseModel):
	model_config = _BASE_INPUT_CFG

	full_name: str | None = Field(default=None, min_length=1, max_length=256)
	avatar_url: str | None = Field(default=None, max_length=2048)
	preferred_language: str | None = Field(default=None, pattern=r"^(en|pidgin|yoruba|igbo)$")
	current_password: str | None = Field(default=None, min_length=8)
	new_password: str | None = Field(default=None, min_length=8, max_length=128)


# ── Track schemas ──────────────────────────────────────────────────────────────

class TrackCreate(BaseModel):
	model_config = _BASE_INPUT_CFG

	title: str = Field(min_length=1, max_length=256)
	prompt: str = Field(min_length=1, max_length=500)
	sub_genre: SubGenre
	language: Language
	energy_level: int = Field(ge=1, le=10, default=5)
	duration_seconds: int | None = Field(default=None, ge=30, le=240)
	bpm: int | None = Field(default=None, ge=80, le=130)


class TrackRead(BaseModel):
	model_config = _BASE_CFG

	id: str
	user_id: str
	title: str
	prompt: str
	sub_genre: SubGenre
	language: Language
	bpm: int | None
	key: str | None
	energy_level: int
	duration_seconds: int | None
	status: TrackStatus
	audio_url: str | None
	audio_url_watermarked: str | None
	stem_urls: dict[str, Any]
	lyrics: str | None
	cover_art_url: str | None
	is_public: bool
	play_count: int
	share_count: int
	generation_job_id: str | None
	created_at: datetime
	updated_at: datetime


class TrackPublic(BaseModel):
	"""Public track view — no watermarked URL, no prompt (IP protection)."""
	model_config = _BASE_CFG

	id: str
	title: str
	sub_genre: SubGenre
	language: Language
	bpm: int | None
	energy_level: int
	duration_seconds: int | None
	audio_url: str | None
	cover_art_url: str | None
	play_count: int
	share_count: int
	created_at: datetime


# ── Generation schemas ─────────────────────────────────────────────────────────

class GenerationRequest(BaseModel):
	model_config = _BASE_INPUT_CFG

	prompt: str = Field(min_length=1, max_length=500)
	sub_genre: SubGenre
	language: Language
	energy_level: int = Field(ge=1, le=10, default=5)
	duration_seconds: int = Field(ge=30, le=240, default=120)
	bpm: int | None = Field(default=None, ge=80, le=130)
	voice_model_id: str | None = Field(default=None)
	# Optional custom title — auto-generated from prompt if omitted
	title: str | None = Field(default=None, min_length=1, max_length=256)

	@field_validator("prompt")
	@classmethod
	def strip_prompt(cls, v: str) -> str:
		return v.strip()


class GenerationResponse(BaseModel):
	model_config = _BASE_INPUT_CFG

	job_id: str
	track_id: str | None
	status: JobStatus
	message: str
	estimated_seconds: int | None = None


# ── Job schemas ────────────────────────────────────────────────────────────────

class JobRead(BaseModel):
	model_config = _BASE_CFG

	id: str
	user_id: str
	track_id: str | None
	status: JobStatus
	celery_task_id: str | None
	model_used: str | None
	prompt_used: str
	error_message: str | None
	started_at: datetime | None
	completed_at: datetime | None
	progress_percent: int
	created_at: datetime


class JobStatusUpdate(BaseModel):
	model_config = _BASE_INPUT_CFG

	status: JobStatus
	progress_percent: int | None = Field(default=None, ge=0, le=100)
	error_message: str | None = None
	celery_task_id: str | None = None
	model_used: str | None = None


# ── Payment schemas ────────────────────────────────────────────────────────────

class SubscriptionRead(BaseModel):
	model_config = _BASE_CFG

	id: str
	user_id: str
	provider: PaymentProvider
	provider_subscription_id: str
	tier: str
	status: str
	amount_minor: int
	currency: str
	current_period_start: datetime
	current_period_end: datetime
	cancel_at_period_end: bool
	created_at: datetime


class PaymentRead(BaseModel):
	model_config = _BASE_CFG

	id: str
	user_id: str
	provider: PaymentProvider
	provider_payment_id: str
	status: PaymentStatus
	amount_minor: int
	currency: str
	description: str | None
	paid_at: datetime | None
	created_at: datetime


class InvoiceRead(BaseModel):
	model_config = _BASE_CFG

	id: str
	user_id: str
	provider: PaymentProvider
	provider_invoice_id: str
	status: InvoiceStatus
	subtotal_minor: int
	tax_minor: int
	total_minor: int
	currency: str
	invoice_pdf_url: str | None
	due_date: datetime | None
	paid_at: datetime | None
	created_at: datetime


# ── Voice model schemas ────────────────────────────────────────────────────────

class VoiceModelRead(BaseModel):
	model_config = _BASE_CFG

	id: str
	user_id: str | None
	name: str
	description: str | None
	archetype: VoiceArchetype
	status: VoiceModelStatus
	is_preset: bool
	is_public: bool
	training_progress_percent: int
	error_message: str | None
	created_at: datetime


# ── Marketplace schemas ────────────────────────────────────────────────────────

class BeatListingRead(BaseModel):
	model_config = _BASE_CFG

	id: str
	track_id: str
	seller_id: str
	title: str
	description: str | None
	status: ListingStatus
	license_type: LicenseType
	price_minor: int
	currency: str
	view_count: int
	purchase_count: int
	tags: list[str]
	preview_url: str | None
	created_at: datetime


class BeatPurchaseRead(BaseModel):
	model_config = _BASE_CFG

	id: str
	listing_id: str
	buyer_id: str
	seller_id: str
	payment_provider: str
	amount_minor: int
	currency: str
	license_type: LicenseType
	download_url: str | None
	download_expires_at: datetime | None
	download_count: int
	created_at: datetime


# ── Auth schemas ───────────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
	model_config = _BASE_INPUT_CFG

	access_token: str
	refresh_token: str
	token_type: str = "bearer"
	expires_in: int


class RefreshRequest(BaseModel):
	model_config = _BASE_INPUT_CFG

	refresh_token: str


__all__ = [
	"UserCreate",
	"UserRead",
	"UserUpdate",
	"UserPublic",
	"TrackCreate",
	"TrackRead",
	"TrackPublic",
	"GenerationRequest",
	"GenerationResponse",
	"JobRead",
	"JobStatusUpdate",
	"SubscriptionRead",
	"PaymentRead",
	"InvoiceRead",
	"VoiceModelRead",
	"BeatListingRead",
	"BeatPurchaseRead",
	"TokenResponse",
	"RefreshRequest",
]
