# Gbẹdu FMEA — Failure Mode and Effects Analysis

**Version:** 1.0  
**Date:** 2026-06-15  
**Author:** Platform Engineering  
**Status:** Living document — update whenever RPN > 200 items are remediated or new components are added.

---

## 1. Scope and SLO Targets

### In Scope

All production components of the Gbẹdu platform:

- `gbedu-api` — FastAPI service on port 8000 (routers: `auth`, `users`, `generations`, `tracks`, `payments`, `marketplace`, `voice_models`)
- `gbedu-ml` — FastAPI ML inference service on port 8001 (ACE-Step 1.5 → Stable Audio 3.0 → YuE fallback chain)
- `gbedu-worker` — Celery task queue (generation pipeline: ML inference → DSP → R2 upload → DB write)
- `gbedu-web` — Next.js 14 frontend on port 3000
- PostgreSQL 16 — primary relational store (`pool_size=20`, `max_overflow=40`, `pool_recycle=3600s`)
- Redis 7 — Celery broker (db 1), results backend (db 2), API cache (db 0)
- Cloudflare R2 — audio file storage (bucket: `gbedu-audio`)
- Kubernetes deployment — HPA, PDB, RBAC, namespaced secrets

### Out of Scope

Cloudflare CDN edge layer, DNS propagation failures, upstream HuggingFace Hub outages during initial model downloads, end-user device/browser failures.

### SLO Targets

| SLO | Target | Error Budget (30-day) |
|-----|--------|-----------------------|
| API availability | 99.9% | 43.2 minutes |
| Generation submission (p95) | < 2 seconds | — |
| Generation completion (p95) | < 5 minutes | — |
| API p99 latency | < 500 ms | — |
| Payment webhook processing | < 10 seconds | — |

### RPN Scoring Method

- **Severity (S):** 1 (negligible) → 10 (total service loss / data loss / financial loss)
- **Probability (P):** 1 (near impossible) → 10 (happens multiple times per week in production)
- **Detectability (D):** 1 (immediately obvious, auto-alerted) → 10 (silent failure, no current detection)
- **RPN = S × P × D** — anything above 100 requires a remediation item; above 200 is P0.

---

## 2. FMEA Table

