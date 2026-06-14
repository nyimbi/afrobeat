from __future__ import annotations

from typing import Any

from gbedu_core.models.track import Language, SubGenre
from gbedu_core.schemas import GenerationRequest
from gbedu_ml.language.pidgin_patterns import PidginPatternLibrary

_pidgin_lib = PidginPatternLibrary()


# ── Subgenre priors ────────────────────────────────────────────────────────────

SUBGENRE_PRIORS: dict[SubGenre, dict[str, Any]] = {
	SubGenre.afropop: {
		"bpm_range": (90, 110),
		"key_preferences": ["A minor", "D minor", "G minor", "E minor", "F major"],
		"percussion_description": (
			"punchy kick on beats 1 and 2.5, sharp rimshot snare on 3, "
			"shuffled 16th-note hi-hat pattern, shekere ostinato on the upbeats, "
			"djembe ghost notes, call-and-response guitar riff on off-beats"
		),
		"mood_words": ["joyful", "celebratory", "infectious", "danceable", "vibrant", "uplifting"],
		"production_style": (
			"bright afropop production, punchy compression, warm analog bass, "
			"telephone-filtered guitar leads, lush backing vocals, radio-ready mix"
		),
	},
	SubGenre.afrofusion: {
		"bpm_range": (95, 115),
		"key_preferences": ["D Dorian", "A Dorian", "E Dorian", "G Dorian"],
		"percussion_description": (
			"talking drum call-and-response against a programmed trap kick, "
			"syncopated bass pattern on the 2e-and, lush synth pads sustaining through bars, "
			"congas doubling the downbeat, shaker on the 16th-note grid"
		),
		"mood_words": ["soulful", "sophisticated", "hypnotic", "lush", "cosmopolitan"],
		"production_style": (
			"fusion of live instrumentation and electronic production, "
			"sidechain compression on pads against kick, "
			"jazz-influenced chord voicings, neo-soul feel, "
			"reverb-drenched horns, warm but punchy low end"
		),
	},
	SubGenre.alte: {
		"bpm_range": (80, 100),
		"key_preferences": ["D Dorian", "B Phrygian", "A minor", "C Phrygian"],
		"percussion_description": (
			"lo-fi drum texture with vinyl crackle, sparse kick-snare framework, "
			"brushed hi-hats, minimal percussion allowing space, "
			"occasional hand-clap on the 4, ambient room sound"
		),
		"mood_words": ["dreamy", "introspective", "hazy", "artistic", "experimental", "melancholic"],
		"production_style": (
			"indie Afrobeats aesthetic, lo-fi processing, "
			"heavy tape saturation, detuned synths, "
			"dreamy reverb tails, sparse arrangement with intentional space, "
			"bedroom-producer intimacy, unconventional song structure"
		),
	},
	SubGenre.amapiano_cross: {
		"bpm_range": (108, 116),
		"key_preferences": ["F major", "C major", "G major", "D major", "B♭ major"],
		"percussion_description": (
			"iconic log drum bass stab on the 1-and, piano-led melodic phrase, "
			"deep soulful keys comping behind the vocal, township bounce groove, "
			"percussive shaker triplets, bass-heavy kick, "
			"call-and-response between piano and bass"
		),
		"mood_words": ["euphoric", "township energy", "soulful", "deep", "groove-driven"],
		"production_style": (
			"amapiano crossover — log drum sub bass, "
			"jazzy piano improvisation layered over programmed drums, "
			"Afrobeats vocal melody hooks, Johannesburg club sound meets Lagos pop, "
			"heavy sub frequencies, crisp high-hat work"
		),
	},
	SubGenre.afrobeats_uk: {
		"bpm_range": (88, 105),
		"key_preferences": ["G minor", "C minor", "F minor", "A♭ major"],
		"percussion_description": (
			"crisp 808 kick on the 1, afroswing triplet hi-hat flow, "
			"snappy snare with heavy reverb tail, trap-influenced hi-hat rolls, "
			"melodic hook on the chorus, urban UK street sound"
		),
		"mood_words": ["cool", "smooth", "urban", "melodic", "confident", "versatile"],
		"production_style": (
			"UK Afrobeats production — trap drums meets Afrobeats melody, "
			"808 bass dominant, drill-influenced hi-hat programming, "
			"crisp mix with heavy low end, autotune melodic vocal style, "
			"London urban sensibility fused with West African roots"
		),
	},
}

# ── Language vocal descriptors ─────────────────────────────────────────────────

LANGUAGE_VOCALS: dict[Language, str] = {
	Language.english: (
		"English vocals with West African melodic phrasing, "
		"clear enunciation, gospel-influenced melisma on hook"
	),
	Language.pidgin: (
		"Nigerian Pidgin English vocals, expressive patois delivery, "
		"street-authentic flow, mix of English and Pidgin phrases, "
		"warm conversational tone, rhythmic Pidgin cadence"
	),
	Language.yoruba: (
		"Yoruba language vocals with tonal precision, "
		"traditional praise-singing (oriki) influence, "
		"call-and-response structure, tonal vowel melodies that follow speech tones, "
		"rich cultural authenticity"
	),
	Language.igbo: (
		"Igbo language vocals with high-energy delivery, "
		"highlife-influenced phrasing, tonal language melody, "
		"celebratory vocal tradition, rhythmic Igbo speech patterns"
	),
	Language.mix: (
		"multilingual code-switching vocals — Yoruba hook, Pidgin verses, English bridge, "
		"natural language alternation as heard in contemporary Lagos pop, "
		"authentic multilingual delivery"
	),
}

# ── Energy level descriptors ───────────────────────────────────────────────────

