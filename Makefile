.PHONY: install dev test test-unit test-integration lint typecheck format migrate build docker-up docker-down clean

PYTHON := uv run python
UV := uv

# ── Setup ─────────────────────────────────────────────────────────────────────

install:
	$(UV) sync --all-packages

dev: install
	$(UV) run pre-commit install

# ── Testing ───────────────────────────────────────────────────────────────────

test:
	$(UV) run pytest tests/ libs/core/tests/ libs/audio/tests/ services/api/tests/ services/worker/tests/ services/ml/tests/ -v --tb=short

test-unit:
	$(UV) run pytest tests/ libs/core/tests/ -v --tb=short -m "not integration"

test-integration:
	$(UV) run pytest tests/ libs/core/tests/ libs/audio/tests/ services/api/tests/ services/worker/tests/ services/ml/tests/ -v --tb=short -m integration

test-cov:
	$(UV) run pytest --cov=libs --cov=services --cov-report=html --cov-report=term-missing

# ── Code quality ──────────────────────────────────────────────────────────────

lint:
	$(UV) run ruff check libs/ services/
	$(UV) run ruff format --check libs/ services/

typecheck:
	$(UV) run pyright libs/ services/

format:
	$(UV) run ruff format libs/ services/
	$(UV) run ruff check --fix libs/ services/

# ── Database ──────────────────────────────────────────────────────────────────

migrate:
	$(UV) run --package gbedu-core alembic upgrade head

migrate-gen:
	$(UV) run --package gbedu-core alembic revision --autogenerate -m "$(msg)"

migrate-down:
	$(UV) run --package gbedu-core alembic downgrade -1

# ── Build ─────────────────────────────────────────────────────────────────────

build:
	docker build -t gbedu-api:latest ./services/api
	docker build -t gbedu-worker:latest ./services/worker
	docker build -t gbedu-ml:latest ./services/ml
	cd services/web && npm run build

# ── Docker ────────────────────────────────────────────────────────────────────

docker-up:
	docker compose up -d

docker-up-infra:
	docker compose up -d postgres redis localstack

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

docker-reset:
	docker compose down -v
	docker compose up -d

# ── Dev servers ───────────────────────────────────────────────────────────────

api:
	$(UV) run --package gbedu-api uvicorn gbedu_api.main:app --reload --host 0.0.0.0 --port 8000

worker:
	$(UV) run --package gbedu-worker celery -A gbedu_worker.celery_app worker --loglevel=info --concurrency=4

ml:
	$(UV) run --package gbedu-ml uvicorn gbedu_ml.main:app --reload --host 0.0.0.0 --port 8001

web:
	cd services/web && npm run dev

# ── Clean ─────────────────────────────────────────────────────────────────────

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name htmlcov -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name ".coverage*" -delete 2>/dev/null || true
