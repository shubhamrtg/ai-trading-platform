import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.config.settings import TradingMode
from app.execution.engine import ExecutionEngine, ExecutionError
from app.execution.intent import ExecutableOrderIntent
from app.execution.simulated import SimulatedExecutionAdapter
from app.models.enums import OrderSide, OrderType, RiskDecisionStatus, TimeInForce
from app.schemas.execution import ExecutionStatus
from app.schemas.order import OrderIntent


@pytest.fixture
def intent_factory():
    def _create(
        quantity: Decimal = Decimal("1.5"),
        order_type: OrderType = OrderType.MARKET,
        limit_price: Decimal | None = None,
        trading_mode: TradingMode = TradingMode.PAPER,
    ) -> ExecutableOrderIntent:
        from app.models.enums import SignalType
        from app.risk.engine import RiskEngine
        from app.schemas.risk import RiskContext, RiskPolicy
        from app.schemas.signal import Signal

        signal = Signal(
            signal_id=uuid.uuid4(),
            correlation_id=uuid.uuid4(),
            strategy_id="strat-1",
            strategy_version="1.0.0",
            symbol="BTC-USD",
            timestamp=datetime.now(UTC),
            timeframe="1h",
            side=OrderSide.BUY,
            order_type=order_type,
            signal_type=SignalType.ENTRY,
            quantity=quantity,
            proposed_entry_price=limit_price or Decimal("50000.0"),
            stop_loss=Decimal("45000.0"),
            take_profit=Decimal("60000.0"),
            confidence=0.9,
            rationale="Test"
        )

        context = RiskContext(
            trading_mode=trading_mode,
            current_position=Decimal("0.0"),
            current_exposure=Decimal("0.0"),
            portfolio_equity=Decimal("100000.0"),
            peak_equity=Decimal("100000.0"),
            current_equity=Decimal("100000.0"),
            available_cash=Decimal("100000.0"),
            daily_pnl=Decimal("0.0"),
            trading_halted=False,
            evaluated_at=datetime.now(UTC)
        )

        policy = RiskPolicy(
            version="1.0.0",
            max_order_quantity=Decimal("100.0"),
            max_position_quantity=Decimal("100.0"),
            max_exposure_amount=Decimal("100000.0"),
            max_exposure_percent=Decimal("1.0"),
            max_risk_per_trade=Decimal("10000.0"),
            max_daily_loss=Decimal("5000.0"),
            max_drawdown_percent=Decimal("0.2"),
            trading_halted=False
        )

        engine = RiskEngine()
        decision = engine.evaluate(signal, context, policy)

        from app.execution.intent import build_order_intent
        return build_order_intent(signal, decision, "ACC1")

    return _create


@pytest.fixture
def engine():
    adapter = SimulatedExecutionAdapter(identity="TEST_SIM_V1")
    return ExecutionEngine(adapter=adapter)


def test_basic_execution_success(engine: ExecutionEngine, intent_factory):
    # 1. Valid approved OrderIntent executes successfully
    exec_intent = intent_factory()
    intent = exec_intent.intent
    result = engine.submit_intent(exec_intent)

    assert result.status == ExecutionStatus.EXECUTED
    # 2. ExecutionResult contains correct OrderIntent identity
    assert result.order_intent_id == intent.intent_id
    # 3. Symbol propagates correctly
    assert result.symbol == intent.symbol
    # 4. Side propagates correctly
    assert result.side == intent.side
    # 5. Quantity propagates correctly
    assert result.quantity_requested == intent.quantity
    assert result.quantity_executed == intent.quantity
    # 6. OrderType propagates correctly
    assert result.order_type == intent.order_type
    # 7. TradingMode propagates correctly
    assert result.trading_mode == intent.trading_mode
    # 8. Correlation ID propagates correctly
    assert result.correlation_id == intent.correlation_id

    assert result.adapter_identity == "TEST_SIM_V1"
    assert result.rejection_reason is None


