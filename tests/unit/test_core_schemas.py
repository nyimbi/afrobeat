"""Unit tests for all Pydantic schemas: valid data, invalid data, extra='forbid'."""

from __future__ import annotations

import pytest
from gbedu_core.schemas import (
	GenerationRequest,
	JobStatusUpdate,
	RefreshRequest,
	TokenResponse,
	TrackCreate,
	UserCreate,
	UserUpdate,
)
from pydantic import ValidationError

# ── UserCreate ─────────────────────────────────────────────────────────────────


def test_user_create_valid() -> None:
	u = UserCreate(
		email="test@example.com",
		password="SecurePass1",
		full_name="Ade Ojo",
		preferred_language="en",
	)
	assert u.email == "test@example.com"
	assert u.full_name == "Ade Ojo"


def test_user_create_invalid_email() -> None:
	with pytest.raises(ValidationError) as exc_info:
		UserCreate(email="not-an-email", password="SecurePass1", full_name="Ade")
	errors = exc_info.value.errors()
	assert any(e["loc"] == ("email",) for e in errors)


def test_user_create_password_too_short() -> None:
	with pytest.raises(ValidationError) as exc_info:
		UserCreate(email="a@b.com", password="short", full_name="Ade")
	errors = exc_info.value.errors()
	assert any(e["loc"] == ("password",) for e in errors)


def test_user_create_extra_field_forbidden() -> None:
	with pytest.raises(ValidationError) as exc_info:
		UserCreate(
			email="a@b.com",
			password="SecurePass1",
			full_name="Ade",
			extra_field="should_fail",
		)
	errors = exc_info.value.errors()
	assert any(e["type"] == "extra_forbidden" for e in errors)


def test_user_create_invalid_language() -> None:
	with pytest.raises(ValidationError):
		UserCreate(
			email="a@b.com",
			password="SecurePass1",
			full_name="Ade",
			preferred_language="klingon",
		)


# ── UserUpdate ─────────────────────────────────────────────────────────────────


def test_user_update_all_none_valid() -> None:
	u = UserUpdate()
	assert u.full_name is None
	assert u.new_password is None


def test_user_update_extra_forbidden() -> None:
	with pytest.raises(ValidationError) as exc_info:
		UserUpdate(unknown_key="value")
	assert any(e["type"] == "extra_forbidden" for e in exc_info.value.errors())


# ── TrackCreate ────────────────────────────────────────────────────────────────


def test_track_create_valid() -> None:
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


def test_track_create_energy_out_of_range() -> None:
	with pytest.raises(ValidationError) as exc_info:
		TrackCreate(
			title="X",
			prompt="test",
			sub_genre="afropop",
			language="english",
			energy_level=11,
		)
	assert any(e["loc"] == ("energy_level",) for e in exc_info.value.errors())


def test_track_create_bpm_out_of_range() -> None:
	with pytest.raises(ValidationError):
		TrackCreate(
			title="X",
			prompt="test",
			sub_genre="afropop",
			language="english",
			bpm=200,
		)


def test_track_create_invalid_sub_genre() -> None:
	with pytest.raises(ValidationError):
		TrackCreate(
			title="X",
			prompt="test",
			sub_genre="polka",
			language="english",
		)


def test_track_create_extra_forbidden() -> None:
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


def test_generation_request_strips_prompt() -> None:
	r = GenerationRequest(
		prompt="  groovy beat  ",
		sub_genre="afropop",
		language="english",
	)
	assert r.prompt == "groovy beat"


def test_generation_request_duration_bounds() -> None:
	with pytest.raises(ValidationError):
		GenerationRequest(
			prompt="test",
			sub_genre="afropop",
			language="english",
			duration_seconds=10,  # below 30
		)


def test_generation_request_extra_forbidden() -> None:
	with pytest.raises(ValidationError) as exc_info:
		GenerationRequest(
			prompt="test",
			sub_genre="afropop",
			language="english",
			malicious_field=True,
		)
	assert any(e["type"] == "extra_forbidden" for e in exc_info.value.errors())


# ── JobStatusUpdate ────────────────────────────────────────────────────────────


def test_job_status_update_valid() -> None:
	u = JobStatusUpdate(status="complete", progress_percent=100)
	assert u.status.value == "complete"
	assert u.progress_percent == 100


def test_job_status_update_progress_out_of_range() -> None:
	with pytest.raises(ValidationError):
		JobStatusUpdate(status="complete", progress_percent=101)


def test_job_status_update_invalid_status() -> None:
	with pytest.raises(ValidationError):
		JobStatusUpdate(status="flying")


# ── TokenResponse ──────────────────────────────────────────────────────────────


def test_token_response_defaults() -> None:
	t = TokenResponse(
		access_token="abc",
		refresh_token="def",
		expires_in=1800,
	)
	assert t.token_type == "bearer"


def test_token_response_extra_forbidden() -> None:
	with pytest.raises(ValidationError) as exc_info:
		TokenResponse(
			access_token="abc",
			refresh_token="def",
			expires_in=1800,
			extra="bad",
		)
	assert any(e["type"] == "extra_forbidden" for e in exc_info.value.errors())


# ── RefreshRequest ─────────────────────────────────────────────────────────────


def test_refresh_request_valid() -> None:
	r = RefreshRequest(refresh_token="some_token")
	assert r.refresh_token == "some_token"


def test_refresh_request_extra_forbidden() -> None:
	with pytest.raises(ValidationError) as exc_info:
		RefreshRequest(refresh_token="tok", bonus="nope")
	assert any(e["type"] == "extra_forbidden" for e in exc_info.value.errors())
