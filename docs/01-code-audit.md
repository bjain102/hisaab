# 01 — Code Audit

**Date:** 2026-07-12
**Scope:** Full read of `app.py`, `pdf_parsers.py`, `debug_rewards.py`, templates/static, the live SQLite DB (`data/hisaab.db`, a few hundred transactions, Jan–Jul 2026), and the `statements/` folder (35 files). Parsers were executed against the redacted statement files. No application code was modified.

All amounts in this document are synthetic. No card numbers, real amounts, or statement contents appear here.

---

## 1. What exists

| Piece | Reality |
|---|---|
| Backend | Single-file Flask app (`app.py`, ~760 lines): routes, CSV parsers, keyword categorizer, schema DDL, and ad-hoc migrations all in one module. |
| PDF parsing | `pdf_parsers.py` (~370 lines): five regex-based parsers (IDFC, ICICI, Axis, Kotak, HDFC) over `pdfplumber` text extraction, each also scraping a rewards balance. Amex is CSV-only. |
| Frontend | One Jinja template (`templates/index.html`) + vanilla JS (`static/js/app.js`, ~650 lines) + CSS (~500 lines). Four views (Dashboard, Transactions, Import, Milestones) toggled by class switching. No framework, no build step, no motion. |
| Data | SQLite, 6 tables. a few hundred transactions across 8 card labels. Dates are clean (all `YYYY-MM-DD`), amounts currently all have ≤2 decimal places. |
| Tests | **None.** No test files, no pytest, no fixtures. The README makes no coverage claims — but it does claim runtime behavior that is false (see F6). |
| Statements | `statements/` holds 35 PDFs/CSVs, one subfolder per card, including one `*_redacted.pdf` per card. Gitignored. The app itself discards every uploaded PDF after parsing. |

### Test coverage: claimed vs real

Claimed: nothing explicit. Implied by the README ("the relevant parser gets a targeted fix"): an iterate-on-real-files workflow.
Real: **zero automated coverage of any kind.** Every parser fix is verified by manually re-importing a file and eyeballing the UI. There is no way to know whether a fix to the HDFC parser breaks the Tata Neu variant without manually re-importing both. This is the enabling condition for most findings below.

---

## 2. Findings, ranked by how badly they bite

Severity is ranked by *expected damage to your data or trust in the numbers*, not by code aesthetics.

### F1 — HIGH: No regression corpus; parsers are unverifiable (the flagged finding)

Uploaded statements are **not persisted anywhere** — verified empirically on all three possible channels (2026-07-12):

1. **Config vs usage:** `app.config['UPLOAD_FOLDER'] = 'uploads'` (`app.py:13`) is dead configuration — it is never referenced again; there is no `file.save()` anywhere in the codebase. The upload route reads the file into memory (`file.read()`, `app.py:395` for PDF / `app.py:413` for CSV), parses, and lets it go.
2. **Filesystem:** `uploads/` exists and is empty, untouched since Jun 30 despite 29 imports since.
3. **SQLite:** no table has a BLOB column; the DB file is ~172 KB, physically too small to contain the ~35 statement files it has ingested.

The only surviving artifact per import is the filename string in `import_batches.filename`. The parsers encode dozens of bank-specific layout assumptions (documented below in §3) with nothing pinning them down. Any parser edit — including a "targeted fix" for one bank — can silently change what another statement parses to, and nothing will tell you.

The raw material for the fix already exists: `statements/` has real files per card **and a redacted file per card**. Verified: the redacted files open without a password and parse (with one caveat: the Axis-Rewards redacted file had its amount column stripped by redaction, so it yields 0 transactions — it needs re-redacting to keep amounts syntactically intact, or synthetic amounts substituted).

**Fix (designed in ADR-006, built in Phase 1):** golden-file corpus + pytest snapshot tests + per-statement reconciliation. Parsers become testable against real files; every future parser change runs against every statement. **Go-forward persistence** (spec M2, backlog 3.4): every successfully imported file is copied to `statements/<card>/<label>_<period-end>.<ext>` with its SHA-256 recorded, so the corpus grows automatically with each month's imports and no statement is ever parse-and-discarded again.

### F2 — HIGH: Parsers silently drop transactions by design

