from __future__ import annotations

"""Unit tests for gbedu_worker.tasks.payments async helpers."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── DB session mock helpers ───────────────────────────────────────────────

def _make_session(execute_returns: list[Any] | None = None) -> tuple[MagicMock, Any]:
	"""Build a session mock whose execute() returns scalar_one_or_none() values in order."""
	session = MagicMock()
	session.add = MagicMock()
	session.flush = AsyncMock()
	session.commit = AsyncMock()

	call_idx = [-1]

	async def _execute(stmt: Any, *args: Any, **kwargs: Any) -> Any:
		call_idx[0] += 1
		result = MagicMock()
		if execute_returns is not None:
			idx = min(call_idx[0], len(execute_returns) - 1)
			result.scalar_one_or_none.return_value = execute_returns[idx]
			result.scalars.return_value.all.return_value = execute_returns[idx] if isinstance(execute_returns[idx], list) else []
		else:
			result.scalar_one_or_none.return_value = None
			result.scalars.return_value.all.return_value = []
		return result

	session.execute = _execute

	@asynccontextmanager
	async def _ctx():
		yield session

	return session, _ctx


def _make_user(
	user_id: str = "user-1",
	stripe_customer_id: str = "cus_abc",
	paystack_customer_code: str = "CUS_xyz",
	email: str = "a@b.com",
) -> MagicMock:
	u = MagicMock()
	u.id = user_id
	u.stripe_customer_id = stripe_customer_id
	u.paystack_customer_code = paystack_customer_code
	u.email = email
	return u


def _fake_redis() -> MagicMock:
	r = MagicMock()
	r.exists = AsyncMock(return_value=0)
	r.setex = AsyncMock()
	r.__aenter__ = AsyncMock(return_value=r)
	r.__aexit__ = AsyncMock(return_value=False)
	return r


# ── _handle_stripe_event ──────────────────────────────────────────────────

async def test_stripe_duplicate_event_skipped() -> None:
	from gbedu_worker.tasks.payments import _handle_stripe_event

	with patch("gbedu_worker.tasks.payments._already_processed", AsyncMock(return_value=True)):
		result = await _handle_stripe_event("evt_123", "invoice.payment_succeeded", {"object": {}})

	assert result["status"] == "skipped"
	assert result["reason"] == "duplicate"


async def test_stripe_unknown_event_type_ignored() -> None:
	from gbedu_worker.tasks.payments import _handle_stripe_event

	_, ctx = _make_session()

	with (
		patch("gbedu_worker.tasks.payments._already_processed", AsyncMock(return_value=False)),
		patch("gbedu_worker.tasks.payments._mark_processed", AsyncMock()),
		patch("gbedu_worker.tasks.payments.get_async_session", ctx),
	):
		result = await _handle_stripe_event("evt_123", "charge.refunded", {"object": {}})

	assert result["status"] == "ignored"


async def test_stripe_subscription_deleted_dispatches() -> None:
	from gbedu_worker.tasks.payments import _handle_stripe_event

	user = _make_user()
	_, ctx = _make_session([None, user, user])  # sub not found, then user found x2

	obj = {
		"id": "sub_123",
		"customer": "cus_abc",
		"status": "cancelled",
		"current_period_start": 1700000000,
		"current_period_end": 1702592000,
		"cancel_at_period_end": False,
	}

	mock_stripe_cfg = MagicMock(
		price_id_creator="price_creator",
		price_id_pro="price_pro",
		price_id_label="price_label",
	)

	with (
		patch("gbedu_worker.tasks.payments._already_processed", AsyncMock(return_value=False)),
		patch("gbedu_worker.tasks.payments._mark_processed", AsyncMock()),
		patch("gbedu_worker.tasks.payments.get_async_session", ctx),
		patch("gbedu_core.config.StripeSettings", return_value=mock_stripe_cfg),
	):
		result = await _handle_stripe_event("evt_del", "customer.subscription.deleted", {"object": obj})

	assert result["status"] == "ok"


async def test_stripe_invoice_payment_succeeded() -> None:
	from gbedu_worker.tasks.payments import _handle_stripe_event

	user = _make_user()
	_, ctx = _make_session([None, user])  # payment not found, then user found

	invoice = {
		"id": "in_abc",
		"payment_intent": "pi_xyz",
		"customer": "cus_abc",
		"amount_paid": 999,
		"currency": "usd",
	}

	with (
		patch("gbedu_worker.tasks.payments._already_processed", AsyncMock(return_value=False)),
		patch("gbedu_worker.tasks.payments._mark_processed", AsyncMock()),
		patch("gbedu_worker.tasks.payments.get_async_session", ctx),
	):
		result = await _handle_stripe_event("evt_pay", "invoice.payment_succeeded", {"object": invoice})

	assert result["status"] == "ok"


async def test_stripe_invoice_payment_failed_user_not_found() -> None:
	from gbedu_worker.tasks.payments import _handle_stripe_event

	# All queries return None
	_, ctx = _make_session([None, None])

	invoice = {
		"id": "in_abc",
		"payment_intent": "pi_xyz",
		"customer": "cus_unknown",
		"amount_paid": 0,
		"currency": "usd",
	}

	with (
		patch("gbedu_worker.tasks.payments._already_processed", AsyncMock(return_value=False)),
		patch("gbedu_worker.tasks.payments._mark_processed", AsyncMock()),
		patch("gbedu_worker.tasks.payments.get_async_session", ctx),
	):
		# Should not raise — just logs warning
		result = await _handle_stripe_event("evt_fail", "invoice.payment_failed", {"object": invoice})

	assert result["status"] == "ok"


async def test_stripe_checkout_session_completed_non_subscription_ignored() -> None:
	from gbedu_worker.tasks.payments import _handle_stripe_event

	_, ctx = _make_session()

	checkout_obj = {"id": "cs_abc", "mode": "payment"}

	with (
		patch("gbedu_worker.tasks.payments._already_processed", AsyncMock(return_value=False)),
		patch("gbedu_worker.tasks.payments._mark_processed", AsyncMock()),
		patch("gbedu_worker.tasks.payments.get_async_session", ctx),
	):
		result = await _handle_stripe_event("evt_chk", "checkout.session.completed", {"object": checkout_obj})

	assert result["status"] == "ok"


# ── _stripe_record_payment: existing payment updated ──────────────────────

async def test_stripe_record_payment_updates_existing() -> None:
	from gbedu_worker.tasks.payments import _stripe_record_payment
	from gbedu_core.models.payment import PaymentStatus

	existing_payment = MagicMock()
	existing_payment.status = PaymentStatus.pending

	session = MagicMock()
	session.add = MagicMock()
	session.flush = AsyncMock()

	call_idx = [-1]

	async def _execute(stmt: Any, *args: Any, **kwargs: Any) -> Any:
		call_idx[0] += 1
		result = MagicMock()
		result.scalar_one_or_none.return_value = existing_payment
		return result

	session.execute = _execute

	invoice = {"id": "in_abc", "payment_intent": "pi_xyz", "customer": "cus_abc", "amount_paid": 100, "currency": "usd"}
	await _stripe_record_payment(session, invoice, PaymentStatus.succeeded)

	assert existing_payment.status == PaymentStatus.succeeded
	assert existing_payment.paid_at is not None


# ── _handle_paystack_event ────────────────────────────────────────────────

async def test_paystack_duplicate_event_skipped() -> None:
	from gbedu_worker.tasks.payments import _handle_paystack_event

	with patch("gbedu_worker.tasks.payments._already_processed", AsyncMock(return_value=True)):
		result = await _handle_paystack_event("charge.success", {"reference": "REF123"}, "REF123")

	assert result["status"] == "skipped"


async def test_paystack_unknown_event_ignored() -> None:
	from gbedu_worker.tasks.payments import _handle_paystack_event

	_, ctx = _make_session()

	with (
		patch("gbedu_worker.tasks.payments._already_processed", AsyncMock(return_value=False)),
		patch("gbedu_worker.tasks.payments._mark_processed", AsyncMock()),
		patch("gbedu_worker.tasks.payments.get_async_session", ctx),
	):
		result = await _handle_paystack_event("transfer.success", {"reference": "REF123"}, "REF123")

	assert result["status"] == "ignored"


async def test_paystack_charge_success_new_payment() -> None:
	from gbedu_worker.tasks.payments import _handle_paystack_event

	user = _make_user()
	# First query: payment not found, second: user by customer_code, third query update
	_, ctx = _make_session([None, user])

	data = {
		"reference": "REF_pay",
		"amount": 50000,
		"currency": "NGN",
		"customer": {"customer_code": "CUS_xyz", "email": "a@b.com"},
	}

	with (
		patch("gbedu_worker.tasks.payments._already_processed", AsyncMock(return_value=False)),
		patch("gbedu_worker.tasks.payments._mark_processed", AsyncMock()),
		patch("gbedu_worker.tasks.payments.get_async_session", ctx),
	):
		result = await _handle_paystack_event("charge.success", data, "REF_pay")

	assert result["status"] == "ok"


async def test_paystack_charge_success_user_not_found() -> None:
	from gbedu_worker.tasks.payments import _handle_paystack_event

	# All queries return None (no payment, no user by code, no user by email)
	_, ctx = _make_session([None, None, None])

	data = {
		"reference": "REF_pay",
		"amount": 50000,
		"currency": "NGN",
		"customer": {"customer_code": "UNKNOWN", "email": "notfound@b.com"},
	}

	with (
		patch("gbedu_worker.tasks.payments._already_processed", AsyncMock(return_value=False)),
		patch("gbedu_worker.tasks.payments._mark_processed", AsyncMock()),
		patch("gbedu_worker.tasks.payments.get_async_session", ctx),
	):
		result = await _handle_paystack_event("charge.success", data, "REF_pay")

	assert result["status"] == "ok"


async def test_paystack_subscription_create_user_not_found() -> None:
	from gbedu_worker.tasks.payments import _handle_paystack_event

	_, ctx = _make_session([None])  # user not found

	data = {
		"subscription_code": "SUB_abc",
		"plan": {"plan_code": "PLN_creator_monthly"},
		"customer": {"customer_code": "CUS_unknown"},
		"amount": 50000,
	}

	with (
		patch("gbedu_worker.tasks.payments._already_processed", AsyncMock(return_value=False)),
		patch("gbedu_worker.tasks.payments._mark_processed", AsyncMock()),
		patch("gbedu_worker.tasks.payments.get_async_session", ctx),
	):
		result = await _handle_paystack_event("subscription.create", data, "")

	assert result["status"] == "ok"


async def test_paystack_subscription_disable() -> None:
	from gbedu_worker.tasks.payments import _handle_paystack_event

	sub = MagicMock()
	sub.status = "active"
	user = _make_user()
	_, ctx = _make_session([sub, user])

	data = {
		"subscription_code": "SUB_abc",
		"customer": {"customer_code": "CUS_xyz"},
	}

	with (
		patch("gbedu_worker.tasks.payments._already_processed", AsyncMock(return_value=False)),
		patch("gbedu_worker.tasks.payments._mark_processed", AsyncMock()),
		patch("gbedu_worker.tasks.payments.get_async_session", ctx),
	):
		result = await _handle_paystack_event("subscription.disable", data, "SUB_abc")

	assert result["status"] == "ok"


# ── helper functions ───────────────────────────────────────────────────────

def test_stripe_plan_to_tier_fallback() -> None:
	from gbedu_worker.tasks.payments import _stripe_plan_to_tier
	from gbedu_core.models.user import SubscriptionTier

	mock_cfg = MagicMock(price_id_creator="price_a", price_id_pro="price_b", price_id_label="price_c")
	with patch("gbedu_core.config.StripeSettings", return_value=mock_cfg):
		tier = _stripe_plan_to_tier({"metadata": {"tier": "pro"}, "plan": {}})

	assert tier == SubscriptionTier.pro


def test_stripe_plan_to_tier_unknown_falls_back_to_creator() -> None:
	from gbedu_worker.tasks.payments import _stripe_plan_to_tier
	from gbedu_core.models.user import SubscriptionTier

	mock_cfg = MagicMock(price_id_creator="price_a", price_id_pro="price_b", price_id_label="price_c")
	with patch("gbedu_core.config.StripeSettings", return_value=mock_cfg):
		tier = _stripe_plan_to_tier({"metadata": {}, "plan": {}})

	assert tier == SubscriptionTier.creator


def test_paystack_plan_to_tier_keyword_match() -> None:
	from gbedu_worker.tasks.payments import _paystack_plan_to_tier
	from gbedu_core.models.user import SubscriptionTier

	assert _paystack_plan_to_tier("PLN_pro_monthly") == SubscriptionTier.pro
	assert _paystack_plan_to_tier("PLN_label_annual") == SubscriptionTier.label
	assert _paystack_plan_to_tier("PLN_unknown") == SubscriptionTier.creator


def test_stripe_interval_year() -> None:
	from gbedu_worker.tasks.payments import _stripe_interval
	from gbedu_core.models.payment import SubscriptionInterval

	assert _stripe_interval({"plan": {"interval": "year"}}) == SubscriptionInterval.year
	assert _stripe_interval({"plan": {"interval": "month"}}) == SubscriptionInterval.month
	assert _stripe_interval({"plan": {}}) == SubscriptionInterval.month


def test_paystack_retry_countdown_clamped() -> None:
	from gbedu_worker.tasks.payments import _paystack_retry_countdown

	assert _paystack_retry_countdown(0) == 10
	assert _paystack_retry_countdown(4) == 300
	assert _paystack_retry_countdown(99) == 300


def test_ts_converts_unix() -> None:
	from gbedu_worker.tasks.payments import _ts

	dt = _ts(0)
	assert dt.year == 1970
	assert dt.tzinfo is not None


def test_paystack_next_billing_fallback() -> None:
	from gbedu_worker.tasks.payments import _paystack_next_billing

	result = _paystack_next_billing({})
	assert result > datetime.now(timezone.utc)


def test_paystack_next_billing_from_date_string() -> None:
	from gbedu_worker.tasks.payments import _paystack_next_billing

	result = _paystack_next_billing({"next_payment_date": "2026-07-01T00:00:00"})
	assert result.year == 2026
