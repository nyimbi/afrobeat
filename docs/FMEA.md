# Gbẹdu — Failure Mode and Effects Analysis (FMEA)

**Document version**: 2.0
**Date**: 2026-06-20
**Authors**: Platform Engineering
**Status**: DRAFT — requires sign-off before production launch

---

## Executive Summary

This FMEA covers six component domains of the Gbẹdu platform: the FastAPI API service (gbedu-api, :8000), the FastAPI ML inference service (gbedu-ml, :8001), the Celery worker (gbedu-worker), PostgreSQL 16, the shared infrastructure layer (Cloudflare R2, Kubernetes, Redis, Prometheus), and cross-cutting security failure modes.

**51 failure modes** are documented below. Of these:

- **CRITICAL (RPN > 50)**: 19 items requiring immediate action before production launch.
- **HIGH (RPN 26–50)**: 14 items requiring mitigation within the first quarter of production operation.
- **MODERATE/LOW (RPN ≤ 25)**: 18 items accepted as residual risk with monitoring in place.

**Reliability target**: 99.9% API availability = **8.76 hours of allowable downtime per year**. The generation pipeline specifically targets 99.5% per-request success rate, acknowledging the inherent instability of GPU inference workloads.

**Key findings**:

1. Redis is a single point of failure for both the Celery broker (task queue) and SlowAPI rate limiting. Any Redis outage cascades to generation unavailability. Redis Sentinel or Cluster is required before production launch.
2. The ML service has no per-request VRAM budget enforcement. A single `duration_seconds=300` request can exhaust GPU memory and crash inference for all concurrent users.
3. JWT secret rotation has no zero-downtime procedure. Rotating `JWT_SECRET_KEY` invalidates all active sessions simultaneously. RS256 with a JWKS rotation procedure must be documented.
4. The DLQ has no automated consumer. Dead tasks accumulate silently in `gbedu.dlq` unless Grafana alerting fires. Manual remediation is undocumented.
5. Credit decrement on generation submission is not serialized. Concurrent requests can race past the credits check and double-spend.

---

## Reliability Targets

| Metric | Target | Allowable downtime / error budget (per year) |
|--------|--------|----------------------------------------------|
| API availability (all endpoints) | 99.9% | 8h 46m |
| Generation success rate (submitted → completed) | 99.5% | — |
| Audio delivery (CDN / R2) | 99.95% | 4h 23m |
| P99 API response time (non-generation) | < 500 ms | — |
| Generation end-to-end latency P50 | < 180 s | — |
| Recovery Point Objective (RPO) | 1 hour | pgBackRest PITR |
| Recovery Time Objective (RTO) | 30 minutes | — |

---

## Scoring Scale

| Score | Severity (S) | Likelihood (L) |
|-------|--------------|----------------|
| 1–2 | Cosmetic / no user impact | Extremely rare (< 1/year) |
| 3–4 | Minor degradation, workaround exists | Rare (1–4/year) |
| 5–6 | Significant feature loss, some users impacted | Occasional (monthly) |
| 7–8 | Major feature unavailable, many users impacted | Frequent (weekly) |
| 9–10 | Full outage or data loss | Near-certain (daily) |

**RPN = Severity × Likelihood**. Items with RPN > 50 are flagged **CRITICAL**.

---

## FMEA Table

### Section 1 — API Service (gbedu-api, :8000)

