"""Existing native Page RPC shape, isolated real DOM, freshly compiled tag leaves."""
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import manual_republication_flow_v5 as flow
from src.operations_accounts import manual_republication_flow_v1 as v1
from src.platform_adapter.browser_session import Page


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')
    return flow.reference(path)


@pytest.fixture(scope='module')
def native(tmp_path_factory):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='chrome',headless=True,args=['--disable-background-networking','--mute-audio'])
        context=browser.new_context();context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body='<html><body></body></html>'))
        yield context
        context.close();browser.close()


@pytest.fixture
def draft(tmp_path,monkeypatch,native):
    page=native.new_page();page.goto('https://creator.douyin.com/creator-micro/content/post/video')
    html='''<div hidden><input class="semi-input" placeholder="填写作品标题，为作品获得更多流量" value="hidden">
        <div class="editor" contenteditable="true" data-placeholder="添加作品简介">hidden</div></div>
      <input id="unrelated" class="semi-input" placeholder="地理位置" value="not authorized">
      <input id="title" class="semi-input" placeholder="填写作品标题，为作品获得更多流量">
      <div id="editor" class="editor" contenteditable="true" data-slate-editor="true" data-placeholder="添加作品简介"></div>
      <button id="entry" type="button" aria-haspopup="listbox" aria-expanded="false">请选择自主声明</button>
      <div id="options" role="listbox" hidden><div role="option">内容由AI生成</div><div role="option">含营销信息</div></div>
      <button id="publish">发布</button><input type="file" hidden>
      <video id="preview" style="width:200px;height:100px"></video>
      <script>window.clicked=[];document.addEventListener('click',e=>window.clicked.push(e.target.id),true);
      entry.onclick=()=>{entry.setAttribute('aria-expanded','true');options.hidden=false};
      Object.defineProperty(document.querySelector('input[hidden],div[hidden] input'),'value',{get(){throw Error('hidden value read')},set(){throw Error('hidden write')}});
      Object.defineProperty(document.querySelector('#unrelated'),'value',{get(){throw Error('unrelated value read')},set(){throw Error('unrelated write')}});</script>'''
    page.set_content(html)
    page.locator('#preview').evaluate("el=>{Object.defineProperty(el,'duration',{get:()=>2896/24,configurable:true});Object.defineProperty(el,'readyState',{get:()=>4})}")
    run=tmp_path/'run';run.mkdir();media=run/'unchanged.mp4';media.write_bytes(b'unchanged original synthetic file')
    binding=NS(account_uuid='account:test',account_key='novel-test',platform_identity_key='public_uid:75891235130',
        browser_environment_key='original',browser_profile_dir='private',storage_state_path='unused',confirmed_by='user',created_at='bound',public_uid='75891235130')
    profile=NS(account_uuid=binding.account_uuid,profile_version=1)
    authority=put(run/'AUTH.json',dict(media=flow.reference(media),expected_public_uid=binding.public_uid))
    metadata=dict(schema='manual_republication_metadata/v1',account_uuid=binding.account_uuid,account_key=binding.account_key,media=flow.reference(media),
        title='两分钟新文案',description='推广信息；剧情虚构，非真实事件。',hashtags=['小说推文','穿书','小说剧情','AI短剧','AI生成'],ai_generated=True,fictional_story=True,visibility='public')
    mref=put(run/'METADATA.json',metadata)
    sources={k:flow.reference(flow.ROOT/p) for k,p in {'flow_v2':'src/operations_accounts/manual_republication_flow_v2.py',
        'flow_v1':'src/operations_accounts/manual_republication_flow_v1.py','publish_workflow':'src/platform_adapter/publish_workflow.py',
        'upload_diagnostic':'src/platform_adapter/upload_surface_diagnostic.py'}.items()}
    cfg=dict(account_id=binding.account_uuid,account_key=binding.account_key,owner_id='original-owner',generation=33,tab_id='same-tab',
        binding_version=v1._binding_version(NS(binding=binding,profile=profile)),authority=authority,metadata=mref,sources=sources)
    cref=put(run/'CONFIG.json',cfg);oldplan=put(run/'v4/PLAN.json',{'schema':'private-v4'});oldaction=put(run/'v4/ACTION_CLAIM.json',{'schema':'private-v4-action'})
    fileclaim=put(run/'FILE_SELECTION_CLAIM.json',dict(schema='manual_file_selection_claim/v4',media=metadata['media'],metadata=mref,authority=authority,
        owner_id=cfg['owner_id'],generation=33,tab_id='same-tab',plan=oldplan,action_claim=oldaction))
    req=dict(schema='manual_republication_operator_request/v5',config=cref,action='prepare_existing_draft',prior_upload_plan=oldplan,
        prior_upload_action=oldaction,file_selection_claim=fileclaim,prior_unknown=put(run/'UNKNOWN.json',{}),
        prior_failure=put(run/'FAILURE.json',{}),post_upload_editor=put(run/'POST_UPLOAD_EDITOR.json',{}))
    nonce='a'*32
    diag=dict(initial_route='upload',current_route='editor',generation=1,route_history_truncated=False,
        routes=[dict(route='upload',generation=0,event='begin'),dict(route='editor',generation=1,event='route_change')])
    proof=dict(schema='upload_check_transition/v2',selection_nonce=nonce,diagnostic=diag,verified=False,reason='selection_proof_deadline')
    journal=run/'UPLOAD_JOURNAL.jsonl';journal.write_text(json.dumps(dict(stage='upload_check_transition_observed',selection_nonce=nonce,proof=proof))+'\n',encoding='utf8')
    rref=put(run/'REQUEST.json',req);pref=put(run/'v5/PLAN.json',dict(config=cref,request=rref,
        prior=dict(upload_journal=flow.reference(journal),selection_nonce=nonce,upload_route_baseline=diag,source_duration_seconds=2896/24)))
    put(run/'v5/ACTION_CLAIM.json',dict(schema='manual_republication_existing_draft_action_claim/v5',plan=pref,config=cref,request=rref,
        action='prepare_existing_draft',owner_id='original-owner',generation=33,tab_id='same-tab',actor_thread_id=threading.get_ident(),
        navigation_allowed=False,file_selection_allowed=False,submissions_allowed=0))
    commands=[];hooks=[None];state=NS(drop_fill=False,proof=proof,slate_zero_width=False)
    class Owner:
        _proc=NS(poll=lambda:None)
        def get_page(self,tab):assert tab=='same-tab';return raw
        def cmd(self,kind,**kw):
            assert kw.pop('tab_id')=='same-tab';commands.append((kind,dict(kw)))
            if hooks[0]:hook=hooks[0];hooks[0]=None;hook(kind,kw)
            sel=kw.get('selector','');index=kw.get('index',-1)
            loc=page.locator(sel).nth(index if index>=0 else 0) if sel else None
            if kind=='current_url':return {'url':page.url}
            if kind=='upload_check_proof':assert kw['operation']=='observe' and kw['selection_nonce']==nonce;return {'proof':state.proof}
            if kind=='evaluate':return {'value':loc.evaluate(kw['js']) if sel else page.evaluate(kw['js'])}
            if kind=='locator_count':return {'count':page.locator(sel).count()}
            if kind=='wait_for_timeout':return {}
            if kind=='fill':
                loc.fill(kw['value'])
                if state.slate_zero_width and sel==flow.EDITOR+':visible':loc.evaluate("el=>{el.textContent='\\u200b'+el.textContent+'\\u200b'}")
                if state.drop_fill:raise RuntimeError('lost fill acknowledgement')
                return {}
            if kind=='click':loc.click();return {}
            if kind=='type_hashtag':
                tagloc=page.locator(kw['selectors'][0]);tagloc.click();page.keyboard.press('Control+End');page.keyboard.insert_text(' #'+kw['tag']);page.keyboard.press('Enter');return {}
            raise AssertionError('forbidden IO: '+kind)
    owner=Owner();raw=Page(owner,'same-tab');actor=NS(owner_id='original-owner',generation=33)
    resource=NS(session=owner,runtime=NS(bindings=NS(get=lambda _:binding),profiles=NS(get=lambda _:profile)))
    import src.operations_accounts as ops
    runtime=NS(validate_live=lambda *args:None)
    monkeypatch.setitem(sys.modules,'src.operations_accounts.manual_republication_runtime_v5',runtime)
    monkeypatch.setattr(ops,'manual_republication_runtime_v5',runtime,raising=False)
    yield NS(page=page,run=run,config=cfg,request=req,out=run/'v5/preparation',actor=actor,resource=resource,
        commands=commands,metadata=metadata,hooks=hooks,state=state,fileclaim=fileclaim)
    page.close()


