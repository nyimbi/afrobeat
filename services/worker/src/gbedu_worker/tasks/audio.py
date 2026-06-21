from __future__ import annotations

"""Secondary audio processing tasks — stems, remastering, preview regeneration.

All tasks are idempotent: each checks current track state before doing any
expensive work and stores its output back on the Track record.
"""

import asyncio
from typing import Any

import structlog
from celery import Task
from gbedu_core.models.track import Track
from gbedu_core.telemetry import get_tracer, increment_error_count
from opentelemetry import trace

from gbedu_worker.celery_app import celery_task, retry_task
from gbedu_worker.db import get_async_session, run_async
from gbedu_worker.storage import R2Client

log = structlog.get_logger(__name__)
tracer = get_tracer(__name__)


@celery_task(
	bind=True,
	name="gbedu_worker.tasks.audio.process_stems",
	max_retries=3,
	acks_late=True,
	reject_on_worker_lost=True,
	queue="default",
	soft_time_limit=900,
	time_limit=960,
)
def process_stems(self: Task, track_id: str) -> dict[str, Any]:
	"""Run Demucs stem separation on an existing track.

	Idempotent: skips if stem_urls already populated.
	"""
	assert track_id, "track_id must not be empty"
	task_log = log.bind(track_id=track_id, task_id=self.request.id)
	task_log.info("process_stems task received")

	with tracer.start_as_current_span("task.process_stems") as span:
		span.set_attribute("track.id", track_id)
		try:
			result = run_async(_do_process_stems, track_id)
			return result
		except Exception as exc:
			task_log.error("process_stems failed", exc_type=type(exc).__name__, exc_msg=str(exc))
			increment_error_count(error_code=type(exc).__name__, service="worker.audio")
			span.record_exception(exc)
			span.set_status(trace.StatusCode.ERROR, str(exc))
			try:
				retry_task(self, exc=exc, countdown=_jitter_countdown(self.request.retries))
			except Exception:
				raise


@celery_task(
	bind=True,
	name="gbedu_worker.tasks.audio.remaster_track",
	max_retries=3,
	acks_late=True,
	reject_on_worker_lost=True,
	queue="default",
	soft_time_limit=600,
	time_limit=660,
)
def remaster_track(self: Task, track_id: str, reference_profile: str) -> dict[str, Any]:
	"""Remaster a track against a reference loudness/EQ profile.

	`reference_profile` is a profile key understood by AudioPipeline.remaster
	(e.g. "afropop_radio", "streaming_norm").
	Idempotent: safe to call multiple times; last call wins.
	"""
	assert track_id, "track_id must not be empty"
	assert reference_profile, "reference_profile must not be empty"
	task_log = log.bind(
		track_id=track_id, reference_profile=reference_profile, task_id=self.request.id
	)
	task_log.info("remaster_track task received")

	with tracer.start_as_current_span("task.remaster_track") as span:
		span.set_attribute("track.id", track_id)
		span.set_attribute("audio.reference_profile", reference_profile)
		try:
			result = run_async(_do_remaster_track, track_id, reference_profile)
			return result
		except Exception as exc:
			task_log.error("remaster_track failed", exc_type=type(exc).__name__, exc_msg=str(exc))
			increment_error_count(error_code=type(exc).__name__, service="worker.audio")
			span.record_exception(exc)
			span.set_status(trace.StatusCode.ERROR, str(exc))
			try:
				retry_task(self, exc=exc, countdown=_jitter_countdown(self.request.retries))
			except Exception:
				raise


@celery_task(
	bind=True,
	name="gbedu_worker.tasks.audio.create_preview",
	max_retries=3,
	acks_late=True,
	reject_on_worker_lost=True,
	queue="default",
	soft_time_limit=120,
	time_limit=150,
)
def create_preview(self: Task, track_id: str) -> dict[str, Any]:
	"""Regenerate the 15-second watermarked preview clip for a track.

	Idempotent: overwrites any existing preview_url on the track.
	"""
	assert track_id, "track_id must not be empty"
	task_log = log.bind(track_id=track_id, task_id=self.request.id)
	task_log.info("create_preview task received")

	with tracer.start_as_current_span("task.create_preview") as span:
		span.set_attribute("track.id", track_id)
		try:
			result = run_async(_do_create_preview, track_id)
			return result
		except Exception as exc:
			task_log.error("create_preview failed", exc_type=type(exc).__name__, exc_msg=str(exc))
			increment_error_count(error_code=type(exc).__name__, service="worker.audio")
			span.record_exception(exc)
			span.set_status(trace.StatusCode.ERROR, str(exc))
			try:
				retry_task(self, exc=exc, countdown=_jitter_countdown(self.request.retries))
			except Exception:
				raise


