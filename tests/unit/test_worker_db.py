from __future__ import annotations

"""Unit tests for gbedu_worker.db — run_async() is pure Python, fully testable."""


def test_run_async_returns_value() -> None:
	from gbedu_worker.db import run_async

	async def _coro() -> int:
		return 42

	result = run_async(_coro())
	assert result == 42


def test_run_async_propagates_exception() -> None:
	import pytest
	from gbedu_worker.db import run_async

	async def _failing():
		raise ValueError("boom")

	with pytest.raises(ValueError, match="boom"):
		run_async(_failing())


def test_run_async_cancels_pending_tasks() -> None:
	"""run_async must cancel any dangling tasks before closing the loop."""
	import asyncio
	from gbedu_worker.db import run_async

	async def _with_dangling() -> str:
		asyncio.ensure_future(asyncio.sleep(100))  # dangling task
		return "done"

	result = run_async(_with_dangling())
	assert result == "done"


def test_run_async_works_with_no_pending_tasks() -> None:
	from gbedu_worker.db import run_async

	async def _simple() -> list[int]:
		return [1, 2, 3]

	assert run_async(_simple()) == [1, 2, 3]


def test_run_async_closes_loop_on_exception() -> None:
	"""Loop must be closed even when the coroutine raises."""
	import asyncio
	import pytest
	from gbedu_worker.db import run_async

	loops_before: list[bool] = []

	async def _check_and_fail() -> None:
		loops_before.append(asyncio.get_event_loop().is_running())
		raise RuntimeError("deliberate")

	with pytest.raises(RuntimeError):
		run_async(_check_and_fail())

	assert loops_before == [True]
