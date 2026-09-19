"""Accrual engine (ADR-008, task 5.3).

Computes `reward_accruals` — one row per transaction — from the seeded rules
(reward_programs / earn_rules / redemption_routes) and the transactions
table. Accruals are a DERIVED CACHE: `rebuild_all` deletes and recomputes
everything deterministically (same inputs -> byte-identical outputs except
`computed_at`), which is also how rule edits and transaction deletes stay
consistent — app.py calls it after every write that changes engine inputs.

ADR-008 semantics implemented here, with the v1 judgment calls spelled out:

- **Era selection by date**: the program row whose [valid_from, valid_to)
  window contains the transaction date. valid_to IS NULL = current era.
- **Pre-first-era transactions**: an account's EARLIEST era extends backward
  to cover transactions before its valid_from, flagged in the notes. Most
  real eras start at `researched_on` (the YAML's rules_effective_from was
  UNKNOWN), so a strict reading would leave the entire imported history —
  the data the gap report exists to analyze — with no accruals at all.
  Extending the earliest KNOWN rules backward is the pragmatic reading;
  5.4's reconciliation loop is the honesty check on it. Devaluation
  boundaries BETWEEN eras remain strict.
- **First-match-wins**: earn_rules by priority ASC; a rule matches when its
  category (NULL = any) equals the txn's, every merchant_match token check
  passes (any comma-token substring-matches the ADR-009-normalized
  description; merchant_match_exclude tokens carve the rule out), and the
  txn meets min_txn_paise. `excluded` rules match and earn 0 — explicit,
  traceable zeroes (rule_id points at the exclusion).
- **Units**: floor(amount_paise * earn_numer / earn_denom_paise) — banks
  floor per transaction. For cashback_inr programs units ARE paise.
- **Caps**: accrued into buckets keyed by (program, cap_group-or-rule,
  period). `statement_cycle` uses the txn's statement period; txns with no
  statement_id fall back to calendar month, flagged once per program.
  `anniversary_*` periods fall back to their calendar equivalents, flagged —
  the card-anniversary date isn't in the data. units_uncapped - units_earned
  is the visible "lost to cap".
- **Refunds** (credit, not cashback, not 'Credit Card Bills'): if a prior
  debit with the same normalized description AND amount has an accrual, the
  refund reverses exactly that accrual (negative row, same rule) and
  restores the original cap bucket's headroom; each prior accrual can be
  reversed once. Otherwise the refund "reduces the category pool": it's
  matched against the rules like a debit and reversed at that rate,
  uncapped. Banks claw back points on refunds; statements can't show which
  earn was clawed — reconciliation (5.4) is the honesty check (ADR-008).
- **value_paise**: units at the program's default redemption route
  (centipaise per point / 100); identity for cashback_inr.
- **Bonus rules** are evaluated per period on the fly (`evaluate_bonuses`)
  and NOT cached in reward_accruals (they're program-period facts, not
  per-txn facts). v1 simplification, documented: refunds don't reduce a
  period's bonus-qualifying spend/count.
"""
import datetime

from categorization.normalize import normalize

# Credits in these buckets are not refunds of card spend: bill payments are
# money in, cashback credits are reward postings (both already excluded from
# net-spend math elsewhere in the app for the same reason).
_NON_REFUND_CREDIT_CATEGORIES = {'Credit Card Bills'}


def _period_token(period, txn, flags):
    """Bucket token for a cap/bonus period. `flags` is a per-program set of
    fallback markers (emitted as notes once, not per txn)."""
    date = txn['date']
    if period == 'statement_cycle':
        if txn['statement_id'] is not None:
            return ('stmt', txn['statement_id'])
        flags.add('statement_cycle->calendar_month')
        return ('cm', date[:7])
    if period == 'calendar_month':
        return ('cm', date[:7])
    if period in ('calendar_quarter', 'anniversary_quarter'):
        if period == 'anniversary_quarter':
            flags.add('anniversary_quarter->calendar_quarter')
        return ('cq', f"{date[:4]}-Q{(int(date[5:7]) - 1) // 3 + 1}")
    if period in ('calendar_year', 'anniversary_year'):
        if period == 'anniversary_year':
            flags.add('anniversary_year->calendar_year')
        return ('cy', date[:4])
    return ('once',)  # one_time: one bucket for the whole era


