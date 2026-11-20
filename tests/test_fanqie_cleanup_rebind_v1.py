"""Local real Chrome and real shared native identity evidence; no platform IO."""
import json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest

from test_fanqie_backfill_editor_inspection_v1 import context
from test_fanqie_promotion_identity_v2 import make_case,prepare
from src.platform_adapter import fanqie_cleanup_rebind_v1 as adapter
from src.platform_adapter.browser_session import Page
from src.services import fanqie_promotion_identity_v2 as native


@pytest.fixture
def cleanup(context,tmp_path):
    n=context.new_page();n.goto('https://kol.fanqieopen.com/page/promotion-list')
    n.set_content('''<style>.arco-modal{position:fixed;left:100px;top:60px;background:white;padding:30px;z-index:10} .arco-link{cursor:pointer}</style>
    <table><thead><tr><th>关键词</th><th>书本信息</th><th>发文类型</th><th>别名状态</th><th>操作</th></tr></thead><tbody>
    <tr id="active"><td>准确推广词</td><td><span class="book-name">准确书名</span> ID:1234567890123456780</td><td>AIGC</td><td>生效中</td><td><span class="arco-link" id="delete">删除</span></td></tr>
    <tr id="inactive"><td>失效推广词</td><td><span class="book-name">另一本书</span> ID:2234567890123456780</td><td>AIGC</td><td>强制失效</td><td><span class="arco-link arco-link-disabled" tabindex="-1" id="disabled" style="cursor:not-allowed">删除</span></td></tr>
    </tbody></table><div id="holder"></div><script>window.opens=window.deletes=window.disabledClicks=0;window.wrong=false;
    disabled.onclick=()=>window.disabledClicks++;
    document.querySelector('#delete').onclick=()=>{window.opens++;holder.innerHTML='<div class="arco-modal"><div class="arco-modal-title">删除别名</div><div class="arco-modal-content">是否确认删除别名'+(window.wrong?'其他推广词':'准确推广词')+'，该别名在结算有效期内，删除后将停止结算</div><button type="button">取消</button><button type="button" id="confirm">删除</button></div>';
      document.querySelector('#confirm').onclick=()=>{window.deletes++;document.querySelector('#active').remove();holder.innerHTML='';};};</script>''')
    inactive_native=dict(alias_id='2234567890123456789',book_id='2234567890123456780',book_name='另一本书',alias_name='失效推广词',task_type=1,alias_post_type=29,
        alias_status=5,book_status=1,alias_start_time='2026-01-01',alias_end_time='2027-01-01')
    inactive_dom=dict(book_id='2234567890123456780',book_name='另一本书',alias='失效推广词',publish_type='AIGC',alias_status='强制失效',book_status='可用',
        valid_from='2026-01-01',valid_until='2027-01-01',published_links=[],fill_status='未填写')
    before_case=make_case(tmp_path/'before',extra_native=[inactive_native],extra_dom=[inactive_dom]);before=prepare(before_case,tmp_path/'before');before_ref=native._ref(tmp_path/'before/output/PROMOTION_SNAPSHOT_V2.json')
    after_case=make_case(tmp_path/'after',native_updates=inactive_native,dom_updates=inactive_dom);after=prepare(after_case,tmp_path/'after');after_ref=native._ref(tmp_path/'after/output/PROMOTION_SNAPSHOT_V2.json')
    soft_case=make_case(tmp_path/'soft',native_updates=dict(alias_status=101),dom_updates=dict(alias_status='已删除'),extra_native=[inactive_native],extra_dom=[inactive_dom])
    prepare(soft_case,tmp_path/'soft');soft_ref=native._ref(tmp_path/'soft/output/PROMOTION_SNAPSHOT_V2.json')
    targets=[adapter.target_from_row(before,row) for row in before['rows']]
    request=dict(schema='fanqie_cleanup_rebind_request/v1',action='cleanup_aliases',delete_authorized=True,targets=targets,
        **{k:before_case['subject'][k] for k in ('resource_id','binding_version','environment_key','platform_identity_key')})
    ref=adapter.save(tmp_path/'REQUEST.json',request);subject=before_case['subject'];claims=[];commands=[]
    class Owner:
        def cmd(self,kind,**kw):
            assert kw.pop('tab_id')=='private-tab';commands.append(kind)
            sel=kw.get('selector');loc=n.locator(sel) if sel else None
            if loc is not None and kw.get('index',-1)>=0:loc=loc.nth(kw['index'])
            if kind=='evaluate':return {'value':loc.evaluate(kw['js']) if sel else n.evaluate(kw['js'])}
            if kind=='click':loc.click(timeout=kw.get('timeout',8000));return {}
            if kind=='wait_for_timeout':return {}
            raise AssertionError('forbidden RPC '+kind)
    page=Page(Owner(),'private-tab')
    def fresh(stage):return after_ref if n.locator('#active').count()==0 else before_ref
    def claim(preflight):
        proof=adapter.read(preflight);assert proof['subject']==subject and proof['request']==ref
        value=dict(schema='fanqie_cleanup_delete_claim/v1',request=ref,subject=subject,target=proof['target'],preflight=preflight)
        binding=adapter.save(tmp_path/'DELETE_CLAIM.json',value);claims.append(binding);return binding
    yield NS(native=n,page=page,request=request,ref=ref,subject=subject,out=tmp_path/'cleanup',fresh=fresh,claim=claim,claims=claims,commands=commands,soft_ref=soft_ref)
    n.close()


