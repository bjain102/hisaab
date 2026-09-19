# 08 — Architecture Review

**Date:** 2026-09-06
**Scope:** Full read of `app.py`, `pdf_parsers.py`, `categorization/`, `rewards/`,
`networth/`, `db.py`, the `frontend/src` tree, the test suite, and the live schema.
Every quantitative claim below was measured against the repository and the real
database at the date above, not recalled.
**Status:** Assessment only. Nothing here was implemented as part of writing it —
this is a list of what an experienced reviewer would say about the codebase as it
stands, ordered by what actually matters.

**On the numbers:** the database figures are a point-in-time snapshot and move as
statements are imported (transaction count moved 1,649 → 1,682 during the hour this
was written). Treat them as scale indicators, not constants.

---

## 0. Snapshot

| | |
|---|---|
| Backend | 5,356 lines Python — `app.py` **2,193**, `pdf_parsers.py` 1,081, rest across 4 packages |
| Frontend | 7,129 lines TS/TSX — `api/client.ts` 763, `api/types.ts` 529 the largest |
| API surface | **46 routes**, all in one file |
| Parsers | **8 PDF** (amex, axis, hdfc, hsbc, icici, idfc, indusind, kotak), **6 CSV** |
| Schema | 9 versioned migrations, `user_version=9` |
| Tests | 42 files, 351 test functions — **575 passing, 45 skipped** |
| Real data | ~1,682 transactions, 11 card accounts, ~442 merchants, ~435 aliases |
| Statements on disk | 65 MB, 137 files |

## 1. What is genuinely strong

Stated first because a review that only lists faults misleads about where this
codebase actually sits. These are choices worth defending in any design review:

- **The golden-file parser regime (ADR-006).** Pinning every corpus statement's
  exact parsed output, plus reconciling against the bank's own printed totals, is
  the correct answer to "PDF parsing is unfalsifiable." It keeps earning its cost:
  it caught HSBC's `NET OUTSTANDING BALANCE` line doubling a statement to the
  rupee, IndusInd's right-column bleed-through, and HDFC's description-wrap — each
  by *arithmetic*, not by someone eyeballing a diff. `gen_expectations.py --check`
  reporting zero drift is a real safety property, not a formality.
- **Migrations with `verify()` inside the transaction.** A failed verification
  rolls back the version bump too. Better than Alembic's default posture, and
  better than most production systems.
- **Integer paise end-to-end** (ADR-005), with rupees confined to parser input and
  display output. The one place money conversion happens is the DB boundary.
- **`category_source` as first-class provenance.** This is the project's actual
  intellectual contribution. Most finance apps hand you a category and no way to
  interrogate it; this one records *why* every categorisation exists and can
  therefore report honestly on how much of your spend you've personally vouched for.
- **A demonstrated willingness to refuse to guess.** HSBC shipped with credits
  unimplemented rather than inventing a marker; `computable: false` gates rules the
  statement data can't see; "TAD is a balance, not a sum" is documented per parser.
  This discipline is why the parsers are trustworthy, and it is rarer than it sounds.

## 2. The structural debt: one file, and the ADR that says it shouldn't be

`app.py` is **2,193 lines and 46 routes**. ADR-001 states plainly:

> *"In Phase 2 restructure from one file into a small package (app factory +
> blueprints: `cards`, `networth`, `ingest`)."*

Phase 2 shipped; Phases 3–6 piled on; the restructure never happened. There are
**zero blueprints** in the file today. `get_summary` is 197 lines and 9 queries;
`_import_statement` is 187. The frontend shows the same creep: `client.ts` at 763
lines and `types.ts` at 529 are both one-file-per-domain candidates.

This is the highest-leverage refactor available and it is *already designed* — the
work is mechanical, not architectural. The cost of leaving it isn't aesthetic: every
new feature now requires reading a 2,193-line file to know where code belongs.

**Recommendation:** blueprints (`cards`, `ingest`, `networth`, `rewards`) + an app
factory, queries pushed into a thin repository layer. Route behaviour and tests
unchanged — ADR-001 already frames it as "a re-org, not a rewrite."

## 3. Connection lifecycle is a latent bug generator

`get_db()` returns a raw connection. There are **80 manual `conn.close()` calls
against 98 `return jsonify(...)` sites**. Every route is one early return away from
leaking a connection, and any exception between open and close leaks by
construction. This has already produced adjacent bugs (a `conn.close()` ordering
mistake in the valuations route, fixed during 6.3).

The fix is standard Flask and would *delete* roughly 80 lines: connection on
`flask.g`, released in `teardown_appcontext`. While in there, two pragmas:

- **`PRAGMA foreign_keys = ON`.** Manual cascade logic now exists in at least four
  places (`reward_balances`, `loan_events`, `reward_accruals`, `valuations`), each
  with a comment explaining that the schema's own `ON DELETE CASCADE` is decorative.
  That's a recurring, self-inflicted tax, and every new table repeats it.
- **`PRAGMA journal_mode = WAL`** plus a busy timeout — today a long import blocks
  reads.

## 4. Categorisation: the matcher, and what the `cc` incident really exposed

**Partly fixed since the first draft of this review, so stated as it now stands.**

Three guards now exist, all added in response to a real incident where a
two-character alias (`cc`) silently claimed unrelated transactions:

- `MIN_ALIAS_LEN = 4` in `app.py` — refuses to *store* a too-short alias.
- `MIN_MERCHANT_LEN = 3` in `normalize.py` — refuses to *manufacture* a too-short
  identity in the first place.
- A reference-token stripping rule, so per-statement rail codes stop generating a
  fresh merchant every cycle.

What remains unaddressed:

**4a. Alias specificity is still unmodelled.** A length floor is a proxy, not a
model. `hdfc` is four characters and would pass while being an equally bad rule.
The app already computes exactly the right signal — `_blast_radius(alias)` returns
how many transactions and which categories a confirm would restamp — and **shows it
to the user, but never enforces it**. Verified: zero references to blast radius
inside `_confirm_merchant`. Gating a confirm on "this alias would restamp N
transactions spanning M unrelated categories — are you sure?" is a small change
against machinery that already exists.

**4b. Stored aliases are permanent text snapshots, and nothing detects when they go
stale.** This is the sharpest finding in this document and it is *not* hypothetical
— it was hit twice in one session. Alias matching is `INSTR(normalize(description),
stored_pattern)`. Change `normalize()` and every stored alias computed under the old
rules keeps sitting in the table, silently unmatchable forever, because a longer old
pattern can never be contained in a shorter new normalized string. There is **no
re-normalisation mechanism anywhere** in `app.py`, the migrations, or `scripts/`
(verified). The failure is completely silent: no error, no test, no drift check —
categorisation simply gets quietly worse.

**Recommendation:** either store `normalized_description` on `transactions` as a
maintained column (see 4c) and re-derive aliases from it, or add a migration-time
"re-normalise all aliases" step that runs whenever `normalize()` changes, with a
test asserting every stored alias still equals `normalize()` of at least one live
transaction. Today nothing would tell you.

**4c. The matcher won't scale, structurally.** `_confirm_merchant` loads **every
transaction into Python and calls `normalize()` per row** on each confirm. At ~1,700
rows that's fine. The real issue is that the normalised form is never stored — it's
recomputed constantly and can't be indexed or joined. Storing
`normalized_description` (populated at write, backfilled by migration, indexed)
turns alias matching into a SQL join and the review queue's grouping into a
`GROUP BY` — and, per 4b, gives re-normalisation something concrete to operate on.

**4d. The review queue silently excludes credits.** `WHERE type='debit' AND
is_cashback=0`. Defensible for a *spend* review tool — but it means a miscategorised
credit can never surface for review. This is the mechanism behind a real sprawl:
bill payments (all credits) never appeared in the queue, so they were confirmed
one at a time from the Transactions page instead, each creating a throwaway
single-use alias. The queue's own design quietly pushed the user toward the action
that made the mess. Worth either including credits in a separate section, or
surfacing "N credits categorised only by keyword" somewhere.

## 5. The strategic problem: the stated purpose is behind a `false` flag

ADR-008 rev. 2 makes rewards optimisation *the app's core job*. Today
`REWARDS_INTELLIGENCE_ENABLED = false`, and ~900 lines across `engine.py`,
`gaps.py`, `reports.py` are dark — **but not idle**. `rebuild_accruals()` fires from
**6 write paths** and maintains **1,407 accrual rows** against 7 seeded reward
programs, for a UI nobody can see. Every import and every recategorise pays that
cost and gets nothing back.

This is a product decision, not an engineering one, and it is **still open** — it
was raised in conversation and not resolved. Three honest options:

1. **Revive it.** It was archived because it "wasn't working well," but the *why*
   was never diagnosed — wrong model, thin `ccyamls` data, or unconvincing
   presentation? Thirty minutes of diagnosis should precede any other decision here.
2. **Narrow it.** The full gap report ("you lost ₹X by using the wrong card") needs
   counterfactual reasoning across cap states — genuinely hard. *"Which card should
   I put this next purchase on?"* is most of the value at a fraction of the
   complexity.
3. **Cut it.** Delete the engine, keep the schema. Dead code that runs is strictly
   worse than dead code that doesn't.

