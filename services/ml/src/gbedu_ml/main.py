from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import structlog
import torch
from fastapi import Depends, FastAPI, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from gbedu_core.errors import GenerationError
from gbedu_core.schemas import GenerationRequest
from gbedu_core.telemetry import configure_telemetry, get_tracer, record_generation_duration, increment_generation_count, increment_error_count
from gbedu_ml.config import settings
from gbedu_ml.inference.lyric_generator import LyricGenerator
from gbedu_ml.inference.music_generator import MusicGenerator, MusicGenerationResult
from gbedu_ml.inference.vocal_synthesizer import VocalSynthesizer
from gbedu_ml.models.ace_step import AceStepModel
from gbedu_ml.models.stable_audio import StableAudioModel
from gbedu_ml.models.yue import YuEModel
from gbedu_ml.pipeline import GenerationPipeline, GenerationPipelineResult

log = structlog.get_logger(__name__)

# ── Globals populated during lifespan ─────────────────────────────────────────
_ace_step: AceStepModel
_stable_audio: StableAudioModel
_yue: YuEModel
_lyric_gen: LyricGenerator
_vocal_synth: VocalSynthesizer
_music_gen: MusicGenerator
_pipeline: GenerationPipeline
_generation_semaphore: asyncio.Semaphore

_startup_time: float = 0.0
_model_load_errors: dict[str, str] = {}

# ── API key auth ───────────────────────────────────────────────────────────────
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


def _require_api_key(api_key: str = Security(_api_key_header)) -> str:
	if api_key != settings.API_KEY:
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")
	return api_key


# ── Lifespan ───────────────────────────────────────────────────────────────────

async def _load_model(name: str, model: Any) -> None:
	"""Load a single model, logging a warning (not crashing) on failure."""
	try:
		await model.load()
		log.info("model.loaded", name=name)
	except Exception as exc:
		_model_load_errors[name] = str(exc)
		log.warning("model.load.failed", name=name, error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
	global _ace_step, _stable_audio, _yue
	global _lyric_gen, _vocal_synth, _music_gen, _pipeline
	global _generation_semaphore, _startup_time

	t0 = time.perf_counter()
	log.info("gbedu_ml.startup.begin")

	configure_telemetry(service_name="gbedu-ml", otlp_endpoint=settings.OTLP_ENDPOINT)

	_generation_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_GENERATIONS)

	# Instantiate models
	_ace_step = AceStepModel()
	_stable_audio = StableAudioModel()
	_yue = YuEModel()
	_lyric_gen = LyricGenerator()
	_vocal_synth = VocalSynthesizer()

	# Load all models concurrently — failures are non-fatal (degraded mode)
	await asyncio.gather(
		_load_model("ace_step", _ace_step),
		_load_model("stable_audio", _stable_audio),
		_load_model("yue", _yue),
		_load_model("lyric_gen", _lyric_gen),
		_load_model("vocal_synth", _vocal_synth),
	)

	# GPU warm-up — run a short dummy generation if at least one audio model loaded
	for m in (_ace_step, _stable_audio, _yue):
		if m.is_loaded:
			try:
				log.info("model.warmup.start", model=m.model_id)
				await m.generate_safe(prompt="warm-up afrobeats 4 bars", duration_seconds=4)
				log.info("model.warmup.done", model=m.model_id)
			except Exception as exc:
				log.warning("model.warmup.failed", model=m.model_id, error=str(exc))
			break  # Only warm up the primary model

	_music_gen = MusicGenerator(_ace_step, _stable_audio, _yue)
	_pipeline = GenerationPipeline(_music_gen, _lyric_gen, _vocal_synth)

	_startup_time = time.perf_counter() - t0
	log.info("gbedu_ml.startup.done", elapsed_seconds=round(_startup_time, 2))

	yield

	# ── Shutdown ───────────────────────────────────────────────────────────────
	log.info("gbedu_ml.shutdown.begin")
	await asyncio.gather(
		_ace_step.unload(),
		_stable_audio.unload(),
		_yue.unload(),
		_lyric_gen.unload(),
	)
	log.info("gbedu_ml.shutdown.done")


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
	title="Gbẹdu ML Inference",
	description="Internal ML inference service for Afrobeats generation",
	version="0.1.0",
	lifespan=lifespan,
	docs_url="/docs",
	redoc_url=None,
)

FastAPIInstrumentor.instrument_app(app)


# ── Health / readiness ─────────────────────────────────────────────────────────