def test_execution_determinism(engine: ExecutionEngine, intent_factory):
    exec_intent = intent_factory()
    intent = exec_intent.intent

    res1 = engine.submit_intent(exec_intent)
    res2 = engine.submit_intent(exec_intent)

    # 14. Same OrderIntent produces same business execution identity
    assert res1.execution_id == res2.execution_id
    # 15. Same OrderIntent produces same business execution result
    assert res1.model_dump() == res2.model_dump()

    # 16. No uuid4-based business identity, and
    # 17. No system-clock-based deterministic identity
    # (res1 and res2 run at slightly different times, yet execution_id and timestamp are exactly identical)
    assert res1.timestamp == intent.creation_timestamp

    # 18. Different OrderIntents produce different business identities
    exec_intent_diff = intent_factory()
    res3 = engine.submit_intent(exec_intent_diff)
    assert res3.execution_id != res1.execution_id


def test_validation_zero_quantity(engine: ExecutionEngine):
    # 19. Zero quantity rejected
    # Category B: Defensive execution validation test.
    # We mock ExecutableOrderIntent and OrderIntent to simulate untrusted/malformed data reaching the engine.
    from unittest.mock import MagicMock
    mock_exec = MagicMock(spec=ExecutableOrderIntent)
    mock_intent = MagicMock(spec=OrderIntent)
    mock_intent.symbol = "BTC-USD"
    mock_intent.side = OrderSide.BUY
    mock_intent.creation_timestamp = datetime.now(UTC)
    mock_intent.quantity = Decimal("0")
    mock_intent.order_type = OrderType.MARKET
    mock_intent.trading_mode = TradingMode.PAPER
    mock_intent.intent_id = uuid.uuid4()
    mock_intent.correlation_id = uuid.uuid4()
    mock_exec.intent = mock_intent

    res = engine.submit_intent(mock_exec)
    assert res.status == ExecutionStatus.REJECTED
    assert res.rejection_reason is not None and "INVALID_QUANTITY" in res.rejection_reason
    assert res.quantity_executed == Decimal("0")


def test_validation_negative_quantity(engine: ExecutionEngine):
    # 20. Negative quantity rejected
    # Category B: Defensive execution validation test.
    from unittest.mock import MagicMock
    mock_exec = MagicMock(spec=ExecutableOrderIntent)
    mock_intent = MagicMock(spec=OrderIntent)
    mock_intent.symbol = "BTC-USD"
    mock_intent.side = OrderSide.BUY
    mock_intent.creation_timestamp = datetime.now(UTC)
    mock_intent.quantity = Decimal("-1.0")
    mock_intent.order_type = OrderType.MARKET
    mock_intent.trading_mode = TradingMode.PAPER
    mock_intent.intent_id = uuid.uuid4()
    mock_intent.correlation_id = uuid.uuid4()
    mock_exec.intent = mock_intent

    res = engine.submit_intent(mock_exec)
    assert res.status == ExecutionStatus.REJECTED
    assert res.rejection_reason is not None and "INVALID_QUANTITY" in res.rejection_reason
    assert res.quantity_executed == Decimal("0")


def test_validation_unsupported_order_type(engine: ExecutionEngine):
    # 22. Unsupported order type rejected
    # Category B: Defensive execution validation test.
    from unittest.mock import MagicMock
    mock_exec = MagicMock(spec=ExecutableOrderIntent)
    mock_intent = MagicMock(spec=OrderIntent)
    mock_intent.symbol = "BTC-USD"
    mock_intent.side = OrderSide.BUY
    mock_intent.creation_timestamp = datetime.now(UTC)
    mock_intent.quantity = Decimal("1.0")
    mock_intent.order_type = OrderType.STOP_MARKET
    mock_intent.trading_mode = TradingMode.PAPER
    mock_intent.intent_id = uuid.uuid4()
    mock_intent.correlation_id = uuid.uuid4()
    mock_exec.intent = mock_intent

    res = engine.submit_intent(mock_exec)
    assert res.status == ExecutionStatus.REJECTED
    assert res.rejection_reason is not None and "UNSUPPORTED_ORDER_TYPE" in res.rejection_reason


