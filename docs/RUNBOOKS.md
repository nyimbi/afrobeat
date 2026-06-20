# Gbẹdu — Operational Runbooks

All commands assume you have `kubectl` configured for the target cluster. For staging: `--context staging-cluster`. For prod: `--context prod-cluster`. Omit the flag to use whichever context is currently active.

---

## On-call escalation paths

| Severity | Response time | Owner | Contact |
|----------|--------------|-------|---------|
| P0 — full outage | 15 min | On-call engineer | PagerDuty primary |
| P1 — degraded (ML down, payments down) | 30 min | On-call engineer | PagerDuty secondary |
| P2 — non-critical feature broken | 4 hours | Engineering team | Slack #incidents |
| P3 — cosmetic / minor | Next business day | Assigned engineer | GitHub issue |

Slack channels: `#incidents` (P0/P1 auto-alerts), `#deploys` (deploy notifications), `#security` (security scan alerts).

---

## Incident response checklist

### 1. Acknowledge and assess

```bash
# Check pod status across all services
kubectl get pods -n gbedu-prod

# Check recent events for crash loops or OOMKilled
kubectl get events -n gbedu-prod --sort-by='.lastTimestamp' | tail -30

# Check deployment rollout history
kubectl rollout history deployment/gbedu-api -n gbedu-prod
```

### 2. Identify blast radius

- Is the web UI returning errors? → Check `gbedu-api` and `gbedu-web` pods.
- Are generations failing? → Check `gbedu-worker` and `gbedu-ml` pods.
- Are payments failing? → Check `gbedu-api` Stripe/Paystack logs, verify webhook delivery.
- Is the database unreachable? → Check Postgres pod and connection pool metrics in Grafana.

### 3. Check logs

```bash
# Tail logs for a specific service (replace api with worker/ml/web)
kubectl logs -f deployment/gbedu-api -n gbedu-prod --tail=100

# All pods for a service
kubectl logs -l app=gbedu-api -n gbedu-prod --tail=100 --prefix

# Previous crashed container (for OOMKilled / crash loop)
kubectl logs deployment/gbedu-api -n gbedu-prod --previous
```

### 4. Check metrics

Open Grafana: `http://vmi3171558:3001` (credentials in 1Password → Grafana Prod).

Key dashboards:
- **Gbedu Overview** — request rate, error rate, p99 latency per service
- **ML Service** — GPU utilisation, model load time, inference queue depth
- **Celery** — task queue depth, success/failure rate, task duration
- **Postgres** — connection pool, query time, lock waits
- **Redis** — memory usage, hit/miss rate, command latency

### 5. Resolve or escalate

If the cause is clear, apply the fix from the relevant runbook section below.
If cause is unclear after 20 minutes of investigation, escalate to P0 and pull in a second engineer.

### 6. Post-incident

Write a brief incident summary in Slack `#incidents` within 24 hours:
- What broke and when
- Root cause
- Fix applied
- Follow-up tasks (link GitHub issues)

---

## ML service GPU OOM recovery

Symptom: `gbedu-ml` pod shows `OOMKilled` in `kubectl describe pod`. GPU memory exhausted, usually from a concurrent generation request that exceeded model VRAM budget.

### Immediate recovery

```bash
# Confirm OOMKilled
kubectl describe pod -l app=gbedu-ml -n gbedu-prod | grep -A5 "Last State"

# Pod will restart automatically. Watch it come back.
kubectl rollout status deployment/gbedu-ml -n gbedu-prod --timeout=600s

# Verify health once restarted
curl https://ml.gbedu.com/health
```

### If pod restart loop continues

```bash
# Check current memory limits
kubectl get deployment gbedu-ml -n gbedu-prod -o jsonpath='{.spec.template.spec.containers[0].resources}'

# Temporarily disable concurrent generation to reduce load
# Set max concurrent inference to 1 via env var patch
kubectl set env deployment/gbedu-ml -n gbedu-prod MAX_CONCURRENT_GENERATIONS=1

# Watch rollout
kubectl rollout status deployment/gbedu-ml -n gbedu-prod
```

