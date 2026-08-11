"""HDFC's OLD statement layout (owner-reported 2026-07-29).

HDFC changed its credit-card statement format at some point in the owner's
history: older statements print bare `dd/mm/yyyy [HH:MM:SS] DESC  1,234.00
[Cr]` rows under a "Domestic Transactions" header, where current ones print
`dd/mm/yyyy| HH:MM  DESC  <glyph> 1,234.00 l`. The parser only knew the
current shape, so importing an older statement returned zero transactions and
the upload route rejected it with "No transactions found."

The optional "HH:MM:SS" was itself a second, follow-up bug: the first fix
(this file's original version) didn't know old-layout rows could carry an
inline time with no separator, so on a Tata Neu old-layout statement the time
was swallowed into the description group whole — "13:47:59 UPI-Indian Oil
Petrol Pump S" as a merchant name, visible in the Transactions table. Not
every row in the same statement carries the time (system-posted rows like
"TELE TRANSFER CREDIT" often don't), so it has to be optional, not assumed
present.

These tests pin the behaviour that fix depends on. The golden-snapshot test
(test_parsers_golden) already pins the exact parse of the corpus file; what's
here is the reasoning the snapshot can't express — that the two layouts don't
poach each other's rows, that the fine print can't be read as transactions,
and that a silent zero-row parse is now a loud one.
"""
from pathlib import Path
import re

import pytest

from pdf_parsers import parse_hdfc_pdf
from tests.corpus_loader import TIER1_DIR, parse_corpus_file

_CORPUS_DIR = Path(__file__).parent / 'corpus' / 'tier1'
# This repository ships no statements (they are real financial documents), so
# every test in this module skips on a fresh clone and comes alive the moment
# you add your own to tests/corpus/tier1/ — see that directory's README.
pytestmark = pytest.mark.skipif(
    not _CORPUS_DIR.is_dir() or not any(f.suffix.lower() in ('.pdf', '.csv') for f in _CORPUS_DIR.glob('*')),
    reason='no local statement corpus — see tests/corpus/tier1/README.md',
)

OLD_FILE = TIER1_DIR / 'HDFC_SWIGGY_OLD_REDACTED.PDF'
# Second old-layout statement, supplied by the owner specifically because the
# first one has no credits (its summary shows Payment/Credits 0.00). This is
# the file that turned the 'Cr' credit marker from an assumption into a
# verified fact — same precedent as the Kotak F7 fix, which also needed a
# second real statement because the corpus had no credit-bearing file.
OLD_FILE_WITH_CREDITS = TIER1_DIR / 'HDFC_SWIGGY_OLD_REDACTED-2.PDF'
# Old-layout Tata Neu statement — the file that exposed the inline-time bug.
# Its rows are a mix: most carry "HH:MM:SS" right after the date with no
# separator, a few (system-posted credits) don't.
OLD_TATANEU_FILE = TIER1_DIR / 'HDFC_TATANEU_OLD_REDACTED.PDF'
CUR_FILE = TIER1_DIR / 'HDFC_SWIGGY_redacted.pdf'


def _entry(path):
    return {'path': path, 'bank': 'hdfc', 'format': 'pdf', 'password': None}


def test_old_layout_parses_every_row():
    """The regression itself: this file used to yield 0 transactions."""
    result = parse_corpus_file(_entry(OLD_FILE))
    txns = result['transactions']
    assert len(txns) == 5
    assert all(t['type'] == 'debit' for t in txns)
    assert [t['date'] for t in txns] == [
        '2025-01-10', '2025-01-12', '2025-01-17', '2025-01-18', '2025-01-18',
    ]
    # Description keeps the gateway prefix verbatim — normalization is the
    # categorization layer's job (ADR-009), never the parser's.
    assert txns[0]['description'] == 'RSP*INSTAMART BANGALORE'


