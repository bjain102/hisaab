"""v2 — money as integer paise (ADR-003 step 2, ADR-005; fixes audit F8).

Rebuilds `transactions` with `amount_paise INTEGER NOT NULL CHECK (amount_paise
> 0)` replacing the float `amount` column (SQLite can't drop/retype a column —
ADR-007 rebuild pattern, ids preserved, indexes recreated).

Boundary discipline (who speaks which unit after this migration):
  - parsers (pdf_parsers.py / app.PARSERS): still rupee floats — their output
    is pinned by the golden corpus and does not change.
  - DB + API wire: integer paise.
  - frontend: converts back to rupees once, at the API-client boundary
    (frontend/src/api/client.ts) — components and formatters unchanged.

Only `transactions` converts here. `milestones.target_spend` (rupees, v5) and
`rewards.value` (mixed points/rupees, v4) are later migrations' jobs.
"""


def up(conn):
    # Stash id -> original float amount for verify()'s per-row check.
    conn.execute('CREATE TEMP TABLE mig2_check AS SELECT id, amount FROM transactions')

    conn.execute('''
        CREATE TABLE transactions_new (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id    INTEGER NOT NULL REFERENCES accounts(id),
            date          TEXT NOT NULL,
            description   TEXT NOT NULL,
            amount_paise  INTEGER NOT NULL CHECK (amount_paise > 0),
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
        SELECT id, account_id, date, description,
               CAST(ROUND(amount * 100) AS INTEGER),
               type, category, bank_category, card, card_label,
               is_cashback, raw_merchant, import_batch, created_at
        FROM transactions
    ''')
    conn.execute('DROP TABLE transactions')
    conn.execute('ALTER TABLE transactions_new RENAME TO transactions')
    conn.execute('CREATE INDEX idx_txn_account_date ON transactions(account_id, date)')
    conn.execute('CREATE INDEX idx_txn_date ON transactions(date)')


def verify(conn):
    # Row count preserved by the rebuild.
    n_before = conn.execute('SELECT COUNT(*) FROM mig2_check').fetchone()[0]
    n_after = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
    assert n_after == n_before, f'row loss in rebuild: {n_before} -> {n_after}'

    # THE gate (backlog-specified): per-row |amount*100 - amount_paise| < 0.5.
    bad_rows = conn.execute('''
        SELECT COUNT(*) FROM mig2_check c
        JOIN transactions t ON t.id = c.id
        WHERE ABS(c.amount * 100 - t.amount_paise) >= 0.5
    ''').fetchone()[0]
    assert bad_rows == 0, f'{bad_rows} rows failed the per-row paise-conversion check'

    # Per-account sums within float tolerance (±1 paise per 1,000 rows; the
    # per-row check above is the real gate — this catches gross join errors).
    mismatches = conn.execute('''
        SELECT COUNT(*) FROM (
            SELECT t.account_id,
                   SUM(t.amount_paise) AS paise_sum,
                   ROUND(SUM(c.amount) * 100) AS float_sum,
                   COUNT(*) AS n
            FROM transactions t JOIN mig2_check c ON c.id = t.id
            GROUP BY t.account_id
            HAVING ABS(paise_sum - float_sum) > MAX(1, n / 1000 + 1)
        )
    ''').fetchone()[0]
    assert mismatches == 0, f'{mismatches} accounts with paise-sum drift beyond tolerance'

    # The float column is gone; the paise column exists and is INTEGER.
    cols = {r[1]: r[2] for r in conn.execute('PRAGMA table_info(transactions)')}
    assert 'amount' not in cols, 'float amount column still present'
    assert cols.get('amount_paise') == 'INTEGER', cols.get('amount_paise')

    indexes = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='transactions'")}
    assert 'idx_txn_account_date' in indexes and 'idx_txn_date' in indexes, indexes
