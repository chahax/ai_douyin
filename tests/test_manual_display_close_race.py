from types import SimpleNamespace as NS
import pytest

from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts import manual_window_visibility as visibility
from src.operations_accounts.browser_control import BrowserControlActor, BrowserControlStore


@pytest.mark.parametrize('failure',['closed','timeout','restore_unconfirmed'])
def test_actor_display_failure_never_creates_unknown_business_fence(tmp_path,monkeypatch,failure):
    monkeypatch.setattr('src.operations_accounts.interactive_desktop.require_interactive_desktop',lambda:None)
    store=BrowserControlStore(tmp_path/'control.db',clock=lambda:1000)
    calls=[]
    def display(action):
        calls.append(action)
        if failure=='restore_unconfirmed':return {'restored':False}
        raise TimeoutError('secret transport')if failure=='timeout'else RuntimeError('target closed')
    resource=NS(manual_tasks={},session=NS(config=NS(headless=False),get_page=lambda tab:NS(_cmd=display)))
    manual=store.submit('a','binding','manual','original',{'account_key':'key','account_uuid':'a'})
    actor=BrowserControlActor(store,'a','binding','owner',{
        'manual':lambda ctx,payload:bridge.BrowserCommandResult('waiting_human',{'tab_id':'tab'}),
        'read':bridge._adapter_read},context=resource)
    actor.run_next();resource.manual_tasks[manual['command_id']]='tab'
    before=store.get(manual['command_id'])
    payload={'account_key':'key','account_uuid':'a','method':visibility.METHOD,'operation_profile':None,
        'params':{'manual_id':manual['command_id'],'owner_id':actor.owner_id,'generation':actor.generation,'tab_id':'tab'}}
    request=store.submit('a','binding','read','display',payload,300)
    try:
        result=actor.run_next()
        assert result['command_id']==request['command_id'] and result['state']=='failed'
        assert result['error_code']=='manual_display_unconfirmed'
        assert store.get(manual['command_id'])==before
        assert calls==['reveal_manual_window']
        assert 'secret transport' not in str(result)
    finally:actor.stop_heartbeat()


def seed(store):
    owner=store.acquire_owner('a','binding','owner')
    manual=store.submit('a','binding','manual','manual',{'account_key':'key','account_uuid':'a'},200)
    store.claim_next('a','binding','owner',owner['generation'])
    store.transition(manual['command_id'],'owner',owner['generation'],'waiting_human',result={'tab_id':'tab'})
    payload={'account_key':'key','account_uuid':'a','method':visibility.METHOD,'operation_profile':None,
        'params':{'manual_id':manual['command_id'],'owner_id':'owner','generation':owner['generation'],'tab_id':'tab'}}
    display=store.submit('a','binding','read','display',payload,300)
    store.claim_next('a','binding','owner',owner['generation'])
    from src.operations_accounts.browser_execution_journal import before_handler
    before_handler(store,display['command_id'],'owner',owner['generation'])
    store.transition(display['command_id'],'owner',owner['generation'],'outcome_unknown',error_code='handler_exception:RuntimeError')
    store.complete_waiting(manual['command_id'],'owner',owner['generation'],
        {'window_closed':True,'identity_verified':False,'closed_tab_id':'tab','account_pause_changed':False})
    return manual,display


@pytest.mark.parametrize('change',['','publish','method','sha','extra','tab','owner','binding','not_closed','verified'])
def test_legacy_reconciliation_requires_exact_native_closure_and_keeps_original_evidence(tmp_path,change):
    store=BrowserControlStore(tmp_path/'control.db',clock=lambda:1000)
    manual,display=seed(store)
    with store._db(write=True)as db:
        if change in {'publish','sha','binding'}:
            field,value={'publish':('kind','publish'),'sha':('request_sha','changed'),'binding':('binding_version','changed')}[change]
            db.execute(f'UPDATE browser_control_commands SET {field}=? WHERE command_id=?',(value,display['command_id']))
        elif change in {'method','extra','owner'}:
            import json
            row=store._command(db.execute('select * from browser_control_commands where command_id=?',(display['command_id'],)).fetchone())
            p=row['payload']
            if change=='method':p['method']='sync_videos'
            elif change=='extra':p['params']['script']='forbidden'
            else:p['params']['owner_id']='foreign'
            # Even a self-consistent different request cannot use this exception.
            import hashlib
            from src.operations_accounts.browser_control import _json
            sha=hashlib.sha256(_json([row['account_id'],row['binding_version'],row['kind'],p,row['priority']]).encode()).hexdigest()
            db.execute('update browser_control_commands set payload=?,request_sha=? where command_id=?',(_json(p),sha,display['command_id']))
        elif change in {'tab','not_closed','verified'}:
            import json
            r={'window_closed':change!='not_closed','identity_verified':change=='verified',
               'closed_tab_id':'different'if change=='tab'else'tab'}
            db.execute('update browser_control_commands set result=? where command_id=?',(json.dumps(r),manual['command_id']))
    before=store.get(display['command_id']);closed=store.get(manual['command_id'])
    with store._db(write=True)as db:
        assert visibility.reconcile_closed_display(db,display['command_id'],1001) is (not change)
    result=store.get(display['command_id'])
    if not change:
        assert result['state']=='failed' and result['error_code']=='manual_window_closed'
        with store._db()as db:
            import json
            evidence=db.execute('select original_command,original_manual from manual_display_close_reconciliations').fetchone()
            assert json.loads(evidence[0])==before and json.loads(evidence[1])==closed
        with store._db(write=True)as db:
            assert not visibility.reconcile_closed_display(db,display['command_id'],1002)
    else:assert result==before
    assert store.get(manual['command_id'])==closed


def test_real_serial_queue_continues_same_user_manual_id_after_closed_display_settles(tmp_path):
    store=BrowserControlStore(tmp_path/'control.db',clock=lambda:1000)
    manual,display=seed(store)
    pending=store.submit('a','binding','manual','user-original-request',{'account_key':'key','account_uuid':'a'},200)
    assert store.claim_next('a','binding','owner',1) is None  # Production fence.
    visibility.reconcile_closed_displays(store,'a')
    result=store.claim_next('a','binding','owner',1)
    assert result['command_id']==pending['command_id'] and result['state']=='running'
    assert store.get(display['command_id'])['state']=='failed'
    assert len(store.snapshot('a')['commands'])==3
    assert store.get(manual['command_id'])['result']['identity_verified'] is False
