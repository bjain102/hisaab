# 04 — Phased Backlog

**Date:** 2026-07-12. Philosophy: smallest task first, ship, fix, move on. Every phase is independently shippable and independently useful; no task depends on a later task. All commands are **PowerShell**. Cross-references: audit findings (F#) from doc 01, modules (M#) from doc 02, ADRs from doc 03.

**Phase ordering rationale** (rev. 2 — resequenced after the purpose correction): parity-then-schema stands — the legacy UI must keep working until the new UI reaches parity, so schema/API changes wait for Phase 3; known data bugs (F4–F6) are *documented but live* until then, accepted because the safety net (Phase 1) must exist before touching parsers or schema anyway. **The rewards-optimisation engine (the app's core purpose) now lands immediately after the schema phase — Phases 4–5 — and net worth moves after it.** The engine cannot come earlier than Phase 4: it computes rupee claims from parsed transactions × categories × rules, so it needs the corpus safety net (Phase 1), paise + accounts + statement cycles (Phase 3), and trustworthy categories (Phase 4) or its loss numbers are fiction. Phases: **0** shell+dashboard · **1** safety net · **2** parity · **3** schema v1–v6 · **4** trustworthy categories (v7) · **5** rewards engine (v8) · **6** net worth manual (v9) · **7** Kite · **8** polish.

---

## Phase 0 — Design system + app shell + Dashboard (M1 + M4)

**Ships:** the new dark-fintech UI at `/` with a fully working Dashboard; legacy UI intact at `/legacy`. Backend untouched except static serving and one additive `/api/summary` field (0.5).

### 0.0 Environment check
- **Goal:** Node.js ≥ 20 available.
- **Files:** none.
- **Done:** `node --version` ≥ 20, `npm --version` works.
- **Verify:** `node --version` — if missing: `winget install OpenJS.NodeJS.LTS`, reopen terminal.

### 0.1 Scaffold frontend
- **Goal:** Vite + React + TS app under `frontend/`, per ADR-002, proxying `/api` to Flask.
- **Steps:** `npm create vite@latest frontend -- --template react-ts`; then in `frontend/`: `npm i motion @tanstack/react-query react-router recharts` and `npm i -D tailwindcss @tailwindcss/vite`. Add Tailwind plugin and dev proxy to `vite.config.ts`: `server: { proxy: { '/api': 'http://127.0.0.1:5000' } }`.
- **Files:** `frontend/**` (new), root `.gitignore` (+`frontend/node_modules/`, `frontend/dist/`).
- **Done:** Vite dev server renders a page; a test `fetch('/api/cards')` from it returns live data with Flask running.
- **Verify:** terminal 1: `python app.py`; terminal 2: `cd frontend; npm run dev`; open `http://localhost:5173`, check the network tab shows `/api/cards` → 200 with card labels.

### 0.2 Design tokens
- **Goal:** M1's single source of truth. Dark-first tokens as CSS variables consumed through Tailwind v4 `@theme`.
- **Starter values (tune by eye, keep the structure):** backgrounds `#0B0E14` (app) / `#12161F` (surface) / `#1A2029` (raised); text `#E6EAF2` / muted `#8B93A5`; asset-class accents — equity `#4C8DFF`, MF `#8B7CF6`, retirement (EPF/PPF) `#2DD4A7`, gold `#F0B429`, property `#F4845F`, cash `#5FD4F4`, liability `#F45F6D`; semantic good/bad `#2DD4A7`/`#F45F6D`. Type: Inter (UI), JetBrains Mono (all figures), scale 12/14/16/20/28/40 with tabular-nums on money. Spacing: 4px grid. Motion tokens: `--dur-fast: 150ms`, `--dur-base: 250ms`, `--dur-slow: 400ms`; springs via `motion` defaults (stiffness 260, damping 24) for layout, easings `cubic-bezier(0.2, 0, 0, 1)` for opacity/color. Fonts self-hosted in `frontend/public/fonts/` (drop the Google Fonts CDN link the legacy page uses — local-only app should not phone out).
- **Files:** `frontend/src/styles/tokens.css`, `frontend/src/index.css`.
- **Done:** tokens render on a demo page; no hardcoded colors outside `tokens.css`.
- **Verify:** grep discipline: `Select-String -Path frontend/src -Pattern '#[0-9a-fA-F]{6}' -Recurse -Exclude tokens.css` returns nothing (excluding tokens file).

### 0.3 App shell
- **Goal:** sidebar (Dashboard · Transactions · Import · Rewards · Net Worth · Assets — last two visible but marked "soon", routing to styled empty states), routed pages, animated route transitions (`AnimatePresence` fade+8px-rise, `--dur-base`).
- **Files:** `frontend/src/App.tsx`, `frontend/src/shell/*`, `frontend/src/pages/*` (placeholders).
- **Done:** all six routes navigate with transition; active nav state animates (layoutId underline/pill); keyboard navigable.
- **Verify:** click through all routes; no layout jump; `npm run build` passes clean.

### 0.4 Component kit
- **Goal:** the M1 component set: `StatCard`, `Panel`, `DataTable`, `Select`, `Modal`, `Toast`, `EmptyState`, `AnimatedNumber` (spring number ticker via `motion`'s `animate()`, Indian-format via `Intl.NumberFormat('en-IN', {style:'currency', currency:'INR'})`).
- **Files:** `frontend/src/components/*`, plus an internal `/kit` route rendering every component in every state (empty/loading/error/full). No Storybook — the route is the gallery.
- **Done:** `/kit` shows all components; `AnimatedNumber` demo ticks ₹0 → ₹1,23,456.78 with lakh grouping.
- **Verify:** open `/kit`, eyeball each state; toggle a demo control that swaps values to see tickers animate.

### 0.5 Dashboard page (the migrated module — M4's redesigned layout, not a 1:1 port)
- **Goal:** build M4 as specced (rev. 2 layout): hero row of 5 stable slots — Net spend · vs-last-month delta · Cashback earned (interim until Phase 5's effective rate) · **Left on table** (reserved, intentional empty state until Phase 5) · **trust meter** (reserved until Phase 4); stacked month × top-5-categories bars with distinct partial-current-month treatment and human month labels; ranked category bars (no donut); by-card and top-merchants panels; card + date-range filters. Legacy "Top category"/"Top card" hero cards and the rewards-balances panel are deliberately not ported (M4 rationale). TanStack Query; filter changes animate (tickers re-spring, charts morph).
- **API (additive):** `/api/summary` gains `monthly_by_category` (month × category net totals) — the only Phase 0 backend touch beyond 0.6; legacy UI ignores it.
- **Files:** `frontend/src/pages/Dashboard.tsx`, `frontend/src/api/*` (typed client), `app.py` (one additive field in the summary query).
- **Done — acceptance gate:** with the same DB, every *shared* number equals the legacy dashboard at `/legacy` for at least three filter combinations: (all cards, YTD), (one HDFC card, all time), (all cards, last 3 months) — shared = net spend, cashback, category totals, card totals, monthly totals, merchant totals; the layouts intentionally differ. Additionally: stacked bars' per-month column sums equal the legacy trend line's monthly values; reserved slots show designed empty states, not blanks. *(Float-backed rupee values today — paise migration is Phase 3 — so "equals" means identical rendered values.)*
- **Verify:** run both UIs side by side (`http://localhost:5173` vs `http://127.0.0.1:5000/legacy`), compare the three combinations by eye; spot-check one month's stacked column against the legacy line; confirm the current partial month renders visually distinct (dashed/hatched) rather than as a cliff to zero.

### 0.6 Serve the build; scripts
- **Goal:** `python app.py` alone serves the new UI at `/` and the old at `/legacy`; one-command dev.
- **Changes:** `app.py`: route `/` serves `frontend/dist/index.html` + static assets (fallback message "run build.ps1" if `dist/` missing); move the legacy template route to `/legacy`. New `dev.ps1` (starts Flask and Vite in two windows: `Start-Process python app.py; Set-Location frontend; npm run dev`), `build.ps1` (`Set-Location frontend; npm run build`).
- **Files:** `app.py` (small), `dev.ps1`, `build.ps1` (new, repo root).
- **Done:** fresh terminal: `./build.ps1; python app.py` → new dashboard at `http://127.0.0.1:5000/`; `/legacy` unchanged.
- **Verify:** exactly that sequence, plus confirm an import still works via `/legacy` (upload one existing statement — expect the duplicate data, then remove it via batch delete, exercising the current remedy).

**Phase 0 exit:** you use the new dashboard daily; everything else still happens in `/legacy`.

---

## Phase 1 — Safety net: corpus + parser tests + latent-bug fixes (ADR-006; F1, F2, F3)

**Ships:** parsers pinned by tests against real statements; two silent-corruption risks eliminated. No schema change, no UI change (import responses gain additive fields).

### 1.1 Test scaffold
- **Goal:** pytest runs; dependencies pinned exactly.
- **Files:** `requirements.txt` (add `pytest`, pin all versions exactly per ADR-006), `tests/__init__.py`, `tests/test_smoke.py` (imports `pdf_parsers`, asserts `PDF_PARSERS` keys), `test.ps1` (`python -m pytest tests/ -q`).
- **Done/Verify:** `./test.ps1` → 1 passed.

### 1.2 Corpus assembly — **includes one manual owner task**
- **Goal:** ADR-006 two-tier corpus in place.
- **Steps:** create `tests/corpus/tier1/` (copy each `*_redacted.pdf` in) and `tests/corpus/tier2/` (copy real statements per card). Add `.gitignore` exception `!tests/corpus/tier1/**` (repo currently ignores `*.pdf` globally) and rules ignoring `tier2/` + `passwords.local.json`. Create `tests/corpus/passwords.local.json` mapping tier-2 filename → password. **Owner task:** re-make the Axis-Rewards redacted PDF — the current one strips the amount column (audit §3); amounts must stay syntactically intact (substitute synthetic values, don't delete).
- **Done:** `git status` shows only tier1 files as addable; a loader utility lists both tiers and skips tier2 gracefully when files/passwords are absent.
- **Verify:** `git add -n .` lists no tier2/password files; run loader in pytest: collected file count printed.

### 1.3 Golden snapshot tests
- **Goal:** F1 closed: every corpus file has a checked-in (tier1) / local (tier2) expected-output JSON; parse → deep-compare.
- **Files:** `scripts/gen_expectations.py` (parses a corpus file, writes `<file>.expected.json` next to it: transactions, rewards, and — after 1.4 — period + totals), `tests/test_parsers_golden.py`.
- **Done:** all corpus files have expectations, generated once and **eyeballed** (spot-check 3 transactions per file against the PDF before committing tier1); suite green; deliberately editing a regex in `pdf_parsers.py` makes it fail.
- **Verify:** `./test.ps1` green; then temporarily break the IDFC date regex, `./test.ps1` fails on IDFC files only, revert.

### 1.4 Statement period + printed-totals extraction, and reconciliation tests
- **Goal:** F2's cheapest check: each PDF parser also returns `period_start/period_end` (printed cycle) and `stmt_debits/stmt_credits` (printed totals) where the bank prints them; invariant tests assert Σ(parsed debits/credits) == printed totals and every transaction date ∈ period, for every corpus file.
- **Files:** `pdf_parsers.py` (each parser's result dict gains `period` and `totals`, `None` where genuinely unavailable — document which banks lack printed totals in the parser docstring as you discover it from the corpus; CSV path derives period from min/max dates), `tests/test_reconciliation.py`.
- **Done:** invariants pass on every corpus file; a hand-truncated copy of a tier1 file fails reconciliation.
- **Verify:** `./test.ps1`; run `python scripts/gen_expectations.py --check` on the truncated copy → mismatch reported.

### 1.4b Amex PDF parser (inserted 2026-07-15 — owner scope change)
- **Goal:** Amex PDFs become a supported import (spec rev. 3): `parse_amex_pdf` with period ("Statement Period From <Mon D> to <Mon D, YYYY>"), year inference for year-less transaction dates (Dec→Jan straddle handled), explicit `CR` next-line credit markers, and the page-1 summary equation providing the corpus's only **dual** reconcilable totals (debits AND credits both asserted). CSV parser retained as fallback. Legacy UI unblocked (`PDF_CAPABLE` + hard-block removal).
- **Files:** `pdf_parsers.py`, `static/js/app.js` (2 lines), tests (smoke registry, tier1 count, lazy reconciliation collection), regenerated expectations.
- **Done/Verify:** suite green including Amex golden + dual Σ-reconciliation; tier1 Σdebits/Σcredits match printed totals exactly.

### 1.5 Fix F3 — date-format order
- **Goal:** CSV parsers stop guessing MM/DD-first for DD/MM banks. `parse_date()` gains an explicit format-priority argument: Amex passes MM/DD-first, all other banks DD/MM-first.
- **Files:** `app.py` (`parse_date`, the six CSV parsers), `tests/test_dates.py` (table-driven: `05/03/2026` → March 5 for HDFC-style, May 3 for Amex; day>12 both ways; every format in the list).
- **Done/Verify:** `./test.ps1` green; golden suite (which includes the Amex CSV in tier2) unchanged.

### 1.6 Unparsed-line surfacing (F2)
- **Goal:** parsers count date-like candidate lines that matched no pattern; result carries `skipped_candidates`; `/api/upload` response includes it (additive — legacy UI ignores it). Corpus tests pin `skipped_candidates == 0` (or the known count) per file.
- **Files:** `pdf_parsers.py`, `app.py` (upload response), tests.
- **Done/Verify:** corpus green with pinned counts; hand-corrupt one transaction line in a tier1 copy → its test reports `skipped_candidates: 1`.

### 1.7 Fix F7 — Kotak credits
- **Goal:** the Kotak parser reads the payments/credits section too (today it only reads "Purchases" and hardcodes `type='debit'` — audit §3), with corpus coverage from the Kotak tier-1/tier-2 files.
- **Files:** `pdf_parsers.py` (`parse_kotak_pdf`), corpus expectations regenerated for Kotak files.
- **Done/Verify:** Kotak golden tests include at least one credit row (from the real statement's payment entry); reconciliation invariants (1.4) pass for Kotak, which they cannot while credits are missing.

### 1.8 Remove committed secret (F11)
- **Goal:** delete `debug_rewards.py` (contains a statement password).
- **Done/Verify:** file gone; `git log --oneline -- debug_rewards.py` still shows history (accepted for a local-only repo; note in commit message that history rewrite is deliberately skipped unless the repo is ever pushed).

**Phase 1 exit:** parser changes are safe to make; the two nastiest latent bugs (F1, F3) are dead.

---

## Phase 2 — UI parity: migrate remaining views, retire legacy

**Ships:** the whole app runs on the new UI; legacy deleted. Existing API preserved (additive changes only).

### 2.1 Transactions view (M3, parity)
- **Goal:** filter/search/sort/paging list. Add optional `offset` param to `/api/transactions` (additive; default behavior unchanged) so the UI pages past today's 1000 cap (F12).
- **Files:** `frontend/src/pages/Transactions.tsx`, `app.py` (offset param), tests for offset.
- **Done:** all a few hundred rows reachable; filters combine; animated row stagger on filter change.
- **Verify:** filter by each card and category; compare counts against `/legacy`.

### 2.2 Recategorize + learn (M3, parity)
- **Goal:** click category → modal → pick → optional "remember"; identical behavior to legacy (deterministic precedence and the merchant model come in Phase 4 — ADR-009).
- **Files:** `Transactions.tsx`, `frontend/src/components/RecategorizeModal.tsx`.
- **Done/Verify:** recategorize one transaction with learn on; confirm the override row appears (`/api/…` response) and past rows updated — same result via legacy UI on a second merchant.

### 2.3 Import view (M2 partial — UI only)
- **Goal:** card select, drop zone, password field, per-file result panel showing the Phase-1 additive fields: reconciliation status and `skipped_candidates` ("32 parsed · totals reconcile ✓ · 0 unparsed lines").
- **Files:** `frontend/src/pages/Import.tsx`.
- **Done:** an import round-trips with the rich result panel; errors (wrong password, wrong card) display cleanly.
- **Verify:** import a tier-2 statement for a card, see reconciliation ✓; delete the batch afterwards (dedup gating doesn't exist yet — that's Phase 3).

### 2.4 Rewards + Milestones view (M5, parity with today's semantics)
- **Goal:** port current rewards balances + milestones display (stale semantics and all — fixed in Phase 3; the view notes "milestone progress frozen at creation — fix coming" so the UI doesn't launder a known-wrong number as fresh).
- **Files:** `frontend/src/pages/Rewards.tsx`.
- **Done/Verify:** values match `/legacy` milestones/rewards exactly.

### 2.5 Retire legacy
- **Goal:** delete `templates/`, `static/`, the `/legacy` route, and `/api/clear` (F12 — replaced by nothing; batch delete remains).
- **Done:** `python app.py` serves only the new UI; grep shows no `render_template` left.
- **Verify:** `./test.ps1` green; click through every view; `Invoke-WebRequest http://127.0.0.1:5000/api/clear -Method POST` → 404.

**Phase 2 exit:** one UI, visibly yours. Data-layer bugs F4–F6 still live, now with a safety net under them.

---

## Phase 3 — Schema v1–v6 + card-module correctness (ADR-003, ADR-005, ADR-007; F4, F5, F6, F8, F9, F10)

**Ships:** correct money, dedup gating, honest rewards/milestones. Each migration is its own shippable task (runner verifies + backs up per ADR-007). API and frontend updated in the same task as each migration — the frontend is the only consumer now.

### 3.1 Migration runner
- **Goal:** ADR-007 mechanics: `PRAGMA user_version`, numbered modules with `up()`/`verify()`, auto-backup to `data/backups/` (keep last 20), refuse-to-start on failed verify. The backup helper is also exposed as a utility and wired into destructive bulk operations (import-batch/statement delete), satisfying the spec's backup rule (§4).
- **Files:** `db.py` (new), `migrations/__init__.py`, `migrate.ps1`, `tests/test_migrations.py` (runs the chain against a copied fixture DB).
- **Done/Verify:** running on a copy of the real DB is a no-op at v0 with a backup created; a deliberately failing verify rolls back and preserves the original.

### 3.2 v1 — accounts
- **Goal:** ADR-003 step 1: `accounts` seeded from distinct card labels (expect exactly 8), `transactions.account_id` backfilled, API keeps emitting `card_label` (joined) so the frontend is untouched.
- **Verify (in `verify()`):** `SELECT COUNT(*) FROM transactions WHERE account_id IS NULL` = 0; account count = old distinct-label count; per-account txn counts equal per-label counts.

### 3.3 v2 — paise (F8)
- **Goal:** ADR-003 step 2 + API emits integer paise + frontend divides by 100 (single formatting utility already centralizes this from task 0.4).
- **Verify:** per-row `ABS(amount*100 − amount_paise) < 0.5` (all 602); per-account paise sums equal `ROUND(SUM(amount)*100)` within ±1 paise per 1,000 rows (float-sum tolerance — per-row check is the real gate); Dashboard shows identical rendered values before/after.

### 3.4 v3 — statements + period gating + persistence (F4, M2)
- **Goal:** `statements` table (backfilled from `import_batches`, periods = min/max txn dates per batch); upload flow gains: SHA-256 byte-identical rejection, period-overlap rejection with `force=true` override, file persistence to `statements/<card>/<label>_<period-end>.<ext>`, and storage of the Phase-1 period/totals. Import UI shows overlap rejections with a force button. Migration prints an **overlap report** of existing statements (feeds 3.7).
- **Verify:** `tests/test_gating.py`: same file twice → rejected (hash); overlapping period different file → rejected with clear message → force succeeds; disjoint period → clean import. Re-import a tier-2 file through the UI to see the rejection live.

### 3.5 v4 — reward history (F5)
- **Goal:** `reward_balances` replaces `rewards` (ADR-003 step 4); upload writes a dated row keyed to statement period-end; Rewards view shows current-latest + sparkline of history.
- **Verify:** import two tier-2 statements for one card **out of order** (older second) → current balance is still the newer one; both rows present.

### 3.6 v5 — windowed milestones (F6)
- **Goal:** ADR-003 step 5; progress computed live (net spend within window per M5); migration output tells owner to review the 2 migrated windows; UI gets window date pickers and animated progress.
- **Verify:** `tests/test_milestones.py`: synthetic fixture — transactions inside/outside window, refunds, cashback rows, a card-bill payment → expected progress to the paisa. UI: create a milestone windowed to exclude January; verify January spend absent from progress.

### 3.7 v6 — drop legacy tables; dedup cleanup (F10, F4-history)
- **Goal:** drop `import_batches`, `card_profiles`, legacy columns (`category_overrides` survives untouched until Phase 4's v7 — ADR-009). Plus the **one-time duplicate cleanup**: a screen (or reviewed script) listing the 3.4 overlap report + the 35 same-tuple groups, letting the owner mark which batches/rows to delete, with a DB backup taken first.
- **Verify:** after cleanup, dupe-group query returns only owner-confirmed genuine repeats; Dashboard totals change by exactly the removed rows' sum (visible in the cleanup screen's summary).

**Phase 3 exit:** every spend number in the card module is defensible. Closes all HIGH/MEDIUM audit findings except F9, which Phase 4 closes structurally.

---

## Phase 4 — Trustworthy categories (M3; ADR-009; F9)

**Ships:** merchant-level categorization with explicit confidence — the precondition for honest gap numbers, and immediately useful on its own (better dashboard categories, no more "Others" dumping ground).

### 4.1 Description normalizer
- **Goal:** the ADR-009 pure function (strip `UPI-`/gateway prefixes/city suffixes/trailing numbers), tested against real description shapes harvested from the corpus.
- **Files:** `categorization/normalize.py`, `tests/test_normalize.py` (table-driven; cases taken from distinct `raw_description` shapes in the DB — synthetic amounts, real noise patterns).
- **Done/Verify:** `./test.ps1` green; running the normalizer over all existing descriptions produces a distinct-merchant count meaningfully below the raw distinct-description count (print both — expect roughly 2–4× compression).

### 4.2 v7 — merchants pipeline migration
- **Goal:** ADR-009 schema (`merchants`, `merchant_aliases`, `issuer_category_map`; `transactions.merchant_id` + `category_source`); migrate the 153 `category_overrides` rows to confirmed merchants; seed `issuer_category_map` from distinct live `bank_category` values; backfill all transactions by precedence; drop `category_overrides`.
- **Verify (in `verify()`):** every transaction has a `category_source`; no transaction's *category* changed during backfill unless its source improved (report any diffs for owner review, don't silently change spend analytics); override count == confirmed-merchant count.

### 4.3 Review queue + trust meter
- **Goal:** Transactions view gains the review queue (non-confirmed, grouped by merchant, sorted by spend, one-click confirm) and a badge count; recategorize now edits the merchant with blast-radius preview; M10-bound taxonomy additions (Rent, Wallet/Prepaid Load, Government & Taxes, Education, Jewellery, Uncategorized). **Dashboard light-ups (M4):** the reserved trust-meter hero slot goes live (paise-weighted % confirmed), and Top merchants switches to canonical merchants with confirmed-category badges (no more gateway-costume duplicates).
- **Files:** `frontend/src/pages/Transactions.tsx` (queue mode), API endpoints for confirm/merge/split, `tests/test_precedence.py` (longest-pattern-wins, ties-newest).
- **Done/Verify:** confirming a suggested merchant restamps all its transactions to `confirmed` in one round-trip; precedence tests green; trust meter moves when you confirm.

### 4.4 Historical review session (owner task, ~30 min)
- **Goal:** work the queue for the existing ~600 transactions until ≥90% of spend is confirmed (M3's done-gate).
- **Verify:** trust meter ≥90%; remaining Uncategorized spend is genuinely unidentifiable.

**Phase 4 exit:** every category on the dashboard is either owner-confirmed or visibly marked otherwise. F9 closed.

---

## Phase 5 — Rewards optimisation engine (M10; ADR-008)

**Ships:** the app's reason to exist — effective rates, reconciliation, and the gap report.

### 5.1 v8 — rules schema
- **Goal:** ADR-008 tables (`reward_programs`, `redemption_routes`, `earn_rules`, `bonus_rules`, `reward_accruals`) + `milestones.benefit_paise`.
- **Verify:** migration chain green on fixture + real DB.

### 5.2 Rules worksheet + editor + seeding (owner task, ~2 h one-time)
- **Goal:** a per-card rules editor (program eras, routes, earn rules with priorities/caps/exclusions, bonus rules, fee + waiver link) and a printable worksheet listing exactly what to pull from each card's MITC (base rate, accelerators, caps, exclusions, threshold bonuses, point values per redemption route, annual fee). Owner fills it for all 8 cards; the editor enforces one `base` rule per program and warns on gaps (no rules, no default route).
- **Files:** `rewards/` API, `frontend/src/pages/Rewards.tsx` (rules tab), `docs/rules-worksheet.md`.
- **Done/Verify:** all 8 cards have a current program era with ≥1 base rule and a default route; editor round-trips a devaluation (close era, open era) without touching the old era's rows.

### 5.3 Accrual engine
- **Goal:** ADR-008 semantics: era selection by date, priority-ordered first-match, cap buckets per statement cycle (calendar-month fallback flagged), bonus-rule evaluation per period, refund reversal, deterministic rebuild of `reward_accruals` on rule change.
- **Files:** `rewards/engine.py`, `tests/test_engine.py`.
- **Done/Verify — the synthetic fixture gate:** a hand-computed fixture covering: base vs accelerated match, an exclusion, a cap hit mid-month, a min-txn threshold, a bonus rule met and missed, a refund, and a mid-window devaluation — every accrual matches the hand computation to the unit and paisa. Fixture lives in the repo as the engine's permanent regression anchor.

### 5.4 Effective rates + reconciliation (Job 2)
- **Goal:** per card × month and card × category × month effective-rate reports (net of fee/milestone amortisation per ADR-008); reconciliation panel per statement cycle (modeled vs `reward_balances` delta, tolerance per ADR-008, "redemption suspected" flagging). **Dashboard light-ups (M4):** the Cashback-earned hero slot is replaced by the blended effective rate, and the By-card panel gains its rate column + reconciliation badge.
- **Done/Verify:** engine tests extended with the rate formula; live: after importing the next real statement, at least one card reconciles within tolerance — a mismatch is investigated (rules typo vs parser vs devaluation) before calling this task done.
- **Files:** `rewards/reports.py`, Rewards page (rates + reconciliation tabs).

### 5.5 Gap report + forward guidance (Job 3)
- **Goal:** cap-aware greedy counterfactual per (category, month) per ADR-008; the target sentence with drill-down to transactions and rules; monthly loss total, top-3 gaps, 6-month trend; current-cycle guidance with live headroom; trust meter + v1 caveats displayed on the report itself. **Dashboard light-ups (M4):** the reserved Left-on-table hero slot goes live (click-through to this report) and the forward-guidance strip appears.
- **Files:** `rewards/gaps.py`, Rewards page (gaps tab), `tests/test_gaps.py`.
- **Done/Verify:** synthetic fixture with known best-card answers (including a case where the naive answer is wrong because the better card's cap is nearly consumed) passes to the paisa; live: the report renders the target sentence on real data and the owner can trace one gap end-to-end.

**Phase 5 exit:** M10's done-gate (two consecutive reconciled cycles on ≥5 cards) is tracked from here; the app now does its core job.

### 5.6 Transfer-partner valuation (DEFERRED — future work; owner-requested 2026-07-19, not part of the Phase 5 exit gate)
- **Why:** the engine values points at each program's default redemption route (Amex MR ≈ ₹0.50/pt catalogue, Axis EDGE = ₹0.20/pt Pay-By-Rewards). But for transfer-partner programs (Amex MR, Axis EDGE Miles; HSBC cited by the owner as the pattern though not held), airline/hotel transfers are typically the value CEILING — often ₹1+/pt at sweet spots. As the owner put it: ultimately the points' real value comes out of transfer partners. Default-route-only valuation systematically understates these cards in effective rates and the gap report.
- **Goal:** extend the redemption model with per-partner transfer data: partner name + program, transfer ratio (N points → 1 partner mile/point), min transfer block, transfer fees, and a dated/sourced INR valuation of the partner currency (volatile and behavior-dependent — every valuation carries its own confidence + as_of). Compute a "transfer-optimized value per point" alongside the default-route value.
- **Honesty stance (decide before building):** partner-mile valuations are speculative (they depend on how you redeem the miles). Keep the DEFAULT route as the headline number the gap report's rupee claims stand on; surface transfer value as an annotated upside band ("worth up to ~₹X/pt via <partner> at <ratio>, valued <date>"), never silently swap it into counterfactuals — that would reintroduce exactly the overstated-loss dishonesty ADR-008's cap-aware design exists to avoid.
- **Data reality today:** `ccyamls/amex-mrcc.yaml` records the transfer route with `value_per_point_inr: UNKNOWN`; `ccyamls/axis-rewards.yaml` has the partner ratio flagged ambiguous (5:1 vs 10:1 in the official T&C). Both files' review_flags already point here.
- **Touches when picked up:** `ccyamls/SCHEMA.md` (+ validator) gain a `transfer_partners` block per route or program; the researcher skill gains a transfer-partner research section (ratios change — same era/devaluation discipline as earn rules); v8+ schema gains the table; 5.4's rate reports gain the upside band.
- **Sequencing:** best after 5.4 (reconciliation working) so speculative valuations layer on a trustworthy base; nothing else blocks on it.

---

## Phase 8 — Polish (optional, unordered)
Motion refinement pass (per-page transitions, chart morphs); statement-archive browser (the persisted PDFs, by card/period); backup browser + restore; README rewrite (current one describes the legacy app); light-theme tokens; CAMS/KFintech CAS parser for non-Zerodha MF (only if the need materializes — new parser = corpus discipline applies).

---

## Dependency summary
Linear by phase; within phases, tasks are ordered but 2.1–2.4 are mutually independent, as are 6.2/6.4. Nothing in any phase depends on a later phase. The only external dependencies in the critical path are Node.js (0.0) and two owner work-sessions: the merchant review (4.4) and the rules worksheet (5.2) — the engine is only as good as those inputs. Kite credentials gate only Phase 7.
