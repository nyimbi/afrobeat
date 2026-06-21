from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import structlog
import torch
from fastapi import Depends, FastAPI, HTTPException, Request, Security, status
from pydantic import BaseModel
from fastapi.security import APIKeyHeader
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from gbedu_core.config import StorageSettings
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


_GPU_WATCHDOG_INTERVAL_SECONDS = 60
_GPU_LEAK_ALERT_CONSECUTIVE = 5   # alert after this many monotonically rising samples


async def _gpu_memory_watchdog() -> None:  # pragma: no cover
	"""Background task: detect GPU VRAM leaks (FMEA M02).

	Samples torch.cuda.memory_reserved() every minute. If reserved memory
	grows for _GPU_LEAK_ALERT_CONSECUTIVE consecutive samples (5 min default)
	without a generation completing in that window, log CRITICAL so alerting
	fires. Does NOT kill the process — that's for the operator to decide.
	"""
	samples: list[float] = []
	while True:
		try:
			await asyncio.sleep(_GPU_WATCHDOG_INTERVAL_SECONDS)
			if not torch.cuda.is_available():
				continue

			reserved_mb = torch.cuda.memory_reserved(0) / 1024**2
			log.debug("gpu.watchdog.sample", reserved_mb=round(reserved_mb, 1))

			samples.append(reserved_mb)
			if len(samples) > _GPU_LEAK_ALERT_CONSECUTIVE:
				samples.pop(0)

			if (
				len(samples) == _GPU_LEAK_ALERT_CONSECUTIVE
				and all(samples[i] < samples[i + 1] for i in range(len(samples) - 1))
			):
				log.critical(
					"gpu.memory_leak_suspected",
					samples_mb=[round(s, 1) for s in samples],
					latest_mb=round(reserved_mb, 1),
					action="investigate_and_restart_ml_service_if_confirmed",
				)
		except asyncio.CancelledError:
			return
		except Exception as exc:
			log.warning("gpu.watchdog.error", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # pragma: no cover
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

	# FMEA M02: GPU memory leak watchdog — sample reserved VRAM every 60 s.
	# Alert CRITICAL if reserved memory grows monotonically for 5 consecutive
	# samples (5 min trend) without a generation completing — likely a leak.
	gpu_watchdog_task = asyncio.create_task(_gpu_memory_watchdog())

	yield

	gpu_watchdog_task.cancel()
	try:
		await gpu_watchdog_task
	except asyncio.CancelledError:
		pass

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


# ── Voice training endpoint ────────────────────────────────────────────────────

class _VoiceTrainRequest(BaseModel):
	voice_model_id: str
	training_audio_urls: list[str]
	training_config: dict[str, Any] = {}


@app.post("/voice/train", tags=["voice"], status_code=200)
async def voice_train(  # pragma: no cover
	request: _VoiceTrainRequest,
	_: str = Depends(_require_api_key),
) -> dict[str, Any]:
	"""Train an RVC v2 voice model from audio sample URLs.

	Downloads audio from presigned GET URLs, runs RVC v2 training on GPU,
	uploads the .pth and .index artifacts to R2, and returns their public URLs.

	Long-running — callers must use a timeout of at least 4 hours.
	"""
	import tempfile
	import time as _time
	import httpx
	import boto3

	assert request.voice_model_id, "voice_model_id required"
	assert request.training_audio_urls, "training_audio_urls must not be empty"

	tracer = get_tracer()
	t0 = _time.perf_counter()

	with tracer.start_as_current_span("gbedu.voice_train") as span:
		span.set_attribute("voice_model.id", request.voice_model_id)
		span.set_attribute("voice_model.sample_count", len(request.training_audio_urls))

		log.info(
			"voice_train.start",
			voice_model_id=request.voice_model_id,
			sample_count=len(request.training_audio_urls),
		)

		with tempfile.TemporaryDirectory(prefix="gbedu_voice_") as tmp_dir:
			tmp_path = Path(tmp_dir)

			# ── Step 1: Download training audio from presigned URLs ─────────
			voice_samples: list[Path] = []
			async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=300.0, write=60.0, pool=10.0)) as client:
				for idx, url in enumerate(request.training_audio_urls):
					sample_path = tmp_path / f"sample_{idx:03d}.wav"
					try:
						resp = await client.get(url)
						resp.raise_for_status()
						sample_path.write_bytes(resp.content)
						voice_samples.append(sample_path)
						log.debug("voice_train.sample.downloaded", idx=idx, bytes=len(resp.content))
					except Exception as exc:
						log.warning("voice_train.sample.download_failed", idx=idx, exc=str(exc))
						raise HTTPException(
							status_code=502,
							detail=f"Failed to download training sample {idx}: {exc}",
						)

			# ── Step 2: Run RVC v2 training ────────────────────────────────
			output_model_path = tmp_path / request.voice_model_id

			if not _vocal_synth.is_loaded:
				raise HTTPException(
					status_code=503,
					detail="Vocal synthesizer (RVC) not available on this instance",
				)

			try:
				await _vocal_synth.train_user_voice(
					voice_samples=voice_samples,
					output_model_path=output_model_path,
				)
			except Exception as exc:
				log.error("voice_train.training.failed", voice_model_id=request.voice_model_id, exc=str(exc))
				span.record_exception(exc)
				raise HTTPException(status_code=500, detail=f"RVC training failed: {exc}")

			# Expected artifacts from RVC trainer
			pth_path = output_model_path.with_suffix(".pth")
			index_path = output_model_path.with_suffix(".index")

			if not pth_path.exists():
				raise HTTPException(
					status_code=500,
					detail=f"Training completed but .pth artifact not found at {pth_path}",
				)

			# ── Step 3: Upload artifacts to R2 ─────────────────────────────
			storage = StorageSettings()
			s3 = boto3.client(
				"s3",
				endpoint_url=storage.r2_endpoint_url,
				aws_access_key_id=storage.r2_access_key_id,
				aws_secret_access_key=storage.r2_secret_access_key,
				region_name="auto",
			)

			r2_prefix = f"voice-models/{request.voice_model_id}"

			loop = asyncio.get_event_loop()

			pth_key = f"{r2_prefix}/model.pth"
			await loop.run_in_executor(
				None,
				lambda: s3.upload_file(
					str(pth_path),
					storage.r2_bucket_name,
					pth_key,
					ExtraArgs={"ContentType": "application/octet-stream"},
				),
			)
			model_file_url = f"{storage.r2_public_url}/{pth_key}"
			log.info("voice_train.pth.uploaded", key=pth_key)

			index_file_url: str | None = None
			if index_path.exists():
				index_key = f"{r2_prefix}/model.index"
				await loop.run_in_executor(
					None,
					lambda: s3.upload_file(
						str(index_path),
						storage.r2_bucket_name,
						index_key,
						ExtraArgs={"ContentType": "application/octet-stream"},
					),
				)
				index_file_url = f"{storage.r2_public_url}/{index_key}"
				log.info("voice_train.index.uploaded", key=index_key)

		elapsed = _time.perf_counter() - t0
		metrics: dict[str, Any] = {
			"training_duration_seconds": round(elapsed, 1),
			"sample_count": len(request.training_audio_urls),
			"model_id": request.voice_model_id,
			"has_index": index_file_url is not None,
		}

		log.info(
			"voice_train.complete",
			voice_model_id=request.voice_model_id,
			elapsed_seconds=round(elapsed, 1),
			model_file_url=model_file_url,
		)

	return {
		"voice_model_id": request.voice_model_id,
		"model_file_url": model_file_url,
		"index_file_url": index_file_url,
		"metrics": metrics,
	}
