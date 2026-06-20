# Gbẹdu — ML Model Fine-Tuning Guide

This document covers updating all three models in the Gbẹdu ML stack. Read the relevant section completely before touching model weights — a bad model update silently degrades output quality for all users.

---

## Overview

| Model | Base | Task | Adapter type | Approx. training time |
|-------|------|------|-------------|----------------------|
| ACE-Step 1.5 | ACE-Step 1.5 diffusion | Music generation | LoRA (rank 16) | 8h on A100 80GB |
| Gbedu-Lyrics | Llama-3 8B Instruct | Afrobeats lyrics | SFT (full fine-tune last 8 layers) | 4h on A100 80GB |
| Gbedu-Voice | RVC v2 | Voice conversion | Full model per voice | 30–90 min on A100 |

All trained weights live in Cloudflare R2 under `gbedu-models/`:
```
gbedu-models/
  ace-step/
    v1.0/  ← current prod
    v1.1/  ← previous (keep for rollback)
  lyrics/
    v1.0/
  voice/
    {voice_model_id}/
      model.pth
      index.faiss
```

---

## ACE-Step 1.5 LoRA fine-tuning

### Why LoRA

ACE-Step 1.5 is a diffusion model with ~800M parameters. Full fine-tuning on a single A100 takes days and overfits quickly on small datasets. LoRA (rank 16, alpha 32) trains ~3M parameters, trains in 8h, and adapts the model's genre/style conditioning without degrading its general music understanding.

### Dataset format

Each training example is a JSON Lines entry in `data/ace_step_train.jsonl`:

```jsonl
{"audio_path": "data/audio/track_001.wav", "genre": "afrobeats", "bpm": 128, "key": "A minor", "mood": "euphoric", "instruments": ["drums", "talking_drum", "bass", "guitar"], "lyrics": "Verse 1: ..."}
{"audio_path": "data/audio/track_002.wav", "genre": "amapiano", "bpm": 112, "key": "G major", "mood": "energetic", "instruments": ["piano", "bass", "percussion", "claps"], "lyrics": null}
```

Requirements:
- Minimum 500 tracks per genre being fine-tuned
- Audio: 44.1kHz stereo WAV, normalized to -14 LUFS, minimum 60s (longer clips are windowed)
- All audio must be cleared for AI training use — no unlicensed samples, no samples from uncleared artists
- BPM and key must be verified with a reliable tool (we use `librosa` via `gbedu_audio.analysis`)
- Recommended validation split: 90/10 train/val, stratified by genre

### Dataset quality criteria

Before training, run the dataset auditor:

```bash
uv run python scripts/audit_dataset.py \
  --manifest data/ace_step_train.jsonl \
  --audio-dir data/audio/ \
  --output data/audit_report.json
```

The auditor checks:
- Audio duration (rejects < 30s)
- Silence detection (rejects > 30% silence)
- Clipping detection (rejects if peak > -0.1 dBFS)
- BPM variance (warns if claimed BPM differs from detected by > 5 BPM)
- Duplicate detection via audio fingerprinting

Fix all errors before training. Warnings may be acceptable if < 5% of the dataset.

### Training command

Training runs on the GPU server. SSH to `62.169.25.77` (ml server with Ollama/GPU), then:

```bash
# Activate training environment
cd /opt/gbedu-training
source .venv/bin/activate

# Start LoRA fine-tuning
python train_ace_step_lora.py \
  --base-model ace-step/ace-step-v1-5 \
  --dataset data/ace_step_train.jsonl \
  --output-dir checkpoints/ace-step-v1.2 \
  --lora-rank 16 \
  --lora-alpha 32 \
  --lora-target-modules "to_q,to_k,to_v,to_out.0" \
  --learning-rate 1e-4 \
  --warmup-steps 100 \
  --max-steps 5000 \
  --batch-size 4 \
  --gradient-accumulation-steps 4 \
  --eval-steps 500 \
  --save-steps 1000 \
  --fp16 \
  --report-to wandb \
  --run-name "ace-step-v1.2-$(date +%Y%m%d)"
```