def run(x):return adapter.run_cleanup(x.page,request=x.request,request_ref=x.ref,subject=x.subject,guard=lambda:None,
    evidence_directory=x.out,refresh_native_snapshot=x.fresh,claim_delete=x.claim)


def test_exact_cleanup_deletes_active_once_and_never_dispatches_disabled(cleanup):
    x=cleanup;value=run(x)
    assert value['status']=='cleanup_observed' and len(value['disabled_targets'])==1
    assert x.native.evaluate('()=>[window.opens,window.deletes,window.disabledClicks]')==[1,1,0]
    assert len(x.claims)==1 and value['results'][0]['status']=='deleted_not_observed_in_fresh_native_list'
    assert not any(kind in {'api_request','goto','set_input_files','new_tab'} for kind in x.commands)


def test_wrong_confirmation_body_never_claims_or_confirms(cleanup):
    x=cleanup;x.native.evaluate('()=>window.wrong=true')
    with pytest.raises(adapter.CleanupBlocked,match='native_confirmation_not_confirmed'):run(x)
    assert x.native.evaluate('()=>[window.opens,window.deletes,window.disabledClicks]')==[1,0,0] and not x.claims


def test_inspect_soft_deleted_and_disabled_targets_is_strictly_read_only(cleanup,tmp_path):
    x=cleanup
    x.native.evaluate('''()=>{document.querySelector('#active td:nth-child(4)').textContent='已删除';const b=document.querySelector('#delete');b.classList.add('arco-link-disabled');b.tabIndex=-1;b.style.cursor='not-allowed';}''')
    request=dict(x.request,action='inspect_cleanup_state',delete_authorized=False,read_only=True);ref=adapter.save(tmp_path/'READ_REQUEST.json',request)
    result=adapter.inspect_cleanup_state(x.page,request=request,request_ref=ref,subject=x.subject,guard=lambda:None,evidence_directory=tmp_path/'read',refresh_native_snapshot=lambda stage:x.soft_ref)
    assert result['status']=='cleanup_state_observed' and result['click_count']==result['delete_claims_created']==0
    assert result['targets'][0]['live_target']['alias_status']=='已删除'
    assert all(t['native_delete_available'] is False for t in result['targets'])
    assert x.native.evaluate('()=>[window.opens,window.deletes,window.disabledClicks]')==[0,0,0]
    assert all(kind=='evaluate' for kind in x.commands) and not x.claims