def run(x,out=None):return flow.run_action(x.actor,x.resource,x.config,x.request,out or x.out)


def test_hidden_duplicates_use_unique_visible_same_element_and_inventory_only(draft):
    x=draft;original=Path(x.fileclaim['path']).read_bytes();result=run(x)
    assert result['metadata_readback_matched'] and result['hashtag_readback_verified'] and result['declaration_entry_expanded']
    assert not any(result[k] for k in ('submitted','declaration_selected','navigation_performed','file_selected','publication_ready'))
    projection=flow.read(result['field_projection']);row=next(r for r in projection['rows'] if r['selector']==flow.TITLE)
    assert row['all_count']==2 and [r['index'] for r in row['candidates'] if r['visible']]==[1]
    assert row['candidates'][0]['content'] is None
    assert Path(x.fileclaim['path']).read_bytes()==original
    assert not any(k in {'set_input_files','goto','ai_content_declaration','new_tab'} for k,_ in x.commands)
    assert 'publish' not in x.page.evaluate('()=>window.clicked')
    before=len(x.commands)
    with pytest.raises(flow.ExistingDraftBlocked):run(x)
    assert len(x.commands)==before


def test_two_visible_authorized_fields_stop_before_any_input(draft):
    x=draft;x.page.locator('#title').evaluate('el=>el.after(el.cloneNode())')
    with pytest.raises(flow.ExistingDraftBlocked):run(x)
    assert (x.out/'FIELD_PROJECTION.json').exists() and not any(k in {'fill','click','type_hashtag'} for k,_ in x.commands)


