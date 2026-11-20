"""Private owner/SQLite protocol; normal host closure remains the settler."""
import json
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts.browser_control import BrowserControlActor,BrowserControlStore
from src.operations_accounts.manual_tab_closure import settle_closed_manual_tabs
from src.operations_accounts import manual_session_finish_v1 as leaf


@pytest.mark.parametrize('fault',['none','save_unconfirmed','close_ack_lost'])
def test_save_ack_precedes_exact_close_and_only_later_normal_host_settles(tmp_path,monkeypatch,fault):
    store=BrowserControlStore(tmp_path/'browser.db')
    actor=BrowserControlActor(store,'private-account','binding','backend:123:private',{}).start()
    try:
        task=store.submit(actor.account_id,'binding','manual','private-original',{},200)
        store.claim_next(actor.account_id,'binding',actor.owner_id,actor.generation)
        store.transition(task['command_id'],actor.owner_id,actor.generation,'waiting_human',result={'tab_id':'original-manual'})
        scope=dict(account_key='private-key',account_id=actor.account_id,owner_id=actor.owner_id,generation=actor.generation,binding_version='binding',
            manual_command_id=task['command_id'],manual_request_sha256=task['request_sha'],tab_id='original-manual')
        monkeypatch.setattr(leaf,'RUN',tmp_path);monkeypatch.setattr(leaf,'SCOPE',scope)
        events=[];closed=[False]
        state_path=str(tmp_path/'never-read-storage-state.json')
        class Session:
            _proc=NS(poll=lambda:None)
            config=NS(headless=False,storage_state_path=state_path)
            def worker_failure(self):return ''
            def window_status(self):
                events.append('window_status')
                return dict(context_closed=False,tabs=[dict(tab_id='original-manual',role='manual',closed=closed[0]),dict(tab_id='user-other',role='unclaimed',closed=False,url='https://www.douyin.com/')])
            def cmd(self,action,**kwargs):
                assert action=='save_state' and kwargs==dict(path=state_path);events.append('save_state')
                return dict(state_saved=fault!='save_unconfirmed')
            def close_tab(self,tab):
                assert tab=='original-manual' and events[-1]=='save_state';events.append('close_tab');closed[0]=True
                if fault=='close_ack_lost':raise RuntimeError('close acknowledgement lost')
                return dict(tab_id=tab,closed=True)
            def save_storage_state(self):events.append('normal_host_save')
        session=Session();resource=NS(session=session,manual_tasks={task['command_id']:'original-manual'},console_tasks={},
            context=NS(storage_state_path=state_path),headless=False,shutdown=lambda:events.append('forbidden_shutdown'))
        def put(path,value):
            path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8');return leaf.reference(path)
        authority=put(tmp_path/'USER_AUTHORIZATION.json',dict(account_key=scope['account_key'],account_uuid=actor.account_id,expected_public_uid='75891235130'))
        completion=put(tmp_path/'PRIVATE_COMPLETION.json',dict(status='confirmed',confirmed=True))
        permit=put(tmp_path/'MANUAL_SESSION_FINISH_PERMIT.json',dict(schema='original_manual_session_finish_permit/v1',scope=scope,cleanup_authority=authority,
            completion_ref=completion,helper_source=leaf.reference(leaf.__file__),save_state_calls_allowed=1,close_tab_calls_allowed=1,account_recovery_allowed=False))
        def guard():actor._assert_thread();actor._check_owner()
        def verify(ref):return leaf.read(ref)==dict(status='confirmed',confirmed=True)
        with pytest.raises(ValueError,match='success_not_verified'):
            leaf.close_original_manual_once(actor,resource,permit_ref=permit,outdir=tmp_path/'manual_finish_001',guard=guard,verify_completion=lambda ref:False)
        assert events==[] and not (tmp_path/'MANUAL_SESSION_FINISH_CLAIM.json').exists()
        result=leaf.read(leaf.close_original_manual_once(actor,resource,permit_ref=permit,outdir=tmp_path/'manual_finish_001',guard=guard,verify_completion=verify))
        assert store.get(task['command_id'])['state']=='waiting_human' and resource.manual_tasks=={task['command_id']:'original-manual'}
        assert events==['window_status','save_state']+([] if fault=='save_unconfirmed' else ['close_tab'])
        assert not result['account_pause_changed'] and not result['recovery_requested'] and not result['manual_completed_by_helper']
        assert result['save_state_dispatches']==1 and result['close_tab_dispatches']==(0 if fault=='save_unconfirmed' else 1)
        previous=list(events)
        with pytest.raises(FileExistsError):
            leaf.close_original_manual_once(actor,resource,permit_ref=permit,outdir=tmp_path/'manual_finish_001',guard=guard,verify_completion=verify)
        assert events==previous
        if fault=='none':
            assert result['status']=='waiting_natural_manual_settlement'
            assert not settle_closed_manual_tabs(actor,resource,session.window_status())
            settled=store.get(task['command_id'])
            assert settled['state']=='succeeded' and settled['result']['window_closed'] and settled['result']['account_pause_changed'] is False
            assert resource.manual_tasks=={} and events[-1]=='normal_host_save' and 'forbidden_shutdown' not in events
        else:
            assert result['schema']=='original_manual_session_finish_unknown/v1' and result['automatic_replay_allowed'] is False
    finally:actor.stop_heartbeat()
