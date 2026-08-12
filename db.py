"""Migration runner + backup helper (task 3.1, ADR-007).

Mechanics:
  - Schema version lives in SQLite's `PRAGMA user_version` (0 = legacy/pre-
    migration schema as created by app.init_db).
  - Migrations are numbered Python modules in the `migrations` package,
    named `m###_short_name.py`, each exposing `up(conn)` and `verify(conn)`.
    verify() raises on failure. Both run inside ONE transaction per
    migration: a failed verify rolls the whole migration back (user_version
    included — it's stored in the DB header and is transactional).
  - Before each migration the DB file is snapshot-copied to
    data/backups/hisaab-<stamp>-pre-v<N>.db. Newest 20 backups are kept.
  - The runner is invoked on app start (app.py __main__) and by migrate.ps1;
    a failed migration means the app REFUSES TO START with a clear message —
    never runs against a half-migrated DB.

backup_db() is also a general-purpose helper, wired into destructive bulk
operations (import-batch delete) per the spec's backup rule (02-product-spec
§4).
"""
import importlib
import os
import pkgutil
import re
import shutil
import sqlite3
from datetime import datetime

BACKUPS_KEEP = 20
_MIGRATION_NAME_RE = re.compile(r'^m(\d{3})_\w+$')


class MigrationError(RuntimeError):
    """A migration's up() or verify() failed; the DB was rolled back."""


def backup_db(db_path, reason):
    """Snapshot-copy the DB to <db_dir>/backups/hisaab-<stamp>-<reason>.db.
    Returns the backup path, or None when the DB file doesn't exist yet
    (fresh install — nothing to protect). Prunes to the newest BACKUPS_KEEP."""
    if not os.path.exists(db_path):
        return None
    backups_dir = os.path.join(os.path.dirname(os.path.abspath(db_path)), 'backups')
    os.makedirs(backups_dir, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    dest = os.path.join(backups_dir, f'hisaab-{stamp}-{reason}.db')
    shutil.copy2(db_path, dest)
    _prune_backups(backups_dir)
    return dest


def _prune_backups(backups_dir, keep=BACKUPS_KEEP):
    backups = sorted(
        (os.path.join(backups_dir, f) for f in os.listdir(backups_dir) if f.endswith('.db')),
        key=os.path.getmtime,
        reverse=True,
    )
    for stale in backups[keep:]:
        os.remove(stale)


def get_version(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute('PRAGMA user_version').fetchone()[0]
    finally:
        conn.close()


def discover_migrations():
    """[(version, module), ...] sorted ascending, from the migrations package.
    Filenames define versions (m001_foo.py -> 1); duplicates are a bug."""
    import migrations
    found = []
    for info in pkgutil.iter_modules(migrations.__path__):
        m = _MIGRATION_NAME_RE.match(info.name)
        if not m:
            continue
        found.append((int(m.group(1)), importlib.import_module(f'migrations.{info.name}')))
    found.sort(key=lambda pair: pair[0])
    versions = [v for v, _ in found]
    if len(versions) != len(set(versions)):
        raise MigrationError(f'duplicate migration versions: {versions}')
    return found


def migrate(db_path, migrations_list=None, checkpoint=False):
    """Apply pending migrations (those with version > current user_version).
    Returns the list of applied versions ([] = already up to date).

    checkpoint=True takes one extra backup up front even when nothing is
    pending (used by migrate.ps1 so every manual run leaves a restore point).
    migrations_list overrides package discovery — used by tests to inject
    synthetic migrations.
    """
    if checkpoint:
        backup_db(db_path, 'checkpoint')

    all_migrations = discover_migrations() if migrations_list is None else migrations_list
    current = get_version(db_path) if os.path.exists(db_path) else 0
    pending = [(v, mod) for v, mod in all_migrations if v > current]

    applied = []
    for version, module in pending:
        backup_db(db_path, f'pre-v{version}')
        # isolation_level=None -> autocommit off, we control the transaction
        # explicitly; BEGIN IMMEDIATE takes the write lock up front.
        conn = sqlite3.connect(db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('BEGIN IMMEDIATE')
            module.up(conn)
            module.verify(conn)
            conn.execute(f'PRAGMA user_version = {int(version)}')
            conn.execute('COMMIT')
        except Exception as e:
            conn.execute('ROLLBACK')
            raise MigrationError(
                f'migration v{version} ({getattr(module, "__name__", module)}) failed and was '
                f'rolled back — DB unchanged, backup in data/backups/. Cause: {e}'
            ) from e
        finally:
            conn.close()
        applied.append(version)
    return applied
