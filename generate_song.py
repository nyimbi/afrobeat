#!/usr/bin/env python3
"""Standalone Afrobeats song generator.

Two modes:
  Instrumental  — facebook/musicgen-* via HuggingFace transformers (fast, no vocals)
  Vocals        — ACE-Step 1.5 (full song with real singing, slower)

Usage:
    python generate_song.py [--model small|medium|large] [--duration 30]
    python generate_song.py --vocals [--style choir|solo|duet] [--language english|pidgin|yoruba]
    python generate_song.py --vocals --lyrics "custom lyrics here" --prompt "custom prompt"
    python generate_song.py --vocals --style choir --fast   # 20 inference steps, ~10 min on CPU
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
]


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
        description="Generate an Afrobeats track (instrumental or with vocals)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_song.py                                  # instrumental, medium model
  python generate_song.py --model large --duration 45      # longer, higher quality
  python generate_song.py --vocals                         # choir vocals, English, 30s
  python generate_song.py --vocals --style choir --language pidgin --duration 60
  python generate_song.py --vocals --style solo --fast     # quick test, 20 steps
  python generate_song.py --vocals --lyrics "$(cat my_lyrics.txt)"
""",
    )

    # Shared
    p.add_argument("--duration", type=int, default=30, metavar="SEC")
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
                     choices=["choir", "solo", "duet"],
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

    args = p.parse_args()

    if args.vocals:
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
