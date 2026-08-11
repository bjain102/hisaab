"""
pdf_parsers.py — Parsers for password-protected bank/card PDF statements.

Each parser returns:
  transactions: list of {date, description, amount, type, bank_category (optional)}
  rewards: dict of {label, value, value_type} or None
    value_type: 'points' | 'cashback_inr' | 'balance_inr'

IDFC wrap patterns (from real statements):
  Pattern A: merchant on prev_line only, date line has no description
  Pattern B: merchant on prev_line, date line has only forex+amount, continuation on next_line
             e.g. "KUCARA COFFEE AND SPACE H," / "06/06/2026 IDR 71300.00 378.75 DR" / "GIANYAR"
"""
import re
from datetime import datetime


def parse_amount(s):
    return float(s.replace(',', '').strip())


def parse_date_flexible(s):
    s = s.strip()
    for fmt in ['%d/%m/%Y', '%d-%m-%Y', '%d-%b-%Y', '%d/%b/%Y', '%d %b %Y', '%d-%B-%Y',
                '%d/%B/%Y', '%B %d, %Y', '%b %d, %Y', '%d %b, %Y', '%d %B, %Y']:
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return None


def make_result(transactions, rewards=None, period=None, totals=None, skipped_candidates=0):
    """period: {'start','end'} or None. totals: {'debits','credits','tad'} or None.
    Both additive (task 1.4) — 'debits'/'credits' are set only where the bank prints a
    total that reconciles with parsed transactions; 'tad' (Total Amount Due) is a
    balance, stored informationally and NOT a debit checksum.
    skipped_candidates (task 1.6, F2): count of date-like lines that looked like a
    transaction but didn't become one — see _count_anchor_lines."""
    return {'transactions': transactions, 'rewards': rewards,
            'period': period, 'totals': totals,
            'skipped_candidates': skipped_candidates}


def _count_anchor_lines(lines, anchor_re):
    """Count lines matching a bank's transaction-line anchor (its own date-position
    rule, verbatim — NOT a hand-simplified guess; e.g. ICICI's anchor must include
    the optional leading 'NN% ' EMI prefix its own line regex allows, or this
    undercounts real transaction lines as false 'skips').
    skipped_candidates = max(0, anchor_count - len(transactions)) holds because, in
    every parser here, one anchor-matched line yields at most one transaction —
    continuation lines a parser absorbs (e.g. IDFC's wrap patterns) are never
    themselves anchor-matched."""
    return sum(1 for l in lines if anchor_re.match(l))


def _period(start_raw, end_raw):
    """Normalize a raw start/end date pair to {'start','end'} or None if either fails."""
    start, end = parse_date_flexible(start_raw), parse_date_flexible(end_raw)
    if start and end:
        return {'start': start, 'end': end}
    return None


def _amt_or_none(s):
    try:
        return parse_amount(s)
    except (ValueError, AttributeError):
        return None


