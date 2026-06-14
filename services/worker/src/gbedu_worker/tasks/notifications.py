from __future__ import annotations

"""Email notification tasks — all on the `low` queue.

Tasks are idempotent via Redis dedup keys (24 h TTL). A second enqueue for
the same (user, event) pair within the window is a no-op. This prevents
duplicate emails from Celery retries or accidental double-enqueue.
"""

from typing import Any

import structlog
from celery import Task
from opentelemetry import trace
from sqlalchemy import select

from gbedu_core.config import EmailSettings, RedisSettings
from gbedu_core.models.track import Track
from gbedu_core.models.user import User
from gbedu_core.telemetry import get_tracer, increment_error_count
from gbedu_worker.celery_app import app
from gbedu_worker.db import get_async_session, run_async

log = structlog.get_logger(__name__)
tracer = get_tracer(__name__)

_redis_settings = RedisSettings()
_email_settings = EmailSettings()

_EMAIL_DEDUP_TTL = 86_400  # 24 h


# ── Task definitions ───────────────────────────────────────────────────────────

@app.task(
	bind=True,
	name="gbedu_worker.tasks.notifications.send_generation_complete_email",
	max_retries=3,
	acks_late=True,
	queue="low",
	soft_time_limit=30,
	time_limit=45,
)
def send_generation_complete_email(self: Task, user_id: str, track_id: str) -> dict[str, Any]:
	"""Send 'your track is ready' email to the user."""
	assert user_id, "user_id required"
	assert track_id, "track_id required"

	task_log = log.bind(user_id=user_id, track_id=track_id, task_id=self.request.id)
	task_log.info("send_generation_complete_email task received")

	with tracer.start_as_current_span("task.send_generation_complete_email") as span:
		span.set_attribute("user.id", user_id)
		span.set_attribute("track.id", track_id)
		try:
			return run_async(_send_generation_complete(user_id, track_id))
		except Exception as exc:
			task_log.error("email task failed", exc_type=type(exc).__name__, exc_msg=str(exc))
			increment_error_count(error_code=type(exc).__name__, service="worker.notifications")
			span.record_exception(exc)
			span.set_status(trace.StatusCode.ERROR, str(exc))
			raise self.retry(exc=exc, countdown=_email_retry_countdown(self.request.retries))


@app.task(
	bind=True,
	name="gbedu_worker.tasks.notifications.send_welcome_email",
	max_retries=3,
	acks_late=True,
	queue="low",
	soft_time_limit=30,
	time_limit=45,
)
def send_welcome_email(self: Task, user_id: str) -> dict[str, Any]:
	"""Send the onboarding welcome email to a newly registered user."""
	assert user_id, "user_id required"

	task_log = log.bind(user_id=user_id, task_id=self.request.id)
	task_log.info("send_welcome_email task received")

	with tracer.start_as_current_span("task.send_welcome_email") as span:
		span.set_attribute("user.id", user_id)
		try:
			return run_async(_send_welcome(user_id))
		except Exception as exc:
			task_log.error("email task failed", exc_type=type(exc).__name__, exc_msg=str(exc))
			increment_error_count(error_code=type(exc).__name__, service="worker.notifications")
			span.record_exception(exc)
			span.set_status(trace.StatusCode.ERROR, str(exc))
			raise self.retry(exc=exc, countdown=_email_retry_countdown(self.request.retries))


@app.task(
	bind=True,
	name="gbedu_worker.tasks.notifications.send_subscription_confirmation",
	max_retries=3,
	acks_late=True,
	queue="low",
	soft_time_limit=30,
	time_limit=45,
)
def send_subscription_confirmation(self: Task, user_id: str, tier: str) -> dict[str, Any]:
	"""Send subscription upgrade / new subscription confirmation email."""
	assert user_id, "user_id required"
	assert tier, "tier required"

	task_log = log.bind(user_id=user_id, tier=tier, task_id=self.request.id)
	task_log.info("send_subscription_confirmation task received")

	with tracer.start_as_current_span("task.send_subscription_confirmation") as span:
		span.set_attribute("user.id", user_id)
		span.set_attribute("subscription.tier", tier)
		try:
			return run_async(_send_subscription_confirmation(user_id, tier))
		except Exception as exc:
			task_log.error("email task failed", exc_type=type(exc).__name__, exc_msg=str(exc))
			increment_error_count(error_code=type(exc).__name__, service="worker.notifications")
			span.record_exception(exc)
			span.set_status(trace.StatusCode.ERROR, str(exc))
			raise self.retry(exc=exc, countdown=_email_retry_countdown(self.request.retries))


# ── Async implementations ──────────────────────────────────────────────────────

async def _send_generation_complete(user_id: str, track_id: str) -> dict[str, Any]:
	dedup_key = f"email:gen_complete:{user_id}:{track_id}"
	if await _already_sent(dedup_key):
		log.info("generation_complete email already sent — skipping", user_id=user_id, track_id=track_id)
		return {"status": "skipped", "reason": "duplicate"}

	async with get_async_session() as session:
		user = await session.get(User, user_id)
		track = await session.get(Track, track_id)

		if user is None:
			log.warning("send_generation_complete_email: user not found", user_id=user_id)
			return {"status": "skipped", "reason": "user_not_found"}
		if track is None:
			log.warning("send_generation_complete_email: track not found", track_id=track_id)
			return {"status": "skipped", "reason": "track_not_found"}

		email_svc = _build_email_service()
		await email_svc.send(
			to=user.email,
			subject="Your Gbẹdu track is ready 🎵",
			template="generation_complete",
			context={
				"user_name": user.full_name.split()[0],
				"track_title": track.title,
				"track_url": f"https://app.gbedu.io/tracks/{track_id}",
				"audio_url": track.audio_url,
				"preview_url": track.audio_url_watermarked,
			},
		)

	await _mark_sent(dedup_key)
	log.info("generation_complete email sent", user_id=user_id, track_id=track_id)
	return {"status": "sent", "user_id": user_id, "track_id": track_id}


