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


@pytest.mark.asyncio
async def test_strategy_version_immutability_draft(db_session: AsyncSession) -> None:
    """DRAFT strategy versions can be modified."""
    strategy = StrategyModel(strategy_id="s_draft", name="Draft Strat")
    db_session.add(strategy)

    v = StrategyVersionModel(strategy_id="s_draft", version="1.0", status=StrategyStatus.DRAFT)
    db_session.add(v)
    await db_session.commit()

    # Modify protected fields
    v.source_hash = "abc"
    v.supported_asset_classes = ["CRYPTO"]
    await db_session.commit()  # Should succeed
    assert v.source_hash == "abc"


@pytest.mark.asyncio
async def test_strategy_version_immutability_active(db_session: AsyncSession) -> None:
    """ACTIVE strategy versions reject modification of immutable fields."""
    strategy = StrategyModel(strategy_id="s_active", name="Active Strat")
    db_session.add(strategy)

    v = StrategyVersionModel(strategy_id="s_active", version="1.0", status=StrategyStatus.ACTIVE)
    db_session.add(v)
    await db_session.commit()

    # Try modifying an immutable field
    v.source_hash = "tampered_hash"
    with pytest.raises(ValueError, match="Cannot modify immutable field 'source_hash'"):
        await db_session.commit()

    await db_session.rollback()

    # Status change should still be allowed
    v.status = StrategyStatus.DEPRECATED
    await db_session.commit()

    # Try in-place JSON mutation
    v.parameters_schema["new_key"] = "bypassed"
    with pytest.raises(ValueError, match="Cannot modify immutable field 'parameters_schema'"):
        await db_session.commit()
    await db_session.rollback()  # Should succeed
    result = await db_session.execute(
        select(StrategyVersionModel).where(
            StrategyVersionModel.strategy_id == "s_active", StrategyVersionModel.version == "1.0"
        )
    )
    v = result.scalar_one()
    assert v.status == StrategyStatus.DEPRECATED


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


@pytest.mark.asyncio
async def test_order_state_transitions_valid(db_session: AsyncSession) -> None:
    """Test valid order state transitions through the SQLAlchemy event listener."""
    sig_id = uuid.uuid4()
    corr_id = uuid.uuid4()
    signal = _make_signal(sig_id=sig_id, corr_id=corr_id)
    db_session.add(signal)
    await db_session.commit()

    dec_id = uuid.uuid4()
    decision = RiskDecisionModel(
        decision_id=dec_id,
        correlation_id=corr_id,
        signal_id=sig_id,
        status=RiskDecisionStatus.APPROVED.value,
        timestamp=datetime.now(UTC),
    )
    db_session.add(decision)
    await db_session.commit()

    intent_id = uuid.uuid4()
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
        order_id=uuid.uuid4(),
        correlation_id=corr_id,
        intent_id=intent_id,
        symbol="BTC-USD",
        side=OrderSide.BUY.value,
        order_type=OrderType.MARKET.value,
        quantity=Decimal("1.0"),
        state=OrderState.CREATED.value,
    )
    db_session.add(order)
    await db_session.commit()

    # Valid transitions
    valid_path = [
        OrderState.VALIDATED.value,
        OrderState.SUBMITTED.value,
        OrderState.ACKNOWLEDGED.value,
        OrderState.PARTIALLY_FILLED.value,
        OrderState.FILLED.value,
    ]

    for state in valid_path:
        order.state = state
        await db_session.commit()  # Should succeed
        assert order.state == state


