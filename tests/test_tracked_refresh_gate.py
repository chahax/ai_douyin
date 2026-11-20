import pytest
from test_account_handling_continuation import backend,complete
from test_queued_refresh_recovery import waiting
from src.scheduler import tracked_refresh_gate as tracked


@pytest.mark.parametrize('state',['running','terminal','stale_owner','unknown','changed'])
def test_expired_original_queue_lease_never_overrules_fresh_native_execution(waiting,state):
    ar,path,store,command,run=waiting
    assert complete(ar,path)['accepted']
    token=ar._claim_recovery('A','a',path=path)
    assert ar._finish_recovery('A','a',token,healthy=True,status='active',path=path)
    owner=store.acquire_owner('A','binding','owner')
    store.claim_next('A','binding','owner',owner['generation'])
    from src.operations_accounts.browser_execution_journal import before_handler
    before_handler(store,command['command_id'],'owner',owner['generation'])
    now=1001
    if state=='terminal':
        store.transition(command['command_id'],'owner',owner['generation'],'succeeded',result={'known_terminal':True})
    elif state=='unknown':
        store.transition(command['command_id'],'owner',owner['generation'],'outcome_unknown')
    elif state=='changed':
        with store._db(write=True)as db:db.execute("update browser_control_commands set request_sha='changed'")
    elif state=='stale_owner':now=1200
    before=store.get(command['command_id'])
    assert ar.claim_smart('A','a',now=now,path=path)is None
    after=ar.snapshot(path)
    control=after['controls'][0]
    if state in {'running','terminal'}:
        assert control['state']=='active' and not control['error_code']
        assert after['runs'][0]['status']=='waiting_original'
    else:
        assert control['state']=='paused' and control['error_code']=='outcome_unknown'
    assert store.get(command['command_id'])==before


def test_live_stateless_gate_uses_same_fresh_original_evidence(waiting,monkeypatch):
    ar,path,store,command,run=waiting
    assert complete(ar,path)['accepted'];token=ar._claim_recovery('A','a',path=path)
    assert ar._finish_recovery('A','a',token,healthy=True,status='active',path=path)
    owner=store.acquire_owner('A','binding','owner');store.claim_next('A','binding','owner',owner['generation'])
    previous=ar._gate
    monkeypatch.setattr(ar,'_gate',previous)
    tracked.install_live_gate(ar);first=ar._gate;tracked.install_live_gate(ar);assert ar._gate is first
    assert ar.claim_smart('A','a',now=1001,path=path)is None
    assert ar.snapshot(path)['controls'][0]['state']=='active'
