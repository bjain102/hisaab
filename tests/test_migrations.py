"""Task 3.1: migration runner + backup helper (ADR-007 mechanics).

Fake migrations are injected via migrate(migrations_list=...) — the real
migrations package is empty until task 3.2, and the runner's behavior
(transaction-per-migration, rollback on failed verify, version bumping,
backups) is what's under test, not any specific migration.
"""
from pathlib import Path
import os
import sqlite3
import time
from types import SimpleNamespace

import pytest

import app as app_module
from db import MigrationError, _prune_backups, backup_db, get_version, migrate

_CORPUS_DIR = Path(__file__).parent / 'corpus' / 'tier1'
# This repository ships no statements (they are real financial documents), so
# every test in this module skips on a fresh clone and comes alive the moment
# you add your own to tests/corpus/tier1/ — see that directory's README.
pytestmark = pytest.mark.skipif(
    not _CORPUS_DIR.is_dir() or not any(f.suffix.lower() in ('.pdf', '.csv') for f in _CORPUS_DIR.glob('*')),
    reason='no local statement corpus — see tests/corpus/tier1/README.md',
)


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    """A synthetic legacy-schema DB in a temp dir (never the real one)."""
    path = str(tmp_path / 'test.db')
    monkeypatch.setattr(app_module, 'DB_PATH', path)
    app_module.init_db()
    conn = sqlite3.connect(path)
    conn.execute(
        '''INSERT INTO transactions
           (date, description, amount, type, category, card, card_label, is_cashback, import_batch)
           VALUES ('2026-01-05','SAMPLE ROW',100.0,'debit','Others','ALPHA','CARD-A',0,'test-batch')'''
    )
    conn.commit()
    conn.close()
    return path


def _backups_dir(path):
    return os.path.join(os.path.dirname(path), 'backups')


def _mig(version_name, up, verify):
    return SimpleNamespace(up=up, verify=verify, __name__=version_name)


# ── The backlog's Done criteria, verbatim ─────────────────────────────────────

def test_noop_at_v0_with_checkpoint_backup(db_path):
    """'running on a copy of the real DB is a no-op at v0 with a backup created'"""
    applied = migrate(db_path, migrations_list=[], checkpoint=True)
    assert applied == []
    assert get_version(db_path) == 0
    backups = os.listdir(_backups_dir(db_path))
    assert len(backups) == 1 and 'checkpoint' in backups[0]


def test_failed_verify_rolls_back_and_preserves_original(db_path):
    """'a deliberately failing verify rolls back and preserves the original'"""
    def up(conn):
        conn.execute("INSERT INTO transactions (date, description, amount, type, category, card, card_label) "
                     "VALUES ('2026-02-01','SHOULD NOT SURVIVE',1.0,'debit','Others','X','CARD-X')")

    def verify(conn):
        raise AssertionError('deliberate verify failure')

    before = sqlite3.connect(db_path).execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
    with pytest.raises(MigrationError, match='deliberate verify failure'):
        migrate(db_path, migrations_list=[(1, _mig('m001_fail', up, verify))])

    assert get_version(db_path) == 0                       # version bump rolled back too
    conn = sqlite3.connect(db_path)
    assert conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0] == before
    conn.close()
    assert any('pre-v1' in f for f in os.listdir(_backups_dir(db_path)))


# ── Runner mechanics ──────────────────────────────────────────────────────────

