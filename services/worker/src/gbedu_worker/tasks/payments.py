from __future__ import annotations

"""Payment webhook processing tasks.

Both Stripe and Paystack webhooks are delivered via the `high` queue.
Every handler is IDEMPOTENT: the event ID / reference is checked against a
Redis set before any DB writes. Duplicate deliveries are a no-op.

Idempotency key TTL: 72 h (well past any realistic retry window from either
payment provider).
"""

from datetime import datetime, timezone
from typing import Any

import structlog
from celery import Task
from opentelemetry import trace
from sqlalchemy import select

from gbedu_core.config import RedisSettings
from gbedu_core.models.payment import (
	Payment,
	PaymentProvider,
	PaymentStatus,
	Subscription,
	SubscriptionInterval,
)
from gbedu_core.models.user import SubscriptionStatus, SubscriptionTier, User
from gbedu_core.telemetry import get_tracer, increment_error_count
from gbedu_worker.celery_app import app
from gbedu_worker.db import get_async_session, run_async

log = structlog.get_logger(__name__)
tracer = get_tracer(__name__)

_redis_settings = RedisSettings()

# How long idempotency keys live in Redis (seconds)
_IDEMPOTENCY_TTL = 72 * 3600


# ── Stripe ─────────────────────────────────────────────────────────────────────

@app.task(
	bind=True,
	name="gbedu_worker.tasks.payments.process_stripe_webhook",
	max_retries=5,
	acks_late=True,
	reject_on_worker_lost=True,
	queue="high",
	soft_time_limit=60,
	time_limit=90,
)
def process_stripe_webhook(
	self: Task,
	event_id: str,
	event_type: str,
	event_data: dict[str, Any],
) -> dict[str, Any]:
	"""Process a Stripe webhook event. Idempotent on event_id."""
	assert event_id, "event_id must not be empty"
	assert event_type, "event_type must not be empty"

	task_log = log.bind(event_id=event_id, event_type=event_type, task_id=self.request.id)
	task_log.info("stripe webhook task received")

	with tracer.start_as_current_span("task.process_stripe_webhook") as span:
		span.set_attribute("stripe.event_id", event_id)
		span.set_attribute("stripe.event_type", event_type)

		try:
			result = run_async(_handle_stripe_event(event_id, event_type, event_data))
			return result
		except Exception as exc:  # pragma: no cover
			task_log.error(
				"stripe webhook processing failed",
				exc_type=type(exc).__name__,
				exc_msg=str(exc),
			)
			increment_error_count(error_code=type(exc).__name__, service="worker.payments.stripe")
			span.record_exception(exc)
			span.set_status(trace.StatusCode.ERROR, str(exc))
			raise self.retry(
				exc=exc,
				countdown=_stripe_retry_countdown(self.request.retries),
			)


async def _handle_stripe_event(  # pragma: no cover
	event_id: str,
	event_type: str,
	event_data: dict[str, Any],
) -> dict[str, Any]:
	if await _already_processed(f"stripe:{event_id}"):
		log.info("stripe event already processed — skipping", event_id=event_id)
		return {"status": "skipped", "reason": "duplicate", "event_id": event_id}

	async with get_async_session() as session:
		obj = event_data.get("object", {})

		if event_type == "customer.subscription.created":
			await _stripe_subscription_upsert(session, obj, "active")

		elif event_type == "customer.subscription.updated":
			await _stripe_subscription_upsert(session, obj, obj.get("status", "active"))

		elif event_type == "customer.subscription.deleted":
			await _stripe_subscription_upsert(session, obj, "cancelled")
			await _update_user_subscription(
				session,
				stripe_customer_id=obj.get("customer"),
				tier=SubscriptionTier.free,
				status=SubscriptionStatus.cancelled,
			)

		elif event_type == "invoice.payment_succeeded":
			await _stripe_record_payment(session, obj, PaymentStatus.succeeded)

		elif event_type == "invoice.payment_failed":
			await _stripe_record_payment(session, obj, PaymentStatus.failed)
			await _update_user_subscription(
				session,
				stripe_customer_id=obj.get("customer"),
				tier=None,
				status=SubscriptionStatus.past_due,
			)

		elif event_type == "checkout.session.completed":
			await _stripe_checkout_completed(session, obj)

		else:
			log.debug("stripe event type not handled", event_type=event_type)
			await _mark_processed(f"stripe:{event_id}")
			return {"status": "ignored", "event_type": event_type}

	await _mark_processed(f"stripe:{event_id}")
	return {"status": "ok", "event_id": event_id, "event_type": event_type}


