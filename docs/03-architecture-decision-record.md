# 03 — Architecture Decision Records

**Date:** 2026-07-12. Decisions marked **Accepted** were agreed with the owner in the 2026-07-12 interview. All examples use synthetic values.

- ADR-001: Keep Flask (restructured), don't replace
- ADR-002: Frontend — Path A stack (React/Vite/Tailwind SPA over a Flask JSON API)
- ADR-003: **The unified data model** (schema + migration path)
- ADR-005: Money as integer paise
- ADR-006: Golden-file corpus & testing regime
- ADR-007: Migration mechanics
- ADR-008: **Card rules data model & rewards engine** (added rev. 2 — purpose correction)
- ADR-009: Trustworthy categorization pipeline (added rev. 2)

---

## ADR-001 — Keep Flask, restructure it. **Accepted.**

### Context
Backend is one 760-line Flask file. The roadmap triples the API surface (net worth, Kite, snapshots). Constraint set: single user, localhost, Windows, SQLite, owner-maintained, PDF parsing in Python.

### Alternatives considered
- **FastAPI** — the fashionable swap. Rejected: its wins (async, OpenAPI, Pydantic validation) buy nothing here. There is no concurrency problem (one user, SQLite, and `pdfplumber` is synchronous CPU work anyway). Typed request models are nice but Pydantic can be used inside Flask if ever wanted. Cost: rewrite every route and re-learn deployment quirks for zero user-visible gain.
- **Django** — rejected outright: ORM + admin + auth machinery for a no-auth single-user app is the definition of over-engineering here.
- **Node/Express or Go** — rejected: the app's crown jewels are the Python PDF parsers; splitting parsing from serving across runtimes doubles operational surface on a personal machine.
- **No backend (Electron/Tauri + SQLite directly)** — seriously considered, since "local app in a browser tab" is mildly awkward. Rejected: rewriting parsers or bridging to Python erases the benefit; the browser-tab workflow is already proven fine for this user.

### Decision
Keep Flask. In Phase 2 restructure from one file into a small package (app factory + blueprints: `cards`, `networth`, `ingest`; `db.py` with migration runner; `parsers/` package). Flask's role narrows to: JSON API + static file server for the built frontend. This is a re-org, not a rewrite — routes keep their behavior and their tests.

### Consequences
No new framework risk; the restructure is mechanical. The single-file era ends, which costs some grep-ability but is unavoidable at 3× the surface.

---

## ADR-002 — Frontend: Path A. **Accepted (owner-decided); assessed honestly below.**

### Context
Owner decided: Flask becomes a JSON API; a React SPA with real motion consumes it. Current frontend is ~1,500 lines of vanilla JS/CSS with zero motion.

### Honest assessment (requested)
Path A is **right, and cheaper than it looks** for this codebase: the backend is already ~90% JSON API — the only server-rendered artifact is one shell template. Nothing of value is lost by abandoning the Jinja page. The genuine risks are (a) toolchain churn on a personal project (the classic way these stall), and (b) rebuilding four working views before any new value ships. Mitigations: the stack below is deliberately boring; and the backlog migrates one module per phase with the legacy UI kept alive at `/legacy` until parity (Phase 0 ships the new shell + Dashboard only). Where I'd push back: if motion/design were *not* a first-class goal, I'd say keep vanilla JS and spend the effort on net worth — but they are the stated goal, and hand-rolling spring animations in vanilla JS is worse engineering than adopting React.

### Decision — exact stack
| Concern | Choice | Why / rejected alternatives |
|---|---|---|
| Build | **Vite 6 + TypeScript** | Instant dev server, zero-config proxy. (Next.js rejected: SSR/routing machinery pointless for localhost.) |
| UI | **React 18** | Owner's choice; largest motion ecosystem. (Svelte would be lighter but smaller ecosystem; not worth relitigating.) |
| Styling | **Tailwind CSS v4** | Design tokens as CSS variables in one file; dark-first. |
| Motion | **`motion` (Framer Motion successor)** | Springs, layout animations, `AnimatePresence` route transitions, number tickers via `animate()`. This is the library that delivers the "dark fintech" feel. |
| Server state | **TanStack Query v5** | Caching/refetch for `/api/*`; eliminates hand-rolled fetch state. No Redux — there is no client state worth a store. |
| Routing | **React Router v7 (library mode)** | Boring and sufficient. |
| Charts | **Recharts** | Declarative, animates on data change, fine at this data volume. (D3 rejected: power we don't need at cost we'd pay; visx rejected: more control than a 6-panel dashboard needs.) |
| Formatting | `Intl.NumberFormat('en-IN')` | Lakh/crore grouping for free. |

