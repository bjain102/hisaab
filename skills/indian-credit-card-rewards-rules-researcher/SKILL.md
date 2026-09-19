---
name: indian-credit-card-rewards-rules-researcher
description: "Research the rewards rules of one Indian credit card variant and write or refresh its machine-readable rules YAML for the Hisaab rewards engine (the ccyamls/ contract). Use this whenever the user asks to research a card's rewards, T&C, or MITC; add a new card YAML; update, re-verify, or fix an existing card file; record a devaluation or announced rule change; or says a card's rules look stale — even if they only name the card and say 'update it'."
---

## Job

Given one Indian credit card (bank + product name, e.g. "HDFC Tata Neu Infinity"),
research its CURRENT rewards structure from multiple sources and produce — or
update — a rules file in the Hisaab card-rules YAML contract, ready for human
review. The output feeds a personal rewards-optimisation engine that computes
per-transaction accruals from card statements, so three things matter more than
completeness: precision, honest uncertainty, and knowing which rules the engine
can actually compute (see "The computable flag" — the single most important
section of this skill).

Two modes:
- **New research**: no file exists for the card yet → full research pass, new file.
- **Update / re-verify**: a file already exists → read it FIRST, then research
  what changed and edit it. Follow "Update mode" below; never start from scratch.

## Hisaab integration (check for the repo first)

If you are working inside (or can see) the Hisaab repo:
- The canonical contract is **`ccyamls/SCHEMA.md`** — read it if in doubt; it
  wins over this skill's summary of the format.
- Existing files in **`ccyamls/`** are worked exemplars — skim one (e.g.
  `hdfc-swiggy.yaml` for a cashback card, `amex-mrcc.yaml` for a points card)
  before writing.
- After ANY write, run **`python scripts/validate_card_rules.py`** and fix
  every error it reports. Do not consider the task done with a failing
  validator. (It checks parsing, enums, taxonomy categories, unique
  priorities, exactly-one-base-rule, exactly-one-default-route, and that
  `account` matches a real DB account.)
- File naming: `ccyamls/<bank>-<card>.yaml`, lowercase, hyphens, **no shell-
  hostile characters** (`!`, spaces, `&` — an earlier file named `...wow!.yaml`
  broke shell tooling). One YAML document per file — the validator cannot read
  multi-document files.
- The `account:` field must be the exact `accounts.name` string from the
  Hisaab DB (e.g. `AMEX-MRCC-1009`). If unsure, list them:
  `python -c "import sqlite3; print([r[0] for r in sqlite3.connect('data/hisaab.db').execute(\"SELECT name FROM accounts WHERE kind='credit_card'\")])"`

If the repo is NOT available (e.g. researching in a chat), still produce the
exact same format; the user will drop the file into `ccyamls/` and validate.

## Sources, in trust order — consult multiple, cite every field

1. The bank's official rewards-program T&C / addendum for this specific card variant (NOT just the MITC — MITC is usually stale on caps and exclusions).
2. The MITC and the card's official product page (base rates, fees).
3. The bank's rewards portal / redemption catalog (the ONLY honest source for rupee-value-per-point by redemption route).
4. Community documentation: TechnoFino, CardExpert.in, r/CreditCardsIndia — frequently the only accurate record of caps, exclusions, and recent devaluations. Treat as the cross-check layer; prefer recent posts. Record the URL and publication/checked date for every field. Where sources conflict, report BOTH values with their sources — do not silently pick one.

### Blocked or unreadable official documents — STOP AND ASK

Bank sites frequently block automated fetching (robots/ROBOTS_DISALLOWED) of the
exact PDFs that matter (MITC, rewards T&C). If an official document cannot be
fetched:
- Do NOT silently substitute community transcriptions of it and present them at
  official-source confidence.
- PAUSE before finalising: tell the user which document(s) you could not read,
  give the exact URL(s), and ask them to download and upload the file(s). Then
  read the uploaded file and treat it as the official source (confidence HIGH).
- Only if the user declines or cannot provide it: proceed using community
  transcriptions, cap those fields at MEDIUM confidence, and add a review_flag
  stating that the official document was never directly read.

### Stale-official vs fresh-announcement conflicts

