"""New-authority form leaves on isolated real Chrome; no live requests."""
import json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest

from test_fanqie_backfill_editor_inspection_v1 import context
from test_fanqie_promotion_identity_v2 import make_case,prepare
from test_fanqie_application_readback_v1 import local_html,NAME as TEMPLATE_NAME
from src.platform_adapter import fanqie_replacement_forms_v1 as flow
from src.platform_adapter.browser_session import Page
from src.services import fanqie_promotion_identity_v2 as native

BOOK='7302660145530539062';NAME='你敢惹我？我有六个反派儿子';ALIAS='从旧饭桌开始改命'
OLD_ID='7708816622072381502';NEW_ID='8708816622072381502';URL='https://www.douyin.com/video/7709219071845256488'


def snapshot(folder,*,target=True,deleted=False):
    n=dict(alias_id=NEW_ID,book_id=BOOK,book_name=NAME,alias_name=ALIAS)
    d=dict(book_id=BOOK,book_name=NAME,alias=ALIAS)
    if not target:n.update(book_id='8302660145530539062',book_name='别的书',alias_name='别的词');d.update(book_id=n['book_id'],book_name=n['book_name'],alias=n['alias_name'])
    if deleted:n.update(alias_id=OLD_ID,alias_status=101);d.update(alias_status='已删除')
    case=make_case(folder,native_updates=n,dom_updates=d);prepare(case,folder)
    return native._ref(folder/'output/PROMOTION_SNAPSHOT_V2.json'),case['subject']


def owner(n,commands):
    class Owner:
        def cmd(self,kind,**kw):
            assert kw.pop('tab_id')=='same-tab';commands.append((kind,dict(kw)))
            sel=kw.get('selector');loc=n.locator(sel) if sel else None
            if loc is not None and kw.get('index',-1)>=0:loc=loc.nth(kw['index'])
            if kind=='evaluate':return {'value':loc.evaluate(kw['js']) if sel else n.evaluate(kw['js'])}
            if kind=='current_url':return {'url':n.url}
            if kind=='locator_count':return {'count':loc.count()}
            if kind=='click':loc.click(timeout=kw.get('timeout',8000));return {}
            if kind=='fill':loc.fill(kw['value']);return {}
            if kind=='press':loc.press(kw['key']);return {}
            if kind=='wait_for_timeout':n.wait_for_timeout(kw['ms']);return {}
            raise AssertionError('forbidden '+kind)
    return Owner()


def base_request(tmp_path,subject,action):
    authority=flow.save(tmp_path/'AUTHORITY.json',dict(private=True))
    return dict(schema='fanqie_cleanup_rebind_request/v1',action=action,authority=authority,
        **{k:subject[k] for k in native.SCOPE},book_id=BOOK,book_name=NAME,alias=ALIAS,publish_type='AIGC',promotion_path='别名推广',
        replaces_native_identity=dict(platform_identity_key=subject['platform_identity_key'],native_kind='promotion_alias',native_record_id=OLD_ID))


def test_replacement_apply_same_keyword_has_new_claim_and_native_id(context,tmp_path):
    before,subject=snapshot(tmp_path/'before',deleted=True);after,_=snapshot(tmp_path/'after')
    request=base_request(tmp_path,subject,'replacement_apply');request['cleanup_result']=flow.save(tmp_path/'CLEANUP.json',dict(private=True))
    ref=flow.save(tmp_path/'REQUEST.json',request);n=context.new_page();n.goto('https://kol.fanqieopen.com/page/promotion-list');commands=[];page=Page(owner(n,commands),'same-tab')
    form=local_html('replace').replace(TEMPLATE_NAME,NAME).replace('};render();</script>',"};document.querySelector('#host').innerHTML='';</script>")
    cards='<div class="kol-page"><input placeholder="请输入作者名/书名/BookID"><div class="kol-page-header-title">搜索结果</div><div class="books-YEBPOv" id="search-area-scroll-box"><div class="book-hQ7GYr"><span class="book-title-txt-_CIhYa">'+NAME+'</span><div class="c-promotions"><button type="button" onclick="render()">别名推广</button></div></div></div></div>'
    search='''<script>window.searches=0;const s=document.querySelector('input[placeholder="请输入作者名/书名/BookID"]');s.onkeydown=e=>{if(e.key==='Enter'){window.searches++;setTimeout(()=>{const root=document.querySelector('.books-YEBPOv');root.innerHTML=root.innerHTML;},50)}};</script>'''
    def navigate(url):
        n.goto(url)
        if '/page/content?' in url:n.set_content(cards+form+search)
        page.url=url;return page
    claims=[]
    def claim(refproof):
        proof=flow.read(refproof);assert proof['intent']['alias']==ALIAS and flow.read(proof['form_prepared'])['ready']
        value=flow.save(tmp_path/'NEW_APPLY_CLAIM.json',dict(schema='fanqie_replacement_apply_claim/v1',request=ref,subject=subject,preflight=refproof));claims.append(value);return value
    try:
        result=flow.run_action(page,request=request,request_ref=ref,subject=subject,guard=lambda:None,evidence_directory=tmp_path/'apply',
            refresh_native_snapshot=lambda stage:after if stage=='after_apply' else before,navigate=navigate,claim_submission=claim)
        assert result['status']=='replacement_alias_observed' and result['application_submitted'] is True and result['native_identity']['native_record_id']==NEW_ID
        assert len(claims)==1 and result['native_identity']['native_record_id']!=OLD_ID
        assert not any(kind in {'api_request','set_input_files','new_tab'} for kind,_ in commands)
    finally:n.close()


