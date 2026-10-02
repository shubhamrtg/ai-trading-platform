import asyncio
import os
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
async def test_cash_concurrency_a_b():
    import uuid
    from decimal import Decimal

    from app.config.settings import Settings
    from app.models.base import Base
    from app.models.enums import OrderSide, OrderType, RiskDecisionStatus
    from app.models.paper import CashReservationModel, PaperSessionModel, PaperSessionState
    from app.models.portfolio import PortfolioSnapshotModel
    from app.models.trading import SignalModel
    from app.paper.orchestrator import PaperOrchestrator
    from app.schemas.risk import RiskDecision
    from app.schemas.signal import Signal
    from sqlalchemy import func, select, text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool

    from tests.test_k1_rules import MockAdapter

    # Use PostgreSQL for genuine row-lock concurrency proof.
    # Fallback to the application default if no explicit test URL provided.
    default_pg_url = Settings.model_fields["database_url"].default
    pg_url = os.environ.get("POSTGRES_TEST_URL", default_pg_url)

    schema_name = f"test_k1_{uuid.uuid4().hex}"
    admin_engine = None
    a_lock_acquired = None
    a_can_complete = None
    engine1 = None
    engine2 = None
    engine3 = None
    session_a = None
    session_b = None
    task_a = None
    task_b = None

    try:
        # Create isolated schema safely without dropping application tables
        admin_engine = create_async_engine(pg_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
        async with admin_engine.connect() as conn:
            await conn.execute(text(f"CREATE SCHEMA {schema_name}"))
        await admin_engine.dispose()
        admin_engine = None

        # Use the isolated schema for all test connections
        app_name_a = f"k1_worker_a_{uuid.uuid4().hex}"
        app_name_b = f"k1_worker_b_{uuid.uuid4().hex}"
        connect_args_a = {
            "server_settings": {"search_path": schema_name, "application_name": app_name_a}
        }
        connect_args_b = {
            "server_settings": {"search_path": schema_name, "application_name": app_name_b}
        }
        connect_args_verify = {
            "server_settings": {
                "search_path": schema_name,
                "application_name": f"k1_verify_{uuid.uuid4().hex}"
            }
        }

        engine1 = create_async_engine(pg_url, poolclass=NullPool, connect_args=connect_args_a)
        engine2 = create_async_engine(pg_url, poolclass=NullPool, connect_args=connect_args_b)
        engine3 = create_async_engine(pg_url, poolclass=NullPool, connect_args=connect_args_verify)

        async with engine1.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        account_id = f"test-account-{uuid.uuid4()}"
        worker_a_id = uuid.uuid4()
        worker_b_id = uuid.uuid4()
        session_id = uuid.uuid4()

        async with AsyncSession(engine1) as init_db:
            init_db.add(
                PortfolioSnapshotModel(
                    snapshot_id=uuid.uuid4(),
                    account_id=account_id,
                    timestamp=_now(),
                    cash=Decimal("10000.0"),
                    available_cash=Decimal("10000.0"),
                    equity=Decimal("10000.0"),
                    total_realized_pnl=Decimal("0.0"),
                    total_unrealized_pnl=Decimal("0.0"),
                    total_exposure=Decimal("0.0"),
                    reserved_capital=Decimal("0.0"),
                )
            )
            session_id_a = session_id
            session_id_b = uuid.uuid4()
            init_db.add(
                PaperSessionModel(
                    session_id=session_id_a,
                    account_id=account_id,
                    strategy_id="test",
                    strategy_version="1.0",
                    symbol="BTC-USD",
                    timeframe="1h",
                    state=PaperSessionState.RUNNING,
                    worker_owner_id=worker_a_id,
                    worker_heartbeat=_now(),
                    created_at=_now(),
                )
            )
            init_db.add(
                PaperSessionModel(
                    session_id=session_id_b,
                    account_id=account_id,
                    strategy_id="test",
                    strategy_version="1.0",
                    symbol="BTC-USD",
                    timeframe="1h",
                    state=PaperSessionState.RUNNING,
                    worker_owner_id=worker_b_id,
                    worker_heartbeat=_now(),
                    created_at=_now(),
                )
            )
            await init_db.commit()

        # Shared events to coordinate A and B deterministically
        a_lock_acquired = asyncio.Event()
        a_can_complete = asyncio.Event()
        session_a = AsyncSession(engine1)
        session_b = AsyncSession(engine2)

        orig_execute_a = session_a.execute
        import types

        async def wrapped_execute_a(self_obj, *args, **kwargs):
            stmt = args[0]
            res = await orig_execute_a(*args, **kwargs)
            if "FOR UPDATE" in str(stmt).upper() and "portfolio_snapshots" in str(stmt).lower():
                a_lock_acquired.set()
                await a_can_complete.wait()
            return res

        session_a.execute = types.MethodType(wrapped_execute_a, session_a)

        orchestrator_a = PaperOrchestrator(session_a, MockAdapter())

        async def mock_check(*args):
            return True

        orchestrator_a.check_lease = mock_check
        orchestrator_b = PaperOrchestrator(session_b, MockAdapter())
        orchestrator_b.check_lease = mock_check

        sig_a = Signal(
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
            metadata={"time_in_force": "GTC"},
        )
        rd_a = RiskDecision(
            decision_id=uuid.uuid4(),
            correlation_id=sig_a.correlation_id,
            signal_id=sig_a.signal_id,
            status=RiskDecisionStatus.APPROVED,
            trading_mode="PAPER",
            calculated_quantity=Decimal("60.0"),
            authorized_cash_requirement=Decimal("6000.0"),
            risk_policy_version="1.0",
            timestamp=_now(),
        )

        sig_b = Signal(
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
            metadata={"time_in_force": "GTC"},
        )
        rd_b = RiskDecision(
            decision_id=uuid.uuid4(),
            correlation_id=sig_b.correlation_id,
            signal_id=sig_b.signal_id,
            status=RiskDecisionStatus.APPROVED,
            trading_mode="PAPER",
            calculated_quantity=Decimal("60.0"),
            authorized_cash_requirement=Decimal("6000.0"),
            risk_policy_version="1.0",
            timestamp=_now(),
        )

        async with AsyncSession(engine1) as sig_db:
            sig_db.add(SignalModel(**sig_a.model_dump(mode="python")))
            sig_db.add(SignalModel(**sig_b.model_dump(mode="python")))
            await sig_db.commit()

        # Start Worker A
        task_a = asyncio.create_task(
            orchestrator_a.transaction_b_reserve_cash(session_id_a, worker_a_id, sig_a, rd_a)
        )

        # Wait for A to acquire the row lock
        await asyncio.wait_for(a_lock_acquired.wait(), timeout=5.0)

        # Start Worker B
        task_b = asyncio.create_task(
            orchestrator_b.transaction_b_reserve_cash(session_id_b, worker_b_id, sig_b, rd_b)
        )

        # Prove B is ACTUALLY waiting at the database level using pg_stat_activity
        b_is_blocked = False
        async with engine3.connect() as verify_conn:
            for _ in range(50):  # Bounded timeout of 5 seconds
                res = await verify_conn.execute(text(f"""
                    SELECT
                        a.pid as worker_a_pid,
                        b.pid as worker_b_pid,
                        b.wait_event_type as worker_b_wait_event,
                        pg_blocking_pids(b.pid) as blocking_pids
                    FROM pg_stat_activity a, pg_stat_activity b
                    WHERE a.application_name = '{app_name_a}'
                      AND b.application_name = '{app_name_b}'
                """))

                rows = res.fetchall()
                if rows:
                    row = rows[0]
                    worker_a_pid = row[0]
                    worker_b_wait = row[2]
                    blocking_pids = row[3] or []

                    if worker_b_wait == 'Lock' and worker_a_pid in blocking_pids:
                        b_is_blocked = True
                        break

                await asyncio.sleep(0.1)

        # Release A so we don't hang teardown
        a_can_complete.set()

        # Gather tasks BEFORE asserting, so we don't skip task teardown and hang engine.dispose()
        res_a, res_b = await asyncio.gather(task_a, task_b)

        assert b_is_blocked, (
            "Worker B never reached the PostgreSQL lock wait state, "
            "or was not blocked by Worker A"
        )


        # Verify exact outcomes: One success, one legitimate business rejection (not an exception)
        assert (res_a is True and res_b is False) or (res_a is False and res_b is True)

        async with AsyncSession(engine3) as verify_db:
            res_sum = await verify_db.execute(
                select(func.sum(CashReservationModel.authorized_cash_requirement)).where(
                    CashReservationModel.active.is_(True),
                    CashReservationModel.session_id.in_([session_id_a, session_id_b]),
                )
            )
            total_req = res_sum.scalar() or Decimal("0.0")
            assert total_req == Decimal("6000.0"), "Only one transaction should have reserved cash"

    finally:
        # 1. Signal Worker A to stop waiting
        if a_can_complete is not None:
            a_can_complete.set()

        # 2. Cancel/await unfinished Worker A/B tasks safely
        for task in (task_a, task_b):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # 3. Close session_a/session_b
        if session_a is not None:
            await session_a.close()
        if session_b is not None:
            await session_b.close()

        # 4. Dispose worker/verification engines
        if engine1 is not None:
            await engine1.dispose()
        if engine2 is not None:
            await engine2.dispose()
        if engine3 is not None:
            await engine3.dispose()

        if admin_engine is not None:
            await admin_engine.dispose()

        # 5. Drop only the isolated PostgreSQL schema
        # 6. Dispose cleanup/admin engine
        try:
            admin_engine_cleanup = create_async_engine(
                pg_url, poolclass=NullPool, isolation_level="AUTOCOMMIT"
            )
            async with admin_engine_cleanup.connect() as conn:
                await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE"))
            await admin_engine_cleanup.dispose()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_cash_reservation_boundary(db_session: AsyncSession, setup_session):
    import uuid
    from decimal import Decimal

    from app.models.enums import OrderSide, OrderType, RiskDecisionStatus
    from app.models.paper import CashReservationModel
    from app.models.trading import OrderIntentModel, OrderModel, RiskDecisionModel, SignalModel
    from app.paper.orchestrator import PaperOrchestrator
    from app.schemas.risk import RiskDecision
    from app.schemas.signal import Signal
    from sqlalchemy import delete

    from tests.test_k1_rules import MockAdapter

    session_id, worker_id, account_id = setup_session
    orchestrator = PaperOrchestrator(db_session, MockAdapter())

    # 1. 7000 active reservation
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

    # 2. Test 3,000 should pass (7,000 + 3,000 = 10,000 <= 10,000)
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

    from sqlalchemy import select

    intent_record = await db_session.execute(
        select(OrderIntentModel).where(OrderIntentModel.correlation_id == sig1.correlation_id)
    )
    intent_id = intent_record.scalar_one().intent_id
    await db_session.execute(
        delete(OrderModel).where(OrderModel.correlation_id == sig1.correlation_id)
    )
    await db_session.execute(
        delete(CashReservationModel).where(CashReservationModel.order_intent_id == intent_id)
    )
    await db_session.execute(
        delete(OrderIntentModel).where(OrderIntentModel.intent_id == intent_id)
    )
    await db_session.execute(
        delete(RiskDecisionModel).where(RiskDecisionModel.decision_id == rd1.decision_id)
    )
    await db_session.execute(delete(SignalModel).where(SignalModel.signal_id == sig1.signal_id))
    await db_session.commit()

    # 3. Test one-cent over (7,000 + 3,000.01 = 10,000.01 > 10,000)
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
        quantity=Decimal("30.0"),
        metadata={"time_in_force": "GTC"},
    )
    rd2 = RiskDecision(
        decision_id=uuid.uuid4(),
        correlation_id=sig2.correlation_id,
        signal_id=sig2.signal_id,
        status=RiskDecisionStatus.APPROVED,
        trading_mode="PAPER",
        calculated_quantity=Decimal("30.0"),
        authorized_cash_requirement=Decimal("3000.01"),
        risk_policy_version="1.0",
        timestamp=_now(),
    )
    db_session.add(SignalModel(**sig2.model_dump(mode="python")))
    await db_session.commit()

    success2 = await orchestrator.transaction_b_reserve_cash(session_id, worker_id, sig2, rd2)
    assert success2 is False