| ID | Component | Failure Mode | Severity | Likelihood | RPN | Detection | Current Mitigation | Required Action |
|----|-----------|--------------|:--------:|:----------:|:---:|-----------|--------------------|-----------------|
| A01 | API / Database | **DB connection pool exhausted** — SQLAlchemy hard cap of 60 connections (pool_size=20 + max_overflow=40) saturated; new requests queue then raise `TimeoutError`, returning 500 | 9 | 5 | **45** | `QueuePool limit overflow` in structlog; 5xx spike; no `db_pool_checkedout` metric currently exported | `pool_pre_ping=True`; `pool_recycle=3600s`; structured exception logging | Export `db_pool_checkedout` Prometheus gauge; alert at > 35 (58% of cap); deploy PgBouncer in transaction mode to multiply effective connection headroom |
| A02 | API / Redis | **Redis unavailable — rate limiter disabled** — SlowAPI loses its Redis-backed state; requests either pass unthrottled or return 500 depending on SlowAPI error handling mode | 8 | 4 | **32** | 5xx spike on rate-limited paths; Redis PING failure logged at startup | SlowAPI wraps Redis; connection validated in `lifespan()` | Implement in-process token bucket fallback when Redis is unreachable; alert within 30 s of Redis PING failure; never let Redis unavailability cause 500 on rate-limited endpoints |
| A03 | API / Redis | **Redis unavailable — refresh token blacklist bypassed** — logout writes the revoked JTI to Redis; if Redis is down, revoked tokens remain accepted for the remainder of their 30-minute TTL | 7 | 4 | **28** | Mass 401s after Redis recovery; stale tokens accepted post-logout during outage window | Access token TTL 30 min bounds the exposure window | Reduce access token TTL to 5 min; document Redis-down auth behaviour explicitly in RUNBOOKS.md; add blacklist-check circuit breaker that fails closed (rejects unverifiable tokens) |
| A04 | API / Auth | **JWT secret rotation invalidates all sessions** — rotating `JWT_SECRET_KEY` without a grace period logs out every active user simultaneously; no zero-downtime rotation procedure documented | 8 | 3 | **24** | Mass 401s; spike in `/auth/refresh` failures | `validate_production_secrets()` prevents default key in prod | Migrate to RS256 (asymmetric); implement JWKS endpoint; document two-key grace-period rotation procedure in RUNBOOKS.md |
| A05 | API / Email | **SMTP failure — registration verification email undelivered** — user registers, verification email is never delivered; account stuck unverified; generation gated behind email verification returns 403 | 5 | 5 | **25** | Email task failure in Celery low-priority queue; no `email_delivery_success_rate` metric | Email task max_retries=3 on low-priority Celery queue | Add secondary SMTP provider fallback; expose `email_send_failed_total` metric; alert if > 5% failure rate over 5 min |
| A06 | API / Payments | **Stripe webhook replay — double credit grant** — Stripe retries a webhook that succeeded silently; payment processed twice; user's credits or subscription activated twice | 8 | 5 | **40** | Duplicate `provider_payment_id` on INSERT raises `DatabaseIntegrityError` — caught but retry may re-attempt | `provider_payment_id` UNIQUE constraint; `PaymentWebhookError` handler exists | Implement `webhook_events(event_id PK, provider, processed_at)` idempotency table; `INSERT ON CONFLICT DO NOTHING`; return 200 immediately for already-processed events |
| A07 | API / Payments | **Paystack HMAC not enforced when `PAYSTACK_SECRET_KEY` is empty** — if the env var is missing, HMAC comparison with an empty string passes vacuously; forged webhooks activate subscriptions | 9 | 3 | **27** | Anomalous credit grants with no corresponding Paystack transaction | `PaystackSettings` loads key from env; no explicit non-empty assertion | Add `assert settings.paystack.secret_key, "PAYSTACK_SECRET_KEY must be set"` in `validate_production_secrets()`; add forged-webhook integration test |
| A08 | API / Memory | **OOM under burst load** — 50+ concurrent generation submissions or large response bodies exhaust the 1 Gi pod heap; Kubernetes OOMKilled; 502 from ingress during restart | 7 | 4 | **28** | Kubernetes OOMKilled event; container restart count metric | 1 Gi RAM limit in k8s spec; GZipMiddleware compresses large responses | Profile memory under load test; set `--limit-max-requests 500` on uvicorn to recycle worker processes; tune k8s memory limit to P99 + 20% headroom |
| A09 | API / Config | **Stale config during rolling deploy** — two API pod versions coexist mid-rollout; one has new feature flags or schema expectations; responses are inconsistent | 5 | 6 | **30** | Intermittent 422 / 500 errors during deploys; `X-App-Version` header drift | `get_settings()` is `@lru_cache` — immutable per process | Add `X-App-Version` response header; Grafana alert if multiple distinct versions serve traffic simultaneously during a rollout window |
| A10 | API / Credits | **Credits race condition — double spend** — two concurrent generation requests both read `credits >= 1`, both pass, both decrement; user generates more tracks than their credit balance | 8 | 4 | **32** | Users report unexpected credit loss; credits can go negative | No serialization observed on credit decrement | Use atomic `UPDATE users SET credits = credits - 1 WHERE id = $1 AND credits > 0 RETURNING credits`; if no row returned, abort with `INSUFFICIENT_CREDITS`; add integration test for concurrent requests |

---

### Section 2 — ML Service (gbedu-ml, :8001)

| ID | Component | Failure Mode | Severity | Likelihood | RPN | Detection | Current Mitigation | Required Action |
|----|-----------|--------------|:--------:|:----------:|:---:|-----------|--------------------|-----------------|
| M01 | ML / GPU | **CUDA OOM — single large request kills inference** — a `duration_seconds=300` request allocates > available VRAM; `torch.cuda.OutOfMemoryError`; GPU memory fragmentation persists and cascades to subsequent requests | 9 | 6 | **54** ⚠️ CRITICAL | OOMKilled Kubernetes event; ML service 503; Sentry alert | Three-model fallback chain (ACE-Step → Stable Audio → YuE); `circuit_failure_threshold=5` | Enforce per-request VRAM budget: reject if `torch.cuda.memory_reserved() / total > 0.85`; add `torch.cuda.empty_cache()` after every inference; expose `ml_gpu_memory_reserved_bytes` metric; alert at > 80% |
| M02 | ML / GPU | **GPU memory leak across requests** — PyTorch tensors not released after inference; VRAM slowly exhausted over hours; inference latency grows then OOM occurs | 7 | 5 | **35** ⚠️ | `nvidia-smi` shows monotonically increasing reserved memory; p99 inference latency trending up | Pod restarts on OOMKilled (eventual recovery) | Call `torch.cuda.empty_cache()` after each inference; add `ml_gpu_memory_reserved_bytes` Prometheus gauge sampled every 30 s; alert if reserved > 80% of total; set up nightly pod recycle as a safety net |
| M03 | ML / Models | **Model weight corruption on disk** — partial download or disk error produces a corrupt checkpoint; `RuntimeError` on `torch.load()`; ML service fails to start | 8 | 3 | **24** | ML service crash loop; health check returns 503; Kubernetes pod restart events | HuggingFace Hub downloads with checksums | Store expected SHA-256 of every model file in `gbedu_ml/config.py`; verify at startup before loading; alert and refuse to start on mismatch |
| M04 | ML / Models | **Model download failure on first boot** — network partition during the ~15 GB HuggingFace download; service stuck in restart loop; liveness probe eventually fails | 7 | 4 | **28** | Pod restart loop; `initialDelaySeconds=600` gives 10 min window but persistent partition exceeds it | 10-minute `initialDelaySeconds` on liveness probe; HF Hub retries | Implement download resumption via HTTP range requests; add `model_download_progress_pct{model="..."}` metric; pre-pull model weights in CI and bake into a versioned Docker image layer for production |
| M05 | ML / Inference | **ACE-Step inference timeout — process does not respond to SIGTERM** — GPU kernel hangs; `soft_time_limit=720` fires but SIGTERM is not honoured inside a blocking CUDA call; `time_limit=780` SIGKILL eventually fires | 8 | 4 | **32** | Worker task marked FAILED after `time_limit=780`; generation DB row stuck in `processing` | `soft_time_limit=720` + `time_limit=780` on Celery task | Add a watchdog thread in the ML service that sends SIGKILL to the inference subprocess if wall-clock time exceeds budget; expose per-step `ml_inference_duration_seconds{model="..."}` histogram |
| M06 | ML / Models | **All three model circuit breakers open simultaneously** — dependency update breaks all three model loaders in the same deploy; every generation request fails instantly | 10 | 2 | **20** | Health check reports all circuits open; generation failure rate 100%; DLQ depth grows | Per-model circuit breakers; breakers are independent | Add `/health/detailed` component `ml_service` reporting per-model circuit state; alert CRITICAL if ≥ 2 circuits open; implement admin endpoint to manually reset a specific circuit breaker |
| M07 | ML / Models | **RVC voice model missing from R2** — voice model deleted from storage but DB record exists; worker dispatches RVC step with an invalid R2 key; `StorageError` raised | 6 | 4 | **24** | `StorageError` in worker logs; generation fails at voice conversion step | `voice_model_id` FK constraint in DB | Pre-flight check in `GenerationPipelineOrchestrator`: verify R2 key exists before dispatching RVC step; auto-disable voice models with > 3 consecutive `StorageError` failures |
| M08 | ML / Inference | **Llama-3 8B GPU stall — lyrics generation hangs indefinitely** — long-context prompt with no `max_new_tokens` cap; autoregressive loop runs without bound; no per-step timeout in the orchestrator | 8 | 4 | **32** | Worker task hits `soft_time_limit=720`; generation marked FAILED with timeout | Worker-level `soft_time_limit` is the only backstop | Set `max_new_tokens=512` cap in every Llama-3 inference call; add per-step deadline in `GenerationPipelineOrchestrator` (e.g., 60 s for lyrics, 300 s for music); expose `ml_step_duration_seconds{step="..."}` histogram |
| M09 | ML / Audio | **ACE-Step produces silent audio** — model generates a valid WAV with zero amplitude; audio mastering normalises silence to a valid-looking file; user hears nothing | 6 | 3 | **18** | User complaint; play count anomaly; audio analysis step measures loudness | Audio analysis step (`gbedu_audio/analysis.py`) measures loudness | Add `assert peak_db > -60` quality gate in `gbedu_audio/analysis.py` before upload; fail generation with `GENERATION_QUALITY_FAILED` error code; surface this to the user as a retryable error |
| M10 | ML / LoRA | **LoRA weight hot-swap corrupts active inference** — new LoRA weights loaded while an in-flight inference request reads the same model weights; output quality degrades or model crashes | 7 | 3 | **21** | Corrupt or zero-length audio output; non-deterministic errors on the hot-swap pod | Hot-swap described as a capability; no locking mechanism confirmed | Implement a `threading.RLock` (or `asyncio.Lock`) around the model adapter; reject new inference requests during the swap window (< 5 s); log every swap event with model version |

