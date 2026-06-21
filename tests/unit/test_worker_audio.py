from __future__ import annotations

"""Unit tests for gbedu_worker.tasks.audio async helpers."""

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── session mock ──────────────────────────────────────────────────────────

def _make_session(get_return: Any = None) -> tuple[MagicMock, Any]:
	session = MagicMock()
	session.add = MagicMock()
	session.flush = AsyncMock()
	session.commit = AsyncMock()

	async def _get(model_cls: Any, pk: str) -> Any:
		return get_return

	session.get = _get

	@asynccontextmanager
	async def _ctx():
		yield session

	return session, _ctx


def _make_track(
	track_id: str = "track-1",
	audio_url: str = "https://r2.example.com/audio.mp3",
	stem_urls: dict | None = None,
) -> MagicMock:
	t = MagicMock()
	t.id = track_id
	t.audio_url = audio_url
	t.stem_urls = stem_urls
	t.metadata_ = {}
	return t


# ── _do_process_stems ─────────────────────────────────────────────────────

async def test_process_stems_track_not_found() -> None:
	from gbedu_worker.tasks.audio import _do_process_stems

	_, ctx = _make_session(None)

	with patch("gbedu_worker.tasks.audio.get_async_session", ctx):
		result = await _do_process_stems("track-missing")

	assert result == {"status": "skipped", "reason": "not_found"}


async def test_process_stems_already_done() -> None:
	from gbedu_worker.tasks.audio import _do_process_stems

	track = _make_track(stem_urls={"vocals": "url1", "drums": "url2"})
	_, ctx = _make_session(track)

	with patch("gbedu_worker.tasks.audio.get_async_session", ctx):
		result = await _do_process_stems("track-1")

	assert result["status"] == "skipped"
	assert result["reason"] == "already_done"


async def test_process_stems_happy_path() -> None:
	from gbedu_worker.tasks.audio import _do_process_stems
	import sys

	track = _make_track(stem_urls=None)
	session, ctx = _make_session(track)

	mock_pipeline = MagicMock()
	mock_pipeline.separate_stems.return_value = {"vocals": b"data1", "drums": b"data2"}

	mock_r2 = MagicMock()
	mock_r2.upload = AsyncMock(side_effect=lambda key, data, content_type: f"https://r2/{key}")

	gbedu_audio_mod = MagicMock()
	gbedu_audio_pipeline_mod = MagicMock()
	gbedu_audio_pipeline_mod.AudioPipeline.return_value = mock_pipeline

	mock_loop = MagicMock()

	async def _fake_run_in_executor(executor: Any, fn: Any, *args: Any) -> Any:
		return fn(*args)

	mock_loop.run_in_executor = _fake_run_in_executor

	with (
		patch("gbedu_worker.tasks.audio.get_async_session", ctx),
		patch("gbedu_worker.tasks.audio.R2Client", return_value=mock_r2),
		patch("asyncio.get_event_loop", return_value=mock_loop),
		patch.dict(sys.modules, {"gbedu_audio": gbedu_audio_mod, "gbedu_audio.pipeline": gbedu_audio_pipeline_mod}),
	):
		result = await _do_process_stems("track-1")

	assert result["status"] == "complete"
	assert "vocals" in result["stem_urls"]
	assert "drums" in result["stem_urls"]


# ── _do_remaster_track ────────────────────────────────────────────────────

async def test_remaster_track_not_found() -> None:
	from gbedu_worker.tasks.audio import _do_remaster_track

	_, ctx = _make_session(None)

	with patch("gbedu_worker.tasks.audio.get_async_session", ctx):
		result = await _do_remaster_track("track-missing", "afropop_radio")

	assert result == {"status": "skipped", "reason": "not_found"}


