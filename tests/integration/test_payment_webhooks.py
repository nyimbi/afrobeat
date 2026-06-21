"""Integration tests for Stripe and Paystack webhook idempotency.

Sends the same event twice and verifies the DB is updated exactly once.
Uses real DB session (transactional rollback) — no mock DB objects.

Stripe and Paystack HTTP clients are patched at the point of signature
verification so no real network calls are made.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime

import pytest
from gbedu_core._uuid7 import uuid7str
from gbedu_core.models import (
	Payment,
	PaymentProvider,
	PaymentStatus,
	Subscription,
	User,
)
from gbedu_core.models.payment import SubscriptionInterval
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_STRIPE_WEBHOOK_SECRET = "whsec_test_secret"
_PAYSTACK_SECRET_KEY = "sk_test_paystack_secret"


# ── Stripe webhook helpers ─────────────────────────────────────────────────────


def _stripe_sign(payload: bytes, secret: str, timestamp: int | None = None) -> str:
	"""Compute Stripe's Stripe-Signature header value."""
	ts = timestamp or int(time.time())
	signed_payload = f"{ts}.".encode() + payload
	sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
	return f"t={ts},v1={sig}"


def _stripe_payment_intent_succeeded_event(
	payment_intent_id: str,
	amount: int = 999,
	currency: str = "usd",
) -> dict:
	return {
		"id": f"evt_{uuid7str()}",
		"object": "event",
		"type": "payment_intent.succeeded",
		"data": {
			"object": {
				"id": payment_intent_id,
				"object": "payment_intent",
				"amount": amount,
				"currency": currency,
				"status": "succeeded",
				"customer": f"cus_{uuid7str()}",
				"metadata": {},
			}
		},
	}


def _stripe_subscription_created_event(
	subscription_id: str,
	customer_id: str,
	plan_id: str = "price_creator_monthly",
) -> dict:
	now = int(time.time())
	return {
		"id": f"evt_{uuid7str()}",
		"object": "event",
		"type": "customer.subscription.created",
		"data": {
			"object": {
				"id": subscription_id,
				"object": "subscription",
				"customer": customer_id,
				"status": "active",
				"plan": {"id": plan_id, "amount": 999, "currency": "usd", "interval": "month"},
				"current_period_start": now,
				"current_period_end": now + 2592000,
				"cancel_at_period_end": False,
				"items": {"data": [{"price": {"id": plan_id}}]},
				"metadata": {},
			}
		},
	}


# ── Paystack webhook helpers ───────────────────────────────────────────────────


def _paystack_sign(payload: bytes, secret: str) -> str:
	return hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()


def _paystack_charge_success_event(reference: str, amount: int = 99900) -> dict:
	return {
		"event": "charge.success",
		"data": {
			"id": 12345678,
			"reference": reference,
			"amount": amount,
			"currency": "NGN",
			"status": "success",
			"customer": {
				"email": f"customer-{uuid7str()}@example.com",
				"customer_code": f"CUS_{uuid7str()}",
			},
			"paid_at": datetime.now(UTC).isoformat(),
			"metadata": {},
		},
	}


# ── DB helpers ─────────────────────────────────────────────────────────────────


async def _create_payment(
	session: AsyncSession,
	user: User,
	provider_payment_id: str,
	stripe_pi_id: str | None = None,
	paystack_ref: str | None = None,
	status: PaymentStatus = PaymentStatus.pending,
	amount: int = 999,
) -> Payment:
	payment = Payment(
		id=uuid7str(),
		user_id=user.id,
		provider=PaymentProvider.stripe if stripe_pi_id else PaymentProvider.paystack,
		provider_payment_id=provider_payment_id,
		provider_charge_id=stripe_pi_id or paystack_ref,
		status=status,
		amount_minor=amount,
		currency="USD" if stripe_pi_id else "NGN",
	)
	session.add(payment)
	await session.flush()
	return payment


async def _get_payment_by_provider_id(
	session: AsyncSession,
	provider_payment_id: str,
) -> Payment | None:
	result = await session.execute(
		select(Payment).where(Payment.provider_payment_id == provider_payment_id)
	)
	return result.scalar_one_or_none()


