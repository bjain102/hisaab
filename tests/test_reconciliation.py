"""Reconciliation invariants (task 1.4) — the cheap silent-drop checks (F2).

Two invariants over the corpus, plus a self-contained proof the check bites:
  - date-membership: every parsed transaction date falls inside the printed
    statement period (± a small grace for boundary postings). Runs for every
    file that has a period (all of them).
  - totals reconciliation: where a bank prints a debit total that genuinely
    equals the sum of purchases, Σ(parsed debits) must match it. In this corpus
    that is Kotak only (see the per-parser docstrings in pdf_parsers.py — TAD is
    a balance, not a debit checksum, so it is stored informational-only).
"""
from datetime import datetime, timedelta

import pytest

from tests.corpus_loader import (
    CORPUS_DIR, CorpusFileLocked, tier1_entries, load_tier2, parse_corpus_file,
)


def _parse_or_skip(entry):
    try:
        return parse_corpus_file(entry)
    except CorpusFileLocked as e:
        pytest.skip(str(e))

GRACE = timedelta(days=5)  # transactions can post a few days outside the printed cycle


def _all_entries():
    t2, _skipped = load_tier2()
    return list(tier1_entries()) + t2


def _case_id(entry):
    return entry['path'].relative_to(CORPUS_DIR).as_posix()


def _debit_total(transactions):
    return round(sum(t['amount'] for t in transactions if t['type'] == 'debit'), 2)


def _credit_total(transactions):
    return round(sum(t['amount'] for t in transactions if t['type'] == 'credit'), 2)


def _reconciles(transactions, printed_debits):
    return abs(_debit_total(transactions) - printed_debits) < 0.01


# Collection stays lazy on purpose: parametrize over loader entries only and
# parse INSIDE the tests. Parsing at collection time meant one unknown tier1
# bank (a freshly dropped statement format) errored the whole suite instead of
# failing that file's cases — exactly what happened when the Amex PDF landed.
_ENTRIES = _all_entries()


# ── Date-membership ───────────────────────────────────────────────────────────
@pytest.mark.parametrize('entry', _ENTRIES, ids=_case_id)
def test_transaction_dates_within_period(entry):
    result = _parse_or_skip(entry)
    period = result.get('period')
    if not period:
        pytest.skip('no statement period extracted for this file')
    lo = datetime.strptime(period['start'], '%Y-%m-%d').date() - GRACE
    hi = datetime.strptime(period['end'], '%Y-%m-%d').date() + GRACE
    for t in result['transactions']:
        d = datetime.strptime(t['date'], '%Y-%m-%d').date()
        assert lo <= d <= hi, f"{t['date']} outside {period['start']}..{period['end']}"


# ── Totals reconciliation (only where a printed total exists) ─────────────────
@pytest.mark.parametrize('entry', _ENTRIES, ids=_case_id)
def test_parsed_totals_match_printed_totals(entry):
    result = _parse_or_skip(entry)
    totals = result.get('totals') or {}
    if totals.get('debits') is None and totals.get('credits') is None:
        pytest.skip('bank prints no reconcilable total (see parser docstring)')
    if totals.get('debits') is not None:
        assert _debit_total(result['transactions']) == totals['debits']
    if totals.get('credits') is not None:
        assert _credit_total(result['transactions']) == totals['credits']


# ── The check bites (committable, no corpus dependency) ───────────────────────
def test_reconciliation_detects_a_dropped_transaction():
    txns = [
        {'type': 'debit', 'amount': 100.00},
        {'type': 'debit', 'amount': 25.00},
        {'type': 'credit', 'amount': 40.00},
    ]
    printed_debits = 125.00
    assert _reconciles(txns, printed_debits)          # full set reconciles
    assert not _reconciles(txns[:1], printed_debits)  # a dropped debit is caught
