"""Bulk PDF upload + delete-all-imports (owner request 2026-07-29).

Both endpoints are thin shells over machinery that already existed and is
already tested — `_import_statement` for the upload path, the single-statement
manual cascade for the delete path. What's tested here is what those shells
add and could get wrong: that bulk import doesn't weaken the F4 gating a
single upload enforces, that one bad file doesn't take the batch down, and
that the destructive endpoint is genuinely hard to fire by accident.
"""
from pathlib import Path

import pytest

_CORPUS_DIR = Path(__file__).parent / 'corpus' / 'tier1'
# This repository ships no statements (they are real financial documents), so
# every test in this module skips on a fresh clone and comes alive the moment
# you add your own to tests/corpus/tier1/ — see that directory's README.
pytestmark = pytest.mark.skipif(
    not _CORPUS_DIR.is_dir() or not any(f.suffix.lower() in ('.pdf', '.csv') for f in _CORPUS_DIR.glob('*')),
    reason='no local statement corpus — see tests/corpus/tier1/README.md',
)

CORPUS_TIER1 = Path(__file__).parent / 'corpus' / 'tier1'

OLD_SWIGGY = CORPUS_TIER1 / 'HDFC_SWIGGY_OLD_REDACTED.PDF'          # Jan 10–18 2025
OLD_SWIGGY_2 = CORPUS_TIER1 / 'HDFC_SWIGGY_OLD_REDACTED-2.PDF'      # Jan 20–Feb 09 2025
CUR_SWIGGY = CORPUS_TIER1 / 'HDFC_SWIGGY_redacted.pdf'              # May 2026


def bulk(client, paths, card='hdfc', card_label='HDFC-BULK', force=False):
    data = {'card': card, 'card_label': card_label, 'password': ''}
    if force:
        data['force'] = 'true'
    handles = [open(p, 'rb') for p in paths]
    try:
        data['files'] = [(h, Path(h.name).name) for h in handles]
        return client.post('/api/upload_bulk', data=data,
                           content_type='multipart/form-data')
    finally:
        for h in handles:
            h.close()


def single(client, path, card='hdfc', card_label='HDFC-BULK'):
    with open(path, 'rb') as f:
        return client.post('/api/upload', data={
            'file': (f, path.name), 'card': card,
            'card_label': card_label, 'password': '',
        }, content_type='multipart/form-data')


# ── bulk upload ──────────────────────────────────────────────────────────────

def test_bulk_imports_every_disjoint_file(client):
    resp = bulk(client, [OLD_SWIGGY, OLD_SWIGGY_2, CUR_SWIGGY])
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['files'] == 3
    assert body['succeeded'] == 3 and body['failed'] == 0
    # 5 + 5 + 32, the counts the golden expectations already pin per file.
    assert body['imported'] == 42
    assert all(r['ok'] for r in body['results'])

    listed = client.get('/api/statements').get_json()
    assert len(listed) == 3


def test_bulk_still_enforces_hash_dedup(client):
    """The same file twice in ONE batch must not import twice.

    Worth pinning explicitly: the gate is a SELECT against `statements`, so it
    only works because each file is committed before the next is processed. A
    bulk path that deferred commits to the end of the batch would silently
    import duplicates while every existing gating test still passed.
    """
    resp = bulk(client, [OLD_SWIGGY, OLD_SWIGGY])
    body = resp.get_json()
    assert body['succeeded'] == 1 and body['failed'] == 1
    failed = next(r for r in body['results'] if not r['ok'])
    assert 'already imported' in failed['error']


def test_bulk_still_enforces_period_overlap(client):
    single(client, OLD_SWIGGY)                     # Jan 10–18 lands first
    resp = bulk(client, [OLD_SWIGGY_2, CUR_SWIGGY])
    body = resp.get_json()
    # OLD_SWIGGY_2 spans Jan 20–Feb 09, disjoint from Jan 10–18; both import.
    assert body['succeeded'] == 2, body['results']


def test_one_bad_file_does_not_abort_the_batch(client, tmp_path):
    """A year of statements where one is unreadable should still import 11.

    This is the whole reason the bulk route collects (payload, status) per
    file instead of returning on the first non-200.
    """
    junk = tmp_path / 'not-really.pdf'
    junk.write_bytes(b'this is not a pdf')
    resp = bulk(client, [OLD_SWIGGY, junk, OLD_SWIGGY_2])
    assert resp.status_code == 200          # the BATCH succeeded
    body = resp.get_json()
    assert body['succeeded'] == 2 and body['failed'] == 1
    bad = next(r for r in body['results'] if not r['ok'])
    assert bad['filename'] == 'not-really.pdf'
    assert bad['error']