# ── IDFC FIRST Bank ───────────────────────────────────────────────────────────
def parse_idfc_pdf(full_text):
    lines = [l.strip() for l in full_text.split('\n') if l.strip()]
    date_re    = re.compile(r'^(\d{2}/\d{2}/\d{4})\s+(.*)$')
    amount_re  = re.compile(r'([\d,]+\.\d{2})\s*(DR|CR)\s*$')
    forex_re   = re.compile(r'\s*(Convert\b.*|(IDR|USD|EUR|GBP|SGD|AED|THB|MYR)\s+[\d,]+\.?\d*)\s*$')
    section_markers = ('Purchases, EMIs & Other Debits', 'Payments & Other Credits')
    skip_starts = ('Card Number', 'Date Details', 'YOUR TRANSACTIONS')

    def is_noise(l):
        return (not l or any(l.startswith(s) for s in skip_starts)
                or l in section_markers
                or bool(date_re.match(l))
                or bool(amount_re.search(l)))

    transactions = []
    section = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if 'Purchases, EMIs & Other Debits' in line:
            section = 'debit'; i += 1; continue
        if 'Payments & Other Credits' in line:
            section = 'credit'; i += 1; continue
        if section is None or any(line.startswith(s) for s in skip_starts):
            i += 1; continue

        m = date_re.match(line)
        if m:
            date_str, rest = m.groups()
            date = parse_date_flexible(date_str)
            amt_m = amount_re.search(rest)
            if date and amt_m:
                amount   = parse_amount(amt_m.group(1))
                txn_type = 'debit' if amt_m.group(2) == 'DR' else 'credit'
                desc     = rest[:amt_m.start()].strip()

                # Strip forex artifacts: "Convert", "IDR 71300.00", "USD 66.92", etc.
                desc = forex_re.sub('', desc).strip()
                if desc.lower() in ('convert', ''):
                    desc = ''

                if not desc:
                    prev = lines[i - 1] if i > 0 else ''
                    nxt  = lines[i + 1] if i + 1 < len(lines) else ''
                    parts = []
                    if prev and not is_noise(prev):
                        parts.append(prev)
                    if nxt and not is_noise(nxt):
                        parts.append(nxt)
                        i += 1  # consume continuation
                    desc = ' '.join(parts).strip() or 'IDFC Transaction'

                transactions.append({'date': date, 'description': desc,
                                     'amount': amount, 'type': txn_type})
        i += 1

    # ── Rewards: extract "Rewards Available" (cumulative) ──
    rewards = None
    for line in lines:
        m = re.search(r'Rewards Available[^0-9]*([0-9,]+)', line)
        if m:
            try:
                rewards = {
                    'label': 'Reward Points',
                    'value': int(m.group(1).replace(',', '')),
                    'value_type': 'points'
                }
            except ValueError:
                pass
            break

    # ── Period + totals (task 1.4) ──
    # IDFC prints "Statement Date 02/May/2026 to 01/Jun/2026" and a "Total Amount Due"
    # (a balance, not Σdebits — stored as tad only, debits/credits left None).
    period = None
    pm = re.search(r'Statement Date\s+(\d{2}/[A-Za-z]{3}/\d{4})\s+to\s+(\d{2}/[A-Za-z]{3}/\d{4})', full_text)
    if pm:
        period = _period(pm.group(1), pm.group(2))
    tad = None
    tm = re.search(r'Total Amount Due\s*=?\s*[^\d]*([\d,]+\.\d{2})', full_text)
    if tm:
        tad = _amt_or_none(tm.group(1))
    totals = {'debits': None, 'credits': None, 'tad': tad}

    # ── Unparsed-line surfacing (task 1.6, F2) ──
    anchor_count = _count_anchor_lines(lines, re.compile(r'^\d{2}/\d{2}/\d{4}\b'))
    skipped_candidates = max(0, anchor_count - len(transactions))

    return make_result(transactions, rewards, period, totals, skipped_candidates)


# ── ICICI (incl. Amazon Pay) ──────────────────────────────────────────────────
def parse_icici_pdf(full_text):
    lines = full_text.split('\n')
    line_re = re.compile(
        r'^(?:\d+%\s+)?(\d{2}/\d{2}/\d{4})\s+(\d+)\s+(.+?)\s+([\d,]+\.\d{2})\s*(CR)?\s*$'
    )
    transactions = []
    for line in lines:
        line = line.strip()
        m = line_re.match(line)
        if not m:
            continue
        date_str, serno, rest, amt_str, cr_flag = m.groups()
        date = parse_date_flexible(date_str)
        if not date:
            continue
        amount   = parse_amount(amt_str)
        txn_type = 'credit' if cr_flag == 'CR' else 'debit'
        tokens = rest.split()
        while tokens and re.match(r'^\d+(\.\d+)?$', tokens[-1]):
            tokens.pop()
        desc = ' '.join(tokens).strip() or rest.strip()
        transactions.append({'date': date, 'description': desc,
                             'amount': amount, 'type': txn_type})

    # ── Rewards: "Earnings transferred to Amazon Pay balance" ──
    rewards = None
    for line in lines:
        m = re.search(r'Earnings\s+transfer(?:red)?\s+to\s+Amazon\s+Pay\s+balance[^\d]*([\d,]+\.?\d*)', line, re.I)
        if m:
            try:
                rewards = {
                    'label': 'Amazon Pay Balance',
                    'value': float(m.group(1).replace(',', '')),
                    'value_type': 'balance_inr'
                }
            except ValueError:
                pass
            break
        # Also catch single-number "Earned / Transferred" summary rows
        m2 = re.search(r'(\d+)\s+(\d+)\s*$', line)
        if 'Earned' in line and 'Amazon' in line and m2:
            try:
                rewards = {
                    'label': 'Amazon Pay Balance',
                    'value': float(m2.group(2)),
                    'value_type': 'balance_inr'
                }
            except ValueError:
                pass

    # ── Period + totals (task 1.4) ──
    # ICICI prints "Statement period : February 3, 2026 to March 2, 2026".
    # No clean Σdebits total: its breakdown table is positional and the nearby
    # per-transaction figures are fine-print interest *illustrations* — debits None.
    period = None
    pm = re.search(r'Statement period\s*:?\s*([A-Za-z]+ \d{1,2}, \d{4})\s+to\s+([A-Za-z]+ \d{1,2}, \d{4})', full_text)
    if pm:
        period = _period(pm.group(1), pm.group(2))
    totals = {'debits': None, 'credits': None, 'tad': None}

    # ── Unparsed-line surfacing (task 1.6, F2) ──
    # Anchor mirrors line_re's optional leading 'NN% ' EMI prefix — a plain
    # ^\d{2}/\d{2}/\d{4} anchor undercounts (a real corpus line, "15% 17/02/2026 ...",
    # only matches with that prefix accounted for).
    anchor_re = re.compile(r'^(?:\d+%\s+)?\d{2}/\d{2}/\d{4}\b')
    anchor_count = _count_anchor_lines([l.strip() for l in lines if l.strip()], anchor_re)
    skipped_candidates = max(0, anchor_count - len(transactions))

    return make_result(transactions, rewards, period, totals, skipped_candidates)


