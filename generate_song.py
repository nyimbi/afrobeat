#!/usr/bin/env python3
"""Standalone Afrobeats / Congolese song generator.

Two modes:
  Instrumental  — facebook/musicgen-* via HuggingFace transformers (fast, no vocals)
  Vocals        — ACE-Step 1.5 (full song with real singing, slower)

Styles:
  choir             Afrobeats SATB gospel choir (Nigerian, Pidgin/Yoruba/English)
  solo              Afrobeats solo vocalist
  duet              Afrobeats male/female duet
  congolese-choir   Congolese Afro-rumba choir (Fally Ipupa style, English)
  soukous           Fast Congolese soukous/ndombolo (145 BPM, English)

Usage:
    python generate_song.py [--model small|medium|large] [--duration 30]
    python generate_song.py --vocals [--style choir|solo|duet|congolese-choir|soukous]
    python generate_song.py --vocals --style congolese-choir --duration 60
    python generate_song.py --vocals --style soukous --fast
    python generate_song.py --vocals --lyrics "custom lyrics" --prompt "custom prompt"
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

OUTPUT_DIR = Path("/tmp/gbedu_output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MODEL_CACHE = Path("/tmp/gbedu_model_cache")
MODEL_CACHE.mkdir(parents=True, exist_ok=True)


# ── Lyric templates ────────────────────────────────────────────────────────────

_LYRICS: dict[str, dict[str, str]] = {
    "choir": {
        "english": """\
[verse]
The day has come and we lift our voices high
From every corner of this city to the sky
Together we stand with one song in our hearts
This melody unites us, this is where joy starts

[chorus]
Mayday mayday, the celebration begins
Choir: Mayday, we are here
Mayday mayday, let the music ring
Choir: Mayday, everybody sing

[verse]
From Lagos to London our sound fills the air
The talking drum is calling and the world stops to stare
We carry the rhythm that our grandmothers knew
This Afrobeats anthem is breaking through

[chorus]
Mayday mayday, the celebration begins
Choir: Mayday, we are here
Mayday mayday, let the music ring
Choir: Mayday, everybody sing

[bridge]
We will not stop, we will not tire
The fire inside our hearts burns higher
Together strong and unified
Gbẹdu music, Afro pride

[outro]
Mayday mayday...
Choir: Mayday o, mayday o
""",
        "pidgin": """\
[verse]
E don happen o, the day wey we dey wait
Raise your voice up make the whole world hear
We dey here together, from Lagos to the world
Our anthem don sound, make everybody know

[chorus]
Mayday mayday, e don happen o
Choir: Mayday, we dey here o
Mayday mayday, come celebrate
Choir: Mayday, glory don reach

[verse]
From east to west our voices don unite
From north to south we dey sing with delight
This melody go carry us go high
Our song go reach the sky

[chorus]
Mayday mayday, e don happen o
Choir: Mayday, we dey here o
Mayday mayday, come celebrate
Choir: Mayday, glory don reach

[bridge]
We no go stop, we no go tire
The fire dey burn inside our chest
Together strong, together we rise
Gbẹdu sound go light the way

[outro]
Mayday mayday...
Choir: Mayday o, mayday o
""",
        "yoruba": """\
[verse]
Ọjọ ti de, a gbe ohun wa soke
Lati ilu wa titi de ọrun loke
Papọ a duro, orin kan n ọkàn wa
Orin yii n so wa pọ, ayọ ti wa

[chorus]
Mayday mayday, ayẹyẹ ti bẹrẹ
Àwọn akọrin: Mayday, a wà nibi
Mayday mayday, jẹ ki orin gbọ
Àwọn akọrin: Mayday, gbogbo ẹnikan kọrin

[verse]
Lati Lagos si London ohun wa n kun afẹfẹ
Ìlù agbẹ n pe wa, ayé duro tẹtisi
A gbe ilu ti awọn ìyá wa mọ
Afrobeats orin yii n ja ọna rẹ

[chorus]
Mayday mayday, ayẹyẹ ti bẹrẹ
Àwọn akọrin: Mayday, a wà nibi
Mayday mayday, jẹ ki orin gbọ
Àwọn akọrin: Mayday, gbogbo ẹnikan kọrin

