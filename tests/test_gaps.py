"""Task 5.5 — gap report + forward guidance fixture gate (the backlog's
done-condition): known best-card answers, hand-computed to the paisa,
INCLUDING the case the whole cap-aware design exists for — where the naive
rate comparison picks the wrong card because the better-looking card's cap
is nearly consumed by its own other spend.

═══ THE HAND COMPUTATION (all March 2026; route ₹1/pt everywhere) ══════════
  GAP-A  base 1 pt/₹100, uncapped              (the "actual" card)
  GAP-X  Rent EXCLUDED; Food 5 pts/₹100 and Shopping 5 pts/₹100 sharing ONE
         100-pt/calendar-month cap pool ('pool')
  GAP-Y  Food 2 pts/₹100, uncapped

  txns (all category_source='manual' unless noted):
    Mar-05  BIG FOOD          ₹10,000  Food      on GAP-A
    Mar-08  X SHOP             ₹1,800  Shopping  on GAP-X
    Mar-10  LANDLORD           ₹5,000  Rent      on GAP-A
    Mar-12  AIRLINE            ₹1,000  Travel    on GAP-A
    Mar-15  UNCONFIRMED FOOD   ₹2,000  Food      on GAP-A  (source 'none')
    Apr-02  X SHOP APR           ₹400  Shopping  on GAP-X

  Food (confirmed spend ₹10,000; actual on A = 100 pts = ₹100):
    naive says GAP-X (5% > 2%) — but X's own ₹1,800 Shopping consumed 90 of
    its 100-pt pool, so X's real headroom is 10 pts = ₹10.
    GAP-Y at 2% uncapped = 200 pts = ₹200  → BEST. loss = 200−100 = ₹100.
  Shopping (₹1,800 on X; actual 90 pts = ₹90):
    X counterfactual seeds from X's own NON-shopping spend (none) → full
    100-pt headroom → 90 pts = actual → loss 0, headroom-before ₹100.
  Rent: X excluded → ineligible; Y no rule → ineligible; best = A = actual
    → loss 0.  Travel: only A eligible → loss 0.
  March total loss = ₹100 exactly.

  Guidance (lookback 1 month → complete=[Mar], current=Apr):
    Food → GAP-Y @2%, headroom None (uncapped)
    Shopping → GAP-X @5%; live April headroom = 100 − 20 (Apr ₹400 → 20
    pts) = 80 pts = ₹80.
════════════════════════════════════════════════════════════════════════════
"""
import sqlite3

import pytest

import app as app_module
from rewards.engine import rebuild_all
from rewards.gaps import gap_report, guidance


@pytest.fixture()
def conn(client):
    c = sqlite3.connect(app_module.DB_PATH)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def _account(conn, name):
    return conn.execute(
        "INSERT INTO accounts (kind, name) VALUES ('credit_card', ?)", (name,)).lastrowid


def _txn(conn, account_id, date, desc, inr, category, source='manual'):
    return conn.execute(
        'INSERT INTO transactions (account_id, date, description, amount_paise, type, category, '
        "category_source) VALUES (?,?,?,?,'debit',?,?)",
        (account_id, date, desc, int(round(inr * 100)), category, source)).lastrowid


def _program(conn, account_id):
    pid = conn.execute(
        "INSERT INTO reward_programs (account_id, name, earn_currency, valid_from, valid_to) "
        "VALUES (?, 'Pts', 'points', '2026-01-01', NULL)", (account_id,)).lastrowid
    conn.execute("INSERT INTO redemption_routes (program_id, name, value_per_point_centipaise, "
                 "is_default) VALUES (?, 'Default', 10000, 1)", (pid,))
    return pid


def _rule(conn, pid, priority, kind, category=None, numer=0, denom=10000,
          cap_units=None, cap_period=None, cap_group=None):
    conn.execute(
        'INSERT INTO earn_rules (program_id, priority, kind, category, earn_numer, '
        'earn_denom_paise, cap_units, cap_period, cap_group) VALUES (?,?,?,?,?,?,?,?,?)',
        (pid, priority, kind, category, numer, denom, cap_units, cap_period, cap_group))


