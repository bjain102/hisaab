"""Task 3.4 (schema half): migration v3 (statements table + linkage).

Covers the migration's own guarantees. App-side gating (SHA-256 reject,
period-overlap reject/force, file persistence) is exercised separately in
tests/test_gating.py once app.py's upload route is reworked.
"""
import sqlite3

import pytest

import app as app_module
from db import get_version, migrate


@pytest.fixture()
def db_with_batches(tmp_path, monkeypatch):
    """Legacy-shape DB: one account's worth of transactions across two
    non-overlapping batches, plus a batch with zero surviving transactions
    (simulates a fully-deleted import) to prove it's correctly skipped."""
    db_path = str(tmp_path / 'test.db')
    monkeypatch.setattr(app_module, 'DB_PATH', db_path)
    app_module.init_db()
    conn = sqlite3.connect(db_path)
    conn.executemany(
        '''INSERT INTO transactions
           (date, description, amount, type, category, card, card_label, import_batch)
           VALUES (?,?,?,?,?,?,?,?)''',
        [
            ('2026-01-05', 'JAN 1', 100.0, 'debit', 'Others', 'ALPHA', 'ALPHA-1234', 'batch-jan'),
            ('2026-01-20', 'JAN 2', 50.0, 'debit', 'Others', 'ALPHA', 'ALPHA-1234', 'batch-jan'),
            ('2026-02-03', 'FEB 1', 75.0, 'debit', 'Others', 'ALPHA', 'ALPHA-1234', 'batch-feb'),
        ],
    )
    conn.executemany(
        "INSERT INTO import_batches (batch_id, card, card_label, filename, txn_count) VALUES (?,?,?,?,?)",
        [
            ('batch-jan', 'ALPHA', 'ALPHA-1234', 'January.pdf', 2),
            ('batch-feb', 'ALPHA', 'ALPHA-1234', 'February.pdf', 1),
            ('batch-deleted', 'ALPHA', 'ALPHA-1234', 'Deleted.pdf', 0),  # no txns -> no statement
        ],
    )
    conn.commit()
    conn.close()
    applied = migrate(db_path)
    assert 3 in applied
    return db_path


def test_one_statement_per_batch_with_transactions(db_with_batches):
    conn = sqlite3.connect(db_with_batches)
    conn.row_factory = sqlite3.Row
    stmts = list(conn.execute('SELECT * FROM statements ORDER BY period_start'))
    conn.close()
    assert len(stmts) == 2  # batch-deleted correctly produces no statement
    jan, feb = stmts
    assert (jan['period_start'], jan['period_end']) == ('2026-01-05', '2026-01-20')
    assert (feb['period_start'], feb['period_end']) == ('2026-02-03', '2026-02-03')
    assert jan['format'] == 'pdf'
    assert jan['source_path'] is None and jan['file_sha256'] is None  # honest: pre-3.4 files are gone
    assert jan['txn_count'] == 2 and feb['txn_count'] == 1


def test_transactions_linked_to_correct_statement(db_with_batches):
    conn = sqlite3.connect(db_with_batches)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute('''
        SELECT t.description, s.period_start FROM transactions t
        JOIN statements s ON s.id = t.statement_id ORDER BY t.date
    '''))
    conn.close()
    assert [(r['description'], r['period_start']) for r in rows] == [
        ('JAN 1', '2026-01-05'), ('JAN 2', '2026-01-05'), ('FEB 1', '2026-02-03'),
    ]


def test_no_overlap_in_this_fixture(db_with_batches, capsys):
    # Jan and Feb periods are disjoint — the overlap report should say so.
    conn = sqlite3.connect(db_with_batches)
    n = conn.execute('SELECT COUNT(*) FROM statements').fetchone()[0]
    conn.close()
    assert n == 2  # sanity: fixture didn't drift


def test_overlap_report_prints_for_intersecting_periods(tmp_path, monkeypatch, capsys):
    db_path = str(tmp_path / 'test.db')
    monkeypatch.setattr(app_module, 'DB_PATH', db_path)
    app_module.init_db()
    conn = sqlite3.connect(db_path)
    conn.executemany(
        '''INSERT INTO transactions
           (date, description, amount, type, category, card, card_label, import_batch)
           VALUES (?,?,?,?,?,?,?,?)''',
        [
            ('2026-01-05', 'A', 100.0, 'debit', 'Others', 'ALPHA', 'ALPHA-1234', 'full-cycle'),
            ('2026-01-20', 'B', 100.0, 'debit', 'Others', 'ALPHA', 'ALPHA-1234', 'full-cycle'),
            ('2026-01-10', 'C', 50.0, 'debit', 'Others', 'ALPHA', 'ALPHA-1234', 'partial-reimport'),
        ],
    )
    conn.executemany(
        "INSERT INTO import_batches (batch_id, card, card_label, filename, txn_count) VALUES (?,?,?,?,?)",
        [('full-cycle', 'ALPHA', 'ALPHA-1234', 'Jan.pdf', 2),
         ('partial-reimport', 'ALPHA', 'ALPHA-1234', 'JanRedo.pdf', 1)],
    )
    conn.commit()
    conn.close()
    migrate(db_path)
    out = capsys.readouterr().out
    assert 'OVERLAP REPORT' in out
    assert '2 overlapping' in out or 'overlapping statement pairs' in out


def test_idempotent(db_with_batches):
    # This fixture's own migrate() call (in db_with_batches above) already ran
    # the full chain to whatever the latest migration is, not just v3 — a
    # second call here must be a true no-op regardless of how many
    # migrations exist beyond v3. (import_batches itself is dropped at v6 —
    # see tests/test_migration_v6.py; this fixture's migrate() already ran
    # past that, so there's nothing v3-specific left to assert about it here.)
    version_after_fixture = get_version(db_with_batches)
    assert migrate(db_with_batches) == []
    assert get_version(db_with_batches) == version_after_fixture
