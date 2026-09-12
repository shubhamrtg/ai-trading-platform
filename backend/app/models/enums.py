from enum import Enum


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    STOP_LIMIT = "STOP_LIMIT"


class TimeInForce(str, Enum):
    GTC = "GTC"  # Good Till Cancelled
    IOC = "IOC"  # Immediate Or Cancel
    FOK = "FOK"  # Fill Or Kill
    DAY = "DAY"  # Day Order


class OrderState(str, Enum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class PositionState(str, Enum):
    OPENING = "OPENING"
    OPEN = "OPEN"
    REDUCING = "REDUCING"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class SignalType(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


class RiskDecisionStatus(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MODIFIED = "MODIFIED"


class AIRecommendation(str, Enum):
    ALLOW = "ALLOW"
    REJECT = "REJECT"
    HOLD = "HOLD"
