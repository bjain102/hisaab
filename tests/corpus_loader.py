"""Corpus loader (task 1.2, ADR-006).

Two tiers under tests/corpus/:
  tier1/  sanitized (redacted/synthetic) files, committed to git, no passwords.
  tier2/  real statements, gitignored, per-card folders; PDFs need a password
          from passwords.local.json (gitignored, keyed by tier2-relative path).

Tier 2 is strictly optional: on a checkout with no tier2 folder or no
passwords file, loading returns empty/skipped without raising — the suite
must stay green anywhere.

Run `python -m tests.corpus_loader` for a summary.
"""
import json
from pathlib import Path

CORPUS_DIR = Path(__file__).parent / 'corpus'
TIER1_DIR = CORPUS_DIR / 'tier1'
TIER2_DIR = CORPUS_DIR / 'tier2'
PASSWORDS_FILE = CORPUS_DIR / 'passwords.local.json'


class CorpusFileLocked(Exception):
    """A tier2 PDF is encrypted and no password is on file — tests skip it."""

# tier2 folder name (lowercased) → parser key
FOLDER_BANKS = {
    'amazon pay icici': 'icici',
    'amex mrcc': 'amex',
    'axis myzone': 'axis',
    'axis rewards': 'axis',
    'hdfc swiggy': 'hdfc',
    'hdfc tata neu': 'hdfc',
    'idfc wow!': 'idfc',
    'kotak zen': 'kotak',
}

# tier1 filename prefix (uppercased) → parser key; order matters (first match)
FILENAME_BANKS = [
    ('AMAZON_ICICI', 'icici'),
    ('AMEX', 'amex'),
    ('AXIS', 'axis'),
    ('HDFC', 'hdfc'),
    ('IDFC', 'idfc'),
    ('KOTAK', 'kotak'),
]


def _bank_for_filename(name):
    upper = name.upper()
    for prefix, bank in FILENAME_BANKS:
        if upper.startswith(prefix):
            return bank
    return None


def tier1_entries():
    """[{path, bank, format}] — every sanitized corpus file present locally.

    An unmappable tier1 file is a mistake and raises. A MISSING tier1
    directory is not: this repository ships no statements at all (they are
    real financial documents), so a fresh clone has an empty corpus and every
    parser test parametrized over it collects zero cases instead of erroring.
    Drop your own statements into tests/corpus/tier1/ — named with the bank
    prefixes in FILENAME_BANKS — and the whole golden-file suite comes alive.
    Same graceful-degradation contract tier2 has always had."""
    entries = []
    if not TIER1_DIR.is_dir():
        return entries
    for path in sorted(TIER1_DIR.iterdir()):
        if path.suffix.lower() not in ('.pdf', '.csv'):
            continue
        bank = _bank_for_filename(path.name)
        if bank is None:
            raise ValueError(f'tier1 file with unrecognized bank prefix: {path.name}')
        entries.append({'path': path, 'bank': bank, 'format': path.suffix.lstrip('.').lower()})
    return entries


def load_tier2():
    """(entries, skipped) — entries as tier1 plus 'password' (PDFs only).
    PDFs without a password entry are still INCLUDED (some banks, e.g. Amex,
    send unencrypted PDFs) — if such a file turns out to be encrypted,
    parse_corpus_file raises CorpusFileLocked and tests skip it with a clear
    reason. Only files in unrecognized card folders are skipped here. Never
    raises for absent tier2/passwords."""
    entries, skipped = [], []
    if not TIER2_DIR.is_dir():
        return entries, skipped
    passwords = {}
    if PASSWORDS_FILE.is_file():
        passwords = json.loads(PASSWORDS_FILE.read_text(encoding='utf-8'))

    for path in sorted(TIER2_DIR.rglob('*')):
        if not path.is_file() or path.suffix.lower() not in ('.pdf', '.csv'):
            continue
        rel = path.relative_to(TIER2_DIR).as_posix()
        bank = FOLDER_BANKS.get(path.parent.name.lower())
        if bank is None:
            skipped.append((rel, 'unknown card folder'))
            continue
        fmt = path.suffix.lstrip('.').lower()
        password = passwords.get(rel) or None if fmt == 'pdf' else None
        entries.append({'path': path, 'bank': bank, 'format': fmt, 'password': password})
    return entries, skipped


_PARSE_CACHE = {}


def parse_corpus_file(entry):
    """Parse one corpus entry to the normalized shape
    {transactions, rewards, period, totals}.

    Reuses the app's existing dispatch tables read-only — PDF via
    pdf_parsers.PDF_PARSERS, CSV via app.PARSERS (which returns a bare list,
    normalized here). Imports are lazy so importing this module stays light
    and side-effect-free for the non-parsing tests.

    Results are cached per process by file path: parsing is deterministic and
    several tests (golden + reconciliation) parse the same files, so this keeps
    the suite from re-extracting every PDF multiple times."""
    key = str(entry['path'])
    if key in _PARSE_CACHE:
        return _PARSE_CACHE[key]
    bank = entry['bank']
    if entry['format'] == 'pdf':
        import pdfplumber
        from pdfminer.pdfdocument import PDFEncryptionError
        from pdf_parsers import PDF_PARSERS
        try:
            with pdfplumber.open(entry['path'], password=entry.get('password') or '') as pdf:
                text = '\n'.join(p.extract_text() or '' for p in pdf.pages)
        except PDFEncryptionError:
            # Catch by exception TYPE, not message text: some pdfminer encryption
            # failures (e.g. PDFPasswordIncorrect) carry an empty str(e) — a prior
            # message-substring check silently missed exactly this case on a real
            # corpus file that had no entry in passwords.local.json yet.
            raise CorpusFileLocked(
                f"{entry['path'].name}: encrypted — add its password to passwords.local.json"
            ) from None
        except Exception as e:
            msg = str(e).lower()
            if not entry.get('password') and ('password' in msg or 'decrypt' in msg or 'encrypt' in msg):
                raise CorpusFileLocked(
                    f"{entry['path'].name}: encrypted — add its password to passwords.local.json"
                ) from e
            raise
        result = PDF_PARSERS[bank](text)
        out = {'transactions': result['transactions'], 'rewards': result.get('rewards'),
               'period': result.get('period'), 'totals': result.get('totals'),
               'skipped_candidates': result.get('skipped_candidates', 0)}
    else:  # csv
        import app as app_module
        content = entry['path'].read_text(encoding='utf-8', errors='replace')
        transactions = app_module.PARSERS[bank](content)
        # CSVs carry no printed cycle — derive the period from min/max txn dates.
        dates = [t['date'] for t in transactions if t.get('date')]
        period = {'start': min(dates), 'end': max(dates)} if dates else None
        out = {'transactions': transactions, 'rewards': None,
               'period': period, 'totals': None, 'skipped_candidates': None}
    _PARSE_CACHE[key] = out
    return out


if __name__ == '__main__':
    t1 = tier1_entries()
    t2, skipped = load_tier2()
    print(f'tier1: {len(t1)} files ({sum(1 for e in t1 if e["format"] == "pdf")} pdf, '
          f'{sum(1 for e in t1 if e["format"] == "csv")} csv)')
    print(f'tier2: {len(t2)} usable, {len(skipped)} skipped')
    for rel, reason in skipped:
        print(f'  skipped {rel}: {reason}')