Leaving it exactly as-is is the only option worth arguing against.

## 6. Ingestion automation — and the tension worth naming first

Automating ingestion is the right instinct: the monthly manual import is the app's
largest friction, and friction is what kills personal tools. But there's a conflict
that should be stated before anything is built.

**This app exists specifically to avoid granting standing access to financial
data.** A cloud automation platform holding a persistent Gmail OAuth token plus a
vault of statement passwords reintroduces exactly the trade it was built to escape —
with the automation vendor in the position CRED used to occupy.

The version that preserves the original principle:

- A **local** folder watcher — mail-rule the statements into a folder, or drop them
  in — with the app ingesting anything new on launch. Zero standing credentials,
  most of the convenience.
- If mail access is wanted: **IMAP with an app-specific password, read-only,
  running locally**, scoped to one label. Materially different from OAuth-into-SaaS.
- Statement passwords in the OS keychain (`keyring` → Windows Credential Manager),
  never a config file.

**Why this is unusually achievable here:** ingestion is already idempotent by
construction — SHA-256 file hashing plus period-overlap gating (F4) means a
re-import is safely refused. Most apps would need that built first.

**Related, and more urgent as volume grows:** `statements/` is **65 MB across 137
files** of unencrypted real bank PDFs sitting beside the database, and the backup
logic snapshots only the `.db`. Auto-ingestion makes that pile grow faster and
unattended. At minimum, document a restore path that includes it; better, encrypt
the directory.

## 7. Where the product could go

- **Lead with provenance — it's the moat.** No mainstream finance app can tell you
  *why* a transaction is categorised as it is. This one can. Make the trust meter
  clickable: "92% verified — here are the 8%, and here's what each one is resting
  on." That's a differentiated product idea, not a feature.
- **The long tail is an embeddings problem, not a rules problem.** The review queue
  exists because ~200 one-off UPI payees can't be keyword-matched. A local
  sentence-embedding model — nothing leaving the machine, fully consistent with the
  privacy stance — could cluster `SRI LAKSHMI CONDIMENTS` and `KRISHNA STORES` as
  "local grocery" and *suggest*. Note the schema already has a `suggested` merchant
  status that is barely used; this is what it was for.
- **Recurring-payment detection.** Dated transactions plus canonical merchants make
  "Netflix ₹649 monthly, ₹799 since March" a straightforward periodicity analysis,
  and it's the single most-loved feature in Monarch/Copilot-class apps.
- **Cash-flow forecasting.** Loan amortization (known future outflows) + recurring
  subscriptions + statement cycles ⇒ "you'll owe ₹X across three cards by the 15th."
- **Mobile.** The monthly review is a couch activity. The review queue in
  particular — swipe to categorise — is a natural phone interaction. There is
  currently no responsive story at all.

## 8. Operational gaps

- **No CI.** No `.github/`. 575 tests that run only when someone remembers. A
  GitHub Action on the public repo is about an hour of work and would have caught
  nothing so far only because the discipline has been manual and good.
- **Zero frontend tests.** 7,129 lines of TypeScript, no runner. Broad coverage
  isn't needed — but `dateRange.ts`, `format.ts`, `deltaMovers.ts` and `client.ts`'s
  paise conversion are pure functions where a bug is silent *and* financial. That
  handful is the highest-value test debt in the codebase.
- **`pytest` sits in `requirements.txt`** alongside runtime deps, and there's no
  lockfile — transitive drift will eventually break a fresh clone.
- **`app.run()` as production.** Fine for localhost, but single-threaded: a long PDF
  parse blocks the UI entirely. `waitress` is a one-line swap on Windows.
- **Parser asymmetry is undocumented outside code.** 8 PDF parsers vs 6 CSV — `hsbc`
  and `indusind` are PDF-only because no CSV export has been seen. The CSV path
  returns a clean 400, which is correct, but the asymmetry is worth a line in the
  README so it reads as deliberate.

## 9. Suggested order

1. **Decide the rewards engine's fate** (§5) — a product decision that blocks
   sequencing everything else, and currently costs compute for zero return.
2. **Connection lifecycle + `foreign_keys=ON` + WAL** (§3) — small, deletes code,
   removes an entire bug class.
3. **CI on the public repo** (§8).
4. **Alias staleness detection** (§4b) — the silent one. Even just a test asserting
   every stored alias still matches something would surface it.
5. **Split `app.py` into blueprints** (§2) — already designed in ADR-001.
6. **Store `normalized_description`; move matching into SQL** (§4c).
7. **Local folder-watch ingestion** (§6).
8. **Pure-function frontend tests** (§8).

---

*Nothing in this document was acted on. Items 1 and §5's open question in particular
need an owner decision before implementation.*
