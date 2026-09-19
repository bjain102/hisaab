"""v3 — statements table + linkage (ADR-003 step 3; enables the F4 dedup gate).

Creates `statements` and backfills one row per `import_batches` row that still
has transactions (period = min/max transaction date in that batch — the best
available signal; the original files were parse-and-discarded pre-Phase 1, so
`source_path`/`file_sha256`/printed-totals are honestly NULL for migrated
rows). Adds nullable `transactions.statement_id` (plain ALTER — no rebuild
needed for a nullable column) and links via the legacy `import_batch`
timestamp string. `import_batches` itself survives until v6.

Existing overlapping periods are ALLOWED to migrate — gating applies to new
imports only — but an **overlap report** is printed for the 3.7 cleanup task.

DELIBERATE DEVIATION from ADR-003's DDL, discovered at implementation: the
ADR's `UNIQUE (account_id, period_start, period_end)` is omitted. It would
make the owner-approved `force=true` override physically impossible for
identical-period re-imports (a re-downloaded statement carries the same
printed cycle with different bytes), contradicting the ADR's own app-level
"gating ... unless force=true" design. Exact-duplicate *files* are still hard-
rejected via UNIQUE file_sha256; identical periods are caught by the same
app-level overlap check as any other overlap.
"""


def up(conn):
    conn.execute('''
        CREATE TABLE statements (
            id                 INTEGER PRIMARY KEY,
            account_id         INTEGER NOT NULL REFERENCES accounts(id),
            period_start       TEXT NOT NULL,
            period_end         TEXT NOT NULL,
            format             TEXT NOT NULL CHECK (format IN ('pdf','csv')),
            source_path        TEXT,
            file_sha256        TEXT UNIQUE,
            txn_count          INTEGER NOT NULL DEFAULT 0,
            stmt_debits_paise  INTEGER,
            stmt_credits_paise INTEGER,
            imported_at        TEXT NOT NULL DEFAULT (datetime('now'))
        )
    ''')
    conn.execute('ALTER TABLE transactions ADD COLUMN statement_id INTEGER REFERENCES statements(id)')

    batches = conn.execute('''
        SELECT b.batch_id, b.filename, b.imported_at,
               a.id AS account_id,
               MIN(t.date) AS period_start, MAX(t.date) AS period_end,
               COUNT(t.id) AS txn_count
        FROM import_batches b
        JOIN transactions t ON t.import_batch = b.batch_id
        JOIN accounts a ON a.id = t.account_id
        GROUP BY b.batch_id
        ORDER BY b.imported_at
    ''').fetchall()

    for b in batches:
        fmt = 'csv' if (b['filename'] or '').lower().endswith('.csv') else 'pdf'
        cur = conn.execute('''
            INSERT INTO statements (account_id, period_start, period_end, format,
                                    source_path, file_sha256, txn_count, imported_at)
            VALUES (?,?,?,?,NULL,NULL,?,?)
        ''', (b['account_id'], b['period_start'], b['period_end'], fmt,
              b['txn_count'], b['imported_at']))
        conn.execute('UPDATE transactions SET statement_id=? WHERE import_batch=?',
                     (cur.lastrowid, b['batch_id']))

    # ── Overlap report (feeds task 3.7's one-time cleanup) ──
    overlaps = conn.execute('''
        SELECT a.name AS account, s1.id AS id1, s1.period_start AS start1, s1.period_end AS end1,
               s2.id AS id2, s2.period_start AS start2, s2.period_end AS end2,
               s1.txn_count AS n1, s2.txn_count AS n2
        FROM statements s1
        JOIN statements s2 ON s2.account_id = s1.account_id AND s2.id > s1.id
        JOIN accounts a ON a.id = s1.account_id
        WHERE NOT (s1.period_end < s2.period_start OR s1.period_start > s2.period_end)
        ORDER BY a.name
    ''').fetchall()
    if overlaps:
        print(f'\n  OVERLAP REPORT — {len(overlaps)} overlapping statement pairs '
              f'(pre-existing double-counts; task 3.7 cleans these up):')
        for o in overlaps:
            print(f"    {o['account']}: stmt#{o['id1']} [{o['start1']}..{o['end1']}, {o['n1']} txns]"
                  f" overlaps stmt#{o['id2']} [{o['start2']}..{o['end2']}, {o['n2']} txns]")
    else:
        print('\n  OVERLAP REPORT — no overlapping statements found.')


def verify(conn):
    # Every batch that has transactions produced exactly one statement.
    n_batches = conn.execute('''
        SELECT COUNT(DISTINCT b.batch_id) FROM import_batches b
        JOIN transactions t ON t.import_batch = b.batch_id
    ''').fetchone()[0]
    n_statements = conn.execute('SELECT COUNT(*) FROM statements').fetchone()[0]
    assert n_statements == n_batches, f'{n_statements} statements != {n_batches} batches with txns'

    # Every transaction belonging to a real batch is linked; period sanity.
    unlinked = conn.execute('''
        SELECT COUNT(*) FROM transactions t
        JOIN import_batches b ON b.batch_id = t.import_batch
        WHERE t.statement_id IS NULL
    ''').fetchone()[0]
    assert unlinked == 0, f'{unlinked} batch-backed transactions missing statement_id'

    bad_periods = conn.execute(
        'SELECT COUNT(*) FROM statements WHERE period_start > period_end').fetchone()[0]
    assert bad_periods == 0, f'{bad_periods} statements with inverted periods'

    # Linked transactions fall inside their statement period and match accounts.
    out_of_period = conn.execute('''
        SELECT COUNT(*) FROM transactions t
        JOIN statements s ON s.id = t.statement_id
        WHERE t.date < s.period_start OR t.date > s.period_end OR t.account_id != s.account_id
    ''').fetchone()[0]
    assert out_of_period == 0, f'{out_of_period} linked txns outside period or wrong account'

    # Per-statement counts match.
    count_mismatch = conn.execute('''
        SELECT COUNT(*) FROM statements s
        WHERE s.txn_count != (SELECT COUNT(*) FROM transactions t WHERE t.statement_id = s.id)
    ''').fetchone()[0]
    assert count_mismatch == 0, f'{count_mismatch} statements with wrong txn_count'
