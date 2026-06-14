from __future__ import annotations

"""Synchronous-compatible database access for Celery tasks.

Celery tasks are synchronous by default. We expose two helpers:

1. `run_async(coro)` — runs a coroutine in a fresh event loop (safe because
   each task runs in its own OS thread / process depending on worker pool).

2. `get_async_session()` — async context manager yielding an AsyncSession.
   Use inside `run_async()`.

Usage inside a Celery task:

    from gbedu_worker.db import run_async, get_async_session

    def my_task(...):
        async def _body():
            async with get_async_session() as session:
                user = await session.get(User, user_id)
                ...
        run_async(_body())
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, TypeVar

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gbedu_core.config import DatabaseSettings

log = structlog.get_logger(__name__)

_settings = DatabaseSettings()

# One engine per worker process — created lazily on first use.
_engine: Any = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_engine() -> Any:
	global _engine, _session_factory
	if _engine is None:
		_engine = create_async_engine(
			_settings.url,
			pool_size=_settings.pool_size,
			max_overflow=_settings.max_overflow,
			pool_pre_ping=_settings.pool_pre_ping,
			pool_recycle=_settings.pool_recycle,
			echo=_settings.echo,
		)
		_session_factory = async_sessionmaker(
			bind=_engine,
			class_=AsyncSession,
			expire_on_commit=False,
			autocommit=False,
			autoflush=False,
		)
		log.info(
			"worker db engine initialised",
			pool_size=_settings.pool_size,
			max_overflow=_settings.max_overflow,
		)
	return _engine


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
	"""Async context manager providing a transactional AsyncSession.

	Commits on clean exit, rolls back on any unhandled exception.
	"""
	_get_engine()
	assert _session_factory is not None

	async with _session_factory() as session:
		try:
			yield session
			await session.commit()
		except Exception:
			await session.rollback()
			raise


T = TypeVar("T")


def run_async(coro: Any) -> Any:
	"""Run an async coroutine from a synchronous Celery task body.

	Creates a new event loop for each call, which is safe because Celery
	workers run each task body in its own thread (prefork pool: separate
	process; gevent/eventlet: separate greenlet).
	"""
	loop = asyncio.new_event_loop()
	try:
		return loop.run_until_complete(coro)
	finally:
		try:
			pending = asyncio.all_tasks(loop)
			for task in pending:
				task.cancel()
			if pending:
				loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
		finally:
			loop.close()
