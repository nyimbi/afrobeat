"""Tests covering the three FMEA bugs fixed in this session.

F-10: JWT secret guard — Settings must reject the default key in production.
F-08: Webhook idempotency — atomic SET NX replaces racy exists()→setex().
F-19: Non-retryable task failure — job row must transition to 'failed'.
"""
from __future__ import annotations

import asyncio
import unittest.mock as mock
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError


# ── F-10: JWT secret guard ─────────────────────────────────────────────────────

def test_jwt_default_secret_rejected_in_production() -> None:
	"""Settings must raise if the default JWT secret is used in production.

	JWTSettings is a nested BaseSettings that reads from env vars, not from the
	parent Settings constructor kwargs — so we patch os.environ directly.
	"""
	import os
	from gbedu_core.config import Settings

	env = {
		"ENVIRONMENT": "production",
		"DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
		"JWT_SECRET_KEY": "change-this-in-production",
	}
	with mock.patch.dict(os.environ, env, clear=False):
		with pytest.raises((AssertionError, ValidationError)):
			Settings()


def test_jwt_custom_secret_accepted_in_production() -> None:
	"""A non-default JWT secret must be accepted in production."""
	import os
	from gbedu_core.config import Settings

	env = {
		"ENVIRONMENT": "production",
		"DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
		"JWT_SECRET_KEY": "s3cur3-r4nd0m-64-char-secret-that-is-definitely-not-the-default!!",
	}
	with mock.patch.dict(os.environ, env, clear=False):
		s = Settings()
	assert s.is_production
	assert s.jwt.secret_key != "change-this-in-production"


def test_jwt_default_secret_allowed_in_development() -> None:
	"""Development environment must not block the default secret."""
	import os
	from gbedu_core.config import Settings

	env = {
		"ENVIRONMENT": "development",
		"JWT_SECRET_KEY": "change-this-in-production",
	}
	with mock.patch.dict(os.environ, env, clear=False):
		s = Settings()
	assert s.is_development


def test_jwt_default_secret_allowed_in_test() -> None:
	"""Test environment must not block the default secret."""
	import os
	from gbedu_core.config import Settings

	env = {
		"ENVIRONMENT": "test",
		"JWT_SECRET_KEY": "change-this-in-production",
	}
	with mock.patch.dict(os.environ, env, clear=False):
		s = Settings()
	assert s.environment == "test"


# ── F-08: Webhook idempotency ──────────────────────────────────────────────────

async def _make_redis_mock(set_returns: bool) -> AsyncMock:
	"""Build a minimal async Redis mock for webhook tests."""
	redis = AsyncMock()
	redis.set = AsyncMock(return_value=set_returns)
	redis.setex = AsyncMock(return_value=True)
	redis.delete = AsyncMock(return_value=1)
	return redis


async def test_stripe_webhook_atomic_claim_on_first_delivery() -> None:
	"""First delivery claims the key with SET NX and proceeds to handle the event."""
	from gbedu_api.routers.payments import stripe_webhook

	redis = await _make_redis_mock(set_returns=True)  # SET NX succeeds → we claimed it

	request = MagicMock()
	request.body = AsyncMock(return_value=b'{"id":"evt_1","type":"ping","data":{"object":{}}}')
	request.headers = {"Stripe-Signature": "t=1,v1=abc"}

	with (
		patch("stripe.Webhook.construct_event", return_value={"id": "evt_1", "type": "ping", "data": {"object": {}}}),
		patch("gbedu_api.routers.payments._handle_stripe_event", new_callable=AsyncMock),
		patch("gbedu_api.routers.payments.get_settings") as mock_settings,
	):
		mock_settings.return_value.stripe.secret_key = "sk_test"
		mock_settings.return_value.stripe.webhook_secret = "whsec_test"

		db = AsyncMock()
		result = await stripe_webhook(request=request, db=db, redis=redis)

	assert result == {"status": "ok"}
	redis.set.assert_called_once()
	call_kwargs = redis.set.call_args
	assert call_kwargs.kwargs.get("nx") is True


async def test_stripe_webhook_duplicate_rejected_atomically() -> None:
	"""Second delivery gets SET NX=False and is returned 'already_processed' without handling."""
	from gbedu_api.routers.payments import stripe_webhook

	redis = await _make_redis_mock(set_returns=False)  # SET NX fails → already claimed

	request = MagicMock()
	request.body = AsyncMock(return_value=b'{"id":"evt_1","type":"ping","data":{"object":{}}}')
	request.headers = {"Stripe-Signature": "t=1,v1=abc"}

	with (
		patch("stripe.Webhook.construct_event", return_value={"id": "evt_1", "type": "ping", "data": {"object": {}}}),
		patch("gbedu_api.routers.payments._handle_stripe_event", new_callable=AsyncMock) as mock_handler,
		patch("gbedu_api.routers.payments.get_settings") as mock_settings,
	):
		mock_settings.return_value.stripe.secret_key = "sk_test"
		mock_settings.return_value.stripe.webhook_secret = "whsec_test"

		db = AsyncMock()
		result = await stripe_webhook(request=request, db=db, redis=redis)

	assert result == {"status": "already_processed"}
	mock_handler.assert_not_called()


