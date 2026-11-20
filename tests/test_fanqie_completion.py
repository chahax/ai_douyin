import sqlite3
import time
from pathlib import Path
import pytest
from test_fanqie_account_control import accounts,login
from src.operations_accounts.browser_control import BrowserControlRejected
from src.operations_accounts.fanqie_account_control import write_json
from src.operations_accounts.fanqie_completion import bounded_write,reconcile_saved_login


def pending_completion(a):
    env,cmd,result,session=login(a)
    folder=a.folder(cmd['command_id'])
    write_json(folder/'WORKER_PROCESS.json',dict(command_id=cmd['command_id'],pid=123))
    write_json(folder/'CLOSE_REQUEST.json',dict(command_id=cmd['command_id']))
    state=Path(env['storage_state_path']);state.parent.mkdir(parents=True,exist_ok=True);state.write_text('fixture saved session')
    with a.connection(True) as db:
        db.execute("UPDATE browser_control_commands SET state='running',result=NULL WHERE command_id=?",(cmd['command_id'],))
        db.execute("UPDATE browser_control_owners SET state='active' WHERE account_id=?",(env['resource_id'],))
    return env,cmd


def test_reconciles_only_saved_original_login(accounts):
    env,cmd=pending_completion(accounts)
    result=reconcile_saved_login(accounts,cmd['command_id'],pid_exists=lambda pid:False)
    assert result['state']=='succeeded'
    assert result['result']['before_snapshot']['state']=='running'
    assert not result['result']['platform_request_replayed']
    binding=accounts.confirm(cmd['command_id'],'uid:12345','fixture explicit')
    assert binding['environment_key']==env['environment_key']


@pytest.mark.parametrize('bad',['live','missing_state','stale'])
def test_refuses_incomplete_reconciliation(accounts,bad):
    env,cmd=pending_completion(accounts)
    if bad=='missing_state': Path(env['storage_state_path']).unlink()
    if bad=='stale':
        import json
        path=accounts.folder(cmd['command_id'])/'IDENTITY_PROBE.json'
        value=json.loads(path.read_text());value['observed_at']=time.time()-301;write_json(path,value)
    with pytest.raises(BrowserControlRejected):
        reconcile_saved_login(accounts,cmd['command_id'],pid_exists=lambda pid:bad=='live')
    assert accounts.latest_command(env['resource_id'])['state']=='running'


def test_write_retry_never_reexecutes_business():
    calls=[]
    def commit():
        calls.append(1)
        if len(calls)==1:
            exc=sqlite3.OperationalError('fixture locked');exc.sqlite_errorcode=sqlite3.SQLITE_BUSY;raise exc
        return 'committed'
    assert bounded_write(commit,seconds=1)=='committed' and len(calls)==2
