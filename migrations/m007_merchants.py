"""v7 — merchant-level categorization pipeline (ADR-009; fixes F9).

Introduces `merchants`, `merchant_aliases`, `issuer_category_map`, and adds
`transactions.merchant_id` + `transactions.category_source`. Migrates the
existing `category_overrides` rows to confirmed merchants (they were human
decisions — kept verbatim, deduped later in the 4.3 review UI, not here), then
backfills every transaction's source/merchant link by the ADR-009 precedence
ladder, then drops `category_overrides`.

THE TRUST GUARANTEE (backlog 4.2): the backfill NEVER changes a transaction's
`category`. It only stamps `category_source` and links `merchant_id`. Where the
new deterministic precedence *disagrees* with the stored category — e.g. the 15
"AMAZON  Mumbai" rows the owner had manually pinned to Insurance/Transportation
/etc. despite the amazon->Grocery override — the stored category is preserved
and stamped `category_source='manual'` (so it survives every future recompute,
ADR precedence ⓪), and every such row is printed for owner review. This is
strictly stronger than "no category changed unless its source improved": no
category changes at all.

Precedence used to stamp source (category preserved throughout):
  ① confirmed-merchant alias (longest normalized-substring match, ties newest)
  ③ issuer_category_map on (institution, bank_category)
  ④ keyword rule (app.categorize) / the cashback auto-rule
  → if the stored category matches none of the above, it's a manual pin.
(② suggested merchants don't exist yet — they arrive via the 4.3 review queue.)
"""
from categorization import normalize

_SOURCE_CHECK = "('confirmed','suggested','bank','keyword','manual','none')"


