# Gbẹdu — CLAUDE.md

AI-powered Afrobeats music generation platform. Four Python services + one Next.js frontend, all wired together with Celery, Postgres, Redis, and Cloudflare R2.

Goal: a new engineer is productive within 30 minutes. Read this top-to-bottom once, then start coding.

---

## Project structure

```
afrobeat/
├── libs/
│   ├── core/              # gbedu-core — shared models, config, DB, auth, telemetry
│   │   └── src/gbedu_core/
│   │       ├── _uuid7.py          # uuid7str() shim
│   │       ├── config.py          # pydantic-settings Settings class
│   │       ├── db.py              # SQLAlchemy async engine + session factory
│   │       ├── errors.py          # domain exception hierarchy
│   │       ├── health.py          # /health + /ready response models
│   │       ├── logging.py         # structlog configuration
│   │       ├── security.py        # JWT encode/decode, password hashing
│   │       ├── telemetry.py       # OpenTelemetry tracer + meter setup
│   │       ├── models/            # SQLAlchemy ORM models
│   │       └── schemas/           # Pydantic request/response schemas
│   └── audio/             # gbedu-audio — audio DSP pipeline
│       └── src/gbedu_audio/
│           ├── analysis.py        # BPM, key, loudness analysis
│           ├── conversion.py      # format conversion (wav→mp3, etc.)
│           ├── effects.py         # reverb, compression, EQ
│           ├── mastering.py       # loudness normalization, limiting
│           ├── pipeline.py        # composable processing pipeline
│           └── separation.py     # stem separation (vocals/drums/bass)
│
├── services/
│   ├── api/               # gbedu-api — FastAPI HTTP service (:8000)
│   │   └── src/gbedu_api/
│   │       ├── main.py            # app factory, lifespan, middleware
│   │       ├── deps.py            # FastAPI dependency providers
│   │       ├── middleware/        # rate limiting, request ID, CORS
│   │       ├── routers/           # auth, tracks, generations, payments, ...
│   │       └── services/          # business logic (auth, generation, storage, ...)
│   ├── ml/                # gbedu-ml — ML inference service (:8001)
│   │   └── src/gbedu_ml/
│   ├── worker/            # gbedu-worker — Celery task queue
│   │   └── src/gbedu_worker/
│   └── web/               # Next.js 14 frontend (:3000)
│       └── src/
│
├── infra/
│   ├── k8s/               # Kubernetes manifests (staging + prod)
│   └── monitoring/        # Prometheus config, Grafana dashboards
│
├── tests/
│   ├── unit/              # Fast unit tests, no I/O, no containers
│   └── integration/       # Tests that need Postgres + Redis
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── API.md
│   ├── RUNBOOKS.md
│   └── FINE_TUNING.md
│
├── docker-compose.yml     # Full local stack
├── docker-compose.override.yml  # Local dev overrides (hot reload, etc.)
├── Makefile               # All common tasks
└── pyproject.toml         # uv workspace root
```

---

## Service map

| Service | Port | Role |
|---------|------|------|
| `api` | 8000 | FastAPI — auth, tracks, generations, payments, marketplace |
| `ml` | 8001 | FastAPI — ACE-Step inference, lyrics generation, RVC voice |
| `worker` | — | Celery — async generation pipeline, email, webhooks |
| `web` | 3000 | Next.js 14 — user-facing UI |
| `postgres` | 5432 | Primary relational store |
| `redis` | 6379 | Celery broker (db 1), results (db 2), cache (db 0) |
| `localstack` | 4566 | Local S3 emulation (Cloudflare R2 in prod) |
| `prometheus` | 9090 | Metrics scraping |
| `grafana` | 3001 | Dashboards |

---

## Running locally

### First-time setup

```bash
cp .env.example .env          # fill in JWT_SECRET_KEY at minimum
make install                  # uv sync --all-packages
make dev                      # installs pre-commit hooks too
```

### Start everything

```bash
make docker-up                # postgres, redis, localstack, all services
# OR spin up only infra + run services locally for hot-reload:
make docker-up-infra          # postgres, redis, localstack
make api                      # uvicorn with --reload on :8000
make ml                       # uvicorn with --reload on :8001
make worker                   # celery worker, 4 concurrency
make web                      # next dev on :3000
```

### Check health

```bash
curl http://localhost:8000/health
curl http://localhost:8001/health
```

### View logs

```bash
make docker-logs              # tail all services
docker compose logs -f api    # single service
```

---

## Python coding standards (mandatory)

### Tabs, not spaces

Every Python file uses tabs. The ruff config enforces `indent-style = "tab"`. Never use spaces.

### async/await throughout

All I/O — DB queries, HTTP calls, file operations — must be async. No `requests`, no `psycopg2`, no sync SQLAlchemy calls.

### Modern typing

