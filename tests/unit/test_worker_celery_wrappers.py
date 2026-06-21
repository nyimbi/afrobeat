from __future__ import annotations

"""Tests for Celery task wrapper bodies.

Celery tasks are PromiseProxy objects; _get_current_object() gives the real
Task instance, and type(real).run(mock_self, *args) invokes the Python
function with a controllable self.
"""

from unittest.mock import MagicMock, patch

import pytest
from celery.exceptions import MaxRetriesExceededError, Retry


def _make_self(retries: int = 0) -> MagicMock:
	mock_self = MagicMock()
	mock_self.request.id = "task-test-123"
	mock_self.request.retries = retries
	mock_self.request.delivery_info = {"routing_key": "default"}
	return mock_self


def _run(task_proxy, mock_self, *args, **kwargs):
	"""Call a Celery bind=True task's body with a controlled self."""
	real = task_proxy._get_current_object()
	return type(real).run(mock_self, *args, **kwargs)


# ── audio.process_stems ───────────────────────────────────────────────────────


def test_process_stems_happy_path() -> None:
	from gbedu_worker.tasks.audio import process_stems

	mock_self = _make_self()
	expected = {"status": "complete", "track_id": "t1"}
	with patch("gbedu_worker.tasks.audio.run_async", return_value=expected):
		with patch("gbedu_worker.tasks.audio.tracer"):
			with patch("gbedu_worker.tasks.audio.increment_error_count"):
				result = _run(process_stems, mock_self, "track-1")
	assert result == expected


def test_process_stems_assert_empty_track_id() -> None:
	from gbedu_worker.tasks.audio import process_stems

	mock_self = _make_self()
	with pytest.raises(AssertionError):
		_run(process_stems, mock_self, "")


def test_process_stems_error_triggers_retry() -> None:
	from gbedu_worker.tasks.audio import process_stems

	mock_self = _make_self()
	mock_self.retry.side_effect = Retry("retrying")
	with patch("gbedu_worker.tasks.audio.run_async", side_effect=RuntimeError("boom")):
		with patch("gbedu_worker.tasks.audio.tracer"):
			with patch("gbedu_worker.tasks.audio.increment_error_count"):
				with pytest.raises((RuntimeError, Retry)):
					_run(process_stems, mock_self, "track-1")
	mock_self.retry.assert_called_once()


# ── audio.remaster_track ──────────────────────────────────────────────────────


def test_remaster_track_happy_path() -> None:
	from gbedu_worker.tasks.audio import remaster_track

	mock_self = _make_self()
	expected = {"status": "remastered", "track_id": "t1"}
	with patch("gbedu_worker.tasks.audio.run_async", return_value=expected):
		with patch("gbedu_worker.tasks.audio.tracer"):
			with patch("gbedu_worker.tasks.audio.increment_error_count"):
				result = _run(remaster_track, mock_self, "track-1", "afropop_radio")
	assert result == expected


def test_remaster_track_assert_empty_profile() -> None:
	from gbedu_worker.tasks.audio import remaster_track

	mock_self = _make_self()
	with pytest.raises(AssertionError):
		_run(remaster_track, mock_self, "track-1", "")


def test_remaster_track_error_triggers_retry() -> None:
	from gbedu_worker.tasks.audio import remaster_track

	mock_self = _make_self()
	mock_self.retry.side_effect = Retry("retrying")
	with patch("gbedu_worker.tasks.audio.run_async", side_effect=ValueError("bad")):
		with patch("gbedu_worker.tasks.audio.tracer"):
			with patch("gbedu_worker.tasks.audio.increment_error_count"):
				with pytest.raises((ValueError, Retry)):
					_run(remaster_track, mock_self, "track-1", "profile")
	mock_self.retry.assert_called_once()


# ── audio.create_preview ─────────────────────────────────────────────────────


def test_create_preview_happy_path() -> None:
	from gbedu_worker.tasks.audio import create_preview

	mock_self = _make_self()
	expected = {"status": "done", "preview_url": "https://r2.example/preview.mp3"}
	with patch("gbedu_worker.tasks.audio.run_async", return_value=expected):
		with patch("gbedu_worker.tasks.audio.tracer"):
			with patch("gbedu_worker.tasks.audio.increment_error_count"):
				result = _run(create_preview, mock_self, "track-1")
	assert result["preview_url"] == "https://r2.example/preview.mp3"


