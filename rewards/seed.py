"""Turn ccyamls/*.yaml (the owner's researched card rules, ADR-009-normalizer-
matched, validated by scripts/validate_card_rules.py) into ADR-008 rows:
reward_programs / redemption_routes / earn_rules / bonus_rules.

This is the "editor" for task 5.2, by design rather than by omission: rules
change by editing the YAML (a devaluation = a new `rules_effective_from`; a
correction = the same date) and re-running this seeder — not through a
second, competing in-app CRUD surface duplicating what the validated YAML +
research skill already do well. GET /api/reward_programs (app.py) is the
read-only view for checking what's live.

Era handling (ADR-008: "a devaluation CLOSES this row and opens a new one;
history is never rewritten"):
  - No open era (valid_to IS NULL) for this account yet -> INSERT a new one.
  - An open era exists with the SAME valid_from as the file -> treated as a
    correction to the current era, not a devaluation: its child rows
    (routes/rules/bonuses) are replaced with what the file says now. ADR-008
    says a rule edit must rebuild accruals — the CLI below calls
    engine.rebuild_all() after every seed run, so the derived cache never
    outlives the rules it was computed from. (Callers using seed_card/
    seed_all directly own that rebuild themselves.)
  - An open era exists with an EARLIER valid_from -> a genuine devaluation:
    the old era is closed (valid_to = the new valid_from) untouched, and a
    fresh era is inserted. Old rows are never edited or deleted.
  - An open era with a LATER valid_from than the file being seeded is a
    contradiction (the file claims to predate what's already recorded as
    current) and is refused loudly rather than silently reordered.

Unit conversions (money always paise at rest; point values always
centipaise, per ADR-008's own comment: 1 pt = ₹0.25 -> 2500 centipaise):
  - annual_fee_inr -> annual_fee_paise:            × 100
  - value_per_point_inr -> value_per_point_centipaise: × 10000  (rupees -> centipaise)
  - earn_rate {points_per, per_spend_inr} -> (earn_numer, earn_denom_paise):
        denom_paise = per_spend_inr × 100; if points_per isn't a whole
        number, both numer and denom are scaled by the same power of ten
        until numer is (e.g. 1.5 pts/₹100 -> numer=15, denom_paise=100000).
        The RATIO is what matters — 5.3's engine applies it as
        amount_paise * earn_numer / earn_denom_paise, still exact.
  - earn_rate {cashback_pct} -> (earn_numer, earn_denom_paise):
        cashback programs earn PAISE directly (units = paise), so
        numer=cashback_pct, denom_paise=100 (i.e. "cashback_pct per ₹1").
  - cap_units / bonus_units / min_txn_inr / min_spend_inr: for a
    cashback_inr program these are owner-recorded in INR (ccyamls/SCHEMA.md)
    and are converted × 100 to paise; for a points program they're already
    the right unit (points) and pass through unconverted.

`computable: false` rules are never seeded — they're the documentation/
caveat layer (see ccyamls/SCHEMA.md), not engine input. Rules gated by
`requires_owner_flag` are seeded ONLY when every flag in that mapping matches
the file's own `owner_flags` block; if the file has no owner_flags or the
value doesn't match, the rule is skipped (with a note) rather than guessed.
"""
import glob
import os

import yaml

CCYAML_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ccyamls')


def _scale_to_int(x, max_scale=10000):
    """Smallest power-of-ten `scale` such that x*scale is (near enough) an
    integer. Used to keep earn_numer an INTEGER column honest for fractional
    per-unit rates (1.5 points, 2.5% cashback) without losing precision —
    the ratio earn_numer/earn_denom_paise is unaffected by the scale."""
    scale = 1
    while scale <= max_scale and abs(round(x * scale) - x * scale) > 1e-9:
        scale *= 10
    return scale


def _earn_fraction(rule, currency):
    er = rule['earn_rate']
    if currency == 'points':
        pts, per_inr = er['points_per'], er['per_spend_inr']
        scale = _scale_to_int(pts)
        return int(round(pts * scale)), int(round(per_inr * 100 * scale))
    else:  # cashback_inr
        pct = er['cashback_pct']
        scale = _scale_to_int(pct)
        return int(round(pct * scale)), int(round(100 * scale))


def _units_to_db(value, currency):
    """cap_units / bonus_units / min_txn_inr / min_spend_inr: INR for
    cashback programs (owner recorded them that way — SCHEMA.md), already
    the native unit (points) for points programs."""
    if value in (None, 'UNKNOWN'):
        return None
    return int(round(value * 100)) if currency == 'cashback_inr' else int(value)