[bridge]
A kò ní dáwọ, a kò ní rẹ
Ina ninu ọkàn wa n jo gaan
Papọ lagbara, papọ ni ṣiṣe
Gbẹdu orin, igberaga Yoruba

[outro]
Mayday mayday...
Àwọn akọrin: Mayday o, mayday o
""",
    },
    "solo": {
        "english": """\
[verse]
I've been searching for the sound inside my soul
This Afrobeats melody is making me whole
The bass is rolling and the talking drum calls
I lose myself whenever that rhythm falls

[chorus]
Give me that feeling, that Lagos sensation
Give me that music, my daily salvation
Afrobeats got me moving through the night
Everything is better when the rhythm is right

[verse]
From the market to the beach the sound never stops
The DJ's dropping hits and the crowd never drops
We dance till morning comes with sweat on our face
This music is a gift, this music is grace

[chorus]
Give me that feeling, that Lagos sensation
Give me that music, my daily salvation
Afrobeats got me moving through the night
Everything is better when the rhythm is right

[bridge]
I don't need anything else tonight
Just this music and the city lights
Hold me close and let the bass line guide
This is where I want to be inside

[outro]
Take me there, take me there
Where the music fills the air
""",
        "pidgin": """\
[verse]
I don find the sound wey dey inside my soul
This Afrobeats melody don make me whole
The bass dey roll and the talking drum dey call
I dey lose myself when that rhythm fall

[chorus]
Give me that feeling, that Lagos vibes
Give me that music, my daily rise
Afrobeats dey move me through the night
Everything better when the rhythm right

[verse]
From market to the beach the sound no stop
The DJ dey drop hit, the crowd no drop
We dance till morning with sweat for our face
This music na gift, this music na grace

[chorus]
Give me that feeling, that Lagos vibes
Give me that music, my daily rise
Afrobeats dey move me through the night
Everything better when the rhythm right

[bridge]
I no need anything else tonight
Just this music and the city light
Hold me close make the bassline guide
This na where I want to be inside

[outro]
Take me there, take me there
Where the music full the air
""",
    },
    # ── Congolese styles ─────────────────────────────────────────────────────
    # Afro-rumba choir in Fally Ipupa style — 90 BPM, SATB harmonies,
    # lead soloist + full choir call-response, sebene guitar break.
    "congolese-choir": {
        "english": """\
[verse]
I'm calling out across the water tonight
My heart is heavy but my soul wants to fight
From Kinshasa to the world I raise my voice
The rhythm of the Congo is my only choice

[chorus]
Mayday mayday hear my prayer tonight
Choir: Mayday, we are here
Mayday mayday bring us to the light
Choir: Mayday, do not fear
We are rising we are never going down
Choir: Rising, rising
From the river to the mountains and the town
Choir: Never stop, never stop

[verse]
The guitar starts to sing and the bass rolls low
The ancestors are dancing in the evening glow
Brass horns rising up like a morning sun
This Congolese rumba says we all are one

[chorus]
Mayday mayday hear my prayer tonight
Choir: Mayday, we are here
Mayday mayday bring us to the light
Choir: Mayday, do not fear
We are rising we are never going down
Choir: Rising, rising
From the river to the mountains and the town
Choir: Never stop, never stop

[bridge]
Hey hey hey
Choir: Hey
We keep moving forward
Choir: Forward
Nothing can stop us now
Choir: Nothing now
The sebene calls us all to dance
This is our moment, this is our chance
Hey hey hey
Choir: Mayday o

[outro]
Hear us calling
Choir: Mayday o
We are calling
Choir: Mayday o
From the Congo to the world
Choir: Mayday, mayday o
""",
    },
    # Soukous / Ndombolo — fast 145 BPM, rapid sebene guitar, atalaku shouts,
    # short punchy verses, designed to make the dance floor erupt.
    "soukous": {
        "english": """\
[verse]
The guitar is on fire tonight
My feet cannot stop moving right
Everybody on the floor
Kinshasa sound you can't ignore