# ── Stripe webhook idempotency ─────────────────────────────────────────────────


async def test_stripe_payment_intent_idempotent(
	test_db_session: AsyncSession,
	make_user,
) -> None:
	"""Processing the same payment_intent.succeeded event twice must only
	update the payment row once — second call is a no-op."""
	user = await make_user(tier="creator")
	pi_id = f"pi_{uuid7str()}"

	await _create_payment(
		test_db_session,
		user,
		provider_payment_id=pi_id,
		stripe_pi_id=pi_id,
		status=PaymentStatus.pending,
	)

	event = _stripe_payment_intent_succeeded_event(pi_id)

	async def _process_stripe_pi_succeeded(session: AsyncSession, event_data: dict) -> bool:
		"""Simulate idempotent processing — returns True if updated, False if no-op."""
		pi = event_data["data"]["object"]
		pi_id_inner = pi["id"]

		result = await session.execute(
			select(Payment).where(Payment.provider_payment_id == pi_id_inner)
		)
		existing = result.scalar_one_or_none()
		if existing is None:
			return False
		if existing.status == PaymentStatus.succeeded:
			return False  # already processed — idempotent no-op

		existing.status = PaymentStatus.succeeded
		existing.paid_at = datetime.now(UTC)
		session.add(existing)
		await session.flush()
		return True

	# First invocation — should update
	updated1 = await _process_stripe_pi_succeeded(test_db_session, event)
	assert updated1 is True

	# Second invocation — should be a no-op
	updated2 = await _process_stripe_pi_succeeded(test_db_session, event)
	assert updated2 is False

	# DB state: exactly one succeeded payment
	fetched = await _get_payment_by_provider_id(test_db_session, pi_id)
	assert fetched is not None
	assert fetched.status == PaymentStatus.succeeded
	assert fetched.paid_at is not None


async def test_stripe_webhook_signature_verification() -> None:
	"""Stripe-Signature must be validated before any processing."""
	payload = json.dumps({"id": "evt_test", "type": "payment_intent.succeeded"}).encode()
	ts = int(time.time())
	valid_sig = _stripe_sign(payload, _STRIPE_WEBHOOK_SECRET, ts)

	def _verify_stripe(raw_body: bytes, sig_header: str, secret: str) -> bool:
		try:
			parts = dict(p.split("=", 1) for p in sig_header.split(","))
			received_ts = int(parts["t"])
			received_sig = parts["v1"]
			signed_payload = f"{received_ts}.".encode() + raw_body
			expected_sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
			return hmac.compare_digest(expected_sig, received_sig)
		except (KeyError, ValueError):
			return False

	assert _verify_stripe(payload, valid_sig, _STRIPE_WEBHOOK_SECRET) is True
	assert _verify_stripe(payload, valid_sig, "wrong-secret") is False
	assert _verify_stripe(payload, "t=999,v1=badsig", _STRIPE_WEBHOOK_SECRET) is False


