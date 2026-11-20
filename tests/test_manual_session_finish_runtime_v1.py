"""Strict completion semantics with private durable owner/command state."""
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts.browser_control import BrowserControlActor,BrowserControlStore
from src.operations_accounts import manual_session_finish_runtime_v1 as runtime


@pytest.mark.parametrize('change',['none','wrong_native_date','wrong_claim_subject'])
def test_completion_checks_actual_native_records_claim_and_private_terminal_command(tmp_path,monkeypatch,change):
    monkeypatch.setattr(runtime,'ROOT',tmp_path);run=tmp_path/'run';run.mkdir();monkeypatch.setattr(runtime,'RUN',run)
    db=tmp_path/'private-browser.db';store=BrowserControlStore(db)
    resource='fanqie:52ce7e06afc9451b8a81bfd9269ad94e';identity='uid:2521598930983028';env=resource+':browser';owner='backend:123:fanqie-private'
    store.acquire_owner(resource,'fanqie-binding',owner)
    def put(path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True),encoding='utf8');return runtime.reference(path)
    authority=put(run/'USER_AUTHORIZATION.json',dict(fanqie_resource_id=resource,fanqie_identity=identity,book_id='7302660145530539062',book_name='你敢惹我？我有六个反派儿子',preferred_recreated_alias='从旧饭桌开始改命'))
    config=dict(authority=authority,browser_db=str(db),account_id='account:9158f1d29f70eff9819c46b4')
    verified=put(run/'VERIFIED_PUBLICATION.json',dict(schema='verified_declared_publication/v1',post_verified=True,numeric_duration_verified=True,
        account_uuid=config['account_id'],expected_public_uid='75891235130',**{k:runtime.PUBLICATION[k] for k in ('post_id','canonical_url','native_created_epoch')}))
    request=dict(schema='fanqie_cleanup_rebind_request/v1',action='bind_new_publication',draft_only=False,authority=authority,resource_id=resource,
        platform_identity_key=identity,binding_version='fanqie-binding',environment_key=env,book_id='7302660145530539062',book_name='你敢惹我？我有六个反派儿子',
        alias='从旧饭桌开始改命',publish_type='AIGC',new_publication=runtime.PUBLICATION,new_native_identity=runtime.NATIVE_ID,verified_publication=verified,original_records=[])
    request_ref=put(run/'REQUEST.json',request)
    task=store.submit(resource,'fanqie-binding','fanqie_cleanup_rebind','private-final-backfill',dict(environment_key=env,request=request_ref))
    store.claim_next(resource,'fanqie-binding',owner,1)
    subject={k:request[k] for k in ('resource_id','platform_identity_key','binding_version','environment_key')}
    subject.update(owner_id=owner,generation=1,task_id=task['command_id'])
    folder=tmp_path/'data/fanqie_account_control/commands'/task['command_id']
    target=dict(book_id=request['book_id'],book_name=request['book_name'],alias=request['alias'],publish_type='AIGC')
    preflight=put(folder/'replacement/BACKFILL_PREFLIGHT.json',dict(schema='fanqie_replacement_backfill_preflight/v1',request=request_ref,subject=subject,target=target,
        native_identity=runtime.NATIVE_ID,new_publication=runtime.PUBLICATION,actual_form=dict(eligible=True,scope_count=1,input_count=2,other_inputs=[],
            identity=dict(book_name=request['book_name'],alias=request['alias'],aigc=True),date=dict(value='2026-11-18'),link=dict(value=runtime.PUBLICATION['canonical_url']))))
    claim_subject=dict(subject,generation=2) if change=='wrong_claim_subject' else subject
    claim=put(run/'REPLACEMENT_BACKFILL_SUBMIT_CLAIM.json',dict(schema='fanqie_replacement_backfill_claim/v1',request=request_ref,subject=claim_subject,preflight=preflight,
        target=target,automatic_replay_allowed=False))
    observed_day='2026-11-17' if change=='wrong_native_date' else '2026-11-18'
    records=[dict(canonical_url=runtime.PUBLICATION['canonical_url'],publish_date=observed_day)]
    readback=put(folder/'replacement/READBACK_RECORDS.json',dict(scope=dict(eligible=True,retained_link_observed=True,
        scope=dict(visible_text=request['book_name']+' '+request['alias']+' AIGC\n发文时间 '+observed_day+'\n发文链接 '+runtime.PUBLICATION['canonical_url'])),records=records))
    value=dict(status='new_backfill_confirmed',business_confirmed=True,native_result=dict(status='new_backfill_confirmed',submitted=True,
        new_native_identity=runtime.NATIVE_ID,automatic_retry=False,claim=claim,readback=readback,records=records))
    result=put(folder/'CLEANUP_REBIND_RESULT.json',dict(schema='fanqie_cleanup_rebind_command_result/v1',request=request_ref,subject=subject,broker_state='succeeded',result=value))
    receipt=put(folder/'CLEANUP_REBIND_RESULT_BINDING.json',dict(schema='fanqie_cleanup_rebind_result_binding/v1',request=request_ref,subject=subject,result=result))
    completion=put(run/'COMPLETION.json',dict(schema='verified_fanqie_cleanup_rebind_completion/v1',result=result,receipt=receipt))
    store.transition(task['command_id'],owner,1,'succeeded',result=dict(value,result_evidence=result))
    before=db.read_bytes()
    if change=='none':
        assert runtime.verify_completion(completion,config) is True
        # The cached V10 bootstrap remains identical; only its fixed cleanup
        # path whitelist changes, never the parent publisher handler.
        project=Path(__file__).resolve().parents[1]
        current=(project/'src/operations_accounts/manual_republication_runtime_v10.py').read_text(encoding='utf8')
        prior=(project/'data/production_trials/fanqie_cleanup_rebind_20261118_v1/bootstrap_before_manual_finish/manual_republication_runtime_v10.py').read_text(encoding='utf8')
        assert current.replace(",ROOT/'src/operations_accounts/manual_session_finish_runtime_v1.py'",'')==prior
    else:
        with pytest.raises(ValueError,match='native_date_link_readback_mismatch' if change=='wrong_native_date' else 'original_backfill_claim_required'):
            runtime.verify_completion(completion,config)
    assert db.read_bytes()==before