### Drain inflight tasks to prevent re-triggering

```bash
# Connect to redis and inspect the generation queue
kubectl exec -it deployment/gbedu-api -n gbedu-prod -- redis-cli -u "$REDIS_URL" LLEN celery.generation

# Pause the generation queue temporarily
kubectl exec -it deployment/gbedu-worker -n gbedu-prod -- celery -A gbedu_worker.celery_app inspect active
kubectl exec -it deployment/gbedu-worker -n gbedu-prod -- celery -A gbedu_worker.celery_app control cancel_consumer generation
```

### Root cause investigation

After recovery, check whether a single large model or batch caused the OOM. The ML service logs model loading and peak VRAM usage per request:

```bash
kubectl logs -l app=gbedu-ml -n gbedu-prod --since=1h | grep "vram_peak_mb"
```

If VRAM usage is trending upward, a memory leak may be present in the model loading path. File an issue with the log snippet.

---

## Database migration procedure (zero-downtime)

Never run migrations during peak traffic. Schedule for low-traffic periods (02:00–05:00 Lagos time, UTC+1).

### Pre-migration checklist

- [ ] Migration script has been reviewed by a second engineer
- [ ] `downgrade()` is implemented and tested locally
- [ ] Migration is additive only (new tables, new nullable columns, new indexes)
- [ ] No `DROP COLUMN` or `NOT NULL` constraints added to existing columns
- [ ] Large table migrations use `CREATE INDEX CONCURRENTLY`
- [ ] Backup confirmed recent (within 6h, see pgBackRest below)

### Verify latest backup

```bash
# SSH to db server
ssh root@62.84.181.55
sudo -u postgres pgbackrest --stanza=gbedu info
# Confirm latest full or incremental backup timestamp
```

### Run migration

```bash
# From your local machine with DB access tunnelled or from the API pod
kubectl exec -it deployment/gbedu-api -n gbedu-prod -- \
  uv run --package gbedu-core alembic upgrade head

# Or via make (locally, with prod DATABASE_URL exported)
DATABASE_URL="postgresql+asyncpg://..." make migrate
```

### Verify migration applied

```bash
kubectl exec -it deployment/gbedu-api -n gbedu-prod -- \
  uv run --package gbedu-core alembic current
```

### If migration fails mid-run

```bash
# Check which revision failed
kubectl exec -it deployment/gbedu-api -n gbedu-prod -- \
  uv run --package gbedu-core alembic current

# Roll back one step
kubectl exec -it deployment/gbedu-api -n gbedu-prod -- \
  uv run --package gbedu-core alembic downgrade -1

# Investigate the error in the migration script, fix, and re-run
```

### Post-migration

- [ ] Run `make test-integration` against staging to confirm no regressions
- [ ] Monitor Grafana — Postgres query time dashboard — for 15 minutes after migration
- [ ] Update migration log comment in the Alembic file with the date applied

---

## Rollback procedure

### Automatic rollback (deploy pipeline)

The `deploy-prod.yml` workflow automatically runs `kubectl rollout undo` if the smoke test fails. No manual intervention needed unless the rollback itself fails.

### Manual rollback

```bash
# Check rollout history to find the previous good revision
kubectl rollout history deployment/gbedu-api -n gbedu-prod

# Roll back to the immediately previous revision
kubectl rollout undo deployment/gbedu-api -n gbedu-prod

# Roll back to a specific revision number (e.g. revision 5)
kubectl rollout undo deployment/gbedu-api -n gbedu-prod --to-revision=5

# Roll back all services at once
for svc in gbedu-api gbedu-worker gbedu-ml gbedu-web; do
  kubectl rollout undo deployment/$svc -n gbedu-prod
done

# Wait for all rollbacks to complete
for svc in gbedu-api gbedu-worker gbedu-ml gbedu-web; do
  kubectl rollout status deployment/$svc -n gbedu-prod --timeout=300s
done
```