@app.get("/health", tags=["ops"])
async def health() -> dict[str, Any]:
	gpu_info: dict[str, Any] = {}
	if torch.cuda.is_available():
		gpu_info = {
			"device": torch.cuda.get_device_name(0),
			"memory_allocated_mb": round(torch.cuda.memory_allocated(0) / 1024**2, 1),
			"memory_reserved_mb": round(torch.cuda.memory_reserved(0) / 1024**2, 1),
			"memory_total_mb": round(torch.cuda.get_device_properties(0).total_memory / 1024**2, 1),
		}

	return {
		"status": "ok",
		"startup_seconds": round(_startup_time, 2),
		"load_errors": _model_load_errors,
		"gpu": gpu_info,
		"models": {
			"ace_step": _ace_step.health_check(),
			"stable_audio": _stable_audio.health_check(),
			"yue": _yue.health_check(),
			"lyric_gen": {
				"is_loaded": _lyric_gen.is_loaded,
			},
			"vocal_synth": {
				"is_loaded": _vocal_synth.is_loaded,
			},
		},
	}


@app.get("/ready", tags=["ops"])
async def ready() -> dict[str, str]:
	"""K8s readiness probe — 200 iff at least one audio model is loaded."""
	if any(m.is_loaded for m in (_ace_step, _stable_audio, _yue)):
		return {"status": "ready"}
	raise HTTPException(status_code=503, detail="No audio models loaded")


@app.get("/models", tags=["ops"])
async def list_models(_: str = Depends(_require_api_key)) -> dict[str, Any]:
	return {
		"models": [
			_ace_step.health_check(),
			_stable_audio.health_check(),
			_yue.health_check(),
		],
		"lyric_generator": {"is_loaded": _lyric_gen.is_loaded},
		"vocal_synthesizer": {"is_loaded": _vocal_synth.is_loaded},
	}


# ── Generation endpoint ────────────────────────────────────────────────────────

class _GenerateResponse(GenerationPipelineResult):
	pass


@app.post(
	"/generate",
	response_model=None,
	tags=["generation"],
	status_code=200,
)
async def generate(
	request: GenerationRequest,
	http_request: Request,
	_: str = Depends(_require_api_key),
) -> dict[str, Any]:
	"""Run the full Afrobeats generation pipeline.

	Accepts a GenerationRequest and returns audio paths + metadata.
	Enforces MAX_CONCURRENT_GENERATIONS via a semaphore.
	"""
	from gbedu_core._uuid7 import uuid7str

	job_id = uuid7str()
	tracer = get_tracer()

	async with _generation_semaphore:
		t0 = time.perf_counter()

		with tracer.start_as_current_span("gbedu.generate") as span:
			span.set_attribute("job.id", job_id)
			span.set_attribute("request.sub_genre", request.sub_genre.value)
			span.set_attribute("request.language", request.language.value)
			span.set_attribute("request.duration_seconds", request.duration_seconds)

			try:
				result = await _pipeline.run(request, job_id)
			except GenerationError as exc:
				span.record_exception(exc)
				span.set_status(trace.StatusCode.ERROR, str(exc))
				increment_error_count(error_code=exc.error_code, service="gbedu-ml")
				log.error("generate.failed", job_id=job_id, error=str(exc), details=exc.details)
				raise HTTPException(status_code=502, detail=exc.to_dict())
			except Exception as exc:
				span.record_exception(exc)
				span.set_status(trace.StatusCode.ERROR, str(exc))
				increment_error_count(error_code="UNEXPECTED", service="gbedu-ml")
				log.exception("generate.unexpected_error", job_id=job_id)
				raise HTTPException(status_code=500, detail={"error_code": "UNEXPECTED", "message": str(exc)})

			elapsed = time.perf_counter() - t0
			record_generation_duration(
				elapsed,
				sub_genre=request.sub_genre.value,
				model=result.music_result.model_used,
			)
			increment_generation_count(
				sub_genre=request.sub_genre.value,
				model=result.music_result.model_used,
				status="success",
			)
			span.set_attribute("model.used", result.music_result.model_used)

	return {
		"job_id": result.job_id,
		"final_audio_path": str(result.final_audio_path),
		"instrumental_path": str(result.instrumental_path),
		"vocal_path": str(result.vocal_path) if result.vocal_path else None,
		"lyrics": result.lyrics_result.model_dump() if result.lyrics_result else None,
		"model_used": result.music_result.model_used,
		"duration_seconds": result.duration_seconds,
		"elapsed_seconds": result.elapsed_seconds,
		"metadata": result.metadata,
	}
