import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.domain.transitions import validate_order_transition
from app.models.enums import OrderSide, OrderState, OrderType, PaperSessionState
from app.models.paper import CashReservationModel, PaperSessionModel
from app.models.portfolio import PortfolioSnapshotModel, PositionModel
from app.models.trading import (
    OrderIntentModel,
    OrderModel,
    RiskDecisionModel,
    SignalModel,
)
from app.paper.adapter import PaperExecutionAdapter
from app.paper.orchestrator import PaperOrchestrator
from app.schemas.risk import RiskDecision, RiskDecisionStatus
from app.schemas.signal import Signal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _now():
    return datetime.now(UTC)


class MockQuoteProvider:
    async def get_live_quote(self, symbol: str) -> Decimal:
        return Decimal("50.0")


@pytest.fixture
def mock_adapter():
    return PaperExecutionAdapter(quote_provider=MockQuoteProvider(), fee_rate=Decimal("0.0"))


@pytest.fixture
async def setup_session(db_session: AsyncSession):
    worker_id = uuid.uuid4()
    session_id = uuid.uuid4()
    account_id = "test-account"

    session = PaperSessionModel(
        session_id=session_id,
        account_id=account_id,
        strategy_id="test_strat",
        strategy_version="1.0",
        symbol="BTC-USD",
        timeframe="1h",
        state=PaperSessionState.RUNNING,
        worker_owner_id=worker_id,
        worker_heartbeat=_now(),
    )
    db_session.add(session)

    portfolio = PortfolioSnapshotModel(
        account_id=account_id,
        timestamp=_now() - timedelta(seconds=1),
        cash=Decimal("10000.0"),
        available_cash=Decimal("10000.0"),
        equity=Decimal("10000.0"),
    )
    db_session.add(portfolio)
    await db_session.commit()

    return session_id, worker_id, account_id


@pytest.mark.asyncio
async def test_cancellation_transitions():
    """SUBMITTED -> CANCELLED must fail. SUBMITTED -> CANCEL_PENDING -> CANCELLED must succeed."""
    with pytest.raises(ValueError):
        validate_order_transition(OrderState.SUBMITTED, OrderState.CANCELLED)

    # Should succeed
    validate_order_transition(OrderState.SUBMITTED, OrderState.CANCEL_PENDING)
    validate_order_transition(OrderState.CANCEL_PENDING, OrderState.CANCELLED)


@pytest.mark.asyncio
async def test_order_semantics_preserved(db_session: AsyncSession, mock_adapter, setup_session):
    session_id, worker_id, account_id = setup_session
    orchestrator = PaperOrchestrator(db_session, mock_adapter)

    signal = Signal(
        signal_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        strategy_id="test",
        strategy_version="1.0",
        symbol="BTC-USD",
        timestamp=_now(),
        timeframe="1h",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        signal_type="ENTRY",
        quantity=Decimal("1.5"),
        metadata={"source": "test", "time_in_force": "GTC"},
    )

    rd = RiskDecision(
        decision_id=uuid.uuid4(),
        correlation_id=signal.correlation_id,
        signal_id=signal.signal_id,
        status=RiskDecisionStatus.APPROVED,
        trading_mode="PAPER",
        calculated_quantity=Decimal("1.5"),
        calculated_risk=Decimal("0.0"),
        authorized_cash_requirement=Decimal("1000.0"),
        risk_policy_version="1.0",
        timestamp=_now(),
    )

    # Save SignalModel to satisfy FK
    db_session.add(SignalModel(**signal.model_dump(mode="python")))
    await db_session.commit()

    # Debug: Check signal
    db_signal = await db_session.execute(
        select(SignalModel).where(SignalModel.signal_id == signal.signal_id)
    )
    assert db_signal.scalar_one() is not None

    res = await orchestrator.transaction_b_reserve_cash(session_id, worker_id, signal, rd)
    assert res is True

    intent = await db_session.execute(
        select(OrderIntentModel).where(OrderIntentModel.correlation_id == signal.correlation_id)
    )
    intent = intent.scalar_one()

    # Must preserve Signal semantics
    assert intent.side == OrderSide.SELL
    assert intent.order_type == OrderType.LIMIT
    assert intent.quantity == Decimal("1.5")


