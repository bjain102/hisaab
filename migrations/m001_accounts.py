"""v1 — accounts (ADR-003 migration step 1).

Creates the `accounts` table (the spine of the unified data model: everything
is an account), seeds one `credit_card` account per distinct
`transactions.card_label`, enriched with institution/identifier from
`card_profiles` where a profile's label matches (fallbacks: institution from
the transaction rows' own `card` column, identifier from the label's trailing
-NNNN digits). Then rebuilds `transactions` with `account_id INTEGER NOT NULL
REFERENCES accounts(id)` — SQLite can't add a NOT NULL column to an existing
table, so this uses the ADR-007 table-rebuild pattern (create new, copy via
label join, drop old, rename), preserving row ids.

`card`/`card_label`/`card_profiles` stay untouched — they remain the API's
source until v6 drops them.

Honesty property: a transaction whose card_label matches no account (e.g. a
NULL label) is DROPPED by the backfill join — the row-count check in verify()
turns that into a loud failure instead of silent data loss.
"""


def up(conn):
    # Stash the pre-rebuild row count for verify(); TEMP tables are
    # connection-scoped, so this never leaks into the committed schema.
    conn.execute('CREATE TEMP TABLE mig1_precount AS SELECT COUNT(*) AS n FROM transactions')

    conn.execute('''
        CREATE TABLE accounts (
            id           INTEGER PRIMARY KEY,
            kind         TEXT NOT NULL CHECK (kind IN
                         ('credit_card','equity','mutual_fund','epf','ppf',
                          'gold','property','bank','loan')),
            name         TEXT NOT NULL,
            institution  TEXT,
            identifier   TEXT,
            is_active    INTEGER NOT NULL DEFAULT 1,
            meta         TEXT NOT NULL DEFAULT '{}',
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (kind, name)
        )
    ''')

    profiles = {r['label']: r for r in conn.execute('SELECT * FROM card_profiles')}
    labels = [r['card_label'] for r in conn.execute(
        'SELECT DISTINCT card_label FROM transactions WHERE card_label IS NOT NULL ORDER BY card_label')]
    for label in labels:
        profile = profiles.get(label)
        if profile is not None:
            institution = profile['bank'].upper()
            identifier = profile['last4']
        else:
            row = conn.execute(
                'SELECT card FROM transactions WHERE card_label=? LIMIT 1', (label,)).fetchone()
            institution = row['card'] if row else None
            # trailing -NNNN in the label is the card's last4 by construction
            tail = label.rsplit('-', 1)[-1]
            identifier = tail if tail.isdigit() and len(tail) == 4 else None
        conn.execute(
            "INSERT INTO accounts (kind, name, institution, identifier) VALUES ('credit_card', ?, ?, ?)",
            (label, institution, identifier))

    conn.execute('''
        CREATE TABLE transactions_new (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id    INTEGER NOT NULL REFERENCES accounts(id),
            date          TEXT NOT NULL,
            description   TEXT NOT NULL,
            amount        REAL NOT NULL,
            type          TEXT NOT NULL,
            category      TEXT NOT NULL,
            bank_category TEXT,
            card          TEXT NOT NULL,
            card_label    TEXT,
            is_cashback   INTEGER DEFAULT 0,
            raw_merchant  TEXT,
            import_batch  TEXT,
            created_at    TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('''
        INSERT INTO transactions_new
        SELECT t.id, a.id, t.date, t.description, t.amount, t.type, t.category,
               t.bank_category, t.card, t.card_label, t.is_cashback,
               t.raw_merchant, t.import_batch, t.created_at
        FROM transactions t
        JOIN accounts a ON a.kind = 'credit_card' AND a.name = t.card_label
    ''')
    conn.execute('DROP TABLE transactions')
    conn.execute('ALTER TABLE transactions_new RENAME TO transactions')
    conn.execute('CREATE INDEX idx_txn_account_date ON transactions(account_id, date)')
    conn.execute('CREATE INDEX idx_txn_date ON transactions(date)')


def verify(conn):
    # Backlog-specified invariants, plus row-loss and name-consistency checks.
    n_null = conn.execute(
        'SELECT COUNT(*) FROM transactions WHERE account_id IS NULL').fetchone()[0]
    assert n_null == 0, f'{n_null} transactions without account_id'

    n_before = conn.execute('SELECT n FROM mig1_precount').fetchone()[0]
    n_after = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
    assert n_after == n_before, f'row loss in rebuild: {n_before} -> {n_after}'

    n_labels = conn.execute(
        'SELECT COUNT(DISTINCT card_label) FROM transactions').fetchone()[0]
    n_accounts = conn.execute(
        "SELECT COUNT(*) FROM accounts WHERE kind='credit_card'").fetchone()[0]
    assert n_accounts == n_labels, f'{n_accounts} accounts != {n_labels} distinct labels'

    mismatched_names = conn.execute('''
        SELECT COUNT(*) FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE a.name != t.card_label
    ''').fetchone()[0]
    assert mismatched_names == 0, f'{mismatched_names} rows joined to the wrong account'

    per_account_mismatches = conn.execute('''
        SELECT COUNT(*) FROM (
            SELECT a.id FROM accounts a
            WHERE a.kind = 'credit_card'
            GROUP BY a.id
            HAVING (SELECT COUNT(*) FROM transactions t WHERE t.account_id = a.id)
                != (SELECT COUNT(*) FROM transactions t2 WHERE t2.card_label = a.name)
        )
    ''').fetchone()[0]
    assert per_account_mismatches == 0, f'{per_account_mismatches} accounts with count mismatch'

    indexes = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='transactions'")}
    assert 'idx_txn_account_date' in indexes and 'idx_txn_date' in indexes, indexes