def _match_rule(rules, category, norm_desc, amount_paise):
    """First match wins (ADR-008): category, then merchant_match, then
    min_txn. Returns the rule row or None."""
    for r in rules:
        if r['category'] is not None and r['category'] != category:
            continue
        if r['merchant_match']:
            if not any(tok in norm_desc for tok in r['merchant_match'].split(',')):
                continue
        if r['merchant_match_exclude']:
            if any(tok in norm_desc for tok in r['merchant_match_exclude'].split(',')):
                continue
        if r['min_txn_paise'] is not None and amount_paise < r['min_txn_paise']:
            continue
        return r
    return None


def _uncapped_units(rule, amount_paise):
    if rule['kind'] == 'excluded':
        return 0
    return amount_paise * rule['earn_numer'] // rule['earn_denom_paise']


def _value_paise(units, era):
    """Positive units only — callers negate for reversals so flooring stays
    symmetric around zero."""
    if era['earn_currency'] == 'cashback_inr':
        return units
    vpp = era['default_vpp_centipaise']
    return units * vpp // 100 if vpp is not None else 0


def _load_eras(conn, account_id):
    eras = [dict(r) for r in conn.execute(
        'SELECT * FROM reward_programs WHERE account_id=? ORDER BY valid_from',
        (account_id,)).fetchall()]
    for era in eras:
        era['rules'] = [dict(r) for r in conn.execute(
            'SELECT * FROM earn_rules WHERE program_id=? ORDER BY priority',
            (era['id'],)).fetchall()]
        row = conn.execute(
            'SELECT value_per_point_centipaise FROM redemption_routes '
            'WHERE program_id=? AND is_default=1 LIMIT 1', (era['id'],)).fetchone()
        era['default_vpp_centipaise'] = row['value_per_point_centipaise'] if row else None
    return eras


def _era_for(eras, date):
    """Era covering `date`; the earliest era extends backward (see module
    docstring). Returns (era_or_None, extended_backward: bool)."""
    if not eras:
        return None, False
    if date < eras[0]['valid_from']:
        return eras[0], True
    for era in eras:
        if era['valid_from'] <= date and (era['valid_to'] is None or date < era['valid_to']):
            return era, False
    return None, False


def _rebuild_account(conn, account_id, notes):
    eras = _load_eras(conn, account_id)
    if not eras:
        return 0
    account_name = conn.execute(
        'SELECT name FROM accounts WHERE id=?', (account_id,)).fetchone()['name']
    txns = conn.execute(
        'SELECT id, date, description, raw_description, amount_paise, type, category, '
        'is_cashback, statement_id FROM transactions WHERE account_id=? ORDER BY date, id',
        (account_id,)).fetchall()

    bucket_used = {}          # (program_id, group_token, period_token) -> units
    reversible = {}           # (norm_desc, amount_paise) -> last accrual info, popped on reversal
    flags = set()             # period fallbacks, noted once per account
    n_backdated = 0
    rows = []
    computed_at = datetime.datetime.now().isoformat(timespec='seconds')

    def bucket_key(era, rule, txn):
        group = rule['cap_group'] or f"rule:{rule['id']}"
        return (era['id'], group, _period_token(rule['cap_period'], txn, flags))

    for txn in txns:
        if txn['is_cashback']:
            continue
        norm = normalize(txn['raw_description'] or txn['description'])

        if txn['type'] == 'debit':
            era, extended = _era_for(eras, txn['date'])
            if era is None:
                continue
            if extended:
                n_backdated += 1
            rule = _match_rule(era['rules'], txn['category'], norm, txn['amount_paise'])
            if rule is None:
                # No rule matched at all (a program with no base catch-all):
                # record the zero so the txn is visibly unmodeled, not missing.
                rows.append((txn['id'], era['id'], None, 0, 0, 0, computed_at))
                continue
            uncapped = _uncapped_units(rule, txn['amount_paise'])
            earned = uncapped
            if rule['cap_units'] is not None and uncapped > 0:
                key = bucket_key(era, rule, txn)
                used = bucket_used.get(key, 0)
                earned = max(0, min(uncapped, rule['cap_units'] - used))
                bucket_used[key] = used + earned
            value = _value_paise(earned, era)
            rows.append((txn['id'], era['id'], rule['id'], earned, uncapped, value, computed_at))
            if earned or uncapped:
                reversible[(norm, txn['amount_paise'])] = {
                    'rule': rule, 'era': era, 'earned': earned,
                    'uncapped': uncapped, 'value': value,
                    'bucket': bucket_key(era, rule, txn) if rule['cap_units'] is not None else None,
                }
        elif txn['type'] == 'credit' and txn['category'] not in _NON_REFUND_CREDIT_CATEGORIES:
            matched = reversible.pop((norm, txn['amount_paise']), None)
            if matched:
                rows.append((txn['id'], matched['era']['id'], matched['rule']['id'],
                             -matched['earned'], -matched['uncapped'], -matched['value'],
                             computed_at))
                if matched['bucket'] is not None:
                    bucket_used[matched['bucket']] -= matched['earned']
            else:
                era, _ = _era_for(eras, txn['date'])
                if era is None:
                    continue
                rule = _match_rule(era['rules'], txn['category'], norm, txn['amount_paise'])
                if rule is None:
                    continue
                units = _uncapped_units(rule, txn['amount_paise'])
                value = _value_paise(units, era)
                rows.append((txn['id'], era['id'], rule['id'], -units, -units, -value,
                             computed_at))
                if rule['cap_units'] is not None and units:
                    key = bucket_key(era, rule, txn)
                    bucket_used[key] = bucket_used.get(key, 0) - units

    conn.executemany(
        'INSERT INTO reward_accruals (txn_id, program_id, rule_id, units_earned, '
        'units_uncapped, value_paise, computed_at) VALUES (?,?,?,?,?,?,?)', rows)

    if n_backdated:
        notes.append(f"{account_name}: {n_backdated} txns predate the first era's valid_from "
                     f"({eras[0]['valid_from']}) — earliest researched rules extended backward")
    for f in sorted(flags):
        notes.append(f"{account_name}: cap-period fallback {f} used")
    return len(rows)