[chorus]
Dance dance let the soukous flow
Choir: Soukous, let it go
Move move feel the sebene glow
Choir: Sebene, high and low
Ey ey ey the music takes control
Ey ey ey it's living in my soul

[verse]
The atalaku calls the crowd
Brass section playing way too loud
Bass guitar is walking fast
This Congolese groove is built to last

[chorus]
Dance dance let the soukous flow
Choir: Soukous, let it go
Move move feel the sebene glow
Choir: Sebene, high and low
Ey ey ey the music takes control
Ey ey ey it's living in my soul

[bridge]
Ey ey ey
Choir: Ey
Sebene time
Choir: Sebene
Guitar guitar guitar
Choir: Play it
Everybody wave your hands
Choir: Hands up
Nobody sits when soukous lands
Ey ey ey ey

[outro]
Soukous soukous
Choir: Ey ey
Soukous soukous
Choir: Don't stop now
""",
    },
    "duet": {
        "english": """\
[verse]
She: I heard you from across the room
He: Your melody cut right through the gloom
She: The way you move to that talking drum
He: Made me forget where I was coming from

[chorus]
Together: We found each other in the rhythm tonight
She: You and me
He: Moving right
Together: This Afrobeats love is burning bright
She: Don't let go
He: Hold me tight

[verse]
He: Tell me your story in this Lagos night
She: I'll sing it to you if the timing is right
He: The shekere speaks when the words run dry
She: Our hearts beat together beneath this sky

[chorus]
Together: We found each other in the rhythm tonight
She: You and me
He: Moving right
Together: This Afrobeats love is burning bright
She: Don't let go
He: Hold me tight

[bridge]
Together: No distance too far, no night too long
When we have this music and this song
Side by side we'll face whatever comes
Guided by the talking drums