# ── Async implementations ──────────────────────────────────────────────────────


async def _do_process_stems(track_id: str) -> dict[str, Any]:
	from gbedu_audio.pipeline import AudioPipeline  # type: ignore[import]
	from gbedu_core.config import StorageSettings

	storage = StorageSettings()

	async with get_async_session() as session:
		track = await session.get(Track, track_id)
		if track is None:
			log.warning("process_stems: track not found", track_id=track_id)
			return {"status": "skipped", "reason": "not_found"}

		if track.stem_urls:
			log.info("process_stems: stems already present — skipping", track_id=track_id)
			return {"status": "skipped", "reason": "already_done", "stem_urls": track.stem_urls}

		assert track.audio_url, f"track {track_id} has no audio_url — cannot stem"

		pipeline = AudioPipeline(settings=storage)
		r2 = R2Client(settings=storage)

		stem_data: dict[str, bytes] = await asyncio.get_event_loop().run_in_executor(
			None,
			pipeline.separate_stems,
			track.audio_url,
		)

		stem_urls: dict[str, str] = {}
		for stem_name, data in stem_data.items():
			key = f"tracks/{track_id}/stems/{stem_name}.mp3"
			url = await r2.upload(key=key, data=data, content_type="audio/mpeg")
			stem_urls[stem_name] = url

		track.stem_urls = stem_urls
		session.add(track)

		log.info("process_stems: done", track_id=track_id, stems=list(stem_urls.keys()))
		return {"status": "complete", "track_id": track_id, "stem_urls": stem_urls}


async def _do_remaster_track(track_id: str, reference_profile: str) -> dict[str, Any]:
	from gbedu_audio.pipeline import AudioPipeline  # type: ignore[import]
	from gbedu_core.config import StorageSettings

	storage = StorageSettings()

	async with get_async_session() as session:
		track = await session.get(Track, track_id)
		if track is None:
			log.warning("remaster_track: track not found", track_id=track_id)
			return {"status": "skipped", "reason": "not_found"}

		assert track.audio_url, f"track {track_id} has no audio_url — cannot remaster"

		pipeline = AudioPipeline(settings=storage)
		r2 = R2Client(settings=storage)

		remastered_bytes: bytes = await asyncio.get_event_loop().run_in_executor(
			None,
			pipeline.remaster,
			track.audio_url,
			reference_profile,
		)

		key = f"tracks/{track_id}/audio_remastered_{reference_profile}.mp3"
		url = await r2.upload(key=key, data=remastered_bytes, content_type="audio/mpeg")

		# Store the remastered URL in metadata so the API can surface it
		track.metadata_ = {
			**getattr(track, "metadata_", {}),
			f"remastered_{reference_profile}_url": url,
		}
		session.add(track)

		log.info("remaster_track: done", track_id=track_id, profile=reference_profile, url=url)
		return {
			"status": "complete",
			"track_id": track_id,
			"url": url,
			"profile": reference_profile,
		}


async def _do_create_preview(track_id: str) -> dict[str, Any]:
	from gbedu_audio.pipeline import AudioPipeline  # type: ignore[import]
	from gbedu_core.config import StorageSettings

	storage = StorageSettings()

	async with get_async_session() as session:
		track = await session.get(Track, track_id)
		if track is None:
			log.warning("create_preview: track not found", track_id=track_id)
			return {"status": "skipped", "reason": "not_found"}

		assert track.audio_url, f"track {track_id} has no audio_url — cannot create preview"

		pipeline = AudioPipeline(settings=storage)
		r2 = R2Client(settings=storage)

		preview_bytes: bytes = await asyncio.get_event_loop().run_in_executor(
			None,
			pipeline.create_preview,
			track.audio_url,
			15,
		)

		key = f"tracks/{track_id}/preview_15s.mp3"
		url = await r2.upload(key=key, data=preview_bytes, content_type="audio/mpeg")

		# BeatListing.preview_url is stored on the listing, not the track.
		# Update the track's watermarked URL as the canonical preview.
		track.audio_url_watermarked = url
		session.add(track)

		log.info("create_preview: done", track_id=track_id, url=url)
		return {"status": "complete", "track_id": track_id, "preview_url": url}


def _jitter_countdown(retry_num: int) -> int:
	"""Exponential back-off with modest jitter: 30 / 90 / 270 seconds."""
	import random

	base = (30, 90, 270)[min(retry_num, 2)]
	jitter = random.randint(0, max(1, base // 10))
	return base + jitter