### Verify health after rollback

```bash
curl https://api.gbedu.com/health
curl https://ml.gbedu.com/health
```

---

## Celery queue backup and drain

### Inspect queue state

```bash
# Queue depths
kubectl exec -it deployment/gbedu-worker -n gbedu-prod -- \
  celery -A gbedu_worker.celery_app inspect reserved

# Active tasks
kubectl exec -it deployment/gbedu-worker -n gbedu-prod -- \
  celery -A gbedu_worker.celery_app inspect active

# Dead letter queue depth
kubectl exec -it deployment/gbedu-api -n gbedu-prod -- \
  redis-cli -u "$REDIS_URL" LLEN gbedu.dlq
```

### Drain a queue (stop accepting new tasks, finish current)

```bash
# Cancel consumer for a specific queue
kubectl exec -it deployment/gbedu-worker -n gbedu-prod -- \
  celery -A gbedu_worker.celery_app control cancel_consumer generation

# Re-enable after maintenance
kubectl exec -it deployment/gbedu-worker -n gbedu-prod -- \
  celery -A gbedu_worker.celery_app control add_consumer generation
```

### Purge a queue (discard all pending tasks — use only in emergencies)

```bash
# Dry-run: count tasks that would be purged
kubectl exec -it deployment/gbedu-api -n gbedu-prod -- \
  redis-cli -u "$REDIS_URL" LLEN celery.generation

# Actually purge (irreversible)
kubectl exec -it deployment/gbedu-worker -n gbedu-prod -- \
  celery -A gbedu_worker.celery_app purge -Q generation --force
```

### Inspect and retry dead letter queue

```bash
# View dead tasks (stored as JSON in Redis list gbedu.dlq)
kubectl exec -it deployment/gbedu-api -n gbedu-prod -- \
  redis-cli -u "$REDIS_URL" LRANGE gbedu.dlq 0 9

# Manually retry a specific generation (by generation_id)
kubectl exec -it deployment/gbedu-worker -n gbedu-prod -- \
  python -c "
from gbedu_worker.celery_app import celery_app
from gbedu_worker.tasks.generation import generate_audio_task
generate_audio_task.apply_async(args=['GENERATION_ID_HERE'])
"
```

---

## Model update procedure (new LoRA / SFT weights)

Use this procedure whenever deploying updated ML model weights without a full service redeploy. See `docs/FINE_TUNING.md` for how to train the weights.

### Prerequisites

- New weights uploaded to R2 at `gbedu-models/{model_name}/{version}/`
- Model evaluated against benchmark set (see FINE_TUNING.md § Evaluation)
- Rollback path confirmed: previous weights still present in R2

### Staging validation

```bash
# Patch staging ML service to load new weights
kubectl set env deployment/gbedu-ml -n gbedu-staging \
  ACE_STEP_LORA_PATH=s3://gbedu-models/ace-step/v1.2/lora.safetensors

# Watch the pod restart and load new weights (can take 2-5 min)
kubectl rollout status deployment/gbedu-ml -n gbedu-staging --timeout=600s

# Run a test generation on staging
curl -X POST https://staging-api.gbedu.com/api/v1/generations \
  -H "Authorization: Bearer $STAGING_TEST_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"genre": "afrobeats", "bpm": 128, "key": "A minor", "mood": "euphoric"}'
```

Listen to the output. If quality is acceptable, proceed to production.

### Production deployment

```bash
# Update model path in prod
kubectl set env deployment/gbedu-ml -n gbedu-prod \
  ACE_STEP_LORA_PATH=s3://gbedu-models/ace-step/v1.2/lora.safetensors

# Wait for rollout
kubectl rollout status deployment/gbedu-ml -n gbedu-prod --timeout=600s

# Health check
curl https://ml.gbedu.com/health
```

### Rollback model weights

```bash
kubectl set env deployment/gbedu-ml -n gbedu-prod \
  ACE_STEP_LORA_PATH=s3://gbedu-models/ace-step/v1.1/lora.safetensors

kubectl rollout status deployment/gbedu-ml -n gbedu-prod --timeout=600s
```

