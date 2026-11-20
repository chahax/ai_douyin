"""Local completion writes and independent reconciliation of saved login evidence."""
import hashlib
import json
import sqlite3
import time
from .browser_control import BrowserControlStore, BrowserControlRejected, _json


def bounded_write(operation, seconds=10):
    deadline=time.monotonic()+seconds
    while True:
        try:
            return operation()
        except sqlite3.Error as exc:
            code=getattr(exc,'sqlite_errorcode',None)
            if not isinstance(code,int) or code & 255 not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED) or time.monotonic()>=deadline:
                raise
            time.sleep(.25)


class FanqieControlStore(BrowserControlStore):
    """Retry a rolled-back local transaction, never its browser handler."""
    def transition(self,*args,**kwargs):
        return bounded_write(lambda:super(FanqieControlStore,self).transition(*args,**kwargs))
    def release_owner(self,*args,**kwargs):
        return bounded_write(lambda:super(FanqieControlStore,self).release_owner(*args,**kwargs))


def reconcile_saved_login(accounts,command_id,*,pid_exists):
    from .fanqie_account_control import write_json
    folder=accounts.folder(command_id)
    launch=json.loads((folder/'WORKER_PROCESS.json').read_text(encoding='utf-8'))
    if launch.get('command_id')!=command_id or pid_exists(launch['pid']):
        raise BrowserControlRejected('login_worker_not_exited','原工作进程尚未退出')
    if not (folder/'CLOSE_REQUEST.json').is_file():
        raise BrowserControlRejected('original_close_request_required','没有原窗口保存关闭请求')
    raw=(folder/'IDENTITY_PROBE.json').read_bytes()
    probe=json.loads(raw)
    command=BrowserControlStore(accounts.db).get(command_id)
    if not command or command['kind']!='fanqie_login' or command['state']!='running':
        raise BrowserControlRejected('unfinalized_login_required','仅确认尚未结算的原登录任务')
    env=accounts.get(command['account_id']);accounts.check_association(env)
    if (probe.get('schema')!='platform_identity_probe/v1' or probe.get('verified') is not True
            or probe.get('platform')!='fanqie' or probe.get('challenge') is not False
            or probe.get('identity_source')!='platform_account_id'
            or not str(probe.get('platform_identity_key','')).startswith('uid:')
            or probe.get('environment_key')!=env['environment_key']
            or not 0<=time.time()-probe.get('observed_at',0)<=300):
        raise BrowserControlRejected('saved_identity_not_fresh','原身份凭据无效或过期')
    from pathlib import Path
    state=Path(env['storage_state_path'])
    if not state.is_file() or state.stat().st_mtime<probe['observed_at']:
        raise BrowserControlRejected('saved_session_required','缺少原核验之后的会话保存证据')
    proof={'path':str((folder/'IDENTITY_PROBE.json').resolve()),'sha256':hashlib.sha256(raw).hexdigest()}
    result={'probe_evidence':proof,'identity':probe['platform_identity_key'],'binding_confirmed':False,
        'independent_saved_login_reconciliation':True,'original_terminal_write_missing':True,
        'before_snapshot':command,'platform_request_replayed':False}
    audit=write_json(folder/'COMPLETION_RECONCILIATION.json',{'observed_at':time.time(),'result':result})
    def settle():
        store=BrowserControlStore(accounts.db)
        with store._db(write=True) as db:
            current=store._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',(command_id,)).fetchone())
            owner=db.execute('SELECT * FROM browser_control_owners WHERE account_id=?',(command['account_id'],)).fetchone()
            if current!=command or not owner or owner['owner_id']!=command['owner_id'] or owner['generation']!=command['generation']:
                raise BrowserControlRejected('original_completion_changed','原任务或owner已变化')
            if owner['binding_version']!=env['binding_version'] or not 0<=time.time()-probe['observed_at']<=300:
                raise BrowserControlRejected('original_completion_changed','原绑定变化或身份凭据过期')
            if db.execute("SELECT 1 FROM browser_control_commands WHERE account_id=? AND command_id!=? AND state IN ('queued','running','paused','waiting_human','outcome_unknown')",(command['account_id'],command_id)).fetchone():
                raise BrowserControlRejected('other_pending_command','存在其他未决任务')
            from .browser_execution_journal import finish
            finish(db,current,'succeeded',None,time.time())
            db.execute("UPDATE browser_control_commands SET state='succeeded',result=?,error_code=NULL,updated_at=? WHERE command_id=?",(_json(dict(result,reconciliation_evidence=audit)),time.time(),command_id))
            db.execute("UPDATE browser_control_owners SET state='released',updated_at=? WHERE account_id=?",(time.time(),command['account_id']))
        return store.get(command_id)
    return bounded_write(settle)
