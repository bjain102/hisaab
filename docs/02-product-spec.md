# 02 — Product Spec: Hisaab → Personal Finance OS

**Date:** 2026-07-12 (rev. 2 same day — purpose corrected by owner: rewards optimisation is the core, not a side feature)
**Status:** Agreed with owner (interviews 2026-07-12). This is the spec that was never written; a stranger should be able to build from it.

---

## 1. What this is

A **local-only, single-user personal finance OS** for one person (the owner), running on their Windows machine.

**Its core purpose is credit-card rewards optimisation.** Three jobs, in order of value:

1. **Understand expenses** — where money actually goes, by category, across all cards, over time. *(Foundation — exists today, being hardened.)*
2. **Understand rewards** — what is *actually* earned per rupee spent, by card **and** by category: the effective reward rate (net of caps, exclusions, fees), not the advertised one.
3. **Identify gaps** — where rewards are being left on the table by using the wrong card for a category. The app must be able to say: *"you spent ₹X on category Y using card A earning Z%, but card B would have earned W% — you lost ₹N this month."* **Job 3 is the whole point of the app.** Everything in the card module exists to make this sentence trustworthy.

Layered on top, the net-worth OS answers three more questions: **what am I worth** (equities, MF, EPF/PPF, gold, property, bank balances, minus liabilities), **how is that changing** (MoM delta, allocation), and **what are my loans costing me** (liability drag).

A consequence of Job 3 worth stating: a gap report is only as trustworthy as its inputs — parsed transactions (hence the corpus regime), category assignments (hence M3's trust pipeline), and card rules (hence M10's rules model). The spec treats *trustworthiness of the loss number* as a first-class requirement, not a nice-to-have.

### Principles (non-negotiable)

- **Local-only.** SQLite file on disk. No cloud, no auth, no multi-tenancy, no telemetry. Nothing leaves the machine except outbound API calls the owner explicitly triggers (Kite refresh).
- **Honest numbers.** No interpolation, no invented history, no "estimated" values presented as facts. Where data is a manual snapshot, the UI says so and shows its date.
- **Snapshot-based investments.** Holdings are dated snapshots, not a transaction ledger. XIRR is explicitly out of scope (see §6).
- **History starts now.** No backfill machinery. The net-worth timeline begins at first use.
- **Incremental forever.** Every phase ships alone and is useful alone (see backlog doc).
- **Windows-first.** All scripts and setup instructions are PowerShell.

### The one user

Owner: engineer, comfortable with terminals and CSV exports, holds 7–8 credit cards optimized for rewards, invests via Zerodha, has EPF/PPF/gold/property, tolerant of *monthly-ish* manual data entry but not daily. Design for exactly this person.

---

## 2. Module map