def test_validation_invalid_price_semantics(engine: ExecutionEngine):
    # 23. Invalid price semantics rejected
    # Category B: Defensive execution validation test.
    from unittest.mock import MagicMock
    mock_exec = MagicMock(spec=ExecutableOrderIntent)
    mock_intent = MagicMock(spec=OrderIntent)
    mock_intent.symbol = "BTC-USD"
    mock_intent.side = OrderSide.BUY
    mock_intent.creation_timestamp = datetime.now(UTC)
    mock_intent.quantity = Decimal("1.0")
    mock_intent.order_type = OrderType.LIMIT
    mock_intent.limit_price = None
    mock_intent.trading_mode = TradingMode.PAPER
    mock_intent.intent_id = uuid.uuid4()
    mock_intent.correlation_id = uuid.uuid4()
    mock_exec.intent = mock_intent

    res = engine.submit_intent(mock_exec)
    assert res.status == ExecutionStatus.REJECTED
    assert res.rejection_reason is not None and "INVALID_PRICE" in res.rejection_reason


def test_validation_invalid_trading_mode(engine: ExecutionEngine):
    # 24. Invalid trading mode rejected (LIVE)
    # Category B: Defensive execution validation test.
    from unittest.mock import MagicMock
    mock_exec = MagicMock(spec=ExecutableOrderIntent)
    mock_intent = MagicMock(spec=OrderIntent)
    mock_intent.symbol = "BTC-USD"
    mock_intent.side = OrderSide.BUY
    mock_intent.creation_timestamp = datetime.now(UTC)
    mock_intent.quantity = Decimal("1.0")
    mock_intent.order_type = OrderType.MARKET
    mock_intent.trading_mode = TradingMode.LIVE
    mock_intent.intent_id = uuid.uuid4()
    mock_intent.correlation_id = uuid.uuid4()
    mock_exec.intent = mock_intent

    res = engine.submit_intent(mock_exec)
    assert res.status == ExecutionStatus.REJECTED
    assert res.rejection_reason is not None and "EXECUTION_NOT_PERMITTED" in res.rejection_reason
    assert res.quantity_executed == Decimal("0")


def test_immutability(engine: ExecutionEngine, intent_factory):
    exec_intent = intent_factory()
    intent = exec_intent.intent
    intent_dump_before = intent.model_dump()

    engine.submit_intent(exec_intent)

    intent_dump_after = intent.model_dump()
    # 26. Input OrderIntent is unchanged after execution
    assert intent_dump_before == intent_dump_after


def test_failure_safety_invalid_input(engine: ExecutionEngine):
    # 28. Invalid input fails closed
    with pytest.raises(ExecutionError, match="requires a trustworthy ExecutableOrderIntent"):
        engine.submit_intent({"not_an": "intent"})  # type: ignore


def test_properties_and_invariants(engine: ExecutionEngine, intent_factory):
    exec_intent = intent_factory()
    intent = exec_intent.intent
    res = engine.submit_intent(exec_intent)

    # ExecutionResult.quantity_executed <= OrderIntent.quantity
    assert res.quantity_executed <= intent.quantity
    # For successful execution in Phase I:
    assert res.quantity_executed == intent.quantity

    # ExecutionResult.order_intent_id == OrderIntent.id
    assert res.order_intent_id == intent.intent_id

    # ExecutionResult.correlation_id == OrderIntent.correlation_id
    assert res.correlation_id == intent.correlation_id

    # ExecutionResult.trading_mode == OrderIntent.trading_mode
    assert res.trading_mode == intent.trading_mode