| ID | Component | Failure Mode | Effect on System | S | P | D | RPN | Current Mitigation | Recommended Action |
|----|-----------|--------------|-----------------|---|---|---|-----|--------------------|--------------------|
| F-01 | PostgreSQL / SQLAlchemy | DB connection pool exhaustion (`pool_size=20`, `max_overflow=40` → hard cap 60 connections) | All API requests requiring DB access queue behind the pool. Requests exceeding asyncpg's internal wait timeout raise `TimeoutError`, returning 500 to users. Celery tasks also share the DB; generation pipeline stalls. | 9 | 4 | 3 | **108** | `pool_pre_ping=True` evicts dead connections. `pool_recycle=3600s` prevents stale connections. structlog emits pool events. | Add `db_pool_checkedout` Prometheus gauge. Alert at > 35 (58%). Profile slow queries holding connections. Consider PgBouncer in transaction mode between API pods and Postgres to multiply effective concurrency. |
| F-02 | Redis 7 | Redis unavailability (pod OOM kill, network partition, node failure) | Celery broker (db 1) unreachable: no new tasks enqueued, no existing tasks picked up. Result backend (db 2) unavailable: task status polling returns errors. API cache (db 0) miss forces all reads to DB. SlowAPI rate limiter loses state (Redis-backed), potentially allowing burst traffic directly to API. | 9 | 3 | 2 | **54** | `acks_late=True` + `reject_on_worker_lost=True` ensure in-flight tasks are not lost. Redis deployed as single-node in current config. | Deploy Redis Sentinel or Redis Cluster. Configure `CELERY_BROKER_TRANSPORT_OPTIONS` with `visibility_timeout` and connection retry policy. Implement Redis health check in `/api/v1/health` endpoint. |
| F-03 | Celery worker | Worker process crash mid-generation (OOM, segfault from librosa/demucs, uncaught exception in orchestrator) | In-flight generation job is lost from the in-memory prefetch queue. With `acks_late=True` and `reject_on_worker_lost=True`, the message is requeued to `default`. Generation job re-runs from the beginning (ML inference + DSP + upload all re-executed). User waits up to `_RETRY_COUNTDOWN[0]` = 30 seconds before retry begins. If the crash is deterministic (same input triggers same crash), the task will exhaust all 3 retries (30s + 90s + 270s = 390s delay) then route to `gbedu.dlq`. | 7 | 4 | 2 | **56** | `acks_late=True`, `reject_on_worker_lost=True`, DLQ routing in `_route_to_dlq()`. `soft_time_limit=720s`, `time_limit=780s`. Structured exception logging with full `traceback`. | Each pipeline stage should checkpoint its output status to DB (`STAGE_ML_DONE`, `STAGE_DSP_DONE`, `STAGE_UPLOADED`) so retries resume from last completed stage rather than re-running from scratch. Currently `GenerationPipelineOrchestrator.run()` has no mid-pipeline checkpointing visible in the task wrapper. |
| F-04 | ML service (gbedu-ml) | GPU/MPS out-of-memory during ACE-Step 1.5 inference (large batch, long duration request) | `torch.cuda.OutOfMemoryError` raised inside `model.generate_safe()`. `MusicGenerator.generate()` catches it as a generic `Exception`, records the failure, and falls through to Stable Audio 3.0. If all three models OOM (unlikely unless GPU is shared with other processes), raises `GenerationError`. Celery task receives `MLServiceError` (if the ML service returns 5xx) and schedules a retry. GPU memory fragmentation may persist until pod restart, causing cascading OOM for subsequent requests. | 8 | 5 | 3 | **120** | Three-model fallback chain: ACE-Step → Stable Audio → YuE. `circuit_failure_threshold=5`, `circuit_recovery_timeout=60s`. | Add CUDA memory pre-check before inference: reject request if `torch.cuda.memory_reserved() / torch.cuda.get_device_properties(0).total_memory > 0.85`. Implement per-request GPU memory limit with `torch.cuda.set_per_process_memory_fraction()`. Alert on `ml_gpu_memory_used_pct > 80`. |
| F-05 | ML service (gbedu-ml) | All three circuit breakers simultaneously open (ACE-Step + Stable Audio + YuE all tripped) | `MusicGenerator.generate()` skips all three models (checking `model.circuit_open` before each attempt), immediately raises `GenerationError("All music generation models failed")`. Every generation request fails instantly. Celery worker marks tasks as `FAILURE` after exhausting retries. DLQ backlog grows. Users see generation failure notifications. Revenue impact: direct if subscription tiers are metered on completions. | 10 | 2 | 2 | **40** | Per-model circuit breakers with `failure_threshold=5`, `recovery_timeout=60s`. Separate breaker state per model means one model's failures don't directly trip others. structlog warning on each skip. | Add a `/api/v1/health` check that aggregates all three circuit breaker states. If all three are open, return HTTP 503 with `Retry-After` header. Expose `ml_circuit_open{model="ace_step|stable_audio|yue"}` Prometheus counter. Alert: CRITICAL if count of open circuits >= 2. |
| F-06 | ML service (gbedu-ml) | ACE-Step circuit breaker stuck open past `recovery_timeout=60s` (half-open probe also fails) | ACE-Step, the highest-quality model, is permanently bypassed. All traffic falls to Stable Audio 3.0 or YuE. Output quality degrades noticeably — Stable Audio 3.0 is less fine-tuned for Afrobeats; YuE is a last-resort model. No user-visible error, but quality SLA is violated silently. | 6 | 3 | 7 | **126** | Circuit breaker implements half-open recovery probe. `recovery_timeout=60s` configured in `MLSettings`. | Expose `ml_model_active{model="..."}` metric showing which model is currently serving. Alert on Slack (non-paging) if ACE-Step circuit has been open for > 5 minutes. Implement admin endpoint `POST /api/v1/admin/ml/reset-circuit?model=ace_step` (auth-gated, staff role only). |
| F-07 | Cloudflare R2 | Audio upload failure after successful ML generation and DSP processing | `UploadError` raised in the upload stage. Celery task catches it as a `_RETRYABLE_EXCEPTIONS` member and schedules retry with countdown `[30, 90, 270]` seconds. Three retries means up to 390 seconds of additional wait, then DLQ. The generated audio file exists on the worker pod's ephemeral local disk (`audio_path` from `MusicGenerationResult`). If the pod is evicted or OOM-killed between retries, the local file is gone and the retry will fail with a missing-file error (which is not retryable), masking the original R2 failure. | 7 | 3 | 3 | **63** | `UploadError` classified as retryable. Exponential backoff retry. DLQ on exhaustion. | Store generated audio to a shared volume or S3-compatible staging bucket before attempting R2 upload, so retries have access to the file regardless of pod lifecycle. Alternatively, upload immediately from ML service to R2 and pass the URL to the worker, removing the local-file dependency. |
| F-08 | Payments (Stripe) | Webhook duplicate delivery (Stripe retries on non-2xx, or network blip causes double delivery) | Payment event processed twice. Depending on idempotency implementation in `payments` router, this could result in double credit grant (user gets 2x subscription credits), double email, or double DB record. | 8 | 5 | 4 | **160** | Stripe sends `stripe-signature` header for HMAC-SHA256 verification. `STRIPE_WEBHOOK_SECRET` configured in `StripeSettings`. | Implement webhook idempotency table: `webhook_events(event_id TEXT PRIMARY KEY, processed_at TIMESTAMPTZ)`. On receipt, `INSERT OR IGNORE` by `event.id`. Process only if insert succeeded. Add unique index. This is a common Stripe integration pattern and is not implemented based on current code review. |
| F-09 | Payments (Paystack) | HMAC validation failure on Paystack webhook (misconfigured `PAYSTACK_SECRET_KEY`, rotated key, or spoofed request) | Paystack webhook rejected, payment not recorded in DB. Nigerian users' subscriptions not activated. Support load increases. If the failure is systematic (e.g., after a key rotation), all Paystack events are silently dropped. | 7 | 3 | 6 | **126** | `PAYSTACK_SECRET_KEY` configured in `PaystackSettings`. HMAC computed against `x-paystack-signature` header. | Log every HMAC validation failure with the source IP and raw payload hash (not payload body — PII concern). Alert on > 3 consecutive Paystack HMAC failures within 60 seconds (could indicate key rotation or spoofing). Add `paystack_webhook_hmac_failures_total` counter metric. |
| F-10 | Auth (gbedu-api) | JWT secret key compromise (`JWT_SECRET_KEY`, default `"change-this-in-production"`) | Attacker can forge arbitrary JWT tokens, impersonate any user including admin accounts. Full account takeover across all users who have active sessions. In the worst case, attacker can access voice model data, payment information, and private tracks of all users. | 10 | 2 | 8 | **160** | `JWTSettings.secret_key` loaded from `JWT_SECRET_KEY` env var. Kubernetes Secrets mount in production. HTTPS-only in production (`HTTPSRedirectMiddleware`). Access token TTL: `ACCESS_TOKEN_EXPIRE_MINUTES=30`. Refresh token TTL: `REFRESH_TOKEN_EXPIRE_DAYS=30`. | (1) Rotate to RS256 (asymmetric): sign with private key, verify with public key — compromise of the verification key does not enable token forgery. (2) Add JWT `jti` (JWT ID) claim and a Redis-backed token revocation list checked on every request. (3) Alert on > 50 failed JWT decode attempts per minute per IP (brute-force indicator). (4) Scan for default value `"change-this-in-production"` in CI: `if JWT_SECRET_KEY == "change-this-in-production": raise RuntimeError`. |
| F-11 | Database / Alembic | Migration failure on production deploy (`alembic upgrade head` fails mid-migration) | If migration is non-transactional (e.g., `CREATE INDEX CONCURRENTLY`, which cannot run inside a transaction), Alembic's `alembic_version` table may not be updated, leaving DB in a partial state. New API pods start against partially-migrated schema, causing SQLAlchemy `OperationalError` (missing column/table). Rollback requires manual `alembic downgrade`. | 9 | 3 | 4 | **108** | `RUNBOOKS.md` documents "Database migration procedure". Every migration must implement `downgrade()`. Two-phase column removal policy documented in `CLAUDE.md`. | (1) Run `alembic upgrade --sql | review` in CI before applying to prod. (2) Run migrations as a Kubernetes pre-upgrade Job (not inside the app container startup) with a timeout. (3) Store last-known-good migration ID in a config map; auto-rollback if the Job fails. (4) `CREATE INDEX CONCURRENTLY` requires a separate migration file run outside a transaction — document this explicitly in migration template. |
| F-12 | Celery worker / DSP | Audio DSP pipeline crash: librosa or demucs OOM during stem separation on a long track (> 4 minutes) | `MemoryError` or OS kill (`SIGKILL`) inside `gbedu_audio` pipeline functions. If `SIGKILL`, Celery cannot catch it — the worker process dies, `reject_on_worker_lost=True` requeues the message. If `MemoryError`, Python catches it but the state may be corrupt; the task retries the full pipeline including re-running ML inference. Very long tracks (8+ minutes at 44.1 kHz stereo = ~84MB raw) can exhaust a 4GB worker memory limit. | 7 | 4 | 3 | **84** | `reject_on_worker_lost=True` handles hard kills. `soft_time_limit=720s` kills stuck tasks cleanly (raises `SoftTimeLimitExceeded`). Retry logic handles `MemoryError` if it propagates. | Set explicit maximum track duration in generation request schema (`max_duration_seconds=480`). Run DSP in a subprocess (via `asyncio.create_subprocess_exec`) with its own memory limit (`resource.setrlimit(RLIMIT_AS, ...)`) so DSP OOM kills only the subprocess, not the Celery worker. |
| F-13 | ML service (gbedu-ml) | RVC voice conversion crash (model weight incompatibility, CUDA kernel mismatch, or corrupt speaker embedding) | `voice_models` router endpoint returns 500. User's custom voice model fails to apply. Base generation still succeeds (RVC is post-processing, applied after `MusicGenerator.generate()`). If RVC crash is deterministic for a specific voice model file, the user cannot use that voice model until the file is replaced. | 5 | 4 | 3 | **60** | Structured error logging. Exception caught and re-raised as `GbeduError` via error handler. | Validate RVC model files at upload time (checksum + format check). Store per-voice-model health status in DB (`voice_models.last_error`, `voice_models.error_count`). Auto-disable voice models with > 3 consecutive failures and notify the user. |
| F-14 | ML service (gbedu-ml) | Nigerian Pidgin / Yoruba LLM hallucination in `AfrobeatsPromptEngine.build_music_prompt()` | Lyrics or prompt generated for a Nigerian Pidgin or Yoruba-language request contains culturally inappropriate content, wrong language tokens, or nonsense text that degrades generation quality. Not a system failure, but a quality defect that affects brand reputation. If the hallucinated content violates content policy, it could result in track moderation removal or user reports. | 6 | 5 | 8 | **240** | `AfrobeatsPromptEngine` builds music prompts — assumed to have language-specific templates. | (1) Run automated evaluation on a held-out set of Yoruba/Pidgin prompts weekly; threshold on BLEU/chrF against reference translations. (2) Add content safety filter (LLM-based classifier) on generated prompts before passing to music model. (3) Human-in-the-loop review queue for first-generation from any user choosing a language other than English. Alert threshold: > 5% of Yoruba/Pidgin generations flagged by safety filter in a 24h window. |
| F-15 | Frontend (gbedu-web) | Next.js 14 hydration failure (server-rendered HTML diverges from client JS, e.g., timestamp formatting, random IDs, locale mismatch) | React throws hydration error in browser console. Component subtree re-renders from scratch on client, causing flash of unstyled content (FOUC). Generation status polling via `useEffect` may be delayed by the re-render. In worst case, if the hydration error is in the payment flow, the Stripe Elements iframe may not mount correctly, blocking payment submission. | 5 | 4 | 5 | **100** | Next.js 14 App Router with server components reduces hydration surface. Structured error boundaries (`error.tsx`) per route segment. | Audit all client components for non-deterministic rendering (dates formatted with `Date.toLocaleString()`, `Math.random()`, `crypto.randomUUID()` without stable seeds). Add `suppressHydrationWarning` only where necessary and document the justification. Run Playwright visual diff tests on critical paths (auth, payment, generation status). |
| F-16 | Kubernetes | Pod OOM kill (`SIGKILL`) during active payment flow (Stripe webhook processing or Paystack callback handling) | In-flight payment webhook HTTP handler is interrupted. The payment provider's server receives no 2xx response and retries the webhook. If idempotency is not implemented (see F-08), the retry processes the payment again. If idempotency is implemented, the retry is a no-op but the user may see a delayed subscription activation. | 8 | 3 | 4 | **96** | HPA scales pods based on CPU/memory. PDB prevents all pods from being evicted simultaneously. K8s `terminationGracePeriodSeconds` allows in-flight requests to complete. | Set `resources.requests.memory` and `resources.limits.memory` accurately on the `api` deployment (profile memory usage under load). Add `preStop` lifecycle hook with a short sleep (`sleep 5`) to allow load balancer to drain connections before SIGTERM. This is particularly important during rolling deployments. |
| F-17 | API (gbedu-api) | Rate limiter false positive: SlowAPI (Redis-backed) incorrectly blocks legitimate users | User receives HTTP 429 `Too Many Requests` despite being within their actual usage quota. Causes: Redis key TTL miscalculation, SlowAPI bug, clock skew between API pods, or aggressive limit configuration. Particularly damaging if it blocks payment submission or generation submission. | 6 | 3 | 5 | **90** | SlowAPI middleware with `_rate_limit_exceeded_handler`. Redis-backed state (`set_redis(redis)` in lifespan). | Log every 429 response with user ID, path, and current Redis key TTL. Expose `rate_limit_hit_total{path="..."}` metric. Review and document rate limits per endpoint in `docs/API.md`. Implement rate limit bypass for internal service-to-service calls (e.g., Celery callbacks). Add `RateLimit-Remaining` and `RateLimit-Reset` headers to all responses. |
| F-18 | PostgreSQL / asyncpg | asyncpg connection leak (session not closed due to unhandled exception escaping `async with get_async_session()` context manager) | Connections accumulate in IDLE state, consuming pool slots. Pool exhaustion (F-01) follows within minutes to hours depending on traffic. Since `pool_recycle=3600s`, leaked connections persist for up to 1 hour before recycling. `pool_pre_ping=True` only evicts dead server-side connections, not application-side idle connections. | 8 | 3 | 6 | **144** | `async with get_async_session() as session:` in `_run_pipeline()` ensures session closed on normal exit and on exceptions. FastAPI `get_db` dependency uses `yield` with try/finally. | Add Prometheus gauge tracking `db_pool_checkedout` (current checked-out connections), `db_pool_overflow` (overflow count), `db_pool_size`. Alert on `db_pool_checkedout > 35` (58% of hard cap). Periodically audit with `SELECT count(*), state FROM pg_stat_activity GROUP BY state` in a cron job that logs results. |
| F-19 | Celery worker | Task deserialization failure: malformed JSON payload in Celery message (e.g., `job_id` is None, missing field, type mismatch) | Celery raises `kombu.exceptions.DecodeError` or the task's `assert job_id, "job_id must not be empty"` assertion fails at line 51 of `generation.py`. This falls through to the bare `except Exception` branch, logs the error, and re-raises. Task is marked `FAILURE` without retry (assertion errors are not in `_RETRYABLE_EXCEPTIONS`). Message moves to dead-letter queue (if configured) or is dropped. The associated generation job in DB remains in `PENDING` state permanently. | 6 | 2 | 4 | **48** | `accept_content=["json"]` rejects non-JSON messages. `task_serializer="json"` enforces serialization. Assertion at task entry. | Add a `mark_job_failed()` call in the non-retryable `except Exception` branch in `generation.py` to transition the DB generation record from `PENDING` to `FAILED` with an error message. Currently the task fails but the DB record is never updated, leaving jobs permanently stuck in `PENDING`. |
| F-20 | Redis / API | Cache stampede on cold start: Redis restarts with empty cache, all API pods simultaneously hit PostgreSQL for the same cached queries (e.g., marketplace listings, featured tracks) | PostgreSQL receives N × (number of API pods) simultaneous queries for the same data. With HPA at 5 pods and 10 concurrent requests each, this is 50 simultaneous queries for `SELECT * FROM tracks WHERE featured = true`. Can cause DB CPU spike, pool exhaustion (F-01), and cascading slow responses across all endpoints. | 7 | 4 | 5 | **140** | `pool_pre_ping=True` handles reconnection. Structured logging on cache miss. | Implement probabilistic early expiry (PER algorithm) to prevent synchronized expiry. Add a distributed lock (Redis `SET NX PX`) per cache key: first waiter fetches from DB, others wait for the lock to release, then read from cache. Consider warming the cache via a startup script that pre-populates high-traffic keys after Redis restart. |