def test_create_preview_error_triggers_retry() -> None:
	from gbedu_worker.tasks.audio import create_preview

	mock_self = _make_self()
	mock_self.retry.side_effect = Retry("retrying")
	with patch("gbedu_worker.tasks.audio.run_async", side_effect=OSError("r2 down")):
		with patch("gbedu_worker.tasks.audio.tracer"):
			with patch("gbedu_worker.tasks.audio.increment_error_count"):
				with pytest.raises((IOError, Retry)):
					_run(create_preview, mock_self, "track-1")
	mock_self.retry.assert_called_once()


# ── notifications.send_generation_complete_email ──────────────────────────────


def test_send_generation_complete_email_happy_path() -> None:
	from gbedu_worker.tasks.notifications import send_generation_complete_email

	mock_self = _make_self()
	expected = {"status": "sent", "user_id": "u1", "track_id": "t1"}
	with patch("gbedu_worker.tasks.notifications.run_async", return_value=expected):
		with patch("gbedu_worker.tasks.notifications.tracer"):
			with patch("gbedu_worker.tasks.notifications.increment_error_count"):
				result = _run(send_generation_complete_email, mock_self, "u1", "t1")
	assert result["status"] == "sent"


def test_send_generation_complete_email_assert_empty() -> None:
	from gbedu_worker.tasks.notifications import send_generation_complete_email

	mock_self = _make_self()
	with pytest.raises(AssertionError):
		_run(send_generation_complete_email, mock_self, "", "t1")


def test_send_generation_complete_email_error_triggers_retry() -> None:
	from gbedu_worker.tasks.notifications import send_generation_complete_email

	mock_self = _make_self()
	mock_self.retry.side_effect = Retry("retrying")
	with patch("gbedu_worker.tasks.notifications.run_async", side_effect=OSError("smtp down")):
		with patch("gbedu_worker.tasks.notifications.tracer"):
			with patch("gbedu_worker.tasks.notifications.increment_error_count"):
				with pytest.raises((OSError, Retry)):
					_run(send_generation_complete_email, mock_self, "u1", "t1")
	mock_self.retry.assert_called_once()


# ── notifications.send_welcome_email ─────────────────────────────────────────


def test_send_welcome_email_happy_path() -> None:
	from gbedu_worker.tasks.notifications import send_welcome_email

	mock_self = _make_self()
	expected = {"status": "sent", "user_id": "u1"}
	with patch("gbedu_worker.tasks.notifications.run_async", return_value=expected):
		with patch("gbedu_worker.tasks.notifications.tracer"):
			with patch("gbedu_worker.tasks.notifications.increment_error_count"):
				result = _run(send_welcome_email, mock_self, "u1")
	assert result["status"] == "sent"


def test_send_welcome_email_assert_empty() -> None:
	from gbedu_worker.tasks.notifications import send_welcome_email

	mock_self = _make_self()
	with pytest.raises(AssertionError):
		_run(send_welcome_email, mock_self, "")


def test_send_welcome_email_error_triggers_retry() -> None:
	from gbedu_worker.tasks.notifications import send_welcome_email

	mock_self = _make_self()
	mock_self.retry.side_effect = Retry("retry")
	with patch("gbedu_worker.tasks.notifications.run_async", side_effect=ConnectionError("net")):
		with patch("gbedu_worker.tasks.notifications.tracer"):
			with patch("gbedu_worker.tasks.notifications.increment_error_count"):
				with pytest.raises((ConnectionError, Retry)):
					_run(send_welcome_email, mock_self, "u1")
	mock_self.retry.assert_called_once()


# ── notifications.send_verify_email ──────────────────────────────────────────


def test_send_verify_email_happy_path() -> None:
	from gbedu_worker.tasks.notifications import send_verify_email

	mock_self = _make_self()
	expected = {"status": "sent", "user_id": "u1"}
	with patch("gbedu_worker.tasks.notifications.run_async", return_value=expected):
		with patch("gbedu_worker.tasks.notifications.tracer"):
			with patch("gbedu_worker.tasks.notifications.increment_error_count"):
				result = _run(send_verify_email, mock_self, "u1", "https://example.com/verify")
	assert result["status"] == "sent"


def test_send_verify_email_assert_empty_url() -> None:
	from gbedu_worker.tasks.notifications import send_verify_email

	mock_self = _make_self()
	with pytest.raises(AssertionError):
		_run(send_verify_email, mock_self, "u1", "")