Monitor training in WandB. Key metrics:
- `train/loss` — should decrease steadily. Plateau after step 3000 is normal.
- `eval/loss` — must stay close to `train/loss`. Divergence > 0.2 = overfitting, stop early.
- `eval/fad` — Fréchet Audio Distance vs. held-out set. Target < 5.0 for Afrobeats.

### Evaluation

Before promoting any checkpoint to production, run the full evaluation suite:

```bash
python evaluate_ace_step.py \
  --checkpoint checkpoints/ace-step-v1.2/checkpoint-5000 \
  --eval-set data/ace_step_eval.jsonl \
  --output evals/ace-step-v1.2.json \
  --metrics fad,clap_score,bpm_accuracy,key_accuracy
```

Minimum passing thresholds (enforced by the evaluation script — exits non-zero if not met):

| Metric | Threshold | Notes |
|--------|-----------|-------|
| FAD (Fréchet Audio Distance) | < 6.0 | Lower is better. Current prod: ~4.2 |
| CLAP score | > 0.28 | Text-audio alignment. Current prod: ~0.31 |
| BPM accuracy (±3 BPM) | > 85% | |
| Key accuracy | > 70% | |

Also do a mandatory human listening test: generate 20 tracks across all 6 genres, listen to all of them. Reject the checkpoint if > 2 tracks have obvious artefacts (metallic noise, sudden silence, tempo drift).

### Upload and deploy

```bash
# Convert safetensors checkpoint
python export_lora.py \
  --checkpoint checkpoints/ace-step-v1.2/checkpoint-5000 \
  --output lora-v1.2.safetensors

# Upload to R2
aws s3 cp lora-v1.2.safetensors \
  s3://gbedu-models/ace-step/v1.2/lora.safetensors \
  --endpoint-url https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com
```

Then follow the model update procedure in `docs/RUNBOOKS.md` § "Model update procedure".

---

## Llama-3 8B lyrics model SFT

### Why SFT on Llama-3

Llama-3 8B Instruct generates coherent English text but knows nothing about Afrobeats song structure, Yoruba/Pidgin code-switching, or the specific imagery and idioms of the genre. SFT on a curated dataset of ~10 000 Afrobeats lyrics examples teaches the model song structure (verse, chorus, bridge), genre-specific vocabulary, and multilingual mixing.

### Dataset format

`data/lyrics_train.jsonl` — each entry is a single instruction-response pair:

```jsonl
{"instruction": "Write Afrobeats lyrics about celebrating life in Lagos, energetic mood, mix Yoruba and English, verse + chorus structure.", "response": "Verse 1:\nWe come a long way, e no easy\n...\n\nChorus:\nLife is sweet, aye, Lagos don't sleep\n..."}
```

Requirements:
- Minimum 10 000 examples
- Genre distribution: 40% afrobeats, 20% afropop, 15% amapiano, 15% highlife, 10% other
- Language distribution: 50% English-dominant, 30% Yoruba/English mix, 20% Pidgin English
- All lyrics must be original or cleared for AI training — no scraping copyrighted lyrics
- Quality filter: reject examples < 100 tokens or > 2000 tokens (outlier lyrics)
- Deduplication: remove near-duplicates with MinHash similarity > 0.8

### Training command

```bash
python train_lyrics_sft.py \
  --base-model meta-llama/Meta-Llama-3-8B-Instruct \
  --dataset data/lyrics_train.jsonl \
  --output-dir checkpoints/lyrics-v1.1 \
  --freeze-layers 24 \
  --learning-rate 2e-5 \
  --warmup-ratio 0.03 \
  --num-epochs 3 \
  --batch-size 8 \
  --gradient-accumulation-steps 2 \
  --max-seq-length 2048 \
  --bf16 \
  --report-to wandb \
  --run-name "lyrics-sft-v1.1-$(date +%Y%m%d)"
```

`--freeze-layers 24` freezes the first 24 of 32 transformer layers. Only the last 8 layers + the LM head are trained. This prevents catastrophic forgetting of general language capabilities while allowing genre adaptation.

### Evaluation

```bash
python evaluate_lyrics.py \
  --checkpoint checkpoints/lyrics-v1.1 \
  --eval-set data/lyrics_eval.jsonl \
  --output evals/lyrics-v1.1.json
```

