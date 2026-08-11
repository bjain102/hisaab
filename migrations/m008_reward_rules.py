"""v8 — rewards rules engine schema (ADR-008; task 5.1).

Creates `reward_programs`, `redemption_routes`, `earn_rules`, `bonus_rules`,
`reward_accruals`, and adds `milestones.benefit_paise`. Pure additions — no
existing data to migrate or backfill (these tables are empty until the 5.2
seeder reads `ccyamls/*.yaml`), so this migration is schema-only.

DEVIATIONS from ADR-008's literal DDL, found while checking the schema
against the owner's actual researched card data (`ccyamls/`) before building
on top of it — same discipline as 3.4's ADR-003 correction: don't implement
an ADR's constraint blindly when the real data it must hold already proves it
wrong.

1. **`cap_period`/`period` CHECK constraints widened.** ADR-008's text only
   lists `('statement_cycle','calendar_month','calendar_year')`. Real cards
   need more: Axis MyZone's milestones are quarterly and anniversary-year
   (`calendar_quarter`, `anniversary_quarter`, `anniversary_year`), and every
   card's welcome/renewal bonus is a one-time event with no recurring period
   at all (`one_time`). Both `earn_rules.cap_period` and `bonus_rules.period`
   gain the full set: `statement_cycle, calendar_month, calendar_quarter,
   calendar_year, anniversary_quarter, anniversary_year, one_time` — matching
   `ccyamls/SCHEMA.md`, which was written against the same real cards.
2. **`earn_rules.cap_group` added** (nullable TEXT). ADR-008's `earn_rules`
   has no way to express a cap SHARED across multiple rules. This is not a
   corner case — it's how several real cards actually work: HDFC Swiggy's 5%
   accelerator spans five different taxonomy categories (Shopping,
   Entertainment, Medical, Health & Wellness, Transportation, Grocery) all
   drawing from ONE pooled ₹1,500/statement-cycle cap. Modeled as one-rule-
   per-category with a shared `cap_group` token (same convention already
   established in the YAML research layer); the engine sums usage across
   every rule sharing a non-null `cap_group` before applying the cap.
3. **`earn_rules.merchant_match_exclude` added** (nullable TEXT, comma-
   separated normalized tokens — same shape as `merchant_match`). ADR-008 has
   no carve-out mechanism, but real accelerators routinely exclude specific
   merchants from an otherwise-matching category/merchant rule (Amazon Pay
   ICICI's 5%/3% Amazon tiers explicitly exclude Gold Coins and travel
   bookings; Amex's Reward Multiplier excludes several per-brand product
   lines). Without this column those carve-outs have nowhere to live, and
   omitting them would silently over-credit excluded spend.
4. **`redemption_routes.value_per_point_centipaise` made nullable.** ADR-008
   declares it `NOT NULL`, but several real non-default routes have no fixed
   value at all (Axis Rewards Store catalogue: "varies per catalogue item";
   Amex airline transfer partners: ratio confirmed, INR value not published).
   The ADR's own text says "headline valuations use the default route" — so
   only the default route's value is load-bearing for engine math. `verify()`
   below enforces that constraint explicitly (every program's is_default row
   has a non-null value) since a DB-level CHECK can't reference sibling rows.

Everything else follows ADR-008's DDL as written.

REMINDER FOR WHOEVER BUILDS 5.3+ (the accrual engine) OR TOUCHES DELETE
PATHS: this app never sets `PRAGMA foreign_keys = ON` (established in 3.7's
handoff notes — SQLite defaults it OFF per-connection, and app.py's `get_db()`
never turns it on). `reward_accruals.txn_id ... ON DELETE CASCADE` is
therefore NOT self-enforcing. `DELETE /api/transactions/<id>` (the dedup-
cleanup lever) and `delete_statement` will orphan `reward_accruals` rows
unless they're taught to delete matching accrual rows explicitly — the exact
same trap 3.7 hit with `reward_balances.statement_id`.
"""

_PERIODS = "('statement_cycle','calendar_month','calendar_quarter','calendar_year','anniversary_quarter','anniversary_year','one_time')"


