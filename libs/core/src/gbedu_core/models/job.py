from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gbedu_core._uuid7 import uuid7str
from gbedu_core.db import Base, TimestampMixin

if TYPE_CHECKING:
	from gbedu_core.models.user import User
	from gbedu_core.models.track import Track


class JobStatus(str, enum.Enum):
	queued = "queued"
	ml_generating = "ml_generating"
	audio_processing = "audio_processing"
	uploading = "uploading"
	complete = "complete"
	failed = "failed"
	cancelled = "cancelled"


# Terminal states — a job in these states will never transition again
TERMINAL_JOB_STATUSES: frozenset[JobStatus] = frozenset({
	JobStatus.complete,
	JobStatus.failed,
	JobStatus.cancelled,
})


class GenerationJob(Base, TimestampMixin):
	__tablename__ = "generation_jobs"

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)
	user_id: Mapped[str] = mapped_column(
		String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
	)
	track_id: Mapped[str | None] = mapped_column(
		String(36), ForeignKey("tracks.id", ondelete="SET NULL"), nullable=True, index=True
	)

	status: Mapped[JobStatus] = mapped_column(
		Enum(JobStatus, name="job_status"),
		nullable=False,
		default=JobStatus.queued,
		server_default=JobStatus.queued.value,
		index=True,
	)

	celery_task_id: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
	model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
	prompt_used: Mapped[str] = mapped_column(Text, nullable=False)

	error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
	error_traceback: Mapped[str | None] = mapped_column(Text, nullable=True)

	started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
	completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

	progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

	# Arbitrary extra info — model params, seed, latency breakdown, etc.
	metadata_: Mapped[dict[str, Any]] = mapped_column(
		"metadata", JSONB, nullable=False, default=dict, server_default="{}"
	)

	# ── Relationships ──────────────────────────────────────────────────────────
	user: Mapped[User] = relationship("User", back_populates="jobs", lazy="noload")
	track: Mapped[Track | None] = relationship(
		"Track",
		foreign_keys="[GenerationJob.track_id]",
		back_populates="jobs",
		lazy="noload",
	)

	__table_args__ = (
		Index("ix_jobs_user_status", "user_id", "status"),
		Index("ix_jobs_celery_task", "celery_task_id"),
	)

	@property
	def is_terminal(self) -> bool:
		return self.status in TERMINAL_JOB_STATUSES

	@property
	def duration_seconds(self) -> float | None:
		if self.started_at and self.completed_at:
			return (self.completed_at - self.started_at).total_seconds()
		return None

	def __repr__(self) -> str:
		return f"<GenerationJob id={self.id!r} status={self.status.value!r} progress={self.progress_percent}%>"
