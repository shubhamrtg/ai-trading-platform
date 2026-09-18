import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.config.settings import TradingMode
from app.execution.engine import ExecutionEngine, ExecutionError
from app.execution.intent import ExecutableOrderIntent
from app.execution.simulated import SimulatedExecutionAdapter
from app.models.enums import OrderSide, OrderType, RiskDecisionStatus
from app.schemas.execution import ExecutionStatus
from app.schemas.order import OrderIntent
from app.schemas.risk import RiskDecision


@pytest.fixture
def intent_factory():
    def _create(
        quantity=Decimal("1.5"),
        order_type=OrderType.MARKET,
        limit_price=None,
        trading_mode=TradingMode.PAPER,
    ) -> ExecutableOrderIntent:
        intent = OrderIntent(
            intent_id=uuid.uuid4(),
            correlation_id=uuid.uuid4(),
            originating_signal_id=uuid.uuid4(),
            risk_decision_id=uuid.uuid4(),
            account_id="ACC1",
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=order_type,
            quantity=quantity,
            limit_price=limit_price,
            stop_price=None,
            idempotency_key="idempotent_key",
            creation_timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            risk_policy_version="1.0",
            strategy_id="strat1",
            strategy_version="1.0",
            trading_mode=trading_mode,
        )
        from app.risk.capability import _ISSUANCE_TOKEN, ApprovedRiskCapability

        decision = RiskDecision(
            decision_id=intent.risk_decision_id,
            signal_id=intent.originating_signal_id,
            correlation_id=intent.correlation_id,
            status=RiskDecisionStatus.APPROVED,
            calculated_quantity=intent.quantity,
            calculated_risk=Decimal("0.0"),
            risk_limit_applied=None,
            trading_mode=intent.trading_mode,
            risk_policy_version=intent.risk_policy_version or "1.0",
            timestamp=intent.creation_timestamp,
        )
        capability = ApprovedRiskCapability(
            decision_id=decision.decision_id,
            risk_policy_version=decision.risk_policy_version,
            trading_mode=decision.trading_mode,
            calculated_quantity=decision.calculated_quantity,  # type: ignore
            correlation_id=decision.correlation_id,
            token=_ISSUANCE_TOKEN,
        )
        return ExecutableOrderIntent(intent, capability)

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


def test_validation_zero_quantity(engine: ExecutionEngine, intent_factory):
    # 19. Zero quantity rejected
    exec_intent = intent_factory()
    intent = exec_intent.intent
    object.__setattr__(intent, "quantity", Decimal("0"))
    res = engine.submit_intent(exec_intent)
    assert res.status == ExecutionStatus.REJECTED
    assert res.rejection_reason is not None and "INVALID_QUANTITY" in res.rejection_reason
    assert res.quantity_executed == Decimal("0")


def test_validation_negative_quantity(engine: ExecutionEngine, intent_factory):
    # 20. Negative quantity rejected
    exec_intent = intent_factory()
    intent = exec_intent.intent
    object.__setattr__(intent, "quantity", Decimal("-1.0"))
    res = engine.submit_intent(exec_intent)
    assert res.status == ExecutionStatus.REJECTED
    assert res.rejection_reason is not None and "INVALID_QUANTITY" in res.rejection_reason
    assert res.quantity_executed == Decimal("0")


def test_validation_unsupported_order_type(engine: ExecutionEngine, intent_factory):
    # 22. Unsupported order type rejected (e.g. STOP_MARKET not supported in simple sim yet)
    exec_intent = intent_factory()
    intent = exec_intent.intent
    object.__setattr__(intent, "order_type", OrderType.STOP_MARKET)
    res = engine.submit_intent(exec_intent)
    assert res.status == ExecutionStatus.REJECTED
    assert res.rejection_reason is not None and "UNSUPPORTED_ORDER_TYPE" in res.rejection_reason


def test_validation_invalid_price_semantics(engine: ExecutionEngine, intent_factory):
    # 23. Invalid price semantics rejected
    # Note: Pydantic rejects limit orders without limit_price in OrderIntent,
    # but we test the adapter's safety net by directly calling it if possible.
    # To bypass Pydantic for the test, we mock or construct carefully.

    # Pydantic validates `OrderIntent`. If we instantiate normally, it fails.
    with pytest.raises(ValueError, match="LIMIT orders require a limit_price"):
        intent_factory(order_type=OrderType.LIMIT, limit_price=None)

    # We can mock to test adapter safety net
    exec_intent = intent_factory(order_type=OrderType.MARKET)
    intent = exec_intent.intent
    # forcefully alter without validation
    object.__setattr__(intent, "order_type", OrderType.LIMIT)
    object.__setattr__(intent, "limit_price", None)

    res = engine.submit_intent(exec_intent)
    assert res.status == ExecutionStatus.REJECTED
    assert res.rejection_reason is not None and "INVALID_PRICE" in res.rejection_reason


def test_validation_invalid_trading_mode(engine: ExecutionEngine, intent_factory):
    # 24. Invalid trading mode rejected (LIVE)
    exec_intent = intent_factory(trading_mode=TradingMode.LIVE)
    res = engine.submit_intent(exec_intent)
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
