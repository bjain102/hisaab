"""Golden snapshot tests (task 1.3) — closes F1.

Re-parse every corpus file and deep-compare against its committed (tier1) or
local (tier2) expected.json. Any change that alters what a parser extracts
fails here. Regenerate intentionally with `python scripts/gen_expectations.py`.

Test id is the corpus-relative path, so a failure names the exact file/bank.
"""
import json

import pytest

from tests.corpus_loader import (
    CORPUS_DIR, CorpusFileLocked, tier1_entries, load_tier2, parse_corpus_file,
)


def _cases():
    t2, _skipped = load_tier2()
    return [('tier1', e) for e in tier1_entries()] + [('tier2', e) for e in t2]


def _case_id(case):
    tier, entry = case
    return entry['path'].relative_to(CORPUS_DIR).as_posix()


def _expected_path(entry):
    return entry['path'].with_suffix(entry['path'].suffix + '.expected.json')


@pytest.mark.parametrize('case', _cases(), ids=_case_id)
def test_parser_matches_expectation(case):
    tier, entry = case
    ep = _expected_path(entry)
    if not ep.exists():
        if tier == 'tier1':
            pytest.fail(f'committed expectation missing: {ep.name} '
                        f'(run: python scripts/gen_expectations.py)')
        pytest.skip('tier2 expectation not generated on this machine')

    expected = json.loads(ep.read_text(encoding='utf-8'))
    try:
        actual = parse_corpus_file(entry)
    except CorpusFileLocked as e:
        pytest.skip(str(e))
    # round-trip through JSON so int/float and key ordering compare like-for-like
    actual = json.loads(json.dumps(actual))
    assert actual == expected
