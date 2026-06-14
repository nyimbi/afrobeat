# Gbẹdu — Architecture

## System diagram

```
                        ┌─────────────────────────────────────────────────────┐
                        │                   Cloudflare CDN                     │
                        │         (edge caching for audio files + web)         │
                        └────────────────────┬────────────────────────────────┘
                                             │
                 ┌───────────────────────────┼───────────────────────────┐
                 │                           │                           │
          ┌──────▼──────┐            ┌───────▼──────┐           ┌───────▼──────┐
          │  web (:3000) │            │  api (:8000) │           │  Cloudflare  │
          │  Next.js 14  │◄──────────►│  FastAPI     │           │  R2 (audio   │
          │              │  REST/JSON │              │           │  storage)    │
          └─────────────┘            └──────┬───────┘           └─────────────┘
                                            │                          ▲
                                            │ SQLAlchemy async         │ boto3 S3
                        ┌───────────────────┼──────────────────┐       │
                        │                   │                  │       │
                 ┌──────▼──────┐    ┌───────▼──────┐   ┌──────▼──────┐
                 │  postgres   │    │    redis      │   │   worker    │
                 │  (:5432)    │    │  (:6379)      │   │  Celery     │
                 │  Primary    │    │  broker/cache │   │  (:—)       │
                 │  data store │    │               │   └──────┬──────┘
                 └─────────────┘    └───────────────┘          │
                                           ▲                    │ HTTP
                                           │ results            │
                                    ┌──────┴──────┐     ┌───────▼──────┐
                                    │   worker    │     │  ml (:8001)  │
                                    │  (reads     │     │  FastAPI     │
                                    │   results)  │     │  ACE-Step    │
                                    └─────────────┘     │  Llama-3 8B  │
                                                        │  RVC v2      │
                                                        └──────────────┘

Observability sidecar (all services emit to):
  ┌───────────────────────────────────────────────────────────────────┐
  │  OpenTelemetry Collector → Tempo (traces)                         │
  │  Prometheus scrape → Grafana (metrics)                            │
  │  structlog JSON → Loki (logs, in prod via Grafana Loki sidecar)   │
  └───────────────────────────────────────────────────────────────────┘
```

---

## Service responsibilities

### `api` (gbedu-api) — Port 8000

FastAPI service. Owns the HTTP surface area: authentication, track CRUD, generation requests, payment flows, and marketplace. Contains no ML inference and no heavy computation — anything that takes more than ~200ms is dispatched as a Celery task.

Key responsibilities:
- JWT issuance and validation (access + refresh token rotation)
- Google OAuth2 callback handling
- Stripe + Paystack webhook ingestion
- Enqueueing generation tasks to Celery
- Polling generation status from Redis/Postgres
- Serving signed R2 URLs for audio downloads
- Rate limiting (slowapi, per-user limits stored in Redis)
- OpenTelemetry auto-instrumentation (FastAPI + SQLAlchemy + httpx)

### `ml` (gbedu-ml) — Port 8001

FastAPI inference service. Private — not exposed to the internet, called only by the `worker` service over internal DNS. Owns all model loading, GPU allocation, and inference logic.

Key responsibilities:
- ACE-Step 1.5 music generation (conditioned on genre, BPM, key, mood, instrument tags)
- Llama-3 8B SFT lyrics generation (Afrobeats-style, language-conditioned: English, Yoruba, Pidgin, Igbo)
- RVC v2 voice conversion (apply artist voice model to generated vocals)
- LoRA weight hot-swapping without service restart
- Model health reporting (loaded models, GPU memory, queue depth)

### `worker` (gbedu-worker) — Celery

Celery application consuming from Redis broker. Runs the full generation pipeline as a sequence of chained tasks. All tasks are idempotent and use `acks_late=True` — a task is only acknowledged after successful completion to prevent silent loss on worker crash.

Task queues:
- `generation` — core audio generation pipeline (concurrency = 1 per GPU worker)
- `postprocess` — audio analysis, mastering, stem separation (CPU-bound)
- `email` — transactional email (high concurrency, I/O-bound)
- `webhook` — Stripe/Paystack webhook retry delivery

