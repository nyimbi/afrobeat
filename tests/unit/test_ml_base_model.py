from __future__ import annotations

"""Unit tests for gbedu_ml.models.base.BaseMusGen and helpers."""

from pathlib import Path

import pytest


def _make_concrete():
	"""Return a concrete BaseMusGen subclass with mocked generate."""
	from gbedu_ml.models.base import BaseMusGen

	class _FakeModel(BaseMusGen):
		@property
		def model_id(self) -> str:
			return "fake/model-v1"

		async def load(self) -> None:
			self._is_loaded = True

		async def generate(self, prompt: str, duration_seconds: int, **kwargs) -> Path:
			return Path("/tmp/output.wav")

	return _FakeModel()


# ── _make_circuit_breaker ─────────────────────────────────────────────────────


def test_make_circuit_breaker_returns_cb() -> None:
	from gbedu_ml.models.base import _make_circuit_breaker

	cb = _make_circuit_breaker("test/model-1")
	assert cb._failure_threshold == 3
	assert cb._recovery_timeout == 60


# ── BaseMusGen properties ─────────────────────────────────────────────────────


def test_model_id_property() -> None:
	m = _make_concrete()
	assert m.model_id == "fake/model-v1"


def test_is_loaded_false_initially() -> None:
	m = _make_concrete()
	assert m.is_loaded is False


def test_circuit_open_false_initially() -> None:
	m = _make_concrete()
	assert m.circuit_open is False


# ── health_check ──────────────────────────────────────────────────────────────


def test_health_check_structure() -> None:
	m = _make_concrete()
	h = m.health_check()
	assert h["model_id"] == "fake/model-v1"
	assert h["is_loaded"] is False
	assert h["circuit_open"] is False
	assert h["load_error"] is None
	assert h["circuit_failure_count"] == 0
	assert h["last_generation_ms"] is None


def test_health_check_after_load() -> None:
	import asyncio

	m = _make_concrete()
	asyncio.get_event_loop().run_until_complete(m.load())
	h = m.health_check()
	assert h["is_loaded"] is True


# ── unload ────────────────────────────────────────────────────────────────────


async def test_unload_sets_is_loaded_false() -> None:
	m = _make_concrete()
	await m.load()
	assert m.is_loaded is True
	await m.unload()
	assert m.is_loaded is False


# ── generate_safe ─────────────────────────────────────────────────────────────


async def test_generate_safe_success() -> None:
	m = _make_concrete()
	result = await m.generate_safe("afrobeats love song", 30)
	assert result == Path("/tmp/output.wav")
	assert m._last_generation_ms is not None
	assert m._last_generation_ms >= 0


async def test_generate_safe_assert_empty_prompt() -> None:
	m = _make_concrete()
	with pytest.raises(AssertionError):
		await m.generate_safe("", 30)


async def test_generate_safe_assert_zero_duration() -> None:
	m = _make_concrete()
	with pytest.raises(AssertionError):
		await m.generate_safe("prompt", 0)


async def test_generate_safe_circuit_open_raises() -> None:
	from circuitbreaker import CircuitBreakerError

	m = _make_concrete()
	# Force circuit open by marking it opened
	m._cb._failure_count = 10
	m._cb._state = "open"
	with pytest.raises(CircuitBreakerError):
		await m.generate_safe("prompt", 30)


async def test_generate_safe_records_timing() -> None:
	m = _make_concrete()
	await m.generate_safe("test prompt", 60)
	assert m._last_generation_ms is not None
	assert m._last_generation_ms >= 0


async def test_generate_safe_error_records_timing_and_reraises() -> None:
	from gbedu_ml.models.base import BaseMusGen

	class _FailingModel(BaseMusGen):
		@property
		def model_id(self) -> str:
			return "fail/model"

		async def load(self) -> None:
			pass

		async def generate(self, prompt: str, duration_seconds: int, **kwargs) -> Path:
			raise RuntimeError("inference failed")

	m = _FailingModel()
	with pytest.raises(RuntimeError, match="inference failed"):
		await m.generate_safe("prompt", 30)
	assert m._last_generation_ms is not None