@pytest.mark.parametrize('empty_first',[False,True])
def test_new_alias_backfill_removes_only_empty_other_draft_and_reads_new_record(context,tmp_path,empty_first):
    snapref,subject=snapshot(tmp_path/'native');request=base_request(tmp_path,subject,'bind_new_publication')
    request.update(new_native_identity=dict(platform_identity_key=subject['platform_identity_key'],native_kind='promotion_alias',native_record_id=NEW_ID),
        new_publication=dict(post_id='7709219071845256488',canonical_url=URL,publish_date='2026-11-18',native_created_epoch=1794942450))
    if empty_first:request.update(add_empty_douyin_draft_row=True,empty_douyin_draft_add_limit=1)
    ref=flow.save(tmp_path/'REQUEST.json',request);n=context.new_page();n.goto('https://kol.fanqieopen.com/page/promotion-list')
    old_row='<tr><td>'+ALIAS+'</td><td><span class="book-name">'+NAME+'</span>ID:'+BOOK+'</td><td>AIGC</td><td>已删除</td><td>可用</td><td>已填写（1条）</td><td><span class="arco-link" style="cursor:pointer" onclick="window.oldViews++">查看</span></td></tr>'
    n.set_content('''<table><thead><tr><th>关键词</th><th>书本信息</th><th>发文类型</th><th>别名状态</th><th>书籍状态</th><th>发文详情</th><th>操作</th></tr></thead><tbody>'''+old_row+'''<tr><td>'''+ALIAS+'''</td><td><span class="book-name">'''+NAME+'''</span>ID:'''+BOOK+'''</td><td>AIGC</td><td>生效中</td><td>可用</td><td id="status">未填写<div class="link" style="cursor:pointer" id="open">回填发文</div></td><td><span class="arco-link" style="cursor:pointer" id="view">查看</span></td></tr></tbody></table><div class="arco-drawer" id="drawer" hidden></div>
    <script>window.submits=window.removes=window.historyDeletes=window.oldViews=0;window.link='';window.day='';
    function editor(){drawer.hidden=false;drawer.innerHTML='<h2>回填发文</h2><p>'''+NAME+''' '''+ALIAS+''' AIGC</p><section><h3>抖音发文</h3><div><input class="arco-picker-start-time" placeholder="选择发文日期"><input placeholder="输入抖音发文链接,https://开头"></div></section><section><h3>其他平台发文</h3><div class="control"><div class="post"><input class="arco-picker-start-time" placeholder="选择发文日期"><input placeholder="输入发文链接"><button type="button" id="remove">删除</button></div></div></section><button type="button" id="submit">提交</button>';
      document.querySelector('#remove').onclick=()=>{window.removes++;document.querySelector('.post').remove()};
      document.querySelector('#submit').onclick=()=>{window.submits++;if(document.querySelector('input[placeholder="输入发文链接"]')){drawer.insertAdjacentHTML('beforeend','<p>发文日期必填，请填写内容</p>');return;}
       window.link=document.querySelector('input[placeholder="输入抖音发文链接,https://开头"]').value;window.day=document.querySelector('input[placeholder="选择发文日期"]').value;drawer.hidden=true;document.querySelector('#status').textContent='已填写（1条）';};}
    function details(){drawer.hidden=false;drawer.innerHTML='<h2>推广计划</h2><h3>基础信息</h3><p>书名 '''+NAME+'''</p><p>别名 '''+ALIAS+'''</p><p>发文类型 AIGC</p><p>发文时间 '+window.day+'</p><p>发文链接 '+window.link+'</p><button type="button">回填发文</button>';}
    document.querySelector('#open').onclick=editor;document.querySelector('#view').onclick=details;</script>''')
    if empty_first:
        n.evaluate('''()=>{window.adds=window.otherAdds=0;const oldEditor=editor;editor=()=>{
          drawer.hidden=false;drawer.innerHTML='<h2>回填发文</h2><p>'''+NAME+''' '''+ALIAS+''' AIGC</p><section class="arco-form-item arco-form-layout-vertical" id="dy"><label><span>抖音发文</span></label><div><button id="addDy" type="button" class="text-btn-DGPBPp add-btn-DErxLi">添加发文</button></div></section><section class="arco-form-item arco-form-layout-vertical"><label>其他平台发文</label><button type="button" onclick="window.otherAdds++">添加发文</button></section><button type="button" disabled>提交</button>';
          document.querySelector('#addDy').onclick=()=>{window.adds++;oldEditor();document.querySelector('.post').remove();};};document.querySelector('#open').onclick=editor;}''')
    commands=[];page=Page(owner(n,commands),'same-tab');claims=[]
    def claim(proofref):
        proof=flow.read(proofref);assert proof['actual_form']['input_count']==2 and proof['actual_form']['other_inputs']==[] and proof['empty_other_row_removed'] is (not empty_first)
        assert proof['preparation']['add_row_clicks']==int(empty_first) and proof['preparation']['remove_row_clicks']==int(not empty_first)
        # The actual late preflight validator consumes the branch proof, not a
        # mirrored fake claim fixture.
        flow.validate_preflight(request,proof)
        value=flow.save(tmp_path/'NEW_BACKFILL_CLAIM.json',dict(schema='fanqie_replacement_backfill_claim/v1',request=ref,subject=subject,preflight=proofref));claims.append(value);return value
    try:
        result=flow.run_action(page,request=request,request_ref=ref,subject=subject,guard=lambda:None,evidence_directory=tmp_path/'backfill',
            refresh_native_snapshot=lambda stage:snapref,navigate=lambda url:pytest.fail('backfill must not navigate'),claim_submission=claim)
        assert result['status']=='new_backfill_confirmed' and result['submitted'] is True
        assert n.evaluate('()=>[window.submits,window.removes,window.historyDeletes,window.oldViews]')==[1,int(not empty_first),0,0] and len(claims)==1
        if empty_first:assert n.evaluate('()=>[window.adds,window.otherAdds]')==[1,0]
        assert result['records']==[dict(canonical_url=URL,publish_date='2026-11-18')]
        assert not any(kind in {'api_request','set_input_files','new_tab','goto'} for kind,_ in commands)
    finally:n.close()


