"""Description normalizer (ADR-009, task 4.1).

A pure, deterministic function that strips the payment-rail noise off a raw
transaction description so the same merchant stops appearing as a dozen
different strings. It is the substring basis the merchant-alias layer (task
4.2) matches against, and the grouping key the review queue (4.3) buckets by.

Scope is deliberately conservative — exactly what ADR-009 specifies:
  lowercase → strip `UPI-`/gateway prefixes → strip trailing city tokens and
  bare numbers → collapse whitespace.
It does NOT try to canonicalize to a single "Swiggy" (that is the alias
layer's job, via longest-substring matching), and it does NOT fuzzy-correct
typos (`Banglore`) or strip corporate suffixes (`Pvt Ltd`) — over-merging
distinct merchants is worse than leaving a little noise for the alias layer
to absorb. Every rule here is allow-list driven (known gateways, known
cities) so it can never silently mangle an unrecognized merchant token.

All constants are harvested from the real corpus's distinct `raw_description`
shapes; test_normalize.py pins the behavior against those same shapes.
"""
import re

# Payment-gateway / acquirer prefixes that appear as `<gateway>*<merchant>`.
# Allow-list ONLY — `surfshark*` and `grab*` also occur in the corpus but are
# real merchants, so they are deliberately absent and pass through untouched.
_GATEWAYS = {
    "razorpay", "raz", "rsp",           # Razorpay + SmartCollect variants
    "payu", "pyu", "pu",                # PayU
    "paytm", "ptm",                     # Paytm
    "cashfree", "cas",                  # Cashfree
    "easebuzz", "easebozz",             # Easebuzz (+ a real misspelling in data)
    "ccavenue",                         # CCAvenue (per ADR; not yet in corpus)
    "jiop",                             # JioPay
    "rbl",                              # RBL acquirer
    "pay",                              # generic PAY* wrapper
}

# Leading transaction-instrument tokens (delimited by `-` or whitespace), not
# part of the merchant name. Stripped repeatedly so stacked forms like
# `EMI UPI-...` peel fully.
_LEADING_TOKENS = ("upicc", "upi", "emi")

# City / location suffixes, longest-phrase-first so multiword cities win before
# their trailing single word does. Matched both as a trailing whitespace/comma
# -delimited token AND as a glued suffix (`SwiggyBANGALORE` -> `swiggy`).
_CITIES = [
    # multiword first
    "navi mumbai", "new delhi", "south delhi", "dki jakarta", "south jakarta",
    "lombok utara", "hong kong", "bengaluru urban", "bengaluru urb",
    # single word
    "bengaluru", "bangalore", "banglore", "mumbai", "gurugram", "gurgaon",
    "gurgoan", "faridabad", "thane", "noida", "newdelhi", "delhi", "nagpur",
    "darjiling", "jakarta", "badung", "gianyar", "berlin", "london", "internet",
]

# Trailing geo qualifiers that aren't cities themselves.
_TRAILING_NOISE = ("in", "urban", "urb", "utara", "kab")


def _preclean(raw: str) -> str:
    """The shared pre-peel tidy: lowercase, drop reference blocks, normalize
    separators, collapse whitespace. Factored out so normalize() and
    leading_instrument_tokens() cannot drift — both must see the same string
    before the peel loop runs, or they would disagree about what is leading."""
    s = raw.lower()
    s = re.sub(r"\(ref#[^)]*\)", " ", s)   # drop "(ref# ...)" reference blocks
    s = s.replace("_", " ")                # underscores are word separators here
    return re.sub(r"\s+", " ", s).strip()  # collapse runs of whitespace early


