"""Add webhook_events table for durable payment idempotency.

Replaces Redis-only SET NX with a DB-backed dedup record that survives
Redis restarts. Both Stripe and Paystack webhook handlers write here
before processing, preventing double-execution of financial operations.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-20 00:00:00.000000
"""
from __future__ import annotations

from datetime import timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
	op.create_table(
		"webhook_events",
		sa.Column("id", sa.String(36), nullable=False),
		sa.Column("event_id", sa.String(255), nullable=False),
		sa.Column(
			"provider",
			postgresql.ENUM("stripe", "paystack", name="payment_provider", create_type=False),
			nullable=False,
		),
		sa.Column("event_type", sa.String(128), nullable=False),
		sa.Column(
			"processed_at",
			sa.DateTime(timezone=True),
			nullable=False,
			server_default=sa.text("NOW()"),
		),
		sa.Column(
			"metadata",
			postgresql.JSONB(astext_type=sa.Text()),
			nullable=False,
			server_default=sa.text("'{}'::jsonb"),
		),
		sa.PrimaryKeyConstraint("id", name="pk_webhook_events"),
		sa.UniqueConstraint("event_id", name="uq_webhook_events_event_id"),
	)
	# Partial index: querying by event_id is the hot path; cover it explicitly.
def downgrade() -> None:
	op.drop_table("webhook_events")
