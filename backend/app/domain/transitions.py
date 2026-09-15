"""Order state transition graph and validation logic.

The Order lifecycle is governed by an explicit state machine.
This ensures the Execution Engine and other components cannot
force an Order into an inconsistent or invalid state.
"""

from app.models.enums import OrderState

# Authoritative transition graph defining all allowed state changes
VALID_ORDER_TRANSITIONS: dict[OrderState, set[OrderState]] = {
    OrderState.CREATED: {
        OrderState.VALIDATED,
        OrderState.FAILED,
        OrderState.CANCEL_PENDING,
    },
    OrderState.VALIDATED: {
        OrderState.SUBMITTED,
        OrderState.FAILED,
        OrderState.CANCEL_PENDING,
    },
    OrderState.SUBMITTED: {
        OrderState.ACKNOWLEDGED,
        OrderState.REJECTED,
        OrderState.FAILED,
        OrderState.CANCEL_PENDING,
    },
    OrderState.ACKNOWLEDGED: {
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.EXPIRED,
        OrderState.FAILED,
        OrderState.CANCEL_PENDING,
    },
    OrderState.PARTIALLY_FILLED: {
        OrderState.PARTIALLY_FILLED,  # Consecutive partial fills allowed
        OrderState.FILLED,
        OrderState.EXPIRED,
        OrderState.FAILED,
        OrderState.CANCEL_PENDING,
    },
    OrderState.CANCEL_PENDING: {
        OrderState.CANCELLED,
        OrderState.FAILED,
    },
    # Terminal States
    OrderState.FILLED: set(),
    OrderState.CANCELLED: set(),
    OrderState.REJECTED: set(),
    OrderState.EXPIRED: set(),
    OrderState.FAILED: set(),
}

TERMINAL_STATES = {
    OrderState.FILLED,
    OrderState.CANCELLED,
    OrderState.REJECTED,
    OrderState.EXPIRED,
    OrderState.FAILED,
}


def can_transition(from_state: OrderState, to_state: OrderState) -> bool:
    """Check if a transition from `from_state` to `to_state` is allowed.

    Self-transitions (e.g., CREATED -> CREATED) are allowed as idempotent
    operations, except for terminal states where we explicitly enforce
    that no further updates should happen.
    """
    if from_state == to_state:
        # Idempotent updates are allowed, except we shouldn't be updating terminal orders
        return from_state not in TERMINAL_STATES or to_state == OrderState.PARTIALLY_FILLED

    allowed_destinations = VALID_ORDER_TRANSITIONS.get(from_state, set())
    return to_state in allowed_destinations


def validate_order_transition(from_state: OrderState, to_state: OrderState) -> None:
    """Validate a transition and raise ValueError if invalid."""
    if not can_transition(from_state, to_state):
        if from_state in TERMINAL_STATES:
            raise ValueError(f"Invalid transition: {from_state.value} is a terminal state.")
        raise ValueError(f"Invalid transition from {from_state.value} to {to_state.value}.")
