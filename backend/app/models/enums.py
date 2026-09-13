"""Domain enumerations for the AI Trading Platform.

All enums use (str, Enum) pattern intentionally for SQLAlchemy string column
compatibility. Values are persisted as plain strings in the database, avoiding
PostgreSQL native enum types which complicate future migrations.

This is an intentional design choice documented here. Ruff UP042 is suppressed
project-wide for this reason.
"""

from enum import Enum


class OrderSide(str, Enum):
    """Side of a trading order."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Type of order to place."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    STOP_LIMIT = "STOP_LIMIT"


class TimeInForce(str, Enum):
    """Duration policy for an order."""

    GTC = "GTC"  # Good Till Cancelled
    IOC = "IOC"  # Immediate Or Cancel
    FOK = "FOK"  # Fill Or Kill
    DAY = "DAY"  # Day Order


class OrderState(str, Enum):
    """Lifecycle state of an Order.

    Valid transitions (enforced by future execution engine):
      CREATED → VALIDATED → SUBMITTED → ACKNOWLEDGED
      ACKNOWLEDGED → PARTIALLY_FILLED → FILLED
      ACKNOWLEDGED → CANCELLED | EXPIRED | FAILED
      SUBMITTED → REJECTED
      Any active state → CANCEL_PENDING → CANCELLED
    """

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
    """Lifecycle state of a Position."""

    OPENING = "OPENING"
    OPEN = "OPEN"
    REDUCING = "REDUCING"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class SignalType(str, Enum):
    """Type of trading signal."""

    ENTRY = "ENTRY"
    EXIT = "EXIT"


class RiskDecisionStatus(str, Enum):
    """Outcome of the Risk Engine's evaluation."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MODIFIED = "MODIFIED"


class AIRecommendation(str, Enum):
    """AI advisory layer recommendation. Advisory only, never authoritative."""

    ALLOW = "ALLOW"
    REJECT = "REJECT"
    HOLD = "HOLD"


class StrategyStatus(str, Enum):
    """Lifecycle status of a registered strategy or strategy version."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    DISABLED = "DISABLED"
