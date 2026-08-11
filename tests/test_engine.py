"""Task 5.3 — the accrual engine's synthetic fixture gate (the backlog's
done-condition): a hand-computed fixture covering base vs accelerated match,
an exclusion, a cap hit mid-month, a min-txn threshold, a bonus rule met and
missed, refunds (matched + unmatched), and a mid-window devaluation — every
accrual must match the hand computation to the unit and paisa. This file is
the engine's permanent regression anchor.

═══ THE HAND COMPUTATION ═══════════════════════════════════════════════════
Account CARD-E, points program, two eras:
  era1 [2026-01-01 .. 2026-03-01)  route ₹0.25/pt (2500 centipaise)
    r_excl  p1 excluded  'Rent'
    r_food  p2 accel     'Food & Drinks'  5 pts/₹100   cap 100 pts/calendar_month
    r_shop  p3 accel     'Shopping'      10 pts/₹100   min_txn ₹1,000
    r_base  p10 base     (any)            1 pt /₹100
    bonus: '4 txns ≥ ₹500 in a calendar month → 500 pts'
  era2 [2026-03-01 .. open)        route ₹0.20/pt (2000 centipaise)
    r2_base p1 base      (any)            1 pt /₹200   (the devaluation)

txn  date        desc            amt(₹)  cat        → rule    earned/uncapped  value(paise)
 t1  2025-12-20  OLD FOOD PLACE  1000    Food       → r_food   50/50    1250   (pre-era1: earliest era extended backward, flagged; own Dec cap bucket)
 t2  2026-01-05  FOOD ONE        1500    Food       → r_food   75/75    1875   (Jan bucket: 75 used)
 t3  2026-01-08  FOOD TWO        1000    Food       → r_food   25/50     625   (cap hit: only 25 of 100 left; 25 lost)
 t4  2026-01-10  LANDLORD       10000    Rent       → r_excl    0/0        0   (explicit exclusion row)
 t5  2026-01-12  STORE SMALL      800    Shopping   → r_base    8/8      200   (₹800 < r_shop's ₹1,000 min_txn → falls through to base)
 t6  2026-01-15  STORE BIG       2000    Shopping   → r_shop  200/200   5000
 t7  2026-01-20  CAB RIDE         600    Travel     → r_base    6/6      150
 t8  2026-01-25  FOOD TWO        1000cr  Refunds    → r_food  -25/-50   -625   (matched reversal of t3; Jan bucket back to 75)
 t9  2026-01-28  FOOD FOUR       1000    Food       → r_food   25/50     625   (refund restored headroom: 25 of 100 left again)
 t10 2026-01-30  MYSTERY REFUND   200cr  Refunds    → r_base   -2/-2     -50   (no matching debit → reversed at first-match rate, uncapped)
 t11 2026-02-10  FOOD THREE       400    Food       → r_food   20/20     500   (fresh Feb bucket)
 t12 2026-03-05  FOOD MARCH      1000    Food       → r2_base   5/5      100   (era2: devalued base rate + ₹0.20 route)

Bonus ('4 txns ≥ ₹500/month', era1 txns only):
  2025-12: 1 qualifying (t1)                       → MISSED
  2026-01: 7 qualifying (t2..t7,t9 all ≥ ₹500)     → MET, 500 pts = 12500 paise
  2026-02: 0 qualifying (t11 is ₹400)              → MISSED

Account CARD-B (conftest rows), cashback program (units ARE paise):
  cb_food  p1 accel 'Food & Drinks' 5%  cap ₹150/statement_cycle
  cb_base  p2 base  (any)           1%
  SAMPLE STORE ₹2000 Shopping → cb_base  2000/2000  value 2000 (identity)
  SAMPLE CAFE   ₹300 Food     → cb_food  1500/1500  value 1500
  (both txns have no statement_id → statement_cycle falls back to calendar
   month, flagged in notes)
════════════════════════════════════════════════════════════════════════════
"""
import sqlite3

import pytest

import app as app_module
from rewards.engine import evaluate_bonuses, rebuild_all


@pytest.fixture()
def conn(client):
    c = sqlite3.connect(app_module.DB_PATH)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def _account(conn, name):
    return conn.execute(
        "INSERT INTO accounts (kind, name) VALUES ('credit_card', ?)", (name,)).lastrowid