def _strip_leading(s: str, collect: list | None = None) -> str:
    """Peel gateway (`x*`) and instrument (`upi-`/`emi`) prefixes, repeatedly.

    `collect`, when given, receives each instrument token in peel order — the
    evidence source for the payment-channel lens (see channel.py). We record
    what the peel discards rather than re-deriving it, because the rules that
    decide what counts as a leading token (the delimiter set, stacking, the
    interleaved gateway case) are corpus-harvested here and must not be forked.
    """
    changed = True
    while changed:
        changed = False
        s = s.lstrip(" -")
        # gateway*  (allow-list only)
        m = re.match(r"([a-z]{2,9})\*", s)
        if m and m.group(1) in _GATEWAYS:
            s = s[m.end():]
            changed = True
            continue
        # leading instrument token, delimited by '-', '/', or whitespace
        for tok in _LEADING_TOKENS:
            m = re.match(rf"{tok}[-\s/]", s)
            if m:
                if collect is not None:
                    collect.append(tok)
                s = s[m.end():]
                changed = True
                break
    return s


def _strip_trailing(s: str) -> str:
    """Peel trailing ref tails, cities (delimited or glued), geo qualifiers,
    and bare numbers/pincodes, repeatedly and longest-first."""
    changed = True
    while changed:
        changed = False
        s = s.strip(" ,-")

        # "(kab)" regency qualifier, e.g. "badung (kab)"
        if s.endswith("(kab)"):
            s = s[:-5]
            changed = True
            continue

        # trailing number preceded by a separator: pincode "560008", "- 15",
        # bare "60". A number glued to letters (a store code inside a name) is
        # left alone — only separator-delimited trailing digits are noise.
        m = re.search(r"[\s,-]\d+$", s)
        if m:
            s = s[:m.start()]
            changed = True
            continue

        # city as a delimited trailing token (space or comma)
        for city in _CITIES:
            if s.endswith(" " + city) or s.endswith("," + city) or s == city:
                s = s[: len(s) - len(city)]
                changed = True
                break
        if changed:
            continue

        # geo qualifier token (India country code, "urban", ...)
        for noise in _TRAILING_NOISE:
            if s.endswith(" " + noise) or s.endswith("," + noise):
                s = s[: len(s) - len(noise)]
                changed = True
                break
        if changed:
            continue

        # city glued directly onto the name with no delimiter. Guarded so we
        # never reduce the string to just-the-city or near-nothing.
        for city in _CITIES:
            if s.endswith(city) and len(s) - len(city) >= 3:
                s = s[: len(s) - len(city)]
                changed = True
                break
    return s


def normalize(raw: str) -> str:
    """Return the noise-stripped, lowercased merchant string for `raw`.

    Deterministic and side-effect free. May return '' for descriptions that
    are pure payment references with no merchant (e.g. a UPI bill-payment ID);
    the caller treats an empty result as unmappable, not an error.
    """
    if not raw:
        return ""
    s = _strip_leading(_preclean(raw))
    s = _strip_trailing(s)
    s = re.sub(r"\s+", " ", s).strip()     # final tidy after edge removals
    # A result with no letters is a pure payment reference (a UPI/BBPS id),
    # never a merchant — return '' so the caller treats it as unmappable.
    if not re.search(r"[a-z]", s):
        return ""
    return s


def leading_instrument_tokens(raw: str) -> list:
    """Return the payment-instrument tokens ('upi', 'upicc', 'emi') peeled off
    the FRONT of `raw`, in peel order. Empty when there is no such prefix.

    Shares normalize()'s exact pre-clean and peel loop, so a leading-token
    match requires a real delimiter — which a substring test cannot express:

        'UPI-UBER INDIA'      -> ['upi']
        'EMI UPI-GLOBUS'      -> ['emi', 'upi']     (stacked prefixes)
        'UPICC-0902595...'    -> ['upicc']          (normalize() gives '' here,
                                                     but the rail is knowable)
        'UPIWALA STORES'      -> []                 (glued: a merchant name)
        'SOME SHOP UPI REF'   -> []                 (present but not leading)
    """
    if not raw:
        return []
    tokens: list = []
    _strip_leading(_preclean(raw), collect=tokens)
    return tokens