async def _stripe_subscription_upsert(  # pragma: no cover
	session: Any,
	obj: dict[str, Any],
	new_status: str,
) -> None:
	provider_sub_id: str = obj.get("id", "")
	assert provider_sub_id, "subscription object missing id"

	result = await session.execute(
		select(Subscription).where(Subscription.provider_subscription_id == provider_sub_id)
	)
	sub: Subscription | None = result.scalar_one_or_none()

	tier = _stripe_plan_to_tier(obj)

	if sub is None:
		# First time we see this subscription — need the user
		stripe_customer_id: str = obj.get("customer", "")
		user_result = await session.execute(
			select(User).where(User.stripe_customer_id == stripe_customer_id)
		)
		user: User | None = user_result.scalar_one_or_none()
		if user is None:
			log.warning(
				"stripe subscription: no user for customer",
				customer_id=stripe_customer_id,
				provider_sub_id=provider_sub_id,
			)
			return

		from gbedu_core._uuid7 import uuid7str

		sub = Subscription(
			id=uuid7str(),
			user_id=user.id,
			provider=PaymentProvider.stripe,
			provider_subscription_id=provider_sub_id,
			provider_plan_id=obj.get("plan", {}).get("id", "") or obj.get("items", {}).get("data", [{}])[0].get("price", {}).get("id", ""),
			tier=tier.value,
			interval=_stripe_interval(obj),
			status=new_status,
			amount_minor=obj.get("plan", {}).get("amount", 0) or 0,
			currency=(obj.get("currency") or "USD").upper(),
			current_period_start=_ts(obj.get("current_period_start", 0)),
			current_period_end=_ts(obj.get("current_period_end", 0)),
			cancel_at_period_end=obj.get("cancel_at_period_end", False),
		)
		session.add(sub)
	else:
		sub.status = new_status
		sub.current_period_start = _ts(obj.get("current_period_start", 0))
		sub.current_period_end = _ts(obj.get("current_period_end", 0))
		sub.cancel_at_period_end = obj.get("cancel_at_period_end", False)
		if obj.get("canceled_at"):
			sub.cancelled_at = _ts(obj["canceled_at"])
		session.add(sub)

	# Sync user tier when subscription is active/trialing
	if new_status in ("active", "trialing"):
		await _update_user_subscription(
			session,
			stripe_customer_id=obj.get("customer"),
			tier=tier,
			status=SubscriptionStatus.active if new_status == "active" else SubscriptionStatus.trialing,
		)

	await session.flush()
	log.info(
		"stripe subscription upserted",
		provider_sub_id=provider_sub_id,
		tier=tier.value,
		status=new_status,
	)


async def _stripe_record_payment(  # pragma: no cover
	session: Any,
	invoice_obj: dict[str, Any],
	status: PaymentStatus,
) -> None:
	provider_payment_id: str = invoice_obj.get("payment_intent") or invoice_obj.get("id", "")
	if not provider_payment_id:
		log.warning("stripe invoice missing payment_intent and id — skipping")
		return

	result = await session.execute(
		select(Payment).where(Payment.provider_payment_id == provider_payment_id)
	)
	existing: Payment | None = result.scalar_one_or_none()
	if existing is not None:
		existing.status = status
		if status == PaymentStatus.succeeded:
			existing.paid_at = datetime.now(timezone.utc)
		session.add(existing)
		await session.flush()
		return

	stripe_customer_id: str = invoice_obj.get("customer", "")
	user_result = await session.execute(
		select(User).where(User.stripe_customer_id == stripe_customer_id)
	)
	user: User | None = user_result.scalar_one_or_none()
	if user is None:
		log.warning(
			"stripe payment: no user for customer",
			customer_id=stripe_customer_id,
		)
		return

	from gbedu_core._uuid7 import uuid7str

	payment = Payment(
		id=uuid7str(),
		user_id=user.id,
		provider=PaymentProvider.stripe,
		provider_payment_id=provider_payment_id,
		status=status,
		amount_minor=invoice_obj.get("amount_paid", 0) or invoice_obj.get("total", 0),
		currency=(invoice_obj.get("currency") or "usd").upper(),
		description=f"Stripe invoice {invoice_obj.get('id', '')}",
		paid_at=datetime.now(timezone.utc) if status == PaymentStatus.succeeded else None,
	)
	session.add(payment)
	await session.flush()
	log.info("stripe payment recorded", provider_payment_id=provider_payment_id, status=status.value)