@pytest.mark.asyncio
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
        metadata={"source": "test", "time_in_force": "GTC"},
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
        metadata={"source": "test", "time_in_force": "GTC"},
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
        metadata={"source": "test", "time_in_force": "GTC"},
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


@pytest.mark.asyncio
async def test_quote_failure_recovery(db_session: AsyncSession, setup_session):
    import uuid
    from decimal import Decimal

    from app.models.enums import OrderSide, OrderState, OrderType, RiskDecisionStatus
    from app.models.paper import CashReservationModel
    from app.models.trading import OrderModel
    from app.paper.orchestrator import PaperOrchestrator
    from app.schemas.risk import RiskDecision
    from app.schemas.signal import Signal
    from sqlalchemy import select

    session_id, worker_id, account_id = setup_session

    class FailingAdapter:
        async def get_quote(self, symbol: str):
            raise RuntimeError("Fake quote acquisition failure")

    orchestrator = PaperOrchestrator(db_session, FailingAdapter())

    class DummyRunner:
        def process_candle(self, candle):
            return Signal(
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
                metadata={"time_in_force": "GTC"},
            )

    class DummySizer:
        def calculate_size(self, signal, portfolio_equity, current_position_quantity):
            from app.schemas.paper import SizingResult

            return SizingResult(is_valid=True, quantity=signal.quantity, reason="ok")

    class DummyRisk:
        def evaluate(self, signal, context, policy, sizing_result):
            return RiskDecision(
                decision_id=uuid.uuid4(),
                correlation_id=signal.correlation_id,
                signal_id=signal.signal_id,
                status=RiskDecisionStatus.APPROVED,
                trading_mode="PAPER",
                calculated_quantity=signal.quantity,
                calculated_risk=Decimal("0.0"),
                authorized_cash_requirement=Decimal("1000.0"),
                risk_policy_version="1.0",
                timestamp=_now(),
            )

    # 1. Run pipeline - this will do Tx B, then get_quote, which fails, calling cancel recovery.
    await orchestrator.run_pipeline_for_candle(
        session_id=session_id,
        worker_id=worker_id,
        candle={},
        runner=DummyRunner(),
        position_sizer=DummySizer(),
        risk_engine=DummyRisk(),
        risk_policy={},
    )

    # Verify Order is CANCELLED and reservation released
    order = await db_session.execute(select(OrderModel))
    order = order.scalars().first()

    assert order.state == OrderState.CANCELLED

    res = await db_session.execute(
        select(CashReservationModel).where(CashReservationModel.order_intent_id == order.intent_id)
    )
    res = res.scalar_one()
    assert res.active is False
    assert res.released_timestamp is not None

    # 3. Test idempotent recovery
    await orchestrator.transaction_cancel_submitted_order(
        session_id, worker_id, order.order_id, "retry"
    )
    await db_session.refresh(res)
    assert res.active is False

    # Verify no Fill, no Portfolio mutation
    from app.models.portfolio import PortfolioSnapshotModel
    from app.models.trading import FillModel

    fills = await db_session.execute(select(FillModel))
    assert len(fills.scalars().all()) == 0

    snapshots = await db_session.execute(select(PortfolioSnapshotModel))
    snapshots = snapshots.scalars().all()
    # Only the initial snapshot should exist
    assert len(snapshots) == 1


