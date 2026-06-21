from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from inspect import isawaitable
from typing import Annotated, Any, cast

import httpx
import stripe
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from gbedu_core._uuid7 import uuid7str
from gbedu_core.models.payment import (
	Payment,
	PaymentProvider,
	PaymentStatus,
	Subscription,
	SubscriptionInterval,
	WebhookEvent,
)
from gbedu_core.models.user import SubscriptionStatus, SubscriptionTier, User
from pydantic import BaseModel, ConfigDict
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gbedu_api.config import get_settings
from gbedu_api.deps import get_current_active_user, get_db, get_redis

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])

_STRIPE_EVENT_IDEMPOTENCY_PREFIX = "stripe_event:"
_PAYSTACK_EVENT_IDEMPOTENCY_PREFIX = "paystack_event:"
_IDEMPOTENCY_TTL = 86400 * 7  # 7 days


async def _add_db_object(db: AsyncSession, obj: object) -> None:
	maybe_awaitable: Any = db.add(obj)
	if isawaitable(maybe_awaitable):
		await maybe_awaitable


# ── Schemas ────────────────────────────────────────────────────────────────────


class CheckoutRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")
	tier: SubscriptionTier
	interval: SubscriptionInterval = SubscriptionInterval.month


class CheckoutResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	checkout_url: str
	session_id: str


class PaystackInitRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")
	tier: SubscriptionTier
	interval: SubscriptionInterval = SubscriptionInterval.month
	currency: str = "NGN"


class PaystackInitResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	authorization_url: str
	access_code: str
	reference: str


class PaystackVerifyResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	status: str
	reference: str
	amount_minor: int
	currency: str


class PortalResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	portal_url: str


class SubscriptionStatusResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	tier: str
	status: str
	current_period_end: str | None
	cancel_at_period_end: bool


def _tier_to_stripe_price(tier: SubscriptionTier, interval: SubscriptionInterval) -> str:
	settings = get_settings()
	price_map = {
		SubscriptionTier.creator: settings.stripe.price_id_creator,
		SubscriptionTier.pro: settings.stripe.price_id_pro,
		SubscriptionTier.label: settings.stripe.price_id_label,
	}
	price_id = price_map.get(tier)
	if not price_id:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail={
				"error_code": "VALIDATION_ERROR",
				"message": f"No Stripe price for tier {tier.value}",
			},
		)
	return price_id


# ── Stripe endpoints ───────────────────────────────────────────────────────────


@router.post(
	"/stripe/create-checkout",
	response_model=CheckoutResponse,
	status_code=status.HTTP_200_OK,
	summary="Create Stripe checkout session for subscription upgrade",
)
async def stripe_create_checkout(
	body: CheckoutRequest,
	user: Annotated[User, Depends(get_current_active_user)],
) -> CheckoutResponse:
	settings = get_settings()
	stripe.api_key = settings.stripe.secret_key

	price_id = _tier_to_stripe_price(body.tier, body.interval)

	customer_id = user.stripe_customer_id
	if not customer_id:
		customer = stripe.Customer.create(
			email=user.email,
			name=user.full_name,
			metadata={"user_id": user.id},
		)
		customer_id = customer.id

	session = stripe.checkout.Session.create(
		customer=customer_id,
		payment_method_types=["card"],
		line_items=[{"price": price_id, "quantity": 1}],
		mode="subscription",
		success_url=f"{settings.frontend_url}/subscription/success?session_id={{CHECKOUT_SESSION_ID}}",
		cancel_url=f"{settings.frontend_url}/subscription/cancel",
		metadata={"user_id": user.id, "tier": body.tier.value},
	)

	if not session.url:
		raise HTTPException(
			status_code=status.HTTP_502_BAD_GATEWAY,
			detail={
				"error_code": "PAYMENT_ERROR",
				"message": "Stripe did not return a checkout URL",
			},
		)
	return CheckoutResponse(checkout_url=session.url, session_id=session.id)