| # | Module | Status |
|---|---|---|
| M1 | App shell & design system | New (Phase 0) |
| M2 | Cards — import & ingestion | Exists; hardening (dedup, reconciliation, corpus) |
| M3 | Cards — transactions & categorization | Exists; migrating to new UI |
| M4 | Cards — dashboard | Exists; migrating to new UI (Phase 0's "one migrated module") |
| M5 | Cards — rewards & milestones | Exists; semantics fixed (history + windows) |
| M6 | Net worth — asset registry & manual snapshots | New |
| M7 | Net worth — liabilities (EMI-aware) | New |
| M8 | Net worth — Kite integration (equity/MF) | New |
| M9 | Net worth — dashboard | New |
| **M10** | **Rewards optimisation engine** | **New — the core module (Jobs 2 & 3)** |

M3 (trustworthy categories) and M10 (rules engine) are the two pillars of Job 3; M2's parsing correctness feeds both.

---

## 3. Module specs

### M1 — App shell & design system

Dark-first "fintech" visual language: high-contrast numerals, monospace for figures, one saturated accent per asset class, animated number tickers, spring-based view transitions. Sidebar navigation: **Dashboard · Transactions · Import · Rewards · Net Worth · Assets** (Rewards absorbs Milestones; Assets is the registry + snapshot entry).

**Done when:** design tokens (color, type, spacing, motion durations/easings) exist as a single source of truth; app shell renders with animated route transitions; a component set exists covering: stat card, panel, data table, select, modal, toast, empty state; both an empty-DB and full-DB state look intentional.

**Out:** light theme (may come later; tokens must not hardcode against it), mobile layout (desktop-first; must not *break* at tablet width).

### M2 — Cards: import & ingestion

As today (PDF with password / CSV, per card), plus:

1. **Statement persistence.** Every successfully imported file is copied to `statements/<card>/` (canonical name: `<label>_<period-end>.pdf`). The DB stores the file's SHA-256 and path. Re-uploading a byte-identical file is rejected outright.
2. **Statement-period gating.** Each import records `period_start`/`period_end` — extracted from the PDF for PDF imports; **derived from min/max transaction dates for CSVs**. An import whose period overlaps an existing statement on the same card is rejected with a clear message and a visible **force-import override**. *Accepted limitation (owner-chosen):* a partial CSV export of an already-covered window is wrongly rejected and requires the override.
3. **Reconciliation.** Where the statement prints its own totals, the parser extracts them; import response reports `parsed n transactions; statement claims total ₹X debits, parsed ₹X — ✓ match` or a **loud mismatch warning** (import still allowed — the warning is the product).
4. **Unparsed-line surfacing.** Import response includes count of candidate lines that were *not* parsed (date-like lines that matched no pattern), so silent parser drift becomes visible at import time.

**Journey (statement day, monthly):** statements arrive by email → owner downloads 7 PDFs → Import view → for each: pick card, drop file, type password → sees "34 transactions · period 05 Jun–04 Jul · totals reconcile ✓ · rewards balance recorded" → done in <5 minutes.

**Done when:** all four behaviors above work for every supported bank; overlap rejection and force-import both demonstrated; a deliberately truncated statement shows a reconciliation mismatch warning.

**Out:** auto-fetching statements from email, parsing any new bank not already supported. *(Rev. 3, 2026-07-15: Amex PDF moved IN — owner receives PDFs, and they carry a printed period plus the corpus's only dual debit/credit reconcilable totals, strictly better inputs for gating and reconciliation than the CSV. CSV export retained as the Amex fallback.)*

### M3 — Cards: transactions & trustworthy categorization

The transactions list stays as today (filter/search/sort, plus paging past the 1000-row cap). What changes fundamentally is **how categories are assigned** — because gap analysis (M10) turns a wrong category from a cosmetic annoyance into a wrong rupee number.

**The problem, stated honestly:** bank categorisation exists only for Axis and Kotak, uses incompatible taxonomies, and is wrong often enough that the README already distrusts it. Keyword matching over raw descriptions is noisy (gateway prefixes like `Razorpay*`, UPI prefixes, city suffixes make the same merchant look like five). Statements do not expose MCC codes, so true merchant-category data is unavailable — **certainty is impossible; the design goal is *explicit confidence*, not fake precision.**

**The model — categorize merchants, not transactions** (schema in ADR-009):

1. **Normalisation:** every raw description passes a deterministic, corpus-tested normaliser (lowercase; strip `UPI-`, gateway prefixes `Razorpay*`/`PayU*`/`CCAvenue*`/`Paytm*`, trailing city tokens and numbers; collapse whitespace).
2. **Merchant registry:** normalised patterns map to a canonical **merchant** (e.g. `swiggy` → *Swiggy*), and the merchant — not the transaction — carries the category. Fixing a merchant once fixes every past and future transaction (today's learn-loop, made structural).
3. **Assignment precedence,** recorded per transaction as `category_source`: confirmed merchant match → suggested merchant match → issuer category (via a per-issuer translation table, since Axis "RESTAURANTS" ≠ Kotak "Dining") → keyword rule → **Uncategorized** (a real state; no more silently dumping into "Others").
4. **Review queue:** transactions whose source is not "confirmed" surface grouped by merchant, sorted by spend, with one-click confirm of the suggested category. After a statement import this is ~5–10 mostly-repeat merchants — seconds, not minutes.
5. **Trust meter:** the dashboard and every M10 report display **% of spend with confirmed categories**. A gap report computed on 60%-confirmed data says so on its face.

Taxonomy gains reward-relevant categories that card rules need and the current 16 lack: **Rent, Wallet/Prepaid Load, Government & Taxes, Education, Jewellery** (all common exclusion classes), plus the explicit **Uncategorized**.

**Done when:** normaliser is corpus-tested; the review queue confirms a whole statement's new merchants in under a minute; precedence is deterministic (longest pattern wins, ties by newest); retroactive application previews its blast radius before touching rows ("will recategorize 12 transactions — apply?"); trust meter live; ≥90% of existing spend reaches "confirmed" after one owner review session of the historical backlog.

### M4 — Cards: dashboard

Net-spend semantics preserved exactly (gross debits − refunds; cashback excluded from both sides; card-bill payments excluded from credits), but the layout is redesigned — the legacy dashboard is a Job-1 report; this one reads in the app's value order: **spent → earned → lost.** (Design review of the legacy dashboard, 2026-07-12.)

**Hero row (5 slots, stable across phases so nothing reflows as data lights up):**
1. **Net spend** (period, with refunds note) — live from Phase 0.
2. **vs last month** (delta ₹ and %) — live from Phase 0; replaces the weak 6-month average, which seasonality (travel spikes) makes misleading.
3. **Cashback earned** — interim from Phase 0; **replaced at Phase 5 by Effective reward rate** (blended, net, e.g. "1.6% · ₹5,700 on ₹3.6L" — synthetic).
4. **Left on table (₹, this month)** — reserved slot with an intentional empty state until Phase 5; then the gap headline, click-through to the M10 report. This is deliberately in the hero: it is the app's reason to exist.
5. **Category trust meter** (% spend confirmed) — reserved until Phase 4.
The legacy "Top category" and "Top card" hero cards are dropped: both repeat panels below, and "top card by spend" actively implies the wrong mental model (high spend share ≠ good card usage — that judgment belongs to the effective-rate column).

**Panels:**
- **Monthly composition** — stacked bars, month × top-5-categories + other (answers *where over time*, which the legacy single line cannot). The **current partial month renders visually distinct** (hatched/dashed) or is excluded — the legacy chart's month-start cliff-dive to zero is a recurring lie. Month labels human-readable ("Jan"), not `26-01`.
- **Category breakdown** — the ranked-bars list stays (it's the best panel legacy has). **The donut is dropped**: same data as the ranked bars, worse at comparison.
- **By card** — spend ₹ and share as today; **gains at Phase 5**: effective-rate column and reconciliation badge (✓ modeled ≈ statement actual).
- **Top merchants** — as today until Phase 4; **then canonical merchants** (normalized — no more "AMAZON Mumbai"/"Amazon Mumbai" as two rows, no gateway costumes like `PayU*…`) with confirmed-category badges.
- **Forward guidance strip** — Phase 5: current-cycle card-per-category recommendations with live cap headroom ("Dining → Swiggy card, ₹410 headroom left" — synthetic).
- Every panel drills down: category → its transactions/merchants; card → its transactions; gap → the M10 report.
- Rewards *balances* move off the dashboard entirely (they live in M5's Rewards view as earn history) — inventory is not a dashboard concern; rates and losses are.

**Done when:** every number both dashboards display (net spend, cashback, category totals, card totals, monthly totals, merchant totals) matches the legacy dashboard on the same DB to the paisa — the parity gate applies to *shared numbers*, since the layouts intentionally differ; animated transitions between filter states; partial-month treatment verified at a month boundary; reserved hero slots render intentional empty states, not blanks.

### M5 — Cards: rewards & milestones

**Rewards:** per-statement dated history per card (balance as-of statement period end). Card view shows current balance + sparkline of balance over statements. Manual entry still possible (dated). Import order can no longer regress a balance. **Rewards do not count toward net worth.** *(Revision note: the original "no rupee valuation of points" decision is superseded by M10, which requires per-route valuation — what survives is only the net-worth exclusion.)* Balance history doubles as M10's reconciliation signal: modeled earnings are sanity-checked against actual balance deltas per statement.

**Milestones:** a milestone = card + name + target amount + **explicit date window** + benefit text. Progress computed live: net spend (as M4 defines it) on that card within the window. No stored counter.

**Done when:** importing statements out of order leaves rewards history correct; a milestone whose window excludes old spend shows only in-window progress; both render with progress motion in the new UI.

### M6 — Net worth: asset registry & manual snapshots

A registry of **accounts** (see ADR-003 for schema): each has a kind (equity, mutual_fund, epf, ppf, gold, property, bank, loan, credit_card), a display name, an institution, and kind-specific fields. Manual-valued kinds (EPF, PPF, gold, property, bank) get **dated value snapshots**: owner opens Assets view, sees each account with its last value and how stale it is ("42 days old"), enters today's value, done. Gold may be entered as grams + rate or as a flat value — stored as the resulting value either way.

Net worth at any date = latest snapshot per account ≤ that date (no interpolation), plus computed loan balances (M7), plus latest Kite snapshot (M8).

**Journey (monthly pass, ~10 min):** EPF passbook → enter value. PPF netbanking → enter value. Bank balances → enter. Gold/property only when the owner cares to revise.

**Done when:** CRUD for accounts; dated snapshot entry with staleness indicators; net worth math correct on a synthetic fixture with known answer; deleting a snapshot recomputes correctly.

**Out:** automated EPF/PPF/gold price fetching, property valuation APIs, interpolation between snapshots.

### M7 — Net worth: liabilities

A loan account stores principal, annual rate, EMI amount, start date, tenure. The app **computes** outstanding balance for any month (standard reducing-balance amortization) and the interest/principal split per EMI — no monthly manual entry. Prepayments are recorded as dated events that re-base the schedule. **Liability drag** = current month's total interest across loans; shown on the net-worth dashboard, with cumulative interest paid.

**Done when:** amortization matches a bank-published schedule for a synthetic loan (₹10,00,000 @ 9%, 60 months) to the rupee; prepayment re-bases correctly; outstanding balances subtract from net worth.

### M8 — Net worth: Kite integration

A **"Refresh from Kite"** button. Flow: app opens the Kite Connect login URL → owner logs in and approves → redirect back to the local app with a request token → app exchanges it and pulls **equity holdings and MF holdings** → stores a dated holdings snapshot (per-instrument: symbol/ISIN, qty, avg cost, last price) and rolls it up to account-level valuations. Expected cadence: weekly/monthly, owner-initiated. Daily token expiry is irrelevant because each refresh is a fresh login.

Also supported: **Console CSV fallback** (holdings export from Zerodha Console imported as a snapshot) for when the API path is down. *(Owner picked API-primary; CSV fallback retained because it is cheap and de-risks the API dependency.)*

**Done when:** one click + Kite login produces a dated snapshot; holdings visible per-instrument; equity and MF roll into net worth and allocation; a failed/cancelled login leaves no partial snapshot.

**Out:** placing orders, positions/intraday anything, historical price charts, non-Zerodha brokers.

### M9 — Net worth: dashboard

The INDmoney-style view, dark-fintech rendered:

- **Total net worth** (animated ticker) with delta vs last month.
- **Asset allocation** donut/bars by kind (equity, MF, EPF/PPF, gold, property, cash) — computed from latest values.
- **Month-on-month timeline**: net worth at each month-end since first use (stepped, from snapshots — no smoothing).
- **Liability drag panel**: outstanding debt, this month's interest burn, interest vs principal split.
- Per-account drill-down.

**Done when:** all four render from real data; every displayed number is traceable to snapshots/formulas (a "how is this computed" affordance per panel); the month a snapshot is missing shows carry-forward with a staleness marker, never a made-up value.

### M10 — Rewards optimisation engine (Jobs 2 & 3)

The card-rules engine and the reports built on it. Schema and computation semantics in ADR-008; this section is the product contract.

**Inputs:** transactions with trustworthy categories (M3), card rules maintained by the owner (per-card: base rate, accelerated categories/merchants, caps, exclusions, threshold bonuses, redemption routes with rupee values, annual fee, fee-waiver milestone), and reward-balance history (M5) for reconciliation.

**Rules are owner-maintained, with the app making that cheap:** a rules editor per card, seeded once from a worksheet the owner fills from each card's MITC/T&C (~15 min/card, 8 cards, one-time), then touched only on devaluations (validity windows preserve history — a rate change never rewrites past earnings). *No automation is possible here: card T&Cs have no API, and scraping them would be the fragility we just engineered out of the parsers.*

**Outputs:**

1. **Accruals (per transaction):** which rule matched, units earned (capped and uncapped), rupee value at the default redemption route. Deterministic, recomputed on any rule change, fully traceable ("why did this earn 12 NeuCoins?").
2. **Effective reward rate (Job 2):** per card × month and per card × category × month: `(accrual value + threshold-bonus value + amortised milestone benefits − amortised annual fee if not waived) / spend`. This is the *net* rate — a card that advertises 5% but caps at ₹500/month shows its true blended number.
3. **Reconciliation:** modeled earn per statement cycle vs actual reward-balance delta from M5 history. Match within tolerance → engine credible; mismatch → shown loudly (a rules bug, a parser bug, or a devaluation you missed — all three are things the owner wants to know). *Honest limit: statements give card-level actuals only, so per-category rates are model-derived and marked as such.*
4. **Gap report (Job 3):** per category × month: actual cards used and value earned vs the best single card for that spend, **cap-aware** — the counterfactual respects the alternative card's exclusions and its *remaining* cap headroom that month (given its actual other spend), so the report never claims value the cap would have eaten. Output is the target sentence: "₹18,400 on Food & Drinks went on HDFC Tata Neu (1.5% effective); HDFC Swiggy had ₹410 of cashback headroom at 10% — you lost ₹340." Monthly total loss, top-3 gaps, 6-month trend. *(All example values synthetic.)*
5. **Forward guidance:** current-cycle card-per-category recommendation with live headroom ("Dining → Swiggy card, ₹410 headroom left this cycle").

**Explicit caveats displayed in-product (v1):** counterfactuals ignore threshold-bonus and milestone side-effects (moving spend off a card might cost a fee waiver — the report flags affected cards but doesn't solve the joint optimisation); caps accrue per statement cycle when the cycle is known, calendar month otherwise; gap math uses confirmed-category spend only and shows the trust meter alongside.

**Done when:** rules for all 8 cards entered and reconciliation is green (within tolerance) for two consecutive statement cycles on at least 5 cards; the gap report produces the target sentence on real data; a synthetic fixture with hand-computed expected losses (covering caps, exclusions, and a mid-window rule change) passes to the paisa; every number drills down to transactions and matched rules.

**Out:** automatic T&C ingestion, MCC data (statements don't carry it), time-of-day/weekend rate conditions, forex markup modeling, points expiry tracking, "which new card should I get" simulation (v2 candidate — the data model already supports evaluating a hypothetical card's rules against real spend).

---

## 4. Cross-cutting requirements

- **Money:** integer paise end-to-end (ADR-005). UI formats Indian-style (₹1,23,456.78).
- **Dates:** ISO `YYYY-MM-DD` in storage and API, always.
- **Backups:** the app makes a dated copy of the DB file before any migration and before any destructive bulk operation (`data/backups/hisaab-<date>-<reason>.db`, last 20 kept). `/api/clear` is removed entirely.
- **Privacy in artifacts:** no full card numbers anywhere (last4 only); statement files live under gitignored `statements/`; passwords never persisted.
- **Testing:** parser golden corpus is a permanent institution (ADR-006); every new parser or parser fix lands with corpus coverage.

## 5. Explicit journeys (end-to-end)

1. **Statement day** (monthly, ~7 min): described in M2, plus a pass through the M3 review queue (~5–10 new merchants, one click each) and a glance at the M10 reconciliation badges.
2. **Gap review** (monthly, ~3 min): open Rewards → read the loss number and top-3 gaps → adjust which card lives in which app/wallet accordingly. This is the payoff journey the app exists for.
3. **Kite refresh** (weekly/monthly, ~1 min): M8.
4. **Manual snapshot pass** (monthly, ~10 min): M6.
5. **Correction loop** (ad hoc, seconds): spot a miscategorized transaction → click → fix at the merchant level → every past and future transaction follows.
6. **Rules maintenance** (rare, ~5 min/event): a bank devalues or re-tiers a card → close the old rule window, open the new one. Reconciliation mismatches are the tripwire that tells you this happened.

One-time setup costs (not recurring): rules worksheet ~15 min/card × 8, historical merchant-review backlog ~30 min.

Total sustained effort: **≈25 minutes/month.** If a design choice pushes this up, the choice is wrong.

## 6. OUT of scope (explicit, agreed 2026-07-12)

- Budgets and alerts of any kind.
- Tax views (capital gains, 80C) — snapshot data can't do this honestly.
- Goals (corpus targets, funded-by mapping).
- Transaction-level investment ledger and true XIRR.
- Historical backfill of net worth.
- Bank-account *transaction* parsing (balances only; schema keeps the door open — ADR-003).
- UPI/wallet tracking.
- Rewards counted in net worth. *(Point valuation itself is now IN scope — required by M10, per redemption route. Only the net-worth exclusion survives from the original decision.)*
- MCC-based categorization (statements don't expose MCC); any external merchant-category database.
- Automatic card-T&C ingestion or scraping; rules are owner-maintained.
- "Which new card should I get" simulation (v2 candidate), points expiry tracking, time-of-week rate conditions, forex markup modeling.
- Joint optimisation of gaps against milestone/threshold side-effects (v1 flags the interaction, doesn't solve it).
- Multi-user, auth, cloud sync, mobile app, email ingestion.
- Any Account-Aggregator integration (not accessible to individuals — ADR-004).
