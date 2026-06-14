"""Unit tests for all Pydantic schemas: valid data, invalid data, extra='forbid'."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from gbedu_core.schemas import (
	BeatListingRead,
	BeatPurchaseRead,
	GenerationRequest,
	GenerationResponse,
	InvoiceRead,
	JobRead,
	JobStatusUpdate,
	PaymentRead,
	RefreshRequest,
	SubscriptionRead,
	TokenResponse,
	TrackCreate,
	TrackPublic,
	TrackRead,
	UserCreate,
	UserPublic,
	UserRead,
	UserUpdate,
	VoiceModelRead,
)


# ── UserCreate ─────────────────────────────────────────────────────────────────

def test_user_create_valid():
	u = UserCreate(
		email="test@example.com",
		password="SecurePass1",
		full_name="Ade Ojo",
		preferred_language="en",
	)
	assert u.email == "test@example.com"
	assert u.full_name == "Ade Ojo"


def test_user_create_invalid_email():
	with pytest.raises(ValidationError) as exc_info:
		UserCreate(email="not-an-email", password="SecurePass1", full_name="Ade")
	errors = exc_info.value.errors()
	assert any(e["loc"] == ("email",) for e in errors)


def test_user_create_password_too_short():
	with pytest.raises(ValidationError) as exc_info:
		UserCreate(email="a@b.com", password="short", full_name="Ade")
	errors = exc_info.value.errors()
	assert any(e["loc"] == ("password",) for e in errors)


def test_user_create_extra_field_forbidden():
	with pytest.raises(ValidationError) as exc_info:
		UserCreate(
			email="a@b.com",
			password="SecurePass1",
			full_name="Ade",
			extra_field="should_fail",
		)
	errors = exc_info.value.errors()
	assert any(e["type"] == "extra_forbidden" for e in errors)


def test_user_create_invalid_language():
	with pytest.raises(ValidationError):
		UserCreate(
			email="a@b.com",
			password="SecurePass1",
			full_name="Ade",
			preferred_language="klingon",
		)


# ── UserUpdate ─────────────────────────────────────────────────────────────────

def test_user_update_all_none_valid():
	u = UserUpdate()
	assert u.full_name is None
	assert u.new_password is None


def test_user_update_extra_forbidden():
	with pytest.raises(ValidationError) as exc_info:
		UserUpdate(unknown_key="value")
	assert any(e["type"] == "extra_forbidden" for e in exc_info.value.errors())


# ── TrackCreate ────────────────────────────────────────────────────────────────

def test_track_create_valid():
	t = TrackCreate(
		title="Summer Nights",
		prompt="Slow afropop, romantic vibe, 90bpm",
		sub_genre="afropop",
		language="english",
		energy_level=6,
		duration_seconds=120,
		bpm=90,
	)
	assert t.title == "Summer Nights"
	assert t.energy_level == 6


def test_track_create_energy_out_of_range():
	with pytest.raises(ValidationError) as exc_info:
		TrackCreate(
			title="X",
			prompt="test",
			sub_genre="afropop",
			language="english",
			energy_level=11,
		)
	assert any(e["loc"] == ("energy_level",) for e in exc_info.value.errors())


def test_track_create_bpm_out_of_range():
	with pytest.raises(ValidationError):
		TrackCreate(
			title="X",
			prompt="test",
			sub_genre="afropop",
			language="english",
			bpm=200,
		)


def test_track_create_invalid_sub_genre():
	with pytest.raises(ValidationError):
		TrackCreate(
			title="X",
			prompt="test",
			sub_genre="polka",
			language="english",
		)


def test_track_create_extra_forbidden():
	with pytest.raises(ValidationError) as exc_info:
		TrackCreate(
			title="X",
			prompt="test",
			sub_genre="afropop",
			language="english",
			secret="value",
		)
	assert any(e["type"] == "extra_forbidden" for e in exc_info.value.errors())


# ── GenerationRequest ──────────────────────────────────────────────────────────

def test_generation_request_strips_prompt():
	r = GenerationRequest(
		prompt="  groovy beat  ",
		sub_genre="afropop",
		language="english",
	)
	assert r.prompt == "groovy beat"


def test_generation_request_duration_bounds():
	with pytest.raises(ValidationError):
		GenerationRequest(
			prompt="test",
			sub_genre="afropop",
			language="english",
			duration_seconds=10,   # below 30
		)


def test_generation_request_extra_forbidden():
	with pytest.raises(ValidationError) as exc_info:
		GenerationRequest(
			prompt="test",
			sub_genre="afropop",
			language="english",
			malicious_field=True,
		)
	assert any(e["type"] == "extra_forbidden" for e in exc_info.value.errors())


# ── JobStatusUpdate ────────────────────────────────────────────────────────────

def test_job_status_update_valid():
	u = JobStatusUpdate(status="complete", progress_percent=100)
	assert u.status.value == "complete"
	assert u.progress_percent == 100


def test_job_status_update_progress_out_of_range():
	with pytest.raises(ValidationError):
		JobStatusUpdate(status="complete", progress_percent=101)


def test_job_status_update_invalid_status():
	with pytest.raises(ValidationError):
		JobStatusUpdate(status="flying")


# ── TokenResponse ──────────────────────────────────────────────────────────────

def test_token_response_defaults():
	t = TokenResponse(
		access_token="abc",
		refresh_token="def",
		expires_in=1800,
	)
	assert t.token_type == "bearer"


def test_token_response_extra_forbidden():
	with pytest.raises(ValidationError) as exc_info:
		TokenResponse(
			access_token="abc",
			refresh_token="def",
			expires_in=1800,
			extra="bad",
		)
	assert any(e["type"] == "extra_forbidden" for e in exc_info.value.errors())


# ── RefreshRequest ─────────────────────────────────────────────────────────────

def test_refresh_request_valid():
	r = RefreshRequest(refresh_token="some_token")
	assert r.refresh_token == "some_token"


def test_refresh_request_extra_forbidden():
	with pytest.raises(ValidationError) as exc_info:
		RefreshRequest(refresh_token="tok", bonus="nope")
	assert any(e["type"] == "extra_forbidden" for e in exc_info.value.errors())
