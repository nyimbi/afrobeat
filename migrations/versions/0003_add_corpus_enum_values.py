"""Add corpus-derived sub_genre and language enum values.

Adds 5 SubGenre values  : afrobeats, highlife, bongo_flava, soukous, mbalax
Adds 4 Language values  : swahili, lingala, zulu, twi

PostgreSQL has no ALTER TYPE … DROP VALUE so the downgrade must recreate
both types from scratch via the standard temp-column strategy.  It raises
explicitly if any row in tracks or generation_jobs carries a new value —
migrate the data first if needed.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-18 00:00:00.000000
"""
from __future__ import annotations

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None

# Values added by this migration — kept as constants so downgrade can reference them.
_NEW_SUB_GENRES: tuple[str, ...] = (
	"afrobeats",
	"highlife",
	"bongo_flava",
	"soukous",
	"mbalax",
)

_NEW_LANGUAGES: tuple[str, ...] = (
	"swahili",
	"lingala",
	"zulu",
	"twi",
)

# Original values from migration 0001 — used to recreate types on downgrade.
_ORIG_SUB_GENRES: tuple[str, ...] = (
	"afropop",
	"afrofusion",
	"alte",
	"amapiano_cross",
	"afrobeats_uk",
)

_ORIG_LANGUAGES: tuple[str, ...] = (
	"english",
	"pidgin",
	"yoruba",
	"igbo",
	"mix",
)


def upgrade() -> None:
	# ADD VALUE IF NOT EXISTS is idempotent and safe inside a transaction on PG ≥ 9.3.
	for value in _NEW_SUB_GENRES:
		op.execute(f"ALTER TYPE sub_genre ADD VALUE IF NOT EXISTS '{value}'")

	for value in _NEW_LANGUAGES:
		op.execute(f"ALTER TYPE language ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
	# Guard: refuse to downgrade if any row carries a value we are about to remove.
	new_sg = ", ".join(f"'{v}'" for v in _NEW_SUB_GENRES)
	new_la = ", ".join(f"'{v}'" for v in _NEW_LANGUAGES)

	op.execute(f"""
		DO $$
		BEGIN
			IF EXISTS (
				SELECT 1 FROM tracks
				WHERE sub_genre::text IN ({new_sg})
				LIMIT 1
			) OR EXISTS (
				SELECT 1 FROM generation_jobs
				WHERE sub_genre::text IN ({new_sg})
				LIMIT 1
			) THEN
				RAISE EXCEPTION
					'Cannot downgrade 0003: rows with new sub_genre values exist. '
					'Remove or remap them before running downgrade.';
			END IF;

			IF EXISTS (
				SELECT 1 FROM tracks
				WHERE language::text IN ({new_la})
				LIMIT 1
			) OR EXISTS (
				SELECT 1 FROM generation_jobs
				WHERE language::text IN ({new_la})
				LIMIT 1
			) THEN
				RAISE EXCEPTION
					'Cannot downgrade 0003: rows with new language values exist. '
					'Remove or remap them before running downgrade.';
			END IF;
		END $$
	""")

	# ── Recreate sub_genre without the new values ──────────────────────────────
	# PostgreSQL has no DROP VALUE, so: temp-column → drop column → drop type →
	# recreate type → restore column → restore data → enforce NOT NULL.

	orig_sg = ", ".join(f"'{v}'" for v in _ORIG_SUB_GENRES)
	orig_la = ", ".join(f"'{v}'" for v in _ORIG_LANGUAGES)

	for table in ("tracks", "generation_jobs"):
		op.execute(
			f"ALTER TABLE {table} ADD COLUMN sub_genre_old text"
		)
		op.execute(
			f"UPDATE {table} SET sub_genre_old = sub_genre::text"
		)
		op.execute(
			f"ALTER TABLE {table} DROP COLUMN sub_genre"
		)

	op.execute("DROP TYPE sub_genre")
	op.execute(f"CREATE TYPE sub_genre AS ENUM ({orig_sg})")

	for table in ("tracks", "generation_jobs"):
		op.execute(
			f"ALTER TABLE {table} ADD COLUMN sub_genre sub_genre"
		)
		op.execute(
			f"UPDATE {table} SET sub_genre = sub_genre_old::sub_genre"
		)
		op.execute(
			f"ALTER TABLE {table} ALTER COLUMN sub_genre SET NOT NULL"
		)
		op.execute(
			f"ALTER TABLE {table} DROP COLUMN sub_genre_old"
		)

	# ── Recreate language without the new values ───────────────────────────────

	for table in ("tracks", "generation_jobs"):
		op.execute(
			f"ALTER TABLE {table} ADD COLUMN language_old text"
		)
		op.execute(
			f"UPDATE {table} SET language_old = language::text"
		)
		op.execute(
			f"ALTER TABLE {table} DROP COLUMN language"
		)

	op.execute("DROP TYPE language")
	op.execute(f"CREATE TYPE language AS ENUM ({orig_la})")

	for table in ("tracks", "generation_jobs"):
		op.execute(
			f"ALTER TABLE {table} ADD COLUMN language language"
		)
		op.execute(
			f"UPDATE {table} SET language = language_old::language"
		)
		op.execute(
			f"ALTER TABLE {table} ALTER COLUMN language SET NOT NULL"
		)
		op.execute(
			f"ALTER TABLE {table} DROP COLUMN language_old"
		)
