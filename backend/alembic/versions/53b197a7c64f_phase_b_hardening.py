"""phase_b_hardening

Revision ID: 53b197a7c64f
Revises: cd52aeed004f
Create Date: 2026-09-13 12:36:12.662208
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "53b197a7c64f"
down_revision: str | None = "cd52aeed004f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add new columns as nullable first
    op.add_column("ai_assessments", sa.Column("correlation_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_ai_assessments_correlation_id"), "ai_assessments", ["correlation_id"], unique=False
    )

    op.add_column("audit_events", sa.Column("risk_decision_id", sa.Uuid(), nullable=True))
    op.add_column("audit_events", sa.Column("order_intent_id", sa.Uuid(), nullable=True))

    op.add_column("fills", sa.Column("correlation_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_fills_correlation_id"), "fills", ["correlation_id"], unique=False)

    op.add_column("order_intents", sa.Column("correlation_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_order_intents_correlation_id"), "order_intents", ["correlation_id"], unique=False
    )

    op.add_column("orders", sa.Column("correlation_id", sa.Uuid(), nullable=True))
    op.add_column("orders", sa.Column("symbol", sa.String(), nullable=True))
    op.add_column("orders", sa.Column("side", sa.String(), nullable=True))
    op.add_column("orders", sa.Column("order_type", sa.String(), nullable=True))
    op.add_column("orders", sa.Column("quantity", sa.Numeric(precision=24, scale=8), nullable=True))
    op.add_column("orders", sa.Column("rejection_reason", sa.String(), nullable=True))

    op.create_index(op.f("ix_orders_correlation_id"), "orders", ["correlation_id"], unique=False)
    op.create_index(op.f("ix_orders_state"), "orders", ["state"], unique=False)
    op.create_index(op.f("ix_orders_symbol"), "orders", ["symbol"], unique=False)

    op.add_column("risk_decisions", sa.Column("correlation_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_risk_decisions_correlation_id"), "risk_decisions", ["correlation_id"], unique=False
    )

    op.add_column("signals", sa.Column("correlation_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_signals_correlation_id"), "signals", ["correlation_id"], unique=False)

    op.add_column("strategies", sa.Column("status", sa.String(), nullable=True))

    op.add_column("strategy_versions", sa.Column("status", sa.String(), nullable=True))
    op.add_column("strategy_versions", sa.Column("source_hash", sa.String(), nullable=True))

    with op.batch_alter_table("strategy_versions") as batch_op:
        batch_op.create_unique_constraint("uq_strategy_version", ["strategy_id", "version"])

    # 2. Backfill Data
    bind = op.get_bind()

    # Generate UUIDs for correlation_id where it's NULL.
    # Note: Using python's uuid4 directly ensures dialect independence.
    for table in [
        "signals",
        "risk_decisions",
        "order_intents",
        "orders",
        "fills",
        "ai_assessments",
    ]:
        rows = bind.execute(
            sa.text(f"SELECT id FROM {table} WHERE correlation_id IS NULL")
        ).fetchall()
        for row in rows:
            bind.execute(
                sa.text(f"UPDATE {table} SET correlation_id = :uuid WHERE id = :id"),
                {"uuid": uuid.uuid4().hex, "id": row[0]},
            )

    # Backfill missing order fields independently by joining with order_intents.
    # This safely replicates the denormalized data without inventing anything.
    bind.execute(sa.text("UPDATE orders SET symbol = (SELECT symbol FROM order_intents WHERE order_intents.intent_id = orders.intent_id) WHERE symbol IS NULL"))
    bind.execute(sa.text("UPDATE orders SET side = (SELECT side FROM order_intents WHERE order_intents.intent_id = orders.intent_id) WHERE side IS NULL"))
    bind.execute(sa.text("UPDATE orders SET order_type = (SELECT order_type FROM order_intents WHERE order_intents.intent_id = orders.intent_id) WHERE order_type IS NULL"))
    bind.execute(sa.text("UPDATE orders SET quantity = (SELECT quantity FROM order_intents WHERE order_intents.intent_id = orders.intent_id) WHERE quantity IS NULL"))

    # Backfill strategy status with reasonable defaults
    bind.execute(sa.text("UPDATE strategies SET status = 'DRAFT' WHERE status IS NULL"))
    bind.execute(sa.text("UPDATE strategy_versions SET status = 'DRAFT' WHERE status IS NULL"))

    # Explicit NULL verification before enforcing NOT NULL constraints
    for table, col in [
        ("ai_assessments", "correlation_id"),
        ("fills", "correlation_id"),
        ("order_intents", "correlation_id"),
        ("orders", "correlation_id"),
        ("orders", "symbol"),
        ("orders", "side"),
        ("orders", "order_type"),
        ("orders", "quantity"),
        ("risk_decisions", "correlation_id"),
        ("signals", "correlation_id"),
        ("strategies", "status"),
        ("strategy_versions", "status")
    ]:
        result = bind.execute(sa.text(f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL")).scalar()
        if result and result > 0:
            raise RuntimeError(
                f"Migration Failed: Cannot safely apply NOT NULL constraint to {table}.{col}. "
                f"Found {result} unmappable records with NULL values after backfilling."
            )

    # 3. Alter columns to NOT NULL safely using batch_alter_table
    with op.batch_alter_table("ai_assessments") as batch_op:
        batch_op.alter_column("correlation_id", nullable=False)

    with op.batch_alter_table("fills") as batch_op:
        batch_op.alter_column("correlation_id", nullable=False)

    with op.batch_alter_table("order_intents") as batch_op:
        batch_op.alter_column("correlation_id", nullable=False)

    with op.batch_alter_table("orders") as batch_op:
        batch_op.alter_column("correlation_id", nullable=False)
        batch_op.alter_column("symbol", nullable=False)
        batch_op.alter_column("side", nullable=False)
        batch_op.alter_column("order_type", nullable=False)
        batch_op.alter_column("quantity", nullable=False)

    with op.batch_alter_table("risk_decisions") as batch_op:
        batch_op.alter_column("correlation_id", nullable=False)

    with op.batch_alter_table("signals") as batch_op:
        batch_op.alter_column("correlation_id", nullable=False)

    with op.batch_alter_table("strategies") as batch_op:
        batch_op.alter_column("status", nullable=False)

    with op.batch_alter_table("strategy_versions") as batch_op:
        batch_op.alter_column("status", nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("strategy_versions") as batch_op:
        batch_op.drop_constraint("uq_strategy_version", type_="unique")
        batch_op.drop_column("source_hash")
        batch_op.drop_column("status")

    with op.batch_alter_table("strategies") as batch_op:
        batch_op.drop_column("status")

    with op.batch_alter_table("signals") as batch_op:
        batch_op.drop_index(op.f("ix_signals_correlation_id"))
        batch_op.drop_column("correlation_id")

    with op.batch_alter_table("risk_decisions") as batch_op:
        batch_op.drop_index(op.f("ix_risk_decisions_correlation_id"))
        batch_op.drop_column("correlation_id")

    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_index(op.f("ix_orders_symbol"))
        batch_op.drop_index(op.f("ix_orders_state"))
        batch_op.drop_index(op.f("ix_orders_correlation_id"))
        batch_op.drop_column("rejection_reason")
        batch_op.drop_column("quantity")
        batch_op.drop_column("order_type")
        batch_op.drop_column("side")
        batch_op.drop_column("symbol")
        batch_op.drop_column("correlation_id")

    with op.batch_alter_table("order_intents") as batch_op:
        batch_op.drop_index(op.f("ix_order_intents_correlation_id"))
        batch_op.drop_column("correlation_id")

    with op.batch_alter_table("fills") as batch_op:
        batch_op.drop_index(op.f("ix_fills_correlation_id"))
        batch_op.drop_column("correlation_id")

    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.drop_column("order_intent_id")
        batch_op.drop_column("risk_decision_id")

    with op.batch_alter_table("ai_assessments") as batch_op:
        batch_op.drop_index(op.f("ix_ai_assessments_correlation_id"))
        batch_op.drop_column("correlation_id")
