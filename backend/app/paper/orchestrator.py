"""Paper Session Orchestrator.

Implements the deterministic paper-trading execution path defined in Phase K V3.8.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrderState, PaperSessionState
from app.models.paper import CashReservationModel, PaperSessionModel
from app.models.trading import (
    FillModel,
    OrderIntentModel,
    OrderModel,
    RiskDecisionModel,
)
from app.paper.adapter import PaperExecutionAdapter
from app.schemas.risk import RiskDecision


class PaperOrchestrator:
    """Orchestrates paper session lifecycle and execution transactions."""

    def __init__(self, db: AsyncSession, adapter: PaperExecutionAdapter):
        self.db = db
        self.adapter = adapter

    async def transaction_b_reserve_cash(
        self,
        session_id: uuid.UUID,
        worker_id: uuid.UUID,
        risk_decision: RiskDecision,
        portfolio_cash: Decimal,
        active_reserved_cash: Decimal,
    ) -> bool:
        """Transaction B: Atomically reserve cash and persist intent."""
        # 1. Verify worker lease (assumes caller fetched session with FOR UPDATE)
        session = await self.db.execute(
            select(PaperSessionModel)
            .where(PaperSessionModel.session_id == session_id)
            .with_for_update()
        )
        session = session.scalar_one_or_none()

        if (
            not session
            or session.worker_owner_id != worker_id
            or session.state != PaperSessionState.RUNNING
        ):
            return False

        # 2-4. Re-calculate available cash
        cash_available_for_authorization = portfolio_cash - active_reserved_cash

        # 5. Verify authorization requirement
        if risk_decision.authorized_cash_requirement is None:
            return False

        if risk_decision.authorized_cash_requirement > cash_available_for_authorization:
            # Stale context or concurrent reservation took the cash
            return False

        # 6. Atomically persist
        decision_model = RiskDecisionModel(
            decision_id=risk_decision.decision_id,
            correlation_id=risk_decision.correlation_id,
            signal_id=risk_decision.signal_id,
            status=risk_decision.status,
            trading_mode=risk_decision.trading_mode,
            calculated_quantity=risk_decision.calculated_quantity,
            calculated_risk=risk_decision.calculated_risk,
            authorized_cash_requirement=risk_decision.authorized_cash_requirement,
            risk_policy_version=risk_decision.risk_policy_version,
            timestamp=risk_decision.timestamp,
        )
        self.db.add(decision_model)

        intent_model = OrderIntentModel(
            correlation_id=risk_decision.correlation_id,
            originating_signal_id=risk_decision.signal_id,
            risk_decision_id=risk_decision.decision_id,
            account_id=session.account_id,
            symbol=session.symbol,
            side="BUY",  # Should come from Signal
            order_type="MARKET",
            quantity=risk_decision.calculated_quantity,
            time_in_force="GTC",
            idempotency_key=str(risk_decision.decision_id),
            creation_timestamp=datetime.utcnow(),
        )
        self.db.add(intent_model)
        await self.db.flush()

        reservation = CashReservationModel(
            session_id=session.session_id,
            order_intent_id=intent_model.intent_id,
            authorized_cash_requirement=risk_decision.authorized_cash_requirement,
            active=True,
        )
        self.db.add(reservation)

        order = OrderModel(
            correlation_id=risk_decision.correlation_id,
            intent_id=intent_model.intent_id,
            symbol=intent_model.symbol,
            side=intent_model.side,
            order_type=intent_model.order_type,
            quantity=intent_model.quantity,
            state=OrderState.SUBMITTED,
        )
        self.db.add(order)

        return True

    async def transaction_c_acknowledge(
        self,
        session_id: uuid.UUID,
        worker_id: uuid.UUID,
        order_id: uuid.UUID,
        actual_execution_price: Decimal,
        actual_execution_fees: Decimal,
    ) -> bool:
        """Transaction C: Cash-vs-Price Authorization Dimensionality Check."""

        session = await self.db.execute(
            select(PaperSessionModel)
            .where(PaperSessionModel.session_id == session_id)
            .with_for_update()
        )
        session = session.scalar_one_or_none()

        if not session or session.worker_owner_id != worker_id:
            return False

        order = await self.db.execute(
            select(OrderModel).where(OrderModel.order_id == order_id).with_for_update()
        )
        order = order.scalar_one_or_none()

        if not order or order.state != OrderState.SUBMITTED:
            return False

        intent = await self.db.execute(
            select(OrderIntentModel).where(OrderIntentModel.intent_id == order.intent_id)
        )
        intent = intent.scalar_one()

        reservation = await self.db.execute(
            select(CashReservationModel).where(
                CashReservationModel.order_intent_id == intent.intent_id
            )
        )
        reservation = reservation.scalar_one()

        actual_execution_cash_requirement = (
            order.quantity * actual_execution_price
        ) + actual_execution_fees

        if actual_execution_cash_requirement <= reservation.authorized_cash_requirement:
            order.state = OrderState.ACKNOWLEDGED
            order.execution_price = actual_execution_price
            return True
        else:
            order.state = OrderState.CANCELLED
            reservation.active = False
            reservation.released_timestamp = datetime.utcnow()
            return False

    async def transaction_d_fill(
        self,
        session_id: uuid.UUID,
        worker_id: uuid.UUID,
        order_id: uuid.UUID,
    ) -> bool:
        """Transaction D: Atomic Economic Commit."""
        session = await self.db.execute(
            select(PaperSessionModel)
            .where(PaperSessionModel.session_id == session_id)
            .with_for_update()
        )
        session = session.scalar_one_or_none()

        if not session or session.worker_owner_id != worker_id:
            return False

        order = await self.db.execute(
            select(OrderModel).where(OrderModel.order_id == order_id).with_for_update()
        )
        order = order.scalar_one_or_none()

        if not order or order.state != OrderState.ACKNOWLEDGED:
            return False

        intent = await self.db.execute(
            select(OrderIntentModel).where(OrderIntentModel.intent_id == order.intent_id)
        )
        intent = intent.scalar_one()

        reservation = await self.db.execute(
            select(CashReservationModel).where(
                CashReservationModel.order_intent_id == intent.intent_id
            )
        )
        reservation = reservation.scalar_one()

        if not order.execution_price:
            return False

        actual_execution_fees = Decimal("0.0")  # We should persist fees to order, simplified here

        fill = FillModel(
            correlation_id=order.correlation_id,
            order_id=order.order_id,
            timestamp=datetime.utcnow(),
            price=order.execution_price,
            quantity=order.quantity,
            fee=actual_execution_fees,
            slippage=Decimal("0.0"),
        )
        self.db.add(fill)

        order.state = OrderState.FILLED
        order.filled_quantity = order.quantity
        order.average_fill_price = order.execution_price

        reservation.active = False
        reservation.released_timestamp = datetime.utcnow()

        return True
