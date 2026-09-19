"""Task 5.2 (code half): rewards/seed.py — turns a parsed ccyamls-shaped YAML
document into ADR-008 rows. Uses small synthetic documents (not the real
ccyamls/ files) so these tests don't depend on the owner's data changing.
"""
import sqlite3

import pytest

import app as app_module
from rewards.seed import seed_all, seed_card


@pytest.fixture()
def conn(client):
    """The conftest `client` fixture already migrates a synthetic DB through
    the full chain (now including v8); reuse its connection for direct
    rewards/seed.py calls."""
    c = sqlite3.connect(app_module.DB_PATH)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def _points_doc(valid_from='2026-01-01', prime=None):
    doc = {
        'card': 'Test Points Card', 'account': 'CARD-A',
        'researched_on': '2026-07-19', 'status': 'in_force',
        'rules_effective_from': valid_from, 'rules_effective_to': None, 'reverify_by': None,
        'program': {
            'reward_currency': 'points', 'unit_name': 'Test Points',
            'annual_fee_inr': 500, 'fee_waiver_condition': 'Spend 100000',
            'fee_waiver_spend_inr': 100000, 'network': 'Visa', 'forex_markup': '3.5%',
            'sources': [{'url': 'x', 'as_of': valid_from, 'confidence': 'HIGH'}],
        },
        'earn_rules': [
            {'priority': 1, 'kind': 'excluded', 'category': 'Fuel', 'computable': True,
             'note': None, 'sources': []},
            {'priority': 2, 'kind': 'excluded', 'category': 'Others', 'computable': False,
             'note': 'EMI, not computable', 'sources': []},
            {'priority': 11, 'kind': 'accelerated', 'category': 'Shopping',
             'merchant_match': ['amazon'], 'merchant_match_exclude': ['gold'],
             'earn_rate': {'points_per': 1.5, 'per_spend_inr': 100},
             'cap_units': 2000, 'cap_period': 'calendar_month', 'cap_group': 'shop_pool',
             'min_txn_inr': None, 'computable': True, 'note': None, 'sources': []},
            {'priority': 99, 'kind': 'base', 'earn_rate': {'points_per': 4, 'per_spend_inr': 200},
             'cap_units': None, 'computable': True, 'note': None, 'sources': []},
        ],
        'bonus_rules': [
            {'name': 'Welcome', 'period': 'one_time', 'min_txn_count': None, 'min_txn_inr': None,
             'min_spend_inr': 1000, 'bonus_units': 5000, 'bonus_kind': 'points',
             'computable': False, 'note': None, 'sources': []},
            {'name': 'Monthly', 'period': 'calendar_month', 'min_txn_count': 4, 'min_txn_inr': 1500,
             'min_spend_inr': None, 'bonus_units': 1000, 'bonus_kind': 'points',
             'computable': True, 'note': None, 'sources': []},
        ],
        'redemption_routes': [
            {'name': 'Catalogue', 'value_per_point_inr': None, 'recommended_default': False, 'note': 'varies'},
            {'name': 'Statement credit', 'value_per_point_inr': 0.25, 'recommended_default': True, 'note': None},
        ],
    }
    if prime is not None:
        doc['owner_flags'] = {'amazon_prime': prime}
        doc['earn_rules'].append(
            {'priority': 9, 'kind': 'accelerated', 'category': 'Shopping', 'merchant_match': ['amazon'],
             'earn_rate': {'points_per': 5, 'per_spend_inr': 100}, 'requires_owner_flag': {'amazon_prime': True},
             'computable': True, 'note': None, 'sources': []})
        doc['earn_rules'].append(
            {'priority': 10, 'kind': 'accelerated', 'category': 'Shopping', 'merchant_match': ['amazon'],
             'earn_rate': {'points_per': 3, 'per_spend_inr': 100}, 'requires_owner_flag': {'amazon_prime': False},
             'computable': True, 'note': None, 'sources': []})
    return doc


