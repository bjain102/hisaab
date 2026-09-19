"""v6 — drop legacy tables + columns (ADR-003 step 6; closes F10).

Everything `import_batches` and `card_profiles` recorded is now covered by
tables introduced in v1/v3: `accounts` (the card registry, replacing
`card_profiles`) and `statements` (one row per import, replacing
`import_batches`). This migration removes the now-redundant originals and the
`transactions` columns that only existed to support them (`card`,
`card_label`, `import_batch`), plus renames `raw_merchant` -> `raw_description`
to match ADR-003's canonical schema (a pure rename — its value is still
`description` verbatim; making it a genuinely distinct, never-mutated raw
field is a Phase 4 categorization-pipeline concern, not this migration's).

Two honesty-preserving backfills happen BEFORE anything is dropped, since
the source data disappears once the drop runs:

1. Any `card_profiles` row whose label has no matching `accounts` row yet
   (a card registered but never imported into) gets one created — otherwise
   dropping `card_profiles` would silently forget that card exists.
2. `statements.original_filename` (new nullable column) is backfilled from
   `import_batches.filename` via the `transactions.import_batch` linkage —
   otherwise the 29 pre-3.4 statements (which never got a `source_path` of
   their own, per m003's honesty note) would lose their last remaining
   filename, regressing the Import view's history list. New imports from
   here on populate this column directly at upload time.
"""


def up(conn):
    # ── 1. Rescue any never-imported card profiles before card_profiles goes away ──
    conn.execute('''
        INSERT INTO accounts (kind, name, institution, identifier)
        SELECT 'credit_card', cp.label, UPPER(cp.bank), cp.last4
        FROM card_profiles cp
        LEFT JOIN accounts a ON a.kind = 'credit_card' AND a.name = cp.label
        WHERE a.id IS NULL
    ''')

    # ── 2. Rescue historical filenames before import_batches goes away ──
    conn.execute('ALTER TABLE statements ADD COLUMN original_filename TEXT')
    conn.execute('''
        UPDATE statements SET original_filename = (
            SELECT b.filename FROM import_batches b
            JOIN transactions t ON t.import_batch = b.batch_id
            WHERE t.statement_id = statements.id
            LIMIT 1
        )
        WHERE original_filename IS NULL
    ''')

    # ── 3. Rebuild transactions without card/card_label/import_batch ──
    conn.execute('CREATE TEMP TABLE mig6_precount AS SELECT COUNT(*) AS n FROM transactions')
    conn.execute('''
        CREATE TABLE transactions_new (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id      INTEGER NOT NULL REFERENCES accounts(id),
            statement_id    INTEGER REFERENCES statements(id),
            date            TEXT NOT NULL,
            description     TEXT NOT NULL,
            raw_description TEXT,
            amount_paise    INTEGER NOT NULL CHECK (amount_paise > 0),
            type            TEXT NOT NULL,
            category        TEXT NOT NULL,
            bank_category   TEXT,
            is_cashback     INTEGER DEFAULT 0,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('''
        INSERT INTO transactions_new
        SELECT id, account_id, statement_id, date, description, raw_merchant,
               amount_paise, type, category, bank_category, is_cashback, created_at
        FROM transactions
    ''')
    conn.execute('DROP TABLE transactions')
    conn.execute('ALTER TABLE transactions_new RENAME TO transactions')
    conn.execute('CREATE INDEX idx_txn_account_date ON transactions(account_id, date)')
    conn.execute('CREATE INDEX idx_txn_date ON transactions(date)')

    # ── 4. Drop the now-redundant legacy tables ──
    conn.execute('DROP TABLE import_batches')
    conn.execute('DROP TABLE card_profiles')


def verify(conn):
    n_before = conn.execute('SELECT n FROM mig6_precount').fetchone()[0]
    n_after = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
    assert n_after == n_before, f'row loss in rebuild: {n_before} -> {n_after}'

    cols = {r[1] for r in conn.execute('PRAGMA table_info(transactions)')}
    assert not ({'card', 'card_label', 'import_batch'} & cols), cols
    assert 'raw_description' in cols and 'raw_merchant' not in cols, cols

    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert 'import_batches' not in tables and 'card_profiles' not in tables, tables

    indexes = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='transactions'")}
    assert 'idx_txn_account_date' in indexes and 'idx_txn_date' in indexes, indexes

    # Every account referenced by transactions still resolves (rebuild didn't
    # silently drop the join integrity established back in v1).
    dangling = conn.execute('''
        SELECT COUNT(*) FROM transactions t
        LEFT JOIN accounts a ON a.id = t.account_id
        WHERE a.id IS NULL
    ''').fetchone()[0]
    assert dangling == 0, f'{dangling} transactions with no matching account'

    # Historical statements (no source_path of their own) kept a filename.
    missing_filename = conn.execute('''
        SELECT COUNT(*) FROM statements
        WHERE source_path IS NULL AND original_filename IS NULL AND txn_count > 0
    ''').fetchone()[0]
    assert missing_filename == 0, f'{missing_filename} historical statements lost their filename'
