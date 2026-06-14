"""Initial schema — all tables for Gbẹdu.

Revision ID: 0001
Revises:
Create Date: 2026-06-14 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
	# ── Enums ──────────────────────────────────────────────────────────────────
	subscription_tier = postgresql.ENUM(
		"free", "creator", "pro", "label",
		name="subscription_tier",
	)
	subscription_status = postgresql.ENUM(
		"active", "past_due", "cancelled", "trialing",
		name="subscription_status",
	)
	job_status = postgresql.ENUM(
		"queued", "ml_generating", "audio_processing", "uploading",
		"complete", "failed", "cancelled",
		name="job_status",
	)
	track_status = postgresql.ENUM(
		"generating", "processing", "ready", "failed",
		name="track_status",
	)
	sub_genre = postgresql.ENUM(
		"afropop", "afrofusion", "alte", "amapiano_cross", "afrobeats_uk",
		name="sub_genre",
	)
	language = postgresql.ENUM(
		"english", "pidgin", "yoruba", "igbo", "mix",
		name="language",
	)
	payment_provider = postgresql.ENUM(
		"stripe", "paystack",
		name="payment_provider",
	)
	payment_status = postgresql.ENUM(
		"pending", "succeeded", "failed", "refunded",
		"partially_refunded", "disputed",
		name="payment_status",
	)
	invoice_status = postgresql.ENUM(
		"draft", "open", "paid", "void", "uncollectible",
		name="invoice_status",
	)
	subscription_interval = postgresql.ENUM(
		"month", "year",
		name="subscription_interval",
	)
	voice_archetype = postgresql.ENUM(
		"omah_lay_inspired", "burna_boy_inspired", "wizkid_inspired",
		"tems_inspired", "davido_inspired", "ckay_inspired",
		"rema_inspired", "ayra_starr_inspired",
		"neutral_male", "neutral_female", "custom",
		name="voice_archetype",
	)
	voice_model_status = postgresql.ENUM(
		"pending", "training", "ready", "failed", "deprecated",
		name="voice_model_status",
	)
	listing_status = postgresql.ENUM(
		"draft", "active", "paused", "sold_out", "removed",
		name="listing_status",
	)
	license_type = postgresql.ENUM(
		"non_exclusive", "exclusive", "free",
		name="license_type",
	)

	for enum in [
		subscription_tier, subscription_status, job_status, track_status,
		sub_genre, language, payment_provider, payment_status,
		invoice_status, subscription_interval, voice_archetype,
		voice_model_status, listing_status, license_type,
	]:
		enum.create(op.get_bind(), checkfirst=True)

	# ── users ──────────────────────────────────────────────────────────────────
	op.create_table(
		"users",
		sa.Column("id", sa.String(36), primary_key=True, nullable=False),
		sa.Column("email", sa.String(320), nullable=False),
		sa.Column("hashed_password", sa.String(256), nullable=True),
		sa.Column("full_name", sa.String(256), nullable=False),
		sa.Column("avatar_url", sa.String(2048), nullable=True),
		sa.Column(
			"subscription_tier",
			postgresql.ENUM("free", "creator", "pro", "label", name="subscription_tier", create_type=False),
			nullable=False,
			server_default="free",
		),
		sa.Column(
			"subscription_status",
			postgresql.ENUM("active", "past_due", "cancelled", "trialing", name="subscription_status", create_type=False),
			nullable=False,
			server_default="active",
		),
		sa.Column("stripe_customer_id", sa.String(64), nullable=True),
		sa.Column("paystack_customer_code", sa.String(64), nullable=True),
		sa.Column("oauth_provider", sa.String(32), nullable=True),
		sa.Column("oauth_provider_id", sa.String(256), nullable=True),
		sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
		sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
		sa.Column("preferred_language", sa.String(8), nullable=False, server_default="en"),
		sa.Column("generation_count_today", sa.Integer(), nullable=False, server_default="0"),
		sa.Column(
			"generation_count_reset_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column(
			"created_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.Column(
			"updated_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
		sa.UniqueConstraint("email", name=op.f("uq_users_email")),
	)
	op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
	op.create_index("ix_users_subscription_tier", "users", ["subscription_tier"])
	op.create_index("ix_users_created_at", "users", ["created_at"])
	op.create_index(
		"ix_users_oauth",
		"users",
		["oauth_provider", "oauth_provider_id"],
		unique=True,
		postgresql_where=sa.text("oauth_provider_id IS NOT NULL"),
	)
	op.create_index("ix_users_stripe_customer_id", "users", ["stripe_customer_id"])
	op.create_index("ix_users_paystack_customer_code", "users", ["paystack_customer_code"])

	# ── refresh_tokens ─────────────────────────────────────────────────────────
	op.create_table(
		"refresh_tokens",
		sa.Column("id", sa.String(36), primary_key=True, nullable=False),
		sa.Column("user_id", sa.String(36), nullable=False),
		sa.Column("token_hash", sa.String(64), nullable=False),
		sa.Column("jti", sa.String(64), nullable=False),
		sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
		sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column("user_agent", sa.String(512), nullable=True),
		sa.Column("ip_address", sa.String(45), nullable=True),
		sa.Column(
			"created_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.Column(
			"updated_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.ForeignKeyConstraint(
			["user_id"], ["users.id"],
			name=op.f("fk_refresh_tokens_user_id_users"),
			ondelete="CASCADE",
		),
		sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
		sa.UniqueConstraint("jti", name=op.f("uq_refresh_tokens_jti")),
	)
	op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"])
	op.create_index(op.f("ix_refresh_tokens_token_hash"), "refresh_tokens", ["token_hash"], unique=True)
	op.create_index(op.f("ix_refresh_tokens_expires_at"), "refresh_tokens", ["expires_at"])

	# ── email_verifications ────────────────────────────────────────────────────
	op.create_table(
		"email_verifications",
		sa.Column("id", sa.String(36), primary_key=True, nullable=False),
		sa.Column("user_id", sa.String(36), nullable=False),
		sa.Column("token_hash", sa.String(64), nullable=False),
		sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
		sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column(
			"created_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.Column(
			"updated_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.ForeignKeyConstraint(
			["user_id"], ["users.id"],
			name=op.f("fk_email_verifications_user_id_users"),
			ondelete="CASCADE",
		),
		sa.PrimaryKeyConstraint("id", name=op.f("pk_email_verifications")),
	)
	op.create_index(op.f("ix_email_verifications_user_id"), "email_verifications", ["user_id"])
	op.create_index(
		op.f("ix_email_verifications_token_hash"),
		"email_verifications",
		["token_hash"],
		unique=True,
	)

	# ── password_resets ────────────────────────────────────────────────────────
	op.create_table(
		"password_resets",
		sa.Column("id", sa.String(36), primary_key=True, nullable=False),
		sa.Column("user_id", sa.String(36), nullable=False),
		sa.Column("token_hash", sa.String(64), nullable=False),
		sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
		sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column(
			"created_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.Column(
			"updated_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.ForeignKeyConstraint(
			["user_id"], ["users.id"],
			name=op.f("fk_password_resets_user_id_users"),
			ondelete="CASCADE",
		),
		sa.PrimaryKeyConstraint("id", name=op.f("pk_password_resets")),
	)
	op.create_index(op.f("ix_password_resets_user_id"), "password_resets", ["user_id"])
	op.create_index(
		op.f("ix_password_resets_token_hash"),
		"password_resets",
		["token_hash"],
		unique=True,
	)

	# ── generation_jobs ────────────────────────────────────────────────────────
	op.create_table(
		"generation_jobs",
		sa.Column("id", sa.String(36), primary_key=True, nullable=False),
		sa.Column("user_id", sa.String(36), nullable=False),
		sa.Column("track_id", sa.String(36), nullable=True),
		sa.Column(
			"status",
			postgresql.ENUM(
				"queued", "ml_generating", "audio_processing", "uploading",
				"complete", "failed", "cancelled",
				name="job_status",
				create_type=False,
			),
			nullable=False,
			server_default="queued",
		),
		sa.Column("celery_task_id", sa.String(256), nullable=True),
		sa.Column("model_used", sa.String(64), nullable=True),
		sa.Column("prompt_used", sa.Text(), nullable=False),
		sa.Column("error_message", sa.Text(), nullable=True),
		sa.Column("error_traceback", sa.Text(), nullable=True),
		sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"),
		sa.Column(
			"metadata",
			postgresql.JSONB(astext_type=sa.Text()),
			nullable=False,
			server_default="{}",
		),
		sa.Column(
			"created_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.Column(
			"updated_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.ForeignKeyConstraint(
			["user_id"], ["users.id"],
			name=op.f("fk_generation_jobs_user_id_users"),
			ondelete="CASCADE",
		),
		sa.PrimaryKeyConstraint("id", name=op.f("pk_generation_jobs")),
	)
	op.create_index(op.f("ix_generation_jobs_user_id"), "generation_jobs", ["user_id"])
	op.create_index(op.f("ix_generation_jobs_status"), "generation_jobs", ["status"])
	op.create_index("ix_generation_jobs_celery_task_id", "generation_jobs", ["celery_task_id"])
	op.create_index("ix_generation_jobs_created_at", "generation_jobs", ["created_at"])
	op.create_index("ix_jobs_user_status", "generation_jobs", ["user_id", "status"])
	op.create_index("ix_jobs_celery_task", "generation_jobs", ["celery_task_id"])

	# ── tracks ─────────────────────────────────────────────────────────────────
	op.create_table(
		"tracks",
		sa.Column("id", sa.String(36), primary_key=True, nullable=False),
		sa.Column("user_id", sa.String(36), nullable=False),
		sa.Column("generation_job_id", sa.String(36), nullable=True),
		sa.Column("title", sa.String(256), nullable=False),
		sa.Column("prompt", sa.Text(), nullable=False),
		sa.Column(
			"sub_genre",
			postgresql.ENUM("afropop", "afrofusion", "alte", "amapiano_cross", "afrobeats_uk", name="sub_genre", create_type=False),
			nullable=False,
		),
		sa.Column(
			"language",
			postgresql.ENUM("english", "pidgin", "yoruba", "igbo", "mix", name="language", create_type=False),
			nullable=False,
		),
		sa.Column("bpm", sa.Integer(), nullable=True),
		sa.Column("key", sa.String(8), nullable=True),
		sa.Column("energy_level", sa.Integer(), nullable=False, server_default="5"),
		sa.Column("duration_seconds", sa.Integer(), nullable=True),
		sa.Column(
			"status",
			postgresql.ENUM("generating", "processing", "ready", "failed", name="track_status", create_type=False),
			nullable=False,
			server_default="generating",
		),
		sa.Column("audio_url", sa.String(2048), nullable=True),
		sa.Column("audio_url_watermarked", sa.String(2048), nullable=True),
		sa.Column(
			"stem_urls",
			postgresql.JSONB(astext_type=sa.Text()),
			nullable=False,
			server_default="{}",
		),
		sa.Column("lyrics", sa.Text(), nullable=True),
		sa.Column("cover_art_url", sa.String(2048), nullable=True),
		sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("false")),
		sa.Column("play_count", sa.Integer(), nullable=False, server_default="0"),
		sa.Column("share_count", sa.Integer(), nullable=False, server_default="0"),
		sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column(
			"created_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.Column(
			"updated_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.ForeignKeyConstraint(
			["user_id"], ["users.id"],
			name=op.f("fk_tracks_user_id_users"),
			ondelete="CASCADE",
		),
		sa.ForeignKeyConstraint(
			["generation_job_id"], ["generation_jobs.id"],
			name=op.f("fk_tracks_generation_job_id_generation_jobs"),
			ondelete="SET NULL",
		),
		sa.PrimaryKeyConstraint("id", name=op.f("pk_tracks")),
	)
	op.create_index(op.f("ix_tracks_user_id"), "tracks", ["user_id"])
	op.create_index(op.f("ix_tracks_status"), "tracks", ["status"])
	op.create_index("ix_tracks_user_created_at", "tracks", ["user_id", "created_at"])
	op.create_index("ix_tracks_public_created", "tracks", ["is_public", "created_at"])
	op.create_index("ix_tracks_user_status", "tracks", ["user_id", "status"])

	# Back-fill the FK that generation_jobs has on tracks — add it now that
	# tracks exists.
	op.create_foreign_key(
		op.f("fk_generation_jobs_track_id_tracks"),
		"generation_jobs",
		"tracks",
		["track_id"],
		["id"],
		ondelete="SET NULL",
	)

	# ── track_stems ────────────────────────────────────────────────────────────
	op.create_table(
		"track_stems",
		sa.Column("id", sa.String(36), primary_key=True, nullable=False),
		sa.Column("track_id", sa.String(36), nullable=False),
		sa.Column("stem_type", sa.String(32), nullable=False),  # drums/bass/melody/vocals
		sa.Column("audio_url", sa.String(2048), nullable=False),
		sa.Column("duration_seconds", sa.Integer(), nullable=True),
		sa.Column("file_size_bytes", sa.Integer(), nullable=True),
		sa.Column(
			"created_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.Column(
			"updated_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.ForeignKeyConstraint(
			["track_id"], ["tracks.id"],
			name=op.f("fk_track_stems_track_id_tracks"),
			ondelete="CASCADE",
		),
		sa.PrimaryKeyConstraint("id", name=op.f("pk_track_stems")),
		sa.UniqueConstraint("track_id", "stem_type", name=op.f("uq_track_stems_track_id")),
	)
	op.create_index(op.f("ix_track_stems_track_id"), "track_stems", ["track_id"])

	# ── voice_models ───────────────────────────────────────────────────────────
	op.create_table(
		"voice_models",
		sa.Column("id", sa.String(36), primary_key=True, nullable=False),
		sa.Column("user_id", sa.String(36), nullable=True),
		sa.Column("name", sa.String(128), nullable=False),
		sa.Column("description", sa.Text(), nullable=True),
		sa.Column(
			"archetype",
			postgresql.ENUM(
				"omah_lay_inspired", "burna_boy_inspired", "wizkid_inspired",
				"tems_inspired", "davido_inspired", "ckay_inspired",
				"rema_inspired", "ayra_starr_inspired",
				"neutral_male", "neutral_female", "custom",
				name="voice_archetype",
				create_type=False,
			),
			nullable=False,
		),
		sa.Column(
			"status",
			postgresql.ENUM("pending", "training", "ready", "failed", "deprecated", name="voice_model_status", create_type=False),
			nullable=False,
			server_default="pending",
		),
		sa.Column("is_preset", sa.Boolean(), nullable=False, server_default=sa.text("false")),
		sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("false")),
		sa.Column("model_file_url", sa.String(2048), nullable=True),
		sa.Column("index_file_url", sa.String(2048), nullable=True),
		sa.Column(
			"training_audio_urls",
			postgresql.JSONB(astext_type=sa.Text()),
			nullable=False,
			server_default="[]",
		),
		sa.Column(
			"training_config",
			postgresql.JSONB(astext_type=sa.Text()),
			nullable=False,
			server_default="{}",
		),
		sa.Column(
			"training_metrics",
			postgresql.JSONB(astext_type=sa.Text()),
			nullable=False,
			server_default="{}",
		),
		sa.Column("training_task_id", sa.String(256), nullable=True),
		sa.Column("training_progress_percent", sa.Integer(), nullable=False, server_default="0"),
		sa.Column("error_message", sa.Text(), nullable=True),
		sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column(
			"created_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.Column(
			"updated_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.ForeignKeyConstraint(
			["user_id"], ["users.id"],
			name=op.f("fk_voice_models_user_id_users"),
			ondelete="CASCADE",
		),
		sa.PrimaryKeyConstraint("id", name=op.f("pk_voice_models")),
	)
	op.create_index(op.f("ix_voice_models_user_id"), "voice_models", ["user_id"])
	op.create_index(op.f("ix_voice_models_status"), "voice_models", ["status"])
	op.create_index("ix_voice_models_user_status", "voice_models", ["user_id", "status"])
	op.create_index("ix_voice_models_preset", "voice_models", ["is_preset", "status"])

	# ── user_voice_models (junction — user bookmarks a preset) ─────────────────
	op.create_table(
		"user_voice_models",
		sa.Column("user_id", sa.String(36), nullable=False),
		sa.Column("voice_model_id", sa.String(36), nullable=False),
		sa.Column(
			"created_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.ForeignKeyConstraint(
			["user_id"], ["users.id"],
			name=op.f("fk_user_voice_models_user_id_users"),
			ondelete="CASCADE",
		),
		sa.ForeignKeyConstraint(
			["voice_model_id"], ["voice_models.id"],
			name=op.f("fk_user_voice_models_voice_model_id_voice_models"),
			ondelete="CASCADE",
		),
		sa.PrimaryKeyConstraint("user_id", "voice_model_id", name=op.f("pk_user_voice_models")),
	)
	op.create_index(op.f("ix_user_voice_models_user_id"), "user_voice_models", ["user_id"])

	# ── subscriptions ──────────────────────────────────────────────────────────
	op.create_table(
		"subscriptions",
		sa.Column("id", sa.String(36), primary_key=True, nullable=False),
		sa.Column("user_id", sa.String(36), nullable=False),
		sa.Column(
			"provider",
			postgresql.ENUM("stripe", "paystack", name="payment_provider", create_type=False),
			nullable=False,
		),
		sa.Column("provider_subscription_id", sa.String(128), nullable=False),
		sa.Column("provider_plan_id", sa.String(128), nullable=False),
		sa.Column("tier", sa.String(32), nullable=False),
		sa.Column(
			"interval",
			postgresql.ENUM("month", "year", name="subscription_interval", create_type=False),
			nullable=False,
		),
		sa.Column("status", sa.String(32), nullable=False),
		sa.Column("amount_minor", sa.Integer(), nullable=False),
		sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
		sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
		sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
		sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.text("false")),
		sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column("trial_start", sa.DateTime(timezone=True), nullable=True),
		sa.Column("trial_end", sa.DateTime(timezone=True), nullable=True),
		sa.Column(
			"metadata",
			postgresql.JSONB(astext_type=sa.Text()),
			nullable=False,
			server_default="{}",
		),
		sa.Column(
			"created_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.Column(
			"updated_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.ForeignKeyConstraint(
			["user_id"], ["users.id"],
			name=op.f("fk_subscriptions_user_id_users"),
			ondelete="CASCADE",
		),
		sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
		sa.UniqueConstraint(
			"provider_subscription_id",
			name=op.f("uq_subscriptions_provider_subscription_id"),
		),
	)
	op.create_index(op.f("ix_subscriptions_user_id"), "subscriptions", ["user_id"])
	op.create_index(op.f("ix_subscriptions_status"), "subscriptions", ["status"])
	op.create_index("ix_subscriptions_user_status", "subscriptions", ["user_id", "status"])

	# ── payments ───────────────────────────────────────────────────────────────
	op.create_table(
		"payments",
		sa.Column("id", sa.String(36), primary_key=True, nullable=False),
		sa.Column("user_id", sa.String(36), nullable=False),
		sa.Column("subscription_id", sa.String(36), nullable=True),
		sa.Column(
			"provider",
			postgresql.ENUM("stripe", "paystack", name="payment_provider", create_type=False),
			nullable=False,
		),
		sa.Column("provider_payment_id", sa.String(128), nullable=False),
		sa.Column("provider_charge_id", sa.String(128), nullable=True),
		# Stripe uses payment_intent_id, Paystack uses reference — both land in
		# provider_payment_id.  Dedicated alias columns kept for query clarity.
		sa.Column("stripe_payment_intent_id", sa.String(128), nullable=True),
		sa.Column("paystack_reference", sa.String(128), nullable=True),
		sa.Column(
			"status",
			postgresql.ENUM(
				"pending", "succeeded", "failed", "refunded",
				"partially_refunded", "disputed",
				name="payment_status",
				create_type=False,
			),
			nullable=False,
		),
		sa.Column("amount_minor", sa.Integer(), nullable=False),
		sa.Column("currency", sa.String(3), nullable=False),
		sa.Column("refunded_amount_minor", sa.Integer(), nullable=False, server_default="0"),
		sa.Column("description", sa.Text(), nullable=True),
		sa.Column("failure_code", sa.String(64), nullable=True),
		sa.Column("failure_message", sa.Text(), nullable=True),
		sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column(
			"metadata",
			postgresql.JSONB(astext_type=sa.Text()),
			nullable=False,
			server_default="{}",
		),
		sa.Column(
			"created_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.Column(
			"updated_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.ForeignKeyConstraint(
			["user_id"], ["users.id"],
			name=op.f("fk_payments_user_id_users"),
			ondelete="CASCADE",
		),
		sa.ForeignKeyConstraint(
			["subscription_id"], ["subscriptions.id"],
			name=op.f("fk_payments_subscription_id_subscriptions"),
			ondelete="SET NULL",
		),
		sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
		sa.UniqueConstraint(
			"provider_payment_id",
			name=op.f("uq_payments_provider_payment_id"),
		),
		sa.UniqueConstraint(
			"stripe_payment_intent_id",
			name=op.f("uq_payments_stripe_payment_intent_id"),
		),
		sa.UniqueConstraint(
			"paystack_reference",
			name=op.f("uq_payments_paystack_reference"),
		),
	)
	op.create_index(op.f("ix_payments_user_id"), "payments", ["user_id"])
	op.create_index(op.f("ix_payments_status"), "payments", ["status"])
	op.create_index("ix_payments_stripe_payment_intent_id", "payments", ["stripe_payment_intent_id"])
	op.create_index("ix_payments_paystack_reference", "payments", ["paystack_reference"])

	# ── invoices ───────────────────────────────────────────────────────────────
	op.create_table(
		"invoices",
		sa.Column("id", sa.String(36), primary_key=True, nullable=False),
		sa.Column("user_id", sa.String(36), nullable=False),
		sa.Column("subscription_id", sa.String(36), nullable=True),
		sa.Column("payment_id", sa.String(36), nullable=True),
		sa.Column(
			"provider",
			postgresql.ENUM("stripe", "paystack", name="payment_provider", create_type=False),
			nullable=False,
		),
		sa.Column("provider_invoice_id", sa.String(128), nullable=False),
		sa.Column(
			"status",
			postgresql.ENUM("draft", "open", "paid", "void", "uncollectible", name="invoice_status", create_type=False),
			nullable=False,
		),
		sa.Column("subtotal_minor", sa.Integer(), nullable=False),
		sa.Column("tax_minor", sa.Integer(), nullable=False, server_default="0"),
		sa.Column("total_minor", sa.Integer(), nullable=False),
		sa.Column("currency", sa.String(3), nullable=False),
		sa.Column("invoice_pdf_url", sa.String(2048), nullable=True),
		sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
		sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column(
			"line_items",
			postgresql.JSONB(astext_type=sa.Text()),
			nullable=False,
			server_default="[]",
		),
		sa.Column(
			"created_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.Column(
			"updated_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.ForeignKeyConstraint(
			["user_id"], ["users.id"],
			name=op.f("fk_invoices_user_id_users"),
			ondelete="CASCADE",
		),
		sa.ForeignKeyConstraint(
			["subscription_id"], ["subscriptions.id"],
			name=op.f("fk_invoices_subscription_id_subscriptions"),
			ondelete="SET NULL",
		),
		sa.ForeignKeyConstraint(
			["payment_id"], ["payments.id"],
			name=op.f("fk_invoices_payment_id_payments"),
			ondelete="SET NULL",
		),
		sa.PrimaryKeyConstraint("id", name=op.f("pk_invoices")),
		sa.UniqueConstraint(
			"provider_invoice_id",
			name=op.f("uq_invoices_provider_invoice_id"),
		),
	)
	op.create_index(op.f("ix_invoices_user_id"), "invoices", ["user_id"])
	op.create_index(op.f("ix_invoices_status"), "invoices", ["status"])

	# ── beat_listings ──────────────────────────────────────────────────────────
	op.create_table(
		"beat_listings",
		sa.Column("id", sa.String(36), primary_key=True, nullable=False),
		sa.Column("track_id", sa.String(36), nullable=False),
		sa.Column("seller_id", sa.String(36), nullable=False),
		sa.Column("title", sa.String(256), nullable=False),
		sa.Column("description", sa.Text(), nullable=True),
		sa.Column(
			"status",
			postgresql.ENUM("draft", "active", "paused", "sold_out", "removed", name="listing_status", create_type=False),
			nullable=False,
			server_default="draft",
		),
		sa.Column(
			"license_type",
			postgresql.ENUM("non_exclusive", "exclusive", "free", name="license_type", create_type=False),
			nullable=False,
			server_default="non_exclusive",
		),
		sa.Column("price_minor", sa.Integer(), nullable=False, server_default="0"),
		sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
		sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
		sa.Column("purchase_count", sa.Integer(), nullable=False, server_default="0"),
		sa.Column(
			"tags",
			postgresql.JSONB(astext_type=sa.Text()),
			nullable=False,
			server_default="[]",
		),
		sa.Column("preview_url", sa.String(2048), nullable=True),
		sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column(
			"created_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.Column(
			"updated_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.ForeignKeyConstraint(
			["track_id"], ["tracks.id"],
			name=op.f("fk_beat_listings_track_id_tracks"),
			ondelete="CASCADE",
		),
		sa.ForeignKeyConstraint(
			["seller_id"], ["users.id"],
			name=op.f("fk_beat_listings_seller_id_users"),
			ondelete="CASCADE",
		),
		sa.PrimaryKeyConstraint("id", name=op.f("pk_beat_listings")),
		sa.UniqueConstraint("track_id", name=op.f("uq_beat_listings_track_id")),
	)
	op.create_index(op.f("ix_beat_listings_track_id"), "beat_listings", ["track_id"])
	op.create_index(op.f("ix_beat_listings_seller_id"), "beat_listings", ["seller_id"])
	op.create_index(op.f("ix_beat_listings_status"), "beat_listings", ["status"])
	op.create_index("ix_listings_status_created", "beat_listings", ["status", "created_at"])
	op.create_index("ix_listings_seller_status", "beat_listings", ["seller_id", "status"])

	# ── beat_purchases ─────────────────────────────────────────────────────────
	op.create_table(
		"beat_purchases",
		sa.Column("id", sa.String(36), primary_key=True, nullable=False),
		sa.Column("listing_id", sa.String(36), nullable=False),
		sa.Column("buyer_id", sa.String(36), nullable=False),
		sa.Column("seller_id", sa.String(36), nullable=False),
		sa.Column("payment_provider", sa.String(32), nullable=False),
		sa.Column("provider_payment_id", sa.String(128), nullable=False),
		sa.Column("amount_minor", sa.Integer(), nullable=False),
		sa.Column("currency", sa.String(3), nullable=False),
		sa.Column(
			"license_type",
			postgresql.ENUM("non_exclusive", "exclusive", "free", name="license_type", create_type=False),
			nullable=False,
		),
		sa.Column("download_url", sa.String(2048), nullable=True),
		sa.Column("download_expires_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column("download_count", sa.Integer(), nullable=False, server_default="0"),
		sa.Column(
			"metadata",
			postgresql.JSONB(astext_type=sa.Text()),
			nullable=False,
			server_default="{}",
		),
		sa.Column(
			"created_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.Column(
			"updated_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.ForeignKeyConstraint(
			["listing_id"], ["beat_listings.id"],
			name=op.f("fk_beat_purchases_listing_id_beat_listings"),
			ondelete="RESTRICT",
		),
		sa.ForeignKeyConstraint(
			["buyer_id"], ["users.id"],
			name=op.f("fk_beat_purchases_buyer_id_users"),
			ondelete="RESTRICT",
		),
		sa.PrimaryKeyConstraint("id", name=op.f("pk_beat_purchases")),
		sa.UniqueConstraint("provider_payment_id", name=op.f("uq_beat_purchases_provider_payment_id")),
	)
	op.create_index(op.f("ix_beat_purchases_listing_id"), "beat_purchases", ["listing_id"])
	op.create_index(op.f("ix_beat_purchases_buyer_id"), "beat_purchases", ["buyer_id"])
	op.create_index(op.f("ix_beat_purchases_seller_id"), "beat_purchases", ["seller_id"])
	op.create_index(
		"ix_purchases_buyer_listing",
		"beat_purchases",
		["buyer_id", "listing_id"],
		unique=True,
	)

	# ── social_shares ──────────────────────────────────────────────────────────
	op.create_table(
		"social_shares",
		sa.Column("id", sa.String(36), primary_key=True, nullable=False),
		sa.Column("user_id", sa.String(36), nullable=False),
		sa.Column("track_id", sa.String(36), nullable=False),
		sa.Column("platform", sa.String(32), nullable=False),  # twitter/instagram/tiktok/whatsapp
		sa.Column("share_url", sa.String(2048), nullable=True),
		sa.Column("click_count", sa.Integer(), nullable=False, server_default="0"),
		sa.Column(
			"created_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.Column(
			"updated_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.ForeignKeyConstraint(
			["user_id"], ["users.id"],
			name=op.f("fk_social_shares_user_id_users"),
			ondelete="CASCADE",
		),
		sa.ForeignKeyConstraint(
			["track_id"], ["tracks.id"],
			name=op.f("fk_social_shares_track_id_tracks"),
			ondelete="CASCADE",
		),
		sa.PrimaryKeyConstraint("id", name=op.f("pk_social_shares")),
	)
	op.create_index(op.f("ix_social_shares_user_id"), "social_shares", ["user_id"])
	op.create_index(op.f("ix_social_shares_track_id"), "social_shares", ["track_id"])

	# ── audit_log ──────────────────────────────────────────────────────────────
	op.create_table(
		"audit_log",
		sa.Column("id", sa.String(36), primary_key=True, nullable=False),
		sa.Column("table_name", sa.String(64), nullable=False),
		sa.Column("record_id", sa.String(36), nullable=False),
		sa.Column("action", sa.String(16), nullable=False),  # INSERT/UPDATE/DELETE
		sa.Column("old_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
		sa.Column("new_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
		sa.Column("user_id", sa.String(36), nullable=True),
		sa.Column(
			"created_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("now()"),
		),
		sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
	)
	op.create_index(op.f("ix_audit_log_table_name"), "audit_log", ["table_name"])
	op.create_index(op.f("ix_audit_log_record_id"), "audit_log", ["record_id"])
	op.create_index(op.f("ix_audit_log_user_id"), "audit_log", ["user_id"])
	op.create_index("ix_audit_log_table_record", "audit_log", ["table_name", "record_id"])
	op.create_index(op.f("ix_audit_log_created_at"), "audit_log", ["created_at"])


def downgrade() -> None:
	op.drop_table("audit_log")
	op.drop_table("social_shares")
	op.drop_table("beat_purchases")
	op.drop_table("beat_listings")
	op.drop_table("invoices")
	op.drop_table("payments")
	op.drop_table("subscriptions")
	op.drop_table("user_voice_models")
	op.drop_table("voice_models")
	op.drop_table("track_stems")

	# Drop cross-table FK before dropping either table
	op.drop_constraint(
		op.f("fk_generation_jobs_track_id_tracks"),
		"generation_jobs",
		type_="foreignkey",
	)
	op.drop_table("tracks")
	op.drop_table("generation_jobs")
	op.drop_table("password_resets")
	op.drop_table("email_verifications")
	op.drop_table("refresh_tokens")
	op.drop_table("users")

	for enum_name in [
		"subscription_tier", "subscription_status", "job_status", "track_status",
		"sub_genre", "language", "payment_provider", "payment_status",
		"invoice_status", "subscription_interval", "voice_archetype",
		"voice_model_status", "listing_status", "license_type",
	]:
		op.execute(f"DROP TYPE IF EXISTS {enum_name}")