Metrics evaluated:
- **Perplexity** on held-out Afrobeats lyrics (target < 18; current prod: ~14)
- **Structure adherence** — does output contain verse/chorus markers? (target > 90%)
- **Language mixing quality** — automated classifier for appropriate Yoruba/English mixing (target > 0.75)
- **Toxicity score** — must score < 0.05 on Perspective API

Human evaluation: generate 30 lyrics sets (5 per mood), have at least 2 Afrobeats-familiar reviewers rate them 1–5 for authenticity. Minimum average score: 3.5/5.

### Export and upload

```bash
# Merge adapter into base model for faster inference (avoids LoRA overhead at serving time)
python merge_and_export.py \
  --checkpoint checkpoints/lyrics-v1.1 \
  --output checkpoints/lyrics-v1.1-merged \
  --format safetensors

# Upload
aws s3 sync checkpoints/lyrics-v1.1-merged/ \
  s3://gbedu-models/lyrics/v1.1/ \
  --endpoint-url https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com
```

The ML service loads the model from R2 on startup via `LYRICS_MODEL_PATH` env var.

---

## RVC v2 voice model training

### Dependencies

The `rvc` package is not on PyPI. Install it from source before running any training or inference commands:

```bash
# From the repo root — installs rvc and all required native deps
bash services/ml/install_rvc.sh
```

Required packages installed by that script:

| Package | Purpose |
|---------|---------|
| `rvc` (from GitHub) | Voice conversion and training core |
| `fairseq` | Wav2Vec2 feature extraction (used by RVC pitch extractor) |
| `faiss-cpu` | FAISS index for feature retrieval (use `faiss-gpu` on GPU nodes) |
| `praat-parselmouth` | Pitch analysis via Praat |
| `pyworld` | WORLD vocoder — harvest/dio pitch extraction |

In the ML service Docker image, `install_rvc.sh` is called during the builder stage. If installation fails at build time (e.g. network issue fetching the GitHub repo), the build continues with a warning and voice synthesis is disabled at runtime (`is_loaded=False` in `/health`).

### Overview

RVC (Retrieval-based Voice Conversion) v2 trains a small voice encoder per speaker from 5–30 minutes of clean vocal audio. Each voice model is specific to one speaker/artist. System-provided voice models are generic (gender + style); user-uploaded voice models are speaker-specific.

Training one voice model takes 30–90 minutes on a single A100, depending on dataset duration.

### Audio requirements

| Requirement | Specification |
|-------------|--------------|
| Duration | 10–30 minutes (more = better quality; diminishing returns after 30 min) |
| Format | WAV, 44.1kHz, mono or stereo (converted to mono internally) |
| SNR | > 35 dB (very clean; background noise < -35 dBFS) |
| Content | Dry vocals only — no music, no reverb, no harmonies |
| Linguistic diversity | Cover full phoneme set of the target language |
| Consistency | Same recording session and microphone throughout |

Reject audio that:
- Contains music in the background
- Has clipping (peak > -0.5 dBFS)
- Has noticeable reverb (RT60 > 200ms detected via `gbedu_audio.analysis.estimate_rt60`)
- Is compressed voice memo quality (below 44.1kHz)

### Dataset preparation

```bash
# 1. Denoise (if needed) — optional but improves quality
python tools/denoise_audio.py \
  --input user_recordings/ \
  --output user_recordings_clean/ \
  --model denoiser/dns48

# 2. Slice into 3–10s segments (RVC training requirement)
python tools/slice_audio.py \
  --input user_recordings_clean/ \
  --output sliced/ \
  --min-length 3 \
  --max-length 10 \
  --silence-threshold -40

# 3. Verify segment count (need at least 100 segments)
ls sliced/ | wc -l
```

### Training command

RVC training runs via the `train_rvc.py` script which wraps the RVC v2 training pipeline:

```bash
python train_rvc.py \
  --voice-model-id {voice_model_id} \
  --dataset sliced/ \
  --output-dir checkpoints/voice/{voice_model_id} \
  --pitch-extraction crepe \
  --f0-method harvest \
  --total-epoch 200 \
  --save-every-epoch 50 \
  --batch-size 8 \
  --sample-rate 44100

# Build FAISS index (retrieval component — run after training)
python tools/build_rvc_index.py \
  --checkpoint checkpoints/voice/{voice_model_id}/G_200.pth \
  --output checkpoints/voice/{voice_model_id}/added_IVF256_Flat_nprobe_1.index
```