---

### Section 3 — Worker / Celery

| ID | Component | Failure Mode | Severity | Likelihood | RPN | Detection | Current Mitigation | Required Action |
|----|-----------|--------------|:--------:|:----------:|:---:|-----------|--------------------|-----------------|
| W01 | Worker / Tasks | **Task duplication — generation run twice** — network partition between Redis broker and worker causes a late ack; Celery delivers the task a second time while the first execution is still running | 7 | 4 | **28** | Two concurrent DB updates for the same `job_id`; pipeline state machine detects duplicate | `acks_late=True`; `reject_on_worker_lost=True`; `GenerationPipelineOrchestrator` checks DB state at each step entry | Add idempotency integration test: invoke `_run_pipeline(job_id)` twice concurrently; verify second call is a no-op at each stage |
| W02 | Worker / Tasks | **Worker crash mid-generation — no pipeline checkpointing** — OOMKilled or SIGKILL during audio mastering; task requeued; retry restarts from ML inference, not from the DSP checkpoint; user waits up to 2× the normal generation time | 7 | 5 | **35** ⚠️ | Task redelivered to queue; generation takes > 2× expected; structlog shows retry with same `job_id` | `reject_on_worker_lost=True` requeues; max_retries=3 with backoff 30/90/270 s | Implement stage checkpointing: persist completed stage IDs (e.g., `LYRICS_DONE`, `MUSIC_DONE`, `DSP_DONE`) to Redis with 24h TTL; `GenerationPipelineOrchestrator.run()` resumes from last completed stage on retry |
| W03 | Worker / Broker | **Redis broker lost — all tasks undeliverable** — Redis pod crash or network partition; Celery cannot publish or consume tasks; all in-flight and queued generations stall | 9 | 4 | **36** ⚠️ | All generations stall in `processing`; `celery_queue_length` drops to zero AND no tasks complete; Redis PING failures | Celery retries broker connection with exponential backoff | Deploy Redis Sentinel (3 nodes) before production; add broker health check to `/api/v1/health/detailed`; alert within 60 s of broker unavailability |
| W04 | Worker / DLQ | **DLQ overflow — dead tasks accumulate silently** — `gbedu.dlq` queue grows unbounded; no automated consumer removes messages; affected users never notified | 6 | 5 | **30** | `celery_queue_length{queue="gbedu.dlq"}` gauge grows; no user-visible error | `process_dlq_message` task exists with max_retries=0 | Alert: DLQ depth > 10 → Slack; > 50 → PagerDuty; add DLQ depth to the `/health/detailed` response; document manual DLQ remediation in RUNBOOKS.md |
| W05 | Worker / Serialization | **Task deserialization failure — Pydantic model passed as arg** — caller passes a non-JSON-serializable object (UUID, Pydantic model); Celery raises `kombu.exceptions.EncodeError` at dispatch; task never enqueued; generation DB record stuck in `PENDING` | 6 | 3 | **18** | `EncodeError` in API structlog at task dispatch; generation job permanently in `PENDING` state | `task_serializer="json"`, `accept_content=["json"]`; task arg documented as str | Add `_mark_job_failed()` call in the non-retryable `except Exception` branch in `generation.py` so DB record transitions `PENDING → FAILED`; add CI test calling `.apply_async()` with production arg types |
| W06 | Worker / Beat | **Beat scheduler single point of failure** — single `celery beat` process; crash means `reset_daily_generation_counts` does not run; users cannot generate after midnight until manually restarted | 6 | 4 | **24** | Daily generation limits not reset; users hit quota permanently; no beat heartbeat metric | Kubernetes Deployment for beat with `replicas: 1` | Deploy `celery-redbeat` (Redis-backed distributed beat scheduler) to guarantee exactly-once schedule execution across pod restarts; add beat heartbeat metric and alert if missing for > 5 min |
| W07 | Worker / Tasks | **Zombie tasks — blocking subprocess holds GIL** — ffmpeg or librosa subprocess called with a blocking API inside the Celery task; SIGTERM from `soft_time_limit` cannot interrupt a GIL-holding C extension; `time_limit` SIGKILL eventually fires | 7 | 4 | **28** | Task duration exceeds `soft_time_limit`; `SoftTimeLimitExceeded` not raised until next Python bytecode checkpoint | `soft_time_limit=720` / `time_limit=780` | Wrap all subprocess calls in `asyncio.create_subprocess_exec` with `asyncio.wait_for`; use `run_in_executor` for blocking C-extension calls; test that `soft_time_limit` fires correctly |
| W08 | Worker / Tasks | **R2 upload timeout mid-multipart — audio file lost** — `boto3` upload stalls; `UploadError` raised; task retried; but the temp audio file is on ephemeral pod disk and may be deleted by the hourly cleanup task before the retry runs | 8 | 3 | **24** | `StorageUploadError` in worker logs; generation FAILED after retries | Tenacity retry (3×) on `UploadError`; `UploadError` is retryable | Persist generated audio to a shared volume or S3-compatible staging bucket before attempting R2 upload; extend temp file cleanup TTL to at minimum 2 h; add multipart upload resumption via S3 upload ID |
| W09 | Worker / Ordering | **Message ordering violation — postprocess before generate completes** — Celery does not guarantee FIFO within a queue under retry; a postprocess task could execute before the parent generate task commits to DB | 5 | 3 | **15** | State machine violation logged; postprocess step finds no audio path in DB | Pipeline stages chained via Celery chord/chain | Enforce: postprocess tasks are always dispatched within the same chain as generate; add DB state assertion (`assert job.status == JobStatus.ml_done`) at postprocess entry |
| W10 | Worker / Notifications | **Notification task failure silently swallowed** — email notification task fails after max_retries; user never notified that generation completed; no fallback delivery path | 4 | 5 | **20** | `task_failure` signal fires for notification task; no user-visible symptom | Email task retried 3× on low-priority queue | Add fallback: on DLQ for notification tasks, write an unread notification row to a `notifications` DB table; frontend polls `GET /api/v1/notifications` |

