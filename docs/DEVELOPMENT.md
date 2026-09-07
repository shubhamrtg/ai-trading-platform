# Development Guide

## Prerequisites

- Python 3.12 or higher
- Docker and Docker Compose
- Git
- PostgreSQL 16 (if running without Docker)

## Local Setup

### Option 1: Docker (Recommended)

```bash
# Copy environment template
cp .env.example .env

# Build and start all services
docker-compose up --build

# Application will be available at http://localhost:8000
# API docs at http://localhost:8000/docs
```

### Option 2: Local Development

```bash
# Create virtual environment
cd backend
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Activate (Linux/Mac)
source .venv/bin/activate

# Install dependencies (including dev tools)
pip install -e ".[dev]"

# Start PostgreSQL (via Docker if needed)
docker-compose up db redis -d

# Run the application
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Environment Variables

All configuration is managed through environment variables. See `.env.example` for the complete list.

Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `TRADING_MODE` | `BACKTEST` | Trading mode: BACKTEST, PAPER, LIVE |
| `DATABASE_URL` | (required) | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LOG_FORMAT` | `json` | Log format: json or console |
| `DEBUG` | `false` | Enable debug mode |

### Live Trading Safety

Live trading requires **three** environment variables to be set:

```bash
TRADING_MODE=LIVE
LIVE_TRADING_ENABLED=true
LIVE_TRADING_CONFIRMATION=I_UNDERSTAND_REAL_MONEY_IS_AT_RISK
```

All three must be present and correct. Missing any one prevents live trading.

## Running Tests

```bash
cd backend

# Run all tests
pytest -v

# Run with coverage
pytest --cov=app --cov-report=term-missing

# Run specific test file
pytest tests/test_health.py -v

# Run specific test
pytest tests/test_config.py::test_default_mode_is_backtest -v
```

Tests use an in-memory SQLite database by default — no external services needed.

## Database Migrations

```bash
cd backend

# Create a new migration
alembic revision --autogenerate -m "description of change"

# Apply migrations
alembic upgrade head

# Rollback one step
alembic downgrade -1
```

## Code Style

The project uses:
- **Ruff** for linting and formatting
- **mypy** for type checking

```bash
# Lint
ruff check .

# Format
ruff format .

# Type check
mypy app/
```

## Project Conventions

1. **Type hints** — All function signatures should have type annotations
2. **Pydantic models** — Use for all API request/response schemas
3. **Async by default** — Use async functions for I/O operations
4. **Structured logging** — Use `structlog` bound loggers, not print statements
5. **Tests required** — Every feature must have corresponding tests

## API Documentation

FastAPI auto-generates interactive API docs:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Git Workflow

Use descriptive commit messages:

```
feat: add strategy plugin interface
fix: correct position sizing calculation
test: add risk engine edge cases
docs: update architecture diagram
```