def _txn(conn, account_id, date, desc, inr, type='debit', category='Food & Drinks'):
    return conn.execute(
        'INSERT INTO transactions (account_id, date, description, amount_paise, type, category) '
        'VALUES (?,?,?,?,?,?)',
        (account_id, date, desc, int(round(inr * 100)), type, category)).lastrowid


def _era(conn, account_id, valid_from, valid_to, vpp_centipaise, currency='points'):
    pid = conn.execute(
        'INSERT INTO reward_programs (account_id, name, earn_currency, valid_from, valid_to) '
        'VALUES (?,?,?,?,?)', (account_id, 'Fixture Points', currency, valid_from, valid_to)).lastrowid
    conn.execute(
        "INSERT INTO redemption_routes (program_id, name, value_per_point_centipaise, is_default) "
        "VALUES (?, 'Default', ?, 1)", (pid, vpp_centipaise))
    return pid


def _rule(conn, pid, priority, kind, category=None, numer=0, denom=10000,
          cap_units=None, cap_period=None, cap_group=None, min_txn_paise=None):
    return conn.execute(
        'INSERT INTO earn_rules (program_id, priority, kind, category, earn_numer, '
        'earn_denom_paise, cap_units, cap_period, cap_group, min_txn_paise) '
        'VALUES (?,?,?,?,?,?,?,?,?,?)',
        (pid, priority, kind, category, numer, denom,
         cap_units, cap_period, cap_group, min_txn_paise)).lastrowid


@pytest.fixture()
def fixture(conn):
    """Builds the hand-computed CARD-E fixture above; returns ids."""
    acc = _account(conn, 'CARD-E')
    era1 = _era(conn, acc, '2026-01-01', '2026-03-01', 2500)
    era2 = _era(conn, acc, '2026-03-01', None, 2000)
    r_excl = _rule(conn, era1, 1, 'excluded', category='Rent')
    r_food = _rule(conn, era1, 2, 'accelerated', category='Food & Drinks',
                   numer=5, denom=10000, cap_units=100, cap_period='calendar_month')
    r_shop = _rule(conn, era1, 3, 'accelerated', category='Shopping',
                   numer=10, denom=10000, min_txn_paise=100000)
    r_base = _rule(conn, era1, 10, 'base', numer=1, denom=10000)
    r2_base = _rule(conn, era2, 1, 'base', numer=1, denom=20000)
    conn.execute(
        'INSERT INTO bonus_rules (program_id, name, period, min_txn_count, min_txn_paise, bonus_units) '
        "VALUES (?, '4 txns >= 500/month -> 500 pts', 'calendar_month', 4, 50000, 500)", (era1,))

    t = {}
    t['t1'] = _txn(conn, acc, '2025-12-20', 'OLD FOOD PLACE', 1000)
    t['t2'] = _txn(conn, acc, '2026-01-05', 'FOOD ONE', 1500)
    t['t3'] = _txn(conn, acc, '2026-01-08', 'FOOD TWO', 1000)
    t['t4'] = _txn(conn, acc, '2026-01-10', 'LANDLORD', 10000, category='Rent')
    t['t5'] = _txn(conn, acc, '2026-01-12', 'STORE SMALL', 800, category='Shopping')
    t['t6'] = _txn(conn, acc, '2026-01-15', 'STORE BIG', 2000, category='Shopping')
    t['t7'] = _txn(conn, acc, '2026-01-20', 'CAB RIDE', 600, category='Travel')
    t['t8'] = _txn(conn, acc, '2026-01-25', 'FOOD TWO', 1000, type='credit',
                   category='Reversals & Refunds')
    t['t9'] = _txn(conn, acc, '2026-01-28', 'FOOD FOUR', 1000)
    t['t10'] = _txn(conn, acc, '2026-01-30', 'MYSTERY REFUND', 200, type='credit',
                    category='Reversals & Refunds')
    t['t11'] = _txn(conn, acc, '2026-02-10', 'FOOD THREE', 400)
    t['t12'] = _txn(conn, acc, '2026-03-05', 'FOOD MARCH', 1000)
    conn.commit()
    return {'account_id': acc, 'era1': era1, 'era2': era2, 'txns': t,
            'rules': {'excl': r_excl, 'food': r_food, 'shop': r_shop,
                      'base': r_base, 'base2': r2_base}}