---

### Section 4 — Database (PostgreSQL 16)

| ID | Component | Failure Mode | Severity | Likelihood | RPN | Detection | Current Mitigation | Required Action |
|----|-----------|--------------|:--------:|:----------:|:---:|-----------|--------------------|-----------------|
| D01 | Database | **Connection pool exhaustion from worker** — worker opens a DB session at task start and holds it open across the ML HTTP call (up to 300 s); pool slots exhausted; API requests queue and timeout | 8 | 5 | **40** | `QueuePool limit overflow` in worker structlog | `get_async_session()` is a context manager; `pool_pre_ping=True` | Ensure `get_async_session()` context is exited before any ML HTTP call; never hold a DB session across a network boundary; add worker-specific pool metrics |
| D02 | Database | **Long-running transaction deadlock** — two concurrent `UPDATE tracks` or `UPDATE users` requests acquire row locks in different order; PostgreSQL deadlock detector aborts one; request returns 500 | 5 | 4 | **20** | `DeadlockDetected` PostgreSQL error in structlog; occasional 500 on update paths | SQLAlchemy raises `OperationalError`; unhandled exception handler returns 500 | Add retry-on-deadlock decorator to service layer functions; use `SELECT ... FOR UPDATE SKIP LOCKED` for non-blocking patterns; add `deadlock_total` metric |
| D03 | Database | **Migration failure on live traffic — ACCESS EXCLUSIVE lock** — `alembic upgrade head` acquires `ACCESS EXCLUSIVE` on the target table; all queries blocked; 504 cascade across API and worker | 9 | 4 | **36** ⚠️ | All API requests timeout; 504 from ingress; no mitigation for currently running migrations | Runbook mandates low-traffic window; two-phase column removal documented | Enforce `CREATE INDEX CONCURRENTLY` for all index additions (requires separate migration file, no transaction wrapper); mandate nullable-first column additions; add pre-migration traffic drain to deploy workflow; run migration as a pre-upgrade Kubernetes Job with timeout |
| D04 | Database | **Disk full — all writes fail** — PostgreSQL data volume fills; all INSERT/UPDATE fail with `ENOSPC`; service degrades to read-only then total failure | 10 | 3 | **30** | `disk_used_percent` Prometheus metric > 85%; PostgreSQL error logs show `ENOSPC` | pgBackRest PITR on vmi3169165; managed instance | Alert at 75% disk usage; implement partitioning + archival: audio analysis tables > 90 days → archive to R2; add `pg_partman` for large tables |
| D05 | Database | **Soft-delete filter missing on a new query** — a new query added without `WHERE deleted_at IS NULL` returns soft-deleted tracks, users, or voice models to callers | 7 | 4 | **28** | Users see deleted content; privacy violation potential | Soft-delete pattern documented in ARCHITECTURE.md | Add SQLAlchemy `__mapper_args__` with a default `where_clause` enforcing `deleted_at IS NULL` on all models; or use a custom `Query` subclass; add a unit test asserting soft-deleted rows are invisible |
| D06 | Database | **Credits race condition — double spend** — two concurrent generation requests read `credits >= 1` before either commits the decrement; both pass; user generates two tracks with one credit | 8 | 4 | **32** | Credits go negative; user generates more than their tier allows | No serialization observed on credit reads | Atomic `UPDATE users SET credits = credits - 1 WHERE id = $1 AND credits > 0 RETURNING credits`; abort if no row returned; this is the same root cause as A10 — fix must be in the DB layer |
| D07 | Database | **Replication lag — stale reads on future replica** — when a read replica is added, replication lag causes stale generation status reads; user sees `PENDING` for a completed job | 5 | 2 | **10** | `pg_stat_replication.replay_lag` metric; stale status in frontend | Currently no read replica (single primary) | When replica added: route `generation status` reads to primary; use `synchronous_commit = remote_apply` for credit and payment writes |
| D08 | Database | **pg_hba lockout after bad config deploy** — `pg_hba.conf` edited incorrectly; all connections refused; full service outage | 9 | 2 | **18** | All DB connections fail immediately; total outage | Managed PG instance on vmi3169165; config changes via admin UI | Never edit `pg_hba.conf` directly; add pre-deploy connectivity smoke test: `psql -c "SELECT 1"` before traffic switchover |
| D09 | Database | **asyncpg connection leak — unhandled exception escapes context manager** — an exception propagates before the `async with get_async_session()` `__aexit__` runs; connection left in IDLE state; pool slots exhausted over hours | 8 | 3 | **24** | `db_pool_checkedout` gauge climbs monotonically; no `db_pool_checkin` events | `async with get_async_session() as session:` should handle this; FastAPI `get_db` uses `yield` with try/finally | Add SQLAlchemy pool event listeners to export `db_pool_checkedout` and `db_pool_overflow` Prometheus gauges; alert at > 35 checked out (58% of hard cap 60) |