@pytest.mark.parametrize('kind',['submit','radio'])
def test_declaration_control_cannot_be_submit_or_choice(draft,kind):
    x=draft
    if kind=='submit':x.page.locator('#entry').evaluate("el=>el.type='submit'")
    else:x.page.locator('#entry').evaluate("el=>el.setAttribute('role','radio')")
    result=run(x)
    assert not result['declaration_entry_expanded'] and 'entry' not in x.page.evaluate('()=>window.clicked')


def test_wrong_outdir_rejects_before_rpc(draft):
    x=draft
    with pytest.raises((flow.ExistingDraftBlocked,FileNotFoundError)):run(x,x.run/'other/preparation')
    assert x.commands==[]


def test_lost_fill_ack_preserves_claim_and_cannot_restart(draft):
    x=draft;x.state.drop_fill=True
    with pytest.raises(flow.ExistingDraftBlocked) as e:run(x)
    assert e.value.code=='draft_mutation_unknown'
    assert flow.read(flow.reference(x.out/'PREPARE_FAILURE.json'))['metadata_mutation_dispatched']
    before=len(x.commands)
    with pytest.raises(flow.ExistingDraftBlocked):run(x)
    assert len(x.commands)==before and not any(k=='set_input_files' for k,_ in x.commands)


@pytest.mark.parametrize('change',['new_generation','wrong_duration'])
def test_changed_draft_fence_rejects_before_input(draft,change):
    x=draft
    if change=='new_generation':x.state.proof['diagnostic']['generation']=2
    else:x.page.locator('#preview').evaluate("el=>Object.defineProperty(el,'duration',{get:()=>60,configurable:true})")
    with pytest.raises(flow.ExistingDraftBlocked):run(x)
    assert not any(k in {'fill','click','type_hashtag'} for k,_ in x.commands)
    assert (x.out/'FIELD_PROJECTION.json').exists()


def test_slate_zero_width_readback_is_exact_except_confirmed_formatting(draft):
    x=draft;x.state.slate_zero_width=True;result=run(x)
    assert '\u200b' in result['description_readback']['content']
    assert result['metadata_readback_matched'] and result['hashtag_readback_verified']
    assert flow.description_exact(result['description_readback']['content'],x.metadata['description'])
    assert not flow.description_exact(x.metadata['description']+'额外字',x.metadata['description'])
    assert not flow.description_exact(x.metadata['description']+'\u200c',x.metadata['description'])
