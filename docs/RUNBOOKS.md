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
