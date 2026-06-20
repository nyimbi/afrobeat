from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import DateTime, MetaData, func, text
from sqlalchemy.ext.asyncio import (
	AsyncEngine,
	AsyncSession,
	async_sessionmaker,
	create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from gbedu_core.config import DatabaseSettings

log = structlog.get_logger(__name__)

# Explicit naming convention so Alembic can auto-generate constraint names
# across all databases without relying on DB-specific defaults.
NAMING_CONVENTION: dict[str, str] = {
	"ix": "ix_%(column_0_label)s",
	"uq": "uq_%(table_name)s_%(column_0_name)s",
	"ck": "ck_%(table_name)s_%(constraint_name)s",
	"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
	"pk": "pk_%(table_name)s",
}


def get_engine(settings: DatabaseSettings) -> AsyncEngine:
	assert settings.url, "DATABASE_URL must be set"
	assert settings.pool_size > 0, "pool_size must be positive"
	assert settings.max_overflow >= 0, "max_overflow must be non-negative"

	engine = create_async_engine(
		settings.url,
		pool_size=settings.pool_size,
		max_overflow=settings.max_overflow,
		pool_pre_ping=settings.pool_pre_ping,
		pool_recycle=settings.pool_recycle,
		echo=settings.echo,
		# JSON serialization for JSONB columns
		json_serializer=_json_serializer,
		json_deserializer=_json_deserializer,
	)

	log.info(
		"database engine created",
		pool_size=settings.pool_size,
		max_overflow=settings.max_overflow,
	)
	return engine


def _json_serializer(obj: Any) -> str:
	import json
	return json.dumps(obj, default=str)


def _json_deserializer(s: str) -> Any:
	import json
	return json.loads(s)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
	return async_sessionmaker(
		bind=engine,
		class_=AsyncSession,
		expire_on_commit=False,
		autocommit=False,
		autoflush=False,
	)


class Base(DeclarativeBase):
	metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
	"""Adds server-side created_at / updated_at timestamps."""

	created_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True),
		server_default=func.now(),
		nullable=False,
	)
	updated_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True),
		server_default=func.now(),
		onupdate=func.now(),
		nullable=False,
	)


class SoftDeleteMixin:
	"""Non-destructive logical deletion via deleted_at timestamp."""

	deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)

	@property
	def is_deleted(self) -> bool:
		return self.deleted_at is not None

	async def delete(self, session: AsyncSession) -> None:
		"""Mark this record deleted without removing it from the database."""
		from datetime import datetime, timezone
		assert not self.is_deleted, "record is already deleted"
		self.deleted_at = datetime.now(timezone.utc)
		session.add(self)
		await session.flush()


# ── FastAPI dependency ─────────────────────────────────────────────────────────

_session_factory: async_sessionmaker[AsyncSession] | None = None
_engine: AsyncEngine | None = None


def init_db(engine: AsyncEngine) -> None:
	"""Call once at application startup to wire up the session factory."""
	global _session_factory, _engine
	_engine = engine
	_session_factory = make_session_factory(engine)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
	"""FastAPI dependency that provides a transactional AsyncSession.

	Commits on clean exit, rolls back on any exception.
	"""
	assert _session_factory is not None, (
		"Database not initialised — call init_db(engine) at startup"
	)

	async with _session_factory() as session:
		try:
			yield session
			await session.commit()
		except Exception:
			await session.rollback()
			raise


async def ping_database(engine: AsyncEngine) -> float:
	"""Execute a trivial query and return round-trip latency in milliseconds."""
	import time

	start = time.perf_counter()
	async with engine.connect() as conn:
		await conn.execute(text("SELECT 1"))
	return (time.perf_counter() - start) * 1000


def get_pool_status(engine: AsyncEngine) -> dict[str, int]:
	"""Return current connection pool statistics (synchronous — no I/O)."""
	pool = engine.sync_engine.pool
	return {
		"pool_size": pool.size(),
		"checked_in": pool.checkedin(),
		"checked_out": pool.checkedout(),
		"overflow": pool.overflow(),
		"invalid": pool.invalid(),
	}
