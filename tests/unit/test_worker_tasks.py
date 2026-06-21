"""Unit tests for services/api/src/gbedu_api/worker_tasks.py.

Each thin shim function is tested for:
- Happy path: task.delay() is called with correct args
- Assertion error on empty/missing required args
- ImportError path: degrades gracefully (no exception propagates)
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_task_mock() -> MagicMock:
	task = MagicMock()
	task.delay = MagicMock()
	return task


# ── enqueue_generation ────────────────────────────────────────────────────────

def test_enqueue_generation_calls_delay():
	from gbedu_api.worker_tasks import enqueue_generation

	mock_task = _make_task_mock()
	mock_module = MagicMock()
	mock_module.run_generation_pipeline = mock_task
	with patch.dict(sys.modules, {"gbedu_worker.tasks.generation": mock_module}):
		enqueue_generation("job-abc-123")

	mock_task.delay.assert_called_once_with("job-abc-123")


def test_enqueue_generation_empty_job_id_raises():
	from gbedu_api.worker_tasks import enqueue_generation
	import pytest
	with pytest.raises(AssertionError):
		enqueue_generation("")


def test_enqueue_generation_import_error_graceful():
	from gbedu_api.worker_tasks import enqueue_generation
	with patch.dict(sys.modules, {"gbedu_worker.tasks.generation": None}):
		enqueue_generation("job-xyz")  # must not raise


# ── revoke_task ───────────────────────────────────────────────────────────────

def test_revoke_task_calls_control_revoke():
	from gbedu_api.worker_tasks import revoke_task

	mock_app = MagicMock()
	mock_app_module = MagicMock()
	mock_app_module.celery_app = mock_app
	with patch.dict(sys.modules, {"gbedu_worker.app": mock_app_module}):
		revoke_task("celery-task-id-001")

	mock_app.control.revoke.assert_called_once_with("celery-task-id-001", terminate=True)


def test_revoke_task_empty_id_raises():
	from gbedu_api.worker_tasks import revoke_task
	import pytest
	with pytest.raises(AssertionError):
		revoke_task("")


def test_revoke_task_import_error_graceful():
	from gbedu_api.worker_tasks import revoke_task
	with patch.dict(sys.modules, {"gbedu_worker.app": None}):
		revoke_task("celery-task-id-002")  # must not raise


# ── enqueue_voice_training ────────────────────────────────────────────────────

def test_enqueue_voice_training_calls_delay():
	from gbedu_api.worker_tasks import enqueue_voice_training

	mock_task = _make_task_mock()
	mock_module = MagicMock()
	mock_module.train_voice_model = mock_task
	with patch.dict(sys.modules, {"gbedu_worker.tasks.voice": mock_module}):
		enqueue_voice_training("voice-model-001")

	mock_task.delay.assert_called_once_with("voice-model-001")


def test_enqueue_voice_training_empty_id_raises():
	from gbedu_api.worker_tasks import enqueue_voice_training
	import pytest
	with pytest.raises(AssertionError):
		enqueue_voice_training("")


def test_enqueue_voice_training_import_error_graceful():
	from gbedu_api.worker_tasks import enqueue_voice_training
	with patch.dict(sys.modules, {"gbedu_worker.tasks.voice": None}):
		enqueue_voice_training("voice-model-002")  # must not raise


# ── enqueue_welcome_email ─────────────────────────────────────────────────────

def test_enqueue_welcome_email_calls_delay():
	from gbedu_api.worker_tasks import enqueue_welcome_email

	mock_task = _make_task_mock()
	mock_module = MagicMock()
	mock_module.send_welcome_email = mock_task
	with patch.dict(sys.modules, {"gbedu_worker.tasks.notifications": mock_module}):
		enqueue_welcome_email("user-001")

	mock_task.delay.assert_called_once_with("user-001")


def test_enqueue_welcome_email_empty_id_raises():
	from gbedu_api.worker_tasks import enqueue_welcome_email
	import pytest
	with pytest.raises(AssertionError):
		enqueue_welcome_email("")


def test_enqueue_welcome_email_import_error_graceful():
	from gbedu_api.worker_tasks import enqueue_welcome_email
	with patch.dict(sys.modules, {"gbedu_worker.tasks.notifications": None}):
		enqueue_welcome_email("user-002")  # must not raise


# ── enqueue_verify_email ──────────────────────────────────────────────────────

def test_enqueue_verify_email_calls_delay():
	from gbedu_api.worker_tasks import enqueue_verify_email

	mock_task = _make_task_mock()
	mock_module = MagicMock()
	mock_module.send_verify_email = mock_task
	with patch.dict(sys.modules, {"gbedu_worker.tasks.notifications": mock_module}):
		enqueue_verify_email("user-001", "https://example.com/verify?token=abc")

	mock_task.delay.assert_called_once_with("user-001", "https://example.com/verify?token=abc")


def test_enqueue_verify_email_empty_user_id_raises():
	from gbedu_api.worker_tasks import enqueue_verify_email
	import pytest
	with pytest.raises(AssertionError):
		enqueue_verify_email("", "https://example.com/verify")


def test_enqueue_verify_email_empty_url_raises():
	from gbedu_api.worker_tasks import enqueue_verify_email
	import pytest
	with pytest.raises(AssertionError):
		enqueue_verify_email("user-001", "")


def test_enqueue_verify_email_import_error_graceful():
	from gbedu_api.worker_tasks import enqueue_verify_email
	with patch.dict(sys.modules, {"gbedu_worker.tasks.notifications": None}):
		enqueue_verify_email("user-003", "https://example.com/verify")  # must not raise


# ── enqueue_password_reset_email ──────────────────────────────────────────────

def test_enqueue_password_reset_email_calls_delay():
	from gbedu_api.worker_tasks import enqueue_password_reset_email

	mock_task = _make_task_mock()
	mock_module = MagicMock()
	mock_module.send_password_reset_email = mock_task
	with patch.dict(sys.modules, {"gbedu_worker.tasks.notifications": mock_module}):
		enqueue_password_reset_email("user-001", "https://example.com/reset?token=xyz")

	mock_task.delay.assert_called_once_with("user-001", "https://example.com/reset?token=xyz")


def test_enqueue_password_reset_email_empty_user_id_raises():
	from gbedu_api.worker_tasks import enqueue_password_reset_email
	import pytest
	with pytest.raises(AssertionError):
		enqueue_password_reset_email("", "https://example.com/reset")


def test_enqueue_password_reset_email_empty_url_raises():
	from gbedu_api.worker_tasks import enqueue_password_reset_email
	import pytest
	with pytest.raises(AssertionError):
		enqueue_password_reset_email("user-001", "")


def test_enqueue_password_reset_email_import_error_graceful():
	from gbedu_api.worker_tasks import enqueue_password_reset_email
	with patch.dict(sys.modules, {"gbedu_worker.tasks.notifications": None}):
		enqueue_password_reset_email("user-004", "https://example.com/reset")  # must not raise
