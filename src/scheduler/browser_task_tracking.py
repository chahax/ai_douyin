"""Keep a refresh plan attached to its original browser command across waits.""" 
from contextlib import contextmanager
from contextvars import ContextVar
import json
from pathlib import Path
import sqlite3
import time

_current = ContextVar('browser_refresh_run', default=None)
TABLE = 'refresh_browser_commands'


@contextmanager
def tracking(run_id, path):
    token = _current.set((run_id, path))
    try:
        yield
    finally:
        _current.reset(token)


def exists(db):
    return bool(db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(TABLE,)).fetchone())


def attach(command, browser_path, *, run_id=None, path=None):
    current = _current.get()
    if run_id is None:
        if current is None:
            return
        run_id,path = current
    from .account_refresh import connect
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        run = db.execute('SELECT * FROM refresh_runs WHERE run_id=?',(run_id,)).fetchone()
        if not run or run['account_uuid'] != command['account_id'] or command['kind'] != 'maintenance' or command['payload']['mode'] != 'post-publish':
            raise ValueError('Refresh/browser identity mismatch')
        db.execute(f'''CREATE TABLE IF NOT EXISTS {TABLE}(run_id TEXT PRIMARY KEY,account_uuid TEXT NOT NULL,
            command_id TEXT UNIQUE NOT NULL,request_sha TEXT NOT NULL,browser_path TEXT NOT NULL,
            state TEXT NOT NULL,original_run TEXT NOT NULL,settlement TEXT,created_at REAL NOT NULL)''')
        old = db.execute(f'SELECT * FROM {TABLE} WHERE run_id=?',(run_id,)).fetchone()
        if old:
            if old['command_id'] != command['command_id'] or old['request_sha'] != command['request_sha']:
                raise ValueError('Original command already attached')
            return
        db.execute(f'INSERT INTO {TABLE} VALUES(?,?,?,?,?,?,?,?,?)',
            (run_id,run['account_uuid'],command['command_id'],command['request_sha'],str(Path(browser_path).resolve()),
             'waiting',json.dumps(dict(run),ensure_ascii=False),None,time.time()))


def pending(db, account_uuid):
    return exists(db) and bool(db.execute(f"SELECT 1 FROM {TABLE} WHERE account_uuid=? AND state='waiting'",(account_uuid,)).fetchone())


def read_command(link):
    from src.operations_accounts.browser_control import BrowserControlStore
    with sqlite3.connect(Path(link['browser_path']).as_uri()+'?mode=ro',uri=True,timeout=3) as db:
        db.row_factory=sqlite3.Row
        row=db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',(link['command_id'],)).fetchone()
        c=BrowserControlStore._command(row) if row else None
    if not c or c['account_id'] != link['account_uuid'] or c['request_sha'] != link['request_sha']:
        raise ValueError('Original browser command missing or changed')
    return c


def waiting_before_dispatch(db, run_id):
    if not exists(db):
        return False
    row=db.execute(f"SELECT * FROM {TABLE} WHERE run_id=? AND state='waiting'",(run_id,)).fetchone()
    if row is None:
        return False
    c=read_command(dict(row))
    return c['state']=='queued' and c['owner_id'] is None and c['generation'] is None


def reconcile(path):
    """Only consume original receipts; never submit or claim a browser task."""
    from . import account_refresh as refresh
    with refresh.connect(path) as db:
        if not exists(db):return
        links=[dict(r) for r in db.execute(f"SELECT * FROM {TABLE} WHERE state='waiting'")]
    for link in links:
        c=read_command(link)
        if c['state'] not in {'succeeded','failed'}:continue
        value=(c.get('result') or {}).get('maintenance_result')
        # A dispatch rejection also has a known failure; it never means success.
        status=value['status'] if isinstance(value,dict) else 'failed'
        detail=({'message':value['message'],'maintenance_run_id':value['run_id'],
                 'videos':value['synced_videos'],'comments':value['synced_comments'],
                 'comment_failures':value['comment_sync_failures'],'login_healthy':value['login_healthy'],
                 'error_code':value.get('error_code','')} if isinstance(value,dict) else
                {'message':'原浏览器请求已结束，详情见原命令。','error_code':c.get('error_code') or 'browser_command_failed'})
        with refresh.connect(path) as db:
            run=db.execute('SELECT * FROM refresh_runs WHERE run_id=?',(link['run_id'],)).fetchone()
        if run['status'] in {'running','outcome_unknown','waiting_original'} and run['finished_at'] is None:
            refresh.finish(link['run_id'],status,detail,path=path)
        elif run['finished_at'] is None:
            continue  # Original caller still owns the plan receipt.
        with refresh.connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute(f'SELECT state FROM {TABLE} WHERE run_id=?',(link['run_id'],)).fetchone()
            if current['state']!='waiting':continue
            historical=json.loads(link['original_run']).get('finished_at') is not None
            if historical:
                # A historical wait failure is immutable. Its original command's
                # new receipt advances the schedule once, instead of immediately
                # dispatching another refresh after the recovery probe.
                interval=db.execute('SELECT interval_seconds FROM refresh_policy WHERE id=1').fetchone()[0]
                now=time.time()
                db.execute('UPDATE refresh_accounts SET next_due=? WHERE account_uuid=? AND run_id IS NULL AND next_due<=?',
                    (now+(interval if status=='completed' and not detail['error_code'] else min(interval,1800)),link['account_uuid'],now))
                if status!='completed' or detail['error_code']:
                    refresh._pause(db,link['account_uuid'],run['account_key'],
                        '原排队任务恢复后仍失败，已保留独立回执并停止自动重试。',detail['error_code'] or 'continuation_failed',now)
            db.execute(f"UPDATE {TABLE} SET state='settled',settlement=? WHERE run_id=? AND state='waiting'",
                (json.dumps({'command_id':c['command_id'],'status':status,'detail':detail,'at':time.time()},ensure_ascii=False),link['run_id']))