# ── notifications.send_password_reset_email ───────────────────────────────────


def test_send_password_reset_email_happy_path() -> None:
	from gbedu_worker.tasks.notifications import send_password_reset_email

	mock_self = _make_self()
	expected = {"status": "sent", "user_id": "u1"}
	with patch("gbedu_worker.tasks.notifications.run_async", return_value=expected):
		with patch("gbedu_worker.tasks.notifications.tracer"):
			with patch("gbedu_worker.tasks.notifications.increment_error_count"):
				result = _run(send_password_reset_email, mock_self, "u1", "https://reset")
	assert result["status"] == "sent"


def test_send_password_reset_email_assert_empty_reset_url() -> None:
	from gbedu_worker.tasks.notifications import send_password_reset_email

	mock_self = _make_self()
	with pytest.raises(AssertionError):
		_run(send_password_reset_email, mock_self, "u1", "")


# ── notifications.send_subscription_confirmation ─────────────────────────────


def test_send_subscription_confirmation_happy_path() -> None:
	from gbedu_worker.tasks.notifications import send_subscription_confirmation

	mock_self = _make_self()
	expected = {"status": "sent", "user_id": "u1", "tier": "pro"}
	with patch("gbedu_worker.tasks.notifications.run_async", return_value=expected):
		with patch("gbedu_worker.tasks.notifications.tracer"):
			with patch("gbedu_worker.tasks.notifications.increment_error_count"):
				result = _run(send_subscription_confirmation, mock_self, "u1", "pro")
	assert result["tier"] == "pro"


def test_send_subscription_confirmation_assert_empty_tier() -> None:
	from gbedu_worker.tasks.notifications import send_subscription_confirmation

	mock_self = _make_self()
	with pytest.raises(AssertionError):
		_run(send_subscription_confirmation, mock_self, "u1", "")


# ── cleanup.cleanup_expired_temp_files ────────────────────────────────────────


def test_cleanup_expired_temp_files_happy_path() -> None:
	from gbedu_worker.tasks.cleanup import cleanup_expired_temp_files

	mock_self = _make_self()
	expected = {"deleted_count": 5}
	with patch("gbedu_worker.tasks.cleanup.run_async", return_value=expected):
		with patch("gbedu_worker.tasks.cleanup.tracer"):
			with patch("gbedu_worker.tasks.cleanup.increment_error_count"):
				result = _run(cleanup_expired_temp_files, mock_self)
	assert result["deleted_count"] == 5


def test_cleanup_expired_temp_files_error_triggers_retry() -> None:
	from gbedu_worker.tasks.cleanup import cleanup_expired_temp_files

	mock_self = _make_self()
	mock_self.retry.side_effect = Retry("retry")
	with patch("gbedu_worker.tasks.cleanup.run_async", side_effect=RuntimeError("s3 err")):
		with patch("gbedu_worker.tasks.cleanup.tracer"):
			with patch("gbedu_worker.tasks.cleanup.increment_error_count"):
				with pytest.raises((RuntimeError, Retry)):
					_run(cleanup_expired_temp_files, mock_self)
	mock_self.retry.assert_called_once()


# ── cleanup.reset_daily_generation_counts ────────────────────────────────────


def test_reset_daily_generation_counts_happy_path() -> None:
	from gbedu_worker.tasks.cleanup import reset_daily_generation_counts

	mock_self = _make_self()
	expected = {"rows_affected": 42}
	with patch("gbedu_worker.tasks.cleanup.run_async", return_value=expected):
		with patch("gbedu_worker.tasks.cleanup.tracer"):
			with patch("gbedu_worker.tasks.cleanup.increment_error_count"):
				result = _run(reset_daily_generation_counts, mock_self)
	assert result["rows_affected"] == 42


def test_reset_daily_generation_counts_error_triggers_retry() -> None:
	from gbedu_worker.tasks.cleanup import reset_daily_generation_counts

	mock_self = _make_self()
	mock_self.retry.side_effect = Retry("retry")
	with patch("gbedu_worker.tasks.cleanup.run_async", side_effect=ConnectionError("db")):
		with patch("gbedu_worker.tasks.cleanup.tracer"):
			with patch("gbedu_worker.tasks.cleanup.increment_error_count"):
				with pytest.raises((ConnectionError, Retry)):
					_run(reset_daily_generation_counts, mock_self)
	mock_self.retry.assert_called_once()


