"""Task 5.2: GET /api/reward_programs — the read-only view of whatever
rewards/seed.py has seeded (rules themselves are edited via ccyamls/*.yaml +
re-seeding, not this endpoint)."""
import sqlite3

import app as app_module
from rewards.seed import seed_card


def _seed_one(card='CARD-A'):
    conn = sqlite3.connect(app_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    doc = {
        'card': 'Test Card', 'account': card,
        'researched_on': '2026-07-19', 'status': 'in_force',
        'rules_effective_from': '2026-01-01', 'rules_effective_to': None, 'reverify_by': None,
        'program': {
            'reward_currency': 'points', 'unit_name': 'Test Points',
            'annual_fee_inr': 500, 'fee_waiver_condition': None, 'fee_waiver_spend_inr': None,
            'network': 'Visa', 'forex_markup': '3.5%', 'sources': [],
        },
        'earn_rules': [
            {'priority': 99, 'kind': 'base', 'earn_rate': {'points_per': 2, 'per_spend_inr': 100},
             'cap_units': None, 'computable': True, 'note': None, 'sources': []},
        ],
        'bonus_rules': [],
        'redemption_routes': [
            {'name': 'Statement credit', 'value_per_point_inr': 0.25, 'recommended_default': True, 'note': None},
        ],
    }
    seed_card(conn, doc)
    conn.commit()
    conn.close()


def test_lists_seeded_program_with_route_and_rule_counts(client):
    _seed_one()
    rows = client.get('/api/reward_programs').get_json()
    row = next(r for r in rows if r['card_label'] == 'CARD-A')
    assert row['name'] == 'Test Points'
    assert row['earn_currency'] == 'points'
    assert row['annual_fee_paise'] == 50000
    assert row['earn_rule_count'] == 1
    assert row['bonus_rule_count'] == 0
    assert row['default_route_name'] == 'Statement credit'
    assert row['default_route_centipaise'] == 2500


def test_empty_when_nothing_seeded(client):
    rows = client.get('/api/reward_programs').get_json()
    assert rows == []