### `web` (gbedu-web) — Port 3000

Next.js 14 frontend with App Router. Server components for SEO-critical pages (landing, marketplace listings). Client components for interactive studio UI (track editor, waveform player, generation wizard).

State: Zustand for client state, TanStack Query for server state with optimistic updates.

### `postgres` — Port 5432

PostgreSQL 16. All persistent application data. Single primary in development; production uses a managed PG17 instance (Contabo vmi3169165) with pgBackRest for PITR.

### `redis` — Port 6379

Three logical databases:
- `db=0` — application cache (user sessions, rate limit counters, model availability)
- `db=1` — Celery broker (task queue)
- `db=2` — Celery result backend (task status + results, TTL 24h)

---

## Data flow — track generation (step by step)

```
1. User submits GenerationRequest via POST /api/v1/generations
   Fields: genre, bpm, key, mood, instruments[], lyrics_prompt, voice_model_id

2. api validates request, checks user credits, creates Generation row (status=PENDING)
   Returns: {generation_id, status: "pending", estimated_seconds: 120}

3. api enqueues Celery task: generate_audio_task.delay(generation_id)

4. worker picks up task from "generation" queue
   Updates Generation.status = PROCESSING in Postgres
   Stores progress key in Redis: task:generate:{generation_id} = {step: "lyrics", pct: 0}

5. worker → POST http://ml:8001/v1/lyrics
   Payload: {prompt, genre, mood, language}
   ml runs Llama-3 8B inference (typically 5-15s)
   Returns: {lyrics: "..."}

6. worker updates progress: {step: "music", pct: 20}
   worker → POST http://ml:8001/v1/generate
   Payload: {genre, bpm, key, instruments, lyrics, duration_seconds}
   ml runs ACE-Step 1.5 inference (typically 60-120s on GPU)
   Returns: {audio_url: "file:///tmp/gen_xxx.wav"}

7. If voice_model_id specified:
   worker updates progress: {step: "voice", pct: 75}
   worker → POST http://ml:8001/v1/voice-convert
   Payload: {audio_path, voice_model_id}
   ml applies RVC v2 (typically 10-30s)
   Returns: {audio_url: "file:///tmp/voice_xxx.wav"}

8. worker runs gbedu_audio pipeline:
   - analysis: BPM verification, key detection, loudness measurement
   - mastering: loudness normalization to -14 LUFS, true peak -1 dBTP
   - conversion: wav → mp3 (320kbps) + wav (lossless)
   Progress: {step: "mastering", pct: 90}

9. worker uploads both files to R2:
   - gbedu-audio/{user_id}/{generation_id}/track.mp3
   - gbedu-audio/{user_id}/{generation_id}/track.wav
   Returns signed URLs valid 7 days (mp3) / 1 day (wav)

10. worker updates Generation row:
    status=COMPLETED, mp3_url=..., wav_url=..., duration_ms=..., bpm=..., key=...
    Deletes Redis progress key.

11. worker sends email notification to user (gbedu.email queue)

12. Frontend polls GET /api/v1/generations/{id} every 3s
    api reads Generation.status from Postgres
    On COMPLETED: returns mp3_url for immediate playback
    Web player begins streaming from Cloudflare CDN (R2 public bucket)
```

---

## Database schema overview

All tables use UUID7 string primary keys. `created_at` and `updated_at` are set via SQLAlchemy server defaults. Soft deletes use `deleted_at IS NULL` filters rather than hard DELETE.