# ── Axis Bank (all variants) ──────────────────────────────────────────────────
def parse_axis_pdf(full_text):
    lines = full_text.split('\n')
    line_re = re.compile(
        r'^(\d{2}/\d{2}/\d{4})\s+(.+?)\s+([A-Z][A-Z .&]+?)\s+([\d,]+\.\d{2})\s*(Dr|Cr)?\s*$'
    )
    simple_re = re.compile(
        r'^(\d{2}/\d{2}/\d{4})\s+(.+?)\s+([\d,]+\.\d{2})\s*(Dr|Cr)?\s*$'
    )
    transactions = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith('DATE TRANSACTION') or '****' in line:
            continue
        m = line_re.match(line)
        bank_category = None
        if m:
            date_str, desc, category, amt_str, drcr = m.groups()
            bank_category = category.strip()
        else:
            m = simple_re.match(line)
            if not m:
                continue
            date_str, desc, amt_str, drcr = m.groups()
        date = parse_date_flexible(date_str)
        if not date:
            continue
        amount   = parse_amount(amt_str)
        txn_type = 'credit' if drcr == 'Cr' else 'debit'
        row = {'date': date, 'description': desc.strip(),
               'amount': amount, 'type': txn_type}
        if bank_category:
            row['bank_category'] = bank_category
        transactions.append(row)

    # ── Rewards: eDGE REWARD POINTS balance ──
    # Header: "eDGE REWARD  BALANCE AS  CUSTOMER ID"
    # Sub-header: "POINTS  ON DATE"
    # Value line: "7678  30-06-2026  938951948 ..."
    # First number on value line = points balance
    rewards = None
    lines_list = full_text.split('\n')
    for idx, line in enumerate(lines_list):
        if 'eDGE REWARD' in line or 'EDGE REWARD' in line:
            for offset in [1, 2, 3]:
                if idx + offset < len(lines_list):
                    val_line = lines_list[idx + offset].strip()
                    # Value line starts with points number followed by a date DD-MM-YYYY
                    m = re.match(r'^(\d{3,6})\s+\d{2}-\d{2}-\d{4}', val_line)
                    if m:
                        try:
                            rewards = {
                                'label': 'EDGE Points',
                                'value': int(m.group(1)),
                                'value_type': 'points'
                            }
                        except ValueError:
                            pass
                        break
            break

    # ── Period + totals (task 1.4) ──
    # Axis prints the cycle as "dd/mm/yyyy - dd/mm/yyyy" on the summary value line.
    # "Total Payment Due" is a balance (a cycle can show TAD=447 alongside a 68,421
    # credit) — not Σdebits, so debits/credits stay None.
    period = None
    pm = re.search(r'(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})', full_text)
    if pm:
        period = _period(pm.group(1), pm.group(2))
    totals = {'debits': None, 'credits': None, 'tad': None}

    # ── Unparsed-line surfacing (task 1.6, F2) ──
    anchor_re = re.compile(r'^\d{2}/\d{2}/\d{4}\b')
    anchor_count = _count_anchor_lines([l.strip() for l in lines if l.strip()], anchor_re)
    skipped_candidates = max(0, anchor_count - len(transactions))

    return make_result(transactions, rewards, period, totals, skipped_candidates)


