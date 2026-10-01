"""Deterministic Position Sizing utility.

Converts Strategy intent into a requested quantity proposal.
Does NOT authorize cash or evaluate RiskPolicy.
"""

from decimal import Decimal

from app.schemas.paper import SizingResult


class PositionSizer:
    """Position sizing utility."""

    def calculate_size(self, signal, portfolio_equity, current_position_quantity) -> SizingResult:
        if signal.quantity is not None and signal.quantity > 0:
            return SizingResult(quantity=signal.quantity)
        return self.size_position(portfolio_equity, signal.proposed_entry_price)

    @staticmethod
    def size_position(
        portfolio_equity: Decimal,
        proposed_entry_price: Decimal | None,
        allocation_fraction: Decimal | None = None,
        risk_percent: Decimal | None = None,
        stop_loss: Decimal | None = None,
    ) -> SizingResult:
        """Calculate the requested quantity."""
        if proposed_entry_price is None or proposed_entry_price <= 0:
            return SizingResult(validation_error="Invalid or missing proposed_entry_price")

        # Explicitly supplied risk_percent
        if risk_percent is not None:
            if risk_percent <= 0 or risk_percent > 1:
                return SizingResult(validation_error="risk_percent must be > 0 and <= 1")

            if stop_loss is None or stop_loss <= 0:
                return SizingResult(
                    validation_error="stop_loss is missing or invalid for risk-based sizing"
                )

            risk_amount = portfolio_equity * risk_percent
            price_risk = abs(proposed_entry_price - stop_loss)

            if price_risk == 0:
                return SizingResult(validation_error="proposed_entry_price cannot equal stop_loss")

            quantity = risk_amount / price_risk
            return SizingResult(quantity=quantity)

        # Allocation-based sizing
        if allocation_fraction is None or allocation_fraction <= 0 or allocation_fraction > 1:
            return SizingResult(validation_error="allocation_fraction missing or invalid")

        allocation_amount = portfolio_equity * allocation_fraction
        quantity = allocation_amount / proposed_entry_price

        return SizingResult(quantity=quantity)
