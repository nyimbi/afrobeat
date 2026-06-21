"""Quality gate for African-language lyric generation.

Underrepresentation levels in foundational multilingual models:
- Nigerian Pidgin: absent from mBERT, mT5, XLM-R, NLLB-200
- Yoruba: scores 2.69/5.0 on N-ATLaS
- Swahili: moderate coverage (NLLB-200), but Bongo Flava register is absent
- Lingala: low coverage; Congolese pop register absent
- Zulu: moderate coverage (NLLB-200); isiZulu township register absent
- Twi: minimal coverage; Akan pop register absent

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
_PIDGIN_MARKERS_SINGLE: frozenset[str] = frozenset(
	{
		"don",  # aspect marker (completive): "I don chop" = "I have eaten"
		"dey",  # locative / progressive: "e dey here", "she dey sing"
		"na",  # copula / focus marker: "na lie", "na me"
		"abi",  # tag question / confirmation: "you sabi, abi?"
		"wetin",  # what: "wetin dey happen?"
		"sabi",  # to know / to understand: "you sabi?"
		"wahala",  # trouble / problem: "no wahala"
		"shey",  # interrogative tag / confirmation: "shey you ready?"
		"oga",  # boss / sir / term of address
		"waka",  # to walk / go away: "waka waka"
		"chop",  # to eat / enjoy: "make we chop"
		"kpele",  # sorry / pity
		"dem",  # they/them: "dem dey come"
		"una",  # you (plural): "una ready?"
		"comot",  # come out / leave: "comot here"
		# Excluded (high English false-positive rate):
		# "e"    — \be\b matches English text too broadly
		# "am"   — auxiliary verb in standard English ("I am going")
		# "im"   — marginal; too short to be reliable
		# "make" — common English verb ("make it happen")
	}
)

# Multi-word markers — matched as literal phrases (spaces handled by \s+).
_PIDGIN_MARKERS_MULTI: tuple[str, ...] = (
	"no be",  # negated copula: "e no be lie"
)

# Combined marker set for external reference (e.g. tests, prompt generation).
_PIDGIN_MARKERS: frozenset[str] = _PIDGIN_MARKERS_SINGLE | frozenset(_PIDGIN_MARKERS_MULTI)

# Require word-boundary matching to avoid false positives on substrings.
# "don" should not match "donkey", "na" should not match "navigate".
# Multi-word phrases are matched separately with \s+ between tokens.
_single_alts = sorted(_PIDGIN_MARKERS_SINGLE, key=len, reverse=True)
_multi_alts = [
	r"\b" + r"\s+".join(re.escape(w) for w in p.split()) + r"\b" for p in _PIDGIN_MARKERS_MULTI
]
_PIDGIN_MARKER_RE = re.compile(
	"|".join(_multi_alts + [r"\b" + re.escape(m) + r"\b" for m in _single_alts]),
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


# ── Swahili marker lexicon ─────────────────────────────────────────────────────
# Swahili is ASCII — detected via high-precision vocabulary markers that are
# common in East African pop but absent or rare in English.

_SWAHILI_MARKERS: frozenset[str] = frozenset(
	{
		"mimi",  # I / me
		"wewe",  # you (singular)
		"sisi",  # we / us
		"lakini",  # but
		"pamoja",  # together
		"asante",  # thank you
		"karibu",  # welcome / near
		"mbona",  # why / how come
		"bado",  # still / not yet
		"pole",  # sorry / gently
		"haraka",  # quickly / hurry
		"ndiyo",  # yes
		"hapana",  # no
		"nataka",  # I want
		"kweli",  # truth / truly
		"sawa",  # okay / equal
		"jambo",  # hello / matter
		"nakupenda",  # I love you
		"uchungu",  # pain / bitterness
		"furaha",  # happiness / joy
	}
)

_SWAHILI_MARKER_RE = re.compile(
	"|".join(r"\b" + re.escape(m) + r"\b" for m in sorted(_SWAHILI_MARKERS, key=len, reverse=True)),
	re.IGNORECASE,
)

_SWAHILI_MARKER_MIN_RATE = 2.0  # markers per 100 words

# ── Lingala marker lexicon ─────────────────────────────────────────────────────
# High-precision Lingala vocabulary found in Congolese soukous lyrics.
# Using vocabulary rather than diacritics because Lingala diacritics overlap with French.

_LINGALA_MARKERS: frozenset[str] = frozenset(
	{
		"bolingo",  # love
		"mbote",  # hello / peace / greetings
		"ndeko",  # friend / sibling
		"biso",  # us / our
		"mpenza",  # really / truly
		"ntango",  # time / moment
		"nzoto",  # body
		"eloko",  # thing / something
		"mwana",  # child
		"sango",  # news / message
		"nakobina",  # I will dance
		"nakozela",  # I will wait
		"nakokoma",  # I will arrive / become
		"liwa",  # death (dramatic; common in Congolese ballads)
		"lelo",  # today
		"lobi",  # tomorrow
		"boye",  # like this / thus
		"elongi",  # face / beauty
	}
)

_LINGALA_MARKER_RE = re.compile(
	"|".join(r"\b" + re.escape(m) + r"\b" for m in sorted(_LINGALA_MARKERS, key=len, reverse=True)),
	re.IGNORECASE,
)

_LINGALA_MARKER_MIN_RATE = 1.5  # markers per 100 words (lower: less training data)

# ── Zulu marker lexicon ────────────────────────────────────────────────────────
# isiZulu vocabulary markers from township and Amapiano register.

_ZULU_MARKERS: frozenset[str] = frozenset(
	{
		"sawubona",  # hello (singular)
		"sanibonani",  # hello (plural)
		"ngiyabonga",  # thank you
		"siyabonga",  # we thank you
		"yebo",  # yes
		"hayi",  # no
		"thina",  # we / us
		"wena",  # you
		"umuntu",  # person
		"ubuntu",  # humanity / communal spirit
		"abantu",  # people
		"amandla",  # power
		"uthando",  # love
		"injabulo",  # happiness / joy
		"laduma",  # it thunders — shout of celebration
		"bayete",  # royal greeting / praise
		"ngikhona",  # I am here / I'm present
		"ngiyakuthanda",  # I love you
		"mina",  # I / me (emphatic)
		"woza",  # come / come here
	}
)

_ZULU_MARKER_RE = re.compile(
	"|".join(r"\b" + re.escape(m) + r"\b" for m in sorted(_ZULU_MARKERS, key=len, reverse=True)),
	re.IGNORECASE,
)

_ZULU_MARKER_MIN_RATE = 1.5  # markers per 100 words

# ── Twi / Akan character set ───────────────────────────────────────────────────
# Twi (Akan) orthography uses ɔ (U+0254, open-o) and ɛ (U+025B, open-e) which
# are highly distinctive — rare outside Akan-family languages.

_TWI_CHARS: frozenset[str] = frozenset("ɔɛƆƐ")

_TWI_CHAR_MIN_DENSITY = 0.3  # chars per 100 total chars (lower than Yoruba: fewer diacritics)

# ── Igbo marker lexicon ────────────────────────────────────────────────────────
# High-precision Igbo vocabulary — words absent from English, unlikely in other
# African-language outputs, common in Igbo lyric tradition.

_IGBO_MARKERS: frozenset[str] = frozenset(
	{
		"biko",  # please — highly distinctive
		"daalu",  # thank you
		"ndewo",  # hello / greeting
		"ututu",  # morning
		"oge",  # time
		"obi",  # heart / compound (home)
		"eze",  # king
		"nna",  # father
		"nne",  # mother
		"onye",  # person
		"mmiri",  # water
		"oji",  # kola nut
		"igwe",  # iron / chief
		"chukwu",  # God (supreme deity)
		"chineke",  # Creator God
		"ifunanya",  # love
		"ekele",  # greeting / respect
		"ugwu",  # respect / hill
	}
)

_IGBO_MARKER_RE = re.compile(
	"|".join(r"\b" + re.escape(m) + r"\b" for m in sorted(_IGBO_MARKERS, key=len, reverse=True)),
	re.IGNORECASE,
)

_IGBO_MARKER_MIN_RATE = 1.5  # markers per 100 words (low training data — lenient threshold)


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
			f"markers found: {sorted({m.lower() for m in matches}) or 'none'}"
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

	# ── Swahili ───────────────────────────────────────────────────────────────

	def check_swahili(self, text: str) -> QualityGateResult:
		"""Return a gate result for Swahili (Kiswahili) lyrics.

		Checks vocabulary marker density: fewer than 2 canonical Swahili
		markers per 100 words is considered suspect. Swahili is ASCII so
		diacritic detection is not applicable.
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

		matches = _SWAHILI_MARKER_RE.findall(text)
		match_count = len(matches)
		rate = (match_count / word_count) * 100

		passed = rate >= _SWAHILI_MARKER_MIN_RATE
		if passed:
			confidence = min(1.0, 0.5 + (rate / (_SWAHILI_MARKER_MIN_RATE * 2)) * 0.5)
		else:
			confidence = min(0.9, 0.3 + (rate / _SWAHILI_MARKER_MIN_RATE) * 0.6)

		reason = (
			f"Swahili marker rate {rate:.1f}/100 words "
			f"({'≥' if passed else '<'} threshold {_SWAHILI_MARKER_MIN_RATE}); "
			f"markers found: {sorted({m.lower() for m in matches}) or 'none'}"
		)

		log.debug(
			"quality_gate.swahili",
			passed=passed,
			marker_rate=round(rate, 2),
			marker_count=match_count,
			word_count=word_count,
			confidence=round(confidence, 3),
		)

		return QualityGateResult(
			passed=passed, confidence=confidence, reason=reason, marker_rate=rate
		)

	# ── Lingala ───────────────────────────────────────────────────────────────

	def check_lingala(self, text: str) -> QualityGateResult:
		"""Return a gate result for Lingala lyrics.

		Uses vocabulary marker density. Lingala diacritics overlap with French,
		so vocabulary is a more reliable signal than character sets.
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

		matches = _LINGALA_MARKER_RE.findall(text)
		match_count = len(matches)
		rate = (match_count / word_count) * 100

		passed = rate >= _LINGALA_MARKER_MIN_RATE
		if passed:
			confidence = min(1.0, 0.5 + (rate / (_LINGALA_MARKER_MIN_RATE * 2)) * 0.5)
		else:
			confidence = min(0.9, 0.3 + (rate / _LINGALA_MARKER_MIN_RATE) * 0.6)

		reason = (
			f"Lingala marker rate {rate:.1f}/100 words "
			f"({'≥' if passed else '<'} threshold {_LINGALA_MARKER_MIN_RATE}); "
			f"markers found: {sorted({m.lower() for m in matches}) or 'none'}"
		)

		log.debug(
			"quality_gate.lingala",
			passed=passed,
			marker_rate=round(rate, 2),
			marker_count=match_count,
			word_count=word_count,
			confidence=round(confidence, 3),
		)

		return QualityGateResult(
			passed=passed, confidence=confidence, reason=reason, marker_rate=rate
		)

	# ── Zulu ──────────────────────────────────────────────────────────────────

	def check_zulu(self, text: str) -> QualityGateResult:
		"""Return a gate result for Zulu (isiZulu) lyrics.

		Uses vocabulary marker density from the township and Amapiano register.
		isiZulu click consonants (c, q, x) are not reliably reproduced by LLMs
		so vocabulary presence is the primary signal.
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

		matches = _ZULU_MARKER_RE.findall(text)
		match_count = len(matches)
		rate = (match_count / word_count) * 100

		passed = rate >= _ZULU_MARKER_MIN_RATE
		if passed:
			confidence = min(1.0, 0.5 + (rate / (_ZULU_MARKER_MIN_RATE * 2)) * 0.5)
		else:
			confidence = min(0.9, 0.3 + (rate / _ZULU_MARKER_MIN_RATE) * 0.6)

		reason = (
			f"Zulu marker rate {rate:.1f}/100 words "
			f"({'≥' if passed else '<'} threshold {_ZULU_MARKER_MIN_RATE}); "
			f"markers found: {sorted({m.lower() for m in matches}) or 'none'}"
		)

		log.debug(
			"quality_gate.zulu",
			passed=passed,
			marker_rate=round(rate, 2),
			marker_count=match_count,
			word_count=word_count,
			confidence=round(confidence, 3),
		)

		return QualityGateResult(
			passed=passed, confidence=confidence, reason=reason, marker_rate=rate
		)

	# ── Igbo ──────────────────────────────────────────────────────────────────

	def check_igbo(self, text: str) -> QualityGateResult:
		"""Return a gate result for Igbo lyrics.

		Uses vocabulary marker density. Igbo dot-below diacritics (ụ, ọ, ị)
		overlap with Yoruba so vocabulary is a more reliable primary signal.
		Threshold is lenient (1.5/100 words) reflecting minimal LLM training data.
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

		matches = _IGBO_MARKER_RE.findall(text)
		match_count = len(matches)
		rate = (match_count / word_count) * 100

		passed = rate >= _IGBO_MARKER_MIN_RATE
		if passed:
			confidence = min(1.0, 0.5 + (rate / (_IGBO_MARKER_MIN_RATE * 2)) * 0.5)
		else:
			confidence = min(0.9, 0.3 + (rate / _IGBO_MARKER_MIN_RATE) * 0.6)

		reason = (
			f"Igbo marker rate {rate:.1f}/100 words "
			f"({'≥' if passed else '<'} threshold {_IGBO_MARKER_MIN_RATE}); "
			f"markers found: {sorted({m.lower() for m in matches}) or 'none'}"
		)

		log.debug(
			"quality_gate.igbo",
			passed=passed,
			marker_rate=round(rate, 2),
			marker_count=match_count,
			word_count=word_count,
			confidence=round(confidence, 3),
		)

		return QualityGateResult(
			passed=passed, confidence=confidence, reason=reason, marker_rate=rate
		)

	# ── Twi / Akan ────────────────────────────────────────────────────────────

	def check_twi(self, text: str) -> QualityGateResult:
		"""Return a gate result for Twi (Akan) lyrics.

		Checks density of ɔ (U+0254) and ɛ (U+025B) — the two open vowels
		that are orthographically mandatory in standard Twi and highly distinctive.
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

		twi_count = sum(1 for c in text if c in _TWI_CHARS)
		density = (twi_count / char_count) * 100

		passed = density >= _TWI_CHAR_MIN_DENSITY
		if passed:
			confidence = min(1.0, 0.4 + (density / (_TWI_CHAR_MIN_DENSITY * 4)) * 0.6)
		else:
			confidence = min(0.9, 0.25 + (density / _TWI_CHAR_MIN_DENSITY) * 0.65)

		reason = (
			f"Twi open-vowel density {density:.2f}/100 chars "
			f"({'≥' if passed else '<'} threshold {_TWI_CHAR_MIN_DENSITY}); "
			f"characteristic chars found: {twi_count}"
		)

		log.debug(
			"quality_gate.twi",
			passed=passed,
			char_density=round(density, 3),
			twi_count=twi_count,
			total_chars=char_count,
			confidence=round(confidence, 3),
		)

		return QualityGateResult(
			passed=passed, confidence=confidence, reason=reason, char_density=density
		)
