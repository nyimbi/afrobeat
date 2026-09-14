# Yue2-3B-GGUF Integration Report

**Last verified against code:** 2026-09-14

---

## 1. Status

| Layer | Status |
|-------|--------|
| Backend (ML pipeline) | ✅ Fully wired |
| API → worker → ML chain | ✅ Fully wired |
| Studio UI (progress, lyrics, voices, takes) | ✅ Wired + tested |
| Automated coverage | ✅ 770 backend + 38 frontend tests green |

---

## 2. Model configuration (verified)

Source: `services/ml/src/gbedu_ml/config.py`

| Setting | Value |
|---------|-------|
| HuggingFace repo | `audio-cpp/Yue2-3B-GGUF` |
| Main weights | `yue2-3b-q8_0.gguf` (bf16/q8_0/q4_0 variants supported) |
| VAE decoder | `yue2-vae-f16.gguf` (f32/f16 variants supported) |
| Runtime | `audiocpp_cli` (audio.cpp), invoked as a subprocess |
| Threads | 8 (configurable 1–64) |
| Flow-matching steps | 8 (configurable 1–64) |
| Symbolic planning (CoT) | `full` (melody+chords); `melody` or `off` |
| Invocation timeout | 600 s (configurable 60–1800) |

`YuE2Model` (`services/ml/src/gbedu_ml/models/yue2.py`) shells out to
`audiocpp_cli --task gen --family yue2 ...`, writes a WAV to the output dir,
then trims/pads it to the requested duration with ffmpeg. It accepts
`lyrics`, `seed`, `cot`, `num_inference_steps`, `style_tags`, and `abc`
(optional ABC notation) as kwargs.

---

## 3. Generation chain

```
POST /api/v1/generations
  → GenerationService.submit_job  (quota check, job row, metadata_)
  → Celery run_generation_pipeline(job_id)
  → worker reads job.metadata_ allowlist → POST ML /generate
  → ML GenerationPipeline: music + Llama-3 lyrics in parallel
  → MusicGenerator fallback chain: ACE-Step → YuE2 → Stable Audio → YuE
  → optional RVC v2 voice conversion (voice_model_id)
  → gbedu-audio DSP → R2 upload → Track row → job complete
```

- Lyrics come from Llama-3 8B unless the request carries user `lyrics`,
  in which case the LLM is skipped and the supplied text is shaped into
  the same `LyricResult` (`parse_sections`).
- `seed` is forwarded through `generate_safe(**kwargs)` to every model;
  YuE2 defaults to `0` when unset.
- Progress flows via Redis pub/sub mirrored into `job.progress_percent`;
  the frontend polls `GET /api/v1/generations/{id}` every 2 s.

---

## 4. Request options

`POST /api/v1/generations` accepts (camelCase):

| Field | Notes |
|-------|-------|
| `prompt`, `subGenre`, `language` | required |
| `energyLevel`, `durationSeconds`, `bpm`, `voiceModelId` | optional |
| `lyrics` (1–5000 chars) | user-supplied lyrics; skips AI lyric writing |
| `seed` (0–2³¹−1) | reproducible/varied takes |

`POST /api/v1/lyrics/draft` returns lyric-only drafts (no audio, no quota
deduction, rate-limited) for pre-generation exploration.

Renditions are N jobs with distinct seeds (1 credit each); the studio
submits and compares up to 3 takes.

Voice cloning is RVC v2: `POST /voice-models/upload` (Pro+) trains from
samples; ready models are selectable per generation via `voiceModelId`.

---

## 5. Frontend integration

`services/web/src/app/(studio)/studio/page.tsx` wires:

- `GenerationProgress` — 5 steps (Queue → Compose → Master → Upload → Done),
  ETA display, distinct failed/cancelled states.
- `LyricsStage` — Describe (AI draft → edit) / Write / Surprise-me modes.
- `VoiceSelector` — AI / preset / cloned voices, training progress, delete.
- Takes panel — per-rendition progress with seed labels and A/B listening.
- `useGenerationStore` — submit, immediate + interval polling, stale-job
  guard, per-rendition orchestration, cancel/reset.

Coverage: vitest + Testing Library (`npm test`, 38 tests) over the lyrics
stage, the generation store, and the progress component; `tsc`, `eslint`,
and `next build` clean.

---

## 6. Key files

| File | Role |
|------|------|
| `services/ml/src/gbedu_ml/models/yue2.py` | YuE2 subprocess inference |
| `services/ml/src/gbedu_ml/inference/music_generator.py` | ACE-Step → YuE2 → Stable → YuE chain |
| `services/ml/src/gbedu_ml/inference/lyric_generator.py` | Llama-3 lyrics + section parsing |
| `services/ml/src/gbedu_ml/pipeline.py` | End-to-end ML orchestration |
| `services/ml/src/gbedu_ml/main.py` | `/generate`, `/lyrics/draft` endpoints |
| `services/api/src/gbedu_api/routers/generations.py` | Submit/status/cancel/list |
| `services/api/src/gbedu_api/routers/lyrics.py` | Lyric drafts |
| `services/api/src/gbedu_api/routers/voice_models.py` | Clone library + training |
| `services/worker/src/gbedu_worker/pipelines/generation_pipeline.py` | Job lifecycle orchestration |
| `services/web/src/components/studio/lyrics-stage.tsx` | Explorer lyrics UI |
| `services/web/src/components/studio/voice-selector.tsx` | Voice library UI |
