"""Unit tests for /api/v1/marketplace/* route handlers.

Strategy:
- Override get_db / get_current_active_user via app.dependency_overrides.
- browse_beats and get_beat are public (no auth dep) — override only get_db.
- purchase_beat / my_listings / my_purchases need auth.
- require_tier(pro) overridden for create_listing tests.
- Stripe / Paystack calls are patched at the module level.
- Mock model objects with MagicMock() — avoids SQLAlchemy mapper state issues
  that arise from Model.__new__() in isolated unit tests without a DB session.
- No @pytest.mark.asyncio — asyncio_mode = "auto" is set project-wide.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.testclient import TestClient

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost/gbedu_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("GBEDU_ML_API_KEY", "test-ml-internal-api-key")

from gbedu_core.models.user import SubscriptionTier, SubscriptionStatus
from gbedu_core.models.track import SubGenre, Language, TrackStatus
from gbedu_core.models.marketplace import LicenseType, ListingStatus


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_user(tier: str = "pro", user_id: str = "user-test-001") -> MagicMock:
	user = MagicMock()
	user.id = user_id
	user.email = "test@example.com"
	user.full_name = "Test User"
	user.subscription_tier = SubscriptionTier(tier)
	user.subscription_status = SubscriptionStatus.active
	user.is_verified = True
	user.is_active = True
	user.deleted_at = None
	return user


def _make_track(user_id: str = "user-test-001") -> MagicMock:
	track = MagicMock()
	track.id = "track-test-001"
	track.user_id = user_id
	track.title = "Naija Banger"
	track.prompt = "afropop 110bpm"
	track.sub_genre = SubGenre.afropop
	track.language = Language.english
	track.bpm = 110
	track.key = "Am"
	track.energy_level = 7
	track.duration_seconds = 200
	track.status = TrackStatus.ready
	track.audio_url = "https://cdn.example.com/track.mp3"
	track.audio_url_watermarked = "https://cdn.example.com/track-wm.mp3"
	track.cover_art_url = None
	track.lyrics = None
	track.is_public = True
	track.play_count = 0
	track.share_count = 0
	track.deleted_at = None
	track.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
	return track


def _make_listing(
	seller_id: str = "user-test-001",
	price_minor: int = 1000,
	license_type: LicenseType = LicenseType.non_exclusive,
	status: ListingStatus = ListingStatus.active,
) -> MagicMock:
	listing = MagicMock()
	listing.id = "listing-test-001"
	listing.track_id = "track-test-001"
	listing.seller_id = seller_id
	listing.title = "Naija Banger"
	listing.description = "Hot afropop beat"
	listing.status = status
	listing.license_type = license_type
	listing.price_minor = price_minor
	listing.price_decimal = price_minor / 100.0
	listing.currency = "USD"
	listing.view_count = 0
	listing.purchase_count = 0
	listing.tags = ["afropop", "naija"]
	listing.preview_url = "https://cdn.example.com/track-wm.mp3"
	# Use a real datetime so isoformat() returns a string; the router calls
	# listing.created_at.isoformat() and Pydantic expects a str, not a MagicMock.
	listing.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
	listing.created_at = MagicMock()
	listing.created_at.isoformat.return_value = "2025-01-01T00:00:00+00:00"
	listing.deleted_at = None
	return listing


def _make_purchase(buyer_id: str = "buyer-001", listing_id: str = "listing-test-001") -> MagicMock:
	purchase = MagicMock()
	purchase.id = "purchase-test-001"
	purchase.listing_id = listing_id
	purchase.buyer_id = buyer_id
	purchase.seller_id = "user-test-001"
	purchase.payment_provider = "free"
	purchase.provider_payment_id = "free-0001"
	purchase.amount_minor = 0
	purchase.currency = "USD"
	purchase.license_type = LicenseType.non_exclusive
	purchase.download_url = None
	# created_at.isoformat() must return a str for Pydantic serialization
	purchase.created_at = MagicMock()
	purchase.created_at.isoformat.return_value = "2025-01-01T00:00:00+00:00"
	return purchase


def _build_client(tier: str = "pro", user_id: str = "user-test-001"):
	from gbedu_api.main import app
	from gbedu_api.deps import get_db, get_current_active_user

	user = _make_user(tier, user_id)
	mock_db = AsyncMock()

	async def _override_db():
		yield mock_db

	app.dependency_overrides[get_db] = _override_db
	app.dependency_overrides[get_current_active_user] = lambda: user

	client = TestClient(app, raise_server_exceptions=False)
	return client, mock_db, user


def teardown_function():
	from gbedu_api.main import app
	app.dependency_overrides.clear()


# ── GET /marketplace/beats ─────────────────────────────────────────────────────

def test_browse_beats_returns_paginated_listings():
	from gbedu_api.main import app
	from gbedu_api.deps import get_db

	mock_db = AsyncMock()
	listing = _make_listing()
	track = _make_track()

	count_result = MagicMock()
	count_result.scalar_one.return_value = 1
	rows_result = MagicMock()
	rows_result.all.return_value = [(listing, track)]
	mock_db.execute = AsyncMock(side_effect=[count_result, rows_result])

	async def _override_db():
		yield mock_db

	app.dependency_overrides[get_db] = _override_db
	client = TestClient(app, raise_server_exceptions=False)

	resp = client.get("/api/v1/marketplace/beats")

	assert resp.status_code == 200
	body = resp.json()
	assert body["total"] == 1
	assert len(body["items"]) == 1
	assert body["items"][0]["id"] == "listing-test-001"


def test_browse_beats_empty_marketplace():
	from gbedu_api.main import app
	from gbedu_api.deps import get_db

	mock_db = AsyncMock()
	count_result = MagicMock()
	count_result.scalar_one.return_value = 0
	rows_result = MagicMock()
	rows_result.all.return_value = []
	mock_db.execute = AsyncMock(side_effect=[count_result, rows_result])

	async def _override_db():
		yield mock_db

	app.dependency_overrides[get_db] = _override_db
	client = TestClient(app, raise_server_exceptions=False)

	resp = client.get("/api/v1/marketplace/beats")

	assert resp.status_code == 200
	assert resp.json()["total"] == 0
	assert resp.json()["items"] == []


# ── GET /marketplace/beats/{beat_id} ──────────────────────────────────────────

def test_get_beat_found_increments_view_count():
	from gbedu_api.main import app
	from gbedu_api.deps import get_db

	mock_db = AsyncMock()
	mock_db.add = MagicMock()
	mock_db.flush = AsyncMock()
	listing = _make_listing()
	listing.view_count = 3
	track = _make_track()

	listing_result = MagicMock()
	listing_result.scalar_one_or_none.return_value = listing
	track_result = MagicMock()
	track_result.scalar_one_or_none.return_value = track
	mock_db.execute = AsyncMock(side_effect=[listing_result, track_result])

	async def _override_db():
		yield mock_db

	app.dependency_overrides[get_db] = _override_db
	client = TestClient(app, raise_server_exceptions=False)

	resp = client.get("/api/v1/marketplace/beats/listing-test-001")

	assert resp.status_code == 200
	assert listing.view_count == 4


def test_get_beat_not_found_returns_404():
	from gbedu_api.main import app
	from gbedu_api.deps import get_db

	mock_db = AsyncMock()
	result = MagicMock()
	result.scalar_one_or_none.return_value = None
	mock_db.execute = AsyncMock(return_value=result)

	async def _override_db():
		yield mock_db

	app.dependency_overrides[get_db] = _override_db
	client = TestClient(app, raise_server_exceptions=False)

	resp = client.get("/api/v1/marketplace/beats/ghost-listing")

	assert resp.status_code == 404


# ── POST /marketplace/beats (create listing) ───────────────────────────────────

def test_create_listing_pro_tier_rejects_missing_track():
	"""create_listing returns 404 when the track doesn't exist or isn't owned.

	This covers the full guard path without hitting BeatListing() construction,
	which requires a live SQLAlchemy session to configure mapper state.
	"""
	from gbedu_api.main import app
	from gbedu_api.deps import get_db, get_current_active_user, require_tier

	user = _make_user(tier="pro")
	mock_db = AsyncMock()
	_tier_dep = require_tier(SubscriptionTier.pro)

	# Track query returns None — handler raises 404 before BeatListing() is called
	track_result = MagicMock()
	track_result.scalar_one_or_none.return_value = None
	mock_db.execute = AsyncMock(return_value=track_result)

	async def _override_db():
		yield mock_db

	app.dependency_overrides[get_db] = _override_db
	app.dependency_overrides[get_current_active_user] = lambda: user
	app.dependency_overrides[_tier_dep] = lambda: user

	client = TestClient(app, raise_server_exceptions=False)
	resp = client.post("/api/v1/marketplace/beats", json={
		"track_id": "nonexistent-track",
		"title": "Ghost Beat",
		"price_minor": 500,
	})

	assert resp.status_code == 404
	assert resp.json()["detail"]["error_code"] == "NOT_FOUND"


def test_create_listing_pro_tier_rejects_free_user():
	"""create_listing requires Pro tier — free user gets 403."""
	from gbedu_api.main import app
	from gbedu_api.deps import get_db, get_current_active_user, require_tier
	from fastapi import HTTPException, status

	user = _make_user(tier="free")
	mock_db = AsyncMock()
	_tier_dep = require_tier(SubscriptionTier.pro)

	async def _override_db():
		yield mock_db

	def _deny():
		raise HTTPException(
			status_code=status.HTTP_403_FORBIDDEN,
			detail={
				"error_code": "AUTHORIZATION_ERROR",
				"message": "This feature requires pro subscription or higher",
			},
		)

	app.dependency_overrides[get_db] = _override_db
	app.dependency_overrides[get_current_active_user] = lambda: user
	app.dependency_overrides[_tier_dep] = _deny

	client = TestClient(app, raise_server_exceptions=False)
	resp = client.post("/api/v1/marketplace/beats", json={
		"track_id": "track-test-001",
		"title": "Beat",
		"price_minor": 500,
	})

	assert resp.status_code == 403


def test_create_listing_track_not_found_returns_404():
	from gbedu_api.main import app
	from gbedu_api.deps import get_db, get_current_active_user, require_tier

	user = _make_user(tier="pro")
	mock_db = AsyncMock()
	_tier_dep = require_tier(SubscriptionTier.pro)

	track_result = MagicMock()
	track_result.scalar_one_or_none.return_value = None
	mock_db.execute = AsyncMock(return_value=track_result)

	async def _override_db():
		yield mock_db

	app.dependency_overrides[get_db] = _override_db
	app.dependency_overrides[get_current_active_user] = lambda: user
	app.dependency_overrides[_tier_dep] = lambda: user

	client = TestClient(app, raise_server_exceptions=False)
	resp = client.post("/api/v1/marketplace/beats", json={
		"track_id": "nonexistent-track",
		"title": "Ghost Track",
		"price_minor": 500,
	})

	assert resp.status_code == 404


def test_create_listing_duplicate_returns_409():
	from gbedu_api.main import app
	from gbedu_api.deps import get_db, get_current_active_user, require_tier

	user = _make_user(tier="pro")
	mock_db = AsyncMock()
	track = _make_track()
	existing_listing = _make_listing()
	_tier_dep = require_tier(SubscriptionTier.pro)

	track_result = MagicMock()
	track_result.scalar_one_or_none.return_value = track
	existing_result = MagicMock()
	existing_result.scalar_one_or_none.return_value = existing_listing
	mock_db.execute = AsyncMock(side_effect=[track_result, existing_result])

	async def _override_db():
		yield mock_db

	app.dependency_overrides[get_db] = _override_db
	app.dependency_overrides[get_current_active_user] = lambda: user
	app.dependency_overrides[_tier_dep] = lambda: user

	client = TestClient(app, raise_server_exceptions=False)
	resp = client.post("/api/v1/marketplace/beats", json={
		"track_id": "track-test-001",
		"title": "Duplicate",
		"price_minor": 500,
	})

	assert resp.status_code == 409
	assert resp.json()["detail"]["error_code"] == "CONFLICT"


# ── POST /marketplace/beats/{beat_id}/purchase ────────────────────────────────

def test_purchase_beat_inactive_listing_returns_404():
	"""purchase_beat returns 404 when the listing is not active.

	This exercises the guard path without hitting BeatPurchase() construction,
	which requires a live SQLAlchemy session to configure mapper state.
	"""
	client, mock_db, _ = _build_client(tier="free", user_id="buyer-999")

	result = MagicMock()
	result.scalar_one_or_none.return_value = None  # listing not found / not active
	mock_db.execute = AsyncMock(return_value=result)

	resp = client.post("/api/v1/marketplace/beats/inactive-listing/purchase", json={})

	assert resp.status_code == 404
	assert resp.json()["detail"]["error_code"] == "NOT_FOUND"


def test_purchase_own_beat_returns_422():
	client, mock_db, _ = _build_client(tier="pro", user_id="user-test-001")
	listing = _make_listing(seller_id="user-test-001", price_minor=500)

	listing_result = MagicMock()
	listing_result.scalar_one_or_none.return_value = listing
	mock_db.execute = AsyncMock(return_value=listing_result)

	resp = client.post("/api/v1/marketplace/beats/listing-test-001/purchase", json={})

	assert resp.status_code == 422
	assert "own beat" in resp.json()["detail"]["message"].lower()


def test_purchase_already_purchased_returns_409():
	client, mock_db, _ = _build_client(tier="free", user_id="buyer-999")
	listing = _make_listing(seller_id="other-seller-001", price_minor=0)
	existing = _make_purchase(buyer_id="buyer-999")

	listing_result = MagicMock()
	listing_result.scalar_one_or_none.return_value = listing
	existing_result = MagicMock()
	existing_result.scalar_one_or_none.return_value = existing
	mock_db.execute = AsyncMock(side_effect=[listing_result, existing_result])

	resp = client.post("/api/v1/marketplace/beats/listing-test-001/purchase", json={})

	assert resp.status_code == 409
	assert resp.json()["detail"]["error_code"] == "CONFLICT"


def test_purchase_listing_not_found_returns_404():
	client, mock_db, _ = _build_client(user_id="buyer-999")

	result = MagicMock()
	result.scalar_one_or_none.return_value = None
	mock_db.execute = AsyncMock(return_value=result)

	resp = client.post("/api/v1/marketplace/beats/ghost-listing/purchase", json={})

	assert resp.status_code == 404


# ── GET /marketplace/my-listings ──────────────────────────────────────────────

def test_my_listings_returns_seller_listings():
	client, mock_db, _ = _build_client()
	listing = _make_listing()

	count_result = MagicMock()
	count_result.scalar_one.return_value = 1
	listings_result = MagicMock()
	listings_result.scalars.return_value.all.return_value = [listing]
	mock_db.execute = AsyncMock(side_effect=[count_result, listings_result])

	resp = client.get("/api/v1/marketplace/my-listings")

	assert resp.status_code == 200
	body = resp.json()
	assert body["total"] == 1
	assert body["items"][0]["seller_id"] == "user-test-001"


# ── GET /marketplace/my-purchases ─────────────────────────────────────────────

def test_my_purchases_returns_buyer_purchases():
	client, mock_db, _ = _build_client(user_id="buyer-999")
	purchase = _make_purchase(buyer_id="buyer-999")

	count_result = MagicMock()
	count_result.scalar_one.return_value = 1
	purchases_result = MagicMock()
	purchases_result.scalars.return_value.all.return_value = [purchase]
	mock_db.execute = AsyncMock(side_effect=[count_result, purchases_result])

	resp = client.get("/api/v1/marketplace/my-purchases")

	assert resp.status_code == 200
	body = resp.json()
	assert body["total"] == 1
	assert body["items"][0]["id"] == "purchase-test-001"
