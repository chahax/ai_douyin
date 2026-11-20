"""Explicit disposition of one failed Fanqie login; never replay its request."""
import hashlib
import json
import time
from .browser_control import BrowserControlStore, BrowserControlRejected, _json


def dispose_login(accounts, command_id, authorization, *, expected_sha, exited_pids, pid_exists):
    decision=accounts.bindings()._evidence(authorization)
    if (decision.get('decision_source')!='explicit_user_statement'
            or decision.get('command_id')!=command_id
            or not decision.get('user_statement')):
        raise BrowserControlRejected('explicit_login_disposition_required','需要这条原登录任务的明确处置授权')
    launch=json.loads((accounts.folder(command_id)/'WORKER_PROCESS.json').read_text(encoding='utf-8'))
    if launch.get('command_id')!=command_id or launch.get('pid') not in exited_pids:
        raise BrowserControlRejected('original_worker_evidence_required','缺少原工作进程证据')
    if not exited_pids or any(type(pid) is not int or pid<=0 or pid_exists(pid) for pid in exited_pids):
        raise BrowserControlRejected('original_process_still_present','原进程未全部确认退出')
    store=BrowserControlStore(accounts.db)
    with store._db(write=True) as db:
        before=store._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',(command_id,)).fetchone())
        if (not before or before['kind']!='fanqie_login' or before['state']!='outcome_unknown'
                or not before['account_id'].startswith('fanqie:')
                or decision.get('resource_id')!=before['account_id']):
            raise BrowserControlRejected('original_login_unknown_required','仅可处置指定番茄未知登录任务')
        if hashlib.sha256(_json(before).encode()).hexdigest()!=expected_sha:
            raise BrowserControlRejected('command_changed','原任务已变化')
        owner=db.execute('SELECT * FROM browser_control_owners WHERE account_id=?',(before['account_id'],)).fetchone()
        if (not owner or owner['owner_id']!=before['owner_id'] or owner['generation']!=before['generation']
                or owner['binding_version']!=before['binding_version']):
            raise BrowserControlRejected('original_owner_changed','原owner已变化')
        pending=db.execute("SELECT 1 FROM browser_control_commands WHERE account_id=? AND command_id!=? AND state IN ('queued','running','paused','waiting_human','outcome_unknown') LIMIT 1",(before['account_id'],command_id)).fetchone()
        if pending:
            raise BrowserControlRejected('other_pending_command','同环境还有其他未决任务')
        result={'operator_cancelled_unknown_login':True,'original_outcome_known':False,
            'before_snapshot':before,'before_snapshot_sha256':expected_sha,
            'authorization':authorization,'observed_exited_pids':list(exited_pids),
            'cancelled_at':time.time(),'original_request_replayed':False}
        db.execute("UPDATE browser_control_commands SET state='failed',error_code='operator_cancelled_unknown_login',result=?,updated_at=? WHERE command_id=?",(_json(result),time.time(),command_id))
        db.execute("UPDATE browser_control_owners SET state='released',updated_at=? WHERE account_id=?",(time.time(),before['account_id']))
    return store.get(command_id)