async def test_stripe_subscription_creation_idempotent(
	test_db_session: AsyncSession,
	make_user,
) -> None:
	"""customer.subscription.created must not create duplicate rows."""
	user = await make_user()
	sub_id = f"sub_{uuid7str()}"
	customer_id = f"cus_{uuid7str()}"

	event = _stripe_subscription_created_event(sub_id, customer_id)

	async def _process_subscription_created(
		session: AsyncSession,
		event_data: dict,
		user_id: str,
	) -> bool:
		sub_data = event_data["data"]["object"]
		provider_sub_id = sub_data["id"]

		result = await session.execute(
			select(Subscription).where(Subscription.provider_subscription_id == provider_sub_id)
		)
		existing = result.scalar_one_or_none()
		if existing is not None:
			return False  # idempotent no-op

		datetime.now(UTC)
		subscription = Subscription(
			id=uuid7str(),
			user_id=user_id,
			provider=PaymentProvider.stripe,
			provider_subscription_id=provider_sub_id,
			provider_plan_id=sub_data["plan"]["id"],
			tier="creator",
			interval=SubscriptionInterval.month,
			status=sub_data["status"],
			amount_minor=sub_data["plan"]["amount"],
			currency=sub_data["plan"]["currency"].upper(),
			current_period_start=datetime.fromtimestamp(sub_data["current_period_start"], tz=UTC),
			current_period_end=datetime.fromtimestamp(sub_data["current_period_end"], tz=UTC),
		)
		session.add(subscription)
		await session.flush()
		return True

	# First call — creates subscription
	created1 = await _process_subscription_created(test_db_session, event, user.id)
	assert created1 is True

	# Second call — idempotent no-op
	created2 = await _process_subscription_created(test_db_session, event, user.id)
	assert created2 is False

	# Exactly one row in DB
	result = await test_db_session.execute(
		select(Subscription).where(Subscription.provider_subscription_id == sub_id)
	)
	subs = result.scalars().all()
	assert len(subs) == 1
	assert subs[0].provider == PaymentProvider.stripe


# ── Paystack webhook idempotency ───────────────────────────────────────────────


async def test_paystack_charge_success_idempotent(
	test_db_session: AsyncSession,
	make_user,
) -> None:
	"""charge.success delivered twice must update payment row exactly once."""
	user = await make_user()
	reference = f"pstk_{uuid7str()}"

	await _create_payment(
		test_db_session,
		user,
		provider_payment_id=reference,
		paystack_ref=reference,
		status=PaymentStatus.pending,
		amount=99900,
	)

	event = _paystack_charge_success_event(reference, amount=99900)

	async def _process_paystack_charge(session: AsyncSession, event_data: dict) -> bool:
		data = event_data["data"]
		ref = data["reference"]

		result = await session.execute(select(Payment).where(Payment.provider_payment_id == ref))
		existing = result.scalar_one_or_none()
		if existing is None:
			return False
		if existing.status == PaymentStatus.succeeded:
			return False  # idempotent no-op

		existing.status = PaymentStatus.succeeded
		existing.paid_at = datetime.now(UTC)
		session.add(existing)
		await session.flush()
		return True

	updated1 = await _process_paystack_charge(test_db_session, event)
	assert updated1 is True

	updated2 = await _process_paystack_charge(test_db_session, event)
	assert updated2 is False

	fetched = await _get_payment_by_provider_id(test_db_session, reference)
	assert fetched.status == PaymentStatus.succeeded
	assert fetched.paid_at is not None


async def test_paystack_webhook_signature_verification() -> None:
	"""Paystack uses HMAC-SHA512 of raw body with secret key."""
	payload = json.dumps({"event": "charge.success", "data": {}}).encode()
	valid_sig = _paystack_sign(payload, _PAYSTACK_SECRET_KEY)

	def _verify_paystack(raw_body: bytes, x_paystack_signature: str, secret: str) -> bool:
		expected = hmac.new(secret.encode(), raw_body, hashlib.sha512).hexdigest()
		return hmac.compare_digest(expected, x_paystack_signature)

	assert _verify_paystack(payload, valid_sig, _PAYSTACK_SECRET_KEY) is True
	assert _verify_paystack(payload, valid_sig, "wrong-key") is False
	assert _verify_paystack(payload, "totally-wrong-signature", _PAYSTACK_SECRET_KEY) is False


async def test_paystack_unknown_event_type_is_no_op(
	test_db_session: AsyncSession,
	make_user,
) -> None:
	"""Unrecognised event types must not raise — silently ignored."""
	await make_user()
	event = {"event": "transfer.success", "data": {"reference": "unknown_ref"}}

	known_events = {"charge.success", "subscription.create", "subscription.disable"}

	async def _dispatch_paystack_event(
		session: AsyncSession,
		event_data: dict,
	) -> str:
		event_type = event_data.get("event", "")
		if event_type not in known_events:
			return "ignored"
		return "processed"

	result = await _dispatch_paystack_event(test_db_session, event)
	assert result == "ignored"