def _acc_row(conn, txn_id):
    return conn.execute('SELECT * FROM reward_accruals WHERE txn_id=?', (txn_id,)).fetchone()


def test_full_fixture_table_to_the_paisa(conn, fixture):
    """The whole hand computation, row for row."""
    _, notes = rebuild_all(conn)
    t, r = fixture['txns'], fixture['rules']
    expected = {  # txn -> (rule, units_earned, units_uncapped, value_paise)
        't1': (r['food'], 50, 50, 1250),
        't2': (r['food'], 75, 75, 1875),
        't3': (r['food'], 25, 50, 625),
        't4': (r['excl'], 0, 0, 0),
        't5': (r['base'], 8, 8, 200),
        't6': (r['shop'], 200, 200, 5000),
        't7': (r['base'], 6, 6, 150),
        't8': (r['food'], -25, -50, -625),
        't9': (r['food'], 25, 50, 625),
        't10': (r['base'], -2, -2, -50),
        't11': (r['food'], 20, 20, 500),
        't12': (r['base2'], 5, 5, 100),
    }
    for name, (rule_id, earned, uncapped, value) in expected.items():
        row = _acc_row(conn, t[name])
        assert row is not None, f'{name}: no accrual row'
        got = (row['rule_id'], row['units_earned'], row['units_uncapped'], row['value_paise'])
        assert got == (rule_id, earned, uncapped, value), f'{name}: {got}'
    # era assignment: t12 belongs to era2, everything else to era1
    assert _acc_row(conn, t['t12'])['program_id'] == fixture['era2']
    assert _acc_row(conn, t['t2'])['program_id'] == fixture['era1']
    # the pre-era backward extension is flagged, not silent
    assert any('predate' in n for n in notes)


def test_cap_hit_and_refund_restored_headroom(conn, fixture):
    """t3 loses 25 to the cap; t8's reversal frees headroom that t9 then
    consumes — the lost-to-cap arithmetic is (uncapped - earned)."""
    rebuild_all(conn)
    t = fixture['txns']
    t3 = _acc_row(conn, t['t3'])
    assert t3['units_uncapped'] - t3['units_earned'] == 25  # visible cap loss
    t9 = _acc_row(conn, t['t9'])
    assert (t9['units_earned'], t9['units_uncapped']) == (25, 50)


def test_excluded_txns_get_explicit_zero_rows(conn, fixture):
    rebuild_all(conn)
    row = _acc_row(conn, fixture['txns']['t4'])
    assert row['rule_id'] == fixture['rules']['excl']
    assert (row['units_earned'], row['units_uncapped'], row['value_paise']) == (0, 0, 0)


def test_devaluation_boundary_is_strict(conn, fixture):
    """2026-03-05 falls in era2 (1pt/₹200, ₹0.20 route); era1 rows keep
    their era1 program_id — history is never rewritten."""
    rebuild_all(conn)
    t12 = _acc_row(conn, fixture['txns']['t12'])
    assert t12['program_id'] == fixture['era2']
    assert (t12['units_earned'], t12['value_paise']) == (5, 100)
    era1_rows = conn.execute(
        'SELECT COUNT(*) c FROM reward_accruals WHERE program_id=?', (fixture['era1'],)).fetchone()
    assert era1_rows['c'] == 11


def test_bonus_met_and_missed(conn, fixture):
    results = [b for b in evaluate_bonuses(conn, account_id=fixture['account_id'])]
    by_month = {b['period_token'][1]: b for b in results}
    assert by_month['2025-12']['met'] is False and by_month['2025-12']['qualifying_count'] == 1
    jan = by_month['2026-01']
    assert jan['met'] is True and jan['qualifying_count'] == 7
    assert jan['bonus_units'] == 500 and jan['value_paise'] == 12500
    assert by_month['2026-02']['met'] is False and by_month['2026-02']['qualifying_count'] == 0


