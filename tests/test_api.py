"""API-layer tests against the synthetic fixture (see conftest for the
hand-computed expectations). These pin the net-spend semantics the new
dashboard consumes; the parser layer is deliberately untested here (Phase 1)."""
from collections import defaultdict


def get_summary(client, **params):
    resp = client.get('/api/summary', query_string=params)
    assert resp.status_code == 200
    return resp.get_json()


def test_summary_net_spend_semantics(client):
    # All money on the wire is INTEGER PAISE since migration v2 (ADR-005).
    s = get_summary(client)
    assert s['gross_debits'] == 380000
    assert s['refund_credits'] == 20000            # bill payment + cashback excluded
    assert s['total_spend'] == 360000
    assert s['cashback_total'] == 5000
    assert s['cashback_count'] == 1


def test_summary_monthly_trend(client):
    s = get_summary(client)
    assert s['monthly_trend'] == [
        {'month': '2026-01', 'total': 130000},
        {'month': '2026-02', 'total': 230000},
    ]


def test_monthly_by_category_values(client):
    s = get_summary(client)
    got = {(r['month'], r['category']): r['total'] for r in s['monthly_by_category']}
    assert got == {
        ('2026-01', 'Food & Drinks'): 100000,
        ('2026-01', 'Travel'): 50000,
        ('2026-01', 'Reversals & Refunds'): -20000,   # unfloored by design
        ('2026-02', 'Shopping'): 200000,
        ('2026-02', 'Food & Drinks'): 30000,
    }


def test_monthly_by_category_sums_to_monthly_trend(client):
    """The 0.5 acceptance invariant: per-month column sums equal the trend."""
    s = get_summary(client)
    by_month = defaultdict(float)
    for r in s['monthly_by_category']:
        by_month[r['month']] += r['total']
    for m in s['monthly_trend']:
        assert round(by_month[m['month']], 2) == m['total'], m['month']


def test_summary_card_filter(client):
    s = get_summary(client, card='CARD-A')
    assert s['total_spend'] == 130000              # 1500 debits - 200 refund, in paise
    assert all(r['card_label'] == 'CARD-A' for r in s['by_card'])
    # monthly_by_category respects the filter too
    months = {r['month'] for r in s['monthly_by_category']}
    assert months == {'2026-01'}


def test_summary_date_filter(client):
    s = get_summary(client, from_date='2026-02-01', to_date='2026-02-28')
    assert s['total_spend'] == 230000
    assert [m['month'] for m in s['monthly_trend']] == ['2026-02']


def test_summary_money_fields_are_integers(client):
    """ADR-005 wire contract: every money field is an int, never a float."""
    s = get_summary(client)
    for key in ('total_spend', 'category_sum', 'gross_debits', 'refund_credits', 'cashback_total'):
        assert isinstance(s[key], int), key
    for row in s['by_category']:
        assert isinstance(row['total'], int)
    for row in s['monthly_by_category']:
        assert isinstance(row['total'], int)


def test_summary_existing_fields_shape(client):
    """The field is additive: everything the legacy UI reads is still there."""
    s = get_summary(client)
    for key in ('total_spend', 'category_sum', 'gross_debits', 'refund_credits',
                'cashback_total', 'cashback_count', 'by_category', 'by_card',
                'monthly_trend', 'top_merchants', 'by_channel'):
        assert key in s, key


def test_cards_endpoint(client):
    resp = client.get('/api/cards')
    assert resp.status_code == 200
    assert resp.get_json() == ['CARD-A', 'CARD-B']


def test_by_category_floors_at_zero(client):
    """Legacy by_category behavior unchanged: net-negative categories are
    floored/dropped there (unlike monthly_by_category, which stays signed)."""
    s = get_summary(client)
    for row in s['by_category']:
        assert row['total'] >= 0


# ── /api/transactions: limit/offset + X-Total-Count (task 2.1) ────────────────

def test_transactions_default_behavior_unchanged(client):
    """Omitting limit/offset must behave exactly as before — additive only."""
    resp = client.get('/api/transactions')
    assert resp.status_code == 200
    rows = resp.get_json()
    assert len(rows) == 7  # all seed rows, under the legacy bare-LIMIT-1000 cap
    assert resp.headers['X-Total-Count'] == '7'


def test_transactions_limit_offset_pages_correctly(client):
    first = client.get('/api/transactions', query_string={'limit': 3, 'offset': 0})
    second = client.get('/api/transactions', query_string={'limit': 3, 'offset': 3})
    assert len(first.get_json()) == 3
    assert len(second.get_json()) == 3
    assert first.headers['X-Total-Count'] == second.headers['X-Total-Count'] == '7'
    # no overlap between pages
    first_ids = {r['id'] for r in first.get_json()}
    second_ids = {r['id'] for r in second.get_json()}
    assert first_ids.isdisjoint(second_ids)


def test_transactions_total_count_respects_filters(client):
    resp = client.get('/api/transactions', query_string={'card': 'CARD-A'})
    rows = resp.get_json()
    assert resp.headers['X-Total-Count'] == str(len(rows))
    assert all(r['card_label'] == 'CARD-A' for r in rows)


# ── Payment-channel lens: by_channel + per-card UPI fields ────────────────────
# The seed corpus carries no UPI-prefixed descriptions, so the baseline is
# all-card and any UPI figure below comes from a row the test inserted itself.

