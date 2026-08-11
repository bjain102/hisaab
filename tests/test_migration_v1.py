"""Task 3.2: migration v1 (accounts) — the first real migration.

The generic `client` fixture (conftest) already migrates, so every existing
API test implicitly proves the API is unchanged post-v1. These tests cover
the migration's own guarantees plus the new upload-time account resolution.
"""
import sqlite3
from pathlib import Path

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

CORPUS_TIER1 = Path(__file__).parent / 'corpus' / 'tier1'


@pytest.fixture()
def migrated_db(tmp_path, monkeypatch):
    """Legacy DB with two cards + one matching card_profile, then migrated."""
    db_path = str(tmp_path / 'test.db')
    monkeypatch.setattr(app_module, 'DB_PATH', db_path)
    app_module.init_db()
    conn = sqlite3.connect(db_path)
    conn.executemany(
        '''INSERT INTO transactions
           (id, date, description, amount, type, category, card, card_label, is_cashback)
           VALUES (?,?,?,?,?,?,?,?,?)''',
        [
            (10, '2026-01-05', 'ROW A1', 100.0, 'debit', 'Others', 'ALPHA', 'ALPHA-Test-1234', 0),
            (11, '2026-01-06', 'ROW A2', 50.0, 'credit', 'Others', 'ALPHA', 'ALPHA-Test-1234', 0),
            (12, '2026-02-01', 'ROW B1', 200.0, 'debit', 'Others', 'BRAVO', 'CARD-B', 0),
        ],
    )
    # profile matches the first label -> enrichment source
    conn.execute(
        "INSERT INTO card_profiles (bank, variant, last4, label) VALUES ('alpha','Test','1234','ALPHA-Test-1234')")
    conn.commit()
    conn.close()
    applied = migrate(db_path)
    assert applied[0] == 1 and applied == sorted(applied)  # full chain, v1 first
    return db_path


def test_accounts_seeded_and_enriched(migrated_db):
    conn = sqlite3.connect(migrated_db)
    conn.row_factory = sqlite3.Row
    accounts = {r['name']: r for r in conn.execute("SELECT * FROM accounts WHERE kind='credit_card'")}
    conn.close()
    assert set(accounts) == {'ALPHA-Test-1234', 'CARD-B'}
    # enriched from the matching card_profile
    assert accounts['ALPHA-Test-1234']['institution'] == 'ALPHA'
    assert accounts['ALPHA-Test-1234']['identifier'] == '1234'
    # fallbacks: institution from transactions.card; no -NNNN tail -> no identifier
    assert accounts['CARD-B']['institution'] == 'BRAVO'
    assert accounts['CARD-B']['identifier'] is None


def test_backfill_preserves_ids_and_counts(migrated_db):
    conn = sqlite3.connect(migrated_db)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute(
        'SELECT t.id, t.account_id, a.name FROM transactions t JOIN accounts a ON a.id=t.account_id ORDER BY t.id'))
    conn.close()
    assert [r['id'] for r in rows] == [10, 11, 12]        # ids survived the rebuild
    assert all(r['account_id'] is not None for r in rows)
    assert [r['name'] for r in rows] == ['ALPHA-Test-1234', 'ALPHA-Test-1234', 'CARD-B']


def test_migration_is_idempotent(migrated_db):
    assert migrate(migrated_db) == []                     # nothing pending after full chain
    assert get_version(migrated_db) >= 1


def test_new_inserts_still_autoincrement_past_old_ids(migrated_db):
    conn = sqlite3.connect(migrated_db)
    cur = conn.execute(
        '''INSERT INTO transactions (account_id, date, description, amount_paise, type, category)
           VALUES (1, '2026-03-01', 'NEW ROW', 1000, 'debit', 'Others')''')
    new_id = cur.lastrowid
    conn.close()
    assert new_id > 12                                    # AUTOINCREMENT sequence carried over


# ── Upload-time account resolution (the app-side half of 3.2) ─────────────────

def upload(client, path, card, card_label):
    with open(path, 'rb') as f:
        return client.post(
            '/api/upload',
            data={'file': (f, path.name), 'card': card, 'card_label': card_label, 'password': ''},
            content_type='multipart/form-data',
        )


def test_upload_creates_account_for_new_card(client):
    # `client` is migrated (conftest); KOTAK-NEW-9999 has no account yet
    resp = upload(client, CORPUS_TIER1 / 'KOTAK_ZEN_redacted.pdf', 'kotak', 'KOTAK-NEW-9999')
    assert resp.status_code == 200

    conn = sqlite3.connect(app_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    acct = conn.execute(
        "SELECT * FROM accounts WHERE kind='credit_card' AND name='KOTAK-NEW-9999'").fetchone()
    assert acct is not None
    assert acct['institution'] == 'KOTAK'
    assert acct['identifier'] == '9999'
    n_linked = conn.execute(
        'SELECT COUNT(*) FROM transactions WHERE account_id=?', (acct['id'],)).fetchone()[0]
    conn.close()
    assert n_linked == resp.get_json()['imported']


def test_upload_reuses_existing_account(client):
    first = upload(client, CORPUS_TIER1 / 'KOTAK_ZEN_redacted.pdf', 'kotak', 'KOTAK-NEW-9999')
    second = upload(client, CORPUS_TIER1 / 'KOTAK_ZEN_redacted-2.pdf', 'kotak', 'KOTAK-NEW-9999')
    assert first.status_code == second.status_code == 200

    conn = sqlite3.connect(app_module.DB_PATH)
    n_accounts = conn.execute(
        "SELECT COUNT(*) FROM accounts WHERE name='KOTAK-NEW-9999'").fetchone()[0]
    conn.close()
    assert n_accounts == 1                                # get-or-create, not duplicate