def _owner_flags_match(rule, owner_flags):
    req = rule.get('requires_owner_flag')
    if not req:
        return True
    owner_flags = owner_flags or {}
    return all(owner_flags.get(k) == v for k, v in req.items())


def _resolve_era(conn, account_id, valid_from):
    """Returns ('new'|'reseed'|'devaluation', existing_row_or_None)."""
    row = conn.execute(
        'SELECT id, valid_from FROM reward_programs WHERE account_id=? AND valid_to IS NULL',
        (account_id,)).fetchone()
    if row is None:
        return 'new', None
    if row['valid_from'] == valid_from:
        return 'reseed', row
    if row['valid_from'] < valid_from:
        return 'devaluation', row
    raise ValueError(
        f"open era for account {account_id} already starts {row['valid_from']!r}, "
        f"which is AFTER this file's rules_effective_from {valid_from!r} — refusing to "
        f"seed out of order. Fix the file's date or investigate which era is stale.")


def _find_fee_waiver_milestone(conn, account_id):
    """Best-effort link to an existing milestone whose purpose is this
    card's fee waiver. Never fabricates one — a fee-waiver milestone's real
    window is an owner decision (and, per the 3.6 handoff notes, migration-
    inferred windows already needed owner review once before)."""
    rows = conn.execute(
        "SELECT id FROM milestones WHERE account_id=? "
        "AND (name LIKE '%Fee Waiver%' OR benefit LIKE '%fee%')", (account_id,)).fetchall()
    return rows[0]['id'] if len(rows) == 1 else None


