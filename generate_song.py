#!/usr/bin/env python3
"""Standalone Afrobeats song generator — runs directly on MPS/CPU.

Uses facebook/musicgen-medium (1.5B params, ~3GB) via HuggingFace transformers.
No auth token needed. Saves output to /tmp/gbedu_output/afrobeats_<n>.wav
and plays it with afplay (macOS).

Usage:
    python generate_song.py [--model small|medium|large] [--duration 30] [--prompt "..."]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# ── output dir ────────────────────────────────────────────────────────────────
OUTPUT_DIR = Path("/tmp/gbedu_output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Afrobeats prompt library ──────────────────────────────────────────────────
AFROBEATS_PROMPTS = [
	(
		"Afrobeats pop song, 100 BPM, featuring talking drum, shekere percussion, "
		"deep bass guitar, Rhodes piano chords, call-and-response vocals, Lagos street energy, "
		"Wizkid style, warm mix, radio-ready production"
	),
	(
		"Amapiano crossover track, 115 BPM, log drum bass, marimba lead melody, "
		"deep house groove, layered vocals, South African influence, dance floor energy, "
		"professional studio production"
	),
	(
		"Afrofusion ballad, 85 BPM, acoustic guitar, talking drum, gentle shekere, "
		"soulful male vocals, minor key, Yoruba vocal inflections, lush strings arrangement, "
		"emotional and atmospheric"
	),
	(
		"Alte indie Afrobeats, 95 BPM, lo-fi drum machine, plucked kora, synthesizer pads, "
		"reverb-heavy guitar, dreamy vocals, Lagos alternative scene, midnight vibes"
	),
]


def build_prompt(custom: str | None = None) -> str:
	if custom:
		return custom
	import random
	return random.choice(AFROBEATS_PROMPTS)


def generate(model_size: str, duration_seconds: int, prompt: str) -> Path:
	model_id = {
		"small": "facebook/musicgen-small",      # ~300MB
		"medium": "facebook/musicgen-medium",    # ~1.5GB
		"large": "facebook/musicgen-large",      # ~3.3GB
		"stereo-medium": "facebook/musicgen-stereo-medium",  # stereo, ~1.5GB
	}.get(model_size, f"facebook/musicgen-{model_size}")

	print(f"\n[gbedu] Model:    {model_id}")
	print(f"[gbedu] Duration: {duration_seconds}s")
	print(f"[gbedu] Prompt:   {prompt[:120]}...")

	import torch

	# Device selection: MPS → CPU
	if torch.backends.mps.is_available():
		device = "mps"
	else:
		device = "cpu"
	print(f"[gbedu] Device:   {device}")

	from transformers import AutoProcessor, MusicgenForConditionalGeneration

	print("\n[gbedu] Loading model (will download on first run)...")
	cache_dir = Path("/tmp/gbedu_model_cache")
	cache_dir.mkdir(parents=True, exist_ok=True)

	processor = AutoProcessor.from_pretrained(model_id, cache_dir=str(cache_dir))
	model = MusicgenForConditionalGeneration.from_pretrained(
		model_id,
		cache_dir=str(cache_dir),
	)
	model = model.to(device)
	print("[gbedu] Model loaded.")

	# tokens_per_second ≈ 50 for MusicGen
	max_new_tokens = duration_seconds * 50

	inputs = processor(
		text=[prompt],
		padding=True,
		return_tensors="pt",
	).to(device)

	print(f"\n[gbedu] Generating {duration_seconds}s of audio (~{max_new_tokens} tokens)...")

	with torch.no_grad():
		audio_values = model.generate(
			**inputs,
			max_new_tokens=max_new_tokens,
			do_sample=True,
			guidance_scale=3.0,
		)

	# audio_values: [batch, channels, samples]
	audio = audio_values[0].cpu()  # [channels, samples] or [samples]
	if audio.dim() == 1:
		audio = audio.unsqueeze(0)

	sampling_rate = model.config.audio_encoder.sampling_rate

	import numpy as np
	import soundfile as sf

	# Next available filename
	existing = sorted(OUTPUT_DIR.glob("afrobeats_*.wav"))
	n = len(existing) + 1
	out_path = OUTPUT_DIR / f"afrobeats_{n:03d}.wav"

	# audio: [channels, samples] float32 tensor → numpy [samples, channels]
	audio_np = audio.float().numpy().T
	sf.write(str(out_path), audio_np, sampling_rate)
	print(f"\n[gbedu] Saved: {out_path}")
	print(f"[gbedu] Sample rate: {sampling_rate} Hz, Duration: {audio.shape[-1] / sampling_rate:.1f}s")

	return out_path


def play(path: Path) -> None:
	print(f"\n[gbedu] Playing {path.name} ...")
	if sys.platform == "darwin":
		subprocess.run(["afplay", str(path)], check=False)
	elif sys.platform.startswith("linux"):
		subprocess.run(["aplay", str(path)], check=False)
	else:
		print(f"[gbedu] Open {path} in your audio player.")


def main() -> None:
	parser = argparse.ArgumentParser(description="Generate an Afrobeats track")
	parser.add_argument("--model", default="medium", choices=["small", "medium", "large", "stereo-medium"])
	parser.add_argument("--duration", type=int, default=30, help="Duration in seconds (default: 30)")
	parser.add_argument("--prompt", type=str, default=None, help="Custom text prompt")
	parser.add_argument("--no-play", action="store_true", help="Skip playback")
	args = parser.parse_args()

	prompt = build_prompt(args.prompt)
	out_path = generate(args.model, args.duration, prompt)

	if not args.no_play:
		play(out_path)
	else:
		print(f"\n[gbedu] Output: {out_path}")


if __name__ == "__main__":
	main()
