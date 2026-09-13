"""Comprehensive tests for SQLAlchemy persistence models.

Covers:
- Table creation (metadata correctness)
- Foreign key integrity
- Uniqueness constraints (idempotency key, strategy version)
- Multiple fills per order
- Decimal precision round-trip through DB
- Correlation ID persistence
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.models import (
    AuditEventModel,
    Base,
    FillModel,
    OrderIntentModel,
    OrderModel,
    RiskDecisionModel,
    SignalModel,
    StrategyModel,
    StrategyVersionModel,
)
from app.models.enums import (
    OrderSide,
    OrderState,
    OrderType,
    RiskDecisionStatus,
    SignalType,
    StrategyStatus,
    TimeInForce,
)
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
async def db_session() -> AsyncSession:  # type: ignore[misc]
    """Create an in-memory SQLite database with all tables for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Enable FK enforcement for SQLite
        await conn.execute(text("PRAGMA foreign_keys = ON"))

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

    await engine.dispose()


# ============================================================
# Table Creation
# ============================================================


@pytest.mark.asyncio
async def test_all_tables_created() -> None:
    """Verify that all models can be created without mapping errors."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


# ============================================================
# Strategy + Version Tests
# ============================================================


@pytest.mark.asyncio
async def test_strategy_creation(db_session: AsyncSession) -> None:
    strategy = StrategyModel(
        strategy_id="sma_crossover",
        name="SMA Crossover",
        description="Simple moving average crossover strategy",
        author="test_author",
        status=StrategyStatus.ACTIVE,
    )
    db_session.add(strategy)
    await db_session.commit()

    result = await db_session.execute(
        select(StrategyModel).where(StrategyModel.strategy_id == "sma_crossover")
    )
    fetched = result.scalar_one()
    assert fetched.name == "SMA Crossover"
    assert fetched.status == StrategyStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_strategy_version_uniqueness(db_session: AsyncSession) -> None:
    """Duplicate (strategy_id, version) must be rejected by DB constraint."""
    strategy = StrategyModel(
        strategy_id="test_strat",
        name="Test",
        status=StrategyStatus.ACTIVE,
    )
    db_session.add(strategy)
    await db_session.commit()

    v1 = StrategyVersionModel(
        strategy_id="test_strat",
        version="1.0.0",
        status=StrategyStatus.ACTIVE,
    )
    db_session.add(v1)
    await db_session.commit()

    v1_dup = StrategyVersionModel(
        strategy_id="test_strat",
        version="1.0.0",  # Duplicate!
        status=StrategyStatus.ACTIVE,
    )
    db_session.add(v1_dup)
    with pytest.raises(IntegrityError):
        await db_session.commit()


# ============================================================
# Signal + FK Tests
# ============================================================


def _make_signal(
    corr_id: uuid.UUID | None = None,
    sig_id: uuid.UUID | None = None,
) -> SignalModel:
    return SignalModel(
        signal_id=sig_id or uuid.uuid4(),
        correlation_id=corr_id or uuid.uuid4(),
        strategy_id="test_strat",
        strategy_version="1.0.0",
        symbol="BTC-USD",
        timestamp=datetime.now(UTC),
        timeframe="1h",
        side=OrderSide.BUY.value,
        signal_type=SignalType.ENTRY.value,
    )


@pytest.mark.asyncio
async def test_signal_creation(db_session: AsyncSession) -> None:
    signal = _make_signal()
    db_session.add(signal)
    await db_session.commit()
    assert signal.id is not None


# ============================================================
# Risk Decision FK Tests
# ============================================================


@pytest.mark.asyncio
async def test_risk_decision_references_signal(db_session: AsyncSession) -> None:
    sig_id = uuid.uuid4()
    signal = _make_signal(sig_id=sig_id)
    db_session.add(signal)
    await db_session.commit()

    decision = RiskDecisionModel(
        decision_id=uuid.uuid4(),
        correlation_id=signal.correlation_id,
        signal_id=sig_id,
        status=RiskDecisionStatus.APPROVED.value,
        calculated_quantity=Decimal("1.5"),
        timestamp=datetime.now(UTC),
    )
    db_session.add(decision)
    await db_session.commit()
    assert decision.id is not None


# ============================================================
# OrderIntent + Idempotency Tests
# ============================================================


@pytest.mark.asyncio
async def test_order_intent_idempotency_key_unique(
    db_session: AsyncSession,
) -> None:
    """Duplicate idempotency keys must be rejected by the database."""
    sig_id = uuid.uuid4()
    dec_id = uuid.uuid4()
    corr_id = uuid.uuid4()

    signal = _make_signal(sig_id=sig_id, corr_id=corr_id)
    db_session.add(signal)
    await db_session.commit()

    decision = RiskDecisionModel(
        decision_id=dec_id,
        correlation_id=corr_id,
        signal_id=sig_id,
        status=RiskDecisionStatus.APPROVED.value,
        calculated_quantity=Decimal("1.0"),
        timestamp=datetime.now(UTC),
    )
    db_session.add(decision)
    await db_session.commit()

    intent1 = OrderIntentModel(
        intent_id=uuid.uuid4(),
        correlation_id=corr_id,
        originating_signal_id=sig_id,
        risk_decision_id=dec_id,
        account_id="acc1",
        symbol="BTC-USD",
        side=OrderSide.BUY.value,
        order_type=OrderType.MARKET.value,
        quantity=Decimal("1.0"),
        time_in_force=TimeInForce.GTC.value,
        idempotency_key="unique-key-1",
        creation_timestamp=datetime.now(UTC),
    )
    db_session.add(intent1)
    await db_session.commit()

    intent2 = OrderIntentModel(
        intent_id=uuid.uuid4(),
        correlation_id=corr_id,
        originating_signal_id=sig_id,
        risk_decision_id=dec_id,
        account_id="acc1",
        symbol="BTC-USD",
        side=OrderSide.BUY.value,
        order_type=OrderType.MARKET.value,
        quantity=Decimal("1.0"),
        time_in_force=TimeInForce.GTC.value,
        idempotency_key="unique-key-1",  # Duplicate!
        creation_timestamp=datetime.now(UTC),
    )
    db_session.add(intent2)
    with pytest.raises(IntegrityError):
        await db_session.commit()


# ============================================================
# Order + Fill Tests
# ============================================================


@pytest.mark.asyncio
async def test_multiple_fills_per_order(db_session: AsyncSession) -> None:
    """One order can have multiple fills (partial fills)."""
    sig_id = uuid.uuid4()
    dec_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    order_id = uuid.uuid4()
    corr_id = uuid.uuid4()

    # Build the full chain
    signal = _make_signal(sig_id=sig_id, corr_id=corr_id)
    db_session.add(signal)
    await db_session.commit()

    decision = RiskDecisionModel(
        decision_id=dec_id,
        correlation_id=corr_id,
        signal_id=sig_id,
        status=RiskDecisionStatus.APPROVED.value,
        calculated_quantity=Decimal("1.0"),
        timestamp=datetime.now(UTC),
    )
    db_session.add(decision)
    await db_session.commit()

    intent = OrderIntentModel(
        intent_id=intent_id,
        correlation_id=corr_id,
        originating_signal_id=sig_id,
        risk_decision_id=dec_id,
        account_id="acc1",
        symbol="BTC-USD",
        side=OrderSide.BUY.value,
        order_type=OrderType.MARKET.value,
        quantity=Decimal("1.0"),
        time_in_force=TimeInForce.GTC.value,
        idempotency_key=f"key-{uuid.uuid4()}",
        creation_timestamp=datetime.now(UTC),
    )
    db_session.add(intent)
    await db_session.commit()

    order = OrderModel(
        order_id=order_id,
        correlation_id=corr_id,
        intent_id=intent_id,
        symbol="BTC-USD",
        side=OrderSide.BUY.value,
        order_type=OrderType.MARKET.value,
        quantity=Decimal("1.0"),
        state=OrderState.PARTIALLY_FILLED.value,
        filled_quantity=Decimal("0.6"),
    )
    db_session.add(order)
    await db_session.commit()

    # Two partial fills
    fill1 = FillModel(
        fill_id=uuid.uuid4(),
        correlation_id=corr_id,
        order_id=order_id,
        timestamp=datetime.now(UTC),
        price=Decimal("50000.00"),
        quantity=Decimal("0.3"),
        fee=Decimal("0.50"),
    )
    fill2 = FillModel(
        fill_id=uuid.uuid4(),
        correlation_id=corr_id,
        order_id=order_id,
        timestamp=datetime.now(UTC),
        price=Decimal("50001.00"),
        quantity=Decimal("0.3"),
        fee=Decimal("0.50"),
    )
    db_session.add_all([fill1, fill2])
    await db_session.commit()

    # Query fills for this order
    result = await db_session.execute(select(FillModel).where(FillModel.order_id == order_id))
    fills = result.scalars().all()
    assert len(fills) == 2
    total_filled = sum(f.quantity for f in fills)
    assert total_filled == Decimal("0.6")


# ============================================================
# Decimal Round-Trip Tests
# ============================================================


@pytest.mark.asyncio
async def test_decimal_precision_roundtrip(db_session: AsyncSession) -> None:
    """Financial values must survive a DB round-trip without precision loss."""
    sig_id = uuid.uuid4()
    signal = SignalModel(
        signal_id=sig_id,
        correlation_id=uuid.uuid4(),
        strategy_id="test",
        strategy_version="1.0.0",
        symbol="BTC-USD",
        timestamp=datetime.now(UTC),
        timeframe="1h",
        side=OrderSide.BUY.value,
        signal_type=SignalType.ENTRY.value,
        proposed_entry_price=Decimal("50000.12345678"),
        stop_loss=Decimal("49000.87654321"),
        take_profit=Decimal("51000.00000001"),
    )
    db_session.add(signal)
    await db_session.commit()

    result = await db_session.execute(select(SignalModel).where(SignalModel.signal_id == sig_id))
    fetched = result.scalar_one()
    assert fetched.proposed_entry_price == Decimal("50000.12345678")
    assert fetched.stop_loss == Decimal("49000.87654321")
    assert fetched.take_profit == Decimal("51000.00000001")


# ============================================================
# Correlation ID Tracing Tests
# ============================================================


@pytest.mark.asyncio
async def test_correlation_id_traces_full_chain(
    db_session: AsyncSession,
) -> None:
    """A single correlation_id should link Signal → Risk → Intent → Order → Fill."""
    corr_id = uuid.uuid4()
    sig_id = uuid.uuid4()
    dec_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    order_id = uuid.uuid4()

    signal = _make_signal(sig_id=sig_id, corr_id=corr_id)
    db_session.add(signal)
    await db_session.commit()

    decision = RiskDecisionModel(
        decision_id=dec_id,
        correlation_id=corr_id,
        signal_id=sig_id,
        status=RiskDecisionStatus.APPROVED.value,
        calculated_quantity=Decimal("1.0"),
        timestamp=datetime.now(UTC),
    )
    db_session.add(decision)
    await db_session.commit()

    intent = OrderIntentModel(
        intent_id=intent_id,
        correlation_id=corr_id,
        originating_signal_id=sig_id,
        risk_decision_id=dec_id,
        account_id="acc1",
        symbol="BTC-USD",
        side=OrderSide.BUY.value,
        order_type=OrderType.MARKET.value,
        quantity=Decimal("1.0"),
        time_in_force=TimeInForce.GTC.value,
        idempotency_key=f"corr-test-{uuid.uuid4()}",
        creation_timestamp=datetime.now(UTC),
    )
    db_session.add(intent)
    await db_session.commit()

    order = OrderModel(
        order_id=order_id,
        correlation_id=corr_id,
        intent_id=intent_id,
        symbol="BTC-USD",
        side=OrderSide.BUY.value,
        order_type=OrderType.MARKET.value,
        quantity=Decimal("1.0"),
        state=OrderState.FILLED.value,
        filled_quantity=Decimal("1.0"),
        average_fill_price=Decimal("50000.00"),
    )
    db_session.add(order)
    await db_session.commit()

    fill = FillModel(
        fill_id=uuid.uuid4(),
        correlation_id=corr_id,
        order_id=order_id,
        timestamp=datetime.now(UTC),
        price=Decimal("50000.00"),
        quantity=Decimal("1.0"),
    )
    db_session.add(fill)
    await db_session.commit()

    # Verify all entities share the same correlation_id
    for model_cls in [SignalModel, RiskDecisionModel, OrderIntentModel, OrderModel, FillModel]:
        result = await db_session.execute(
            select(model_cls).where(model_cls.correlation_id == corr_id)  # type: ignore[attr-defined]
        )
        entity = result.scalar_one()
        assert entity is not None


# ============================================================
# Audit Event Tests
# ============================================================


@pytest.mark.asyncio
async def test_audit_event_full_references(db_session: AsyncSession) -> None:
    """Audit events should be able to reference all pipeline entity IDs."""
    event = AuditEventModel(
        event_id=uuid.uuid4(),
        timestamp=datetime.now(UTC),
        correlation_id=uuid.uuid4(),
        component="RISK",
        event_type="RISK_APPROVED",
        trading_mode="BACKTEST",
        strategy_id="test_strat",
        symbol="BTC-USD",
        signal_id=uuid.uuid4(),
        risk_decision_id=uuid.uuid4(),
        order_intent_id=uuid.uuid4(),
        order_id=uuid.uuid4(),
        details={"reason": "Within limits"},
    )
    db_session.add(event)
    await db_session.commit()
    assert event.risk_decision_id is not None
    assert event.order_intent_id is not None
