"""Deterministic Risk Engine for Phase G.

The Risk Engine evaluates a proposed Signal against a RiskPolicy and RiskContext.
It has final authority on whether a trade is permitted.
It is deterministic, stateless, and side-effect free.
"""

import uuid
from decimal import Decimal
from functools import wraps
from typing import Any

from app.models.enums import OrderSide, RiskDecisionStatus, RiskRejectionCode
from app.schemas.risk import RiskContext, RiskDecision, RiskPolicy
from app.schemas.signal import Signal


class RiskEngine:
    """Core deterministic risk evaluation engine."""

    def _generate_decision_id(
        self, signal: Signal, context: RiskContext, policy: RiskPolicy
    ) -> uuid.UUID:
        """Generate a deterministic UUID representing the exact evaluation state."""
        import json

        state = {
            "signal": {
                "signal_id": str(signal.signal_id),
                "correlation_id": str(signal.correlation_id),
                "side": signal.side.value,
                "quantity": str(signal.quantity),
                "proposed_entry_price": str(signal.proposed_entry_price)
                if signal.proposed_entry_price is not None
                else None,
                "stop_loss": str(signal.stop_loss) if signal.stop_loss is not None else None,
                "strategy_id": str(signal.strategy_id) if signal.strategy_id is not None else None,
                "strategy_version": str(signal.strategy_version)
                if signal.strategy_version is not None
                else None,
            },
            "context": {
                "portfolio_equity": str(context.portfolio_equity),
                "current_position": str(context.current_position),
                "current_exposure": str(context.current_exposure),
                "daily_pnl": str(context.daily_pnl),
                "peak_equity": str(context.peak_equity),
                "current_equity": str(context.current_equity),
                "trading_mode": context.trading_mode.value,
                "trading_halted": context.trading_halted,
                "evaluated_at": context.evaluated_at.isoformat(),
            },
            "policy": {
                "version": policy.version,
                "max_order_quantity": str(policy.max_order_quantity),
                "max_position_quantity": str(policy.max_position_quantity),
                "max_exposure_amount": str(policy.max_exposure_amount),
                "max_exposure_percent": str(policy.max_exposure_percent),
                "max_risk_per_trade": str(policy.max_risk_per_trade),
                "max_daily_loss": str(policy.max_daily_loss),
                "max_drawdown_percent": str(policy.max_drawdown_percent),
                "trading_halted": policy.trading_halted,
            },
        }

        canonical_string = json.dumps(state, sort_keys=True, separators=(",", ":"))
        return uuid.uuid5(uuid.NAMESPACE_OID, canonical_string)

    def evaluate(self, signal: Signal, context: RiskContext, policy: RiskPolicy) -> RiskDecision:
        """Evaluate a signal against the policy and context."""
        rejection_codes: list[RiskRejectionCode] = []
        rejection_reasons: list[str] = []

        # 1. HARD GATE: Global Trading Halt
        # Prevent duplicate TRADING_HALTED codes
        if context.trading_halted or policy.trading_halted:
            rejection_codes.append(RiskRejectionCode.TRADING_HALTED)
            sources = []
            if context.trading_halted:
                sources.append("RiskContext")
            if policy.trading_halted:
                sources.append("RiskPolicy")
            rejection_reasons.append(f"Trading is globally halted via {' and '.join(sources)}.")

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
            if signal.side == OrderSide.BUY or (
                signal.side == OrderSide.SELL and context.current_exposure > 0
            ):
                # We need to evaluate exposure limits, but price is missing
                rejection_codes.append(RiskRejectionCode.INSUFFICIENT_INFORMATION)
                rejection_reasons.append(
                    "Cannot calculate exposure without a proposed_entry_price."
                )
        else:
            order_notional = signal.quantity * signal.proposed_entry_price

            if signal.side == OrderSide.BUY:
                resulting_exposure = context.current_exposure + order_notional
            else:
                resulting_exposure = max(Decimal("0.0"), context.current_exposure - order_notional)

            if resulting_exposure > policy.max_exposure_amount:
                rejection_codes.append(RiskRejectionCode.MAX_EXPOSURE_EXCEEDED)
                rejection_reasons.append(
                    f"Resulting exposure {resulting_exposure} exceeds absolute max_exposure_amount {policy.max_exposure_amount}"
                )

            exposure_percent = resulting_exposure / context.portfolio_equity
            if exposure_percent > policy.max_exposure_percent:
                rejection_codes.append(RiskRejectionCode.MAX_EXPOSURE_EXCEEDED)
                rejection_reasons.append(
                    f"Resulting exposure percent {exposure_percent:.4f} exceeds max_exposure_percent {policy.max_exposure_percent}"
                )

        # 6. MAX RISK PER TRADE (Stop Loss based risk)
        if policy.max_risk_per_trade > 0:
            if signal.stop_loss is None or signal.proposed_entry_price is None:
                rejection_codes.append(RiskRejectionCode.INSUFFICIENT_INFORMATION)
                rejection_reasons.append(
                    "Policy enforces max_risk_per_trade, but stop_loss or proposed_entry_price is missing."
                )
            else:
                trade_risk = abs(signal.proposed_entry_price - signal.stop_loss) * signal.quantity
                if trade_risk > policy.max_risk_per_trade:
                    rejection_codes.append(RiskRejectionCode.MAX_RISK_PER_TRADE_EXCEEDED)
                    rejection_reasons.append(
                        f"Calculated trade risk {trade_risk} exceeds max_risk_per_trade {policy.max_risk_per_trade}"
                    )

        # 7. DAILY LOSS LIMIT
        # If daily_pnl is negative and reaches or exceeds max_daily_loss
        if context.daily_pnl < 0 and abs(context.daily_pnl) >= policy.max_daily_loss:
            rejection_codes.append(RiskRejectionCode.DAILY_LOSS_LIMIT_BREACHED)
            rejection_reasons.append(
                f"Current daily loss {abs(context.daily_pnl)} reaches or exceeds max_daily_loss {policy.max_daily_loss}"
            )

        # 8. DRAWDOWN LIMIT
        if context.peak_equity <= 0:
            rejection_codes.append(RiskRejectionCode.INVALID_RISK_CONTEXT)
            rejection_reasons.append("Peak equity must be greater than zero.")
        else:
            drawdown = (context.peak_equity - context.current_equity) / context.peak_equity
            if drawdown >= policy.max_drawdown_percent:
                rejection_codes.append(RiskRejectionCode.MAX_DRAWDOWN_EXCEEDED)
                rejection_reasons.append(
                    f"Current drawdown {drawdown:.4f} reaches or exceeds max_drawdown_percent {policy.max_drawdown_percent}"
                )

        # Deterministic Decision ID Generation
        # Use UUID5 based on stable inputs
        deterministic_id = self._generate_decision_id(signal, context, policy)

        if rejection_codes:
            return RiskDecision(
                decision_id=deterministic_id,
                correlation_id=signal.correlation_id,
                signal_id=signal.signal_id,
                status=RiskDecisionStatus.REJECTED,
                risk_policy_version=policy.version,
                trading_mode=context.trading_mode,
                rejection_codes=rejection_codes,
                rejection_reasons=rejection_reasons,
                calculated_quantity=None,
                calculated_risk=None,
                risk_limit_applied=None,
                timestamp=context.evaluated_at,
            )

        # Approved!
        calculated_risk = None
        if signal.proposed_entry_price is not None and signal.stop_loss is not None:
            calculated_risk = abs(signal.proposed_entry_price - signal.stop_loss) * signal.quantity

        decision = RiskDecision(
            decision_id=deterministic_id,
            correlation_id=signal.correlation_id,
            signal_id=signal.signal_id,
            status=RiskDecisionStatus.APPROVED,
            risk_policy_version=policy.version,
            trading_mode=context.trading_mode,
            calculated_quantity=signal.quantity,
            calculated_risk=calculated_risk,
            risk_limit_applied=None,
            timestamp=context.evaluated_at,
        )

        from app.risk.capability import ApprovedRiskCapability
        from app.schemas.order import OrderIntent

        # Lock the approved state into the local closure scope
        approved_decision_id = decision.decision_id
        approved_quantity = decision.calculated_quantity
        approved_policy_version = decision.risk_policy_version
        approved_trading_mode = decision.trading_mode
        approved_correlation_id = decision.correlation_id

        class _RiskEngineIssuedCapability(ApprovedRiskCapability):
            def validate_intent(self, intent: OrderIntent) -> None:
                if intent.risk_decision_id != approved_decision_id:
                    raise ValueError("Execution authority provenance mismatch: decision_id")
                if intent.quantity != approved_quantity:
                    raise ValueError("Execution authority provenance mismatch: quantity")
                if intent.risk_policy_version != approved_policy_version:
                    raise ValueError("Execution authority provenance mismatch: policy_version")
                if intent.trading_mode != approved_trading_mode:
                    raise ValueError("Execution authority provenance mismatch: trading_mode")
                if intent.correlation_id != approved_correlation_id:
                    raise ValueError("Execution authority provenance mismatch: correlation_id")

        decision._execution_capability = _RiskEngineIssuedCapability()
        return decision
