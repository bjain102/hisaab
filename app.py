from flask import Flask, abort, request, jsonify, send_from_directory
import sqlite3
import os
import sys
from datetime import datetime
import traceback
import pdfplumber
import io as _io_module
from pdf_parsers import PDF_PARSERS
from db import backup_db, migrate, MigrationError
from categorization import classify_channel, normalize
from rewards import gaps as gaps_module
from rewards import reports
import csv
import io
import hashlib
import json
import re

# static_folder=None: legacy Jinja/static assets are gone (task 2.5) — every
# asset now flows through FRONTEND_DIST via the explicit spa() route below.
app = Flask(__name__, static_folder=None)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
DB_PATH = 'data/fintrack.db'
FRONTEND_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'frontend', 'dist')
# Module-level like DB_PATH so tests can monkeypatch it to a tmp dir — the
# hardcoded-path version of this (relative to app.py's own location) silently
# wrote real test files into the repo's real statements/ folder on every
# test run (caught and fixed while building task 3.4's gating tests).
STATEMENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'statements')

# ── Categories ───────────────────────────────────────────────────────────────
CATEGORIES = [
    "Food & Drinks", "Transportation", "Travel", "Insurance", "Shopping",
    "Medical", "Grocery", "Health & Wellness", "Utility Bills",
    "Credit Card Bills", "Reversals & Refunds", "Others", "Entertainment",
    "Apps & Software", "Fuel", "Professional Services", "Finance Charges",
    # M10-bound taxonomy additions (task 4.3, ADR-009): reward-relevant buckets
    # so ADR-008 exclusion rules have something to bind to. "Uncategorized" is
    # the honest first-class unknown; keyword's default stays "Others" for now.
    "Rent", "Wallet/Prepaid Load", "Government & Taxes", "Education",
    "Jewellery", "Uncategorized",
]

# ── Keyword rules ─────────────────────────────────────────────────────────────
CATEGORY_RULES = {
    "Food & Drinks": [
        "swiggy", "zomato", "dominos", "pizza", "mcdonald", "kfc", "burger",
        "subway", "starbucks", "cafe", "coffee", "restaurant", "biryani",
        "dining", "food", "barbeque", "bbq", "bakery", "chai",
        "juice", "dhaba", "eatery", "kitchen", "meals", "tiffin"
    ],
    "Transportation": [
        "uber", "ola", "rapido", "namma yatri", "yatri", "auto", "cab",
        "taxi", "metro", "bmtc", "irctc", "parking",
        "fastag", "toll"
    ],
    "Fuel": [
        "petrol", "fuel", "bp fuel", "indian oil", "hp petrol", "shell",
        "reliance petrol", "nayara", "iocl", "hpcl", "bpcl"
    ],
    "Travel": [
        "makemytrip", "goibibo", "cleartrip", "yatra", "airbnb", "oyo",
        "flight", "airline", "indigo", "air india",
        "spicejet", "vistara", "akasa", "ixigo", "easemytrip", "treebo",
        "fabhotel", "zostel", "klook", "agoda"
    ],
    "Insurance": [
        "lic", "hdfc life", "icici prudential", "bajaj allianz", "star health",
        "niva bupa", "care health", "digit insurance", "policy bazaar",
        "insurance", "mediclaim", "term plan"
    ],
    "Shopping": [
        "amazon", "flipkart", "myntra", "ajio", "nykaa", "meesho", "snapdeal",
        "reliance digital", "croma", "vijay sales", "decathlon", "ikea",
        "lifestyle", "westside", "max fashion", "h&m", "zara", "pantaloons",
        "shoppers stop", "big bazaar", "dmart", "zepto", "blinkit"
    ],
    "Medical": [
        "apollo", "fortis", "manipal", "columbia asia", "medplus", "netmeds",
        "1mg", "pharmeasy", "hospital", "clinic", "doctor", "pharmacy",
        "medical", "diagnostic", "lab test", "pathology", "dental", "optician",
        "narayana", "sakra", "cloudnine"
    ],
    "Grocery": [
        "bigbasket", "grofers", "instamart", "nature's basket",
        "reliance fresh", "more supermarket", "lulu", "heritage fresh",
        "grocery", "supermarket", "kirana", "nilgiris",
        "spencer", "easyday", "star bazaar"
    ],
    "Health & Wellness": [
        "cult.fit", "cult fit", "cure.fit", "curefit", "gold's gym",
        "anytime fitness", "gym", "fitness", "yoga", "spa", "salon",
        "haircut", "beauty", "wellness", "physio", "therapy",
        "meditation", "crossfit", "protein", "supplement"
    ],
    "Entertainment": [
        "netflix", "spotify", "prime video", "hotstar", "disney", "zee5",
        "sonyliv", "bookmyshow", "pvr", "inox", "cinema", "theatre",
        "youtube premium", "apple tv", "mxplayer"
    ],
    "Apps & Software": [
        "surfshark", "nordvpn", "adobe", "microsoft", "google one",
        "dropbox", "notion", "slack", "zoom", "github", "openai",
        "chatgpt", "canva", "figma", "apple.com/bill", "play.google"
    ],
    "Professional Services": [
        "ca ", "chartered accountant", "lawyer", "legal", "consultant",
        "freelance", "upwork", "fiverr", "notary"
    ],
    "Utility Bills": [
        "bescom", "bwssb", "airtel", "jio", "vodafone", "idea",
        "electricity", "water bill", "gas bill", "lpg", "indane", "hp gas",
        "bharat gas", "broadband", "internet", "postpaid", "dth", "tata sky",
        "dish tv", "sun direct", "mseb", "tneb", "kseb"
    ],
    "Credit Card Bills": [
        "credit card payment", "cc payment", "card payment", "amex payment",
        "hdfc cc", "icici cc", "axis cc", "kotak cc", "idfc cc",
        "bill payment cc", "credit card bill", "bbps",
        # HDFC's OLD statement layout labels an inbound bill payment
        # "TELE TRANSFER CREDIT" (its current layout says "BPPY CC PAYMENT",
        # already covered by "cc payment" above). Without this it falls to
        # "Others", and an uncategorized CREDIT is counted as a refund by
        # /api/summary — silently understating net spend by the whole bill.
        # The review queue can't catch that: it only surfaces debits, so
        # nothing would ever prompt a correction.
        "tele transfer",
    ],
    "Reversals & Refunds": [
        "refund", "reversal", "reversed", "return", "reimbursement", "rebate"
    ]
}

def categorize(description):
    desc_lower = description.lower()
    for category, keywords in CATEGORY_RULES.items():
        for kw in keywords:
            if kw in desc_lower:
                return category
    return "Others"

def is_cashback(description):
    return 'cashback' in description.lower()

