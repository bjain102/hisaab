"""Task 4.3: review queue, one-click confirm, trust meter, blast radius, merge.

Uses the conftest `client` fixture (synthetic CARD-A/CARD-B dataset migrated
through v7 — all spend starts keyword-sourced, so the queue is fully populated).
"""
import sqlite3

import app as app_module


def _trust(client):
    return client.get('/api/summary').get_json()['trust']


def test_queue_groups_unconfirmed_by_merchant(client):
    queue = client.get('/api/review_queue').get_json()
    assert len(queue) > 0
    # every group is a normalized merchant key with a positive spend total
    assert all(g['merchant'] and g['total'] > 0 for g in queue)
    # sorted by spend descending
    totals = [g['total'] for g in queue]
    assert totals == sorted(totals, reverse=True)


def test_confirm_restamps_all_matching_in_one_roundtrip(client):
    # A broad 'sample' confirm exercises both restamp-many AND manual-protection:
    # several seed rows normalize to contain 'sample', but 'SAMPLE STORE' was
    # marked manual by the migration (its Shopping disagreed with keyword) and
    # must be left untouched.
    resp = client.post('/api/review_queue/confirm', json={
        'merchant': 'sample', 'category': 'Entertainment'})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['restamped'] >= 2 and body['merchant_id'] is not None

    conn = sqlite3.connect(app_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    confirmed = {r['description'] for r in conn.execute(
        "SELECT description FROM transactions WHERE merchant_id=? "
        "AND category='Entertainment' AND category_source='confirmed'", (body['merchant_id'],))}
    store = conn.execute("SELECT category, category_source FROM transactions "
                         "WHERE description='SAMPLE STORE'").fetchone()
    conn.close()
    assert {'SAMPLE RESTAURANT', 'SAMPLE CAFE'} <= confirmed  # restamped in one round-trip
    assert store['category'] == 'Shopping' and store['category_source'] == 'manual'  # protected


def test_trust_meter_moves_when_you_confirm(client):
    before = _trust(client)
    client.post('/api/review_queue/confirm', json={'merchant': 'sample', 'category': 'Entertainment'})
    after = _trust(client)
    assert after > before  # confirming spend raises the paise-weighted trust fraction


def test_confirmed_group_leaves_the_queue(client):
    client.post('/api/review_queue/confirm', json={'merchant': 'sample', 'category': 'Entertainment'})
    queue = client.get('/api/review_queue').get_json()
    assert not any('sample' in g['merchant'] for g in queue)


def test_blast_radius_previews_without_mutating(client):
    res = client.get('/api/blast_radius', query_string={'merchant': 'SAMPLE'}).get_json()
    assert res['count'] >= 2 and res['total'] > 0
    # nothing changed — still unconfirmed
    queue = client.get('/api/review_queue').get_json()
    assert any('sample' in g['merchant'] for g in queue)


def test_confirm_rejects_unknown_category(client):
    resp = client.post('/api/review_queue/confirm', json={'merchant': 'sample', 'category': 'Nonsense'})
    assert resp.status_code == 400


def test_merge_folds_one_merchant_into_another(client):
    # create two confirmed merchants over the two SAMPLE rows, then merge.
    c1 = client.post('/api/review_queue/confirm', json={'merchant': 'sample restaurant', 'category': 'Food & Drinks'})
    c2 = client.post('/api/review_queue/confirm', json={'merchant': 'sample cafe', 'category': 'Food & Drinks'})
    m1, m2 = c1.get_json()['merchant_id'], c2.get_json()['merchant_id']
    assert m1 and m2 and m1 != m2

    resp = client.post('/api/merchants/merge', json={'from_id': m1, 'into_id': m2})
    assert resp.status_code == 200

    merchants = {m['id'] for m in client.get('/api/merchants').get_json()}
    assert m1 not in merchants and m2 in merchants
    conn = sqlite3.connect(app_module.DB_PATH)
    orphan = conn.execute('SELECT COUNT(*) FROM transactions WHERE merchant_id=?', (m1,)).fetchone()[0]
    conn.close()
    assert orphan == 0  # no transaction still points at the merged-away merchant


def test_new_taxonomy_categories_available(client):
    cats = client.get('/api/categories').get_json()
    for c in ('Rent', 'Wallet/Prepaid Load', 'Government & Taxes', 'Education', 'Jewellery', 'Uncategorized'):
        assert c in cats
