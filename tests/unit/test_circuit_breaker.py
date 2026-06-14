from __future__ import annotations

"""Unit tests for circuit breaker behaviour.

Uses the real ``circuitbreaker`` library — no mocks.  Each test gets a fresh
``CircuitBreaker`` instance so state never bleeds between tests.

The MLServiceClient circuit breaker config is also verified against the values
declared in ``MLSettings``.
"""

import asyncio
import time
from typing import Any

import pytest
from circuitbreaker import CircuitBreaker, CircuitBreakerError

from gbedu_core.config import MLSettings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _Sentinel(Exception):
	"""Dummy exception used as the expected_exception for test circuits."""


def _make_circuit(
	failure_threshold: int = 3,
	recovery_timeout: int = 1,
	name: str | None = None,
) -> CircuitBreaker:
	"""Return a fresh CircuitBreaker with the given parameters.

	Using a unique name per call prevents the library's global registry from
	returning a previously-opened circuit when tests share the same name.
	"""
	import uuid
	cb_name = name or f"test_cb_{uuid.uuid4().hex[:8]}"
	return CircuitBreaker(
		failure_threshold=failure_threshold,
		recovery_timeout=recovery_timeout,
		expected_exception=_Sentinel,
		name=cb_name,
	)


def _failing_call(cb: CircuitBreaker) -> None:
	"""Invoke the circuit breaker with a function that always raises _Sentinel."""
	@cb
	def _inner() -> None:
		raise _Sentinel("deliberate failure")

	_inner()


def _succeeding_call(cb: CircuitBreaker) -> str:
	"""Invoke the circuit breaker with a function that always succeeds."""
	@cb
	def _inner() -> str:
		return "ok"

	return _inner()


# ---------------------------------------------------------------------------
# 1. Circuit opens after failure_threshold consecutive failures
# ---------------------------------------------------------------------------

def test_circuit_opens_after_threshold() -> None:
	"""Circuit must transition CLOSED → OPEN after exactly failure_threshold failures."""
	threshold = 3
	cb = _make_circuit(failure_threshold=threshold)

	assert cb.closed, "circuit must start CLOSED"

	for i in range(threshold - 1):
		with pytest.raises(_Sentinel):
			_failing_call(cb)
		assert cb.closed, f"circuit must still be CLOSED after {i + 1} failures"

	# Final failure that crosses the threshold
	with pytest.raises(_Sentinel):
		_failing_call(cb)

	assert cb.opened, "circuit must be OPEN after reaching failure threshold"


# ---------------------------------------------------------------------------
# 2. Circuit rejects calls when open (raises CircuitBreakerError immediately)
# ---------------------------------------------------------------------------

def test_open_circuit_rejects_calls() -> None:
	"""Once open the circuit must raise CircuitBreakerError without calling the wrapped fn."""
	threshold = 2
	cb = _make_circuit(failure_threshold=threshold)

	# Trip the circuit
	for _ in range(threshold):
		with pytest.raises(_Sentinel):
			_failing_call(cb)

	assert cb.opened

	# Subsequent calls must be rejected before even reaching the wrapped function
	call_count = 0

	@cb
	def _tracked() -> None:
		nonlocal call_count
		call_count += 1

	with pytest.raises(CircuitBreakerError):
		_tracked()

	assert call_count == 0, "wrapped function must NOT be called while circuit is open"


# ---------------------------------------------------------------------------
# 3. Circuit rejects multiple consecutive calls when open
# ---------------------------------------------------------------------------

def test_open_circuit_rejects_all_subsequent_calls() -> None:
	"""Every call while the circuit is open must raise CircuitBreakerError."""
	cb = _make_circuit(failure_threshold=2)

	for _ in range(2):
		with pytest.raises(_Sentinel):
			_failing_call(cb)

	assert cb.opened

	for _ in range(5):
		with pytest.raises(CircuitBreakerError):
			_failing_call(cb)


# ---------------------------------------------------------------------------
# 4. Circuit recovers to HALF-OPEN after recovery_timeout, then CLOSED on success
# ---------------------------------------------------------------------------

