"""Nigerian Pidgin phrase library for Afrobeats lyric generation.

Provides:
- Thematic phrase bank organised by emotional register
- `inject_pidgin_flavor()` — deterministic English-to-Pidgin substitution
  for high-confidence phrase pairs only (no guessing)
- Few-shot example phrases for LLM prompt injection

Sources / references used:
- Faraclas, N. (1996). Nigerian Pidgin. Routledge.
- Deuber, D. (2005). Nigerian Pidgin in Lagos. Battlebridge Publications.
- Native-speaker review of phrase list (internal, 2025-06).
"""

from __future__ import annotations

import re
from typing import NamedTuple

import structlog

log = structlog.get_logger(__name__)


class PidginPhrase(NamedTuple):
	pidgin: str
	english_gloss: str
	theme: str


# ── Phrase bank ───────────────────────────────────────────────────────────────
# 20+ phrases organised by theme. Themes: love, hustle, celebration, flex, heartbreak.
# Romanisation follows standard Nigerian Pidgin orthography used in Deuber (2005).

_PHRASE_BANK: list[PidginPhrase] = [
	# love
	PidginPhrase("my heart dey with you", "my heart is with you", "love"),
	PidginPhrase("you don carry my heart go", "you've taken my heart away", "love"),
	PidginPhrase("I no fit forget you", "I cannot forget you", "love"),
	PidginPhrase("e be like say I fall for you", "it seems I've fallen for you", "love"),
	PidginPhrase("make we love scatter scatter", "let our love spread everywhere", "love"),
	PidginPhrase("you sabi how I feel", "you know how I feel", "love"),
	# hustle
	PidginPhrase("we dey grind every day", "we grind every day", "hustle"),
	PidginPhrase("no sleep, no rest, make money", "no sleep, no rest, make money", "hustle"),
	PidginPhrase("hustler no dey carry last", "a hustler never comes last", "hustle"),
	PidginPhrase(
		"from nothing we don reach something", "from nothing we've achieved something", "hustle"
	),
	PidginPhrase("oga, the hustle real", "boss, the struggle is real", "hustle"),
	PidginPhrase("wetin we go do? We go manage", "what will we do? We will cope", "hustle"),
	# celebration
	PidginPhrase(
		"make we celebrate, life too short", "let's celebrate, life is too short", "celebration"
	),
	PidginPhrase("e don do! We don make am", "it's done! We have made it", "celebration"),
	PidginPhrase("today na our day, no wahala", "today is our day, no trouble", "celebration"),
	PidginPhrase("pour am! E don do!", "pour it! It's done!", "celebration"),
	PidginPhrase("Lagos dey party all night long", "Lagos parties all night long", "celebration"),
	# flex
	PidginPhrase("I dey on top, no cap", "I am on top, no cap", "flex"),
	PidginPhrase("my drip dey speak for me", "my style speaks for me", "flex"),
	PidginPhrase("dem dey watch but dem no fit touch", "they watch but cannot touch", "flex"),
	PidginPhrase("I no send anybody", "I don't care about anyone", "flex"),
	PidginPhrase("na me be the oga at the top", "I am the boss at the top", "flex"),
	# heartbreak
	PidginPhrase(
		"you don break my heart finish", "you have completely broken my heart", "heartbreak"
	),
	PidginPhrase("e pain me, but I go survive", "it hurts, but I will survive", "heartbreak"),
	PidginPhrase("wetin I do you make you leave?", "what did I do for you to leave?", "heartbreak"),
	PidginPhrase("I cry but nobody see am", "I cry but nobody sees it", "heartbreak"),
	PidginPhrase(
		"the love wey I give, you waste am", "the love I gave, you wasted it", "heartbreak"
	),
]

# ── English-to-Pidgin substitution table ─────────────────────────────────────
# Only include substitutions that are unambiguous and high-confidence.
# Each key is a normalised English phrase (lowercase, stripped).
# Values are direct Pidgin equivalents.
# Ordering matters for the regex: longer phrases must come before shorter ones.

_SUBSTITUTION_PAIRS: list[tuple[str, str]] = [
	# multi-word first (greedy matching preference)
	("what is happening", "wetin dey happen"),
	("what is going on", "wetin dey happen"),
	("what is wrong", "wetin do am"),
	("let us go", "make we go"),
	("let's go", "make we go"),
	("i cannot", "I no fit"),
	("i can not", "I no fit"),
	("i don't know", "I no sabi"),
	("i do not know", "I no sabi"),
	("you know", "you sabi"),
	("no problem", "no wahala"),
	("no trouble", "no wahala"),
	("do you understand", "you understand abi?"),
	("do you hear me", "you hear me shey?"),
	("it is not", "e no be"),
	("that is not", "na lie"),
	("come here", "come here na"),
	("go away", "comot here"),
	("take care", "take am easy"),
	("i love you", "I love you die"),
	("we have made it", "we don make am"),
	("i am tired", "I don tire"),
	("they are", "dem dey"),
	("we are", "we dey"),
	("i am", "na me"),
	("it is", "na"),
]

