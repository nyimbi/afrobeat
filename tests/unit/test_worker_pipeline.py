from __future__ import annotations

"""Unit tests for GenerationPipelineOrchestrator and R2Client."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from gbedu_core.models.job import GenerationJob, JobStatus
from gbedu_core.models.track import Track, TrackStatus
from gbedu_worker.exceptions import MLServiceError, UploadError

# ── shared helpers ────────────────────────────────────────────────────────


def _make_job(
	job_id: str = "job-1",
	status: JobStatus = JobStatus.queued,
	is_terminal: bool = False,
	track_id: str | None = None,
	metadata: dict | None = None,
) -> MagicMock:
	job = MagicMock(spec=GenerationJob)
	job.id = job_id
	job.status = status
	job.is_terminal = is_terminal
	job.track_id = track_id
	job.metadata_ = metadata or {"sub_genre": "afropop", "language": "english"}
	job.prompt_used = "Create an afrobeats track"
	job.user_id = "user-1"
	job.started_at = None
	job.progress_percent = 0
	job.completed_at = None
	job.model_used = None
	job.error_message = None
	job.error_traceback = None
	return job


def _make_track(track_id: str = "track-1") -> MagicMock:
	t = MagicMock(spec=Track)
	t.id = track_id
	t.status = TrackStatus.processing
	return t


def _make_session(
	execute_return: Any = None,
	get_return: Any = None,
) -> MagicMock:
	session = MagicMock()
	session.add = MagicMock()
	session.flush = AsyncMock()
	session.commit = AsyncMock()

	result = MagicMock()
	result.scalar_one_or_none.return_value = execute_return
	session.execute = AsyncMock(return_value=result)

	async def _get(model_cls: Any, pk: str) -> Any:
		return get_return

	session.get = _get
	return session


def _fake_redis(get_return: str | None = None) -> MagicMock:
	r = MagicMock()
	r.get = AsyncMock(return_value=get_return)
	r.setex = AsyncMock()
	r.publish = AsyncMock()
	r.__aenter__ = AsyncMock(return_value=r)
	r.__aexit__ = AsyncMock(return_value=False)
	return r


def _make_orchestrator(job_id: str = "job-1", session: MagicMock | None = None) -> Any:
	from gbedu_worker.pipelines.generation_pipeline import GenerationPipelineOrchestrator

	if session is None:
		session = _make_session()
	return GenerationPipelineOrchestrator(job_id=job_id, session=session)


# ── run(): job not found ───────────────────────────────────────────────────


async def test_run_job_not_found_skipped() -> None:
	session = _make_session(execute_return=None)
	orch = _make_orchestrator(session=session)

	result = await orch.run()

	assert result == {"status": "skipped", "reason": "not_found"}


async def test_run_job_already_terminal_skipped() -> None:
	job = _make_job(status=JobStatus.complete, is_terminal=True)
	session = _make_session(execute_return=job)
	orch = _make_orchestrator(session=session)

	result = await orch.run()

	assert result["status"] == "skipped"
	assert result["reason"] == "already_terminal"


# ── run(): happy path ─────────────────────────────────────────────────────


async def test_run_happy_path_complete() -> None:
	from gbedu_worker.pipelines.generation_pipeline import GenerationPipelineOrchestrator

	job = _make_job()
	track = _make_track()
	session = _make_session(execute_return=job)

	redis = _fake_redis()

	orch = GenerationPipelineOrchestrator(job_id="job-1", session=session)

	ml_result = {
		"audio_bytes_b64": "dGVzdA==",  # base64 of "test"
		"lyrics": "Aye-aye-aye",
		"bpm": 120,
		"model_used": "ace_step",
	}

	with (
		patch.object(orch, "_stage_ml_generate", AsyncMock(return_value=ml_result)),
		patch.object(
			orch,
			"_stage_audio_process",
			AsyncMock(return_value={"artifacts": {"audio": b"x"}, "analysis": {}}),
		),
		patch.object(
			orch, "_stage_upload", AsyncMock(return_value={"audio": "https://r2/audio.mp3"})
		),
		patch.object(orch, "_stage_create_track", AsyncMock(return_value=track)),
		patch.object(orch, "_stage_complete", AsyncMock()),
		patch("redis.asyncio.from_url", AsyncMock(return_value=redis)),
	):
		result = await orch.run()

	assert result["status"] == "complete"
	assert result["job_id"] == "job-1"
	assert result["track_id"] == "track-1"


async def test_run_stage_exception_calls_handle_failure() -> None:
	from gbedu_worker.pipelines.generation_pipeline import GenerationPipelineOrchestrator

	job = _make_job()
	session = _make_session(execute_return=job)
	orch = GenerationPipelineOrchestrator(job_id="job-1", session=session)

	handle_mock = AsyncMock()
	with (
		patch.object(orch, "_stage_ml_generate", AsyncMock(side_effect=MLServiceError("GPU OOM"))),
		patch.object(orch, "_handle_failure", handle_mock),
		patch("gbedu_core.telemetry.increment_generation_count", MagicMock()),
		patch("gbedu_core.telemetry.increment_error_count", MagicMock()),
	):
		with pytest.raises(MLServiceError):
			await orch.run()

	handle_mock.assert_awaited_once()


# ── _stage_ml_generate ────────────────────────────────────────────────────


async def test_stage_ml_generate_checkpoint_hit() -> None:
	from gbedu_worker.pipelines.generation_pipeline import GenerationPipelineOrchestrator

	job = _make_job()
	session = _make_session()
	orch = GenerationPipelineOrchestrator(job_id="job-1", session=session)

	cached = {"audio_bytes_b64": "dGVzdA==", "model_used": "ace_step"}

	with patch.object(orch, "_checkpoint_get", AsyncMock(return_value=cached)):
		result = await orch._stage_ml_generate(job)

	assert result == cached


async def test_stage_ml_generate_stored_result_resumed() -> None:
	from gbedu_worker.pipelines.generation_pipeline import GenerationPipelineOrchestrator

	stored = {"audio_bytes_b64": "dGVzdA==", "model_used": "ace_step"}
	job = _make_job(
		status=JobStatus.audio_processing, metadata={"ml_result": stored, "sub_genre": "afropop"}
	)
	session = _make_session()
	orch = GenerationPipelineOrchestrator(job_id="job-1", session=session)

	with patch.object(orch, "_checkpoint_get", AsyncMock(return_value=None)):
		result = await orch._stage_ml_generate(job)

	assert result == stored


async def test_stage_ml_generate_calls_ml_service() -> None:
	from gbedu_worker.pipelines.generation_pipeline import GenerationPipelineOrchestrator

	job = _make_job()
	session = _make_session()
	orch = GenerationPipelineOrchestrator(job_id="job-1", session=session)

	ml_result = {"audio_bytes_b64": "dGVzdA==", "model_used": "ace_step"}

	with (
		patch.object(orch, "_checkpoint_get", AsyncMock(return_value=None)),
		patch.object(orch, "_checkpoint_set", AsyncMock()),
		patch.object(orch, "_update_status", AsyncMock()),
		patch.object(orch, "_publish_progress", AsyncMock()),
		patch.object(orch, "_call_ml_service", AsyncMock(return_value=ml_result)),
	):
		result = await orch._stage_ml_generate(job)

	assert result == ml_result


# ── _call_ml_service ──────────────────────────────────────────────────────


async def test_call_ml_service_success() -> None:
	from gbedu_worker.pipelines.generation_pipeline import GenerationPipelineOrchestrator

	_make_job()
	session = _make_session()
	orch = GenerationPipelineOrchestrator(job_id="job-1", session=session)

	mock_resp = MagicMock()
	mock_resp.status_code = 200
	mock_resp.json.return_value = {"audio_bytes_b64": "dGVzdA==", "model_used": "ace_step"}

	mock_client = AsyncMock()
	mock_client.__aenter__ = AsyncMock(return_value=mock_client)
	mock_client.__aexit__ = AsyncMock(return_value=False)
	mock_client.post = AsyncMock(return_value=mock_resp)

	with patch("httpx.AsyncClient", return_value=mock_client):
		result = await orch._call_ml_service({"job_id": "job-1", "prompt": "test"})

	assert result["audio_bytes_b64"] == "dGVzdA=="


async def test_call_ml_service_non_200_raises() -> None:
	from gbedu_worker.pipelines.generation_pipeline import GenerationPipelineOrchestrator

	session = _make_session()
	orch = GenerationPipelineOrchestrator(job_id="job-1", session=session)

	mock_resp = MagicMock()
	mock_resp.status_code = 503
	mock_resp.text = "Service Unavailable"

	mock_client = AsyncMock()
	mock_client.__aenter__ = AsyncMock(return_value=mock_client)
	mock_client.__aexit__ = AsyncMock(return_value=False)
	mock_client.post = AsyncMock(return_value=mock_resp)

	with patch("httpx.AsyncClient", return_value=mock_client):
		with pytest.raises(MLServiceError, match="503"):
			await orch._call_ml_service({"job_id": "job-1", "prompt": "test"})


async def test_call_ml_service_missing_audio_field_raises() -> None:
	from gbedu_worker.pipelines.generation_pipeline import GenerationPipelineOrchestrator

	session = _make_session()
	orch = GenerationPipelineOrchestrator(job_id="job-1", session=session)

	mock_resp = MagicMock()
	mock_resp.status_code = 200
	mock_resp.json.return_value = {"lyrics": "test", "bpm": 120}

	mock_client = AsyncMock()
	mock_client.__aenter__ = AsyncMock(return_value=mock_client)
	mock_client.__aexit__ = AsyncMock(return_value=False)
	mock_client.post = AsyncMock(return_value=mock_resp)

	with patch("httpx.AsyncClient", return_value=mock_client):
		with pytest.raises(AssertionError, match="audio field"):
			await orch._call_ml_service({"job_id": "job-1", "prompt": "test"})


# ── _stage_upload ─────────────────────────────────────────────────────────


async def test_stage_upload_resumes_from_stored_urls() -> None:
	from gbedu_worker.pipelines.generation_pipeline import GenerationPipelineOrchestrator

	stored_urls = {"audio": "https://r2/audio.mp3"}
	job = _make_job(status=JobStatus.uploading, metadata={"uploaded_urls": stored_urls})
	session = _make_session()
	orch = GenerationPipelineOrchestrator(job_id="job-1", session=session)

	result = await orch._stage_upload(job, {"artifacts": {"audio": b"x"}})

	assert result == stored_urls


async def test_stage_upload_empty_artifacts_raises() -> None:
	from gbedu_worker.pipelines.generation_pipeline import GenerationPipelineOrchestrator

	job = _make_job()
	session = _make_session()
	orch = GenerationPipelineOrchestrator(job_id="job-1", session=session)

	with (
		patch.object(orch, "_update_status", AsyncMock()),
		patch.object(orch, "_publish_progress", AsyncMock()),
	):
		with pytest.raises(AssertionError, match="artifact"):
			await orch._stage_upload(job, {"artifacts": {}})


# ── _stage_create_track ───────────────────────────────────────────────────


async def test_stage_create_track_returns_existing_if_linked() -> None:
	from gbedu_worker.pipelines.generation_pipeline import GenerationPipelineOrchestrator

	existing_track = _make_track("existing-track")
	job = _make_job(track_id="existing-track")
	session = _make_session(get_return=existing_track)
	orch = GenerationPipelineOrchestrator(job_id="job-1", session=session)

	result = await orch._stage_create_track(job, {}, {"audio": "https://r2/audio.mp3"})

	assert result.id == "existing-track"


async def test_stage_create_track_creates_new() -> None:
	from gbedu_worker.pipelines.generation_pipeline import GenerationPipelineOrchestrator

	job = _make_job(track_id=None)
	session = _make_session()
	orch = GenerationPipelineOrchestrator(job_id="job-1", session=session)

	ml_result = {"lyrics": "test lyrics", "bpm": 100, "model_used": "ace_step"}
	urls = {"audio": "https://r2/audio.mp3", "audio_watermarked": "https://r2/prev.mp3"}

	result = await orch._stage_create_track(job, ml_result, urls)

	assert isinstance(result, Track)
	session.add.assert_called()


# ── _stage_complete ────────────────────────────────────────────────────────


async def test_stage_complete_sets_job_and_track_status() -> None:
	from gbedu_worker.pipelines.generation_pipeline import GenerationPipelineOrchestrator

	job = _make_job()
	track = _make_track()
	session = _make_session()
	orch = GenerationPipelineOrchestrator(job_id="job-1", session=session)

	with patch.object(orch, "_publish_progress", AsyncMock()):
		await orch._stage_complete(job, track, {"model_used": "ace_step"})

	assert job.status == JobStatus.complete
	assert track.status == TrackStatus.ready
	assert job.progress_percent == 100
	assert job.completed_at is not None


# ── _handle_failure ────────────────────────────────────────────────────────


async def test_handle_failure_marks_job_failed() -> None:
	from gbedu_worker.pipelines.generation_pipeline import GenerationPipelineOrchestrator

	job = _make_job()
	session = _make_session()
	orch = GenerationPipelineOrchestrator(job_id="job-1", session=session)

	with patch.object(orch, "_publish_progress", AsyncMock()):
		await orch._handle_failure(job, RuntimeError("disk full"))

	assert job.status == JobStatus.failed
	assert "disk full" in job.error_message


# ── _checkpoint_set / _checkpoint_get ─────────────────────────────────────


async def test_checkpoint_set_writes_to_redis() -> None:
	from gbedu_worker.pipelines.generation_pipeline import GenerationPipelineOrchestrator

	session = _make_session()
	orch = GenerationPipelineOrchestrator(job_id="job-1", session=session)

	redis = _fake_redis()
	with patch("redis.asyncio.from_url", AsyncMock(return_value=redis)):
		await orch._checkpoint_set("ml_result", {"audio_bytes_b64": "abc"})

	redis.setex.assert_awaited_once()
	key, ttl, value = redis.setex.call_args[0]
	assert "job-1" in key
	assert "ml_result" in key
	assert json.loads(value)["audio_bytes_b64"] == "abc"


async def test_checkpoint_get_returns_none_on_miss() -> None:
	from gbedu_worker.pipelines.generation_pipeline import GenerationPipelineOrchestrator

	session = _make_session()
	orch = GenerationPipelineOrchestrator(job_id="job-1", session=session)

	redis = _fake_redis(get_return=None)
	with patch("redis.asyncio.from_url", AsyncMock(return_value=redis)):
		result = await orch._checkpoint_get("ml_result")

	assert result is None


async def test_checkpoint_get_returns_parsed_json_on_hit() -> None:
	from gbedu_worker.pipelines.generation_pipeline import GenerationPipelineOrchestrator

	session = _make_session()
	orch = GenerationPipelineOrchestrator(job_id="job-1", session=session)

	cached = {"audio_bytes_b64": "xyz", "model_used": "ace_step"}
	redis = _fake_redis(get_return=json.dumps(cached))
	with patch("redis.asyncio.from_url", AsyncMock(return_value=redis)):
		result = await orch._checkpoint_get("ml_result")

	assert result == cached


async def test_checkpoint_set_failure_is_non_fatal() -> None:
	from gbedu_worker.pipelines.generation_pipeline import GenerationPipelineOrchestrator

	session = _make_session()
	orch = GenerationPipelineOrchestrator(job_id="job-1", session=session)

	with patch("redis.asyncio.from_url", AsyncMock(side_effect=Exception("redis down"))):
		# Should not raise
		await orch._checkpoint_set("ml_result", {"data": "x"})


async def test_publish_progress_redis_failure_is_non_fatal() -> None:
	from gbedu_worker.pipelines.generation_pipeline import GenerationPipelineOrchestrator

	session = _make_session()
	orch = GenerationPipelineOrchestrator(job_id="job-1", session=session)

	with patch("redis.asyncio.from_url", AsyncMock(side_effect=Exception("redis down"))):
		# Should not raise
		await orch._publish_progress(50, "Processing…")


# ── R2Client ──────────────────────────────────────────────────────────────


async def test_r2_upload_returns_public_url() -> None:
	from gbedu_core.config import StorageSettings
	from gbedu_worker.storage import R2Client

	settings = MagicMock(spec=StorageSettings)
	settings.r2_endpoint_url = "https://r2.cloudflare.com"
	settings.r2_access_key_id = "key"
	settings.r2_secret_access_key = "secret"
	settings.r2_bucket_name = "gbedu"
	settings.r2_public_url = "https://cdn.gbedu.io"

	client = R2Client(settings=settings)

	mock_s3 = MagicMock()
	mock_s3.put_object = MagicMock()

	mock_loop = MagicMock()

	async def _fake_run_in_executor(executor: Any, fn: Any) -> None:
		fn()

	mock_loop.run_in_executor = _fake_run_in_executor

	with (
		patch("boto3.client", return_value=mock_s3),
		patch("asyncio.get_event_loop", return_value=mock_loop),
	):
		url = await client.upload(
			key="tracks/t1/audio.mp3", data=b"audio", content_type="audio/mpeg"
		)

	assert url == "https://cdn.gbedu.io/tracks/t1/audio.mp3"


async def test_r2_upload_raises_upload_error_on_failure() -> None:
	from gbedu_core.config import StorageSettings
	from gbedu_worker.storage import R2Client

	settings = MagicMock(spec=StorageSettings)
	settings.r2_endpoint_url = "https://r2.cloudflare.com"
	settings.r2_access_key_id = "key"
	settings.r2_secret_access_key = "secret"
	settings.r2_bucket_name = "gbedu"
	settings.r2_public_url = "https://cdn.gbedu.io"

	client = R2Client(settings=settings)

	mock_s3 = MagicMock()
	mock_s3.put_object.side_effect = Exception("network error")

	mock_loop = MagicMock()

	async def _fake_run_in_executor(executor: Any, fn: Any) -> None:
		fn()

	mock_loop.run_in_executor = _fake_run_in_executor

	with (
		patch("boto3.client", return_value=mock_s3),
		patch("asyncio.get_event_loop", return_value=mock_loop),
	):
		with pytest.raises(UploadError, match="R2 upload failed"):
			await client.upload(key="tracks/t1/audio.mp3", data=b"audio", content_type="audio/mpeg")


async def test_r2_delete_success() -> None:
	from gbedu_core.config import StorageSettings
	from gbedu_worker.storage import R2Client

	settings = MagicMock(spec=StorageSettings)
	settings.r2_endpoint_url = "https://r2.cloudflare.com"
	settings.r2_access_key_id = "key"
	settings.r2_secret_access_key = "secret"
	settings.r2_bucket_name = "gbedu"
	settings.r2_public_url = "https://cdn.gbedu.io"

	client = R2Client(settings=settings)

	mock_s3 = MagicMock()
	mock_s3.delete_object = MagicMock()

	mock_loop = MagicMock()

	async def _fake_run_in_executor(executor: Any, fn: Any) -> None:
		fn()

	mock_loop.run_in_executor = _fake_run_in_executor

	with (
		patch("boto3.client", return_value=mock_s3),
		patch("asyncio.get_event_loop", return_value=mock_loop),
	):
		await client.delete(key="tracks/t1/audio.mp3")

	mock_s3.delete_object.assert_called_once()


async def test_r2_delete_raises_on_failure() -> None:
	from gbedu_core.config import StorageSettings
	from gbedu_worker.storage import R2Client

	settings = MagicMock(spec=StorageSettings)
	settings.r2_endpoint_url = "https://r2.cloudflare.com"
	settings.r2_access_key_id = "key"
	settings.r2_secret_access_key = "secret"
	settings.r2_bucket_name = "gbedu"
	settings.r2_public_url = "https://cdn.gbedu.io"

	client = R2Client(settings=settings)

	mock_s3 = MagicMock()
	mock_s3.delete_object.side_effect = Exception("permission denied")

	mock_loop = MagicMock()

	async def _fake_run_in_executor(executor: Any, fn: Any) -> None:
		fn()

	mock_loop.run_in_executor = _fake_run_in_executor

	with (
		patch("boto3.client", return_value=mock_s3),
		patch("asyncio.get_event_loop", return_value=mock_loop),
	):
		with pytest.raises(UploadError, match="R2 delete failed"):
			await client.delete(key="tracks/t1/audio.mp3")


async def test_r2_generate_presigned_url() -> None:
	from gbedu_core.config import StorageSettings
	from gbedu_worker.storage import R2Client

	settings = MagicMock(spec=StorageSettings)
	settings.r2_endpoint_url = "https://r2.cloudflare.com"
	settings.r2_access_key_id = "key"
	settings.r2_secret_access_key = "secret"
	settings.r2_bucket_name = "gbedu"
	settings.r2_public_url = "https://cdn.gbedu.io"

	client = R2Client(settings=settings)

	expected_url = "https://r2.cloudflare.com/gbedu/key?sig=abc"
	mock_s3 = MagicMock()
	mock_s3.generate_presigned_url.return_value = expected_url

	mock_loop = MagicMock()

	async def _fake_run_in_executor(executor: Any, fn: Any) -> str:
		return fn()

	mock_loop.run_in_executor = _fake_run_in_executor

	with (
		patch("boto3.client", return_value=mock_s3),
		patch("asyncio.get_event_loop", return_value=mock_loop),
	):
		url = await client.generate_presigned_url(key="tracks/t1/audio.mp3", expires_in=3600)

	assert url == expected_url