_ENERGY_DESCRIPTORS: dict[int, str] = {
	1: "very mellow, slow-burn, intimate",
	2: "laid-back, understated, smooth",
	3: "relaxed groove, gentle momentum",
	4: "mid-tempo, warm energy",
	5: "balanced energy, versatile dancefloor",
	6: "building energy, uptempo",
	7: "high energy, party-ready",
	8: "peak dancefloor energy, driving",
	9: "intense, euphoric, peak-time",
	10: "maximum energy, rave-level intensity",
}


def _energy_descriptor(level: int) -> str:
	clamped = max(1, min(10, level))
	return _ENERGY_DESCRIPTORS.get(clamped, "balanced energy")


class AfrobeatsPromptEngine:

	def build_music_prompt(self, request: GenerationRequest) -> str:
		assert request.prompt, "request.prompt must not be empty"

		prior = SUBGENRE_PRIORS[request.sub_genre]
		vocal_style = LANGUAGE_VOCALS[request.language]
		energy = _energy_descriptor(request.energy_level)

		bpm_low, bpm_high = prior["bpm_range"]
		bpm_str = (
			f"{request.bpm} BPM"
			if request.bpm
			else f"{bpm_low}–{bpm_high} BPM"
		)

		keys = ", ".join(prior["key_preferences"][:3])
		mood = ", ".join(prior["mood_words"][:4])

		duration_str = f"{request.duration_seconds} seconds"

		return (
			f"{request.sub_genre.value.replace('_', ' ').title()} track. "
			f"{request.prompt}. "
			f"Tempo: {bpm_str}. "
			f"Key: {keys}. "
			f"Percussion: {prior['percussion_description']}. "
			f"Mood: {mood}, {energy}. "
			f"Vocals: {vocal_style}. "
			f"Production: {prior['production_style']}. "
			f"Duration: {duration_str}. "
			f"High-quality professional studio recording."
		)

	def build_lyric_prompt(self, request: GenerationRequest, song_structure: dict[str, Any]) -> str:
		assert request.prompt, "request.prompt must not be empty"

		prior = SUBGENRE_PRIORS[request.sub_genre]
		mood = ", ".join(prior["mood_words"][:3])
		bpm_low, bpm_high = prior["bpm_range"]

		sections = song_structure.get("sections", ["verse1", "prehook", "hook", "verse2", "bridge", "outro"])
		sections_str = " → ".join(sections)

		language_instruction = {
			Language.english: "Write all lyrics in English with West African cultural references.",
			Language.pidgin: (
				"Write lyrics primarily in Nigerian Pidgin English. "
				"Use authentic Pidgin expressions. Mix in English phrases naturally. "
				"NOTE: Pidgin lyric generation is experimental — quality may vary. "
				"Every verse must include canonical Pidgin markers (dey, na, sabi, wahala, wetin, don, abi, shey, oga). "
				"If you are uncertain about a Pidgin word or phrase, mark it with [?] for human review."
			),
			Language.yoruba: (
				"Write lyrics in Yoruba language. "
				"Ensure tonal accuracy in word choice. "
				"Include traditional Yoruba imagery, proverbs, and praise-song (oriki) elements. "
				"NOTE: Yoruba lyric generation is experimental — quality may vary. "
				"Always use correct Yoruba orthography: sub-dot vowels (ẹ, ọ), retroflex s (ṣ), "
				"and tone marks (à, á, è, é, ì, í, ò, ó) are mandatory. "
				"If you are uncertain about a Yoruba word's tone or spelling, mark it with [?] for human review."
			),
			Language.igbo: (
				"Write lyrics in Igbo language with some English. "
				"Include celebratory Igbo expressions and highlife lyrical tradition."
			),
			Language.mix: (
				"Write multilingual lyrics that code-switch naturally. "
				"Hook in Yoruba, verses in Pidgin English, bridge in English. "
				"As heard in contemporary Lagos pop."
			),
		}[request.language]

		# Inject Pidgin few-shot examples into the prompt for Pidgin and mix requests
		few_shot_block = ""
		if request.language in (Language.pidgin, Language.mix):
			few_shot_block = (
				"\n" + _pidgin_lib.format_few_shot_block(n=5) + "\n"
				"Use these as a style reference. Integrate similar expressions naturally.\n"
			)

		return (
			f"Write original Afrobeats lyrics for a {request.sub_genre.value.replace('_', ' ')} song.\n\n"
			f"Theme and concept: {request.prompt}\n"
			f"Mood: {mood}\n"
			f"Tempo feel: {bpm_low}–{bpm_high} BPM\n"
			f"Song structure: {sections_str}\n\n"
			f"Language instruction: {language_instruction}\n"
			f"{few_shot_block}\n"
			f"Lyric requirements:\n"
			f"- Hook (chorus): 4 lines, highly memorable, singable, repeated throughout\n"
			f"- Verse 1: 8 lines, scene-setting, introduce protagonist/story\n"
			f"- Pre-hook: 2–4 lines, build tension into chorus\n"
			f"- Verse 2: 8 lines, deepen the narrative or perspective shift\n"
			f"- Bridge: 4 lines, emotional peak or contrast\n"
			f"- Outro: 2–4 lines, resolution\n\n"
			f"Style: authentic Afrobeats lyricism — direct emotional expression, "
			f"vivid imagery, rhythmic wordplay, cultural specificity. "
			f"Avoid clichés. Write with the voice of a Lagos-bred artist.\n\n"
			f"Output format — label each section exactly as:\n"
			f"[VERSE 1]\n[PRE-HOOK]\n[HOOK]\n[VERSE 2]\n[BRIDGE]\n[OUTRO]"
		)
