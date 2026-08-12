"""Task 4.1 verify: report how much the normalizer collapses the real corpus.

Prints distinct raw vs distinct normalized, for all rows and for spend rows
(debits, excluding cashback — the population merchant categorization targets),
plus the largest collapse clusters so the compression is auditable, not just a
number. Run: python scripts/normalize_compression.py
"""
import os
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from categorization import normalize  # noqa: E402

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "hisaab.db")


def report(label, rows):
    distinct_raw = set(rows)
    buckets = defaultdict(set)
    for r in rows:
        n = normalize(r)
        if n:
            buckets[n].add(r)
    distinct_norm = len(buckets)
    ratio = len(distinct_raw) / distinct_norm if distinct_norm else 0
    print(f"\n{label}: {len(rows)} txns")
    print(f"  distinct raw_description : {len(distinct_raw)}")
    print(f"  distinct normalized      : {distinct_norm}")
    print(f"  compression              : {ratio:.2f}x")
    top = sorted(buckets.items(), key=lambda kv: len(kv[1]), reverse=True)[:8]
    print("  largest collapse clusters (normalized <- N raw forms):")
    for norm, raws in top:
        if len(raws) > 1:
            print(f"    {norm!r:34} <- {len(raws)} forms")


def main():
    conn = sqlite3.connect(DB_PATH)
    all_rows = [r[0] for r in conn.execute("SELECT raw_description FROM transactions")]
    spend_rows = [r[0] for r in conn.execute(
        "SELECT raw_description FROM transactions WHERE type='debit' AND is_cashback=0")]
    conn.close()
    report("ALL rows", all_rows)
    report("SPEND rows (debit, non-cashback)", spend_rows)


if __name__ == "__main__":
    main()
