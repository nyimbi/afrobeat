from __future__ import annotations

"""Unit tests for gbedu_worker.tasks.voice async helpers."""

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from gbedu_core.models.voice import VoiceModelStatus


# ── helpers ───────────────────────────────────────────────────────────────

def _make_vm(
	vm_id: str = "vm-1",
	status: VoiceModelStatus = VoiceModelStatus.pending,
	training_audio_urls: list[str] | None = None,
	no_audio: bool = False,
) -> MagicMock:
	vm = MagicMock()
	vm.id = vm_id
	vm.status = status
	vm.training_audio_urls = [] if no_audio else (training_audio_urls if training_audio_urls is not None else ["https://r2/sample1.mp3"])
	vm.training_config = {"epochs": 10}
	vm.training_task_id = None
	vm.training_progress_percent = 0
	vm.error_message = None
	return vm


def _make_session(get_returns: list[Any]) -> tuple[MagicMock, Any]:
	session = MagicMock()
	session.add = MagicMock()
	session.commit = AsyncMock()

	call_idx = [-1]

	async def _get(model_cls: Any, pk: str) -> Any:
		call_idx[0] += 1
		idx = min(call_idx[0], len(get_returns) - 1)
		return get_returns[idx]

	session.get = _get

	@asynccontextmanager
	async def _ctx():
		yield session

	return session, _ctx


# ── _run_training ─────────────────────────────────────────────────────────

async def test_run_training_model_not_found_raises() -> None:
	from gbedu_worker.tasks.voice import _run_training

	_, ctx = _make_session([None])

	with patch("gbedu_worker.tasks.voice.get_async_session", ctx):
		with pytest.raises(ValueError, match="not found"):
			await _run_training("vm-missing", "task-1")


async def test_run_training_already_ready_skipped() -> None:
	from gbedu_worker.tasks.voice import _run_training

	vm = _make_vm(status=VoiceModelStatus.ready)
	_, ctx = _make_session([vm])

	with patch("gbedu_worker.tasks.voice.get_async_session", ctx):
		result = await _run_training("vm-1", "task-1")

	assert result["status"] == "skipped"
	assert result["reason"] == "already_terminal"


async def test_run_training_already_deprecated_skipped() -> None:
	from gbedu_worker.tasks.voice import _run_training

	vm = _make_vm(status=VoiceModelStatus.deprecated)
	_, ctx = _make_session([vm])

	with patch("gbedu_worker.tasks.voice.get_async_session", ctx):
		result = await _run_training("vm-1", "task-1")

	assert result["status"] == "skipped"


async def test_run_training_no_audio_raises() -> None:
	from gbedu_worker.tasks.voice import _run_training

	vm = _make_vm(no_audio=True)
	_, ctx = _make_session([vm])

	with patch("gbedu_worker.tasks.voice.get_async_session", ctx):
		with pytest.raises(ValueError, match="no training_audio_urls"):
			await _run_training("vm-1", "task-1")


async def test_run_training_ml_service_error_raises() -> None:
	from gbedu_worker.tasks.voice import _run_training

	vm = _make_vm()
	# First session: load + transition; second session: update after training
	vm_after = _make_vm()
	_, ctx = _make_session([vm, vm_after])

	mock_resp = MagicMock()
	mock_resp.status_code = 500
	mock_resp.text = "GPU OOM"

	mock_client = AsyncMock()
	mock_client.__aenter__ = AsyncMock(return_value=mock_client)
	mock_client.__aexit__ = AsyncMock(return_value=False)
	mock_client.post = AsyncMock(return_value=mock_resp)

	with (
		patch("gbedu_worker.tasks.voice.get_async_session", ctx),
		patch("httpx.AsyncClient", return_value=mock_client),
		patch("gbedu_worker.tasks.voice.get_settings", MagicMock(return_value=MagicMock(
			ml=MagicMock(service_url="http://ml:8001", service_api_key="key"),
		))),
	):
		with pytest.raises(RuntimeError, match="HTTP 500"):
			await _run_training("vm-1", "task-1")


async def test_run_training_happy_path() -> None:
	from gbedu_worker.tasks.voice import _run_training

	vm = _make_vm()
	vm_after = _make_vm()
	_, ctx = _make_session([vm, vm_after])

	mock_resp = MagicMock()
	mock_resp.status_code = 200
	mock_resp.json.return_value = {
		"model_file_url": "https://r2/model.pth",
		"index_file_url": "https://r2/model.index",
		"metrics": {"loss": 0.01},
	}

	mock_client = AsyncMock()
	mock_client.__aenter__ = AsyncMock(return_value=mock_client)
	mock_client.__aexit__ = AsyncMock(return_value=False)
	mock_client.post = AsyncMock(return_value=mock_resp)

	with (
		patch("gbedu_worker.tasks.voice.get_async_session", ctx),
		patch("httpx.AsyncClient", return_value=mock_client),
		patch("gbedu_worker.tasks.voice.get_settings", MagicMock(return_value=MagicMock(
			ml=MagicMock(service_url="http://ml:8001", service_api_key="key"),
		))),
	):
		result = await _run_training("vm-1", "task-1")

	assert result["status"] == "complete"
	assert result["model_file_url"] == "https://r2/model.pth"
	assert vm_after.status == VoiceModelStatus.ready


# ── _mark_failed ──────────────────────────────────────────────────────────

async def test_mark_failed_updates_status() -> None:
	from gbedu_worker.tasks.voice import _mark_failed

	vm = _make_vm(status=VoiceModelStatus.training)
	_, ctx = _make_session([vm])

	with patch("gbedu_worker.tasks.voice.get_async_session", ctx):
		await _mark_failed("vm-1", ValueError("something broke"))

	assert vm.status == VoiceModelStatus.failed
	assert "ValueError" in vm.error_message


async def test_mark_failed_no_op_if_already_ready() -> None:
	from gbedu_worker.tasks.voice import _mark_failed

	vm = _make_vm(status=VoiceModelStatus.ready)
	_, ctx = _make_session([vm])

	with patch("gbedu_worker.tasks.voice.get_async_session", ctx):
		await _mark_failed("vm-1", ValueError("irrelevant"))

	# Status must not change
	assert vm.status == VoiceModelStatus.ready


async def test_mark_failed_no_op_if_model_gone() -> None:
	from gbedu_worker.tasks.voice import _mark_failed

	_, ctx = _make_session([None])

	with patch("gbedu_worker.tasks.voice.get_async_session", ctx):
		# Should not raise
		await _mark_failed("vm-missing", RuntimeError("gone"))