def _add_txn(desc, amount_paise=5000, card='CARD-A', date='2026-01-12',
             ttype='debit', category='Food & Drinks', is_cashback=0):
    """Insert one transaction against the live test DB, post-migration (the
    tests/test_dedup_cleanup.py pattern — the fixture's own seeding runs on the
    legacy schema, which no longer exists by the time a test body runs)."""
    import sqlite3

    import app as app_module
    conn = sqlite3.connect(app_module.DB_PATH)
    account_id = conn.execute('SELECT id FROM accounts WHERE name=?', (card,)).fetchone()[0]
    conn.execute(
        '''INSERT INTO transactions (account_id, date, description, raw_description,
                                     amount_paise, type, category, is_cashback, category_source)
           VALUES (?,?,?,?,?,?,?,?, 'manual')''',
        (account_id, date, desc, desc, amount_paise, ttype, category, is_cashback))
    conn.commit()
    conn.close()


def test_by_channel_baseline_is_all_card(client):
    s = get_summary(client)
    assert s['by_channel']['upi'] == {'count': 0, 'total': 0}
    assert s['by_channel']['card'] == {'count': 4, 'total': 380000}


def test_by_channel_partitions_gross_debits(client):
    """The lens invariant: the two rails split the debits exactly, with no row
    double-counted or dropped. Holds whatever the mix happens to be."""
    _add_txn('UPI-SAMPLE CHAI', 7500)
    s = get_summary(client)
    ch = s['by_channel']
    assert ch['upi']['total'] + ch['card']['total'] == s['gross_debits']
    assert ch['upi']['count'] + ch['card']['count'] == sum(r['count'] for r in s['by_card'])


def test_upi_rows_land_in_the_upi_bucket_and_roll_up_per_card(client):
    _add_txn('UPI-SAMPLE CHAI', 5000)
    _add_txn('UPI-SAMPLE KIRANA', 5000)
    s = get_summary(client)
    assert s['by_channel']['upi'] == {'count': 2, 'total': 10000}
    a = next(r for r in s['by_card'] if r['card_label'] == 'CARD-A')
    assert a['upi_count'] == 2
    assert a['upi_total'] == 10000
    assert a['gross_debits'] == 160000          # 1500 seed + 100 added, in paise
    # per-card UPI must roll up to the top-level figure
    assert sum(r['upi_total'] for r in s['by_card']) == s['by_channel']['upi']['total']


def test_emi_is_not_upi_at_the_api_layer(client):
    """The one classifier subtlety that must not regress in aggregate: 'EMI' is
    a leading token but names no rail, so a card EMI stays card spend."""
    _add_txn('EMI TATA PAYMENTS LIMITEDMUMBAI', 9000)
    s = get_summary(client)
    assert s['by_channel']['upi'] == {'count': 0, 'total': 0}
    assert s['by_channel']['card']['total'] == 389000


def test_by_channel_excludes_credits_and_cashback(client):
    """A channel is a property of a spend: refunds and cashback have none."""
    _add_txn('UPI-SAMPLE REFUND', 4000, ttype='credit', category='Reversals & Refunds')
    _add_txn('UPI-SAMPLE CASHBACK', 3000, ttype='credit', is_cashback=1)
    s = get_summary(client)
    assert s['by_channel']['upi'] == {'count': 0, 'total': 0}


def test_by_channel_respects_the_card_filter(client):
    _add_txn('UPI-SAMPLE CHAI', 5000, card='CARD-A')
    assert get_summary(client, card='CARD-A')['by_channel']['upi']['count'] == 1
    assert get_summary(client, card='CARD-B')['by_channel']['upi'] == {'count': 0, 'total': 0}


def test_by_channel_respects_the_date_filter(client):
    _add_txn('UPI-SAMPLE CHAI', 5000, date='2026-01-12')
    s = get_summary(client, from_date='2026-02-01', to_date='2026-02-28')
    assert s['by_channel']['upi'] == {'count': 0, 'total': 0}


def test_channel_fields_are_integers(client):
    """ADR-005 wire contract, extended to the new fields."""
    _add_txn('UPI-SAMPLE CHAI', 5000)
    s = get_summary(client)
    for row in s['by_card']:
        for key in ('count', 'gross_debits', 'upi_count', 'upi_total'):
            assert isinstance(row[key], int), key
    for rail in ('upi', 'card'):
        assert isinstance(s['by_channel'][rail]['count'], int)
        assert isinstance(s['by_channel'][rail]['total'], int)


def test_card_with_only_credits_zero_fills_channel_fields(client):
    """A card whose rows are all credits still appears in by_card (its net is
    negative, not floored) — its channel fields must be present zeros, not a
    KeyError from the debit-only accumulator never having seen it."""
    import sqlite3

    import app as app_module
    conn = sqlite3.connect(app_module.DB_PATH)
    conn.execute("INSERT INTO accounts (kind, name) VALUES ('credit_card', 'CARD-C')")
    conn.commit()
    conn.close()
    _add_txn('REFUND ONLY', 2500, card='CARD-C', ttype='credit',
             category='Reversals & Refunds')

    s = get_summary(client)
    c = next(r for r in s['by_card'] if r['card_label'] == 'CARD-C')
    assert c['gross_debits'] == 0
    assert c['upi_count'] == 0
    assert c['upi_total'] == 0