async def _stripe_checkout_completed(session: Any, obj: dict[str, Any]) -> None:  # pragma: no cover
	mode: str = obj.get("mode", "")
	if mode != "subscription":
		log.debug("checkout.session.completed: not a subscription checkout — skipping", mode=mode)
		return

	# Subscription creation is handled by customer.subscription.created
	# which fires in the same batch. No extra action needed here unless
	# we want to provision free-trial access before the sub event arrives.
	log.info("checkout.session.completed acknowledged", session_id=obj.get("id"))


async def _update_user_subscription(  # pragma: no cover
	session: Any,
	*,
	stripe_customer_id: str | None,
	tier: SubscriptionTier | None,
	status: SubscriptionStatus,
) -> None:
	if not stripe_customer_id:
		return

	result = await session.execute(
		select(User).where(User.stripe_customer_id == stripe_customer_id)
	)
	user: User | None = result.scalar_one_or_none()
	if user is None:
		log.warning("update_user_subscription: user not found", stripe_customer_id=stripe_customer_id)
		return

	if tier is not None:
		user.subscription_tier = tier
	user.subscription_status = status
	session.add(user)
	await session.flush()
	log.info(
		"user subscription updated",
		user_id=user.id,
		tier=tier.value if tier else "unchanged",
		status=status.value,
	)


# ── Paystack ───────────────────────────────────────────────────────────────────

@app.task(
	bind=True,
	name="gbedu_worker.tasks.payments.process_paystack_webhook",
	max_retries=5,
	acks_late=True,
	reject_on_worker_lost=True,
	queue="high",
	soft_time_limit=60,
	time_limit=90,
)
def process_paystack_webhook(
	self: Task,
	event: str,
	data: dict[str, Any],
) -> dict[str, Any]:
	"""Process a Paystack webhook event. Idempotent on data.reference."""
	assert event, "event must not be empty"

	reference: str = data.get("reference", "") or data.get("id", "")
	task_log = log.bind(event=event, reference=reference, task_id=self.request.id)
	task_log.info("paystack webhook task received")

	with tracer.start_as_current_span("task.process_paystack_webhook") as span:
		span.set_attribute("paystack.event", event)
		span.set_attribute("paystack.reference", reference)

		try:
			result = run_async(_handle_paystack_event(event, data, reference))
			return result
		except Exception as exc:  # pragma: no cover
			task_log.error(
				"paystack webhook processing failed",
				exc_type=type(exc).__name__,
				exc_msg=str(exc),
			)
			increment_error_count(error_code=type(exc).__name__, service="worker.payments.paystack")
			span.record_exception(exc)
			span.set_status(trace.StatusCode.ERROR, str(exc))
			raise self.retry(
				exc=exc,
				countdown=_paystack_retry_countdown(self.request.retries),
			)


async def _handle_paystack_event(  # pragma: no cover
	event: str,
	data: dict[str, Any],
	reference: str,
) -> dict[str, Any]:
	idempotency_key = f"paystack:{event}:{reference}"
	if await _already_processed(idempotency_key):
		log.info("paystack event already processed — skipping", paystack_event=event, reference=reference)
		return {"status": "skipped", "reason": "duplicate", "reference": reference}

	async with get_async_session() as session:
		if event == "charge.success":
			await _paystack_charge_success(session, data)

		elif event == "subscription.create":
			await _paystack_subscription_create(session, data)

		elif event == "subscription.disable":
			await _paystack_subscription_disable(session, data)

		else:
			log.debug("paystack event type not handled", paystack_event=event)
			await _mark_processed(idempotency_key)
			return {"status": "ignored", "event": event}

	await _mark_processed(idempotency_key)
	return {"status": "ok", "event": event, "reference": reference}


