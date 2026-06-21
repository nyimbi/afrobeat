"""add track metadata_ jsonb column

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-20
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
	op.add_column(
		"tracks",
		sa.Column(
			"metadata_",
			postgresql.JSONB(astext_type=sa.Text()),
			nullable=False,
			server_default="{}",
		),
	)


def downgrade() -> None:
	op.drop_column("tracks", "metadata_")
