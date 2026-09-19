# Rewards rules worksheet (task 5.2)

> **SUPERSEDED (2026-07-19):** the owner filled this in as structured YAML
> instead — one file per card in [`ccyamls/`](../ccyamls/), format documented
> in [`ccyamls/SCHEMA.md`](../ccyamls/SCHEMA.md), validated by
> `python scripts/validate_card_rules.py`. Those files are the 5.2 source of
> truth; this document remains only as the original field-by-field guide
> (and for the Kotak Zen card, which has no YAML yet).

**Purpose:** this is the raw material the Phase 5 rules engine (ADR-008) runs
on. The engine can only be as honest as what's filled in here — anything you
don't know or that's genuinely ambiguous, write in the Notes column rather
than guessing. `Uncategorized`/blank is better than a confident wrong number.

**Where to get this:** each bank's **MITC** (Most Important Terms & Conditions)
document or the card's rewards T&C page — search "`<bank>` `<card name>`
MITC" or check the bank's app under the card's terms/rewards section.
Budget **~15 min per card** (8 cards ≈ 2 hours total).

**How this becomes data:** once filled in, each card's row(s) below become one
`reward_programs` row (+ `redemption_routes` + `earn_rules` + `bonus_rules`)
per ADR-008. You don't need to touch SQL — just fill in this document (or
tell me the answers) and the 5.2 rules editor / a one-time seed script turns
it into rows. A **devaluation later** = close this program's `valid_to` and
open a new dated block; never edit history.

**The categories the engine matches against** (`earn_rules.category` — must
be spelled exactly as below, or leave blank for "any category" base rules):

```
Food & Drinks · Transportation · Travel · Insurance · Shopping · Medical ·
Grocery · Health & Wellness · Utility Bills · Credit Card Bills ·
Reversals & Refunds · Others · Entertainment · Apps & Software · Fuel ·
Professional Services · Finance Charges · Rent · Wallet/Prepaid Load ·
Government & Taxes · Education · Jewellery · Uncategorized
```

---

## Per-card template (copy this block per card)

```
### <BANK> <Card variant> (····<last4>)

Program name:            ______________________  (e.g. "Membership Rewards")
Earn currency:           [ ] points   [ ] cashback (₹)
Annual fee:              ₹______  (0 if lifetime-free)
Fee waived by:           [ ] spend milestone  [ ] never charged  [ ] not waivable
  → if spend milestone: ₹______ in ______ months of card membership

Base earn rate:          ______ points per ₹100   (or ₹______ per ₹100 if cashback)

Accelerated categories/merchants (highest priority first):
  1. Category/merchant: ____________  Rate: ______ per ₹100   Cap: ______ /month [or /cycle/year]
  2. Category/merchant: ____________  Rate: ______ per ₹100   Cap: ______ /month
  3. Category/merchant: ____________  Rate: ______ per ₹100   Cap: ______ /month

Excluded categories (earn ZERO — check the T&C's exclusion list, commonly
rent, wallet loads, fuel, insurance, government/tax payments, EMI conversions):
  ____________________________________________________

Threshold bonus (if any), e.g. "spend ₹X in Y transactions/month → Z bonus pts":
  Min transactions: ______   Min ₹ per txn: ______   OR min total spend: ₹______
  Period: [ ] statement cycle [ ] calendar month [ ] calendar year
  Bonus units: ______

Redemption routes (how points convert to value — list every route you
actually use, mark your usual one as default):
  Route name           Value per point      Default?
  ___________________  ₹______ per point    [ ]
  ___________________  ₹______ per point    [ ]

Notes (devaluations you know are coming, weird rules, anything uncertain):
  ____________________________________________________
```

---

## Your 8 cards — pre-filled with what Hisaab already knows

Each block below already has the account identity and whatever the app has
observed from statements (reward balance label/type, any milestone). Fill in
the rest from the card's MITC.

### AMEX MRCC (····1009)
```
Program name:            Membership Rewards            [confirm exact name]
Earn currency:           [ ] points   [ ] cashback (₹)  [likely points]
Annual fee:              ₹______
Fee waived by:           [x] spend milestone — app already has one recorded:
                             target ₹1,50,000, window 2026-07-07→2026-07-31
                             (this window looks OWNER-INFERRED from the 3.6
                             migration, not your card's real fee-year — please
                             correct window_start/window_end if wrong)
Base earn rate:          ______ points per ₹100
Accelerated categories/merchants: ______
Excluded categories: ______
Threshold bonus: ______
Redemption routes: ______
Notes: ______
```

