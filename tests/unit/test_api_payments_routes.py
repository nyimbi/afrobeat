"""Unit tests for /api/v1/payments/* route handlers.

Covers Stripe and Paystack endpoints including:
- Checkout session creation
- Stripe webhook handling (idempotency, signature verification)
- Customer portal
- Subscription status
- Paystack initialize, verify, webhook
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
from starlette.testclient import TestClient

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost/gbedu_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("GBEDU_ML_API_KEY", "test-ml-internal-api-key")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_fake")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_fake")
os.environ.setdefault("PAYSTACK_SECRET_KEY", "sk_test_paystack_fake")
os.environ.setdefault("STRIPE_PRICE_ID_CREATOR", "price_creator_test")
os.environ.setdefault("STRIPE_PRICE_ID_PRO", "price_pro_test")
os.environ.setdefault("STRIPE_PRICE_ID_LABEL", "price_label_test")

from gbedu_core.models.user import SubscriptionStatus, SubscriptionTier

_PAYSTACK_SECRET = os.environ["PAYSTACK_SECRET_KEY"]


def _make_user(
	stripe_customer_id: str | None = "cus_test_123",
	tier: str = "creator",
) -> MagicMock:
	user = MagicMock()
	user.id = "user-pay-test-001"
	user.email = "pay@example.com"
	user.full_name = "Pay Tester"
	user.stripe_customer_id = stripe_customer_id
	user.subscription_tier = SubscriptionTier(tier)
	user.subscription_status = SubscriptionStatus.active
	user.is_active = True
	user.is_verified = True
	user.deleted_at = None
	return user


def _make_mock_settings():
	"""Return a fully-populated settings mock so we never depend on lru_cache state."""
	settings = MagicMock()
	settings.stripe.secret_key = "sk_test_fake"
	settings.stripe.webhook_secret = "whsec_fake"
	settings.stripe.price_id_creator = "price_creator_test"
	settings.stripe.price_id_pro = "price_pro_test"
	settings.stripe.price_id_label = "price_label_test"
	settings.paystack.secret_key = "sk_test_paystack_fake"
	settings.paystack.base_url = "https://api.paystack.co"
	settings.frontend_url = "https://app.test.example.com"
	return settings


def _build_client(
	stripe_customer_id: str | None = "cus_test_123",
	tier: str = "creator",
):
	from gbedu_api.deps import get_current_active_user, get_db, get_redis
	from gbedu_api.main import app

	user = _make_user(stripe_customer_id, tier)
	mock_db = AsyncMock()
	mock_db.add = MagicMock()
	mock_db.flush = AsyncMock()
	fake_redis = fakeredis.aioredis.FakeRedis()

	async def _override_db():
		yield mock_db

	async def _override_redis():
		return fake_redis

	app.dependency_overrides[get_db] = _override_db
	app.dependency_overrides[get_redis] = _override_redis
	app.dependency_overrides[get_current_active_user] = lambda: user

	client = TestClient(app, raise_server_exceptions=False)
	return client, mock_db, fake_redis, user


def teardown_function() -> None:
	from gbedu_api.main import app

	app.dependency_overrides.clear()


def _paystack_sig(payload: bytes) -> str:
	return hmac.new(
		key=_PAYSTACK_SECRET.encode(),
		msg=payload,
		digestmod=hashlib.sha512,
	).hexdigest()


# ── POST /payments/stripe/create-checkout ─────────────────────────────────────


def test_create_checkout_success() -> None:
	client, _, _, _ = _build_client(stripe_customer_id="cus_test_123", tier="creator")

	mock_session = MagicMock()
	mock_session.url = "https://checkout.stripe.com/pay/cs_test_abc"
	mock_session.id = "cs_test_abc"

	with (
		patch("gbedu_api.routers.payments.get_settings", return_value=_make_mock_settings()),
		patch("stripe.checkout.Session.create", return_value=mock_session),
	):
		resp = client.post(
			"/api/v1/payments/stripe/create-checkout",
			json={"tier": "creator", "interval": "month"},
		)

	assert resp.status_code == 200
	body = resp.json()
	assert body["checkout_url"] == "https://checkout.stripe.com/pay/cs_test_abc"
	assert body["session_id"] == "cs_test_abc"


def test_create_checkout_no_customer_id_creates_customer() -> None:
	client, _, _, _ = _build_client(stripe_customer_id=None, tier="creator")

	mock_customer = MagicMock()
	mock_customer.id = "cus_new_123"

	mock_session = MagicMock()
	mock_session.url = "https://checkout.stripe.com/pay/cs_test_new"
	mock_session.id = "cs_test_new"

	with (
		patch("gbedu_api.routers.payments.get_settings", return_value=_make_mock_settings()),
		patch("stripe.Customer.create", return_value=mock_customer) as mock_create,
		patch("stripe.checkout.Session.create", return_value=mock_session),
	):
		resp = client.post(
			"/api/v1/payments/stripe/create-checkout",
			json={"tier": "creator", "interval": "month"},
		)

	assert resp.status_code == 200
	mock_create.assert_called_once()


def test_create_checkout_free_tier_returns_422() -> None:
	client, _, _, _ = _build_client(tier="free")
	with patch("gbedu_api.routers.payments.get_settings", return_value=_make_mock_settings()):
		resp = client.post(
			"/api/v1/payments/stripe/create-checkout",
			json={"tier": "free", "interval": "month"},
		)
	assert resp.status_code == 422


# ── POST /payments/stripe/webhook ─────────────────────────────────────────────


def test_stripe_webhook_invalid_signature_returns_400() -> None:
	import stripe

	client, _, _, _ = _build_client()

	with (
		patch("gbedu_api.routers.payments.get_settings", return_value=_make_mock_settings()),
		patch(
			"stripe.Webhook.construct_event",
			side_effect=stripe.error.SignatureVerificationError("bad sig", "bad_sig_header"),
		),
	):
		resp = client.post(
			"/api/v1/payments/stripe/webhook",
			content=b'{"id": "evt_test"}',
			headers={"Stripe-Signature": "bad_sig", "Content-Type": "application/json"},
		)

	assert resp.status_code == 400
	assert resp.json()["detail"]["error_code"] == "PAYMENT_WEBHOOK_ERROR"


def test_stripe_webhook_duplicate_redis_returns_already_processed() -> None:
	import asyncio

	client, mock_db, fake_redis, _ = _build_client()

	event_id = "evt_dupe_001"
	idempotency_key = f"stripe_event:{event_id}"
	# Pre-set the key in fake_redis to simulate duplicate
	asyncio.get_event_loop().run_until_complete(fake_redis.set(idempotency_key, "1"))

	mock_event = {
		"id": event_id,
		"type": "customer.subscription.updated",
		"data": {"object": {}},
	}

	with (
		patch("gbedu_api.routers.payments.get_settings", return_value=_make_mock_settings()),
		patch("stripe.Webhook.construct_event", return_value=mock_event),
	):
		resp = client.post(
			"/api/v1/payments/stripe/webhook",
			content=b'{"id": "evt_dupe_001"}',
			headers={"Stripe-Signature": "sig_ok", "Content-Type": "application/json"},
		)

	assert resp.status_code == 200
	assert resp.json()["status"] == "already_processed"


def test_stripe_webhook_new_event_returns_ok() -> None:
	client, mock_db, _, _ = _build_client()

	event_id = "evt_new_001"
	mock_event = {
		"id": event_id,
		"type": "customer.subscription.updated",
		"data": {"object": {}},
	}

	# DB returns None for the webhook_events lookup and None for the user lookup
	none_result = MagicMock()
	none_result.scalar_one_or_none.return_value = None
	mock_db.execute = AsyncMock(return_value=none_result)

	with (
		patch("gbedu_api.routers.payments.get_settings", return_value=_make_mock_settings()),
		patch("stripe.Webhook.construct_event", return_value=mock_event),
		patch(
			"gbedu_api.routers.payments._handle_stripe_event",
			AsyncMock(return_value=None),
		),
	):
		resp = client.post(
			"/api/v1/payments/stripe/webhook",
			content=b'{"id": "evt_new_001"}',
			headers={"Stripe-Signature": "sig_ok", "Content-Type": "application/json"},
		)

	assert resp.status_code == 200
	assert resp.json()["status"] == "ok"


# ── GET /payments/portal ──────────────────────────────────────────────────────


def test_portal_no_customer_returns_422() -> None:
	client, _, _, _ = _build_client(stripe_customer_id=None)
	with patch("gbedu_api.routers.payments.get_settings", return_value=_make_mock_settings()):
		resp = client.get("/api/v1/payments/portal")
	assert resp.status_code == 422
	assert resp.json()["detail"]["error_code"] == "PAYMENT_ERROR"


def test_portal_success() -> None:
	client, _, _, _ = _build_client(stripe_customer_id="cus_test_123")

	mock_session = MagicMock()
	mock_session.url = "https://billing.stripe.com/session/bps_test"

	with (
		patch("gbedu_api.routers.payments.get_settings", return_value=_make_mock_settings()),
		patch("stripe.billing_portal.Session.create", return_value=mock_session),
	):
		resp = client.get("/api/v1/payments/portal")

	assert resp.status_code == 200
	assert resp.json()["portal_url"] == "https://billing.stripe.com/session/bps_test"


# ── GET /payments/subscription ────────────────────────────────────────────────


def test_get_subscription_no_sub() -> None:
	client, mock_db, _, _ = _build_client(tier="creator")

	none_result = MagicMock()
	none_result.scalar_one_or_none.return_value = None
	mock_db.execute = AsyncMock(return_value=none_result)

	resp = client.get("/api/v1/payments/subscription")

	assert resp.status_code == 200
	body = resp.json()
	assert body["tier"] == "creator"
	assert body["current_period_end"] is None
	assert body["cancel_at_period_end"] is False


def test_get_subscription_with_sub() -> None:
	client, mock_db, _, _ = _build_client(tier="pro")

	mock_sub = MagicMock()
	mock_sub.current_period_end = datetime(2026, 12, 31, tzinfo=UTC)
	mock_sub.cancel_at_period_end = False

	sub_result = MagicMock()
	sub_result.scalar_one_or_none.return_value = mock_sub
	mock_db.execute = AsyncMock(return_value=sub_result)

	resp = client.get("/api/v1/payments/subscription")

	assert resp.status_code == 200
	body = resp.json()
	assert body["tier"] == "pro"
	assert "2026" in body["current_period_end"]
	assert body["cancel_at_period_end"] is False


# ── POST /payments/paystack/initialize ────────────────────────────────────────


def test_paystack_initialize_success() -> None:
	client, _, _, _ = _build_client(tier="creator")

	mock_resp = MagicMock()
	mock_resp.status_code = 200
	mock_resp.json.return_value = {
		"data": {
			"authorization_url": "https://checkout.paystack.com/abc123",
			"access_code": "abc123",
			"reference": "ref_001",
		}
	}

	with (
		patch("gbedu_api.routers.payments.get_settings", return_value=_make_mock_settings()),
		patch("httpx.AsyncClient") as MockClient,
	):
		mock_http = AsyncMock()
		mock_http.__aenter__ = AsyncMock(return_value=mock_http)
		mock_http.__aexit__ = AsyncMock(return_value=False)
		mock_http.post = AsyncMock(return_value=mock_resp)
		MockClient.return_value = mock_http

		resp = client.post(
			"/api/v1/payments/paystack/initialize",
			json={"tier": "creator", "interval": "month", "currency": "NGN"},
		)

	assert resp.status_code == 200
	body = resp.json()
	assert body["authorization_url"] == "https://checkout.paystack.com/abc123"
	assert body["reference"] == "ref_001"


def test_paystack_initialize_free_tier_returns_422() -> None:
	client, _, _, _ = _build_client(tier="free")
	with patch("gbedu_api.routers.payments.get_settings", return_value=_make_mock_settings()):
		resp = client.post(
			"/api/v1/payments/paystack/initialize",
			json={"tier": "free", "interval": "month"},
		)
	assert resp.status_code == 422


def test_paystack_initialize_api_failure_returns_502() -> None:
	client, _, _, _ = _build_client(tier="creator")

	mock_resp = MagicMock()
	mock_resp.status_code = 500
	mock_resp.json.return_value = {"message": "internal error"}

	with (
		patch("gbedu_api.routers.payments.get_settings", return_value=_make_mock_settings()),
		patch("httpx.AsyncClient") as MockClient,
	):
		mock_http = AsyncMock()
		mock_http.__aenter__ = AsyncMock(return_value=mock_http)
		mock_http.__aexit__ = AsyncMock(return_value=False)
		mock_http.post = AsyncMock(return_value=mock_resp)
		MockClient.return_value = mock_http

		resp = client.post(
			"/api/v1/payments/paystack/initialize",
			json={"tier": "creator", "interval": "month"},
		)

	assert resp.status_code == 502


# ── GET /payments/paystack/verify/{reference} ─────────────────────────────────


def test_paystack_verify_success_new_payment() -> None:
	client, mock_db, _, _ = _build_client(tier="creator")

	mock_resp = MagicMock()
	mock_resp.status_code = 200
	mock_resp.json.return_value = {
		"data": {
			"status": "success",
			"reference": "ref_verify_001",
			"amount": 500000,
			"currency": "NGN",
			"metadata": {"user_id": "user-pay-test-001", "tier": "creator"},
			"customer": {"customer_code": "CUS_001"},
		}
	}

	# DB returns None for payment lookup (new payment)
	none_result = MagicMock()
	none_result.scalar_one_or_none.return_value = None
	mock_db.execute = AsyncMock(return_value=none_result)

	with (
		patch("gbedu_api.routers.payments.get_settings", return_value=_make_mock_settings()),
		patch("httpx.AsyncClient") as MockClient,
	):
		mock_http = AsyncMock()
		mock_http.__aenter__ = AsyncMock(return_value=mock_http)
		mock_http.__aexit__ = AsyncMock(return_value=False)
		mock_http.get = AsyncMock(return_value=mock_resp)
		MockClient.return_value = mock_http

		resp = client.get("/api/v1/payments/paystack/verify/ref_verify_001")

	assert resp.status_code == 200
	body = resp.json()
	assert body["status"] == "success"
	assert body["reference"] == "ref_verify_001"


def test_paystack_verify_api_failure_returns_502() -> None:
	client, _, _, _ = _build_client()

	mock_resp = MagicMock()
	mock_resp.status_code = 400
	mock_resp.json.return_value = {"message": "invalid reference"}

	with (
		patch("gbedu_api.routers.payments.get_settings", return_value=_make_mock_settings()),
		patch("httpx.AsyncClient") as MockClient,
	):
		mock_http = AsyncMock()
		mock_http.__aenter__ = AsyncMock(return_value=mock_http)
		mock_http.__aexit__ = AsyncMock(return_value=False)
		mock_http.get = AsyncMock(return_value=mock_resp)
		MockClient.return_value = mock_http

		resp = client.get("/api/v1/payments/paystack/verify/bad_ref")

	assert resp.status_code == 502


# ── POST /payments/paystack/webhook ──────────────────────────────────────────


def _paystack_webhook_payload(
	event_type: str = "charge.success", reference: str = "ref_wh_001"
) -> bytes:
	return json.dumps(
		{
			"event": event_type,
			"data": {
				"reference": reference,
				"amount": 500000,
				"currency": "NGN",
				"status": "success",
				"metadata": {"user_id": "user-pay-test-001", "tier": "creator"},
				"customer": {"customer_code": "CUS_001"},
			},
		}
	).encode()


def test_paystack_webhook_invalid_signature_returns_400() -> None:
	client, _, _, _ = _build_client()
	payload = _paystack_webhook_payload()
	with patch("gbedu_api.routers.payments.get_settings", return_value=_make_mock_settings()):
		resp = client.post(
			"/api/v1/payments/paystack/webhook",
			content=payload,
			headers={"x-paystack-signature": "bad_sig", "Content-Type": "application/json"},
		)
	assert resp.status_code == 400
	assert resp.json()["detail"]["error_code"] == "PAYMENT_WEBHOOK_ERROR"


def test_paystack_webhook_duplicate_returns_already_processed() -> None:
	import asyncio

	client, mock_db, fake_redis, _ = _build_client()

	reference = "ref_wh_dupe"
	idempotency_key = f"paystack_event:{reference}"
	asyncio.get_event_loop().run_until_complete(fake_redis.set(idempotency_key, "1"))

	payload = _paystack_webhook_payload(reference=reference)
	sig = _paystack_sig(payload)

	with patch("gbedu_api.routers.payments.get_settings", return_value=_make_mock_settings()):
		resp = client.post(
			"/api/v1/payments/paystack/webhook",
			content=payload,
			headers={"x-paystack-signature": sig, "Content-Type": "application/json"},
		)

	assert resp.status_code == 200
	assert resp.json()["status"] == "already_processed"


def test_paystack_webhook_charge_success_returns_ok() -> None:
	client, mock_db, _, _ = _build_client()

	payload = _paystack_webhook_payload("charge.success", "ref_wh_new_001")
	sig = _paystack_sig(payload)

	# DB returns None for webhook_events lookup and user lookup
	none_result = MagicMock()
	none_result.scalar_one_or_none.return_value = None
	user_result = MagicMock()
	user_result.scalar_one_or_none.return_value = _make_user()
	mock_db.execute = AsyncMock(side_effect=[none_result, user_result])

	with patch("gbedu_api.routers.payments.get_settings", return_value=_make_mock_settings()):
		resp = client.post(
			"/api/v1/payments/paystack/webhook",
			content=payload,
			headers={"x-paystack-signature": sig, "Content-Type": "application/json"},
		)

	assert resp.status_code == 200
	assert resp.json()["status"] == "ok"


def test_paystack_webhook_unknown_event_returns_ok() -> None:
	client, mock_db, _, _ = _build_client()

	payload = _paystack_webhook_payload("transfer.success", "ref_wh_transfer_001")
	sig = _paystack_sig(payload)

	none_result = MagicMock()
	none_result.scalar_one_or_none.return_value = None
	mock_db.execute = AsyncMock(return_value=none_result)

	with patch("gbedu_api.routers.payments.get_settings", return_value=_make_mock_settings()):
		resp = client.post(
			"/api/v1/payments/paystack/webhook",
			content=payload,
			headers={"x-paystack-signature": sig, "Content-Type": "application/json"},
		)

	assert resp.status_code == 200
	assert resp.json()["status"] == "ok"


# ── _handle_stripe_event helpers ──────────────────────────────────────────────


async def test_handle_stripe_event_subscription_created() -> None:
	from gbedu_api.routers.payments import _handle_stripe_event

	mock_db = AsyncMock()
	none_result = MagicMock()
	none_result.scalar_one_or_none.return_value = None
	mock_db.execute = AsyncMock(return_value=none_result)
	mock_db.add = MagicMock()
	mock_db.flush = AsyncMock()

	event = {
		"type": "customer.subscription.created",
		"data": {
			"object": {
				"id": "sub_001",
				"customer": "cus_test_123",
				"status": "active",
				"metadata": {"tier": "creator"},
				"current_period_start": 1700000000,
				"current_period_end": 1702592000,
				"cancel_at_period_end": False,
				"items": {"data": [{"price": {"id": "price_creator"}}]},
				"currency": "usd",
			}
		},
	}
	# Should not raise
	await _handle_stripe_event(event, mock_db)


async def test_handle_stripe_event_unhandled_type_does_not_raise() -> None:
	from gbedu_api.routers.payments import _handle_stripe_event

	mock_db = AsyncMock()
	event = {
		"type": "payment_intent.created",
		"data": {"object": {}},
	}
	await _handle_stripe_event(event, mock_db)


async def test_handle_stripe_event_invoice_paid() -> None:
	from gbedu_api.routers.payments import _handle_stripe_event

	mock_db = AsyncMock()
	user_result = MagicMock()
	user_result.scalar_one_or_none.return_value = _make_user()
	mock_db.execute = AsyncMock(return_value=user_result)
	mock_db.add = MagicMock()
	mock_db.flush = AsyncMock()

	event = {
		"type": "invoice.payment_succeeded",
		"data": {
			"object": {
				"id": "in_001",
				"customer": "cus_test_123",
				"amount_paid": 2000,
				"currency": "usd",
			}
		},
	}
	await _handle_stripe_event(event, mock_db)
	mock_db.add.assert_called()


async def test_handle_stripe_event_subscription_deleted() -> None:
	from gbedu_api.routers.payments import _handle_stripe_event

	mock_db = AsyncMock()

	mock_sub = MagicMock()
	mock_sub.user_id = "user-pay-test-001"
	sub_result = MagicMock()
	sub_result.scalar_one_or_none.return_value = mock_sub

	none_user_result = MagicMock()
	none_user_result.scalar_one_or_none.return_value = None

	mock_db.execute = AsyncMock(side_effect=[sub_result, none_user_result])
	mock_db.add = MagicMock()
	mock_db.flush = AsyncMock()

	event = {
		"type": "customer.subscription.deleted",
		"data": {"object": {"id": "sub_001"}},
	}
	await _handle_stripe_event(event, mock_db)


async def test_handle_stripe_event_checkout_beat_purchase_no_beat_meta() -> None:
	from gbedu_api.routers.payments import _handle_stripe_event

	mock_db = AsyncMock()
	event = {
		"type": "checkout.session.completed",
		"data": {
			"object": {
				"id": "cs_001",
				"metadata": {},  # no purchase_type=beat
			}
		},
	}
	# Should return early without DB calls
	await _handle_stripe_event(event, mock_db)
