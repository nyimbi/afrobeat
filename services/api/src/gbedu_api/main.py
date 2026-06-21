from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from redis.asyncio import Redis
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from gbedu_api.config import API_VERSION, get_settings
from gbedu_api.deps import limiter, set_ml_client, set_redis, set_storage_client
from gbedu_api.middleware.logging import StructlogMiddleware
from gbedu_api.middleware.request_id import RequestIDMiddleware
from gbedu_api.routers import auth, contact, generations, health, marketplace, payments, tracks, users, voice_models
from gbedu_core.config import get_settings as core_settings
from gbedu_core.db import get_engine, init_db
from gbedu_core.errors import GbeduError
from gbedu_core.telemetry import configure_telemetry

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # pragma: no cover
	settings = get_settings()

	# ── Telemetry / logging ────────────────────────────────────────────────────
	configure_telemetry(
		service_name="gbedu-api",
		otlp_endpoint=settings.observability.otlp_endpoint,
	)

	# ── Database ───────────────────────────────────────────────────────────────
	engine = get_engine(settings.database)
	init_db(engine)
	log.info("startup.database_ready")

	# ── Redis ──────────────────────────────────────────────────────────────────
	# FMEA A02: never crash on Redis unavailability — start in degraded mode so
	# the API can still serve requests and retry Redis on the next operation.
	# asyncio-redis reconnects automatically; rate-limiting falls back to in-process.
	redis = Redis.from_url(settings.redis.url, decode_responses=False)
	try:
		await redis.ping()
		log.info("startup.redis_ready")
	except Exception as exc:
		log.critical(
			"startup.redis_unavailable",
			error=str(exc),
			action="degraded_mode_rate_limiting_in_process_only",
		)
	set_redis(redis)

	# ── Storage client ─────────────────────────────────────────────────────────
	from gbedu_api.services.storage_service import LocalStorageClient, StorageClient
	if settings.storage.r2_account_id:
		storage: StorageClient | LocalStorageClient = StorageClient(settings.storage)
	else:
		assert not settings.is_production, "R2_ACCOUNT_ID is required in production"
		storage = LocalStorageClient()
	set_storage_client(storage)
	log.info("startup.storage_ready")

	# ── ML service client ──────────────────────────────────────────────────────
	from gbedu_api.services.ml_client import MLServiceClient
	ml_client = MLServiceClient(settings.ml)
	set_ml_client(ml_client)
	log.info("startup.ml_client_ready")

	log.info("startup.complete", version=API_VERSION, environment=settings.environment)

	yield

	# ── Shutdown ───────────────────────────────────────────────────────────────
	await ml_client.close()
	await redis.aclose()
	await engine.dispose()
	log.info("shutdown.complete")


def create_app() -> FastAPI:
	settings = get_settings()

	app = FastAPI(
		title="Gbẹdu API",
		description="AI-powered Afrobeats music generation platform",
		version=API_VERSION,
		docs_url=None if settings.is_production else "/docs",
		redoc_url=None if settings.is_production else "/redoc",
		openapi_url=None if settings.is_production else "/openapi.json",
		lifespan=lifespan,
	)

	# ── Rate limiter state ─────────────────────────────────────────────────────
	app.state.limiter = limiter
	app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

	# ── Middleware (applied in reverse LIFO order — last added = outermost) ────
	# Outermost → innermost at request time:
	# TrustedHost → HTTPS → RequestID → Structlog → OTel → CORS → SlowAPI → GZip

	app.add_middleware(GZipMiddleware, minimum_size=1000)
	app.add_middleware(SlowAPIMiddleware)
	app.add_middleware(
		CORSMiddleware,
		allow_origins=settings.allowed_origins_list,
		allow_credentials=True,
		allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
		allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Request-ID", "Cache-Control"],
	)

	# OpenTelemetry ASGI middleware is applied via instrumentor after app creation
	app.add_middleware(StructlogMiddleware)
	app.add_middleware(RequestIDMiddleware)

	if settings.is_production:
		from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
		app.add_middleware(HTTPSRedirectMiddleware)

	app.add_middleware(
		TrustedHostMiddleware,
		allowed_hosts=["*"] if not settings.is_production else [
			"api.gbedu.io",
			"*.gbedu.io",
		],
	)

	# ── Error handlers ─────────────────────────────────────────────────────────

	@app.exception_handler(GbeduError)
	async def gbedu_error_handler(request: Request, exc: GbeduError) -> JSONResponse:
		request_id = getattr(request.state, "request_id", None)
		return JSONResponse(
			status_code=exc.http_status,
			content={
				"error_code": exc.error_code,
				"message": exc.message,
				"details": exc.details,
				"request_id": request_id,
			},
		)

	@app.exception_handler(Exception)
	async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
		request_id = getattr(request.state, "request_id", None)
		log.error(
			"unhandled_exception",
			exc_type=type(exc).__name__,
			request_id=request_id,
			path=request.url.path,
		)
		return JSONResponse(
			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			content={
				"error_code": "INTERNAL_ERROR",
				"message": "An unexpected error occurred",
				"request_id": request_id,
			},
		)

	# ── Routers ────────────────────────────────────────────────────────────────
	_prefix = "/api/v1"

	app.include_router(health.router, prefix=_prefix)
	app.include_router(auth.router, prefix=_prefix)
	app.include_router(users.router, prefix=_prefix)
	app.include_router(generations.router, prefix=_prefix)
	app.include_router(tracks.router, prefix=_prefix)
	app.include_router(payments.router, prefix=_prefix)
	app.include_router(marketplace.router, prefix=_prefix)
	app.include_router(voice_models.router, prefix=_prefix)
	app.include_router(contact.router, prefix=_prefix)

	# Instrument after routers are registered so spans include route templates.
	# Patch _get_route_details to guard against _IncludedRouter objects that lack
	# a .path attribute (opentelemetry-instrumentation-fastapi <= 0.48b0 bug).
	import opentelemetry.instrumentation.fastapi as _otel_fastapi
	_orig_get_route = _otel_fastapi._get_route_details

	def _safe_get_route_details(scope):  # type: ignore[no-untyped-def]
		try:
			return _orig_get_route(scope)
		except AttributeError:
			return None, {}

	_otel_fastapi._get_route_details = _safe_get_route_details
	FastAPIInstrumentor.instrument_app(app)

	return app


# Entry point for uvicorn: `uvicorn gbedu_api.main:app`
app = create_app()
