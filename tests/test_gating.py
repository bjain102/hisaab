"""Task 3.4 (app-side half): statement-period gating + SHA-256 dedup on
/api/upload. Exercises the real endpoint against real tier1 corpus files —
same pattern as test_upload_reconciliation.py.
"""
import pytest
import os
import sqlite3
from io import BytesIO
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


def upload_bytes(client, data_bytes, card_label, force=False):
    form = {'card': 'kotak', 'card_label': card_label, 'password': ''}
    if force:
        form['force'] = 'true'
    return client.post(
        '/api/upload',
        data={**form, 'file': (BytesIO(data_bytes), 'kotak.pdf')},
        content_type='multipart/form-data',
    )


def test_same_file_twice_is_rejected_by_hash(client):
    first = upload(client, CORPUS_TIER1 / 'KOTAK_ZEN_redacted.pdf', 'kotak', 'KOTAK-A')
    assert first.status_code == 200

    second = upload(client, CORPUS_TIER1 / 'KOTAK_ZEN_redacted.pdf', 'kotak', 'KOTAK-A')
    assert second.status_code == 400
    body = second.get_json()
    assert 'already imported' in body['error']
    assert 'overlap' not in body  # distinct from a period-overlap rejection


def test_same_file_twice_rejected_even_with_force(client):
    """force=true bypasses period-OVERLAP rejection, not the hash check —
    an identical file is identical regardless of intent."""
    upload(client, CORPUS_TIER1 / 'KOTAK_ZEN_redacted.pdf', 'kotak', 'KOTAK-A')
    resp = upload(client, CORPUS_TIER1 / 'KOTAK_ZEN_redacted.pdf', 'kotak', 'KOTAK-A', force=True)
    assert resp.status_code == 400
    assert 'already imported' in resp.get_json()['error']


def test_overlapping_period_different_file_is_rejected_then_force_succeeds(client):
    """Same printed cycle, different bytes (a trailing byte appended, which
    pdfplumber ignores when extracting text — the parsed period is
    identical) must be REJECTED without force and ACCEPTED with it. This is
    exactly the case that ruled out a DB-level UNIQUE(account, period) —
    see migrations/m003_statements.py and the ADR-003 correction."""
    original = (CORPUS_TIER1 / 'KOTAK_ZEN_redacted.pdf').read_bytes()
    tampered = original + b'\n'

    first = upload_bytes(client, original, 'KOTAK-B')
    assert first.status_code == 200

    rejected = upload_bytes(client, tampered, 'KOTAK-B')
    assert rejected.status_code == 400
    body = rejected.get_json()
    assert body.get('overlap') is True
    assert 'overlaps' in body['error']

    forced = upload_bytes(client, tampered, 'KOTAK-B', force=True)
    assert forced.status_code == 200


def test_disjoint_period_imports_cleanly_without_force(client):
    first = upload(client, CORPUS_TIER1 / 'KOTAK_ZEN_redacted.pdf', 'kotak', 'KOTAK-C')       # Mar-Apr
    second = upload(client, CORPUS_TIER1 / 'KOTAK_ZEN_redacted-2.pdf', 'kotak', 'KOTAK-C')    # Apr-May
    assert first.status_code == 200
    assert second.status_code == 200
    assert 'overlap' not in second.get_json()


def test_gated_import_persists_the_file_and_statement_row(client):
    resp = upload(client, CORPUS_TIER1 / 'KOTAK_ZEN_redacted.pdf', 'kotak', 'KOTAK-D')
    assert resp.status_code == 200

    conn = sqlite3.connect(app_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    stmt = conn.execute("SELECT * FROM statements WHERE account_id = "
                        "(SELECT id FROM accounts WHERE name='KOTAK-D')").fetchone()
    conn.close()
    assert stmt is not None
    assert stmt['file_sha256'] is not None
    assert stmt['source_path'] and os.path.isfile(stmt['source_path'])
    assert stmt['stmt_debits_paise'] == 112500  # Kotak reconciles: ₹1,125.00 -> 112500 paise
