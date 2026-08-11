"""Task 3.7 (app-side): /api/statements (replaces import_batches for the
Import view's history list) and the one-time dedup-cleanup surface
(/api/dedup_candidates, DELETE /api/transactions/<id>). The app never
auto-deletes a duplicate — these tests only check that candidates are
reported correctly and that the deletion levers work; the owner's actual
review judgment isn't something a test can stand in for.
"""
import pytest
import sqlite3
from pathlib import Path

import app as app_module

_CORPUS_DIR = Path(__file__).parent / 'corpus' / 'tier1'
# This repository ships no statements (they are real financial documents), so
# every test in this module skips on a fresh clone and comes alive the moment
# you add your own to tests/corpus/tier1/ — see that directory's README.
pytestmark = pytest.mark.skipif(
    not _CORPUS_DIR.is_dir() or not any(f.suffix.lower() in ('.pdf', '.csv') for f in _CORPUS_DIR.glob('*')),
    reason='no local statement corpus — see tests/corpus/tier1/README.md',
)

CORPUS_TIER1 = Path(__file__).parent / 'corpus' / 'tier1'


def upload(client, path, card, card_label, force=False):
    with open(path, 'rb') as f:
        data = {'file': (f, path.name), 'card': card, 'card_label': card_label, 'password': ''}
        if force:
            data['force'] = 'true'
        return client.post('/api/upload', data=data, content_type='multipart/form-data')


def test_statements_list_shows_filename_and_card_label(client):
    resp = upload(client, CORPUS_TIER1 / 'KOTAK_ZEN_redacted.pdf', 'kotak', 'KOTAK-STMT-TEST')
    assert resp.status_code == 200

    statements = client.get('/api/statements').get_json()
    row = next(s for s in statements if s['card_label'] == 'KOTAK-STMT-TEST')
    assert row['filename'] == 'KOTAK_ZEN_redacted.pdf'
    assert row['txn_count'] > 0


def test_overlapping_statements_reported_as_dedup_candidates(client):
    original = (CORPUS_TIER1 / 'KOTAK_ZEN_redacted.pdf').read_bytes()
    tampered = original + b'\n'

    client.post('/api/upload', data={
        'file': (__import__('io').BytesIO(original), 'a.pdf'), 'card': 'kotak',
        'card_label': 'KOTAK-DEDUP-TEST', 'password': '',
    }, content_type='multipart/form-data')
    client.post('/api/upload', data={
        'file': (__import__('io').BytesIO(tampered), 'b.pdf'), 'card': 'kotak',
        'card_label': 'KOTAK-DEDUP-TEST', 'password': '', 'force': 'true',
    }, content_type='multipart/form-data')

    candidates = client.get('/api/dedup_candidates').get_json()
    pair = next(p for p in candidates['overlapping_statements'] if p['card_label'] == 'KOTAK-DEDUP-TEST')
    assert pair['id1'] and pair['id2']


def test_duplicate_transaction_groups_detected(client):
    conn = sqlite3.connect(app_module.DB_PATH)
    account_id = conn.execute(
        "SELECT id FROM accounts WHERE name='CARD-A'").fetchone()[0]
    # Insert a byte-for-byte duplicate of an existing seeded row (same
    # account/date/description/amount/type) — the audit's "same-tuple" shape.
    conn.execute('''
        INSERT INTO transactions (account_id, date, description, amount_paise, type, category, is_cashback)
        VALUES (?, '2026-01-05', 'SAMPLE RESTAURANT', 100000, 'debit', 'Food & Drinks', 0)
    ''', (account_id,))
    conn.commit()
    conn.close()

    candidates = client.get('/api/dedup_candidates').get_json()
    group = next(g for g in candidates['duplicate_groups']
                 if g['transactions'][0]['description'] == 'SAMPLE RESTAURANT')
    assert group['count'] == 2
    assert len(group['transactions']) == 2


def test_delete_one_transaction_resolves_a_duplicate_group(client):
    conn = sqlite3.connect(app_module.DB_PATH)
    account_id = conn.execute("SELECT id FROM accounts WHERE name='CARD-A'").fetchone()[0]
    conn.execute('''
        INSERT INTO transactions (account_id, date, description, amount_paise, type, category, is_cashback)
        VALUES (?, '2026-01-10', 'SAMPLE AIRLINE', 50000, 'debit', 'Travel', 0)
    ''', (account_id,))
    conn.commit()
    conn.close()

    before = client.get('/api/dedup_candidates').get_json()
    group = next(g for g in before['duplicate_groups']
                 if g['transactions'][0]['description'] == 'SAMPLE AIRLINE')
    dupe_id = group['transactions'][-1]['id']

    resp = client.delete(f'/api/transactions/{dupe_id}')
    assert resp.status_code == 200

    after = client.get('/api/dedup_candidates').get_json()
    assert not any(g['transactions'][0]['description'] == 'SAMPLE AIRLINE' for g in after['duplicate_groups'])


def test_delete_statement_resolves_an_overlap_pair():
    pass  # covered by tests/test_migrations.py::test_statement_delete_takes_a_backup_first
