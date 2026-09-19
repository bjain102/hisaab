"""Validate ccyamls/*.yaml card-rules files against the SCHEMA.md contract.

Run after ANY edit to a card file:  python scripts/validate_card_rules.py
Exit 0 = all files valid (warnings allowed). Exit 1 = structural errors.

Checks per file: parses as YAML; required keys; enum values; earn_rate shape
matches the card's reward_currency; unique rule priorities; categories exist in
the app taxonomy; cap consistency (a numeric cap needs a period); exactly one
default redemption route; account maps to a real accounts row. Cross-file:
warns for credit-card accounts with no rules file (Kotak Zen, currently).
"""
import datetime
import glob
import os
import sqlite3
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import CATEGORIES  # noqa: E402  (taxonomy is the single source of truth)

CCYAML_DIR = os.path.join(ROOT, 'ccyamls')
DB_PATH = os.path.join(ROOT, 'data', 'hisaab.db')

REQUIRED_TOP = ['card', 'account', 'researched_on', 'status', 'rules_effective_from',
                'rules_effective_to', 'reverify_by', 'program', 'earn_rules',
                'bonus_rules', 'redemption_routes']
CAP_PERIODS = {'statement_cycle', 'calendar_month', 'calendar_quarter', 'calendar_year'}
BONUS_PERIODS = CAP_PERIODS | {'anniversary_quarter', 'anniversary_year', 'one_time'}
BONUS_KINDS = {'points', 'cashback', 'perk', 'pct_of_spend'}
CONFIDENCES = {'HIGH', 'MEDIUM', 'LOW'}


def is_date(v):
    if isinstance(v, datetime.date):
        return True
    if isinstance(v, str):
        try:
            datetime.date.fromisoformat(v)
            return True
        except ValueError:
            return False
    return False


def check_sources(sources, where, errors):
    if not isinstance(sources, list) or not sources:
        errors.append(f'{where}: sources must be a non-empty list')
        return
    for s in sources:
        if not isinstance(s, dict) or 'url' not in s:
            errors.append(f'{where}: each source needs at least a url')
        elif s.get('confidence') not in CONFIDENCES:
            errors.append(f'{where}: source confidence must be HIGH/MEDIUM/LOW, got {s.get("confidence")!r}')


