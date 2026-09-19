"""Task 5.4 — effective rates + reconciliation (M10 Job 2). Hand-computed
fixtures to the paisa; the reconciliation-status matrix (ok / mismatch /
redemption_suspected / insufficient_history) pinned explicitly.

═══ EFFECTIVE-RATE HAND COMPUTATION (account RATE-CARD) ════════════════════
points program, default route ₹1/pt (10000 centipaise), so 1 pt = ₹1.
  base rule 1 pt / ₹100
  bonus '₹5,000 spend / calendar_month → 500 pts'
  milestone: window 2026-01-01..2026-02-28 (2 months), target ₹5,000,
             benefit ₹600  → amortises ₹300/month when met
  annual fee ₹1,200 → amortises ₹100/month, NOT waived (no waiver milestone)

2026-01: one ₹10,000 debit
  accrual   = 100 pts × ₹1                    = ₹100   (10000 paise)
  bonus     = met (10000 ≥ 5000) → 500 pts    = ₹500   (50000 paise)
  milestone = met (window spend 10000 ≥ 5000) = ₹300   (30000 paise, 600/2)
  fee       = −₹100                            (−10000 paise)
  net       = 100 + 500 + 300 − 100 = ₹800    (80000 paise)
  spend ₹10,000 → rate 800/10000 = 8.00 %
2026-02: no txns → spend 0, rate None, but milestone still amortises ₹300
════════════════════════════════════════════════════════════════════════════
"""
import sqlite3

import pytest

import app as app_module
from rewards import reports
from rewards.engine import rebuild_all


@pytest.fixture()
def conn(client):
    c = sqlite3.connect(app_module.DB_PATH)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def _account(conn, name):
    return conn.execute(
        "INSERT INTO accounts (kind, name) VALUES ('credit_card', ?)", (name,)).lastrowid


def _txn(conn, account_id, date, desc, inr, type='debit', category='Shopping'):
    return conn.execute(
        'INSERT INTO transactions (account_id, date, description, amount_paise, type, category) '
        'VALUES (?,?,?,?,?,?)',
        (account_id, date, desc, int(round(inr * 100)), type, category)).lastrowid


def _points_program(conn, account_id, valid_from='2026-01-01', fee_inr=1200,
                    fee_waiver_milestone_id=None):
    pid = conn.execute(
        'INSERT INTO reward_programs (account_id, name, earn_currency, annual_fee_paise, '
        'fee_waiver_milestone_id, valid_from, valid_to) VALUES (?,?,?,?,?,?,NULL)',
        (account_id, 'Pts', 'points', fee_inr * 100, fee_waiver_milestone_id, valid_from)).lastrowid
    conn.execute("INSERT INTO redemption_routes (program_id, name, value_per_point_centipaise, "
                 "is_default) VALUES (?, 'Default', 10000, 1)", (pid,))
    conn.execute("INSERT INTO earn_rules (program_id, priority, kind, earn_numer, earn_denom_paise) "
                 "VALUES (?, 10, 'base', 1, 10000)", (pid,))
    return pid


def _snapshot(conn, account_id, as_of, value, label='Pts'):
    conn.execute("INSERT INTO reward_balances (account_id, as_of, label, value_minor, value_type, "
                 "source) VALUES (?,?,?,?,'points','statement')", (account_id, as_of, label, value))


@pytest.fixture()
def rate_card(conn):
    acc = _account(conn, 'RATE-CARD')
    pid = _points_program(conn, acc)
    conn.execute("INSERT INTO bonus_rules (program_id, name, period, min_spend_paise, bonus_units) "
                 "VALUES (?, '5000/mo -> 500', 'calendar_month', 500000, 500)", (pid,))
    conn.execute("INSERT INTO milestones (account_id, name, target_paise, window_start, "
                 "window_end, benefit_paise) VALUES (?, 'W', 500000, '2026-01-01', '2026-02-28', 60000)",
                 (acc,))
    _txn(conn, acc, '2026-01-15', 'BIG BUY', 10000)
    conn.commit()
    rebuild_all(conn)
    return {'account_id': acc, 'program_id': pid}


def test_effective_rate_full_formula_to_the_paisa(conn, rate_card):
    by_card_month, _ = reports.effective_rates(conn)
    jan = next(r for r in by_card_month if r['card_label'] == 'RATE-CARD' and r['month'] == '2026-01')
    assert jan['accrual_value_paise'] == 10000
    assert jan['bonus_value_paise'] == 50000
    assert jan['milestone_value_paise'] == 30000
    assert jan['fee_amort_paise'] == 10000
    assert jan['net_value_paise'] == 80000
    assert jan['spend_paise'] == 1000000
    assert jan['rate'] == pytest.approx(0.08)


def test_milestone_amortises_into_a_spendless_month(conn, rate_card):
    """2026-02 has no txns but the milestone window covers it — the ₹300
    still appears (rate None, since dividing value by zero spend is not a
    rate) rather than silently vanishing from the window aggregate."""
    by_card_month, _ = reports.effective_rates(conn)
    feb = next((r for r in by_card_month
                if r['card_label'] == 'RATE-CARD' and r['month'] == '2026-02'), None)
    assert feb is not None
    assert feb['milestone_value_paise'] == 30000
    assert feb['spend_paise'] == 0 and feb['rate'] is None


