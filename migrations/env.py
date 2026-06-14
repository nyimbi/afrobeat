from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# Import ALL models so their tables are registered on Base.metadata before
# Alembic inspects it.  The order must satisfy FK references (user → others).
import gbedu_core.models  # noqa: F401 — side-effect import registers all mappers
from gbedu_core.db import Base, NAMING_CONVENTION
from gbedu_core.config import DatabaseSettings

# Alembic Config object — gives access to the values in alembic.ini
config = context.config

# Interpret the config file's logging section if it exists.
if config.config_file_name is not None:
	fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url() -> str:
	"""Prefer DATABASE_URL env var over alembic.ini value."""
	settings = DatabaseSettings()
	return settings.url


def run_migrations_offline() -> None:
	"""Generate SQL script without a live DB connection.

	Useful for inspecting what Alembic would do, or for applying migrations
	via a DBA review workflow.
	"""
	url = _get_url()
	context.configure(
		url=url,
		target_metadata=target_metadata,
		literal_binds=True,
		dialect_opts={"paramstyle": "named"},
		# Emit ANSI-compatible DDL so the script works against plain psql
		render_as_batch=False,
	)

	with context.begin_transaction():
		context.run_migrations()


async def run_async_migrations() -> None:
	"""Create an async engine and run migrations inside a connection."""
	url = _get_url()
	connectable = create_async_engine(url, future=True)

	async with connectable.connect() as connection:
		await connection.run_sync(_do_run_migrations)

	await connectable.dispose()


def _do_run_migrations(connection):  # type: ignore[no-untyped-def]
	context.configure(
		connection=connection,
		target_metadata=target_metadata,
		# Use naming convention from the metadata so generated constraints are
		# deterministic across engines.
		render_item=None,
		compare_type=True,
		compare_server_default=True,
	)

	with context.begin_transaction():
		context.run_migrations()


def run_migrations_online() -> None:
	asyncio.run(run_async_migrations())


if context.is_offline_mode():
	run_migrations_offline()
else:
	run_migrations_online()
