from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = structlog.get_logger(__name__)


class StructlogMiddleware(BaseHTTPMiddleware):
	"""Log every HTTP request with method, path, status, duration, request_id,
	and user_id when authenticated. Binds request_id into the structlog context
	so all downstream log calls in the same request carry it automatically."""

	async def dispatch(
		self,
		request: Request,
		call_next: Callable[[Request], Awaitable[Response]],
	) -> Response:
		request_id = getattr(request.state, "request_id", None)

		structlog.contextvars.clear_contextvars()
		structlog.contextvars.bind_contextvars(request_id=request_id)

		start = time.perf_counter()
		try:
			response = await call_next(request)
		except Exception as exc:
			duration_ms = (time.perf_counter() - start) * 1000
			log.error(
				"request.unhandled_exception",
				method=request.method,
				path=request.url.path,
				duration_ms=round(duration_ms, 2),
				exc_type=type(exc).__name__,
			)
			raise

		duration_ms = (time.perf_counter() - start) * 1000

		user_id = getattr(request.state, "user_id", None)

		log.info(
			"request.complete",
			method=request.method,
			path=request.url.path,
			status=response.status_code,
			duration_ms=round(duration_ms, 2),
			user_id=user_id,
		)

		return response
