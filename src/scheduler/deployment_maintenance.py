"""Preserve one proven unexecuted maintenance wait across backend deployment."""
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from src.operations_accounts.browser_control import BrowserControlStore, _json

TABLE='deployment_maintenance_holds'


def _exists(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(TABLE,)).fetchone())


def _row(db,table,key,value):
    row=db.execute(f'SELECT * FROM {table} WHERE {key}=?',(value,)).fetchone()
    return dict(row) if row else None


def is_same_hold(current,*,authorization,command,run,cursor,browser_path):
    return (current is not None and current['state']=='awaiting_original'
        and current['authorization']==_json(authorization) and current['command_id']==command['command_id']
        and current['run_id']==run['run_id'] and current['command_snapshot']==_json(command)
        and current['run_snapshot']==_json(run) and current['cursor_snapshot']==_json(cursor)
        and current['browser_path']==str(Path(browser_path).resolve()) and current['settlement'] is None)


def hold_queued(control,browser,*,authorization,command_id,run_id,account_uuid,account_key,browser_path):
    if not control.in_transaction or not browser.in_transaction:
        raise RuntimeError('Deployment hold requires both writer fences')
    command=BrowserControlStore._command(browser.execute('SELECT * FROM browser_control_commands WHERE command_id=?',(command_id,)).fetchone())
    run=_row(control,'refresh_runs','run_id',run_id)
    cursor=_row(control,'refresh_accounts','account_uuid',account_uuid)
    if (not command or command['kind']!='maintenance' or command['state']!='queued'
            or command['account_id']!=account_uuid or command['owner_id'] is not None or command['generation'] is not None
            or command['cursor'] is not None or command['result'] is not None
            or command['payload'].get('mode')!='post-publish'
            or not run or run['account_uuid']!=account_uuid or run['account_key']!=account_key
            or run['status'] not in {'running','outcome_unknown'} or run['finished_at'] is not None
            or not cursor or cursor['account_key']!=account_key or cursor['run_id']!=run_id):
        raise RuntimeError('Only the exact unexecuted queued maintenance may be held')
    control.execute(f'''CREATE TABLE IF NOT EXISTS {TABLE}(account_uuid TEXT PRIMARY KEY,
        authorization TEXT NOT NULL,command_id TEXT NOT NULL,run_id TEXT NOT NULL,
        command_snapshot TEXT NOT NULL,run_snapshot TEXT NOT NULL,cursor_snapshot TEXT NOT NULL,
        browser_path TEXT NOT NULL,state TEXT NOT NULL,settlement TEXT,created_at REAL NOT NULL,settled_at REAL)''')
    current=_row(control,TABLE,'account_uuid',account_uuid)
    if current:
        if not is_same_hold(current,authorization=authorization,command=command,run=run,cursor=cursor,browser_path=browser_path):
            raise RuntimeError('An existing deployment hold cannot be overwritten')
        return {'account_uuid':account_uuid,'command_id':command_id,'run_id':run_id,
            'command_sha256':hashlib.sha256(_json(command).encode()).hexdigest(),'state':'awaiting_original','reused_existing':True}
    control.execute(f'INSERT INTO {TABLE} VALUES(?,?,?,?,?,?,?,?,?,?,?,NULL)',
        (account_uuid,_json(authorization),command_id,run_id,_json(command),_json(run),_json(cursor),
         str(Path(browser_path).resolve()),'awaiting_original',None,time.time()))
    return {'account_uuid':account_uuid,'command_id':command_id,'run_id':run_id,
        'command_sha256':hashlib.sha256(_json(command).encode()).hexdigest(),'state':'awaiting_original'}


def has_active_hold(db,account_uuid):
    if not _exists(db):return False
    hold=_row(db,TABLE,'account_uuid',account_uuid)
    if not hold or hold['state']=='settled':return False
    if hold['state'] not in {'awaiting_original','settling'}:
        raise RuntimeError('Unknown deployment hold state')
    cursor=_row(db,'refresh_accounts','account_uuid',account_uuid)
    run=_row(db,'refresh_runs','run_id',hold['run_id'])
    if hold['state']=='awaiting_original' and (cursor!=json.loads(hold['cursor_snapshot']) or run!=json.loads(hold['run_snapshot'])):
        raise RuntimeError('Original deployment maintenance cursor changed')
    return True