async def _paystack_charge_success(session: Any, data: dict[str, Any]) -> None:  # pragma: no cover
	reference: str = data.get("reference", "")
	assert reference, "charge.success missing reference"

	# Check idempotency at DB level too
	result = await session.execute(
		select(Payment).where(Payment.provider_payment_id == reference)
	)
	if result.scalar_one_or_none() is not None:
		log.info("paystack charge already recorded", reference=reference)
		return

	customer_code: str = data.get("customer", {}).get("customer_code", "")
	user_result = await session.execute(
		select(User).where(User.paystack_customer_code == customer_code)
	)
	user: User | None = user_result.scalar_one_or_none()
	if user is None:
		email: str = data.get("customer", {}).get("email", "")
		if email:
			user_result = await session.execute(select(User).where(User.email == email))
			user = user_result.scalar_one_or_none()

	if user is None:
		log.warning("paystack charge.success: user not found", reference=reference, customer_code=customer_code)
		return

	from gbedu_core._uuid7 import uuid7str

	amount_kobo: int = data.get("amount", 0)
	currency: str = (data.get("currency") or "NGN").upper()

	payment = Payment(
		id=uuid7str(),
		user_id=user.id,
		provider=PaymentProvider.paystack,
		provider_payment_id=reference,
		status=PaymentStatus.succeeded,
		amount_minor=amount_kobo,
		currency=currency,
		description=f"Paystack charge {reference}",
		paid_at=datetime.now(timezone.utc),
	)
	session.add(payment)
	await session.flush()
	log.info("paystack charge recorded", reference=reference, amount_kobo=amount_kobo)


async def _paystack_subscription_create(session: Any, data: dict[str, Any]) -> None:  # pragma: no cover
	sub_code: str = data.get("subscription_code", "")
	plan_code: str = data.get("plan", {}).get("plan_code", "")
	customer_code: str = data.get("customer", {}).get("customer_code", "")

	user_result = await session.execute(
		select(User).where(User.paystack_customer_code == customer_code)
	)
	user: User | None = user_result.scalar_one_or_none()
	if user is None:
		log.warning("paystack subscription.create: user not found", customer_code=customer_code)
		return

	# Idempotent: skip if already recorded
	existing_result = await session.execute(
		select(Subscription).where(Subscription.provider_subscription_id == sub_code)
	)
	if existing_result.scalar_one_or_none() is not None:
		log.info("paystack subscription already exists", sub_code=sub_code)
		return

	from gbedu_core._uuid7 import uuid7str

	tier = _paystack_plan_to_tier(plan_code)
	amount_kobo: int = data.get("amount", 0)

	sub = Subscription(
		id=uuid7str(),
		user_id=user.id,
		provider=PaymentProvider.paystack,
		provider_subscription_id=sub_code,
		provider_plan_id=plan_code,
		tier=tier.value,
		interval=SubscriptionInterval.month,
		status="active",
		amount_minor=amount_kobo,
		currency="NGN",
		current_period_start=datetime.now(timezone.utc),
		current_period_end=_paystack_next_billing(data),
	)
	session.add(sub)

	user.subscription_tier = tier
	user.subscription_status = SubscriptionStatus.active
	session.add(user)

	await session.flush()
	log.info(
		"paystack subscription created",
		sub_code=sub_code,
		user_id=user.id,
		tier=tier.value,
	)


async def _paystack_subscription_disable(session: Any, data: dict[str, Any]) -> None:  # pragma: no cover
	sub_code: str = data.get("subscription_code", "")
	customer_code: str = data.get("customer", {}).get("customer_code", "")

	sub_result = await session.execute(
		select(Subscription).where(Subscription.provider_subscription_id == sub_code)
	)
	sub: Subscription | None = sub_result.scalar_one_or_none()

	if sub is None:
		log.warning("paystack subscription.disable: subscription not found", sub_code=sub_code)
		return

	sub.status = "cancelled"
	sub.cancelled_at = datetime.now(timezone.utc)
	session.add(sub)

	user_result = await session.execute(
		select(User).where(User.paystack_customer_code == customer_code)
	)
	user: User | None = user_result.scalar_one_or_none()
	if user is not None:
		user.subscription_tier = SubscriptionTier.free
		user.subscription_status = SubscriptionStatus.cancelled
		session.add(user)

	await session.flush()
	log.info("paystack subscription disabled", sub_code=sub_code)


