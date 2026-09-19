"""HSBC Live+ statement parser.

The golden-snapshot test (test_parsers_golden) already pins the exact parse of
both corpus files. What's here is the reasoning a snapshot can't express: the
traps this layout sets, and how the credit marker was learned rather than
guessed.

Layout facts, all verified against the real statement rather than assumed:
  - Transaction rows are `DDMMM <description> <amount>` with no year, so the
    year comes from the statement period.
  - The transaction table repeats per page between a `DATE TRANSACTION DETAILS`
    header and an `ACCOUNT SUMMARY` footer, and page 4 is a dense tariff sheet
    full of bare dates and rupee figures that must never be read as spend.
  - `14AUG NET OUTSTANDING BALANCE 21,561.30` sits INSIDE the table and matches
    the transaction shape exactly. It is a balance, not a purchase — and since
    it restates the cycle total, including it doubles the statement. The first
    prototype of this parser did exactly that: 43,122.60 parsed against 21,561.30
    printed.
  - Credits carry a trailing ` CR` after the amount; debits carry no marker.

Two statements are covered, and the pairing is the point. The first has
`Payment & other credits 0.00` - no credit row at all - so the parser shipped
with credits UNIMPLEMENTED rather than guessing a marker. The second is the
credit-bearing statement that arrived later and settled it. See
test_credit_marker_was_learned_not_guessed for what that failure actually
looked like, which was not what the original note predicted.
"""
import pytest

from pdf_parsers import parse_hsbc_pdf
from tests.corpus_loader import TIER1_DIR, parse_corpus_file

HSBC_FILE = TIER1_DIR / 'HSBC_Live+_redacted.pdf'
HSBC_CASHBACK_FILE = TIER1_DIR / 'HSBC_Live+_redacted_cashback.pdf'

pytestmark = pytest.mark.skipif(
    not HSBC_FILE.exists(),
    reason='HSBC corpus statement not present locally',
)


@pytest.fixture(scope='module')
def parsed():
    return parse_corpus_file({'path': HSBC_FILE, 'bank': 'hsbc', 'format': 'pdf'})


@pytest.fixture(scope='module')
def cashback():
    """The credit-bearing statement: a cashback, a bill payment, two refunds."""
    if not HSBC_CASHBACK_FILE.exists():
        pytest.skip('HSBC cashback statement not present locally')
    return parse_corpus_file({'path': HSBC_CASHBACK_FILE, 'bank': 'hsbc', 'format': 'pdf'})


def test_period_is_the_printed_cycle(parsed):
    assert parsed['period'] == {'start': '2026-07-15', 'end': '2026-08-14'}


def test_debits_reconcile_to_the_printed_purchases_total(parsed):
    """HSBC prints 'Purchase & other charges' in its ACCOUNT SUMMARY, which is
    a REAL sum of debits — unlike the 'Total Amount Due' most banks here print,
    which is a balance. This is the check that catches a mis-parsed row."""
    total = sum(t['amount'] for t in parsed['transactions'] if t['type'] == 'debit')
    assert parsed['totals']['debits'] == pytest.approx(21561.30, abs=0.01)
    assert total == pytest.approx(parsed['totals']['debits'], abs=0.01)


def test_net_outstanding_balance_row_is_not_a_transaction(parsed):
    """The trap. It carries a date, sits inside the transaction window, and
    matches the row shape — but it restates the cycle total, so counting it
    doubles the statement to the rupee."""
    assert not any('OUTSTANDING BALANCE' in t['description'].upper()
                   for t in parsed['transactions'])
    assert not any(t['amount'] == pytest.approx(21561.30) for t in parsed['transactions'])


def test_summary_rows_inside_the_window_are_all_excluded(parsed):
    for banned in ('TOTAL PURCHASE OUTSTANDING', 'TOTAL CASH OUTSTANDING',
                   'TOTAL BALANCE TRANSFER OUTSTANDING', 'TOTAL LOAN OUTSTANDING',
                   'OPENING BALANCE'):
        assert not any(banned in t['description'].upper() for t in parsed['transactions'])


def test_year_is_inferred_and_every_date_lands_in_the_cycle(parsed):
    """Rows print DDMMM with no year at all. Getting this wrong puts spend in
    the wrong year silently — nothing else in the pipeline would notice."""
    assert parsed['transactions'], 'no transactions parsed'
    for t in parsed['transactions']:
        assert parsed['period']['start'] <= t['date'] <= parsed['period']['end'], t


