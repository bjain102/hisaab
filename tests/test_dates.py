"""Task 1.5: fix F3 — CSV date-format priority.

parse_date() defaults to DD/MM-first (every Indian bank); only Amex passes
mm_dd_first=True. Before this fix, '05/03/2026' silently misread as May 3
for every bank because %m/%d/%Y was tried first unconditionally.
"""
from app import parse_date


def test_ambiguous_date_resolves_by_bank_convention():
    # day=05, month=03 under DD/MM (any Indian bank, the default)
    assert parse_date('05/03/2026') == '2026-03-05'
    # month=05, day=03 under MM/DD (Amex)
    assert parse_date('05/03/2026', mm_dd_first=True) == '2026-05-03'


def test_unambiguous_date_agrees_regardless_of_convention():
    # day=15 can't be a month, so only %d/%m/%Y matches under either flag —
    # proves the fallback still resolves correctly when the ambiguity dissolves.
    assert parse_date('15/03/2026') == '2026-03-15'
    assert parse_date('15/03/2026', mm_dd_first=True) == '2026-03-15'


def test_hyphenated_ambiguous_pair_also_respects_convention():
    assert parse_date('05-03-2026') == '2026-03-05'
    assert parse_date('05-03-2026', mm_dd_first=True) == '2026-05-03'


def test_every_other_format_still_parses():
    cases = [
        ('2026-03-05', '2026-03-05'),   # %Y-%m-%d
        ('05 Mar 2026', '2026-03-05'),  # %d %b %Y
        ('05-Mar-2026', '2026-03-05'),  # %d-%b-%Y
        ('05/Mar/2026', '2026-03-05'),  # %d/%b/%Y
        ('Mar 05, 2026', '2026-03-05'), # %b %d, %Y
        ('05 March 2026', '2026-03-05'),# %d %B %Y
        ('2026/03/05', '2026-03-05'),   # %Y/%m/%d
        ('05.03.2026', '2026-03-05'),   # %d.%m.%Y
        ('05-03-26', '2026-03-05'),     # %d-%m-%y
        ('05/03/26', '2026-03-05'),     # %d/%m/%y
        ('Mar 05 2026', '2026-03-05'),  # %b %d %Y
    ]
    for raw, expected in cases:
        assert parse_date(raw) == expected, raw


def test_unparseable_returns_none():
    assert parse_date('not a date') is None
    assert parse_date('') is None
