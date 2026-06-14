from __future__ import annotations

"""Celery task registry — import all task modules so Celery discovers them."""

from gbedu_worker.tasks.audio import create_preview, process_stems, remaster_track
from gbedu_worker.tasks.cleanup import (
	cleanup_expired_temp_files,
	reset_daily_generation_counts,
	retry_failed_distributions,
)
from gbedu_worker.tasks.generation import run_generation_pipeline
from gbedu_worker.tasks.notifications import (
	send_generation_complete_email,
	send_subscription_confirmation,
	send_welcome_email,
)
from gbedu_worker.tasks.payments import process_paystack_webhook, process_stripe_webhook

__all__ = [
	# generation
	"run_generation_pipeline",
	# audio
	"process_stems",
	"remaster_track",
	"create_preview",
	# payments
	"process_stripe_webhook",
	"process_paystack_webhook",
	# notifications
	"send_generation_complete_email",
	"send_welcome_email",
	"send_subscription_confirmation",
	# cleanup
	"cleanup_expired_temp_files",
	"reset_daily_generation_counts",
	"retry_failed_distributions",
]
