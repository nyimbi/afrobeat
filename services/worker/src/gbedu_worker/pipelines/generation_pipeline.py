from __future__ import annotations

"""GenerationPipelineOrchestrator — stateful business logic for audio generation.

Called exclusively by tasks/generation.py. Manages the full state machine:

    queued → ml_generating → audio_processing → uploading → complete
                                    ↓ (any stage)
                                  failed

Each method is idempotent: it checks the current DB state before acting so
retried Celery tasks converge to the correct final state.

Progress events are published to Redis pub/sub on channel `job:{job_id}` as
JSON objects compatible with the SSE stream in the API service.
"""

import asyncio
import base64
import json
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import structlog
from opentelemetry import trace
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
	AsyncRetrying,
	retry_if_exception_type,
	stop_after_attempt,
	wait_exponential,
)

from gbedu_core._uuid7 import uuid7str
from gbedu_core.config import MLSettings, RedisSettings, StorageSettings
from gbedu_core.models.job import GenerationJob, JobStatus, TERMINAL_JOB_STATUSES
from gbedu_core.models.track import Track, TrackStatus
from gbedu_core.telemetry import (
	get_tracer,
	increment_error_count,
	increment_generation_count,
	record_generation_duration,
)
from gbedu_worker.exceptions import MLServiceError, UploadError

log = structlog.get_logger(__name__)
tracer = get_tracer(__name__)

_ml_settings = MLSettings()
_redis_settings = RedisSettings()
_storage_settings = StorageSettings()

# Redis channel prefix for SSE progress events
_JOB_CHANNEL_PREFIX = "job:"

# TTL for idempotency keys (24 h in seconds)
_IDEMPOTENCY_TTL = 86_400

# Redis checkpoint TTL for pipeline stage results (2 h — longer than max retry window)
_CHECKPOINT_TTL = 7_200
_CHECKPOINT_PREFIX = "pipeline_ckpt:"

# Per-stage wall-clock deadlines (FMEA M05).
# ml_generate covers 3 tenacity retries × 300 s each + 2 × 270 s backoff ≈ 1440 s.
# Values are conservative upper bounds; a hung stage is forced to fail instead of
# consuming a Celery slot indefinitely.
_STAGE_TIMEOUT_SECONDS: dict[str, int] = {
	"ml_generate":    1500,   # 25 min — covers worst-case tenacity retry chain
	"audio_process":  300,    # 5 min
	"upload":         180,    # 3 min
	"create_track":   60,     # 1 min
	"complete":       30,     # 30 s
}


