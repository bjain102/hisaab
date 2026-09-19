"""v5 — windowed milestones (ADR-003 step 5; fixes F6).

Rebuilds `milestones` (ADR-007 rebuild pattern — SQLite can't drop/retype
columns) replacing `card_label`/`target_spend`/`current_spend`/`deadline` with
`account_id`/`target_paise`/`window_start`/`window_end`. Progress is no longer
a stored counter (F6: it was seeded once at creation and never updated after —
see app.py's pre-3.6 add_milestone) — it becomes a live query over the window,
using M4's own net-spend definition (gross debits, excluding cashback
credits, minus refund credits, excluding Credit Card Bills payments).

Backfill: `window_start` = date part of the old `created_at` (the milestone's
own start of tracking — the best available proxy; the old schema never
recorded an intentional start date). `window_end` = the old `deadline` when
present; milestones with no deadline get `window_end = '9999-12-31'` (an
open-ended window). `target_paise = round(target_spend * 100)`. Every
migrated window is inferred, never chosen by the owner — a review report
prints for all of them (ADR-003's migration note: review both rows'
windows regardless of whether a deadline existed).

A milestone whose `card_label` no longer matches any account (deleted card,
typo) is skipped and reported — it has nothing to reference as account_id.
"""


def up(conn):
    conn.execute('''
        CREATE TABLE milestones_new (
            id           INTEGER PRIMARY KEY,
            account_id   INTEGER NOT NULL REFERENCES accounts(id),
            name         TEXT NOT NULL,
            target_paise INTEGER NOT NULL,
            window_start TEXT NOT NULL,
            window_end   TEXT NOT NULL,
            benefit      TEXT,
            created_at   TEXT NOT NULL DEFAULT (datetime('now'))
        )
    ''')

    conn.execute('''
        INSERT INTO milestones_new (id, account_id, name, target_paise, window_start, window_end,
                                     benefit, created_at)
        SELECT m.id, a.id, m.name, CAST(ROUND(m.target_spend * 100) AS INTEGER),
               substr(m.created_at, 1, 10), COALESCE(NULLIF(m.deadline, ''), '9999-12-31'),
               m.benefit, m.created_at
        FROM milestones m
        JOIN accounts a ON a.kind = 'credit_card' AND a.name = m.card_label
    ''')

    skipped = conn.execute('''
        SELECT m.card_label, m.name FROM milestones m
        LEFT JOIN accounts a ON a.kind = 'credit_card' AND a.name = m.card_label
        WHERE a.id IS NULL
    ''').fetchall()
    for s in skipped:
        print(f"  SKIPPED milestone '{s['name']}' for unknown card '{s['card_label']}' — no matching account.")

    conn.execute('DROP TABLE milestones')
    conn.execute('ALTER TABLE milestones_new RENAME TO milestones')

    migrated = conn.execute('''
        SELECT a.name AS card, m.name AS milestone, m.window_start, m.window_end
        FROM milestones m JOIN accounts a ON a.id = m.account_id
        ORDER BY a.name
    ''').fetchall()
    if migrated:
        print(f'\n  MILESTONE WINDOW REVIEW — {len(migrated)} migrated milestone(s), '
              f'windows inferred (not owner-chosen). Please review:')
        for m in migrated:
            open_note = ' (no deadline — open-ended)' if m['window_end'] == '9999-12-31' else ''
            print(f"    {m['card']} / {m['milestone']!r}: {m['window_start']} .. {m['window_end']}{open_note}")


def verify(conn):
    n_before = conn.execute('SELECT COUNT(*) FROM milestones').fetchone()[0]
    assert n_before >= 0  # table exists and is queryable post-rebuild

    dangling_account = conn.execute('''
        SELECT COUNT(*) FROM milestones m
        LEFT JOIN accounts a ON a.id = m.account_id
        WHERE a.id IS NULL
    ''').fetchone()[0]
    assert dangling_account == 0, f'{dangling_account} milestones with no matching account'

    bad_window = conn.execute(
        'SELECT COUNT(*) FROM milestones WHERE window_start > window_end').fetchone()[0]
    assert bad_window == 0, f'{bad_window} milestones with window_start after window_end'

    bad_target = conn.execute('SELECT COUNT(*) FROM milestones WHERE target_paise <= 0').fetchone()[0]
    assert bad_target == 0, f'{bad_target} milestones with a non-positive target_paise'

    cols = {r[1] for r in conn.execute('PRAGMA table_info(milestones)')}
    assert 'card_label' not in cols and 'target_spend' not in cols and 'current_spend' not in cols \
        and 'deadline' not in cols, cols
    assert {'account_id', 'target_paise', 'window_start', 'window_end'} <= cols, cols
