from __future__ import annotations

"""Unit tests for gbedu_ml.language.pidgin_patterns."""


def _lib():
	from gbedu_ml.language.pidgin_patterns import PidginPatternLibrary

	return PidginPatternLibrary()


# ── PidginPatternLibrary ──────────────────────────────────────────────────


def test_all_themes_returns_list() -> None:
	lib = _lib()
	themes = lib.all_themes()
	assert isinstance(themes, list)
	assert len(themes) > 0


def test_phrases_by_theme_returns_phrases() -> None:
	lib = _lib()
	themes = lib.all_themes()
	theme = themes[0]
	phrases = lib.phrases_by_theme(theme)
	assert isinstance(phrases, list)
	assert len(phrases) > 0


def test_phrases_by_unknown_theme_returns_empty() -> None:
	lib = _lib()
	phrases = lib.phrases_by_theme("totally_nonexistent_theme_xyz")
	assert phrases == []


def test_few_shot_examples_returns_limited_list() -> None:
	lib = _lib()
	examples = lib.few_shot_examples(n=3)
	assert len(examples) <= 3


def test_few_shot_examples_by_themes() -> None:
	lib = _lib()
	themes = lib.all_themes()[:2]
	examples = lib.few_shot_examples(themes=themes, n=5)
	assert isinstance(examples, list)
	assert len(examples) <= 5


def test_inject_pidgin_flavor_returns_string() -> None:
	lib = _lib()
	result = lib.inject_pidgin_flavor("I love you very much")
	assert isinstance(result, str)
	assert len(result) > 0


def test_inject_pidgin_flavor_non_empty_input() -> None:
	lib = _lib()
	result = lib.inject_pidgin_flavor("You are the one I love")
	assert isinstance(result, str)
	assert len(result) > 0


def test_format_few_shot_block_returns_string() -> None:
	lib = _lib()
	result = lib.format_few_shot_block(n=3)
	assert isinstance(result, str)
	assert len(result) > 0


def test_format_few_shot_block_with_themes() -> None:
	lib = _lib()
	themes = lib.all_themes()[:1]
	result = lib.format_few_shot_block(themes=themes, n=2)
	assert isinstance(result, str)


# ── PidginPhrase ──────────────────────────────────────────────────────────


def test_pidgin_phrase_is_namedtuple() -> None:
	from gbedu_ml.language.pidgin_patterns import PidginPhrase

	p = PidginPhrase(pidgin="Na me", english_gloss="It is me", theme="identity")
	assert p.pidgin == "Na me"
	assert p.english_gloss == "It is me"
	assert p.theme == "identity"
