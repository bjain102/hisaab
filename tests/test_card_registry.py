"""Task 3.7 (app-side): /api/card_profiles is now backed by `accounts`
directly (card_profiles table is gone). Same request/response wire shape as
before — bank/variant/last4/label — so this only exercises the new backing
logic: variant derivation, rename-in-place on (bank, last4) match, and the
delete-blocked-when-has-transactions guard.
"""
import pytest
from pathlib import Path

_CORPUS_DIR = Path(__file__).parent / 'corpus' / 'tier1'
# This repository ships no statements (they are real financial documents), so
# every test in this module skips on a fresh clone and comes alive the moment
# you add your own to tests/corpus/tier1/ — see that directory's README.
pytestmark = pytest.mark.skipif(
    not _CORPUS_DIR.is_dir() or not any(f.suffix.lower() in ('.pdf', '.csv') for f in _CORPUS_DIR.glob('*')),
    reason='no local statement corpus — see tests/corpus/tier1/README.md',
)

CORPUS_TIER1 = Path(__file__).parent / 'corpus' / 'tier1'


def test_add_card_creates_an_account(client):
    resp = client.post('/api/card_profiles', json={'bank': 'hdfc', 'variant': 'Millennia', 'last4': '2222'})
    assert resp.status_code == 200
    assert resp.get_json()['label'] == 'HDFC-Millennia-2222'

    profiles = client.get('/api/card_profiles').get_json()
    row = next(p for p in profiles if p['label'] == 'HDFC-Millennia-2222')
    assert row['bank'] == 'hdfc'
    assert row['variant'] == 'Millennia'
    assert row['last4'] == '2222'


def test_variant_derived_correctly_for_multiword_variant(client):
    client.post('/api/card_profiles', json={'bank': 'hdfc', 'variant': 'Tata Neu Infinity', 'last4': '1234'})
    profiles = client.get('/api/card_profiles').get_json()
    row = next(p for p in profiles if p['last4'] == '1234')
    assert row['variant'] == 'Tata Neu Infinity'
    assert row['label'] == 'HDFC-Tata Neu Infinity-1234'


def test_same_bank_and_last4_renames_instead_of_duplicating(client):
    """Re-submitting the same (bank, last4) with a corrected variant edits
    the existing account in place — everything else references it by id, so
    this is safe (no card_profiles UNIQUE(bank,last4) to lean on anymore)."""
    client.post('/api/card_profiles', json={'bank': 'axis', 'variant': 'Mzone', 'last4': '5555'})
    before = client.get('/api/card_profiles').get_json()
    n_before = len(before)

    resp = client.post('/api/card_profiles', json={'bank': 'axis', 'variant': 'MyZone', 'last4': '5555'})
    assert resp.status_code == 200
    assert resp.get_json()['label'] == 'AXIS-MyZone-5555'

    after = client.get('/api/card_profiles').get_json()
    assert len(after) == n_before  # renamed, not duplicated
    assert any(p['label'] == 'AXIS-MyZone-5555' for p in after)
    assert not any(p['label'] == 'AXIS-Mzone-5555' for p in after)


def test_delete_unused_card_succeeds(client):
    client.post('/api/card_profiles', json={'bank': 'idfc', 'variant': 'Select', 'last4': '3333'})
    profiles = client.get('/api/card_profiles').get_json()
    pid = next(p['id'] for p in profiles if p['label'] == 'IDFC-Select-3333')

    resp = client.delete(f'/api/card_profiles/{pid}')
    assert resp.status_code == 200
    after = client.get('/api/card_profiles').get_json()
    assert not any(p['id'] == pid for p in after)


def test_delete_blocked_when_card_has_transactions(client):
    with open(CORPUS_TIER1 / 'KOTAK_ZEN_redacted.pdf', 'rb') as f:
        client.post('/api/upload', data={
            'file': (f, 'KOTAK_ZEN_redacted.pdf'), 'card': 'kotak',
            'card_label': 'KOTAK-INUSE-4444', 'password': '',
        }, content_type='multipart/form-data')

    profiles = client.get('/api/card_profiles').get_json()
    pid = next(p['id'] for p in profiles if p['label'] == 'KOTAK-INUSE-4444')

    resp = client.delete(f'/api/card_profiles/{pid}')
    assert resp.status_code == 400
    assert 'transaction' in resp.get_json()['error'].lower()

    after = client.get('/api/card_profiles').get_json()
    assert any(p['id'] == pid for p in after)  # still there