@router.post(
	"/stripe/webhook",
	status_code=status.HTTP_200_OK,
	summary="Handle Stripe webhook events (idempotent)",
	include_in_schema=False,
)
async def stripe_webhook(
	request: Request,
	db: Annotated[AsyncSession, Depends(get_db)],
	redis: Annotated[Redis, Depends(get_redis)],
) -> dict[str, str]:
	settings = get_settings()
	payload = await request.body()
	sig_header = request.headers.get("Stripe-Signature", "")

	stripe.api_key = settings.stripe.secret_key
	stripe_api = cast(Any, stripe)
	try:
		event = cast(
			dict[str, Any],
			stripe_api.Webhook.construct_event(payload, sig_header, settings.stripe.webhook_secret),
		)
	except stripe_api.error.SignatureVerificationError as exc:
		log.warning("stripe.webhook.invalid_signature", error=str(exc))
		raise HTTPException(
			status_code=400,
			detail={"error_code": "PAYMENT_WEBHOOK_ERROR", "message": "Invalid signature"},
		)

	event_id = event["id"]
	idempotency_key = f"{_STRIPE_EVENT_IDEMPOTENCY_PREFIX}{event_id}"

	# Fast path: Redis SET NX (handles 99.9% of duplicates with sub-ms latency).
	claimed = await redis.set(idempotency_key, "processing", nx=True, ex=_IDEMPOTENCY_TTL)
	if not claimed:
		log.info("stripe.webhook.duplicate.redis", event_id=event_id, event_type=event["type"])
		return {"status": "already_processed"}

	# Durable path: DB check survives Redis restarts between delivery attempts.
	# If the webhook was already written to webhook_events, skip processing and
	# re-prime Redis so the fast path catches the next duplicate.
	existing = await db.execute(select(WebhookEvent).where(WebhookEvent.event_id == event_id))
	if existing.scalar_one_or_none():
		await redis.setex(idempotency_key, _IDEMPOTENCY_TTL, "1")
		log.info("stripe.webhook.duplicate.db", event_id=event_id)
		return {"status": "already_processed"}

	event_type = event["type"]
	log.info("stripe.webhook.received", event_id=event_id, event_type=event_type)

	try:
		await _handle_stripe_event(event, db)
		# Write durable record within the same transaction as the business logic.
		await _add_db_object(
			db,
			WebhookEvent(
				id=uuid7str(),
				event_id=event_id,
				provider=PaymentProvider.stripe,
				event_type=event_type,
				processed_at=datetime.now(UTC),
			),
		)
		await db.flush()
	except Exception as exc:
		await redis.delete(idempotency_key)
		log.error("stripe.webhook.handler_error", event_id=event_id, error=str(exc))
		raise HTTPException(
			status_code=500, detail={"error_code": "PAYMENT_WEBHOOK_ERROR", "message": str(exc)}
		)

	await redis.setex(idempotency_key, _IDEMPOTENCY_TTL, "1")
	return {"status": "ok"}


async def _handle_stripe_event(event: dict[str, Any], db: AsyncSession) -> None:
	event_type = event["type"]
	data = event["data"]["object"]

	if (
		event_type == "customer.subscription.created"
		or event_type == "customer.subscription.updated"
	):
		await _stripe_subscription_upsert(data, db)
	elif event_type == "customer.subscription.deleted":
		await _stripe_subscription_cancel(data, db)
	elif event_type == "invoice.payment_succeeded":
		await _stripe_invoice_paid(data, db)
	elif event_type == "checkout.session.completed":
		await _stripe_checkout_beat_purchase(data, db)
	else:
		log.debug("stripe.webhook.unhandled_event", event_type=event_type)


