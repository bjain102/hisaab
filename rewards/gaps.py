"""Gap report + forward guidance (ADR-008 / M10 Job 3, task 5.5).

The counterfactual the app exists for: per (category, month), what the spend
actually earned vs what the best single card would have earned — CAP-AWARE,
so the report never claims value a cap would have eaten (ADR-008's explicit
rejection of naive rate comparison).

Semantics (ADR-008, restated):
  - Greedy per (category, month), NOT a joint optimisation across
    categories: each category's counterfactual moves ONLY that category's
    transactions; everything else stays where it really happened.
  - A candidate card's hypothetical earn = its rules applied to the
    category's real transactions (first-match, same engine primitives),
    capped by its REMAINING headroom: cap minus what the candidate's own
    actual other spend already consumed that month.
  - Exclusion rules make a candidate ineligible for the category (a card
    that excludes Rent can't be "best" for Rent).
  - Loss = best candidate value − actual value, floored at 0.

v1 caveats (returned by the API and displayed on the report — spec M10):
  - Counterfactuals ignore threshold-bonus and milestone side-effects
    (moving spend off a card might cost a bonus or fee waiver there).
  - Caps are evaluated per calendar month in counterfactuals (a moved
    transaction has no statement cycle on the candidate card). All real
    capped rules today are monthly/statement-cycle, so this is exact under
    the engine's own documented fallback; quarterly/annual caps would be
    approximated month-locally.
  - Gap math uses confirmed-category spend only (category_source
    'confirmed'/'manual' — same footing as the trust meter); the trust
    share is reported alongside.
  - Debits only; refunds are ignored on both sides of the comparison.
"""
import datetime

from categorization.normalize import normalize

from .engine import _era_for, _load_eras, _match_rule, _uncapped_units, _value_paise

CAVEATS = [
    "Counterfactuals ignore threshold-bonus and milestone side-effects — moving spend off a card might cost a bonus or fee waiver there.",
    "Caps are evaluated per calendar month in the counterfactual (moved spend has no statement cycle on the candidate card).",
    "Gap math uses confirmed-category spend only (the trust meter's footing); unconfirmed spend is not counted against any card.",
    "Best-card is chosen per category independently, not as a joint optimisation across categories.",
]

# Never gap-analyzed: not discretionary card spend.
_SKIP_CATEGORIES = ("Credit Card Bills", "Reversals & Refunds")


def _month_bounds(month):
    start = f'{month}-01'
    y, m = int(month[:4]), int(month[5:7])
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return start, f'{y:04d}-{m:02d}-01'  # [start, next_month_start)


def _bucket_group(rule):
    return rule['cap_group'] or f"rule:{rule['id']}"


def _consume(rule, used, amount_paise):
    """Earned units for one txn under `rule` given month-local bucket state
    `used` (mutated). Uncapped rules never touch buckets."""
    uncapped = _uncapped_units(rule, amount_paise)
    if rule['cap_units'] is None or uncapped <= 0:
        return uncapped
    group = _bucket_group(rule)
    remaining = max(0, rule['cap_units'] - used.get(group, 0))
    earned = min(uncapped, remaining)
    used[group] = used.get(group, 0) + earned
    return earned


def _seed_usage(era, own_txns):
    """Month-local cap usage from the candidate's own real spend (the txns
    NOT being moved). Returns the bucket dict the hypothetical continues
    from."""
    used = {}
    for t in own_txns:
        rule = _match_rule(era['rules'], t['category'], t['norm'], t['amount_paise'])
        if rule is not None and rule['kind'] != 'excluded':
            _consume(rule, used, t['amount_paise'])
    return used


def _hypothetical(era, cat_txns, used):
    """(value_paise, matched_any, top_rule_id) — the category's txns pushed
    through `era`'s rules from bucket state `used`. top_rule_id is the rule
    contributing the most value (drives the guidance headroom display)."""
    value, matched_any = 0, False
    by_rule = {}
    for t in cat_txns:
        rule = _match_rule(era['rules'], t['category'], t['norm'], t['amount_paise'])
        if rule is None or rule['kind'] == 'excluded':
            continue
        matched_any = True
        earned = _consume(rule, used, t['amount_paise'])
        v = _value_paise(earned, era)
        value += v
        by_rule[rule['id']] = by_rule.get(rule['id'], 0) + v
    top_rule_id = max(by_rule, key=by_rule.get) if by_rule else None
    return value, matched_any, top_rule_id