# ── Redis idempotency helpers ──────────────────────────────────────────────────

async def _already_processed(key: str) -> bool:  # pragma: no cover
	import redis.asyncio as aioredis
	r = await aioredis.from_url(_redis_settings.url, encoding="utf-8", decode_responses=True)
	async with r:
		return bool(await r.exists(f"webhook_processed:{key}"))


async def _mark_processed(key: str) -> None:  # pragma: no cover
	import redis.asyncio as aioredis
	r = await aioredis.from_url(_redis_settings.url, encoding="utf-8", decode_responses=True)
	async with r:
		await r.setex(f"webhook_processed:{key}", _IDEMPOTENCY_TTL, "1")


# ── Stripe helpers ─────────────────────────────────────────────────────────────

_STRIPE_PLAN_TIER_MAP: dict[str, SubscriptionTier] = {}


def _stripe_plan_to_tier(obj: dict[str, Any]) -> SubscriptionTier:
	from gbedu_core.config import StripeSettings
	stripe_cfg = StripeSettings()

	# Try to resolve from price ID on the plan or first item
	plan = obj.get("plan") or {}
	price_id: str = (
		plan.get("id", "")
		or (obj.get("items", {}).get("data", [{}])[0].get("price", {}).get("id", ""))
	)

	if price_id == stripe_cfg.price_id_creator:
		return SubscriptionTier.creator
	if price_id == stripe_cfg.price_id_pro:
		return SubscriptionTier.pro
	if price_id == stripe_cfg.price_id_label:
		return SubscriptionTier.label

	# Fallback: infer from metadata
	meta_tier: str = obj.get("metadata", {}).get("tier", "")
	try:
		return SubscriptionTier(meta_tier)
	except ValueError:
		return SubscriptionTier.creator


def _stripe_interval(obj: dict[str, Any]) -> SubscriptionInterval:
	plan = obj.get("plan") or {}
	interval: str = plan.get("interval", "month")
	return SubscriptionInterval.year if interval == "year" else SubscriptionInterval.month


def _stripe_retry_countdown(retry_num: int) -> int:
	return (10, 30, 60, 120, 300)[min(retry_num, 4)]


# ── Paystack helpers ───────────────────────────────────────────────────────────

# Maps Paystack plan codes (env-configured prefix) to tiers.
# In production these codes are set via PAYSTACK_PLAN_CODE_<TIER> env vars.
_PAYSTACK_PLAN_TIERS: dict[str, SubscriptionTier] = {
	"creator": SubscriptionTier.creator,
	"pro": SubscriptionTier.pro,
	"label": SubscriptionTier.label,
}


def _paystack_plan_to_tier(plan_code: str) -> SubscriptionTier:
	plan_lower = plan_code.lower()
	for keyword, tier in _PAYSTACK_PLAN_TIERS.items():
		if keyword in plan_lower:
			return tier
	return SubscriptionTier.creator


def _paystack_next_billing(data: dict[str, Any]) -> datetime:
	from dateutil.parser import parse as parse_dt
	next_date = data.get("next_payment_date")
	if next_date:
		try:
			return parse_dt(next_date).replace(tzinfo=timezone.utc)
		except ValueError:
			pass
	from datetime import timedelta
	return datetime.now(timezone.utc) + timedelta(days=30)


def _paystack_retry_countdown(retry_num: int) -> int:
	return (10, 30, 60, 120, 300)[min(retry_num, 4)]


# ── Shared ─────────────────────────────────────────────────────────────────────

def _ts(unix_ts: int | float) -> datetime:
	"""Convert a Unix timestamp to a timezone-aware datetime."""
	return datetime.fromtimestamp(unix_ts, tz=timezone.utc)