async def _send_welcome(user_id: str) -> dict[str, Any]:
	dedup_key = f"email:welcome:{user_id}"
	if await _already_sent(dedup_key):
		log.info("welcome email already sent — skipping", user_id=user_id)
		return {"status": "skipped", "reason": "duplicate"}

	async with get_async_session() as session:
		user = await session.get(User, user_id)
		if user is None:
			log.warning("send_welcome_email: user not found", user_id=user_id)
			return {"status": "skipped", "reason": "user_not_found"}

		email_svc = _build_email_service()
		await email_svc.send(
			to=user.email,
			subject="Welcome to Gbẹdu — let's make something",
			template="welcome",
			context={
				"user_name": user.full_name.split()[0],
				"dashboard_url": "https://app.gbedu.io/dashboard",
				"docs_url": "https://docs.gbedu.io",
			},
		)

	await _mark_sent(dedup_key)
	log.info("welcome email sent", user_id=user_id)
	return {"status": "sent", "user_id": user_id}


async def _send_subscription_confirmation(user_id: str, tier: str) -> dict[str, Any]:
	dedup_key = f"email:sub_confirm:{user_id}:{tier}"
	if await _already_sent(dedup_key):
		log.info("subscription_confirmation email already sent — skipping", user_id=user_id, tier=tier)
		return {"status": "skipped", "reason": "duplicate"}

	async with get_async_session() as session:
		user = await session.get(User, user_id)
		if user is None:
			log.warning("send_subscription_confirmation: user not found", user_id=user_id)
			return {"status": "skipped", "reason": "user_not_found"}

		tier_display = tier.replace("_", " ").title()
		email_svc = _build_email_service()
		await email_svc.send(
			to=user.email,
			subject=f"You're now on the {tier_display} plan",
			template="subscription_confirmation",
			context={
				"user_name": user.full_name.split()[0],
				"tier": tier_display,
				"dashboard_url": "https://app.gbedu.io/dashboard",
				"billing_url": "https://app.gbedu.io/settings/billing",
			},
		)

	await _mark_sent(dedup_key)
	log.info("subscription_confirmation email sent", user_id=user_id, tier=tier)
	return {"status": "sent", "user_id": user_id, "tier": tier}


# ── Email service builder ──────────────────────────────────────────────────────

def _build_email_service() -> _SmtpEmailService:
	return _SmtpEmailService(settings=_email_settings)


class _SmtpEmailService:
	"""Thin async SMTP wrapper. Production should swap for Mailgun/SendGrid SDK."""

	def __init__(self, settings: EmailSettings) -> None:
		self._settings = settings

	async def send(
		self,
		*,
		to: str,
		subject: str,
		template: str,
		context: dict[str, Any],
	) -> None:
		import smtplib
		from email.mime.multipart import MIMEMultipart
		from email.mime.text import MIMEText
		import asyncio

		body = self._render_template(template, context)

		msg = MIMEMultipart("alternative")
		msg["Subject"] = subject
		msg["From"] = self._settings.from_email
		msg["To"] = to
		msg.attach(MIMEText(body, "html"))

		# Run blocking SMTP in executor so we don't block the event loop
		loop = asyncio.get_event_loop()
		await loop.run_in_executor(None, self._send_smtp, to, msg)

	def _send_smtp(self, to: str, msg: Any) -> None:
		import smtplib
		with smtplib.SMTP(self._settings.smtp_host, self._settings.smtp_port) as server:
			if self._settings.use_tls:
				server.starttls()
			if self._settings.smtp_user:
				server.login(self._settings.smtp_user, self._settings.smtp_password)
			server.sendmail(self._settings.from_email, to, msg.as_string())

	@staticmethod
	def _render_template(template: str, context: dict[str, Any]) -> str:
		# Minimal template rendering — replace {key} placeholders.
		# Production: use Jinja2 with HTML email templates.
		lines = [f"<p>{k}: {v}</p>" for k, v in context.items()]
		return f"<html><body>{''.join(lines)}</body></html>"


# ── Redis dedup helpers ────────────────────────────────────────────────────────

async def _already_sent(key: str) -> bool:
	import redis.asyncio as aioredis
	r = await aioredis.from_url(_redis_settings.url, encoding="utf-8", decode_responses=True)
	async with r:
		return bool(await r.exists(f"email_sent:{key}"))


async def _mark_sent(key: str) -> None:
	import redis.asyncio as aioredis
	r = await aioredis.from_url(_redis_settings.url, encoding="utf-8", decode_responses=True)
	async with r:
		await r.setex(f"email_sent:{key}", _EMAIL_DEDUP_TTL, "1")


def _email_retry_countdown(retry_num: int) -> int:
	return (15, 60, 300)[min(retry_num, 2)]
