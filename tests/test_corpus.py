"""Task 1.2: the corpus loader works and tier1 is complete. No parsing here —
running the parsers against the corpus is task 1.3."""
from pathlib import Path
import pytest
from tests.corpus_loader import load_tier2, tier1_entries

_CORPUS_DIR = Path(__file__).parent / 'corpus' / 'tier1'
# This repository ships no statements (they are real financial documents), so
# every test in this module skips on a fresh clone and comes alive the moment
# you add your own to tests/corpus/tier1/ — see that directory's README.
pytestmark = pytest.mark.skipif(
    not _CORPUS_DIR.is_dir() or not any(f.suffix.lower() in ('.pdf', '.csv') for f in _CORPUS_DIR.glob('*')),
    reason='no local statement corpus — see tests/corpus/tier1/README.md',
)


def test_tier1_complete():
    entries = tier1_entries()
    print(f'\ntier1 collected: {len(entries)} files')
    # 12 redacted PDFs (incl. Amex, a 2nd Kotak file with a credit row (task
    # 1.7), TWO OLD-layout HDFC Swiggy statements — HDFC changed its statement
    # format mid-history, so one card needs a file per layout, and the second
    # old file is the one carrying credits, since the first has none — and one
    # OLD-layout HDFC Tata Neu statement, which exposed a second bug in the
    # same old-layout matcher: an inline "HH:MM:SS" time some rows carry)
    # + 1 synthetic Amex CSV
    assert len(entries) == 13
    banks = {e['bank'] for e in entries}
    assert banks == {'icici', 'amex', 'axis', 'hdfc', 'idfc', 'kotak'}
    assert sum(1 for e in entries if e['format'] == 'csv') == 1  # the Amex synthetic


def test_tier2_loads_or_skips_gracefully():
    # Must never raise — including on checkouts with no tier2 at all.
    entries, skipped = load_tier2()
    print(f'\ntier2 collected: {len(entries)} usable, {len(skipped)} skipped')
    for e in entries:
        assert e['bank'] in {'icici', 'amex', 'axis', 'hdfc', 'idfc', 'kotak'}
        if e['format'] == 'pdf':
            # password may be None (unencrypted PDFs, e.g. Amex); if the file
            # turns out to be locked, parse raises CorpusFileLocked and the
            # parsing tests skip it with that reason.
            assert e['password'] is None or e['password']
    for _rel, reason in skipped:
        assert reason  # every skip carries a human-readable reason
