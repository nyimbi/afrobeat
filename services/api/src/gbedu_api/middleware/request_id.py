from __future__ import annotations

import uuid
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
	"""Generate a UUID4 per request and attach it to both the request state
	and the response header so callers can correlate logs to responses."""

	async def dispatch(self, request: Request, call_next: Callable) -> Response:
		request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
		request.state.request_id = request_id

		response = await call_next(request)
		response.headers[REQUEST_ID_HEADER] = request_id
		return response