# ── DB setup ──────────────────────────────────────────────────────────────────
def init_db():
    os.makedirs('data', exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Migrations for columns added after initial release. card_label is
    # deliberately NOT here (task 3.7): migration m006 permanently drops it
    # from transactions, and unlike the CREATE TABLE guards below, a bare
    # ALTER TABLE ADD COLUMN isn't naturally version-gated — it would
    # silently resurrect the column (all NULL) on every app start post-v6.
    # This bit us for real: caught via a live browser check after applying
    # v6, where /api/transactions came back with card_label always null.
    for migration in [
        "ALTER TABLE transactions ADD COLUMN bank_category TEXT",
        "ALTER TABLE transactions ADD COLUMN is_cashback INTEGER DEFAULT 0",
    ]:
        try:
            c.execute(migration)
        except sqlite3.OperationalError:
            pass

    # Milestones schema changed: old table had 'card' column, new uses 'card_label'.
    # Drop and recreate if the old schema is detected.
    try:
        cols = [row[1] for row in c.execute("PRAGMA table_info(milestones)").fetchall()]
        if 'card' in cols and 'card_label' not in cols:
            c.execute("DROP TABLE milestones")
    except sqlite3.OperationalError:
        pass

    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            type TEXT NOT NULL,
            category TEXT NOT NULL,
            bank_category TEXT,
            card TEXT NOT NULL,
            card_label TEXT,
            is_cashback INTEGER DEFAULT 0,
            raw_merchant TEXT,
            import_batch TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # import_batches/card_profiles are legacy pre-migration-v6 shape: migration
    # m006 DROPs both in favor of `statements` and `accounts` respectively,
    # which had made them fully redundant. Same reasoning as `rewards` below —
    # a dropped table must only be recreated pre-migration, or every app
    # restart on an already-migrated DB would silently resurrect it.
    if c.execute('PRAGMA user_version').fetchone()[0] < 6:
        c.execute('''
            CREATE TABLE IF NOT EXISTS import_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT UNIQUE NOT NULL,
                card TEXT NOT NULL,
                card_label TEXT,
                filename TEXT,
                txn_count INTEGER DEFAULT 0,
                imported_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS card_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bank TEXT NOT NULL,
                variant TEXT NOT NULL,
                last4 TEXT NOT NULL,
                label TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(bank, last4)
            )
        ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS milestones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_label TEXT NOT NULL,
            name TEXT NOT NULL,
            target_spend REAL NOT NULL,
            current_spend REAL DEFAULT 0,
            benefit TEXT,
            deadline TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # category_overrides is legacy pre-migration-v7 shape: migration m007 DROPs
    # it in favor of the merchants/aliases pipeline (ADR-009, fixes F9). Gated
    # like the other dropped tables so an app restart on a v7+ DB can't
    # resurrect it (the init_db-resurrects-a-dropped-table bug from task 3.7).
    if c.execute('PRAGMA user_version').fetchone()[0] < 7:
        c.execute('''
            CREATE TABLE IF NOT EXISTS category_overrides (
                merchant_pattern TEXT PRIMARY KEY,
                category TEXT NOT NULL
            )
        ''')
    # `rewards` is legacy pre-migration-v4 shape: migration m004 DROPs it in
    # favor of `reward_balances` (dated history, fixes F5). Unlike other
    # tables here (rebuilt-in-place by their migrations, so they always
    # exist and IF NOT EXISTS never fires again), a dropped table truly goes
    # away — so this must only run pre-v4, or every app restart on an
    # already-migrated DB would silently resurrect an empty, unused table.
    if c.execute('PRAGMA user_version').fetchone()[0] < 4:
        c.execute('''
            CREATE TABLE IF NOT EXISTS rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_label TEXT NOT NULL,
                label TEXT NOT NULL,
                value REAL NOT NULL,
                value_type TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'statement',
                import_batch TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(card_label)
            )
        ''')
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def rebuild_accruals(conn):
    """reward_accruals is a derived cache (ADR-008) — call before commit in
    every write path that changes its inputs (transactions, categories,
    merchant restamps). Full deterministic rebuild; also the manual stand-in
    for the schema's ON DELETE CASCADE, since this app never sets PRAGMA
    foreign_keys (see migrations/m008_reward_rules.py)."""
    from rewards.engine import rebuild_all
    rebuild_all(conn, commit=False)


def get_or_create_account(conn, card_label, institution):
    """Resolve a card_label to its accounts.id, creating the account on first
    sight (a brand-new card's first import). Only meaningful once migration v1
    has run — before that there is no accounts table, and the transactions
    INSERT doesn't reference it either (see upload()). Identifier falls back
    to the label's trailing -NNNN digits, mirroring migration m001."""
    row = conn.execute(
        "SELECT id FROM accounts WHERE kind='credit_card' AND name=?", (card_label,)).fetchone()
    if row:
        return row['id']
    tail = card_label.rsplit('-', 1)[-1]
    identifier = tail if tail.isdigit() and len(tail) == 4 else None
    cur = conn.execute(
        "INSERT INTO accounts (kind, name, institution, identifier) VALUES ('credit_card', ?, ?, ?)",
        (card_label, institution, identifier))
    return cur.lastrowid


def assign_category(conn, description, raw_description, bank_category, institution,
                    is_cashback, txn_type):
    """ADR-009 category assignment for a NEW transaction (task 4.2). Returns
    (category, category_source, merchant_id). Precedence, highest first:
      ① confirmed-merchant alias (longest normalized-substring match, ties newest)
      ② suggested-merchant alias (same match rule; created via the 4.3 review queue)
      ③ issuer_category_map on (institution, bank_category)
      ④ keyword rule / cashback auto-rule
      ⑤ 'Others' (keyword's own default — a first-class 'Uncategorized' arrives in 4.3)
    A manual pin (⓪) is applied by the recategorize endpoint, not here — a fresh
    import has no manual decision yet.
    """
    nd = normalize(raw_description or description)
    if nd:
        # confirmed before suggested; within each, longest pattern then newest id
        row = conn.execute('''
            SELECT m.id AS merchant_id, m.category, m.status
            FROM merchant_aliases ma JOIN merchants m ON m.id = ma.merchant_id
            WHERE INSTR(?, ma.pattern) > 0
            ORDER BY (m.status='confirmed') DESC, LENGTH(ma.pattern) DESC, ma.id DESC
            LIMIT 1
        ''', (nd,)).fetchone()
        if row:
            source = 'confirmed' if row['status'] == 'confirmed' else 'suggested'
            return row['category'], source, row['merchant_id']

    if bank_category:
        m = conn.execute(
            'SELECT category FROM issuer_category_map WHERE institution=? AND bank_category=?',
            (institution, bank_category)).fetchone()
        if m:
            return m['category'], 'bank', None

    if is_cashback and txn_type == 'credit':
        return 'Reversals & Refunds', 'keyword', None
    return categorize(description), 'keyword', None


def schema_version(conn):
    return conn.execute('PRAGMA user_version').fetchone()[0]

# ── CSV Parsers ───────────────────────────────────────────────────────────────
# F3 fix (task 1.5): the ambiguous d/m vs m/d pair must NOT default to US order
# for Indian banks — only Amex genuinely exports MM/DD/YYYY. Every other format
# is unaffected by the flag; only these two pairs swap priority.
_DATE_FORMATS_DMY_FIRST = [
    '%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d',
    '%d %b %Y', '%d-%b-%Y', '%d/%b/%Y', '%b %d, %Y',
    '%d %B %Y', '%Y/%m/%d', '%d.%m.%Y', '%d-%m-%y',
    '%d/%m/%y', '%m/%d/%Y', '%m-%d-%Y', '%b %d %Y'
]
_DATE_FORMATS_MDY_FIRST = [
    '%m/%d/%Y', '%m-%d-%Y', '%Y-%m-%d',
    '%d %b %Y', '%d-%b-%Y', '%d/%b/%Y', '%b %d, %Y',
    '%d %B %Y', '%Y/%m/%d', '%d.%m.%Y', '%d-%m-%y',
    '%d/%m/%y', '%d/%m/%Y', '%d-%m-%Y', '%b %d %Y'
]


def parse_date(date_str, mm_dd_first=False):
    """mm_dd_first=True tries MM/DD/YYYY-style formats before DD/MM — correct
    only for Amex. Every Indian bank (the default) must try DD/MM first, or a
    date like '05/03/2026' silently misreads as May 3 instead of March 5."""
    formats = _DATE_FORMATS_MDY_FIRST if mm_dd_first else _DATE_FORMATS_DMY_FIRST
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return None

def parse_amex(content):
    rows = []
    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        keys = list(row.keys())
        try:
            date_str = row.get('Date') or row.get('date') or row.get(keys[0])
            desc = row.get('Description') or row.get('description') or row.get(keys[1])
            amt_str = row.get('Amount') or row.get('amount') or row.get(keys[2])
            if not date_str or not amt_str:
                continue
            amt = float(str(amt_str).replace(',', '').replace('₹', '').strip())
            date = parse_date(date_str.strip(), mm_dd_first=True)
            if not date:
                continue
            txn_type = 'debit' if amt > 0 else 'credit'
            rows.append({'date': date, 'description': str(desc).strip(), 'amount': abs(amt), 'type': txn_type})
        except Exception:
            continue
    return rows

def _parse_bank_csv(content, header_tokens, date_keys, desc_keys, debit_keys, credit_keys,
                     mm_dd_first=False):
    lines = content.strip().split('\n')
    start = 0
    for i, line in enumerate(lines):
        if 'Date' in line and any(t in line for t in header_tokens):
            start = i
            break
    reader = csv.DictReader(io.StringIO('\n'.join(lines[start:])))
    rows = []
    for row in reader:
        try:
            date_str = next((row.get(k) for k in date_keys if row.get(k)), None)
            desc = next((row.get(k) for k in desc_keys if row.get(k)), None)
            debit_raw = next((row.get(k) for k in debit_keys if row.get(k)), '0')
            credit_raw = next((row.get(k) for k in credit_keys if row.get(k)), '0')
            if not date_str or str(date_str).strip() in ('', 'nan') or not desc:
                continue
            date = parse_date(str(date_str).strip(), mm_dd_first=mm_dd_first)
            if not date:
                continue
            d = float(str(debit_raw).replace(',', '').strip() or 0)
            c = float(str(credit_raw).replace(',', '').strip() or 0)
            if d > 0:
                rows.append({'date': date, 'description': str(desc).strip(), 'amount': d, 'type': 'debit'})
            if c > 0:
                rows.append({'date': date, 'description': str(desc).strip(), 'amount': c, 'type': 'credit'})
        except Exception:
            continue
    return rows

def parse_idfc(content):
    return _parse_bank_csv(content,
        ['Remarks', 'Narration', 'Description'],
        ['Transaction Date', 'Date', 'Value Date'],
        ['Transaction Remarks', 'Description', 'Narration'],
        ['Debit', 'Withdrawal'], ['Credit', 'Deposit'],
        mm_dd_first=False)

def parse_hdfc(content):
    return _parse_bank_csv(content,
        ['Narration', 'Description'],
        ['Date', 'Value Date'],
        ['Narration', 'Description', 'Transaction Remarks'],
        ['Withdrawal Amt.', 'Debit Amount', 'Debit'],
        ['Deposit Amt.', 'Credit Amount', 'Credit'],
        mm_dd_first=False)

def parse_axis(content):
    return _parse_bank_csv(content,
        ['Particulars', 'Description', 'Narration'],
        ['Tran Date', 'Date', 'Transaction Date'],
        ['Particulars', 'Description', 'Narration'],
        ['Debit', 'Dr Amount'], ['Credit', 'Cr Amount'],
        mm_dd_first=False)

def parse_icici(content):
    return _parse_bank_csv(content,
        ['Description', 'Particulars', 'Remarks'],
        ['Transaction Date', 'Value Date', 'Date', 'Txn Date'],
        ['Transaction Remarks', 'Description', 'Particulars', 'Narration'],
        ['Debit', 'Withdrawal Amount (INR )', 'Withdrawal Amount'],
        ['Credit', 'Deposit Amount (INR )', 'Deposit Amount'],
        mm_dd_first=False)

def parse_kotak(content):
    return _parse_bank_csv(content,
        ['Description', 'Narration', 'Particulars'],
        ['Date', 'Transaction Date', 'Txn Date'],
        ['Description', 'Narration', 'Particulars'],
        ['Debit', 'Dr'], ['Credit', 'Cr'],
        mm_dd_first=False)

PARSERS = {
    'amex': parse_amex, 'idfc': parse_idfc, 'hdfc': parse_hdfc,
    'axis': parse_axis, 'icici': parse_icici, 'kotak': parse_kotak,
}

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/')
@app.route('/<path:spa_path>')
def spa(spa_path=''):
    """Serve the built React app; unknown paths fall back to index.html so
    client-side routes (/kit, /transactions, ...) survive a refresh.
    Registered routes (/api/*) are more specific and win; the guard below
    keeps unknown API paths as JSON-shaped 404s, never HTML. static_folder=None
    means there's no separate Flask static route to shadow anymore (task 2.5)."""
    if spa_path.startswith('api/'):
        abort(404)
    if spa_path and os.path.isfile(os.path.join(FRONTEND_DIST, spa_path)):
        return send_from_directory(FRONTEND_DIST, spa_path)
    if os.path.isfile(os.path.join(FRONTEND_DIST, 'index.html')):
        return send_from_directory(FRONTEND_DIST, 'index.html')
    return (
        '<h1>FinTrack</h1><p>Frontend build not found. Run <code>./build.ps1</code>, then reload.</p>',
        503,
    )

@app.route('/api/categories')
def get_categories():
    return jsonify(CATEGORIES)

# ── Card profiles (task 3.7: backed by `accounts` now, card_profiles is
# gone — bank/variant/last4/label is a display vocabulary derived from
# accounts.institution/name/identifier, not a separately stored shape) ────────
def _derive_variant(name, institution, identifier):
    """accounts has no separate 'variant' column — it's whatever's left of
    name after stripping the institution prefix and identifier suffix that
    are already stored (e.g. 'HDFC-Tata Neu Infinity-1234' -> 'Tata Neu
    Infinity'). Always derivable because the label was built the same way."""
    v = name
    if institution and v.upper().startswith(institution.upper() + '-'):
        v = v[len(institution) + 1:]
    if identifier and v.endswith('-' + identifier):
        v = v[:-(len(identifier) + 1)]
    return v

@app.route('/api/card_profiles', methods=['GET'])
def get_card_profiles():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, institution, identifier, created_at FROM accounts "
        "WHERE kind='credit_card' ORDER BY institution, name"
    ).fetchall()
    conn.close()
    return jsonify([{
        'id': r['id'], 'bank': (r['institution'] or '').lower(),
        'variant': _derive_variant(r['name'], r['institution'], r['identifier']),
        'last4': r['identifier'], 'label': r['name'], 'created_at': r['created_at'],
    } for r in rows])

@app.route('/api/card_profiles', methods=['POST'])
def add_card_profile():
    data = request.json
    bank = data.get('bank', '').strip().lower()
    variant = data.get('variant', '').strip()
    last4 = data.get('last4', '').strip()
    if not bank or not variant or not last4:
        return jsonify({'error': 'bank, variant, and last4 are required'}), 400
    label = f"{bank.upper()}-{variant}-{last4}"
    conn = get_db()
    try:
        # Same (bank, last4) as an existing card = editing it (e.g. a typo'd
        # variant) — rename in place rather than creating a duplicate account.
        # Safe: everything else references the account by id, never by name.
        existing = conn.execute(
            "SELECT id FROM accounts WHERE kind='credit_card' AND institution=? AND identifier=?",
            (bank.upper(), last4)
        ).fetchone()
        if existing:
            conn.execute('UPDATE accounts SET name=? WHERE id=?', (label, existing['id']))
        else:
            conn.execute(
                "INSERT INTO accounts (kind, name, institution, identifier) VALUES ('credit_card', ?, ?, ?)",
                (label, bank.upper(), last4)
            )
        conn.commit()
    except Exception as e:
        return jsonify({'error': str(e)}), 400
    finally:
        conn.close()
    return jsonify({'success': True, 'label': label})

@app.route('/api/card_profiles/<int:pid>', methods=['DELETE'])
def delete_card_profile(pid):
    conn = get_db()
    txn_count = conn.execute(
        'SELECT COUNT(*) FROM transactions WHERE account_id=?', (pid,)).fetchone()[0]
    if txn_count:
        conn.close()
        return jsonify({
            'error': f'This card has {txn_count} transaction(s) — delete its statements first.',
        }), 400
    conn.execute('DELETE FROM accounts WHERE id=?', (pid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ── Upload ────────────────────────────────────────────────────────────────────
def _import_statement(file_bytes, original_filename, card, card_label,
                      password='', force=False):
    """Import ONE statement. Returns (payload_dict, http_status).

    The whole import pipeline — parse, dedup/overlap gating, file persistence,
    transaction insert, reward balance, accrual rebuild — lives here rather
    than in the route so `/api/upload` and `/api/upload_bulk` cannot drift
    apart. A bulk path that reimplemented any of this would be a second,
    untested way to write to `transactions`; gating in particular is the F4
    fix and must be identical for one file or twenty.

    Returns a plain dict (not a Response) so the bulk caller can collect
    per-file outcomes instead of having a single failure end the batch.
    """
    is_pdf = (original_filename or '').lower().endswith('.pdf')
    file_sha256 = hashlib.sha256(file_bytes).hexdigest()

    if is_pdf:
        if card not in PDF_PARSERS:
            return {'error': f'PDF import not supported for: {card}'}, 400
        try:
            with pdfplumber.open(_io_module.BytesIO(file_bytes), password=password) as pdf:
                full_text = '\n'.join(p.extract_text() or '' for p in pdf.pages)
        except Exception as e:
            err = str(e).lower()
            if 'password' in err or 'decrypt' in err or 'encrypt' in err:
                return {'error': 'Incorrect password or PDF could not be unlocked.'}, 400
            return {'error': f'Could not read PDF: {str(e)}'}, 400
        try:
            result = PDF_PARSERS[card](full_text)
            transactions = result['transactions']
            rewards_data = result.get('rewards')
            skipped_candidates = result.get('skipped_candidates')
            period = result.get('period')
            totals = result.get('totals')
        except Exception as e:
            return {'error': f'Parse error: {str(e)}'}, 400
    else:
        if card not in PARSERS:
            return {'error': f'Unknown card: {card}'}, 400
        try:
            content = file_bytes.decode('utf-8', errors='replace')
        except Exception as e:
            return {'error': f'Could not read file: {str(e)}'}, 400
        try:
            transactions = PARSERS[card](content)
            rewards_data = None
            skipped_candidates = None
            period = None       # CSVs carry no printed cycle — derived below from txn dates
            totals = None       # CSVs carry no printed totals to reconcile against
        except Exception as e:
            return {'error': f'Parse error: {str(e)}'}, 400

    if not transactions:
        return {'error': 'No transactions found. Check file format, card selection, or password.'}, 400

    # Period for gating (task 3.4): use the parser's printed cycle when it
    # found one; fall back to the transaction dates' own span otherwise (a
    # bank whose layout defeated period extraction still gets gated, rather
    # than silently skipping the dedup check).
    if not period:
        dates = sorted(t['date'] for t in transactions)
        period = {'start': dates[0], 'end': dates[-1]}

    conn = get_db()

    # ── Dedup gating (F4, task 3.4) ──
    existing_by_hash = conn.execute(
        'SELECT id FROM statements WHERE file_sha256=?', (file_sha256,)).fetchone()
    if existing_by_hash:
        conn.close()
        return {
            'error': f'This exact file was already imported (statement #{existing_by_hash["id"]}).',
        }, 400

    account_id = get_or_create_account(conn, card_label, card.upper())
    if not force:
        overlap = conn.execute('''
            SELECT id, period_start, period_end, source_path FROM statements
            WHERE account_id=? AND NOT (period_end < ? OR period_start > ?)
        ''', (account_id, period['start'], period['end'])).fetchone()
        if overlap:
            conn.rollback()
            conn.close()
            existing_file = os.path.basename(overlap['source_path']) if overlap['source_path'] else 'an earlier import'
            return {
                'error': (f"This statement's period ({period['start']} to {period['end']}) overlaps "
                          f"an existing import (statement #{overlap['id']}, {overlap['period_start']} to "
                          f"{overlap['period_end']}, from {existing_file}). Import anyway?"),
                'overlap': True,
            }, 400

    # Reconciliation (task 2.3): compare parsed sums against whatever printed
    # totals the parser found (task 1.4). None when the bank prints nothing
    # checkable — an honest "we can't tell" rather than a false pass/fail.
    reconciled = None
    if totals:
        checks = []
        if totals.get('debits') is not None:
            parsed_debits = round(sum(t['amount'] for t in transactions if t['type'] == 'debit'), 2)
            checks.append(abs(parsed_debits - totals['debits']) < 0.01)
        if totals.get('credits') is not None:
            parsed_credits = round(sum(t['amount'] for t in transactions if t['type'] == 'credit'), 2)
            checks.append(abs(parsed_credits - totals['credits']) < 0.01)
        if checks:
            reconciled = all(checks)

    # Persist the file (task 3.4, F1's go-forward fix): every successfully
    # gated import is copied to statements/<card>/ — no statement is ever
    # parse-and-discarded again. Filesystem-unsafe chars in the label are
    # replaced defensively (card labels are owner-entered via the accounts
    # registry, not attacker input, but this is cheap insurance).
    safe_label = re.sub(r'[<>:"/\\|?*]', '_', card_label)
    ext = 'pdf' if is_pdf else 'csv'
    statements_dir = os.path.join(STATEMENTS_DIR, card)
    os.makedirs(statements_dir, exist_ok=True)
    source_path = os.path.join(statements_dir, f"{safe_label}_{period['end']}.{ext}")
    with open(source_path, 'wb') as f:
        f.write(file_bytes)

    institution = card.upper()
    stmt_debits_paise = int(round(totals['debits'] * 100)) if totals and totals.get('debits') is not None else None
    stmt_credits_paise = int(round(totals['credits'] * 100)) if totals and totals.get('credits') is not None else None
    cur = conn.execute(
        '''INSERT INTO statements
           (account_id, period_start, period_end, format, source_path, file_sha256,
            txn_count, stmt_debits_paise, stmt_credits_paise, original_filename)
           VALUES (?,?,?,?,?,?,?,?,?,?)''',
        (account_id, period['start'], period['end'], ext, source_path, file_sha256,
         len(transactions), stmt_debits_paise, stmt_credits_paise, original_filename or None)
    )
    statement_id = cur.lastrowid

    for txn in transactions:
        desc = txn['description']
        bank_category = txn.get('bank_category')
        cashback = 1 if is_cashback(desc) else 0

        # ADR-009 precedence (task 4.2): confirmed/suggested merchant alias ->
        # issuer map -> keyword/cashback. Stamps category_source + merchant_id
        # so "fix once, fixed forever" works and the trust meter can weigh it.
        cat, source, merchant_id = assign_category(
            conn, desc, desc, bank_category, institution, cashback, txn['type'])

        conn.execute(
            '''INSERT INTO transactions
               (account_id, statement_id, date, description, amount_paise, type, category,
                bank_category, is_cashback, raw_description, merchant_id, category_source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
            # Parsers speak rupee floats (their golden corpus pins that);
            # the paise conversion happens exactly here, at the DB boundary (v2).
            (account_id, statement_id, txn['date'], desc, int(round(txn['amount'] * 100)), txn['type'],
             cat, bank_category, cashback, desc, merchant_id, source)
        )
    txn_count = len(transactions)

    # Save a dated reward balance keyed to the statement's own period-end
    # (task 3.5, fixes F5): "current" is whichever row has the latest as_of,
    # not whichever was inserted last — so importing an older statement after
    # a newer one no longer regresses the displayed balance. Paise conversion
    # happens here, at this same write boundary, matching v2/v3's pattern.
    if rewards_data:
        legacy_type = rewards_data['value_type']
        if legacy_type == 'points':
            value_minor, value_type = int(round(rewards_data['value'])), 'points'
        elif legacy_type == 'cashback_inr':
            value_minor, value_type = int(round(rewards_data['value'] * 100)), 'cashback_paise'
        elif legacy_type == 'balance_inr':
            value_minor, value_type = int(round(rewards_data['value'] * 100)), 'balance_paise'
        else:
            raise ValueError(f'unknown reward value_type from parser: {legacy_type!r}')
        conn.execute(
            '''INSERT INTO reward_balances (account_id, as_of, label, value_minor, value_type, source, statement_id)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(account_id, as_of) DO UPDATE SET
                 label=excluded.label, value_minor=excluded.value_minor,
                 value_type=excluded.value_type, source='statement',
                 statement_id=excluded.statement_id''',
            (account_id, period['end'], rewards_data['label'], value_minor, value_type,
             'statement', statement_id)
        )

    rebuild_accruals(conn)
    conn.commit()
    conn.close()
    return {'success': True, 'imported': txn_count, 'card': card_label,
            'skipped_candidates': skipped_candidates,
            'period': period, 'totals': totals, 'reconciled': reconciled}, 200


@app.route('/api/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    file = request.files['file']
    card = request.form.get('card', '').strip().lower()
    payload, status = _import_statement(
        file_bytes=file.read(),
        original_filename=file.filename,
        card=card,
        card_label=request.form.get('card_label', '').strip() or card.upper(),
        password=request.form.get('password', ''),
        force=request.form.get('force', '').strip().lower() == 'true',
    )
    return jsonify(payload), status


@app.route('/api/upload_bulk', methods=['POST'])
def upload_bulk():
    """Import many statements for ONE card in a single request.

    Per-card by design, not per-request-free-for-all: `card` selects the
    parser and `password` unlocks the PDFs, and both are properties of the
    issuer, not the file. Mixing banks in one batch would mean guessing the
    parser per file, which is exactly the "don't guess at bank behavior"
    trap the corpus work kept hitting.

    Every file goes through `_import_statement` unchanged, so hash-dedup and
    period-overlap gating behave exactly as they do for a single upload. One
    file failing does NOT abort the batch — each result is reported
    individually, because the common case (a year of monthly statements
    where two overlap) should still import the other ten.

    Files are processed in filename order so the outcome of a batch doesn't
    depend on the browser's arbitrary ordering of a multi-select: with
    overlap gating, WHICH of two overlapping statements lands first decides
    which one is rejected, and that should at least be reproducible.
    """
    files = request.files.getlist('files')
    if not files:
        return jsonify({'error': 'No files uploaded'}), 400
    card = request.form.get('card', '').strip().lower()
    card_label = request.form.get('card_label', '').strip() or card.upper()
    password = request.form.get('password', '')
    force = request.form.get('force', '').strip().lower() == 'true'

    results = []
    for f in sorted(files, key=lambda x: (x.filename or '').lower()):
        payload, status = _import_statement(
            file_bytes=f.read(), original_filename=f.filename, card=card,
            card_label=card_label, password=password, force=force,
        )
        results.append({
            'filename': f.filename,
            'ok': status == 200,
            **({'imported': payload.get('imported'),
                'period': payload.get('period'),
                'reconciled': payload.get('reconciled')}
               if status == 200 else
               {'error': payload.get('error'), 'overlap': payload.get('overlap', False)}),
        })

    imported_total = sum(r.get('imported') or 0 for r in results if r['ok'])
    return jsonify({
        'success': True,          # the BATCH ran; per-file outcomes are in results
        'card': card_label,
        'files': len(results),
        'succeeded': sum(1 for r in results if r['ok']),
        'failed': sum(1 for r in results if not r['ok']),
        'imported': imported_total,
        'results': results,
    }), 200

# ── Statements (import history; replaces import_batches, task 3.7) ───────────
@app.route('/api/statements', methods=['GET'])
def get_statements():
    conn = get_db()
    rows = conn.execute('''
        SELECT s.id, a.name AS card_label, s.original_filename AS filename,
               s.format, s.period_start, s.period_end, s.txn_count, s.imported_at
        FROM statements s
        JOIN accounts a ON a.id = s.account_id
        ORDER BY s.imported_at DESC
    ''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/statements/all', methods=['DELETE'])
def delete_all_statements():
    """Wipe every imported statement and its transactions.

    Guarded by an explicit `confirm=DELETE ALL` body/query token rather than
    just the HTTP verb: this is the single most destructive button in the app,
    the route sits next to `/api/statements/<id>`, and a stray call with no
    id must never be able to mean "all". Registered BEFORE the <int:sid> rule
    — Flask would otherwise 404 on 'all' failing the int converter.

    Reward BALANCES survive deliberately. They're dated observations of what
    the bank said a card was worth on a given date (v4/F5), not derived from
    the transactions being deleted, so re-importing the same statements
    reproduces them by upsert rather than duplicating. Accruals ARE rebuilt,
    because those are computed from transactions.
    """
    token = (request.get_json(silent=True) or {}).get('confirm') or request.args.get('confirm')
    if token != 'DELETE ALL':
        return jsonify({'error': "Refusing to delete: send confirm='DELETE ALL'."}), 400

    conn = get_db()
    n_stmts = conn.execute('SELECT COUNT(*) FROM statements').fetchone()[0]
    n_txns = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
    if n_stmts == 0 and n_txns == 0:
        conn.close()
        return jsonify({'success': True, 'statements_deleted': 0, 'transactions_deleted': 0,
                        'backup': None})

    conn.close()
    # Destructive bulk operation -> snapshot first (spec §4 backup rule, task 3.1).
    # Taken only once there's something to lose, so an accidental double-click
    # can't push a real backup out of the newest-20 retention window.
    backup_path = backup_db(DB_PATH, 'pre-delete-all-statements')

    conn = get_db()
    # Manual cascade, same as the single-statement delete below: this app never
    # sets PRAGMA foreign_keys=ON, so ADR-003's ON DELETE CASCADE is app-honored.
    # Transactions are cleared wholesale rather than by statement_id — a row
    # whose statement_id went NULL through some earlier path would otherwise
    # survive as an orphan that no UI lists but every total still counts.
    conn.execute('DELETE FROM reward_accruals')
    conn.execute('UPDATE reward_balances SET statement_id=NULL')
    conn.execute('DELETE FROM transactions')
    conn.execute('DELETE FROM statements')
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'statements_deleted': n_stmts,
                    'transactions_deleted': n_txns,
                    'backup': os.path.basename(backup_path) if backup_path else None})


@app.route('/api/statements/<int:sid>', methods=['DELETE'])
def delete_statement(sid):
    # Destructive bulk operation -> snapshot first (spec §4 backup rule, task 3.1)
    backup_db(DB_PATH, 'pre-statement-delete')
    conn = get_db()
    # No PRAGMA foreign_keys enforcement in this app, so the ADR-003 "ON
    # DELETE CASCADE" on statement_id references is honored manually here.
    conn.execute('DELETE FROM reward_balances WHERE statement_id=?', (sid,))
    conn.execute('DELETE FROM transactions WHERE statement_id=?', (sid,))
    conn.execute('DELETE FROM statements WHERE id=?', (sid,))
    rebuild_accruals(conn)
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ── Dedup cleanup (task 3.7, F10/F4-history) ──────────────────────────────────
# One-time historical cleanup surface: lists CANDIDATES only. The app never
# auto-deletes — the owner reviews each pair/group and decides, using
# DELETE /api/statements/<id> (for an overlapping-statement pair) or
# DELETE /api/transactions/<id> (for one duplicate row within a group).
@app.route('/api/dedup_candidates')
def get_dedup_candidates():
    conn = get_db()
    overlapping_statements = conn.execute('''
        SELECT a.name AS card_label,
               s1.id AS id1, s1.period_start AS start1, s1.period_end AS end1, s1.txn_count AS n1,
               s2.id AS id2, s2.period_start AS start2, s2.period_end AS end2, s2.txn_count AS n2
        FROM statements s1
        JOIN statements s2 ON s2.account_id = s1.account_id AND s2.id > s1.id
        JOIN accounts a ON a.id = s1.account_id
        WHERE NOT (s1.period_end < s2.period_start OR s1.period_start > s2.period_end)
        ORDER BY a.name
    ''').fetchall()

    # Same account + date + description + amount + type, more than once —
    # the audit's "same-tuple" duplicate signature (re-imports of an
    # overlapping period double-count exactly these rows).
    dupe_groups_raw = conn.execute('''
        SELECT account_id, date, description, amount_paise, type, COUNT(*) as n
        FROM transactions
        GROUP BY account_id, date, description, amount_paise, type
        HAVING COUNT(*) > 1
    ''').fetchall()
    duplicate_groups = []
    for g in dupe_groups_raw:
        txns = conn.execute('''
            SELECT t.id, t.date, t.description, t.amount_paise, t.type, t.category,
                   a.name AS card_label, t.statement_id
            FROM transactions t JOIN accounts a ON a.id = t.account_id
            WHERE t.account_id=? AND t.date=? AND t.description=? AND t.amount_paise=? AND t.type=?
            ORDER BY t.id
        ''', (g['account_id'], g['date'], g['description'], g['amount_paise'], g['type'])).fetchall()
        duplicate_groups.append({'count': g['n'], 'transactions': [dict(t) for t in txns]})
    conn.close()

    return jsonify({
        'overlapping_statements': [dict(r) for r in overlapping_statements],
        'duplicate_groups': duplicate_groups,
    })

# ── Transactions ──────────────────────────────────────────────────────────────
@app.route('/api/transactions')
def get_transactions():
    conn = get_db()
    filters, params = [], []
    if request.args.get('card'):
        filters.append('a.name = ?')
        params.append(request.args.get('card'))
    if request.args.get('category'):
        filters.append('t.category = ?')
        params.append(request.args.get('category'))
    if request.args.get('type'):
        filters.append('t.type = ?')
        params.append(request.args.get('type'))
    if request.args.get('from_date'):
        filters.append('t.date >= ?')
        params.append(request.args.get('from_date'))
    if request.args.get('to_date'):
        filters.append('t.date <= ?')
        params.append(request.args.get('to_date'))
    if request.args.get('search'):
        filters.append('t.description LIKE ?')
        params.append(f"%{request.args.get('search')}%")

    where = ('WHERE ' + ' AND '.join(filters)) if filters else ''
    sort_map = {
        'date_desc': 't.date DESC', 'date_asc': 't.date ASC',
        'amount_desc': 't.amount_paise DESC', 'amount_asc': 't.amount_paise ASC'
    }
    order = sort_map.get(request.args.get('sort', 'date_desc'), 't.date DESC')
    # limit/offset are additive (task 2.1): omitting both preserves the original
    # bare-LIMIT-1000 behavior exactly, so existing callers are unaffected.
    limit = request.args.get('limit', 1000, type=int)
    offset = request.args.get('offset', 0, type=int)
    from_clause = 'FROM transactions t JOIN accounts a ON a.id = t.account_id'
    total = conn.execute(f'SELECT COUNT(*) {from_clause} {where}', params).fetchone()[0]
    rows = conn.execute(
        f'SELECT t.*, a.name AS card_label {from_clause} {where} ORDER BY {order} LIMIT ? OFFSET ?',
        params + [limit, offset]
    ).fetchall()
    conn.close()
    resp = jsonify([dict(r) for r in rows])
    resp.headers['X-Total-Count'] = str(total)
    return resp

@app.route('/api/transactions/<int:tid>', methods=['DELETE'])
def delete_transaction(tid):
    """Single-row delete — the lever the task 3.7 duplicate-cleanup screen
    uses to remove one confirmed duplicate at a time (see /api/dedup_candidates)."""
    backup_db(DB_PATH, 'pre-transaction-delete')
    conn = get_db()
    conn.execute('DELETE FROM transactions WHERE id=?', (tid,))
    rebuild_accruals(conn)
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ── Summary ───────────────────────────────────────────────────────────────────
# All money in this response is INTEGER PAISE (v2 migration, ADR-005). Integer
# sums are exact — the float round(..., 2) calls this route used to need are
# gone. The frontend divides by 100 once, at its API-client boundary.
@app.route('/api/summary')
def get_summary():
    conn = get_db()
    from_date = request.args.get('from_date', '2000-01-01')
    to_date = request.args.get('to_date', '2099-12-31')
    card = request.args.get('card', '')

    # card_label was a denormalized column on transactions pre-3.7; it's now
    # accounts.name, so every filtered/grouped query below joins accounts.
    from_clause = 'FROM transactions JOIN accounts a ON a.id = transactions.account_id'
    cf = "AND a.name = ?" if card else ""
    p = [from_date, to_date] + ([card] if card else [])

    # Gross debits (excluding cashback entries which are already credits)
    gross_debits = conn.execute(
        f"""SELECT COALESCE(SUM(amount_paise),0) {from_clause}
            WHERE type='debit' AND is_cashback=0
            AND date BETWEEN ? AND ? {cf}""", p
    ).fetchone()[0]

    # Non-CC-bill credits (refunds) — these reduce spend
    refund_credits = conn.execute(
        f"""SELECT COALESCE(SUM(amount_paise),0) {from_clause}
            WHERE type='credit' AND is_cashback=0
            AND category != 'Credit Card Bills'
            AND date BETWEEN ? AND ? {cf}""", p
    ).fetchone()[0]

    # Cashback total (informational only)
    cashback_total = conn.execute(
        f"""SELECT COALESCE(SUM(amount_paise),0), COUNT(*) {from_clause}
            WHERE is_cashback=1 AND date BETWEEN ? AND ? {cf}""", p
    ).fetchone()

    net_spend = max(0, gross_debits - refund_credits)

    # Trust meter (task 4.3, ADR-009): paise-weighted share of gross debit spend
    # sitting on a firm footing — category_source 'confirmed' (a merchant rule)
    # OR 'manual' (an explicit owner pin). Both are owner-verified; 'keyword'/
    # 'bank'/'none' are guesses and don't count. Moves the moment you confirm a
    # merchant in the review queue. (ADR names 'confirmed'; manual is included
    # because an explicit pin is at least as trustworthy — the honest reading of
    # "% of spend the owner can stand behind".)
    trusted_spend = conn.execute(
        f"""SELECT COALESCE(SUM(amount_paise),0) {from_clause}
            WHERE type='debit' AND is_cashback=0
            AND category_source IN ('confirmed','manual')
            AND date BETWEEN ? AND ? {cf}""", p
    ).fetchone()[0]
    trust = (trusted_spend / gross_debits) if gross_debits else 0.0

    # Per-category: net = debits - credits, floor at 0
    by_cat_raw = conn.execute(
        f"""SELECT category,
               COALESCE(SUM(CASE WHEN type='debit'  AND is_cashback=0 THEN amount_paise ELSE 0 END),0) as debits,
               COALESCE(SUM(CASE WHEN type='credit' AND is_cashback=0
                                  AND category != 'Credit Card Bills' THEN amount_paise ELSE 0 END),0) as credits,
               COUNT(CASE WHEN type='debit' AND is_cashback=0 THEN 1 END) as count
            {from_clause}
            WHERE is_cashback=0 AND date BETWEEN ? AND ? {cf}
            GROUP BY category""", p
    ).fetchall()

    by_cat = []
    for r in by_cat_raw:
        net = max(0, r['debits'] - r['credits'])
        if net > 0 or r['count'] > 0:
            by_cat.append({
                'category': r['category'],
                'total': net,
                'gross_debits': r['debits'],
                'refunds': r['credits'],
                'count': r['count']
            })
    by_cat.sort(key=lambda x: x['total'], reverse=True)

    # Per card (a.name, formerly the denormalized card_label column)
    by_card = conn.execute(
        f"""SELECT a.name AS card_label,
               COALESCE(SUM(CASE WHEN type='debit' AND is_cashback=0 THEN amount_paise ELSE 0 END),0)
               - COALESCE(SUM(CASE WHEN type='credit' AND is_cashback=0
                                    AND category!='Credit Card Bills' THEN amount_paise ELSE 0 END),0)
               as total,
               COUNT(CASE WHEN type='debit' AND is_cashback=0 THEN 1 END) as count
            {from_clause}
            WHERE is_cashback=0 AND date BETWEEN ? AND ? {cf}
            GROUP BY a.name ORDER BY total DESC""", p
    ).fetchall()

    # Monthly trend (net per month)
    monthly_raw = conn.execute(
        f"""SELECT strftime('%Y-%m', date) as month,
               COALESCE(SUM(CASE WHEN type='debit'  AND is_cashback=0 THEN amount_paise ELSE 0 END),0) as debits,
               COALESCE(SUM(CASE WHEN type='credit' AND is_cashback=0
                                  AND category!='Credit Card Bills' THEN amount_paise ELSE 0 END),0) as credits
            {from_clause}
            WHERE is_cashback=0 AND date BETWEEN ? AND ? {cf}
            GROUP BY month ORDER BY month""", p
    ).fetchall()
    monthly = [{'month': r['month'], 'total': max(0, r['debits'] - r['credits'])}
               for r in monthly_raw]

    # Month x category net (additive field for the new dashboard's stacked
    # composition chart). Deliberately NOT floored at zero per category:
    # a refund-heavy category may net negative in a month, and leaving it
    # signed is what makes per-month column sums equal the monthly trend
    # exactly. Display clamping is the frontend's concern.
    monthly_by_cat_raw = conn.execute(
        f"""SELECT strftime('%Y-%m', date) as month, category,
               COALESCE(SUM(CASE WHEN type='debit'  AND is_cashback=0 THEN amount_paise ELSE 0 END),0) as debits,
               COALESCE(SUM(CASE WHEN type='credit' AND is_cashback=0
                                  AND category!='Credit Card Bills' THEN amount_paise ELSE 0 END),0) as credits
            {from_clause}
            WHERE is_cashback=0 AND date BETWEEN ? AND ? {cf}
            GROUP BY month, category ORDER BY month, category""", p
    ).fetchall()
    monthly_by_category = [
        {'month': r['month'], 'category': r['category'],
         'total': r['debits'] - r['credits']}
        for r in monthly_by_cat_raw
        if r['debits'] != 0 or r['credits'] != 0
    ]

    # Top merchants (debits only, no cashback). Canonical now (task 4.3): rows
    # sharing a merchant collapse to its canonical_name with a confirmed badge —
    # no more gateway-costume duplicates (Razorpay*Swiggy vs SwiggyBANGALORE).
    # Rows without a merchant link fall back to their normalized description, so
    # even un-confirmed merchants dedup across statement-noise variants. The
    # normalize() step is Python-only, so this aggregation runs in Python.
    merch_rows = conn.execute(
        f"""SELECT transactions.merchant_id AS merchant_id, transactions.description AS description,
                   transactions.raw_description AS raw_description,
                   transactions.amount_paise AS amount_paise, a.name AS card_label,
                   m.canonical_name AS canonical_name, m.status AS status
            {from_clause} LEFT JOIN merchants m ON m.id = transactions.merchant_id
            WHERE transactions.type='debit' AND transactions.is_cashback=0
            AND transactions.date BETWEEN ? AND ? {cf}""", p
    ).fetchall()
    groups = {}
    # Payment-channel lens: UPI-on-credit-card vs card auth. Folded into the
    # merchant pass rather than given its own query — these are the same debit
    # rows under the same filters, so computing them together makes it
    # impossible for the two aggregates to disagree about what is in scope.
    # classify_channel() is Python-only (it reuses normalize.py's token peel),
    # which is the same reason top_merchants is grouped here and not in SQL.
    by_channel = {'upi': {'count': 0, 'total': 0}, 'card': {'count': 0, 'total': 0}}
    card_channel = {}
    for r in merch_rows:
        ch = classify_channel(r['raw_description'] or r['description'])
        by_channel[ch]['count'] += 1
        by_channel[ch]['total'] += r['amount_paise']
        cc = card_channel.setdefault(
            r['card_label'], {'gross_debits': 0, 'upi_count': 0, 'upi_total': 0})
        cc['gross_debits'] += r['amount_paise']
        if ch == 'upi':
            cc['upi_count'] += 1
            cc['upi_total'] += r['amount_paise']

        if r['merchant_id']:
            key = ('m', r['merchant_id'])
            name, confirmed = r['canonical_name'], (r['status'] == 'confirmed')
        else:
            nk = normalize(r['description']) or r['description'].lower()
            key = ('n', nk)
            name, confirmed = r['description'], False
        g = groups.setdefault(key, {'name': name, 'total': 0, 'count': 0, 'confirmed': confirmed})
        g['total'] += r['amount_paise']
        g['count'] += 1
    top_merchants = sorted(groups.values(), key=lambda x: x['total'], reverse=True)[:20]

    # by_card.total stays NET (debits − refunds); the channel fields below are
    # DEBIT-ONLY, because a refund rode no payment rail. gross_debits ships so
    # the client can show an honest average ticket (gross/count) rather than
    # net/count, which would understate the size of a typical charge. Cards
    # whose only rows are credits zero-fill, so the shape is never ragged.
    by_card_rows = [
        {**dict(r), **card_channel.get(
            r['card_label'], {'gross_debits': 0, 'upi_count': 0, 'upi_total': 0})}
        for r in by_card
    ]

    category_sum = sum(c['total'] for c in by_cat)
    conn.close()
    return jsonify({
        'total_spend': net_spend,
        'category_sum': category_sum,
        'gross_debits': gross_debits,
        'refund_credits': refund_credits,
        'cashback_total': cashback_total[0],
        'cashback_count': cashback_total[1],
        'trust': trust,
        'trusted_spend': trusted_spend,
        'by_category': by_cat,
        'by_card': by_card_rows,
        'by_channel': by_channel,
        'monthly_trend': monthly,
        'monthly_by_category': monthly_by_category,
        'top_merchants': top_merchants,
    })

# ── Recategorize ──────────────────────────────────────────────────────────────
@app.route('/api/recategorize', methods=['POST'])
def recategorize():
    """Recategorize one transaction. Reworked for the ADR-009 pipeline (task
    4.2): the target row becomes a manual pin (category_source='manual', the
    highest precedence — it survives every future recompute). With learn+merchant,
    the merchant field is confirmed: a confirmed merchant + normalized alias is
    upserted, and every non-manual transaction whose normalized description
    contains that alias is restamped to it (the "fix once, fixed forever"
    promise, now structural instead of the old order-dependent override table).
    The richer merge/split review flow is task 4.3."""
    data = request.json
    txn_id = data.get('id')
    new_cat = data.get('category')
    learn = data.get('learn', False)
    merchant = (data.get('merchant', '') or '').strip()
    conn = get_db()

    # The edited transaction is always a manual pin.
    conn.execute("UPDATE transactions SET category=?, category_source='manual' WHERE id=?",
                 (new_cat, txn_id))
    # learn+merchant confirms that merchant (see the review-queue confirm flow,
    # which shares _confirm_merchant). include_txn_id links the edited row to the
    # merchant even though we just marked it manual — it's the seed of the rule.
    if learn and merchant:
        _confirm_merchant(conn, normalize(merchant), new_cat, merchant, include_txn_id=txn_id)

    rebuild_accruals(conn)
    conn.commit()
    conn.close()
    return jsonify({'success': True})


def _unique_canonical(conn, name):
    """merchants.canonical_name is UNIQUE; a learned merchant name might collide
    with a migration-seeded verbatim one. Suffix a counter if needed."""
    base = (name or 'Merchant').title()
    candidate, n = base, 2
    while conn.execute('SELECT 1 FROM merchants WHERE canonical_name=?', (candidate,)).fetchone():
        candidate, n = f'{base} ({n})', n + 1
    return candidate


def _confirm_merchant(conn, alias, category, canonical_hint, include_txn_id=None):
    """Upsert a CONFIRMED merchant keyed by the normalized `alias`, then restamp
    every non-manual transaction whose normalized description contains that alias
    to (category, merchant_id, source='confirmed'). Shared by recategorize+learn
    and the review-queue confirm endpoint — the one structural "fix once, fixed
    forever" primitive. `include_txn_id` forces one specific (possibly-manual)
    row to be restamped too: the transaction the owner explicitly edited, which
    seeds the rule. Returns (merchant_id, restamped_count)."""
    alias = (alias or '').strip()
    if not alias:
        return None, 0
    row = conn.execute('SELECT merchant_id FROM merchant_aliases WHERE pattern=?', (alias,)).fetchone()
    if row:
        merchant_id = row['merchant_id']
        conn.execute("UPDATE merchants SET category=?, status='confirmed' WHERE id=?",
                     (category, merchant_id))
    else:
        cur = conn.execute(
            "INSERT INTO merchants (canonical_name, category, status) VALUES (?,?,'confirmed')",
            (_unique_canonical(conn, canonical_hint or alias), category))
        merchant_id = cur.lastrowid
        conn.execute('INSERT INTO merchant_aliases (merchant_id, pattern) VALUES (?,?)',
                     (merchant_id, alias))
    count = 0
    for t in conn.execute(
            'SELECT id, description, raw_description, category_source FROM transactions').fetchall():
        if t['category_source'] == 'manual' and t['id'] != include_txn_id:
            continue
        if alias in normalize(t['raw_description'] or t['description']):
            conn.execute(
                "UPDATE transactions SET category=?, merchant_id=?, category_source='confirmed' WHERE id=?",
                (category, merchant_id, t['id']))
            count += 1
    return merchant_id, count


def _blast_radius(conn, alias):
    """How many non-manual transactions a confirm of `alias` would restamp, and
    what categories they hold now — the preview shown before a confirm/learn."""
    alias = (alias or '').strip()
    if not alias:
        return {'count': 0, 'total': 0, 'categories': []}
    count = total = 0
    cats = {}
    for t in conn.execute(
            'SELECT description, raw_description, amount_paise, category, category_source, '
            'type, is_cashback FROM transactions').fetchall():
        if t['category_source'] == 'manual':
            continue
        if alias in normalize(t['raw_description'] or t['description']):
            count += 1
            if t['type'] == 'debit' and not t['is_cashback']:
                total += t['amount_paise']
            cats[t['category']] = cats.get(t['category'], 0) + 1
    return {'count': count, 'total': total,
            'categories': [c for c, _ in sorted(cats.items(), key=lambda kv: -kv[1])]}


# ── Review queue + merchant management (task 4.3, ADR-009) ────────────────────
@app.route('/api/review_queue')
def review_queue():
    """Non-confirmed, non-manual spend grouped by normalized merchant, sorted by
    spend — the work list for confirming categories. Confirming a group is one
    round-trip via /api/review_queue/confirm."""
    conn = get_db()
    rows = conn.execute('''
        SELECT description, raw_description, amount_paise, category
        FROM transactions
        WHERE type='debit' AND is_cashback=0
          AND category_source IN ('keyword','bank','suggested','none')
    ''').fetchall()
    conn.close()
    groups = {}
    for r in rows:
        key = normalize(r['raw_description'] or r['description'])
        if not key:
            continue
        g = groups.setdefault(key, {'merchant': key, 'sample': r['description'],
                                    'count': 0, 'total': 0, 'categories': {}})
        g['count'] += 1
        g['total'] += r['amount_paise']
        g['categories'][r['category']] = g['categories'].get(r['category'], 0) + 1
    out = []
    for g in groups.values():
        suggested = max(g['categories'].items(), key=lambda kv: kv[1])[0]
        out.append({'merchant': g['merchant'], 'sample': g['sample'], 'count': g['count'],
                    'total': g['total'], 'suggested_category': suggested})
    out.sort(key=lambda x: x['total'], reverse=True)
    return jsonify(out)


@app.route('/api/review_queue/confirm', methods=['POST'])
def confirm_from_queue():
    data = request.json or {}
    alias = normalize(data.get('merchant', '') or '')   # queue keys are already normalized; idempotent
    category = data.get('category')
    if not alias or not category:
        return jsonify({'error': 'merchant and category required'}), 400
    if category not in CATEGORIES:
        return jsonify({'error': f'Unknown category: {category}'}), 400
    conn = get_db()
    merchant_id, restamped = _confirm_merchant(conn, alias, category, data.get('canonical') or alias)
    rebuild_accruals(conn)
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'merchant_id': merchant_id, 'restamped': restamped})


@app.route('/api/blast_radius')
def blast_radius():
    conn = get_db()
    res = _blast_radius(conn, normalize(request.args.get('merchant', '') or ''))
    conn.close()
    return jsonify(res)


@app.route('/api/merchants')
def get_merchants():
    conn = get_db()
    rows = conn.execute('''
        SELECT m.id, m.canonical_name, m.category, m.status,
               (SELECT COUNT(*) FROM merchant_aliases ma WHERE ma.merchant_id = m.id) AS alias_count,
               (SELECT COUNT(*) FROM transactions t WHERE t.merchant_id = m.id) AS txn_count
        FROM merchants m ORDER BY txn_count DESC, m.canonical_name
    ''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/merchants/merge', methods=['POST'])
def merge_merchants():
    """Fold merchant `from_id` into `into_id`: non-manual transactions adopt
    into's category (source='confirmed'/'suggested'); manual pins keep their
    category but re-link; aliases move (dropping any that collide); from is
    deleted. This is how the owner cleans up the migration's verbatim duplicate
    merchants (e.g. the 4 'California Burrito*' rows)."""
    data = request.json or {}
    from_id, into_id = data.get('from_id'), data.get('into_id')
    if not from_id or not into_id or from_id == into_id:
        return jsonify({'error': 'distinct from_id and into_id required'}), 400
    conn = get_db()
    into = conn.execute('SELECT * FROM merchants WHERE id=?', (into_id,)).fetchone()
    if not into or not conn.execute('SELECT 1 FROM merchants WHERE id=?', (from_id,)).fetchone():
        conn.close()
        return jsonify({'error': 'merchant not found'}), 404
    src = 'confirmed' if into['status'] == 'confirmed' else 'suggested'
    conn.execute("UPDATE transactions SET merchant_id=?, category=?, category_source=? "
                 "WHERE merchant_id=? AND category_source!='manual'",
                 (into_id, into['category'], src, from_id))
    conn.execute("UPDATE transactions SET merchant_id=? WHERE merchant_id=? AND category_source='manual'",
                 (into_id, from_id))
    for a in conn.execute('SELECT id, pattern FROM merchant_aliases WHERE merchant_id=?', (from_id,)).fetchall():
        clash = conn.execute('SELECT 1 FROM merchant_aliases WHERE pattern=? AND merchant_id=?',
                             (a['pattern'], into_id)).fetchone()
        if clash:
            conn.execute('DELETE FROM merchant_aliases WHERE id=?', (a['id'],))
        else:
            conn.execute('UPDATE merchant_aliases SET merchant_id=? WHERE id=?', (into_id, a['id']))
    conn.execute('DELETE FROM merchants WHERE id=?', (from_id,))
    rebuild_accruals(conn)
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ── Milestones ────────────────────────────────────────────────────────────────
@app.route('/api/milestones', methods=['GET'])
def get_milestones():
    """Progress is computed live (task 3.6, fixes F6) — net spend (as M4
    defines it: gross debits excluding cashback and Finance Charges, minus
    refund credits excluding Credit Card Bills payments) within the
    milestone's own window. No stored counter, so it can never go stale the
    way current_spend did."""
    conn = get_db()
    rows = conn.execute('''
        SELECT m.id, a.name AS card_label, m.name, m.target_paise, m.window_start,
               m.window_end, m.benefit,
               COALESCE(SUM(CASE WHEN t.type='debit' AND t.is_cashback=0
                                  AND t.category != 'Finance Charges'
                                  THEN t.amount_paise ELSE 0 END), 0)
             - COALESCE(SUM(CASE WHEN t.type='credit' AND t.is_cashback=0
                                  AND t.category != 'Credit Card Bills'
                                  THEN t.amount_paise ELSE 0 END), 0) AS net_spend_paise
        FROM milestones m
        JOIN accounts a ON a.id = m.account_id
        LEFT JOIN transactions t ON t.account_id = m.account_id
               AND t.date BETWEEN m.window_start AND m.window_end
        GROUP BY m.id
        ORDER BY m.created_at DESC
    ''').fetchall()
    conn.close()
    return jsonify([{
        'id': r['id'], 'card_label': r['card_label'], 'name': r['name'],
        'target_paise': r['target_paise'], 'window_start': r['window_start'],
        'window_end': r['window_end'], 'benefit': r['benefit'],
        'progress_paise': max(0, r['net_spend_paise']),
    } for r in rows])

@app.route('/api/milestones', methods=['POST'])
def add_milestone():
    data = request.json
    card_label = data.get('card_label', '').strip()
    name = data.get('name', '').strip()
    target_spend = data.get('target_spend')
    window_start = data.get('window_start', '').strip()
    window_end = data.get('window_end', '').strip()
    if not card_label or not name or target_spend is None or not window_start or not window_end:
        return jsonify({'error': 'card_label, name, target_spend, window_start, and window_end required'}), 400
    conn = get_db()
    account = conn.execute(
        "SELECT id FROM accounts WHERE kind='credit_card' AND name=?", (card_label,)).fetchone()
    if not account:
        conn.close()
        return jsonify({'error': f'Unknown card: {card_label}. Add it via Import first.'}), 400
    conn.execute(
        '''INSERT INTO milestones (account_id, name, target_paise, window_start, window_end, benefit)
           VALUES (?,?,?,?,?,?)''',
        (account['id'], name, int(round(float(target_spend) * 100)),
         window_start, window_end, data.get('benefit', ''))
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/milestones/<int:mid>', methods=['DELETE'])
def delete_milestone(mid):
    conn = get_db()
    conn.execute('DELETE FROM milestones WHERE id=?', (mid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ── Cards / misc ──────────────────────────────────────────────────────────────
_REWARD_LEGACY_TYPE = {'points': 'points', 'cashback_paise': 'cashback_inr', 'balance_paise': 'balance_inr'}

@app.route('/api/rewards', methods=['GET'])
def get_rewards():
    """Current balance per card: the reward_balances row with the latest
    as_of (task 3.5) — not whichever was inserted last (that was F5)."""
    conn = get_db()
    rows = conn.execute('''
        SELECT rb.id, a.name AS card_label, rb.label, rb.value_minor, rb.value_type,
               rb.source, rb.as_of
        FROM reward_balances rb
        JOIN accounts a ON a.id = rb.account_id
        WHERE NOT EXISTS (
            SELECT 1 FROM reward_balances rb2
            WHERE rb2.account_id = rb.account_id
              AND (rb2.as_of > rb.as_of OR (rb2.as_of = rb.as_of AND rb2.id > rb.id))
        )
        ORDER BY a.name
    ''').fetchall()
    conn.close()
    return jsonify([{
        'id': r['id'], 'card_label': r['card_label'], 'label': r['label'],
        'value': r['value_minor'], 'value_type': _REWARD_LEGACY_TYPE[r['value_type']],
        'source': r['source'], 'as_of': r['as_of'],
    } for r in rows])

@app.route('/api/rewards/history', methods=['GET'])
def get_reward_history():
    """Full dated history for one card (task 3.5) — feeds the Rewards view's
    sparkline."""
    card_label = request.args.get('card_label', '').strip()
    if not card_label:
        return jsonify({'error': 'card_label required'}), 400
    conn = get_db()
    rows = conn.execute('''
        SELECT rb.as_of, rb.label, rb.value_minor, rb.value_type, rb.source
        FROM reward_balances rb
        JOIN accounts a ON a.id = rb.account_id
        WHERE a.name = ?
        ORDER BY rb.as_of
    ''', (card_label,)).fetchall()
    conn.close()
    return jsonify([{
        'as_of': r['as_of'], 'label': r['label'], 'value': r['value_minor'],
        'value_type': _REWARD_LEGACY_TYPE[r['value_type']], 'source': r['source'],
    } for r in rows])

@app.route('/api/rewards', methods=['POST'])
def upsert_reward():
    """Manual entry — user overrides or adds a reward balance for a card, as
    of today. Value arrives in the frontend's rupee/points domain
    ('points'|'cashback_inr'|'balance_inr'); paise conversion happens here,
    same boundary pattern as the upload route's statement-sourced write."""
    data = request.json
    card_label = data.get('card_label', '').strip()
    label      = data.get('label', '').strip()
    value      = data.get('value')
    legacy_type = data.get('value_type', 'points')
    if not card_label or not label or value is None:
        return jsonify({'error': 'card_label, label, and value required'}), 400
    conn = get_db()
    account = conn.execute(
        "SELECT id FROM accounts WHERE kind='credit_card' AND name=?", (card_label,)).fetchone()
    if not account:
        conn.close()
        return jsonify({'error': f'Unknown card: {card_label}. Add it via Import first.'}), 400
    if legacy_type == 'points':
        value_minor, value_type = int(round(float(value))), 'points'
    elif legacy_type == 'cashback_inr':
        value_minor, value_type = int(round(float(value) * 100)), 'cashback_paise'
    elif legacy_type == 'balance_inr':
        value_minor, value_type = int(round(float(value) * 100)), 'balance_paise'
    else:
        return jsonify({'error': f'Unknown value_type: {legacy_type}'}), 400
    as_of = datetime.now().date().isoformat()
    conn.execute(
        '''INSERT INTO reward_balances (account_id, as_of, label, value_minor, value_type, source)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(account_id, as_of) DO UPDATE SET
             label=excluded.label, value_minor=excluded.value_minor,
             value_type=excluded.value_type, source='manual'
           ''',
        (account['id'], as_of, label, value_minor, value_type, 'manual')
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/cards')
def get_cards():
    # Reads the accounts registry directly (task 3.7) rather than distinct
    # transaction card_labels — a card added but not yet imported into now
    # correctly appears here too (previously it only showed up once its
    # first statement landed).
    conn = get_db()
    rows = conn.execute(
        "SELECT name FROM accounts WHERE kind='credit_card' ORDER BY name"
    ).fetchall()
    conn.close()
    return jsonify([r['name'] for r in rows])

# ── Reward programs (task 5.2 — read-only view of the seeded rules) ──────────
# Rules themselves are edited by editing ccyamls/*.yaml and re-running
# `python -m rewards.seed` (see rewards/seed.py's docstring for why this is
# the deliberate "editor" for now rather than a second in-app CRUD surface).
# This endpoint is how the owner sees what's currently live without reading
# YAML or SQL directly.
@app.route('/api/reward_programs')
def get_reward_programs():
    conn = get_db()
    rows = conn.execute('''
        SELECT rp.id, a.name AS card_label, rp.name, rp.earn_currency, rp.annual_fee_paise,
               rp.valid_from, rp.valid_to,
               (SELECT COUNT(*) FROM earn_rules er WHERE er.program_id = rp.id) AS earn_rule_count,
               (SELECT COUNT(*) FROM bonus_rules br WHERE br.program_id = rp.id) AS bonus_rule_count,
               (SELECT rr.name FROM redemption_routes rr
                WHERE rr.program_id = rp.id AND rr.is_default = 1 LIMIT 1) AS default_route_name,
               (SELECT rr.value_per_point_centipaise FROM redemption_routes rr
                WHERE rr.program_id = rp.id AND rr.is_default = 1 LIMIT 1) AS default_route_centipaise
        FROM reward_programs rp
        JOIN accounts a ON a.id = rp.account_id
        ORDER BY (rp.valid_to IS NOT NULL), a.name
    ''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ── Effective rates + reconciliation (task 5.4 — M10 Job 2) ──────────────────
# All derived on the fly from reward_accruals/bonuses/reward_balances —
# nothing stored. Formula + v1 attribution choices: rewards/reports.py.
@app.route('/api/rewards/effective_rates')
def get_effective_rates():
    conn = get_db()
    by_card_month, by_card_category_month = reports.effective_rates(conn)
    conn.close()
    return jsonify({'by_card_month': by_card_month,
                    'by_card_category_month': by_card_category_month})

@app.route('/api/rewards/reconciliation')
def get_reconciliation():
    conn = get_db()
    rows = reports.reconciliation(conn)
    conn.close()
    return jsonify(rows)

# ── Gap report + forward guidance (task 5.5 — M10 Job 3) ─────────────────────
# The cap-aware greedy counterfactual per (category, month). Semantics and
# v1 caveats: rewards/gaps.py (the caveats ride along in the response so the
# UI displays them on the report itself, per spec M10).
@app.route('/api/rewards/gaps')
def get_gaps():
    conn = get_db()
    out = gaps_module.gap_report(conn, months_back=request.args.get('months', 6, type=int))
    conn.close()
    return jsonify(out)

@app.route('/api/rewards/guidance')
def get_guidance():
    conn = get_db()
    rows = gaps_module.guidance(conn)
    conn.close()
    return jsonify(rows)

@app.route('/api/rewards/rates_summary')
def get_rates_summary():
    conn = get_db()
    out = reports.rates_summary(
        conn,
        request.args.get('from_date', '2000-01-01'),
        request.args.get('to_date', '2099-12-31'),
        card=request.args.get('card') or None,
    )
    conn.close()
    return jsonify(out)

if __name__ == '__main__':
    # `--demo` runs against a throwaway database of fabricated transactions
    # (scripts/seed_demo.py), seeding it on first use. It points DB_PATH at a
    # SEPARATE file and never touches data/fintrack.db — running the demo must
    # not be able to disturb real data, so the two never share a path.
    if '--demo' in sys.argv:
        from scripts.seed_demo import DEFAULT_DB, seed
        DB_PATH = DEFAULT_DB
        if not os.path.exists(DB_PATH):
            seed(DB_PATH)
        print("")
        print(f"DEMO MODE - serving fabricated data from {DB_PATH}.")
        print("   Every transaction in it is invented. Your real database is untouched.")
        print("   Delete that file to regenerate it.")

    init_db()
    try:
        applied = migrate(DB_PATH)
        if applied:
            print(f"Applied schema migrations: {applied}")
    except MigrationError as e:
        # Refuse to start against a half-migrated DB (ADR-007). The failed
        # migration was rolled back and a pre-migration backup exists in
        # data/backups/ — nothing was lost.
        print(f"\nMIGRATION FAILED — refusing to start.\n{e}")
        raise SystemExit(1)
    # Plain ASCII: emoji here crashes on Windows when stdout is cp1252
    # (e.g. captured/piped output), killing the server at startup.
    print("\nFinTrack is running!")
    print("   Open http://localhost:5000 in your browser\n")
    app.run(debug=False, port=5000)
