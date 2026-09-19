"""Task 1.1 smoke tests: the parser module imports cleanly and its dispatch
registry has exactly the banks the upload route relies on. The corpus tests
(tasks 1.2-1.4) build on this module; catch import-time breakage first."""


def test_pdf_parsers_importable():
    import pdf_parsers  # noqa: F401 — the import itself is the assertion


def test_pdf_parsers_registry():
    from pdf_parsers import PDF_PARSERS

    # hsbc and indusind are PDF-only — neither has an entry in app.py's CSV
    # PARSERS dict, because no CSV export format has been seen for either.
    # That asymmetry is deliberate; the CSV path returns a clean 400.
    assert set(PDF_PARSERS.keys()) == {'idfc', 'icici', 'axis', 'kotak', 'hdfc', 'amex', 'hsbc', 'indusind'}
    for bank, parser in PDF_PARSERS.items():
        assert callable(parser), bank
