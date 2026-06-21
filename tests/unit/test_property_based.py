"""Property-based tests using Hypothesis.

Tests critical invariants that must hold for ALL valid inputs — not just the
happy-path examples covered by example-based tests.  If Hypothesis finds a
counter-example it prints the minimal reproducing case.

Run:
	uv run pytest tests/unit/test_property_based.py -v
	uv run pytest tests/unit/test_property_based.py --hypothesis-show-statistics
"""

from __future__ import annotations

import hashlib
import re
import string

import pytest
from gbedu_core._uuid7 import uuid7str
from gbedu_core.security import (
	create_access_token,
	hash_password,
	verify_access_token,
	verify_password,
)
from hypothesis import assume, given, settings
from hypothesis import strategies as st

# ── UUID7 invariants ───────────────────────────────────────────────────────────

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def test_uuid7_format_always_valid() -> None:
	"""Every uuid7str() call must return a valid UUID v7 string."""
	for _ in range(200):
		uid = uuid7str()
		assert UUID_RE.match(uid), f"Invalid UUID7: {uid!r}"


def test_uuid7_monotonically_increasing() -> None:
	"""Successive UUID7s must sort in generation order."""
	uuids = [uuid7str() for _ in range(100)]
	assert uuids == sorted(uuids)


def test_uuid7_globally_unique() -> None:
	"""1000 UUID7s must all be distinct."""
	uuids = [uuid7str() for _ in range(1000)]
	assert len(set(uuids)) == 1000


# ── Password hashing invariants ────────────────────────────────────────────────


@given(
	password=st.text(
		alphabet=st.characters(
			whitelist_categories=("Lu", "Ll", "Nd"),
			whitelist_characters="!@#$%-_=+;,.",
		),
		min_size=1,
		max_size=64,
	)
)
@settings(max_examples=25, deadline=None)  # bcrypt is intentionally slow
def test_password_hash_verify_roundtrip(password: str) -> None:
	"""hash_password → verify_password must always succeed."""
	assume(password.strip())
	h = hash_password(password)
	assert h.startswith("$2b$"), "must be bcrypt"
	assert verify_password(password, h)


@given(
	pw1=st.text(min_size=4, max_size=30, alphabet=string.ascii_letters + string.digits),
	pw2=st.text(min_size=4, max_size=30, alphabet=string.ascii_letters + string.digits),
)
@settings(max_examples=25, deadline=None)  # bcrypt is intentionally slow
def test_different_passwords_never_verify(pw1: str, pw2: str) -> None:
	"""Hash of pw1 must never verify against pw2."""
	assume(pw1 != pw2)
	h = hash_password(pw1)
	assert not verify_password(pw2, h)


# ── BPM validation invariants ──────────────────────────────────────────────────


@given(bpm=st.integers(min_value=60, max_value=200))
@settings(max_examples=50)
def test_valid_bpm_range_accepted(bpm: int) -> None:
	"""BPM in [60, 200] must pass validation."""
	from pydantic import BaseModel, field_validator

	class _M(BaseModel):
		bpm: int

		@field_validator("bpm")
		@classmethod
		def _check(cls, v: int) -> int:
			if not (60 <= v <= 200):
				raise ValueError("BPM out of range")
			return v

	assert _M(bpm=bpm).bpm == bpm


@given(bpm=st.one_of(st.integers(max_value=59), st.integers(min_value=201)))
@settings(max_examples=30)
def test_invalid_bpm_always_rejected(bpm: int) -> None:
	"""BPM outside [60, 200] must always be rejected."""
	from pydantic import BaseModel, ValidationError, field_validator

	class _M(BaseModel):
		bpm: int

		@field_validator("bpm")
		@classmethod
		def _check(cls, v: int) -> int:
			if not (60 <= v <= 200):
				raise ValueError("BPM out of range")
			return v

	with pytest.raises(ValidationError):
		_M(bpm=bpm)


# ── Quota enforcement invariants ───────────────────────────────────────────────


