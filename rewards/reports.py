"""Effective rates + reconciliation (ADR-008 / M10 Job 2, task 5.4).

Everything here is DERIVED, computed on the fly from reward_accruals (the
5.3 engine's cache), bonus evaluation, milestones, and reward_balances —
nothing is stored.

**Effective rate** (spec M10): per card x month,
    (accrual value + threshold-bonus value + amortised milestone benefit
     - amortised annual fee if not waived) / net spend.
v1 attribution choices, documented because they're judgment calls:
  - Net spend = debits - refund credits (cashback posts and 'Credit Card
    Bills' payments excluded), same netting the dashboard summary uses.
  - A met bonus's value lands on the month its period ENDS (a quarterly
    bonus lands on the quarter's last month, statement-cycle bonuses on the
    statement's period_end month). one_time bonuses have no month to land
    on and are excluded from monthly rates.
  - The annual fee amortises at fee/12 per month shown, using the era
    active mid-month; waived (0) when the program's linked fee-waiver
    milestone's window target is actually met.
  - A milestone benefit amortises evenly over its window's months, counted
    only for months inside the window and only when the target is MET
    (ADR-008) and benefit_paise is recorded.
  - Per card x category x month rates carry accrual value only — fees and
    bonuses are card-level facts with no honest per-category attribution
    (spec M10: "per-category rates are model-derived and marked as such").

**Reconciliation** (spec M10): per card, each consecutive pair of
reward_balances snapshots is a cycle: modeled units (accruals for txns in
(prev.as_of, cur.as_of] + met bonuses landing in that window) vs the actual
balance delta. Tolerance = max(50 units, 5% of modeled) (ADR-008). Statuses:
  ok                    within tolerance
  mismatch              actual > modeled + tolerance (model under-earns:
                        rules typo, parser gap, or an unrecorded bonus)
  redemption_suspected  actual < modeled - tolerance (balance fell short —
                        points were likely redeemed between snapshots;
                        statements don't itemise redemptions)
  insufficient_history  fewer than two snapshots — no delta to check
"""
import datetime

from .engine import _era_for, _load_eras, evaluate_bonuses

# Netting matches the dashboard summary: bills are money movements, cashback
# posts are reward postings — neither is spend.
_SPEND_WHERE = ("t.is_cashback=0 AND t.category != 'Credit Card Bills'")


def _month_add(month, n):
    y, m = int(month[:4]), int(month[5:7])
    m += n
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return f'{y:04d}-{m:02d}'


def _window_months(start, end):
    """Inclusive list of 'YYYY-MM' months covered by [start, end]."""
    months, cur = [], start[:7]
    while cur <= end[:7]:
        months.append(cur)
        cur = _month_add(cur, 1)
    return months