---

### Section 5 — Infrastructure

| ID | Component | Failure Mode | Severity | Likelihood | RPN | Detection | Current Mitigation | Required Action |
|----|-----------|--------------|:--------:|:----------:|:---:|-----------|--------------------|-----------------|
| I01 | Storage / R2 | **Cloudflare R2 outage** — R2 API unavailable; audio uploads fail; presigned URL generation fails; users cannot access existing tracks via CDN | 8 | 2 | **16** | `StorageUploadError`; CDN 5xx; Cloudflare status page alert | Tenacity retry (3×) on upload; LocalStack in dev | Configure Cloudflare R2 SLA webhook to alert engineering Slack; document manual recovery (no local fallback exists); add `storage_upload_failed_total` metric |
| I02 | CDN | **CDN cache poisoning** — attacker triggers Cloudflare to cache a 403 or corrupt response for a public audio URL; legitimate users receive the cached error | 6 | 2 | **12** | Elevated 403/404 rate on CDN-served audio URLs | Cloudflare CDN with signed URLs for private content; public bucket URLs are time-unlimited | Set `Cache-Control: no-store` on all API JSON responses; use short-lived signed R2 URLs (1 h for WAV, 7 days for MP3); purge CDN cache on track deletion |
| I03 | Kubernetes | **Pod eviction during generation** — memory pressure causes kubelet to evict the worker pod mid-generation; task requeued by `reject_on_worker_lost`; user waits extra time | 7 | 4 | **28** | OOMKilled or Evicted events in `kubectl get events`; task retry counter increments | `acks_late=True` requeues; max_retries=3 | Profile actual worker memory usage under GPU inference load; set `resources.requests.memory` to P95 measured usage; add `PodDisruptionBudget` for the worker deployment |
| I04 | Kubernetes | **Rolling deploy mid-request — connection reset** — old API pod receives SIGTERM while handling a 120 s generation polling request; Kubernetes default `terminationGracePeriodSeconds=30` kills the pod before the response completes; client gets TCP RST | 6 | 6 | **36** ⚠️ | Client receives 502; frontend shows error toast; no data loss but UX impact | `terminationGracePeriodSeconds` defaults apply | Set `terminationGracePeriodSeconds: 120` on the API Deployment; add `preStop` lifecycle hook: `exec: command: ["sleep", "5"]` to drain load balancer connections before SIGTERM |
| I05 | Redis | **Redis `maxmemory` eviction — rate limit keys evicted** — Redis hits its memory limit under load; LRU eviction removes rate limit counters; rate limit bypass possible | 7 | 4 | **28** | `redis_evicted_keys_total` counter increases; anomalous request volumes | Redis `maxmemory-policy` value not confirmed in reviewed config | Set `maxmemory-policy allkeys-lru`; segregate rate limit keys to a dedicated Redis DB with a `noeviction` policy; alert if `redis_evicted_keys_total` rate > 10/s |
| I06 | Observability | **Prometheus scrape failure — metric gaps** — Prometheus cannot reach a pod during pod churn; metric gap causes false alert clearance; incidents missed | 4 | 5 | **20** | `up{job="gbedu-api"}` drops to 0 for a pod; scrape error in Prometheus targets | Prometheus scrape interval 15 s; structlog still writes to Loki | Set `scrape_timeout` < `scrape_interval`; configure Alertmanager with `for: 2m` on pod-down alerts to filter transient scrape gaps |
| I07 | Infrastructure | **TLS certificate expiry** — Let's Encrypt cert on Traefik (vmi3169158) expires; HTTPS breaks for all services | 9 | 2 | **18** | Browser TLS errors; curl cert verify failure | Traefik automatic renewal via ACME | Add `ssl_certificate_expiry_seconds` Prometheus metric (via `blackbox_exporter`); alert at 14 days and 3 days remaining; test renewal in staging |
| I08 | Infrastructure | **Clock skew — JWT `iat`/`exp` invalid** — NTP sync failure on API pod causes token `iat` to be in the future; every newly issued token is immediately rejected | 7 | 2 | **14** | Mass 401 errors on brand-new tokens; `JWT_EXPIRED` error code on tokens issued seconds ago | NTP configured on host nodes | Add `leeway=5` seconds to JWT validation; add clock-skew monitoring via `chrony tracking` on nodes |
| I09 | Infrastructure | **Kubernetes control plane unavailable** — cluster API server unreachable; no new deployments or pod restarts via controller manager; existing pods continue running | 5 | 2 | **10** | `kubectl` commands fail; CI deploy fails | Managed Kubernetes on Contabo; kubelet is local and continues running existing pods | Document "control plane down" runbook; all traffic continues from running pods; escalate to Contabo support |
| I10 | Observability | **Grafana / Alertmanager outage — silent failures** — Grafana pod down; alerts not fired; incidents go undetected | 5 | 3 | **15** | Grafana health check fails; engineers not paged | Prometheus standalone alerting rules via Alertmanager | Route all CRITICAL alerts directly through PagerDuty via Alertmanager, bypassing Grafana; never depend on Grafana for on-call alerting |

