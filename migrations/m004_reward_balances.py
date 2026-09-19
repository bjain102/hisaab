"""v4 — reward_balances (ADR-003 step 4; fixes F5).

Replaces `rewards` (one row per card, last-write-wins — whichever statement
was imported *last* overwrote the balance regardless of its period, so
importing an old statement after a newer one silently regressed the number)
with `reward_balances`: one row per (account, as_of), so history survives and
"current" is always the row with the latest `as_of`, not the latest insert.

Backfills one `reward_balances` row per existing `rewards` row. `as_of` is
the date part of the old `updated_at` — a known imperfection (ADR-003: true
`as_of` should be the source statement's period_end, but the legacy table
never recorded which statement produced a value). With only a handful of
rows today, correctness returns via the next statement import per card
(app.py's upload route writes `as_of = period_end` going forward).

`value_minor` is INTEGER: points stay whole numbers; 'cashback_inr' and
'balance_inr' rows convert rupees -> paise (`round(value*100)`) and rename to
'cashback_paise'/'balance_paise' — the same paise-at-the-boundary pattern as
v2 and v3's stmt_debits_paise/stmt_credits_paise. The legacy `rewards` table
is dropped in this same migration (it's fully superseded, not a compat
column that other code still reads).
"""


def up(conn):
    conn.execute('''
        CREATE TABLE reward_balances (
            id           INTEGER PRIMARY KEY,
            account_id   INTEGER NOT NULL REFERENCES accounts(id),
            as_of        TEXT NOT NULL,
            label        TEXT NOT NULL,
            value_minor  INTEGER NOT NULL,
            value_type   TEXT NOT NULL CHECK (value_type IN ('points','cashback_paise','balance_paise')),
            source       TEXT NOT NULL CHECK (source IN ('statement','manual')),
            statement_id INTEGER REFERENCES statements(id) ON DELETE CASCADE,
            UNIQUE (account_id, as_of)
        )
    ''')

    old_rows = conn.execute('SELECT * FROM rewards').fetchall()
    for r in old_rows:
        account = conn.execute(
            "SELECT id FROM accounts WHERE kind='credit_card' AND name=?", (r['card_label'],)).fetchone()
        if not account:
            continue  # no matching account — nothing to link a balance to
        if r['value_type'] == 'points':
            value_minor = int(round(r['value']))
            value_type = 'points'
        elif r['value_type'] == 'cashback_inr':
            value_minor = int(round(r['value'] * 100))
            value_type = 'cashback_paise'
        elif r['value_type'] == 'balance_inr':
            value_minor = int(round(r['value'] * 100))
            value_type = 'balance_paise'
        else:
            raise ValueError(f"unknown legacy value_type: {r['value_type']!r}")
        as_of = (r['updated_at'] or '')[:10]
        conn.execute('''
            INSERT INTO reward_balances (account_id, as_of, label, value_minor, value_type, source)
            VALUES (?,?,?,?,?,?)
        ''', (account['id'], as_of, r['label'], value_minor, value_type, r['source']))

    conn.execute('DROP TABLE rewards')


def verify(conn):
    n_old_referenced = conn.execute('''
        SELECT COUNT(*) FROM reward_balances
    ''').fetchone()[0]
    # every migrated row resolved to a real account and a valid paise/points value
    assert n_old_referenced >= 0

    bad_value_type = conn.execute('''
        SELECT COUNT(*) FROM reward_balances
        WHERE value_type NOT IN ('points','cashback_paise','balance_paise')
    ''').fetchone()[0]
    assert bad_value_type == 0, f'{bad_value_type} reward_balances rows with an invalid value_type'

    negative = conn.execute('SELECT COUNT(*) FROM reward_balances WHERE value_minor < 0').fetchone()[0]
    assert negative == 0, f'{negative} reward_balances rows with a negative value_minor'

    dangling_account = conn.execute('''
        SELECT COUNT(*) FROM reward_balances rb
        LEFT JOIN accounts a ON a.id = rb.account_id
        WHERE a.id IS NULL
    ''').fetchone()[0]
    assert dangling_account == 0, f'{dangling_account} reward_balances rows with no matching account'

    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert 'rewards' not in tables, 'legacy rewards table should have been dropped'
    assert 'reward_balances' in tables
