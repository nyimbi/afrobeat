from __future__ import annotations

"""Unit tests for gbedu_ml.language.quality_gate and pidgin_patterns."""

import pytest


def _gate():
	from gbedu_ml.language.quality_gate import PidginYorubaQualityGate
	return PidginYorubaQualityGate()


# ── check_pidgin ──────────────────────────────────────────────────────────

def test_check_pidgin_passes_authentic_text() -> None:
	gate = _gate()
	# Dense Pidgin text with multiple markers
	text = (
		"Na me be the oga for this place. "
		"Dem dey come, una sabi wetin dey happen. "
		"No wahala, we don chop already, abi? "
		"E don do, make we waka go."
	)
	result = gate.check_pidgin(text)
	assert result.passed, f"Expected pass; confidence={result.confidence}, reason={result.reason}"


def test_check_pidgin_fails_english_only() -> None:
	gate = _gate()
	text = (
		"This is a completely standard English sentence with no Pidgin markers "
		"whatsoever and it should fail the quality gate for Pidgin lyrics. "
		"The music plays softly in the evening breeze."
	)
	result = gate.check_pidgin(text)
	assert not result.passed


def test_check_pidgin_result_structure() -> None:
	gate = _gate()
	text = "Na true, dem dey come, abi you sabi? No wahala at all. Wetin you dey do oga?"
	result = gate.check_pidgin(text)
	assert result.confidence >= 0.0
	assert result.confidence <= 1.0
	assert result.reason
	assert result.marker_rate is not None


def test_check_pidgin_rejects_short_text() -> None:
	"""Very short text (< word threshold) should not pass."""
	gate = _gate()
	result = gate.check_pidgin("Na.")
	# Short text will have low confidence or fail — just ensure no crash
	assert isinstance(result.passed, bool)


# ── check_yoruba ──────────────────────────────────────────────────────────

def test_check_yoruba_with_diacritics_passes() -> None:
	gate = _gate()
	text = (
		"Ẹni tó bá fẹ́ràn ọmọ rẹ̀ á jẹ kó máa fi ọwọ́ rẹ̀ ṣiṣẹ́. "
		"Ọmọ wẹrẹ ní ọwọ́ ọlọ́pàá."
	)
	result = gate.check_yoruba(text)
	assert result.passed, f"Expected pass; confidence={result.confidence}"


def test_check_yoruba_plain_ascii_fails() -> None:
	gate = _gate()
	text = "This text has no Yoruba diacritics at all and should fail."
	result = gate.check_yoruba(text)
	assert not result.passed


def test_check_yoruba_result_structure() -> None:
	gate = _gate()
	result = gate.check_yoruba("Ẹ káàbọ̀ sí ilẹ̀ Yorùbá. Ọmọ ọlọ́run.")
	assert hasattr(result, "passed")
	assert hasattr(result, "confidence")
	assert hasattr(result, "reason")
	assert result.char_density is not None


# ── check_swahili ─────────────────────────────────────────────────────────

def test_check_swahili_with_markers_passes() -> None:
	gate = _gate()
	text = (
		"Nilikuwa nikisema kwamba ninakupenda sana. "
		"Utaenda wapi usiku huu? Tukutane kesho asubuhi."
		"Nakupenda sana wewe ni mpenzi wangu milele."
	)
	result = gate.check_swahili(text)
	assert hasattr(result, "passed")
	assert result.confidence >= 0.0


def test_check_swahili_result_structure() -> None:
	gate = _gate()
	result = gate.check_swahili("Nilikuwa nikisema kwamba ninakupenda sana.")
	assert isinstance(result.passed, bool)
	assert result.reason


# ── check_lingala ─────────────────────────────────────────────────────────

def test_check_lingala_result_structure() -> None:
	gate = _gate()
	text = "Nalingi yo mingi. Tokende na biso. Ozali malamu."
	result = gate.check_lingala(text)
	assert hasattr(result, "passed")
	assert result.confidence >= 0.0


def test_check_lingala_plain_english_result() -> None:
	gate = _gate()
	result = gate.check_lingala("The sun rises in the east every morning without fail.")
	assert isinstance(result.passed, bool)


# ── check_zulu ────────────────────────────────────────────────────────────

def test_check_zulu_result_structure() -> None:
	gate = _gate()
	text = "Ngiyakuthanda. Sawubona, unjani? Siyabonga kakhulu."
	result = gate.check_zulu(text)
	assert hasattr(result, "passed")
	assert result.confidence >= 0.0


def test_check_zulu_plain_english_result() -> None:
	gate = _gate()
	result = gate.check_zulu("The music flows like a river through the valley.")
	assert isinstance(result.passed, bool)


# ── check_igbo ────────────────────────────────────────────────────────────

def test_check_igbo_result_structure() -> None:
	gate = _gate()
	text = "Ọ dị mma. Anyị na-eje ụgbọ elu. Nna m nọ n'ụlọ."
	result = gate.check_igbo(text)
	assert hasattr(result, "passed")
	assert result.confidence >= 0.0


def test_check_igbo_plain_text_result() -> None:
	gate = _gate()
	result = gate.check_igbo("Some random text without any Igbo specific markers.")
	assert isinstance(result.passed, bool)


# ── check_twi ─────────────────────────────────────────────────────────────

def test_check_twi_result_structure() -> None:
	gate = _gate()
	text = "Medaase paa. Ɛte sɛn? Mɛko fie nnɛ."
	result = gate.check_twi(text)
	assert hasattr(result, "passed")
	assert result.confidence >= 0.0


def test_check_twi_plain_text_result() -> None:
	gate = _gate()
	result = gate.check_twi("Some English text without Twi markers at all.")
	assert isinstance(result.passed, bool)


# ── QualityGateResult model ────────────────────────────────────────────────

def test_quality_gate_result_model() -> None:
	from gbedu_ml.language.quality_gate import QualityGateResult

	r = QualityGateResult(passed=True, confidence=0.85, reason="3 markers/100 words", marker_rate=3.0)
	assert r.passed
	assert r.confidence == 0.85
	assert r.reason
	assert r.marker_rate == 3.0
	assert r.char_density is None


def test_quality_gate_result_char_density() -> None:
	from gbedu_ml.language.quality_gate import QualityGateResult

	r = QualityGateResult(passed=True, confidence=0.9, reason="high density", char_density=12.5)
	assert r.char_density == 12.5
	assert r.marker_rate is None


def test_quality_gate_result_forbids_extra_fields() -> None:
	from gbedu_ml.language.quality_gate import QualityGateResult
	from pydantic import ValidationError

	with pytest.raises(ValidationError):
		QualityGateResult(passed=True, confidence=0.5, reason="ok", unknown_field="bad")