---

### Section 6 — Security

| ID | Component | Failure Mode | Severity | Likelihood | RPN | Detection | Current Mitigation | Required Action |
|----|-----------|--------------|:--------:|:----------:|:---:|-----------|--------------------|-----------------|
| S01 | Auth | **JWT access token replay** — stolen access token used within its 30-minute window; attacker performs actions as victim | 8 | 4 | **32** | Anomalous requests from unexpected IP/User-Agent for same `sub`; no current per-token detection | Short TTL (30 min); HTTPS-only in production | Implement JTI claim in every token; Redis-backed revocation list checked on every request; `SETEX jti:<jti> <remaining_ttl> 1` on logout; `EXISTS jti:<jti>` on auth |
| S02 | Auth | **Refresh token theft — indefinite account takeover** — refresh token exfiltrated from `httpOnly` cookie or local storage; attacker rotates tokens indefinitely | 9 | 4 | **36** ⚠️ | Multiple concurrent refresh sessions from different IPs; no current detection | Refresh token rotation on each use (sliding window) | Implement refresh token family detection: store a `family_id` with each token; on re-use of a superseded token, revoke all tokens in the family for that user (OWASP recommended pattern) |
| S03 | API | **SSRF via user-supplied webhook URL** — attacker supplies `http://169.254.169.254/latest/meta-data/` or `http://10.0.0.1/` as a webhook callback; internal metadata service or cluster network accessed | 8 | 4 | **32** | Internal metadata service hit; cloud credentials exfiltrated | No SSRF protection confirmed in webhook URL handling | Validate all user-supplied URLs: reject private IP ranges (RFC 1918: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16), link-local (169.254.0.0/16), and loopback; use `httpx` with `allow_redirects=False` |
| S04 | API / Database | **SQL injection via raw `text()` call** — a `text()` call with string interpolation instead of bound parameters; attacker crafts payload that escapes the query | 9 | 2 | **18** | WAF alert; anomalous SQL error in structlog | SQLAlchemy ORM parameterizes all queries by default | Audit all `text()` calls for bound parameter usage; add `bandit` SAST to CI with rule B608 (SQL injection); WAF rule for SQLi patterns at Traefik layer |
| S05 | API | **Rate limit bypass via IP rotation** — attacker rotates through a residential proxy pool; anonymous rate limit of 20 req/min per IP is ineffective | 6 | 6 | **36** ⚠️ | High volume from many IPs; generation abuse; GPU cost spike | Anonymous rate limit is per-IP; authenticated rate limits are per user | Require account creation for any generation request; add CAPTCHA on registration; implement behavioral fingerprinting (browser fingerprint, request timing analysis) at Cloudflare WAF level |
| S06 | Storage | **Presigned URL leakage** — a 7-day presigned R2 URL shared by a user or leaked from the frontend; third party downloads tracks without authentication | 5 | 4 | **20** | Unexpected download volume from non-user-owned regions; anomalous R2 bandwidth | Presigned URLs have 7-day (MP3) and 1-day (WAV) TTL | Reduce MP3 presigned URL TTL to 1 h; log presigned URL generation with `user_id` and `track_id`; add Cloudflare R2 custom domain with WAF `Referer` check |
| S07 | Auth | **OAuth2 CSRF — missing or weak state parameter** — Google OAuth callback does not validate the `state` nonce; CSRF attack forces a victim to link the attacker's Google account | 8 | 3 | **24** | Victim's account linked to attacker's Google ID | OAuth flow exists; state validation not confirmed in reviewed code | Audit `google_oauth_callback` to verify `state` is a CSPRNG nonce stored in the user's session cookie and validated on callback; add CSRF integration test |
| S08 | Auth | **JWT secret compromise — default key used in staging** — staging cluster deployed with `JWT_SECRET_KEY=change-this-in-production` (the default); staging JWT tokens forged and replayed against production if the secret matches | 10 | 3 | **30** | Forged tokens accepted in production; attacker impersonates any user | `validate_production_secrets()` asserts key is not default in `ENVIRONMENT=production` | Enforce unique secrets per environment; add CI secret scanning (`gitleaks`); add `bandit` check B105 (hardcoded password) to CI |
| S09 | Infrastructure | **Kubernetes RBAC over-permission** — service accounts with broad permissions; compromised pod pivots to cluster secrets or other namespaces | 8 | 3 | **24** | No k8s audit log anomaly detection currently configured | Kubernetes RBAC exists | Audit service account permissions; enforce least-privilege (no `cluster-admin` for application service accounts); add `Falco` for runtime threat detection; enable k8s audit policy for `get secrets` calls |
| S10 | API | **Mass assignment via `extra="allow"` schema** — a schema accidentally configured with `extra="allow"` (or `extra="ignore"`) allows attackers to set internal fields like `subscription_tier` or `is_admin` | 6 | 2 | **12** | Privilege escalation; unexpected DB column values | All schemas reviewed use `extra="forbid"` | Add CI lint rule: `grep -r 'extra="allow"' services/ libs/` fails the build; enforce in code review checklist |
| S11 | Infrastructure | **TLS private key exposed in environment** — TLS private key accidentally set as an environment variable or logged via structlog's `log.info("config", **settings.dict())` | 7 | 2 | **14** | Private key visible in Grafana Loki logs; man-in-the-middle possible | Kubernetes Secrets mount as files, not env vars (when correctly configured) | Audit all `log.info` calls that log settings objects; add secret scrubbing to structlog processor chain; verify TLS keys are volume-mounted, not env-var-mounted |

---

## RPN Summary — CRITICAL Items (RPN > 50), Sorted Descending