---

## Secrets rotation

### JWT secret rotation (zero-downtime, two-phase)

JWT secret rotation requires a two-phase approach to avoid invalidating active sessions.

**Phase 1 — add new secret, keep old valid:**

```bash
# Generate new secret (32 bytes, base64)
NEW_SECRET=$(openssl rand -base64 32)
echo "New secret: $NEW_SECRET"  # store in 1Password immediately

# Update Kubernetes secret with both old and new (API reads BOTH during transition)
kubectl create secret generic gbedu-jwt \
  -n gbedu-prod \
  --from-literal=JWT_SECRET_KEY="$NEW_SECRET" \
  --from-literal=JWT_SECRET_KEY_PREV="$CURRENT_SECRET" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl rollout restart deployment/gbedu-api -n gbedu-prod
kubectl rollout status deployment/gbedu-api -n gbedu-prod --timeout=120s
```

**Phase 2 — 24h later (all old tokens expired), remove old secret:**

```bash
kubectl create secret generic gbedu-jwt \
  -n gbedu-prod \
  --from-literal=JWT_SECRET_KEY="$NEW_SECRET" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl rollout restart deployment/gbedu-api -n gbedu-prod
```

### Stripe webhook secret rotation

1. In the Stripe dashboard, add a new webhook endpoint secret.
2. Update `STRIPE_WEBHOOK_SECRET` in the Kubernetes secret.
3. Restart the API pod.
4. Verify a test webhook delivery succeeds in Stripe dashboard.
5. Remove the old webhook secret from Stripe.

### Database password rotation

1. Generate new password: `openssl rand -base64 24`
2. Create the new Postgres user/password (do not drop old user yet):
   ```sql
   ALTER USER gbedu PASSWORD 'new-password-here';
   ```
3. Update `DATABASE_URL` in Kubernetes secrets.
4. Rolling restart all services that connect to Postgres (api, worker, ml):
   ```bash
   for svc in gbedu-api gbedu-worker gbedu-ml; do
     kubectl rollout restart deployment/$svc -n gbedu-prod
     kubectl rollout status deployment/$svc -n gbedu-prod --timeout=120s
   done
   ```
5. Verify all services healthy. Monitor Postgres connection errors in Grafana for 10 minutes.

### R2 access key rotation

1. Generate new R2 key pair in Cloudflare dashboard.
2. Update `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY` in Kubernetes secrets.
3. Rolling restart `gbedu-api` and `gbedu-worker`.
4. Verify an upload and download succeed.
5. Revoke old R2 key in Cloudflare dashboard.

### Refresh token family revocation (FMEA S02)

**When to use:** `auth.refresh_token_replay_detected` CRITICAL log appears — a refresh token that was already used (rotated) was presented again. This indicates a stolen token was replayed.

**What happened automatically:** The API already set `refresh_family_revoked:{user_id}` in Redis with a 30-day TTL. The affected user's refresh tokens are all invalidated immediately — any subsequent `/auth/refresh` call returns 401.

**Operator actions:**

```bash
# Confirm the revocation key is set (replace USER_ID with the UUID from the log)
USER_ID="<user-id-from-log>"
kubectl exec -it deployment/redis -n gbedu-prod -- \
  redis-cli GET "refresh_family_revoked:${USER_ID}"
# Should return "1"

# Check what IP triggered the replay (grep structlog for the event)
kubectl logs -l app=gbedu-api -n gbedu-prod --since=1h | \
  grep "refresh_token_replay_detected" | grep "${USER_ID}"

# If the incident is confirmed theft, also revoke any active access tokens by
# updating the user's JWT version (requires a DB migration or admin endpoint).
# For now, access tokens expire in 30 minutes — no further action needed unless
# the access token lifetime is too long for the risk profile.
```

**User impact:** The affected user must log in again. Their active session is terminated. Notify them via email if the security event appears malicious (recommend password change).

---