def test_old_layout_debits_reconcile_with_printed_summary():
    """Σ(parsed debits) equals the statement's own Purchase/Debits column.

    Asserted here rather than in test_reconciliation because `totals` is
    deliberately left None for HDFC (see parse_hdfc_pdf's docstring: the
    printed column excludes Finance Charges, which this sample happens to have
    at 0.00 — not enough evidence to promote it to a generic invariant). This
    keeps the one file where the identity is verifiable honest.
    """
    txns = parse_corpus_file(_entry(OLD_FILE))['transactions']
    total = round(sum(t['amount'] for t in txns if t['type'] == 'debit'), 2)
    assert total == 8849.00


def test_current_layout_unaffected_by_the_old_matcher():
    """The old matcher must not steal or duplicate current-format rows."""
    result = parse_corpus_file(_entry(CUR_FILE))
    txns = result['transactions']
    assert len(txns) == 32
    # Both layouts live in the same 'Domestic Transactions' window, so the only
    # thing keeping them apart is the line shape — a current row's '|HH:MM'
    # means the old regex's `date + whitespace` can never match it.
    assert sum(1 for t in txns if t['type'] == 'credit') == 14
    assert sum(1 for t in txns if t['type'] == 'debit') == 18


def test_no_phantom_rows_from_the_legal_fine_print():
    """A bare leading date is only a transaction inside the txn window.

    HDFC's fine print is dense and mentions dates; the old layout has no
    distinctive signature (no pipe, no time), so an unwindowed bare-date match
    is exactly the kind of thing that would invent rows.
    """
    text = '\n'.join([
        'Domestic Transactions',
        'Date Transaction Description Amount (in Rs.)',
        '10/01/2025 REAL MERCHANT BANGALORE 291.00',
        'Important Information',
        # Shaped exactly like a transaction, but after the window closes.
        '01/08/2024 REVISION OF CHARGES ON YOUR CARD 9.00',
    ])
    txns = parse_hdfc_pdf(text)['transactions']
    assert [t['description'] for t in txns] == ['REAL MERCHANT BANGALORE']


def test_old_layout_credit_suffix_is_recognized():
    """'Cr' after the amount marks a credit — verified against a real file.

    Note the marker is GLUED to the amount with no separating space
    ("879.90Cr"), which is why the parser's amount/suffix boundary can't
    assume whitespace there.
    """
    txns = parse_corpus_file(_entry(OLD_FILE_WITH_CREDITS))['transactions']
    assert len(txns) == 5
    by_type = [(t['type'], t['amount']) for t in txns]
    assert by_type == [
        ('credit', 879.90),   # 10% Swiggy Cashback
        ('debit', 164.00),
        ('credit', 8849.00),  # TELE TRANSFER CREDIT — the bill payment
        ('debit', 539.00),
        ('debit', 268.00),
    ]


def test_old_layout_strips_inline_time_from_description():
    """The regression itself: HH:MM:SS must not end up in the description.

    Owner-reported via a screenshot of the Transactions table showing rows
    like "13:47:59 UPI-Indian Oil Petrol Pump S" as the merchant name — the
    parser worked (22/22 rows imported) but every timed row's description
    carried its own posting time as a prefix.
    """
    result = parse_corpus_file(_entry(OLD_TATANEU_FILE))
    txns = result['transactions']
    assert len(txns) == 22
    time_re = re.compile(r'^\d{2}:\d{2}:\d{2}\b')
    leaked = [t['description'] for t in txns if time_re.match(t['description'])]
    assert leaked == [], f'time leaked into description: {leaked}'
    # Spot-check the exact row from the owner's screenshot.
    feb1 = next(t for t in txns if t['date'] == '2025-02-01')
    assert feb1['description'] == 'UPI-Indian Oil Petrol Pump S'


