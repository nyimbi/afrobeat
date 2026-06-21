from __future__ import annotations

"""Instantiation and property tests for ML model classes.

These tests cover __init__ and model_id without touching GPU code.
All load() and generate() methods are marked # pragma: no cover since they
dispatch to GPU executors.
"""


def test_ace_step_instantiation() -> None:
	from gbedu_ml.models.ace_step import AceStepModel
	m = AceStepModel()
	assert not m.is_loaded
	assert not m.circuit_open
	assert isinstance(m.model_id, str)
	assert m.model_id  # non-empty


def test_ace_step_health_check_unloaded() -> None:
	from gbedu_ml.models.ace_step import AceStepModel
	m = AceStepModel()
	h = m.health_check()
	assert h["model_id"] == m.model_id
	assert h["is_loaded"] is False
	assert h["circuit_open"] is False


def test_stable_audio_instantiation() -> None:
	from gbedu_ml.models.stable_audio import StableAudioModel
	m = StableAudioModel()
	assert not m.is_loaded
	assert isinstance(m.model_id, str)
	assert m.model_id


def test_stable_audio_has_sample_rate_attr() -> None:
	from gbedu_ml.models.stable_audio import StableAudioModel
	m = StableAudioModel()
	assert hasattr(m, "_sample_rate")
	assert m._sample_rate == 44100


def test_stable_audio_health_check() -> None:
	from gbedu_ml.models.stable_audio import StableAudioModel
	m = StableAudioModel()
	h = m.health_check()
	assert h["is_loaded"] is False
	assert h["last_generation_ms"] is None


def test_yue_instantiation() -> None:
	from gbedu_ml.models.yue import YuEModel
	m = YuEModel()
	assert not m.is_loaded
	assert isinstance(m.model_id, str)
	assert m.model_id


def test_yue_has_sample_rate() -> None:
	from gbedu_ml.models.yue import YuEModel
	m = YuEModel()
	assert m._sample_rate == 24000


def test_yue_health_check() -> None:
	from gbedu_ml.models.yue import YuEModel
	m = YuEModel()
	h = m.health_check()
	assert h["is_loaded"] is False
	assert h["circuit_open"] is False
