"""Payment-channel lens.

Splits a spend by the rail it rode on: 'upi' (UPI-on-credit-card) vs 'card'
(a normal swipe / online authorisation). That distinction is what separates
the card the owner *lives on* — hundreds of small UPI taps — from the card a
single large purchase happened to land on. Ranking by rupees alone hides it
completely: on the real corpus UPI is over half the transactions but barely a
tenth of the spend.

The classification is deliberately NOT `LIKE '%UPI%'`. It reuses the
corpus-harvested leading-token peel in normalize.py, which requires a real
delimiter after the token, so:

    'UPI-UBER INDIA SYSTEMS'   -> upi
    'UPICC-090259055286-...'   -> upi    (normalize() returns '' for this — the
                                          merchant is unknowable, the rail is not)
    'EMI UPI-GLOBUS DESIGN'    -> upi    (stacked instrument prefixes)
    'EMI TATA PAYMENTS LTD'    -> card   ('emi' is a repayment arrangement on top
                                          of some rail; it names no rail itself)
    'UPIWALA STORES'           -> card   (glued, so it is a merchant name)
    'SWIGGY UPI REFUND'        -> card   ('upi' present but not leading)

The last two are the cases a substring test gets wrong.
"""
from .normalize import leading_instrument_tokens

# Of the three leading instrument tokens, only these two name the UPI rail.
# 'emi' is deliberately absent: it describes how a charge is repaid, not how it
# was made, so letting it leak in here would misfile card EMIs as UPI spend.
_UPI_TOKENS = frozenset({"upi", "upicc"})


def classify_channel(raw: str) -> str:
    """Return 'upi' or 'card' for a raw transaction description.

    Pure and deterministic. 'card' is the default: only positive UPI evidence
    flips it, so an empty or unrecognised description is never silently
    counted as UPI.
    """
    if not raw:
        return "card"
    return "upi" if _UPI_TOKENS.intersection(leading_instrument_tokens(raw)) else "card"