[outro]
She: Stay with me
He: Stay with me
Together: In the rhythm, forever
""",
    },
}

# Default prompt for each style
_PROMPTS: dict[str, str] = {
    "choir": (
        "Afrobeats gospel choir anthem, 96 BPM, SATB choir with lead vocalist, "
        "call-and-response between soloist and full choir, talking drum, shekere, "
        "bass guitar, piano, orchestral strings, powerful and uplifting, "
        "Nigerian sound, professional studio production, high energy celebration"
    ),
    "solo": (
        "Afrobeats pop song, 100 BPM, soulful male vocalist, talking drum, shekere, "
        "bass guitar, Rhodes piano, smooth production, Lagos street energy, "
        "Wizkid style, warm mix, radio-ready"
    ),
    "duet": (
        "Afrobeats love song, 88 BPM, male and female vocalists, call-and-response, "
        "talking drum, acoustic guitar, gentle shekere, lush strings, "
        "romantic and soulful, Afrofusion ballad style"
    ),
    "congolese-choir": (
        "Congolese Afro-rumba choir anthem in the style of Fally Ipupa, 90 BPM, "
        "SATB gospel choir with powerful lead soloist, call-and-response between "
        "soloist and full choir, sebene electric guitar riff, walking bass guitar, "
        "congas and bougarabou drums, trumpet and trombone brass section, "
        "lush choir harmonies, deeply emotional and uplifting, Kinshasa sound, "
        "professional studio production, English lyrics"
    ),
    "soukous": (
        "Fast Congolese soukous ndombolo, 145 BPM, rapid syncopated sebene electric "
        "guitar riff, rhythm guitar comping, driving walking bass, tumba and conga "
        "polyrhythmic percussion, atalaku vocal shouts, brass stabs, "
        "high-energy dance floor, Kinshasa club sound, English lyrics"
    ),
}

# Instrumental prompt library
_INSTRUMENTAL_PROMPTS = [
    (
        "Afrobeats pop song, 100 BPM, featuring talking drum, shekere percussion, "
        "deep bass guitar, Rhodes piano chords, call-and-response vocal texture, "
        "Lagos street energy, Wizkid style, warm mix, radio-ready production"
    ),
    (
        "Amapiano crossover track, 115 BPM, log drum bass, marimba lead melody, "
        "deep house groove, layered vocals, South African influence, dance floor energy, "
        "professional studio production"
    ),
    (
        "Afrofusion ballad, 85 BPM, acoustic guitar, talking drum, gentle shekere, "
        "soulful vocal melody, minor key, Yoruba lyrical inflections, lush strings, "
        "emotional and atmospheric"
    ),
    (
        "Alte indie Afrobeats, 95 BPM, lo-fi drum machine, plucked kora, synthesizer pads, "
        "reverb-heavy guitar, dreamy vocal texture, Lagos alternative scene, midnight vibes"
    ),
    (
        "Congolese Afro-rumba instrumental, 90 BPM, sebene electric guitar riff, "
        "walking bass, congas and bougarabou percussion, trumpet and trombone, "
        "rhythm guitar comping, Kinshasa sound, Fally Ipupa style"
    ),
    (
        "Soukous ndombolo instrumental, 145 BPM, rapid sebene guitar, polyrhythmic "
        "tumba and conga drums, walking bass, brass stabs, Congolese dance music"
    ),
]


# ── Audio stitching and mastering ─────────────────────────────────────────────

def crossfade_stitch(
    path_a: Path,
    path_b: Path,
    out_path: Path,
    crossfade_s: float = 3.0,
) -> Path:
    """Concatenate two audio files with a cosine crossfade, matching sample rates.

    path_a tail fades out while path_b head fades in over crossfade_s seconds.
    Both files are normalized to stereo float32 before mixing.
    Final output is peak-limited to -1 dBFS.
    """
    import numpy as np
    import soundfile as sf

    audio_a, sr_a = sf.read(str(path_a), always_2d=True)
    audio_b, sr_b = sf.read(str(path_b), always_2d=True)

    # Resample b to match a if needed.
    # Use soxr directly — librosa.resample lazy-loads numba which breaks on NumPy 2.4+.
    if sr_a != sr_b:
        import soxr
        audio_b = soxr.resample(audio_b.astype(np.float32), sr_b, sr_a, quality="HQ")
        sr_b = sr_a

    sr = sr_a

    # Normalise channel count to stereo
    def _to_stereo(a: "np.ndarray") -> "np.ndarray":
        if a.shape[1] == 1:
            return np.repeat(a, 2, axis=1)
        return a[:, :2]

    audio_a = _to_stereo(audio_a)
    audio_b = _to_stereo(audio_b)

    cf = int(min(crossfade_s * sr, len(audio_a) * 0.25, len(audio_b) * 0.25))

    # Cosine crossfade — less audible than linear
    t = np.linspace(0.0, np.pi / 2, cf, dtype=np.float32)
    fade_out = np.cos(t)[:, None]
    fade_in  = np.sin(t)[:, None]

    overlap = audio_a[-cf:] * fade_out + audio_b[:cf] * fade_in
    result  = np.concatenate([audio_a[:-cf], overlap, audio_b[cf:]], axis=0)

    # Peak limit to -1 dBFS
    peak = float(np.abs(result).max())
    if peak > 0.891:
        result = result * (0.891 / peak)

    sf.write(str(out_path), result.astype(np.float32), sr, subtype="FLOAT")
    print(f"[gbedu] Stitched: {len(audio_a)/sr:.1f}s + {len(audio_b)/sr:.1f}s "
          f"→ {len(result)/sr:.1f}s  ({crossfade_s}s crossfade)  → {out_path.name}")
    return out_path


def apply_congolese_master(path: Path, out_path: Path) -> Path:
    """Pedalboard mastering chain tuned for Congolese Afro-rumba.

    Afrobeats chain boosts low-end bass.  Congolese rumba needs a cleaner
    midrange — the sebene guitar must cut through without mud.  So we:
      • HP at 50 Hz (remove sub-rumble, keep warm bass)
      • Moderate compression (3:1, slower attack — preserve transients)
      • +2.5 dB peak at 2.8 kHz (sebene guitar presence)
      • +1.5 dB high shelf at 10 kHz (brass air, choir shimmer)
      • Brickwall limit at -1 dBFS
    """
    try:
        import numpy as np
        import soundfile as sf
        from pedalboard import (
            Compressor, HighpassFilter, HighShelfFilter,
            Limiter, Pedalboard, PeakFilter,
        )

        audio, sr = sf.read(str(path), always_2d=True)
        chain = Pedalboard([
            HighpassFilter(cutoff_frequency_hz=50.0),
            Compressor(threshold_db=-16.0, ratio=3.0, attack_ms=8.0, release_ms=150.0),
            PeakFilter(cutoff_frequency_hz=2800.0, gain_db=2.5, q=1.0),
            HighShelfFilter(cutoff_frequency_hz=10000.0, gain_db=1.5, q=0.707),
            Limiter(threshold_db=-1.0, release_ms=100.0),
        ])
        processed = chain(audio.T.astype(np.float32), sample_rate=sr)
        sf.write(str(out_path), processed.T, sr, subtype="FLOAT")
        print(f"[gbedu] Mastering applied → {out_path.name}")
        return out_path
    except Exception as exc:
        print(f"[gbedu] Mastering skipped ({type(exc).__name__}: {exc}), using stitched file")
        return path


# ── Instrumental path (MusicGen) ───────────────────────────────────────────────

def _next_output_path(prefix: str, ext: str = "wav") -> Path:
    existing = sorted(OUTPUT_DIR.glob(f"afrobeats_*.{ext}"))
    n = len(existing) + 1
    return OUTPUT_DIR / f"afrobeats_{n:03d}.{ext}"


def generate_instrumental(model_size: str, duration: int, prompt: str) -> Path:
    import random
    if not prompt:
        prompt = random.choice(_INSTRUMENTAL_PROMPTS)

    model_id = {
        "small": "facebook/musicgen-small",
        "medium": "facebook/musicgen-medium",
        "large": "facebook/musicgen-large",
        "stereo-medium": "facebook/musicgen-stereo-medium",
    }.get(model_size, f"facebook/musicgen-{model_size}")

    print(f"\n[gbedu] Mode:     instrumental (MusicGen)")
    print(f"[gbedu] Model:    {model_id}")
    print(f"[gbedu] Duration: {duration}s")
    print(f"[gbedu] Prompt:   {prompt[:120]}...")

    import torch
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"[gbedu] Device:   {device}")

    from transformers import AutoProcessor, MusicgenForConditionalGeneration
    import numpy as np
    import soundfile as sf

    print("\n[gbedu] Loading model...")
    processor = AutoProcessor.from_pretrained(model_id, cache_dir=str(MODEL_CACHE))
    model = MusicgenForConditionalGeneration.from_pretrained(model_id, cache_dir=str(MODEL_CACHE))
    model = model.to(device)
    print("[gbedu] Model loaded.")

    inputs = processor(text=[prompt], padding=True, return_tensors="pt").to(device)
    max_new_tokens = duration * 50
    print(f"\n[gbedu] Generating {duration}s (~{max_new_tokens} tokens)...")

    with torch.no_grad():
        audio_values = model.generate(
            **inputs, max_new_tokens=max_new_tokens, do_sample=True, guidance_scale=3.0,
        )

    audio = audio_values[0].cpu()
    if audio.dim() == 1:
        audio = audio.unsqueeze(0)

    sr = model.config.audio_encoder.sampling_rate
    out_path = _next_output_path("afrobeats")
    sf.write(str(out_path), audio.float().numpy().T, sr)
    print(f"\n[gbedu] Saved: {out_path}  ({audio.shape[-1] / sr:.1f}s @ {sr}Hz)")
    return out_path


# ── Vocal path (ACE-Step) ──────────────────────────────────────────────────────

def generate_vocals(
    style: str,
    duration: int,
    prompt_override: str | None,
    lyrics_override: str | None,
    language: str,
    infer_steps: int,
) -> Path:
    try:
        from acestep.pipeline_ace_step import ACEStepPipeline  # type: ignore[import]
    except ImportError:
        print("[gbedu] ERROR: ACE-Step not installed.", file=sys.stderr)
        print("[gbedu]   uv pip install 'git+https://github.com/ace-step/ACE-Step.git'", file=sys.stderr)
        sys.exit(1)

    prompt = prompt_override or _PROMPTS.get(style, _PROMPTS["solo"])
    lyrics_bank = _LYRICS.get(style, _LYRICS["solo"])
    lyrics = lyrics_override or lyrics_bank.get(language) or lyrics_bank.get("english", "")

    print(f"\n[gbedu] Mode:     vocals (ACE-Step 1.5)")
    print(f"[gbedu] Style:    {style}")
    print(f"[gbedu] Language: {language}")
    print(f"[gbedu] Duration: {duration}s")
    print(f"[gbedu] Steps:    {infer_steps}  (more = better quality, longer runtime)")
    print(f"[gbedu] Prompt:   {prompt[:120]}...")
    print(f"[gbedu] Lyrics:   {lyrics[:80].strip()}...")

    import torch
    device_label = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"[gbedu] Device:   {device_label} (auto-detected by ACE-Step)")

    if device_label == "cpu":
        est = duration * infer_steps * 4 // 60
        print(f"[gbedu] ⚠  CPU mode — estimated ~{est}+ min for {duration}s clip at {infer_steps} steps")
        print(f"[gbedu]    Use --fast for 20 steps (~{duration * 20 * 4 // 60} min) or a CUDA GPU for best speed")
    elif device_label == "mps":
        est = duration * infer_steps // 6
        print(f"[gbedu] ⚠  MPS mode — estimated ~{est}+ min for {duration}s at {infer_steps} steps")

    print("\n[gbedu] Loading ACE-Step (downloads ~7GB on first run to ~/.cache/ace-step/)...")
    pipeline = ACEStepPipeline(
        checkpoint_dir=None,   # uses ~/.cache/ace-step/checkpoints, auto-downloads
        cpu_offload=True,      # layer-by-layer offload keeps peak VRAM manageable
    )

    out_path = _next_output_path("afrobeats")

    print(f"[gbedu] Generating...")
    pipeline(
        format="wav",
        audio_duration=float(duration),
        prompt=prompt,
        lyrics=lyrics,
        infer_step=infer_steps,
        guidance_scale=15.0,
        scheduler_type="euler",
        cfg_type="apg",
        omega_scale=10.0,
        use_erg_tag=True,
        use_erg_lyric=True,
        use_erg_diffusion=True,
        save_path=str(out_path),
    )

    print(f"\n[gbedu] Saved: {out_path}")
    return out_path


# ── Full Congolese composition pipeline ───────────────────────────────────────

# Vocal lyrics used in the full pipeline: verse1 → chorus → verse2 → chorus →
# bridge (choir transition INTO the sebene) → outro.  No separate [bridge] tag
# for the sebene itself — MusicGen generates that section independently.
_CONGOLESE_FULL_LYRICS = """\
[verse]
I'm calling out across the water tonight
My heart is heavy but my soul wants to fight
From Kinshasa to the world I raise my voice
The rhythm of the Congo is my only choice