def test_public_cleanup_owner_and_late_claim_once(tmp_path,monkeypatch):
    import time
    from src.operations_accounts import fanqie_cleanup_rebind_v1 as runtime
    from src.operations_accounts import fanqie_managed_promotion_v1 as managed
    from src.operations_accounts.browser_control import BrowserControlActor
    from test_fanqie_new_publication_backfill_v1 import package
    a,env,store,probe,old_request,old_ref=package(tmp_path/'private')
    raw_case=make_case(tmp_path/'raw',identity=probe['platform_identity_key']);scope={k:(probe if k=='platform_identity_key' else env)[k] for k in native.SCOPE}
    dom=adapter.read(raw_case['legacy']['evidence_ref']);dom['subject'].update(scope)
    domref=adapter.save(tmp_path/'BOUND_DOM.json',dom)
    legacy=managed.normalise_snapshot(dom['raw'],**dom['subject'],evidence_ref=domref);legacyref=adapter.save(tmp_path/'BOUND_LEGACY.json',legacy)
    subject=dict(raw_case['subject'],**scope);observation=dict(raw_case['observation'],subject=subject)
    obsref=adapter.save(tmp_path/'BOUND_OBSERVATION.json',observation);snapref=native.prepare_snapshot(legacyref,obsref,tmp_path/'native',managed_subject=subject);snapshot=adapter.read(snapref)
    target=adapter.target_from_row(snapshot,snapshot['rows'][0])
    auth=adapter.save(tmp_path/'AUTHORITY.json',dict(schema='explicit_platform_cleanup_rebind_authorization/v1',user_statement='private explicit cleanup',
        fanqie_resource_id=env['resource_id'],account_uuid=env['douyin_account_uuid'],account_key='novel',expected_public_uid='12345',fanqie_identity=probe['platform_identity_key'],
        old_unknowns_and_claims_unchanged=True,local_media_unchanged=True,models_and_media_calls_allowed=False,new_publication_allowed=False,
        book_id=target['book_id'],book_name=target['book_name'],preferred_recreated_alias=target['alias']))
    seal=adapter.save(tmp_path/'CLEANUP_SOURCES.json',dict(schema='fanqie_cleanup_rebind_source_seal/v1',sources=[adapter.reference(p) for p in runtime.source_paths('cleanup_aliases')]))
    request=dict(schema='fanqie_cleanup_rebind_request/v1',action='cleanup_aliases',draft_only=False,authority=auth,source_seal=seal,
        **scope,native_snapshot=snapref,targets=[target],delete_authorized=True,delete_claim_directory=str(tmp_path/'DELETE_CLAIMS'),original_records=[old_ref])
    old_source=dict(path=str(runtime.ROOT/'src/platform_adapter/fanqie_cleanup_rebind_v1.py'),sha256='1e5d42af662c486ea2edf6b949b6eca3d49a0e038cb37cda4fc1d6a09b5699b2')
    old_seal=adapter.save(tmp_path/'OLD_CLEANUP_SOURCES.json',dict(schema='fanqie_cleanup_rebind_source_seal/v1',sources=[old_source]))
    old_request=dict(request,source_seal=old_seal);old_request_ref=adapter.save(tmp_path/'OLD_CLEANUP_REQUEST.json',old_request)
    prior=store.submit(env['resource_id'],env['binding_version'],runtime.KIND,runtime.idempotency_key(old_request),dict(environment_key=env['environment_key'],request=old_request_ref))
    old_owner=store.acquire_owner(env['resource_id'],env['binding_version'],'prior-private-owner');store.claim_next(env['resource_id'],env['binding_version'],'prior-private-owner',old_owner['generation'])
    old_folder=a.folder(prior['command_id']);old_folder.mkdir(parents=True)
    old_subject=dict(scope,owner_id='prior-private-owner',generation=old_owner['generation'],task_id=prior['command_id'])
    reason=dict(status='action_not_confirmed',error_type='CleanupBlocked',reason='native_confirmation_not_confirmed',automatic_retry=False)
    prior_result=adapter.save(old_folder/'CLEANUP_REBIND_RESULT.json',dict(schema='fanqie_cleanup_rebind_command_result/v1',request=old_request_ref,subject=old_subject,broker_state='failed',result=reason))
    store.transition(prior['command_id'],'prior-private-owner',old_owner['generation'],'failed',result=dict(reason,result_evidence=prior_result));store.release_owner(env['resource_id'],'prior-private-owner',old_owner['generation'])
    adapter.save(old_folder/'cleanup/01/DELETE_MODAL.json',dict(title='删除别名',body='',eligible=False,expected_content=False,modal_count=1))
    historical=runtime.ROOT/'data/production_trials/fanqie_cleanup_rebind_20261118_v1/known_preconfirm_fix/source_before/src/platform_adapter/fanqie_cleanup_rebind_v1.py'
    copy=tmp_path/'ORIGINAL_CLEANUP_UI.py';copy.write_bytes(historical.read_bytes())
    adapter.save(tmp_path/'known_preconfirm_fix/SOURCE_AND_FAILURE_BEFORE.json',dict(schema='fanqie_cleanup_preconfirm_fix_before/v1',command_id=prior['command_id'],sources_and_evidence=[dict(original=old_source,snapshot=adapter.reference(copy))]))
    request=dict(request,known_preconfirm_failure=prior_result)
    ref=adapter.save(tmp_path/'REQUEST.json',request);command=a.queue(env['resource_id'],runtime.KIND,promotion_request=ref)
    assert command['command_id']!=prior['command_id'] and store.get(prior['command_id'])['state']=='failed'
    calls=[];claims=[]
    def action(page,*,request,request_ref,subject,guard,evidence_directory,refresh_native_snapshot,claim_delete):
        calls.append(subject);guard();folder=Path(evidence_directory);folder.mkdir(parents=True)
        modal=adapter.save(folder/'MODAL.json',dict(eligible=True,title='删除别名',expected_content=True))
        preflight=adapter.save(folder/'DELETE_PREFLIGHT.json',dict(schema='fanqie_cleanup_delete_preflight/v1',request=request_ref,subject=subject,target=target,
            native_snapshot=snapref,modal=modal,boundary=dict(eligible=True,same_node=True,center_hit=True,modal=dict(eligible=True)),observed_at=time.time(),delete_limit=1))
        claimed=claim_delete(preflight);claims.append(claimed);guard()  # Same successor's own late claim must not self-fence.
        with pytest.raises(FileExistsError):claim_delete(preflight)
        return dict(schema='fanqie_cleanup_result/v1',status='deletion_unknown',claim=claimed,automatic_retry=False)
    monkeypatch.setattr(adapter,'run_cleanup',action)
    monkeypatch.setattr(managed,'capture_native_snapshot',lambda *args,**kwargs:snapref)
    page=NS(_session=NS(worker_failure=lambda:None),tab_id='private-tab')
    handlers=managed.make_handlers(a,env,page_provider=lambda ctx,url:NS(page=page),probe_provider=lambda ctx:dict(probe,observed_at=time.time()))
    actor=BrowserControlActor(store,env['resource_id'],env['binding_version'],'private-cleanup-owner',handlers)
    try:
        result=actor.run_next();assert result['state']=='succeeded' and result['result']['requires_read_only_reconciliation'] is True
        assert len(calls)==len(claims)==1
        before=Path(claims[0]['path']).read_bytes()
        assert a.queue(env['resource_id'],runtime.KIND,promotion_request=ref)['command_id']==command['command_id']
        assert actor.run_next() is None and Path(claims[0]['path']).read_bytes()==before
        assert store.get(prior['command_id'])['state']=='failed' and not list(old_folder.rglob('DELETE_CONFIRM_INTENT.json'))
        read_request=dict(request,action='inspect_cleanup_state',delete_authorized=False,read_only=True);read_request.pop('known_preconfirm_failure')
        read_ref=adapter.save(tmp_path/'READ_REQUEST.json',read_request)
        reads=[]
        def inspect(page,*,request,request_ref,subject,guard,evidence_directory,refresh_native_snapshot):
            guard();reads.append(subject);assert Path(claims[0]['path']).read_bytes()==before
            return dict(schema='fanqie_cleanup_state_observation/v1',status='cleanup_state_observed',click_count=0,delete_claims_created=0)
        monkeypatch.setattr(adapter,'inspect_cleanup_state',inspect)
        read_command=a.queue(env['resource_id'],runtime.KIND,promotion_request=read_ref)
        observed=actor.run_next();assert observed['command_id']==read_command['command_id'] and observed['state']=='succeeded'
        assert observed['result']['status']=='cleanup_state_observed' and len(reads)==1 and len(calls)==1 and Path(claims[0]['path']).read_bytes()==before
    finally:actor.close()


