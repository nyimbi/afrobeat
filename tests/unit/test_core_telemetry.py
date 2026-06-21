from __future__ import annotations

from collections.abc import Callable
from typing import Any, Self, cast

import pytest
from gbedu_core import telemetry


class _FakeInstrument:
	def __init__(self) -> None:
		self.calls: list[tuple[float, dict[str, str]]] = []

	def record(self, value: float, *, attributes: dict[str, str]) -> None:
		self.calls.append((value, attributes))

	def add(self, value: float, *, attributes: dict[str, str]) -> None:
		self.calls.append((value, attributes))


class _FakeSpan:
	def __init__(self) -> None:
		self.exceptions: list[Exception] = []
		self.statuses: list[tuple[Any, str]] = []

	def __enter__(self) -> Self:
		return self

	def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
		return None

	def record_exception(self, exc: Exception) -> None:
		self.exceptions.append(exc)

	def set_status(self, status: Any, description: str) -> None:
		self.statuses.append((status, description))


class _FakeTracer:
	def __init__(self) -> None:
		self.span_names: list[str] = []
		self.spans: list[_FakeSpan] = []

	def start_as_current_span(self, name: str) -> _FakeSpan:
		self.span_names.append(name)
		span = _FakeSpan()
		self.spans.append(span)
		return span


def _telemetry_module() -> Any:
	return cast(Any, telemetry)


def _fake_get_tracer(fake_tracer: _FakeTracer) -> Callable[[str | None], _FakeTracer]:
	def get_tracer(name: str | None = None) -> _FakeTracer:
		return fake_tracer

	return get_tracer


def test_metric_helpers_noop_before_configuration() -> None:
	module = _telemetry_module()
	module._generation_duration_histogram = None
	module._generation_count_counter = None
	module._error_counter = None

	telemetry.record_generation_duration(1.5, sub_genre="afrobeats", model="ace")
	telemetry.increment_generation_count(sub_genre="afrobeats", model="ace", status="success")
	telemetry.increment_error_count(error_code="E_TEST", service="unit")


def test_metric_helpers_record_attributes() -> None:
	module = _telemetry_module()
	duration = _FakeInstrument()
	generation_count = _FakeInstrument()
	error_count = _FakeInstrument()
	module._generation_duration_histogram = duration
	module._generation_count_counter = generation_count
	module._error_counter = error_count

	telemetry.record_generation_duration(2.25, sub_genre="amapiano", model="stable")
	telemetry.increment_generation_count(sub_genre="amapiano", model="stable", status="queued")
	telemetry.increment_error_count(error_code="E_TIMEOUT", service="ml")

	assert duration.calls == [(2.25, {"sub_genre": "amapiano", "model": "stable"})]
	assert generation_count.calls == [
		(1, {"sub_genre": "amapiano", "model": "stable", "status": "queued"})
	]
	assert error_count.calls == [(1, {"error_code": "E_TIMEOUT", "service": "ml"})]


def test_traced_wraps_sync_function(monkeypatch: pytest.MonkeyPatch) -> None:
	fake_tracer = _FakeTracer()
	monkeypatch.setattr(telemetry, "get_tracer", _fake_get_tracer(fake_tracer))

	@telemetry.traced("sync-span")
	def add_one(value: int) -> int:
		return value + 1

	assert add_one(4) == 5
	assert fake_tracer.span_names == ["sync-span"]


async def test_traced_wraps_async_function(monkeypatch: pytest.MonkeyPatch) -> None:
	fake_tracer = _FakeTracer()
	monkeypatch.setattr(telemetry, "get_tracer", _fake_get_tracer(fake_tracer))

	@telemetry.traced("async-span")
	async def add_one(value: int) -> int:
		return value + 1

	assert await add_one(6) == 7
	assert fake_tracer.span_names == ["async-span"]


def test_traced_records_sync_exception(monkeypatch: pytest.MonkeyPatch) -> None:
	fake_tracer = _FakeTracer()
	monkeypatch.setattr(telemetry, "get_tracer", _fake_get_tracer(fake_tracer))

	@telemetry.traced("failing-sync")
	def fail() -> None:
		raise ValueError("boom")

	with pytest.raises(ValueError, match="boom"):
		fail()

	assert len(fake_tracer.spans[0].exceptions) == 1
	assert fake_tracer.spans[0].statuses


async def test_traced_can_skip_async_exception_recording(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	fake_tracer = _FakeTracer()
	monkeypatch.setattr(telemetry, "get_tracer", _fake_get_tracer(fake_tracer))

	@telemetry.traced("failing-async", record_exception=False)
	async def fail() -> None:
		raise RuntimeError("skip")

	with pytest.raises(RuntimeError, match="skip"):
		await fail()

	assert fake_tracer.spans[0].exceptions == []
	assert fake_tracer.spans[0].statuses == []