# ── cleanup.retry_failed_distributions ───────────────────────────────────────


def test_retry_failed_distributions_happy_path() -> None:
	from gbedu_worker.tasks.cleanup import retry_failed_distributions

	mock_self = _make_self()
	expected = {"attempted_count": 3, "succeeded_count": 2}
	with patch("gbedu_worker.tasks.cleanup.run_async", return_value=expected):
		with patch("gbedu_worker.tasks.cleanup.tracer"):
			with patch("gbedu_worker.tasks.cleanup.increment_error_count"):
				result = _run(retry_failed_distributions, mock_self)
	assert result["attempted_count"] == 3


def test_retry_failed_distributions_error_triggers_retry() -> None:
	from gbedu_worker.tasks.cleanup import retry_failed_distributions

	mock_self = _make_self()
	mock_self.retry.side_effect = Retry("retry")
	with patch("gbedu_worker.tasks.cleanup.run_async", side_effect=TimeoutError("timeout")):
		with patch("gbedu_worker.tasks.cleanup.tracer"):
			with patch("gbedu_worker.tasks.cleanup.increment_error_count"):
				with pytest.raises((TimeoutError, Retry)):
					_run(retry_failed_distributions, mock_self)
	mock_self.retry.assert_called_once()


# ── generation.run_generation_pipeline ───────────────────────────────────────


def test_run_generation_pipeline_happy_path() -> None:
	from gbedu_worker.tasks.generation import run_generation_pipeline

	mock_self = _make_self()
	expected = {"status": "complete", "track_id": "t1"}
	with patch("gbedu_worker.tasks.generation.run_async", return_value=expected):
		with patch("gbedu_worker.tasks.generation.tracer"):
			result = _run(run_generation_pipeline, mock_self, "job-1")
	assert result["status"] == "complete"


def test_run_generation_pipeline_assert_empty_job_id() -> None:
	from gbedu_worker.tasks.generation import run_generation_pipeline

	mock_self = _make_self()
	with pytest.raises(AssertionError):
		_run(run_generation_pipeline, mock_self, "")


def test_run_generation_pipeline_retryable_error_schedules_retry() -> None:
	from gbedu_worker.exceptions import MLServiceError
	from gbedu_worker.tasks.generation import run_generation_pipeline

	mock_self = _make_self(retries=0)
	mock_self.retry.side_effect = Retry("retrying")
	with patch("gbedu_worker.tasks.generation.run_async", side_effect=MLServiceError("ml down")):
		with patch("gbedu_worker.tasks.generation.tracer"):
			with pytest.raises((MLServiceError, Retry)):
				_run(run_generation_pipeline, mock_self, "job-1")
	mock_self.retry.assert_called_once()


def test_run_generation_pipeline_max_retries_routes_to_dlq() -> None:
	from gbedu_worker.exceptions import MLServiceError
	from gbedu_worker.tasks.generation import run_generation_pipeline

	mock_self = _make_self(retries=3)
	mock_self.retry.side_effect = MaxRetriesExceededError()
	with patch("gbedu_worker.tasks.generation.run_async", side_effect=MLServiceError("ml dead")):
		with patch("gbedu_worker.tasks.generation.tracer"):
			with patch("gbedu_worker.tasks.generation._route_to_dlq") as mock_dlq:
				with pytest.raises(MaxRetriesExceededError):
					_run(run_generation_pipeline, mock_self, "job-1")
	mock_dlq.assert_called_once()


def test_run_generation_pipeline_non_retryable_marks_job_failed() -> None:
	from gbedu_worker.tasks.generation import run_generation_pipeline

	mock_self = _make_self()
	with patch("gbedu_worker.tasks.generation.run_async") as mock_run:
		mock_run.side_effect = [ValueError("bad input"), None]
		with patch("gbedu_worker.tasks.generation.tracer"), pytest.raises(ValueError):
			_run(run_generation_pipeline, mock_self, "job-1")
	assert mock_run.call_count == 2


# ── dlq.process_dlq_message ───────────────────────────────────────────────────


