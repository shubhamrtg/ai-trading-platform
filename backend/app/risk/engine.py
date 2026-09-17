"""Deterministic Risk Engine for Phase G.

The Risk Engine evaluates a proposed Signal against a RiskPolicy and RiskContext.
It has final authority on whether a trade is permitted.
It is deterministic, stateless, and side-effect free.
"""

from datetime import UTC, datetime
from uuid import uuid4

from app.models.enums import OrderSide, RiskDecisionStatus, RiskRejectionCode
from app.schemas.risk import RiskContext, RiskDecision, RiskPolicy
from app.schemas.signal import Signal


class RiskEngine:
    """Core deterministic risk evaluation engine."""

    def evaluate(self, signal: Signal, context: RiskContext, policy: RiskPolicy) -> RiskDecision:
        """Evaluate a signal against the policy and context."""
        rejection_codes: list[RiskRejectionCode] = []
        rejection_reasons: list[str] = []

        # 1. HARD GATE: Global Trading Halt
        if context.trading_halted:
            rejection_codes.append(RiskRejectionCode.TRADING_HALTED)
            rejection_reasons.append("Trading is globally halted via RiskContext.")
        if policy.trading_halted:
            rejection_codes.append(RiskRejectionCode.TRADING_HALTED)
            rejection_reasons.append("Trading is globally halted via RiskPolicy.")

        # 2. SIGNAL VALIDATION (Context-independent basic logic, besides pydantic rules)
        if signal.quantity <= 0:
            rejection_codes.append(RiskRejectionCode.INVALID_SIGNAL)
            rejection_reasons.append("Signal quantity must be positive.")

        # 3. MAX ORDER QUANTITY
        if signal.quantity > policy.max_order_quantity:
            rejection_codes.append(RiskRejectionCode.MAX_ORDER_QUANTITY_EXCEEDED)
            rejection_reasons.append(
                f"Proposed quantity {signal.quantity} exceeds max_order_quantity {policy.max_order_quantity}"
            )

        # 4. MAX POSITION QUANTITY
        # For a BUY, resulting_position = current_position + quantity
        # For a SELL, resulting_position = current_position - quantity
        # If long-only semantics apply (as per standard platform rules unless overridden),
        # selling more than held is invalid.
        if signal.side == OrderSide.BUY:
            resulting_position = context.current_position + signal.quantity
        else:
            resulting_position = context.current_position - signal.quantity
            if resulting_position < 0:
                rejection_codes.append(RiskRejectionCode.UNSUPPORTED_ORDER_SEMANTICS)
                rejection_reasons.append(
                    f"Short selling is not supported. Attempting to sell {signal.quantity} with only {context.current_position} held."
                )

        if resulting_position > policy.max_position_quantity:
            rejection_codes.append(RiskRejectionCode.MAX_POSITION_EXCEEDED)
            rejection_reasons.append(
                f"Resulting position {resulting_position} exceeds max_position_quantity {policy.max_position_quantity}"
            )

        # 5. EXPOSURE LIMIT
        # Exposure requires a reference price. Use proposed_entry_price.
        if signal.proposed_entry_price is None:
            rejection_codes.append(RiskRejectionCode.INSUFFICIENT_INFORMATION)
            rejection_reasons.append("Cannot calculate exposure without a proposed_entry_price.")
        else:
            proposed_exposure = signal.quantity * signal.proposed_entry_price
            if proposed_exposure > policy.max_exposure_amount:
                rejection_codes.append(RiskRejectionCode.MAX_EXPOSURE_EXCEEDED)
                rejection_reasons.append(
                    f"Proposed exposure {proposed_exposure} exceeds absolute max_exposure_amount {policy.max_exposure_amount}"
                )

            exposure_percent = proposed_exposure / context.portfolio_equity
            if exposure_percent > policy.max_exposure_percent:
                rejection_codes.append(RiskRejectionCode.MAX_EXPOSURE_EXCEEDED)
                rejection_reasons.append(
                    f"Proposed exposure percent {exposure_percent:.4f} exceeds max_exposure_percent {policy.max_exposure_percent}"
                )

        # 6. MAX RISK PER TRADE (Stop Loss based risk)
        # trade_risk = abs(entry - stop) * quantity
        if signal.stop_loss is not None and signal.proposed_entry_price is None:
            rejection_codes.append(RiskRejectionCode.INSUFFICIENT_INFORMATION)
            rejection_reasons.append(
                "Stop loss is provided but proposed_entry_price is missing, cannot calculate risk."
            )
        elif signal.stop_loss is not None and signal.proposed_entry_price is not None:
            trade_risk = abs(signal.proposed_entry_price - signal.stop_loss) * signal.quantity
            if trade_risk > policy.max_risk_per_trade:
                rejection_codes.append(RiskRejectionCode.MAX_RISK_PER_TRADE_EXCEEDED)
                rejection_reasons.append(
                    f"Calculated trade risk {trade_risk} exceeds max_risk_per_trade {policy.max_risk_per_trade}"
                )
        else:
            # If the active policy REQUIRES a stop loss to be present, but it's not.
            # "If stop information is required by the active policy but missing: reject"
            # Since policy.max_risk_per_trade is always defined (ge=0), if it's strictly > 0 we could require a stop.
            # But the prompt says "If stop information is required by the active policy".
            # For this simple phase, we'll assume a non-zero max_risk_per_trade requires a stop loss.
            # Let's check this assumption: if the policy restricts trade risk, we MUST know the trade risk.
            if policy.max_risk_per_trade > 0:
                rejection_codes.append(RiskRejectionCode.INSUFFICIENT_INFORMATION)
                rejection_reasons.append(
                    "Policy enforces max_risk_per_trade, but stop_loss or proposed_entry_price is missing."
                )

        # 7. DAILY LOSS LIMIT
        # daily_pnl < 0 means a loss. If abs(daily_pnl) >= max_daily_loss, REJECT
        if context.daily_pnl < 0 and abs(context.daily_pnl) >= policy.max_daily_loss:
            rejection_codes.append(RiskRejectionCode.DAILY_LOSS_LIMIT_BREACHED)
            rejection_reasons.append(
                f"Current daily loss {abs(context.daily_pnl)} reaches or exceeds max_daily_loss {policy.max_daily_loss}"
            )

        # 8. DRAWDOWN LIMIT
        # drawdown = (peak_equity - current_equity) / peak_equity
        if context.peak_equity <= 0:
            rejection_codes.append(RiskRejectionCode.INVALID_RISK_CONTEXT)
            rejection_reasons.append("Peak equity must be greater than zero.")
        else:
            drawdown = (context.peak_equity - context.current_equity) / context.peak_equity
            if drawdown > policy.max_drawdown_percent:
                rejection_codes.append(RiskRejectionCode.MAX_DRAWDOWN_EXCEEDED)
                rejection_reasons.append(
                    f"Current drawdown {drawdown:.4f} exceeds max_drawdown_percent {policy.max_drawdown_percent}"
                )

        if rejection_codes:
            return RiskDecision(
                decision_id=uuid4(),
                correlation_id=signal.correlation_id,
                signal_id=signal.signal_id,
                status=RiskDecisionStatus.REJECTED,
                rejection_codes=rejection_codes,
                rejection_reasons=rejection_reasons,
                timestamp=datetime.now(UTC),
            )

        # Approved!
        return RiskDecision(
            decision_id=uuid4(),
            correlation_id=signal.correlation_id,
            signal_id=signal.signal_id,
            status=RiskDecisionStatus.APPROVED,
            calculated_quantity=signal.quantity,
            # For calculated_risk, we can record the trade_risk if calculated
            calculated_risk=(abs(signal.proposed_entry_price - signal.stop_loss) * signal.quantity)
            if signal.proposed_entry_price and signal.stop_loss
            else None,
            timestamp=datetime.now(UTC),
        )
