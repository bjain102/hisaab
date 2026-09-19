"""Task 4.2 (schema half): migration v7 — merchants/aliases/issuer_category_map
pipeline (ADR-009, fixes F9). Covers the migration's own guarantees; app-side
categorization (upload precedence, recategorize as manual pin / learn) is in
tests/test_categorization.py.
"""
import sqlite3

import pytest

import app as app_module
from db import get_version, migrate


@pytest.fixture()
def db_migrated(tmp_path, monkeypatch):
    """Legacy-shape DB with two overrides and transactions that exercise every
    backfill branch: confirmed-agree, confirmed-DISAGREE (the F9 manual-pin
    case), issuer-map (bank), keyword, and cashback."""
    db_path = str(tmp_path / 'test.db')
    monkeypatch.setattr(app_module, 'DB_PATH', db_path)
    monkeypatch.setattr(app_module, 'STATEMENTS_DIR', str(tmp_path / 'statements'))
    app_module.init_db()
    conn = sqlite3.connect(db_path)
    rows = [
        # (date, desc, amount, type, category, card, card_label, is_cashback, raw_merchant)
        ('2026-01-05', 'RAZ*SwiggyBangalore', 500.0, 'debit', 'Food & Drinks', 'ALPHA', 'ALPHA-1234', 0, 'RAZ*SwiggyBangalore'),
        ('2026-01-06', 'AMAZON  Mumbai', 200.0, 'debit', 'Grocery', 'ALPHA', 'ALPHA-1234', 0, 'AMAZON  Mumbai'),
        ('2026-01-07', 'AMAZON  Mumbai', 900.0, 'debit', 'Insurance', 'ALPHA', 'ALPHA-1234', 0, 'AMAZON  Mumbai'),
        ('2026-01-08', 'RANDOM UNKNOWN THING', 100.0, 'debit', 'Others', 'ALPHA', 'ALPHA-1234', 0, 'RANDOM UNKNOWN THING'),
        ('2026-01-09', 'SOMESTORE', 300.0, 'debit', 'Health & Wellness', 'ALPHA', 'ALPHA-1234', 0, 'SOMESTORE'),
        ('2026-01-10', 'MEMBERSHIP REWARDS', 40.0, 'credit', 'Reversals & Refunds', 'ALPHA', 'ALPHA-1234', 1, 'MEMBERSHIP REWARDS'),
    ]
    conn.executemany(
        '''INSERT INTO transactions
           (date, description, amount, type, category, card, card_label, is_cashback, raw_merchant, bank_category)
           VALUES (?,?,?,?,?,?,?,?,?, NULL)''', rows)
    # give the issuer-map row a bank_category
    conn.execute("UPDATE transactions SET bank_category='DEPT STORES' WHERE description='SOMESTORE'")
    conn.executemany(
        'INSERT INTO category_overrides (merchant_pattern, category) VALUES (?,?)',
        [('swiggy', 'Food & Drinks'), ('amazon mumbai', 'Grocery')])
    conn.commit()
    conn.close()
    applied = migrate(db_path)
    assert 7 in applied
    return db_path


def _rows(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = {r['description'] + '|' + r['category']: r
            for r in conn.execute('SELECT * FROM transactions ORDER BY id')}
    # keyed uniquely enough for this fixture (two AMAZON rows differ by category)
    all_rows = list(conn.execute('SELECT * FROM transactions ORDER BY id'))
    conn.close()
    return all_rows


def test_merchant_count_equals_override_count(db_migrated):
    conn = sqlite3.connect(db_migrated)
    n = conn.execute("SELECT COUNT(*) FROM merchants WHERE status='confirmed'").fetchone()[0]
    conn.close()
    assert n == 2  # two overrides -> two confirmed merchants


def test_aliases_are_normalized(db_migrated):
    conn = sqlite3.connect(db_migrated)
    pats = {r[0] for r in conn.execute('SELECT pattern FROM merchant_aliases')}
    conn.close()
    assert pats == {'swiggy', 'amazon'}  # normalize('amazon mumbai') -> 'amazon'


def test_no_category_changed(db_migrated):
    rows = _rows(db_migrated)
    by = {(r['description'], r['amount_paise']): r['category'] for r in rows}
    assert by[('RAZ*SwiggyBangalore', 50000)] == 'Food & Drinks'
    assert by[('AMAZON  Mumbai', 20000)] == 'Grocery'
    assert by[('AMAZON  Mumbai', 90000)] == 'Insurance'      # the manual pin: unchanged
    assert by[('SOMESTORE', 30000)] == 'Health & Wellness'


def test_category_sources_stamped_by_precedence(db_migrated):
    rows = {(r['description'], r['amount_paise']): r for r in _rows(db_migrated)}
    swiggy = rows[('RAZ*SwiggyBangalore', 50000)]
    assert swiggy['category_source'] == 'confirmed' and swiggy['merchant_id'] is not None
    amazon_ok = rows[('AMAZON  Mumbai', 20000)]
    assert amazon_ok['category_source'] == 'confirmed'
    # the disagreement (Amazon pinned to Insurance) -> manual, no merchant link
    amazon_pin = rows[('AMAZON  Mumbai', 90000)]
    assert amazon_pin['category_source'] == 'manual'
    assert amazon_pin['merchant_id'] is None
    # bank_category with no alias match, category == issuer map -> bank
    store = rows[('SOMESTORE', 30000)]
    assert store['category_source'] == 'bank'
    # keyword default and cashback auto-rule -> keyword
    assert rows[('RANDOM UNKNOWN THING', 10000)]['category_source'] == 'keyword'
    assert rows[('MEMBERSHIP REWARDS', 4000)]['category_source'] == 'keyword'


def test_issuer_map_seeded(db_migrated):
    conn = sqlite3.connect(db_migrated)
    conn.row_factory = sqlite3.Row
    m = conn.execute("SELECT * FROM issuer_category_map WHERE bank_category='DEPT STORES'").fetchone()
    conn.close()
    assert m['institution'] == 'ALPHA'
    assert m['category'] == 'Health & Wellness'


def test_category_overrides_dropped(db_migrated):
    conn = sqlite3.connect(db_migrated)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert 'category_overrides' not in tables
    assert {'merchants', 'merchant_aliases', 'issuer_category_map'} <= tables


def test_init_db_does_not_resurrect_category_overrides(db_migrated):
    app_module.init_db()  # simulate an app restart on a v7 DB
    conn = sqlite3.connect(db_migrated)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert 'category_overrides' not in tables


def test_idempotent(db_migrated):
    version = get_version(db_migrated)
    assert migrate(db_migrated) == []
    assert get_version(db_migrated) == version
    conn = sqlite3.connect(db_migrated)
    n = conn.execute("SELECT COUNT(*) FROM merchants").fetchone()[0]
    conn.close()
    assert n == 2
