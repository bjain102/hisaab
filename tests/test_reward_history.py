"""Task 3.5 (app-side half): dated reward-balance history (fixes F5).

Exercises /api/upload's reward-write, and the reworked /api/rewards (now
"current balance" = latest as_of, not latest insert) + new
/api/rewards/history, against real tier1 corpus files.
"""
import pytest
import sqlite3
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


def upload(client, path, card, card_label, force=False):
    with open(path, 'rb') as f:
        data = {'file': (f, path.name), 'card': card, 'card_label': card_label, 'password': ''}
        if force:
            data['force'] = 'true'
        return client.post('/api/upload', data=data, content_type='multipart/form-data')


def test_upload_writes_a_dated_reward_balance(client):
    resp = upload(client, CORPUS_TIER1 / 'HDFC_TATANEU_redacted.pdf', 'hdfc', 'HDFC-TEST')
    assert resp.status_code == 200

    rewards = client.get('/api/rewards').get_json()
    row = next(r for r in rewards if r['card_label'] == 'HDFC-TEST')
    assert row['label'] == 'NeuCoins'
    assert row['value'] == 202
    assert row['value_type'] == 'points'
    assert row['source'] == 'statement'
    assert row['as_of'] == '2026-06-01'  # the statement's own period_end


def test_cashback_inr_stored_and_wired_as_paise(client):
    """DB + API wire carry paise (matching v2's boundary-discipline pattern) —
    the frontend client.ts converts to rupees once at the fetch boundary, so
    the wire value here is intentionally x100 of the printed rupee amount."""
    resp = upload(client, CORPUS_TIER1 / 'HDFC_SWIGGY_redacted.pdf', 'hdfc', 'HDFC-CASHBACK')
    assert resp.status_code == 200

    rewards = client.get('/api/rewards').get_json()
    row = next(r for r in rewards if r['card_label'] == 'HDFC-CASHBACK')
    assert row['value_type'] == 'cashback_inr'
    assert row['value'] == 37966  # paise: 379.66 -> 37966


def test_out_of_order_import_does_not_regress_current_balance(client):
    """The exact F5 scenario: import the NEWER statement first, then an
    OLDER one for the same card (periods overlap between these two real
    files, so the older import needs force=true — the overlap check and the
    reward-history check are independent concerns). Current balance must
    stay the newer statement's value."""
    newer = upload(client, CORPUS_TIER1 / 'Axis_MYZONE_redacted.pdf', 'axis', 'AXIS-TEST')
    assert newer.status_code == 200
    assert newer.get_json()['period']['end'] == '2026-06-01'

    older = upload(client, CORPUS_TIER1 / 'AXIS_REWARDS_redacted.pdf', 'axis', 'AXIS-TEST', force=True)
    assert older.status_code == 200
    assert older.get_json()['period']['end'] == '2026-04-01'

    rewards = client.get('/api/rewards').get_json()
    row = next(r for r in rewards if r['card_label'] == 'AXIS-TEST')
    assert row['value'] == 7652  # the NEWER statement's points, not the last-imported one
    assert row['as_of'] == '2026-06-01'

    history = client.get('/api/rewards/history?card_label=AXIS-TEST').get_json()
    assert [h['as_of'] for h in history] == ['2026-04-01', '2026-06-01']
    assert [h['value'] for h in history] == [7628, 7652]


def test_manual_entry_upserts_for_existing_card(client):
    upload(client, CORPUS_TIER1 / 'HDFC_TATANEU_redacted.pdf', 'hdfc', 'HDFC-MANUAL')

    resp = client.post('/api/rewards', json={
        'card_label': 'HDFC-MANUAL', 'label': 'Manual Correction',
        'value': 500, 'value_type': 'points',
    })
    assert resp.status_code == 200

    rewards = client.get('/api/rewards').get_json()
    row = next(r for r in rewards if r['card_label'] == 'HDFC-MANUAL')
    # manual entry is as_of TODAY, which is >= the statement's period_end, so
    # it becomes (or ties as) the current row.
    assert row['label'] == 'Manual Correction'
    assert row['value'] == 500
    assert row['source'] == 'manual'


def test_manual_entry_rejects_unknown_card(client):
    resp = client.post('/api/rewards', json={
        'card_label': 'NO-SUCH-CARD', 'label': 'Points', 'value': 100, 'value_type': 'points',
    })
    assert resp.status_code == 400
    assert 'Unknown card' in resp.get_json()['error']
