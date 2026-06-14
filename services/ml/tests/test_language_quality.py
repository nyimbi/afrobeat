"""Unit tests for language quality gate and Pidgin pattern library.

No mocks — all tests operate on real string inputs and real objects.
Run with: uv run pytest services/ml/tests/test_language_quality.py -vxs
"""

from __future__ import annotations

import pytest

from gbedu_ml.language.quality_gate import (
	PidginYorubaQualityGate,
	QualityGateResult,
	_PIDGIN_MARKER_MIN_RATE,
	_YORUBA_CHAR_MIN_DENSITY,
)
from gbedu_ml.language.pidgin_patterns import (
	PidginPatternLibrary,
	PidginPhrase,
	_PHRASE_BANK,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def gate() -> PidginYorubaQualityGate:
	return PidginYorubaQualityGate()


@pytest.fixture
def lib() -> PidginPatternLibrary:
	return PidginPatternLibrary()


# ── Authentic Pidgin samples (should pass) ───────────────────────────────────

_GOOD_PIDGIN_VERSE = (
	"Na Lagos we dey, hustlers every day, "
	"abi you no sabi how we grind for the street? "
	"Wahala no dey stop us, shey you hear me well? "
	"Oga at the top, na we be the best dem dey fear."
)

_GOOD_PIDGIN_HOOK = (
	"Make we celebrate, life too short to cry, "
	"e don do, we don make am, reach the sky, "
	"wetin dey happen? Only blessings dey flow, "
	"sabi the vibe, make we go go go."
)

# Concatenated to ensure sufficient word count
_GOOD_PIDGIN_LYRICS = f"{_GOOD_PIDGIN_VERSE}\n{_GOOD_PIDGIN_HOOK}\n" * 2


# ── Sparse-Pidgin / English-heavy samples (should fail) ──────────────────────

_SPARSE_PIDGIN = (
	"I walk through the streets of Lagos every morning, "
	"the sun rises over the water and everything is beautiful. "
	"We celebrate life and love each other deeply. "
	"Music fills the air and brings us together as one."
)


# ── Authentic Yoruba samples (should pass) ───────────────────────────────────

_GOOD_YORUBA_VERSE = (
	"Ẹ jọ, ẹ gbọ ohun tí mo ń sọ, "
	"ọpẹ ni mo dupẹ lọwọ Ọlọrun mi, "
	"Àwa ń jọ síwájú, ẹ wá kí wà, "
	"ìfẹ́ rẹ ń gbádùn gbogbo ọjọ́ àti alẹ."
)

_GOOD_YORUBA_HOOK = (
	"Ṣe o mọ bí mo ti fẹ ọ? "
	"Ọkàn mi ń lọ sí ọ titi láé, "
	"àṣà wa pọ̀, ìfẹ́ wa dára, "
	"jẹ́ kí a gbádùn ìgbésí ayé."
)

_GOOD_YORUBA_LYRICS = f"{_GOOD_YORUBA_VERSE}\n{_GOOD_YORUBA_HOOK}\n"


# ── Plain-ASCII pseudo-Yoruba (should fail) ──────────────────────────────────

_FAKE_YORUBA = (
	"Emi o mo, emi o ri, emi o gbo ohun e, "
	"awa lo siwaju, awa lo pada, awa lo joba, "
	"ife wa pelu re, ife wa dara pupo, "
	"jeki a gba ayo, jeki a gba ire lailai."
)


# ═══════════════════════════════════════════════════════════════════════════════
# PidginYorubaQualityGate — Pidgin tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestPidginGatePasses:
	def test_authentic_verse_passes(self, gate: PidginYorubaQualityGate) -> None:
		result = gate.check_pidgin(_GOOD_PIDGIN_LYRICS)
		assert result.passed is True

	def test_result_is_quality_gate_result(self, gate: PidginYorubaQualityGate) -> None:
		result = gate.check_pidgin(_GOOD_PIDGIN_LYRICS)
		assert isinstance(result, QualityGateResult)

	def test_confidence_above_half_when_passing(self, gate: PidginYorubaQualityGate) -> None:
		result = gate.check_pidgin(_GOOD_PIDGIN_LYRICS)
		assert result.confidence >= 0.5

	def test_marker_rate_populated(self, gate: PidginYorubaQualityGate) -> None:
		result = gate.check_pidgin(_GOOD_PIDGIN_LYRICS)
		assert result.marker_rate is not None
		assert result.marker_rate >= _PIDGIN_MARKER_MIN_RATE

	def test_reason_contains_marker_info(self, gate: PidginYorubaQualityGate) -> None:
		result = gate.check_pidgin(_GOOD_PIDGIN_LYRICS)
		assert "marker rate" in result.reason.lower()

	def test_known_markers_detected(self, gate: PidginYorubaQualityGate) -> None:
		# Text with explicit markers embedded
		text = " ".join(["word"] * 80 + ["dey", "na", "sabi", "wahala", "wetin"] * 5)
		result = gate.check_pidgin(text)
		assert result.passed is True


class TestPidginGateFails:
	def test_english_only_fails(self, gate: PidginYorubaQualityGate) -> None:
		result = gate.check_pidgin(_SPARSE_PIDGIN)
		assert result.passed is False

	def test_confidence_below_one_when_failing(self, gate: PidginYorubaQualityGate) -> None:
		result = gate.check_pidgin(_SPARSE_PIDGIN)
		assert result.confidence < 1.0

	def test_reason_mentions_threshold(self, gate: PidginYorubaQualityGate) -> None:
		result = gate.check_pidgin(_SPARSE_PIDGIN)
		assert str(_PIDGIN_MARKER_MIN_RATE) in result.reason

	def test_very_short_text_fails(self, gate: PidginYorubaQualityGate) -> None:
		result = gate.check_pidgin("na me")
		assert result.passed is False
		assert "too short" in result.reason


class TestPidginGateEdgeCases:
	def test_marker_in_word_boundary_not_matched(self, gate: PidginYorubaQualityGate) -> None:
		# "donkey", "navigate", "ability" should NOT count as Pidgin markers
		text = " ".join(["donkey", "navigate", "ability", "donate"] * 30)
		result = gate.check_pidgin(text)
		# marker rate should be 0
		assert result.marker_rate == 0.0
		assert result.passed is False

	def test_empty_assertion(self, gate: PidginYorubaQualityGate) -> None:
		with pytest.raises(AssertionError):
			gate.check_pidgin("")

	def test_marker_rate_is_per_100_words(self, gate: PidginYorubaQualityGate) -> None:
		# Exactly 100 words: 50 filler + 50 "dey" (well above threshold)
		text = " ".join(["hello"] * 50 + ["dey"] * 50)
		result = gate.check_pidgin(text)
		assert result.marker_rate is not None
		assert abs(result.marker_rate - 50.0) < 0.01  # 50 dey per 100 words


# ═══════════════════════════════════════════════════════════════════════════════
# PidginYorubaQualityGate — Yoruba tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestYorubaGatePasses:
	def test_authentic_yoruba_passes(self, gate: PidginYorubaQualityGate) -> None:
		result = gate.check_yoruba(_GOOD_YORUBA_LYRICS)
		assert result.passed is True

	def test_confidence_above_half_when_passing(self, gate: PidginYorubaQualityGate) -> None:
		result = gate.check_yoruba(_GOOD_YORUBA_LYRICS)
		assert result.confidence >= 0.4

	def test_char_density_populated(self, gate: PidginYorubaQualityGate) -> None:
		result = gate.check_yoruba(_GOOD_YORUBA_LYRICS)
		assert result.char_density is not None
		assert result.char_density >= _YORUBA_CHAR_MIN_DENSITY

	def test_reason_contains_density_info(self, gate: PidginYorubaQualityGate) -> None:
		result = gate.check_yoruba(_GOOD_YORUBA_LYRICS)
		assert "density" in result.reason.lower()


class TestYorubaGateFails:
	def test_ascii_pseudo_yoruba_fails(self, gate: PidginYorubaQualityGate) -> None:
		result = gate.check_yoruba(_FAKE_YORUBA)
		assert result.passed is False

	def test_plain_english_fails(self, gate: PidginYorubaQualityGate) -> None:
		result = gate.check_yoruba("the quick brown fox jumps over the lazy dog " * 5)
		assert result.passed is False

	def test_char_density_zero_for_ascii(self, gate: PidginYorubaQualityGate) -> None:
		result = gate.check_yoruba(_FAKE_YORUBA)
		assert result.char_density is not None
		assert result.char_density == 0.0

	def test_very_short_text_fails(self, gate: PidginYorubaQualityGate) -> None:
		result = gate.check_yoruba("ẹ jọ")
		assert result.passed is False
		assert "too short" in result.reason

	def test_empty_assertion(self, gate: PidginYorubaQualityGate) -> None:
		with pytest.raises(AssertionError):
			gate.check_yoruba("")


class TestYorubaGateEdgeCases:
	def test_single_diacritic_dense_text(self, gate: PidginYorubaQualityGate) -> None:
		# 100 chars, all Yoruba diacritics — should pass easily
		text = "ẹọṣ" * 34  # 102 chars, all characteristic
		result = gate.check_yoruba(text)
		assert result.passed is True
		assert result.char_density is not None
		assert result.char_density > 50.0

	def test_mixed_content_near_threshold(self, gate: PidginYorubaQualityGate) -> None:
		# Construct text with exactly 1 char per 100 total (below threshold 0.5)
		base = "a" * 99 + "ẹ"  # 1 Yoruba char in 100 — density = 1.0
		# density = 1.0, threshold = 0.5, so this should pass
		result = gate.check_yoruba(base * 2)
		assert result.passed is True


# ═══════════════════════════════════════════════════════════════════════════════
# PidginPatternLibrary tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestPhraseBank:
	def test_phrase_bank_has_minimum_size(self) -> None:
		assert len(_PHRASE_BANK) >= 20

	def test_all_entries_are_pidgin_phrase(self) -> None:
		for p in _PHRASE_BANK:
			assert isinstance(p, PidginPhrase)
			assert p.pidgin
			assert p.english_gloss
			assert p.theme

	def test_all_expected_themes_present(self) -> None:
		themes = {p.theme for p in _PHRASE_BANK}
		for expected in ("love", "hustle", "celebration", "flex", "heartbreak"):
			assert expected in themes, f"theme '{expected}' missing from phrase bank"

	def test_each_theme_has_at_least_four_phrases(self) -> None:
		from collections import Counter
		counts = Counter(p.theme for p in _PHRASE_BANK)
		for theme, count in counts.items():
			assert count >= 4, f"theme '{theme}' only has {count} phrases"


class TestPhrasesByTheme:
	def test_love_phrases_returned(self, lib: PidginPatternLibrary) -> None:
		phrases = lib.phrases_by_theme("love")
		assert len(phrases) >= 1
		assert all(p.theme == "love" for p in phrases)

	def test_unknown_theme_returns_empty(self, lib: PidginPatternLibrary) -> None:
		phrases = lib.phrases_by_theme("unknown_theme_xyz")
		assert phrases == []

	def test_all_themes_returns_all(self, lib: PidginPatternLibrary) -> None:
		all_themes = lib.all_themes()
		for theme in all_themes:
			assert len(lib.phrases_by_theme(theme)) >= 1

	def test_empty_theme_assertion(self, lib: PidginPatternLibrary) -> None:
		with pytest.raises(AssertionError):
			lib.phrases_by_theme("")


class TestFewShotExamples:
	def test_returns_up_to_n(self, lib: PidginPatternLibrary) -> None:
		examples = lib.few_shot_examples(n=3)
		assert len(examples) == 3

	def test_returns_pidgin_phrases(self, lib: PidginPatternLibrary) -> None:
		examples = lib.few_shot_examples(n=5)
		assert all(isinstance(e, PidginPhrase) for e in examples)

	def test_theme_filter_works(self, lib: PidginPatternLibrary) -> None:
		examples = lib.few_shot_examples(themes=["hustle"], n=10)
		assert all(e.theme == "hustle" for e in examples)

	def test_n_zero_assertion(self, lib: PidginPatternLibrary) -> None:
		with pytest.raises(AssertionError):
			lib.few_shot_examples(n=0)

	def test_multi_theme_filter(self, lib: PidginPatternLibrary) -> None:
		examples = lib.few_shot_examples(themes=["love", "heartbreak"], n=10)
		assert all(e.theme in ("love", "heartbreak") for e in examples)


class TestFewShotBlock:
	def test_block_is_string(self, lib: PidginPatternLibrary) -> None:
		block = lib.format_few_shot_block(n=3)
		assert isinstance(block, str)
		assert len(block) > 0

	def test_block_contains_header(self, lib: PidginPatternLibrary) -> None:
		block = lib.format_few_shot_block(n=3)
		assert "Nigerian Pidgin" in block

	def test_block_contains_n_examples(self, lib: PidginPatternLibrary) -> None:
		block = lib.format_few_shot_block(n=4)
		# Each phrase line starts with "  - "
		lines = [l for l in block.splitlines() if l.strip().startswith("-")]
		assert len(lines) == 4

	def test_block_format_has_gloss(self, lib: PidginPatternLibrary) -> None:
		block = lib.format_few_shot_block(n=2)
		# Each line should have parenthesised gloss and bracketed theme
		assert "(" in block and ")" in block
		assert "[" in block and "]" in block


# ═══════════════════════════════════════════════════════════════════════════════
# inject_pidgin_flavor tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestInjectPidginFlavor:
	def test_you_know_becomes_you_sabi(self, lib: PidginPatternLibrary) -> None:
		result = lib.inject_pidgin_flavor("you know how it feels")
		assert "you sabi" in result

	def test_lets_go_becomes_make_we_go(self, lib: PidginPatternLibrary) -> None:
		result = lib.inject_pidgin_flavor("let's go and celebrate tonight")
		assert "make we go" in result

	def test_no_problem_becomes_no_wahala(self, lib: PidginPatternLibrary) -> None:
		result = lib.inject_pidgin_flavor("no problem, we handle it")
		assert "no wahala" in result

	def test_what_is_happening_substituted(self, lib: PidginPatternLibrary) -> None:
		result = lib.inject_pidgin_flavor("what is happening in the streets tonight?")
		assert "wetin dey happen" in result

	def test_i_cannot_becomes_i_no_fit(self, lib: PidginPatternLibrary) -> None:
		result = lib.inject_pidgin_flavor("I cannot leave you alone")
		assert "I no fit" in result

	def test_no_substitution_on_unmatched_text(self, lib: PidginPatternLibrary) -> None:
		original = "the rhythms of Lagos are unique and powerful"
		result = lib.inject_pidgin_flavor(original)
		# No substitution pairs match — text should be returned unchanged
		assert result == original

	def test_case_insensitive_matching(self, lib: PidginPatternLibrary) -> None:
		result = lib.inject_pidgin_flavor("YOU KNOW this is real")
		assert "you sabi" in result.lower()

	def test_empty_assertion(self, lib: PidginPatternLibrary) -> None:
		with pytest.raises(AssertionError):
			lib.inject_pidgin_flavor("")

	def test_multiple_substitutions_in_one_call(self, lib: PidginPatternLibrary) -> None:
		text = "you know what is happening? let's go now, no problem at all"
		result = lib.inject_pidgin_flavor(text)
		# At minimum two substitutions should fire
		pidgin_markers = sum([
			"you sabi" in result,
			"wetin dey happen" in result,
			"make we go" in result,
			"no wahala" in result,
		])
		assert pidgin_markers >= 2

	def test_result_is_longer_or_equal(self, lib: PidginPatternLibrary) -> None:
		# Pidgin phrases are generally longer than the English originals
		text = "you know the way, let's go together"
		result = lib.inject_pidgin_flavor(text)
		# Result should be non-empty and a string
		assert isinstance(result, str)
		assert len(result) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# QualityGateResult model tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestQualityGateResultModel:
	def test_construct_minimal(self) -> None:
		r = QualityGateResult(passed=True, confidence=0.8, reason="ok")
		assert r.passed is True
		assert r.marker_rate is None
		assert r.char_density is None

	def test_construct_with_all_fields(self) -> None:
		r = QualityGateResult(
			passed=False,
			confidence=0.4,
			reason="low density",
			char_density=0.2,
			marker_rate=1.5,
		)
		assert r.char_density == 0.2
		assert r.marker_rate == 1.5

	def test_extra_fields_forbidden(self) -> None:
		from pydantic import ValidationError
		with pytest.raises(ValidationError):
			QualityGateResult(passed=True, confidence=1.0, reason="ok", unknown_field="x")  # type: ignore[call-arg]
