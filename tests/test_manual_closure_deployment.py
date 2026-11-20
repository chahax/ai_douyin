import json
from types import SimpleNamespace as NS
import pytest


@pytest.mark.parametrize('case',['original','wrong_process','wrong_thread'])
def test_installer_changes_only_original_poll_and_defers_browser_io_to_owner(tmp_path,monkeypatch,case):
    from src.operations_accounts import manual_closure_deployment as deployment
    from src.operations_accounts import manual_tab_closure
    arm=tmp_path/'arm.json'
    config={'backend_pid':123,'account_key':'novel','account_id':'a','owner_id':'backend:123:abc','generation':2,'manual_id':'original'}
    arm.write_text(json.dumps(config))
    monkeypatch.setattr(deployment,'ROOT',tmp_path)
    monkeypatch.setattr(deployment,'ARM',arm)
    monkeypatch.setattr(deployment,'CHECKPOINT',tmp_path)
    monkeypatch.setattr(deployment.os,'getpid',lambda:456 if case=='wrong_process'else 123)
    events=[]
    previous=lambda actor,resource:events.append('previous')
    namespace={'_poll_manual_windows':previous}
    exec(compile('def _host(key): pass',str(tmp_path/'src/operations_accounts/browser_control_runtime.py'),'exec'),namespace)
    thread=NS(name='AccountBrowser-other'if case=='wrong_thread'else'AccountBrowser-novel',
        _target=namespace['_host'],_args=('novel',),is_alive=lambda:True)
    monkeypatch.setattr(deployment.threading,'enumerate',lambda:[thread])
    monkeypatch.setattr(manual_tab_closure,'settle_closed_manual_tabs',lambda actor,resource,status:events.append('owner-close-check')or True)
    deployment.install_if_armed()
    assert events==[]
    if case=='original':
        assert namespace['_poll_manual_windows'] is not previous
        actor=NS(account_id='a',owner_id='backend:123:abc',generation=2)
        resource=NS(manual_tasks={'original':'tab'},session=NS(_proc=object(),window_status=lambda:events.append('native-status')or{'tabs':[]}))
        namespace['_poll_manual_windows'](actor,resource)
        assert events==['native-status','owner-close-check']
    else:
        assert namespace['_poll_manual_windows'] is previous
