"""Build a demo database of entirely fabricated transactions.

Why this exists: FinTrack ships with no data — statements are real financial
documents, so none are published (see tests/corpus/tier1/README.md). That
leaves anyone who clones this repo looking at empty screens. This script
produces a self-contained database with invented cards, invented statements
and invented spending, so the app can be run and read by someone who has
never touched an Indian credit-card statement.

**Nothing here is real.** The card numbers are test values (4242, 1111, …),
the amounts and dates are generated, and no output of this script has ever
been anyone's actual spending. Merchant names are real brands, deliberately:
the categorisation pipeline keys on them, so a demo full of ACME CORP would
demonstrate nothing.

The data is shaped to show the parts worth looking at, not just to fill
tables:
  - descriptions carry real rail noise — gateway prefixes (`PTM*`, `RAZ*`),
    UPI prefixes, glued city suffixes, reference blocks — so the normalizer
    has something to do;
  - one merchant appears under four different disguises, which is what the
    canonical top-merchants grouping exists to collapse;
  - roughly a sixth of spend is left un-confirmed so the review queue has
    real work in it and the trust meter reads below 100%;
  - reward balances are dated per statement so the sparklines have a series.

Deterministic: same seed, same database, so screenshots and any future
fixture use stay reproducible.

    python scripts/seed_demo.py                    # -> data/fintrack-demo.db
    python scripts/seed_demo.py --db path/to.db --force
    python app.py --demo                           # seed if needed, then serve
"""
import argparse
import os
import random
import sqlite3
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402
from db import migrate  # noqa: E402

SEED = 20260101
DEFAULT_DB = os.path.join('data', 'fintrack-demo.db')

# (institution, variant, last4) — last4s are conventional test values so no
# reader mistakes these for anyone's real cards.
CARDS = [
    ('HDFC', 'Demo Cashback', '4242'),
    ('AXIS', 'Demo Rewards', '1111'),
    ('ICICI', 'Demo Shopping', '0007'),
    ('AMEX', 'Demo Membership', '9999'),
]

# (raw description, canonical merchant, category, typical amount range, weight)
# The four SWIGGY spellings all carry the SAME canonical name on purpose: one
# merchant wearing four rail costumes is exactly what the normalizer + alias
# layer exists to collapse, and what the canonical top-merchants grouping
# shows off. Their normalized aliases collide too, which is correct — the
# first one inserted covers the rest.
MERCHANT_POOL = [
    ('UPI-SWIGGY BANGALORE', 'Swiggy', 'Food & Drinks', (180, 900), 9),
    ('SWIGGYBANGALORE', 'Swiggy', 'Food & Drinks', (150, 700), 4),
    ('RAZ*SWIGGY', 'Swiggy', 'Food & Drinks', (200, 800), 3),
    ('PTM*SWIGGY LIMITED MUMBAI', 'Swiggy', 'Food & Drinks', (160, 650), 2),
    ('UPI-ZOMATO LTD GURGAON', 'Zomato', 'Food & Drinks', (200, 1100), 7),
    ('PTM*BIGBASKET', 'BigBasket', 'Grocery', (400, 3200), 6),
    ('ZEPTO MARKETPLACE BANGALORE', 'Zepto', 'Grocery', (120, 1400), 8),
    ('RELIANCE RETAIL LIMITENAVI MUMBAI', 'Reliance Retail', 'Grocery', (300, 2600), 5),
    ('AMAZON  Mumbai', 'Amazon', 'Shopping', (250, 6500), 8),
    ('FLIPKART INTERNET PVT', 'Flipkart', 'Shopping', (300, 5200), 4),
    ('UPI-UBER INDIA SYSTEMS', 'Uber', 'Transportation', (90, 620), 9),
    ('BMTC BUS KA01F1234', 'BMTC Bus', 'Transportation', (10, 60), 6),
    ('IRCTC WEBSITE NEW DELHI', 'IRCTC', 'Travel', (450, 3400), 2),
    ('INDIGO AIRLINES', 'IndiGo', 'Travel', (3200, 14000), 1),
    ('NETFLIX.COM', 'Netflix', 'Apps & Software', (199, 799), 2),
    ('GOOGLE CLOUD INDIA', 'Google Cloud', 'Apps & Software', (80, 900), 3),
    ('BHARAT PETROLEUM KORAMANGALA', 'Bharat Petroleum', 'Fuel', (500, 3000), 4),
    ('APOLLO PHARMACY BANGALORE', 'Apollo Pharmacy', 'Medical', (120, 1800), 3),
    ('CULT FIT BANGALORE', 'Cult Fit', 'Health & Wellness', (500, 2400), 2),
    ('UPI-BESCOM BILL PAYMENT (Ref# 8891204471)', 'BESCOM', 'Utility Bills', (700, 2800), 3),
    ('AIRTEL PREPAID RECHARGE', 'Airtel', 'Utility Bills', (299, 1199), 3),
    ('PVR CINEMAS FORUM MALL', 'PVR Cinemas', 'Entertainment', (300, 1600), 2),
]