## Postgres backup verification

Run monthly or after any infrastructure change.

```bash
# SSH to db server
ssh root@62.84.181.55

# List recent backups
sudo -u postgres pgbackrest --stanza=gbedu info

# Test restore to scratch (non-destructive — restores to a test path)
sudo -u postgres pgbackrest --stanza=gbedu \
  --pg1-path=/var/lib/postgresql/17/test_restore \
  restore --delta --target-action=promote

# Connect to the restored DB and run a sanity query
sudo -u postgres psql -p 5433 -d gbedu -c "SELECT COUNT(*) FROM users;"

# Clean up test restore
sudo rm -rf /var/lib/postgresql/17/test_restore
```

Expected: restore completes without errors, user count is reasonable.

---

## Disaster Recovery Scenarios

### DR-1: PostgreSQL Primary Failure

**Detection:** Prometheus alert `PostgresPrimaryDown` fires, or `pg_replication_slots_pg_wal_lsn_diff > 0` sustained for 5m. Confirm via API `/ready` returning 503 with `db` component unhealthy.

**Immediate response:**

```bash
# Check replication lag on hot standby (run on standby server: 144.91.112.190)
ssh root@144.91.112.190
sudo -u postgres psql -c "SELECT now() - pg_last_xact_replay_timestamp() AS replication_lag;"

# Verify API health — look for db component
curl https://api.gbedu.com/ready
```

**Promote standby to primary:**

```bash
# On standby server (144.91.112.190)
sudo -u postgres pg_ctl promote -D /var/lib/postgresql/17/main
# Confirm promotion
sudo -u postgres psql -c "SELECT pg_is_in_recovery();"
# Should return: f (false = now primary)
```

**Update DATABASE_URL and restart services:**

```bash
# Edit the Kubernetes secret — update DATABASE_URL host to 144.91.112.190
kubectl edit secret gbedu-secrets -n gbedu

# Rolling restart API and worker to pick up new DATABASE_URL
kubectl rollout restart deployment/gbedu-api deployment/gbedu-worker -n gbedu
kubectl rollout status deployment/gbedu-api deployment/gbedu-worker -n gbedu --timeout=120s

# Verify health
curl https://api.gbedu.com/ready
```

**Data loss assessment (run on former primary if still reachable):**

```bash
# How many WAL bytes were not replicated at time of failure
sudo -u postgres psql -c "
  SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS unsynced_bytes
  FROM pg_stat_replication;
"
```

| Target | Value |
|--------|-------|
| RTO | 5 minutes |
| RPO | 0 (synchronous replication) or < 30s (async) |

---

### DR-2: Redis Cluster Failure

**Detection:** `redis_connected_clients == 0` for 1m, or all Celery workers show idle with no task throughput.

**Impact assessment:**
- Rate limiting fails open — traffic continues to be served (no immediate user impact)
- Session tokens may be unverifiable until Redis recovers — users may be force-logged out
- Quota counters (daily generation limits) reset to 0 — users effectively get a fresh daily quota

**Restart Redis:**

```bash
kubectl rollout restart deployment/redis -n gbedu
kubectl rollout status deployment/redis -n gbedu --timeout=60s
```

**If data is corrupt and a clean slate is required:**

```bash
# DESTRUCTIVE — quota counters reset, active sessions invalidated
kubectl exec -it deployment/redis -n gbedu -- redis-cli FLUSHALL
```

After FLUSHALL: quota counters reset to 0 (users get fresh daily quota), all sessions require re-login. Alert the team in `#incidents` before doing this.

| Target | Value |
|--------|-------|
| RTO | 2 minutes |
| RPO | Non-critical — all Redis data is ephemeral or reconstructable from Postgres |

---

### DR-3: Celery Worker Deadlock / Queue Saturation

**Detection:** `celery_queue_length{queue="generation"} > 100` sustained for 5m, or generations are accepted but never complete.

**Inspect active and stuck tasks:**