@pytest.mark.asyncio
async def test_cash_authorization(db_session: AsyncSession, mock_adapter, setup_session):
    session_id, worker_id, account_id = setup_session
    orchestrator = PaperOrchestrator(db_session, mock_adapter)

    signal = Signal(
        signal_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        strategy_id="test",
        strategy_version="1.0",
        symbol="BTC-USD",
        timestamp=_now(),
        timeframe="1h",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        signal_type="ENTRY",
        quantity=Decimal("1.0"),
        metadata={"source": "test", "time_in_force": "GTC"},
    )
    db_session.add(SignalModel(**signal.model_dump(mode="python")))
    await db_session.commit()

    # Add an active reservation for 7000
    # We need risk decision and intent for FK
    fake_rd = RiskDecisionModel(
        decision_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        signal_id=signal.signal_id,
        status="APPROVED",
        timestamp=_now(),
    )
    db_session.add(fake_rd)
    await db_session.flush()

    intent = OrderIntentModel(
        intent_id=uuid.uuid4(),
        correlation_id=fake_rd.correlation_id,
        originating_signal_id=signal.signal_id,
        risk_decision_id=fake_rd.decision_id,
        account_id=account_id,
        symbol="BTC-USD",
        side=OrderSide.BUY.value,
        order_type=OrderType.MARKET.value,
        quantity=Decimal("1.0"),
        time_in_force="GTC",
        idempotency_key=str(uuid.uuid4()),
        creation_timestamp=_now(),
    )
    db_session.add(intent)
    await db_session.flush()

    res = CashReservationModel(
        reservation_id=uuid.uuid4(),
        session_id=session_id,
        order_intent_id=intent.intent_id,
        authorized_cash_requirement=Decimal("7000.0"),
        active=True,
        creation_timestamp=_now(),
    )
    db_session.add(res)
    await db_session.commit()

    rd = RiskDecision(
        decision_id=uuid.uuid4(),
        correlation_id=signal.correlation_id,
        signal_id=signal.signal_id,
        status=RiskDecisionStatus.APPROVED,
        trading_mode="PAPER",
        calculated_quantity=Decimal("1.0"),
        authorized_cash_requirement=Decimal("4000.0"),
        risk_policy_version="1.0",
        timestamp=_now(),
    )

    await db_session.commit()

    # Available is 3000. 4000 should fail.
    res_bool = await orchestrator.transaction_b_reserve_cash(session_id, worker_id, signal, rd)
    assert res_bool is False

    # 3000 should succeed
    rd.decision_id = uuid.uuid4()
    rd.authorized_cash_requirement = Decimal("3000.0")
    res_bool = await orchestrator.transaction_b_reserve_cash(session_id, worker_id, signal, rd)
    assert res_bool is True


@pytest.mark.asyncio
async def test_quote_authorization(db_session: AsyncSession, mock_adapter, setup_session):
    session_id, worker_id, account_id = setup_session
    orchestrator = PaperOrchestrator(db_session, mock_adapter)

    signal = Signal(
        signal_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        strategy_id="test",
        strategy_version="1.0",
        symbol="BTC-USD",
        timestamp=_now(),
        timeframe="1h",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        signal_type="ENTRY",
        quantity=Decimal("100.0"),
        metadata={"source": "test", "time_in_force": "GTC"},
    )

    rd = RiskDecision(
        decision_id=uuid.uuid4(),
        correlation_id=signal.correlation_id,
        signal_id=signal.signal_id,
        status=RiskDecisionStatus.APPROVED,
        trading_mode="PAPER",
        calculated_quantity=Decimal("100.0"),
        authorized_cash_requirement=Decimal("5000.0"),
        risk_policy_version="1.0",
        timestamp=_now(),
    )

    db_session.add(SignalModel(**signal.model_dump(mode="python")))
    await db_session.commit()
    await orchestrator.transaction_b_reserve_cash(session_id, worker_id, signal, rd)

    order = await db_session.execute(
        select(OrderModel).where(OrderModel.correlation_id == rd.correlation_id)
    )
    order = order.scalar_one()

    # Actual cash req = 100 * 50 + 10 = 5010 > 5000 (rejected)
    res = await orchestrator.transaction_c_acknowledge(
        session_id, worker_id, order.order_id, Decimal("50.0"), Decimal("10.0")
    )
    assert res is False

    await db_session.flush()
    await db_session.refresh(order)
    assert order.state == OrderState.CANCELLED.value

    reservation = await db_session.execute(
        select(CashReservationModel).where(CashReservationModel.order_intent_id == order.intent_id)
    )
    reservation = reservation.scalar_one()
    assert reservation.active is False


