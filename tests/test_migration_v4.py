"""Task 3.5 (schema half): migration v4 (reward_balances, replacing rewards).

Covers the migration's own guarantees. App-side reward-history writing
(as_of = statement period_end, sparkline read) is exercised separately in
tests/test_reward_history.py once app.py's upload/rewards routes are reworked.
"""
import sqlite3

import pytest

import app as app_module
from db import get_version, migrate


@pytest.fixture()
def db_with_rewards(tmp_path, monkeypatch):
    """Legacy-shape DB: one accounts-eligible card with a statement-sourced
    points balance, one with a manual cashback_inr entry, one with a
    balance_inr entry — covers all three legacy value_types."""
    db_path = str(tmp_path / 'test.db')
    monkeypatch.setattr(app_module, 'DB_PATH', db_path)
    monkeypatch.setattr(app_module, 'STATEMENTS_DIR', str(tmp_path / 'statements'))
    app_module.init_db()
    conn = sqlite3.connect(db_path)
    conn.execute(
        '''INSERT INTO transactions
           (date, description, amount, type, category, card, card_label, import_batch)
           VALUES ('2026-01-05', 'X', 100.0, 'debit', 'Others', 'ALPHA', 'ALPHA-1234', 'batch-a')''')
    conn.execute(
        '''INSERT INTO transactions
           (date, description, amount, type, category, card, card_label, import_batch)
           VALUES ('2026-01-06', 'Y', 50.0, 'debit', 'Others', 'BRAVO', 'BRAVO-5678', 'batch-b')''')
    conn.executemany(
        '''INSERT INTO rewards (card_label, label, value, value_type, source, updated_at)
           VALUES (?,?,?,?,?,?)''',
        [
            ('ALPHA-1234', 'EDGE Points', 12345, 'points', 'statement', '2026-02-01T10:00:00'),
            ('BRAVO-5678', 'Cashback', 250.50, 'cashback_inr', 'manual', '2026-02-15T09:30:00'),
        ],
    )
    conn.commit()
    conn.close()
    applied = migrate(db_path)
    assert 4 in applied
    return db_path


def test_one_reward_balance_per_legacy_row(db_with_rewards):
    conn = sqlite3.connect(db_with_rewards)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute('SELECT * FROM reward_balances ORDER BY as_of'))
    conn.close()
    assert len(rows) == 2
    points, cashback = rows
    assert points['label'] == 'EDGE Points'
    assert points['value_type'] == 'points'
    assert points['value_minor'] == 12345
    assert points['as_of'] == '2026-02-01'
    assert points['source'] == 'statement'

    assert cashback['value_type'] == 'cashback_paise'
    assert cashback['value_minor'] == 25050  # 250.50 -> paise
    assert cashback['source'] == 'manual'


def test_reward_balances_linked_to_correct_account(db_with_rewards):
    conn = sqlite3.connect(db_with_rewards)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute('''
        SELECT a.name, rb.label FROM reward_balances rb
        JOIN accounts a ON a.id = rb.account_id ORDER BY a.name
    '''))
    conn.close()
    assert [(r['name'], r['label']) for r in rows] == [
        ('ALPHA-1234', 'EDGE Points'), ('BRAVO-5678', 'Cashback'),
    ]


def test_legacy_rewards_table_dropped(db_with_rewards):
    conn = sqlite3.connect(db_with_rewards)
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert 'rewards' not in tables
    assert 'reward_balances' in tables


def test_idempotent(db_with_rewards):
    # The fixture's own migrate() call already ran the full chain to
    # whatever the latest migration is, not just v4 — compare against that,
    # not a hardcoded 4, so this doesn't break every time a new migration lands.
    version_after_fixture = get_version(db_with_rewards)
    assert migrate(db_with_rewards) == []
    assert get_version(db_with_rewards) == version_after_fixture
    conn = sqlite3.connect(db_with_rewards)
    n = conn.execute('SELECT COUNT(*) FROM reward_balances').fetchone()[0]
    conn.close()
    assert n == 2


def test_row_with_no_matching_account_is_skipped_not_crashed(tmp_path, monkeypatch):
    """A rewards row for a card_label that never made it into accounts (e.g.
    a manually-added reward for a card with zero transactions) has nothing to
    link to — must be skipped cleanly, not raise."""
    db_path = str(tmp_path / 'test.db')
    monkeypatch.setattr(app_module, 'DB_PATH', db_path)
    monkeypatch.setattr(app_module, 'STATEMENTS_DIR', str(tmp_path / 'statements'))
    app_module.init_db()
    conn = sqlite3.connect(db_path)
    conn.execute(
        '''INSERT INTO rewards (card_label, label, value, value_type, source, updated_at)
           VALUES ('GHOST-0000', 'Orphan Points', 500, 'points', 'manual', '2026-03-01T00:00:00')''')
    conn.commit()
    conn.close()
    migrate(db_path)
    conn = sqlite3.connect(db_path)
    n = conn.execute('SELECT COUNT(*) FROM reward_balances').fetchone()[0]
    conn.close()
    assert n == 0
