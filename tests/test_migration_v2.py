"""Task 3.3: migration v2 (paise, F8) — money becomes integer paise.

The `client` fixture (conftest) migrates through the full chain, so all
existing API tests already assert paise-on-the-wire. These cover the
migration's own conversion guarantees and the paise-sensitive edges.
"""
from pathlib import Path
import sqlite3

import pytest

import app as app_module
from db import get_version, migrate

_CORPUS_DIR = Path(__file__).parent / 'corpus' / 'tier1'
# This repository ships no statements (they are real financial documents), so
# every test in this module skips on a fresh clone and comes alive the moment
# you add your own to tests/corpus/tier1/ — see that directory's README.
pytestmark = pytest.mark.skipif(
    not _CORPUS_DIR.is_dir() or not any(f.suffix.lower() in ('.pdf', '.csv') for f in _CORPUS_DIR.glob('*')),
    reason='no local statement corpus — see tests/corpus/tier1/README.md',
)


@pytest.fixture()
def migrated_db(tmp_path, monkeypatch):
    """Legacy DB with awkward float amounts, migrated through the chain."""
    db_path = str(tmp_path / 'test.db')
    monkeypatch.setattr(app_module, 'DB_PATH', db_path)
    app_module.init_db()
    conn = sqlite3.connect(db_path)
    conn.executemany(
        '''INSERT INTO transactions
           (id, date, description, amount, type, category, card, card_label, is_cashback)
           VALUES (?,?,?,?,?,?,?,?,?)''',
        [
            # Amounts chosen to stress float representation: .1/.2-style
            # decimals have no exact binary form; ROUND(x*100) must still
            # land on the right integer paise.
            (1, '2026-01-05', 'FLOAT TRAP A', 0.1, 'debit', 'Others', 'ALPHA', 'CARD-A', 0),
            (2, '2026-01-06', 'FLOAT TRAP B', 1234.56, 'debit', 'Others', 'ALPHA', 'CARD-A', 0),
            (3, '2026-01-07', 'FLOAT TRAP C', 115.61, 'credit', 'Others', 'ALPHA', 'CARD-A', 0),
            (4, '2026-01-08', 'WHOLE', 5000.0, 'debit', 'Others', 'BRAVO', 'CARD-B', 0),
            (5, '2026-01-09', 'TINY', 0.01, 'debit', 'Others', 'BRAVO', 'CARD-B', 0),
        ],
    )
    conn.commit()
    conn.close()
    migrate(db_path)
    assert get_version(db_path) >= 2
    return db_path


def test_amounts_converted_exactly(migrated_db):
    conn = sqlite3.connect(migrated_db)
    got = dict(conn.execute('SELECT id, amount_paise FROM transactions'))
    conn.close()
    assert got == {1: 10, 2: 123456, 3: 11561, 4: 500000, 5: 1}


def test_float_column_gone_paise_is_integer(migrated_db):
    conn = sqlite3.connect(migrated_db)
    cols = {r[1]: r[2] for r in conn.execute('PRAGMA table_info(transactions)')}
    conn.close()
    assert 'amount' not in cols
    assert cols['amount_paise'] == 'INTEGER'


def test_zero_amount_rejected_by_check_constraint(migrated_db):
    conn = sqlite3.connect(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            '''INSERT INTO transactions (account_id, date, description, amount_paise, type, category)
               VALUES (1, '2026-02-01', 'ZERO', 0, 'debit', 'Others')''')
    conn.close()


def test_amount_sort_uses_paise(client):
    """The sort_map now orders by amount_paise — highest first must work."""
    resp = client.get('/api/transactions', query_string={'sort': 'amount_desc', 'limit': 2})
    rows = resp.get_json()
    assert resp.status_code == 200
    assert rows[0]['amount_paise'] >= rows[1]['amount_paise']


def test_upload_inserts_paise(client):
    """Parsers still emit rupee floats; the INSERT boundary converts."""
    from pathlib import Path
    corpus = Path(__file__).parent / 'corpus' / 'tier1' / 'KOTAK_ZEN_redacted.pdf'
    with open(corpus, 'rb') as f:
        resp = client.post(
            '/api/upload',
            data={'file': (f, corpus.name), 'card': 'kotak', 'card_label': 'KOTAK-PAISE-1111', 'password': ''},
            content_type='multipart/form-data')
    assert resp.status_code == 200

    conn = sqlite3.connect(app_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT t.amount_paise FROM transactions t JOIN accounts a ON a.id=t.account_id "
        "WHERE a.name='KOTAK-PAISE-1111'").fetchone()
    conn.close()
    # The Kotak tier1 file's one transaction is 1,125.00 rupees -> 112500 paise
    assert row['amount_paise'] == 112500
    assert isinstance(row['amount_paise'], int)


# The v2-era current_spend-seeded-in-rupees boundary quirk this test covered
# no longer exists: task 3.6 (migration v5) dropped `current_spend` entirely —
# progress is now a live windowed query, not a stored seed. See
# tests/test_milestones.py for the current milestone-progress coverage.