def _cashback_doc(valid_from='2026-01-01'):
    return {
        'card': 'Test Cashback Card', 'account': 'CARD-B',
        'researched_on': '2026-07-19', 'status': 'in_force',
        'rules_effective_from': valid_from, 'rules_effective_to': None, 'reverify_by': None,
        'program': {
            'reward_currency': 'cashback_inr', 'unit_name': None,
            'annual_fee_inr': 0, 'fee_waiver_condition': None, 'fee_waiver_spend_inr': None,
            'network': 'Visa', 'forex_markup': '3.5%', 'sources': [],
        },
        'earn_rules': [
            {'priority': 99, 'kind': 'base', 'earn_rate': {'cashback_pct': 1},
             'cap_units': 500, 'cap_period': 'statement_cycle', 'min_txn_inr': 100,
             'computable': True, 'note': None, 'sources': []},
        ],
        'bonus_rules': [],
        'redemption_routes': [
            {'name': 'Statement credit', 'value_per_point_inr': 1.0, 'recommended_default': True, 'note': None},
        ],
    }


def test_new_points_program_seeded_with_correct_conversions(conn):
    result = seed_card(conn, _points_doc())
    conn.commit()
    assert result['mode'] == 'new'
    assert (result['routes'], result['earn_rules'], result['bonus_rules']) == (2, 3, 1)
    # skipped counts BOTH computable:false earn_rules (the EMI exclusion) AND
    # computable:false bonus_rules (the one-time Welcome bonus) — 2 total
    assert result['skipped'] == 2

    prog = conn.execute('SELECT * FROM reward_programs WHERE id=?', (result['program_id'],)).fetchone()
    assert prog['annual_fee_paise'] == 50000  # 500 * 100
    assert prog['earn_currency'] == 'points'
    assert prog['valid_from'] == '2026-01-01' and prog['valid_to'] is None

    # 1.5 points per ₹100 -> numer/denom scaled to stay integer, ratio preserved
    accel = conn.execute(
        "SELECT * FROM earn_rules WHERE program_id=? AND priority=11", (result['program_id'],)).fetchone()
    assert accel['earn_numer'] / accel['earn_denom_paise'] == pytest.approx(1.5 / 10000)
    assert accel['merchant_match'] == 'amazon'
    assert accel['merchant_match_exclude'] == 'gold'
    assert accel['cap_units'] == 2000  # points program: cap stays raw units
    assert accel['cap_group'] == 'shop_pool'

    excluded = conn.execute(
        "SELECT * FROM earn_rules WHERE program_id=? AND kind='excluded'", (result['program_id'],)).fetchone()
    assert excluded['earn_numer'] == 0

    default_route = conn.execute(
        "SELECT * FROM redemption_routes WHERE program_id=? AND is_default=1", (result['program_id'],)).fetchone()
    assert default_route['value_per_point_centipaise'] == 2500  # ₹0.25 -> centipaise
    varying_route = conn.execute(
        "SELECT * FROM redemption_routes WHERE program_id=? AND is_default=0", (result['program_id'],)).fetchone()
    assert varying_route['value_per_point_centipaise'] is None


def test_cashback_program_units_converted_to_paise(conn):
    result = seed_card(conn, _cashback_doc())
    conn.commit()
    rule = conn.execute(
        "SELECT * FROM earn_rules WHERE program_id=?", (result['program_id'],)).fetchone()
    # 1% cashback -> numer=1, denom=100 (units_earned_paise = amount_paise * 1/100)
    assert (rule['earn_numer'], rule['earn_denom_paise']) == (1, 100)
    assert rule['cap_units'] == 50000    # ₹500 cap -> paise
    assert rule['min_txn_paise'] == 10000  # ₹100 -> paise


def test_computable_false_bonus_skipped(conn):
    result = seed_card(conn, _points_doc())
    conn.commit()
    names = {r['name'] for r in conn.execute(
        "SELECT name FROM bonus_rules WHERE program_id=?", (result['program_id'],))}
    assert names == {'Monthly'}  # the one_time 'Welcome' bonus is computable:false


def test_owner_flag_selects_one_tier_only(conn):
    result = seed_card(conn, _points_doc(prime=True))
    conn.commit()
    rates = {r['priority']: r['earn_numer'] for r in conn.execute(
        "SELECT priority, earn_numer FROM earn_rules WHERE program_id=? AND priority IN (9,10)",
        (result['program_id'],))}
    assert list(rates.keys()) == [9]  # only the amazon_prime=true tier seeded


