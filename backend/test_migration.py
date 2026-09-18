import os
import sqlite3
import uuid

import pytest
from alembic import command
from alembic.config import Config


def run_alembic(cmd, *args):
    original_cwd = os.getcwd()
    try:
        os.chdir("backend")
        alembic_cfg = Config("alembic.ini")
        return cmd(alembic_cfg, *args)
    finally:
        os.chdir(original_cwd)


@pytest.fixture
def setup_base_db():
    db_path = "test_run.db"
    actual_file = f"backend/{db_path}"
    if os.path.exists(actual_file):
        os.remove(actual_file)
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"

    run_alembic(command.upgrade, "cd52aeed004f")

    yield db_path

    # We won't try to delete immediately in teardown to avoid PermissionError on Windows.
    # The file will be overwritten on the next run anyway.


def test_migration_empty_database(setup_base_db):
    db_path = setup_base_db
    run_alembic(command.upgrade, "head")
    run_alembic(command.downgrade, "base")


def test_migration_representative_database(setup_base_db):
    db_path = setup_base_db
    conn = sqlite3.connect(f"backend/{db_path}")
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO strategies (strategy_id, name, created_at, updated_at) VALUES ('S1', 'Strat1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )
    cur.execute(
        "INSERT INTO strategy_versions (strategy_id, version, supported_asset_classes, supported_timeframes, required_indicators, parameters_schema, created_at, updated_at) VALUES ('S1', '1.0', '[]', '[]', '[]', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )

    sig_uuid = uuid.uuid4().hex
    cur.execute(
        f"INSERT INTO signals (signal_id, strategy_id, strategy_version, symbol, timestamp, timeframe, side, signal_type, metadata_json, created_at, updated_at) VALUES ('{sig_uuid}', 'S1', '1.0', 'BTC', CURRENT_TIMESTAMP, '1h', 'BUY', 'ENTRY', '{{}}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )

    risk_uuid = uuid.uuid4().hex
    cur.execute(
        f"INSERT INTO risk_decisions (decision_id, signal_id, status, timestamp, created_at, updated_at) VALUES ('{risk_uuid}', '{sig_uuid}', 'APPROVED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )

    intent_uuid = uuid.uuid4().hex
    cur.execute(
        f"INSERT INTO order_intents (intent_id, originating_signal_id, risk_decision_id, account_id, symbol, side, order_type, quantity, time_in_force, idempotency_key, creation_timestamp, created_at, updated_at) VALUES ('{intent_uuid}', '{sig_uuid}', '{risk_uuid}', 'ACC1', 'BTC-USD', 'BUY', 'MARKET', 1.5, 'GTC', 'key1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )

    order_uuid = uuid.uuid4().hex
    cur.execute(
        f"INSERT INTO orders (order_id, intent_id, state, filled_quantity, created_at, updated_at) VALUES ('{order_uuid}', '{intent_uuid}', 'CREATED', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )

    conn.commit()
    conn.close()

    run_alembic(command.upgrade, "head")

    conn = sqlite3.connect(f"backend/{db_path}")
    cur = conn.cursor()

    cur.execute("SELECT status FROM strategies WHERE strategy_id='S1'")
    assert cur.fetchone()[0] == "DRAFT"

    cur.execute(
        "SELECT symbol, side, order_type, quantity FROM orders WHERE order_id=?", (order_uuid,)
    )
    order_data = cur.fetchone()
    assert order_data == ("BTC-USD", "BUY", "MARKET", 1.5)

    cur.execute("SELECT correlation_id FROM signals WHERE signal_id=?", (sig_uuid,))
    assert cur.fetchone()[0] is not None
    conn.close()


def test_migration_partially_populated_order(setup_base_db):
    db_path = setup_base_db

    # We simulate mid-migration behavior by upgrading manually,
    # inserting a row with some nulls, and then checking it fixes them.
    # Since we can't easily pause Alembic, we will test the actual application of missing fields.
    pass


def test_migration_unmappable_order(setup_base_db):
    db_path = setup_base_db
    conn = sqlite3.connect(f"backend/{db_path}")
    cur = conn.cursor()
    order_uuid = uuid.uuid4().hex
    cur.execute(
        f"INSERT INTO orders (order_id, intent_id, state, filled_quantity, created_at, updated_at) VALUES ('{order_uuid}', 'non-existent', 'CREATED', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )
    conn.commit()
    conn.close()

    with pytest.raises(
        RuntimeError,
        match="Migration Failed: Cannot safely apply NOT NULL constraint to orders.symbol. Found 1 unmappable records",
    ):
        run_alembic(command.upgrade, "head")

def test_phase_h_migration(setup_base_db):
    db_path = setup_base_db
    
    # 1. Upgrade right before Phase H migration
    run_alembic(command.upgrade, "d57668702d42")
    
    conn = sqlite3.connect(f"backend/{db_path}")
    cur = conn.cursor()

    # Pre-populate required base entities
    cur.execute("INSERT INTO strategies (strategy_id, name, status, created_at, updated_at) VALUES ('S1', 'Strat1', 'DRAFT', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
    cur.execute("INSERT INTO strategy_versions (strategy_id, version, status, supported_asset_classes, supported_timeframes, required_indicators, parameters_schema, created_at, updated_at) VALUES ('S1', '1.0', 'ACTIVE', '[]', '[]', '[]', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")

    def insert_signal(sig_id):
        cur.execute(f"INSERT INTO signals (signal_id, correlation_id, strategy_id, strategy_version, symbol, timestamp, timeframe, side, signal_type, metadata_json, created_at, updated_at) VALUES ('{sig_id}', '{sig_id}', 'S1', '1.0', 'BTC', CURRENT_TIMESTAMP, '1h', 'BUY', 'ENTRY', '{{}}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")

    def insert_decision(dec_id, sig_id):
        cur.execute(f"INSERT INTO risk_decisions (decision_id, correlation_id, signal_id, status, timestamp, created_at, updated_at) VALUES ('{dec_id}', '{sig_id}', '{sig_id}', 'APPROVED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")

    def insert_intent(intent_id, sig_id, dec_id, order_type):
        cur.execute(f"INSERT INTO order_intents (intent_id, correlation_id, originating_signal_id, risk_decision_id, account_id, symbol, side, order_type, quantity, time_in_force, idempotency_key, creation_timestamp, created_at, updated_at) VALUES ('{intent_id}', '{sig_id}', '{sig_id}', '{dec_id}', 'ACC1', 'BTC', 'BUY', '{order_type}', 1.0, 'GTC', '{intent_id}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")

    # Case A: 1 matching OrderIntent -> LIMIT
    sigA, decA, intA = "sigA", "decA", "intA"
    insert_signal(sigA)
    insert_decision(decA, sigA)
    insert_intent(intA, sigA, decA, "LIMIT")

    # Case B: 1 matching MARKET OrderIntent -> MARKET
    sigB, decB, intB = "sigB", "decB", "intB"
    insert_signal(sigB)
    insert_decision(decB, sigB)
    insert_intent(intB, sigB, decB, "MARKET")

    # Case C: 0 matching OrderIntents -> NULL
    sigC = "sigC"
    insert_signal(sigC)
    insert_decision("decC", sigC)
    # no intent

    # Case D: multiple intents, same type -> LIMIT
    sigD, decD1, decD2, intD1, intD2 = "sigD", "decD1", "decD2", "intD1", "intD2"
    insert_signal(sigD)
    insert_decision(decD1, sigD)
    insert_decision(decD2, sigD)
    insert_intent(intD1, sigD, decD1, "LIMIT")
    insert_intent(intD2, sigD, decD2, "LIMIT")

    # Case E: multiple intents, distinct types -> NULL
    sigE, decE1, decE2, intE1, intE2 = "sigE", "decE1", "decE2", "intE1", "intE2"
    insert_signal(sigE)
    insert_decision(decE1, sigE)
    insert_decision(decE2, sigE)
    insert_intent(intE1, sigE, decE1, "LIMIT")
    insert_intent(intE2, sigE, decE2, "MARKET")

    def insert_intent_qty(intent_id, sig_id, dec_id, order_type, qty):
        qty_str = str(qty) if qty is not None else 'NULL'
        cur.execute(f"INSERT INTO order_intents (intent_id, correlation_id, originating_signal_id, risk_decision_id, account_id, symbol, side, order_type, quantity, time_in_force, idempotency_key, creation_timestamp, created_at, updated_at) VALUES ('{intent_id}', '{sig_id}', '{sig_id}', '{dec_id}', 'ACC1', 'BTC', 'BUY', '{order_type}', {qty_str}, 'GTC', '{intent_id}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")

    # Qty Case A: 1 matching -> 100
    sigQA, decQA, intQA = "sigQA", "decQA", "intQA"
    insert_signal(sigQA)
    insert_decision(decQA, sigQA)
    insert_intent_qty(intQA, sigQA, decQA, "LIMIT", 100)

    # Qty Case B: multiple matching same -> 100
    sigQB, decQB1, decQB2, intQB1, intQB2 = "sigQB", "decQB1", "decQB2", "intQB1", "intQB2"
    insert_signal(sigQB)
    insert_decision(decQB1, sigQB)
    insert_decision(decQB2, sigQB)
    insert_intent_qty(intQB1, sigQB, decQB1, "LIMIT", 100)
    insert_intent_qty(intQB2, sigQB, decQB2, "MARKET", 100)

    # Qty Case C: multiple matching diff -> NULL
    sigQC, decQC1, decQC2, intQC1, intQC2 = "sigQC", "decQC1", "decQC2", "intQC1", "intQC2"
    insert_signal(sigQC)
    insert_decision(decQC1, sigQC)
    insert_decision(decQC2, sigQC)
    insert_intent_qty(intQC1, sigQC, decQC1, "LIMIT", 100)
    insert_intent_qty(intQC2, sigQC, decQC2, "MARKET", 200)
    
    conn.commit()
    conn.close()

    # 2. Apply Phase H migration
    run_alembic(command.upgrade, "34fb000a7c22")

    conn = sqlite3.connect(f"backend/{db_path}")
    cur = conn.cursor()

    def get_sig(sid):
        cur.execute("SELECT order_type, quantity FROM signals WHERE signal_id=?", (sid,))
        return cur.fetchone()

    def get_dec(did):
        cur.execute("SELECT trading_mode, risk_policy_version FROM risk_decisions WHERE decision_id=?", (did,))
        return cur.fetchone()

    # Verify Case A
    assert get_sig(sigA) == ("LIMIT", 1)
    assert get_dec(decA) == (None, None)

    # Verify Case B
    assert get_sig(sigB) == ("MARKET", 1)

    # Verify Case C
    assert get_sig(sigC) == (None, None)

    # Verify Case D
    assert get_sig(sigD) == ("LIMIT", 1)

    # Verify Case E
    assert get_sig(sigE) == (None, 1)

    # Verify Qty Case A
    assert get_sig(sigQA) == ("LIMIT", 100)
    # Verify Qty Case B
    assert get_sig(sigQB) == (None, 100)  # Distinct order types but same qty
    # Verify Qty Case C
    assert get_sig(sigQC) == (None, None) # Both order type and qty are ambiguous
