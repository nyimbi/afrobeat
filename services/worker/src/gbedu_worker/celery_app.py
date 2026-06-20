from __future__ import annotations

import asyncio
from datetime import timedelta

import structlog
from celery import Celery
from celery.signals import (
	celeryd_after_setup,
	task_failure,
	task_postrun,
	task_prerun,
	task_retry,
	task_success,
	worker_ready,
	worker_shutdown,
)
from opentelemetry.instrumentation.celery import CeleryInstrumentor

from gbedu_core.config import CelerySettings, ObservabilitySettings
from gbedu_core.telemetry import configure_telemetry, increment_error_count

log = structlog.get_logger(__name__)

_celery_settings = CelerySettings()
_obs_settings = ObservabilitySettings()

app = Celery("gbedu_worker")

app.conf.update(
	broker_url=_celery_settings.broker_url,
	result_backend=_celery_settings.result_backend,

	# Serialisation
	task_serializer="json",
	result_serializer="json",
	accept_content=["json"],

	# Timezone
	timezone="UTC",
	enable_utc=True,

	# Reliability — ack only after the task body returns successfully
	task_acks_late=True,
	task_reject_on_worker_lost=True,

	# Single task per fetch so acks_late works correctly across crashes
	worker_prefetch_multiplier=1,

	# Default concurrency — overridden by GPU worker via CLI --concurrency
	worker_concurrency=4,

	# Result TTL: keep results 24 h then discard
	result_expires=86400,

	# Compression
	task_compression="gzip",
	result_compression="gzip",

	# Routing
	task_default_queue="default",
	task_queues={
		"high": {
			"exchange": "high",
			"routing_key": "high",
			"queue_arguments": {"x-max-priority": 10},
		},
		"generation": {
			"exchange": "generation",
			"routing_key": "generation",
			# Messages that are nacked / rejected after max retries are forwarded
			# to the dead-letter exchange, which binds to the gbedu.dlq queue.
			"queue_arguments": {
				"x-max-priority": 5,
				"x-dead-letter-exchange": "gbedu.dlq",
				"x-dead-letter-routing-key": "gbedu.dlq",
			},
		},
		"default": {
			"exchange": "default",
			"routing_key": "default",
			"queue_arguments": {
				"x-dead-letter-exchange": "gbedu.dlq",
				"x-dead-letter-routing-key": "gbedu.dlq",
			},
		},
		"low": {"exchange": "low", "routing_key": "low"},
		# Dead-letter queue — receives rejected/expired messages from other queues
		# and messages explicitly routed here by application code.
		"gbedu.dlq": {
			"exchange": "gbedu.dlq",
			"routing_key": "gbedu.dlq",
			# No DLX on the DLQ itself — messages that fail here are lost
			# (handler has max_retries=0) so they stay in this queue for manual
			# inspection rather than looping forever.
		},
	},
	task_routes={
		# Generation tasks go to the dedicated "generation" queue so GPU workers
		# can consume it exclusively without starving other work.
		"gbedu_worker.tasks.generation.*": {"queue": "generation"},
		"gbedu_worker.tasks.audio.*": {"queue": "generation"},
		# Voice model training also needs GPU — same queue as generation
		"gbedu_worker.tasks.voice.*": {"queue": "generation"},
		# DLQ handler always stays on the DLQ queue
		"gbedu_worker.tasks.dlq.*": {"queue": "gbedu.dlq"},
		# Webhooks / payment — must be processed quickly
		"gbedu_worker.tasks.payments.*": {"queue": "high"},
		# Cheap background work
		"gbedu_worker.tasks.notifications.*": {"queue": "low"},
		"gbedu_worker.tasks.cleanup.*": {"queue": "low"},
	},

	# Default retry policy applied to all tasks unless overridden
	task_acks_on_failure_or_timeout=True,

	# Beat schedule
	beat_schedule={
		"cleanup-expired-temp-files": {
			"task": "gbedu_worker.tasks.cleanup.cleanup_expired_temp_files",
			"schedule": timedelta(hours=1),
			"options": {"queue": "low"},
		},
		"reset-daily-generation-counts": {
			"task": "gbedu_worker.tasks.cleanup.reset_daily_generation_counts",
			# crontab: midnight UTC daily
			"schedule": timedelta(days=1),
			"options": {"queue": "low"},
		},
		"retry-failed-distributions": {
			"task": "gbedu_worker.tasks.cleanup.retry_failed_distributions",
			"schedule": timedelta(hours=6),
			"options": {"queue": "low"},
		},
	},
)


# ── OpenTelemetry ──────────────────────────────────────────────────────────────

def _instrument_otel() -> None:
	configure_telemetry(
		service_name="gbedu-worker",
		otlp_endpoint=_obs_settings.otlp_endpoint,
	)
	CeleryInstrumentor().instrument()
	log.info("opentelemetry instrumented for celery worker")


# ── Celery signals ─────────────────────────────────────────────────────────────

@worker_ready.connect
def on_worker_ready(sender: object, **kwargs: object) -> None:
	_instrument_otel()
	log.info("celery worker ready", queues=["high", "default", "low"])


@worker_shutdown.connect
def on_worker_shutdown(sender: object, **kwargs: object) -> None:
	log.info("celery worker shutting down")


@celeryd_after_setup.connect
def on_worker_setup(sender: str, instance: object, **kwargs: object) -> None:
	log.info("celery worker configured", hostname=sender)


@task_prerun.connect
def on_task_prerun(
	task_id: str,
	task: object,
	args: tuple[object, ...],
	kwargs: dict[str, object],
	**extra: object,
) -> None:
	log.info(
		"task starting",
		task_id=task_id,
		task_name=getattr(task, "name", "unknown"),
	)


@task_postrun.connect
def on_task_postrun(
	task_id: str,
	task: object,
	args: tuple[object, ...],
	kwargs: dict[str, object],
	retval: object,
	state: str,
	**extra: object,
) -> None:
	log.info(
		"task finished",
		task_id=task_id,
		task_name=getattr(task, "name", "unknown"),
		state=state,
	)


@task_failure.connect
def on_task_failure(
	task_id: str,
	exception: Exception,
	traceback: object,
	einfo: object,
	**kwargs: object,
) -> None:
	log.error(
		"task failed",
		task_id=task_id,
		exc_type=type(exception).__name__,
		exc_msg=str(exception),
	)
	increment_error_count(error_code=type(exception).__name__, service="worker")


@task_retry.connect
def on_task_retry(
	request: object,
	reason: Exception,
	einfo: object,
	**kwargs: object,
) -> None:
	log.warning(
		"task retrying",
		task_id=getattr(request, "id", "unknown"),
		reason=str(reason),
	)


@task_success.connect
def on_task_success(
	sender: object,
	result: object,
	**kwargs: object,
) -> None:
	log.debug("task succeeded", task_name=getattr(sender, "name", "unknown"))


# ── Import all task modules so Celery discovers them ──────────────────────────
app.autodiscover_tasks(
	[
		"gbedu_worker.tasks.generation",
		"gbedu_worker.tasks.audio",
		"gbedu_worker.tasks.payments",
		"gbedu_worker.tasks.notifications",
		"gbedu_worker.tasks.cleanup",
		"gbedu_worker.tasks.dlq",
		"gbedu_worker.tasks.voice",
	],
	force=True,
)