def held_command(command,*,path=None):
    """Read-only admission lookup for this exact original queued request."""
    from src.scheduler import account_refresh as refresh
    target=Path(path or refresh.DB).resolve()
    if not target.exists():return None
    with sqlite3.connect(target.as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        if not _exists(db):return None
        rows=[dict(row) for row in db.execute(f"SELECT * FROM {TABLE} WHERE command_id=? AND state IN ('awaiting_original','settling')",(command['command_id'],))]
    if len(rows)!=1:return None
    hold=rows[0];before=json.loads(hold['command_snapshot'])
    keys=('command_id','account_id','binding_version','kind','idempotency_key','payload','request_sha','priority','created_at','cursor')
    if (command.get('kind')!='maintenance' or hold['account_uuid']!=command.get('account_id')
            or command.get('payload',{}).get('mode')!='post-publish'
            or any(command.get(key)!=before.get(key) for key in keys)):
        return None
    return {'authorization':json.loads(hold['authorization']),'command_snapshot':before,'run_id':hold['run_id'],'state':hold['state']}


def resume_pending(*,path=None):
    """Poll the original command; never submit, claim or re-execute maintenance."""
    from src.scheduler import account_refresh as refresh
    path=Path(path or refresh.DB).resolve()
    with refresh.connect(path) as db:
        if not _exists(db):return []
        holds=[dict(row) for row in db.execute(f"SELECT * FROM {TABLE} WHERE state!='settled'")]
    results=[]
    for hold in holds:
        with sqlite3.connect(Path(hold['browser_path']).as_uri()+'?mode=ro',uri=True) as browser:
            browser.row_factory=sqlite3.Row
            command=BrowserControlStore._command(browser.execute('SELECT * FROM browser_control_commands WHERE command_id=?',(hold['command_id'],)).fetchone())
        before=json.loads(hold['command_snapshot'])
        if not command or any(command[k]!=before[k] for k in ('command_id','account_id','binding_version','kind','idempotency_key','payload','request_sha','priority','created_at')):
            raise RuntimeError('Original maintenance command identity changed')
        if command['state'] not in {'succeeded','failed'}:
            results.append({'command_id':command['command_id'],'state':'waiting_original','command_state':command['state']});continue
        value=(command.get('result') or {}).get('maintenance_result')
        if not isinstance(value,dict):
            raise RuntimeError('Known maintenance terminal lacks its original result')
        detail={'message':refresh._safe_text(value['message']),'maintenance_run_id':value['run_id'],
            'videos':value['synced_videos'],'comments':value['synced_comments'],
            'comment_failures':value['comment_sync_failures'],'login_healthy':value['login_healthy'],
            'error_code':value.get('error_code','')}
        settlement={'command_snapshot':command,'status':value['status'],'detail':detail}
        with refresh.connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            current=_row(db,TABLE,'account_uuid',hold['account_uuid'])
            if current['state']=='settled':continue
            if current['settlement'] is not None and json.loads(current['settlement'])!=settlement:
                raise RuntimeError('Original maintenance settlement changed')
            has_active_hold(db,hold['account_uuid'])
            db.execute(f"UPDATE {TABLE} SET state='settling',settlement=? WHERE account_uuid=?",(_json(settlement),hold['account_uuid']))
        with refresh.connect(path) as db:
            run=_row(db,'refresh_runs','run_id',hold['run_id'])
        if run['status'] in {'running','outcome_unknown'} and run['finished_at'] is None:
            refresh.finish(hold['run_id'],settlement['status'],detail,path=path)
        with refresh.connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            final=_row(db,'refresh_runs','run_id',hold['run_id'])
            if final['finished_at'] is None or final['status']!=settlement['status'] or json.loads(final['detail'])!=detail:
                raise RuntimeError('Original maintenance finish is not confirmed')
            db.execute(f"UPDATE {TABLE} SET state='settled',settled_at=? WHERE account_uuid=? AND settlement=?",
                (time.time(),hold['account_uuid'],_json(settlement)))
        results.append({'command_id':command['command_id'],'run_id':hold['run_id'],'state':'settled'})
    return results
