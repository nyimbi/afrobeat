"""Unit tests for reference-track steering helpers.

Pure functions — no DB, Redis, R2, or audio decoding required.
"""

from __future__ import annotations

from gbedu_worker.pipelines.generation_pipeline import (
	_ML_BPM_MAX,
	_ML_BPM_MIN,
	apply_reference_steering,
	describe_reference,
)


def _payload(**overrides):  # type: ignore[no-untyped-def]
	base = {"job_id": "job-1", "prompt": "lagos night drive", "bpm": None}
	base.update(overrides)
	return base


# ── describe_reference ────────────────────────────────────────────────────────


def test_describe_reference_full() -> None:
	assert describe_reference({"bpm": 103.7, "key": "A minor"}) == "~104 BPM in A minor"


def test_describe_reference_without_bpm() -> None:
	assert describe_reference({"bpm": None, "key": "D major"}) == "key of D major"


# ── apply_reference_steering ──────────────────────────────────────────────────


def test_measured_bpm_applied_when_user_bpm_unset() -> None:
	out = apply_reference_steering(_payload(), {"bpm": 104.2, "key": "A minor", "energy": 7.0})
	assert out["bpm"] == 104
	assert "104-BPM groove" in out["prompt"]
	assert "A minor" in out["prompt"]
	# Original prompt preserved
	assert out["prompt"].startswith("lagos night drive")


def test_user_bpm_always_wins() -> None:
	out = apply_reference_steering(
		_payload(bpm=120), {"bpm": 96.0, "key": "G major", "energy": 5.0}
	)
	assert out["bpm"] == 120
	# Character sentence still references the measured feel
	assert "96-BPM groove" in out["prompt"]


def test_measured_bpm_clamped_to_ml_bounds() -> None:
	out = apply_reference_steering(_payload(), {"bpm": 172.0, "key": "F minor", "energy": 9.0})
	assert out["bpm"] == _ML_BPM_MAX
	out = apply_reference_steering(_payload(), {"bpm": 62.0, "key": "C major", "energy": 3.0})
	assert out["bpm"] == _ML_BPM_MIN


def test_empty_analysis_leaves_payload_untouched() -> None:
	payload = _payload()
	assert apply_reference_steering(payload, {}) == payload