# Left deliberately unconfirmed so the review queue has real groups in it and
# the trust meter reads below 100%. These are the long tail of one-off UPI
# payees that no keyword rule can honestly classify — which is the whole
# reason the review queue exists.
UNREVIEWED_POOL = [
    ('UPI-BEERESHA M N', None, 'Others', (40, 300), 5),
    ('PTM*KRISHNA STORES', None, 'Others', (60, 700), 4),
    ('UPI-SRI LAKSHMI CONDIMENTS', None, 'Others', (30, 260), 4),
    ('RSP*THE FILTER COFFEE CO', None, 'Others', (120, 480), 3),
    ('UPI-CHANDU TAILORS BANGALORE', None, 'Others', (150, 900), 2),
    ('EASEBUZZ*APARTMENT DUES', None, 'Others', (800, 2400), 2),
]


def _month_starts(count):
    """`count` month-start dates ending with the current month."""
    today = date.today()
    out = []
    y, m = today.year, today.month
    for _ in range(count):
        out.append(date(y, m, 1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def _month_end(d):
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def _weighted(rng, pool):
    return rng.choices(pool, weights=[p[4] for p in pool], k=1)[0]


def build(conn, months=9):
    rng = random.Random(SEED)
    today = date.today()

    account_ids = []
    for institution, variant, last4 in CARDS:
        cur = conn.execute(
            'INSERT INTO accounts (kind, name, institution, identifier) VALUES (?,?,?,?)',
            ('credit_card', f'{institution}-{variant}-{last4}', institution, last4))
        account_ids.append(cur.lastrowid)

    # Confirmed merchants — the "fix it once" layer. Every alias is the
    # normalized form of its raw description, which is what the longest-
    # substring matcher looks for.
    from categorization import normalize
    merchant_ids, seen_aliases = {}, set()
    for raw, canonical, category, _amt, _w in MERCHANT_POOL:
        if canonical not in merchant_ids:
            cur = conn.execute(
                "INSERT INTO merchants (canonical_name, category, status) VALUES (?,?,'confirmed')",
                (canonical, category))
            merchant_ids[canonical] = cur.lastrowid
        alias = normalize(raw)
        # merchant_aliases.pattern is UNIQUE: two disguises of one merchant
        # routinely normalize to the same alias, and ONE row covering both is
        # the intended outcome, not a collision to work around.
        if alias and alias not in seen_aliases:
            conn.execute('INSERT INTO merchant_aliases (merchant_id, pattern) VALUES (?,?)',
                         (merchant_ids[canonical], alias))
            seen_aliases.add(alias)
        merchant_ids[raw] = merchant_ids[canonical]

    total_rows = 0
    for account_id in account_ids:
        # Each card has its own spend personality, so the by-card breakdown
        # and the UPI-vs-card lens have something to differentiate.
        appetite = rng.uniform(0.6, 1.5)
        for start in _month_starts(months):
            end = min(_month_end(start), today)
            if start > today:
                continue
            cur = conn.execute(
                '''INSERT INTO statements (account_id, period_start, period_end, format,
                                           txn_count, original_filename)
                   VALUES (?,?,?,'pdf',0,?)''',
                (account_id, start.isoformat(), end.isoformat(),
                 f'demo-statement-{start:%Y-%m}.pdf'))
            statement_id = cur.lastrowid

            n = int(rng.randint(9, 22) * appetite)
            count = 0
            for _ in range(n):
                unreviewed = rng.random() < 0.18
                raw, _canonical, category, (lo, hi), _w = _weighted(
                    rng, UNREVIEWED_POOL if unreviewed else MERCHANT_POOL)
                day = rng.randint(1, (end - start).days + 1)
                when = start + timedelta(days=day - 1)
                if when > today:
                    continue
                amount = round(rng.uniform(lo, hi), 2)
                conn.execute(
                    '''INSERT INTO transactions
                       (account_id, statement_id, date, description, raw_description,
                        amount_paise, type, category, is_cashback, merchant_id, category_source)
                       VALUES (?,?,?,?,?,?,'debit',?,0,?,?)''',
                    (account_id, statement_id, when.isoformat(), raw, raw,
                     int(round(amount * 100)), category,
                     None if unreviewed else merchant_ids.get(raw),
                     'keyword' if unreviewed else 'confirmed'))
                count += 1

            # One bill payment and an occasional refund/cashback per cycle —
            # without these the net-spend maths has nothing to exclude.
            bill = round(rng.uniform(4000, 26000), 2)
            conn.execute(
                '''INSERT INTO transactions
                   (account_id, statement_id, date, description, raw_description,
                    amount_paise, type, category, is_cashback, category_source)
                   VALUES (?,?,?,?,?,?,'credit','Credit Card Bills',0,'keyword')''',
                (account_id, statement_id, (start + timedelta(days=rng.randint(2, 12))).isoformat(),
                 'BPPY CC PAYMENT', 'BPPY CC PAYMENT', int(round(bill * 100))))
            count += 1
            if rng.random() < 0.5:
                conn.execute(
                    '''INSERT INTO transactions
                       (account_id, statement_id, date, description, raw_description,
                        amount_paise, type, category, is_cashback, category_source)
                       VALUES (?,?,?,?,?,?,'credit','Reversals & Refunds',?,'keyword')''',
                    (account_id, statement_id,
                     (start + timedelta(days=rng.randint(3, 20))).isoformat(),
                     'CASHBACK CREDIT', 'CASHBACK CREDIT',
                     int(round(rng.uniform(20, 400) * 100)), 1))
                count += 1

            conn.execute('UPDATE statements SET txn_count=? WHERE id=?', (count, statement_id))
            total_rows += count

            # A dated reward balance per statement — this is what the Rewards
            # sparkline plots, and dating it per cycle is exactly what stops an
            # out-of-order import from regressing it.
            label, value_type, value = (
                ('Cashback', 'cashback_paise', int(rng.uniform(200, 3000) * 100))
                if account_id == account_ids[0]
                else ('Points', 'points', rng.randint(800, 40000)))
            conn.execute(
                '''INSERT INTO reward_balances (account_id, as_of, label, value_minor, value_type, source)
                   VALUES (?,?,?,?,?,'statement')
                   ON CONFLICT(account_id, as_of) DO NOTHING''',
                (account_id, end.isoformat(), label, value, value_type))

    # Two milestones: one comfortably in progress, one barely started.
    window_start = _month_starts(months)[0].isoformat()
    window_end = (today + timedelta(days=120)).isoformat()
    conn.execute(
        '''INSERT INTO milestones (account_id, name, target_paise, window_start, window_end, benefit)
           VALUES (?,?,?,?,?,?)''',
        (account_ids[0], 'Annual fee waiver', 15_000_000, window_start, window_end,
         'Renewal fee waived'))
    conn.execute(
        '''INSERT INTO milestones (account_id, name, target_paise, window_start, window_end, benefit)
           VALUES (?,?,?,?,?,?)''',
        (account_ids[1], 'Bonus 5,000 points', 40_000_000, window_start, window_end,
         '5,000 bonus points'))

    conn.commit()
    return total_rows


def seed(db_path=DEFAULT_DB, force=False, quiet=False):
    """Create `db_path` and fill it with demo data. Refuses to touch a file
    that already exists unless `force` — this script writes fiction, and
    silently overwriting somebody's real database with it would be the worst
    bug in the repository."""
    if os.path.exists(db_path):
        if not force:
            raise SystemExit(
                f'{db_path} already exists — refusing to overwrite it.\n'
                f'Delete it, pass --force, or point --db somewhere else.')
        os.remove(db_path)
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

    original = app_module.DB_PATH
    app_module.DB_PATH = db_path
    try:
        app_module.init_db()
        migrate(db_path)
    finally:
        app_module.DB_PATH = original

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = build(conn)
    finally:
        conn.close()
    if not quiet:
        print(f'Demo database written to {db_path}: {rows} fabricated transactions '
              f'across {len(CARDS)} invented cards.')
    return db_path


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Generate a demo FinTrack database (all data fabricated).')
    ap.add_argument('--db', default=DEFAULT_DB, help=f'output path (default: {DEFAULT_DB})')
    ap.add_argument('--force', action='store_true', help='overwrite the file if it already exists')
    args = ap.parse_args()
    seed(args.db, force=args.force)
