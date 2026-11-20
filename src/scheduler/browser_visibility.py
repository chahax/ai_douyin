"""Per-account permission for unsolicited visible verification windows."""
import json
import sqlite3
import time
from pathlib import Path


def _path(path):
    if path is None:
        from .account_refresh import DB
        path = DB
    return Path(path).resolve()


def automatic_window_allowed(account_uuid, *, issue=None, path=None):
    with sqlite3.connect(_path(path).as_uri() + '?mode=ro', uri=True, timeout=3) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='account_browser_preferences'").fetchone():
            return True
        row = db.execute('SELECT auto_visible_windows FROM account_browser_preferences WHERE account_uuid=?',
                         (account_uuid,)).fetchone()
        if row is None or row[0] == 1:
            return True
        if row[0] == 2:
            # The detector emits human_required only after usable challenge
            # content is confirmed. An unconfirmed/blank frame stays silent.
            return bool(isinstance(issue, dict) and issue.get('account_uuid') == account_uuid
                        and issue.get('error_code') == 'human_required' and issue.get('status') == 'open')
        return False


def set_automatic_windows(account_uuid, enabled, *, authorization, confirmed_only=False, path=None):
    if not account_uuid or type(enabled) is not bool or type(confirmed_only) is not bool or not authorization.strip():
        raise ValueError('Account, boolean preference and explicit authorization required')
    value = 2 if enabled and confirmed_only else int(enabled)
    with sqlite3.connect(_path(path).as_uri() + '?mode=rw', uri=True, timeout=10) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS account_browser_preferences(account_uuid TEXT PRIMARY KEY, auto_visible_windows INTEGER NOT NULL, updated_at REAL NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS account_browser_preference_history(id INTEGER PRIMARY KEY, account_uuid TEXT NOT NULL, before_value TEXT NOT NULL, after_value INTEGER NOT NULL, authorization TEXT NOT NULL, changed_at REAL NOT NULL)')
        old = db.execute('SELECT auto_visible_windows FROM account_browser_preferences WHERE account_uuid=?', (account_uuid,)).fetchone()
        now = time.time()
        db.execute('INSERT INTO account_browser_preference_history(account_uuid,before_value,after_value,authorization,changed_at) VALUES(?,?,?,?,?)',
                   (account_uuid, json.dumps(old[0] if old else None), value, authorization, now))
        db.execute('INSERT INTO account_browser_preferences VALUES(?,?,?) ON CONFLICT(account_uuid) DO UPDATE SET auto_visible_windows=excluded.auto_visible_windows,updated_at=excluded.updated_at',
                   (account_uuid, value, now))
