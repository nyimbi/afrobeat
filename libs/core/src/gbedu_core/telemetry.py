from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypeVar

import structlog
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

log = structlog.get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

_tracer_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None
_service_name: str = "gbedu"

# ── Singleton metric instruments ───────────────────────────────────────────────
_generation_duration_histogram: metrics.Histogram | None = None
_generation_count_counter: metrics.Counter | None = None
_active_jobs_gauge: metrics.ObservableGauge | None = None
_error_counter: metrics.Counter | None = None


def configure_telemetry(service_name: str, otlp_endpoint: str) -> None:  # pragma: no cover
	"""Initialise OTel tracing and metrics. Call once at process startup."""
	global _tracer_provider, _meter_provider, _service_name
	global _generation_duration_histogram, _generation_count_counter
	global _active_jobs_gauge, _error_counter

	assert service_name, "service_name must not be empty"
	_service_name = service_name

	resource = Resource(attributes={SERVICE_NAME: service_name})

	# ── Tracing ────────────────────────────────────────────────────────────────
	_tracer_provider = TracerProvider(resource=resource)
	if otlp_endpoint:
		span_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
		_tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
	trace.set_tracer_provider(_tracer_provider)

	# ── Metrics ────────────────────────────────────────────────────────────────
	readers: list[Any] = []
	if otlp_endpoint:
		metric_exporter = OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True)
		readers.append(
			PeriodicExportingMetricReader(metric_exporter, export_interval_millis=30_000)
		)

	_meter_provider = MeterProvider(resource=resource, metric_readers=readers)
	metrics.set_meter_provider(_meter_provider)

	meter = get_meter()

	_generation_duration_histogram = meter.create_histogram(
		name="gbedu.generation.duration_seconds",
		description="End-to-end audio generation latency in seconds",
		unit="s",
	)
	_generation_count_counter = meter.create_counter(
		name="gbedu.generation.count",
		description="Total number of generation requests",
		unit="1",
	)
	_error_counter = meter.create_counter(
		name="gbedu.errors.count",
		description="Total number of application errors by error_code",
		unit="1",
	)

	# SQLAlchemy auto-instrumentation (noop if engine not yet created)
	SQLAlchemyInstrumentor().instrument()

	log.info("opentelemetry configured", service=service_name, otlp_endpoint=otlp_endpoint)


def get_tracer(name: str | None = None) -> trace.Tracer:
	return trace.get_tracer(name or _service_name)


def get_meter(name: str | None = None) -> metrics.Meter:
	return metrics.get_meter(name or _service_name)


# ── Metric accessors ───────────────────────────────────────────────────────────


def record_generation_duration(seconds: float, *, sub_genre: str, model: str) -> None:
	if _generation_duration_histogram is not None:
		_generation_duration_histogram.record(
			seconds,
			attributes={"sub_genre": sub_genre, "model": model},
		)


def increment_generation_count(*, sub_genre: str, model: str, status: str) -> None:
	if _generation_count_counter is not None:
		_generation_count_counter.add(
			1,
			attributes={"sub_genre": sub_genre, "model": model, "status": status},
		)


def increment_error_count(*, error_code: str, service: str) -> None:
	if _error_counter is not None:
		_error_counter.add(
			1,
			attributes={"error_code": error_code, "service": service},
		)


# ── @traced decorator ──────────────────────────────────────────────────────────


def traced(span_name: str | None = None, *, record_exception: bool = True) -> Callable[[F], F]:
	"""Decorator that wraps a sync or async function in an OTel span.

	Works with both plain functions and coroutine functions.
	"""

	def decorator(fn: F) -> F:
		name = span_name or f"{fn.__module__}.{fn.__qualname__}"

		if _is_coroutine_function(fn):

			@functools.wraps(fn)
			async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
				tracer = get_tracer()
				with tracer.start_as_current_span(name) as span:
					try:
						return await fn(*args, **kwargs)
					except Exception as exc:
						if record_exception:
							span.record_exception(exc)
							span.set_status(trace.StatusCode.ERROR, str(exc))
						raise

			return async_wrapper  # type: ignore[return-value]

		@functools.wraps(fn)
		def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
			tracer = get_tracer()
			with tracer.start_as_current_span(name) as span:
				try:
					return fn(*args, **kwargs)
				except Exception as exc:
					if record_exception:
						span.record_exception(exc)
						span.set_status(trace.StatusCode.ERROR, str(exc))
					raise

		return sync_wrapper  # type: ignore[return-value]

	return decorator


def _is_coroutine_function(fn: Callable[..., Any]) -> bool:
	import inspect

	return inspect.iscoroutinefunction(fn)
