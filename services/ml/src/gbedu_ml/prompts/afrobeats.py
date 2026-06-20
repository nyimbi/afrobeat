from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gbedu_core.models.track import Language, SubGenre
from gbedu_core.schemas import GenerationRequest
from gbedu_ml.language.pidgin_patterns import PidginPatternLibrary

_pidgin_lib = PidginPatternLibrary()


# ── Corpus-derived structural targets ─────────────────────────────────────────
# Source: 11,604-song analysis of afrikalyrics.com mirror.
# All line-count targets assume 4-line stanzas (89.9% of stanzas in corpus).

@dataclass(frozen=True)
class CorpusTarget:
	target_lines: int       # median total lines for this genre
	min_lines: int
	max_lines: int
	target_stanzas: int     # 4-line stanzas
	words_per_line: tuple[int, int]  # (min, max)
	target_words_per_line: int
	repetition_ratio: float  # proportion of lines that are repeats (hook echoes)
	rhyme_density: float     # proportion of lines with a shared end-rhyme
	hook_repeats: int        # how many times the hook block recurs


CORPUS_TARGETS: dict[SubGenre, CorpusTarget] = {
	SubGenre.afrobeats: CorpusTarget(
		target_lines=34, min_lines=28, max_lines=42,
		target_stanzas=9, words_per_line=(5, 8), target_words_per_line=6,
		repetition_ratio=0.25, rhyme_density=0.69, hook_repeats=3,
	),
	SubGenre.afropop: CorpusTarget(
		target_lines=37, min_lines=30, max_lines=44,
		target_stanzas=9, words_per_line=(5, 8), target_words_per_line=6,
		repetition_ratio=0.25, rhyme_density=0.67, hook_repeats=3,
	),
	SubGenre.afrofusion: CorpusTarget(
		target_lines=36, min_lines=28, max_lines=44,
		target_stanzas=9, words_per_line=(5, 8), target_words_per_line=6,
		repetition_ratio=0.24, rhyme_density=0.67, hook_repeats=3,
	),
	SubGenre.alte: CorpusTarget(
		target_lines=30, min_lines=22, max_lines=40,
		target_stanzas=7, words_per_line=(4, 9), target_words_per_line=6,
		repetition_ratio=0.18, rhyme_density=0.55, hook_repeats=2,
	),
	SubGenre.highlife: CorpusTarget(
		target_lines=39, min_lines=32, max_lines=50,
		target_stanzas=10, words_per_line=(6, 9), target_words_per_line=7,
		repetition_ratio=0.26, rhyme_density=0.66, hook_repeats=3,
	),
	SubGenre.bongo_flava: CorpusTarget(
		target_lines=33, min_lines=26, max_lines=42,
		target_stanzas=9, words_per_line=(4, 7), target_words_per_line=5,
		repetition_ratio=0.23, rhyme_density=0.70, hook_repeats=3,
	),
	SubGenre.soukous: CorpusTarget(
		target_lines=36, min_lines=28, max_lines=46,
		target_stanzas=9, words_per_line=(5, 8), target_words_per_line=6,
		repetition_ratio=0.23, rhyme_density=0.64, hook_repeats=2,
	),
	SubGenre.amapiano_cross: CorpusTarget(
		target_lines=36, min_lines=28, max_lines=46,
		target_stanzas=9, words_per_line=(5, 8), target_words_per_line=6,
		repetition_ratio=0.29, rhyme_density=0.71, hook_repeats=4,
	),
	SubGenre.mbalax: CorpusTarget(
		target_lines=36, min_lines=28, max_lines=46,
		target_stanzas=9, words_per_line=(5, 8), target_words_per_line=6,
		repetition_ratio=0.20, rhyme_density=0.61, hook_repeats=2,
	),
	SubGenre.afrobeats_uk: CorpusTarget(
		target_lines=35, min_lines=28, max_lines=44,
		target_stanzas=9, words_per_line=(5, 8), target_words_per_line=6,
		repetition_ratio=0.24, rhyme_density=0.67, hook_repeats=3,
	),
	# Caribbean
	SubGenre.soca: CorpusTarget(
		target_lines=28, min_lines=22, max_lines=36,
		target_stanzas=7, words_per_line=(4, 7), target_words_per_line=5,
		repetition_ratio=0.35, rhyme_density=0.75, hook_repeats=4,
	),
	SubGenre.calypso: CorpusTarget(
		target_lines=40, min_lines=32, max_lines=50,
		target_stanzas=10, words_per_line=(6, 10), target_words_per_line=8,
		repetition_ratio=0.20, rhyme_density=0.72, hook_repeats=2,
	),
	# Kenyan
	SubGenre.gengetone: CorpusTarget(
		target_lines=28, min_lines=20, max_lines=38,
		target_stanzas=7, words_per_line=(4, 8), target_words_per_line=5,
		repetition_ratio=0.28, rhyme_density=0.65, hook_repeats=3,
	),
	SubGenre.benga: CorpusTarget(
		target_lines=36, min_lines=28, max_lines=46,
		target_stanzas=9, words_per_line=(5, 8), target_words_per_line=6,
		repetition_ratio=0.22, rhyme_density=0.65, hook_repeats=3,
	),
	# East African coastal
	SubGenre.taarab: CorpusTarget(
		target_lines=42, min_lines=34, max_lines=52,
		target_stanzas=10, words_per_line=(6, 9), target_words_per_line=7,
		repetition_ratio=0.18, rhyme_density=0.70, hook_repeats=2,
	),
	# Cross-Atlantic fusion
	SubGenre.afro_soca: CorpusTarget(
		target_lines=30, min_lines=24, max_lines=38,
		target_stanzas=7, words_per_line=(4, 7), target_words_per_line=5,
		repetition_ratio=0.32, rhyme_density=0.72, hook_repeats=4,
	),
}

