"""phase_h_order_intent

Revision ID: 34fb000a7c22
Revises: d57668702d42
Create Date: 2026-09-18 11:21:44.403732
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '34fb000a7c22'
down_revision: str | None = 'd57668702d42'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add columns as nullable first
    op.add_column('risk_decisions', sa.Column('trading_mode', sa.String(), nullable=True))
    op.add_column('risk_decisions', sa.Column('risk_policy_version', sa.String(), nullable=True))
    op.add_column('signals', sa.Column('order_type', sa.String(), nullable=True))
    op.add_column('signals', sa.Column('quantity', sa.Numeric(24, 8), nullable=True))

    # 2. Backfill Data
    bind = op.get_bind()

    # Backfill signals.order_type from order_intents.order_type where a matching risk_decision exists.
    # This safely replicates the historical data without inventing anything.
    bind.execute(
        sa.text(
            """
            UPDATE signals 
            SET order_type = (
                SELECT MIN(order_intents.order_type)
                FROM order_intents 
                JOIN risk_decisions ON risk_decisions.decision_id = order_intents.risk_decision_id 
                WHERE risk_decisions.signal_id = signals.signal_id
                GROUP BY risk_decisions.signal_id
                HAVING COUNT(DISTINCT order_intents.order_type) = 1
            )
            WHERE order_type IS NULL
            AND EXISTS (
                SELECT 1 
                FROM order_intents 
                JOIN risk_decisions ON risk_decisions.decision_id = order_intents.risk_decision_id 
                WHERE risk_decisions.signal_id = signals.signal_id
                GROUP BY risk_decisions.signal_id
                HAVING COUNT(DISTINCT order_intents.order_type) = 1
            )
            """
        )
    )

    # Backfill signals.quantity from order_intents.quantity where a matching risk_decision exists.
    # We only backfill if the quantity is completely unambiguous and authoritative.
    bind.execute(
        sa.text(
            """
            UPDATE signals 
            SET quantity = (
                SELECT MIN(order_intents.quantity)
                FROM order_intents 
                JOIN risk_decisions ON risk_decisions.decision_id = order_intents.risk_decision_id 
                WHERE risk_decisions.signal_id = signals.signal_id
                GROUP BY risk_decisions.signal_id
                HAVING COUNT(DISTINCT order_intents.quantity) = 1
                   AND COUNT(order_intents.quantity) = COUNT(*)
            )
            WHERE quantity IS NULL
            AND EXISTS (
                SELECT 1 
                FROM order_intents 
                JOIN risk_decisions ON risk_decisions.decision_id = order_intents.risk_decision_id 
                WHERE risk_decisions.signal_id = signals.signal_id
                GROUP BY risk_decisions.signal_id
                HAVING COUNT(DISTINCT order_intents.quantity) = 1
                   AND COUNT(order_intents.quantity) = COUNT(*)
            )
            """
        )
    )

    # 3. We cannot safely enforce NOT NULL constraint for trading_mode or remaining order_types
    # without inventing data, which is explicitly forbidden.
    # We leave the columns nullable=True in DB to preserve historical records safely.


def downgrade() -> None:
    op.drop_column('signals', 'quantity')
    op.drop_column('signals', 'order_type')
    op.drop_column('risk_decisions', 'risk_policy_version')
    op.drop_column('risk_decisions', 'trading_mode')
