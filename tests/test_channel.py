"""Payment-channel classifier — UPI-on-credit-card vs card authorisation.

Every case below is a real shape from the statement corpus. The point of the
classifier is that it reuses normalize.py's leading-token peel instead of
testing for the substring 'UPI', so the cases that matter most here are the
ones a substring test gets WRONG (see the `card` block).

Note the companion gate: `tests/test_normalize.py` must keep passing unchanged.
The channel work refactored normalize.py (extracting `_preclean`, threading an
optional `collect` through `_strip_leading`), and that suite passing untouched
is the proof the refactor left normalize()'s output byte-identical. Do not
weaken it to accommodate a change here.
"""
import pytest

from categorization import classify_channel
from categorization.normalize import leading_instrument_tokens

UPI_CASES = [
    ('UPI-UBER INDIA SYSTEMSPRIVAT', 'plain upi prefix'),
    ('UPI-zeptonow', 'lowercase merchant'),
    ('upi-already lowercased', 'case-insensitive'),
    ('UPICC-090259055286-15-03-2026', 'UPI credit-card rail; normalize() yields ""'),
    ('UPI/124140827202/030626/', 'slash delimiter'),
    ('EMI UPI-GLOBUS DESIGN', 'stacked emi+upi peels through to the upi'),
]

CARD_CASES = [
    ('EMI TATA PAYMENTS LIMITEDMUMBAI', 'emi is a repayment plan, not a rail'),
    ('RAZORPAY*Swiggy         Bangalore', 'gateway prefix, card rail'),
    ('SWIGGY,BANGALORE', 'plain merchant'),
    ('AMAZON                  Mumbai', 'plain merchant'),
    # The two a naive LIKE '%UPI%' would misclassify:
    ('UPIWALA STORES BANGALORE', 'upi glued into a merchant name — no delimiter'),
    ('SOME MERCHANT UPI REFUND', 'upi present but not leading'),
]


@pytest.mark.parametrize('raw,why', UPI_CASES)
def test_upi_rail(raw, why):
    assert classify_channel(raw) == 'upi', why


@pytest.mark.parametrize('raw,why', CARD_CASES)
def test_card_rail(raw, why):
    assert classify_channel(raw) == 'card', why


def test_empty_input_defaults_to_card():
    """Only positive evidence may flip the answer to 'upi' — an absent or
    unreadable description must never inflate the UPI share."""
    assert classify_channel('') == 'card'
    assert classify_channel(None) == 'card'


@pytest.mark.parametrize('raw,_why', UPI_CASES + CARD_CASES)
def test_result_is_always_one_of_two_values(raw, _why):
    assert classify_channel(raw) in {'upi', 'card'}


def test_stacked_prefixes_are_collected_in_peel_order():
    """The classifier reads whatever the peel discarded; this pins that the
    evidence itself is exposed correctly, not just the final verdict."""
    assert leading_instrument_tokens('EMI UPI-GLOBUS DESIGN') == ['emi', 'upi']
    assert leading_instrument_tokens('SWIGGY,BANGALORE') == []


def test_upicc_rail_survives_an_unmappable_merchant():
    """A pure payment reference normalizes to '' (no merchant to speak of) yet
    still carries a knowable rail — the channel lens must not lose it."""
    from categorization import normalize
    raw = 'UPICC-090259055286-15-03-2026'
    assert normalize(raw) == ''
    assert classify_channel(raw) == 'upi'
