"""Only original, proven-unexecuted refresh waits may cross identity recovery."""
import sqlite3
import hashlib
from pathlib import Path


def reference(db, run_id):
    from .browser_task_tracking import exists, TABLE, read_command
    if not run_id or not exists(db):
        return None
    run=db.execute('SELECT * FROM refresh_runs WHERE run_id=?',(run_id,)).fetchone()
    if not run or run['status']!='waiting_original' or run['finished_at'] is not None:
        return None
    owner=db.execute('SELECT * FROM refresh_accounts WHERE account_uuid=?',(run['account_uuid'],)).fetchone()
    policy=db.execute('SELECT enabled FROM refresh_policy WHERE id=1').fetchone()
    link=db.execute(f"SELECT * FROM {TABLE} WHERE run_id=? AND state='waiting'",(run_id,)).fetchone()
    if (not owner or owner['run_id']!=run_id or owner['account_key']!=run['account_key']
            or not policy or not policy['enabled'] or not link or link['account_uuid']!=run['account_uuid']):
        return None
    try:
        command=read_command(dict(link))
        from src.operations_accounts.browser_control import _json
        digest=hashlib.sha256(_json([command['account_id'],command['binding_version'],command['kind'],command['payload'],command['priority']]).encode()).hexdigest()
        if (command['kind']!='maintenance' or command['payload'].get('mode')!='post-publish'
                or digest!=command['request_sha']
                or command['payload'].get('account_key')!=run['account_key']
                or command['state']!='queued' or command['owner_id'] is not None
                or command['generation'] is not None or command['cursor'] is not None or command['result'] is not None):
            return None
        # Missing legacy entry is acceptable only for this known pre-dispatch
        # shape. Any actual handler-entry evidence forbids this exception.
        with sqlite3.connect(Path(link['browser_path']).resolve().as_uri()+'?mode=ro',uri=True,timeout=1) as browser:
            if browser.execute("SELECT 1 FROM sqlite_master WHERE name='browser_control_execution'").fetchone():
                stage=browser.execute('SELECT handler_entered FROM browser_control_execution WHERE command_id=?',(command['command_id'],)).fetchone()
                if stage and stage[0]:
                    return None
        return {'account_uuid':run['account_uuid'],'run_id':run_id,'command_id':command['command_id'],
                'request_sha':command['request_sha'],'binding_version':command['binding_version']}
    except (sqlite3.Error,ValueError,KeyError,OSError):
        return None


def snapshot(db):
    values=[]
    for row in db.execute("SELECT run_id FROM refresh_runs WHERE status='waiting_original' AND finished_at IS NULL"):
        value=reference(db,row['run_id'])
        if value:
            values.append(value)
    return values