```python
# Good
def process(name: str | None, tags: list[str]) -> dict[str, Any]: ...

# Bad
def process(name: Optional[str], tags: List[str]) -> Dict[str, Any]: ...
```

### Pydantic v2

```python
from pydantic import BaseModel, ConfigDict, Field
from typing import Annotated
from pydantic.functional_validators import AfterValidator

class TrackCreate(BaseModel):
	model_config = ConfigDict(extra="forbid", validate_by_name=True)

	title: str = Field(min_length=1, max_length=200)
	genre: str
	bpm: Annotated[int, AfterValidator(lambda v: v if 60 <= v <= 200 else (_ for _ in ()).throw(ValueError("BPM out of range")))]
```

### UUID7 IDs

```python
from gbedu_core._uuid7 import uuid7str
from pydantic import Field

class Track(BaseModel):
	id: str = Field(default_factory=uuid7str)
```

### structlog everywhere

```python
import structlog
log = structlog.get_logger()

async def create_track(data: TrackCreate) -> Track:
	log.info("track.create.start", title=data.title, genre=data.genre)
	...
	log.info("track.create.done", track_id=track.id)
```

Never use `print()` or the stdlib `logging` module directly.

### Error handling

```python
# Good
try:
	result = await db.execute(stmt)
except SQLAlchemyError as e:
	log.error("db.query.failed", error=str(e))
	raise DatabaseError("query failed") from e

# Bad
try:
	...
except Exception:   # bare except — forbidden
	pass
```

### External calls: retry + circuit breaker

```python
from tenacity import retry, stop_after_attempt, wait_exponential
from circuitbreaker import circuit

@circuit(failure_threshold=5, recovery_timeout=30)
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
async def call_ml_service(payload: dict) -> dict:
	...
```

### Runtime assertions

```python
async def process_track(track_id: str, user_id: str) -> None:
	assert track_id, "track_id must not be empty"
	assert user_id, "user_id must not be empty"
	...
```

### OpenTelemetry tracing

```python
from gbedu_core.telemetry import get_tracer

tracer = get_tracer(__name__)

async def generate_track(request: GenerationRequest) -> Generation:
	with tracer.start_as_current_span("generate_track") as span:
		span.set_attribute("track.genre", request.genre)
		...
```

---

## Testing

### Running tests

```bash
make test-unit          # tests/unit/ + libs/core/tests/ — fast, no containers
make test-integration   # tests/integration/ + services/ — needs docker-up-infra
make test               # everything
make test-cov           # with HTML coverage report
```

### Specific subsets

```bash
uv run pytest tests/unit/ -vxs                     # stop on first failure
uv run pytest tests/unit/ -k "test_auth"           # filter by name
uv run pytest services/api/tests/ -vxs             # single service
uv run pytest --co -q                              # dry-run: list collected tests
```

### Coverage requirement

gbedu-core and gbedu-audio must maintain >= 90% coverage. CI enforces this with `--cov-fail-under=90`.

### Test conventions

- No mocks. Use real objects, real DB (via fixtures), pytest-httpserver for external HTTP.
- Integration tests are marked `@pytest.mark.integration`.
- Read-only prod smoke tests are marked `@pytest.mark.integration and @pytest.mark.readonly`.
- Async tests: plain `async def test_foo():` — no `@pytest.mark.asyncio` decorator needed (`asyncio_mode = "auto"`).
- DB fixtures: use the `db_session` fixture from `tests/conftest.py` which wraps each test in a transaction and rolls back.

```python
async def test_create_track(db_session, api_client):
	resp = await api_client.post("/api/v1/tracks", json={"title": "Test", "genre": "afrobeats"})
	assert resp.status_code == 201
	assert resp.json()["title"] == "Test"
```

---

## Type checking

```bash
make typecheck          # uv run pyright libs/ services/
```

Pyright runs in strict mode. All functions must be fully annotated. `Any` is allowed only where genuinely necessary (e.g., JSON deserialization boundary).

---

## Linting and formatting

```bash
make lint               # ruff check + ruff format --check
make format             # ruff format + ruff check --fix (auto-fix)
```

Pre-commit hooks run lint + format on every commit. If the hook fires, run `make format` and re-commit.

---

## Database

### Running migrations

```bash
make migrate                        # alembic upgrade head
make migrate-gen msg="add_stems"    # generate a new migration
make migrate-down                   # downgrade one step
```

Migrations live in `libs/core/src/gbedu_core/migrations/`. Every migration must be reversible (implement `downgrade()`).

### Zero-downtime migration rules

1. Never drop a column in the same migration that removes code using it — two-phase: deprecate column → remove code → remove column.
2. Always add columns as nullable or with a server default first.
3. Index creation: use `CREATE INDEX CONCURRENTLY` (add `postgresql_concurrently=True` in Alembic).
4. See `docs/RUNBOOKS.md` § "Database migration procedure" for the full checklist.

---

