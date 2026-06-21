from __future__ import annotations

"""Unit tests for gbedu_worker.tasks.cleanup async helpers."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# ── helpers ───────────────────────────────────────────────────────────────


def _make_session(
	scalars_return: list[Any] | None = None, rowcount: int = 5
) -> tuple[MagicMock, Any]:
	session = MagicMock()
	session.add = MagicMock()
	session.commit = AsyncMock()
	session.flush = AsyncMock()

	result = MagicMock()
	result.rowcount = rowcount
	if scalars_return is not None:
		result.scalars.return_value.all.return_value = scalars_return
	else:
		result.scalars.return_value.all.return_value = []

	session.execute = AsyncMock(return_value=result)

	@asynccontextmanager
	async def _ctx():
		yield session

	return session, _ctx


def _make_track(track_id: str = "t1", distribution_status: str = "pending_retry") -> MagicMock:
	t = MagicMock()
	t.id = track_id
	t.metadata_ = {
		"distribution_status": distribution_status,
		"distribution_retry_count": 0,
	}
	return t


# ── _do_cleanup_temp_files ────────────────────────────────────────────────


async def test_cleanup_temp_files_deletes_old_objects() -> None:
	from gbedu_worker.tasks.cleanup import _do_cleanup_temp_files

	now = datetime.now(UTC)
	old_time = now - timedelta(hours=25)
	recent_time = now - timedelta(hours=1)

	paginator = MagicMock()
	page = {
		"Contents": [
			{"Key": "temp/old.mp3", "LastModified": old_time},
			{"Key": "temp/recent.mp3", "LastModified": recent_time},
		]
	}
	paginator.paginate.return_value = [page]

	mock_s3 = MagicMock()
	mock_s3.get_paginator.return_value = paginator
	mock_s3.delete_objects.return_value = {"Errors": []}

	with patch("boto3.client", return_value=mock_s3):
		result = await _do_cleanup_temp_files()

	assert result["status"] == "complete"
	assert result["deleted_count"] == 1  # only old file deleted
	mock_s3.delete_objects.assert_called_once()


async def test_cleanup_temp_files_no_old_objects() -> None:
	from gbedu_worker.tasks.cleanup import _do_cleanup_temp_files

	now = datetime.now(UTC)
	paginator = MagicMock()
	page = {"Contents": [{"Key": "temp/fresh.mp3", "LastModified": now}]}
	paginator.paginate.return_value = [page]

	mock_s3 = MagicMock()
	mock_s3.get_paginator.return_value = paginator

	with patch("boto3.client", return_value=mock_s3):
		result = await _do_cleanup_temp_files()

	assert result["status"] == "complete"
	assert result["deleted_count"] == 0
	mock_s3.delete_objects.assert_not_called()


async def test_cleanup_temp_files_empty_bucket() -> None:
	from gbedu_worker.tasks.cleanup import _do_cleanup_temp_files

	paginator = MagicMock()
	paginator.paginate.return_value = [{}]  # no Contents key

	mock_s3 = MagicMock()
	mock_s3.get_paginator.return_value = paginator

	with patch("boto3.client", return_value=mock_s3):
		result = await _do_cleanup_temp_files()

	assert result["status"] == "complete"
	assert result["deleted_count"] == 0


# ── _delete_batch ─────────────────────────────────────────────────────────


def test_delete_batch_returns_count_minus_errors() -> None:
	from gbedu_worker.tasks.cleanup import _delete_batch

	mock_s3 = MagicMock()
	mock_s3.delete_objects.return_value = {"Errors": [{"Key": "temp/bad.mp3"}]}

	keys = [{"Key": "temp/a.mp3"}, {"Key": "temp/b.mp3"}, {"Key": "temp/bad.mp3"}]
	with patch("gbedu_worker.tasks.cleanup._storage_settings"):
		result = _delete_batch(mock_s3, keys)

	assert result == 2  # 3 total - 1 error


def test_delete_batch_client_error_returns_zero() -> None:
	from botocore.exceptions import ClientError
	from gbedu_worker.tasks.cleanup import _delete_batch

	mock_s3 = MagicMock()
	mock_s3.delete_objects.side_effect = ClientError(
		{"Error": {"Code": "AccessDenied", "Message": "no"}}, "DeleteObjects"
	)

	with patch("gbedu_worker.tasks.cleanup._storage_settings"):
		result = _delete_batch(mock_s3, [{"Key": "temp/a.mp3"}])

	assert result == 0


# ── _do_reset_generation_counts ───────────────────────────────────────────


async def test_reset_generation_counts_returns_rows_affected() -> None:
	from gbedu_worker.tasks.cleanup import _do_reset_generation_counts

	_, ctx = _make_session(rowcount=12)

	with patch("gbedu_worker.tasks.cleanup.get_async_session", ctx):
		result = await _do_reset_generation_counts()

	assert result["status"] == "complete"
	assert result["rows_affected"] == 12


async def test_reset_generation_counts_no_rows() -> None:
	from gbedu_worker.tasks.cleanup import _do_reset_generation_counts

	_, ctx = _make_session(rowcount=0)

	with patch("gbedu_worker.tasks.cleanup.get_async_session", ctx):
		result = await _do_reset_generation_counts()

	assert result["rows_affected"] == 0


# ── _do_retry_failed_distributions ────────────────────────────────────────


async def test_retry_distributions_empty_list() -> None:
	from gbedu_worker.tasks.cleanup import _do_retry_failed_distributions

	_, ctx = _make_session(scalars_return=[])

	with patch("gbedu_worker.tasks.cleanup.get_async_session", ctx):
		result = await _do_retry_failed_distributions()

	assert result["status"] == "complete"
	assert result["attempted_count"] == 0


async def test_retry_distributions_success() -> None:
	from gbedu_worker.tasks.cleanup import _do_retry_failed_distributions

	track = _make_track()
	_, ctx = _make_session(scalars_return=[track])

	with (
		patch("gbedu_worker.tasks.cleanup.get_async_session", ctx),
		patch("gbedu_worker.tasks.cleanup._attempt_distribution", AsyncMock()),
	):
		result = await _do_retry_failed_distributions()

	assert result["attempted_count"] == 1
	assert result["succeeded_count"] == 1
	assert result["still_failing_count"] == 0
	assert track.metadata_["distribution_status"] == "distributed"


async def test_retry_distributions_failure_increments_count() -> None:
	from gbedu_worker.tasks.cleanup import _do_retry_failed_distributions

	track = _make_track()
	_, ctx = _make_session(scalars_return=[track])

	with (
		patch("gbedu_worker.tasks.cleanup.get_async_session", ctx),
		patch(
			"gbedu_worker.tasks.cleanup._attempt_distribution",
			AsyncMock(side_effect=RuntimeError("DSP down")),
		),
	):
		result = await _do_retry_failed_distributions()

	assert result["still_failing_count"] == 1
	assert result["succeeded_count"] == 0
	assert track.metadata_["distribution_retry_count"] == 1
	assert "DSP down" in track.metadata_["distribution_last_error"]