def test_caller_preserves_real_leaf_unconfirmed_save_without_close_or_settlement(tmp_path,monkeypatch):
    from src.operations_accounts import manual_session_finish_v1 as leaf
    store=BrowserControlStore(tmp_path/'private.db');actor=BrowserControlActor(store,'private-account','binding','backend:123:manual-private',{}).start()
    try:
        task=store.submit(actor.account_id,'binding','manual','original',{},200)
        store.claim_next(actor.account_id,'binding',actor.owner_id,actor.generation)
        store.transition(task['command_id'],actor.owner_id,actor.generation,'waiting_human',result={'tab_id':'original-tab'})
        scope=dict(account_key='private-key',account_id=actor.account_id,owner_id=actor.owner_id,generation=actor.generation,binding_version='binding',
            manual_command_id=task['command_id'],manual_request_sha256=task['request_sha'],tab_id='original-tab')
        monkeypatch.setattr(leaf,'SCOPE',scope);monkeypatch.setattr(leaf,'RUN',tmp_path);monkeypatch.setattr(runtime,'ROOT',tmp_path)
        def put(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v),encoding='utf8');return runtime.reference(p)
        auth=put(tmp_path/'USER_AUTHORIZATION.json',dict(account_key=scope['account_key'],account_uuid=actor.account_id,expected_public_uid='75891235130'))
        completion=put(tmp_path/'COMPLETION.json',{});config=dict(authority=auth);request=dict(completion=completion)
        folder=tmp_path/'manual_finish_001';reqref=put(tmp_path/'REQUEST.json',request);plan_ref=put(folder/'PLAN.json',{})
        permit=put(tmp_path/'MANUAL_SESSION_FINISH_PERMIT.json',dict(schema='original_manual_session_finish_permit/v1',scope=scope,cleanup_authority=auth,
            completion_ref=completion,helper_source=leaf.reference(leaf.__file__),save_state_calls_allowed=1,close_tab_calls_allowed=1,account_recovery_allowed=False))
        plan=dict(config={},request=reqref,state={},permit=permit)
        arm=put(tmp_path/'ARM.json',dict(schema='manual_republication_runtime_arm/v10',plan=plan_ref));monkeypatch.setattr(runtime,'ARM',Path(arm['path']))
        monkeypatch.setattr(runtime,'_plan',lambda ref:(plan,config,request));monkeypatch.setattr(runtime,'_config',lambda ref:config)
        monkeypatch.setattr(runtime,'verify_completion',lambda *a:True);monkeypatch.setattr(runtime,'validate_live',lambda *a:{})
        monkeypatch.setattr(runtime,'_load',lambda key,config:leaf)
        events=[];state_path=str(tmp_path/'never-read-state.json')
        class Session:
            _proc=NS(poll=lambda:None);config=NS(headless=False,storage_state_path=state_path)
            def worker_failure(self):return ''
            def window_status(self):return dict(context_closed=False,tabs=[dict(tab_id='original-tab',role='manual',closed=False)])
            def cmd(self,action,**kw):events.append(action);return dict(state_saved=False)
            def close_tab(self,*a):raise AssertionError('close after unconfirmed save')
        resource=NS(session=Session(),manual_tasks={task['command_id']:'original-tab'},console_tasks={},context=NS(storage_state_path=state_path))
        value=runtime.read(runtime._perform(actor,resource,plan_ref,arm))
        assert events==['save_state'] and value['manual_settlement_pending'] is False
        assert runtime.read(value['leaf_result'])['close_tab_dispatches']==0
        assert store.get(task['command_id'])['state']=='waiting_human' and resource.manual_tasks=={task['command_id']:'original-tab'}
        assert not value['account_recovery_requested']
    finally:actor.stop_heartbeat()