## ML models

Models are downloaded lazily on first inference request from HuggingFace Hub. They are cached at `/models/` inside the `ml` container (a persistent volume in production).

```
ACE-Step 1.5       — music generation backbone
Llama-3 8B (SFT)  — Afrobeats lyrics generation
RVC v2             — voice conversion / artist voice cloning
```

Force a pre-download:

```bash
docker compose exec ml python -c "from gbedu_ml.models import preload_all; import asyncio; asyncio.run(preload_all())"
```

See `docs/FINE_TUNING.md` for updating model weights.

---

## Adding a new API endpoint

Follow the router → service → test pattern:

1. **Schema** — add request/response Pydantic models to `libs/core/src/gbedu_core/schemas/`.
2. **Router** — add a new route function in the appropriate router file under `services/api/src/gbedu_api/routers/`. Wire the router in `main.py` if it's new.
3. **Service** — add business logic in `services/api/src/gbedu_api/services/`. Keep routers thin — no SQL in routers.
4. **Test** — add a test in `services/api/tests/`. Use the `api_client` fixture and real DB session.
5. **Docs** — update `docs/API.md` with the new endpoint, request/response schema, and error codes.

Example skeleton:

```python
# services/api/src/gbedu_api/routers/tracks.py
from fastapi import APIRouter, Depends
from gbedu_core.schemas.track import TrackCreate, TrackOut
from gbedu_api.deps import get_current_user, get_db
from gbedu_api.services.track_service import TrackService
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/tracks", tags=["tracks"])

@router.post("/", response_model=TrackOut, status_code=201)
async def create_track(
	body: TrackCreate,
	user = Depends(get_current_user),
	db = Depends(get_db),
) -> TrackOut:
	svc = TrackService(db)
	track = await svc.create(body, owner_id=user.id)
	log.info("track.created", track_id=track.id, user_id=user.id)
	return track
```

---

## Adding a new Celery task

All tasks must be idempotent — they may be retried multiple times.

1. Add the task function in `services/worker/src/gbedu_worker/tasks/`.
2. Decorate with `@celery_app.task(bind=True, max_retries=3, acks_late=True)`.
3. Use `task.request.id` as an idempotency key — store progress in Redis with TTL 24h.
4. On unrecoverable failure, move the message to the DLQ (`gbedu.dlq`) via `task.update_state(state="DEAD")` and alert via Sentry.
5. Add a unit test that calls the task function directly (not via `.delay()`).

```python
@celery_app.task(bind=True, max_retries=3, acks_late=True, queue="generation")
def generate_audio_task(self, generation_id: str) -> None:
	assert generation_id, "generation_id required"
	idempotency_key = f"task:generate:{generation_id}"
	...
```

---

## Secrets

All secrets come from environment variables via `gbedu_core.config.Settings` (pydantic-settings). Never hardcode secrets or read them with `os.environ[]` directly — always go through `Settings`.

In CI: secrets live in GitHub Actions repository secrets. In staging/prod: injected via Kubernetes Secrets. Locally: `.env` file (never committed — in `.gitignore`).

---

## Skill routing table

| Task | Skill |
|------|-------|
| React/Next.js | `vercel-react-best-practices` |
| UI/UX | `web-design-guidelines` |
| API design | `api-design-principles` |
| Python async | `async-python-patterns` |
| FastAPI | `fastapi-templates` |
| PostgreSQL schema | `postgresql-table-design` |
| SQL optimization | `sql-optimization-patterns` |
| LangChain/LangGraph | `langchain-architecture` |
| Diagrams | `mermaid-diagrams` |

---

## Required GitHub secrets

| Secret | Where used |
|--------|-----------|
| `STAGING_KUBECONFIG` | deploy-staging workflow |
| `PROD_KUBECONFIG` | deploy-prod workflow |
| `SLACK_WEBHOOK_URL` | all deploy + security workflows |
| `CODECOV_TOKEN` | CI coverage upload |

---

## Common gotchas

- **Tabs vs spaces**: ruff enforces tabs. If your editor inserts spaces, configure it now. VSCode: set `editor.insertSpaces: false` for Python.
- **asyncpg + SQLAlchemy**: always use `async with db.begin():` for transactions. Never call `.commit()` manually inside a service — the dependency provider owns the transaction boundary.
- **Celery task serialization**: all task arguments must be JSON-serializable primitives (str, int, float, list, dict). No Pydantic models, no UUIDs — convert to str first.
- **ML service cold start**: on first request the ML service downloads ~15GB of model weights. The Kubernetes liveness probe has a 10-minute `initialDelaySeconds`. Don't reduce this.
- **R2 vs LocalStack**: `ENVIRONMENT=development` routes storage through LocalStack. `ENVIRONMENT=production` routes through Cloudflare R2. The `storage_service.py` handles this transparently via the `R2_ENDPOINT_URL` setting.