This is also what runs when a user uploads a voice model via the API — the `gbedu-worker` Celery task calls this script on the GPU node.

### Evaluation

```bash
# Convert a held-out vocal sample with the new model
python tools/test_rvc_conversion.py \
  --model checkpoints/voice/{voice_model_id}/G_200.pth \
  --index checkpoints/voice/{voice_model_id}/added_IVF256_Flat_nprobe_1.index \
  --input test_vocal.wav \
  --output converted_test.wav \
  --pitch-shift 0

# Listen to converted_test.wav — check for:
# - Voice similarity to target speaker
# - Absence of artefacts (metallic, robotic, pitch glitches)
# - Natural prosody preserved
```

Automated evaluation:
```bash
python evaluate_rvc.py \
  --model checkpoints/voice/{voice_model_id}/G_200.pth \
  --test-set data/rvc_eval/ \
  --output evals/voice/{voice_model_id}.json
```

Metrics: speaker cosine similarity (target > 0.85 using resemblyzer), PESQ score (target > 3.0).

### Upload

```bash
aws s3 cp checkpoints/voice/{voice_model_id}/G_200.pth \
  s3://gbedu-models/voice/{voice_model_id}/model.pth \
  --endpoint-url https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com

aws s3 cp "checkpoints/voice/{voice_model_id}/added_IVF256_Flat_nprobe_1.index" \
  s3://gbedu-models/voice/{voice_model_id}/index.faiss \
  --endpoint-url https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com

# Update voice_models table: set model_path, mark status=ready
uv run python scripts/activate_voice_model.py --voice-model-id {voice_model_id}
```

---

## Deploying updated models without downtime

### The pattern

The ML service supports hot-swapping model weights via the `/v1/admin/reload-model` endpoint (internal only, API-key gated). The sequence:

1. Upload new weights to R2.
2. Call `/v1/admin/reload-model` on the ML service — it loads the new weights alongside the old, switches the pointer atomically, then unloads the old weights.
3. Zero requests are dropped. The switchover takes 2–10 seconds on GPU.
4. If the reload fails (OOM, corrupt weights), the endpoint returns an error and the old weights remain active.

```bash
# Trigger hot reload on staging
curl -X POST https://ml.gbedu.com/v1/admin/reload-model \
  -H "X-ML-Admin-Key: $ML_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model_type": "ace_step_lora",
    "weights_path": "s3://gbedu-models/ace-step/v1.2/lora.safetensors"
  }'
```

Response `200` (success):
```json
{"status": "reloaded", "model_type": "ace_step_lora", "version": "v1.2", "load_time_s": 4.2}
```

Response `500` (failure — old weights still active):
```json
{"status": "failed", "error": "CUDA out of memory while loading new weights", "active_version": "v1.1"}
```

### GPU memory budget

Keep this in mind when scheduling model updates:

| Model | VRAM | Notes |
|-------|------|-------|
| ACE-Step 1.5 base | ~10GB | Always resident |
| ACE-Step LoRA | ~0.1GB | Swappable |
| Llama-3 8B (4-bit quant) | ~6GB | Always resident |
| RVC v2 (one voice) | ~0.5GB | Loaded per-request, cached for 30s |

Total baseline: ~16.1GB. An A100 80GB has ample headroom. An A10G (24GB) is the minimum viable GPU — runs with exactly one concurrent generation, no headroom for hot-swapping. On A10G, use the pod restart approach (see RUNBOOKS.md) instead of hot-swap.

---

## Versioning convention

Model versions follow `v{major}.{minor}`:
- Increment `major` when the base model changes (e.g. ACE-Step 1.5 → ACE-Step 2.0).
- Increment `minor` for LoRA/SFT updates on the same base.

Always keep the previous version's weights in R2 for at least 30 days for rollback.

The active version for each model type is stored in the ML service config (env var). Historical versions are discoverable from R2 listing.
