"""Desktop admission only. Never opens a browser or touches production files."""
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from src.operations_accounts import fanqie_account_control as a
from src.operations_accounts import interactive_desktop as desktop
from src.operations_accounts.browser_control import BrowserControlRejected


def fake_accounts(tmp_path,monkeypatch):
    for name in ('DB','PROFILES','EVIDENCE'):monkeypatch.setattr(a,name,tmp_path/name)
    return NS(db=a.DB,profiles=a.PROFILES,evidence=a.EVIDENCE,folder=lambda command:tmp_path/'evidence'/command,
              ledger_path=tmp_path/'p0.db',_ledger_path=a.FanqieAccounts._ledger_path)


def test_nondefault_login_rejected_before_claim_and_Popen(tmp_path,monkeypatch):
    accounts=fake_accounts(tmp_path,monkeypatch)
    monkeypatch.setattr(desktop,'current_desktop_name',lambda:'CodexSandboxDesktop-test')
    monkeypatch.setattr(a.subprocess,'Popen',lambda *args,**kwargs:pytest.fail('No launch'))
    command=dict(state='queued',command_id='original123',kind='fanqie_login',account_id='fanqie:r')
    with pytest.raises(BrowserControlRejected,match='正常桌面'):a.launch_worker(command,accounts)
    assert not accounts.folder(command['command_id']).exists()


def test_Default_login_allowed_and_existing_running_not_reopened(tmp_path,monkeypatch):
    accounts=fake_accounts(tmp_path,monkeypatch);calls=[]
    monkeypatch.setattr(desktop,'current_desktop_name',lambda:'Default')
    monkeypatch.setattr(a.subprocess,'Popen',lambda *args,**kwargs:calls.append(args) or NS(pid=123456789))
    command=dict(state='queued',command_id='original123',kind='fanqie_login',account_id='fanqie:r')
    assert a.launch_worker(command,accounts)['status']=='launched' and len(calls)==1
    monkeypatch.setattr(desktop,'current_desktop_name',lambda:'CodexSandboxDesktop-test')
    assert a.launch_worker(dict(command,state='running'),accounts)['status']=='running' and len(calls)==1


def test_headless_business_unaffected_by_isolated_desktop(tmp_path,monkeypatch):
    accounts=fake_accounts(tmp_path,monkeypatch)
    monkeypatch.setattr(desktop,'current_desktop_name',lambda:'CodexSandboxDesktop-test')
    monkeypatch.setattr(a.subprocess,'Popen',lambda *args,**kwargs:NS(pid=123456789))
    command=dict(state='queued',command_id='original123',kind='fanqie_promotion_list',account_id='fanqie:r')
    assert a.launch_worker(command,accounts)['status']=='launched'


def test_CLI_open_guard_is_before_queue(monkeypatch):
    from scripts import run_fanqie_account as cli
    monkeypatch.setattr(cli.sys,'argv',['run_fanqie_account.py','open','--resource','fanqie:r'])
    monkeypatch.setattr(cli,'FanqieAccounts',lambda:NS(queue=lambda *args,**kwargs:pytest.fail('No queue')))
    monkeypatch.setattr(desktop,'current_desktop_name',lambda:'CodexSandboxDesktop-test')
    with pytest.raises(BrowserControlRejected):cli.main()


def test_CLI_worker_passes_the_configured_accounts_instance(monkeypatch,tmp_path):
    from scripts import run_fanqie_account as cli
    from types import SimpleNamespace
    configured=SimpleNamespace(ledger_path=tmp_path/'trusted-ledger.db')
    calls=[]
    monkeypatch.setattr(cli.sys,'argv',['run_fanqie_account.py','worker','--resource','fanqie:fixture',
                                      '--ledger-path',str(configured.ledger_path)])
    def build(**kwargs):
        assert kwargs==dict(ledger_path=configured.ledger_path)
        return configured
    monkeypatch.setattr(cli,'FanqieAccounts',build)
    monkeypatch.setattr(cli,'run_owner',lambda resource,*,accounts:calls.append((resource,accounts)) or {'state':'failed'})
    monkeypatch.setattr(cli,'launch_worker',lambda *a,**k:pytest.fail('worker entry must not relaunch'))
    cli.main()
    assert calls==[('fanqie:fixture',configured)]