def test_rebuild_is_deterministic(conn, fixture):
    rebuild_all(conn)
    first = conn.execute(
        'SELECT txn_id, program_id, rule_id, units_earned, units_uncapped, value_paise '
        'FROM reward_accruals ORDER BY txn_id').fetchall()
    rebuild_all(conn)
    second = conn.execute(
        'SELECT txn_id, program_id, rule_id, units_earned, units_uncapped, value_paise '
        'FROM reward_accruals ORDER BY txn_id').fetchall()
    assert [tuple(r) for r in first] == [tuple(r) for r in second]
    assert len(first) > 0


def test_rebuild_reflects_rule_change(conn, fixture):
    """ADR-008: any rule edit invalidates and rebuilds — the cache follows
    the rules, deterministically, with no duplicate rows."""
    rebuild_all(conn)
    conn.execute('UPDATE earn_rules SET earn_numer=2 WHERE id=?', (fixture['rules']['food'],))
    rebuild_all(conn)
    t2 = _acc_row(conn, fixture['txns']['t2'])
    assert t2['units_earned'] == 30  # 150000 * 2 // 10000, was 75
    n = conn.execute('SELECT COUNT(*) c FROM reward_accruals WHERE txn_id=?',
                     (fixture['txns']['t2'],)).fetchone()
    assert n['c'] == 1


def test_cashback_program_identity_value_and_cycle_fallback(conn):
    """CARD-B (conftest rows): cashback units ARE paise; a statement_cycle
    cap on txns with no statement falls back to calendar month, flagged."""
    acc = conn.execute("SELECT id FROM accounts WHERE name='CARD-B'").fetchone()['id']
    pid = _era(conn, acc, '2026-01-01', None, None, currency='cashback_inr')
    cb_food = _rule(conn, pid, 1, 'accelerated', category='Food & Drinks',
                    numer=5, denom=100, cap_units=15000, cap_period='statement_cycle')
    cb_base = _rule(conn, pid, 2, 'base', numer=1, denom=100)
    conn.commit()

    _, notes = rebuild_all(conn)
    store = conn.execute(
        "SELECT ra.* FROM reward_accruals ra JOIN transactions t ON t.id = ra.txn_id "
        "WHERE t.description='SAMPLE STORE'").fetchone()
    cafe = conn.execute(
        "SELECT ra.* FROM reward_accruals ra JOIN transactions t ON t.id = ra.txn_id "
        "WHERE t.description='SAMPLE CAFE'").fetchone()
    assert (store['rule_id'], store['units_earned'], store['value_paise']) == (cb_base, 2000, 2000)
    assert (cafe['rule_id'], cafe['units_earned'], cafe['value_paise']) == (cb_food, 1500, 1500)
    assert any('statement_cycle->calendar_month' in n for n in notes)


def test_accounts_without_programs_get_no_rows(conn, fixture):
    """CARD-A has txns but no program — the engine leaves it alone (its
    refund row must not be misattributed to some other account's program)."""
    rebuild_all(conn)
    n = conn.execute(
        "SELECT COUNT(*) c FROM reward_accruals ra JOIN transactions t ON t.id = ra.txn_id "
        "JOIN accounts a ON a.id = t.account_id WHERE a.name='CARD-A'").fetchone()
    assert n['c'] == 0


def test_cashback_and_bill_credits_are_skipped(conn, fixture):
    """is_cashback credits and 'Credit Card Bills' payments never accrue or
    reverse (CARD-A's conftest rows would trip this if account filtering or
    credit filtering broke — belt and braces on the same guarantee)."""
    acc = fixture['account_id']
    _txn(conn, acc, '2026-01-31', 'BILL PAYMENT', 5000, type='credit', category='Credit Card Bills')
    cb = conn.execute(
        "INSERT INTO transactions (account_id, date, description, amount_paise, type, category, is_cashback) "
        "VALUES (?, '2026-01-31', 'CASHBACK POST', 5000, 'credit', 'Reversals & Refunds', 1)",
        (acc,)).lastrowid
    conn.commit()
    rebuild_all(conn)
    bills = conn.execute(
        "SELECT COUNT(*) c FROM reward_accruals ra JOIN transactions t ON t.id = ra.txn_id "
        "WHERE t.category='Credit Card Bills' OR t.id=?", (cb,)).fetchone()
    assert bills['c'] == 0