---

## 3. Fault Tree Analysis

Top-level failure event: **User submits a generation request and the track never arrives.**

```
[TOP] Track never arrives after generation submission
│
├─── [OR] Job never reaches the Celery queue
│         │
│         ├─── Redis broker (db 1) unreachable at submission time [F-02]
│         │         Celery producer in generations router cannot connect.
│         │         Task publish raises ConnectionError.
│         │         API returns 500 or 503 to client.
│         │
│         ├─── Celery task serialization failure
│         │         `job_id` not JSON-serializable (shouldn't happen — it's a str,
│         │         but a future refactor could introduce a UUID type).
│         │         `kombu.exceptions.EncodeError` raised at publish time.
│         │
│         └─── Rate limiter blocks generation submission endpoint [F-17]
│                   SlowAPI returns 429 before task is enqueued.
│                   Client must retry; if rate window is long, user gives up.
│
├─── [OR] Job is queued but no worker picks it up
│         │
│         ├─── All Celery workers are down (OOM kills, deployment rollout, crash loop)
│         │         Messages accumulate in `default` queue in Redis.
│         │         `worker_prefetch_multiplier=1` means no over-fetching,
│         │         but no consumer exists to drain the queue.
│         │
│         ├─── Worker is running but `default` queue is not being consumed
│         │         Misconfigured `queue` routing (task declares `queue="default"`,
│         │         worker started with `-Q high_priority` only).
│         │
│         └─── Task visibility_timeout exceeded before ack
│                   If task runs longer than `BROKER_TRANSPORT_OPTIONS.visibility_timeout`
│                   (default: 3600s for Redis transport), Celery re-delivers the message
│                   to another worker while the first is still running.
│                   With `acks_late=True`, the first worker acks on completion,
│                   but the second worker also picks up the message — double execution.
│
├─── [OR] Job is picked up but fails in the ML inference stage
│         │
│         ├─── ACE-Step circuit breaker open [F-06]
│         │         `model.circuit_open` is True. Model skipped.
│         │
│         ├─── ACE-Step OOM on GPU [F-04]
│         │         `torch.cuda.OutOfMemoryError` caught, model skipped.
│         │         Falls through to Stable Audio 3.0.
│         │
│         ├─── All three models fail / circuit open [F-05]
│         │         `GenerationError` raised from `MusicGenerator.generate()`.
│         │         Celery receives `MLServiceError` (wrapped by ml_client).
│         │         Retried 3× with 30s, 90s, 270s backoff.
│         │         After 3 retries: DLQ. Job is permanently FAILED.
│         │
│         └─── ML service pod OOM killed during inference
│                   `gbedu-ml` pod receives SIGKILL.
│                   HTTP connection from `ml_client` times out after `inference_timeout=300s`.
│                   `TimeoutError` classified as retryable — task retries.
│
├─── [OR] ML inference succeeds but job fails in DSP/upload stage
│         │
│         ├─── DSP pipeline OOM (librosa/demucs) [F-12]
│         │         Worker process killed. `reject_on_worker_lost=True` requeues.
│         │         Audio file on local disk may be corrupt or missing.
│         │         Retry re-runs from ML inference (no stage checkpointing [F-03]).
│         │
│         ├─── R2 upload failure [F-07]
│         │         `UploadError` raised. 3 retries with backoff.
│         │         If worker pod evicted between retries, local audio file gone.
│         │         Retry fails with FileNotFoundError (not retryable) → DLQ.
│         │
│         └─── R2 credentials expired / rotated
│                   `StorageClient` raises auth error (403 from R2).
│                   Not classified as retryable (not `UploadError`).
│                   Task marked FAILURE immediately, no retry.
│
├─── [OR] Pipeline completes but DB write fails
│         │
│         ├─── DB connection pool exhausted at commit time [F-01]
│         │         `async with get_async_session()` waits for pool slot.
│         │         Times out → `TimeoutError` → task retried.
│         │
│         ├─── asyncpg connection leak causes pool exhaustion [F-18]
│         │         Indirect cause; same outcome as above.
│         │
│         └─── Alembic migration left schema in partial state [F-11]
│                   `INSERT INTO generations` fails with `UndefinedColumn`
│                   if a migration added a NOT NULL column without a default.
│                   Task marked FAILURE. All generation DB writes fail until
│                   manual schema fix.
│
└─── [OR] Pipeline completes and DB write succeeds, but frontend never shows completion
          │
          ├─── Frontend polling WebSocket / SSE connection dropped
          │         Next.js client poll interval may be too infrequent.
          │         If generation completes between polls and the job status
          │         is not persisted accessibly, client never sees completion.
          │
          ├─── Next.js hydration failure blocks status component render [F-15]
          │         React hydration error causes component subtree unmount.
          │         Generation status widget not rendered; user sees loading state.
          │
          └─── Redis cache returns stale PENDING status after job completes [F-20]
                    If generation status is cached in Redis db 0 with a TTL
                    longer than the generation duration, the cache returns
                    `status=PENDING` even after the DB has `status=COMPLETED`.
                    User must wait for cache TTL expiry or hard-refresh.
```