def test_old_layout_handles_rows_with_and_without_a_time_in_one_statement():
    """Not every row carries the time — it must be optional, not assumed.

    On the real Tata Neu file, ordinary UPI debits carry "HH:MM:SS" and the
    system-posted "TELE TRANSFER CREDIT" / "UPI CC-..." rows don't. A fix that
    hardcoded the time as required would silently drop those rows instead of
    fixing their description.
    """
    txns = parse_corpus_file(_entry(OLD_TATANEU_FILE))['transactions']
    timed = next(t for t in txns if t['description'] == 'UPI-Jai Hanuman Stationery'
                 and t['amount'] == 10.00)
    untimed = next(t for t in txns if 'TELE TRANSFER CREDIT' in t['description'])
    assert timed['date'] == '2025-01-02'
    assert untimed['date'] == '2025-01-06' and untimed['type'] == 'credit'


def test_old_layout_tataneu_debits_reconcile_with_printed_summary():
    """Cross-check against a SECOND card's Account Summary, not just Swiggy's.

    Guards against a fix that happens to work for one card's line shapes but
    not another's — Tata Neu's old-layout rows are a mix of timed/untimed in
    a way the Swiggy sample never exercised.
    """
    txns = parse_corpus_file(_entry(OLD_TATANEU_FILE))['transactions']
    total = round(sum(t['amount'] for t in txns if t['type'] == 'debit'), 2)
    assert total == 5772.98


def test_emi_badge_is_not_part_of_the_description():
    """'EMI' between the time and the merchant is a BUTTON, not a merchant.

    Owner-reported from the statement PDF itself: HDFC draws a tappable
    "convert to EMI" badge on eligible rows (the document's own legend reads
    "Eligible for EMI CONVERT TO EMI"), and pdfplumber extracts that badge
    label as a plain text token. It was landing in the stored description —
    "EMI MOKSHA DENTAL CLINICBANGALORE" — which also splits one merchant into
    two for categorization purposes, since the EMI-converted rows normalize
    differently from the same merchant's ordinary rows.
    """
    rows = [
        # (line, expected description)
        ('01/05/2026| 14:48 EMI COAL SPARK MULTI CUISINBANGALORE + 70 C 4,659.00 l',
         'COAL SPARK MULTI CUISINBANGALORE'),
        ('24/05/2026| 20:08 EMI UPI-GLOBUS DESIGN C 2,573.00 l',
         'UPI-GLOBUS DESIGN'),
    ]
    for line, expected in rows:
        txns = parse_hdfc_pdf('DATE & TIME\n' + line)['transactions']
        assert txns[0]['description'] == expected


def test_merchant_beginning_with_emi_is_not_truncated():
    """Bare-token match, not a prefix test — EMIRATES keeps its name.

    The reason the strip is `tokens[0] == 'EMI'` and not a startswith: a
    prefix test would silently eat four characters off any merchant whose
    name begins with those letters, and that corruption would look exactly
    like a bank formatting quirk rather than a bug.
    """
    line = '03/05/2026| 22:44 EMIRATES AIRLINE DUBAI C 105.00 l'
    txns = parse_hdfc_pdf('DATE & TIME\n' + line)['transactions']
    assert txns[0]['description'] == 'EMIRATES AIRLINE DUBAI'


def test_emi_strip_does_not_disturb_credit_detection():
    """The EMI token sits at the START; credit markers sit at the END.

    Guards the ordering of the two strips — popping from the front must not
    shift what the trailing '+'/glyph logic sees.
    """
    line = '05/05/2026| 00:00 EMI 5% Swiggy Cashback + C 5.25 l'
    txn = parse_hdfc_pdf('DATE & TIME\n' + line)['transactions'][0]
    assert txn['type'] == 'credit'
    assert txn['description'] == '5% Swiggy Cashback'


