"""Task 3.6 (schema half): migration v5 (windowed milestones, fixes F6).

Covers the migration's own guarantees. Live windowed-progress computation is
exercised separately in tests/test_milestones.py once app.py's milestone
routes are reworked.
"""
import sqlite3

import pytest

import app as app_module
from db import get_version, migrate


@pytest.fixture()
def db_with_milestones(tmp_path, monkeypatch):
    """Legacy-shape DB: one milestone with a deadline, one without (tests the
    open-ended '9999-12-31' fallback), one for a card with zero transactions
    (still migrates fine — milestones don't require transactions, only a
    matching account) and one orphaned card_label with no matching account
    at all (must be skipped, not crash)."""
    db_path = str(tmp_path / 'test.db')
    monkeypatch.setattr(app_module, 'DB_PATH', db_path)
    monkeypatch.setattr(app_module, 'STATEMENTS_DIR', str(tmp_path / 'statements'))
    app_module.init_db()
    conn = sqlite3.connect(db_path)
    conn.execute(
        '''INSERT INTO transactions
           (date, description, amount, type, category, card, card_label, import_batch)
           VALUES ('2026-01-05', 'X', 100.0, 'debit', 'Others', 'ALPHA', 'ALPHA-1234', 'batch-a')''')
    conn.executemany(
        '''INSERT INTO milestones (card_label, name, target_spend, current_spend, benefit, deadline, created_at)
           VALUES (?,?,?,?,?,?,?)''',
        [
            ('ALPHA-1234', 'Fee Waiver', 300000.0, 50000.0, 'Fee waived', '2026-12-31', '2026-06-01 10:00:00'),
            ('ALPHA-1234', 'Bonus Points', 100000.0, 0.0, '', '', '2026-07-01 09:00:00'),
            ('GHOST-9999', 'Orphan Milestone', 50000.0, 0.0, '', '2026-12-31', '2026-06-01 10:00:00'),
        ],
    )
    conn.commit()
    conn.close()
    applied = migrate(db_path)
    assert 5 in applied
    return db_path


def test_migrated_milestones_have_windows_and_paise_targets(db_with_milestones):
    conn = sqlite3.connect(db_with_milestones)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute('SELECT * FROM milestones ORDER BY name'))
    conn.close()
    assert len(rows) == 2  # the orphaned GHOST-9999 row is skipped

    bonus, fee = rows
    assert fee['name'] == 'Fee Waiver'
    assert fee['target_paise'] == 30000000  # 300000.0 -> paise
    assert fee['window_start'] == '2026-06-01'
    assert fee['window_end'] == '2026-12-31'

    assert bonus['name'] == 'Bonus Points'
    assert bonus['window_start'] == '2026-07-01'
    assert bonus['window_end'] == '9999-12-31'  # no deadline -> open-ended


def test_migrated_milestones_linked_to_correct_account(db_with_milestones):
    conn = sqlite3.connect(db_with_milestones)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute('''
        SELECT a.name FROM milestones m JOIN accounts a ON a.id = m.account_id
    '''))
    conn.close()
    assert all(r['name'] == 'ALPHA-1234' for r in rows)


def test_legacy_columns_gone(db_with_milestones):
    conn = sqlite3.connect(db_with_milestones)
    cols = {r[1] for r in conn.execute('PRAGMA table_info(milestones)')}
    conn.close()
    assert 'card_label' not in cols and 'target_spend' not in cols
    assert 'current_spend' not in cols and 'deadline' not in cols
    assert {'account_id', 'target_paise', 'window_start', 'window_end'} <= cols


def test_idempotent(db_with_milestones):
    # The fixture's own migrate() call already ran the full chain, not just
    # to v5 — compare against that, not a hardcoded 5 (same fix as v3/v4).
    version_after_fixture = get_version(db_with_milestones)
    assert migrate(db_with_milestones) == []
    assert get_version(db_with_milestones) == version_after_fixture
    conn = sqlite3.connect(db_with_milestones)
    n = conn.execute('SELECT COUNT(*) FROM milestones').fetchone()[0]
    conn.close()
    assert n == 2