def test_circuit_recovers_after_timeout() -> None:
	"""Circuit must allow a probe call after recovery_timeout and close on success."""
	threshold = 2
	recovery_timeout = 1  # second — keep tests fast
	cb = _make_circuit(failure_threshold=threshold, recovery_timeout=recovery_timeout)

	# Trip it
	for _ in range(threshold):
		with pytest.raises(_Sentinel):
			_failing_call(cb)

	assert cb.opened

	# Wait for recovery window to elapse
	time.sleep(recovery_timeout + 0.1)

	# The library transitions to HALF-OPEN on the next access; a successful
	# call closes the circuit.
	result = _succeeding_call(cb)
	assert result == "ok"
	assert cb.closed, "circuit must be CLOSED after a successful probe call"


# ---------------------------------------------------------------------------
# 5. Circuit re-opens if probe fails during HALF-OPEN
# ---------------------------------------------------------------------------

def test_circuit_reopens_on_failed_probe() -> None:
	"""A failed probe during HALF-OPEN must re-open the circuit."""
	threshold = 2
	recovery_timeout = 1
	cb = _make_circuit(failure_threshold=threshold, recovery_timeout=recovery_timeout)

	for _ in range(threshold):
		with pytest.raises(_Sentinel):
			_failing_call(cb)

	assert cb.opened
	time.sleep(recovery_timeout + 0.1)

	# Probe call fails — circuit must re-open
	with pytest.raises(_Sentinel):
		_failing_call(cb)

	assert cb.opened, "circuit must re-open after a failed HALF-OPEN probe"


# ---------------------------------------------------------------------------
# 6. MLServiceClient circuit breaker config matches MLSettings
# ---------------------------------------------------------------------------

def test_ml_client_circuit_config_matches_settings() -> None:
	"""The CircuitBreaker wired into MLServiceClient must use the values from MLSettings."""
	settings = MLSettings()

	# Build the client with default settings and inspect its circuit breaker.
	# We don't need a real HTTP connection — we're only checking __init__ state.
	import unittest.mock as mock

	# Patch httpx.AsyncClient so no real socket is opened
	with mock.patch("httpx.AsyncClient.__init__", return_value=None):
		from gbedu_api.services.ml_client import MLServiceClient

		client = MLServiceClient.__new__(MLServiceClient)
		# Call __init__ with a settings object that has a non-empty service_url
		patched_settings = MLSettings(
			ML_SERVICE_URL="http://localhost:8001",
			ML_SERVICE_API_KEY="test-key",
		)

		with mock.patch("httpx.AsyncClient", return_value=mock.MagicMock()):
			client.__init__(patched_settings)

	cb: CircuitBreaker = client._circuit  # type: ignore[attr-defined]

	assert cb._failure_threshold == patched_settings.circuit_failure_threshold, (
		f"expected failure_threshold={patched_settings.circuit_failure_threshold}, "
		f"got {cb._failure_threshold}"
	)
	assert cb._recovery_timeout == patched_settings.circuit_recovery_timeout, (
		f"expected recovery_timeout={patched_settings.circuit_recovery_timeout}, "
		f"got {cb._recovery_timeout}"
	)


# ---------------------------------------------------------------------------
# 7. Async-wrapped circuit breaker works correctly
# ---------------------------------------------------------------------------

async def test_async_circuit_breaker_opens_and_rejects() -> None:
	"""Verify circuit breaker integrates correctly with async call sites."""
	threshold = 3
	cb = _make_circuit(failure_threshold=threshold)

	async def _failing_async() -> None:
		@cb
		def _inner() -> None:
			raise _Sentinel("async failure")
		_inner()

	# Trip the circuit
	for _ in range(threshold):
		with pytest.raises(_Sentinel):
			await _failing_async()

	assert cb.opened

	# Now open circuit must reject
	with pytest.raises(CircuitBreakerError):
		await _failing_async()


# ---------------------------------------------------------------------------
# 8. Independent circuits do not share state
# ---------------------------------------------------------------------------

def test_independent_circuits_have_isolated_state() -> None:
	"""Two separate CircuitBreaker instances must not share failure counts."""
	cb_a = _make_circuit(failure_threshold=2, name="isolated_a")
	cb_b = _make_circuit(failure_threshold=2, name="isolated_b")

	# Trip cb_a
	for _ in range(2):
		with pytest.raises(_Sentinel):
			_failing_call(cb_a)

	assert cb_a.opened
	# cb_b must still be closed
	assert cb_b.closed, "cb_b must not be affected by failures in cb_a"