Every parser follows the same pattern: iterate lines, `continue` on regex mismatch. A line that doesn't match is not an error, not a warning, not a counter — it vanishes. Combined with F1, this means **a bank layout change doesn't break imports; it silently shrinks them.** You would discover missing transactions only by noticing your spend looks low.

Aggravating factor: every Indian card statement prints its own totals ("Total Purchases", "Payments & Other Credits", closing balance). **No parser reconciles its extracted transactions against the statement's own totals.** This is the single cheapest correctness check available and it's absent.

The upload route's only guard is `if not transactions:` — a statement that parses to 1 of 40 transactions imports "successfully."

### F3 — HIGH: Latent date-transposition bug for Indian bank CSVs

`parse_date()` (`app.py:224`) tries `%m/%d/%Y` (US, for Amex) **before** `%d/%m/%Y`. This one function serves the CSV parsers for HDFC, ICICI, Axis, Kotak, and IDFC — all of which emit DD/MM dates. Any date with day ≤ 12 parses without error to the wrong date (e.g. `05/03/2026` → May 3 instead of March 5); dates with day > 12 fail `%m/%d/%Y` and fall through correctly — so a single import produces a **mix** of correct and transposed dates, which is worse than uniformly wrong.

Current damage: none — the only CSV imports so far are Amex, which genuinely is MM/DD. But this detonates the first time a non-Amex CSV is imported. (The PDF parsers use `parse_date_flexible()`, which correctly tries `%d/%m/%Y` first — the bug is CSV-path only.)

### F4 — HIGH: No dedup; overlapping imports double-count silently

`transactions` has no uniqueness constraint, and the upload route never checks for prior imports. The live DB already shows the consequence: 35 groups of identical (date, description, amount, card) rows. Some are genuine repeat purchases (same-day identical Uber rides), but the July 7 import batches (full-cycle statements) demonstrably overlap the earlier per-month files for IDFC, HDFC Swiggy, and Amex — those overlaps are counted twice in every dashboard number today.

The only remedy is manual batch deletion, which requires you to *know* an overlap happened. Nothing tells you.

**Fix (decided in interview):** statement-period gating — parsers extract the statement cycle (PDFs print it; CSVs derive it from min/max transaction dates), and imports whose period overlaps an existing statement for that card are rejected with an override. Known accepted limitation: a partial CSV export of an already-covered month will be wrongly rejected and needs the override. One-time cleanup of the existing overlaps is backlog task 3.7.

### F5 — MEDIUM-HIGH: Rewards balance clobbered by import order

`rewards` is `UNIQUE(card_label)` with an unconditional upsert on import (`app.py:458`): whichever statement you imported *last* wins, regardless of which period it covers. Import January's statement after May's (exactly what a catch-up session looks like) and your rewards balance regresses four months with no indication. Also: deleting an import batch does not roll back the rewards row it wrote.

**Fix (decided):** `rewards` becomes dated history keyed by (card, statement period end); "current balance" is the latest-dated row.

### F6 — MEDIUM: Milestones never update, contradicting the README

README: "Progress updates automatically as you import more transactions." Reality: `current_spend` is written once, at milestone creation, from **all-time** card spend (`app.py:685`), and the upload route never touches it. It also ignores the milestone deadline, so a fee-waiver milestone created mid-year starts pre-credited with spend from before the card-anniversary window. Both numbers on your Milestones screen are wrong today unless the milestone was created seconds ago.

**Fix (decided):** milestones get an explicit date window; progress is computed live from transactions (net of refunds, excluding cashback and card-bill payments); the stored counter is dropped.

### F7 — MEDIUM: Per-bank parser fragilities (summary — detail in §3)