async def _stripe_subscription_upsert(data: dict[str, Any], db: AsyncSession) -> None:
	provider_sub_id = data["id"]
	customer_id = data["customer"]
	status_str = data["status"]
	tier_meta = data.get("metadata", {}).get("tier", SubscriptionTier.creator.value)

	result = await db.execute(select(User).where(User.stripe_customer_id == customer_id))
	user = result.scalar_one_or_none()
	if user is None:
		log.warning("stripe.subscription_upsert.user_not_found", customer_id=customer_id)
		return

	existing = await db.execute(
		select(Subscription).where(Subscription.provider_subscription_id == provider_sub_id)
	)
	sub = existing.scalar_one_or_none()

	period_start = datetime.fromtimestamp(data["current_period_start"], tz=UTC)
	period_end = datetime.fromtimestamp(data["current_period_end"], tz=UTC)

	if sub is None:
		sub = Subscription(
			id=uuid7str(),
			user_id=user.id,
			provider=PaymentProvider.stripe,
			provider_subscription_id=provider_sub_id,
			provider_plan_id=data["items"]["data"][0]["price"]["id"] if data.get("items") else "",
			tier=tier_meta,
			interval=SubscriptionInterval.month,
			status=status_str,
			amount_minor=data.get("plan", {}).get("amount", 0) if data.get("plan") else 0,
			currency=(data.get("currency") or "usd").upper(),
			current_period_start=period_start,
			current_period_end=period_end,
			cancel_at_period_end=data.get("cancel_at_period_end", False),
		)
	else:
		sub.status = status_str
		sub.current_period_start = period_start
		sub.current_period_end = period_end
		sub.cancel_at_period_end = data.get("cancel_at_period_end", False)

	db.add(sub)

	# Update user tier
	try:
		user.subscription_tier = SubscriptionTier(tier_meta)
	except ValueError:
		user.subscription_tier = SubscriptionTier.creator

	user.stripe_customer_id = customer_id
	user.subscription_status = (
		SubscriptionStatus.active
		if status_str == "active"
		else SubscriptionStatus.past_due
		if status_str == "past_due"
		else SubscriptionStatus.cancelled
	)
	db.add(user)
	await db.flush()


async def _stripe_subscription_cancel(data: dict[str, Any], db: AsyncSession) -> None:
	provider_sub_id = data["id"]
	result = await db.execute(
		select(Subscription).where(Subscription.provider_subscription_id == provider_sub_id)
	)
	sub = result.scalar_one_or_none()
	if sub is None:
		return

	sub.status = "cancelled"
	sub.cancelled_at = datetime.now(UTC)
	db.add(sub)

	user_result = await db.execute(select(User).where(User.id == sub.user_id))
	user = user_result.scalar_one_or_none()
	if user:
		user.subscription_tier = SubscriptionTier.free
		user.subscription_status = SubscriptionStatus.cancelled
		db.add(user)

	await db.flush()


_BEAT_DOWNLOAD_EXPIRES = 86400 * 3  # 72 hours — long enough for a slow download


async def _stripe_checkout_beat_purchase(data: dict[str, Any], db: AsyncSession) -> None:
	"""Handle checkout.session.completed when the session carries beat purchase metadata."""
	meta = data.get("metadata", {})
	if meta.get("purchase_type") != "beat":
		return  # Subscription checkout — nothing to do here

	listing_id = meta.get("listing_id", "")
	buyer_id = meta.get("user_id", "")
	if not listing_id or not buyer_id:
		log.warning(
			"stripe.checkout_completed.missing_beat_meta",
			session_id=data.get("id"),
			has_listing_id=bool(listing_id),
			has_buyer_id=bool(buyer_id),
		)
		return

	await _fulfil_beat_purchase(
		listing_id=listing_id,
		buyer_id=buyer_id,
		provider="stripe",
		provider_payment_id=data["id"],
		amount_minor=data.get("amount_total", 0),
		currency=(data.get("currency") or "usd").upper(),
		db=db,
	)