def seed_card(conn, doc, notes_out=None):
    """Seed one parsed card YAML document. `notes_out`, if given, is a list
    that gets human-readable notes appended (owner actions, skips, links
    made) — the CLI prints these; callers that don't care can omit it."""
    def note(msg):
        if notes_out is not None:
            notes_out.append(msg)

    account = conn.execute(
        "SELECT id FROM accounts WHERE kind='credit_card' AND name=?", (doc['account'],)).fetchone()
    if not account:
        raise ValueError(f"account {doc['account']!r} not found in accounts table")
    account_id = account['id']
    currency = doc['program']['reward_currency']
    owner_flags = doc.get('owner_flags') or {}

    valid_from = doc['rules_effective_from']
    if valid_from in (None, 'UNKNOWN'):
        valid_from = doc['researched_on']
        note(f"{doc['card']}: rules_effective_from UNKNOWN, used researched_on {valid_from} instead")

    mode, existing = _resolve_era(conn, account_id, valid_from)

    fee_waiver_id = _find_fee_waiver_milestone(conn, account_id)
    if fee_waiver_id is None and doc['program'].get('fee_waiver_spend_inr') not in (None, 'UNKNOWN'):
        note(f"{doc['card']}: no fee-waiver milestone found for this account — "
             f"fee_waiver_milestone_id left NULL (create one in Rewards, then re-seed)")

    prog = doc['program']
    annual_fee_paise = int(round(prog['annual_fee_inr'] * 100))
    prog_notes = prog.get('fee_waiver_condition') or None

    if mode == 'new':
        cur = conn.execute(
            '''INSERT INTO reward_programs
               (account_id, name, earn_currency, annual_fee_paise, fee_waiver_milestone_id,
                valid_from, valid_to, notes)
               VALUES (?,?,?,?,?,?,NULL,?)''',
            (account_id, prog.get('unit_name') or doc['card'], currency, annual_fee_paise,
             fee_waiver_id, valid_from, prog_notes))
        program_id = cur.lastrowid
        note(f"{doc['card']}: new era opened (valid_from={valid_from})")
    elif mode == 'reseed':
        program_id = existing['id']
        conn.execute(
            '''UPDATE reward_programs SET name=?, earn_currency=?, annual_fee_paise=?,
               fee_waiver_milestone_id=?, notes=? WHERE id=?''',
            (prog.get('unit_name') or doc['card'], currency, annual_fee_paise,
             fee_waiver_id, prog_notes, program_id))
        for t in ('redemption_routes', 'earn_rules', 'bonus_rules'):
            conn.execute(f'DELETE FROM {t} WHERE program_id=?', (program_id,))
        note(f"{doc['card']}: re-seeded same era (valid_from={valid_from}) — rules replaced")
    else:  # devaluation
        conn.execute('UPDATE reward_programs SET valid_to=? WHERE id=?', (valid_from, existing['id']))
        cur = conn.execute(
            '''INSERT INTO reward_programs
               (account_id, name, earn_currency, annual_fee_paise, fee_waiver_milestone_id,
                valid_from, valid_to, notes)
               VALUES (?,?,?,?,?,?,NULL,?)''',
            (account_id, prog.get('unit_name') or doc['card'], currency, annual_fee_paise,
             fee_waiver_id, valid_from, prog_notes))
        program_id = cur.lastrowid
        note(f"{doc['card']}: DEVALUATION — closed era #{existing['id']} "
             f"(valid_from={existing['valid_from']}), opened new era (valid_from={valid_from})")

    n_routes = n_rules = n_bonus = n_skipped = 0
    for r in doc['redemption_routes']:
        v = r.get('value_per_point_inr')
        centipaise = None if v in (None, 'UNKNOWN') else int(round(v * 10000))
        conn.execute(
            'INSERT INTO redemption_routes (program_id, name, value_per_point_centipaise, is_default, notes) '
            'VALUES (?,?,?,?,?)',
            (program_id, r['name'], centipaise, 1 if r.get('recommended_default') else 0, r.get('note')))
        n_routes += 1

    for r in doc['earn_rules']:
        if not r.get('computable', True):
            n_skipped += 1
            continue
        if not _owner_flags_match(r, owner_flags):
            n_skipped += 1
            note(f"{doc['card']}: skipped earn_rule p{r['priority']} — "
                 f"requires_owner_flag {r['requires_owner_flag']} not satisfied by {owner_flags}")
            continue
        if r['kind'] == 'excluded':
            earn_numer, earn_denom_paise = 0, 10000
        else:
            earn_numer, earn_denom_paise = _earn_fraction(r, currency)
        merchant_match = ','.join(r['merchant_match']) if r.get('merchant_match') else None
        merchant_exclude = ','.join(r['merchant_match_exclude']) if r.get('merchant_match_exclude') else None
        conn.execute(
            '''INSERT INTO earn_rules
               (program_id, priority, kind, category, merchant_match, merchant_match_exclude,
                earn_numer, earn_denom_paise, cap_units, cap_period, cap_group, min_txn_paise, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (program_id, r['priority'], r['kind'], r.get('category'), merchant_match, merchant_exclude,
             earn_numer, earn_denom_paise, _units_to_db(r.get('cap_units'), currency), r.get('cap_period'),
             r.get('cap_group'), _units_to_db(r.get('min_txn_inr'), currency), r.get('note')))
        n_rules += 1

    for b in doc['bonus_rules']:
        if not b.get('computable', True):
            n_skipped += 1
            continue
        conn.execute(
            '''INSERT INTO bonus_rules
               (program_id, name, period, min_txn_count, min_txn_paise, min_spend_paise,
                bonus_units, notes)
               VALUES (?,?,?,?,?,?,?,?)''',
            (program_id, b['name'], b['period'], b.get('min_txn_count'),
             _units_to_db(b.get('min_txn_inr'), currency), _units_to_db(b.get('min_spend_inr'), currency),
             _units_to_db(b['bonus_units'], currency) if b.get('bonus_units') is not None else 0,
             b.get('note')))
        n_bonus += 1

    return {'card': doc['card'], 'account': doc['account'], 'program_id': program_id, 'mode': mode,
            'routes': n_routes, 'earn_rules': n_rules, 'bonus_rules': n_bonus, 'skipped': n_skipped}


def seed_all(conn, ccyamls_dir=None, commit=True):
    """Seed every *.yaml in ccyamls/ (skips SCHEMA.md by extension). Returns
    (summaries, notes) — one summary dict per card, plus the flattened notes
    list. Wraps everything in a single transaction so a bad file doesn't
    half-seed the DB."""
    ccyamls_dir = ccyamls_dir or CCYAML_DIR
    summaries, notes = [], []
    files = sorted(glob.glob(os.path.join(ccyamls_dir, '*.yaml')))
    try:
        for path in files:
            with open(path, encoding='utf-8') as fh:
                doc = yaml.safe_load(fh)
            summaries.append(seed_card(conn, doc, notes_out=notes))
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    return summaries, notes


def main():
    import sqlite3
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import app as app_module

    from rewards.engine import rebuild_all

    conn = sqlite3.connect(app_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    summaries, notes = seed_all(conn)
    n_accruals, engine_notes = rebuild_all(conn)  # rules changed -> derived cache rebuilt (ADR-008)
    conn.close()

    for s in summaries:
        print(f"{s['card']} [{s['mode']}]: {s['routes']} routes, {s['earn_rules']} earn_rules, "
              f"{s['bonus_rules']} bonus_rules ({s['skipped']} computable:false/gated skipped)")
    print(f'\nrebuilt {n_accruals} accrual rows')
    if notes or engine_notes:
        print('\nNotes:')
        for n in notes + engine_notes:
            print(f'  - {n}')


if __name__ == '__main__':
    main()