Most consequential single item: **the Kotak parser cannot capture credits.** It only reads the "Purchases made in this cycle" section and hardcodes `type='debit'` — payments, refunds, and reversals on Kotak are invisible. (Low current impact — 1 Kotak transaction in the DB — but it's a wrong-by-construction parser, not a missed edge case.)

### F8 — MEDIUM: Money as REAL (float)

All amounts are SQLite `REAL`. Today every stored value is ≤2dp and sums are small enough that IEEE-754 drift hasn't surfaced. But every aggregate the app shows is `SUM()` over floats, and the roadmap adds multiplication (holdings × price, EMI interest splits) where float error compounds. This is the classic "fine until it isn't" — and the migration cost only grows with the row count.

**Fix (ADR-005):** integer paise everywhere, migrate-and-verify (`SUM` before == `SUM` after, exactly).

### F9 — MEDIUM: Category overrides are order-nondeterministic substring matches

`category_overrides` (153 rows) are applied as a Python-dict iteration of substring tests — first match wins, and "first" is dict insertion order from an unordered `SELECT`. Two overlapping patterns (e.g. `amazon` and `amazon pay`) can categorize the same merchant differently across imports. Same mechanism in `recategorize` with `learn=true` does a `LIKE '%pattern%'` update across **all** transactions, including ones on other cards whose description happens to contain the substring.

### F10 — LOW-MEDIUM: Uniqueness constraints too narrow or too broad

- `import_batches.batch_id` is a wall-clock ISO timestamp — collision-safe only by luck of the microsecond; also used as the FK-by-convention from transactions (TEXT match, no actual FK, no `ON DELETE`).
- `card_profiles UNIQUE(bank, last4)` — `INSERT OR REPLACE` on this silently *replaces* a profile (new `id`, same card) if you re-add one, orphaning nothing only because nothing references profiles by id.
- `rewards UNIQUE(card_label)` — too broad, cause of F5.
- No indexes beyond PKs (harmless at this row count; noted for the net-worth tables which will be queried by `(account, date)` constantly).

### F11 — LOW: Committed secret

`debug_rewards.py` contains a hardcoded statement PDF password (DOB-derived pattern) and is committed to git. Local-only repo mitigates, but the file is scratch code and should be deleted; if the repo is ever pushed anywhere, the git history carries it. (Not reproducing the value here.)

### F12 — LOW: Assorted

- `/api/clear` drops all transactions + batches with no confirmation and no backup. One stray fetch away from data loss; the DB file is also not backed up anywhere by the app.
- `/api/transactions` hard-caps at `LIMIT 1000` with no paging — already at 602; the UI will silently truncate within months.
- Amex CSV sign convention (`amt > 0` → debit) is assumed, not verified against a credit-containing export; Amex refunds would flip sign and the parser's handling of them is untested.
- `escapeHtml` is used inconsistently in `app.js` (descriptions escaped in tables, card labels interpolated raw into `<option>`s). Single-user local app → theoretical, not urgent.
- SQL construction is parameterized throughout; the one f-string interpolation (`ORDER BY`) draws from a whitelist dict. No injection risk found.

---

## 3. Per-parser reality check

Method: code read + execution against the redacted files in `statements/`. "Silent failure" = line dropped with no signal.

### IDFC (`parse_idfc_pdf`)
- **Handles:** section-scoped (debits vs credits) DD/MM/YYYY rows with trailing `DR`/`CR`; multi-line merchant wrap (two documented patterns: merchant on previous line; merchant split across previous+next lines); forex artifact stripping for 8 hardcoded currencies (IDR, USD, EUR, GBP, SGD, AED, THB, MYR).
- **Assumes:** section header strings exact (`'Purchases, EMIs & Other Debits'`); amounts always end the line; wrap never exceeds one line each side.
- **Silently fails on:** any currency outside the hardcoded 8 (JPY, LKR, VND…) — the artifact stays glued to the description; transactions before the first section marker; EMI breakout lines.
- **On layout change:** section markers move/reword → **entire statement parses to zero rows** → at least the upload guard fires. Date or amount format change → partial silent loss.
- Redacted-file run: 7/7 date-lines parsed, rewards found.

### ICICI / Amazon Pay (`parse_icici_pdf`)
- **Handles:** single-line rows `date serial# description amount [CR]`, optional leading EMI-percent token; strips trailing numeric tokens (reward-point columns) from descriptions.
- **Assumes:** every row has a serial number; description never *ends* in a meaningful number (a merchant like "STORE 24" loses the "24"); amount always has 2 decimals.
- **Silently fails on:** wrapped descriptions (second line has no date → dropped); rows where pdfplumber merges columns differently.
- **On layout change:** any change to the serial-number column kills every row → zero-import guard fires. Subtler drift → partial silent loss.
- **Rewards scrape is the shakiest in the file:** the fallback branch (`'Earned' in line and 'Amazon' in line` + a two-number regex) can match an unrelated summary line and store a wrong balance with no error.

### Axis (`parse_axis_pdf`)
- **Handles:** rows with an optional UPPERCASE merchant-category column (captured as `bank_category`) and optional `Dr`/`Cr` suffix; falls back to a category-less pattern.
- **Assumes:** category is strictly `[A-Z .&]+` — a category containing a digit or lowercase falls through to the simple pattern, where **the category text gets absorbed into the description**; missing `Dr`/`Cr` suffix defaults to debit.
- **Silently fails on:** wrapped description lines; international transaction sub-lines.
- **On layout change:** degrades gracefully-but-wrongly — rows keep parsing with polluted descriptions rather than failing loudly. Hardest of the five to catch by eye.
- Note: the Axis-Rewards redacted file yields 0 transactions, but I verified this is a redaction artifact (amounts were stripped from the file), not a parser bug. The corpus needs that file re-made.

### Kotak (`parse_kotak_pdf`)
- **Handles:** `DD-Mon-YYYY description category amount` rows, only between "Purchases made in this cycle" and a "Total…" line; last whitespace token treated as `bank_category`.
- **Wrong by construction:** never reads the payments/credits section; hardcodes `type='debit'` (→ F7). Multi-word categories ("Fuel Surcharge") lose all but the last word into the description-vs-category split; single-token descriptions become the category with an empty-ish description.
- **On layout change:** section marker changes → zero rows → guard fires.

### HDFC (`parse_hdfc_pdf`) — Swiggy + Tata Neu variants
- **Handles:** rows keyed on a `DD/MM/YYYY| HH:MM` prefix (the `|` is a pdfplumber extraction quirk, not statement text); trailing currency-glyph artifact stripping; credit detection via a standalone trailing `+` token; disambiguates `+ <number>` (NeuCoins-earned column) from the credit marker.
- **Assumes:** the pipe quirk is stable across pdfplumber versions — **it is an artifact of the text extractor, not the document**; a pdfplumber upgrade can silently zero every HDFC import. This is the strongest single argument for the pinned-dependency + corpus regime.
- **Silently fails on:** EMI-conversion sub-rows; any row where time is absent.
- Redacted-file runs: 32/32 and 64/64 date-lines parsed, rewards found for both variants. Best-tested parser purely by usage volume (442 of a few hundred rows are HDFC).

### Amex (CSV, `parse_amex`)
- **Handles:** `Date, Description, Amount` with positional-header fallback; sign convention `>0` = debit.
- **Assumes:** MM/DD/YYYY (correct for Amex); refund rows are negative (unverified, see F12).
- **On layout change:** column reorder → positional fallback grabs wrong columns → rows drop on date-parse failure *or* — worse — parse with wrong fields. Combined with F3's date ambiguity, this is the parser where a format change can produce *plausible wrong data* rather than zero data.

---

## 4. Current-DB integrity snapshot

Checked 2026-07-12:

- a few hundred transactions, 8 card labels, dates 2026-01-01 → 2026-07-01, all dates well-formed, `card_label` never null.
- **35 duplicate groups** on (date, description, amount, card) — mixture of genuine repeats and F4 double-imports. Needs the one-time review pass (backlog 3.7); cannot be auto-resolved because genuine same-day repeats are real.
- All amounts ≤2dp; no float damage yet (F8 is preventative).
- `rewards` has 4 rows, all `source='statement'` — each is "whichever import came last," per F5, so treat current balances as suspect until re-imported newest-last.
- 2 milestones, both with stale `current_spend` per F6.
- 153 category overrides (F9 applies).

---

## 5. What is actually good

Worth saying, because the rewrite should preserve it:

- The **net-spend model** (gross debits − refunds, cashback excluded from both, card-bill payments excluded from credits) is more honest than most commercial apps, and the SQL implementing it is correct for what it stores.
- The **learn-on-recategorize** loop is the app's best feature and the reason its categories beat CRED's.
- `bank_category` capture (Axis/Kotak) as default-over-keyword is the right precedence.
- Parameterized SQL throughout; passwords used in-memory only (the app-side handling is fine — F11 is a scratch file, not the app).
- The redacted-statement files in `statements/` mean the corpus fix (F1) is a day of work, not a month.