def up(conn):
    # app.categorize is the keyword fallback (its rule map lives there). Safe to
    # import here: migrations run only after app.py is fully imported, and
    # importing app has no side effects (the server starts only under __main__).
    from app import categorize

    conn.execute('CREATE TEMP TABLE mig7_pre AS SELECT id, category FROM transactions')
    override_count = conn.execute('SELECT COUNT(*) FROM category_overrides').fetchone()[0]
    conn.execute(f'CREATE TEMP TABLE mig7_ovcount AS SELECT {override_count} AS n')

    # ── schema ──────────────────────────────────────────────────────────────
    conn.execute('''
        CREATE TABLE merchants (
            id             INTEGER PRIMARY KEY,
            canonical_name TEXT NOT NULL UNIQUE,
            category       TEXT NOT NULL,
            status         TEXT NOT NULL CHECK (status IN ('confirmed','suggested')),
            created_at     TEXT NOT NULL DEFAULT (datetime('now'))
        )
    ''')
    conn.execute('''
        CREATE TABLE merchant_aliases (
            id          INTEGER PRIMARY KEY,
            merchant_id INTEGER NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
            pattern     TEXT NOT NULL UNIQUE
        )
    ''')
    conn.execute('''
        CREATE TABLE issuer_category_map (
            id            INTEGER PRIMARY KEY,
            institution   TEXT NOT NULL,
            bank_category TEXT NOT NULL,
            category      TEXT NOT NULL,
            UNIQUE (institution, bank_category)
        )
    ''')

    # ── seed merchants + aliases from category_overrides ────────────────────
    # One confirmed merchant per override row (canonical_name = title-cased raw
    # pattern; unique because the patterns were a PRIMARY KEY). The alias is the
    # NORMALIZED pattern — the useful match key. Normalized collisions (e.g. the
    # 4 "california burrito*" overrides) share one alias, so the duplicate
    # merchants are alias-less until the owner merges them in review; the empty
    # normalization of a pure payment-ref override likewise gets no alias.
    seen_aliases = set()
    for row in conn.execute('SELECT merchant_pattern, category FROM category_overrides'):
        pattern, category = row[0], row[1]
        cur = conn.execute(
            "INSERT INTO merchants (canonical_name, category, status) VALUES (?,?,'confirmed')",
            (pattern.title(), category))
        merchant_id = cur.lastrowid
        alias = normalize(pattern)
        if alias and alias not in seen_aliases:
            conn.execute('INSERT INTO merchant_aliases (merchant_id, pattern) VALUES (?,?)',
                         (merchant_id, alias))
            seen_aliases.add(alias)

    # ── seed issuer_category_map from live (institution, bank_category) ──────
    # Value = the most-common app-category currently stored for that pair (owner
    # reviews once, per ADR-009). Few rows; small in-Python aggregation is fine.
    pair_counts = {}
    for row in conn.execute('''
            SELECT a.institution AS inst, t.bank_category AS bc, t.category AS cat
            FROM transactions t JOIN accounts a ON a.id = t.account_id
            WHERE t.bank_category IS NOT NULL AND t.bank_category != ''
    '''):
        key = (row[0], row[1])
        pair_counts.setdefault(key, {})
        pair_counts[key][row[2]] = pair_counts[key].get(row[2], 0) + 1
    for (inst, bc), cats in pair_counts.items():
        best = max(cats.items(), key=lambda kv: kv[1])[0]
        conn.execute('INSERT INTO issuer_category_map (institution, bank_category, category) VALUES (?,?,?)',
                     (inst, bc, best))

    # ── rebuild transactions with merchant_id + category_source ─────────────
    # (ADR-007 pattern — SQLite can't ADD a NOT NULL CHECK column cleanly; and a
    # rebuild keeps the schema honest. Existing columns/values copied verbatim.)
    conn.execute(f'''
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
            merchant_id     INTEGER REFERENCES merchants(id),
            category_source TEXT NOT NULL DEFAULT 'none' CHECK (category_source IN {_SOURCE_CHECK}),
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('''
        INSERT INTO transactions_new
        SELECT id, account_id, statement_id, date, description, raw_description,
               amount_paise, type, category, bank_category, is_cashback,
               NULL, 'none', created_at
        FROM transactions
    ''')
    conn.execute('DROP TABLE transactions')
    conn.execute('ALTER TABLE transactions_new RENAME TO transactions')
    conn.execute('CREATE INDEX idx_txn_account_date ON transactions(account_id, date)')
    conn.execute('CREATE INDEX idx_txn_date ON transactions(date)')

    # ── backfill source + merchant link (category preserved throughout) ─────
    aliases = list(conn.execute('''
        SELECT ma.pattern, ma.id, m.id AS merchant_id, m.category
        FROM merchant_aliases ma JOIN merchants m ON m.id = ma.merchant_id
    '''))
    # longest pattern wins; ties -> newest alias id
    aliases.sort(key=lambda r: (len(r[0]), r[1]), reverse=True)
    issuer = {(r[0], r[1]): r[2] for r in conn.execute(
        'SELECT institution, bank_category, category FROM issuer_category_map')}

    disagreements = []
    for t in conn.execute('''
            SELECT t.id, t.description, t.raw_description, t.category, t.bank_category,
                   t.is_cashback, t.type, a.institution AS inst
            FROM transactions t JOIN accounts a ON a.id = t.account_id''').fetchall():
        tid, desc, raw, category, bank_cat = t[0], t[1], t[2], t[3], t[4]
        is_cb, ttype, inst = t[5], t[6], t[7]
        nd = normalize(raw or desc)

        source, merchant_id = None, None
        # ① confirmed alias
        for pat, _aid, mid, mcat in aliases:
            if pat in nd:
                if mcat == category:
                    source, merchant_id = 'confirmed', mid
                # matched but category differs -> a manual pin (handled below)
                break
        if source is None:
            # ③ issuer map
            if bank_cat and (inst, bank_cat) in issuer and issuer[(inst, bank_cat)] == category:
                source = 'bank'
            # ④ keyword / cashback auto-rule
            elif is_cb and ttype == 'credit' and category == 'Reversals & Refunds':
                source = 'keyword'
            elif categorize(desc) == category:
                source = 'keyword'
            else:
                # stored category matches no automatic rule -> a manual pin.
                source = 'manual'
                disagreements.append((tid, desc, category))

        conn.execute('UPDATE transactions SET category_source=?, merchant_id=? WHERE id=?',
                     (source, merchant_id, tid))

    conn.execute('DROP TABLE category_overrides')

    # ── report (feeds owner review; not an error) ───────────────────────────
    if disagreements:
        print(f'\n  MANUAL-PIN REVIEW — {len(disagreements)} transaction(s) whose stored category '
              f'disagrees with the deterministic pipeline were preserved and marked '
              f"category_source='manual'. Review these:")
        for tid, desc, cat in disagreements[:40]:
            print(f"    #{tid} {desc[:44]!r} kept as {cat!r}")
        if len(disagreements) > 40:
            print(f'    ... and {len(disagreements) - 40} more')


def verify(conn):
    # override count == confirmed-merchant count (the ADR/backlog invariant)
    n_overrides = conn.execute('SELECT n FROM mig7_ovcount').fetchone()[0]
    n_confirmed = conn.execute("SELECT COUNT(*) FROM merchants WHERE status='confirmed'").fetchone()[0]
    assert n_confirmed == n_overrides, f'{n_confirmed} confirmed merchants != {n_overrides} overrides'

    # every transaction has a category_source in the enum, never left 'none'
    n_none = conn.execute("SELECT COUNT(*) FROM transactions WHERE category_source='none'").fetchone()[0]
    assert n_none == 0, f'{n_none} transactions left with category_source=none'
    bad_src = conn.execute(f'''
        SELECT COUNT(*) FROM transactions
        WHERE category_source NOT IN {_SOURCE_CHECK}''').fetchone()[0]
    assert bad_src == 0, f'{bad_src} transactions with an invalid category_source'

    # THE guarantee: no category changed during the whole migration
    changed = conn.execute('''
        SELECT COUNT(*) FROM transactions t JOIN mig7_pre p ON p.id = t.id
        WHERE t.category != p.category''').fetchone()[0]
    assert changed == 0, f'{changed} transactions had their category changed (must be 0)'

    # confirmed-source rows are merchant-linked; non-confirmed rows are not
    bad_confirmed = conn.execute('''
        SELECT COUNT(*) FROM transactions WHERE category_source='confirmed' AND merchant_id IS NULL
    ''').fetchone()[0]
    assert bad_confirmed == 0, f'{bad_confirmed} confirmed transactions without a merchant_id'

    # merchant_id references resolve
    dangling = conn.execute('''
        SELECT COUNT(*) FROM transactions t
        WHERE t.merchant_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM merchants m WHERE m.id = t.merchant_id)
    ''').fetchone()[0]
    assert dangling == 0, f'{dangling} transactions link a non-existent merchant'

    # every alias pattern is a non-empty normalized string and unique
    n_empty_alias = conn.execute("SELECT COUNT(*) FROM merchant_aliases WHERE pattern=''").fetchone()[0]
    assert n_empty_alias == 0, 'empty alias pattern present'

    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert 'category_overrides' not in tables, 'category_overrides should have been dropped'
    assert {'merchants', 'merchant_aliases', 'issuer_category_map'} <= tables

    cols = {r[1] for r in conn.execute('PRAGMA table_info(transactions)')}
    assert {'merchant_id', 'category_source'} <= cols, cols