class GenerationPipelineOrchestrator:
	"""Drives a single GenerationJob through its full lifecycle.

	Instantiate once per task invocation; not thread-safe across instances.
	"""

	def __init__(self, job_id: str, session: AsyncSession) -> None:
		assert job_id, "job_id must not be empty"
		self._job_id = job_id
		self._session = session
		self._job: GenerationJob | None = None
		self._log = log.bind(job_id=job_id)

	# ── Public entry point ─────────────────────────────────────────────────────

	async def run(self) -> dict[str, Any]:
		"""Execute the full generation pipeline. Returns a result dict."""
		start_ts = time.monotonic()

		with tracer.start_as_current_span("generation_pipeline.run") as span:
			span.set_attribute("job.id", self._job_id)

			job = await self._load_job()
			if job is None:
				self._log.warning("job not found — skipping (already deleted)")
				return {"status": "skipped", "reason": "not_found"}

			if job.is_terminal:
				self._log.info(
					"job already in terminal state — idempotent skip",
					status=job.status.value,
				)
				return {"status": "skipped", "reason": "already_terminal", "job_status": job.status.value}

			try:
				ml_result = await asyncio.wait_for(
					self._stage_ml_generate(job),
					timeout=_STAGE_TIMEOUT_SECONDS["ml_generate"],
				)
				processed = await asyncio.wait_for(
					self._stage_audio_process(job, ml_result),
					timeout=_STAGE_TIMEOUT_SECONDS["audio_process"],
				)
				urls = await asyncio.wait_for(
					self._stage_upload(job, processed),
					timeout=_STAGE_TIMEOUT_SECONDS["upload"],
				)
				track = await asyncio.wait_for(
					self._stage_create_track(job, ml_result, urls),
					timeout=_STAGE_TIMEOUT_SECONDS["create_track"],
				)
				await asyncio.wait_for(
					self._stage_complete(job, track, ml_result),
					timeout=_STAGE_TIMEOUT_SECONDS["complete"],
				)

				elapsed = time.monotonic() - start_ts
				record_generation_duration(
					elapsed,
					sub_genre=job.metadata_.get("sub_genre", "unknown"),
					model=ml_result.get("model_used", "unknown"),
				)
				increment_generation_count(
					sub_genre=job.metadata_.get("sub_genre", "unknown"),
					model=ml_result.get("model_used", "unknown"),
					status="success",
				)
				span.set_attribute("job.duration_seconds", elapsed)

				return {
					"status": "complete",
					"job_id": self._job_id,
					"track_id": track.id,
					"duration_seconds": elapsed,
				}

			except Exception as exc:
				await self._handle_failure(job, exc)
				increment_generation_count(
					sub_genre=job.metadata_.get("sub_genre", "unknown"),
					model="unknown",
					status="failed",
				)
				increment_error_count(error_code=type(exc).__name__, service="worker.generation")
				span.record_exception(exc)
				span.set_status(trace.StatusCode.ERROR, str(exc))
				# Re-raise so Celery can retry or mark the task failed
				raise

	# ── Pipeline stages ────────────────────────────────────────────────────────

	async def _stage_ml_generate(self, job: GenerationJob) -> dict[str, Any]:
		"""POST to ML service, return raw generation result dict."""
		# 1. Check Redis checkpoint first — survives a crash between ML completion
		#    and DB flush, where job.metadata_ would not yet have ml_result.
		ckpt = await self._checkpoint_get("ml_result")
		if ckpt:
			self._log.info("ml_generate: resuming from Redis checkpoint")
			return ckpt

		if job.status not in (JobStatus.queued, JobStatus.ml_generating):
			# Was already past this stage on a previous attempt — skip ML call
			# and return what's stored in metadata
			stored = job.metadata_.get("ml_result")
			if stored:
				self._log.info("ml_generate: resuming from stored result")
				return stored  # type: ignore[return-value]

		await self._update_status(job, JobStatus.ml_generating, progress=5)
		await self._publish_progress(10, "Generating with ML model…")

		payload = {
			"job_id": self._job_id,
			"prompt": job.prompt_used,
			**{k: v for k, v in job.metadata_.items() if k in (
				"sub_genre", "language", "bpm", "energy_level",
				"key", "duration_seconds", "voice_model_id",
			)},
		}

		self._log.info("calling ml service", url=_ml_settings.service_url)

		result: dict[str, Any] | None = None

		async for attempt in AsyncRetrying(
			stop=stop_after_attempt(3),
			wait=wait_exponential(multiplier=30, min=30, max=270),
			retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError, MLServiceError)),
			reraise=True,
		):
			with attempt:
				result = await self._call_ml_service(payload)

		assert result is not None

		# Write Redis checkpoint BEFORE DB flush — if the worker crashes between
		# ML completion and DB commit, the retry recovers from Redis instead of
		# re-invoking the ML service (saves 30–90 s of GPU time).
		await self._checkpoint_set("ml_result", result)

		# Persist ML result so we can skip this stage on retry
		job.metadata_ = {**job.metadata_, "ml_result": result}
		self._session.add(job)
		await self._session.flush()

		await self._publish_progress(40, "ML generation complete")
		return result

	async def _call_ml_service(self, payload: dict[str, Any]) -> dict[str, Any]:
		headers = {
			"X-API-Key": _ml_settings.service_api_key,
			"Content-Type": "application/json",
		}
		async with httpx.AsyncClient(timeout=_ml_settings.inference_timeout) as client:
			resp = await client.post(
				f"{_ml_settings.service_url}/generate",
				json=payload,
				headers=headers,
			)
		if resp.status_code != 200:
			raise MLServiceError(
				f"ML service returned {resp.status_code}: {resp.text[:512]}"
			)
		data: dict[str, Any] = resp.json()
		assert "audio_bytes_b64" in data or "audio_url" in data, (
			f"ML service response missing audio field: {list(data.keys())}"
		)
		return data

	async def _stage_audio_process(  # pragma: no cover
		self,
		job: GenerationJob,
		ml_result: dict[str, Any],
	) -> dict[str, Any]:
		"""Decode ML audio, run DSP pipeline, return artifacts ready for upload.

		Returns {"artifacts": dict[str, bytes], "analysis": dict[str, Any]}.
		Raw bytes are not cached in JSONB (too large); audio_analysis is cached
		so _stage_create_track can use accurate BPM/key from the DSP layer.
		On retry the pipeline re-runs — it is deterministic from the same input.
		"""
		await self._update_status(job, JobStatus.audio_processing, progress=45)
		await self._publish_progress(50, "Processing audio…")

		# Decode raw audio from ML service response
		if "audio_bytes_b64" in ml_result:
			raw_bytes = base64.b64decode(ml_result["audio_bytes_b64"])
		elif "audio_url" in ml_result:
			async with httpx.AsyncClient(timeout=120) as client:
				resp = await client.get(ml_result["audio_url"])
				resp.raise_for_status()
			raw_bytes = resp.content
		else:
			raise MLServiceError(
				f"ml_result missing audio field; keys present: {list(ml_result.keys())}"
			)

		# Heavy deps loaded inside worker to avoid slow imports at startup
		from gbedu_audio.pipeline import AudioPipeline  # type: ignore[import]

		with tempfile.TemporaryDirectory(prefix="gbedu_audio_") as tmpdir:
			tmp_path = Path(tmpdir)
			raw_audio_path = tmp_path / "raw_audio.wav"
			raw_audio_path.write_bytes(raw_bytes)

			output_dir = tmp_path / "output"
			pipeline = AudioPipeline()
			result = await pipeline.process(raw_audio_path, output_dir)

			# Read output files into bytes while temp dir is still alive
			artifacts: dict[str, bytes] = {}
			if result.final_mp3.is_file():
				artifacts["audio"] = result.final_mp3.read_bytes()
			if result.watermarked_mp3 and result.watermarked_mp3.is_file():
				artifacts["audio_watermarked"] = result.watermarked_mp3.read_bytes()
			if result.preview_mp3.is_file():
				artifacts["preview"] = result.preview_mp3.read_bytes()
			for stem_name, stem_path in result.stems.items():
				if stem_path.is_file():
					artifacts[f"stem_{stem_name}"] = stem_path.read_bytes()

			assert artifacts, "AudioPipeline produced no uploadable artifacts"

			# Cache lightweight analysis for _stage_create_track BPM/key resolution
			job.metadata_ = {**job.metadata_, "audio_analysis": result.analysis}
			self._session.add(job)
			await self._session.flush()

		await self._publish_progress(70, "Audio processing complete")
		return {"artifacts": artifacts, "analysis": result.analysis}

	async def _stage_upload(  # pragma: no cover
		self,
		job: GenerationJob,
		processed: dict[str, Any],
	) -> dict[str, str]:
		"""Upload all artifacts to R2. Returns mapping of artifact_name → public_url."""
		if job.status == JobStatus.uploading and job.metadata_.get("uploaded_urls"):
			self._log.info("upload: resuming from stored URLs")
			return job.metadata_["uploaded_urls"]  # type: ignore[return-value]

		await self._update_status(job, JobStatus.uploading, progress=72)
		await self._publish_progress(75, "Uploading to storage…")

		from gbedu_worker.storage import R2Client  # type: ignore[import]

		r2 = R2Client(settings=_storage_settings)
		urls: dict[str, str] = {}

		artifacts: dict[str, bytes] = processed.get("artifacts", {})
		assert artifacts, "processed result must contain at least one artifact"

		for name, data in artifacts.items():
			key = f"tracks/{self._job_id}/{name}"
			async for attempt in AsyncRetrying(
				stop=stop_after_attempt(3),
				wait=wait_exponential(multiplier=2, min=2, max=30),
				retry=retry_if_exception_type(UploadError),
				reraise=True,
			):
				with attempt:
					url = await r2.upload(key=key, data=data, content_type="audio/mpeg")
					urls[name] = url

		job.metadata_ = {**job.metadata_, "uploaded_urls": urls}
		self._session.add(job)
		await self._session.flush()

		await self._publish_progress(90, "Upload complete")
		return urls

	async def _stage_create_track(  # pragma: no cover
		self,
		job: GenerationJob,
		ml_result: dict[str, Any],
		urls: dict[str, str],
	) -> Track:
		"""Create the Track DB record if it doesn't exist yet (idempotent)."""
		# If a track_id is already linked, load and return it
		if job.track_id:
			existing = await self._session.get(Track, job.track_id)
			if existing is not None:
				self._log.info("create_track: track already exists", track_id=job.track_id)
				return existing

		meta = job.metadata_
		# Prefer DSP-measured BPM/key (from AudioPipeline analysis) over ML estimate
		audio_analysis = meta.get("audio_analysis", {})
		track = Track(
			id=uuid7str(),
			user_id=job.user_id,
			generation_job_id=job.id,
			title=meta.get("title") or f"Track {self._job_id[:8]}",
			prompt=job.prompt_used,
			sub_genre=meta.get("sub_genre", "afropop"),
			language=meta.get("language", "english"),
			bpm=audio_analysis.get("bpm") or ml_result.get("bpm"),
			key=audio_analysis.get("key") or ml_result.get("key"),
			energy_level=meta.get("energy_level", 5),
			duration_seconds=audio_analysis.get("duration_seconds") or ml_result.get("duration_seconds"),
			status=TrackStatus.processing,
			audio_url=urls.get("audio"),
			audio_url_watermarked=urls.get("audio_watermarked"),
			stem_urls={
				k: v
				for k, v in urls.items()
				if k.startswith("stem_")
			},
			lyrics=ml_result.get("lyrics"),
			cover_art_url=urls.get("cover_art"),
		)
		self._session.add(track)

		job.track_id = track.id
		self._session.add(job)

		await self._session.flush()
		self._log.info("track record created", track_id=track.id)
		return track

	async def _stage_complete(  # pragma: no cover
		self,
		job: GenerationJob,
		track: Track,
		ml_result: dict[str, Any],
	) -> None:
		"""Mark job complete and track ready."""
		now = datetime.now(timezone.utc)

		track.status = TrackStatus.ready
		self._session.add(track)

		job.status = JobStatus.complete
		job.completed_at = now
		job.progress_percent = 100
		job.model_used = ml_result.get("model_used")
		self._session.add(job)

		await self._session.flush()
		await self._publish_progress(100, "Complete", extra={"track_id": track.id})
		self._log.info("job complete", track_id=track.id)

	# ── Failure handling ───────────────────────────────────────────────────────

	async def _handle_failure(self, job: GenerationJob, exc: Exception) -> None:  # pragma: no cover
		try:
			job.status = JobStatus.failed
			job.error_message = str(exc)[:1024]
			job.error_traceback = traceback.format_exc()
			self._session.add(job)
			await self._session.flush()
			await self._publish_progress(-1, f"Failed: {type(exc).__name__}")
		except Exception as flush_exc:
			self._log.error(
				"failed to persist failure state",
				orig_exc=str(exc),
				flush_exc=str(flush_exc),
			)

	# ── Helpers ────────────────────────────────────────────────────────────────

	async def _load_job(self) -> GenerationJob | None:
		result = await self._session.execute(
			select(GenerationJob).where(GenerationJob.id == self._job_id)
		)
		self._job = result.scalar_one_or_none()
		return self._job

	async def _update_status(
		self,
		job: GenerationJob,
		status: JobStatus,
		*,
		progress: int = 0,
	) -> None:
		assert status not in TERMINAL_JOB_STATUSES or status in (
			JobStatus.complete, JobStatus.failed
		), f"unexpected terminal transition to {status}"

		job.status = status
		job.progress_percent = progress
		if status == JobStatus.ml_generating and job.started_at is None:
			job.started_at = datetime.now(timezone.utc)
		self._session.add(job)
		await self._session.flush()
		self._log.debug("status updated", status=status.value, progress=progress)

	async def _checkpoint_set(self, stage: str, data: dict[str, Any]) -> None:
		"""Persist stage result to Redis before the DB flush.

		If the worker crashes between ML completion and the DB write, the retry
		finds this key and skips re-calling the ML service (saving 30-90 s of
		GPU time and avoiding duplicate generations).
		"""
		import redis.asyncio as aioredis

		key = f"{_CHECKPOINT_PREFIX}{self._job_id}:{stage}"
		try:
			r = await aioredis.from_url(
				_redis_settings.url, encoding="utf-8", decode_responses=True
			)
			async with r:
				await r.setex(key, _CHECKPOINT_TTL, json.dumps(data))
			self._log.debug("checkpoint.set", stage=stage, key=key)
		except Exception as exc:
			# Checkpoint write failure is non-fatal — the DB write below is the source of truth.
			self._log.warning("checkpoint.set_failed", stage=stage, error=str(exc))

	async def _checkpoint_get(self, stage: str) -> dict[str, Any] | None:
		"""Retrieve a previously checkpointed stage result from Redis."""
		import redis.asyncio as aioredis

		key = f"{_CHECKPOINT_PREFIX}{self._job_id}:{stage}"
		try:
			r = await aioredis.from_url(
				_redis_settings.url, encoding="utf-8", decode_responses=True
			)
			async with r:
				raw = await r.get(key)
			if raw:
				self._log.info("checkpoint.hit", stage=stage)
				return json.loads(raw)
		except Exception as exc:
			self._log.warning("checkpoint.get_failed", stage=stage, error=str(exc))
		return None

	async def _publish_progress(  # pragma: no cover
		self,
		percent: int,
		message: str,
		*,
		extra: dict[str, Any] | None = None,
	) -> None:
		"""Publish SSE-compatible progress event to Redis pub/sub."""
		import redis.asyncio as aioredis

		payload: dict[str, Any] = {
			"job_id": self._job_id,
			"percent": percent,
			"message": message,
			"ts": datetime.now(timezone.utc).isoformat(),
		}
		if extra:
			payload.update(extra)

		channel = f"{_JOB_CHANNEL_PREFIX}{self._job_id}"
		try:
			redis = await aioredis.from_url(
				_redis_settings.url,
				encoding="utf-8",
				decode_responses=True,
			)
			async with redis:
				await redis.publish(channel, json.dumps(payload))
		except Exception as exc:
			# Progress events are best-effort — never fail the pipeline over them
			self._log.warning("failed to publish progress event", exc=str(exc), channel=channel)
