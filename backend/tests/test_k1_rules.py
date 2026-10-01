import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.models.paper import PaperSessionModel, PaperSessionState
from app.models.portfolio import PortfolioSnapshotModel, PositionModel
from app.models.strategy import StrategyVersionModel
from app.models.trading import (
    OrderModel,
    SignalModel,
)
from app.paper.orchestrator import PaperOrchestrator
from app.paper.position_sizer import PositionSizer
from app.risk.engine import RiskEngine
from app.schemas.market_data import Candle
from app.schemas.order import OrderSide, OrderState, OrderType
from app.schemas.risk import RiskDecision, RiskDecisionStatus, RiskPolicy
from app.schemas.signal import Signal
from app.strategies.runner import ChronologicalDataError, DuplicateDataError, StrategyRunner
from app.strategies.sdk import StrategyRegistry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _now():
    return datetime.now(UTC)


class MockAdapter:
    async def get_quote(self, symbol):
        return Decimal("100.0"), Decimal("0.0")


@pytest.fixture
def mock_adapter():
    return MockAdapter()


@pytest.fixture
async def setup_session(db_session: AsyncSession):
    session_id = uuid.uuid4()
    worker_id = uuid.uuid4()
    account_id = "test-account"

    portfolio = PortfolioSnapshotModel(
        snapshot_id=uuid.uuid4(),
        account_id=account_id,
        timestamp=_now(),
        cash=Decimal("10000.0"),
        available_cash=Decimal("10000.0"),
        equity=Decimal("10000.0"),
    )
    db_session.add(portfolio)

    session = PaperSessionModel(
        session_id=session_id,
        account_id=account_id,
        strategy_id="test",
        strategy_version="1.0",
        symbol="BTC-USD",
        timeframe="1h",
        state=PaperSessionState.RUNNING,
        worker_owner_id=worker_id,
        worker_heartbeat=_now(),
    )
    db_session.add(session)
    await db_session.commit()

    return session_id, worker_id, account_id


@pytest.mark.asyncio
async def test_k1_orchestration_e2e(db_session: AsyncSession, mock_adapter, setup_session):
    session_id, worker_id, account_id = setup_session

    # Setup real components
    version_record = StrategyVersionModel(
        strategy_id="MA_Crossover_Reference",
        version="1.0.0",
        source_hash=StrategyRegistry.get("MA_Crossover_Reference", "1.0.0")[1],
        status="ACTIVE",
    )

    runner = StrategyRunner(
        version_record, {"fast_period": 10, "slow_period": 20, "risk_percent": "0.05"}
    )

    position_sizer = PositionSizer()
    risk_engine = RiskEngine()

    risk_policy = RiskPolicy(
        policy_id=uuid.uuid4(),
        name="test_policy",
        version="1.0",
        max_position_size=Decimal("10000.0"),
        max_portfolio_risk=Decimal("0.10"),
        max_order_quantity=Decimal("100.0"),
        max_position_quantity=Decimal("100.0"),
        max_exposure_amount=Decimal("100000.0"),
        max_exposure_percent=Decimal("1.0"),
        max_risk_per_trade=Decimal("5000.0"),
        max_daily_loss=Decimal("1000.0"),
        max_drawdown_percent=Decimal("0.10"),
        trading_mode="PAPER",
    )

    history_candles = []
    for i in range(50):
        candle = Candle(
            symbol="BTC-USD",
            timestamp=_now() - timedelta(minutes=60 - i),
            timeframe="1h",
            open=Decimal("100.0"),
            high=Decimal("110.0"),
            low=Decimal("90.0"),
            close=Decimal("100.0"),
            volume=Decimal("1.0"),
        )
        history_candles.append(candle)

    runner.hydrate_history("BTC-USD", "1h", history_candles)

    candle = Candle(
        symbol="BTC-USD",
        timestamp=_now(),
        timeframe="1h",
        open=Decimal("100.0"),
        high=Decimal("200.0"),
        low=Decimal("100.0"),
        close=Decimal("200.0"),
        volume=Decimal("1.0"),
    )

    class CustomMockAdapter:
        async def get_quote(self, symbol):
            return Decimal("115.0"), Decimal("0.0")

    orchestrator = PaperOrchestrator(db_session, CustomMockAdapter())
    await orchestrator.acquire_lease(session_id, worker_id)

    # Set context cash so RiskEngine approves
    context = runner._get_or_create_context(candle.symbol, candle.timeframe)
    context.available_cash = Decimal("10000.0")

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

    order = await db_session.execute(select(OrderModel).where(OrderModel.symbol == "BTC-USD"))
    order = order.scalar_one_or_none()
    assert order is not None
    assert order.state == OrderState.FILLED.value