```
users
  id (pk, uuid7)
  email (unique, not null)
  display_name
  avatar_url
  hashed_password (nullable — null for OAuth users)
  google_id (nullable, unique)
  subscription_tier  (free | creator | pro | label)
  credits_remaining  (int, default 10)
  created_at, updated_at, deleted_at

tracks
  id (pk, uuid7)
  owner_id (fk users.id)
  title, description
  genre, bpm, key, mood
  duration_ms
  mp3_url, wav_url, cover_url
  is_public (bool, default false)
  is_marketplace_listed (bool, default false)
  price_usd (numeric, nullable)
  play_count, download_count, like_count
  created_at, updated_at, deleted_at

generations
  id (pk, uuid7)
  owner_id (fk users.id)
  track_id (fk tracks.id, nullable — set on completion)
  status  (pending | processing | completed | failed)
  genre, bpm, key, mood
  instruments (jsonb array)
  lyrics_prompt
  voice_model_id (fk voice_models.id, nullable)
  error_message (nullable)
  credits_used (int)
  started_at, completed_at
  created_at, updated_at

voice_models
  id (pk, uuid7)
  owner_id (fk users.id, nullable — null = system model)
  name, description
  model_path (R2 key)
  sample_audio_url
  is_public (bool)
  usage_count
  created_at, updated_at, deleted_at

payments
  id (pk, uuid7)
  user_id (fk users.id)
  provider  (stripe | paystack)
  provider_payment_id (unique)
  amount_cents (int)
  currency (char(3))
  status  (pending | succeeded | failed | refunded)
  plan_tier (creator | pro | label | credits)
  credits_granted (int, nullable)
  created_at, updated_at

marketplace_purchases
  id (pk, uuid7)
  track_id (fk tracks.id)
  buyer_id (fk users.id)
  seller_id (fk users.id)
  payment_id (fk payments.id)
  license_type  (personal | commercial)
  created_at
```

---

## API versioning strategy

All API paths are prefixed `/api/v1/`. When breaking changes are needed:

1. Add the new behaviour under `/api/v2/` alongside the existing `/api/v1/` route.
2. Deprecate the v1 route with a `Deprecation` response header and a sunset date.
3. Keep v1 functional for at least 90 days after the v2 equivalent ships.
4. Remove v1 only after all clients (web, mobile, partner integrations) have migrated.

Non-breaking additive changes (new optional fields, new endpoints) ship directly to the current version with no versioning ceremony.

---

## Deployment topology

### Local development

Single `docker compose up` brings up all eight containers on a shared bridge network. LocalStack mocks R2. No GPU required — ML service falls back to CPU (slow but functional).

### Staging (Kubernetes)

Deployed to the `staging-cluster` context on Contabo vmi3146214 (`109.123.244.151`). All four application services run as single-replica Deployments. No GPU — ML service CPU mode, generation disabled for most tests. Triggered automatically on every push to `main`.

### Production (Kubernetes)

Deployed to `prod-cluster`. Target topology:

| Deployment | Replicas | Resources |
|-----------|----------|-----------|
| `gbedu-api` | 2 | 1 CPU, 1Gi RAM |
| `gbedu-worker` | 1 | 2 CPU, 4Gi RAM (per GPU node) |
| `gbedu-ml` | 1 | 4 CPU, 16Gi RAM + 1× GPU |
| `gbedu-web` | 2 | 0.5 CPU, 512Mi RAM |

Postgres: managed instance on vmi3169165 (PG17, pgBackRest for PITR).
Redis: same server, single-instance with `appendonly yes`.
Audio storage: Cloudflare R2 (zero egress cost for CDN delivery).

Ingress: Traefik on vmi3169158 terminates TLS, routes to cluster.

---

## Failure modes and recovery

| Failure | Detection | Automatic recovery | Manual action |
|---------|-----------|-------------------|---------------|
| API pod crash | Kubernetes liveness probe fails | Pod restarted by kubelet | Check logs if restart loop |
| Worker crash mid-task | `acks_late=True` — task requeued | Task retried up to 3× | Check DLQ for dead tasks |
| ML service OOM (GPU) | Kubernetes OOMKilled event | Pod restarted | See runbook: GPU OOM recovery |
| Postgres connection exhaustion | SQLAlchemy pool timeout errors | Connection pool backoff + retry | See runbook: Postgres |
| Redis unavailable | Celery connection error | Celery retries with exponential backoff | Restart Redis pod |
| R2 upload failure | tenacity retry (3×) | Task retried | Check R2 bucket permissions |
| Stripe webhook replay | idempotency key check in DB | Duplicate silently dropped | None |
| Generation timeout (>10 min) | Celery `time_limit=600` | Task marked FAILED, user notified | Check ML service logs |
| Deploy rollout failure | `kubectl rollout status` non-zero | Automatic rollback via `kubectl rollout undo` | See runbook: Rollback |
