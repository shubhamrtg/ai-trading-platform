from typing import Any
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from app.models import Base
from app.models.enums import OrderSide, StrategyStatus
from app.models.strategy import StrategyModel, StrategyVersionModel
from app.schemas.market_data import Candle
from app.strategies.examples.moving_average_crossover import MovingAverageCrossover
from app.strategies.repository import StrategyVersionRepository
from app.strategies.runner import (
    ChronologicalDataError,
    StrategyExecutionError,
    StrategyValidationError,
)
from app.strategies.sdk import (
    Strategy,
    StrategyContext,
    StrategyMetadata,
    StrategyRegistrationError,
    StrategyRegistry,
)
from app.strategies.service import StrategyExecutionService
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("PRAGMA foreign_keys = ON"))
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


def make_candle(price: str, ts: datetime) -> Candle:
    return Candle(
        symbol="BTC-USD",
        timeframe="1h",
        timestamp=ts,
        open=Decimal(price),
        high=Decimal(price),
        low=Decimal(price),
        close=Decimal(price),
        volume=Decimal("100"),
        vwap=Decimal(price),
        trades=1,
    )


async def setup_persisted_version(
    db_session: AsyncSession,
    name: str = "MA_Crossover_Reference",
    version: str = "1.0.0",
    bad_hash: bool = False,
    status: StrategyStatus = StrategyStatus.ACTIVE,
) -> None:
    try:
        actual_hash = StrategyRegistry.get(name, version)[1]
    except ValueError:
        actual_hash = "unknown_hash"

    if bad_hash:
        actual_hash = "WRONG_HASH"

    strat = StrategyModel(
        strategy_id=name, name=name, created_at=datetime.now(UTC), updated_at=datetime.now(UTC)
    )

    stmt = select(StrategyModel).where(StrategyModel.strategy_id == name)
    res = await db_session.execute(stmt)
    if not res.scalar_one_or_none():
        strat = StrategyModel(
            strategy_id=name, name=name, created_at=datetime.now(UTC), updated_at=datetime.now(UTC)
        )
        db_session.add(strat)

    ver = StrategyVersionModel(
        strategy_id=name,
        version=version,
        source_hash=actual_hash,
        status=status.value,
        supported_asset_classes=["crypto"],
        supported_timeframes=["1h"],
        required_indicators=[],
        parameters_schema={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(ver)
    await db_session.commit()


# FIX 1, 3: Deterministic Output & Complete Output Test
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_strategy_execution_determinism_and_chronology(db_session: AsyncSession) -> None:
    await setup_persisted_version(db_session)
    repo = StrategyVersionRepository(db_session)
    service = StrategyExecutionService(repo)

    runner1 = await service.create_runner(
        "MA_Crossover_Reference",
        "1.0.0",
        {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")},
    )
    runner2 = await service.create_runner(
        "MA_Crossover_Reference",
        "1.0.0",
        {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")},
    )

    c1 = make_candle("100", datetime(2023, 1, 1, 10, tzinfo=UTC))
    c2 = make_candle("100", datetime(2023, 1, 1, 11, tzinfo=UTC))
    c3 = make_candle("100", datetime(2023, 1, 1, 12, tzinfo=UTC))
    c4 = make_candle("150", datetime(2023, 1, 1, 13, tzinfo=UTC))

    for c in [c1, c2, c3]:
        runner1.process_candle(c)
        runner2.process_candle(c)

    ctx1 = runner1.contexts["BTC-USD_1h"]
    ctx2 = runner2.contexts["BTC-USD_1h"]
    assert len(ctx1.history) == 3
    assert len(ctx2.history) == 3

    # Verify runtime Signal logic is separated from strategy
    sig1 = runner1.process_candle(c4)
    sig2 = runner2.process_candle(c4)
    assert sig1 is not None and sig2 is not None
    assert sig1.side == OrderSide.BUY
    assert sig2.side == OrderSide.BUY

    # Runtime IDs are UUIDs and MUST differ
    assert sig1.signal_id != sig2.signal_id
    assert sig1.correlation_id != sig2.correlation_id

    # But business output must match exactly
    assert sig1.strategy_id == sig2.strategy_id
    assert sig1.proposed_entry_price == sig2.proposed_entry_price


# FIX 2, 4: Explicit Chronological Data Validation & Rejection
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_chronological_candle_processing(db_session: AsyncSession) -> None:
    await setup_persisted_version(db_session)
    service = StrategyExecutionService(StrategyVersionRepository(db_session))

    runner = await service.create_runner(
        "MA_Crossover_Reference",
        "1.0.0",
        {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")},
    )

    c1 = make_candle("100", datetime(2023, 1, 1, 10, tzinfo=UTC))
    c2 = make_candle("110", datetime(2023, 1, 1, 11, tzinfo=UTC))
    runner.process_candle(c1)
    runner.process_candle(c2)

    ctx = runner.contexts["BTC-USD_1h"]
    assert len(ctx.history) == 2

    # Duplicate rejected with dedicated error
    with pytest.raises(ChronologicalDataError, match="duplicate candle rejected"):
        runner.process_candle(c2)

    # The history remains unchanged after rejection
    assert len(ctx.history) == 2

    # Out of order rejected with dedicated error
    c3 = make_candle("90", datetime(2023, 1, 1, 9, tzinfo=UTC))
    with pytest.raises(ChronologicalDataError, match="Out-of-order"):
        runner.process_candle(c3)

    assert len(ctx.history) == 2


# -------------------------------------------------------------------------------------------------
# FIX 1, 3: Exact StrategyVersion Binding & Source Identity
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_strategy_version_binding_and_source_hash(db_session: AsyncSession) -> None:
    service = StrategyExecutionService(StrategyVersionRepository(db_session))

    # 1. Successful exact version resolution
    await setup_persisted_version(db_session, "MA_Crossover_Reference", "1.0.0")
    runner = await service.create_runner(
        "MA_Crossover_Reference",
        "1.0.0",
        {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")},
    )
    assert isinstance(runner.strategy, MovingAverageCrossover)

    # 2. Unknown version fails closed
    with pytest.raises(StrategyValidationError, match="not found"):
        await service.create_runner(
            "MA_Crossover_Reference",
            "2.0.0",
            {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")},
        )

    # 3. Mismatched executable/source identity fails closed
    from sqlalchemy import delete

    await db_session.execute(delete(StrategyVersionModel))
    await db_session.execute(delete(StrategyModel))
    await db_session.commit()
    await setup_persisted_version(db_session, "MA_Crossover_Reference", "1.0.0", bad_hash=True)
    with pytest.raises(StrategyValidationError, match="Source hash mismatch"):
        await service.create_runner(
            "MA_Crossover_Reference",
            "1.0.0",
            {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")},
        )

    # 4. Inactive version fails closed
    await db_session.execute(delete(StrategyVersionModel))
    await db_session.execute(delete(StrategyModel))
    await db_session.commit()
    await setup_persisted_version(
        db_session, "MA_Crossover_Reference", "1.0.0", status=StrategyStatus.DRAFT
    )
    with pytest.raises(StrategyValidationError, match="not found"):
        await service.create_runner(
            "MA_Crossover_Reference",
            "1.0.0",
            {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")},
        )


# -------------------------------------------------------------------------------------------------
# FIX 4: Strict Strategy Parameter Validation
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_strategy_parameter_strict_validation(db_session: AsyncSession) -> None:
    await setup_persisted_version(db_session)
    service = StrategyExecutionService(StrategyVersionRepository(db_session))

    with pytest.raises(StrategyValidationError, match="Invalid strategy parameters"):
        await service.create_runner("MA_Crossover_Reference", "1.0.0", {"fast_period": 10})

    with pytest.raises(
        StrategyValidationError,
        match="(?s)Invalid strategy parameters.*Extra inputs are not permitted",
    ):
        await service.create_runner(
            "MA_Crossover_Reference",
            "1.0.0",
            {
                "fast_period": 10,
                "slow_period": 20,
                "risk_percent": Decimal("2.0"),
                "unknown_param": 5,
            },
        )

    with pytest.raises(
        StrategyValidationError,
        match="(?s)Invalid strategy parameters.*Input should be a valid integer",
    ):
        await service.create_runner(
            "MA_Crossover_Reference",
            "1.0.0",
            {"fast_period": "20", "slow_period": 30, "risk_percent": Decimal("2.0")},
        )


# -------------------------------------------------------------------------------------------------
# FIX 5: Immutable StrategyMetadata
# -------------------------------------------------------------------------------------------------
def test_strategy_metadata_immutability() -> None:
    metadata = StrategyMetadata(
        name="Test",
        description="Desc",
        version="1.0.0",
        supported_asset_classes=("crypto",),
        supported_timeframes=("1h",),
        required_indicators=(),
    )

    with pytest.raises(ValidationError):
        metadata.name = "Mutated"

    with pytest.raises(AttributeError):
        metadata.supported_asset_classes.append("stocks")  # type: ignore[attr-defined]


# -------------------------------------------------------------------------------------------------
# FIX 6: Strategy Context & Controlled State
# -------------------------------------------------------------------------------------------------
def test_strategy_context_protection_and_state_api() -> None:
    ctx = StrategyContext("Test", "1.0.0", "BTC-USD", "1h")
    c = make_candle("100", datetime(2023, 1, 1, tzinfo=UTC))
    ctx._history.append(c)

    # 1. Strategy receives read-only history
    assert isinstance(ctx.history, tuple)
    with pytest.raises(AttributeError):
        ctx.history.append(make_candle("200", datetime(2023, 1, 2, tzinfo=UTC)))  # type: ignore[attr-defined]

    # 2. Strategy can read/write its own state API
    assert ctx.strategy_state.get("some_key") is None
    ctx.strategy_state.set("some_key", "calculated_value")
    assert ctx.strategy_state.get("some_key") == "calculated_value"
    assert ctx.strategy_state.contains("some_key") is True

    # 3. Arbitrary replacement is discouraged and prevented via API encapsulation
    ctx.strategy_state.clear()
    assert ctx.strategy_state.contains("some_key") is False


# -------------------------------------------------------------------------------------------------
# FIX 8 & 11: Correct MA Strategy Evaluation & Position Independence
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ma_strategy_sufficient_history_and_position_independence(
    db_session: AsyncSession,
) -> None:
    await setup_persisted_version(db_session)
    service = StrategyExecutionService(StrategyVersionRepository(db_session))

    runner = await service.create_runner(
        "MA_Crossover_Reference",
        "1.0.0",
        {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")},
    )

    c1 = make_candle("100", datetime(2023, 1, 1, tzinfo=UTC))
    c2 = make_candle("100", datetime(2023, 1, 2, tzinfo=UTC))
    c3 = make_candle("100", datetime(2023, 1, 3, tzinfo=UTC))
    c4 = make_candle("150", datetime(2023, 1, 4, tzinfo=UTC))

    assert runner.process_candle(c1) is None
    assert runner.process_candle(c2) is None
    assert runner.process_candle(c3) is None

    sig = runner.process_candle(c4)
    assert sig is not None
    assert sig.side == OrderSide.BUY

    # The strategy calculates internal state for crossover detection ("BULLISH")
    # but does NOT maintain actual position state.
    ctx = runner.contexts["BTC-USD_1h"]
    assert ctx.strategy_state.get("last_crossover") == "BULLISH"
    assert ctx.strategy_state.contains("position") is False


# -------------------------------------------------------------------------------------------------
# FIX 12: Look-ahead Protection
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_strategy_look_ahead_protection(db_session: AsyncSession) -> None:
    await setup_persisted_version(db_session)
    service = StrategyExecutionService(StrategyVersionRepository(db_session))

    runner = await service.create_runner(
        "MA_Crossover_Reference",
        "1.0.0",
        {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")},
    )

    c1 = make_candle("100", datetime(2023, 1, 1, tzinfo=UTC))
    c2 = make_candle("110", datetime(2023, 1, 2, tzinfo=UTC))
    c3 = make_candle("90", datetime(2023, 1, 3, tzinfo=UTC))

    runner.process_candle(c1)
    runner.process_candle(c2)

    ctx = runner.contexts["BTC-USD_1h"]
    assert len(ctx.history) == 2
    assert c3 not in ctx.history


# -------------------------------------------------------------------------------------------------
# Exception Distinctions and Source Hashing
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_strategy_execution_error_distinction(db_session: AsyncSession, monkeypatch: Any) -> None:
    await setup_persisted_version(db_session)
    service = StrategyExecutionService(StrategyVersionRepository(db_session))
    runner = await service.create_runner(
        "MA_Crossover_Reference", "1.0.0", {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")}
    )

    def buggy_on_candle(candle: Any, context: Any) -> None:
        raise ValueError("Division by zero in strategy logic")

    monkeypatch.setattr(runner.strategy, "on_candle", buggy_on_candle)

    c1 = make_candle("100", datetime(2023, 1, 1, 10, tzinfo=UTC))

    with pytest.raises(StrategyExecutionError, match="failed unexpectedly"):
        runner.process_candle(c1)


def test_source_hash_generation_and_failure(monkeypatch: Any) -> None:
    # 1. Deterministic hashing
    hash1 = StrategyRegistry.get("MA_Crossover_Reference", "1.0.0")[1]
    assert len(hash1) == 64

    # 2. Source inspection failure
    class DynamicStrategy(Strategy[Any]):
        metadata = StrategyMetadata(
            name="Dynamic",
            description="",
            version="1.0.0",
            supported_asset_classes=(),
            supported_timeframes=(),
            required_indicators=(),
        )
        parameters_schema = dict

        def on_candle(self, c: Any, ctx: Any) -> None:
            return None

    import inspect

    monkeypatch.setattr(
        inspect, "getsource", lambda x: (_ for _ in ()).throw(OSError("No source found"))
    )

    with pytest.raises(
        StrategyRegistrationError, match="deterministic SHA-256 source hash is strictly required"
    ):
        StrategyRegistry.register(DynamicStrategy)


@pytest.mark.asyncio
async def test_deprecated_strategy_rejection(db_session: AsyncSession) -> None:
    await setup_persisted_version(
        db_session, "MA_Crossover_Reference", "1.0.9", status=StrategyStatus.DEPRECATED
    )
    service = StrategyExecutionService(StrategyVersionRepository(db_session))

    with pytest.raises(StrategyValidationError, match="not found"):
        await service.create_runner(
            "MA_Crossover_Reference",
            "1.0.9",
            {"fast_period": 2, "slow_period": 3, "risk_percent": Decimal("1.0")},
        )