def validate_file(path, db_accounts):
    errors, warnings = [], []
    name = os.path.basename(path)
    with open(path, encoding='utf-8') as fh:
        try:
            doc = yaml.safe_load(fh)
        except yaml.YAMLError as e:
            return [f'{name}: YAML PARSE ERROR — {e}'], []

    for key in REQUIRED_TOP:
        if key not in doc:
            errors.append(f'{name}: missing top-level key {key!r}')
    if errors:
        return errors, warnings

    if db_accounts is not None and doc['account'] not in db_accounts:
        errors.append(f"{name}: account {doc['account']!r} not found in DB accounts "
                      f"(have: {sorted(db_accounts)})")

    for datefield in ('researched_on', 'rules_effective_from', 'rules_effective_to', 'reverify_by'):
        v = doc.get(datefield)
        if v not in (None, 'UNKNOWN') and not is_date(v):
            errors.append(f'{name}: {datefield} must be a date, null, or UNKNOWN — got {v!r}')

    prog = doc['program']
    currency = prog.get('reward_currency')
    if currency not in ('points', 'cashback_inr'):
        errors.append(f'{name}: program.reward_currency must be points|cashback_inr, got {currency!r}')
    if not isinstance(prog.get('annual_fee_inr'), int):
        errors.append(f'{name}: program.annual_fee_inr must be an integer')
    fw = prog.get('fee_waiver_spend_inr', 'MISSING')
    if fw == 'MISSING':
        errors.append(f'{name}: program.fee_waiver_spend_inr is required (int, null, or UNKNOWN)')
    elif fw not in (None, 'UNKNOWN') and not isinstance(fw, int):
        errors.append(f'{name}: program.fee_waiver_spend_inr must be int/null/UNKNOWN, got {fw!r}')
    check_sources(prog.get('sources'), f'{name}: program', errors)

    # ── earn rules ──────────────────────────────────────────────────────────
    priorities = []
    for r in doc['earn_rules']:
        where = f"{name}: earn_rule p{r.get('priority', '?')}"
        if not isinstance(r.get('priority'), int):
            errors.append(f'{where}: priority must be an integer')
        else:
            priorities.append(r['priority'])
        kind = r.get('kind')
        if kind not in ('excluded', 'accelerated', 'base'):
            errors.append(f'{where}: kind must be excluded|accelerated|base, got {kind!r}')
        cat = r.get('category')
        if cat is not None and cat not in CATEGORIES:
            errors.append(f'{where}: category {cat!r} not in app taxonomy')
        if 'computable' not in r:
            warnings.append(f'{where}: computable not set (defaults to true) — set it explicitly')
        elif not isinstance(r['computable'], bool):
            errors.append(f'{where}: computable must be a bool')

        er = r.get('earn_rate')
        if kind == 'excluded':
            if er is not None:
                errors.append(f'{where}: excluded rules must not carry earn_rate')
        else:
            if not isinstance(er, dict):
                errors.append(f'{where}: {kind} rule needs an earn_rate map')
            elif currency == 'points':
                if set(er) != {'points_per', 'per_spend_inr'}:
                    errors.append(f'{where}: points-card earn_rate needs exactly '
                                  f'{{points_per, per_spend_inr}}, got {sorted(er)}')
                elif not all(isinstance(er[k], (int, float)) and er[k] > 0 for k in er):
                    errors.append(f'{where}: earn_rate values must be positive numbers')
            else:  # cashback_inr
                if set(er) != {'cashback_pct'}:
                    errors.append(f'{where}: cashback-card earn_rate needs exactly '
                                  f'{{cashback_pct}}, got {sorted(er)}')
                elif not isinstance(er['cashback_pct'], (int, float)) or er['cashback_pct'] <= 0:
                    errors.append(f'{where}: cashback_pct must be a positive number')

        cap_units = r.get('cap_units', None)
        if cap_units not in (None, 'UNKNOWN') and not isinstance(cap_units, int):
            errors.append(f'{where}: cap_units must be int/null/UNKNOWN, got {cap_units!r}')
        cap_period = r.get('cap_period')
        if isinstance(cap_units, int) and cap_period not in CAP_PERIODS:
            errors.append(f'{where}: numeric cap_units requires cap_period in {sorted(CAP_PERIODS)}')
        if cap_period is not None and cap_period not in CAP_PERIODS:
            errors.append(f'{where}: cap_period {cap_period!r} invalid (or use null)')

        for mfield in ('merchant_match', 'merchant_match_exclude'):
            mv = r.get(mfield)
            if mv is not None and not isinstance(mv, list):
                errors.append(f'{where}: {mfield} must be a list (scalar found: {mv!r})')
        mccs = r.get('mccs')
        if mccs is not None and (not isinstance(mccs, list) or
                                 not all(isinstance(m, int) for m in mccs)):
            errors.append(f'{where}: mccs must be a list of ints')
        check_sources(r.get('sources'), where, errors)

    dupes = {p for p in priorities if priorities.count(p) > 1}
    if dupes:
        errors.append(f'{name}: duplicate earn_rule priorities: {sorted(dupes)}')
    kinds = [r.get('kind') for r in doc['earn_rules']]
    if kinds.count('base') != 1:
        errors.append(f'{name}: exactly one base earn rule required, found {kinds.count("base")}')

    # ── bonus rules ─────────────────────────────────────────────────────────
    for b in doc['bonus_rules']:
        where = f"{name}: bonus_rule {b.get('name', '?')!r}"
        if b.get('period') not in BONUS_PERIODS:
            errors.append(f'{where}: period must be one of {sorted(BONUS_PERIODS)}, got {b.get("period")!r}')
        bk = b.get('bonus_kind', 'points')
        if bk not in BONUS_KINDS:
            errors.append(f'{where}: bonus_kind {bk!r} invalid')
        bu = b.get('bonus_units', 'MISSING')
        if bu == 'MISSING':
            errors.append(f'{where}: bonus_units required (int, or null for perks/pct)')
        elif bu is None and bk in ('points', 'cashback'):
            errors.append(f'{where}: bonus_kind {bk} requires integer bonus_units')
        elif bu is not None and not isinstance(bu, int):
            errors.append(f'{where}: bonus_units must be int or null, got {bu!r}')
        if 'computable' not in b:
            warnings.append(f'{where}: computable not set — set it explicitly')
        if not any(b.get(k) is not None for k in ('min_txn_count', 'min_txn_inr', 'min_spend_inr')) \
                and b.get('computable', True):
            warnings.append(f'{where}: computable bonus with no threshold fields — engine cannot evaluate it')
        check_sources(b.get('sources'), where, errors)

    # ── redemption routes ───────────────────────────────────────────────────
    defaults = [rt for rt in doc['redemption_routes'] if rt.get('recommended_default')]
    if len(defaults) != 1:
        errors.append(f'{name}: exactly one redemption route must have recommended_default: true, '
                      f'found {len(defaults)}')
    for rt in doc['redemption_routes']:
        v = rt.get('value_per_point_inr', 'MISSING')
        if v == 'MISSING':
            errors.append(f'{name}: route {rt.get("name", "?")!r} missing value_per_point_inr')
        elif v not in (None, 'UNKNOWN') and not isinstance(v, (int, float)):
            errors.append(f'{name}: route {rt.get("name", "?")!r} value_per_point_inr must be '
                          f'number/null/UNKNOWN')
    if defaults and defaults[0].get('value_per_point_inr') in (None, 'UNKNOWN'):
        warnings.append(f'{name}: the DEFAULT route has no fixed value_per_point_inr — headline '
                        f'valuations will be undefined')

    return errors, warnings


def main():
    files = sorted(glob.glob(os.path.join(CCYAML_DIR, '*.yaml')))
    if not files:
        print('no card files found in ccyamls/')
        return 1

    db_accounts = None
    if os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        db_accounts = {r[0] for r in conn.execute(
            "SELECT name FROM accounts WHERE kind='credit_card'")}
        conn.close()
    else:
        print('note: DB not found — skipping account-existence checks\n')

    all_errors, covered = [], set()
    for path in files:
        errors, warnings = validate_file(path, db_accounts)
        status = 'FAIL' if errors else ('WARN' if warnings else 'OK')
        print(f'[{status}] {os.path.basename(path)}')
        for e in errors:
            print(f'    ERROR: {e}')
        for w in warnings:
            print(f'    warn:  {w}')
        all_errors.extend(errors)
        if not errors:
            with open(path, encoding='utf-8') as fh:
                covered.add(yaml.safe_load(fh)['account'])

    if db_accounts:
        missing = db_accounts - covered
        for m in sorted(missing):
            print(f'\nwarn: credit-card account {m!r} has no rules file (engine will skip it)')

    print(f'\n{len(files)} files, {len(all_errors)} errors')
    return 1 if all_errors else 0


if __name__ == '__main__':
    sys.exit(main())
