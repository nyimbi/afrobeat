from __future__ import annotations

import enum
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gbedu_core._uuid7 import uuid7str
from gbedu_core.db import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
	from gbedu_core.models.user import User


class VoiceArchetype(str, enum.Enum):
	"""Preset voice archetypes shipped with Gbẹdu — not user-trained."""
	omah_lay_inspired = "omah_lay_inspired"
	burna_boy_inspired = "burna_boy_inspired"
	wizkid_inspired = "wizkid_inspired"
	tems_inspired = "tems_inspired"
	davido_inspired = "davido_inspired"
	ckay_inspired = "ckay_inspired"
	rema_inspired = "rema_inspired"
	ayra_starr_inspired = "ayra_starr_inspired"
	neutral_male = "neutral_male"
	neutral_female = "neutral_female"
	custom = "custom"


class VoiceModelStatus(str, enum.Enum):
	pending = "pending"         # uploaded, training not started
	training = "training"       # RVC training job running
	ready = "ready"             # trained model available for inference
	failed = "failed"           # training failed
	deprecated = "deprecated"   # model retired


class VoiceModel(Base, TimestampMixin, SoftDeleteMixin):
	__tablename__ = "voice_models"

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)
	# null = system preset; non-null = user-trained
	user_id: Mapped[str | None] = mapped_column(
		String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
	)

	name: Mapped[str] = mapped_column(String(128), nullable=False)
	description: Mapped[str | None] = mapped_column(Text, nullable=True)

	archetype: Mapped[VoiceArchetype] = mapped_column(
		Enum(VoiceArchetype, name="voice_archetype"), nullable=False
	)
	status: Mapped[VoiceModelStatus] = mapped_column(
		Enum(VoiceModelStatus, name="voice_model_status"),
		nullable=False,
		default=VoiceModelStatus.pending,
		server_default=VoiceModelStatus.pending.value,
		index=True,
	)

	is_preset: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
	is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

	# R2 paths for model artefacts
	model_file_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
	index_file_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
	# Original uploaded audio samples used for training
	training_audio_urls: Mapped[list[str]] = mapped_column(
		JSONB, nullable=False, default=list, server_default="[]"
	)

	# RVC training hyper-parameters and result metrics
	training_config: Mapped[dict[str, Any]] = mapped_column(
		JSONB, nullable=False, default=dict, server_default="{}"
	)
	training_metrics: Mapped[dict[str, Any]] = mapped_column(
		JSONB, nullable=False, default=dict, server_default="{}"
	)

	# Celery task tracking for async training
	training_task_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
	training_progress_percent: Mapped[int] = mapped_column(
		Integer, nullable=False, default=0, server_default="0"
	)
	error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

	user: Mapped[User | None] = relationship("User", back_populates="voice_models", lazy="noload")

	__table_args__ = (
		Index("ix_voice_models_user_status", "user_id", "status"),
		Index("ix_voice_models_preset", "is_preset", "status"),
	)

	def __repr__(self) -> str:
		return (
			f"<VoiceModel id={self.id!r} name={self.name!r} "
			f"archetype={self.archetype.value!r} status={self.status.value!r}>"
		)