# ── Kotak Mahindra Bank ───────────────────────────────────────────────────────
def parse_kotak_pdf(full_text):
    """Kotak statements (task 1.7, F7 fix — purchases-only was the audit finding).

    The transaction-detail block is bounded between 'Transactions Details from ...'
    and the first of 'Need quick access?' or a 20-line hard cap (real windows are
    4-5 lines in both statements seen; the cap is a safety net, not a tight guess).
    This matters because the summary sentences near the top ("Purchases made in
    this cycle X.XX ...", "Payments and Other Credits X.XX ...") are numeric
    look-alikes OUTSIDE the real block, and — critically — a real statement with
    zero purchases that cycle omits the purchases section header AND prints no
    'Total Payments' closing line at all for its payments section. Without the
    window bound, a naive 'Total Purchases'/'Total Payments' close-trigger could
    leave the section "open" through ~180 lines of dense two-column legal fine
    print (pdfplumber visibly interleaves that region's two columns into garbled
    text) with no guaranteed close.

    Purchase rows ('... <category> <amount>', nothing after) and credit rows
    ('... <amount> Cr') are mutually exclusive by shape, so both regexes are tried
    against every line in the window rather than tracking which bare sub-header
    ('Purchases made in this cycle' / 'Payments and Other Credits') appeared.

    UNVERIFIED: behavior when a single cycle has BOTH purchases and payments — no
    real statement with both populated has been seen yet. The window bound is the
    safety net if that shape ever surfaces something unexpected.
    """
    lines = [l.strip() for l in full_text.split('\n')]
    line_re = re.compile(r'^(\d{2}-[A-Za-z]{3}-\d{4})\s+(.+?)\s+([\d,]+\.\d{2})\s*$')
    credit_re = re.compile(r'^(\d{2}-[A-Za-z]{3}-\d{4})\s+(.+?)\s+([\d,]+\.\d{2})\s*Cr\s*$')
    transactions = []

    start = next((i for i, l in enumerate(lines) if 'Transactions Details from' in l), None)
    if start is not None:
        end = next((i for i in range(start, min(start + 20, len(lines)))
                    if 'Need quick access?' in lines[i]), min(start + 20, len(lines)))
        for line in lines[start:end]:
            m = credit_re.match(line)
            if m:
                date_str, desc, amt_str = m.groups()
                date = parse_date_flexible(date_str)
                if date:
                    transactions.append({'date': date, 'description': desc.strip(),
                                         'amount': parse_amount(amt_str), 'type': 'credit'})
                continue
            m = line_re.match(line)
            if not m:
                continue
            date_str, desc_and_cat, amt_str = m.groups()
            date = parse_date_flexible(date_str)
            if not date:
                continue
            amount = parse_amount(amt_str)
            tokens   = desc_and_cat.split()
            category = tokens[-1] if tokens else ''
            desc     = ' '.join(tokens[:-1]).strip() if len(tokens) > 1 else desc_and_cat
            transactions.append({'date': date, 'description': desc, 'amount': amount,
                                 'type': 'debit', 'bank_category': category})

    # ── Rewards: Kotak shows Points Available in the summary ──
    rewards = None
    for line in lines:
        m = re.search(r'Points available[^\d]*([\d,]+)', line, re.I)
        if not m:
            m = re.search(r'(\d+)\s*$', line) if 'Points available' in line else None
        if m:
            try:
                rewards = {
                    'label': 'Reward Points',
                    'value': int(m.group(1).replace(',', '')),
                    'value_type': 'points'
                }
            except ValueError:
                pass
            break

    # ── Period + totals (task 1.4, extended in 1.7) ──
    # Kotak prints "Transactions Details from 16-Mar-2026 to 15-Apr-2026" and a
    # "Total Purchases" line that DOES equal Σ(parsed debits) — the one bank in the
    # corpus with a clean printed debit total. Since 1.7, the top-of-statement
    # summary sentence "Payments and Other Credits X.XX ..." (a numbered line,
    # distinct from the bare in-window sub-header of the same name) gives an
    # equally clean printed credits total — verified against the real corpus to
    # match its one credit row exactly.
    period = None
    pm = re.search(r'from\s+(\d{2}-[A-Za-z]{3}-\d{4})\s+to\s+(\d{2}-[A-Za-z]{3}-\d{4})', full_text)
    if pm:
        period = _period(pm.group(1), pm.group(2))
    debits = None
    dm = re.search(r'Total Purchases\s+([\d,]+\.\d{2})', full_text)
    if dm:
        debits = _amt_or_none(dm.group(1))
    credits = None
    cm = re.search(r'Payments and Other Credits\s+([\d,]+\.\d{2})', full_text)
    if cm:
        credits = _amt_or_none(cm.group(1))
    tad = None
    tm = re.search(r'Total Amount Due\s+([\d,]+\.\d{2})', full_text)
    if tm:
        tad = _amt_or_none(tm.group(1))
    totals = {'debits': debits, 'credits': credits, 'tad': tad}

    # ── Unparsed-line surfacing (task 1.6, F2) ──
    # Counted over the FULL text, not just the transaction-detail window — still the
    # honest signal that would catch a future Kotak layout dropping a dated line
    # anywhere, now that the known credits gap (F7) is fixed above.
    anchor_re = re.compile(r'^\d{2}-[A-Za-z]{3}-\d{4}\b')
    anchor_count = _count_anchor_lines([l.strip() for l in lines if l.strip()], anchor_re)
    skipped_candidates = max(0, anchor_count - len(transactions))

    return make_result(transactions, rewards, period, totals, skipped_candidates)


