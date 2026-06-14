"""Seed 8 preset Afrobeats voice archetypes into voice_models.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-14 00:01:00.000000
"""
from __future__ import annotations

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None

_NOW = "2026-06-14 00:01:00+00:00"

# 8 preset archetypes shipped with Gbẹdu.  IDs are stable so application code
# can reference them by constant rather than DB lookup.
_PRESETS = [
	{
		"id": "01910000-0000-7000-8000-000000000001",
		"name": "Omah Lay Inspired",
		"description": (
			"Silky, introspective Afro-soul timbre.  Warm mid-range, subtle rasp on high notes, "
			"intimate delivery.  Best for slow-burn Afropop and Alte tracks."
		),
		"archetype": "omah_lay_inspired",
		"training_config": {
			"pitch_shift": 0,
			"formant_shift": -0.5,
			"filter_radius": 3,
			"index_ratio": 0.75,
			"rms_mix_rate": 0.25,
			"protect": 0.33,
		},
	},
	{
		"id": "01910000-0000-7000-8000-000000000002",
		"name": "Burna Boy Inspired",
		"description": (
			"Deep, commanding Afrofusion baritone with Patois inflections.  "
			"Heavy chest resonance, laid-back phrasing.  Suits Afrofusion and dancehall crossover."
		),
		"archetype": "burna_boy_inspired",
		"training_config": {
			"pitch_shift": -2,
			"formant_shift": -1.0,
			"filter_radius": 4,
			"index_ratio": 0.80,
			"rms_mix_rate": 0.20,
			"protect": 0.33,
		},
	},
	{
		"id": "01910000-0000-7000-8000-000000000003",
		"name": "Wizkid Inspired",
		"description": (
			"Smooth, airy tenor with a signature breathy falsetto.  "
			"Light vibrato, effortlessly melodic.  Ideal for mainstream Afrobeats and Afropop."
		),
		"archetype": "wizkid_inspired",
		"training_config": {
			"pitch_shift": 1,
			"formant_shift": 0.0,
			"filter_radius": 3,
			"index_ratio": 0.70,
			"rms_mix_rate": 0.30,
			"protect": 0.33,
		},
	},
	{
		"id": "01910000-0000-7000-8000-000000000004",
		"name": "Tems Inspired",
		"description": (
			"Rich, honeyed alto with gospel undertones.  Full chest voice, "
			"powerful belt, soulful riffs.  Excels on Afrosoul and R&B-cross tracks."
		),
		"archetype": "tems_inspired",
		"training_config": {
			"pitch_shift": 0,
			"formant_shift": 0.5,
			"filter_radius": 3,
			"index_ratio": 0.75,
			"rms_mix_rate": 0.25,
			"protect": 0.40,
		},
	},
	{
		"id": "01910000-0000-7000-8000-000000000005",
		"name": "Davido Inspired",
		"description": (
			"High-energy, punchy tenor with Lagos street energy.  "
			"Bold delivery, punchy consonants, strong hook recall.  "
			"Perfect for high-tempo Afrobeats anthems."
		),
		"archetype": "davido_inspired",
		"training_config": {
			"pitch_shift": 2,
			"formant_shift": 0.0,
			"filter_radius": 3,
			"index_ratio": 0.65,
			"rms_mix_rate": 0.35,
			"protect": 0.33,
		},
	},
	{
		"id": "01910000-0000-7000-8000-000000000006",
		"name": "CKay Inspired",
		"description": (
			"Ethereal, falsetto-forward Afropop voice.  Gentle, airy texture with "
			"electronic edge.  Optimised for melodic Afropop and Alte production."
		),
		"archetype": "ckay_inspired",
		"training_config": {
			"pitch_shift": 3,
			"formant_shift": 1.0,
			"filter_radius": 2,
			"index_ratio": 0.60,
			"rms_mix_rate": 0.40,
			"protect": 0.33,
		},
	},
	{
		"id": "01910000-0000-7000-8000-000000000007",
		"name": "Rema Inspired",
		"description": (
			"Young, versatile trap-Afrobeats tenor.  Melodic rap flow with smooth "
			"singing transitions, digital-native compression.  Suits trap-Afrobeats and Afropop."
		),
		"archetype": "rema_inspired",
		"training_config": {
			"pitch_shift": 1,
			"formant_shift": 0.0,
			"filter_radius": 3,
			"index_ratio": 0.70,
			"rms_mix_rate": 0.30,
			"protect": 0.33,
		},
	},
	{
		"id": "01910000-0000-7000-8000-000000000008",
		"name": "Ayra Starr Inspired",
		"description": (
			"Bright, youthful soprano with Francophone West-African warmth.  "
			"Light, confident delivery with natural vibrato.  "
			"Ideal for contemporary Afropop and Afrosoul."
		),
		"archetype": "ayra_starr_inspired",
		"training_config": {
			"pitch_shift": 4,
			"formant_shift": 1.5,
			"filter_radius": 2,
			"index_ratio": 0.65,
			"rms_mix_rate": 0.35,
			"protect": 0.40,
		},
	},
]


def upgrade() -> None:
	import json

	for p in _PRESETS:
		op.execute(sa.text(
			"INSERT INTO voice_models "
			"(id, user_id, name, description, archetype, status, is_preset, is_public, "
			" model_file_url, index_file_url, training_audio_urls, training_config, "
			" training_metrics, training_task_id, training_progress_percent, "
			" error_message, deleted_at, created_at, updated_at) "
			"VALUES "
			"(:id, NULL, :name, :description, "
			" CAST(:archetype AS voice_archetype), CAST(:status AS voice_model_status), "
			" :is_preset, :is_public, NULL, NULL, "
			" CAST(:training_audio_urls AS json), CAST(:training_config AS json), "
			" CAST(:training_metrics AS json), NULL, :training_progress_percent, "
			" NULL, NULL, CAST(:created_at AS timestamptz), CAST(:updated_at AS timestamptz))"
		).bindparams(
			id=p["id"],
			name=p["name"],
			description=p["description"],
			archetype=p["archetype"],
			status="ready",
			is_preset=True,
			is_public=True,
			training_audio_urls=json.dumps([]),
			training_config=json.dumps(p["training_config"]),
			training_metrics=json.dumps({}),
			training_progress_percent=100,
			created_at=_NOW,
			updated_at=_NOW,
		))


def downgrade() -> None:
	ids = [p["id"] for p in _PRESETS]
	id_list = ", ".join(f"'{i}'" for i in ids)
	op.execute(f"DELETE FROM voice_models WHERE id IN ({id_list})")
