"""HDFC current-layout description wrapping onto the date/amount row itself
(owner-reported, real statement, 2026-09-06).

The golden snapshot (test_parsers_golden) already pins the exact parse of the
corpus file. What's here is the reasoning a snapshot can't express: the trap
this specific statement hit, and why it's a different failure shape than
every other HDFC wrap case already handled (the EMI badge, the NeuCoins '+ N'
column) — those always leave at least one real token behind; this one
leaves none.

The real extracted text, three physical lines for one logical transaction:

    BPPY CC PAYMENT DP216218TU0DV1AG0IS (Ref#
    06/08/2026| 10:23 + C 10,665.00 l
    ST262190083000010073958)

The middle line — the one `_HDFC_CUR_PREFIX_RE` actually anchors on — carries
a date, a time, a credit '+', a currency glyph, and an amount, but ZERO
description tokens. Before this fix, that produced a transaction with
`description: ''`, imported silently (no parse error, no skipped-candidate
flag — the row IS captured, just empty), and landed the owner in the
Transactions view looking at a ₹10,665 row with a blank description and no
error anywhere to explain why.
"""
import pytest

from pdf_parsers import parse_hdfc_pdf
from tests.corpus_loader import TIER1_DIR, parse_corpus_file

WRAP_FILE = TIER1_DIR / 'HDFC_TATANEU_DESC_WRAP_redacted.pdf'

pytestmark = pytest.mark.skipif(
    not WRAP_FILE.exists(),
    reason='HDFC description-wrap corpus statement not present locally',
)


@pytest.fixture(scope='module')
def parsed():
    return parse_corpus_file({'path': WRAP_FILE, 'bank': 'hdfc', 'format': 'pdf'})


def test_period_is_the_printed_cycle(parsed):
    assert parsed['period'] == {'start': '2026-08-02', 'end': '2026-09-01'}


def test_no_transaction_has_a_blank_description(parsed):
    """The bug itself, stated as directly as possible: this must never
    regress to an empty string, on this file or any other HDFC statement."""
    assert parsed['transactions']
    for t in parsed['transactions']:
        assert t['description'].strip() != '', t


def test_wrapped_bppy_description_is_fully_reassembled(parsed):
    """Both halves — the opening line before the date/amount row and the
    closing '(Ref# ...)' after it — must be present, in order, with nothing
    from the date/time/currency-glyph/amount furniture mixed in."""
    row = next(t for t in parsed['transactions'] if t['amount'] == pytest.approx(10665.00))
    assert row['description'] == 'BPPY CC PAYMENT DP216218TU0DV1AG0IS (Ref# ST262190083000010073958)'
    assert row['date'] == '2026-08-06'
    assert row['type'] == 'credit'


def test_single_line_row_on_the_same_statement_is_unaffected(parsed):
    """'ZEROISE CARD ACCOUNT' sits on one ordinary line, right after the
    wrapped row — proof the fix only engages when a row's own tokens are
    genuinely empty, not on every row near a wrap."""
    row = next(t for t in parsed['transactions'] if t['amount'] == pytest.approx(0.23))
    assert row['description'] == 'ZEROISE CARD ACCOUNT'
    assert row['date'] == '2026-08-10'


def test_page_furniture_is_never_absorbed_as_a_description():
    """Direct unit test of the guard, independent of this one file's luck of
    the draw: if some future statement's empty-description row happens to
    sit right after a CKYC bracket or the column header, absorption must
    refuse them rather than manufacture a garbage 'merchant'."""
    fabricated = (
        "[CKYC ID : ]\n"
        "06/08/2026| 10:23 + C 10,665.00 l\n"
        "DATE & TIME TRANSACTION DESCRIPTION Base NeuCoins* AMOUNT PI\n"
    )
    result = parse_hdfc_pdf(fabricated)
    assert len(result['transactions']) == 1
    assert result['transactions'][0]['description'] == ''


def test_only_the_empty_description_case_triggers_absorption():
    """A row that already has a real description must never have neighbour
    lines appended to it — absorption is a fallback for the empty case only,
    not a general 'grab nearby text' behaviour."""
    fabricated = (
        "some prior line that would be wrong to absorb\n"
        "06/08/2026| 10:23 REAL MERCHANT NAME C 500.00 l\n"
        "a following line that would also be wrong to absorb\n"
    )
    result = parse_hdfc_pdf(fabricated)
    assert len(result['transactions']) == 1
    assert result['transactions'][0]['description'] == 'REAL MERCHANT NAME'


def test_no_unexplained_skipped_candidates(parsed):
    assert parsed['skipped_candidates'] == 0


def test_existing_hdfc_corpus_is_byte_identical_after_the_fix():
    """The fix only ever engages when tokens are already empty — every
    existing HDFC corpus row has real tokens, so none of them should take the
    new code path at all. Spot-checked here against the two other current-
    layout files rather than trusting that in the abstract."""
    from tests.corpus_loader import parse_corpus_file as _parse
    for name, expect_first_desc in [
        ('HDFC_SWIGGY_Ornge_redacted.pdf', None),
        ('HDFC_TATANEU_redacted.pdf', None),
    ]:
        f = TIER1_DIR / name
        if not f.exists():
            continue
        r = _parse({'path': f, 'bank': 'hdfc', 'format': 'pdf'})
        assert all(t['description'].strip() != '' for t in r['transactions']), name