async def test_remaster_track_happy_path() -> None:
	from gbedu_worker.tasks.audio import _do_remaster_track
	import sys

	track = _make_track()
	session, ctx = _make_session(track)

	mock_pipeline = MagicMock()
	mock_pipeline.remaster.return_value = b"remastered audio"

	mock_r2 = MagicMock()
	mock_r2.upload = AsyncMock(return_value="https://r2/remastered.mp3")

	gbedu_audio_mod = MagicMock()
	gbedu_audio_pipeline_mod = MagicMock()
	gbedu_audio_pipeline_mod.AudioPipeline.return_value = mock_pipeline

	mock_loop = MagicMock()

	async def _fake_run_in_executor(executor: Any, fn: Any, *args: Any) -> Any:
		return fn(*args)

	mock_loop.run_in_executor = _fake_run_in_executor

	with (
		patch("gbedu_worker.tasks.audio.get_async_session", ctx),
		patch("gbedu_worker.tasks.audio.R2Client", return_value=mock_r2),
		patch("asyncio.get_event_loop", return_value=mock_loop),
		patch.dict(sys.modules, {"gbedu_audio": gbedu_audio_mod, "gbedu_audio.pipeline": gbedu_audio_pipeline_mod}),
	):
		result = await _do_remaster_track("track-1", "afropop_radio")

	assert result["status"] == "complete"
	assert result["url"] == "https://r2/remastered.mp3"
	assert result["profile"] == "afropop_radio"


# ── _do_create_preview ────────────────────────────────────────────────────

async def test_create_preview_track_not_found() -> None:
	from gbedu_worker.tasks.audio import _do_create_preview

	_, ctx = _make_session(None)

	with patch("gbedu_worker.tasks.audio.get_async_session", ctx):
		result = await _do_create_preview("track-missing")

	assert result == {"status": "skipped", "reason": "not_found"}


async def test_create_preview_happy_path() -> None:
	from gbedu_worker.tasks.audio import _do_create_preview
	import sys

	track = _make_track()
	session, ctx = _make_session(track)

	mock_pipeline = MagicMock()
	mock_pipeline.create_preview.return_value = b"preview audio"

	mock_r2 = MagicMock()
	mock_r2.upload = AsyncMock(return_value="https://r2/preview.mp3")

	gbedu_audio_mod = MagicMock()
	gbedu_audio_pipeline_mod = MagicMock()
	gbedu_audio_pipeline_mod.AudioPipeline.return_value = mock_pipeline

	mock_loop = MagicMock()

	async def _fake_run_in_executor(executor: Any, fn: Any, *args: Any) -> Any:
		return fn(*args)

	mock_loop.run_in_executor = _fake_run_in_executor

	with (
		patch("gbedu_worker.tasks.audio.get_async_session", ctx),
		patch("gbedu_worker.tasks.audio.R2Client", return_value=mock_r2),
		patch("asyncio.get_event_loop", return_value=mock_loop),
		patch.dict(sys.modules, {"gbedu_audio": gbedu_audio_mod, "gbedu_audio.pipeline": gbedu_audio_pipeline_mod}),
	):
		result = await _do_create_preview("track-1")

	assert result["status"] == "complete"
	assert result["preview_url"] == "https://r2/preview.mp3"
	assert track.audio_url_watermarked == "https://r2/preview.mp3"


# ── _jitter_countdown ─────────────────────────────────────────────────────

def test_jitter_countdown_ranges() -> None:
	from gbedu_worker.tasks.audio import _jitter_countdown

	# retry 0 → base 30; retry 1 → 90; retry 2+ → 270
	for _ in range(20):
		v0 = _jitter_countdown(0)
		assert 30 <= v0 <= 33, f"unexpected jitter for retry 0: {v0}"

		v1 = _jitter_countdown(1)
		assert 90 <= v1 <= 99, f"unexpected jitter for retry 1: {v1}"

		v2 = _jitter_countdown(2)
		assert 270 <= v2 <= 297, f"unexpected jitter for retry 2: {v2}"

		v99 = _jitter_countdown(99)
		assert 270 <= v99 <= 297