@pytest.fixture()
def fixture(conn):
    a = _account(conn, 'GAP-A')
    x = _account(conn, 'GAP-X')
    y = _account(conn, 'GAP-Y')
    pa, px, py = _program(conn, a), _program(conn, x), _program(conn, y)
    _rule(conn, pa, 10, 'base', numer=1)
    _rule(conn, px, 1, 'excluded', category='Rent')
    _rule(conn, px, 2, 'accelerated', category='Food & Drinks', numer=5,
          cap_units=100, cap_period='calendar_month', cap_group='pool')
    _rule(conn, px, 3, 'accelerated', category='Shopping', numer=5,
          cap_units=100, cap_period='calendar_month', cap_group='pool')
    _rule(conn, py, 2, 'accelerated', category='Food & Drinks', numer=2)

    _txn(conn, a, '2026-03-05', 'BIG FOOD', 10000, 'Food & Drinks')
    _txn(conn, x, '2026-03-08', 'X SHOP', 1800, 'Shopping')
    _txn(conn, a, '2026-03-10', 'LANDLORD', 5000, 'Rent')
    _txn(conn, a, '2026-03-12', 'AIRLINE', 1000, 'Travel')
    _txn(conn, a, '2026-03-15', 'UNCONFIRMED FOOD', 2000, 'Food & Drinks', source='none')
    _txn(conn, x, '2026-04-02', 'X SHOP APR', 400, 'Shopping')
    conn.commit()
    rebuild_all(conn)
    return {'a': a, 'x': x, 'y': y}


def _march_rows(conn):
    rep = gap_report(conn, months_back=2)
    march = next(m for m in rep['months'] if m['month'] == '2026-03')
    return rep, march


def test_cap_aware_counterfactual_rejects_the_naive_answer(conn, fixture):
    """THE case: naive 5% says GAP-X, but X's pool is 90/100 consumed by its
    own Shopping — GAP-Y's uncapped 2% is the true best."""
    _, march = _march_rows(conn)
    food = next(r for r in march['rows'] if r['category'] == 'Food & Drinks')
    assert food['best_card'] == 'GAP-Y'
    assert food['best_value_paise'] == 20000       # 200 pts at ₹1
    assert food['actual_value_paise'] == 10000     # 100 pts on GAP-A
    assert food['loss_paise'] == 10000             # ₹100, to the paisa
    assert food['best_headroom_value_paise'] is None  # Y is uncapped


def test_unconfirmed_spend_is_excluded_from_gap_math(conn, fixture):
    _, march = _march_rows(conn)
    food = next(r for r in march['rows'] if r['category'] == 'Food & Drinks')
    assert food['spend_paise'] == 1000000  # ₹10,000 — the 'none'-source ₹2,000 is out


def test_exclusion_makes_candidate_ineligible_and_loss_floors_at_zero(conn, fixture):
    _, march = _march_rows(conn)
    rent = next(r for r in march['rows'] if r['category'] == 'Rent')
    assert rent['best_card'] == 'GAP-A'  # X excludes Rent, Y has no rule
    assert rent['loss_paise'] == 0
    travel = next(r for r in march['rows'] if r['category'] == 'Travel')
    assert travel['best_card'] == 'GAP-A' and travel['loss_paise'] == 0


def test_actual_card_as_best_reports_zero_loss_with_headroom(conn, fixture):
    """Shopping is already on the right card: X's own counterfactual (full
    pool headroom, its own spend excluded from the seed) equals the actual."""
    _, march = _march_rows(conn)
    shop = next(r for r in march['rows'] if r['category'] == 'Shopping')
    assert shop['best_card'] == 'GAP-X'
    assert shop['actual_value_paise'] == 9000      # 90 pts really earned
    assert shop['best_value_paise'] == 9000
    assert shop['loss_paise'] == 0
    assert shop['best_headroom_value_paise'] == 10000  # full ₹100 pool pre-move


def test_monthly_total_and_trust(conn, fixture):
    rep, march = _march_rows(conn)
    assert march['total_loss_paise'] == 10000  # the Food gap is the only loss
    # window gross ₹20,200 (incl. April ₹400 + unconfirmed ₹2,000); confirmed ₹18,200
    assert rep['trust'] == pytest.approx(1820000 / 2020000)
    assert rep['caveats']  # the v1 caveats ship with the data, not just the UI


def test_guidance_best_card_and_live_headroom(conn, fixture):
    rows = guidance(conn, lookback_months=1)
    food = next(r for r in rows if r['category'] == 'Food & Drinks')
    assert food['card_label'] == 'GAP-Y'
    assert food['trailing_rate'] == pytest.approx(0.02)
    assert food['headroom_value_paise'] is None  # uncapped
    shop = next(r for r in rows if r['category'] == 'Shopping')
    assert shop['card_label'] == 'GAP-X'
    # live April headroom: 100-pt pool minus April's 20 pts = 80 pts = ₹80
    assert shop['headroom_value_paise'] == 8000


def test_guidance_skips_noise_categories(conn, fixture):
    rows = guidance(conn, lookback_months=1, min_spend_paise=200000)
    cats = {r['category'] for r in rows}
    assert 'Travel' not in cats  # ₹1,000 trailing < ₹2,000 floor
    assert 'Food & Drinks' in cats
