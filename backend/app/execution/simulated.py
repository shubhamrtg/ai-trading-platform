import json
import uuid
from decimal import Decimal

from app.models.enums import OrderType
from app.schemas.execution import ExecutionResult, ExecutionStatus
from app.schemas.order import OrderIntent
from app.execution.adapter import ExecutionAdapter


class SimulatedExecutionAdapter(ExecutionAdapter):
    """Deterministic, pure in-memory execution adapter for Phase I.
    
    Performs NO network calls, NO database persistence, and NO live broker interactions.
    """
    
    def __init__(self, identity: str = "SIMULATED_V1"):
        self._identity = identity

    @property
    def adapter_identity(self) -> str:
        return self._identity

    def execute(self, intent: OrderIntent) -> ExecutionResult:
        """Deterministically execute an OrderIntent in full or reject it."""
        
        # 1. Validation Constraints (Simulated limits)
        if intent.quantity <= 0:
            return self._reject(intent, "INVALID_QUANTITY", "Quantity must be strictly positive.")
            
        if intent.order_type not in (OrderType.MARKET, OrderType.LIMIT):
            return self._reject(intent, "UNSUPPORTED_ORDER_TYPE", f"Order type {intent.order_type.value} is not supported by simulated adapter.")
            
        # Prices validation based on OrderType
        if intent.order_type == OrderType.LIMIT and intent.limit_price is None:
            return self._reject(intent, "INVALID_PRICE", "LIMIT order requires a limit_price.")
            
        # LIVE trading must be blocked
        if intent.trading_mode == "LIVE":
            return self._reject(intent, "EXECUTION_NOT_PERMITTED", "LIVE trading mode is blocked by the simulated adapter.")

        # 2. Deterministic Execution Identity
        # Must be based strictly on authoritative business input (OrderIntent), NOT uuid4() or datetime.now()
        identity_payload = {
            "intent_id": str(intent.intent_id),
            "correlation_id": str(intent.correlation_id),
            "adapter": self.adapter_identity,
            "action": "EXECUTE"
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
            quantity_requested=intent.quantity,
            quantity_executed=intent.quantity,  # Phase I invariant
            status=ExecutionStatus.EXECUTED,
            timestamp=intent.creation_timestamp,
            trading_mode=intent.trading_mode,
            adapter_identity=self.adapter_identity,
            rejection_reason=None
        )

    def _reject(self, intent: OrderIntent, reason_code: str, message: str) -> ExecutionResult:
        """Deterministically generate a rejection result."""
        identity_payload = {
            "intent_id": str(intent.intent_id),
            "correlation_id": str(intent.correlation_id),
            "adapter": self.adapter_identity,
            "action": "REJECT",
            "reason": reason_code
        }
        canonical_string = json.dumps(identity_payload, sort_keys=True, separators=(",", ":"))
        execution_id = uuid.uuid5(uuid.NAMESPACE_OID, canonical_string)

        return ExecutionResult(
            execution_id=execution_id,
            order_intent_id=intent.intent_id,
            correlation_id=intent.correlation_id,
            symbol=intent.symbol,
            side=intent.side,
            quantity_requested=intent.quantity,
            quantity_executed=Decimal("0"),
            status=ExecutionStatus.REJECTED,
            timestamp=intent.creation_timestamp,
            trading_mode=intent.trading_mode,
            adapter_identity=self.adapter_identity,
            rejection_reason=f"{reason_code}: {message}"
        )