def _load_month_txns(conn, month):
    """All gap-eligible txns for the month: confirmed-footing debits, with
    normalized descriptions precomputed. Grouped by nothing — callers
    filter."""
    start, end = _month_bounds(month)
    rows = conn.execute(
        "SELECT t.id, t.date, t.description, t.raw_description, t.amount_paise, t.category, "
        "t.account_id, a.name card_label "
        "FROM transactions t JOIN accounts a ON a.id = t.account_id "
        "WHERE t.type='debit' AND t.is_cashback=0 "
        "AND t.category_source IN ('confirmed','manual') "
        "AND t.date >= ? AND t.date < ? ORDER BY t.date, t.id", (start, end)).fetchall()
    txns = []
    for r in rows:
        t = dict(r)
        t['norm'] = normalize(t['raw_description'] or t['description'])
        txns.append(t)
    return txns


def _candidates(conn):
    """[(account_id, card_label, eras)] for every account with seeded rules."""
    out = []
    for r in conn.execute(
            'SELECT DISTINCT rp.account_id, a.name FROM reward_programs rp '
            'JOIN accounts a ON a.id = rp.account_id ORDER BY a.name').fetchall():
        out.append((r['account_id'], r['name'], _load_eras(conn, r['account_id'])))
    return out


def _month_gap_rows(conn, month, candidates):
    """The counterfactual for one month: one row per category with spend."""
    txns = _load_month_txns(conn, month)
    categories = sorted({t['category'] for t in txns} - set(_SKIP_CATEGORIES))
    rows = []
    for cat in categories:
        cat_txns = [t for t in txns if t['category'] == cat]
        cat_ids = {t['id'] for t in cat_txns}
        spend = sum(t['amount_paise'] for t in cat_txns)
        if spend <= 0:
            continue
        qmarks = ','.join('?' * len(cat_ids))
        actual_value = conn.execute(
            f'SELECT COALESCE(SUM(value_paise),0) v FROM reward_accruals WHERE txn_id IN ({qmarks})',
            list(cat_ids)).fetchone()['v']

        by_card = {}
        for t in cat_txns:
            agg = by_card.setdefault(t['card_label'], {'card_label': t['card_label'], 'spend_paise': 0})
            agg['spend_paise'] += t['amount_paise']
        actual_cards = sorted(by_card.values(), key=lambda c: -c['spend_paise'])

        best = None
        for acc_id, label, eras in candidates:
            era, _ = _era_for(eras, f'{month}-15')
            if era is None:
                continue
            own = [t for t in txns if t['account_id'] == acc_id and t['id'] not in cat_ids]
            used = _seed_usage(era, own)
            headroom = {  # value of remaining capped headroom BEFORE the move
                _bucket_group(r): max(0, r['cap_units'] - used.get(_bucket_group(r), 0))
                for r in era['rules'] if r['cap_units'] is not None}
            value, matched, top_rule = _hypothetical(era, cat_txns, used)
            if not matched:
                continue  # excluded / no rule for this category -> ineligible
            if best is None or value > best['value']:
                top = next((r for r in era['rules'] if r['id'] == top_rule), None)
                head_units = headroom.get(_bucket_group(top)) if (top is not None and top['cap_units'] is not None) else None
                best = {'card_label': label, 'value': value,
                        'headroom_value_paise': _value_paise(head_units, era) if head_units is not None else None}

        if best is None:
            continue  # nothing eligible (every card excludes the category)
        loss = max(0, best['value'] - actual_value)
        rows.append({
            'month': month, 'category': cat, 'spend_paise': spend,
            'txn_count': len(cat_txns), 'actual_value_paise': actual_value,
            'actual_rate': (actual_value / spend) if spend else None,
            'actual_cards': actual_cards,
            'best_card': best['card_label'], 'best_value_paise': best['value'],
            'best_rate': (best['value'] / spend) if spend else None,
            'best_headroom_value_paise': best['headroom_value_paise'],
            'loss_paise': loss,
        })
    rows.sort(key=lambda r: -r['loss_paise'])
    return rows


