"""Root test fixtures shared across unit and integration test suites.

pytest.ini settings live in the root pyproject.toml:
  [tool.pytest.ini_options]
  asyncio_mode = "auto"
"""
from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import fakeredis.aioredis
import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
	AsyncEngine,
	AsyncSession,
	async_sessionmaker,
	create_async_engine,
)

import getpass

_DB_USER = getpass.getuser()

# Ensure test env is set before any settings are constructed
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", f"postgresql+asyncpg://{_DB_USER}@localhost:5432/gbedu_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("GBEDU_ML_API_KEY", "test-ml-internal-api-key")

from gbedu_core.config import Settings
from gbedu_core.db import Base, make_session_factory
from gbedu_core.models import (  # noqa: F401 — register all mappers
	User, Track, GenerationJob, Subscription, Payment, Invoice,
	VoiceModel, BeatListing, BeatPurchase,
	SubscriptionTier, SubscriptionStatus,
	SubGenre, Language, TrackStatus,
	JobStatus, PaymentProvider, PaymentStatus,
)
from gbedu_core.security import hash_password
from gbedu_core._uuid7 import uuid7str


# ── Settings fixture ───────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def test_settings() -> Settings:
	"""Isolated settings object pointing at test DB and fake secrets."""
	return Settings(
		ENVIRONMENT="test",
		DATABASE_URL=f"postgresql+asyncpg://{_DB_USER}@localhost:5432/gbedu_test",
		JWT_SECRET_KEY="test-secret-key-not-for-production",
		REDIS_URL="redis://localhost:6379/15",
		LOG_LEVEL="WARNING",
	)


# ── Database engine + schema ───────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session")
async def test_db_engine(test_settings: Settings) -> AsyncGenerator[AsyncEngine, None]:
	"""Create the test database, run all migrations, yield engine, drop after."""
	engine = create_async_engine(
		test_settings.database.url,
		echo=False,
		future=True,
	)

	async with engine.begin() as conn:
		await conn.run_sync(Base.metadata.create_all)

	yield engine

	async with engine.begin() as conn:
		# CASCADE required because FK constraints exist between tables
		await conn.execute(sa.text("DROP SCHEMA public CASCADE"))
		await conn.execute(sa.text("CREATE SCHEMA public"))

	await engine.dispose()


# ── Per-test transactional session (fast — rolls back after each test) ─────────

@pytest_asyncio.fixture
async def test_db_session(test_db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
	"""Provide a session that wraps the entire test in a savepoint.

	The outer transaction is never committed so the DB is clean for the next
	test without truncating tables.
	"""
	connection = await test_db_engine.connect()
	transaction = await connection.begin()

	# Nested savepoint so the code under test can commit/rollback without
	# actually touching the outer transaction.
	await connection.begin_nested()

	factory = async_sessionmaker(
		bind=connection,
		class_=AsyncSession,
		expire_on_commit=False,
		autocommit=False,
		autoflush=False,
	)

	async with factory() as session:
		yield session

	await transaction.rollback()
	await connection.close()


# ── Redis fixture (fakeredis — no real Redis required in unit tests) ───────────

@pytest_asyncio.fixture
async def test_redis() -> AsyncGenerator[fakeredis.aioredis.FakeRedis, None]:
	"""In-memory Redis substitute — isolated per test."""
	redis = fakeredis.aioredis.FakeRedis()
	yield redis
	await redis.aclose()


# ── HTTP test client ───────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def test_client(test_db_session: AsyncSession, test_redis: Any) -> AsyncGenerator[httpx.AsyncClient, None]:
	"""httpx AsyncClient wired to the FastAPI app with DB/Redis overrides.

	Import is deferred so tests that don't need the API don't import FastAPI.
	"""
	from services.api.main import create_app  # type: ignore[import]
	from gbedu_core.db import get_db

	app = create_app()
	app.dependency_overrides[get_db] = lambda: test_db_session

	async with httpx.AsyncClient(
		transport=httpx.ASGITransport(app=app),
		base_url="http://testserver",
	) as client:
		yield client


# ── Factory fixtures ───────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def make_user(test_db_session: AsyncSession):
	"""Factory: make_user(tier="free") → User (persisted, not committed)."""
	async def _factory(
		tier: str = "free",
		email: str | None = None,
		full_name: str = "Test User",
		is_verified: bool = True,
	) -> User:
		user = User(
			id=uuid7str(),
			email=email or f"test-{uuid7str()}@example.com",
			hashed_password=hash_password("TestPassword123!"),
			full_name=full_name,
			subscription_tier=SubscriptionTier(tier),
			subscription_status=SubscriptionStatus.active,
			is_active=True,
			is_verified=is_verified,
			preferred_language="en",
			generation_count_today=0,
			generation_count_reset_at=datetime.now(timezone.utc),
		)
		test_db_session.add(user)
		await test_db_session.flush()
		return user

	return _factory


@pytest_asyncio.fixture
async def make_track(test_db_session: AsyncSession):
	"""Factory: make_track(user) → Track (persisted, not committed)."""
	async def _factory(user: User, status: str = "ready") -> Track:
		track = Track(
			id=uuid7str(),
			user_id=user.id,
			title="Test Track",
			prompt="groovy afropop beat 100bpm",
			sub_genre=SubGenre.afropop,
			language=Language.english,
			bpm=100,
			energy_level=6,
			status=TrackStatus(status),
			is_public=False,
		)
		test_db_session.add(track)
		await test_db_session.flush()
		return track

	return _factory


@pytest_asyncio.fixture
async def make_job(test_db_session: AsyncSession):
	"""Factory: make_job(user, track) → GenerationJob (persisted, not committed)."""
	async def _factory(
		user: User,
		track: Track | None = None,
		status: str = "queued",
	) -> GenerationJob:
		job = GenerationJob(
			id=uuid7str(),
			user_id=user.id,
			track_id=track.id if track else None,
			status=JobStatus(status),
			prompt_used="test prompt",
			progress_percent=0,
		)
		test_db_session.add(job)
		await test_db_session.flush()
		return job

	return _factory