@pytest.mark.asyncio
async def test_economic_commit_and_fees(db_session: AsyncSession, mock_adapter, setup_session):
    session_id, worker_id, account_id = setup_session
    orchestrator = PaperOrchestrator(db_session, mock_adapter)

    signal = Signal(
        signal_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        strategy_id="test",
        strategy_version="1.0",
        symbol="BTC-USD",
        timestamp=_now(),
        timeframe="1h",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        signal_type="ENTRY",
        quantity=Decimal("100.0"),
        metadata={"source": "test", "time_in_force": "GTC"},
    )

    rd = RiskDecision(
        decision_id=uuid.uuid4(),
        correlation_id=signal.correlation_id,
        signal_id=signal.signal_id,
        status=RiskDecisionStatus.APPROVED,
        trading_mode="PAPER",
        calculated_quantity=Decimal("100.0"),
        authorized_cash_requirement=Decimal("5000.0"),
        risk_policy_version="1.0",
        timestamp=_now(),
    )

    db_session.add(SignalModel(**signal.model_dump(mode="python")))
    await db_session.commit()
    await orchestrator.transaction_b_reserve_cash(session_id, worker_id, signal, rd)

    order = await db_session.execute(
        select(OrderModel).where(OrderModel.correlation_id == rd.correlation_id)
    )
    order = order.scalar_one()

    # 100 * 49 + 10 = 4910 <= 5000
    res = await orchestrator.transaction_c_acknowledge(
        session_id, worker_id, order.order_id, Decimal("49.0"), Decimal("10.0")
    )
    assert res is True

    await db_session.flush()
    await db_session.refresh(order)
    assert order.state == OrderState.ACKNOWLEDGED.value
    assert order.execution_fee == Decimal("10.0")

    res = await orchestrator.transaction_d_fill(session_id, worker_id, order.order_id)
    assert res is True

    await db_session.flush()
    await db_session.refresh(order)
    assert order.state == OrderState.FILLED.value

    # Verify portfolio
    portfolios = await db_session.execute(
        select(PortfolioSnapshotModel)
        .where(PortfolioSnapshotModel.account_id == account_id)
        .order_by(PortfolioSnapshotModel.timestamp.desc())
    )
    portfolios = portfolios.scalars().all()
    assert len(portfolios) == 2
    latest = portfolios[0]

    # Initial 10000 - 4910 = 5090
    assert latest.cash == Decimal("5090.0")

    position = await db_session.execute(
        select(PositionModel).where(PositionModel.account_id == account_id)
    )
    position = position.scalar_one()
    assert position.quantity == Decimal("100.0")

    reservation = await db_session.execute(
        select(CashReservationModel).where(CashReservationModel.order_intent_id == order.intent_id)
    )
    reservation = reservation.scalar_one()
    assert reservation.active is False


@pytest.mark.asyncio
async def test_worker_lease(db_session: AsyncSession, mock_adapter, setup_session):
    session_id, worker_id, account_id = setup_session
    orchestrator = PaperOrchestrator(db_session, mock_adapter)

    session = await db_session.execute(
        select(PaperSessionModel).where(PaperSessionModel.session_id == session_id)
    )
    session = session.scalar_one()

    assert await orchestrator.check_lease(session, worker_id) is True
    assert await orchestrator.check_lease(session, uuid.uuid4()) is False

    # Expire heartbeat
    session.worker_heartbeat = _now() - timedelta(seconds=60)
    await db_session.commit()

    assert await orchestrator.check_lease(session, worker_id) is False