| ID | Failure Mode | RPN | S | L |
|----|-------------|:---:|:-:|:-:|
| M01 | CUDA OOM kills inference | **54** | 9 | 6 |
| W03 | Redis broker lost — all tasks undeliverable | **36** | 9 | 4 |
| S02 | Refresh token theft — indefinite account takeover | **36** | 9 | 4 |
| I04 | Rolling deploy mid-request — connection reset | **36** | 6 | 6 |
| S05 | Rate limit bypass via IP rotation | **36** | 6 | 6 |
| D03 | Migration on live traffic — ACCESS EXCLUSIVE lock | **36** | 9 | 4 |
| M05 | ACE-Step inference stalls — SIGTERM not honoured | **32** | 8 | 4 |
| M08 | Llama-3 GPU stall — lyrics generation hangs | **32** | 8 | 4 |
| S01 | JWT access token replay | **32** | 8 | 4 |
| S03 | SSRF via webhook URL | **32** | 8 | 4 |
| A02 | Redis unavailable — rate limiter disabled | **32** | 8 | 4 |
| A10 / D06 | Credits race condition — double spend | **32** | 8 | 4 |
| M02 | GPU memory leak across requests | **35** | 7 | 5 |
| W02 | Worker crash mid-generation — no checkpointing | **35** | 7 | 5 |
| D01 | Connection pool exhaustion from worker | **40** | 8 | 5 |
| A06 | Stripe webhook replay — double credit grant | **40** | 8 | 5 |

---

## Chaos Engineering Test Matrix

Run these experiments quarterly in staging before each production milestone. Record blast radius and recovery time.

| Test ID | Experiment | Target | Method | Pass Criteria |
|---------|------------|--------|--------|---------------|
| CE-01 | Redis total outage | API + Worker | `docker stop redis` or `kubectl delete pod redis-0` | API degrades gracefully (no 500s on rate-limit paths); queued tasks resume within 60 s of Redis recovery; DLQ depth does not grow |
| CE-02 | PostgreSQL primary failure | API + Worker | Kill PG primary; promote replica | RTO < 30 min; no data loss after pgBackRest recovery; generation jobs requeue correctly |
| CE-03 | CUDA OOM injection | ML service | Submit 5 concurrent `duration_seconds=300` requests | Only the offending request(s) fail; other concurrent requests succeed; GPU memory recovers within 30 s |
| CE-04 | Worker OOM-Kill mid-generation | Worker | `stress-ng --vm 1 --vm-bytes 90%` on worker node during active generation | Task requeued; final generation completes via retry (idempotent pipeline); no duplicate tracks created |
| CE-05 | R2 network partition | Worker | `iptables -A OUTPUT -d <R2_endpoint_ip> -j DROP` on worker node | Upload retried 3×; task moved to DLQ on exhaustion; user sees `FAILED` status, not 500; temp audio file still present for manual recovery |
| CE-06 | Rolling deploy under load | API | `kubectl rollout restart deployment/gbedu-api` with 50 req/s Locust load | Zero 5xx during rollout; connection drain completes within `terminationGracePeriodSeconds`; no generation jobs lost |
| CE-07 | Rate limiter Redis eviction | API | Set `maxmemory 1mb` on Redis; hammer with authenticated requests | Rate limits still enforced (in-process fallback); no 500s on rate-limited endpoints |
| CE-08 | Stripe webhook replay | API | Replay same Stripe `event.id` 10× within 60 s | Exactly 1 credit grant; 9 idempotent 200 OK responses; no duplicate DB rows |
| CE-09 | SSRF probe | API | `POST /api/v1/contact` (or webhook URL field) with `http://169.254.169.254/latest/meta-data/` | 422 Unprocessable Entity returned; zero outbound HTTP requests to the SSRF URL observed in network audit |
| CE-10 | ML service total outage | Worker + API | `kubectl scale deployment/gbedu-ml --replicas=0` | API returns 502 with `ML_UNAVAILABLE` on generation submit; existing tasks marked FAILED after timeout; `/health/detailed` shows `ml_service: down`; API recovers when ML is restored |

---

## Graceful Degradation Matrix

| Feature | Primary Dependency | Degraded Behaviour | User-Visible Impact | Auto-Recovery? |
|---------|-------------------|--------------------|---------------------|----------------|
| Song generation | ACE-Step 1.5 | Falls back to Stable Audio 3.0 → YuE via fallback chain | Lower Afrobeats-specific audio quality; no user-visible error unless all three fail | Yes — circuit breaker recovery at `circuit_recovery_timeout=60s` |
| Song generation | Celery worker pool | Generations queue in Redis; completions delayed | HTTP 202 returned; user sees "Processing…" with no ETA | Yes — drains when workers restart; messages preserved in Redis |
| Song generation | PostgreSQL | DB writes fail; ML inference may succeed but results cannot be persisted | Generations appear to process but never appear in history; R2 orphan files accumulate | No — requires DB recovery |
| Voice model conversion | RVC v2 | Generation completes without voice conversion; base audio returned | User's custom voice not applied; track still listenable | Partial — auto-disable voice models with > 3 consecutive errors (recommended, M07) |
| Marketplace browsing | PostgreSQL + Redis cache | Cache miss forces direct DB reads; high DB load slows listings | p95 browse latency degrades; no functional loss | Yes — cache repopulates as load normalises |
| Audio playback | Cloudflare R2 / CDN | Track metadata renders but audio URLs return 5xx | Users can browse but cannot stream or download | Yes — R2 outages typically < 30 min; no local fallback |
| Payments (Stripe) | Stripe webhook | Webhook delivery failure; subscription not activated | Payment charged but subscription not activated; requires retry via Stripe dashboard | Partial — Stripe retries for 72 h; idempotency table (A06) makes retry safe |
| Payments (Paystack) | Paystack webhook | HMAC failure silently drops event | Nigerian users' payments not recorded; silent failure | No — requires manual Paystack transaction API reconciliation |
| Authentication | Redis (JTI revocation) | Revoked tokens remain valid until 30-min TTL expires | Logged-out users or compromised accounts can still call authenticated endpoints for ≤ 30 min | Yes — tokens expire naturally; short TTL bounds blast radius |