@pytest.mark.asyncio
async def test_unexpected_sizing_failure(db_session: AsyncSession, setup_session):
    import uuid
    from datetime import UTC, datetime
    from decimal import Decimal

    from app.paper.orchestrator import PaperOrchestrator

    def _now():
        return datetime.now(UTC)

    session_id, worker_id, account_id = setup_session

    orchestrator = PaperOrchestrator(db_session, MockAdapter())

    class BuggySizer:
        def calculate_size(self, *args, **kwargs):
            raise RuntimeError("Unexpected infrastructure bug in Sizer")

    from app.models.base import ApplicationFailureError

    candle = type("Candle", (), {"symbol": "BTC-USD"})()

    class DummyRunner:
        def _get_or_create_context(self, *args, **kwargs):
            class Ctx:
                def __init__(self):
                    self.id = uuid.uuid4()

            return Ctx()

        def process_market_data(self, *args, **kwargs):
            from app.models.enums import OrderSide, OrderType
            from app.schemas.signal import Signal

            return Signal(
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
                metadata={"time_in_force": "GTC"},
            )

    class DummyRisk:
        pass

    with pytest.raises(ApplicationFailureError) as exc_info:
        await orchestrator.run_pipeline_for_candle(
            session_id, worker_id, candle, DummyRunner(), BuggySizer(), DummyRisk(), {}
        )
    assert "Unexpected system failure" in str(exc_info.value)


