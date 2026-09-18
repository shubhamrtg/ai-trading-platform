import uuid
from decimal import Decimal
from typing import Any

from app.config.settings import TradingMode

# The internal module token that prevents arbitrary instantiation
_ISSUANCE_TOKEN = object()


class ApprovedRiskCapability:
    """Trusted capability representing an approved risk decision.

    Can only be instantiated by the Risk Engine. This establishes an unforgeable
    application-layer trust boundary preventing callers from manually manufacturing
    execution authority via `RiskDecision(status=APPROVED)`.
    """

    _decision_id: uuid.UUID
    _risk_policy_version: str
    _trading_mode: TradingMode
    _calculated_quantity: Decimal
    _correlation_id: uuid.UUID
    
    __slots__ = (
        "_decision_id",
        "_risk_policy_version",
        "_trading_mode",
        "_calculated_quantity",
        "_correlation_id",
    )

    def __init__(
        self,
        decision_id: uuid.UUID,
        risk_policy_version: str,
        trading_mode: TradingMode,
        calculated_quantity: Decimal,
        correlation_id: uuid.UUID,
        token: Any,
    ) -> None:
        if token is not _ISSUANCE_TOKEN:
            raise ValueError(
                "ApprovedRiskCapability cannot be manufactured by callers. "
                "It must be issued through the trusted Risk Engine boundary."
            )

        # We must use object.__setattr__ because the class overrides __setattr__ to be immutable
        object.__setattr__(self, "_decision_id", decision_id)
        object.__setattr__(self, "_risk_policy_version", risk_policy_version)
        object.__setattr__(self, "_trading_mode", trading_mode)
        object.__setattr__(self, "_calculated_quantity", calculated_quantity)
        object.__setattr__(self, "_correlation_id", correlation_id)

    @property
    def decision_id(self) -> uuid.UUID:
        return self._decision_id

    @property
    def risk_policy_version(self) -> str:
        return self._risk_policy_version

    @property
    def trading_mode(self) -> TradingMode:
        return self._trading_mode

    @property
    def calculated_quantity(self) -> Decimal:
        return self._calculated_quantity

    @property
    def correlation_id(self) -> uuid.UUID:
        return self._correlation_id

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("ApprovedRiskCapability is strictly immutable.")
