"""Shared fixtures: a synthetic SQLite DB in a temp dir, wired into the app
by monkeypatching app.DB_PATH. No real data is ever touched by tests."""
import sqlite3

import pytest

import app as app_module

# Synthetic dataset with hand-computable expectations.
# (date, description, amount, type, category, card, card_label, is_cashback)
SEED_ROWS = [
    # CARD-A, January
    ('2026-01-05', 'SAMPLE RESTAURANT', 1000.00, 'debit',  'Food & Drinks',       'ALPHA', 'CARD-A', 0),
    ('2026-01-10', 'SAMPLE AIRLINE',    500.00,  'debit',  'Travel',              'ALPHA', 'CARD-A', 0),
    ('2026-01-15', 'REFUND SAMPLE',     200.00,  'credit', 'Reversals & Refunds', 'ALPHA', 'CARD-A', 0),
    ('2026-01-20', 'CARD BILL PAYMENT', 5000.00, 'credit', 'Credit Card Bills',   'ALPHA', 'CARD-A', 0),
    ('2026-01-25', 'CASHBACK CREDIT',   50.00,   'credit', 'Reversals & Refunds', 'ALPHA', 'CARD-A', 1),
    # CARD-B, February
    ('2026-02-03', 'SAMPLE STORE',      2000.00, 'debit',  'Shopping',            'BRAVO', 'CARD-B', 0),
    ('2026-02-04', 'SAMPLE CAFE',       300.00,  'debit',  'Food & Drinks',       'BRAVO', 'CARD-B', 0),
]

# Hand-computed expectations for the full range, all cards:
#   gross debits            = 1000 + 500 + 2000 + 300 = 3800
#   refund credits          = 200   (bill payment excluded, cashback excluded)
#   net spend               = 3600
#   cashback total / count  = 50 / 1
#   monthly: 2026-01 = 1500 - 200 = 1300 ; 2026-02 = 2300
#   monthly_by_category:
#     2026-01: Food 1000, Travel 500, Reversals & Refunds -200
#     2026-02: Shopping 2000, Food 300


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / 'test.db')
    monkeypatch.setattr(app_module, 'DB_PATH', db_path)
    monkeypatch.setattr(app_module, 'STATEMENTS_DIR', str(tmp_path / 'statements'))
    app_module.init_db()

    conn = sqlite3.connect(db_path)
    conn.executemany(
        '''INSERT INTO transactions
           (date, description, amount, type, category, card, card_label, is_cashback, import_batch)
           VALUES (?,?,?,?,?,?,?,?, 'test-batch')''',
        SEED_ROWS,
    )
    conn.commit()
    conn.close()

    # Mirror production: legacy schema is seeded, then migrations run before
    # the app ever serves a request (app.py __main__ does exactly this). The
    # API layer is therefore always tested against the CURRENT schema version.
    from db import migrate
    migrate(db_path)

    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as c:
        yield c
