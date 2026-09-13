import os
import sqlite3
import uuid

from alembic import command
from alembic.config import Config


def test_migration():
    db_path = "test_migrations.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"

    # 1. Upgrade to first revision
    alembic_cfg = Config("alembic.ini")
    print("Upgrading to cd52aeed004f")
    command.upgrade(alembic_cfg, "cd52aeed004f")

    # 2. Insert mock data
    print("Inserting mock data")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Insert a strategy
    cur.execute(
        "INSERT INTO strategies (strategy_id, name, created_at, updated_at) VALUES ('S1', 'Strat1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )

    # Insert a strategy version
    cur.execute(
        "INSERT INTO strategy_versions (strategy_id, version, supported_asset_classes, supported_timeframes, required_indicators, parameters_schema, created_at, updated_at) VALUES ('S1', '1.0', '[]', '[]', '[]', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )

    # Insert signal
    sig_uuid = uuid.uuid4().hex
    cur.execute(
        f"INSERT INTO signals (signal_id, strategy_id, strategy_version, symbol, timestamp, timeframe, side, signal_type, metadata_json, created_at, updated_at) VALUES ('{sig_uuid}', 'S1', '1.0', 'BTC', CURRENT_TIMESTAMP, '1h', 'BUY', 'ENTRY', '{{}}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )

    # Insert order intent
    intent_uuid = uuid.uuid4().hex
    # need risk decision
    risk_uuid = uuid.uuid4().hex
    cur.execute(
        f"INSERT INTO risk_decisions (decision_id, signal_id, status, timestamp, created_at, updated_at) VALUES ('{risk_uuid}', '{sig_uuid}', 'APPROVED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )

    cur.execute(
        f"INSERT INTO order_intents (intent_id, originating_signal_id, risk_decision_id, account_id, symbol, side, order_type, quantity, time_in_force, idempotency_key, creation_timestamp, created_at, updated_at) VALUES ('{intent_uuid}', '{sig_uuid}', '{risk_uuid}', 'ACC1', 'BTC-USD', 'BUY', 'MARKET', 1.5, 'GTC', 'key1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )

    # Insert order
    order_uuid = uuid.uuid4().hex
    cur.execute(
        f"INSERT INTO orders (order_id, intent_id, state, filled_quantity, created_at, updated_at) VALUES ('{order_uuid}', '{intent_uuid}', 'CREATED', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )

    conn.commit()
    conn.close()

    # 3. Upgrade to head (phase_b_hardening)
    print("Upgrading to head")
    command.upgrade(alembic_cfg, "head")

    # 4. Verify data
    print("Verifying data")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT status FROM strategies WHERE strategy_id='S1'")
    assert cur.fetchone()[0] == "DRAFT"

    cur.execute(
        "SELECT symbol, side, order_type, quantity FROM orders WHERE order_id=?", (order_uuid,)
    )
    order_data = cur.fetchone()
    print("Backfilled Order Data:", order_data)
    assert order_data == ("BTC-USD", "BUY", "MARKET", 1.5)

    cur.execute("SELECT correlation_id FROM signals WHERE signal_id=?", (sig_uuid,))
    assert cur.fetchone()[0] is not None

    conn.close()

    print("Testing downgrade...")
    command.downgrade(alembic_cfg, "base")
    print("Migration successful and verified!")


if __name__ == "__main__":
    test_migration()