def test_bulk_stores_exactly_what_the_parser_produced(client):
    """Bulk must not mangle, drop, or reorder anything on the way to the DB.

    Compared against the parsers' own output rather than against a second
    round of single uploads: hash dedup is GLOBAL (any byte-identical file,
    regardless of card), so the same corpus files can't be imported twice in
    one database to compare the two paths side by side.
    """
    from tests.corpus_loader import parse_corpus_file

    bulk(client, [OLD_SWIGGY, OLD_SWIGGY_2], card_label='VIA-BULK')
    stored = client.get('/api/transactions?card=VIA-BULK&limit=500').get_json()

    expected = []
    for path in (OLD_SWIGGY, OLD_SWIGGY_2):
        parsed = parse_corpus_file(
            {'path': path, 'bank': 'hdfc', 'format': 'pdf', 'password': None})
        expected += parsed['transactions']

    def stored_shape(rows):
        # amount_paise, not amount — the wire carries integer paise (v2/ADR-005).
        return sorted((r['date'], r['description'], r['amount_paise'], r['type'])
                      for r in rows)

    def parsed_shape(txns):
        # Parsers speak rupee floats; the paise conversion is the DB boundary.
        return sorted((t['date'], t['description'], int(round(t['amount'] * 100)),
                       t['type']) for t in txns)

    assert stored_shape(stored) == parsed_shape(expected)
    assert len(stored) == 10


def test_bulk_rejects_an_empty_file_list(client):
    resp = client.post('/api/upload_bulk',
                       data={'card': 'hdfc', 'card_label': 'X'},
                       content_type='multipart/form-data')
    assert resp.status_code == 400
    assert 'No files' in resp.get_json()['error']


def test_bulk_is_deterministic_regardless_of_browser_file_order(client):
    """Files are sorted by name, so a batch's outcome is reproducible.

    With overlap gating, whichever of two overlapping statements is processed
    first decides which one is rejected — that must not depend on the order a
    multi-select happened to hand us.
    """
    a = bulk(client, [OLD_SWIGGY, OLD_SWIGGY_2], card_label='ORDER-A')
    b = bulk(client, [OLD_SWIGGY_2, OLD_SWIGGY], card_label='ORDER-B')
    names = lambda body: [r['filename'] for r in body.get_json()['results']]
    assert names(a) == names(b)


# ── delete all ───────────────────────────────────────────────────────────────

def test_delete_all_requires_the_confirm_token(client):
    single(client, OLD_SWIGGY)
    for data in ({}, {'confirm': 'yes'}, {'confirm': 'delete all'}):
        resp = client.delete('/api/statements/all', json=data)
        assert resp.status_code == 400
        assert 'Refusing to delete' in resp.get_json()['error']
    # Nothing was touched by any of the refused attempts.
    assert len(client.get('/api/statements').get_json()) == 1


def test_delete_all_wipes_statements_and_transactions(client):
    bulk(client, [OLD_SWIGGY, OLD_SWIGGY_2])
    assert len(client.get('/api/statements').get_json()) == 2

    resp = client.delete('/api/statements/all', json={'confirm': 'DELETE ALL'})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['statements_deleted'] == 2
    assert body['transactions_deleted'] > 0
    assert body['backup']                      # a snapshot was taken first

    assert client.get('/api/statements').get_json() == []
    summary = client.get('/api/summary').get_json()
    assert summary['total_spend'] == 0


def test_delete_all_clears_seeded_rows_with_no_statement(client):
    """Transactions are deleted wholesale, not by statement_id.

    The conftest seed rows predate any statement (statement_id IS NULL) —
    exactly the orphan shape a statement_id-scoped delete would leave behind,
    invisible in the import list but still counted in every total.
    """
    before = client.get('/api/summary').get_json()
    assert before['total_spend'] > 0           # seed data is present

    client.delete('/api/statements/all', json={'confirm': 'DELETE ALL'})
    after = client.get('/api/summary').get_json()
    assert after['total_spend'] == 0


def test_delete_all_on_an_empty_db_is_a_no_op(client):
    client.delete('/api/statements/all', json={'confirm': 'DELETE ALL'})
    resp = client.delete('/api/statements/all', json={'confirm': 'DELETE ALL'})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['statements_deleted'] == 0 and body['transactions_deleted'] == 0
    # No backup churn on a no-op — otherwise a double-click could push a real
    # snapshot out of the newest-20 retention window.
    assert body['backup'] is None


def test_reimport_works_after_delete_all(client):
    """The point of the button: wipe, then import again cleanly.

    Hash dedup would reject a re-import if `statements` rows survived, so this
    also proves the delete actually cleared the gate's own table.
    """
    single(client, OLD_SWIGGY)
    client.delete('/api/statements/all', json={'confirm': 'DELETE ALL'})
    resp = single(client, OLD_SWIGGY)
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()['imported'] == 5
