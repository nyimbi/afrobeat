from __future__ import annotations

"""Unit tests for gbedu_worker.tasks.notifications async helpers."""

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_user(user_id: str = "user-1", email: str = "a@b.com", full_name: str = "Amara Nwosu") -> MagicMock:
	u = MagicMock()
	u.id = user_id
	u.email = email
	u.full_name = full_name
	return u


def _make_track(track_id: str = "track-1", title: str = "Test Track") -> MagicMock:
	t = MagicMock()
	t.id = track_id
	t.title = title
	t.audio_url = "https://r2.example.com/audio.mp3"
	t.audio_url_watermarked = "https://r2.example.com/preview.mp3"
	return t


def _session_mock(get_side_effects: list[Any]) -> tuple[MagicMock, Any]:
	"""Return (session_mock, asynccontextmanager-patcher-target-value)."""
	session = MagicMock()
	call_count = [-1]

	async def _get(model_cls: Any, pk: str) -> Any:
		call_count[0] += 1
		idx = min(call_count[0], len(get_side_effects) - 1)
		return get_side_effects[idx]

	session.get = _get

	@asynccontextmanager
	async def _ctx():
		yield session

	return session, _ctx


# ── _send_generation_complete ──────────────────────────────────────────────

async def test_send_generation_complete_duplicate_skipped() -> None:
	from gbedu_worker.tasks.notifications import _send_generation_complete

	with patch("gbedu_worker.tasks.notifications._already_sent", AsyncMock(return_value=True)):
		result = await _send_generation_complete("u1", "t1")

	assert result == {"status": "skipped", "reason": "duplicate"}


async def test_send_generation_complete_user_not_found() -> None:
	from gbedu_worker.tasks.notifications import _send_generation_complete

	_, ctx = _session_mock([None])  # user not found

	with (
		patch("gbedu_worker.tasks.notifications._already_sent", AsyncMock(return_value=False)),
		patch("gbedu_worker.tasks.notifications.get_async_session", ctx),
	):
		result = await _send_generation_complete("u1", "t1")

	assert result == {"status": "skipped", "reason": "user_not_found"}


async def test_send_generation_complete_track_not_found() -> None:
	from gbedu_worker.tasks.notifications import _send_generation_complete

	_, ctx = _session_mock([_make_user(), None])  # user found, track not found

	with (
		patch("gbedu_worker.tasks.notifications._already_sent", AsyncMock(return_value=False)),
		patch("gbedu_worker.tasks.notifications.get_async_session", ctx),
	):
		result = await _send_generation_complete("u1", "t1")

	assert result == {"status": "skipped", "reason": "track_not_found"}


async def test_send_generation_complete_happy_path() -> None:
	from gbedu_worker.tasks.notifications import _send_generation_complete

	user = _make_user()
	track = _make_track()
	_, ctx = _session_mock([user, track])

	mock_svc = MagicMock()
	mock_svc.send = AsyncMock()

	with (
		patch("gbedu_worker.tasks.notifications._already_sent", AsyncMock(return_value=False)),
		patch("gbedu_worker.tasks.notifications.get_async_session", ctx),
		patch("gbedu_worker.tasks.notifications._mark_sent", AsyncMock()),
		patch("gbedu_worker.tasks.notifications._build_email_service", return_value=mock_svc),
	):
		result = await _send_generation_complete("u1", "t1")

	assert result["status"] == "sent"
	mock_svc.send.assert_awaited_once()


# ── _send_welcome ──────────────────────────────────────────────────────────

async def test_send_welcome_duplicate_skipped() -> None:
	from gbedu_worker.tasks.notifications import _send_welcome

	with patch("gbedu_worker.tasks.notifications._already_sent", AsyncMock(return_value=True)):
		result = await _send_welcome("u1")

	assert result == {"status": "skipped", "reason": "duplicate"}


async def test_send_welcome_user_not_found() -> None:
	from gbedu_worker.tasks.notifications import _send_welcome

	_, ctx = _session_mock([None])

	with (
		patch("gbedu_worker.tasks.notifications._already_sent", AsyncMock(return_value=False)),
		patch("gbedu_worker.tasks.notifications.get_async_session", ctx),
	):
		result = await _send_welcome("u1")

	assert result == {"status": "skipped", "reason": "user_not_found"}


async def test_send_welcome_happy_path() -> None:
	from gbedu_worker.tasks.notifications import _send_welcome

	user = _make_user()
	_, ctx = _session_mock([user])

	mock_svc = MagicMock()
	mock_svc.send = AsyncMock()

	with (
		patch("gbedu_worker.tasks.notifications._already_sent", AsyncMock(return_value=False)),
		patch("gbedu_worker.tasks.notifications.get_async_session", ctx),
		patch("gbedu_worker.tasks.notifications._mark_sent", AsyncMock()),
		patch("gbedu_worker.tasks.notifications._build_email_service", return_value=mock_svc),
	):
		result = await _send_welcome("u1")

	assert result["status"] == "sent"


# ── _send_verify_email ─────────────────────────────────────────────────────

async def test_send_verify_email_duplicate_skipped() -> None:
	from gbedu_worker.tasks.notifications import _send_verify_email

	with patch("gbedu_worker.tasks.notifications._already_sent", AsyncMock(return_value=True)):
		result = await _send_verify_email("u1", "https://verify.example.com/token")

	assert result == {"status": "skipped", "reason": "duplicate"}