def test_process_dlq_message_happy_path() -> None:
	from gbedu_worker.tasks.dlq import process_dlq_message

	mock_self = _make_self()
	expected = {"action": "marked_failed", "job_id": "job-1"}
	with patch("gbedu_worker.tasks.dlq.run_async", return_value=expected):
		with patch("gbedu_worker.tasks.dlq.tracer"):
			result = _run(
				process_dlq_message,
				mock_self,
				job_id="job-1",
				original_task_id="task-abc",
				original_queue="default",
				error_type="TimeoutError",
				error_message="timed out",
				error_traceback="Traceback ...",
				retry_count=3,
			)
	assert result["action"] == "marked_failed"


def test_process_dlq_message_assert_empty_job_id() -> None:
	from gbedu_worker.tasks.dlq import process_dlq_message

	mock_self = _make_self()
	with pytest.raises(AssertionError):
		_run(
			process_dlq_message,
			mock_self,
			job_id="",
			original_task_id="task-abc",
			original_queue="default",
			error_type="Err",
			error_message="msg",
			error_traceback="tb",
			retry_count=1,
		)


# ── voice.train_voice_model ───────────────────────────────────────────────────


def test_train_voice_model_happy_path() -> None:
	from gbedu_worker.tasks.voice import train_voice_model

	mock_self = _make_self()
	expected = {"status": "ready", "voice_model_id": "vm-1"}
	with patch("gbedu_worker.tasks.voice.run_async", return_value=expected):
		with patch("gbedu_worker.tasks.voice.tracer"):
			with patch("gbedu_worker.tasks.voice.increment_error_count"):
				result = _run(train_voice_model, mock_self, "vm-1")
	assert result["status"] == "ready"


def test_train_voice_model_assert_empty_id() -> None:
	from gbedu_worker.tasks.voice import train_voice_model

	mock_self = _make_self()
	with pytest.raises(AssertionError):
		_run(train_voice_model, mock_self, "")


def test_train_voice_model_retryable_error_schedules_retry() -> None:
	import httpx
	from gbedu_worker.tasks.voice import train_voice_model

	mock_self = _make_self(retries=0)
	mock_self.retry.side_effect = Retry("retrying")
	with patch("gbedu_worker.tasks.voice.run_async", side_effect=httpx.TimeoutException("timeout")):
		with patch("gbedu_worker.tasks.voice.tracer"):
			with patch("gbedu_worker.tasks.voice.increment_error_count"):
				with pytest.raises((httpx.TimeoutException, Retry)):
					_run(train_voice_model, mock_self, "vm-1")
	mock_self.retry.assert_called_once()


def test_train_voice_model_max_retries_marks_failed() -> None:
	import httpx
	from gbedu_worker.tasks.voice import train_voice_model

	mock_self = _make_self(retries=3)
	mock_self.retry.side_effect = MaxRetriesExceededError()
	with patch("gbedu_worker.tasks.voice.run_async") as mock_run:
		mock_run.side_effect = [httpx.TimeoutException("timeout"), None]
		with patch("gbedu_worker.tasks.voice.tracer"):
			with patch("gbedu_worker.tasks.voice.increment_error_count"):
				with pytest.raises(MaxRetriesExceededError):
					_run(train_voice_model, mock_self, "vm-1")


def test_train_voice_model_non_retryable_marks_failed() -> None:
	from gbedu_worker.tasks.voice import train_voice_model

	mock_self = _make_self()
	with patch("gbedu_worker.tasks.voice.run_async") as mock_run:
		mock_run.side_effect = [ValueError("bad model"), None]
		with patch("gbedu_worker.tasks.voice.tracer"):
			with patch("gbedu_worker.tasks.voice.increment_error_count"):
				with pytest.raises(ValueError):
					_run(train_voice_model, mock_self, "vm-1")
	assert mock_run.call_count == 2


# ── _SmtpEmailService ─────────────────────────────────────────────────────────


def test_smtp_email_service_render_template() -> None:
	from gbedu_worker.tasks.notifications import _email_settings, _SmtpEmailService

	svc = _SmtpEmailService(settings=_email_settings)
	html = svc._render_template(
		"generation_complete", {"user_name": "Tunde", "track_title": "Jẹ ká jo"}
	)
	assert isinstance(html, str)


def test_smtp_email_service_render_template_unknown_raises() -> None:
	from gbedu_worker.tasks.notifications import _email_settings, _SmtpEmailService
	from jinja2 import TemplateNotFound

	svc = _SmtpEmailService(settings=_email_settings)
	with pytest.raises(TemplateNotFound):
		svc._render_template("nonexistent_template", {"key": "val"})
