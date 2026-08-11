# 07 — Decision Log: how FinTrack got here, and why

This is not a technical handoff (see [06-phase-2-handoff.md](06-phase-2-handoff.md)
for that — it's written for the next engineer or AI session to continue the code).
This document is for a **person** — someone being handed this project cold, who
needs to understand not just what exists, but *why it's shaped this way*. Every
non-obvious fork in the road is here: what we were trying to do, where we got stuck
or wrong, what we decided, and why. Read this once, and the codebase stops looking
like a pile of choices and starts looking like a sequence of reasoned trade-offs.

---

## What FinTrack was

A single Windows user's personal side project: three Python files (`app.py`,
`pdf_parsers.py`, a scratch debug script), a Jinja+vanilla-JS frontend, and a SQLite
database. It ingested credit-card statements — PDF and CSV — from seven Indian bank
cards, auto-categorized transactions by keyword matching, and showed a dashboard of
spend by category, by card, over time. No automated tests existed. Every uploaded PDF
was parsed in memory and discarded — only the filename survived in the database.
Money was stored as SQLite `REAL` (floating point). It worked, for one person, on one
machine, and had quietly accumulated the kind of technical debt that never bites you
until the day it does.

## What FinTrack is now

A personal finance OS in active construction: the same card-tracking core, being
rebuilt on a proper foundation (real tests, a golden-file parser corpus, schema
migrations, integer money), with a full React frontend replacing the old one, and a
second major pillar — a rewards-optimization engine — under design to answer the
question the whole rebuild is really for: *which card should I have used, and what
did using the wrong one cost me?* Net worth tracking (equities, EPF/PPF, gold,
property, loans) is planned as a third pillar once the card side is solid. See the
[phased backlog](04-phased-backlog.md) for exactly where things stand today.

---

## The decisions that actually shaped this

### 1. Audit before opinion

**The situation:** the owner handed over a working app and asked for it to become a
"personal finance OS," but hadn't written down what that meant.

**What we did:** read the entire codebase, ran what tests existed (none), queried the
real database, and formed an independent view of what was fragile — *before* asking
a single question. Findings were ranked by how badly each would bite later, not by
how easy each was to fix (a `REAL`-typed money column and a missing test suite rank
above a UI polish item, even though the UI item is more visible).

**Why it mattered:** it meant the interview that followed wasn't "what do you want,"
it was "here's what I found, here's my read on it, tell me where I'm wrong" — a much
higher-value conversation, and one where the owner corrected real misreadings early
(see decision 4) instead of discovering them after code was written.

### 2. Snapshot investments, not a transaction ledger

**The fork:** should equity/mutual-fund holdings be tracked as a full buy/sell
ledger (enabling true XIRR and realized-gains math) or as periodic dated snapshots
(simpler, matches what a brokerage API actually hands you)?

**Why it was the hardest call to get right:** it's nearly impossible to reverse.
Snapshots can never be un-collapsed back into the trades that produced them; a ledger
can always be *rendered* as snapshots. Get this wrong and there's no cheap way back.

**Decision:** snapshots. The owner is willing to spend ~20 minutes a month on manual
upkeep, not maintain a trading ledger by hand, and Kite Connect (the one usable data
source) hands you point-in-time holdings, not a full history. XIRR was explicitly
ruled out as a result — a real capability given up, named as such rather than quietly
dropped.

### 3. One data model for cards *and* net worth

**The problem:** card transactions and equity holdings and EPF balances and home
loans look nothing alike on the surface. Modeling them as unrelated tables would have
been the easy path.

**Decision:** everything is an `account`; every account is valued one of three ways —
snapshot-valued (equities, EPF, gold, property, bank), formula-valued (loans, computed
from amortization terms, never stored), or zero-valued (credit cards — they drive
analytics, not net worth). This is the single idea that lets "what am I worth" and
"where did my money go" share a foundation instead of being two separate apps bolted
together.

**Alternative rejected, on purpose:** a full double-entry ledger (the textbook-correct
answer) was considered and turned down — it would require transaction-level
investment data, which decision 2 had already ruled out. Named as "the road not
taken," not silently avoided.