def test_private_replacement_actor_keeps_old_claim_and_does_not_replay(tmp_path,monkeypatch):
    import time
    from src.operations_accounts import fanqie_cleanup_rebind_v1 as runtime
    from src.operations_accounts import fanqie_managed_promotion_v1 as managed
    from src.operations_accounts.browser_control import BrowserControlActor
    from test_fanqie_new_publication_backfill_v1 import package
    a,env,store,probe,prior_publication,prior_ref=package(tmp_path/'private')
    raw_case=make_case(tmp_path/'raw',identity=probe['platform_identity_key']);scope={k:(probe if k=='platform_identity_key' else env)[k] for k in native.SCOPE}
    dom=flow.read(raw_case['legacy']['evidence_ref']);dom['subject'].update(scope)
    dom_ref=flow.save(tmp_path/'DOM.json',dom);legacy=managed.normalise_snapshot(dom['raw'],**dom['subject'],evidence_ref=dom_ref)
    legacy_ref=flow.save(tmp_path/'LEGACY.json',legacy);subject=dict(raw_case['subject'],**scope)
    obs_ref=flow.save(tmp_path/'OBSERVATION.json',dict(raw_case['observation'],subject=subject));before_ref=native.prepare_snapshot(legacy_ref,obs_ref,tmp_path/'native',managed_subject=subject)
    authority=flow.save(tmp_path/'AUTHORITY.json',dict(schema='explicit_platform_cleanup_rebind_authorization/v1',user_statement='private new replacement authorization',
        fanqie_resource_id=env['resource_id'],account_uuid=env['douyin_account_uuid'],account_key='novel',expected_public_uid='12345',fanqie_identity=probe['platform_identity_key'],
        old_unknowns_and_claims_unchanged=True,local_media_unchanged=True,models_and_media_calls_allowed=False,new_publication_allowed=False,
        book_id=BOOK,book_name=NAME,preferred_recreated_alias=ALIAS))
    old_native=dict(platform_identity_key=probe['platform_identity_key'],native_kind='promotion_alias',native_record_id=OLD_ID)
    cleanup_request=flow.save(tmp_path/'CLEANUP_REQUEST.json',dict(authority=authority,**scope))
    cleanup_subject=dict(subject,task_id='past-cleanup')
    cleanup=flow.save(tmp_path/'CLEANUP_RESULT.json',dict(schema='fanqie_cleanup_rebind_command_result/v1',request=cleanup_request,subject=cleanup_subject,broker_state='succeeded',
        result=dict(status='cleanup_observed',native_result=dict(results=[dict(target=dict(native_identity=old_native,book_id=BOOK,book_name=NAME,alias=ALIAS,publish_type='AIGC'),
            status='deleted_not_observed_in_fresh_native_list',after_snapshot=before_ref)]))))
    receipt=flow.save(tmp_path/'CLEANUP_RECEIPT.json',dict(schema='fanqie_cleanup_rebind_result_binding/v1',request=cleanup_request,subject=cleanup_subject,result=cleanup))
    old_claim=flow.save(tmp_path/'OLD_AUTHORIZED_APPLICATION_CLAIM.json',dict(retained_unknown=True));old_bytes=Path(old_claim['path']).read_bytes()
    seal=flow.save(tmp_path/'SOURCE_SEAL.json',dict(schema='fanqie_cleanup_rebind_source_seal/v1',sources=[flow.reference(p) for p in flow.source_paths('replacement_apply')]))
    request=dict(schema='fanqie_cleanup_rebind_request/v1',action='replacement_apply',draft_only=False,authority=authority,source_seal=seal,**scope,
        book_id=BOOK,book_name=NAME,alias=ALIAS,publish_type='AIGC',promotion_path='别名推广',application_limit=1,cleanup_result=cleanup,cleanup_receipt=receipt,
        replaces_native_identity=old_native,original_records=[old_claim,prior_ref])
    request_ref=flow.save(tmp_path/'REQUEST.json',request);command=a.queue(env['resource_id'],runtime.KIND,promotion_request=request_ref);calls=[]
    def action(page,*,request,request_ref,subject,guard,evidence_directory,refresh_native_snapshot,navigate,claim_submission):
        calls.append(subject);guard();folder=Path(evidence_directory);folder.mkdir(parents=True)
        prepared=flow.save(folder/'FORM.json',dict(ready=True))
        proof=flow.save(folder/'PREFLIGHT.json',dict(schema='fanqie_replacement_apply_preflight/v1',request=request_ref,subject=subject,
            target=dict(book_id=BOOK,book_name=NAME,alias=ALIAS,publish_type='AIGC'),intent={k:request[k] for k in managed.INTENT_FIELDS},
            form_prepared=prepared,native_snapshot=before_ref,cleanup_result=cleanup,observed_at=time.time()))
        claim=claim_submission(proof);guard()
        with pytest.raises(FileExistsError):claim_submission(proof)
        return dict(status='application_unknown',claim=claim,automatic_retry=False)
    monkeypatch.setattr(flow,'run_action',action)
    page=NS(_session=NS(worker_failure=lambda:None),tab_id='private-tab')
    handlers=managed.make_handlers(a,env,page_provider=lambda ctx,url:NS(page=page),probe_provider=lambda ctx:dict(probe,observed_at=time.time()))
    actor=BrowserControlActor(store,env['resource_id'],env['binding_version'],'replacement-owner',handlers)
    try:
        result=actor.run_next();assert result['state']=='succeeded' and result['result']['status']=='application_unknown' and result['result']['requires_read_only_reconciliation'] is True
        assert a.queue(env['resource_id'],runtime.KIND,promotion_request=request_ref)['command_id']==command['command_id'] and actor.run_next() is None
        assert len(calls)==1 and Path(old_claim['path']).read_bytes()==old_bytes
        assert (tmp_path/'REPLACEMENT_APPLY_CLAIM.json').is_file()
    finally:actor.close()


