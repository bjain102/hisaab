"""Task 2.3: /api/upload gains additive period/totals/reconciled fields so the
Import view can show a reconciliation line. Exercises the real endpoint end
to end against tier1 corpus files (committed, safe) — the first tests to
actually POST to /api/upload."""
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


def upload(client, path, card, card_label, password=''):
    with open(path, 'rb') as f:
        return client.post(
            '/api/upload',
            data={'file': (f, path.name), 'card': card, 'card_label': card_label, 'password': password},
            content_type='multipart/form-data',
        )


def test_upload_csv_has_derived_period_but_null_totals(client):
    """CSVs carry no printed cycle, but task 3.4 derives one from the
    transaction dates' own span so dedup gating always has a period to work
    with — period is therefore never null post-3.4. totals/reconciled stay
    null: CSVs carry no printed totals to reconcile against, and that
    honesty is unaffected by the gating change."""
    resp = upload(client, CORPUS_TIER1 / 'AMEX_MRCC_synthetic.csv', 'amex', 'AMEX-TEST')
    data = resp.get_json()
    assert resp.status_code == 200
    assert data['period'] == {'start': '2026-01-15', 'end': '2026-03-08'}
    assert data['totals'] is None
    assert data['reconciled'] is None


def test_upload_pdf_reconciles_when_bank_prints_a_matching_total(client):
    """Kotak prints a Total Purchases line that matches Σ(parsed debits) —
    the one bank in the corpus with a genuinely checkable total."""
    resp = upload(client, CORPUS_TIER1 / 'KOTAK_ZEN_redacted.pdf', 'kotak', 'KOTAK-TEST')
    data = resp.get_json()
    assert resp.status_code == 200
    assert data['period'] is not None
    assert data['totals']['debits'] is not None
    assert data['reconciled'] is True


def test_upload_pdf_reconciled_null_when_bank_prints_no_checkable_total(client):
    """IDFC prints a Total Amount Due (a balance, not Sigma-debits — see
    pdf_parsers.py) so there's nothing to reconcile against; must be null,
    never a false pass or fail."""
    resp = upload(client, CORPUS_TIER1 / 'IDFC_WOW_redacted.pdf', 'idfc', 'IDFC-TEST')
    data = resp.get_json()
    assert resp.status_code == 200
    assert data['period'] is not None
    assert data['totals']['debits'] is None
    assert data['reconciled'] is None


def test_upload_response_shape_is_additive(client):
    """Every existing field the legacy UI reads is still there, unchanged."""
    resp = upload(client, CORPUS_TIER1 / 'KOTAK_ZEN_redacted.pdf', 'kotak', 'KOTAK-TEST2')
    data = resp.get_json()
    for key in ('success', 'imported', 'card', 'skipped_candidates'):
        assert key in data, key