@pytest.mark.asyncio
async def test_cash_concurrency_a_b(db_session: AsyncSession, setup_session):
    import uuid

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    # Use a shared memory database with separate engines to simulate real concurrent connections
    shared_url = "sqlite+aiosqlite:///file:testdb_cash_conc?mode=memory&cache=shared&uri=true"
    engine1 = create_async_engine(shared_url, poolclass=NullPool)
    engine2 = create_async_engine(shared_url, poolclass=NullPool)

    # Keep a connection alive to prevent the in-memory DB from dropping
    keepalive_conn = await engine1.connect()

    # Initialize schema
    from app.models.base import Base

    await keepalive_conn.run_sync(Base.metadata.create_all)
    await keepalive_conn.execute(text("PRAGMA foreign_keys = ON"))
    await keepalive_conn.commit()

    session_id, worker_id, account_id = setup_session

    # We must also setup the account in this new shared DB
    async with AsyncSession(engine1) as init_db:
        from app.models.portfolio import PortfolioSnapshotModel

        init_db.add(
            PortfolioSnapshotModel(
                snapshot_id=uuid.uuid4(),
                account_id=account_id,
                timestamp=_now(),
                cash=Decimal("10000.0"),
                available_cash=Decimal("10000.0"),
                equity=Decimal("10000.0"),
            )
        )
        await init_db.commit()

    async with AsyncSession(engine1) as db1, AsyncSession(engine2) as db2:
        o1 = PaperOrchestrator(db1, MockAdapter())
        o2 = PaperOrchestrator(db2, MockAdapter())

        # We assume the account exists with 10k cash due to setup_session
        session_id_2 = uuid.uuid4()
        worker_id_2 = uuid.uuid4()
        s2 = PaperSessionModel(
            session_id=session_id_2,
            account_id=account_id,
            strategy_id="test2",
            strategy_version="1.0",
            symbol="BTC-USD",
            timeframe="1h",
            state=PaperSessionState.RUNNING,
            worker_owner_id=worker_id_2,
            worker_heartbeat=_now(),
        )
        db1.add(s2)

        sig1 = Signal(
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
            quantity=Decimal("60.0"),
            metadata={"source": "test", "time_in_force": "GTC"},
        )
        db1.add(SignalModel(**sig1.model_dump(mode="python")))

        sig2 = Signal(
            signal_id=uuid.uuid4(),
            correlation_id=uuid.uuid4(),
            strategy_id="test2",
            strategy_version="1.0",
            symbol="BTC-USD",
            timestamp=_now(),
            timeframe="1h",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            signal_type="ENTRY",
            quantity=Decimal("60.0"),
            metadata={"source": "test", "time_in_force": "GTC"},
        )
        db1.add(SignalModel(**sig2.model_dump(mode="python")))
        await db1.commit()

        rd1 = RiskDecision(
            decision_id=uuid.uuid4(),
            correlation_id=sig1.correlation_id,
            signal_id=sig1.signal_id,
            status=RiskDecisionStatus.APPROVED,
            trading_mode="PAPER",
            calculated_quantity=Decimal("60.0"),
            authorized_cash_requirement=Decimal("6000.0"),
            risk_policy_version="1.0",
            timestamp=_now(),
        )
        rd2 = RiskDecision(
            decision_id=uuid.uuid4(),
            correlation_id=sig2.correlation_id,
            signal_id=sig2.signal_id,
            status=RiskDecisionStatus.APPROVED,
            trading_mode="PAPER",
            calculated_quantity=Decimal("60.0"),
            authorized_cash_requirement=Decimal("6000.0"),
            risk_policy_version="1.0",
            timestamp=_now(),
        )

        from app.models.base import ApplicationFailureError

        async def safe_call(func, *args):
            try:
                return await func(*args)
            except ApplicationFailureError:
                return "FAIL"

        results = await asyncio.gather(
            safe_call(o1.transaction_b_reserve_cash, session_id, worker_id, sig1, rd1),
            safe_call(o2.transaction_b_reserve_cash, session_id_2, worker_id_2, sig2, rd2),
        )

        # One should succeed (True), one should fail concurrency lock ("FAIL")
        assert (results[0] is True and results[1] is False) or (
            results[1] is True and results[0] is False
        )


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_cash_reservation_boundary(db_session: AsyncSession, setup_session):
    import uuid
    from decimal import Decimal

    from app.models.enums import (
        OrderSide,
        OrderType,
        RiskDecisionStatus,
    )
    from app.models.paper import CashReservationModel
    from app.paper.orchestrator import PaperOrchestrator
    from app.schemas.risk import RiskDecision
    from app.schemas.signal import Signal

    session_id, worker_id, account_id = setup_session
    orchestrator = PaperOrchestrator(db_session, MockAdapter())

    # We use transaction_b_reserve_cash to safely insert the first 7,000 active reservation
    from app.models.trading import SignalModel

    sig0 = Signal(
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
        quantity=Decimal("70.0"),
        metadata={"time_in_force": "GTC"},
    )
    rd0 = RiskDecision(
        decision_id=uuid.uuid4(),
        correlation_id=sig0.correlation_id,
        signal_id=sig0.signal_id,
        status=RiskDecisionStatus.APPROVED,
        trading_mode="PAPER",
        calculated_quantity=Decimal("70.0"),
        authorized_cash_requirement=Decimal("7000.0"),
        risk_policy_version="1.0",
        timestamp=_now(),
    )
    db_session.add(SignalModel(**sig0.model_dump(mode="python")))
    await db_session.commit()

    success0 = await orchestrator.transaction_b_reserve_cash(session_id, worker_id, sig0, rd0)
    assert success0 is True

    # Test 3,000 should pass (7,000 + 3,000 = 10,000 <= 10,000)
    sig1 = Signal(
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
        quantity=Decimal("30.0"),
        metadata={"time_in_force": "GTC"},
    )
    rd1 = RiskDecision(
        decision_id=uuid.uuid4(),
        correlation_id=sig1.correlation_id,
        signal_id=sig1.signal_id,
        status=RiskDecisionStatus.APPROVED,
        trading_mode="PAPER",
        calculated_quantity=Decimal("30.0"),
        authorized_cash_requirement=Decimal("3000.0"),
        risk_policy_version="1.0",
        timestamp=_now(),
    )
    db_session.add(SignalModel(**sig1.model_dump(mode="python")))
    await db_session.commit()

    success1 = await orchestrator.transaction_b_reserve_cash(session_id, worker_id, sig1, rd1)
    assert success1 is True

    # Clean up the 3000 reservation so we can test 3000.01 cleanly
    from app.models.trading import OrderIntentModel, OrderModel, RiskDecisionModel
    from sqlalchemy import delete

    await db_session.execute(delete(OrderModel).where(OrderModel.quantity == Decimal("30.0")))
    await db_session.execute(
        delete(CashReservationModel).where(
            CashReservationModel.authorized_cash_requirement == Decimal("3000.0")
        )
    )
    await db_session.execute(
        delete(OrderIntentModel).where(OrderIntentModel.quantity == Decimal("30.0"))
    )
    await db_session.execute(
        delete(RiskDecisionModel).where(RiskDecisionModel.calculated_quantity == Decimal("30.0"))
    )
    await db_session.commit()

    # Test 3,000.01 should fail
    sig2 = Signal(
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
        quantity=Decimal("30.0001"),
        metadata={"time_in_force": "GTC"},
    )
    rd2 = RiskDecision(
        decision_id=uuid.uuid4(),
        correlation_id=sig2.correlation_id,
        signal_id=sig2.signal_id,
        status=RiskDecisionStatus.APPROVED,
        trading_mode="PAPER",
        calculated_quantity=Decimal("30.0001"),
        authorized_cash_requirement=Decimal("3000.01"),
        risk_policy_version="1.0",
        timestamp=_now(),
    )
    db_session.add(SignalModel(**sig2.model_dump(mode="python")))
    await db_session.commit()

    success2 = await orchestrator.transaction_b_reserve_cash(session_id, worker_id, sig2, rd2)
    assert success2 is False