### AXIS MyZone (····9698)
```
Program name:            EDGE Rewards                  [confirm exact name]
Earn currency:           [x] points (observed: "EDGE Points", balance 7,678 as of 2026-07-07)
Annual fee:              ₹______
Fee waived by: ______
Base earn rate: ______
Accelerated categories/merchants: ______
Excluded categories: ______
Threshold bonus: ______
Redemption routes: ______
Notes: ______
```

### AXIS Rewards (····6587)
```
Program name:            EDGE Rewards                  [confirm exact name]
Earn currency:           [ ] points   [ ] cashback (₹)  [no balance observed yet]
Annual fee:              ₹______
Fee waived by: ______
Base earn rate: ______
Accelerated categories/merchants: ______
Excluded categories: ______
Threshold bonus: ______
Redemption routes: ______
Notes: ______
```

### HDFC Swiggy (····1930)
```
Program name:            Swiggy HDFC Cashback           [confirm exact name]
Earn currency:           [x] cashback ₹ (observed: "Cashback", ₹198.20 as of 2026-07-07)
Annual fee:              ₹______
Fee waived by: ______
Base earn rate:          ₹______ per ₹100
Accelerated categories/merchants: ______  [likely Swiggy-branded spend gets a higher %]
Excluded categories: ______
Threshold bonus: ______
Redemption routes:       cashback is usually auto-credited — mark the single
                          "Statement credit" route as default, value = ₹1 per ₹1
Notes: ______
```

### HDFC Tata Neu Infinity (····8886)
```
Program name:            NeuCoins                       [confirm exact name]
Earn currency:           [x] points (observed: "NeuCoins", balance 173 as of 2026-07-07)
Annual fee:              ₹______
Fee waived by:           [x] spend milestone — app already has one recorded:
                             target ₹3,00,000, window 2026-07-07→2027-03-24
                             (same caveat as AMEX above — verify the real window)
Base earn rate: ______
Accelerated categories/merchants: ______  [Tata Neu app / Tata-brand spend usually accelerated]
Excluded categories: ______
Threshold bonus: ______
Redemption routes:       NeuCoins are typically 1 NeuCoin = ₹1 on the Tata Neu app —
                          confirm and list other routes if any
Notes: ______
```

### ICICI Amazon Pay (····4006)
```
Program name:            Amazon Pay Cashback             [confirm exact name]
Earn currency:           [ ] points   [x] cashback ₹ (Amazon Pay cards are cashback-only) [no balance observed yet]
Annual fee:              ₹______  [often lifetime-free]
Fee waived by: ______
Base earn rate:          ₹______ per ₹100
Accelerated categories/merchants:  Amazon.in spend, Prime member spend — usual tiers differ
Excluded categories: ______
Threshold bonus: ______
Redemption routes:       cashback credits as Amazon Pay balance — mark as default,
                          value = ₹1 per ₹1
Notes: ______
```

### IDFC Wow! (····4111)
```
Program name:            IDFC Reward Points              [confirm exact name]
Earn currency:           [x] points (observed: "Reward Points", balance 1,330 as of 2026-07-07)
Annual fee:              ₹______
Fee waived by: ______
Base earn rate: ______
Accelerated categories/merchants: ______
Excluded categories: ______
Threshold bonus: ______
Redemption routes: ______
Notes: ______
```

### Kotak Zen (····7404)
```
Program name:            ______________________
Earn currency:           [ ] points   [ ] cashback (₹)  [no balance observed yet]
Annual fee:              ₹______
Fee waived by: ______
Base earn rate: ______
Accelerated categories/merchants: ______
Excluded categories: ______
Threshold bonus: ______
Redemption routes: ______
Notes: ______
```

---

## When you're done

Hand the filled-in version back (or just tell me the answers card by card,
even a few at a time is fine) and I'll turn it into the `reward_programs` /
`redemption_routes` / `earn_rules` / `bonus_rules` seed data once the 5.1
schema migration is in place. You don't need perfect precision on every
field — the reconciliation loop (comparing modeled earnings against your
actual statement balances) is what catches a wrong number later, so getting
started beats getting it perfect.
