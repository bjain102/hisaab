"""Generate / check golden expectations for the parser corpus (task 1.3).

Each corpus file gets a sibling `<file>.expected.json` holding the normalized
parse output {transactions, rewards}. Tier1 expectations are committed
(sanitized); tier2 expectations are generated locally and gitignored.

Usage (from repo root):
  python scripts/gen_expectations.py            # (re)generate all, print summary
  python scripts/gen_expectations.py --check    # compare only; non-zero exit on drift
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tests.corpus_loader import (  # noqa: E402
    CorpusFileLocked, tier1_entries, load_tier2, parse_corpus_file,
)


def expected_path(entry):
    return entry['path'].with_suffix(entry['path'].suffix + '.expected.json')


def serialize(result):
    return json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True)


def all_entries():
    t2, _skipped = load_tier2()
    return tier1_entries() + t2


def generate():
    for entry in all_entries():
        try:
            result = parse_corpus_file(entry)
        except CorpusFileLocked as e:
            print(f'\nSKIPPED (locked): {e}')
            continue
        expected_path(entry).write_text(serialize(result) + '\n', encoding='utf-8')
        txns = result['transactions']
        rel = entry['path'].name
        print(f"\n{rel}  [{entry['bank']}/{entry['format']}]  "
              f"{len(txns)} txns  rewards={'yes' if result['rewards'] else 'no'}")
        for t in txns[:3]:
            print(f"    {t['date']}  {t['type']:6}  {t['amount']:>12}  {t['description'][:44]}")


def check():
    drift = []
    for entry in all_entries():
        ep = expected_path(entry)
        try:
            fresh = serialize(parse_corpus_file(entry))
        except CorpusFileLocked as e:
            print(f'SKIPPED (locked): {e}')
            continue
        if not ep.exists():
            drift.append((entry['path'].name, 'no expected.json'))
            continue
        stored = ep.read_text(encoding='utf-8').rstrip('\n')
        if fresh != stored:
            drift.append((entry['path'].name, 'MISMATCH vs stored expectation'))
    if drift:
        print('DRIFT:')
        for name, why in drift:
            print(f'  {name}: {why}')
        return 1
    print('OK — all expectations match.')
    return 0


if __name__ == '__main__':
    if '--check' in sys.argv[1:]:
        sys.exit(check())
    generate()
