import json
import os
from types import SimpleNamespace as NS
import psutil
import pytest

from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts import paused_claim_deployment as deployment


@pytest.mark.parametrize('match',[True,False])
def test_installs_only_on_exact_owner_then_protects_future_owners(monkeypatch,tmp_path,match):
    arm=tmp_path/'arm.json'
    config={'backend_pid':os.getpid(),'backend_create_time':psutil.Process().create_time(),
        'account_key':'key','account_id':'a','owner_id':'owner','generation':22}
    arm.write_text(json.dumps(config),encoding='utf8')
    monkeypatch.setattr(deployment,'ARM',arm);monkeypatch.setattr(deployment,'HERE',tmp_path)
    thread=NS(name='AccountBrowser-key',_target=bridge._host,_args=('key',),is_alive=lambda:True)
    monkeypatch.setattr(deployment.threading,'enumerate',lambda:[thread])
    events=[]
    previous=lambda actor,resource:events.append('ordinary-poll')
    monkeypatch.setattr(bridge,'_poll_manual_windows',previous)
    monkeypatch.setattr('src.operations_accounts.paused_browser_claims.install',lambda a,r:events.append('install-claim-guard'))
    deployment.install_if_armed()
    actor=NS(account_id='a',owner_id='owner',generation=22 if match else 23,
        _assert_thread=lambda:events.append('owner-thread'),_check_owner=lambda:events.append('owner-fence'))
    resource=NS(manual_tasks={'original-manual':'original-tab'})
    bridge._poll_manual_windows(actor,resource)
    if match:
        assert events==['owner-thread','owner-fence','install-claim-guard','ordinary-poll']
        assert getattr(bridge._poll_manual_windows,'_paused_claim_runtime',False)
        assert json.loads((tmp_path/'CLAIM_GUARD_INSTALLED.json').read_text())['browser_operations']is False
        future=NS(account_id='future',owner_id='next-owner',generation=1)
        bridge._poll_manual_windows(future,NS(manual_tasks={}))
        assert events[-2:]==['install-claim-guard','ordinary-poll']
    else:
        assert events==['ordinary-poll']
        assert not (tmp_path/'CLAIM_GUARD_INSTALLED.json').exists()
    assert resource.manual_tasks=={'original-manual':'original-tab'}
