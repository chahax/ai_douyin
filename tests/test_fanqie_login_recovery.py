import hashlib
import pytest
from test_fanqie_account_control import accounts,login
from src.operations_accounts.browser_control import _json,BrowserControlRejected
from src.operations_accounts.fanqie_account_control import write_json
from src.operations_accounts.fanqie_login_recovery import dispose_login


def setup(accounts):
    env,cmd,result,session=login(accounts,crash=True)
    proof=write_json(accounts.folder(cmd['command_id'])/'AUTHORIZATION.json',dict(decision_source='explicit_user_statement',command_id=cmd['command_id'],resource_id=env['resource_id'],user_statement='fixture explicit cancellation'))
    write_json(accounts.folder(cmd['command_id'])/'WORKER_PROCESS.json',dict(command_id=cmd['command_id'],pid=123))
    return env,cmd,result,proof,hashlib.sha256(_json(result).encode()).hexdigest()


def test_exact_disposition_preserves_original_and_allows_new_id(accounts):
    env,cmd,result,proof,sha=setup(accounts)
    closed=dispose_login(accounts,cmd['command_id'],proof,expected_sha=sha,exited_pids=[123,124],pid_exists=lambda pid:False)
    assert closed['state']=='failed' and closed['result']['before_snapshot']==result
    assert closed['result']['original_outcome_known'] is False
    assert accounts.queue(env['resource_id'])['command_id']!=cmd['command_id']


@pytest.mark.parametrize('reason',['live','changed','wrong_grant'])
def test_disposition_rejects_without_mutation(accounts,reason):
    env,cmd,result,proof,sha=setup(accounts)
    if reason=='wrong_grant':
        proof=write_json(accounts.folder(cmd['command_id'])/'OTHER_AUTH.json',dict(decision_source='explicit_user_statement',command_id='another',user_statement='fixture'))
    with pytest.raises(BrowserControlRejected):
        dispose_login(accounts,cmd['command_id'],proof,expected_sha='changed' if reason=='changed' else sha,exited_pids=[123],pid_exists=lambda pid:reason=='live')
    assert accounts.latest_command(env['resource_id'])==result