### 4. The purpose correction — the biggest pivot in the project

**What happened:** partway through discovery, the owner stopped and corrected the
entire premise. The original brief described *what* FinTrack does (tracks cards,
shows spend) but never said *why it exists*. The real answer, once stated: FinTrack
exists for **credit-card rewards optimization**. Three jobs, in order of value —
understand expenses, understand what you actually earn per rupee (net of caps and
exclusions, not the advertised rate), and — the one that matters most — **identify
where you used the wrong card and what it cost you.**

**The honest admission:** the spec written up to that point had captured job one
completely and job two as a side feature, but had *missed job three entirely*. In the
interview that produced the original spec, the assistant had asked what rewards
*tracking* should look like and gotten confirmation on "no rupee valuation of
points" — the right call for keeping points out of net worth, but it meant the
conversation never got to "what is rewards tracking actually *for*." A real miss,
named as one rather than smoothed over.

**What changed as a result:** a new module (the rewards-optimization engine) and two
new architecture decisions — a card-rules data model (programs, redemption routes,
capped/excluded earn rules, threshold bonuses) and a merchant-level categorization
system (because a gap report is only as trustworthy as the category data feeding it).
The whole backlog was re-sequenced: the rewards engine now ships *before* net worth,
because a personal finance OS that tracks everything except the thing it exists for
would be backwards.

### 5. Certainty is impossible, so build confidence instead

**The problem, surfaced while designing the categorization fix:** bank-provided
transaction categories are inconsistent across issuers, statements carry no
merchant-category codes, and keyword matching is noisy (the same merchant shows up
under five different gateway-prefixed aliases). There is no way to make
categorization *certain*.

**Decision:** stop trying. Categorize the *merchant*, not the transaction (fix it
once, it stays fixed everywhere that merchant appears), track an explicit confidence
level per transaction (`confirmed` / `suggested` / `bank` / `keyword` /
`uncategorized`), and surface a visible trust meter — the percentage of spend that's
actually confirmed — on every report that depends on categories. A gap report
computed from 60%-confirmed data now says so, on its face, instead of presenting a
number with hidden uncertainty.

### 6. Counterfactuals that don't overclaim

**The problem:** the whole point of the rewards engine is to say "you lost ₹N by
using the wrong card." It would be easy to compute this by comparing raw advertised
rates — and easy to be *wrong*, because it ignores whether the better card's monthly
cap was already used up by other spending.

**Decision:** the counterfactual is cap-aware — it checks the alternative card's
*remaining* headroom given what was actually spent on it that period, not just its
advertised rate. Rejected alternatives: a naive rate comparison (systematically
overstates losses — exactly the kind of dishonesty the whole project is trying to
engineer out of the old app) and a full portfolio-optimization solve (technically
more "correct," but produces advice that can't be explained in one sentence, which
defeats the purpose for a personal tool one person has to trust).

### 7. Rejected once, accepted once shown

**What happened:** the owner asked for an F1-motorsport visual direction — deep
black, red accents, condensed racing type. A mockup was built matching that
description. It was rejected: "this is bad."

Later, the owner shared a different, fully-built personal project (a flight-search
results page) as a reference and said they loved its vibe — which was, on paper, the
*same brief*: black background, red accents, condensed italic type. The difference
wasn't the brief. It was that the second time, there was a concrete, working example
to point at instead of an abstract description to guess from — and the reference
revealed a real, specific discipline the first mockup had missed: red and motion
accents were used *sparingly*, on chrome (buttons, nav, one brand mark), never on
repeated data rows. The first mockup had put skew and glow on every rank chip in a
dense list, and that's very likely what read as "gaudy."

**One more fork inside this decision:** the reference used red as its *ambient*
brand color. FinTrack had already reserved red exclusively for losses and alerts —
specifically so a red number in the future gap report means "you lost money" and
nothing else. Adopting the reference literally would have destroyed that signal. The
owner — a Red Bull Racing fan — resolved it by picking Red Bull's navy as the brand
color instead, keeping red rare and reserved. A "borrow the vibe, not the exact
palette" outcome that neither a literal copy nor a rejection would have reached.