---

## 4. Graceful Degradation Matrix

| Feature | Primary Dependency | Degraded State | User-Visible Impact | Auto-Recovery? |
|---------|-------------------|----------------|---------------------|----------------|
| **Song generation** | ACE-Step 1.5 (primary ML model) | Falls back to Stable Audio 3.0, then YuE via `MusicGenerator` fallback chain | Lower audio quality; Afrobeats-specific tuning less precise on fallback models. No user-visible error unless all three fail. | Yes — circuit breaker recovery at `circuit_recovery_timeout=60s` |
| **Song generation** | Celery worker pool | New generations queue in Redis; existing jobs in-flight continue if broker is up | Generation submission succeeds (HTTP 202), but completion may be delayed indefinitely. Frontend shows "Processing..." with no ETA. | Yes — when workers restart they drain the queue. Messages preserved in Redis. |
| **Song generation** | PostgreSQL | DB writes fail; ML inference may succeed but results cannot be persisted | Generations appear to process but never appear in user history. Audio files may be uploaded to R2 orphaned. | No — requires manual DB recovery. |
| **Voice models** | RVC v2 (voice conversion) | Generation completes without voice conversion; base Afrobeats audio is returned | User's custom voice is not applied to the track. Track is still listenable but lacks the requested voice characteristic. | Partial — per-model error tracking; auto-disable after 3 failures (recommended, F-13). |
| **Marketplace** | PostgreSQL + Redis cache | Cache miss forces direct DB reads; high DB load may slow marketplace listings | Marketplace browsing slows down (p95 latency degrades). No functional loss. | Yes — once DB load normalizes, cache repopulates. Cold-start stampede risk (F-20). |
| **Marketplace** | Cloudflare R2 (audio playback) | Track metadata renders but audio URLs return 4xx/5xx from R2 | Users can browse marketplace but cannot preview or download tracks. Revenue impact for sales. | Yes — R2 outages are typically < 30 minutes. No local fallback. |
| **Payments (Stripe)** | Stripe API + webhook | Webhook delivery failure; payment intent not confirmed | User's payment is charged by Stripe but subscription is not activated in Gbẹdu DB. Requires manual reconciliation or Stripe dashboard re-delivery. | Partial — Stripe retries webhooks for 72 hours. Idempotency table (recommended, F-08) makes retry safe. |
| **Payments (Paystack)** | Paystack API + webhook | HMAC validation failure drops event | Nigerian users' payments not recorded; subscription not activated. Silent failure. | No — Paystack has no built-in retry dashboard equivalent to Stripe. Requires manual reconciliation against Paystack transaction API. |
| **User auth** | Redis (JWT revocation list, if implemented) | Revoked tokens may remain valid until expiry (`ACCESS_TOKEN_EXPIRE_MINUTES=30`) | Logged-out users or compromised accounts can still make API requests for up to 30 minutes. Short TTL limits blast radius. | Yes — tokens expire naturally at 30 minutes. |
| **User auth** | PostgreSQL (user lookup) | Login, registration, and token refresh all fail | All authenticated endpoints return 401. Unauthenticated public endpoints (health check, public marketplace browse) still function. | No — requires DB recovery. |
| **Track playback** | Cloudflare R2 | Pre-signed URLs or public CDN URLs return errors | Users cannot stream or download their own tracks. Library page loads but play buttons fail. | Yes — R2 recovers; existing URLs remain valid for their signed TTL. |
| **Track playback** | Next.js frontend (CDN edge) | Static assets unavailable; page does not load | Total frontend outage for web users. Mobile app (if exists) unaffected. | Yes — Cloudflare CDN typically auto-recovers; re-deploy from CI if origin is down. |