# ── HDFC Bank (all co-brand variants) ────────────────────────────────────────
# HDFC ships TWO different statement layouts, and a card can move between them
# mid-history (the owner's Swiggy card did, so a single card's back-catalogue
# needs both):
#
#   CURRENT  "dd/mm/yyyy| HH:MM  DESC  <glyph> 1,234.00 l"   — date+time, a
#            stray currency glyph, a trailing 'l' artifact, and a standalone
#            '+' before the amount marking a credit.
#   OLD      "dd/mm/yyyy [HH:MM:SS] DESC  1,234.00[Cr]"       — bare date under
#            a "Domestic Transactions" header, an OPTIONAL "HH:MM:SS" time
#            with no separator (not every row carries one — auto-debited/
#            system-posted rows like "TELE TRANSFER CREDIT" often don't,
#            observed on both a Swiggy and a Tata Neu old-layout statement),
#            and a 'Cr' suffix marking a credit. That suffix is GLUED to the
#            amount with no separating space ("879.90Cr", verified against a
#            real credit-bearing statement) — don't "tidy" that \s* into \s+.
#
# The two line shapes are mutually exclusive by construction — the current
# format always puts '|HH:MM' immediately after the date, the old format always
# puts whitespace there — so both matchers run over the same pass rather than
# the parser guessing a mode up front. That also means a statement carrying
# both (should HDFC ever straddle a cycle) parses correctly instead of silently
# yielding half its rows.
_HDFC_CUR_PREFIX_RE = re.compile(r'^(\d{2}/\d{2}/\d{4})\|\s*\d{2}:\d{2}\s+(.+)$')
_HDFC_CUR_AMOUNT_RE = re.compile(r'([\d,]+\.\d{2})\s*l?\s*$')
# Old layout: date, optional HH:MM:SS (non-capturing — consumed BEFORE the
# description group starts, so it's never mistaken for part of the merchant
# name), description, amount, optional 'Cr'. Anchored at BOTH ends — the
# amount must terminate the line — so the dense legal fine print (which
# mentions dates in prose but never opens a line with one) can't match.
_HDFC_OLD_TXN_RE = re.compile(
    r'^(\d{2}/\d{2}/\d{4})\s+(?:\d{2}:\d{2}:\d{2}\s+)?(\S.*?)\s+([\d,]+\.\d{2})\s*(Cr)?$', re.I)