[chorus]
Mayday mayday hear my prayer tonight
Choir: Mayday, we are here
Mayday mayday bring us to the light
Choir: Mayday, do not fear
We are rising we are never going down
Choir: Rising, rising
From the river to the mountains and the town
Choir: Never stop, never stop

[verse]
The guitar starts to sing and the bass rolls low
The ancestors are dancing in the evening glow
Brass horns rising up like a morning sun
This Congolese rumba says we all are one

[chorus]
Mayday mayday hear my prayer tonight
Choir: Mayday, we are here
Mayday mayday bring us to the light
Choir: Mayday, do not fear
We are rising we are never going down
Choir: Rising, rising
From the river to the mountains and the town
Choir: Never stop, never stop

[outro]
Hear us calling
Choir: Mayday o
We are calling
Choir: Mayday o
From the Congo to the world
Choir: Mayday, mayday o
"""

_SEBENE_PROMPT = (
    "Congolese soukous sebene guitar instrumental break, 145 BPM, "
    "rapid syncopated electric guitar riff, rhythm guitar comping, "
    "driving walking bass guitar, conga and tumba polyrhythmic drums, "
    "brass stabs, no vocals, no singing, no lyrics, pure instrumental dance break, "
    "Kinshasa club sound, tight professional mix"
)


def generate_congolese_full(
    duration_vocals: int = 60,
    duration_sebene: int = 30,
    crossfade_s: float = 3.0,
    prompt_override: str | None = None,
    lyrics_override: str | None = None,
    infer_steps: int = 60,
    model_size: str = "medium",
    no_master: bool = False,
) -> Path:
    """Full Congolese composition: ACE-Step vocals → MusicGen sebene → crossfade stitch → master.

    Structure:
      [verse] [chorus] [verse] [chorus] [outro]  ←  ACE-Step vocal section
                                    ↓ {crossfade_s}s cosine crossfade
      ════ sebene break ════════════════════════  ←  MusicGen instrumental

    The sebene section is generated separately as pure instrumental so the guitar
    riff is clean and uncontaminated by vocal conditioning.  The crossfade lands
    at the end of the vocal outro, where choir energy naturally recedes.
    """
    total_s = duration_vocals + duration_sebene - crossfade_s
    print()
    print("[gbedu] ═══════════════════════════════════════════════════════")
    print("[gbedu]  Full Congolese Composition Pipeline")
    print("[gbedu]  vocals (ACE-Step) ──crossfade──▶ sebene (MusicGen)")
    print(f"[gbedu]  {duration_vocals}s vocals  +  {duration_sebene}s sebene  "
          f"-  {crossfade_s}s crossfade  =  ~{total_s:.0f}s total")
    print("[gbedu] ═══════════════════════════════════════════════════════")

    # ── Step 1: vocal section ─────────────────────────────────────────────────
    print(f"\n[gbedu] Step 1/3 — Vocal section  ({duration_vocals}s, ACE-Step {infer_steps} steps)")
    vocal_path = generate_vocals(
        style="congolese-choir",
        duration=duration_vocals,
        prompt_override=prompt_override,
        lyrics_override=lyrics_override or _CONGOLESE_FULL_LYRICS,
        language="english",
        infer_steps=infer_steps,
    )

    # ── Step 2: sebene instrumental break ─────────────────────────────────────
    print(f"\n[gbedu] Step 2/3 — Sebene instrumental  ({duration_sebene}s, MusicGen {model_size})")
    sebene_path = generate_instrumental(
        model_size=model_size,
        duration=duration_sebene,
        prompt=_SEBENE_PROMPT,
    )

    # ── Step 3: stitch + master ───────────────────────────────────────────────
    print(f"\n[gbedu] Step 3/3 — Crossfade stitch + mastering")

    # Place the stitched file next to the other outputs, with _stitched suffix
    n = len(sorted(OUTPUT_DIR.glob("afrobeats_*.wav"))) + 1
    stitched_path = OUTPUT_DIR / f"afrobeats_{n:03d}_stitched.wav"
    crossfade_stitch(vocal_path, sebene_path, stitched_path, crossfade_s=crossfade_s)

    if no_master:
        final_path = stitched_path
    else:
        final_path = OUTPUT_DIR / f"afrobeats_{n:03d}_final.wav"
        final_path = apply_congolese_master(stitched_path, final_path)

    print()
    print("[gbedu] ─────────────────────────────────────────────────────")
    print(f"[gbedu]  Vocal section :  {vocal_path.name}  ({duration_vocals}s)")
    print(f"[gbedu]  Sebene break  :  {sebene_path.name}  ({duration_sebene}s)")
    print(f"[gbedu]  Final track   :  {final_path.name}  (~{total_s:.0f}s)")
    print("[gbedu] ─────────────────────────────────────────────────────")
    return final_path


# ── Playback ───────────────────────────────────────────────────────────────────

def play(path: Path) -> None:
    print(f"\n[gbedu] Playing {path.name} ...")
    if sys.platform == "darwin":
        subprocess.run(["afplay", str(path)], check=False)
    elif sys.platform.startswith("linux"):
        subprocess.run(["aplay", str(path)], check=False)
    else:
        print(f"[gbedu] Open {path} in your audio player.")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Generate an Afrobeats / Congolese track (instrumental, vocals, or full composition)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_song.py                                          # instrumental, medium model
  python generate_song.py --model large --duration 45             # longer, higher quality
  python generate_song.py --vocals                                # Afrobeats choir, English, 30s
  python generate_song.py --vocals --style choir --language pidgin --duration 60
  python generate_song.py --vocals --style solo --fast            # quick test, 20 steps
  python generate_song.py --vocals --style congolese-choir        # Fally Ipupa style choir
  python generate_song.py --vocals --style congolese-choir --duration 60 --steps 60
  python generate_song.py --vocals --style soukous --fast         # fast ndombolo
  python generate_song.py --vocals --lyrics "$(cat my_lyrics.txt)"
  python generate_song.py --full                                  # full Congolese composition
  python generate_song.py --full --vocal-duration 90 --sebene-duration 45
  python generate_song.py --full --fast --sebene-duration 20 --no-play
""",
    )

    # Shared
    p.add_argument("--duration", type=int, default=30, metavar="SEC",
                   help="Duration for single-mode generation (default: 30)")
    p.add_argument("--prompt", type=str, default=None, metavar="TEXT")
    p.add_argument("--no-play", action="store_true")

    # Instrumental mode
    inst = p.add_argument_group("instrumental mode (default)")
    inst.add_argument("--model", default="medium",
                      choices=["small", "medium", "large", "stereo-medium"])

    # Vocal mode
    voc = p.add_argument_group("vocal mode (--vocals)")
    voc.add_argument("--vocals", action="store_true",
                     help="Use ACE-Step for full song with real singing")
    voc.add_argument("--style", default="choir",
                     choices=["choir", "solo", "duet", "congolese-choir", "soukous"],
                     help="Vocal arrangement (default: choir)")
    voc.add_argument("--language", default="english",
                     choices=["english", "pidgin", "yoruba"],
                     help="Lyric language (default: english)")
    voc.add_argument("--lyrics", type=str, default=None, metavar="TEXT",
                     help="Custom lyrics (use [verse]/[chorus]/[bridge] tags)")
    voc.add_argument("--steps", type=int, default=60, metavar="N",
                     help="ACE-Step inference steps — more = better (default: 60)")
    voc.add_argument("--fast", action="store_true",
                     help="Shortcut for --steps 20 (good enough for demos)")

    # Full composition mode
    full = p.add_argument_group("full Congolese composition mode (--full)")
    full.add_argument("--full", action="store_true",
                      help="Multi-step pipeline: ACE-Step vocals → MusicGen sebene → crossfade → master")
    full.add_argument("--vocal-duration", type=int, default=60, metavar="SEC",
                      help="Vocal section length for --full (default: 60)")
    full.add_argument("--sebene-duration", type=int, default=30, metavar="SEC",
                      help="Sebene instrumental break length for --full (default: 30)")
    full.add_argument("--crossfade", type=float, default=3.0, metavar="SEC",
                      help="Crossfade overlap between vocal and sebene sections (default: 3.0)")
    full.add_argument("--no-master", action="store_true",
                      help="Skip the pedalboard mastering pass in --full mode")

    args = p.parse_args()

    if args.full:
        infer_steps = 20 if args.fast else args.steps
        out_path = generate_congolese_full(
            duration_vocals=args.vocal_duration,
            duration_sebene=args.sebene_duration,
            crossfade_s=args.crossfade,
            prompt_override=args.prompt,
            lyrics_override=args.lyrics,
            infer_steps=infer_steps,
            model_size=args.model,
            no_master=args.no_master,
        )
    elif args.vocals:
        infer_steps = 20 if args.fast else args.steps
        out_path = generate_vocals(
            style=args.style,
            duration=args.duration,
            prompt_override=args.prompt,
            lyrics_override=args.lyrics,
            language=args.language,
            infer_steps=infer_steps,
        )
    else:
        import random
        prompt = args.prompt or random.choice(_INSTRUMENTAL_PROMPTS)
        out_path = generate_instrumental(args.model, args.duration, prompt)

    if args.no_play:
        print(f"\n[gbedu] Output: {out_path}")
    else:
        play(out_path)


if __name__ == "__main__":
    main()