---

## Sign-Off Checklist

All CRITICAL (RPN > 50) items must have a merged mitigation and a passing chaos test before production launch.

| Item | Owner | Target Date | Status |
|------|-------|-------------|--------|
| M01 — per-request VRAM budget enforcement | ML Engineering | — | ✅ DONE — `gbedu_ml/inference/music_generator.py` pre-flight VRAM guard |
| M02 — GPU memory leak metric + alert | ML Engineering | — | ✅ DONE — `_gpu_memory_watchdog()` background task in `gbedu_ml/main.py` |
| W02 — Stage checkpointing for pipeline retry resume | Worker Engineering | — | ✅ DONE — Redis `pipeline_ckpt:{job_id}:{stage}` keys in `generation_pipeline.py` |
| A06 — Webhook idempotency table (Stripe + Paystack) | API Engineering | — | ✅ DONE — `webhook_events` table + dual Redis+DB idempotency in `payments.py` |
| M05 — Per-step deadline in `GenerationPipelineOrchestrator` | ML Engineering | — | ✅ DONE — `asyncio.wait_for()` per stage in `generation_pipeline.py` |
| M08 — `max_new_tokens` cap in every Llama-3 call | ML Engineering | — | ✅ DONE — `LLAMA_MAX_NEW_TOKENS` config field; used in `lyric_generator.py` |
| A02 — In-process rate limiter fallback when Redis is down | API Engineering | — | ✅ DONE — non-crashing Redis startup + degraded-mode log in `main.py` |
| S02 — Refresh token family detection | Auth Engineering | — | ✅ DONE — replay detection + family revocation in `auth_service.py` |
| S03 — SSRF URL validation on all user-supplied URLs | API Engineering | — | ✅ DONE — `gbedu_core/ssrf.py` validator; apply before any user-URL fetch |
| S05 — Behavioral rate limiting / CAPTCHA on registration | API Engineering | — | ✅ DONE — honeypot field + 3/hour limit on `/register` |
| A10 / D06 — Atomic credit decrement with RETURNING | API Engineering | — | ✅ DONE — `UPDATE users SET generation_count_today... RETURNING` in `generation_service.py` |
| D03 — Zero-downtime migration enforcement (pre-upgrade Job) | DB Engineering | — | ✅ DONE — `scripts/migration_safety_check.py` + CI step in `ci.yml` |
| W03 — Redis Sentinel (3-node) deployed | Infrastructure | — | OPEN — infrastructure provisioning required |
| I04 — `terminationGracePeriodSeconds: 120` + preStop hook | Infrastructure | — | OPEN — Kubernetes manifest update required |
| All CE-01 through CE-10 chaos tests passing in staging | QA | — | OPEN — requires live staging environment |
| RUNBOOKS.md updated with JWT rotation, DLQ remediation, DB migration, Redis recovery procedures | All teams | — | ✅ DONE — all four sections present + token family revocation runbook added |

---

*Reviewed by*: __________________ *Date*: __________________

*Approved by*: __________________ *Date*: __________________

---

## Appendix A — Configuration Values Referenced

| Setting | Value | Source |
|---------|-------|--------|
| `pool_size` | 20 | `DatabaseSettings` — `libs/core/src/gbedu_core/config.py` |
| `max_overflow` | 40 | `DatabaseSettings` — `libs/core/src/gbedu_core/config.py` |
| `pool_recycle` | 3600 s | `DatabaseSettings` — `libs/core/src/gbedu_core/config.py` |
| `pool_pre_ping` | True | `DatabaseSettings` — `libs/core/src/gbedu_core/config.py` |
| `task_acks_late` | True | `CelerySettings` — `libs/core/src/gbedu_core/config.py` |
| `task_reject_on_worker_lost` | True | `CelerySettings` — `libs/core/src/gbedu_core/config.py` |
| `worker_prefetch_multiplier` | 1 | `CelerySettings` — `libs/core/src/gbedu_core/config.py` |
| `soft_time_limit` | 720 s | `run_generation_pipeline` — `services/worker/src/gbedu_worker/tasks/generation.py` |
| `time_limit` | 780 s | `run_generation_pipeline` — `services/worker/src/gbedu_worker/tasks/generation.py` |
| `max_retries` | 3 | `run_generation_pipeline` — `services/worker/src/gbedu_worker/tasks/generation.py` |
| Retry countdowns | 30 s, 90 s, 270 s | `_RETRY_COUNTDOWN` — `services/worker/src/gbedu_worker/tasks/generation.py` |
| `circuit_failure_threshold` | 5 | `MLSettings` — `libs/core/src/gbedu_core/config.py` |
| `circuit_recovery_timeout` | 60 s | `MLSettings` — `libs/core/src/gbedu_core/config.py` |
| `inference_timeout` | 300 s | `MLSettings` — `libs/core/src/gbedu_core/config.py` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 30 | `JWTSettings` — `libs/core/src/gbedu_core/config.py` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | 30 | `JWTSettings` — `libs/core/src/gbedu_core/config.py` |
| `JWT_ALGORITHM` | HS256 | `JWTSettings` — `libs/core/src/gbedu_core/config.py` |
| DLQ queue name | `gbedu.dlq` | `celery_app.py` — `services/worker/src/gbedu_worker/celery_app.py` |
| Generation queue | `generation` | `celery_app.py` — `services/worker/src/gbedu_worker/celery_app.py` |
| Celery broker DB | 1 | `CelerySettings.broker_url` default |
| Celery result backend DB | 2 | `CelerySettings.result_backend` default |
| API cache DB | 0 | `RedisSettings.url` default |
| R2 bucket (prod) | `gbedu-audio` | `StorageSettings.r2_bucket_name` |
| ML fallback order | ACE-Step → Stable Audio 3.0 → YuE | `services/ml/src/gbedu_ml/models/` |