async def test_lease_lifecycle(db_session: AsyncSession, setup_session):
    session_id, worker_id, account_id = setup_session
    orchestrator = PaperOrchestrator(db_session, MockAdapter())
    worker_2 = uuid.uuid4()

    assert await orchestrator.release_lease(session_id, worker_id) is True
    assert await orchestrator.acquire_lease(session_id, worker_2) is True
    assert await orchestrator.renew_lease(session_id, worker_2) is True

    session = await db_session.execute(
        select(PaperSessionModel).where(PaperSessionModel.session_id == session_id)
    )
    session = session.scalar_one()
    session.worker_heartbeat = _now() - timedelta(seconds=35)
    await db_session.commit()

    assert await orchestrator.renew_lease(session_id, worker_2) is False
    worker_3 = uuid.uuid4()
    assert await orchestrator.acquire_lease(session_id, worker_3) is True


@pytest.mark.asyncio
async def test_risk_decision_gate(db_session: AsyncSession, setup_session):
    session_id, worker_id, account_id = setup_session
    orchestrator = PaperOrchestrator(db_session, MockAdapter())

    sig = Signal(
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
        metadata={"source": "test"},
    )
    rd = RiskDecision(
        decision_id=uuid.uuid4(),
        correlation_id=sig.correlation_id,
        signal_id=sig.signal_id,
        status=RiskDecisionStatus.REJECTED,
        trading_mode="PAPER",
        calculated_quantity=None,
        authorized_cash_requirement=None,
        risk_policy_version="1.0",
        timestamp=_now(),
        rejection_codes=["INVALID_SIGNAL"],
    )
    db_session.add(SignalModel(**sig.model_dump(mode="python")))
    await db_session.commit()

    res = await orchestrator.transaction_b_reserve_cash(session_id, worker_id, sig, rd)
    assert res is False


