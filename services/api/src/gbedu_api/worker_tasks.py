from __future__ import annotations

"""Thin shim that imports Celery task functions from the worker package.

The worker package is deployed separately and may not be installed in the API
virtualenv. All calls are wrapped so that ImportError degrades gracefully —
the job record is already persisted in the DB and a supervisor can re-queue it.
"""

import structlog

log = structlog.get_logger(__name__)


def enqueue_generation(job_id: str) -> None:
	assert job_id, "job_id required"
	try:
		from gbedu_worker.tasks.generation import generate_track
		generate_track.delay(job_id)
		log.info("worker.enqueue.generation", job_id=job_id)
	except ImportError:
		log.warning("worker.not_installed", task="generate_track", job_id=job_id)


def revoke_task(celery_task_id: str) -> None:
	assert celery_task_id, "celery_task_id required"
	try:
		from gbedu_worker.app import celery_app
		celery_app.control.revoke(celery_task_id, terminate=True)
		log.info("worker.revoke", celery_task_id=celery_task_id)
	except ImportError:
		log.warning("worker.not_installed", task="revoke", celery_task_id=celery_task_id)


def enqueue_voice_training(voice_model_id: str) -> None:
	assert voice_model_id, "voice_model_id required"
	try:
		from gbedu_worker.tasks.voice import train_voice_model
		train_voice_model.delay(voice_model_id)
		log.info("worker.enqueue.voice_training", voice_model_id=voice_model_id)
	except ImportError:
		log.warning("worker.not_installed", task="train_voice_model", voice_model_id=voice_model_id)
