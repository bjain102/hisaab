"""Task 1.2: the corpus loader works and tier1 is complete. No parsing here —
running the parsers against the corpus is task 1.3."""
from tests.corpus_loader import load_tier2, tier1_entries


def test_tier1_complete():
    entries = tier1_entries()
    print(f'\ntier1 collected: {len(entries)} files')
    # 17 redacted PDFs (incl. Amex, a 2nd Kotak file with a credit row (task
    # 1.7), TWO OLD-layout HDFC Swiggy statements — HDFC changed its statement
    # format mid-history, so one card needs a file per layout, and the second
    # old file is the one carrying credits, since the first has none — one
    # OLD-layout HDFC Tata Neu statement, which exposed a second bug in the
    # same old-layout matcher: an inline "HH:MM:SS" time some rows carry;
    # TWO HSBC Live+ statements, the first with no credit rows at all and the
    # second the credit-bearing one that finally settled the ' CR' marker —
    # see test_hsbc_parser.py; one Swiggy ORNGE statement, the rebranded card
    # that replaced HDFC Swiggy and parses on the existing current-layout
    # matcher with zero parser changes; one CRED IndusInd statement, the
    # only one in the corpus printing an issuer category AND reward points
    # per transaction; and one CURRENT-layout HDFC Tata Neu statement whose
    # one BPPY bill payment wraps its description across the date/amount row
    # itself, not just onto an adjacent line — see test_hdfc_description_wrap.py)
    # + 1 synthetic Amex CSV
    assert len(entries) == 18
    banks = {e['bank'] for e in entries}
    assert banks == {'icici', 'amex', 'axis', 'hdfc', 'idfc', 'kotak', 'hsbc', 'indusind'}
    assert sum(1 for e in entries if e['format'] == 'csv') == 1  # the Amex synthetic


def test_tier2_loads_or_skips_gracefully():
    # Must never raise — including on checkouts with no tier2 at all.
    entries, skipped = load_tier2()
    print(f'\ntier2 collected: {len(entries)} usable, {len(skipped)} skipped')
    for e in entries:
        assert e['bank'] in {'icici', 'amex', 'axis', 'hdfc', 'idfc', 'kotak', 'hsbc', 'indusind'}
        if e['format'] == 'pdf':
            # password may be None (unencrypted PDFs, e.g. Amex); if the file
            # turns out to be locked, parse raises CorpusFileLocked and the
            # parsing tests skip it with that reason.
            assert e['password'] is None or e['password']
    for _rel, reason in skipped:
        assert reason  # every skip carries a human-readable reason
