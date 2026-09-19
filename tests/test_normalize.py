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

    # ── trailing reference-code token stripped (a real recurring bug: 22
    # separate one-off merchants existed in the owner's real DB for what is
    # structurally one bill-payment rail, one per statement's reference) ──
    ("BPPY CC PAYMENT DP015338113028vFnND (Ref# ST253390083000010255226)", "bppy cc payment"),
    ("BPPY CC PAYMENT DP016124172327GWWQR (Ref# ST261250083000010125876)", "bppy cc payment"),
    ("BillDesk BBPS CC Payment/DP316154FI2LOPZ1IBXY", "billdesk bbps cc payment"),
    ("BBPS PAYMENT RECEIVED - DP016005164322XTMZL7", "bbps payment received"),
    ("BBPS PMT BBPSDP2162317BJ548Z24FOZ", "bbps pmt"),
    ("BBPS Payment received", "bbps payment received"),  # already-clean form, unaffected
    # the same rule, found by accident, correctly cleans two manually-pinned
    # HSBC rows too — their STORED category is untouched (manual pins are
    # never re-normalized), this only concerns what normalize() itself returns
    ("JOINING FEE CC26201600663", "joining fee"),
    ("IGST ASSESSMENT @18.00% CC26201600663", "igst assessment @18.00%"),
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


def test_reference_token_needs_six_digits_to_be_stripped():
    """The floor that keeps the reference-token rule from eating a real short
    alphanumeric code. The BMTC vehicle plate (already pinned above,
    'ka57f1377') has its longest digit run at 4 ('1377') and survives whole —
    restated directly here as the boundary the rule is built around, not
    relying on the reader to notice it in the table above."""
    assert normalize("UPI-BMTC BUS KA57F1377") == "bmtc bus ka57f1377"
    assert "1377" in normalize("UPI-BMTC BUS KA57F1377")


def test_residual_shorter_than_min_merchant_len_is_unmappable():
    """The other half of the real bug (app.py's MIN_ALIAS_LEN is the write-time
    guard; this is normalize() refusing to manufacture the garbage identity in
    the first place). 'UPI CC-04-01-2025-500476327499' strips — correctly, via
    the EXISTING trailing-number rule eating one dash-separated digit segment
    at a time, nothing to do with the reference-token rule above — all the way
    down to the bare residual 'cc'. That used to pass the old 'has letters'
    check and get treated as a real 2-letter merchant; it must not anymore."""
    assert normalize("UPI CC-04-01-2025-500476327499 (Ref# ST250080084000010533270)") == ""
    assert normalize("UPI CC-17-09-2025-562629430035") == ""


@pytest.mark.parametrize("raw", [
    "UPI-Amul", "UPI CRED 659026251352", "CULT BENGALURU 190",
    "UPI IOCL 658528323254", "UPI-Lulu Bangalore", "MOAI BANGALORE 27",
    "SAVR BENGALURU IN",
])
def test_four_letter_real_merchants_survive_the_length_floor(raw):
    """MIN_MERCHANT_LEN=3 was chosen, not guessed: these are the shortest
    LEGITIMATE normalized merchants actually present in the real corpus, every
    one of them exactly 4 characters. The floor sits at 3 specifically so it
    clears all of these with room for a hypothetical 3-letter brand (kfc)
    while still catching the 2-letter 'cc' residual above."""
    assert len(normalize(raw)) == 4


def test_case_insensitive_forms_collapse_together():
    """The all-caps, title-case, and glued forms of the same merchant must
    all land on one normalized string — the whole point of the function."""
    forms = ["SWIGGY,BANGALORE", "SwiggyBANGALORE", "RAZORPAY*Swiggy   Bangalore",
             "CAS*SwiggyBengaluru", "PTM*SWIGGY INBANGALORE"]
    assert len({normalize(f) for f in forms}) == 1
