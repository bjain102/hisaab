"""Task 4.1: the ADR-009 description normalizer.

Table-driven, with every case drawn from a real `raw_description` shape in the
owner's corpus (synthetic-safe: these are merchant/noise strings, no amounts
or PII beyond what a card statement already prints). Each row pins the exact
normalized output, so the normalizer's behavior is frozen against real data —
4.2's alias layer and 4.3's review-queue grouping both build on this being
stable.
"""
import pytest

from categorization import normalize

# (raw_description, expected_normalized). Grouped by the rule each exercises.
CASES = [
    # ── gateway prefixes stripped (allow-list) ──────────────────────────────
    ("RAZORPAY*Swiggy         Bangalore", "swiggy"),
    ("RAZ*SwiggyBangalore", "swiggy"),
    ("CAS*SwiggyBengaluru", "swiggy"),
    ("PTM*SWIGGY INBANGALORE", "swiggy"),
    ("PayU*ZEPTO MARKETPLACE  Bangalore", "zepto marketplace"),
    ("JIOP*RELIANCE RETAIL LI MUMBAI", "reliance retail li"),
    ("RSP*INSTAMARTBANGALORE", "instamart"),
    # gateway look-alikes that are actually MERCHANTS — must NOT be stripped
    ("Grab* A-9F6VMCQWWWDSAV, South Jakarta", "grab* a-9f6vmcqwwwdsav"),
    ("SURFSHARK* SURFSHARK., SURFSHARK.COM", "surfshark* surfshark., surfshark.com"),

    # ── UPI / EMI instrument prefixes (incl. stacked) ───────────────────────
    ("UPI-UBER INDIA SYSTEMSPRIVAT", "uber india systemsprivat"),
    ("UPI-zeptonow", "zeptonow"),
    ("UPI-KALA RAM", "kala ram"),
    ("EMI UPI-GLOBUS DESIGN", "globus design"),
    ("EMI TATA PAYMENTS LIMITEDMUMBAI", "tata payments limited"),

    # ── trailing cities: delimited, comma, multiword, country-code ──────────
    ("SWIGGY,BANGALORE", "swiggy"),
    ("ZEPTONOW, NAGPUR", "zeptonow"),
    ("AGODA.COM, Berlin", "agoda.com"),
    ("JIOP*RELIANCE RETAIL LI NAVI MUMBAI", "reliance retail li"),
    ("ZOMATO GURGAON IN", "zomato"),
    ("AMAZON PAY IN GROCERY BANGALORE IN", "amazon pay in grocery"),
    ("VRINDAVAN PURE INDIAN VEG, Badung (Kab)", "vrindavan pure indian veg"),

    # ── trailing cities glued directly onto the name ────────────────────────
    ("SwiggyBANGALORE", "swiggy"),
    ("ZEPTONOWMUMBAI", "zeptonow"),
    ("WESTSIDEBANGALORE", "westside"),

    # ── pincodes, bare numbers, ref blocks ──────────────────────────────────
    ("CALIFORNIA BURRITO      560008", "california burrito"),
    ("UPI-HOPCOMS 60", "hopcoms"),
    ("NYKAA (Ref# RT261560091000010162753) - 15", "nykaa"),

    # ── underscores are separators; whitespace collapses ────────────────────
    ("UPI-HEALTHWAY_PHARMA_", "healthway pharma"),
    ("AMAZON                  Mumbai", "amazon"),

    # ── pure payment references -> '' (no merchant) ─────────────────────────
    ("UPICC-090259055286-15-03-2026", ""),
    ("UPI/124140827202/030626/", ""),

    # ── conservative: things that must be LEFT ALONE ────────────────────────
    # city word inside a name (not trailing) is preserved
    ("UPI-BENGALURU CAFE", "bengaluru cafe"),
    ("UPI-THE_BANGALORE_PRINTING_an", "the bangalore printing an"),
    # "india" is not the country-code token "in" — don't over-strip
    ("NOMAD INDIA", "nomad india"),
    # trailing person-name initials are not noise
    ("UPI-BEERESHA M N", "beeresha m n"),
    # alphanumeric vehicle plate stays — the alias layer (4.2) collapses BMTC
    ("UPI-BMTC BUS KA57F1377", "bmtc bus ka57f1377"),
]


@pytest.mark.parametrize("raw,expected", CASES)
def test_normalize_pins_corpus_shapes(raw, expected):
    assert normalize(raw) == expected


def test_empty_and_none():
    assert normalize("") == ""
    assert normalize(None) == ""


@pytest.mark.parametrize("raw,_", CASES)
def test_idempotent(raw, _):
    once = normalize(raw)
    assert normalize(once) == once


def test_case_insensitive_forms_collapse_together():
    """The all-caps, title-case, and glued forms of the same merchant must
    all land on one normalized string — the whole point of the function."""
    forms = ["SWIGGY,BANGALORE", "SwiggyBANGALORE", "RAZORPAY*Swiggy   Bangalore",
             "CAS*SwiggyBengaluru", "PTM*SWIGGY INBANGALORE"]
    assert len({normalize(f) for f in forms}) == 1