async def test_stripe_webhook_releases_claim_on_handler_failure() -> None:
	"""If the event handler raises, the idempotency key is deleted so Stripe can retry."""
	from fastapi import HTTPException
	from gbedu_api.routers.payments import stripe_webhook

	redis = await _make_redis_mock(set_returns=True)

	request = MagicMock()
	request.body = AsyncMock(return_value=b'{"id":"evt_2","type":"invoice.payment_succeeded","data":{"object":{}}}')
	request.headers = {"Stripe-Signature": "t=1,v1=abc"}

	with (
		patch("stripe.Webhook.construct_event", return_value={"id": "evt_2", "type": "invoice.payment_succeeded", "data": {"object": {}}}),
		patch("gbedu_api.routers.payments._handle_stripe_event", new_callable=AsyncMock, side_effect=RuntimeError("DB down")),
		patch("gbedu_api.routers.payments.get_settings") as mock_settings,
	):
		mock_settings.return_value.stripe.secret_key = "sk_test"
		mock_settings.return_value.stripe.webhook_secret = "whsec_test"

		db = AsyncMock()
		with pytest.raises(HTTPException) as exc_info:
			await stripe_webhook(request=request, db=db, redis=redis)

	assert exc_info.value.status_code == 500
	redis.delete.assert_called_once()


# ── F-19: Non-retryable task failure marks job failed ─────────────────────────

async def test_mark_job_failed_transitions_non_terminal_job() -> None:
	"""_mark_job_failed must set status=failed, error_message, completed_at."""
	from gbedu_worker.tasks.generation import _mark_job_failed  # type: ignore[import]
	from gbedu_core.models.job import GenerationJob, JobStatus

	job = GenerationJob(
		id="job-001",
		user_id="user-001",
		status=JobStatus.ml_generating,
		prompt_used="test",
		progress_percent=40,
	)

	mock_session = AsyncMock()
	mock_result = MagicMock()
	mock_result.scalar_one_or_none.return_value = job
	mock_session.execute = AsyncMock(return_value=mock_result)
	mock_session.commit = AsyncMock()

	mock_ctx = AsyncMock()
	mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
	mock_ctx.__aexit__ = AsyncMock(return_value=False)

	with patch("gbedu_worker.tasks.generation.get_async_session", return_value=mock_ctx):
		await _mark_job_failed("job-001", ValueError("OOM on GPU"))

	assert job.status == JobStatus.failed
	assert "OOM on GPU" in job.error_message
	assert job.completed_at is not None
	mock_session.commit.assert_called_once()


async def test_mark_job_failed_skips_already_terminal_job() -> None:
	"""_mark_job_failed must not overwrite a job that already reached a terminal state."""
	from gbedu_worker.tasks.generation import _mark_job_failed  # type: ignore[import]
	from gbedu_core.models.job import GenerationJob, JobStatus

	job = GenerationJob(
		id="job-002",
		user_id="user-001",
		status=JobStatus.complete,
		prompt_used="test",
		progress_percent=100,
	)

	mock_session = AsyncMock()
	mock_result = MagicMock()
	mock_result.scalar_one_or_none.return_value = job
	mock_session.execute = AsyncMock(return_value=mock_result)
	mock_session.commit = AsyncMock()

	mock_ctx = AsyncMock()
	mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
	mock_ctx.__aexit__ = AsyncMock(return_value=False)

	with patch("gbedu_worker.tasks.generation.get_async_session", return_value=mock_ctx):
		await _mark_job_failed("job-002", RuntimeError("late error"))

	# Status must not be overwritten
	assert job.status == JobStatus.complete
	mock_session.commit.assert_not_called()


async def test_mark_job_failed_handles_missing_job() -> None:
	"""_mark_job_failed must not crash if the job row doesn't exist."""
	from gbedu_worker.tasks.generation import _mark_job_failed  # type: ignore[import]

	mock_session = AsyncMock()
	mock_result = MagicMock()
	mock_result.scalar_one_or_none.return_value = None
	mock_session.execute = AsyncMock(return_value=mock_result)
	mock_session.commit = AsyncMock()

	mock_ctx = AsyncMock()
	mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
	mock_ctx.__aexit__ = AsyncMock(return_value=False)

	with patch("gbedu_worker.tasks.generation.get_async_session", return_value=mock_ctx):
		await _mark_job_failed("no-such-job", RuntimeError("boom"))

	mock_session.commit.assert_not_called()
