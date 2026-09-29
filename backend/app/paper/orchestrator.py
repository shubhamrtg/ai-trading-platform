"""Paper Trading Orchestrator.

Implements the deterministic paper-trading execution path defined in Phase K V3.8.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.transitions import validate_order_transition
from app.models.enums import OrderState, PaperSessionState, PositionState
from app.models.paper import CashReservationModel, PaperSessionModel
from app.models.portfolio import PortfolioSnapshotModel, PositionModel
from app.models.trading import (
    FillModel,
    OrderIntentModel,
    OrderModel,
    RiskDecisionModel,
)
from app.paper.adapter import PaperExecutionAdapter
from app.schemas.risk import RiskDecision
from app.schemas.signal import Signal


class PaperOrchestrator:
    """Orchestrates paper session lifecycle and execution transactions."""

    def __init__(self, db: AsyncSession, adapter: PaperExecutionAdapter):
        self.db = db
        self.adapter = adapter

    def _now(self) -> datetime:
        """Return current UTC timezone-aware datetime."""
        return datetime.now(UTC)

    async def check_lease(self, session: PaperSessionModel, worker_id: uuid.UUID) -> bool:
        """Verify the worker holds a valid lease."""
        if session.worker_owner_id != worker_id:
            return False
        if not session.worker_heartbeat:
            return False

        heartbeat = session.worker_heartbeat
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=UTC)
        # Suppose a 30s lease timeout for this architecture validation
        if (self._now() - heartbeat).total_seconds() > 30:
            return False

        return True

    async def transaction_b_reserve_cash(
        self,
        session_id: uuid.UUID,
        worker_id: uuid.UUID,
        signal: Signal,
        risk_decision: RiskDecision,
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
            or not await self.check_lease(session, worker_id)
            or session.state != PaperSessionState.RUNNING
        ):
            return False

        # 2. Fetch authoritative portfolio cash
        portfolio_snapshot = await self.db.execute(
            select(PortfolioSnapshotModel)
            .where(PortfolioSnapshotModel.account_id == session.account_id)
            .order_by(PortfolioSnapshotModel.timestamp.desc())
            .limit(1)
        )
        portfolio_snapshot = portfolio_snapshot.scalar_one_or_none()
        portfolio_cash = portfolio_snapshot.cash if portfolio_snapshot else Decimal("0.0")

        # 3. Sum authoritative active reservations for this account
        # First we need all session_ids for this account to find their active reservations
        account_sessions = await self.db.execute(
            select(PaperSessionModel.session_id)
            .where(PaperSessionModel.account_id == session.account_id)
        )
        account_session_ids = [row[0] for row in account_sessions.all()]

        active_reserved_cash = Decimal("0.0")
        if account_session_ids:
            sum_res = await self.db.execute(
                select(func.sum(CashReservationModel.authorized_cash_requirement))
                .where(CashReservationModel.session_id.in_(account_session_ids))
                .where(CashReservationModel.active == True)
            )
            val = sum_res.scalar()
            if val is not None:
                active_reserved_cash = Decimal(val)

        # 4. Re-calculate available cash
        cash_available_for_authorization = portfolio_cash - active_reserved_cash

        # 5. Verify authorization requirement
        if risk_decision.authorized_cash_requirement is None:
            return False

        if risk_decision.authorized_cash_requirement > cash_available_for_authorization:
            # Insufficient cash
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
        await self.db.flush()

        # Ensure order semantics come from the originating Signal
        intent_id = uuid.uuid4()
        intent_model = OrderIntentModel(
            intent_id=intent_id,
            correlation_id=risk_decision.correlation_id,
            originating_signal_id=risk_decision.signal_id,
            risk_decision_id=risk_decision.decision_id,
            account_id=session.account_id,
            symbol=signal.symbol,
            side=signal.side.value if hasattr(signal.side, 'value') else signal.side,
            order_type=signal.order_type.value if hasattr(signal.order_type, 'value') else signal.order_type,
            quantity=risk_decision.calculated_quantity,
            time_in_force="GTC",
            idempotency_key=str(risk_decision.decision_id),
            creation_timestamp=self._now(),
        )
        self.db.add(intent_model)
        await self.db.flush()

        reservation = CashReservationModel(
            reservation_id=uuid.uuid4(),
            session_id=session.session_id,
            order_intent_id=intent_model.intent_id,
            authorized_cash_requirement=risk_decision.authorized_cash_requirement,
            active=True,
            creation_timestamp=self._now(),
        )
        self.db.add(reservation)

        order = OrderModel(
            order_id=uuid.uuid4(),
            correlation_id=risk_decision.correlation_id,
            intent_id=intent_model.intent_id,
            symbol=intent_model.symbol,
            side=intent_model.side.value if hasattr(intent_model.side, 'value') else intent_model.side,
            order_type=intent_model.order_type.value if hasattr(intent_model.order_type, 'value') else intent_model.order_type,
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

        if not session or not await self.check_lease(session, worker_id):
            return False

        order = await self.db.execute(
            select(OrderModel).where(OrderModel.order_id == order_id).with_for_update()
        )
        order = order.scalar_one_or_none()

        # Kill switch / cancellation race check!
        # If it has already moved to CANCEL_PENDING or CANCELLED, do not acknowledge.
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
            validate_order_transition(order.state, OrderState.ACKNOWLEDGED)
            order.state = OrderState.ACKNOWLEDGED
            order.execution_price = actual_execution_price
            order.execution_fee = actual_execution_fees
            return True
        else:
            validate_order_transition(order.state, OrderState.CANCEL_PENDING)
            order.state = OrderState.CANCEL_PENDING
            await self.db.flush()

            validate_order_transition(order.state, OrderState.CANCELLED)
            order.state = OrderState.CANCELLED
            reservation.active = False
            reservation.released_timestamp = self._now()
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

        if not session or not await self.check_lease(session, worker_id):
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

        if not order.execution_price or order.execution_fee is None:
            return False

        actual_execution_fees = order.execution_fee

        fill = FillModel(
            fill_id=uuid.uuid4(),
            correlation_id=order.correlation_id,
            order_id=order.order_id,
            timestamp=self._now(),
            price=order.execution_price,
            quantity=order.quantity,
            fee=actual_execution_fees,
            slippage=Decimal("0.0"),
        )
        self.db.add(fill)

        # Economic Commit: Portfolio Cash Deduction and Position Update
        portfolio_snapshot = await self.db.execute(
            select(PortfolioSnapshotModel)
            .where(PortfolioSnapshotModel.account_id == session.account_id)
            .order_by(PortfolioSnapshotModel.timestamp.desc())
            .limit(1)
        )
        portfolio = portfolio_snapshot.scalar_one_or_none()

        if not portfolio:
            # Should not happen in a valid system since Tx B ensures cash exists
            return False

        position = await self.db.execute(
            select(PositionModel)
            .where(PositionModel.account_id == session.account_id)
            .where(PositionModel.symbol == order.symbol)
        )
        position = position.scalar_one_or_none()

        actual_cash_spent = (order.quantity * order.execution_price) + actual_execution_fees

        if not position:
            position = PositionModel(
                position_id=uuid.uuid4(),
                account_id=session.account_id,
                symbol=order.symbol,
                state=PositionState.OPEN,
                side=order.side.value if hasattr(order.side, 'value') else order.side,
                quantity=order.quantity,
                average_entry_price=order.execution_price,
                strategy_id=session.strategy_id,
                entry_signal_id=intent.originating_signal_id
            )
            self.db.add(position)
        else:
            old_notional = position.quantity * position.average_entry_price
            new_notional = order.quantity * order.execution_price
            position.quantity += order.quantity
            if position.quantity > 0:
                position.average_entry_price = (old_notional + new_notional) / position.quantity

        # Create new portfolio snapshot reflecting the economic commit
        new_portfolio = PortfolioSnapshotModel(
            snapshot_id=uuid.uuid4(),
            account_id=portfolio.account_id,
            timestamp=self._now(),
            cash=portfolio.cash - actual_cash_spent,
            available_cash=portfolio.cash - actual_cash_spent,  # Base available cash, gets modified by reservations elsewhere
            equity=portfolio.equity - actual_execution_fees,  # Equity only drops by fee on entry
            total_realized_pnl=portfolio.total_realized_pnl,
            total_unrealized_pnl=portfolio.total_unrealized_pnl,
            total_exposure=portfolio.total_exposure + (order.quantity * order.execution_price),
            reserved_capital=Decimal("0.0") # We don't maintain aggregate reserved_capital here, we compute it on the fly
        )
        self.db.add(new_portfolio)

        validate_order_transition(order.state, OrderState.FILLED)
        order.state = OrderState.FILLED
        order.filled_quantity = order.quantity
        order.average_fill_price = order.execution_price

        reservation.active = False
        reservation.released_timestamp = self._now()

        return True

    async def run_pipeline_for_candle(self, session_id: uuid.UUID, worker_id: uuid.UUID, candle) -> None:
        """Helper to demonstrate full flow if needed. Real system orchestrates this externally via tasks."""
        pass
