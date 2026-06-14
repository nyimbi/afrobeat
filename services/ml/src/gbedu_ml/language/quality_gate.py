"""Quality gate for Nigerian Pidgin and Yoruba lyric generation.

Both languages are severely underrepresented in foundational multilingual models:
- Nigerian Pidgin: absent from mBERT, mT5, XLM-R, NLLB-200
- Yoruba: scores 2.69/5.0 on N-ATLaS

The gate uses token-level heuristics rather than model-based evaluation because
we cannot trust the same underlying LLM to evaluate its own output quality for
languages it was not trained on.
"""

from __future__ import annotations

import re

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger(__name__)

# ── Pidgin marker lexicon ──────────────────────────────────────────────────────
# These are high-precision Pidgin markers — common English words that carry
# distinct Pidgin grammatical or idiomatic function. Their presence in lyric
# output strongly indicates authentic Pidgin rather than English with Pidgin
# code-switching.

# Single-word markers — matched with \b word boundaries.
_PIDGIN_MARKERS_SINGLE: frozenset[str] = frozenset({
	"don",    # aspect marker (completive): "I don chop" = "I have eaten"
	"dey",    # locative / progressive: "e dey here", "she dey sing"
	"na",     # copula / focus marker: "na lie", "na me"
	"abi",    # tag question / confirmation: "you sabi, abi?"
	"wetin",  # what: "wetin dey happen?"
	"sabi",   # to know / to understand: "you sabi?"
	"wahala", # trouble / problem: "no wahala"
	"shey",   # interrogative tag / confirmation: "shey you ready?"
	"oga",    # boss / sir / term of address
	"waka",   # to walk / go away: "waka waka"
	"chop",   # to eat / enjoy: "make we chop"
	"kpele",  # sorry / pity
	"dem",    # they/them: "dem dey come"
	"una",    # you (plural): "una ready?"
	"comot",  # come out / leave: "comot here"
	# Excluded (high English false-positive rate):
	# "e"    — \be\b matches English text too broadly
	# "am"   — auxiliary verb in standard English ("I am going")
	# "im"   — marginal; too short to be reliable
	# "make" — common English verb ("make it happen")
})

# Multi-word markers — matched as literal phrases (spaces handled by \s+).
_PIDGIN_MARKERS_MULTI: tuple[str, ...] = (
	"no be",   # negated copula: "e no be lie"
)

# Combined marker set for external reference (e.g. tests, prompt generation).
_PIDGIN_MARKERS: frozenset[str] = _PIDGIN_MARKERS_SINGLE | frozenset(_PIDGIN_MARKERS_MULTI)

# Require word-boundary matching to avoid false positives on substrings.
# "don" should not match "donkey", "na" should not match "navigate".
# Multi-word phrases are matched separately with \s+ between tokens.
_single_alts = sorted(_PIDGIN_MARKERS_SINGLE, key=len, reverse=True)
_multi_alts = [r"\b" + r"\s+".join(re.escape(w) for w in p.split()) + r"\b" for p in _PIDGIN_MARKERS_MULTI]
_PIDGIN_MARKER_RE = re.compile(
	"|".join(
		_multi_alts + [r"\b" + re.escape(m) + r"\b" for m in _single_alts]
	),
	re.IGNORECASE,
)

# Minimum Pidgin markers per 100 words to pass the gate.
_PIDGIN_MARKER_MIN_RATE = 3.0

# ── Yoruba diacritic character set ────────────────────────────────────────────
# Yoruba orthography requires sub-dot vowels (ẹ, ọ), the retroflex s (ṣ),
# and tone marks (acute, grave, macron) on vowels. Their presence/density is
# the fastest proxy for authentic Yoruba orthographic output.

_YORUBA_CHARS: frozenset[str] = frozenset("ẹọṣńàáèéìíòóùúẸỌṢŃÀÁÈÉÌÍÒÓÙÚ")

# Minimum Yoruba-characteristic characters per 100 total characters to pass.
_YORUBA_CHAR_MIN_DENSITY = 0.5


class QualityGateResult(BaseModel):
	model_config = ConfigDict(extra="forbid")

	passed: bool
	confidence: float  # 0.0–1.0; higher = more confident in the assessment
	reason: str
	marker_rate: float | None = None  # Pidgin: markers per 100 words
	char_density: float | None = None  # Yoruba: characteristic chars per 100 chars