@pytest.mark.asyncio
async def test_explicit_business_cancellation_semantics() -> None:
    """Explicitly verify the required cancellation and execution rules."""
    from app.domain.transitions import validate_order_transition
    from app.models.enums import OrderState

    # ---------------------------------------------------------
    # TEST 1: Direct cancellation from active states is rejected
    # ---------------------------------------------------------
    active_states = [
        OrderState.CREATED,
        OrderState.VALIDATED,
        OrderState.SUBMITTED,
        OrderState.ACKNOWLEDGED,
        OrderState.PARTIALLY_FILLED,
    ]
    for state in active_states:
        with pytest.raises(ValueError, match="Invalid transition"):
            validate_order_transition(state, OrderState.CANCELLED)

    # ---------------------------------------------------------
    # TEST 2: Cancellation through CANCEL_PENDING succeeds
    # ---------------------------------------------------------
    for state in active_states:
        # Step A: Transition to CANCEL_PENDING must succeed
        validate_order_transition(state, OrderState.CANCEL_PENDING)

    # Step B: CANCEL_PENDING -> CANCELLED must succeed
    validate_order_transition(OrderState.CANCEL_PENDING, OrderState.CANCELLED)

    # ---------------------------------------------------------
    # TEST 3: CANCEL_PENDING cannot bypass confirmation
    # ---------------------------------------------------------
    with pytest.raises(ValueError, match="Invalid transition"):
        validate_order_transition(OrderState.CANCEL_PENDING, OrderState.FILLED)

    with pytest.raises(ValueError, match="Invalid transition"):
        validate_order_transition(OrderState.CANCEL_PENDING, OrderState.EXPIRED)

    with pytest.raises(ValueError, match="Invalid transition"):
        validate_order_transition(OrderState.CANCEL_PENDING, OrderState.REJECTED)

    # ---------------------------------------------------------
    # TEST 4: Terminal states remain terminal
    # ---------------------------------------------------------
    terminal_states = [
        OrderState.FILLED,
        OrderState.CANCELLED,
        OrderState.REJECTED,
        OrderState.EXPIRED,
        OrderState.FAILED,
    ]

    for terminal in terminal_states:
        with pytest.raises(ValueError, match="is a terminal state"):
            validate_order_transition(terminal, OrderState.SUBMITTED)
        with pytest.raises(ValueError, match="is a terminal state"):
            validate_order_transition(terminal, OrderState.CANCEL_PENDING)

    # Explicit terminal transition blocks
    with pytest.raises(ValueError, match="is a terminal state"):
        validate_order_transition(OrderState.FILLED, OrderState.CANCELLED)
    with pytest.raises(ValueError, match="is a terminal state"):
        validate_order_transition(OrderState.CANCELLED, OrderState.FILLED)

    # ---------------------------------------------------------
    # TEST 5: Existing valid transitions remain valid (Normal Execution Path)
    # ---------------------------------------------------------
    # Test the normal lifecycle path
    validate_order_transition(OrderState.CREATED, OrderState.VALIDATED)
    validate_order_transition(OrderState.VALIDATED, OrderState.SUBMITTED)
    validate_order_transition(OrderState.SUBMITTED, OrderState.ACKNOWLEDGED)
    validate_order_transition(OrderState.ACKNOWLEDGED, OrderState.PARTIALLY_FILLED)
    validate_order_transition(OrderState.PARTIALLY_FILLED, OrderState.FILLED)

    # Partial fills can be consecutive
    validate_order_transition(OrderState.PARTIALLY_FILLED, OrderState.PARTIALLY_FILLED)


@pytest.mark.asyncio
async def test_order_state_transitions_exhaustive(db_session: AsyncSession) -> None:
    """Test EVERY possible state transition (allowed and invalid)."""
    # Create the prerequisite models once
    sig_id = uuid.uuid4()
    corr_id = uuid.uuid4()
    signal = _make_signal(sig_id=sig_id, corr_id=corr_id)
    db_session.add(signal)
    await db_session.commit()

    dec_id = uuid.uuid4()
    decision = RiskDecisionModel(
        decision_id=dec_id,
        correlation_id=corr_id,
        signal_id=sig_id,
        status=RiskDecisionStatus.APPROVED.value,
        timestamp=datetime.now(UTC),
    )
    db_session.add(decision)
    await db_session.commit()

    from app.domain.transitions import VALID_ORDER_TRANSITIONS

    for from_state in OrderState:
        for to_state in OrderState:
            intent_id = uuid.uuid4()
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

            # We must recreate the order for each test to isolate tests
            order_uuid = uuid.uuid4()
            # Directly inject it into the db bypassing the transition check initially
            order = OrderModel(
                order_id=order_uuid,
                correlation_id=corr_id,
                intent_id=intent_id,
                symbol="BTC-USD",
                side=OrderSide.BUY.value,
                order_type=OrderType.MARKET.value,
                quantity=Decimal("1.0"),
                state=from_state,
            )
            db_session.add(order)
            await db_session.commit()

            # Now try to transition
            order.state = to_state

            if from_state == to_state:
                allowed = True  # SQLAlchemy optimizations mean this never triggers the DB hook
            else:
                allowed = to_state in VALID_ORDER_TRANSITIONS.get(from_state, set())

            if allowed:
                await db_session.commit()  # Should not raise
            else:
                with pytest.raises(ValueError):
                    await db_session.commit()
                await db_session.rollback()


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