_DEFAULT_TARGET = CorpusTarget(
	target_lines=35, min_lines=28, max_lines=44,
	target_stanzas=9, words_per_line=(5, 8), target_words_per_line=6,
	repetition_ratio=0.25, rhyme_density=0.68, hook_repeats=3,
)


def get_target(sub_genre: SubGenre) -> CorpusTarget:
	return CORPUS_TARGETS.get(sub_genre, _DEFAULT_TARGET)


# ── Subgenre priors ────────────────────────────────────────────────────────────

SUBGENRE_PRIORS: dict[SubGenre, dict[str, Any]] = {
	SubGenre.afrobeats: {
		"bpm_range": (96, 112),
		"key_preferences": ["A minor", "D minor", "G minor", "E minor"],
		"percussion_description": (
			"punchy kick on 1 and 2.5, sharp rimshot snare on 3, "
			"talking drum call-and-response every 2 bars, "
			"shekere 8th-note ostinato, congas doubling the downbeat"
		),
		"mood_words": ["vibrant", "infectious", "celebratory", "danceable", "confident"],
		"production_style": (
			"contemporary Lagos Afrobeats — punchy compression, warm analog bass, "
			"telephone-filtered guitar lead, lush BVs, radio-ready mix"
		),
	},
	SubGenre.highlife: {
		"bpm_range": (90, 110),
		"key_preferences": ["G major", "C major", "F major", "D major", "B♭ major"],
		"percussion_description": (
			"highlife rhythm guitar chop on the off-beat, "
			"bass guitar walking pattern on the 2-and-4, "
			"open hi-hat triplet feel, agogô bell timeline, "
			"djembe ghost notes filling the grid"
		),
		"mood_words": ["joyful", "celebratory", "nostalgic", "communal", "warm"],
		"production_style": (
			"classic Ghanaian highlife — live horn section with brass stabs, "
			"palm-wine guitar picking over warm bass, "
			"prominent melody leads, community choir backing vocals"
		),
	},
	SubGenre.bongo_flava: {
		"bpm_range": (85, 105),
		"key_preferences": ["D minor", "A minor", "G minor", "E minor"],
		"percussion_description": (
			"taarab-influenced melodic lead over programmed drums, "
			"bass guitar deep groove, "
			"udu drum texture, shaker 16th-note pattern, "
			"Tanzanian coastal rhythm feel"
		),
		"mood_words": ["romantic", "smooth", "soulful", "coastal", "laid-back"],
		"production_style": (
			"Dar es Salaam Bongo Flava — taarab strings meets hip-hop drums, "
			"warm bass, melodic Swahili vocal flow, "
			"Arabic-influenced melodic ornaments, Tanzanian urban feel"
		),
	},
	SubGenre.soukous: {
		"bpm_range": (120, 145),
		"key_preferences": ["F major", "C major", "G major", "B♭ major"],
		"percussion_description": (
			"sebene electric guitar lead break — fast, syncopated, melodic, "
			"clave rhythm on the bass guitar, "
			"open congas marking the 2 and 4, "
			"bell pattern doubling the guitar phrases"
		),
		"mood_words": ["euphoric", "danceable", "joyful", "electric", "festive"],
		"production_style": (
			"Congolese soukous / Afro-rumba — fast sebene guitar break as the centrepiece, "
			"brass stabs on the chorus, call-and-response choir, "
			"warm analogue Kinshasa production"
		),
	},
	SubGenre.mbalax: {
		"bpm_range": (130, 160),
		"key_preferences": ["D minor", "A minor", "G minor"],
		"percussion_description": (
			"sabar drum lead with intense polyrhythm, "
			"tama talking drum calling between phrases, "
			"bass guitar locking to the sabar, "
			"kora melodic ornamentation on the introduction"
		),
		"mood_words": ["intense", "spiritual", "communal", "proud", "hypnotic"],
		"production_style": (
			"Dakar mbalax — sabar drumming at the core, "
			"kora and xalam melodic phrases, Wolof griot vocal tradition, "
			"live percussion ensemble, Senegambian cultural depth"
		),
	},
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
	SubGenre.soca: {
		"bpm_range": (126, 140),
		"key_preferences": ["F major", "B♭ major", "G major", "C major"],
		"percussion_description": (
			"pan drum melodic hook on the intro, soca kick pattern on the 1-and-3, "
			"tight snare on the 2 and 4, iron rhythm section (cowbell/triangle) driving the groove, "
			"shakers and maracas on every 16th, bass guitar jump-up bounce"
		),
		"mood_words": ["euphoric", "carnival", "jump-up", "electric", "unstoppable", "festive"],
		"production_style": (
			"Trinidad Soca — steelpan melody lead, dense rhythm section, "
			"big brass stabs on the chorus, massive soca kick, "
			"full-frequency mix built for outdoor carnival, "
			"powerful vocals cutting through the mix"
		),
	},
	SubGenre.calypso: {
		"bpm_range": (96, 120),
		"key_preferences": ["F major", "C major", "G major", "D major"],
		"percussion_description": (
			"calypso guitar strum on the off-beat, bass guitar walking clave pattern, "
			"open bongos marking the 2 and 4, iron cowbell timeline, "
			"understated brushed snare, melodic steelpan ornamentation"
		),
		"mood_words": ["witty", "storytelling", "joyful", "satirical", "warm", "communal"],
		"production_style": (
			"Trinidadian Calypso — classic acoustic guitar and steelpan front, "
			"live band feel with warm reverb, "
			"horn section for emphasis on punchlines, "
			"clean natural production highlighting the lyric narrative"
		),
	},
	SubGenre.gengetone: {
		"bpm_range": (88, 108),
		"key_preferences": ["A minor", "D minor", "G minor", "F minor"],
		"percussion_description": (
			"trap 808 kick dominant, rolling hi-hat triplets, "
			"snare on the 2 and 4, Nairobi street percussion texture, "
			"bass-heavy low end, digital shaker pattern on 16ths"
		),
		"mood_words": ["street-smart", "raw", "energetic", "defiant", "urban", "youthful"],
		"production_style": (
			"Kenyan Gengetone — 808 trap production meets Afrobeats melody, "
			"Sheng (Swahili/English/Kikuyu) lyric flow, "
			"heavy bass, mobile-speaker optimised mix, "
			"Nairobi street aesthetic, rough-edged but catchy"
		),
	},
	SubGenre.benga: {
		"bpm_range": (118, 138),
		"key_preferences": ["D major", "G major", "A major", "E major"],
		"percussion_description": (
			"electric guitar fast-picked arpeggios at the core, "
			"bass guitar driving two-beat crotchet pattern, "
			"floor tom and bass drum duet, minimal hi-hat, "
			"Luo rhythmic feel with guitar as the lead percussive voice"
		),
		"mood_words": ["joyful", "driving", "communal", "nostalgic", "vibrant", "roots"],
		"production_style": (
			"Kenyan Benga — electric guitar as melodic and rhythmic centrepiece, "
			"live bass guitar and drums, minimal production, "
			"Dholuo/Luo cultural warmth, "
			"clean bright guitar tone, open natural room sound"
		),
	},
	SubGenre.taarab: {
		"bpm_range": (82, 102),
		"key_preferences": ["D minor", "A minor", "G minor", "C minor"],
		"percussion_description": (
			"oud plucked arpeggios over a gentle darbuka pattern, "
			"violin string section sustaining behind the vocal, "
			"upright bass walking slowly on the 1 and 3, "
			"riq (tambourine) marking the upbeats with delicate ornamentation, "
			"melodic Arabic maqam scales on the intro"
		),
		"mood_words": ["poetic", "romantic", "contemplative", "refined", "coastal", "classical"],
		"production_style": (
			"Zanzibar/coastal Taarab — Arabic-influenced strings and oud, "
			"ornate violin melisma, poetic Swahili lyric tradition, "
			"warm reverb suggesting a large hall, "
			"orchestral arrangement with brass and strings, refined production"
		),
	},
	SubGenre.afro_soca: {
		"bpm_range": (114, 132),
		"key_preferences": ["F major", "B♭ major", "C major", "G major"],
		"percussion_description": (
			"afrobeats talking drum fused with soca iron rhythm, "
			"808 kick meeting the soca jump-up bounce, "
			"shekere and maracas running simultaneously, "
			"bass guitar bridging Afrobeats groove and soca clave"
		),
		"mood_words": ["electric", "carnival", "cross-cultural", "unstoppable", "euphoric", "fusion"],
		"production_style": (
			"Afro-Soca cross-Atlantic fusion — Lagos production aesthetics "
			"(punchy compression, warm bass) merged with Port of Spain soca energy "
			"(iron rhythm, jump-up groove), steelpan melody alongside afrobeats guitar, "
			"massive festival mix"
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
	Language.swahili: (
		"Swahili language vocals with smooth melodic flow, "
		"Bongo Flava rhythmic cadence, coastal East African warmth, "
		"clear vowel-rich Kiswahili pronunciation, taarab melodic ornaments"
	),
	Language.lingala: (
		"Lingala language vocals with joyful Congolese delivery, "
		"call-and-response between lead and choir, "
		"soukous vocal tradition — bright, high-energy, celebratory, "
		"French-influenced melodic phrasing on bridge sections"
	),
	Language.zulu: (
		"Zulu language vocals with deep resonance, "
		"isicathamiya choral influence, township bounce phrasing, "
		"Amapiano log-drum interplay with vocal melody, "
		"Nguni click consonants as rhythmic texture"
	),
	Language.twi: (
		"Twi (Akan) language vocals with bright tonal delivery, "
		"highlife vocal tradition — melodic, call-and-response, "
		"community choir backing, Ghanaian conversational warmth"
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


# ── Regional voice identity ────────────────────────────────────────────────────
# Per-subgenre voice grounding injected at the end of the lyric prompt.

_VOICE_IDENTITY: dict[SubGenre, str] = {
	SubGenre.afrobeats: (
		"Write with the voice of a Lagos-bred artist — street credibility, "
		"Yoruba/Pidgin wordplay, mainland swagger."
	),
	SubGenre.afropop: (
		"Write with the voice of a Lagos afropop artist — polished, radio-ready, "
		"Island/mainland crossover appeal."
	),
	SubGenre.afrofusion: (
		"Write with the voice of a Lagos afrofusion artist — genre-fluid, global influences "
		"filtered through Nigerian sensibility."
	),
	SubGenre.alte: (
		"Write with the voice of an Alte Lagos artist — experimental, introspective, "
		"anti-mainstream, mixtape aesthetic."
	),
	SubGenre.highlife: (
		"Write with the voice of an Accra/Kumasi highlife artist — warm, community-rooted, "
		"Ghanaian proverb and storytelling tradition."
	),
	SubGenre.bongo_flava: (
		"Write with the voice of a Dar es Salaam/Nairobi Bongo Flava artist — "
		"streetwise Swahili flow, East African hustle narrative."
	),
	SubGenre.soukous: (
		"Write with the voice of a Kinshasa soukous artist — joyful, dance-floor ecstatic, "
		"Lingala celebratory tradition."
	),
	SubGenre.mbalax: (
		"Write with the voice of a Dakar mbalax artist — griot storytelling lineage, "
		"Wolof wisdom, Senegalese cultural pride."
	),
	SubGenre.amapiano_cross: (
		"Write with the voice of a Johannesburg township amapiano artist — log-drum groove, "
		"Zulu/Sotho/Tswana vernacular, kasi energy."
	),
	SubGenre.afrobeats_uk: (
		"Write with the voice of a UK Afrobeats artist — Nigerian diaspora perspective, "
		"London street meets Lagos roots, dual-culture identity."
	),
	SubGenre.soca: (
		"Write with the voice of a Trinidad Soca artist — carnival euphoria, "
		"jump-up culture, Port of Spain energy, wining and dancing imagery."
	),
	SubGenre.calypso: (
		"Write with the voice of a Trinidadian Calypso griot — witty social commentator, "
		"masterful storyteller, sharp observations delivered with warm humour."
	),
	SubGenre.gengetone: (
		"Write with the voice of a Nairobi Gengetone artist — Sheng street vernacular, "
		"youth hustle narrative, raw Eastlands energy, defiant and relatable."
	),
	SubGenre.benga: (
		"Write with the voice of a Western Kenya Benga artist — Dholuo warmth, "
		"guitar-rooted storytelling, Luo community pride, rural-meets-urban identity."
	),
	SubGenre.taarab: (
		"Write with the voice of a Zanzibar Taarab poet — refined Swahili verse, "
		"Arabic-influenced imagery, coastal elegance, classical lyric discipline."
	),
	SubGenre.afro_soca: (
		"Write with the voice of a cross-Atlantic fusion artist — "
		"Lagos × Port of Spain identity, two carnival cultures as one voice."
	),
}

# ── Regional code-switching patterns for Language.mix ─────────────────────────
# The natural multilingual blend varies by region and genre convention.

_MIX_LANGUAGE_PATTERN: dict[SubGenre, str] = {
	SubGenre.afrobeats: (
		"Write multilingual lyrics that code-switch naturally. "
		"Hook in Yoruba, verses in Pidgin English, bridge in English. "
		"As heard in contemporary Lagos pop."
	),
	SubGenre.afropop: (
		"Write multilingual lyrics that code-switch naturally. "
		"Hook in Yoruba, verses in Pidgin English, bridge in English. "
		"As heard in contemporary Lagos afropop."
	),
	SubGenre.afrofusion: (
		"Write multilingual lyrics that code-switch naturally. "
		"Blend Pidgin English, Yoruba, and English freely across all sections — "
		"no strict assignment, let the emotion determine the language. "
		"As heard in Lagos afrofusion."
	),
	SubGenre.alte: (
		"Write multilingual lyrics with deliberate code-switching. "
		"English dominates with Pidgin and Yoruba phrases as emotional punctuation. "
		"The bridge may be entirely Yoruba. As heard in the Lagos Alte scene."
	),
	SubGenre.highlife: (
		"Write multilingual lyrics that code-switch naturally. "
		"Hook in Twi (Akan), verses in Ghanaian Pidgin/English mix, bridge in English. "
		"As heard in contemporary Ghanaian afropop and highlife crossover."
	),
	SubGenre.bongo_flava: (
		"Write multilingual lyrics that code-switch naturally. "
		"Hook in Swahili, verses in Swahili/English mix, bridge in English. "
		"As heard in Tanzanian Bongo Flava and Kenyan pop crossover."
	),
	SubGenre.soukous: (
		"Write multilingual lyrics that code-switch naturally. "
		"Hook in Lingala, verses in Lingala, bridge in French. "
		"As heard in Congolese soukous and ndombolo."
	),
	SubGenre.mbalax: (
		"Write multilingual lyrics that code-switch naturally. "
		"Hook in Wolof, verses in Wolof/French mix, bridge in French. "
		"As heard in contemporary Dakar pop and mbalax crossover."
	),
	SubGenre.amapiano_cross: (
		"Write multilingual lyrics that code-switch naturally. "
		"Hook in Zulu, verses in Zulu/English mix, bridge in English. "
		"As heard in Johannesburg amapiano and township pop."
	),
	SubGenre.afrobeats_uk: (
		"Write multilingual lyrics that code-switch naturally. "
		"Verses in English with Pidgin phrases, hook blending Yoruba and English, bridge in English. "
		"As heard in UK Afrobeats — Nigerian diaspora meeting London grime influence."
	),
	SubGenre.soca: (
		"Write multilingual lyrics that code-switch naturally. "
		"Verses in Trinidadian Creole English, hook in standard English, "
		"bridge in patois. As heard in contemporary Port of Spain soca."
	),
	SubGenre.calypso: (
		"Write multilingual lyrics that code-switch naturally. "
		"Storytelling verses in Trinidadian Creole, chorus in clear English, "
		"punchlines landing in patois. As heard in classic Trinidadian calypso."
	),
	SubGenre.gengetone: (
		"Write multilingual lyrics that code-switch naturally. "
		"Verses in Sheng (Swahili + English + Kikuyu slang), hook in Swahili, bridge in English. "
		"As heard in Nairobi Gengetone street music."
	),
	SubGenre.benga: (
		"Write multilingual lyrics that code-switch naturally. "
		"Verses in Dholuo, hook in Dholuo/English mix, bridge in English. "
		"As heard in contemporary Kenyan Benga and Luo pop crossover."
	),
	SubGenre.taarab: (
		"Write multilingual lyrics that code-switch naturally. "
		"Verses in formal poetic Swahili, hook with Arabic phrases and imagery, bridge in Swahili. "
		"As heard in classic Zanzibari and coastal Tanzanian Taarab."
	),
	SubGenre.afro_soca: (
		"Write multilingual lyrics that code-switch naturally. "
		"Hook in Yoruba, verses blending Pidgin English and Trinidadian Creole, bridge in English. "
		"As heard in Lagos × Port of Spain cross-Atlantic festival music."
	),
}


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
		target = get_target(request.sub_genre)
		mood = ", ".join(prior["mood_words"][:3])
		bpm_low, bpm_high = prior["bpm_range"]
		wpl_min, wpl_max = target.words_per_line

		sections = song_structure.get("sections", ["verse1", "prehook", "hook", "verse2", "bridge", "outro"])
		sections_str = " → ".join(sections)

		mix_instruction = _MIX_LANGUAGE_PATTERN.get(
			request.sub_genre,
			_MIX_LANGUAGE_PATTERN[SubGenre.afrobeats],
		)

		_language_instructions: dict[Language, str] = {
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
			Language.mix: mix_instruction,
			Language.swahili: (
				"Write lyrics primarily in Swahili (Kiswahili). "
				"Use natural East African Swahili vocabulary and flow — not overly formal. "
				"Common Bongo Flava connectives: na, ya, wa, ni, kwa, lakini, pamoja. "
				"Mix in occasional English phrases on the hook as heard in Tanzanian/Kenyan pop."
			),
			Language.lingala: (
				"Write lyrics primarily in Lingala, as heard in Congolese soukous. "
				"Use joyful, celebratory phrasing. "
				"Common Lingala expressions: nakobina (I dance), bolingo (love), mbote (hello/peace), "
				"sango nini (what's the news), zoba (fool), ndeko (friend/sibling). "
				"Bridge section may use French phrases naturally, as is Congolese convention."
			),
			Language.zulu: (
				"Write lyrics primarily in Zulu (isiZulu). "
				"Use township idiom as heard in contemporary Amapiano and kwaito. "
				"Common expressions: sawubona (hello), ngiyabonga (thank you), "
				"thina (we/us), wena (you), yebo (yes), hayi (no), umuntu (person). "
				"English chorus phrases acceptable as heard in South African pop crossover."
			),
			Language.twi: (
				"Write lyrics primarily in Twi (Akan), as heard in Ghanaian highlife and afropop. "
				"Use warm, communal phrasing. "
				"Common expressions: akwaaba (welcome), medaase (thank you), "
				"mi dɔ wo (I love you), ɔkwan (way/path), sɛ (like/as), yɛn (our/we). "
				"Mix English phrases on the hook as heard in contemporary Ghanaian music."
			),
		}
		language_instruction = _language_instructions[request.language]

		# Inject Pidgin few-shot examples into the prompt for Pidgin and mix requests
		few_shot_block = ""
		if request.language in (Language.pidgin, Language.mix):
			few_shot_block = (
				"\n" + _pidgin_lib.format_few_shot_block(n=5) + "\n"
				"Use these as a style reference. Integrate similar expressions naturally.\n"
			)

		rhyme_pct = int(target.rhyme_density * 100)
		hook_repeat_note = (
			f"Repeat the [HOOK] block {target.hook_repeats} times across the full song "
			f"(after verse 1, after verse 2, and at outro)."
			if target.hook_repeats >= 3
			else f"Repeat the [HOOK] block {target.hook_repeats} times across the full song."
		)

		return (
			f"Write original Afrobeats lyrics for a {request.sub_genre.value.replace('_', ' ')} song.\n\n"
			f"Theme and concept: {request.prompt}\n"
			f"Mood: {mood}\n"
			f"Tempo feel: {bpm_low}–{bpm_high} BPM\n"
			f"Song structure: {sections_str}\n\n"
			f"Language instruction: {language_instruction}\n"
			f"{few_shot_block}\n"
			f"Structural constraints (derived from {request.sub_genre.value} corpus analysis):\n"
			f"- Total lines: {target.target_lines} (acceptable range {target.min_lines}–{target.max_lines})\n"
			f"- Each stanza (verse/hook/bridge): exactly 4 lines — this is the dominant African pop unit\n"
			f"- Words per line: {wpl_min}–{wpl_max} words (target {target.target_words_per_line})\n"
			f"- Rhyme density: aim for ~{rhyme_pct}% of lines to share end-rhymes within their stanza\n"
			f"- {hook_repeat_note}\n\n"
			f"Lyric requirements:\n"
			f"- Hook (chorus): 4 lines, highly memorable, singable, {wpl_min}–{wpl_max} words/line\n"
			f"- Verse 1: 8 lines (2 stanzas of 4), scene-setting, introduce protagonist/story\n"
			f"- Pre-hook: 4 lines, build tension into chorus\n"
			f"- Verse 2: 8 lines (2 stanzas of 4), deepen narrative or perspective shift\n"
			f"- Bridge: 4 lines, emotional peak or contrast\n"
			f"- Outro: 4 lines, resolution\n\n"
			f"Style: authentic {request.sub_genre.value.replace('_', ' ')} lyricism — direct emotional expression, "
			f"vivid imagery, rhythmic wordplay, cultural specificity. "
			f"Avoid clichés. {_VOICE_IDENTITY.get(request.sub_genre, _VOICE_IDENTITY[SubGenre.afrobeats])}\n\n"
			f"Output format — label each section exactly as:\n"
			f"[VERSE 1]\n[PRE-HOOK]\n[HOOK]\n[VERSE 2]\n[BRIDGE]\n[OUTRO]"
		)
