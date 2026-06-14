from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from typing import Any, Generator

import structlog
from structlog.types import EventDict, WrappedLogger


def _add_service_info(
	logger: WrappedLogger,
	method_name: str,
	event_dict: EventDict,
) -> EventDict:
	"""Inject service_name and environment into every log record."""
	event_dict.setdefault("service", _SERVICE_NAME)
	event_dict.setdefault("environment", _ENVIRONMENT)
	return event_dict


def _drop_color_message_key(
	logger: WrappedLogger,
	method_name: str,
	event_dict: EventDict,
) -> EventDict:
	"""Uvicorn emits a 'color_message' key we don't want in structured logs."""
	event_dict.pop("color_message", None)
	return event_dict


_SERVICE_NAME: str = "gbedu"
_ENVIRONMENT: str = "development"
_CONFIGURED: bool = False


def configure_logging(service_name: str, level: str = "INFO", *, environment: str = "development") -> None:
	"""Configure structlog once at process startup.

	Subsequent calls are no-ops so safe to call from multiple entry points.
	"""
	global _SERVICE_NAME, _ENVIRONMENT, _CONFIGURED

	if _CONFIGURED:
		return

	_SERVICE_NAME = service_name
	_ENVIRONMENT = environment
	_CONFIGURED = True

	log_level = getattr(logging, level.upper(), logging.INFO)
	is_production = environment == "production"

	shared_processors: list[Any] = [
		structlog.contextvars.merge_contextvars,
		structlog.stdlib.add_logger_name,
		structlog.stdlib.add_log_level,
		structlog.stdlib.PositionalArgumentsFormatter(),
		structlog.processors.TimeStamper(fmt="iso"),
		structlog.processors.StackInfoRenderer(),
		_add_service_info,
		_drop_color_message_key,
	]

	if is_production:
		renderer: Any = structlog.processors.JSONRenderer()
	else:
		renderer = structlog.dev.ConsoleRenderer(colors=True)

	structlog.configure(
		processors=[
			*shared_processors,
			structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
		],
		wrapper_class=structlog.make_filtering_bound_logger(log_level),
		context_class=dict,
		logger_factory=structlog.stdlib.LoggerFactory(),
		cache_logger_on_first_use=True,
	)

	formatter = structlog.stdlib.ProcessorFormatter(
		foreign_pre_chain=shared_processors,
		processors=[
			structlog.stdlib.ProcessorFormatter.remove_processors_meta,
			renderer,
		],
	)

	handler = logging.StreamHandler(sys.stdout)
	handler.setFormatter(formatter)

	root_logger = logging.getLogger()
	root_logger.handlers = [handler]
	root_logger.setLevel(log_level)

	# Silence noisy third-party loggers in production
	if is_production:
		for noisy in ("uvicorn.access", "sqlalchemy.engine", "httpx", "httpcore"):
			logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str = __name__) -> structlog.stdlib.BoundLogger:
	return structlog.get_logger(name)


@contextmanager
def LogContext(**kwargs: Any) -> Generator[None, None, None]:
	"""Context manager that binds key/value pairs to all log records within the block.

	Uses structlog contextvars so the bindings are thread/task-local and
	automatically cleaned up on exit — safe in async and threaded code.

	Usage::

		async with LogContext(request_id="abc", user_id="xyz"):
			log.info("processing request")  # will carry request_id + user_id
	"""
	structlog.contextvars.bind_contextvars(**kwargs)
	try:
		yield
	finally:
		structlog.contextvars.unbind_contextvars(*kwargs.keys())