---

## 5. Monitoring and Alert Thresholds

All metrics are assumed to be scraped by Prometheus and visualized in Grafana. Alerts route to PagerDuty (critical) or Slack `#alerts-platform` (warning).

### Generation Pipeline

| Metric | Expression | Warning Threshold | Critical Threshold | Action |
|--------|------------|-------------------|-------------------|--------|
| Generation failure rate | `rate(generation_job_failed_total[5m]) / rate(generation_job_total[5m])` | > 2% | > 5% → PagerDuty | Check DLQ depth, ML circuit breaker states, worker logs |
| DLQ depth | `celery_queue_length{queue="gbedu.dlq"}` | > 5 | > 20 → PagerDuty | Investigate root cause in DLQ messages; notify affected users |
| Generation p95 completion time | `histogram_quantile(0.95, rate(generation_duration_seconds_bucket[10m]))` | > 3min | > 5min → PagerDuty | Scale worker pods; check GPU memory; check ML service latency |
| Celery queue depth | `celery_queue_length{queue="default"}` | > 50 | > 200 → PagerDuty | Scale worker pods via HPA or manual override |

### Database

| Metric | Expression | Warning Threshold | Critical Threshold | Action |
|--------|------------|-------------------|-------------------|--------|
| DB pool checked out | `db_pool_checkedout` | > 35 (58% of cap=60) | > 50 (83% of cap) | Profile slow queries; consider adding read replica |
| DB pool overflow | `db_pool_overflow` | > 10 | > 30 | Pool exhaustion imminent; scale API pods down or add PgBouncer |
| DB connection errors | `rate(db_connection_error_total[5m])` | > 0.1/s | > 1/s → PagerDuty | Check PostgreSQL availability and max_connections |
| Migration version drift | `gbedu_migration_version != expected_version` | — | Any drift → PagerDuty | Run `alembic current` and compare; apply missing migrations |