async def _fulfil_beat_purchase(
	listing_id: str,
	buyer_id: str,
	provider: str,
	provider_payment_id: str,
	amount_minor: int,
	currency: str,
	db: AsyncSession,
) -> None:
	"""Create a BeatPurchase record and generate a 72-hour presigned download URL.

	Idempotent — a second call for the same (buyer_id, listing_id) pair is a
	safe no-op.  The database unique constraint (buyer_id, listing_id) is a
	second line of defence if the SELECT check is somehow bypassed.
	"""
	from gbedu_core.config import StorageSettings
	from gbedu_core.models.marketplace import BeatListing, BeatPurchase, LicenseType, ListingStatus
	from gbedu_core.models.track import Track

	from gbedu_api.deps import get_storage

	assert listing_id, "listing_id required"
	assert buyer_id, "buyer_id required"
	assert provider_payment_id, "provider_payment_id required"

	listing_result = await db.execute(select(BeatListing).where(BeatListing.id == listing_id))
	listing = listing_result.scalar_one_or_none()
	if listing is None:
		log.warning("beat_purchase.listing_not_found", listing_id=listing_id)
		return

	# Idempotency guard
	existing_result = await db.execute(
		select(BeatPurchase).where(
			BeatPurchase.listing_id == listing_id,
			BeatPurchase.buyer_id == buyer_id,
		)
	)
	if existing_result.scalar_one_or_none() is not None:
		log.info("beat_purchase.already_fulfilled", listing_id=listing_id, buyer_id=buyer_id)
		return

	# Load track to derive R2 key for the presigned URL
	track_result = await db.execute(select(Track).where(Track.id == listing.track_id))
	track = track_result.scalar_one_or_none()

	download_url: str | None = None
	download_expires_at: datetime | None = None

	if track and track.audio_url:
		try:
			storage_settings = StorageSettings()
			r2_public_url = storage_settings.r2_public_url.rstrip("/")
			r2_key = track.audio_url.removeprefix(f"{r2_public_url}/")
			storage = await get_storage()
			download_url = await storage.get_presigned_url(
				r2_key, expires_in=_BEAT_DOWNLOAD_EXPIRES
			)
			download_expires_at = datetime.now(UTC) + timedelta(seconds=_BEAT_DOWNLOAD_EXPIRES)
		except Exception as exc:
			# Non-fatal: purchase record is still created. User can re-request
			# via a dedicated endpoint when the link has expired.
			log.error(
				"beat_purchase.presign_failed",
				listing_id=listing_id,
				exc_type=type(exc).__name__,
				exc_msg=str(exc),
			)

	purchase = BeatPurchase(
		id=uuid7str(),
		listing_id=listing_id,
		buyer_id=buyer_id,
		seller_id=listing.seller_id,
		payment_provider=provider,
		provider_payment_id=provider_payment_id,
		amount_minor=amount_minor,
		currency=currency,
		license_type=listing.license_type,
		download_url=download_url,
		download_expires_at=download_expires_at,
	)
	db.add(purchase)

	listing.purchase_count += 1
	if listing.license_type == LicenseType.exclusive:
		listing.status = ListingStatus.sold_out
	db.add(listing)

	await db.flush()
	log.info(
		"beat_purchase.fulfilled",
		listing_id=listing_id,
		buyer_id=buyer_id,
		provider=provider,
		has_download_url=download_url is not None,
	)


async def _stripe_invoice_paid(data: dict[str, Any], db: AsyncSession) -> None:
	customer_id = data.get("customer")
	result = await db.execute(select(User).where(User.stripe_customer_id == customer_id))
	user = result.scalar_one_or_none()
	if user is None:
		return

	payment = Payment(
		id=uuid7str(),
		user_id=user.id,
		provider=PaymentProvider.stripe,
		provider_payment_id=data["id"],
		status=PaymentStatus.succeeded,
		amount_minor=data.get("amount_paid", 0),
		currency=(data.get("currency") or "usd").upper(),
		paid_at=datetime.now(UTC),
	)
	db.add(payment)
	await db.flush()


# ── Stripe portal ──────────────────────────────────────────────────────────────


@router.get(
	"/portal",
	response_model=PortalResponse,
	status_code=status.HTTP_200_OK,
	summary="Get Stripe customer portal URL",
)
async def stripe_portal(
	user: Annotated[User, Depends(get_current_active_user)],
) -> PortalResponse:
	settings = get_settings()
	stripe.api_key = settings.stripe.secret_key

	if not user.stripe_customer_id:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail={"error_code": "PAYMENT_ERROR", "message": "No Stripe customer ID on file"},
		)

	session = stripe.billing_portal.Session.create(
		customer=user.stripe_customer_id,
		return_url=f"{settings.frontend_url}/dashboard",
	)
	return PortalResponse(portal_url=session.url)


