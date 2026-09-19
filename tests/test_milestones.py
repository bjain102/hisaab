"""Task 3.6 (app-side half): windowed milestones, progress computed live
(fixes F6). Uses the conftest `client` fixture's synthetic CARD-A dataset:

  2026-01-05  debit   1000  Food & Drinks
  2026-01-10  debit    500  Travel
  2026-01-15  credit   200  Reversals & Refunds        (a refund)
  2026-01-20  credit  5000  Credit Card Bills           (a card-bill payment)
  2026-01-25  credit    50  Reversals & Refunds, cashback=1

M4's net-spend definition (mirrored here): gross debits excluding cashback,
minus refund credits excluding Credit Card Bills payments. Over the whole of
January that's 1000 + 500 - 200 = 1300 — the card-bill payment and the
cashback credit must NOT reduce it.
"""


def create_milestone(client, card_label, name, target_spend, window_start, window_end, benefit=''):
    return client.post('/api/milestones', json={
        'card_label': card_label, 'name': name, 'target_spend': target_spend,
        'window_start': window_start, 'window_end': window_end, 'benefit': benefit,
    })


def test_progress_matches_net_spend_definition(client):
    resp = create_milestone(client, 'CARD-A', 'Full January', 10000, '2026-01-01', '2026-01-31')
    assert resp.status_code == 200

    milestones = client.get('/api/milestones').get_json()
    row = next(m for m in milestones if m['name'] == 'Full January')
    assert row['progress_paise'] == 130000  # 1300 rupees: debits 1500 - refund 200
    assert row['target_paise'] == 1000000   # 10000 rupees
    assert row['window_start'] == '2026-01-01'
    assert row['window_end'] == '2026-01-31'


def test_window_excludes_transactions_outside_it(client):
    """Narrowing the window to end before the refund/card-bill/cashback rows
    must change progress — proves windowing, not just the formula, is live."""
    resp = create_milestone(client, 'CARD-A', 'Early January', 10000, '2026-01-01', '2026-01-12')
    assert resp.status_code == 200

    milestones = client.get('/api/milestones').get_json()
    row = next(m for m in milestones if m['name'] == 'Early January')
    assert row['progress_paise'] == 150000  # only the 1000 + 500 debits are in-window


def test_window_excludes_a_different_months_spend(client, monkeypatch):
    """A transaction dated outside the window (even same account, same card)
    contributes nothing — the exact scenario the backlog verify step names:
    'a milestone windowed to exclude January'."""
    import sqlite3
    import app as app_module
    conn = sqlite3.connect(app_module.DB_PATH)
    account_id = conn.execute("SELECT id FROM accounts WHERE name='CARD-A'").fetchone()[0]
    conn.execute(
        '''INSERT INTO transactions (account_id, date, description, amount_paise, type, category, is_cashback)
           VALUES (?, '2026-03-15', 'MARCH SPEND', 700000, 'debit', 'Shopping', 0)''',
        (account_id,))
    conn.commit()
    conn.close()

    resp = create_milestone(client, 'CARD-A', 'February Only', 10000, '2026-02-01', '2026-02-28')
    assert resp.status_code == 200
    milestones = client.get('/api/milestones').get_json()
    row = next(m for m in milestones if m['name'] == 'February Only')
    assert row['progress_paise'] == 0  # neither January's nor March's spend falls in February


def test_progress_excludes_finance_charges(client):
    """A Finance Charges debit (late fee / interest) must not count toward
    a milestone — it's the bank charging you, not spend you're driving
    toward a reward."""
    import sqlite3
    import app as app_module
    conn = sqlite3.connect(app_module.DB_PATH)
    account_id = conn.execute("SELECT id FROM accounts WHERE name='CARD-A'").fetchone()[0]
    conn.execute(
        '''INSERT INTO transactions (account_id, date, description, amount_paise, type, category, is_cashback)
           VALUES (?, '2026-01-08', 'LATE PAYMENT FEE', 90000, 'debit', 'Finance Charges', 0)''',
        (account_id,))
    conn.commit()
    conn.close()

    resp = create_milestone(client, 'CARD-A', 'Excludes Finance Charges', 10000, '2026-01-01', '2026-01-31')
    assert resp.status_code == 200
    milestones = client.get('/api/milestones').get_json()
    row = next(m for m in milestones if m['name'] == 'Excludes Finance Charges')
    assert row['progress_paise'] == 130000  # unchanged from the whole-January baseline — the 900 fee is excluded


def test_unknown_card_rejected(client):
    resp = create_milestone(client, 'NO-SUCH-CARD', 'Ghost', 1000, '2026-01-01', '2026-01-31')
    assert resp.status_code == 400
    assert 'Unknown card' in resp.get_json()['error']


def test_delete_milestone(client):
    create_milestone(client, 'CARD-A', 'To Delete', 1000, '2026-01-01', '2026-01-31')
    milestones = client.get('/api/milestones').get_json()
    mid = next(m['id'] for m in milestones if m['name'] == 'To Delete')

    resp = client.delete(f'/api/milestones/{mid}')
    assert resp.status_code == 200

    milestones_after = client.get('/api/milestones').get_json()
    assert all(m['id'] != mid for m in milestones_after)
