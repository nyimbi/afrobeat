from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gbedu_core._uuid7 import uuid7str
from gbedu_core.db import Base, TimestampMixin


class RefreshToken(Base, TimestampMixin):
	"""Audit log of all issued refresh tokens.

	Revocation is enforced at the Redis blocklist layer (fast path); this table
	provides a durable audit trail and enables DB-level revocation queries for
	admin operations (e.g. revoke all tokens for a user).
	"""

	__tablename__ = "refresh_tokens"
	__table_args__ = (
		Index("ix_refresh_tokens_jti", "jti", unique=True),
		Index("ix_refresh_tokens_user_id", "user_id"),
	)

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)
	user_id: Mapped[str] = mapped_column(
		String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
	)
	token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
	jti: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
	expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
	revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
	user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
	ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

	user = relationship("User", back_populates="refresh_tokens", lazy="noload")