@pytest.mark.asyncio
async def test_transaction_d_idempotency(db_session: AsyncSession, setup_session):
    import uuid
    from decimal import Decimal

    from app.models.enums import OrderSide, OrderState, OrderType, RiskDecisionStatus
    from app.models.paper import CashReservationModel
    from app.models.portfolio import PortfolioSnapshotModel, PositionModel
    from app.models.trading import FillModel, OrderModel, SignalModel
    from app.paper.orchestrator import PaperOrchestrator
    from app.schemas.risk import RiskDecision
    from app.schemas.signal import Signal
    from sqlalchemy import select

    from tests.test_k1_rules import MockAdapter

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
        quantity=Decimal("10.0"),
        metadata={"time_in_force": "GTC"},
    )
    rd = RiskDecision(
        decision_id=uuid.uuid4(),
        correlation_id=sig.correlation_id,
        signal_id=sig.signal_id,
        status=RiskDecisionStatus.APPROVED,
        trading_mode="PAPER",
        calculated_quantity=Decimal("10.0"),
        authorized_cash_requirement=Decimal("1000.0"),
        risk_policy_version="1.0",
        timestamp=_now(),
    )

    db_session.add(SignalModel(**sig.model_dump(mode="python")))
    await db_session.flush()

    await orchestrator.transaction_b_reserve_cash(session_id, worker_id, sig, rd)

    order = await db_session.execute(
        select(OrderModel).where(OrderModel.correlation_id == sig.correlation_id)
    )
    order = order.scalar_one()

    await orchestrator.transaction_c_acknowledge(
        session_id, worker_id, order.order_id, Decimal("100.0"), Decimal("0.0")
    )

    res_d_1 = await orchestrator.transaction_d_fill(session_id, worker_id, order.order_id)
    assert res_d_1 is True

    # CAPTURE EVERYTHING
    fills = await db_session.execute(select(FillModel).where(FillModel.order_id == order.order_id))
    fills = fills.scalars().all()
    fill_count_1 = len(fills)
    fill_id_1 = fills[0].fill_id

    portfolios = await db_session.execute(
        select(PortfolioSnapshotModel)
        .where(PortfolioSnapshotModel.account_id == account_id)
        .order_by(
            PortfolioSnapshotModel.timestamp.desc(), PortfolioSnapshotModel.snapshot_id.desc()
        )
    )
    first_portfolio = portfolios.scalars().first()

    cash_1 = first_portfolio.cash
    available_cash_1 = first_portfolio.available_cash
    reserved_capital_1 = first_portfolio.reserved_capital
    equity_1 = first_portfolio.equity
    total_realized_pnl_1 = first_portfolio.total_realized_pnl
    total_unrealized_pnl_1 = first_portfolio.total_unrealized_pnl
    total_exposure_1 = first_portfolio.total_exposure

    pos = await db_session.execute(
        select(PositionModel).where(PositionModel.account_id == account_id)
    )
    pos = pos.scalar_one()
    pos_quantity_1 = pos.quantity
    pos_avg_entry_1 = pos.average_entry_price

    res = await db_session.execute(
        select(CashReservationModel).where(CashReservationModel.order_intent_id == order.intent_id)
    )
    res = res.scalar_one()
    res_active_1 = res.active
    res_released_timestamp_1 = res.released_timestamp

    await db_session.refresh(order)
    order_state_1 = order.state
    order_filled_quantity_1 = order.filled_quantity
    order_average_fill_price_1 = order.average_fill_price

    # CALL AGAIN
    order_id_val = order.order_id
    res_d_2 = await orchestrator.transaction_d_fill(session_id, worker_id, order_id_val)
    assert res_d_2 is False

    # ASSERT EVERYTHING REMAINS UNCHANGED
    fills2 = await db_session.execute(select(FillModel).where(FillModel.order_id == order_id_val))
    fills2 = fills2.scalars().all()
    assert len(fills2) == fill_count_1
    assert fills2[0].fill_id == fill_id_1

    portfolios2 = await db_session.execute(
        select(PortfolioSnapshotModel)
        .where(PortfolioSnapshotModel.account_id == account_id)
        .order_by(
            PortfolioSnapshotModel.timestamp.desc(), PortfolioSnapshotModel.snapshot_id.desc()
        )
    )
    portfolios2_list = portfolios2.scalars().all()
    second_portfolio = portfolios2_list[0]

    assert second_portfolio.snapshot_id == first_portfolio.snapshot_id
    assert second_portfolio.cash == cash_1
    assert second_portfolio.available_cash == available_cash_1
    assert second_portfolio.reserved_capital == reserved_capital_1
    assert second_portfolio.equity == equity_1
    assert second_portfolio.total_realized_pnl == total_realized_pnl_1
    assert second_portfolio.total_unrealized_pnl == total_unrealized_pnl_1
    assert second_portfolio.total_exposure == total_exposure_1

    pos2 = await db_session.execute(
        select(PositionModel).where(PositionModel.account_id == account_id)
    )
    pos2 = pos2.scalar_one()
    assert pos2.quantity == pos_quantity_1
    assert pos2.average_entry_price == pos_avg_entry_1

    await db_session.refresh(res)
    assert res.active == res_active_1
    assert res.released_timestamp == res_released_timestamp_1
    assert res.active is False

    await db_session.refresh(order)
    assert order.state == order_state_1
    assert order.state == OrderState.FILLED
    assert order.filled_quantity == order_filled_quantity_1
    assert order.average_fill_price == order_average_fill_price_1


