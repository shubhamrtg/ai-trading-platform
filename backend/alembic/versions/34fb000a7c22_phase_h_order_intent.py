"""phase_h_order_intent

Revision ID: 34fb000a7c22
Revises: d57668702d42
Create Date: 2026-09-18 11:21:44.403732
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '34fb000a7c22'
down_revision: Union[str, None] = 'd57668702d42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add columns as nullable first
    op.add_column('risk_decisions', sa.Column('trading_mode', sa.String(), nullable=True))
    op.add_column('signals', sa.Column('order_type', sa.String(), nullable=True))
    
    # 2. Backfill Data
    bind = op.get_bind()
    
    # Backfill signals.order_type from order_intents.order_type where a matching risk_decision exists.
    # This safely replicates the historical data without inventing anything.
    bind.execute(
        sa.text(
            """
            UPDATE signals 
            SET order_type = (
                SELECT order_intents.order_type 
                FROM order_intents 
                JOIN risk_decisions ON risk_decisions.decision_id = order_intents.risk_decision_id 
                WHERE risk_decisions.signal_id = signals.signal_id
                LIMIT 1
            )
            WHERE order_type IS NULL
            AND EXISTS (
                SELECT 1 
                FROM order_intents 
                JOIN risk_decisions ON risk_decisions.decision_id = order_intents.risk_decision_id 
                WHERE risk_decisions.signal_id = signals.signal_id
            )
            """
        )
    )

    # 3. We cannot safely enforce NOT NULL constraint for trading_mode or remaining order_types 
    # without inventing data, which is explicitly forbidden.
    # We leave the columns nullable=True in DB to preserve historical records safely.


def downgrade() -> None:
    op.drop_column('signals', 'order_type')
    op.drop_column('risk_decisions', 'trading_mode')
