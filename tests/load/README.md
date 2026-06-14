# Gbẹdu Load & Chaos Testing

Two complementary tools: **Locust** for HTTP load testing and **k6** for pre-deploy smoke tests. Chaos scenarios live under `tests/chaos/`.

---

## Locust load tests

### Install

```bash
uv add --dev locust
# or
pip install locust
```

### Run (interactive UI)

```bash
locust -f tests/load/locustfile.py --host http://localhost:8000
```

Open `http://localhost:8089`, enter user count and spawn rate, then start.

### Run (headless, automated)

```bash
# 60-user sustained run for 5 minutes, CSV output
locust -f tests/load/locustfile.py \
	--host http://localhost:8000 \
	--headless \
	--users 60 \
	--spawn-rate 5 \
	--run-time 5m \
	--csv tests/load/results/run_$(date +%Y%m%d_%H%M%S)

# Use the built-in StagesShape (ignores --users/--spawn-rate)
locust -f tests/load/locustfile.py \
	--host http://localhost:8000 \
	--headless \
	--run-time 15m \
	--csv tests/load/results/stages
```

### User classes

| Class | Weight | Wait | Description |
|-------|--------|------|-------------|
| `AnonymousUser` | 40 | 1–5 s | Public tracks feed, marketplace browse, health checks |
| `AuthenticatedUser` | 50 | 3–10 s | Register → login → submit generation → poll → list tracks |
| `PowerUser` | 10 | 3–10 s | All of the above + voice model listing + marketplace listing creation |

### Load shape (`StagesShape`)

| Phase | Wall time | Users | Spawn rate |
|-------|-----------|-------|------------|
| Ramp-up | 0–2 min | 0 → 50 | 0.5/s |
| Steady state | 2–8 min | 50 | — |
| Spike | 8–10 min | 50 → 200 | 3/s |
| Stress | 10–12 min | 200 | — |
| Wind-down | 12–14 min | 200 → 0 | 5/s |

### Custom metrics

Two custom metrics are emitted via Locust's `events.request.fire`:

- `generation_submission_time` — wall-clock ms from POST to 202 response
- `generation_poll_count` — number of poll iterations per generation lifecycle (stored as ms so it appears in the stats table; divide by 1000 to get actual count)

---

## k6 smoke test

A single-VU, 30-second sanity check intended to run before every deploy.

### Install k6

```bash
# macOS
brew install k6

# Docker
docker pull grafana/k6
```

### Run

```bash
# Against local stack
k6 run tests/load/smoke.js

# Against staging
k6 run --env BASE_URL=https://staging.api.gbedu.io tests/load/smoke.js

# Via Docker
docker run --rm -i --network host grafana/k6 run - < tests/load/smoke.js
```

### What it checks

1. `GET /api/v1/health` — 200 in < 100 ms (p95)
2. `POST /api/v1/auth/register` — 201, access token present, < 1 s (p95)
3. `POST /api/v1/generations` — 202, job ID present, initial status is pending/queued/running
4. `GET /api/v1/generations/{id}` — polls up to 10 × 5 s until terminal state
5. `GET /api/v1/generations` — list returns array with `total >= 1`
6. `GET /api/v1/marketplace/beats` — public browse returns 200 with items array

Thresholds (CI will fail if breached):

| Metric | Threshold |
|--------|-----------|
| `health_latency_ms` | p95 < 100 ms |
| `registration_latency_ms` | p95 < 1 000 ms |
| `generation_submit_latency_ms` | p95 < 2 000 ms |
| `http_req_failed` | rate < 1 % |
| `generation_reached_terminal` | rate > 0 |

---

## Chaos engineering

### Start Toxiproxy

```bash
docker run -d --name toxiproxy \
	-p 8474:8474 \
	-p 5433:5433 \
	-p 6380:6380 \
	shopify/toxiproxy
```

The Toxiproxy admin API listens on `:8474`. Proxies must be created once before scenarios run:

```bash
# Create proxies via the Toxiproxy CLI (inside the container)
docker exec toxiproxy /toxiproxy-cli create postgres \
	--listen 0.0.0.0:5433 --upstream localhost:5432

docker exec toxiproxy /toxiproxy-cli create redis \
	--listen 0.0.0.0:6380 --upstream localhost:6379
```

Or POST them via the REST API directly — the `ToxiproxyClient` in `scenarios.py` handles toxic injection; proxy creation is a one-time setup step.

### Configure the API to use proxied ports

Set these environment variables before starting `gbedu-api` and `gbedu-worker`:

```bash
export DATABASE_URL="postgresql+asyncpg://gbedu:gbedu@localhost:5433/gbedu"
export REDIS_URL="redis://localhost:6380/0"
```

### Run chaos scenarios

```bash
uv run python tests/chaos/scenarios.py
```

Scenarios run sequentially; each cleans up its toxics in a `finally` block so a mid-scenario crash does not leave the proxy in a broken state.

### Scenario summary

| Scenario | Toxic | Duration | Pass criterion |
|----------|-------|----------|----------------|
| `scenario_db_latency` | Postgres latency 500 ms ± 50 ms | 30 s of requests | p99 response time < 2 000 ms |
| `scenario_redis_down` | Redis bandwidth → 0 (hard disconnect) | 20 requests | Zero HTTP 500 responses (503/504/429 acceptable) |
| `scenario_ml_timeout` | ML service timeout (70 s) | Up to 65 s polling | Generation job reaches `status=failed` |

### Toxiproxy preset reference (`tests/chaos/toxiproxy.json`)

| Preset | Proxy | Type | Effect |
|--------|-------|------|--------|
| `db_latency` | postgres | latency | +200 ms downstream, 10 % jitter |
| `db_packet_loss` | postgres | limit_data | 1 % toxicity (random packet drop) |
| `db_timeout` | postgres | timeout | Drop connection after 5 s |
| `redis_latency` | redis | latency | +50 ms downstream |
| `redis_disconnect` | redis | bandwidth | Rate = 0 (full disconnect) |

Apply a preset manually:

```bash
curl -s -X POST http://localhost:8474/proxies/postgres/toxics \
	-H "Content-Type: application/json" \
	-d '{
		"name": "db_latency",
		"type": "latency",
		"stream": "downstream",
		"toxicity": 1.0,
		"attributes": {"latency": 200, "jitter": 20}
	}'

# Remove it
curl -s -X DELETE http://localhost:8474/proxies/postgres/toxics/db_latency
```

---

## CI integration

Add to `.github/workflows/ci.yml` after the unit test job:

```yaml
smoke-test:
  needs: [test-unit]
  runs-on: ubuntu-latest
  services:
    postgres:
      image: postgres:16
      env: { POSTGRES_DB: gbedu, POSTGRES_USER: gbedu, POSTGRES_PASSWORD: gbedu }
      options: >-
        --health-cmd pg_isready
        --health-interval 5s --health-timeout 5s --health-retries 10
    redis:
      image: redis:7
      options: >-
        --health-cmd "redis-cli ping"
        --health-interval 5s --health-timeout 5s --health-retries 10
  steps:
    - uses: actions/checkout@v4
    - uses: grafana/setup-k6-action@v1
    - name: Start API
      run: |
        cp .env.example .env
        uv run uvicorn gbedu_api.main:app --port 8000 &
        sleep 5
      env:
        DATABASE_URL: postgresql+asyncpg://gbedu:gbedu@localhost:5432/gbedu
        REDIS_URL: redis://localhost:6379/0
    - name: k6 smoke
      run: k6 run tests/load/smoke.js
```
