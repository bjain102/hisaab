"""Task 4.3: ADR-009 assignment precedence (app.assign_category).

Exercises the ladder directly against a merchant table built in-test on the
conftest DB (migrated through v7). Covers: longest-alias-wins, ties->newest,
confirmed-beats-suggested-regardless-of-length, issuer map, keyword, cashback.
"""
import sqlite3

import app as app_module


def _conn():
    conn = sqlite3.connect(app_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _merchant(conn, canonical, category, status, *aliases):
    cur = conn.execute(
        'INSERT INTO merchants (canonical_name, category, status) VALUES (?,?,?)',
        (canonical, category, status))
    mid = cur.lastrowid
    for a in aliases:
        conn.execute('INSERT INTO merchant_aliases (merchant_id, pattern) VALUES (?,?)', (mid, a))
    return mid


def test_longest_alias_wins(client):
    conn = _conn()
    _merchant(conn, 'Reliance', 'Shopping', 'confirmed', 'reliance')
    _merchant(conn, 'Reliance Retail', 'Grocery', 'confirmed', 'reliance retail')
    conn.commit()
    cat, src, mid = app_module.assign_category(
        conn, 'RELIANCE RETAIL LIMITED', 'RELIANCE RETAIL LIMITED', None, 'X', 0, 'debit')
    conn.close()
    assert (cat, src) == ('Grocery', 'confirmed')  # longer 'reliance retail' beats 'reliance'


def test_ties_break_to_newest(client):
    conn = _conn()
    _merchant(conn, 'Older', 'Shopping', 'confirmed', 'abcd')
    _merchant(conn, 'Newer', 'Grocery', 'confirmed', 'wxyz')  # same length, higher id
    conn.commit()
    cat, src, _ = app_module.assign_category(
        conn, 'ABCD WXYZ', 'ABCD WXYZ', None, 'X', 0, 'debit')
    conn.close()
    assert cat == 'Grocery'  # equal-length aliases both match -> newest (higher id) wins


def test_confirmed_beats_suggested_even_if_shorter(client):
    conn = _conn()
    _merchant(conn, 'Swiggy', 'Food & Drinks', 'confirmed', 'swiggy')
    _merchant(conn, 'Swiggy Instamart Grocery', 'Grocery', 'suggested', 'swiggy instamart')
    conn.commit()
    cat, src, _ = app_module.assign_category(
        conn, 'SWIGGY INSTAMART', 'SWIGGY INSTAMART', None, 'X', 0, 'debit')
    conn.close()
    assert (cat, src) == ('Food & Drinks', 'confirmed')  # confirmed wins over longer suggested


def test_suggested_used_when_no_confirmed(client):
    conn = _conn()
    _merchant(conn, 'Guessed', 'Entertainment', 'suggested', 'someplace')
    conn.commit()
    cat, src, mid = app_module.assign_category(
        conn, 'SOMEPLACE COOL', 'SOMEPLACE COOL', None, 'X', 0, 'debit')
    conn.close()
    assert (cat, src) == ('Entertainment', 'suggested') and mid is not None


def test_issuer_map_when_no_alias(client):
    conn = _conn()
    conn.execute("INSERT INTO issuer_category_map (institution, bank_category, category) "
                 "VALUES ('AXIS','RESTAURANTS','Food & Drinks')")
    conn.commit()
    cat, src, mid = app_module.assign_category(
        conn, 'UNKNOWN PLACE', 'UNKNOWN PLACE', 'RESTAURANTS', 'AXIS', 0, 'debit')
    conn.close()
    assert (cat, src, mid) == ('Food & Drinks', 'bank', None)


def test_keyword_fallback_and_cashback(client):
    conn = _conn()
    kw_cat, kw_src, _ = app_module.assign_category(
        conn, 'SWIGGY ORDER', 'SWIGGY ORDER', None, 'X', 0, 'debit')  # keyword map has 'swiggy'
    cb_cat, cb_src, _ = app_module.assign_category(
        conn, 'SOME CASHBACK', 'SOME CASHBACK', None, 'X', 1, 'credit')
    conn.close()
    assert (kw_cat, kw_src) == ('Food & Drinks', 'keyword')
    assert (cb_cat, cb_src) == ('Reversals & Refunds', 'keyword')
