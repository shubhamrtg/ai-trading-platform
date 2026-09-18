import json
import uuid
from decimal import Decimal

from app.config.settings import TradingMode
from app.execution.adapter import ExecutionAdapter
from app.models.enums import OrderType
from app.schemas.execution import ExecutionResult, ExecutionStatus
from app.schemas.order import OrderIntent


class SimulatedExecutionAdapter(ExecutionAdapter):
    """A purely deterministic execution adapter for Phase I.

    Operates strictly in-memory without network, database, or background dependencies.
    For Phase I, it deterministically fills MARKET and LIMIT orders completely.
    Rejects LIVE trading, negative quantities, missing limit prices, and STOP orders.
    """

    def __init__(self, identity: str = "SIMULATED_V1"):
        self._identity = identity

    @property
    def adapter_identity(self) -> str:
        return self._identity

    def execute(self, intent: OrderIntent) -> ExecutionResult:
        # 1. Structural validations (safety net below the Pydantic boundary)
        if intent.quantity <= 0:
            return self._reject(intent, "INVALID_QUANTITY", "Quantity must be positive.")

        if intent.order_type not in (OrderType.MARKET, OrderType.LIMIT):
            return self._reject(
                intent,
                "UNSUPPORTED_ORDER_TYPE",
                f"OrderType.{intent.order_type.name} is not supported by the simulated adapter.",
            )

        if intent.order_type == OrderType.LIMIT and intent.limit_price is None:
            return self._reject(intent, "INVALID_PRICE", "LIMIT order requires a limit_price.")

        # LIVE trading must be blocked
        if intent.trading_mode == TradingMode.LIVE:
            return self._reject(
                intent,
                "EXECUTION_NOT_PERMITTED",
                "LIVE trading mode is blocked by the simulated adapter.",
            )

        # 2. Deterministic Execution Identity
        # Must be based strictly on authoritative business input (OrderIntent), NOT uuid4() or datetime.now()
        identity_payload = {
            "intent_id": str(intent.intent_id),
            "correlation_id": str(intent.correlation_id),
            "adapter": self.adapter_identity,
            "action": "EXECUTE",
        }
        canonical_string = json.dumps(identity_payload, sort_keys=True, separators=(",", ":"))
        execution_id = uuid.uuid5(uuid.NAMESPACE_OID, canonical_string)

        # 3. Deterministic Full Fill
        # In Phase I, execution is purely deterministic: it fills entirely.
        return ExecutionResult(
            execution_id=execution_id,
            order_intent_id=intent.intent_id,
            correlation_id=intent.correlation_id,
            symbol=intent.symbol,
            side=intent.side,
            order_type=intent.order_type,
            quantity_requested=intent.quantity,
            quantity_executed=intent.quantity,  # Phase I invariant
            status=ExecutionStatus.EXECUTED,
            timestamp=intent.creation_timestamp,
            trading_mode=intent.trading_mode,
            adapter_identity=self.adapter_identity,
            rejection_reason=None,
        )

    def _reject(self, intent: OrderIntent, reason_code: str, message: str) -> ExecutionResult:
        """Deterministically generate a rejection result."""
        identity_payload = {
            "intent_id": str(intent.intent_id),
            "correlation_id": str(intent.correlation_id),
            "adapter": self.adapter_identity,
            "action": "REJECT",
            "reason": reason_code,
        }
        canonical_string = json.dumps(identity_payload, sort_keys=True, separators=(",", ":"))
        execution_id = uuid.uuid5(uuid.NAMESPACE_OID, canonical_string)

        return ExecutionResult(
            execution_id=execution_id,
            order_intent_id=intent.intent_id,
            correlation_id=intent.correlation_id,
            symbol=intent.symbol,
            side=intent.side,
            order_type=intent.order_type,
            quantity_requested=intent.quantity,
            quantity_executed=Decimal("0"),
            status=ExecutionStatus.REJECTED,
            timestamp=intent.creation_timestamp,
            trading_mode=intent.trading_mode,
            adapter_identity=self.adapter_identity,
            rejection_reason=f"{reason_code}: {message}",
        )
