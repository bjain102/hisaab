"""Task 5.1 (schema half): migration v8 — rewards rules engine schema
(ADR-008). Pure schema addition: no existing data to migrate (these tables
are empty until the 5.2 seeder reads ccyamls/*.yaml), so this covers shape,
the widened period/cap_period enums, and the two ADR-008 deviations
(cap_group, merchant_match_exclude, nullable route value) rather than any
backfill.
"""
import sqlite3

import pytest

import app as app_module
from db import get_version, migrate


@pytest.fixture()
def db_migrated(tmp_path, monkeypatch):
    """Legacy-shape DB with one seeded transaction (so migration v1's account
    backfill has something to create), migrated through the full chain."""
    db_path = str(tmp_path / 'test.db')
    monkeypatch.setattr(app_module, 'DB_PATH', db_path)
    monkeypatch.setattr(app_module, 'STATEMENTS_DIR', str(tmp_path / 'statements'))
    app_module.init_db()
    conn = sqlite3.connect(db_path)
    conn.execute(
        '''INSERT INTO transactions (date, description, amount, type, category, card, card_label, is_cashback)
           VALUES ('2026-01-05', 'X', 100.0, 'debit', 'Others', 'ALPHA', 'ALPHA-1234', 0)''')
    conn.commit()
    conn.close()
    applied = migrate(db_path)
    assert 8 in applied
    return db_path


def _cols(conn, table):
    return {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}


def test_all_new_tables_exist_and_empty(db_migrated):
    conn = sqlite3.connect(db_migrated)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    expected = {'reward_programs', 'redemption_routes', 'earn_rules', 'bonus_rules', 'reward_accruals'}
    assert expected <= tables
    for t in expected:
        assert conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] == 0
    conn.close()


def test_milestones_gains_benefit_paise(db_migrated):
    conn = sqlite3.connect(db_migrated)
    cols = _cols(conn, 'milestones')
    conn.close()
    assert 'benefit_paise' in cols


def test_earn_rules_has_cap_group_and_merchant_exclude(db_migrated):
    conn = sqlite3.connect(db_migrated)
    cols = _cols(conn, 'earn_rules')
    conn.close()
    assert {'cap_group', 'merchant_match_exclude'} <= cols


def test_redemption_route_value_is_nullable(db_migrated):
    conn = sqlite3.connect(db_migrated)
    account_id = conn.execute("SELECT id FROM accounts LIMIT 1").fetchone()[0]
    cur = conn.execute(
        "INSERT INTO reward_programs (account_id, name, earn_currency, valid_from) "
        "VALUES (?, 'Test Program', 'points', '2026-01-01')", (account_id,))
    program_id = cur.lastrowid
    # a non-default route with NO fixed value must be insertable
    conn.execute(
        "INSERT INTO redemption_routes (program_id, name, value_per_point_centipaise, is_default) "
        "VALUES (?, 'Catalogue (varies)', NULL, 0)", (program_id,))
    conn.commit()
    row = conn.execute(
        "SELECT value_per_point_centipaise FROM redemption_routes WHERE name='Catalogue (varies)'").fetchone()
    conn.close()
    assert row[0] is None


def test_widened_period_enums_accepted(db_migrated):
    conn = sqlite3.connect(db_migrated)
    account_id = conn.execute("SELECT id FROM accounts LIMIT 1").fetchone()[0]
    cur = conn.execute(
        "INSERT INTO reward_programs (account_id, name, earn_currency, valid_from) "
        "VALUES (?, 'Test Program 2', 'points', '2026-01-01')", (account_id,))
    program_id = cur.lastrowid
    for period in ('calendar_quarter', 'anniversary_quarter', 'anniversary_year', 'one_time'):
        conn.execute(
            "INSERT INTO bonus_rules (program_id, name, period, bonus_units) VALUES (?,?,?,100)",
            (program_id, f'bonus-{period}', period))
        conn.execute(
            "INSERT INTO earn_rules (program_id, priority, kind, cap_period) VALUES (?,1,'base',?)",
            (program_id, period))
    conn.commit()
    n_bonus = conn.execute(
        "SELECT COUNT(*) FROM bonus_rules WHERE program_id=?", (program_id,)).fetchone()[0]
    n_earn = conn.execute(
        "SELECT COUNT(*) FROM earn_rules WHERE program_id=?", (program_id,)).fetchone()[0]
    conn.close()
    assert n_bonus == 4 and n_earn == 4


def test_bad_period_still_rejected(db_migrated):
    """The widened enum isn't a free-for-all — nonsense values still fail."""
    conn = sqlite3.connect(db_migrated)
    account_id = conn.execute("SELECT id FROM accounts LIMIT 1").fetchone()[0]
    cur = conn.execute(
        "INSERT INTO reward_programs (account_id, name, earn_currency, valid_from) "
        "VALUES (?, 'Test Program 3', 'points', '2026-01-01')", (account_id,))
    program_id = cur.lastrowid
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO bonus_rules (program_id, name, period, bonus_units) VALUES (?,'bad','fortnight',1)",
            (program_id,))
    conn.close()


def test_reward_accruals_cascades_on_transaction_delete(db_migrated):
    conn = sqlite3.connect(db_migrated)
    account_id, txn_id = conn.execute("SELECT account_id, id FROM transactions LIMIT 1").fetchone()
    cur = conn.execute(
        "INSERT INTO reward_programs (account_id, name, earn_currency, valid_from) "
        "VALUES (?, 'Test Program 4', 'points', '2026-01-01')", (account_id,))
    program_id = cur.lastrowid
    conn.execute(
        "INSERT INTO reward_accruals (txn_id, program_id, units_earned, units_uncapped, value_paise, computed_at) "
        "VALUES (?,?,10,10,250,'2026-01-01T00:00:00')", (txn_id, program_id))
    conn.commit()
    conn.close()

    # PRAGMA foreign_keys must be set as the very first statement on a fresh
    # connection (a no-op mid-transaction/mid-connection) for SQLite to
    # actually enforce ON DELETE CASCADE.
    conn = sqlite3.connect(db_migrated)
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('DELETE FROM transactions WHERE id=?', (txn_id,))
    conn.commit()
    n = conn.execute('SELECT COUNT(*) FROM reward_accruals WHERE txn_id=?', (txn_id,)).fetchone()[0]
    conn.close()
    assert n == 0  # ON DELETE CASCADE fired


def test_idempotent(db_migrated):
    version = get_version(db_migrated)
    assert migrate(db_migrated) == []
    assert get_version(db_migrated) == version
    conn = sqlite3.connect(db_migrated)
    for t in ('reward_programs', 'redemption_routes', 'earn_rules', 'bonus_rules', 'reward_accruals'):
        assert conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] == 0
    conn.close()
