"""Refactor coverage fingerprint

Revision ID: d57668702d42
Revises: 7ce4195624be
Create Date: 2026-09-17 23:06:05.446535
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd57668702d42'
down_revision: str | None = '7ce4195624be'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _compute_fingerprint(timestamps: list[str]) -> str:
    """Helper to compute deterministic fingerprint for the migration."""
    import hashlib
    # timestamps are assumed to be UTC isoformat strings
    normalized = sorted(timestamps)
    hasher = hashlib.sha256()
    for ts_str in normalized:
        hasher.update(ts_str.encode("utf-8"))
    return hasher.hexdigest()

def upgrade() -> None:
    # 1. Add columns as nullable
    op.add_column('market_data_coverage', sa.Column('actual_count', sa.Integer(), nullable=True))
    op.add_column('market_data_coverage', sa.Column('timestamp_fingerprint', sa.String(), nullable=True))

    # 2. Backfill data
    bind = op.get_bind()
    coverage_table = sa.table('market_data_coverage',
        sa.column('id', sa.Integer),
        sa.column('symbol', sa.String),
        sa.column('timeframe', sa.String),
        sa.column('start_time', sa.DateTime(timezone=True)),
        sa.column('end_time', sa.DateTime(timezone=True))
    )
    candles_table = sa.table('market_data_candles',
        sa.column('symbol', sa.String),
        sa.column('timeframe', sa.String),
        sa.column('timestamp', sa.DateTime(timezone=True))
    )

    from datetime import UTC
    rows = bind.execute(sa.select(
        coverage_table.c.id, coverage_table.c.symbol, coverage_table.c.timeframe,
        coverage_table.c.start_time, coverage_table.c.end_time
    )).fetchall()

    for row in rows:
        row_id, symbol, timeframe, start_time, end_time = row

        # Ensure timezone-aware
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=UTC)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=UTC)

        candle_rows = bind.execute(
            sa.select(candles_table.c.timestamp)
            .where(
                candles_table.c.symbol == symbol,
                candles_table.c.timeframe == timeframe,
                candles_table.c.timestamp >= start_time,
                candles_table.c.timestamp <= end_time
            )
        ).fetchall()

        # Load and normalize timestamps
        timestamps = []
        for (ts,) in candle_rows:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            timestamps.append(ts)

        if not timestamps:
            # Delete stale coverage
            bind.execute(coverage_table.delete().where(coverage_table.c.id == row_id))
            continue

        min_ts = min(timestamps)
        max_ts = max(timestamps)

        if min_ts > start_time or max_ts < end_time:
            # Boundary requirement not met, delete stale coverage
            bind.execute(coverage_table.delete().where(coverage_table.c.id == row_id))
            continue

        actual_count = len(timestamps)
        ts_strings = [ts.astimezone(UTC).isoformat() for ts in timestamps]
        fingerprint = _compute_fingerprint(ts_strings)

        bind.execute(
            coverage_table.update()
            .where(coverage_table.c.id == row_id)
            .values(actual_count=actual_count, timestamp_fingerprint=fingerprint)
        )

    # 3. Alter columns to NOT NULL and drop expected_count
    with op.batch_alter_table('market_data_coverage') as batch_op:
        batch_op.alter_column('actual_count', nullable=False)
        batch_op.alter_column('timestamp_fingerprint', nullable=False)
        batch_op.drop_column('expected_count')

def downgrade() -> None:
    # 1. Add expected_count as nullable
    op.add_column('market_data_coverage', sa.Column('expected_count', sa.Integer(), nullable=True))

    # 2. Backfill expected_count with actual_count
    bind = op.get_bind()
    coverage_table = sa.table('market_data_coverage',
        sa.column('actual_count', sa.Integer),
        sa.column('expected_count', sa.Integer)
    )
    bind.execute(coverage_table.update().values(expected_count=coverage_table.c.actual_count))

    # 3. Drop actual_count and timestamp_fingerprint, and make expected_count NOT NULL
    with op.batch_alter_table('market_data_coverage') as batch_op:
        batch_op.alter_column('expected_count', nullable=False)
        batch_op.drop_column('timestamp_fingerprint')
        batch_op.drop_column('actual_count')