**The lesson worth keeping:** an identical-sounding design brief can fail as an
abstract description and succeed once there's a concrete artifact to react to — and
even then, "I love this" doesn't mean "copy every pixel." It means find the specific
thing that's actually being loved (here: restrained use of accent color and motion)
and adapt it to constraints the reference never had to deal with.

### 8. Don't guess at what a bank statement says — read one

**The recurring pattern, not a single decision:** almost every parser bug found and
fixed this project came from an assumption that turned out wrong on first contact
with a real file, and right only after reading one:

- Assumed "Total Amount Due" was a sum of that cycle's purchases. It's a running
  *balance* (previous dues minus payments plus new spend plus fees) — true for every
  bank in the corpus except one. Found by testing the assumption against real
  statement text, not by reasoning about what seemed likely.
- Assumed the Kotak parser's failure to capture credit-card payments was a simple
  fix. There was no real example of what Kotak's payments section actually looks
  like anywhere in the corpus — writing the fix without one would have been the
  exact guess-driven parsing this whole rebuild exists to eliminate. Work paused
  until the owner supplied a second real statement.
- Assumed a credit-marker pattern found in a *sanitized* Amex statement would hold
  on a real one. It didn't — the real statement embedded the masked card number
  inside the marker text in a way the redacted copy didn't reproduce. The bug was
  caught immediately because a reconciliation check was already in place to catch
  exactly this kind of silent misclassification.

**Why this belongs in a decision log rather than a bug list:** the common thread
isn't any one fix, it's the standing rule that produced them all — every parser
change is checked against a corpus of real statements, not written from what a
statement is expected to say. That rule is *why* each of these was caught quickly
instead of shipping silently, and it's worth defending the next time someone is
tempted to skip building the fixture for "just a small parser tweak."

### 9. Two similar things that are deliberately not the same thing

**The question:** does FinTrack handle a recurring monthly reward bonus (e.g. "make
4 payments over ₹1,500 in a calendar month" on one particular card) as a "milestone"?

**What we found on checking, rather than assuming:** yes — but as a different
mechanism than milestones. A *milestone* is a one-time, cumulative spend target with
a single start and end date (an annual fee-waiver target). A *bonus rule* is
recurring — it resets every statement cycle or calendar month, and can threshold on
transaction count, not just a rupee sum. The Amex example is, almost word for word,
the design document's own example for what a bonus rule is *for*. The two had already
been kept as separate concepts; the question surfaced whether that separation was
still the right call rather than an oversight.

**Decision:** keep the split. Pulling recurrence into the milestone table would
duplicate accrual-period logic that the rewards engine already owns properly, to
solve a problem the existing design already solves elsewhere.

### 10. A conflict found mid-migration, resolved before it shipped

**The situation, current as of this writing:** while building the schema migration
that will let FinTrack safely reject a duplicate statement import, the original
architecture decision's design was found to contain a real bug: a database constraint
that would make an explicitly-approved feature (force-importing a statement even when
its dates overlap an existing one) *impossible* to actually use, in the one case where
someone would need it — reimporting a statement with the same billing cycle but
different file bytes.

**Decision, made without shipping the conflict:** drop the offending constraint from
the actual migration, keep the safety net it was trying to provide (rejecting
byte-for-byte duplicate files) through a different, non-conflicting check, and record
the deviation plainly rather than quietly patching around it. The parent design
document still needs a matching correction — flagged as unfinished business, not
resolved by pretending it wasn't found.

**Why this belongs here even though it's not finished:** it's the same discipline as
decision 8, just caught one level up — in a schema design instead of a parser regex.
Written down while it's still open, so whoever picks it up next (a person or another
session) inherits the reasoning, not just a `TODO`.

---

## The throughline, if there's only time for one sentence

Every decision above came from checking a real assumption against real evidence — a
real statement, a real screenshot, a real database — before committing to code, and
naming plainly the moments something was wrong, missed, or unresolved rather than
smoothing them into a clean success story. That habit is the actual product of this
project so far, more than any single line of code.