### Redis

| Metric | Expression | Warning Threshold | Critical Threshold | Action |
|--------|------------|-------------------|-------------------|--------|
| Redis connected clients | `redis_connected_clients` | > 100 | > 200 → PagerDuty | Check for connection leaks; profile client connection pools |
| Redis memory usage | `redis_memory_used_bytes / redis_memory_max_bytes` | > 0.75 | > 0.90 → PagerDuty | Evict stale keys; increase memory limit; check for stampede |
| Redis broker reachable | `up{job="redis"}` | — | == 0 → PagerDuty | Redis is broker; all task enqueuing fails immediately |

### ML Service

| Metric | Expression | Warning Threshold | Critical Threshold | Action |
|--------|------------|-------------------|-------------------|--------|
| Circuit breaker open | `ml_circuit_open{model="ace_step"}` | == 1 for > 2min | — (Slack #alerts-ml) | Check ML service logs; inspect GPU memory and error pattern |
| All circuits open | `sum(ml_circuit_open) >= 2` | — | >= 2 → PagerDuty | All generations failing; ML service likely down or OOM |
| GPU memory utilization | `ml_gpu_memory_used_bytes / ml_gpu_memory_total_bytes` | > 0.80 | > 0.92 → PagerDuty | Risk of OOM during next large request; drain in-flight; restart pod |
| ML service p95 latency | `histogram_quantile(0.95, rate(ml_inference_duration_seconds_bucket[5m]))` | > 60s | > 90s → PagerDuty | Inference slower than expected; check GPU utilization, model loading |

### Payments

| Metric | Expression | Warning Threshold | Critical Threshold | Action |
|--------|------------|-------------------|-------------------|--------|
| Stripe webhook HMAC failures | `rate(stripe_webhook_hmac_failure_total[5m])` | > 0 for sustained 5min | > 5/min → PagerDuty | Possible key rotation needed or replay attack in progress |
| Paystack webhook HMAC failures | `rate(paystack_webhook_hmac_failure_total[5m])` | > 0 for sustained 5min | > 3 consecutive → PagerDuty | Check `PAYSTACK_SECRET_KEY` matches Paystack dashboard |
| Payment processing errors | `rate(payment_processing_error_total[5m])` | > 0.01/s | > 0.1/s → PagerDuty | Revenue impacted; check Stripe/Paystack API status pages |

### API / Frontend

| Metric | Expression | Warning Threshold | Critical Threshold | Action |
|--------|------------|-------------------|-------------------|--------|
| API error rate (5xx) | `rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m])` | > 1% | > 5% → PagerDuty | Check unhandled exceptions in structlog; inspect recent deploy |
| API p99 latency | `histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))` | > 300ms | > 500ms → PagerDuty | Check DB pool, Redis latency, slow queries |
| Rate limit hits | `rate(rate_limit_hit_total[5m])` | > 10/s on any single path | > 50/s → PagerDuty | Possible abuse; check source IPs; consider IP-level block |
| Pod OOM kills | `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} > 0` | Any | Repeated > 3 in 10min → PagerDuty | Adjust resource limits; profile memory usage |

---

## 6. Recommended Infrastructure Improvements (Prioritized by RPN)

Items are sorted by RPN descending. All five represent systemic gaps, not minor polish.

---

### Priority 1 — Nigerian Pidgin / Yoruba LLM Hallucination (F-14, RPN: 240)

**Problem:** The `AfrobeatsPromptEngine.build_music_prompt()` generates prompts for West African languages with no automated quality gate. Hallucinated or culturally inappropriate content damages brand trust, could violate content policies, and degrades generation quality for a core user segment (Nigerian and West African users are the primary market).

**Remediation steps:**

1. Build a prompt evaluation harness: a dataset of 50 reference Yoruba, Nigerian Pidgin, Igbo, and Hausa prompts with expected musical descriptors. Run weekly; track BLEU/chrF score drift.
2. Implement a lightweight content safety classifier (distilbert fine-tuned on Afrobeats-domain content) that runs on every generated prompt before it enters `MusicGenerator.generate()`. Route flagged prompts to a human review queue.
3. Add `ml_prompt_safety_flag_total{language="..."}` Prometheus counter. Alert if > 5% of any language's prompts are flagged in a 24-hour window.
4. For languages with < 100 reference prompts in the eval set, default to English-language music descriptors with language metadata appended, rather than generating full non-English prompts until the model is validated.

**Estimated effort:** 2 weeks (1 week eval harness, 1 week classifier + monitoring).

---

### Priority 2 — JWT Secret Compromise Risk (F-10, RPN: 160)

**Problem:** The current HS256 symmetric signing scheme means anyone with the `JWT_SECRET_KEY` can forge tokens for any user. The default value `"change-this-in-production"` is hardcoded in `JWTSettings` and will silently pass if the env var is not set in a new deployment. There is no token revocation mechanism.

**Remediation steps:**

1. **Immediate:** Add a startup assertion in `lifespan()` in `main.py`:
   ```python
   if settings.jwt.secret_key == "change-this-in-production":
       raise RuntimeError("JWT_SECRET_KEY is not set — refusing to start in non-development mode")
   ```
   Gate this on `not settings.is_development`.

2. **Short-term:** Migrate to RS256. Generate a 4096-bit RSA key pair. Store the private key in Kubernetes Secrets. Distribute the public key via a JWKS endpoint (`GET /api/v1/.well-known/jwks.json`). This allows the public key to be exposed without enabling token forgery.

3. **Short-term:** Implement JWT revocation: add a `jti` UUID claim to every issued token. On logout, `SETEX jti:<jti> <remaining_ttl> 1` in Redis. On every authenticated request, check `EXISTS jti:<jti>` before accepting the token.

4. **Medium-term:** Add CI secret scanning (e.g., `gitleaks` in the GitHub Actions workflow) to prevent accidental commits of JWT or payment secrets.

**Estimated effort:** 3 days (RS256 migration is straightforward with PyJWT; JWKS endpoint is ~50 lines).

---

### Priority 3 — Stripe Webhook Duplicate Processing (F-08, RPN: 160)

**Problem:** No idempotency table exists for Stripe (or Paystack) webhooks. Stripe guarantees at-least-once delivery, not exactly-once. Network blips during webhook processing result in the handler not returning 2xx, triggering Stripe's retry mechanism. Each retry risks double-granting credits, double-sending emails, or double-activating subscriptions.

**Remediation steps:**

1. Create a `webhook_events` table:
   ```sql
   CREATE TABLE webhook_events (
       event_id   TEXT        PRIMARY KEY,
       provider   TEXT        NOT NULL,  -- 'stripe' | 'paystack'
       processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
       status     TEXT        NOT NULL   -- 'processed' | 'skipped'
   );
   CREATE INDEX ON webhook_events (processed_at);
   ```

2. In the Stripe webhook handler, wrap processing in:
   ```python
   result = await db.execute(
       insert(WebhookEvent).values(event_id=event.id, provider="stripe", status="processed")
       .on_conflict_do_update(index_elements=["event_id"], set_={"status": "skipped"})
       .returning(WebhookEvent.status)
   )
   if result.scalar() == "skipped":
       return JSONResponse({"status": "already_processed"})
   ```

3. Implement the same pattern for Paystack using Paystack's `data.reference` as the idempotency key.

4. Purge `webhook_events` rows older than 30 days via a nightly Celery task.

**Estimated effort:** 1 day.

---

### Priority 4 — asyncpg Connection Leak / Pool Exhaustion (F-18, RPN: 144 / F-01, RPN: 108)

**Problem:** There is currently no Prometheus instrumentation on the SQLAlchemy connection pool. Connection leaks are invisible until pool exhaustion causes a wave of `TimeoutError` exceptions. The hard cap of 60 connections (pool_size=20 + max_overflow=40) can be exhausted by 3-4 API pods under moderate load if any requests hold connections for extended periods.

**Remediation steps:**

1. Add a SQLAlchemy event listener to export pool metrics:
   ```python
   from sqlalchemy import event
   from prometheus_client import Gauge

   pool_checked_out = Gauge("db_pool_checkedout", "DB connections currently in use")
   pool_overflow = Gauge("db_pool_overflow", "DB connections in overflow")

   @event.listens_for(engine.sync_engine, "checkout")
   def on_checkout(dbapi_conn, conn_record, conn_proxy):
       pool_checked_out.inc()

   @event.listens_for(engine.sync_engine, "checkin")
   def on_checkin(dbapi_conn, conn_record):
       pool_checked_out.dec()
   ```

2. Alert: `db_pool_checkedout > 35` → warning; `> 50` → critical (see Section 5).

3. Deploy PgBouncer in transaction pooling mode between the API pods and PostgreSQL. PgBouncer's pool can be set much larger (e.g., 100) while the actual Postgres `max_connections` stays controlled. This is the most impactful change for preventing F-01 under burst traffic.

4. Audit all code paths that open a DB session for proper context manager usage. The `get_async_session()` in `gbedu_worker/db.py` is correctly wrapped; verify the FastAPI `get_db` dependency also has a try/finally `await session.close()`.

**Estimated effort:** 2 days (metrics: 4 hours; PgBouncer: 1 day; audit: 4 hours).

---

### Priority 5 — Redis Cache Stampede on Cold Start (F-20, RPN: 140)

**Problem:** When Redis restarts with an empty cache (planned maintenance, OOM kill, pod restart), all API pods simultaneously receive cache misses for the same high-traffic keys (marketplace listings, featured tracks, generation status). This produces a thundering-herd DB query spike that can itself cause pool exhaustion (F-01), compounding the incident.

**Remediation steps:**

1. Implement a distributed lock per cache key using Redis `SET NX PX`. Pattern:
   ```python
   async def get_cached_or_fetch(redis, key, ttl, fetch_fn):
       value = await redis.get(key)
       if value:
           return deserialize(value)
       lock_key = f"lock:{key}"
       acquired = await redis.set(lock_key, "1", nx=True, ex=10)
       if acquired:
           try:
               value = await fetch_fn()
               await redis.setex(key, ttl, serialize(value))
               return value
           finally:
               await redis.delete(lock_key)
       else:
           # Another pod is fetching; brief wait then retry
           await asyncio.sleep(0.1)
           return await get_cached_or_fetch(redis, key, ttl, fetch_fn)
   ```

2. Add a cache warm-up Kubernetes Job that runs after Redis restarts (triggered by a Redis readiness probe state change) and pre-populates the top-N marketplace listings, featured tracks, and genre lists.

3. Stagger cache TTLs with jitter: instead of `SETEX key 300`, use `SETEX key (300 + random.randint(-30, 30))` to prevent synchronized expiry.

4. Monitor `redis_keyspace_hits_total / (redis_keyspace_hits_total + redis_keyspace_misses_total)` as a cache hit rate metric. Alert if hit rate drops below 60% for more than 5 minutes (strong signal of cache cold-start or key churn).

**Estimated effort:** 1.5 days.

---

## Appendix A — Failure Mode Index

| RPN | ID | Failure Mode |
|-----|----|--------------|
| 240 | F-14 | Nigerian Pidgin/Yoruba LLM hallucination |
| 160 | F-08 | Stripe webhook duplicate processing |
| 160 | F-10 | JWT secret compromise |
| 144 | F-18 | asyncpg connection leak |
| 140 | F-20 | Redis cache stampede |
| 126 | F-06 | ACE-Step circuit breaker stuck open |
| 126 | F-09 | Paystack HMAC validation failure |
| 120 | F-04 | ML model GPU OOM |
| 108 | F-01 | DB connection pool exhaustion |
| 108 | F-11 | Alembic migration failure |
| 100 | F-15 | Next.js hydration failure |
| 96 | F-16 | Pod OOM kill during payment flow |
| 90 | F-17 | Rate limiter false positive |
| 84 | F-12 | DSP pipeline OOM (librosa/demucs) |
| 63 | F-07 | R2 upload failure after generation |
| 60 | F-13 | RVC voice conversion crash |
| 56 | F-03 | Celery worker crash mid-generation |
| 54 | F-02 | Redis unavailability |
| 48 | F-19 | Celery task deserialization failure |
| 40 | F-05 | All three ML circuits open simultaneously |

---

## Appendix B — Configuration Values Referenced

| Setting | Value | Source |
|---------|-------|--------|
| `pool_size` | 20 | `DatabaseSettings` in `gbedu_core/config.py` |
| `max_overflow` | 40 | `DatabaseSettings` in `gbedu_core/config.py` |
| `pool_recycle` | 3600s | `DatabaseSettings` in `gbedu_core/config.py` |
| `pool_pre_ping` | True | `DatabaseSettings` in `gbedu_core/config.py` |
| `task_acks_late` | True | `CelerySettings` in `gbedu_core/config.py` |
| `task_reject_on_worker_lost` | True | `CelerySettings` in `gbedu_core/config.py` |
| `worker_prefetch_multiplier` | 1 | `CelerySettings` in `gbedu_core/config.py` |
| `soft_time_limit` | 720s | `run_generation_pipeline` task in `generation.py` |
| `time_limit` | 780s | `run_generation_pipeline` task in `generation.py` |
| `max_retries` | 3 | `run_generation_pipeline` task in `generation.py` |
| Retry countdowns | 30s, 90s, 270s | `_RETRY_COUNTDOWN` in `generation.py` |
| `circuit_failure_threshold` | 5 | `MLSettings` in `gbedu_core/config.py` |
| `circuit_recovery_timeout` | 60s | `MLSettings` in `gbedu_core/config.py` |
| `inference_timeout` | 300s | `MLSettings` in `gbedu_core/config.py` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 30 | `JWTSettings` in `gbedu_core/config.py` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | 30 | `JWTSettings` in `gbedu_core/config.py` |
| `JWT_ALGORITHM` | HS256 | `JWTSettings` in `gbedu_core/config.py` |
| ML fallback order | ACE-Step → Stable Audio → YuE | `MusicGenerator.__init__()` in `music_generator.py` |
| Celery broker db | 1 | `CelerySettings.broker_url` default |
| Celery result backend db | 2 | `CelerySettings.result_backend` default |
| API cache db | 0 | `RedisSettings.url` default |
| R2 bucket (prod) | `gbedu-audio` | `StorageSettings.r2_bucket_name` |