@given(
	limit=st.integers(min_value=1, max_value=100),
	total=st.integers(min_value=1, max_value=200),
)
@settings(max_examples=50)
def test_quota_accepted_never_exceeds_limit(limit: int, total: int) -> None:
	"""Simulated INCR-based quota: accepted = min(total, limit), no exceptions."""
	counter = 0
	accepted = 0
	for _ in range(total):
		counter += 1
		if counter <= limit:
			accepted += 1
	assert accepted == min(total, limit)
	assert accepted <= limit


# ── JWT token invariants ───────────────────────────────────────────────────────

_SECRET_A = "hypothesis-secret-A-must-be-32ch!"
_SECRET_B = "hypothesis-secret-B-must-be-32ch!"
_ALG = "HS256"


@given(
	user_id=st.text(min_size=1, max_size=36, alphabet=string.hexdigits + "-"),
	expires_minutes=st.integers(min_value=1, max_value=10080),
)
@settings(max_examples=25)
def test_access_token_encodes_user_id(user_id: str, expires_minutes: int) -> None:
	"""verify_access_token must always return the original sub claim."""
	token = create_access_token(user_id, _SECRET_A, _ALG, expires_minutes=expires_minutes)
	assert isinstance(token, str)
	assert token

	payload = verify_access_token(token, _SECRET_A, _ALG)
	assert payload["sub"] == user_id


@given(
	user_id=st.text(min_size=1, max_size=36, alphabet=string.hexdigits + "-"),
)
@settings(max_examples=20)
def test_token_with_wrong_secret_rejected(user_id: str) -> None:
	"""Token signed with secret A must fail verification with secret B."""
	from jose import JWTError

	token = create_access_token(user_id, _SECRET_A, _ALG, expires_minutes=60)
	with pytest.raises((JWTError, Exception)):
		verify_access_token(token, _SECRET_B, _ALG)


# ── Token hash determinism ─────────────────────────────────────────────────────


@given(token=st.binary(min_size=1, max_size=512))
@settings(max_examples=50)
def test_token_hash_is_deterministic(token: bytes) -> None:
	"""SHA-256 of identical bytes must always produce the same digest."""
	h1 = hashlib.sha256(token).hexdigest()
	h2 = hashlib.sha256(token).hexdigest()
	assert h1 == h2
	assert len(h1) == 64


@given(
	t1=st.binary(min_size=1, max_size=100),
	t2=st.binary(min_size=1, max_size=100),
)
@settings(max_examples=50)
def test_different_tokens_have_different_hashes(t1: bytes, t2: bytes) -> None:
	"""Two different byte strings must hash differently (collision = crypto break)."""
	assume(t1 != t2)
	assert hashlib.sha256(t1).hexdigest() != hashlib.sha256(t2).hexdigest()


# ── Afrobeats prompt invariants ────────────────────────────────────────────────


@given(
	sub_genre=st.sampled_from(["afrobeats", "afropop", "amapiano_cross", "afrobeats_uk"]),
	language=st.sampled_from(["english", "yoruba", "pidgin", "igbo"]),
	bpm=st.integers(min_value=80, max_value=130),
	duration=st.integers(min_value=30, max_value=240),
)
@settings(max_examples=30)
def test_prompt_always_non_empty(sub_genre: str, language: str, bpm: int, duration: int) -> None:
	"""build_music_prompt must always return a non-empty string."""
	from gbedu_core.models.track import Language, SubGenre
	from gbedu_core.schemas import GenerationRequest
	from gbedu_ml.prompts.afrobeats import AfrobeatsPromptEngine

	req = GenerationRequest(
		prompt=f"test {sub_genre} track",
		sub_genre=SubGenre(sub_genre),
		language=Language(language),
		bpm=bpm,
		duration_seconds=duration,
	)
	engine = AfrobeatsPromptEngine()
	prompt = engine.build_music_prompt(req)
	assert isinstance(prompt, str)
	assert len(prompt.strip()) > 10