**Topology:** `frontend/` at repo root. Dev: Vite on `:5173`, proxying `/api` → Flask `:5000` (both started by `dev.ps1`). Prod (daily use): `npm run build` → Flask serves `frontend/dist/` at `/`; legacy UI at `/legacy` until parity, then deleted. No CORS config needed in either mode.

---

## ADR-003 — The unified data model. **Accepted.**

### Context
One schema must span: card transactions (exists), equity & MF holdings (snapshot-based — interview decision), EPF/PPF/gold/property/bank (manual dated snapshots), and loans (EMI-computed). It must answer: net worth now and at any month-end, asset allocation, month-on-month delta, liability drag — without interpolation or invented history.

### The central idea
**Everything is an `account`; every account has a way to get a value at a date; net worth is a fold over accounts.** Three valuation mechanisms, one per account style:

1. **Snapshot-valued** (equity, MF, EPF, PPF, gold, property, bank): value at date *t* = latest `valuations` row ≤ *t*. Kite refreshes and manual entries both write `valuations`; Kite additionally writes per-instrument `holdings` detail.
2. **Formula-valued** (loans): outstanding at *t* computed from amortization terms + `loan_events`. Never materialized — always computed, so a rate-change or prepayment edit retroactively corrects the whole timeline.
3. **Zero-valued** (credit cards): cards contribute analytics, not balance-sheet value. *Deliberate:* statement dues/outstanding are not modeled (we don't track payment status), so cards don't appear in net worth. Revisit only if that ever feels wrong in use.

### Alternatives considered and rejected
- **One giant `assets` table with nullable columns per kind** — rejected: 9 kinds × kind-specific fields = a sparse mess with no integrity.
- **Full double-entry ledger (Beancount-style)** — genuinely attractive and the "correct" accounting answer; rejected because it demands transaction-level investment data, which the owner explicitly chose against (snapshots), and it would make 20-min/month manual upkeep impossible. This is the road not taken, consciously.
- **Materializing loan balances into `valuations` monthly** — rejected: stale rows after any term edit; computing is cheap and always right.
- **Separate tables per asset class** (`epf_snapshots`, `gold_snapshots`, …) — rejected: identical shape 6 times over; the `kind` discriminator + one `valuations` table does it.

### Schema (SQLite DDL)

```sql
-- All money columns are INTEGER paise (ADR-005). All dates are TEXT 'YYYY-MM-DD'.

CREATE TABLE accounts (
  id           INTEGER PRIMARY KEY,
  kind         TEXT NOT NULL CHECK (kind IN
               ('credit_card','equity','mutual_fund','epf','ppf',
                'gold','property','bank','loan')),
  name         TEXT NOT NULL,              -- "HDFC Tata Neu Infinity", "Zerodha Equity"
  institution  TEXT,                       -- "HDFC", "Zerodha", "EPFO"
  identifier   TEXT,                       -- card last4 / folio / masked acct no
  is_active    INTEGER NOT NULL DEFAULT 1,
  meta         TEXT NOT NULL DEFAULT '{}', -- JSON, kind-specific (card variant, property address…)
  created_at   TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (kind, name)
);

-- ── Cards ──────────────────────────────────────────────────────────────
CREATE TABLE statements (                  -- replaces import_batches
  id            INTEGER PRIMARY KEY,
  account_id    INTEGER NOT NULL REFERENCES accounts(id),
  period_start  TEXT NOT NULL,
  period_end    TEXT NOT NULL,             -- PDF: printed cycle; CSV: min/max txn dates
  format        TEXT NOT NULL CHECK (format IN ('pdf','csv')),
  source_path   TEXT,                      -- persisted copy under statements/
  file_sha256   TEXT UNIQUE,               -- byte-identical re-upload → hard reject
  txn_count     INTEGER NOT NULL DEFAULT 0,
  stmt_debits_paise  INTEGER,              -- totals as printed, for reconciliation
  stmt_credits_paise INTEGER,
  imported_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
-- CORRECTED at implementation (task 3.4): earlier drafts of this ADR also had
-- UNIQUE (account_id, period_start, period_end) here. Dropped — it would make
-- the force=true override below physically impossible for the one case that
-- needs it most: re-importing a statement with the SAME printed cycle but
-- different bytes (a redownloaded copy, a corrected reissue). A DB constraint
-- can't distinguish "identical period, should be blocked" from "identical
-- period, owner explicitly said force it" — only the app-level check can.
-- file_sha256 UNIQUE still hard-blocks true byte-identical re-uploads.
--
-- Period-overlap gating is an application-level check (ranges can't be
-- UNIQUE'd, and per above, period equality can't be a hard constraint either):
-- reject import if EXISTS statement s WHERE s.account_id = ? AND NOT
--   (new.period_end < s.period_start OR new.period_start > s.period_end),
-- unless force=true.

CREATE TABLE transactions (
  id            INTEGER PRIMARY KEY,
  account_id    INTEGER NOT NULL REFERENCES accounts(id),
  statement_id  INTEGER REFERENCES statements(id) ON DELETE CASCADE,
  date          TEXT NOT NULL,
  description   TEXT NOT NULL,             -- cleaned
  raw_description TEXT,                    -- as parsed, never mutated
  amount_paise  INTEGER NOT NULL CHECK (amount_paise > 0),
  type          TEXT NOT NULL CHECK (type IN ('debit','credit')),
  category      TEXT NOT NULL,
  bank_category TEXT,                      -- Axis/Kotak statement-provided
  is_cashback   INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_txn_account_date ON transactions(account_id, date);
CREATE INDEX idx_txn_date         ON transactions(date);

-- category_overrides: the legacy table survives unchanged through v6 and is
-- superseded at v7 by the merchants pipeline (ADR-009), which fixes F9
-- (deterministic precedence) as part of the migration.

CREATE TABLE reward_balances (             -- replaces rewards; dated history (fixes F5)
  id          INTEGER PRIMARY KEY,
  account_id  INTEGER NOT NULL REFERENCES accounts(id),
  as_of       TEXT NOT NULL,               -- statement period_end, or manual entry date
  label       TEXT NOT NULL,               -- "NeuCoins", "EDGE Points", "Cashback"
  value_minor INTEGER NOT NULL,            -- points as whole number; INR types in paise
  value_type  TEXT NOT NULL CHECK (value_type IN ('points','cashback_paise','balance_paise')),
  source      TEXT NOT NULL CHECK (source IN ('statement','manual')),
  statement_id INTEGER REFERENCES statements(id) ON DELETE CASCADE,
  UNIQUE (account_id, as_of)
);

CREATE TABLE milestones (                  -- windowed; progress computed live (fixes F6)
  id           INTEGER PRIMARY KEY,
  account_id   INTEGER NOT NULL REFERENCES accounts(id),
  name         TEXT NOT NULL,
  target_paise INTEGER NOT NULL,
  window_start TEXT NOT NULL,
  window_end   TEXT NOT NULL,
  benefit      TEXT,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Net worth ──────────────────────────────────────────────────────────
-- The net-worth tables (dated valuations, per-instrument holdings, loans and
-- their rate-change/prepayment events) are developed outside this public
-- repository. Everything below the `accounts` spine above is card-module
-- schema, which is what this repo implements.

```

### The four required queries

- **Net worth(t):** for each active non-loan, non-card account, latest `valuations.value_paise` with `as_of ≤ t`; minus, for each loan, `outstanding(t)` from amortization over `loans` + `loan_events`. An account with no valuation ≤ t contributes 0 and is flagged "no data yet" (never interpolated).
- **Asset allocation(t):** same per-account values, `GROUP BY accounts.kind` (EPF+PPF presented together as "retirement"; presentation-layer grouping, not schema).
- **Month-on-month delta:** net worth(t) evaluated at each month-end since first data. Snapshot-valued accounts naturally carry forward their latest value (with staleness metadata: days since `as_of`).
- **Liability drag:** for current month m, Σ over loans of interest component = `outstanding(m−1) × monthly_rate`; also cumulative interest paid since `start_date`. Pure computation, no storage.

### Migration path from the current schema
Mechanics in ADR-007; sequence (each step: backup → transform → **verify → bump version**, verification queries shown in the backlog tasks):

1. **v1 — accounts:** create table; seed one `credit_card` account per distinct `transactions.card_label` (8 rows), enriching `institution`/`identifier` from `card_profiles` where labels match. Add `transactions.account_id`, backfill by label join, set NOT NULL. `card_profiles`, `card`, `card_label` become dead (dropped in v6).
2. **v2 — paise:** add `amount_paise`; backfill `CAST(ROUND(amount*100) AS INTEGER)`; **verify per-row** `ABS(amount*100 − amount_paise) < 0.5` for all a few hundred rows and per-account sum equality; rebuild table without `amount` (SQLite can't drop-with-check; table rebuild per ADR-007).
3. **v3 — statements:** create; one row per `import_batches` row, `period_start/end` = min/max transaction date in that batch (best available — the original PDFs' printed cycles are re-derivable later from the persisted `statements/` files if ever needed). Link `transactions.statement_id` via the old `import_batch` timestamp string. **Existing overlapping periods are allowed to migrate** (gating applies to *new* imports only) but flagged in a report for the Phase 2 cleanup task.
4. **v4 — reward_balances:** one row per existing `rewards` row, `as_of` = date part of `updated_at`. *Known imperfection:* true `as_of` should be statement period end; with 4 rows, correctness returns via the next statement import per card.
5. **v5 — milestones:** rebuild with `window_start` = old `created_at` date, `window_end` = old `deadline`, `target_paise = target_spend×100`; drop `current_spend`. Owner reviews both rows' windows after migration (flagged in migration output).
6. **v6 — drop legacy:** `import_batches`, `card_profiles`, legacy columns. (`category_overrides` survives untouched until v7.)
7. **v7 — categorization pipeline (ADR-009):** `merchants`, `merchant_aliases`, `issuer_category_map`; `transactions` gains `merchant_id` + `category_source`; existing `category_overrides` rows migrate to confirmed merchants and the table is dropped. Fixes F9.
8. **v8 — rewards rules (ADR-008):** `reward_programs`, `redemption_routes`, `earn_rules`, `bonus_rules`, `reward_accruals`; `milestones` gains `benefit_paise`.

### Consequences
One valuation mechanism per account style keeps manual upkeep at spec's 20 min/month. The schema deliberately cannot compute XIRR or tax lots — that door was closed by the snapshot decision, and reopening it later means adding a trades table, not reshaping this one. Bank-account *transactions* later (spec M6 "door open") = new statements/transactions rows against a `bank` account; the shape already permits it.

---

## ADR-005 — Money as integer paise. **Accepted.**

Floats (`REAL`) invite drift under aggregation and multiplication (holdings × price, interest computation) — audit F8. Alternatives: Python `Decimal` serialized as TEXT (rejected: SQLite can't `SUM()` it natively; every query grows casts); keep floats + round everywhere (rejected: whack-a-mole). **Decision:** every money column is `INTEGER` paise, suffixed `_paise` (`value_minor` for the mixed points/paise rewards column). Points quantities are whole integers; instrument quantity is `REAL` (not money). Conversion at the API boundary: JSON carries paise as integers; the frontend owns formatting (`Intl.NumberFormat('en-IN')` on `paise/100`). Interest math: compute in integer paise with explicit rounding at each EMI period boundary (round-half-up), matching bank amortization convention; the M7 acceptance test pins this against a published schedule.

---

## ADR-006 — Golden-file corpus & testing regime. **Accepted.**

### Context
Audit F1/F2: parsers are the app's riskiest code and have zero tests; uploaded PDFs are discarded. `statements/` already contains real files per card **and a redacted file per card** — the raw material exists.

### Decision
Two-tier corpus under `tests/corpus/`:

- **Tier 1 — committable:** the redacted PDFs (no password, sanitized identity, **amounts must remain syntactically intact** — the current Axis-Rewards redaction stripped amounts and must be re-made). These can live in git. `.gitignore` gets an exception: `!tests/corpus/tier1/**` (it currently ignores `*.pdf` globally); tier 2 stays ignored.
- **Tier 2 — local-only:** the real statement files, gitignored as today, with passwords in `tests/corpus/passwords.local.json` (gitignored). Tests auto-skip Tier 2 files that are absent, so the suite still runs anywhere.

For every corpus file, a checked-in **expected-output JSON** (transaction list + rewards + period + reconciliation totals) — synthetic-safe for Tier 1; Tier 2 expectations are gitignored alongside their PDFs. Test = parse → deep-compare. Plus invariant tests for every file: parsed totals match statement-printed totals; unparsed-candidate-line count is 0 (or the pinned known count); every date within statement period.

The upload path (M2) persists every newly imported statement into `statements/`, so **the corpus grows by 7–8 real files per month for free** — new expectations generated by a `pytest --snapshot-update`-style helper and eyeballed before commit.

**Pinning:** `pdfplumber` is pinned exactly (the HDFC parser depends on an extraction quirk — audit §3); any bump must go green on the full corpus first. `requirements.txt` gains `pytest` and exact pins. Runner: `pytest` via `test.ps1`; no CI (local-only project — the discipline is "run before commit," enforced by habit and by `verify` steps in the backlog).

Rejected: synthetic-only fixtures (they encode the *developer's* assumptions, which is exactly the failure mode we're fixing); full-DB integration snapshots (brittle, and the parsers are where the risk lives).

---

## ADR-007 — Migration mechanics. **Accepted.**

Alternatives: Alembic (rejected: built for SQLAlchemy, which we don't use; heavy for SQLite); ad-hoc `try/ALTER/except` as today (rejected: it's how the schema got into this shape — unordered, unverifiable, silently swallows errors). **Decision:** `PRAGMA user_version` + numbered Python migration modules (`migrations/m001_accounts.py`, …), each exposing `up(conn)` and `verify(conn)`. Runner (in `db.py`, invoked on app start and by `migrate.ps1`): snapshot-copy the DB to `data/backups/hisaab-<date>-pre-v<N>.db` → `BEGIN` → `up` → `verify` (raises = rollback, backup untouched, app refuses to start with a clear message) → `COMMIT` → bump `user_version`. Column drops use the documented SQLite table-rebuild pattern (create-new, copy, drop-old, rename) inside the same transaction. Migrations are Python, not SQL files, because v1–v5 are data transforms with verification logic, not just DDL.

---

## ADR-008 — Card rules data model & rewards engine. **Accepted (rev. 2).**

### Context
The purpose correction (2026-07-12 rev. 2) makes rewards optimisation the app's core job. The engine must model, per card: base rate, accelerated categories/merchants, monthly/annual caps, minimum-spend thresholds, threshold bonuses (e.g. "1,000 bonus points for 4 transactions ≥ ₹1,500 in a month"), category exclusions (rent, fuel, wallet loads, insurance…), and point values that differ by redemption route. It must compute per-transaction accruals, effective rates, cap-aware counterfactuals, and reconcile against actual statement balances. Rules change over time (devaluations) and history must not be rewritten. This is the second-hardest model in the project after ADR-003.

### Alternatives considered
- **Hardcoded per-card Python rule classes** — rejected: rules change (devaluations are routine); editing code + redeploying for a T&C change is the wrong maintenance loop, and historical validity would live in git archaeology instead of data.
- **A generic expression/DSL engine** (rules as JSON logic trees) — rejected: maximal flexibility nobody needs; un-queryable; impossible to build a sane editing UI over. The real-world structure of Indian card rules fits a fixed relational shape plus a `notes` field for the weird stuff.
- **Modeling rewards as synthetic transactions** in the ledger — rejected: accruals are *derived* data (they change when rules are corrected); mixing derived rows into the source-of-truth table breaks the recompute-from-scratch property.

### Decision — schema

```sql
-- v8. All money INTEGER paise; point values in centipaise (1 pt = ₹0.25 → 2500)
-- because common route values (₹0.25, ₹0.30) are sub-paisa-precision per point.

CREATE TABLE reward_programs (             -- one row per card per rule era
  id            INTEGER PRIMARY KEY,
  account_id    INTEGER NOT NULL REFERENCES accounts(id),  -- kind='credit_card'
  name          TEXT NOT NULL,             -- "NeuCoins", "Membership Rewards", "Cashback"
  earn_currency TEXT NOT NULL CHECK (earn_currency IN ('points','cashback_inr')),
  annual_fee_paise INTEGER NOT NULL DEFAULT 0,
  fee_waiver_milestone_id INTEGER REFERENCES milestones(id),
  valid_from    TEXT NOT NULL,
  valid_to      TEXT,                      -- NULL = current. A devaluation CLOSES this row
                                           -- and opens a new one: history is never rewritten.
  notes         TEXT,                      -- MITC/T&C source reference
  UNIQUE (account_id, valid_from)
);

CREATE TABLE redemption_routes (
  id          INTEGER PRIMARY KEY,
  program_id  INTEGER NOT NULL REFERENCES reward_programs(id),
  name        TEXT NOT NULL,               -- "Statement credit", "Tata Neu app", "Flight transfer"
  value_per_point_centipaise INTEGER,      -- CORRECTED at implementation (task 5.1): nullable, not
                                           -- NOT NULL. Real non-default routes often have no fixed
                                           -- value (a catalogue "varies per item", or a transfer-
                                           -- partner ratio confirmed but its INR value unpublished —
                                           -- see ccyamls/axis-rewards.yaml, ccyamls/amex-mrcc.yaml).
                                           -- Only the is_default route's value is load-bearing (this
                                           -- ADR's own line below says so); migration m008's verify()
                                           -- enforces "every program's default route has a value"
                                           -- explicitly, since a DB CHECK can't reference sibling rows.
  is_default  INTEGER NOT NULL DEFAULT 0,  -- headline valuations use the default route
  notes       TEXT
);
-- cashback_inr programs need no routes; value is identity (engine hardcodes 1:1).

CREATE TABLE earn_rules (
  id          INTEGER PRIMARY KEY,
  program_id  INTEGER NOT NULL REFERENCES reward_programs(id),
  priority    INTEGER NOT NULL,            -- lower = first; FIRST MATCH WINS per transaction
  kind        TEXT NOT NULL CHECK (kind IN ('accelerated','base','excluded')),
  category    TEXT,                        -- internal taxonomy; NULL = any (base/blanket rules)
  merchant_match TEXT,                     -- optional normalized substring ("swiggy", "tata")
                                           -- for brand accelerators; matched via ADR-009 normalizer
  merchant_match_exclude TEXT,             -- ADDED at implementation (task 5.1): comma-separated
                                           -- normalized substrings carved OUT of an otherwise-
                                           -- matching rule. Real cards routinely exclude specific
                                           -- merchants from an accelerator (Amazon Pay ICICI's 5%/3%
                                           -- amazon.in tiers exclude Gold Coins and travel bookings;
                                           -- Amex Reward Multiplier excludes several per-brand product
                                           -- lines) — without this column those carve-outs have
                                           -- nowhere to live and would silently over-credit.
  earn_numer  INTEGER NOT NULL DEFAULT 0,  -- units earned (points, or paise for cashback_inr)…
  earn_denom_paise INTEGER NOT NULL DEFAULT 10000,  -- …per this much spend ("5 pts per ₹100" → 5/10000)
  cap_units   INTEGER,                     -- max units this rule may yield per cap_period
  cap_period  TEXT CHECK (cap_period IN ('statement_cycle','calendar_month','calendar_quarter',
                                          'calendar_year','anniversary_quarter','anniversary_year',
                                          'one_time')),
                                           -- WIDENED at implementation (task 5.1) from the original
                                           -- 3-value enum — see the note below the table.
  cap_group   TEXT,                        -- ADDED at implementation (task 5.1): rules sharing a
                                           -- non-null token share ONE cap pool, summed before the
                                           -- cap applies. The original schema had no pooling concept
                                           -- at all, but real cards need it routinely — e.g. HDFC
                                           -- Swiggy's 5% accelerator spans five different taxonomy
                                           -- categories (Shopping, Entertainment, Medical, Health &
                                           -- Wellness, Transportation, Grocery) all drawing on ONE
                                           -- pooled ₹1,500/statement-cycle cap. A cap_group of NULL
                                           -- means the rule's cap is its own, unshared.
  min_txn_paise INTEGER,                   -- rule applies only to transactions ≥ this
  notes       TEXT
);
-- 'excluded' rows earn nothing and exist so exclusions are explicit, ordered data
-- (rent, wallet load, fuel, insurance…), not engine special-cases.

CREATE TABLE bonus_rules (                 -- threshold bonuses, evaluated per period not per txn
  id             INTEGER PRIMARY KEY,
  program_id     INTEGER NOT NULL REFERENCES reward_programs(id),
  name           TEXT NOT NULL,            -- "4 txns ≥ ₹1,500/month → 1,000 pts"
  period         TEXT NOT NULL CHECK (period IN ('statement_cycle','calendar_month','calendar_quarter',
                                                  'calendar_year','anniversary_quarter','anniversary_year',
                                                  'one_time')),
  min_txn_count  INTEGER,                  -- qualifying-transaction count threshold…
  min_txn_paise  INTEGER,                  -- …where each qualifying txn is ≥ this
  min_spend_paise INTEGER,                 -- OR a total-spend threshold (either/both nullable)
  bonus_units    INTEGER NOT NULL,
  notes          TEXT
);
-- CORRECTED at implementation (task 5.1): `period` (here) and `cap_period` (earn_rules, above) were
-- originally CHECK(... IN ('statement_cycle','calendar_month','calendar_year')) — a 3-value enum
-- that real card research (ccyamls/*.yaml, all 7 researched cards) immediately proved too narrow.
-- Axis MyZone's quarterly AND annual spend milestones need calendar_quarter/anniversary_year; every
-- card's welcome/first-year-renewal bonus is a one-time event with no recurring period at all
-- (one_time). Widened both CHECKs to the same 7-value set rather than inventing a separate enum per
-- table — one vocabulary, defined once in ccyamls/SCHEMA.md, which the researcher skill and the
-- migration both target.

CREATE TABLE reward_accruals (             -- derived CACHE, rebuilt deterministically on any
  txn_id       INTEGER PRIMARY KEY REFERENCES transactions(id) ON DELETE CASCADE,
  program_id   INTEGER NOT NULL REFERENCES reward_programs(id),
  rule_id      INTEGER REFERENCES earn_rules(id),   -- NULL = excluded / no matching program era
  units_earned INTEGER NOT NULL,           -- after cap
  units_uncapped INTEGER NOT NULL,         -- before cap (the difference is "cap loss")
  value_paise  INTEGER NOT NULL,           -- at the program's default route
  computed_at  TEXT NOT NULL
);
-- Source of truth = rules + transactions. Accruals exist for traceability and query speed;
-- any rule edit invalidates and rebuilds the affected program's accruals.

-- v8 also: ALTER TABLE milestones ADD COLUMN benefit_paise INTEGER;  -- rupee value of the
-- benefit, so effective-rate math can amortise it over the milestone window.
```

### Decision — computation semantics
- **Rule matching:** for a transaction, pick the program row whose validity window contains the transaction date; evaluate its `earn_rules` by priority; first match (category, then merchant_match, then min_txn) wins. Debits only; credits/refunds *reverse* accruals of matched prior spend where identifiable, else reduce the category pool (banks claw back points on refunds; modeling this exactly is impossible from statements — the reconciliation loop is the honesty check).
- **Caps:** accrue in `cap_period` buckets; `statement_cycle` uses the statements table's periods (fall back to calendar month when a cycle isn't known — flagged in output). Units beyond cap → `units_uncapped − units_earned` = visible "lost to cap".
- **Effective rate:** as specified in M10 (accruals + bonuses + amortised milestone benefit − amortised fee, over spend). Fee amortises over the card year; milestone benefit amortises over its window, counted only when the window's target is actually met.
- **Counterfactual (Job 3) — cap-aware greedy, per (category, month):** candidate card's hypothetical earn = its rules applied to that category's transactions, capped by its *remaining* headroom (cap minus what its actual other spend already consumed that period). Exclusion rules make a candidate ineligible. Loss = best candidate value − actual value, floored at 0. Explicitly NOT a joint optimisation across categories (an LP would maximize total but produce unstable, unexplainable advice); explicitly ignores bonus/milestone side-effects in v1 (flagged per M10). This was chosen over (a) naive rate comparison ignoring caps — rejected: systematically overstates losses, exactly the dishonesty this app exists to avoid — and (b) full portfolio LP — rejected: over-engineering, and its outputs can't be explained in one sentence.
- **Reconciliation:** per statement cycle per card: Σ modeled units (accruals + bonuses) vs Δ actual balance from `reward_balances` (adjusted for redemptions when the statement shows them — else flagged "redemption suspected"). Tolerance default ±5% or ±50 units, whichever is larger; configurable per card.

### Consequences
Rules entry is a one-time ~2-hour owner task (worksheet provided in the backlog) plus rare devaluation edits — the reconciliation loop is what makes stale rules *detectable* rather than silently wrong. The model deliberately cannot express time-of-week rates, forex markups, or expiry; the `notes` field records them for the human. A hypothetical card (for "should I get card X" later) is just a `reward_programs` row on an inactive account — the door is open, the feature is not built.

---

## ADR-009 — Trustworthy categorization pipeline. **Accepted (rev. 2).**

### Context
Gap analysis converts category errors into wrong rupee claims. Current mechanics (audit F9): keyword substring rules + an order-nondeterministic override table + `bank_category` from two issuers with incompatible vocabularies. Statements carry no MCC. Ground truth does not exist; the design must manufacture *confidence* explicitly.

### Alternatives considered
- **Keep transaction-level overrides, fix ordering only** — rejected: the unit of categorization is wrong. The same merchant recurs dozens of times; categorizing transactions means re-deciding the same fact repeatedly and inconsistently.
- **External merchant databases / MCC lists** — rejected: no good India-first open dataset; statements don't carry MCC to join on; adds a dependency that rots.
- **LLM categorization** — rejected for the pipeline: non-deterministic, non-local, unexplainable rupee claims downstream. (Acceptable someday as a *suggestion* source feeding the review queue; never as silent truth.)

### Decision — merchant-level categorization with explicit confidence

```sql
-- v7
CREATE TABLE merchants (
  id             INTEGER PRIMARY KEY,
  canonical_name TEXT NOT NULL UNIQUE,     -- "Swiggy"
  category       TEXT NOT NULL,
  status         TEXT NOT NULL CHECK (status IN ('confirmed','suggested')),
  created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE merchant_aliases (
  id          INTEGER PRIMARY KEY,
  merchant_id INTEGER NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
  pattern     TEXT NOT NULL UNIQUE         -- normalized substring; longest-match wins, ties newest
);

CREATE TABLE issuer_category_map (
  id            INTEGER PRIMARY KEY,
  institution   TEXT NOT NULL,             -- "AXIS", "KOTAK"
  bank_category TEXT NOT NULL,             -- "RESTAURANTS"
  category      TEXT NOT NULL,             -- "Food & Drinks"
  UNIQUE (institution, bank_category)
);

-- transactions gains:
--   merchant_id     INTEGER REFERENCES merchants(id)
--   category_source TEXT NOT NULL DEFAULT 'none' CHECK (category_source IN
--                   ('confirmed','suggested','bank','keyword','manual','none'))
```

**Normalizer** (pure function, corpus-tested): lowercase → strip `UPI-` and gateway prefixes (`razorpay*`, `payu*`, `ccavenue*`, `paytm*`) → strip trailing city tokens and bare numbers → collapse whitespace. Deterministic; its test fixtures come from the corpus's real description shapes (the audit's dupe examples show the noise: `"UPI-UBER INDIA SYSTEMSPRIVAT"`, `"Razorpay*RELIANCE RETAI Thane"`).

**Assignment precedence** (import-time and on recompute), stamped into `category_source`: ⓪ a per-transaction `manual` pin (the escape hatch for one-offs — a gift bought at a grocer — survives every recompute and beats everything) → ① confirmed-merchant alias match (longest pattern wins, ties newest) → ② suggested-merchant match → ③ `issuer_category_map` on `bank_category` → ④ keyword rules (retained as suggestion-generators, demoted from decision-makers) → ⑤ `Uncategorized` — a first-class state; "Others" stops being a dumping ground.

**Review queue:** non-confirmed transactions grouped by normalized merchant, sorted by spend, one-click confirm (creates/updates the merchant + alias, restamps matching transactions). Recategorizing an already-confirmed transaction edits the *merchant* (with blast-radius preview) or splits a new merchant off a too-broad alias.

**Trust metric:** `% of spend (paise-weighted) with category_source='confirmed'`, shown on the dashboard and stamped onto every M10 report.

**Migration (v7):** each `category_overrides` row → a confirmed merchant (canonical name = title-cased pattern) + alias (they were human decisions, keep them); backfill `merchant_id`/`category_source` across existing transactions by precedence; then drop `category_overrides`. Seed `issuer_category_map` from the distinct `bank_category` values in the live DB (a few dozen rows, owner reviews once).

### Consequences
Fixing a merchant once fixes it forever, the same promise the README makes today but structurally guaranteed. The taxonomy gains reward-relevant categories (Rent, Wallet/Prepaid Load, Government & Taxes, Education, Jewellery, Uncategorized) so exclusion rules in ADR-008 have something to bind to. Cost: a one-time historical review session (~30 min for ~150 merchants at the current data volume) and a few seconds per new merchant monthly. Categories can still be wrong — but now only where the owner explicitly said so or where the UI visibly says "unconfirmed", which is the strongest claim available without MCC data.