def _month_end(month):
    """Last calendar day of a 'YYYY-MM' month, as 'YYYY-MM-DD'."""
    first_next = datetime.date(int(month[:4]), int(month[5:7]), 1)
    first_next = (first_next.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return (first_next - datetime.timedelta(days=1)).isoformat()


def _bonus_land_date(bonus, conn):
    """Full date a met bonus's value lands on — its period's LAST day, so a
    reconciliation window's date comparison places it in the right cycle. A
    monthly bonus for spend in month M lands at month-end (the bank posts it
    once M closes). None for one_time (nowhere honest to put it)."""
    kind, *rest = bonus['period_token']
    if kind == 'cm':
        return _month_end(rest[0])
    if kind == 'cq':
        year, q = rest[0].split('-Q')
        return _month_end(f'{year}-{int(q) * 3:02d}')
    if kind == 'cy':
        return f'{rest[0]}-12-31'
    if kind == 'stmt':
        row = conn.execute('SELECT period_end FROM statements WHERE id=?', (rest[0],)).fetchone()
        return row['period_end'] if row else None
    return None  # 'once'


def _milestone_state(conn, milestone_id):
    """(met, benefit_paise, window_months) for a milestone, computing spend
    progress live over its window — or None if the id is unknown."""
    m = conn.execute('SELECT * FROM milestones WHERE id=?', (milestone_id,)).fetchone()
    if m is None:
        return None
    progress = conn.execute(
        f"SELECT COALESCE(SUM(amount_paise), 0) s FROM transactions t "
        f"WHERE t.account_id=? AND t.type='debit' AND {_SPEND_WHERE} "
        f"AND t.date >= ? AND t.date <= ?",
        (m['account_id'], m['window_start'], m['window_end'])).fetchone()['s']
    return {
        'met': progress >= m['target_paise'],
        'benefit_paise': m['benefit_paise'],
        'months': _window_months(m['window_start'], m['window_end']),
        'account_id': m['account_id'],
    }


def _fee_waived(conn, era):
    if era['fee_waiver_milestone_id'] is None:
        return False
    state = _milestone_state(conn, era['fee_waiver_milestone_id'])
    return bool(state and state['met'])


def effective_rates(conn):
    """Returns (by_card_month, by_card_category_month) — see module
    docstring for the formula and attribution choices."""
    accounts = conn.execute(
        'SELECT DISTINCT rp.account_id, a.name FROM reward_programs rp '
        'JOIN accounts a ON a.id = rp.account_id ORDER BY a.name').fetchall()
    bonuses = evaluate_bonuses(conn)

    by_card_month, by_card_category_month = [], []
    for acct in accounts:
        acc_id, card = acct['account_id'], acct['name']
        eras = _load_eras(conn, acc_id)

        spend = {r['month']: r for r in conn.execute(
            f"SELECT SUBSTR(t.date,1,7) month, "
            f"SUM(CASE WHEN t.type='debit' THEN t.amount_paise ELSE -t.amount_paise END) net_paise "
            f"FROM transactions t WHERE t.account_id=? AND {_SPEND_WHERE} "
            f"GROUP BY month", (acc_id,)).fetchall()}
        accrual = {r['month']: r['value_paise'] for r in conn.execute(
            'SELECT SUBSTR(t.date,1,7) month, SUM(ra.value_paise) value_paise '
            'FROM reward_accruals ra JOIN transactions t ON t.id = ra.txn_id '
            'JOIN reward_programs rp ON rp.id = ra.program_id '
            'WHERE rp.account_id=? GROUP BY month', (acc_id,)).fetchall()}

        bonus_by_month = {}
        for b in bonuses:
            if b['account_id'] != acc_id or not b['met']:
                continue
            land = _bonus_land_date(b, conn)
            if land is not None:
                month = land[:7]
                bonus_by_month[month] = bonus_by_month.get(month, 0) + b['value_paise']

        # Milestone benefit amortisation (met + benefit_paise recorded only)
        milestone_by_month = {}
        for m in conn.execute(
                'SELECT id FROM milestones WHERE account_id=? AND benefit_paise IS NOT NULL',
                (acc_id,)).fetchall():
            state = _milestone_state(conn, m['id'])
            if state and state['met']:
                per_month = state['benefit_paise'] // len(state['months'])
                for month in state['months']:
                    milestone_by_month[month] = milestone_by_month.get(month, 0) + per_month

        months = sorted(set(spend) | set(accrual) | set(bonus_by_month) | set(milestone_by_month))
        for month in months:
            era, _ = _era_for(eras, f'{month}-15')
            fee_amort = 0
            if era is not None and era['annual_fee_paise'] and not _fee_waived(conn, era):
                fee_amort = era['annual_fee_paise'] // 12
            spend_paise = spend[month]['net_paise'] if month in spend else 0
            accrual_paise = accrual.get(month, 0)
            bonus_paise = bonus_by_month.get(month, 0)
            milestone_paise = milestone_by_month.get(month, 0)
            net = accrual_paise + bonus_paise + milestone_paise - fee_amort
            by_card_month.append({
                'account_id': acc_id, 'card_label': card, 'month': month,
                'spend_paise': spend_paise, 'accrual_value_paise': accrual_paise,
                'bonus_value_paise': bonus_paise, 'milestone_value_paise': milestone_paise,
                'fee_amort_paise': fee_amort, 'net_value_paise': net,
                'rate': (net / spend_paise) if spend_paise > 0 else None,
            })

        # Category level: accrual value / spend only (model-derived; no
        # honest fee/bonus attribution per category — see docstring).
        for r in conn.execute(
                f"SELECT SUBSTR(t.date,1,7) month, t.category, "
                f"SUM(CASE WHEN t.type='debit' THEN t.amount_paise ELSE -t.amount_paise END) spend_paise, "
                f"SUM(COALESCE(ra.value_paise, 0)) accrual_value_paise "
                f"FROM transactions t "
                f"LEFT JOIN reward_accruals ra ON ra.txn_id = t.id "
                f"WHERE t.account_id=? AND {_SPEND_WHERE} "
                f"GROUP BY month, t.category ORDER BY month, t.category", (acc_id,)).fetchall():
            by_card_category_month.append({
                'account_id': acc_id, 'card_label': card, 'month': r['month'],
                'category': r['category'], 'spend_paise': r['spend_paise'],
                'accrual_value_paise': r['accrual_value_paise'],
                'rate': (r['accrual_value_paise'] / r['spend_paise']) if r['spend_paise'] > 0 else None,
            })
    return by_card_month, by_card_category_month


def reconciliation(conn):
    """Per card, per consecutive-snapshot cycle: modeled vs actual units.
    See module docstring for statuses and tolerance."""
    bonuses = evaluate_bonuses(conn)
    results = []
    accounts = conn.execute(
        'SELECT DISTINCT rp.account_id, a.name FROM reward_programs rp '
        'JOIN accounts a ON a.id = rp.account_id ORDER BY a.name').fetchall()
    for acct in accounts:
        acc_id, card = acct['account_id'], acct['name']
        snaps = conn.execute(
            'SELECT as_of, label, value_minor, value_type FROM reward_balances '
            'WHERE account_id=? ORDER BY as_of', (acc_id,)).fetchall()
        if len(snaps) < 2:
            results.append({
                'account_id': acc_id, 'card_label': card, 'status': 'insufficient_history',
                'snapshots': len(snaps),
                'window_start': None, 'window_end': snaps[0]['as_of'] if snaps else None,
                'modeled_units': None, 'actual_delta_units': None, 'tolerance_units': None,
            })
            continue
        for prev, cur in zip(snaps, snaps[1:]):
            modeled = conn.execute(
                'SELECT COALESCE(SUM(ra.units_earned), 0) u '
                'FROM reward_accruals ra JOIN transactions t ON t.id = ra.txn_id '
                'WHERE t.account_id=? AND t.date > ? AND t.date <= ?',
                (acc_id, prev['as_of'], cur['as_of'])).fetchone()['u']
            for b in bonuses:
                if b['account_id'] != acc_id or not b['met']:
                    continue
                land = _bonus_land_date(b, conn)
                if land is not None and prev['as_of'] < land <= cur['as_of']:
                    modeled += b['bonus_units']
            actual = cur['value_minor'] - prev['value_minor']
            tolerance = max(50, abs(modeled) * 5 // 100)
            if abs(actual - modeled) <= tolerance:
                status = 'ok'
            elif actual < modeled:
                status = 'redemption_suspected'
            else:
                status = 'mismatch'
            results.append({
                'account_id': acc_id, 'card_label': card, 'status': status,
                'snapshots': len(snaps),
                'window_start': prev['as_of'], 'window_end': cur['as_of'],
                'modeled_units': modeled, 'actual_delta_units': actual,
                'tolerance_units': tolerance,
            })
    return results


def rates_summary(conn, from_date, to_date, card=None):
    """Blended + per-card effective rate over [from_date, to_date] for the
    dashboard hero and By-card panel — same formula, arbitrary window (fee
    amortised per month the window touches), with each card's latest
    reconciliation status attached."""
    months = _window_months(from_date, to_date)
    by_card_month, _ = effective_rates(conn)
    recon = reconciliation(conn)
    latest_status = {}
    for r in recon:  # rows are chronological per card; last one wins
        latest_status[r['card_label']] = r['status']

    per_card = {}
    for row in by_card_month:
        if row['month'] not in months:
            continue
        if card and row['card_label'] != card:
            continue
        agg = per_card.setdefault(row['card_label'], {
            'card_label': row['card_label'], 'spend_paise': 0, 'net_value_paise': 0})
        agg['spend_paise'] += row['spend_paise']
        agg['net_value_paise'] += row['net_value_paise']

    cards_out = []
    for label in sorted(per_card):
        agg = per_card[label]
        agg['rate'] = (agg['net_value_paise'] / agg['spend_paise']) if agg['spend_paise'] > 0 else None
        agg['recon_status'] = latest_status.get(label, 'insufficient_history')
        cards_out.append(agg)

    total_spend = sum(c['spend_paise'] for c in cards_out)
    total_net = sum(c['net_value_paise'] for c in cards_out)
    return {
        'from_date': from_date, 'to_date': to_date,
        'blended_rate': (total_net / total_spend) if total_spend > 0 else None,
        'net_value_paise': total_net, 'spend_paise': total_spend,
        'by_card': cards_out,
        'computed_at': datetime.datetime.now().isoformat(timespec='seconds'),
    }