def _recent_months(conn, n):
    row = conn.execute("SELECT MAX(date) d FROM transactions WHERE type='debit'").fetchone()
    if not row['d']:
        return []
    months = []
    y, m = int(row['d'][:4]), int(row['d'][5:7])
    for _ in range(n):
        months.append(f'{y:04d}-{m:02d}')
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return list(reversed(months))


def gap_report(conn, months_back=6):
    """The Job-3 report: per-month gap rows (latest last), monthly loss
    totals, the trust share of the analyzed window, and the v1 caveats."""
    candidates = _candidates(conn)
    months = _recent_months(conn, months_back)
    out_months = []
    for month in months:
        rows = _month_gap_rows(conn, month, candidates)
        out_months.append({
            'month': month,
            'total_loss_paise': sum(r['loss_paise'] for r in rows),
            'rows': rows,
        })

    start = f'{months[0]}-01' if months else '2000-01-01'
    gross = conn.execute(
        "SELECT COALESCE(SUM(amount_paise),0) s FROM transactions "
        "WHERE type='debit' AND is_cashback=0 AND category != 'Credit Card Bills' "
        "AND date >= ?", (start,)).fetchone()['s']
    trusted = conn.execute(
        "SELECT COALESCE(SUM(amount_paise),0) s FROM transactions "
        "WHERE type='debit' AND is_cashback=0 AND category != 'Credit Card Bills' "
        "AND category_source IN ('confirmed','manual') AND date >= ?", (start,)).fetchone()['s']
    return {
        'months': out_months,
        'trust': (trusted / gross) if gross else 0.0,
        'caveats': CAVEATS,
        'computed_at': datetime.datetime.now().isoformat(timespec='seconds'),
    }


def guidance(conn, lookback_months=3, min_spend_paise=100000):
    """Forward guidance: per recent category, the best card by the trailing
    counterfactual, with LIVE remaining cap headroom this calendar month.
    Categories below `min_spend_paise` of trailing spend are noise, not
    guidance."""
    candidates = _candidates(conn)
    months = _recent_months(conn, lookback_months + 1)
    if not months:
        return []
    current_month, complete = months[-1], months[:-1]

    # Trailing counterfactual: total hypothetical value per (category, card)
    totals, spend_by_cat = {}, {}
    for month in complete:
        # _month_gap_rows reports each category's best card — that's what
        # guidance ranks on: best-card wins per month, value-weighted.
        for row in _month_gap_rows(conn, month, candidates):
            spend_by_cat[row['category']] = spend_by_cat.get(row['category'], 0) + row['spend_paise']
            key = (row['category'], row['best_card'])
            totals[key] = totals.get(key, 0) + row['best_value_paise']

    out = []
    for cat in sorted(spend_by_cat):
        if spend_by_cat[cat] < min_spend_paise:
            continue
        picks = {card: v for (c, card), v in totals.items() if c == cat}
        if not picks:
            continue
        card = max(picks, key=picks.get)
        acc_id, label, eras = next(c for c in candidates if c[1] == card)
        era, _ = _era_for(eras, f'{current_month}-15')
        if era is None:
            continue
        # Live headroom: the card's real current-month spend consumes caps.
        cur_txns = [t for t in _load_month_txns(conn, current_month) if t['account_id'] == acc_id]
        used = _seed_usage(era, cur_txns)
        # Headroom of the rule this category would actually hit (probe with a
        # representative txn: the category's biggest trailing txn shape).
        probe = conn.execute(
            "SELECT description, raw_description, amount_paise FROM transactions "
            "WHERE type='debit' AND is_cashback=0 AND category=? "
            "ORDER BY date DESC LIMIT 1", (cat,)).fetchone()
        headroom_value = None
        if probe:
            norm = normalize(probe['raw_description'] or probe['description'])
            rule = _match_rule(era['rules'], cat, norm, probe['amount_paise'])
            if rule is not None and rule['kind'] != 'excluded' and rule['cap_units'] is not None:
                remaining = max(0, rule['cap_units'] - used.get(_bucket_group(rule), 0))
                headroom_value = _value_paise(remaining, era)
        out.append({
            'category': cat, 'card_label': card,
            'trailing_spend_paise': spend_by_cat[cat],
            'trailing_rate': (picks[card] / spend_by_cat[cat]) if spend_by_cat[cat] else None,
            'headroom_value_paise': headroom_value,  # None = uncapped
        })
    out.sort(key=lambda r: -r['trailing_spend_paise'])
    return out