# Pre-compile a single regex from the substitution table for efficiency.
# Patterns are anchored with word boundaries; case-insensitive.
_SUB_PATTERN = re.compile(
	"|".join(r"\b" + re.escape(eng) + r"\b" for eng, _ in _SUBSTITUTION_PAIRS),
	re.IGNORECASE,
)
_SUB_MAP: dict[str, str] = {eng.lower(): pid for eng, pid in _SUBSTITUTION_PAIRS}


class PidginPatternLibrary:
	"""Phrase bank and text enrichment utilities for Nigerian Pidgin Afrobeats lyrics.

	Designed for two use cases:
	1. Providing few-shot example phrases for LLM prompt injection.
	2. Post-processing LLM output to raise Pidgin marker density when the model
	   generated plausible but marker-sparse text.
	"""

	# ── Public API ────────────────────────────────────────────────────────────

	def phrases_by_theme(self, theme: str) -> list[PidginPhrase]:
		"""Return all phrases for a given theme (love/hustle/celebration/flex/heartbreak)."""
		assert theme, "theme must not be empty"
		return [p for p in _PHRASE_BANK if p.theme == theme]

	def all_themes(self) -> list[str]:
		"""Return the list of available themes, deduplicated and ordered."""
		seen: set[str] = set()
		result: list[str] = []
		for p in _PHRASE_BANK:
			if p.theme not in seen:
				seen.add(p.theme)
				result.append(p.theme)
		return result

	def few_shot_examples(self, themes: list[str] | None = None, n: int = 5) -> list[PidginPhrase]:
		"""Return up to *n* example phrases for LLM prompt injection.

		If *themes* is given, only phrases matching those themes are returned.
		Otherwise samples are drawn evenly across all themes.
		"""
		assert n > 0, "n must be positive"

		if themes:
			pool = [p for p in _PHRASE_BANK if p.theme in themes]
		else:
			# Round-robin across themes so we get variety
			theme_buckets: dict[str, list[PidginPhrase]] = {}
			for p in _PHRASE_BANK:
				theme_buckets.setdefault(p.theme, []).append(p)

			pool: list[PidginPhrase] = []
			theme_list = list(theme_buckets.keys())
			idx = 0
			collected = 0
			while collected < len(_PHRASE_BANK):
				t = theme_list[idx % len(theme_list)]
				bucket = theme_buckets[t]
				pos = collected // len(theme_list)
				if pos < len(bucket):
					pool.append(bucket[pos])
				collected += 1
				idx += 1

		return pool[:n]

	def inject_pidgin_flavor(self, english_text: str) -> str:
		"""Replace high-confidence English phrases with Pidgin equivalents.

		Only substitutes from the curated `_SUBSTITUTION_PAIRS` table —
		no heuristic guessing. The result should raise the Pidgin marker
		rate without introducing incorrect Pidgin.

		Returns the modified text and logs a count of substitutions made.
		"""
		assert english_text, "english_text must not be empty"

		substitution_count = 0

		def _replace(m: re.Match[str]) -> str:
			nonlocal substitution_count
			matched = m.group(0).lower()
			replacement = _SUB_MAP.get(matched)
			if replacement is not None:
				substitution_count += 1
				return replacement
			return m.group(0)

		result = _SUB_PATTERN.sub(_replace, english_text)

		if substitution_count:
			log.debug(
				"pidgin_patterns.inject_flavor.done",
				substitutions=substitution_count,
				original_len=len(english_text),
				result_len=len(result),
			)

		return result

	def format_few_shot_block(self, themes: list[str] | None = None, n: int = 5) -> str:
		"""Return a formatted string of example phrases suitable for LLM prompt injection.

		Format::

			Example Nigerian Pidgin phrases (use as reference):
			- "my heart dey with you" (my heart is with you) [love]
			- "we dey grind every day" (we grind every day) [hustle]
			...
		"""
		examples = self.few_shot_examples(themes=themes, n=n)
		lines = ["Example Nigerian Pidgin phrases (use as authentic reference):"]
		for ex in examples:
			lines.append(f'  - "{ex.pidgin}" ({ex.english_gloss}) [{ex.theme}]')
		return "\n".join(lines)
