"""Add Caribbean, Kenyan, and East African sub_genre enum values.

Adds SubGenre: soca, calypso, gengetone, benga, taarab, afro_soca

No new Language values — existing languages cover these genres.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-19 00:00:00.000000
"""
from __future__ import annotations

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None

_NEW_SUB_GENRES: tuple[str, ...] = (
	"soca",
	"calypso",
	"gengetone",
	"benga",
	"taarab",
	"afro_soca",
)

# All values that exist after 0003 — needed to recreate the type on downgrade.
_ALL_SUB_GENRES_AFTER_0003: tuple[str, ...] = (
	"afropop", "afrofusion", "alte", "amapiano_cross", "afrobeats_uk",
	"afrobeats", "highlife", "bongo_flava", "soukous", "mbalax",
)


def upgrade() -> None:
	for value in _NEW_SUB_GENRES:
		op.execute(f"ALTER TYPE sub_genre ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
	new_sg = ", ".join(f"'{v}'" for v in _NEW_SUB_GENRES)

	op.execute(f"""
		DO $$
		BEGIN
			IF EXISTS (
				SELECT 1 FROM tracks WHERE sub_genre::text IN ({new_sg}) LIMIT 1
			) OR EXISTS (
				SELECT 1 FROM generation_jobs WHERE sub_genre::text IN ({new_sg}) LIMIT 1
			) THEN
				RAISE EXCEPTION
					'Cannot downgrade 0004: rows with new sub_genre values exist. '
					'Remove or remap them before running downgrade.';
			END IF;
		END $$
	""")

	orig_sg = ", ".join(f"'{v}'" for v in _ALL_SUB_GENRES_AFTER_0003)

	for table in ("tracks", "generation_jobs"):
		op.execute(f"ALTER TABLE {table} ADD COLUMN sub_genre_old text")
		op.execute(f"UPDATE {table} SET sub_genre_old = sub_genre::text")
		op.execute(f"ALTER TABLE {table} DROP COLUMN sub_genre")

	op.execute("DROP TYPE sub_genre")
	op.execute(f"CREATE TYPE sub_genre AS ENUM ({orig_sg})")

	for table in ("tracks", "generation_jobs"):
		op.execute(f"ALTER TABLE {table} ADD COLUMN sub_genre sub_genre")
		op.execute(f"UPDATE {table} SET sub_genre = sub_genre_old::sub_genre")
		op.execute(f"ALTER TABLE {table} ALTER COLUMN sub_genre SET NOT NULL")
		op.execute(f"ALTER TABLE {table} DROP COLUMN sub_genre_old")