def _hdfc_old_window(lines):
    """Line indices [start, end) holding the old layout's transaction rows.

    Bounded like the Kotak payments-section scan (F7): the old statement's rows
    sit between the 'Domestic Transactions' header and the 'Important
    Information' legal block. Windowing is belt-and-braces on top of the
    already-anchored regex — it keeps a future HDFC fine-print revision that
    happens to open a line with a date from being read as a transaction.
    Falls back to the whole document when the header is absent, so a variant
    that labels the section differently still parses rather than silently
    returning nothing.
    """
    start, end = None, len(lines)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if start is None and stripped.startswith('Domestic Transactions'):
            start = i + 1
        elif start is not None and stripped.startswith('Important Information'):
            end = i
            break
    return (0, len(lines)) if start is None else (start, end)


def parse_hdfc_pdf(full_text):
    lines = full_text.split('\n')
    transactions = []

    old_start, old_end = _hdfc_old_window(lines)

    for idx, line in enumerate(lines):
        line = line.strip()
        if not line or line.startswith('DATE & TIME'):
            continue

        m = _HDFC_CUR_PREFIX_RE.match(line)
        if not m:
            # Old layout, only inside the transaction-detail window.
            if not (old_start <= idx < old_end):
                continue
            om = _HDFC_OLD_TXN_RE.match(line)
            if not om:
                continue
            date = parse_date_flexible(om.group(1))
            if not date:
                continue
            desc = om.group(2).strip()
            transactions.append({
                'date': date,
                'description': desc,
                'amount': parse_amount(om.group(3)),
                # 'Cr' after the amount = credit. Verified against a real
                # statement carrying both a cashback and a bill payment.
                'type': 'credit' if om.group(4) else 'debit',
            })
            continue

        date_str, rest = m.groups()
        date = parse_date_flexible(date_str)
        if not date:
            continue
        amt_m = _HDFC_CUR_AMOUNT_RE.search(rest)
        if not amt_m:
            continue
        amount        = parse_amount(amt_m.group(1))
        before_amount = rest[:amt_m.start()].strip()
        tokens        = before_amount.split()

        # Leading 'EMI' is the statement's "convert to EMI" BUTTON, not part of
        # the merchant name — the PDF draws a tappable badge between the time
        # and the description, and pdfplumber extracts its label as a plain
        # text token ("Eligible for EMI CONVERT TO EMI" is the legend for it,
        # elsewhere in the same document). Bare-token equality, not a prefix
        # test, so a real merchant like EMIRATES is left alone. Only the
        # current layout has these badges — no old-layout corpus file does.
        if tokens and tokens[0] == 'EMI':
            tokens.pop(0)

        # Strip trailing single-char currency glyph artifact
        if tokens and re.match(r'^[A-Za-z]$', tokens[-1]):
            tokens.pop()

        # Credit detection: standalone '+' as last token = credit/cashback
        # '+ <number>' = NeuCoins earned column — not a credit marker
        is_credit = False
        if tokens and tokens[-1] == '+':
            is_credit = True
            tokens.pop()
        elif len(tokens) >= 2 and tokens[-2] == '+' and re.match(r'^\d+$', tokens[-1]):
            tokens = tokens[:-2]

        desc     = ' '.join(tokens).strip()
        txn_type = 'credit' if is_credit else 'debit'
        transactions.append({'date': date, 'description': desc,
                             'amount': amount, 'type': txn_type})

    # ── Rewards: branch by card type ──────────────────────────────────────
    rewards = None

    # Tata Neu: header is "NeuCoins with Bank ..." on one line,
    # values are on the line two below it: "173 202 188 202 15"
    # First number = NeuCoins with Bank (cumulative balance held by bank)
    lines_list = full_text.split('\n')
    for idx, line in enumerate(lines_list):
        if 'NeuCoins with Bank' in line:
            # Value line is 2 lines ahead (line+1 is the sub-header continuation)
            for offset in [1, 2, 3]:
                if idx + offset < len(lines_list):
                    val_line = lines_list[idx + offset].strip()
                    m = re.match(r'^(\d+)\s+\d+', val_line)
                    if m:
                        try:
                            rewards = {
                                'label': 'NeuCoins',
                                'value': int(m.group(1)),
                                'value_type': 'points'
                            }
                        except ValueError:
                            pass
                        break
            break

    # Swiggy: "Total  ₹379.66" from Cash Back Summary table
    if rewards is None:
        m = re.search(r'Cash\s*Back\s*Summary.*?Total\s+[^\d]*([\d,]+\.\d{2})', full_text, re.I | re.S)
        if m:
            try:
                rewards = {
                    'label': 'Cashback',
                    'value': float(m.group(1).replace(',', '')),
                    'value_type': 'cashback_inr'
                }
            except ValueError:
                pass

    # ── Period + totals (task 1.4) ──
    # HDFC prints "Billing Period 02 May, 2026 - 01 Jun, 2026". Its PURCHASES/DEBIT
    # column is printed separately from FINANCE CHARGES and does NOT match Σ(parsed
    # debits) in the corpus (differs by fee/rounding), so debits stays None; TAD is a
    # balance, not captured as a checksum.
    #
    # The OLD layout prints no billing period at all — only "Statement Date:
    # 19/01/2025" — so `period` stays None there and the upload route falls back
    # to the transaction dates' own span (app.py documents that path). Nothing is
    # inferred from the statement date: the cycle START would be pure guesswork,
    # and a fabricated period feeds straight into dedup/overlap gating.
    #
    # Its Account Summary DOES print a Purchase/Debits column that equals
    # Σ(parsed debits) exactly in the one corpus file (8,849.00) — deliberately
    # NOT promoted to `totals` here. That file has Finance Charges 0.00, and the
    # column excludes finance charges, so it's unknown whether the identity
    # survives a statement carrying fees; asserting it now would fail loudly on
    # real imports for a reason nobody could reproduce. The identity is pinned
    # for that one file in tests/test_hdfc_legacy_layout.py instead. Promote it
    # here only once a fee-bearing old statement confirms the behaviour.
    period = None
    pm = re.search(r'Billing Period\s+(\d{2} [A-Za-z]{3}, \d{4})\s*-\s*(\d{2} [A-Za-z]{3}, \d{4})', full_text)
    if pm:
        period = _period(pm.group(1), pm.group(2))
    totals = {'debits': None, 'credits': None, 'tad': None}

    # ── Unparsed-line surfacing (task 1.6, F2) ──
    # Two anchors, one per layout. The current-format anchor is the pipe+time
    # signature; HDFC's dense legal fine print mentions dates in prose but never
    # starts a line with 'dd/mm/yyyy|HH:MM'.
    #
    # The old layout has no such distinctive signature, so its anchor is a bare
    # leading date counted ONLY inside the transaction window — outside it, a
    # bare date is exactly what the fine print might legitimately open with, and
    # counting those would report phantom skipped rows on every import.
    #
    # This gap is why the old format failed silently rather than loudly: with a
    # pipe+time-only anchor, an old statement parsed to 0 transactions AND 0
    # skipped candidates, so F2's safety net reported nothing amiss.
    stripped = [l.strip() for l in lines if l.strip()]
    cur_anchor_re = re.compile(r'^\d{2}/\d{2}/\d{4}\|\s*\d{2}:\d{2}\b')
    anchor_count = _count_anchor_lines(stripped, cur_anchor_re)

    old_anchor_re = re.compile(r'^\d{2}/\d{2}/\d{4}\s+\S')
    window = [l.strip() for l in lines[old_start:old_end] if l.strip()]
    anchor_count += _count_anchor_lines(window, old_anchor_re)

    skipped_candidates = max(0, anchor_count - len(transactions))

    return make_result(transactions, rewards, period, totals, skipped_candidates)