def test_first_empty_alias_editor_inspection_reads_both_list_add_controls_without_writing(context,tmp_path):
    snapref,subject=snapshot(tmp_path/'native');request=base_request(tmp_path,subject,'inspect_replacement_editor')
    request.update(read_only=True,backfill_limit=0,new_native_identity=dict(platform_identity_key=subject['platform_identity_key'],native_kind='promotion_alias',native_record_id=NEW_ID))
    ref=flow.save(tmp_path/'REQUEST.json',request);n=context.new_page();n.goto('https://kol.fanqieopen.com/page/promotion-list')
    n.set_content('''<table><thead><tr><th>关键词</th><th>书本信息</th><th>发文类型</th><th>别名状态</th><th>书籍状态</th><th>发文详情</th></tr></thead><tbody><tr><td>'''+ALIAS+'''</td><td><span class="book-name">'''+NAME+'''</span>ID:'''+BOOK+'''</td><td>AIGC</td><td>生效中</td><td>可用</td><td>未填写<div class="link" style="cursor:pointer" id="open">回填发文</div></td></tr></tbody></table><div class="arco-drawer" id="drawer" hidden></div>
    <script>window.opens=window.adds=window.submits=0;document.querySelector('#open').onclick=()=>{window.opens++;drawer.hidden=false;drawer.innerHTML='<h2>回填发文</h2><p>'''+NAME+''' '''+ALIAS+''' AIGC</p><section class="arco-form-item"><label><span>抖音发文</span></label><div class="arco-form-item-wrapper"><button type="button" class="add-btn" onclick="window.adds++">添加发文</button></div></section><section class="arco-form-item"><label>其他平台发文</label><div class="arco-form-item-wrapper"><button type="button" class="add-btn" onclick="window.adds++">添加发文</button></div></section><button type="button" disabled onclick="window.submits++">提交</button>';};</script>''')
    commands=[];page=Page(owner(n,commands),'same-tab')
    try:
        result=flow.run_action(page,request=request,request_ref=ref,subject=subject,guard=lambda:None,evidence_directory=tmp_path/'inspection',
            refresh_native_snapshot=lambda stage:snapref,navigate=lambda url:pytest.fail('readonly editor must not navigate'),claim_submission=lambda ref:pytest.fail('readonly cannot claim'))
        evidence=flow.read(result['inspection']);state=evidence['samples'][-1]
        assert result['status']=='replacement_editor_observed' and result['fields_written'] is False and result['submitted'] is False
        assert evidence['stable'] is True and state['structure']['inputs']==[]
        assert {s['label'] for s in state['structure']['sections']}=={'抖音发文','其他平台发文'}
        assert len([c for c in state['structure']['controls'] if c['text']=='添加发文'])==2
        assert n.evaluate('()=>[window.opens,window.adds,window.submits]')==[1,0,0]
        assert {kind for kind,_ in commands}<= {'evaluate','click','wait_for_timeout'}
    finally:n.close()


def test_readonly_editor_has_distinct_key_and_does_not_consume_or_reject_a_write_claim(tmp_path):
    from src.operations_accounts import fanqie_cleanup_rebind_v1 as runtime
    _,subject=snapshot(tmp_path/'native');request=base_request(tmp_path,subject,'inspect_replacement_editor')
    request.update(read_only=True,backfill_limit=0)
    claim=flow.save(tmp_path/'REPLACEMENT_BACKFILL_SUBMIT_CLAIM.json',dict(retained=True));before=Path(claim['path']).read_bytes()
    runtime.require_unclaimed(request)
    write=dict(request,action='bind_new_publication',backfill_limit=1)
    assert runtime.idempotency_key(request)!=runtime.idempotency_key(write)
    with pytest.raises(Exception,match='original_replacement_claim_preserved'):runtime.require_unclaimed(write)
    assert Path(claim['path']).read_bytes()==before