@router.get(
	"/subscription",
	response_model=SubscriptionStatusResponse,
	status_code=status.HTTP_200_OK,
	summary="Get current subscription status",
)
async def get_subscription_status(
	user: Annotated[User, Depends(get_current_active_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> SubscriptionStatusResponse:
	result = await db.execute(
		select(Subscription)
		.where(
			Subscription.user_id == user.id,
			Subscription.status.in_(["active", "trialing"]),
		)
		.order_by(Subscription.created_at.desc())
		.limit(1)
	)
	sub = result.scalar_one_or_none()

	return SubscriptionStatusResponse(
		tier=user.subscription_tier.value,
		status=user.subscription_status.value,
		current_period_end=sub.current_period_end.isoformat() if sub else None,
		cancel_at_period_end=sub.cancel_at_period_end if sub else False,
	)


# ── Paystack endpoints ─────────────────────────────────────────────────────────


@router.post(
	"/paystack/initialize",
	response_model=PaystackInitResponse,
	status_code=status.HTTP_200_OK,
	summary="Initialize a Paystack transaction for subscription",
)
async def paystack_initialize(
	body: PaystackInitRequest,
	user: Annotated[User, Depends(get_current_active_user)],
) -> PaystackInitResponse:
	settings = get_settings()

	_tier_prices_ngn = {
		SubscriptionTier.creator: 5000_00,
		SubscriptionTier.pro: 15000_00,
		SubscriptionTier.label: 50000_00,
	}
	amount_minor = _tier_prices_ngn.get(body.tier)
	if amount_minor is None:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail={
				"error_code": "VALIDATION_ERROR",
				"message": f"No Paystack price for tier {body.tier.value}",
			},
		)

	async with httpx.AsyncClient() as http:
		resp = await http.post(
			f"{settings.paystack.base_url}/transaction/initialize",
			headers={
				"Authorization": f"Bearer {settings.paystack.secret_key}",
				"Content-Type": "application/json",
			},
			json={
				"email": user.email,
				"amount": amount_minor,
				"currency": body.currency,
				"metadata": {
					"user_id": user.id,
					"tier": body.tier.value,
					"interval": body.interval.value,
				},
			},
		)

	if resp.status_code != 200:
		raise HTTPException(
			status_code=status.HTTP_502_BAD_GATEWAY,
			detail={"error_code": "PAYMENT_ERROR", "message": "Paystack initialization failed"},
		)

	data = resp.json()["data"]
	return PaystackInitResponse(
		authorization_url=data["authorization_url"],
		access_code=data["access_code"],
		reference=data["reference"],
	)


@router.get(
	"/paystack/verify/{reference}",
	response_model=PaystackVerifyResponse,
	status_code=status.HTTP_200_OK,
	summary="Verify a Paystack payment by reference",
)
async def paystack_verify(
	reference: str,
	user: Annotated[User, Depends(get_current_active_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> PaystackVerifyResponse:
	settings = get_settings()

	async with httpx.AsyncClient() as http:
		resp = await http.get(
			f"{settings.paystack.base_url}/transaction/verify/{reference}",
			headers={"Authorization": f"Bearer {settings.paystack.secret_key}"},
		)

	if resp.status_code != 200:
		raise HTTPException(
			status_code=status.HTTP_502_BAD_GATEWAY,
			detail={"error_code": "PAYMENT_ERROR", "message": "Paystack verification failed"},
		)

	data = resp.json()["data"]
	ps_status = data["status"]

	if ps_status == "success":
		# Idempotency guard — the frontend may call verify multiple times on success.
		existing = await db.execute(select(Payment).where(Payment.provider_payment_id == reference))
		if existing.scalar_one_or_none() is None:
			payment = Payment(
				id=uuid7str(),
				user_id=user.id,
				provider=PaymentProvider.paystack,
				provider_payment_id=reference,
				status=PaymentStatus.succeeded,
				amount_minor=data["amount"],
				currency=data["currency"],
				paid_at=datetime.now(UTC),
			)
			db.add(payment)

			meta = data.get("metadata", {})
			tier_str = meta.get("tier")
			if tier_str:
				try:
					user.subscription_tier = SubscriptionTier(tier_str)
					user.subscription_status = SubscriptionStatus.active
					user.paystack_customer_code = data.get("customer", {}).get("customer_code")
					db.add(user)
				except ValueError:
					pass

			await db.flush()

	return PaystackVerifyResponse(
		status=ps_status,
		reference=reference,
		amount_minor=data["amount"],
		currency=data["currency"],
	)


@router.post(
	"/paystack/webhook",
	status_code=status.HTTP_200_OK,
	summary="Handle Paystack webhook events (idempotent)",
	include_in_schema=False,
)
async def paystack_webhook(
	request: Request,
	db: Annotated[AsyncSession, Depends(get_db)],
	redis: Annotated[Redis, Depends(get_redis)],
) -> dict[str, str]:
	settings = get_settings()
	payload = await request.body()

	computed = hmac.new(
		key=settings.paystack.secret_key.encode(),
		msg=payload,
		digestmod=hashlib.sha512,
	).hexdigest()
	received = request.headers.get("x-paystack-signature", "")

	if not hmac.compare_digest(computed, received):
		log.warning("paystack.webhook.invalid_signature")
		raise HTTPException(
			status_code=400,
			detail={"error_code": "PAYMENT_WEBHOOK_ERROR", "message": "Invalid Paystack signature"},
		)

	event = json.loads(payload)
	event_ref = event.get("data", {}).get("reference", "")
	idempotency_key = f"{_PAYSTACK_EVENT_IDEMPOTENCY_PREFIX}{event_ref}"

	claimed = await redis.set(idempotency_key, "processing", nx=True, ex=_IDEMPOTENCY_TTL)
	if not claimed:
		log.info("paystack.webhook.duplicate.redis", reference=event_ref)
		return {"status": "already_processed"}

	existing = await db.execute(select(WebhookEvent).where(WebhookEvent.event_id == event_ref))
	if existing.scalar_one_or_none():
		await redis.setex(idempotency_key, _IDEMPOTENCY_TTL, "1")
		log.info("paystack.webhook.duplicate.db", reference=event_ref)
		return {"status": "already_processed"}

	event_type = event.get("event", "")
	log.info("paystack.webhook.received", event_type=event_type, reference=event_ref)

	try:
		if event_type == "charge.success":
			data = event["data"]
			meta = data.get("metadata", {})
			user_id = meta.get("user_id", "")

			if meta.get("purchase_type") == "beat":
				# ── Marketplace beat purchase ──────────────────────────────────
				listing_id = meta.get("listing_id", "")
				if user_id and listing_id:
					await _fulfil_beat_purchase(
						listing_id=listing_id,
						buyer_id=user_id,
						provider="paystack",
						provider_payment_id=data["reference"],
						amount_minor=data["amount"],
						currency=data["currency"],
						db=db,
					)
			elif user_id:
				# ── Subscription payment ───────────────────────────────────────
				result = await db.execute(select(User).where(User.id == user_id))
				user = result.scalar_one_or_none()
				if user:
					tier_str = meta.get("tier")
					if tier_str:
						try:
							user.subscription_tier = SubscriptionTier(tier_str)
							user.subscription_status = SubscriptionStatus.active
							user.paystack_customer_code = data.get("customer", {}).get(
								"customer_code"
							)
							db.add(user)
						except ValueError:
							pass

					payment = Payment(
						id=uuid7str(),
						user_id=user.id,
						provider=PaymentProvider.paystack,
						provider_payment_id=data["reference"],
						status=PaymentStatus.succeeded,
						amount_minor=data["amount"],
						currency=data["currency"],
						paid_at=datetime.now(UTC),
					)
					db.add(payment)
					await db.flush()
	except Exception as exc:
		await redis.delete(idempotency_key)
		log.error("paystack.webhook.handler_error", reference=event_ref, error=str(exc))
		raise HTTPException(
			status_code=500, detail={"error_code": "PAYMENT_WEBHOOK_ERROR", "message": str(exc)}
		)

	await _add_db_object(
		db,
		WebhookEvent(
			id=uuid7str(),
			event_id=event_ref,
			provider=PaymentProvider.paystack,
			event_type=event_type,
			processed_at=datetime.now(UTC),
		),
	)
	await db.flush()

	await redis.setex(idempotency_key, _IDEMPOTENCY_TTL, "1")
	return {"status": "ok"}