class PidginYorubaQualityGate:
	"""Token-level heuristic quality gate for Nigerian Pidgin and Yoruba lyrics.

	Usage::

		gate = PidginYorubaQualityGate()
		result = gate.check_pidgin(lyrics)
		if not result.passed:
			# fall back to English
			...
	"""

	# ── Pidgin ────────────────────────────────────────────────────────────────

	def check_pidgin(self, text: str) -> QualityGateResult:
		"""Return a gate result for Nigerian Pidgin lyrics.

		Checks marker density: fewer than 3 canonical Pidgin markers per 100
		words is considered suspect. The gate is intentionally lenient at the
		low end (confidence rises linearly) to avoid penalising light code-
		switching that is genuine Pidgin style.
		"""
		assert text, "text must not be empty"

		words = re.findall(r"\b\w+\b", text)
		word_count = len(words)

		if word_count < 10:
			return QualityGateResult(
				passed=False,
				confidence=0.3,
				reason=f"text too short to evaluate ({word_count} words)",
				marker_rate=None,
			)

		matches = _PIDGIN_MARKER_RE.findall(text)
		match_count = len(matches)
		rate = (match_count / word_count) * 100  # markers per 100 words

		passed = rate >= _PIDGIN_MARKER_MIN_RATE
		# Confidence: saturates at 1.0 once we're at 2× the threshold.
		# Below threshold, confidence is proportional (max 0.9 on the failing side).
		if passed:
			confidence = min(1.0, 0.5 + (rate / (_PIDGIN_MARKER_MIN_RATE * 2)) * 0.5)
		else:
			confidence = min(0.9, 0.3 + (rate / _PIDGIN_MARKER_MIN_RATE) * 0.6)

		reason = (
			f"Pidgin marker rate {rate:.1f}/100 words "
			f"({'≥' if passed else '<'} threshold {_PIDGIN_MARKER_MIN_RATE}); "
			f"markers found: {sorted(set(m.lower() for m in matches)) or 'none'}"
		)

		log.debug(
			"quality_gate.pidgin",
			passed=passed,
			marker_rate=round(rate, 2),
			marker_count=match_count,
			word_count=word_count,
			confidence=round(confidence, 3),
		)

		return QualityGateResult(
			passed=passed,
			confidence=confidence,
			reason=reason,
			marker_rate=rate,
		)

	# ── Yoruba ────────────────────────────────────────────────────────────────

	def check_yoruba(self, text: str) -> QualityGateResult:
		"""Return a gate result for Yoruba lyrics.

		Checks diacritic density: fewer than 0.5 Yoruba-characteristic
		characters per 100 total characters is considered suspect. Yoruba
		orthography mandates sub-dot vowels and tone marks; their absence
		strongly indicates the model generated pseudo-Yoruba romanisation.
		"""
		assert text, "text must not be empty"

		char_count = len(text)
		if char_count < 20:
			return QualityGateResult(
				passed=False,
				confidence=0.3,
				reason=f"text too short to evaluate ({char_count} chars)",
				char_density=None,
			)

		yoruba_count = sum(1 for c in text if c in _YORUBA_CHARS)
		density = (yoruba_count / char_count) * 100  # chars per 100 total chars

		passed = density >= _YORUBA_CHAR_MIN_DENSITY
		if passed:
			confidence = min(1.0, 0.4 + (density / (_YORUBA_CHAR_MIN_DENSITY * 4)) * 0.6)
		else:
			confidence = min(0.9, 0.25 + (density / _YORUBA_CHAR_MIN_DENSITY) * 0.65)

		reason = (
			f"Yoruba diacritic density {density:.2f}/100 chars "
			f"({'≥' if passed else '<'} threshold {_YORUBA_CHAR_MIN_DENSITY}); "
			f"characteristic chars found: {yoruba_count}"
		)

		log.debug(
			"quality_gate.yoruba",
			passed=passed,
			char_density=round(density, 3),
			yoruba_count=yoruba_count,
			total_chars=char_count,
			confidence=round(confidence, 3),
		)

		return QualityGateResult(
			passed=passed,
			confidence=confidence,
			reason=reason,
			char_density=density,
		)