@pytest.mark.asyncio
async def test_kill_switch_race(db_session: AsyncSession, mock_adapter, setup_session):
    session_id, worker_id, account_id = setup_session
    orchestrator = PaperOrchestrator(db_session, mock_adapter)

    signal = Signal(
        signal_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        strategy_id="test",
        strategy_version="1.0",
        symbol="BTC-USD",
        timestamp=_now(),
        timeframe="1h",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        signal_type="ENTRY",
        quantity=Decimal("1.0"),
        metadata={"source": "test", "time_in_force": "GTC"},
    )

    rd = RiskDecision(
        decision_id=uuid.uuid4(),
        correlation_id=signal.correlation_id,
        signal_id=signal.signal_id,
        status=RiskDecisionStatus.APPROVED,
        trading_mode="PAPER",
        calculated_quantity=Decimal("1.0"),
        authorized_cash_requirement=Decimal("5000.0"),
        risk_policy_version="1.0",
        timestamp=_now(),
    )

    db_session.add(SignalModel(**signal.model_dump(mode="python")))
    await db_session.commit()
    await orchestrator.transaction_b_reserve_cash(session_id, worker_id, signal, rd)

    order = await db_session.execute(
        select(OrderModel).where(OrderModel.correlation_id == rd.correlation_id)
    )
    order = order.scalar_one()

    # Simulate kill switch
    order.state = OrderState.CANCEL_PENDING
    await db_session.commit()

    # Tx C should fail
    res = await orchestrator.transaction_c_acknowledge(
        session_id, worker_id, order.order_id, Decimal("49.0"), Decimal("10.0")
    )
    assert res is False


@pytest.mark.asyncio
async def test_k1_orchestration_e2e(db_session: AsyncSession, mock_adapter, setup_session):
    session_id, worker_id, account_id = setup_session

    class CustomMockAdapter:
        async def get_quote(self, symbol):
            from decimal import Decimal

            return Decimal("100.0"), Decimal("10.0")

    orchestrator = PaperOrchestrator(db_session, CustomMockAdapter())

    from unittest.mock import MagicMock

    from app.schemas.market_data import Candle
    from app.schemas.paper import SizingResult
    from app.schemas.risk import RiskDecision, RiskDecisionStatus

    candle = Candle(
        symbol="BTC-USD",
        timestamp=_now(),
        timeframe="1h",
        open=Decimal("100.0"),
        high=Decimal("110.0"),
        low=Decimal("90.0"),
        close=Decimal("100.0"),
        volume=Decimal("1.0"),
    )

    signal = Signal(
        signal_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        strategy_id="test",
        strategy_version="1.0",
        symbol="BTC-USD",
        timestamp=_now(),
        timeframe="1h",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        signal_type="ENTRY",
        quantity=Decimal("1.0"),
        metadata={"source": "test", "time_in_force": "GTC"},
    )

    runner = MagicMock()
    runner.process_candle.return_value = signal

    position_sizer = MagicMock()
    position_sizer.calculate_size.return_value = SizingResult(
        quantity=Decimal("2.0"), reason="Test", is_valid=True
    )

    risk_engine = MagicMock()
    risk_decision = RiskDecision(
        decision_id=uuid.uuid4(),
        correlation_id=signal.correlation_id,
        signal_id=signal.signal_id,
        status=RiskDecisionStatus.APPROVED,
        trading_mode="PAPER",
        calculated_quantity=Decimal("2.0"),
        calculated_risk=Decimal("10.0"),
        authorized_cash_requirement=Decimal("250.0"),
        risk_policy_version="1.0",
        timestamp=_now(),
    )
    risk_engine.evaluate.return_value = risk_decision
    risk_policy = MagicMock()

    await orchestrator.acquire_lease(session_id, worker_id)

    await orchestrator.run_pipeline_for_candle(
        session_id=session_id,
        worker_id=worker_id,
        candle=candle,
        runner=runner,
        position_sizer=position_sizer,
        risk_engine=risk_engine,
        risk_policy=risk_policy,
        is_complete=True,
    )

    order = await db_session.execute(
        select(OrderModel).where(OrderModel.correlation_id == signal.correlation_id)
    )
    order = order.scalar_one_or_none()
    assert order is not None
    assert order.state == OrderState.FILLED.value
