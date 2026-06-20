from __future__ import annotations

"""Periodic maintenance tasks — Beat schedule invokes these automatically.

All tasks are idempotent: re-running one that already completed is a safe no-op.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from celery import Task
from opentelemetry import trace
from sqlalchemy import select, update

from gbedu_core.config import StorageSettings
from gbedu_core.models.track import Track, TrackStatus
from gbedu_core.telemetry import get_tracer, increment_error_count
from gbedu_worker.celery_app import app
from gbedu_worker.db import get_async_session, run_async

log = structlog.get_logger(__name__)
tracer = get_tracer(__name__)

_storage_settings = StorageSettings()

# Temp files older than this are eligible for deletion
_TEMP_FILE_MAX_AGE = timedelta(hours=24)

# R2 prefix that holds ephemeral working files
_TEMP_PREFIX = "temp/"

# How many distribution retries we attempt per run before giving up this batch
_MAX_DISTRIBUTION_RETRIES_PER_RUN = 50


@app.task(
	bind=True,
	name="gbedu_worker.tasks.cleanup.cleanup_expired_temp_files",
	max_retries=2,
	acks_late=True,
	queue="low",
	soft_time_limit=600,
	time_limit=660,
)
def cleanup_expired_temp_files(self: Task) -> dict[str, Any]:
	"""Scan the R2 temp/ prefix and delete objects older than 24 h.

	Invoked hourly by Celery Beat.
	"""
	task_log = log.bind(task_id=self.request.id)
	task_log.info("cleanup_expired_temp_files starting")

	with tracer.start_as_current_span("task.cleanup_expired_temp_files") as span:
		try:
			result = run_async(_do_cleanup_temp_files())
			span.set_attribute("cleanup.deleted_count", result.get("deleted_count", 0))
			return result
		except Exception as exc:
			task_log.error("cleanup_expired_temp_files failed", exc_type=type(exc).__name__, exc_msg=str(exc))
			increment_error_count(error_code=type(exc).__name__, service="worker.cleanup")
			span.record_exception(exc)
			span.set_status(trace.StatusCode.ERROR, str(exc))
			raise self.retry(exc=exc, countdown=120)


@app.task(
	bind=True,
	name="gbedu_worker.tasks.cleanup.reset_daily_generation_counts",
	max_retries=2,
	acks_late=True,
	queue="low",
	soft_time_limit=120,
	time_limit=150,
)
def reset_daily_generation_counts(self: Task) -> dict[str, Any]:
	"""Reset generation_count_today to 0 for all users.

	Invoked at midnight UTC daily by Celery Beat.
	"""
	task_log = log.bind(task_id=self.request.id)
	task_log.info("reset_daily_generation_counts starting")

	with tracer.start_as_current_span("task.reset_daily_generation_counts") as span:
		try:
			result = run_async(_do_reset_generation_counts())
			span.set_attribute("reset.rows_affected", result.get("rows_affected", 0))
			return result
		except Exception as exc:
			task_log.error("reset_daily_generation_counts failed", exc_type=type(exc).__name__, exc_msg=str(exc))
			increment_error_count(error_code=type(exc).__name__, service="worker.cleanup")
			span.record_exception(exc)
			span.set_status(trace.StatusCode.ERROR, str(exc))
			raise self.retry(exc=exc, countdown=60)


@app.task(
	bind=True,
	name="gbedu_worker.tasks.cleanup.retry_failed_distributions",
	max_retries=2,
	acks_late=True,
	queue="low",
	soft_time_limit=300,
	time_limit=360,
)
def retry_failed_distributions(self: Task) -> dict[str, Any]:
	"""Find tracks with distribution_status=pending_retry and re-attempt distribution.

	Invoked every 6 h by Celery Beat.
	"""
	task_log = log.bind(task_id=self.request.id)
	task_log.info("retry_failed_distributions starting")

	with tracer.start_as_current_span("task.retry_failed_distributions") as span:
		try:
			result = run_async(_do_retry_failed_distributions())
			span.set_attribute("retry.attempted_count", result.get("attempted_count", 0))
			return result
		except Exception as exc:
			task_log.error("retry_failed_distributions failed", exc_type=type(exc).__name__, exc_msg=str(exc))
			increment_error_count(error_code=type(exc).__name__, service="worker.cleanup")
			span.record_exception(exc)
			span.set_status(trace.StatusCode.ERROR, str(exc))
			raise self.retry(exc=exc, countdown=300)


# ── Async implementations ──────────────────────────────────────────────────────

async def _do_cleanup_temp_files() -> dict[str, Any]:
	import boto3
	from botocore.exceptions import BotoCoreError, ClientError

	cutoff = datetime.now(timezone.utc) - _TEMP_FILE_MAX_AGE
	deleted_count = 0
	error_count = 0

	s3 = boto3.client(
		"s3",
		endpoint_url=_storage_settings.r2_endpoint_url,
		aws_access_key_id=_storage_settings.r2_access_key_id,
		aws_secret_access_key=_storage_settings.r2_secret_access_key,
		region_name="auto",
	)

	paginator = s3.get_paginator("list_objects_v2")
	pages = paginator.paginate(
		Bucket=_storage_settings.r2_bucket_name,
		Prefix=_TEMP_PREFIX,
	)

	to_delete: list[dict[str, str]] = []

	for page in pages:
		for obj in page.get("Contents", []):
			last_modified: datetime = obj["LastModified"]
			if last_modified < cutoff:
				to_delete.append({"Key": obj["Key"]})

		# Delete in batches of 1000 (S3 API limit)
		if len(to_delete) >= 1000:
			batch, to_delete = to_delete[:1000], to_delete[1000:]
			deleted_count += _delete_batch(s3, batch)

	if to_delete:
		deleted_count += _delete_batch(s3, to_delete)

	log.info(
		"cleanup_expired_temp_files complete",
		deleted_count=deleted_count,
		error_count=error_count,
		cutoff=cutoff.isoformat(),
	)
	return {
		"status": "complete",
		"deleted_count": deleted_count,
		"cutoff": cutoff.isoformat(),
	}


def _delete_batch(s3: Any, keys: list[dict[str, str]]) -> int:
	from botocore.exceptions import ClientError
	try:
		resp = s3.delete_objects(
			Bucket=_storage_settings.r2_bucket_name,
			Delete={"Objects": keys, "Quiet": True},
		)
		errors = resp.get("Errors", [])
		if errors:
			log.warning("r2 delete_objects had errors", errors=errors[:5])
		return len(keys) - len(errors)
	except ClientError as exc:
		log.error("r2 delete_objects failed", exc_msg=str(exc))
		return 0


async def _do_reset_generation_counts() -> dict[str, Any]:
	from sqlalchemy import text

	now = datetime.now(timezone.utc)

	async with get_async_session() as session:
		result = await session.execute(
			text(
				"UPDATE users "
				"SET generation_count_today = 0, "
				"    generation_count_reset_at = :now "
				"WHERE generation_count_today > 0 "
				"  AND deleted_at IS NULL"
			),
			{"now": now},
		)
		rows_affected = result.rowcount

	log.info(
		"reset_daily_generation_counts complete",
		rows_affected=rows_affected,
		reset_at=now.isoformat(),
	)
	return {
		"status": "complete",
		"rows_affected": rows_affected,
		"reset_at": now.isoformat(),
	}


async def _do_retry_failed_distributions() -> dict[str, Any]:
	"""Retry tracks whose distribution has not yet succeeded.

	Distribution metadata is stored in Track.metadata_ under the key
	`distribution_status`. Values: "pending_retry" triggers a retry here;
	"distributed" means done; anything else is ignored.
	"""
	from sqlalchemy.dialects.postgresql import JSONB
	from sqlalchemy import cast, String, func

	attempted = 0
	succeeded = 0
	still_failing = 0

	async with get_async_session() as session:
		# Find tracks flagged for distribution retry (limit batch size)
		result = await session.execute(
			select(Track)
			.where(Track.status == TrackStatus.ready)
			.where(
				Track.metadata_["distribution_status"].as_string() == "pending_retry"
			)
			.limit(_MAX_DISTRIBUTION_RETRIES_PER_RUN)
		)
		tracks: list[Track] = list(result.scalars().all())

		for track in tracks:
			attempted += 1
			try:
				await _attempt_distribution(track)
				track.metadata_ = {
					**track.metadata_,
					"distribution_status": "distributed",
					"distributed_at": datetime.now(timezone.utc).isoformat(),
				}
				session.add(track)
				succeeded += 1
			except Exception as exc:
				log.warning(
					"distribution retry failed",
					track_id=track.id,
					exc_type=type(exc).__name__,
					exc_msg=str(exc),
				)
				# Increment retry count; leave status as pending_retry for next run
				retry_count = track.metadata_.get("distribution_retry_count", 0) + 1
				track.metadata_ = {
					**track.metadata_,
					"distribution_retry_count": retry_count,
					"distribution_last_error": str(exc),
					"distribution_last_attempt": datetime.now(timezone.utc).isoformat(),
				}
				session.add(track)
				still_failing += 1

	log.info(
		"retry_failed_distributions complete",
		attempted=attempted,
		succeeded=succeeded,
		still_failing=still_failing,
	)
	return {
		"status": "complete",
		"attempted_count": attempted,
		"succeeded_count": succeeded,
		"still_failing_count": still_failing,
	}


async def _attempt_distribution(track: Track) -> None:
	"""Distribute a track to the configured DSP platform.

	Provider is selected via the DISTRIBUTION_PROVIDER environment variable:
	  - unset / "none" — log a warning and no-op (distribution disabled)
	  - "distrokid"    — DistroKid partner API (requires DISTROKID_API_KEY +
	                     DISTROKID_ARTIST_ID in environment)
	  - "tunecore"     — TuneCore API (requires TUNECORE_API_KEY in environment)

	Any failure raises an exception so the caller records a retry.
	"""
	assert track.audio_url, f"track {track.id} has no audio_url — cannot distribute"
	assert track.status == TrackStatus.ready, f"track {track.id} is not ready"

	import os
	provider_name = os.environ.get("DISTRIBUTION_PROVIDER", "none").lower().strip()

	if provider_name in ("", "none"):
		log.info(
			"distribution.skipped — no provider configured",
			track_id=track.id,
			hint="Set DISTRIBUTION_PROVIDER=distrokid|tunecore to enable",
		)
		return

	provider = _build_distribution_provider(provider_name)
	await provider.distribute(track)
	log.info("distribution.sent", track_id=track.id, provider=provider_name)


def _build_distribution_provider(name: str) -> "_DistributionProvider":
	if name == "distrokid":
		return _DistroKidProvider()
	if name == "tunecore":
		return _TuneCoreProvider()
	raise ValueError(
		f"Unknown DISTRIBUTION_PROVIDER={name!r}. Valid values: distrokid, tunecore, none"
	)


class _DistributionProvider:
	"""Abstract base for DSP distribution providers."""

	async def distribute(self, track: Track) -> None:
		raise NotImplementedError


class _DistroKidProvider(_DistributionProvider):
	"""DistroKid Partner API distribution.

	Requires env vars:
	  DISTROKID_API_KEY    — partner API key
	  DISTROKID_ARTIST_ID  — artist account ID to distribute under

	Docs: https://distrokid.com/partner-api (requires partner agreement)
	"""

	async def distribute(self, track: Track) -> None:
		import os
		import httpx

		api_key = os.environ["DISTROKID_API_KEY"]
		artist_id = os.environ["DISTROKID_ARTIST_ID"]

		payload = {
			"artist_id": artist_id,
			"title": track.title,
			"audio_url": track.audio_url,
			"genre": track.sub_genre.value if track.sub_genre else "afrobeats",
			"release_date": track.created_at.strftime("%Y-%m-%d") if track.created_at else None,
			"isrc": track.metadata_.get("isrc") if track.metadata_ else None,
		}

		async with httpx.AsyncClient(timeout=60.0) as client:
			resp = await client.post(
				"https://distrokid.com/api/partner/v1/tracks",
				json=payload,
				headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
			)

		if resp.status_code not in (200, 201, 202):
			raise RuntimeError(
				f"DistroKid API returned HTTP {resp.status_code}: {resp.text[:300]}"
			)

		log.info(
			"distrokid.distribution.accepted",
			track_id=track.id,
			response_status=resp.status_code,
		)


class _TuneCoreProvider(_DistributionProvider):
	"""TuneCore API distribution.

	Requires env var:
	  TUNECORE_API_KEY — TuneCore API key

	Docs: https://www.tunecore.com/api-docs (requires TuneCore account)
	"""

	async def distribute(self, track: Track) -> None:
		import os
		import httpx

		api_key = os.environ["TUNECORE_API_KEY"]

		payload = {
			"title": track.title,
			"audio_url": track.audio_url,
			"genre": track.sub_genre.value if track.sub_genre else "afrobeats",
		}

		async with httpx.AsyncClient(timeout=60.0) as client:
			resp = await client.post(
				"https://api.tunecore.com/v1/tracks",
				json=payload,
				headers={"X-API-Key": api_key, "Content-Type": "application/json"},
			)

		if resp.status_code not in (200, 201, 202):
			raise RuntimeError(
				f"TuneCore API returned HTTP {resp.status_code}: {resp.text[:300]}"
			)

		log.info(
			"tunecore.distribution.accepted",
			track_id=track.id,
			response_status=resp.status_code,
		)
