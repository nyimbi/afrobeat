from __future__ import annotations

import logging
from typing import Any, cast

import structlog
from gbedu_core import logging as logging_module


def _logging_module() -> Any:
	return cast(Any, logging_module)


def _reset_logging_state() -> None:
	module = _logging_module()
	module._service_name = "gbedu"
	module._environment = "development"
	module._configured = False


def test_service_info_processor_adds_defaults() -> None:
	_reset_logging_state()
	module = _logging_module()
	module._service_name = "api"
	module._environment = "test"

	event = module._add_service_info(None, "info", {"event": "hello"})

	assert event == {"event": "hello", "service": "api", "environment": "test"}


def test_service_info_processor_preserves_existing_values() -> None:
	_reset_logging_state()

	event = _logging_module()._add_service_info(
		None,
		"info",
		{"service": "worker", "environment": "ci"},
	)

	assert event["service"] == "worker"
	assert event["environment"] == "ci"


def test_drop_color_message_processor_removes_uvicorn_key() -> None:
	event = _logging_module()._drop_color_message_key(
		None,
		"info",
		{"event": "request", "color_message": "green"},
	)

	assert event == {"event": "request"}


def test_configure_logging_sets_root_handler_and_is_idempotent() -> None:
	_reset_logging_state()

	logging_module.configure_logging("api", level="DEBUG", environment="development")
	root_logger = logging.getLogger()
	first_handlers = list(root_logger.handlers)

	logging_module.configure_logging("worker", level="ERROR", environment="production")

	module = _logging_module()
	assert module._service_name == "api"
	assert module._environment == "development"
	assert module._configured is True
	assert root_logger.level == logging.DEBUG
	assert list(root_logger.handlers) == first_handlers


def test_configure_logging_production_silences_noisy_loggers() -> None:
	_reset_logging_state()

	logging_module.configure_logging("api", level="INFO", environment="production")

	for logger_name in ("uvicorn.access", "sqlalchemy.engine", "httpx", "httpcore"):
		assert logging.getLogger(logger_name).level == logging.WARNING


def test_get_logger_returns_structlog_bound_logger() -> None:
	logger = logging_module.get_logger("unit.test")

	assert callable(cast(Any, logger).bind)


def test_log_context_binds_and_unbinds_contextvars() -> None:
	structlog.contextvars.clear_contextvars()

	with logging_module.LogContext(request_id="req-1", user_id="user-1"):
		assert structlog.contextvars.get_contextvars()["request_id"] == "req-1"
		assert structlog.contextvars.get_contextvars()["user_id"] == "user-1"

	assert "request_id" not in structlog.contextvars.get_contextvars()
	assert "user_id" not in structlog.contextvars.get_contextvars()
