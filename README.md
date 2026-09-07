# AI Trading Platform

A production-grade, AI-assisted automated trading platform built with safety-first principles.

## ⚠️ Safety First

- **Default mode: BACKTEST** — No real money is ever at risk by default
- **Live trading is disabled** unless explicitly enabled through multiple safety gates
- The system **fails closed** — if anything is misconfigured, no trades are placed
- The **Risk Engine has final authority** over every trade decision

## Overview

This platform enables:

1. **Strategy Development** — Create and test trading strategies via a plugin system
2. **Backtesting** — Validate strategies against historical data with realistic simulation
3. **Paper Trading** — Test strategies against live market data with simulated capital
4. **AI Analysis** — Optional AI layer for market regime detection and signal filtering
5. **Risk Management** — Deterministic risk engine with configurable safety limits
6. **Live Trading** — Controlled, broker-connected trading (only after all validation gates pass)

## Architecture

```
Market Data → Strategy Engine → Trade Signal → AI Filter → Risk Engine → Execution → Broker
```

Every component (strategy, AI, broker, execution) is independently replaceable.

See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for full details.

## Trading Modes

| Mode | Data Source | Execution | Real Money |
|------|-----------|-----------|------------|
| BACKTEST | Historical | Simulated | No |
| PAPER | Live | Simulated | No |
| LIVE | Live | Real Broker | Yes |

## Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose
- Git

### Setup

```bash
# Clone the repository
git clone <repository-url>
cd ai-trading-platform

# Copy environment template
cp .env.example .env

# Start with Docker Compose
docker-compose up --build

# Or run locally
cd backend
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

### Verify

```bash
# Health check
curl http://localhost:8000/health

# System status
curl http://localhost:8000/api/v1/system/status
```

### Run Tests

```bash
cd backend
pytest -v
```

## Project Structure

```
ai-trading-platform/
├── backend/              # Python backend (FastAPI)
│   ├── app/
│   │   ├── api/          # REST endpoints
│   │   ├── config/       # Configuration management
│   │   ├── models/       # Database models
│   │   ├── schemas/      # Pydantic schemas
│   │   ├── services/     # Business logic
│   │   ├── market_data/  # Market data providers
│   │   ├── strategies/   # Strategy engine
│   │   ├── backtesting/  # Backtesting engine
│   │   ├── execution/    # Order execution
│   │   ├── brokers/      # Broker adapters
│   │   ├── risk/         # Risk management
│   │   ├── portfolio/    # Portfolio management
│   │   ├── ai/           # AI provider abstraction
│   │   ├── notifications/# Notification service
│   │   ├── monitoring/   # Health & metrics
│   │   └── audit/        # Audit logging
│   └── tests/
├── frontend/             # React/Next.js dashboard
├── strategies/           # Strategy plugins
├── data/                 # Market data storage
├── config/               # Configuration files
├── docs/                 # Documentation
├── scripts/              # Utility scripts
├── docker/               # Docker build files
└── notebooks/            # Jupyter notebooks
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Development Guide](docs/DEVELOPMENT.md)

## Technology Stack

- **Backend**: Python 3.12+, FastAPI, SQLAlchemy, Pydantic
- **Database**: PostgreSQL, Redis
- **Frontend**: React, Next.js, TypeScript (Milestone 9)
- **AI**: Provider abstraction (Gemini, OpenAI, Mock)
- **Infrastructure**: Docker, Docker Compose

## License

MIT License — see [LICENSE](LICENSE) for details.

## Disclaimer

This is a software engineering project. Past performance (backtested or paper-traded) does not guarantee future returns. All trading decisions and live deployment decisions are the operator's responsibility. Never risk money you cannot afford to lose.
