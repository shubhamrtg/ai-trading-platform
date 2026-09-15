# Architecture

## System Overview

The AI Trading Platform is a modular, event-driven trading system designed around safety-first principles. Every trading decision flows through a pipeline where the deterministic Risk Engine has final authority.

## Core Data Flow

```
┌──────────────────┐
│   Market Data    │  Historical or live market data
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Strategy Engine  │  Generates trade signals based on indicators
└────────┬─────────┘
         │
    Trade Signal       Structured proposal (instrument, action, stops)
         │
         ▼
┌──────────────────┐
│    AI Engine     │  Optional: regime detection, signal filtering
└────────┬─────────┘
         │
    AI Assessment      Structured response (allow/reject, confidence)
         │
         ▼
┌──────────────────┐
│   Risk Engine    │  FINAL AUTHORITY — enforces all safety limits
│  (Final Authority)│
└────────┬─────────┘
         │
    Order Intent       Only if all risk checks pass
         │
         ▼
┌──────────────────┐
│Execution Engine  │  Routes to appropriate broker
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Broker Adapter   │  Paper broker or real broker
└──────────────────┘
```

## Safety Architecture

### Fail-Closed Design

The system is designed to fail closed. If any component is misconfigured, unavailable, or returns an error, the result is always: **DO NOT TRADE**.

### Trading Mode Isolation

| Mode | Market Data | Execution | Can Place Real Orders |
|------|------------|-----------|----------------------|
| BACKTEST | Historical replay | Simulated fills | No |
| PAPER | Live feed | Simulated broker | No |
| LIVE | Live feed | Real broker | Yes (gated) |

Modes are enforced at the configuration level. There is no code path where PAPER mode can accidentally route to a real broker.

### Live Trading Gates

Live mode requires ALL of the following:
1. `TRADING_MODE=LIVE`
2. `LIVE_TRADING_ENABLED=true`
3. `LIVE_TRADING_CONFIRMATION=I_UNDERSTAND_REAL_MONEY_IS_AT_RISK`

This triple-gate mechanism prevents accidental live trading.

### Decision Authority

```
Strategy proposes → AI advises → Risk Engine decides
```

The Risk Engine can always reject a trade, regardless of what the strategy or AI recommends.

## Component Architecture

### Market Data

Abstraction layer providing normalized OHLCV data regardless of source.

- `MarketDataProvider` (interface)
  - `HistoricalDataProvider` — replay from database/files
  - `PaperMarketDataProvider` — live feed, read-only
  - `LiveMarketDataProvider` — live feed for real trading

All data is normalized to a common `Candle` model with validation for missing data, duplicates, timezone issues, and staleness.

### Strategy Engine

Plugin-based system where strategies implement a standard interface:

```python
class Strategy(ABC, Generic[TParams]):
    metadata: ClassVar[StrategyMetadata]
    parameters_schema: ClassVar[type[TParams]]

    @abstractmethod
    def on_candle(self, candle: Candle, context: StrategyContext) -> SignalDraft | None:
        pass
```

### Strategy Execution Contract

```text
Persisted StrategyVersion
        |
Exact Executable Strategy Binding
        |
Executable Source Identity / Hash Verification
        |
StrategyRunner
        |
SignalDraft
        |
Runtime Signal
```

Strategies produce structured `SignalDraft`s containing deterministic logic only (not direct orders or runtime-dependent signals). They are strictly bound to a `StrategyVersion` persisted in the database via a verifiable source hash (SHA-256 of the executable implementation). The `StrategyRunner` orchestrates state lifecycle, maintains read-only historical context, ensures chronicity of data feeds, and injects runtime orchestration IDs, completely separating strategy logic from execution routing.

### AI Engine

Provider-abstracted AI layer for market analysis.

- `AIProvider` (interface)
  - `MockAIProvider` — deterministic responses for testing
  - `GeminiProvider` — Google Gemini API
  - Future: `OpenAIProvider`, etc.

AI receives structured context and returns structured assessments. AI failures result in configurable fallback behavior (never uncontrolled trading).

### Risk Engine

Deterministic engine with final trade authority. Enforces:

- Maximum risk per trade
- Daily loss limits
- Maximum drawdown
- Position limits
- Exposure limits
- Duplicate order prevention
- Stale data protection
- Kill switch state

### Execution Engine

Routes validated order intents to the appropriate broker adapter.

### Broker Abstraction

```python
class Broker(ABC):
    def get_account(self) -> Account: ...
    def get_positions(self) -> list[Position]: ...
    def place_order(self, order: Order) -> OrderResult: ...
    def cancel_order(self, order_id: str) -> CancelResult: ...
```

- `PaperBroker` — full simulation with fills, fees, slippage
- Future: Real broker adapters

### Portfolio Manager

Maintains authoritative internal state:
- Cash and available capital
- Open positions with P&L
- Exposure and margin
- Periodic reconciliation against broker state

### Backtesting Engine

Event-driven simulator that replays historical data through the full pipeline (strategy → risk → execution). Supports configurable costs, slippage, and partial fills. Strictly prevents look-ahead bias.

## Supporting Systems

### Database (PostgreSQL)

Persistent storage for:
- Strategies and configurations
- Backtests and results
- Signals, orders, fills
- Positions and portfolio snapshots
- Audit events

Managed via Alembic migrations.

### Audit Logging

Every trading decision is fully traceable: signal → AI assessment → risk decision → order → fill → P&L.

### Notifications

Abstracted notification system (email, Slack, webhook) for critical events: trades, rejections, kill switch, errors.

### Monitoring

Structured logging, health checks, and metrics for all components.

## Technology Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.12+ |
| API Framework | FastAPI |
| Validation | Pydantic |
| Database | PostgreSQL 16 |
| ORM | SQLAlchemy 2.x (async) |
| Migrations | Alembic |
| Cache | Redis 7 |
| Logging | structlog |
| Testing | pytest, httpx |
| Containers | Docker, Docker Compose |
| Frontend | React / Next.js (future) |

## Design Principles

1. **Safety over speed** — The system fails closed, never open
2. **Modularity** — Every major component is independently replaceable
3. **Testability** — Every component can be tested in isolation
4. **Auditability** — Every decision is logged and traceable
5. **Reproducibility** — Backtests with the same inputs produce the same outputs
6. **Simplicity** — Start as a modular monolith; extract services only when needed

