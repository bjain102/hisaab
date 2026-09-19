"""CRED IndusInd Bank RuPay statement parser.

The golden snapshot pins the exact parse. What's here is what a snapshot
can't express: the two layout traps, and the two things this statement prints
that no other bank in the corpus does.

    Date       Transaction Details        Merchant Category  Points  Amount
    13/08/2026 UPI ZEPTO 659126411378     GROCERY &          8       151.00 DR
                                          SUPERMARKET
"""
import pytest

from tests.corpus_loader import TIER1_DIR, parse_corpus_file

INDUSIND_FILE = TIER1_DIR / 'CRED_IndusInd_redacted.pdf'

pytestmark = pytest.mark.skipif(
    not INDUSIND_FILE.exists(),
    reason='CRED IndusInd corpus statement not present locally',
)


@pytest.fixture(scope='module')
def parsed():
    return parse_corpus_file({'path': INDUSIND_FILE, 'bank': 'indusind', 'format': 'pdf'})


def test_period_and_full_dates(parsed):
    """Dates are full dd/mm/yyyy here — no year inference, unlike HSBC/Amex."""
    assert parsed['period'] == {'start': '2026-07-23', 'end': '2026-08-22'}
    assert parsed['transactions']
    for t in parsed['transactions']:
        assert parsed['period']['start'] <= t['date'] <= parsed['period']['end'], t


def test_debits_reconcile_to_the_printed_purchases_total(parsed):
    total = sum(t['amount'] for t in parsed['transactions'] if t['type'] == 'debit')
    assert parsed['totals']['debits'] == pytest.approx(2679.50, abs=0.01)
    assert total == pytest.approx(parsed['totals']['debits'], abs=0.01)
    assert len(parsed['transactions']) == 25


def test_right_column_bleedthrough_does_not_drop_rows(parsed):
    """THE trap in this layout. Page 1 renders a right-hand summary column that
    pdfplumber interleaves into transaction lines, so some rows arrive as
    '... 60.00 DR Statement Date' or '... 2.36 DR (Including Loans)'.

    A regex anchored on '$' after the DR/CR marker drops exactly those rows
    silently — which is precisely how HSBC's credits went missing. Three rows
    in this file carry such junk; the fuel-surcharge one below is the
    smallest, so a naive parser would still look 'nearly right' while being
    2.36 short.
    """
    # The three rows that actually carry trailing junk in this file, asserted
    # by their own reference numbers rather than by amount — amounts repeat.
    for ref in ('658424260690',    # '... 60.00 DR Statement Date'
                '092806966798',    # '... 60.00 DR 22/08/2026'
                '658528323254'):   # '... 2.36 DR (Including Loans)'
        assert any(ref in t['description'] for t in parsed['transactions']), ref
    # ...and the junk itself never reaches the stored description.
    for t in parsed['transactions']:
        assert 'Statement Date' not in t['description']
        assert 'Including Loans' not in t['description']
        assert not t['description'].endswith(('DR', 'CR'))


def test_issuer_category_is_captured_and_is_optional(parsed):
    """This is one of only three banks here that publish their own merchant
    category, and it feeds issuer_category_map. It is genuinely optional —
    fuel-surcharge and CRED's own rows carry none — so a parser that required
    it would drop them."""
    with_cat = [t for t in parsed['transactions'] if 'bank_category' in t]
    without = [t for t in parsed['transactions'] if 'bank_category' not in t]
    assert len(with_cat) == 22
    assert len(without) == 3
    assert {t['bank_category'] for t in with_cat} == {
        'MISCELLANEOUS', 'PETROL', 'STATIONERY', 'GIFT SHOPS', 'GROCERY & SUPERMARKET'}


def test_wrapped_category_is_rejoined(parsed):
    """'GROCERY &' / 'SUPERMARKET' spans two lines. Left unjoined, the issuer
    category map learns the truncated key 'GROCERY &' — wrong, and invisible
    until it mis-categorises something months later."""
    zepto = next(t for t in parsed['transactions'] if 'ZEPTO' in t['description'].upper())
    assert zepto['bank_category'] == 'GROCERY & SUPERMARKET'


def test_description_splits_on_the_upi_reference_not_on_casing(parsed):
    """Merchant names and issuer categories are BOTH uppercase, so no casing
    rule could separate 'UPI KALA RAM' from 'STATIONERY'. The long UPI
    reference number always sits exactly between them, which is what makes
    the split reliable."""
    kala = next(t for t in parsed['transactions'] if 'KALA RAM' in t['description'])
    assert kala['description'] == 'UPI KALA RAM 658805965578'
    assert kala['bank_category'] == 'STATIONERY'
    for t in parsed['transactions']:
        assert not t['description'].endswith(('MISCELLANEOUS', 'PETROL', 'STATIONERY'))


def test_reward_points_total_is_captured_as_the_balance(parsed):
    """The statement prints points per transaction AND a cycle total. Per the
    owner's call, only the cycle total is stored — via reward_balances, the
    same dated-history mechanism every other card uses — rather than adding a
    points column to transactions. The per-transaction figures are parsed and
    available if per-row reconciliation ever becomes interesting."""
    assert parsed['rewards'] == {
        'label': 'CRED Points', 'value': 29, 'value_type': 'points'}


def test_payment_due_date_line_is_not_a_phantom_skip(parsed):
    """'11/09/2026' sits alone on its own line and is the only other
    dd/mm/yyyy-prefixed line in the document. The F2 anchor counts only dated
    lines that ALSO carry a DR/CR amount, so it isn't reported as a skip."""
    assert parsed['skipped_candidates'] == 0


def test_every_row_is_a_upi_transaction(parsed):
    """The card's premise — a UPI-first credit card. classify_channel should
    therefore read this account as ~100% UPI, which is a genuinely useful
    data point for the dashboard's UPI-vs-card lens rather than an anomaly."""
    assert all(t['description'].startswith('UPI ') for t in parsed['transactions'])


def test_credits_are_marked_but_unexercised(parsed):
    """Amounts carry an explicit DR/CR suffix, so unlike HSBC the credit shape
    isn't a guess — but this statement's 'Payments & Other Credits' is 0.00,
    so no credit row has ever actually been seen. The printed credit total
    polices it: a credit-bearing statement that parsed wrongly would fail
    here rather than pass quietly."""
    assert parsed['totals']['credits'] == pytest.approx(0.0, abs=0.01)
    credits = sum(t['amount'] for t in parsed['transactions'] if t['type'] == 'credit')
    assert credits == pytest.approx(parsed['totals']['credits'], abs=0.01)