def test_chain_applies_in_order_and_persists(db_path):
    def up1(conn):
        conn.execute('CREATE TABLE m1_marker (n INTEGER)')
        conn.execute('INSERT INTO m1_marker VALUES (1)')

    def verify1(conn):
        assert conn.execute('SELECT COUNT(*) FROM m1_marker').fetchone()[0] == 1

    def up2(conn):
        conn.execute('INSERT INTO m1_marker VALUES (2)')

    def verify2(conn):
        assert conn.execute('SELECT COUNT(*) FROM m1_marker').fetchone()[0] == 2

    applied = migrate(db_path, migrations_list=[
        (1, _mig('m001_ok', up1, verify1)),
        (2, _mig('m002_ok', up2, verify2)),
    ])
    assert applied == [1, 2]
    assert get_version(db_path) == 2
    # per-migration backups both exist
    names = os.listdir(_backups_dir(db_path))
    assert any('pre-v1' in f for f in names) and any('pre-v2' in f for f in names)
    # re-running is a no-op
    assert migrate(db_path, migrations_list=[(1, _mig('m001_ok', up1, verify1)),
                                             (2, _mig('m002_ok', up2, verify2))]) == []


def test_partial_chain_keeps_earlier_migration(db_path):
    def up1(conn):
        conn.execute('CREATE TABLE survivor (n INTEGER)')

    def ok(conn):
        pass

    def up2(conn):
        conn.execute('CREATE TABLE doomed (n INTEGER)')

    def fail(conn):
        raise AssertionError('v2 verify fails')

    with pytest.raises(MigrationError):
        migrate(db_path, migrations_list=[
            (1, _mig('m001_ok', up1, ok)),
            (2, _mig('m002_fail', up2, fail)),
        ])
    assert get_version(db_path) == 1                       # v1 landed, v2 rolled back
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert 'survivor' in tables and 'doomed' not in tables


def test_backup_prune_keeps_newest_20(tmp_path):
    backups = tmp_path / 'backups'
    backups.mkdir()
    for i in range(25):
        p = backups / f'hisaab-{i:03d}-x.db'
        p.write_bytes(b'x')
        os.utime(p, (1000 + i, 1000 + i))               # deterministic mtime order
    _prune_backups(str(backups))
    remaining = sorted(os.listdir(backups))
    assert len(remaining) == 20
    assert remaining[0] == 'hisaab-005-x.db'           # 5 oldest pruned


def test_backup_db_returns_none_for_missing_file(tmp_path):
    assert backup_db(str(tmp_path / 'nowhere.db'), 'x') is None


# ── Destructive-op wiring (spec §4 backup rule) ───────────────────────────────

def test_statement_delete_takes_a_backup_first(client, tmp_path):
    """Since task 3.7 dropped import_batches, the destructive-bulk-op backup
    rule is exercised via DELETE /api/statements/<id> instead — upload a real
    tier1 file to get a real statement to delete."""
    from pathlib import Path
    corpus = Path(__file__).parent / 'corpus' / 'tier1' / 'KOTAK_ZEN_redacted.pdf'
    with open(corpus, 'rb') as f:
        upload_resp = client.post(
            '/api/upload',
            data={'file': (f, corpus.name), 'card': 'kotak', 'card_label': 'KOTAK-BACKUP-TEST', 'password': ''},
            content_type='multipart/form-data')
    assert upload_resp.status_code == 200

    conn = sqlite3.connect(app_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    stmt = conn.execute('''
        SELECT s.id FROM statements s JOIN accounts a ON a.id = s.account_id
        WHERE a.name = 'KOTAK-BACKUP-TEST'
    ''').fetchone()
    conn.close()
    assert stmt is not None

    resp = client.delete(f'/api/statements/{stmt["id"]}')
    assert resp.status_code == 200
    backups_dir = _backups_dir(app_module.DB_PATH)
    assert os.path.isdir(backups_dir)
    assert any('pre-statement-delete' in f for f in os.listdir(backups_dir))
    # and the delete itself worked
    conn = sqlite3.connect(app_module.DB_PATH)
    assert conn.execute(
        'SELECT COUNT(*) FROM transactions WHERE statement_id=?', (stmt['id'],)).fetchone()[0] == 0
    assert conn.execute(
        'SELECT COUNT(*) FROM statements WHERE id=?', (stmt['id'],)).fetchone()[0] == 0
    conn.close()