async def test_send_verify_email_user_not_found() -> None:
	from gbedu_worker.tasks.notifications import _send_verify_email

	_, ctx = _session_mock([None])

	with (
		patch("gbedu_worker.tasks.notifications._already_sent", AsyncMock(return_value=False)),
		patch("gbedu_worker.tasks.notifications.get_async_session", ctx),
	):
		result = await _send_verify_email("u1", "https://verify.example.com/token")

	assert result == {"status": "skipped", "reason": "user_not_found"}


async def test_send_verify_email_happy_path() -> None:
	from gbedu_worker.tasks.notifications import _send_verify_email

	user = _make_user()
	_, ctx = _session_mock([user])

	mock_svc = MagicMock()
	mock_svc.send = AsyncMock()

	with (
		patch("gbedu_worker.tasks.notifications._already_sent", AsyncMock(return_value=False)),
		patch("gbedu_worker.tasks.notifications.get_async_session", ctx),
		patch("gbedu_worker.tasks.notifications._mark_sent", AsyncMock()),
		patch("gbedu_worker.tasks.notifications._build_email_service", return_value=mock_svc),
	):
		result = await _send_verify_email("u1", "https://verify.example.com/token")

	assert result["status"] == "sent"
	mock_svc.send.assert_awaited_once()


# ── _send_password_reset ───────────────────────────────────────────────────

async def test_send_password_reset_duplicate_skipped() -> None:
	from gbedu_worker.tasks.notifications import _send_password_reset

	with patch("gbedu_worker.tasks.notifications._already_sent", AsyncMock(return_value=True)):
		result = await _send_password_reset("u1", "https://reset.example.com/token")

	assert result == {"status": "skipped", "reason": "duplicate"}


async def test_send_password_reset_user_not_found() -> None:
	from gbedu_worker.tasks.notifications import _send_password_reset

	_, ctx = _session_mock([None])

	with (
		patch("gbedu_worker.tasks.notifications._already_sent", AsyncMock(return_value=False)),
		patch("gbedu_worker.tasks.notifications.get_async_session", ctx),
	):
		result = await _send_password_reset("u1", "https://reset.example.com/token")

	assert result == {"status": "skipped", "reason": "user_not_found"}


async def test_send_password_reset_happy_path() -> None:
	from gbedu_worker.tasks.notifications import _send_password_reset

	user = _make_user()
	_, ctx = _session_mock([user])

	mock_svc = MagicMock()
	mock_svc.send = AsyncMock()

	fake_redis = MagicMock()
	fake_redis.setex = AsyncMock()
	fake_redis.__aenter__ = AsyncMock(return_value=fake_redis)
	fake_redis.__aexit__ = AsyncMock(return_value=False)

	with (
		patch("gbedu_worker.tasks.notifications._already_sent", AsyncMock(return_value=False)),
		patch("gbedu_worker.tasks.notifications.get_async_session", ctx),
		patch("gbedu_worker.tasks.notifications._build_email_service", return_value=mock_svc),
		patch("redis.asyncio.from_url", AsyncMock(return_value=fake_redis)),
	):
		result = await _send_password_reset("u1", "https://reset.example.com/token")

	assert result["status"] == "sent"


# ── _send_subscription_confirmation ───────────────────────────────────────

async def test_send_subscription_confirmation_duplicate_skipped() -> None:
	from gbedu_worker.tasks.notifications import _send_subscription_confirmation

	with patch("gbedu_worker.tasks.notifications._already_sent", AsyncMock(return_value=True)):
		result = await _send_subscription_confirmation("u1", "creator")

	assert result == {"status": "skipped", "reason": "duplicate"}


async def test_send_subscription_confirmation_user_not_found() -> None:
	from gbedu_worker.tasks.notifications import _send_subscription_confirmation

	_, ctx = _session_mock([None])

	with (
		patch("gbedu_worker.tasks.notifications._already_sent", AsyncMock(return_value=False)),
		patch("gbedu_worker.tasks.notifications.get_async_session", ctx),
	):
		result = await _send_subscription_confirmation("u1", "creator")

	assert result == {"status": "skipped", "reason": "user_not_found"}


async def test_send_subscription_confirmation_happy_path() -> None:
	from gbedu_worker.tasks.notifications import _send_subscription_confirmation

	user = _make_user()
	_, ctx = _session_mock([user])

	mock_svc = MagicMock()
	mock_svc.send = AsyncMock()

	with (
		patch("gbedu_worker.tasks.notifications._already_sent", AsyncMock(return_value=False)),
		patch("gbedu_worker.tasks.notifications.get_async_session", ctx),
		patch("gbedu_worker.tasks.notifications._mark_sent", AsyncMock()),
		patch("gbedu_worker.tasks.notifications._build_email_service", return_value=mock_svc),
	):
		result = await _send_subscription_confirmation("u1", "pro")

	assert result["status"] == "sent"
	assert result["tier"] == "pro"


# ── retry countdown ────────────────────────────────────────────────────────

def test_email_retry_countdown_values() -> None:
	from gbedu_worker.tasks.notifications import _email_retry_countdown

	assert _email_retry_countdown(0) == 15
	assert _email_retry_countdown(1) == 60
	assert _email_retry_countdown(2) == 300
	assert _email_retry_countdown(99) == 300  # clamped