```bash
kubectl exec -it deployment/gbedu-worker -n gbedu -- \
  celery -A gbedu_worker.celery_app inspect active

kubectl exec -it deployment/gbedu-worker -n gbedu -- \
  celery -A gbedu_worker.celery_app inspect reserved
```

**Revoke a specific stuck task:**

```bash
kubectl exec -it deployment/gbedu-worker -n gbedu -- \
  celery -A gbedu_worker.celery_app control revoke <task_id> --terminate
```

**Drain the generation queue without processing (emergency only — tasks are discarded):**

```bash
kubectl exec -it deployment/gbedu-worker -n gbedu -- \
  celery -A gbedu_worker.celery_app purge -Q generation --force
```

**Scale workers to clear a backlog:**

```bash
kubectl scale deployment/gbedu-worker --replicas=10 -n gbedu
# Scale back to normal after backlog clears
kubectl scale deployment/gbedu-worker --replicas=3 -n gbedu
```

**Inspect the dead letter queue:**

```bash
kubectl exec -it deployment/gbedu-api -n gbedu -- \
  redis-cli -u "$REDIS_URL" LRANGE gbedu.dlq 0 9
```

---

### DR-4: R2 Storage Unavailability

**Detection:** API returns 502 on track upload or download endpoints; `gbedu_storage_errors_total` counter spikes in Grafana.

**Impact:** New uploads fail with 502. Presigned URLs for existing tracks continue to work (served by Cloudflare CDN edge cache, not R2 directly).

**Check Cloudflare status first:**

```
https://www.cloudflarestatus.com
```

**Production mitigation (queue uploads for replay):**

When R2 is unavailable, the `storage_service.py` fallback queues failed uploads as Celery tasks with `retry_failed_distributions` task name. Once R2 recovers:

```bash
# Verify R2 is back
aws s3 ls s3://gbedu-models/ --endpoint-url https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com

# Trigger retry of queued upload tasks
kubectl exec -it deployment/gbedu-worker -n gbedu -- \
  celery -A gbedu_worker.celery_app call gbedu_worker.tasks.storage.retry_failed_distributions
```

**Development only — local disk fallback (never use in production):**

```bash
# Routes storage through local filesystem — NOT production-safe
kubectl set env deployment/gbedu-api -n gbedu STORAGE_BACKEND=local
```

Revert immediately once R2 recovers: `kubectl set env deployment/gbedu-api -n gbedu STORAGE_BACKEND=r2`.

---

### DR-5: ML Service GPU OOM / Model Corruption

**Detection:** `gbedu_ml_circuit_breaker_state{model="ace_step"} == 1` (circuit breaker open), or `gbedu-ml` pod in `CrashLoopBackOff`.

**Restart the ML pod (clears GPU memory state):**

```bash
kubectl rollout restart deployment/gbedu-ml -n gbedu
kubectl rollout status deployment/gbedu-ml -n gbedu --timeout=600s
curl https://ml.gbedu.com/health
```

**If the pod crashes again on startup (corrupt model cache):**

```bash
# Clear the ACE-Step model cache to force a clean re-download from HF Hub
kubectl exec -it deploy/gbedu-ml -n gbedu -- rm -rf /models/ace-step/

# Then restart — model re-downloads on first request (~15 min cold start)
kubectl rollout restart deployment/gbedu-ml -n gbedu
```

**Model weight rollback (bad weights from a recent fine-tuning deploy):**

```bash
# Previous version is preserved at:
# s3://gbedu-models/ace-step/v1.5-prev.tar.gz
kubectl set env deployment/gbedu-ml -n gbedu \
  ACE_STEP_LORA_PATH=s3://gbedu-models/ace-step/v1.5-prev.tar.gz
kubectl rollout status deployment/gbedu-ml -n gbedu --timeout=600s
```

**Fallback chain:** If circuit breakers for ACE-Step, StableAudio, and YuE are all open simultaneously, the generation endpoint returns HTTP 503 with a user-visible message: `"Generation temporarily unavailable — please try again in a few minutes."` No silent failures.