@pytest.mark.asyncio
async def test_time_in_force_semantics(db_session: AsyncSession, setup_session):
    import uuid
    from decimal import Decimal

    from app.models.enums import OrderSide, OrderType, RiskDecisionStatus
    from app.models.trading import OrderIntentModel, OrderModel, SignalModel
    from app.paper.orchestrator import PaperOrchestrator
    from app.schemas.risk import RiskDecision
    from app.schemas.signal import Signal
    from sqlalchemy import select

    from tests.test_k1_rules import MockAdapter

    session_id, worker_id, account_id = setup_session
    orchestrator = PaperOrchestrator(db_session, MockAdapter())

    # 1. Missing time_in_force -> rejected
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
        quantity=Decimal("1.0"),
        metadata={},
    )
    rd1 = RiskDecision(
        decision_id=uuid.uuid4(),
        correlation_id=sig1.correlation_id,
        signal_id=sig1.signal_id,
        status=RiskDecisionStatus.APPROVED,
        trading_mode="PAPER",
        calculated_quantity=Decimal("1.0"),
        authorized_cash_requirement=Decimal("100.0"),
        risk_policy_version="1.0",
        timestamp=_now(),
    )
    db_session.add(SignalModel(**sig1.model_dump(mode="python")))
    await db_session.commit()

    import pytest
    from app.models.base import ApplicationFailureError

    with pytest.raises(ApplicationFailureError, match="(?i)(time_in_force|TimeInForce)"):
        await orchestrator.transaction_b_reserve_cash(session_id, worker_id, sig1, rd1)

    # Verify no artifacts
    intent = await db_session.execute(
        select(OrderIntentModel).where(OrderIntentModel.correlation_id == sig1.correlation_id)
    )
    assert intent.scalar_one_or_none() is None

    order = await db_session.execute(
        select(OrderModel).where(OrderModel.correlation_id == sig1.correlation_id)
    )
    assert order.scalar_one_or_none() is None

    # 2. Unsupported time_in_force -> rejected
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
        quantity=Decimal("1.0"),
        metadata={"time_in_force": "IOC"},
    )
    rd2 = RiskDecision(
        decision_id=uuid.uuid4(),
        correlation_id=sig2.correlation_id,
        signal_id=sig2.signal_id,
        status=RiskDecisionStatus.APPROVED,
        trading_mode="PAPER",
        calculated_quantity=Decimal("1.0"),
        authorized_cash_requirement=Decimal("100.0"),
        risk_policy_version="1.0",
        timestamp=_now(),
    )
    db_session.add(SignalModel(**sig2.model_dump(mode="python")))
    await db_session.commit()

    with pytest.raises(ApplicationFailureError, match="(?i)(time_in_force|TimeInForce)"):
        await orchestrator.transaction_b_reserve_cash(session_id, worker_id, sig2, rd2)

    intent2 = await db_session.execute(
        select(OrderIntentModel).where(OrderIntentModel.correlation_id == sig2.correlation_id)
    )
    assert intent2.scalar_one_or_none() is None

    # 3. Explicit GTC -> succeeds
    sig3 = Signal(
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
        metadata={"time_in_force": "GTC"},
    )
    rd3 = RiskDecision(
        decision_id=uuid.uuid4(),
        correlation_id=sig3.correlation_id,
        signal_id=sig3.signal_id,
        status=RiskDecisionStatus.APPROVED,
        trading_mode="PAPER",
        calculated_quantity=Decimal("1.0"),
        authorized_cash_requirement=Decimal("100.0"),
        risk_policy_version="1.0",
        timestamp=_now(),
    )
    db_session.add(SignalModel(**sig3.model_dump(mode="python")))
    await db_session.commit()

    res3 = await orchestrator.transaction_b_reserve_cash(session_id, worker_id, sig3, rd3)
    assert res3 is True
