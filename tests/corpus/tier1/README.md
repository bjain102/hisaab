# Corpus — bring your own statements

This directory is **empty in the public repository, on purpose.** The parser
test suite is a golden-file regime (ADR-006): each committed statement is
pinned to its exact parsed output, so a parser change that alters any row
fails loudly. That only works with real statements — and real statements are
real financial documents, so none are published here.

Nothing breaks without them. `tests/corpus_loader.py` returns an empty list
when this directory has no files, and every test parametrized over the corpus
simply collects zero cases.

To turn the suite on for your own data:

1. Drop statement PDFs/CSVs in here, named with a bank prefix the loader
   recognises (see `FILENAME_BANKS` in `tests/corpus_loader.py`) — e.g.
   `HDFC_SWIGGY_mystatement.pdf`.
2. Sanitize them first. `tier1` is the *committable* tier; treat anything you
   put here as public. Password-protected originals belong in `tier2/`, which
   is gitignored, with passwords in `tests/corpus/passwords.local.json`.
3. Generate the expectations: `python scripts/gen_expectations.py`
4. From then on, `python scripts/gen_expectations.py --check` reports drift
   without rewriting, and `./test.ps1` enforces it.