def rebuild_all(conn, commit=True):
    """Delete and deterministically recompute every reward_accruals row.
    Returns (row_count, notes). This is the ONLY writer of reward_accruals —
    orphans from transaction deletes vanish here too (PRAGMA foreign_keys is
    never ON in this app, so the schema's ON DELETE CASCADE never fires)."""
    notes = []
    conn.execute('DELETE FROM reward_accruals')
    accounts = conn.execute(
        'SELECT DISTINCT account_id FROM reward_programs ORDER BY account_id').fetchall()
    total = 0
    for a in accounts:
        total += _rebuild_account(conn, a['account_id'], notes)
    if commit:
        conn.commit()
    return total, notes


def evaluate_bonuses(conn, account_id=None):
    """Per-period bonus evaluation, computed on the fly (never cached).
    Returns a list of dicts: one per (bonus rule, period) that has any
    transactions, with met/missed, the qualifying count, the period's total
    spend, and the bonus's default-route value when met. 5.4's reports and
    reconciliation consume this alongside the accrual rows."""
    where, params = '', ()
    if account_id is not None:
        where, params = 'WHERE rp.account_id=?', (account_id,)
    programs = conn.execute(
        f'SELECT DISTINCT rp.account_id FROM reward_programs rp {where}', params).fetchall()

    results = []
    for prog in programs:
        acc_id = prog['account_id']
        eras = _load_eras(conn, acc_id)
        txns = conn.execute(
            "SELECT id, date, amount_paise, statement_id FROM transactions "
            "WHERE account_id=? AND type='debit' AND is_cashback=0 ORDER BY date, id",
            (acc_id,)).fetchall()
        for era in eras:
            bonuses = conn.execute(
                'SELECT * FROM bonus_rules WHERE program_id=?', (era['id'],)).fetchall()
            if not bonuses:
                continue
            era_txns = []
            for t in txns:
                t_era, _ = _era_for(eras, t['date'])
                if t_era is not None and t_era['id'] == era['id']:
                    era_txns.append(t)
            for b in bonuses:
                flags = set()
                periods = {}
                for t in era_txns:
                    periods.setdefault(_period_token(b['period'], t, flags), []).append(t)
                for token, period_txns in sorted(periods.items()):
                    spend = sum(t['amount_paise'] for t in period_txns)
                    min_amt = b['min_txn_paise'] or 0
                    count = sum(1 for t in period_txns if t['amount_paise'] >= min_amt)
                    met = ((b['min_txn_count'] is None or count >= b['min_txn_count'])
                           and (b['min_spend_paise'] is None or spend >= b['min_spend_paise']))
                    results.append({
                        'account_id': acc_id, 'program_id': era['id'],
                        'bonus_rule_id': b['id'], 'name': b['name'],
                        'period': b['period'], 'period_token': token,
                        'met': met, 'qualifying_count': count, 'spend_paise': spend,
                        'bonus_units': b['bonus_units'],
                        'value_paise': _value_paise(b['bonus_units'], era) if met else 0,
                    })
    return results


def main():
    import os
    import sqlite3
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import app as app_module

    conn = sqlite3.connect(app_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    total, notes = rebuild_all(conn)
    conn.close()
    print(f'rebuilt {total} accrual rows')
    for n in notes:
        print(f'  - {n}')


if __name__ == '__main__':
    main()