def test_known_preconfirm_successor_requires_failed_zero_claim_original(tmp_path):
    from src.operations_accounts import fanqie_cleanup_rebind_v1 as runtime
    from src.operations_accounts import fanqie_new_publication_backfill_v1 as files
    from src.operations_accounts.fanqie_account_control import FanqieAccounts
    from src.operations_accounts.browser_control import BrowserControlStore,BrowserControlRejected
    store=BrowserControlStore(tmp_path/'control.db');a=FanqieAccounts(tmp_path/'control.db',tmp_path/'profiles',tmp_path/'evidence',tmp_path/'douyin.db')
    authority=adapter.save(tmp_path/'AUTHORITY.json',dict(private=True));original=dict(path=str(runtime.ROOT/'src/platform_adapter/fanqie_cleanup_rebind_v1.py'),sha256='1e5d42af662c486ea2edf6b949b6eca3d49a0e038cb37cda4fc1d6a09b5699b2')
    old_seal=adapter.save(tmp_path/'OLD_SEAL.json',dict(sources=[original]))
    request=dict(authority=authority,resource_id='fanqie:private',binding_version='bound',environment_key='env',platform_identity_key='uid:54321',action='cleanup_aliases',
        native_snapshot=dict(private=True),targets=[dict(private=True)],delete_authorized=True,delete_claim_directory=str(tmp_path/'DELETE_CLAIMS'),original_records=[],source_seal=old_seal)
    old_ref=adapter.save(tmp_path/'OLD_REQUEST.json',request);command=store.submit('fanqie:private','bound',runtime.KIND,'original',dict(environment_key='env',request=old_ref))
    owner=store.acquire_owner('fanqie:private','bound','private-owner');store.claim_next('fanqie:private','bound','private-owner',owner['generation'])
    folder=a.folder(command['command_id']);folder.mkdir(parents=True)
    subject=dict(resource_id='fanqie:private',binding_version='bound',environment_key='env',platform_identity_key='uid:54321',owner_id='private-owner',generation=owner['generation'],task_id=command['command_id'])
    reason=dict(status='action_not_confirmed',error_type='CleanupBlocked',reason='native_confirmation_not_confirmed',automatic_retry=False)
    result=adapter.save(folder/'CLEANUP_REBIND_RESULT.json',dict(schema='fanqie_cleanup_rebind_command_result/v1',request=old_ref,subject=subject,broker_state='failed',result=reason))
    store.transition(command['command_id'],'private-owner',owner['generation'],'failed',result=dict(reason,result_evidence=result))
    adapter.save(folder/'cleanup/01/DELETE_MODAL.json',dict(title='删除别名',body='',eligible=False,expected_content=False,modal_count=1))
    # Actual historical producer bytes prove the modal check was before the
    # late claim/confirmation path; tests do not pretend new code is old code.
    historical=runtime.ROOT/'data/production_trials/fanqie_cleanup_rebind_20261118_v1/known_preconfirm_fix/source_before/src/platform_adapter/fanqie_cleanup_rebind_v1.py'
    copy=tmp_path/'SOURCE_OLD.py';copy.write_bytes(historical.read_bytes());assert adapter.reference(copy)['sha256']==original['sha256']
    adapter.save(tmp_path/'known_preconfirm_fix/SOURCE_AND_FAILURE_BEFORE.json',dict(schema='fanqie_cleanup_preconfirm_fix_before/v1',command_id=command['command_id'],sources_and_evidence=[dict(original=original,snapshot=adapter.reference(copy))]))
    successor=dict(request,known_preconfirm_failure=result)
    runtime._known_preconfirm_failure(successor,a)
    assert runtime.idempotency_key(request)!=runtime.idempotency_key(successor)
    adapter.save(folder/'cleanup/01/DELETE_CONFIRM_INTENT.json',dict(unexpected=True))
    with pytest.raises(BrowserControlRejected,match='prior_delete_effect_cannot_be_excluded'):runtime._known_preconfirm_failure(successor,a)