---

### DR-6: Complete Service Restoration Procedure

Use this when recovering from a full outage (all services down). Restore in dependency order — each step must pass its health check before proceeding to the next.

**Step 1 — PostgreSQL**

```bash
# Confirm Postgres is accepting connections
kubectl exec -it deployment/gbedu-api -n gbedu -- \
  python -c "import asyncpg, asyncio; asyncio.run(asyncpg.connect('$DATABASE_URL'))"
# Or check directly:
kubectl get pods -n gbedu -l app=postgres
```

**Step 2 — Redis**

```bash
kubectl rollout status deployment/redis -n gbedu --timeout=60s
kubectl exec -it deployment/redis -n gbedu -- redis-cli PING
# Expected: PONG
```

**Step 3 — LocalStack (dev) / R2 (prod)**

```bash
# Development
curl http://localhost:4566/_localstack/health

# Production — verify R2 reachability
aws s3 ls s3://gbedu-models/ --endpoint-url https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com
```

**Step 4 — API service**

```bash
kubectl rollout restart deployment/gbedu-api -n gbedu
kubectl rollout status deployment/gbedu-api -n gbedu --timeout=120s
curl https://api.gbedu.com/health   # expect: {"status":"ok"}
curl https://api.gbedu.com/ready    # expect: all components green
```

**Step 5 — Worker service**

```bash
kubectl rollout restart deployment/gbedu-worker -n gbedu
kubectl rollout status deployment/gbedu-worker -n gbedu --timeout=120s
# Verify worker is consuming
kubectl exec -it deployment/gbedu-worker -n gbedu -- \
  celery -A gbedu_worker.celery_app inspect ping
```

**Step 6 — ML service**

```bash
kubectl rollout restart deployment/gbedu-ml -n gbedu
# Allow up to 10 minutes for model weight download on cold start
kubectl rollout status deployment/gbedu-ml -n gbedu --timeout=600s
curl https://ml.gbedu.com/health    # expect: {"status":"ok","models":{...}}
```

**Step 7 — Web frontend**

```bash
kubectl rollout restart deployment/gbedu-web -n gbedu
kubectl rollout status deployment/gbedu-web -n gbedu --timeout=120s
curl -I https://app.gbedu.com       # expect: HTTP 200
```

**Estimated total RTO: 15 minutes** (dominated by ML model load time in step 6).

Post-restoration: run a smoke test generation end-to-end before declaring the incident resolved.

---

### DR-7: Stripe Webhook Backfill

Use this when the API server was down during a period of Stripe activity — missed webhook events mean payments, subscription upgrades, or cancellations may not have been processed.

**Identify the outage window:** note the exact UTC start and end times from PagerDuty or Grafana.

**Replay missed events from Stripe dashboard:**

1. Go to Stripe Dashboard → Developers → Webhooks → select the production endpoint.
2. Filter events by the outage window timestamp range.
3. For each missed event, click "Resend" — or use the CLI:

```bash
# Replay a specific event by ID
stripe events resend evt_XXXXXXXXXXXXXXXXXXXXXXXX

# List events in a time window and replay all (requires stripe CLI + jq)
stripe events list \
  --created[gte]=<unix_timestamp_start> \
  --created[lte]=<unix_timestamp_end> \
  --limit 100 \
  | jq -r '.data[].id' \
  | xargs -I{} stripe events resend {}
```

**Idempotency guarantee:** All webhook handlers check Redis `SET NX` (set-if-not-exists) using the Stripe event ID as the key before processing. Replaying events is safe — duplicate deliveries are silently deduplicated. No risk of double-charging.

**Verify backfill completed:**

```bash
# Check webhook delivery status in Stripe dashboard — all events should show "Succeeded"
# Also verify in the application DB that payment records match Stripe:
kubectl exec -it deployment/gbedu-api -n gbedu -- \
  python -c "
from gbedu_core.scripts import reconcile_stripe
import asyncio
asyncio.run(reconcile_stripe.run(since_hours=24))
"
```