def test_fee_waived_when_waiver_milestone_met(conn):
    """A met fee-waiver milestone zeroes the amortised fee."""
    acc = _account(conn, 'WAIVE-CARD')
    mid = conn.execute("INSERT INTO milestones (account_id, name, target_paise, window_start, "
                       "window_end) VALUES (?, 'Fee Waiver', 500000, '2026-01-01', '2026-12-31')",
                       (acc,)).lastrowid
    _points_program(conn, acc, fee_inr=1200, fee_waiver_milestone_id=mid)
    _txn(conn, acc, '2026-01-15', 'SPEND', 10000)  # 10000 >= 5000 target → waiver met
    conn.commit()
    rebuild_all(conn)
    by_card_month, _ = reports.effective_rates(conn)
    jan = next(r for r in by_card_month if r['card_label'] == 'WAIVE-CARD' and r['month'] == '2026-01')
    assert jan['fee_amort_paise'] == 0


def test_category_rate_is_accrual_only(conn, rate_card):
    """Per-category rates carry accrual value only — no per-category fee or
    bonus attribution (spec M10: model-derived, marked as such)."""
    _, by_cat = reports.effective_rates(conn)
    row = next(r for r in by_cat if r['card_label'] == 'RATE-CARD'
               and r['month'] == '2026-01' and r['category'] == 'Shopping')
    assert row['accrual_value_paise'] == 10000
    assert row['spend_paise'] == 1000000
    assert row['rate'] == pytest.approx(0.01)  # base 1% only, no bonus/fee


def _recon_card(conn, name, modeled_spend_inr, actual_delta):
    """A card with two snapshots one month apart; `modeled_spend_inr` of
    debits fall inside the window (→ that many pts modeled at 1pt/₹100)."""
    acc = _account(conn, name)
    _points_program(conn, acc, fee_inr=0)
    _snapshot(conn, acc, '2026-01-01', 0)
    _snapshot(conn, acc, '2026-02-01', actual_delta)
    _txn(conn, acc, '2026-01-15', 'SPEND', modeled_spend_inr)
    conn.commit()
    return acc


def test_reconciliation_ok(conn):
    _recon_card(conn, 'OK-CARD', 10000, 100)  # ₹10000 → 100 pts modeled; actual +100
    rebuild_all(conn)
    r = next(x for x in reports.reconciliation(conn) if x['card_label'] == 'OK-CARD')
    assert r['modeled_units'] == 100 and r['actual_delta_units'] == 100
    assert r['status'] == 'ok'


def test_reconciliation_mismatch_when_model_underearns(conn):
    _recon_card(conn, 'UNDER-CARD', 10000, 300)  # modeled 100, actual 300 (>tol 50)
    rebuild_all(conn)
    r = next(x for x in reports.reconciliation(conn) if x['card_label'] == 'UNDER-CARD')
    assert r['status'] == 'mismatch'


def test_reconciliation_redemption_suspected_when_balance_falls_short(conn):
    _recon_card(conn, 'REDEEM-CARD', 10000, 0)  # modeled 100, actual 0 (balance didn't rise)
    rebuild_all(conn)
    r = next(x for x in reports.reconciliation(conn) if x['card_label'] == 'REDEEM-CARD')
    assert r['status'] == 'redemption_suspected'


def test_reconciliation_insufficient_history_with_one_snapshot(conn):
    acc = _account(conn, 'ONE-SNAP')
    _points_program(conn, acc, fee_inr=0)
    _snapshot(conn, acc, '2026-01-01', 500)
    conn.commit()
    rebuild_all(conn)
    r = next(x for x in reports.reconciliation(conn) if x['card_label'] == 'ONE-SNAP')
    assert r['status'] == 'insufficient_history'
    assert r['modeled_units'] is None


def test_reconciliation_counts_bonus_units_in_window(conn):
    """A met bonus landing inside the cycle is added to modeled units."""
    acc = _account(conn, 'BONUS-RECON')
    pid = _points_program(conn, acc, fee_inr=0)
    conn.execute("INSERT INTO bonus_rules (program_id, name, period, min_spend_paise, bonus_units) "
                 "VALUES (?, '5000/mo -> 500', 'calendar_month', 500000, 500)", (pid,))
    _snapshot(conn, acc, '2026-01-01', 0)
    _snapshot(conn, acc, '2026-02-01', 600)  # 100 base + 500 bonus = 600 modeled
    _txn(conn, acc, '2026-01-15', 'SPEND', 10000)
    conn.commit()
    rebuild_all(conn)
    r = next(x for x in reports.reconciliation(conn) if x['card_label'] == 'BONUS-RECON')
    assert r['modeled_units'] == 600 and r['status'] == 'ok'


def test_rates_summary_blends_across_cards(conn, rate_card):
    _recon_card(conn, 'SECOND-CARD', 20000, 200)
    rebuild_all(conn)
    s = reports.rates_summary(conn, '2026-01-01', '2026-02-28')
    labels = {c['card_label'] for c in s['by_card']}
    assert {'RATE-CARD', 'SECOND-CARD'} <= labels
    # blended = total net / total spend across the window, and each card
    # carries its latest reconciliation status
    assert s['blended_rate'] == pytest.approx(s['net_value_paise'] / s['spend_paise'])
    second = next(c for c in s['by_card'] if c['card_label'] == 'SECOND-CARD')
    assert second['recon_status'] in {'ok', 'mismatch', 'redemption_suspected'}


def test_rates_summary_filters_to_one_card(conn, rate_card):
    _recon_card(conn, 'OTHER', 20000, 200)
    rebuild_all(conn)
    s = reports.rates_summary(conn, '2026-01-01', '2026-02-28', card='RATE-CARD')
    assert [c['card_label'] for c in s['by_card']] == ['RATE-CARD']
