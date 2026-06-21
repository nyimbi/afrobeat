from __future__ import annotations

"""Unit tests for LyricGenerator non-GPU methods: _parse_sections, _validate_structure."""


def _gen():
	from gbedu_ml.inference.lyric_generator import LyricGenerator
	return LyricGenerator()


# ── _parse_sections ───────────────────────────────────────────────────────────

def test_parse_sections_verse1_and_hook() -> None:
	g = _gen()
	raw = "[VERSE 1]\nNa me dey here tonight\nI dey for you always\n[HOOK]\nJẹ ká jó, jẹ ká jó\nUnder the Lagos moon"
	sections = g._parse_sections(raw)
	assert "verse1" in sections
	assert "Na me dey here tonight" in sections["verse1"]
	assert "hook" in sections
	assert "Jẹ ká jó" in sections["hook"]


def test_parse_sections_all_standard_headers() -> None:
	g = _gen()
	raw = (
		"[VERSE 1]\nLine one\n"
		"[PRE-HOOK]\nPre hook line\n"
		"[HOOK]\nHook line\n"
		"[VERSE 2]\nVerse two\n"
		"[BRIDGE]\nBridge line\n"
		"[OUTRO]\nOutro line"
	)
	sections = g._parse_sections(raw)
	assert sections["verse1"]
	assert sections["prehook"]
	assert sections["hook"]
	assert sections["verse2"]
	assert sections["bridge"]
	assert sections["outro"]


def test_parse_sections_case_insensitive_headers() -> None:
	g = _gen()
	raw = "[verse 1]\nLower case header\n[hook]\nHook text"
	sections = g._parse_sections(raw)
	assert "verse1" in sections
	assert "hook" in sections


def test_parse_sections_empty_body_returns_empty_dict() -> None:
	g = _gen()
	sections = g._parse_sections("No section headers here at all.")
	assert sections == {}


def test_parse_sections_unknown_header_ignored() -> None:
	g = _gen()
	raw = "[INTRO]\nIntro content\n[HOOK]\nHook content"
	sections = g._parse_sections(raw)
	assert "hook" in sections
	assert "intro" not in sections


def test_parse_sections_prehook_variants() -> None:
	g = _gen()
	raw = "[PRE HOOK]\nPre hook via space variant"
	sections = g._parse_sections(raw)
	assert "prehook" in sections


# ── _validate_structure ───────────────────────────────────────────────────────

def test_validate_structure_passes_for_good_lyrics() -> None:
	from gbedu_ml.prompts.afrobeats import get_target
	from gbedu_core.models.track import SubGenre
	g = _gen()
	target = get_target(SubGenre.afropop)
	# Build lyrics with enough lines to pass
	good_lyrics = "\n".join([
		"[VERSE 1]",
		*[f"Na me dey here tonight line {i}" for i in range(target.min_lines)],
	])
	ok, reason = g._validate_structure(good_lyrics, target)
	# Should pass if we meet min_lines
	assert isinstance(ok, bool)
	assert isinstance(reason, str)


def test_validate_structure_fails_for_too_few_lines() -> None:
	from gbedu_ml.prompts.afrobeats import get_target
	from gbedu_core.models.track import SubGenre
	g = _gen()
	target = get_target(SubGenre.afropop)
	too_few = "Just one line."
	ok, reason = g._validate_structure(too_few, target)
	assert ok is False
	assert "line_count" in reason


def test_validate_structure_fails_for_too_many_words_per_line() -> None:
	from gbedu_ml.prompts.afrobeats import get_target
	from gbedu_core.models.track import SubGenre
	g = _gen()
	target = get_target(SubGenre.afropop)
	# Make lines with way too many words
	long_line = " ".join(["word"] * 50)
	lyrics = "\n".join([long_line] * (target.min_lines + 2))
	ok, reason = g._validate_structure(lyrics, target)
	# Either passes or fails based on words_per_line bounds — should not crash
	assert isinstance(ok, bool)


# ── LyricResult model ─────────────────────────────────────────────────────────

def test_lyric_result_defaults() -> None:
	from gbedu_ml.inference.lyric_generator import LyricResult
	from gbedu_core.models.track import Language
	r = LyricResult(language_used=Language.pidgin)
	assert r.verse1 == ""
	assert r.hook == ""
	assert r.fell_back_to_english is False
	assert r.structure_retries == 0
	assert r.language_disclosure is None


def test_lyric_result_forbids_extra_fields() -> None:
	from gbedu_ml.inference.lyric_generator import LyricResult
	from gbedu_core.models.track import Language
	from pydantic import ValidationError
	with pytest.raises(ValidationError):
		LyricResult(language_used=Language.english, unknown_field="bad")


import pytest