@pytest.mark.asyncio
async def test_market_data_exceptions(db_session: AsyncSession, setup_session):
    session_id, worker_id, account_id = setup_session
    orchestrator = PaperOrchestrator(db_session, MockAdapter())

    from unittest.mock import MagicMock

    runner = MagicMock()
    runner.strategy_class.metadata.required_history_candles = 0
    ctx = MagicMock()
    ctx._history = []
    runner._get_or_create_context.return_value = ctx

    runner.process_candle.side_effect = DuplicateDataError("dup")
    await orchestrator.run_pipeline_for_candle(
        session_id, worker_id, MagicMock(), runner, MagicMock(), MagicMock(), MagicMock()
    )

    session = await db_session.execute(
        select(PaperSessionModel).where(PaperSessionModel.session_id == session_id)
    )
    session = session.scalar_one()
    assert session.state == PaperSessionState.RUNNING

    runner.process_candle.side_effect = ChronologicalDataError("out of order")
    await orchestrator.run_pipeline_for_candle(
        session_id, worker_id, MagicMock(), runner, MagicMock(), MagicMock(), MagicMock()
    )
    await db_session.refresh(session)
    assert session.state == PaperSessionState.HALTED


@pytest.mark.asyncio
async def test_buy_sell_accounting(db_session: AsyncSession, setup_session):
    session_id, worker_id, account_id = setup_session
    orchestrator = PaperOrchestrator(db_session, MockAdapter())

    sig1 = Signal(
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
        quantity=Decimal("10.0"),
        metadata={"source": "test"},
    )
    rd1 = RiskDecision(
        decision_id=uuid.uuid4(),
        correlation_id=sig1.correlation_id,
        signal_id=sig1.signal_id,
        status=RiskDecisionStatus.APPROVED,
        trading_mode="PAPER",
        calculated_quantity=Decimal("10.0"),
        authorized_cash_requirement=Decimal("1000.0"),
        risk_policy_version="1.0",
        timestamp=_now(),
    )
    db_session.add(SignalModel(**sig1.model_dump(mode="python")))
    await db_session.commit()

    await orchestrator.transaction_b_reserve_cash(session_id, worker_id, sig1, rd1)
    order = await db_session.execute(
        select(OrderModel).where(OrderModel.correlation_id == rd1.correlation_id)
    )
    order = order.scalar_one()
    await orchestrator.transaction_c_acknowledge(
        session_id, worker_id, order.order_id, Decimal("100.0"), Decimal("0.0")
    )
    await orchestrator.transaction_d_fill(session_id, worker_id, order.order_id)

    pos = await db_session.execute(
        select(PositionModel).where(PositionModel.account_id == account_id)
    )
    pos = pos.scalar_one()
    assert pos.quantity == Decimal("10.0")
    assert pos.average_entry_price == Decimal("100.0")

    sig2 = Signal(
        signal_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        strategy_id="test",
        strategy_version="1.0",
        symbol="BTC-USD",
        timestamp=_now(),
        timeframe="1h",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        signal_type="EXIT",
        quantity=Decimal("5.0"),
        metadata={"source": "test"},
    )
    rd2 = RiskDecision(
        decision_id=uuid.uuid4(),
        correlation_id=sig2.correlation_id,
        signal_id=sig2.signal_id,
        status=RiskDecisionStatus.APPROVED,
        trading_mode="PAPER",
        calculated_quantity=Decimal("5.0"),
        authorized_cash_requirement=Decimal("0.0"),
        risk_policy_version="1.0",
        timestamp=_now(),
    )
    db_session.add(SignalModel(**sig2.model_dump(mode="python")))
    await db_session.commit()

    await orchestrator.transaction_b_reserve_cash(session_id, worker_id, sig2, rd2)
    order2 = await db_session.execute(
        select(OrderModel).where(OrderModel.correlation_id == rd2.correlation_id)
    )
    order2 = order2.scalar_one()
    res_c = await orchestrator.transaction_c_acknowledge(
        session_id, worker_id, order2.order_id, Decimal("120.0"), Decimal("0.0")
    )
    assert res_c is True
    res_d = await orchestrator.transaction_d_fill(session_id, worker_id, order2.order_id)
    assert res_d is True

    await db_session.refresh(pos)
    assert pos.quantity == Decimal("5.0")

    port = await db_session.execute(
        select(PortfolioSnapshotModel)
        .where(PortfolioSnapshotModel.account_id == account_id)
        .order_by(PortfolioSnapshotModel.timestamp.desc())
    )
    port = port.scalars().first()
    assert port.total_realized_pnl == Decimal("100.0")


async def test_insufficient_history_fails_closed(
    db_session: AsyncSession, mock_adapter, setup_session
):
    session_id, worker_id, account_id = setup_session

    version_record = StrategyVersionModel(
        strategy_id="MA_Crossover_Reference",
        version="1.0.0",
        source_hash=StrategyRegistry.get("MA_Crossover_Reference", "1.0.0")[1],
        status="ACTIVE",
    )

    runner = StrategyRunner(
        version_record, {"fast_period": 10, "slow_period": 20, "risk_percent": "0.05"}
    )

    # Require 50, provide 49
    history_candles = []
    for i in range(49):
        candle = Candle(
            symbol="BTC-USD",
            timestamp=_now() - timedelta(minutes=60 - i),
            timeframe="1h",
            open=Decimal("100.0"),
            high=Decimal("110.0"),
            low=Decimal("90.0"),
            close=Decimal("100.0"),
            volume=Decimal("1.0"),
        )
        history_candles.append(candle)

    import pytest
    from app.models.base import HistoricalDataIncompleteError

    with pytest.raises(HistoricalDataIncompleteError):
        runner.hydrate_history("BTC-USD", "1h", history_candles)

    ctx = runner._get_or_create_context("BTC-USD", "1h")
    assert ctx._history == []
