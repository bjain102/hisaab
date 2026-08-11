"""Task 3.7 (schema half): migration v6 — drop import_batches/card_profiles,
drop transactions.card/card_label/import_batch, rename raw_merchant ->
raw_description (fixes F10: legacy tables/columns kept around after their
replacements — accounts, statements — made them redundant).
"""
import sqlite3

import pytest

import app as app_module
from db import get_version, migrate


@pytest.fixture()
def db_with_legacy_shape(tmp_path, monkeypatch):
    """Legacy-shape DB: one batch-backed transaction (with a real filename
    on its import_batches row, simulating a pre-3.4 statement that never got
    its own source_path), a card_profiles row that already has a matching
    account, and a SECOND card_profiles row for a card that was registered
    but never imported into (no matching account yet — the rescue case)."""
    db_path = str(tmp_path / 'test.db')
    monkeypatch.setattr(app_module, 'DB_PATH', db_path)
    monkeypatch.setattr(app_module, 'STATEMENTS_DIR', str(tmp_path / 'statements'))
    app_module.init_db()
    conn = sqlite3.connect(db_path)
    conn.execute(
        '''INSERT INTO transactions
           (date, description, amount, type, category, card, card_label,
            is_cashback, raw_merchant, import_batch)
           VALUES ('2026-01-05', 'X', 100.0, 'debit', 'Others', 'ALPHA', 'ALPHA-1234',
                   0, 'X', 'batch-a')''')
    conn.execute(
        "INSERT INTO import_batches (batch_id, card, card_label, filename, txn_count) "
        "VALUES ('batch-a', 'ALPHA', 'ALPHA-1234', 'January.pdf', 1)")
    conn.execute(
        "INSERT INTO card_profiles (bank, variant, last4, label) VALUES ('alpha', 'Basic', '1234', 'ALPHA-1234')")
    conn.execute(
        "INSERT INTO card_profiles (bank, variant, last4, label) VALUES ('bravo', 'Plus', '9999', 'BRAVO-9999')")
    conn.commit()
    conn.close()
    applied = migrate(db_path)
    assert 6 in applied
    return db_path


def test_never_imported_card_profile_gets_rescued_into_accounts(db_with_legacy_shape):
    conn = sqlite3.connect(db_with_legacy_shape)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM accounts WHERE kind='credit_card' AND name='BRAVO-9999'").fetchone()
    conn.close()
    assert row is not None
    assert row['institution'] == 'BRAVO'
    assert row['identifier'] == '9999'


def test_historical_statement_keeps_its_filename(db_with_legacy_shape):
    conn = sqlite3.connect(db_with_legacy_shape)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM statements").fetchone()
    conn.close()
    assert row['source_path'] is None  # honest: pre-3.4, no file was persisted
    assert row['original_filename'] == 'January.pdf'  # but the name survives


def test_legacy_tables_and_columns_gone(db_with_legacy_shape):
    conn = sqlite3.connect(db_with_legacy_shape)
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    cols = {r[1] for r in conn.execute('PRAGMA table_info(transactions)')}
    conn.close()
    assert 'import_batches' not in tables and 'card_profiles' not in tables
    assert not ({'card', 'card_label', 'import_batch'} & cols)
    assert 'raw_description' in cols and 'raw_merchant' not in cols


def test_raw_description_preserves_old_raw_merchant_value(db_with_legacy_shape):
    conn = sqlite3.connect(db_with_legacy_shape)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM transactions").fetchone()
    conn.close()
    assert row['raw_description'] == 'X'


def test_init_db_does_not_resurrect_card_label_after_v6(db_with_legacy_shape):
    """Real bug caught via a live browser check: init_db()'s legacy
    'migrations for columns added after initial release' loop used to
    include a bare, ungated `ALTER TABLE transactions ADD COLUMN card_label`
    — since transactions is rebuilt-in-place (always exists), this ALTER
    succeeded on every app start post-v6 and silently added the column back
    (all NULL), corrupting /api/transactions' card_label via a duplicate-
    column dict() collision. init_db() must be safe to call again on an
    already-migrated-to-v6 DB."""
    app_module.init_db()
    conn = sqlite3.connect(db_with_legacy_shape)
    cols = {r[1] for r in conn.execute('PRAGMA table_info(transactions)')}
    conn.close()
    assert 'card_label' not in cols


def test_idempotent(db_with_legacy_shape):
    # fixture migrates the full chain (past v6); a second call must be a no-op
    version = get_version(db_with_legacy_shape)
    assert migrate(db_with_legacy_shape) == []
    assert get_version(db_with_legacy_shape) == version
    conn = sqlite3.connect(db_with_legacy_shape)
    n = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
    conn.close()
    assert n == 1