def test_tariff_sheet_is_not_read_as_spend(parsed):
    """Page 4 is pages of fees, interest illustrations and phone numbers. The
    windowing is what keeps it out; without it, figures like the 1,200/800
    'finance charge illustration' would import as purchases."""
    for t in parsed['transactions']:
        assert 'INTEREST' not in t['description'].upper()
        assert 'TARIFF' not in t['description'].upper()
    assert len(parsed['transactions']) == 32


def test_fee_and_tax_rows_are_captured_as_real_debits(parsed):
    """The joining fee and its IGST are genuine charges that hit the bill, and
    the printed purchases total includes them — dropping them as 'not
    merchants' would break reconciliation by exactly their sum."""
    descs = [t['description'].upper() for t in parsed['transactions']]
    assert any('JOINING FEE' in d for d in descs)
    assert any('IGST' in d for d in descs)


def test_no_unexplained_skipped_candidates(parsed):
    """F2: a date-shaped line that didn't become a transaction is reported.
    The deliberately-excluded summary rows are discounted, so this should be
    zero — a non-zero value means a real row shape went unparsed."""
    assert parsed['skipped_candidates'] == 0


def test_first_statement_genuinely_has_no_credits(parsed):
    """The statement that forced the parser to ship without credit handling.
    Its printed credit total is 0.00, so there was no marker to read."""
    assert parsed['totals']['credits'] == pytest.approx(0.0, abs=0.01)
    assert all(t['type'] == 'debit' for t in parsed['transactions'])


def test_credit_marker_was_learned_not_guessed(cashback):
    """A trailing ' CR' after the amount marks a credit; debits carry nothing.

    Worth recording how this surfaced, because the failure mode was not the
    one the original parser note predicted. It predicted credits would be
    captured as DEBITS and overshoot the purchases total. What actually
    happened: the line regex anchored on '$' right after the amount, so
    ' CR' rows matched nothing and were dropped entirely - debits still
    reconciled perfectly, and it was the CREDIT total that failed (0.00 vs
    22,112.85) alongside 4 skipped candidates pointing at the exact rows.

    Two checksums, and the one that caught it was not the one expected to.
    That is the argument for reconciling both directions rather than one.
    """
    credits = [t for t in cashback['transactions'] if t['type'] == 'credit']
    assert len(credits) == 4
    total = sum(t['amount'] for t in credits)
    assert cashback['totals']['credits'] == pytest.approx(22112.85, abs=0.01)
    assert total == pytest.approx(cashback['totals']['credits'], abs=0.01)


def test_cashback_statement_reconciles_on_both_totals(cashback):
    """The real gate: debits AND credits, independently, against the printed
    ACCOUNT SUMMARY. Either one alone can miss a whole class of error."""
    d = sum(t['amount'] for t in cashback['transactions'] if t['type'] == 'debit')
    c = sum(t['amount'] for t in cashback['transactions'] if t['type'] == 'credit')
    assert d == pytest.approx(cashback['totals']['debits'], abs=0.01)
    assert c == pytest.approx(cashback['totals']['credits'], abs=0.01)
    assert cashback['skipped_candidates'] == 0


def test_cr_marker_is_not_absorbed_into_the_description(cashback):
    """The marker sits outside the description's lazy capture group. If it
    drifted inside, merchants would silently gain a ' CR' suffix and stop
    matching their own aliases - a categorisation break with no error."""
    for t in cashback['transactions']:
        assert not t['description'].rstrip().endswith('CR'), t


def test_the_three_kinds_of_credit_are_all_captured(cashback):
    """A cashback, a bill payment and two merchant refunds - they are not
    interchangeable downstream. is_cashback (set app-side from the
    description) excludes cashback from refund maths, and the bill payment
    must land in Credit Card Bills rather than reducing spend as a refund."""
    descs = {t['description'].upper() for t in cashback['transactions'] if t['type'] == 'credit'}
    assert any('CASHBACK' in d for d in descs)
    assert any('BBPS PMT' in d for d in descs)
    assert sum(1 for d in descs if 'ZOMATO' in d or 'INNOVATIVE RETAIL' in d) == 2


def test_a_refund_and_its_original_charge_both_survive(cashback):
    """18AUG carries IAP ZOMATO...273.78 CR against ZOMATO...273.78 - a charge
    and its reversal in the same cycle, same amount. A parser that deduped on
    (date, amount) would drop one and silently unbalance the statement."""
    z = [t for t in cashback['transactions'] if t['amount'] == pytest.approx(273.78)]
    assert len(z) == 2
    assert {t['type'] for t in z} == {'debit', 'credit'}