def up(conn):
    conn.execute(f'''
        CREATE TABLE reward_programs (
            id            INTEGER PRIMARY KEY,
            account_id    INTEGER NOT NULL REFERENCES accounts(id),
            name          TEXT NOT NULL,
            earn_currency TEXT NOT NULL CHECK (earn_currency IN ('points','cashback_inr')),
            annual_fee_paise INTEGER NOT NULL DEFAULT 0,
            fee_waiver_milestone_id INTEGER REFERENCES milestones(id),
            valid_from    TEXT NOT NULL,
            valid_to      TEXT,
            notes         TEXT,
            UNIQUE (account_id, valid_from)
        )
    ''')

    conn.execute('''
        CREATE TABLE redemption_routes (
            id          INTEGER PRIMARY KEY,
            program_id  INTEGER NOT NULL REFERENCES reward_programs(id),
            name        TEXT NOT NULL,
            value_per_point_centipaise INTEGER,
            is_default  INTEGER NOT NULL DEFAULT 0,
            notes       TEXT
        )
    ''')

    conn.execute(f'''
        CREATE TABLE earn_rules (
            id          INTEGER PRIMARY KEY,
            program_id  INTEGER NOT NULL REFERENCES reward_programs(id),
            priority    INTEGER NOT NULL,
            kind        TEXT NOT NULL CHECK (kind IN ('accelerated','base','excluded')),
            category    TEXT,
            merchant_match TEXT,
            merchant_match_exclude TEXT,
            earn_numer  INTEGER NOT NULL DEFAULT 0,
            earn_denom_paise INTEGER NOT NULL DEFAULT 10000,
            cap_units   INTEGER,
            cap_period  TEXT CHECK (cap_period IN {_PERIODS}),
            cap_group   TEXT,
            min_txn_paise INTEGER,
            notes       TEXT
        )
    ''')

    conn.execute(f'''
        CREATE TABLE bonus_rules (
            id             INTEGER PRIMARY KEY,
            program_id     INTEGER NOT NULL REFERENCES reward_programs(id),
            name           TEXT NOT NULL,
            period         TEXT NOT NULL CHECK (period IN {_PERIODS}),
            min_txn_count  INTEGER,
            min_txn_paise  INTEGER,
            min_spend_paise INTEGER,
            bonus_units    INTEGER NOT NULL,
            notes          TEXT
        )
    ''')

    conn.execute('''
        CREATE TABLE reward_accruals (
            txn_id       INTEGER PRIMARY KEY REFERENCES transactions(id) ON DELETE CASCADE,
            program_id   INTEGER NOT NULL REFERENCES reward_programs(id),
            rule_id      INTEGER REFERENCES earn_rules(id),
            units_earned INTEGER NOT NULL,
            units_uncapped INTEGER NOT NULL,
            value_paise  INTEGER NOT NULL,
            computed_at  TEXT NOT NULL
        )
    ''')

    conn.execute('ALTER TABLE milestones ADD COLUMN benefit_paise INTEGER')

    conn.execute('CREATE INDEX idx_reward_programs_account ON reward_programs(account_id)')
    conn.execute('CREATE INDEX idx_redemption_routes_program ON redemption_routes(program_id)')
    conn.execute('CREATE INDEX idx_earn_rules_program_priority ON earn_rules(program_id, priority)')
    conn.execute('CREATE INDEX idx_bonus_rules_program ON bonus_rules(program_id)')
    conn.execute('CREATE INDEX idx_reward_accruals_program ON reward_accruals(program_id)')


def verify(conn):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    expected = {'reward_programs', 'redemption_routes', 'earn_rules', 'bonus_rules', 'reward_accruals'}
    assert expected <= tables, f'missing tables: {expected - tables}'

    # every new table starts empty — this migration seeds nothing (5.2's job)
    for t in expected:
        n = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
        assert n == 0, f'{t} should start empty, found {n} rows'

    cols = {r[1] for r in conn.execute('PRAGMA table_info(milestones)')}
    assert 'benefit_paise' in cols, 'milestones.benefit_paise not added'

    # the deviations above, sanity-checked against the live schema
    er_cols = {r[1] for r in conn.execute('PRAGMA table_info(earn_rules)')}
    assert {'cap_group', 'merchant_match_exclude'} <= er_cols, er_cols

    rr_info = {r[1]: r for r in conn.execute('PRAGMA table_info(redemption_routes)')}
    # PRAGMA table_info column 3 (notnull) must be 0 (nullable) for this column
    assert rr_info['value_per_point_centipaise'][3] == 0, \
        'value_per_point_centipaise must be nullable (non-default routes may have no fixed value)'

    # confirm the widened period/cap_period CHECK actually accepts the new
    # values (a real INSERT/ROLLBACK, not just reading the CHECK text back)
    conn.execute('''INSERT INTO reward_programs (account_id, name, earn_currency, valid_from)
                    SELECT id, 'verify-probe', 'points', '2000-01-01' FROM accounts LIMIT 1''')
    pid = conn.execute("SELECT id FROM reward_programs WHERE name='verify-probe'").fetchone()
    if pid:
        pid = pid[0]
        for period in ('calendar_quarter', 'anniversary_quarter', 'anniversary_year', 'one_time'):
            conn.execute(
                'INSERT INTO bonus_rules (program_id, name, period, bonus_units) VALUES (?,?,?,1)',
                (pid, f'probe-{period}', period))
        for cap_period in ('calendar_quarter', 'anniversary_quarter', 'anniversary_year', 'one_time'):
            conn.execute(
                "INSERT INTO earn_rules (program_id, priority, kind, cap_period) VALUES (?,1,'base',?)",
                (pid, cap_period))
        conn.execute("DELETE FROM bonus_rules WHERE program_id=?", (pid,))
        conn.execute("DELETE FROM earn_rules WHERE program_id=?", (pid,))
        conn.execute("DELETE FROM reward_programs WHERE id=?", (pid,))
