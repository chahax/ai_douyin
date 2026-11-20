"""Attached browser execution owns its dispatch lifetime, not the old queue lease."""
import hashlib
from pathlib import Path
import sqlite3


def waiting_state(db, account_uuid, now):
    from .browser_task_tracking import exists, TABLE, read_command
    from src.operations_accounts.browser_control import _json
    if not exists(db):return None
    links=[dict(r)for r in db.execute(f"SELECT * FROM {TABLE} WHERE account_uuid=? AND state='waiting'",(account_uuid,))]
    if not links:return None
    if len(links)!=1:return 'outcome_unknown'
    link=links[0]
    try:
        c=read_command(link)
        digest=hashlib.sha256(_json([c['account_id'],c['binding_version'],c['kind'],c['payload'],c['priority']]).encode()).hexdigest()
        if (c['kind']!='maintenance' or c['payload'].get('mode')!='post-publish'
                or c['payload'].get('account_uuid')!=account_uuid or digest!=c['request_sha']):
            return 'outcome_unknown'
        if c['state'] in {'succeeded','failed'}:return 'terminal_receipt_pending'
        if c['state']=='queued' and c['owner_id'] is None and c['generation'] is None:
            return 'queued_original'
        if c['state'] in {'paused','waiting_human'}:return 'original_suspended'
        if c['state']!='running':return 'outcome_unknown'
        with sqlite3.connect(Path(link['browser_path']).resolve().as_uri()+'?mode=ro',uri=True,timeout=1)as browser:
            browser.row_factory=sqlite3.Row
            owner=browser.execute('SELECT * FROM browser_control_owners WHERE account_id=?',(account_uuid,)).fetchone()
            stage=browser.execute('SELECT * FROM browser_control_execution WHERE command_id=?',(c['command_id'],)).fetchone()
        if (not owner or owner['state']!='active' or owner['owner_id']!=c['owner_id']
                or owner['generation']!=c['generation'] or owner['binding_version']!=c['binding_version']
                or not 0<=now-owner['heartbeat']<=90 or not stage
                or stage['request_sha']!=c['request_sha'] or stage['owner_id']!=c['owner_id']
                or stage['generation']!=c['generation'] or not 0<=now-stage['updated_at']<=3600):
            return 'outcome_unknown'
        return 'owned_original_running'
    except (sqlite3.Error,ValueError,KeyError,OSError):
        return 'outcome_unknown'


def install_live_gate(refresh=None):
    """Replace only a stateless metadata gate; never reload a scheduler/worker."""
    if refresh is None:
        from . import account_refresh as refresh
    previous=refresh._gate
    if getattr(previous,'_tracked_refresh_gate',False):return
    def gate(db,account_uuid,account_key,now):
        control=db.execute('SELECT account_key,state FROM account_controls WHERE account_uuid=?',(account_uuid,)).fetchone()
        if control and control['account_key']==account_key and control['state']=='active':
            state=waiting_state(db,account_uuid,now)
            if state is not None:
                if state=='outcome_unknown':
                    refresh._pause(db,account_uuid,account_key,'原浏览器请求结果或执行证据待核对，保留原任务；未重新派发。','outcome_unknown',now)
                return False
        return previous(db,account_uuid,account_key,now)
    gate._tracked_refresh_gate=True
    refresh._gate=gate