# ── American Express (MRCC) ──────────────────────────────────────────────────
_AMEX_MONTHS = {m: i for i, m in enumerate(
    ['January', 'February', 'March', 'April', 'May', 'June', 'July',
     'August', 'September', 'October', 'November', 'December'], start=1)}


def parse_amex_pdf(full_text):
    """Amex statements (task 1.4b, owner scope change 2026-07-15).

    Layout facts from the corpus:
      - Transaction lines are '<MonthName> <D> <description> <amount>' with NO
        year — the year is inferred from the statement period (handles Dec→Jan
        straddle by trying both period years).
      - Credits carry an explicit CR marker on the FOLLOWING line: either a
        bare 'CR' line (consumed) or the observed 'Card Number CR' page
        artifact (not consumed). New marker variants will surface as credit
        reconciliation failures — by design.
      - Period: 'Statement Period From June 3 to July 2, 2026'.
      - Totals: the page-1 summary equation 'Opening - New Credits + New Debits
        = Closing  MinPayment' prints BOTH a debit and a credit total that
        reconcile with the transaction list — the only bank in the corpus that
        does; both are asserted by the reconciliation tests.
      - Rewards: this statement variant prints no Membership Rewards balance —
        rewards is always None.
    """
    lines = [l.strip() for l in full_text.split('\n') if l.strip()]

    # ── Period ──
    period = None
    start_y = end_y = None
    pm = re.search(
        r'Statement Period\s+From\s+([A-Z][a-z]+)\s+(\d{1,2})\s+to\s+([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})',
        full_text)
    if pm:
        sm, sd, em, ed, ey = (pm.group(1), int(pm.group(2)), pm.group(3),
                              int(pm.group(4)), int(pm.group(5)))
        if sm in _AMEX_MONTHS and em in _AMEX_MONTHS:
            end_y = ey
            start_y = ey - 1 if _AMEX_MONTHS[sm] > _AMEX_MONTHS[em] else ey
            period = {
                'start': f'{start_y:04d}-{_AMEX_MONTHS[sm]:02d}-{sd:02d}',
                'end': f'{end_y:04d}-{_AMEX_MONTHS[em]:02d}-{ed:02d}',
            }
    if end_y is None:
        # Fallback year anchor: the statement 'Date dd/mm/yyyy' header line.
        dm = re.search(r'^Date\b.*?(\d{2})/(\d{2})/(\d{4})', full_text, re.M | re.S)
        end_y = start_y = int(dm.group(3)) if dm else datetime.now().year

    def infer_date(month_name, day):
        mon = _AMEX_MONTHS[month_name]
        for year in (start_y, end_y):
            iso = f'{year:04d}-{mon:02d}-{day:02d}'
            if period and period['start'] <= iso <= period['end']:
                return iso
        return f'{end_y:04d}-{mon:02d}-{day:02d}'

    # ── Transactions ──
    txn_re = re.compile(r'^([A-Z][a-z]+)\s+(\d{1,2})\s+(.+?)\s+([\d,]+\.\d{2})\s*$')
    transactions = []
    i = 0
    while i < len(lines):
        m = txn_re.match(lines[i])
        if not m or m.group(1) not in _AMEX_MONTHS:
            i += 1
            continue
        month_name, day, desc, amt_str = m.group(1), int(m.group(2)), m.group(3), m.group(4)
        txn_type = 'debit'
        nxt = lines[i + 1] if i + 1 < len(lines) else ''
        if nxt == 'CR':
            txn_type = 'credit'
            i += 1  # consume the bare marker
        elif re.match(r'^Card Number\b.*\bCR$', nxt):
            # Page artifact carries the marker; don't consume. Real statements
            # embed the masked card number ('Card Number XXXX-XXXXXX-N CR');
            # redacted ones may print just 'Card Number CR' — match both.
            txn_type = 'credit'
        transactions.append({'date': infer_date(month_name, day),
                             'description': desc.strip(),
                             'amount': parse_amount(amt_str),
                             'type': txn_type})
        i += 1

    # ── Totals: 'Opening - New Credits + New Debits = Closing  MinPayment' ──
    totals = {'debits': None, 'credits': None, 'tad': None}
    tm = re.search(
        r'([\d,]+\.\d{2})\s*-\s*([\d,]+\.\d{2})\s*\+\s*([\d,]+\.\d{2})\s*=\s*([\d,]+\.\d{2})',
        full_text)
    if tm:
        totals = {'debits': _amt_or_none(tm.group(3)),
                  'credits': _amt_or_none(tm.group(2)),
                  'tad': _amt_or_none(tm.group(4))}

    # ── Unparsed-line surfacing (task 1.6, F2) ──
    anchor_re = re.compile(
        r'^(January|February|March|April|May|June|July|'
        r'August|September|October|November|December)\s+\d{1,2}\b')
    anchor_count = _count_anchor_lines(lines, anchor_re)
    skipped_candidates = max(0, anchor_count - len(transactions))

    return make_result(transactions, None, period, totals, skipped_candidates)


PDF_PARSERS = {
    'idfc':  parse_idfc_pdf,
    'icici': parse_icici_pdf,
    'axis':  parse_axis_pdf,
    'kotak': parse_kotak_pdf,
    'hdfc':  parse_hdfc_pdf,
    'amex':  parse_amex_pdf,
}