def test_reseed_same_era_replaces_rules_not_program_row(conn):
    r1 = seed_card(conn, _points_doc())
    conn.commit()
    program_id_1 = r1['program_id']

    doc2 = _points_doc()
    doc2['earn_rules'] = [doc2['earn_rules'][-1]]  # only the base rule now
    r2 = seed_card(conn, doc2)
    conn.commit()

    assert r2['mode'] == 'reseed'
    assert r2['program_id'] == program_id_1  # same era, same row
    n_rules = conn.execute(
        "SELECT COUNT(*) FROM earn_rules WHERE program_id=?", (program_id_1,)).fetchone()[0]
    assert n_rules == 1
    n_programs = conn.execute(
        "SELECT COUNT(*) FROM reward_programs WHERE account_id=(SELECT account_id FROM reward_programs WHERE id=?)",
        (program_id_1,)).fetchone()[0]
    assert n_programs == 1  # no duplicate era created


def test_devaluation_closes_old_era_and_opens_new(conn):
    r1 = seed_card(conn, _points_doc(valid_from='2026-01-01'))
    conn.commit()
    old_id = r1['program_id']

    r2 = seed_card(conn, _points_doc(valid_from='2026-06-01'))
    conn.commit()

    assert r2['mode'] == 'devaluation'
    assert r2['program_id'] != old_id
    old = conn.execute('SELECT * FROM reward_programs WHERE id=?', (old_id,)).fetchone()
    new = conn.execute('SELECT * FROM reward_programs WHERE id=?', (r2['program_id'],)).fetchone()
    assert old['valid_to'] == '2026-06-01'  # old era closed exactly at the new one's start
    assert new['valid_to'] is None
    # old era's rules untouched — still 3 computable rows, not deleted
    old_rules = conn.execute(
        'SELECT COUNT(*) FROM earn_rules WHERE program_id=?', (old_id,)).fetchone()[0]
    assert old_rules == 3


def test_seeding_out_of_order_is_refused(conn):
    seed_card(conn, _points_doc(valid_from='2026-06-01'))
    conn.commit()
    with pytest.raises(ValueError, match='refusing to seed out of order'):
        seed_card(conn, _points_doc(valid_from='2026-01-01'))


def test_fee_waiver_milestone_linked_when_present(conn):
    account_id = conn.execute("SELECT id FROM accounts WHERE name='CARD-A'").fetchone()['id']
    conn.execute(
        "INSERT INTO milestones (account_id, name, target_paise, window_start, window_end, benefit) "
        "VALUES (?, 'Annual Fee Waiver', 10000000, '2026-01-01', '2026-12-31', 'Fee waived')",
        (account_id,))
    conn.commit()
    result = seed_card(conn, _points_doc())
    conn.commit()
    prog = conn.execute('SELECT fee_waiver_milestone_id FROM reward_programs WHERE id=?',
                        (result['program_id'],)).fetchone()
    assert prog['fee_waiver_milestone_id'] is not None


def test_fee_waiver_left_null_with_note_when_absent(conn):
    notes = []
    seed_card(conn, _points_doc(), notes_out=notes)
    conn.commit()
    assert any('no fee-waiver milestone found' in n for n in notes)


def test_seed_all_reads_a_directory_of_files(conn, tmp_path):
    """seed_all()'s own job — glob a directory, seed each file, aggregate —
    tested against synthetic files pointing at the conftest DB's own
    accounts. (The real ccyamls/ directory references real production
    account names that don't exist in this synthetic DB; that check happens
    manually via dress rehearsal, the same discipline every migration in
    this repo follows before running seed_all for real.)"""
    import yaml
    for doc in (_points_doc(), _cashback_doc()):
        with open(tmp_path / f"{doc['account']}.yaml", 'w', encoding='utf-8') as fh:
            yaml.safe_dump(doc, fh)
    summaries, notes = seed_all(conn, ccyamls_dir=str(tmp_path))
    assert len(summaries) == 2
    assert {s['account'] for s in summaries} == {'CARD-A', 'CARD-B'}
    assert all(s['mode'] == 'new' for s in summaries)
