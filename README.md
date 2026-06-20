# Gbẹdu

AI-powered Afrobeats and African music generation platform. Describe a sound, get a full song — vocals, instruments, lyrics — in under two minutes.

Four Python services + one Next.js frontend, wired together with Celery, Postgres, Redis, and Cloudflare R2.

---

## Table of Contents

- [What it does](#what-it-does)
- [Architecture overview](#architecture-overview)
- [Service map](#service-map)
- [Quick start](#quick-start)
- [Full local setup](#full-local-setup)
- [Environment variables](#environment-variables)
- [Development workflow](#development-workflow)
- [Testing](#testing)
- [Code standards](#code-standards)
- [Database migrations](#database-migrations)
- [ML models](#ml-models)
- [Lyrics corpus](#lyrics-corpus)
- [Standalone generation script](#standalone-generation-script)
- [Deployment](#deployment)
- [Project structure](#project-structure)

---

## What it does

Gbẹdu takes a text prompt — genre, mood, language, tempo, instrument palette — and runs a multi-step AI pipeline:

1. **Lyrics generation** — Llama-3 8B fine-tuned on Afrobeats, Amapiano, Afro-rumba, Bongo Flava, and other African styles; outputs in English, Pidgin, Yoruba, Igbo, Hausa, Swahili, Lingala, and more.
2. **Music generation** — ACE-Step 1.5 diffusion model, conditioned on genre tags, BPM, and the generated lyrics. Produces a full song with vocals and instrumentation.
3. **Audio post-processing** — `gbedu-audio` DSP pipeline: format normalisation, genre-tuned EQ and compression, loudness normalisation to −14 LUFS, stem separation, 320 kbps MP3 export.
4. **Voice conversion** (optional) — RVC v2 applies a selected artist voice model to the generated vocals.
5. **Distribution** — output is uploaded to Cloudflare R2; signed URLs are returned to the user.

---

## Architecture overview

```
                       ┌──────────────────────────────────────┐
                       │          Cloudflare CDN               │
                       │    (edge cache: audio + web assets)   │
                       └──────────────┬───────────────────────┘
                                      │
             ┌────────────────────────┼──────────────────────┐
             │                        │                      │
      ┌──────▼──────┐         ┌───────▼──────┐      ┌───────▼─────┐
      │  web :3000  │         │  api :8000   │      │  R2 (audio) │
      │  Next.js 14 │◄────────►  FastAPI     │      │  Cloudflare │
      └─────────────┘  REST   └──────┬───────┘      └─────────────┘
                                     │ SQLAlchemy async      ▲
                    ┌────────────────┼───────────────┐       │ S3
                    │                │               │       │
             ┌──────▼──────┐  ┌──────▼──────┐  ┌────▼───────▼──┐
             │  postgres   │  │    redis    │  │    worker     │
             │  :5432      │  │  :6379      │  │   Celery      │
             │  all data   │  │  broker /   │  │  generation   │
             └─────────────┘  │  cache /    │  │  pipeline     │
                              │  results    │  └───────┬───────┘
                              └─────────────┘          │ HTTP
                                                ┌──────▼──────┐
                                                │  ml :8001   │
                                                │  FastAPI    │
                                                │  ACE-Step   │
                                                │  Llama-3 8B │
                                                │  RVC v2     │
                                                └─────────────┘

Observability (all services):
  structlog JSON → Loki │ OpenTelemetry → Tempo │ Prometheus → Grafana
```

Full diagram and rationale: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

---

## Service map

| Service | Port | Tech | Role |
|---------|------|------|------|
| `api` | 8000 | FastAPI | Auth, tracks, generation requests, payments, marketplace |
| `ml` | 8001 | FastAPI | ACE-Step inference, lyrics generation, RVC voice conversion |
| `worker` | — | Celery | Async generation pipeline, email, webhook retry |
| `web` | 3000 | Next.js 14 | User-facing studio UI |
| `postgres` | 5432 | PostgreSQL 16 | Primary relational store |
| `redis` | 6379 | Redis 7 | Celery broker (db 1), results (db 2), cache (db 0) |
| `localstack` | 4566 | LocalStack | Local S3 emulation (Cloudflare R2 in prod) |
| `prometheus` | 9090 | Prometheus | Metrics scraping |
| `grafana` | 3001 | Grafana | Dashboards |

---

## Quick start

> Requires: Python 3.12+, [uv](https://docs.astral.sh/uv/), Docker Desktop (or Colima), Node.js 20+.

```bash
git clone <repo-url> && cd afrobeat
cp .env.example .env          # set JWT_SECRET_KEY at minimum
make install                  # uv sync --all-packages
make docker-up                # starts all 9 containers
```

Check health:

```bash
curl http://localhost:8000/health    # {"status":"ok","version":"0.1.0",...}
curl http://localhost:8001/health    # {"status":"ok","models_loaded":[...],...}
```

Open the UI at `http://localhost:3000`.

---

## Full local setup

### 1. Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.12+ | `brew install python@3.12` or [python.org](https://python.org) |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Docker | 24+ | [docker.com/get-docker](https://www.docker.com/get-docker/) |
| Node.js | 20+ | `brew install node` or [nvm](https://github.com/nvm-sh/nvm) |
| Git | any | system |

### 2. Clone and install

```bash
git clone <repo-url>
cd afrobeat

# Install all Python packages (workspace: gbedu-core, gbedu-audio, gbedu-api, gbedu-worker, gbedu-ml)
make install

# Install git hooks (ruff format + lint on every commit)
make dev
```

### 3. Configure environment

```bash
cp .env.example .env
```

Minimum required values for local development:

```bash
# .env
JWT_SECRET_KEY=any-long-random-string-for-local-dev-only
ENVIRONMENT=development
```

Everything else defaults to local Docker addresses. See [Environment variables](#environment-variables) for the full reference.

### 4. Start infrastructure only

For hot-reload development (code changes reload instantly without rebuilding containers):

```bash
make docker-up-infra           # starts postgres, redis, localstack only

# In separate terminals:
make api                       # uvicorn --reload on :8000
make ml                        # uvicorn --reload on :8001
make worker                    # celery worker, concurrency 4
make web                       # next dev on :3000
```

### 5. Run database migrations

```bash
make migrate                   # alembic upgrade head
```

### 6. Verify everything

```bash
make test-unit                 # ~10s, no containers required
curl http://localhost:8000/health
curl http://localhost:8001/health
```

---

## Environment variables

All configuration is loaded by `gbedu_core.config.Settings` (pydantic-settings). Never read `os.environ` directly — always go through `Settings`.

### Required in all environments

| Variable | Description |
|----------|-------------|
| `JWT_SECRET_KEY` | 256-bit random secret for JWT signing. **Must not be the default in production.** |

### Required in production

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL asyncpg URL |
| `REDIS_URL` | Redis URL for cache (db 0) |
| `CELERY_BROKER_URL` | Redis URL for Celery broker (db 1) |
| `CELERY_RESULT_BACKEND` | Redis URL for Celery results (db 2) |
| `R2_ACCOUNT_ID` | Cloudflare account ID |
| `R2_ACCESS_KEY_ID` | R2 API token key ID |
| `R2_SECRET_ACCESS_KEY` | R2 API token secret |
| `R2_BUCKET_NAME` | R2 bucket for audio files |
| `R2_PUBLIC_URL` | Public CDN base URL for audio |
| `STRIPE_SECRET_KEY` | Stripe live secret key |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret |
| `PAYSTACK_SECRET_KEY` | Paystack live secret key |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `ML_SERVICE_URL` | Internal URL for the ML service |
| `ML_SERVICE_API_KEY` | Shared secret for worker → ML auth |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVIRONMENT` | `development` | `development`, `staging`, `production`, or `test` |
| `LOG_LEVEL` | `INFO` | Structlog log level |
| `GPU_DEVICE` | `cuda` | `cuda`, `mps`, or `cpu` |
| `SENTRY_DSN` | — | Sentry error tracking (omit to disable) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | OpenTelemetry collector |

---

## Development workflow

### Making changes

1. Write failing tests first (`tests/unit/` for logic, `tests/integration/` for DB/API).
2. Implement the change in `libs/` or `services/`.
3. Run `make test-unit` — should be green in < 15 seconds.
4. Run `make lint` and `make typecheck` — all must pass.
5. Commit — pre-commit hook re-runs lint + format automatically.

### Adding a new API endpoint

Follow the router → service → schema → test pattern (full example in [`CLAUDE.md`](CLAUDE.md)):

1. **Schema** — add Pydantic models to `libs/core/src/gbedu_core/schemas/`
2. **Router** — add route function to `services/api/src/gbedu_api/routers/`
3. **Service** — add business logic to `services/api/src/gbedu_api/services/`
4. **Test** — add test to `services/api/tests/`
5. **Docs** — update `docs/API.md`

### Adding a new Celery task

All tasks must be idempotent. See [`CLAUDE.md`](CLAUDE.md) for the full checklist and the DLQ pattern.

### Logs

```bash
make docker-logs                    # tail all containers
docker compose logs -f api          # single service
docker compose logs -f worker ml    # multiple services
```

Logs are structured JSON (structlog). In development they are pretty-printed automatically.

---

## Testing

### Commands

```bash
make test-unit          # tests/unit/ + libs tests — fast, no containers
make test-integration   # needs docker-up-infra
make test               # everything
make test-cov           # with HTML coverage report in htmlcov/
```

### Specific subsets

```bash
uv run pytest tests/unit/ -vxs                      # stop on first failure
uv run pytest tests/unit/ -k "test_auth"            # filter by name
uv run pytest services/api/tests/ -vxs              # single service
uv run pytest --co -q                               # dry-run: list collected tests
```

### Coverage requirements

`gbedu-core` and `gbedu-audio` must maintain ≥ 90% coverage. CI enforces this with `--cov-fail-under=90`.

### Test conventions

- **No mocks** except for LLM and external payment APIs. Use real objects, real DB (via `db_session` fixture), `pytest-httpserver` for external HTTP.
- **Async tests** — write `async def test_foo():`, no `@pytest.mark.asyncio` decorator needed (`asyncio_mode = "auto"`).
- **Integration tests** — mark with `@pytest.mark.integration`. These need Postgres + Redis.
- **DB isolation** — `db_session` fixture wraps each test in a transaction and rolls back on teardown.

---

## Code standards

Full reference in [`CLAUDE.md`](CLAUDE.md). Key rules:

### Tabs, not spaces

```python
# Good — tab-indented
def process(name: str | None) -> dict[str, Any]:
	return {}

# Bad — spaces
def process(name: str | None) -> dict[str, Any]:
    return {}
```

### Async throughout

```python
# Good
async def get_track(db: AsyncSession, track_id: str) -> Track | None:
	result = await db.execute(select(Track).where(Track.id == track_id))
	return result.scalar_one_or_none()

# Bad — sync SQLAlchemy in an async service
def get_track(db: Session, track_id: str) -> Track | None:
	return db.query(Track).filter(Track.id == track_id).first()
```

### Modern typing

```python
# Good
def process(tags: list[str], meta: dict[str, Any]) -> str | None: ...

# Bad
def process(tags: List[str], meta: Dict[str, Any]) -> Optional[str]: ...
```

### UUID7 IDs

```python
from gbedu_core._uuid7 import uuid7str

class Track(BaseModel):
	id: str = Field(default_factory=uuid7str)
```

### Structured logging

```python
import structlog
log = structlog.get_logger()

log.info("track.created", track_id=track.id, user_id=user.id, genre=genre)
```

Never use `print()` or the stdlib `logging` module.

### External calls: retry + circuit breaker

```python
from tenacity import retry, stop_after_attempt, wait_exponential
from circuitbreaker import circuit

@circuit(failure_threshold=5, recovery_timeout=30)
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def call_ml_service(payload: dict) -> dict: ...
```

---

## Database migrations

```bash
make migrate                        # apply all pending migrations
make migrate-gen msg="add_stems"    # generate migration from model changes
make migrate-down                   # roll back one step
```

Migrations live in `libs/core/src/gbedu_core/migrations/`. Every migration must implement `downgrade()`.

### Zero-downtime rules

1. Never drop a column in the same migration that removes the code using it — two phases: deprecate → remove code → remove column.
2. Add columns as `nullable` or with a server default first.
3. Use `CREATE INDEX CONCURRENTLY` (`postgresql_concurrently=True` in Alembic).

Full procedure: `docs/RUNBOOKS.md` § "Database migration procedure".

---

## ML models

Models are downloaded lazily on first inference request from HuggingFace Hub and cached at `/models/` inside the `ml` container.

| Model | Size | Task |
|-------|------|------|
| ACE-Step 1.5 | ~7 GB | Music + vocal generation |
| Llama-3 8B (SFT) | ~4 GB | Afrobeats lyrics generation |
| RVC v2 | varies | Voice conversion per artist |

Pre-download all models (avoids cold start on first request):

```bash
docker compose exec ml python -c \
  "from gbedu_ml.models import preload_all; import asyncio; asyncio.run(preload_all())"
```

Fine-tuning guide: [`docs/FINE_TUNING.md`](docs/FINE_TUNING.md)

---

## Lyrics corpus

A curated corpus of real African song lyrics spanning 5 regions, 15+ languages, and 20+ genres lives in `data/corpus/`. It is used as training and evaluation data for the lyrics generation model.

```
data/corpus/
├── west_africa/        afrobeats, highlife, jùjú, fuji, mbalax, wassoulou
├── central_africa/     soukous, afro-rumba, ndombolo, coupé-décalé
├── east_africa/        bongo flava, benga, taarab, Ethiopian pop
├── southern_africa/    amapiano, kwaito, maskandi, chimurenga
└── north_africa/       raï, gnawa, chaabi
```

Each file is a plain-text document with a structured header and tagged lyric sections. See `data/corpus/README.md` for the format spec and contribution guidelines.

---

## Standalone generation script

`generate_song.py` is a self-contained CLI for generating audio without running the full service stack. Useful for testing model changes, building the training corpus, and quick demos.

```bash
# Instrumental (MusicGen, no dependencies beyond transformers)
python generate_song.py --model medium --duration 30

# Vocals (ACE-Step 1.5 — downloads ~7 GB on first run)
python generate_song.py --vocals --style choir --language pidgin --duration 60
python generate_song.py --vocals --style congolese-choir --steps 60
python generate_song.py --vocals --style soukous --fast    # 20 steps, quicker

# Full Congolese composition: ACE-Step vocals → MusicGen sebene → crossfade stitch → master
python generate_song.py --full
python generate_song.py --full --vocal-duration 90 --sebene-duration 45 --crossfade 5
python generate_song.py --full --fast --no-play
```

Output files land in `/tmp/gbedu_output/`. The `--full` pipeline:

1. ACE-Step generates the vocal section (verse + chorus structure, no bridge).
2. MusicGen generates a sebene instrumental break (fast Congolese guitar, no vocals).
3. `crossfade_stitch()` joins them with a cosine fade (default 3 s).
4. `apply_congolese_master()` applies EQ and limiting tuned for sebene clarity.

Available styles: `choir`, `solo`, `duet`, `congolese-choir`, `soukous`.
Available languages: `english`, `pidgin`, `yoruba`.

---

## Deployment

### Staging

```bash
git push origin main
# GitHub Actions workflow deploys automatically to staging on merge to main
```

### Production

```bash
# After staging verification:
gh workflow run deploy-prod --field version=$(git describe --tags --abbrev=0)
```

Required GitHub Actions secrets: `STAGING_KUBECONFIG`, `PROD_KUBECONFIG`, `SLACK_WEBHOOK_URL`, `CODECOV_TOKEN`.

### Kubernetes

Manifests live in `infra/k8s/`. Each service has a `Deployment`, `Service`, `HorizontalPodAutoscaler`, and `PodDisruptionBudget`.

```bash
kubectl apply -f infra/k8s/staging/    # staging
kubectl apply -f infra/k8s/prod/       # production
```

ML service liveness probe has `initialDelaySeconds: 600` — model weight download on cold start takes up to 10 minutes. Do not reduce this.

Full runbooks: [`docs/RUNBOOKS.md`](docs/RUNBOOKS.md)

---

## Project structure

```
afrobeat/
├── libs/
│   ├── core/               gbedu-core — shared models, config, DB, auth, telemetry
│   │   └── src/gbedu_core/
│   │       ├── _uuid7.py          uuid7str() shim (uses uuid6 package)
│   │       ├── config.py          pydantic-settings Settings class
│   │       ├── db.py              SQLAlchemy async engine + session factory
│   │       ├── errors.py          domain exception hierarchy
│   │       ├── health.py          /health + /ready response models
│   │       ├── logging.py         structlog configuration
│   │       ├── security.py        JWT encode/decode, password hashing
│   │       ├── telemetry.py       OpenTelemetry tracer + meter setup
│   │       ├── models/            SQLAlchemy ORM models
│   │       └── schemas/           Pydantic request/response schemas
│   └── audio/              gbedu-audio — audio DSP pipeline
│       └── src/gbedu_audio/
│           ├── analysis.py        BPM, key, loudness analysis
│           ├── conversion.py      format conversion (wav → mp3, etc.)
│           ├── effects.py         reverb, compression, EQ chains
│           ├── mastering.py       loudness normalisation, limiting
│           ├── pipeline.py        10-step composable processing pipeline
│           └── separation.py      stem separation (vocals/drums/bass)
│
├── services/
│   ├── api/                gbedu-api — FastAPI HTTP service (:8000)
│   │   └── src/gbedu_api/
│   │       ├── main.py            app factory, lifespan, middleware
│   │       ├── deps.py            FastAPI dependency providers
│   │       ├── middleware/        rate limiting, request ID, CORS
│   │       ├── routers/           auth, tracks, generations, payments, ...
│   │       └── services/          business logic (auth, generation, storage, ...)
│   ├── ml/                 gbedu-ml — ML inference service (:8001)
│   ├── worker/             gbedu-worker — Celery task queue
│   └── web/                Next.js 14 frontend (:3000)
│
├── data/
│   └── corpus/             Curated African lyrics corpus (30+ songs, 15+ languages)
│
├── infra/
│   ├── k8s/                Kubernetes manifests (staging + prod)
│   └── monitoring/         Prometheus config, Grafana dashboards
│
├── tests/
│   ├── unit/               Fast unit tests — no I/O, no containers
│   └── integration/        Tests requiring Postgres + Redis
│
├── docs/
│   ├── ARCHITECTURE.md     System diagram, service responsibilities, data flows
│   ├── API.md              Full REST API reference
│   ├── RUNBOOKS.md         Operational runbooks, incident response, deploys
│   └── FINE_TUNING.md      ML model fine-tuning procedures
│
├── generate_song.py        Standalone CLI — instrumental / vocals / full composition
├── docker-compose.yml      Full local stack (9 services)
├── docker-compose.override.yml  Dev overrides (hot reload, volume mounts)
├── Makefile                All common tasks
└── pyproject.toml          uv workspace root
```

---

## Troubleshooting

**`uv sync` fails with tensorflow wheel error**

`basic-pitch` in `gbedu-audio` depends on `tensorflow < 2.16` which has no Python 3.12 wheels. Workaround:

```bash
uv sync --exclude-package gbedu-audio
# Install gbedu-audio without basic-pitch for local dev:
uv pip install -e libs/audio/ --override "basic-pitch; python_version<'3.12'"
```

**ACE-Step / transformers numpy conflict**

ACE-Step requires `transformers >= 5.0` and `tensorflow` must be removed:

```bash
uv pip install "transformers>=5.0"
uv pip uninstall tensorflow
```

**MPS (Apple Silicon) mode**

ACE-Step auto-detects MPS but forces `float32` — MPS does not support `float16`. Inference is ~6× slower than CUDA but functional. Use `--fast` (20 steps) for rapid iteration.

**pytest import collision between `tests/` and `services/ml/tests/`**

If you see `ImportError: module 'tests' already imported`, the fix is already in `pyproject.toml`:

```toml
addopts = "--import-mode=importlib"
```

Make sure `services/ml/tests/__init__.py` does not exist (it was removed).

---

## Licence

Proprietary — © Nyimbi Odero. All rights reserved.
