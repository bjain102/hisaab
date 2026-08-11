"""Task 4.2 (app half): ADR-009 categorization on upload + recategorize, over
the conftest `client` fixture (synthetic DB migrated through v7).
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


def _txn(client, **where):
    conn = sqlite3.connect(app_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    clause = ' AND '.join(f'{k}=?' for k in where)
    row = conn.execute(f'SELECT * FROM transactions WHERE {clause} ORDER BY id LIMIT 1',
                       tuple(where.values())).fetchone()
    conn.close()
    return row


def test_upload_stamps_category_source_and_merchant(client):
    """A fresh import assigns category_source to every row; a keyword-derived
    row is stamped 'keyword' (the conftest DB has no confirmed merchants, so
    everything falls to the keyword tier)."""
    with open(CORPUS_TIER1 / 'KOTAK_ZEN_redacted.pdf', 'rb') as f:
        resp = client.post('/api/upload', data={
            'file': (f, 'KOTAK_ZEN_redacted.pdf'), 'card': 'kotak',
            'card_label': 'KOTAK-CAT-TEST', 'password': ''},
            content_type='multipart/form-data')
    assert resp.status_code == 200
    conn = sqlite3.connect(app_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    srcs = [r[0] for r in conn.execute('''
        SELECT DISTINCT category_source FROM transactions t
        JOIN accounts a ON a.id=t.account_id WHERE a.name='KOTAK-CAT-TEST' ''')]
    none_left = conn.execute('''
        SELECT COUNT(*) FROM transactions t JOIN accounts a ON a.id=t.account_id
        WHERE a.name='KOTAK-CAT-TEST' AND category_source='none' ''').fetchone()[0]
    conn.close()
    assert none_left == 0
    assert set(srcs) <= {'confirmed', 'suggested', 'bank', 'keyword', 'manual'}


def test_recategorize_without_learn_is_a_manual_pin(client):
    row = _txn(client, description='SAMPLE RESTAURANT')
    resp = client.post('/api/recategorize', json={
        'id': row['id'], 'category': 'Travel', 'learn': False})
    assert resp.status_code == 200
    after = _txn(client, id=row['id'])
    assert after['category'] == 'Travel'
    assert after['category_source'] == 'manual'


def test_recategorize_with_learn_creates_confirmed_merchant_and_restamps(client):
    # conftest seeds two 'SAMPLE ...' merchants? no — seed rows use distinct
    # descriptions. Use the two CARD-A food rows: one restaurant, one cafe are
    # distinct; instead learn on a shared token. Seed has 'SAMPLE RESTAURANT'
    # and 'SAMPLE CAFE' — learn merchant 'SAMPLE' to catch both.
    r1 = _txn(client, description='SAMPLE RESTAURANT')
    resp = client.post('/api/recategorize', json={
        'id': r1['id'], 'category': 'Entertainment', 'learn': True, 'merchant': 'SAMPLE'})
    assert resp.status_code == 200

    conn = sqlite3.connect(app_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    merchant = conn.execute("SELECT * FROM merchants WHERE status='confirmed' AND category='Entertainment'").fetchone()
    alias = conn.execute("SELECT * FROM merchant_aliases WHERE pattern='sample'").fetchone()
    # every non-manual txn whose normalized desc contains 'sample' is now confirmed+Entertainment
    stamped = conn.execute('''
        SELECT description, category, category_source, merchant_id FROM transactions
        WHERE category_source='confirmed' AND merchant_id=? ORDER BY description''',
        (merchant['id'],)).fetchall()
    conn.close()
    assert merchant is not None and alias is not None
    descs = {r['description'] for r in stamped}
    assert 'SAMPLE RESTAURANT' in descs and 'SAMPLE CAFE' in descs
    assert all(r['category'] == 'Entertainment' for r in stamped)


def test_learn_does_not_touch_existing_manual_pins(client):
    # pin SAMPLE CAFE manually to Medical, then learn SAMPLE -> Entertainment.
    cafe = _txn(client, description='SAMPLE CAFE')
    client.post('/api/recategorize', json={'id': cafe['id'], 'category': 'Medical', 'learn': False})
    rest = _txn(client, description='SAMPLE RESTAURANT')
    client.post('/api/recategorize', json={
        'id': rest['id'], 'category': 'Entertainment', 'learn': True, 'merchant': 'SAMPLE'})

    cafe_after = _txn(client, id=cafe['id'])
    assert cafe_after['category'] == 'Medical'          # manual pin preserved
    assert cafe_after['category_source'] == 'manual'