def test_old_layout_bill_payment_is_not_counted_as_a_refund():
    """The bill payment must categorize as Credit Card Bills, not Others.

    /api/summary subtracts non-cashback credits from spend UNLESS they're
    categorized 'Credit Card Bills'. HDFC's old layout calls that payment
    "TELE TRANSFER CREDIT" (the current layout says "BPPY CC PAYMENT"), so
    before this was mapped it fell to "Others" and silently understated net
    spend by the entire bill — ₹8,849 on this statement alone.

    The review queue could never have surfaced it either: the queue lists
    debits, and this is a credit. Nothing would have prompted a correction.
    """
    import app as app_module
    assert app_module.categorize('TELE TRANSFER CREDIT (Ref# ST250300083000010151846)') \
        == 'Credit Card Bills'
    # The cashback credit stays a real cashback (excluded from spend by the
    # is_cashback flag, not by category).
    assert app_module.is_cashback('10% Swiggy Cashback (Ref# ST250210084000010950183)')


def test_cr_suffix_only_counts_after_the_amount():
    """A merchant whose name merely contains "CR" is not a credit."""
    text = '\n'.join([
        'Domestic Transactions',
        'Date Transaction Description Amount (in Rs.)',
        '05/01/2025 SOME MERCHANT CR 5,000.00',
        'Important Information',
    ])
    assert parse_hdfc_pdf(text)['transactions'][0]['type'] == 'debit'


@pytest.mark.parametrize('layout,sample', [
    ('current', '03/05/2026| 22:44 PTM*FLIPKART MBanglore C 105.00 l'),
    ('old, no time', '10/01/2025 RSP*INSTAMART BANGALORE 291.00'),
    ('old, with time', '02/01/2025 22:22:49 UPI-Jai Hanuman Stationery 10.00'),
])
def test_layouts_are_mutually_exclusive_by_line_shape(layout, sample):
    """Neither layout's regex may match the other's rows.

    This is what lets both matchers run in one pass instead of the parser
    guessing a mode per document — and it's what would break first if HDFC
    revised either shape. Imported from pdf_parsers rather than redefined
    here so this test can't quietly drift from the real regex.
    """
    from pdf_parsers import _HDFC_CUR_PREFIX_RE, _HDFC_OLD_TXN_RE
    if layout == 'current':
        assert _HDFC_CUR_PREFIX_RE.match(sample) and not _HDFC_OLD_TXN_RE.match(sample)
    else:
        assert _HDFC_OLD_TXN_RE.match(sample) and not _HDFC_CUR_PREFIX_RE.match(sample)


def test_old_layout_imports_end_to_end(client):
    """The owner-facing symptom: /api/upload used to 400 on this file.

    Parsing correctly is necessary but not sufficient — the route also has to
    survive the old layout printing no billing period. It does, via the
    documented txn-span fallback, which matters because that period is what
    dedup gating compares against.
    """
    with open(OLD_FILE, 'rb') as f:
        resp = client.post(
            '/api/upload',
            data={'file': (f, OLD_FILE.name), 'card': 'hdfc',
                  'card_label': 'HDFC-SWIGGY-0001', 'password': ''},
            content_type='multipart/form-data',
        )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body['imported'] == 5
    # No printed cycle in this layout — the route falls back to the span of the
    # transaction dates rather than skipping the dedup check entirely.
    assert body['period'] == {'start': '2025-01-10', 'end': '2025-01-18'}


def test_zero_row_parse_now_surfaces_as_skipped_candidates():
    """F2's safety net covers the old layout too.

    The original bug was silent precisely because the skipped-candidate anchor
    required the pipe+time signature: an old statement parsed to 0 rows AND 0
    candidates, so nothing reported a problem. Simulate a future old-layout
    revision the row matcher can't read (an amount format it doesn't know) and
    assert the count is non-zero.
    """
    text = '\n'.join([
        'Domestic Transactions',
        'Date Transaction Description Amount (in Rs.)',
        '10/01/2025 SOME MERCHANT BANGALORE 291.00.00.00',
        'Important Information',
    ])
    result = parse_hdfc_pdf(text)
    assert result['transactions'] == []
    assert result['skipped_candidates'] == 1