Banks often announce rule changes by cardholder email weeks before updating their
website. A stale official page does NOT override a well-corroborated announced
change; record both, model the announced ruleset separately (see "Announced
rulesets"), and flag that no official page carries the new terms yet.

## The two-layer contract — why every rule has both prose and numbers

Each file carries two layers, and both are load-bearing:

- **Structured fields** (`account`, `earn_rate`, `cap_units`, `bonus_units`,
  enums, …) are what the seeder and accrual engine read. They must be exact —
  a typo here becomes a wrong rupee claim in the gap report.
- **Prose fields** (`rate`, `cap`, `note`, `sources` with per-fact confidence,
  `review_flags`, `devaluation_watch`, `benefits_watch`) are the research
  record: nuance, caveats, provenance. The machine ignores them; humans (and
  the reconciliation loop, when modeled numbers disagree with real statements)
  depend on them. Never delete prose to "clean up" — when a fact changes,
  update it and say when/why (see Update mode).

Write the prose for a human deciding whether to trust a number; write the
structured fields for a program that will believe them unconditionally.

## Hard rules (research quality)

- Never guess. A cap or exclusion you cannot source is `UNKNOWN`, not omitted
  and not invented. Every UNKNOWN goes in the review_flags list.
- `UNKNOWN` vs `null` mean different things: `null` = confirmed not-applicable
  (e.g. `cap_units: null` = confirmed uncapped); `UNKNOWN` = researched but not
  found. Confusing them turns "we don't know" into "no cap exists".
- Every rate needs its earn basis stated exactly in the prose `rate` field
  (e.g. "2 pts per ₹100, rounded down per transaction" vs "per statement"),
  AND its clean economics in the structured `earn_rate`.
- Note the effective date of the current rule set if discoverable, and any
  devaluation announced or rumoured in the last 12 months.
- Category names MUST come from the Hisaab taxonomy (map the bank's wording
  to the closest match; note the mapping): Food & Drinks, Transportation,
  Travel, Insurance, Shopping, Medical, Grocery, Health & Wellness, Utility
  Bills, Credit Card Bills, Reversals & Refunds, Others, Entertainment,
  Apps & Software, Fuel, Professional Services, Finance Charges, Rent,
  Wallet/Prepaid Load, Government & Taxes, Education, Jewellery, Uncategorized.
  (If the repo is available, `app.CATEGORIES` is the source of truth.) If a
  bank category maps poorly, use the closest match or Others, state the
  imperfect mapping in the note — and think hard about `computable` (below).
- Attribute-keyed rules ("no earn on international spend", "contactless only")
  use the optional `scope` field (domestic | international | contactless |
  online | offline), not a fake category — and are almost always
  `computable: false`.
- Record MCC lists in the optional `mccs` field whenever sources provide them.
  Know their role: Hisaab statements carry NO MCC, so `mccs` is provenance
  (why a category mapping was chosen), not a matching key.
- Merchant accelerators use `merchant_match` with a LIST of lowercase brand
  tokens (`merchant_match: [swiggy]`, never a bare scalar). These are matched
  as substrings against normalized statement descriptions, so pick tokens that
  actually appear in descriptions ("tata", "bigbasket") — not invented labels.
  Carve-outs use `merchant_match_exclude` (also a list); state in the note what
  rate carved-out merchants fall back to.
- Shared/pooled caps: every rule in the pool gets the same `cap_group` token
  and the same `cap_units`/`cap_period`. A cap with no `cap_group` is per-rule.
  Pooled-vs-per-category is often the single highest-value fact about a card —
  if unconfirmable, that is a mandatory review_flag.
- Cap periods (statement_cycle vs calendar_month) are chronically ambiguous in
  bank copy ("per month"). Pick the better-supported reading, mark confidence,
  add a review_flag.
- Confidence per field: HIGH (official current doc), MEDIUM (official but
  possibly stale, or single community source), LOW (conflicting/old sources).
- Quote all dates as ISO strings (`"2026-07-18"`) — quoted, so YAML types stay
  consistent across files.

## Structured-field rules (the machine layer)

- `earn_rate` — required on every `accelerated`/`base` rule, forbidden on
  `excluded`. Exactly one shape, chosen by `program.reward_currency`:
  - points cards: `earn_rate: {points_per: 4, per_spend_inr: 200}` (floats OK,
    e.g. `points_per: 1.5`)
  - cashback cards: `earn_rate: {cashback_pct: 10}`
  Put the TOTAL rate a matching transaction earns (if a bank says "1X base +
  9X bonus", earn_rate carries the 10X total; explain the split and what the
  cap applies to in the note).
- `cap_units` — integer (points, or ₹ for cashback cards), `null` (confirmed
  uncapped), or `UNKNOWN`. A numeric cap requires `cap_period` ∈
  statement_cycle | calendar_month | calendar_quarter | calendar_year.
- `min_txn_inr` — integer or null.
- Exactly ONE `kind: base` rule per file, conventionally `priority: 99`.
  Priorities are unique per file: exclusions 1–9, accelerators 10–98, base 99.
- `program.fee_waiver_spend_inr` — integer (the 100% waiver spend threshold),
  `null` (no fee / no waiver concept), or `UNKNOWN`. Partial-waiver tiers stay
  in the prose `fee_waiver_condition`.
- Bonus rules: `period` ∈ statement_cycle | calendar_month | calendar_quarter
  | calendar_year | anniversary_quarter | anniversary_year | **one_time**
  (welcome gifts, renewal bonuses — never `null`). `bonus_units` integer for
  points/cashback bonuses; `null` + `bonus_kind: perk` for
  memberships/subscriptions; `null` + `bonus_kind: pct_of_spend` for
  percentage bonuses. `requires_enrollment: true` when the owner must opt in.
- Redemption routes: exactly one `recommended_default: true` per file.
  `value_per_point_inr` is a float; `null` = varies per catalogue item;
  `UNKNOWN` = not found. If the DEFAULT route has no fixed value, flag it —
  headline valuations become undefined.
- Membership-dependent tiers (e.g. Amazon Prime 5% vs non-Prime 3%): model
  BOTH rules, gate them with `requires_owner_flag: {amazon_prime: true}` /
  `{amazon_prime: false}`, and declare the flag in a top-level `owner_flags:`
  block. Research cannot determine the owner's membership — set the flag to
  `UNKNOWN` and ASK THE USER to set it (a review_flag until they do).

## The computable flag — the most important call you make

Every earn rule and bonus rule carries `computable: true|false`. The accrual
engine ONLY applies `computable: true` rules; `false` rules are kept as
documentation and surfaced as caveats on the card's numbers.

Why this exists: the engine sees parsed statement rows — date, description,
amount, category, merchant. It cannot see payment method, purchase channel,
or memberships. An EMI exclusion honestly mapped to `category: Others` would,
if seeded naively, zero out ALL Others-category spend — a silent, large error.
`computable: false` is the firewall against that class of bug.

Decision guide — mark `computable: false` when the rule depends on:
- **Payment method**: EMI conversions, cash advances, UPI (and which UPI app),
  wallet loads identified by method rather than merchant, forex/DCC.
- **Purchase channel**: portal click-throughs (Amex Reward Multiplier,
  SmartBuy), "via the bank's/partner's app" rates (Tata Neu app, IDFC app
  bookings), Login & Pay mechanisms.
- **Subset scope**: the bank's exclusion is narrower than the taxonomy
  category you mapped it to (Amex "utilities" = electricity/gas/water only,
  while telecom earns; Axis "Movie" ⊂ Entertainment). Excluding the whole
  category would over-exclude — mark false, explain in the note.
- **Transaction attributes** the statement doesn't carry: international,
  contactless (`scope` rules).
- **One-time historical bonuses** already credited (welcome gifts, first-year
  renewal): nothing to model forward.
- **Stacking**: a rule that adds on top of another matching rule (the engine
  is first-match-wins; it cannot stack).

Mark `computable: true` when the rule is expressible as category and/or
merchant-substring matching plus amount thresholds — including
membership-gated rules resolved via `owner_flags`, and bonus rules the engine
can evaluate from transaction data (e.g. "4 txns ≥ ₹1,500 per calendar
month"). When true-but-approximate (an MCC-gated tier approximated by its
category), keep true and record the approximation in the note plus a
review_flag if reconciliation drift is likely.

Always write the reason as an inline comment next to `computable: false` —
the next researcher must not "fix" it back to true.

## Update mode (file already exists)

1. **Read the existing file fully before searching the web.** Its
  review_flags and reverify_by tell you exactly what to check first; its
  sources tell you what was already consulted and when.
2. **Preserve history — never silently rewrite.**
  - Resolved uncertainty: don't delete the review_flag; rewrite it as
    `"RESOLVED <date> (<how>): <what was established>"` (e.g. owner
    confirmation, newly fetched official PDF).
  - Changed facts (a devaluation now in force): update the structured fields,
    update `rules_effective_from`, keep the old value visible in
    `devaluation_watch` with its date.
  - Keep `account`, the filename, and prose you didn't re-verify untouched.
3. **Bump `researched_on`** to today; set/refresh `reverify_by` (volatile
  cards — several devaluations in recent history — get a 3–6 month horizon).
4. **Owner-only fields** (`owner_flags`, anything marked owner-confirmed):
  never change these from web research; only the user can.
5. Run the validator; the file must pass before you're done.

## Announced rulesets (future-dated changes)

If a change is announced but not yet in force, keep the current file as-is
(`status: in_force`) and create a SIBLING file `<name>.announced.yaml` with
`status: announced`, its own `rules_effective_from` (the announced date), a
`reverify_by` (normally the effective date), and a review_flag that the terms
exist only in announcements. One YAML document per file — never `---`
multi-document files in `ccyamls/` (the validator can't read them). When the
change takes force, fold it into the main file (Update mode) and delete the
announced file. Devaluation + revaluation announced close together signals an
unstable ruleset — say so in devaluation_watch.

## Output template (annotated)

```yaml
card: HDFC Tata Neu Infinity            # bank + product, no card numbers
account: HDFC-Tata Neu Infinity-8886    # EXACT accounts.name from the Hisaab DB
researched_on: "2026-07-19"
status: in_force                        # in_force | announced
rules_effective_from: "2026-05-01"      # or UNKNOWN
rules_effective_to: null                # date the next ruleset takes over, if known
reverify_by: null                       # set for announced rulesets or unstable cards
owner_flags:                            # OPTIONAL — only when rules are membership-gated
  amazon_prime: UNKNOWN                 # ask the user to set; research can't know this
program:
  reward_currency: points               # points | cashback_inr
  unit_name: NeuCoins
  annual_fee_inr: 1499
  fee_waiver_condition: "Spend ₹3,00,000 in card anniversary year"   # prose, incl. partial tiers
  fee_waiver_spend_inr: 300000          # int | null (no fee) | UNKNOWN
  network: "Visa or RuPay"              # note pending migrations
  forex_markup: "2%"                    # affects effective intl earn
  sources: [{url: "https://…", as_of: "2026-07-19", confidence: HIGH}]
earn_rules:                             # priority order, first match wins
  - priority: 1                         # exclusions 1–9
    kind: excluded                      # excluded | accelerated | base
    category: Rent
    mccs: [6513, 7012, 7349]            # provenance only — statements carry no MCC
    computable: true                    # category-matchable exclusion
    note: "No earn on rent since 2025-xx"
    sources: [{url: "https://…", as_of: "2026-07-19", confidence: HIGH}]
  - priority: 2
    kind: excluded
    category: Others
    scope: international                # attribute rule, not a category
    computable: false                   # 'international' is invisible in parsed rows
    note: "No earn on foreign-currency spend"
    sources: [{url: "https://…", as_of: "2026-07-19", confidence: HIGH}]
  - priority: 10                        # accelerators 10–98
    kind: accelerated
    category: Shopping
    merchant_match: [tata]              # LIST of lowercase statement-visible tokens
    merchant_match_exclude: [tanishq]   # carve-outs; note the fallback rate
    earn_rate: {points_per: 5, per_spend_inr: 100}   # or {cashback_pct: 10} on cashback cards
    rate: "5 NeuCoins per ₹100, non-EMI"             # prose: exact earn basis
    cap: "2,000 NeuCoins per calendar month, POOLED" # prose: value + period + pooling
    cap_units: 2000                     # int | null (confirmed uncapped) | UNKNOWN
    cap_period: calendar_month          # statement_cycle | calendar_month | calendar_quarter | calendar_year
    cap_group: tata_pool                # same token on every rule sharing the cap; omit if per-rule
    min_txn_inr: null
    computable: true
    note: "…"
    sources: [{url: "https://…", as_of: "2026-07-19", confidence: MEDIUM}]
  - priority: 99                        # exactly one base rule
    kind: base
    earn_rate: {points_per: 1.5, per_spend_inr: 100}
    rate: "1.5 NeuCoins per ₹100, rounded down per transaction"
    cap_units: null
    computable: true
    sources: [{url: "https://…", as_of: "2026-07-19", confidence: HIGH}]
bonus_rules:                            # empty list if none
  - name: "Monthly usage bonus"
    period: calendar_month              # …| anniversary_quarter | anniversary_year | one_time
    min_txn_count: 4
    min_txn_inr: 1500
    min_spend_inr: null
    scope: null
    bonus: "1,000 points"               # prose
    bonus_units: 1000                   # int; null for perks/pct bonuses
    bonus_kind: points                  # points | cashback | perk | pct_of_spend
    requires_enrollment: false
    computable: true                    # evaluable from txn data (count/amount thresholds)
    note: null
    sources: [{url: "https://…", as_of: "2026-07-19", confidence: HIGH}]
redemption_routes:
  - name: "Tata Neu app"
    value_per_point_inr: 1.00           # float | null (varies) | UNKNOWN
    recommended_default: true           # exactly one true per file; reasoning in note
    note: "…"
    sources: [{url: "https://…", as_of: "2026-07-19", confidence: HIGH}]
benefits_watch:                         # OPTIONAL, brief: non-earn items that change card value
  - "Domestic lounge cut 4 -> 2 visits/year from 2026-07-26"
review_flags:                           # everything the human MUST verify
  - "Cap on 5x Tata accelerator conflicting: source A says 500/cycle (2026-03), source B says uncapped (2025-11)"
devaluation_watch:
  - "…"                                 # announced/rumoured changes, with dates
#Summary: <5 lines as a YAML comment — see below>
```

## After the YAML

End the file with a `#Summary:` YAML comment (a comment, NOT a markdown
section — the file must stay parseable): effective base rate, best
accelerator, biggest exclusion trap, fee-waiver math, and the single field
you're least sure about. In your chat reply (not the file), say explicitly if
any official document was blocked and not user-provided, if any ruleset is
announced-but-not-effective, and list any owner actions needed (owner_flags to
set, review_flags needing their judgment).
