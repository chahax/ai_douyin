"""Repair only the existing uploaded draft; never navigates, selects files or publishes.

Only the authorized title/description values are read. Declaration choices are
inventoried, and a uniquely proven non-submitting disclosure may be opened once.
"""
import hashlib
import json
import os
import math
from pathlib import Path
import threading
import time
import types
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SAFE_REASONS = frozenset({'draft_request_invalid','draft_binding_changed','draft_claim_changed',
    'draft_output_changed','draft_session_changed','draft_deadline_reached','draft_editor_unconfirmed',
    'draft_field_not_unique','draft_readback_unconfirmed','draft_rpc_not_allowed','draft_mutation_unknown'})
TITLE = 'input[placeholder="填写作品标题，为作品获得更多流量"]'
EDITOR = '[contenteditable="true"][data-placeholder="添加作品简介"]'
TITLE_SELECTORS = (TITLE,"input.semi-input[placeholder*='标题']","input.semi-input[placeholder*='作品标题']",".semi-input-wrapper input.semi-input")
EDITOR_SELECTORS = (EDITOR,".editor[contenteditable='true']","div[data-slate-editor='true']")
VISIBLE = "e=>!!e&&e.isConnected&&e.getClientRects().length>0&&!e.closest('[hidden],[aria-hidden=\"true\"]')&&(()=>{for(let p=e;p;p=p.parentElement){let s=getComputedStyle(p);if(s.display==='none'||['hidden','collapse'].includes(s.visibility)||Number(s.opacity)===0)return false}return true})()"


class ExistingDraftBlocked(ValueError):
    def __init__(self,code): self.code=code;super().__init__(code)


def need(ok,code):
    if not ok: raise ExistingDraftBlocked(code)


def description_exact(actual,expected):
    """Only ignore the confirmed Slate U+200B formatting and whitespace."""
    clean=lambda value:''.join(value.replace('\u200b','').split())
    return isinstance(actual,str) and isinstance(expected,str) and clean(actual)==clean(expected)


def reference(path):
    p=Path(path).resolve();need(p.is_relative_to(ROOT) and p.is_file(),'draft_binding_changed')
    with p.open('rb') as stream: sha=hashlib.file_digest(stream,'sha256').hexdigest()
    return dict(path=str(p),sha256=sha)


def read(ref):
    need(isinstance(ref,dict) and set(ref)=={'path','sha256'} and reference(ref['path'])==ref,'draft_binding_changed')
    return json.loads(Path(ref['path']).read_text(encoding='utf8'))


def once(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as stream:
        stream.write((json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode());stream.flush();os.fsync(stream.fileno())
    return reference(path)


def _load_base(config):
    path=ROOT/'src/operations_accounts/manual_republication_flow_v2.py';ref=config['sources']['flow_v2']
    need(reference(path)==ref,'draft_binding_changed')
    module=types.ModuleType('src.operations_accounts._existing_draft_'+ref['sha256'][:16])
    module.__file__,module.__package__=str(path),'src.operations_accounts'
    exec(compile(path.read_bytes(),str(path),'exec'),module.__dict__)
    return module


def field_projection_script():
    selectors=list(dict.fromkeys(TITLE_SELECTORS+EDITOR_SELECTORS))
    return """() => {if(location.origin!=='https://creator.douyin.com'||location.pathname!=='/creator-micro/content/post/video')return {schema:'manual_draft_field_projection/v5',location:{origin:location.origin,path:location.pathname},rows:[]};const visible=VISIBLE;const authorized=e=>e.matches(TITLE)||e.matches(EDITOR);
      const rows=SELECTORS.map(selector=>{const all=[...document.querySelectorAll(selector)];return {selector,all_count:all.length,truncated:all.length>32,
        candidates:all.slice(0,32).map((e,index)=>({index,visible:visible(e),disabled:e.matches(':disabled,[aria-disabled="true"]'),readonly:e.readOnly===true,
          tag:e.tagName.toLowerCase(),placeholder:e.getAttribute('placeholder')||'',data_placeholder:e.getAttribute('data-placeholder')||'',
          authorized_field:authorized(e),content:visible(e)&&authorized(e)?String(e.matches('input')?e.value:e.innerText||'').slice(0,12000):null}))}});
      return {schema:'manual_draft_field_projection/v5',location:{origin:location.origin,path:location.pathname},rows,
        authorized_field_values_read:true,unrelated_input_values_read:false};}
      """.replace('VISIBLE',VISIBLE).replace('TITLE',json.dumps(TITLE)).replace('EDITOR',json.dumps(EDITOR)).replace('SELECTORS',json.dumps(selectors))


def equality_script(css):
    return 'el=>{if(location.origin!=="https://creator.douyin.com"||location.pathname!=="/creator-micro/content/post/video")return false;const visible='+VISIBLE+';const a=[...document.querySelectorAll('+json.dumps(css)+')].filter(visible);return a.length===1&&a[0]===el&&!el.matches(":disabled,[aria-disabled=\\\"true\\\"]")&&!el.readOnly;}'


def trigger_projection_script():
    # Text alone never authorizes a click: require native disclosure semantics.
    return """() => {const visible=VISIBLE;const nodes=[...document.querySelectorAll('body *')].filter(e=>visible(e)&&['自主声明','请选择自主声明','添加自主声明'].includes((e.innerText||'').trim())&&
      ![...e.children].some(c=>visible(c)&&['自主声明','请选择自主声明','添加自主声明'].includes((c.innerText||'').trim())));
      const candidates=nodes.slice(0,12).map(e=>{const chain=[];for(let p=e,i=0;p&&i<4;p=p.parentElement,i++){
        chain.push({tag:p.tagName.toLowerCase(),role:p.getAttribute('role')||'',type:p instanceof HTMLButtonElement?p.type:(p.getAttribute('type')||''),
          class_name:(p.className||'').toString().slice(0,240),aria_haspopup:p.getAttribute('aria-haspopup'),aria_expanded:p.getAttribute('aria-expanded'),
          aria_controls:p.getAttribute('aria-controls'),visible:visible(p),disabled:p.matches(':disabled,[aria-disabled="true"]'),
          text:(p.innerText||'').trim().slice(0,180)});}return {text:(e.innerText||'').trim(),ancestors:chain}});
      return {schema:'manual_draft_declaration_trigger/v5',candidates,truncated:nodes.length>12};}
      """.replace('VISIBLE',VISIBLE)


TRIGGER = '[aria-haspopup]:not([aria-haspopup="false"]),[aria-expanded]'
VIDEO_PROBE = """() => {const visible=e=>!!e&&e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden'&&!e.closest('[hidden],[aria-hidden="true"]');
 const a=[...document.querySelectorAll('video')].filter(visible);return {schema:'manual_draft_video/v5',origin:location.origin,path:location.pathname,
 visible_video_count:a.length,duration:a.length===1&&Number.isFinite(a[0].duration)?a[0].duration:null,ready_state:a.length===1?a[0].readyState:null};}"""


def trigger_check_script():
    return 'el=>{const visible='+VISIBLE+""";const ok=e=>visible(e)&&!e.matches(':disabled,[aria-disabled="true"],input,label,[role="option"],[role="radio"],[role="checkbox"],[role="switch"]')&&
      !(e instanceof HTMLButtonElement&&['submit','reset'].includes(e.type))&&['button','combobox'].includes(e.getAttribute('role')|| (e.tagName==='BUTTON'?'button':''))&&
      (e.getAttribute('aria-haspopup')&&!['false',''].includes(e.getAttribute('aria-haspopup'))||e.hasAttribute('aria-expanded'))&&
      ['自主声明','请选择自主声明','添加自主声明'].includes((e.innerText||'').trim());
      const all=[...document.querySelectorAll("""+json.dumps(TRIGGER)+")].filter(ok);return {unique:all.length===1,same:all[0]===el,expanded:el.getAttribute('aria-expanded')==='true'};}"


def _choose(projection,css):
    need(projection.get('location')=={'origin':'https://creator.douyin.com','path':'/creator-micro/content/post/video'},'draft_editor_unconfirmed')
    row=next((r for r in projection['rows'] if r['selector']==css),None)
    need(row is not None and row.get('truncated') is False,'draft_field_not_unique')
    candidates=[x for x in row['candidates'] if x.get('visible')]
    need(len(candidates)==1 and candidates[0]['authorized_field'] and not candidates[0]['disabled'] and not candidates[0]['readonly'],'draft_field_not_unique')
    return css+':visible'


def run_action(actor,resource,config,request,outdir):
    from . import manual_republication_runtime_v5 as runtime
    fields={'schema','config','action','prior_upload_plan','prior_upload_action','file_selection_claim','prior_unknown','prior_failure','post_upload_editor'}
    need(isinstance(request,dict) and set(request)==fields and request['schema']=='manual_republication_operator_request/v5'
         and request['action']=='prepare_existing_draft','draft_request_invalid')
    need(read(request['config'])==config,'draft_binding_changed')
    for key in fields-{'schema','config','action'}:read(request[key])
    folder=Path(outdir).resolve();need(folder.is_relative_to(ROOT/'data') and folder.name=='preparation','draft_output_changed')
    action_ref=reference(folder.parent/'ACTION_CLAIM.json');action=read(action_ref);plan=read(action['plan'])
    need(action.get('schema')=='manual_republication_existing_draft_action_claim/v5' and action.get('action')==request['action']
         and action.get('config')==request['config'] and read(action['request'])==request
         and action.get('owner_id')==actor.owner_id and action.get('generation')==actor.generation
         and action.get('tab_id')==config['tab_id'] and action.get('actor_thread_id')==threading.get_ident()
         and action.get('navigation_allowed') is False and action.get('file_selection_allowed') is False
         and type(action.get('submissions_allowed')) is int and action['submissions_allowed']==0
         and plan.get('config')==request['config'] and plan.get('request')==action['request']
         and folder==Path(action['plan']['path']).resolve().parent/'preparation','draft_claim_changed')
    need(not (folder/'DRAFT_MUTATION_INTENT.json').exists(),'draft_claim_changed')
    prior=plan.get('prior',{});journal_ref=prior.get('upload_journal');nonce=prior.get('selection_nonce')
    journal_path=Path(journal_ref['path']) if isinstance(journal_ref,dict) and 'path' in journal_ref else None
    need(journal_path is not None and reference(journal_path)==journal_ref
         and journal_path.resolve().parent==Path(request['post_upload_editor']['path']).resolve().parent,'draft_claim_changed')
    events=[json.loads(line) for line in journal_path.read_text(encoding='utf8').splitlines() if line.strip()]
    proofs=[e.get('proof') for e in events if e.get('selection_nonce')==nonce and isinstance(e.get('proof'),dict)
            and e['proof'].get('diagnostic',{}).get('current_route')=='editor']
    need(isinstance(nonce,str) and len(nonce)==32 and proofs,'draft_claim_changed')
    baseline=proofs[-1]['diagnostic'];routes=baseline.get('routes')
    need(baseline.get('initial_route')=='upload' and baseline.get('current_route')=='editor'
         and baseline.get('route_history_truncated') is False and isinstance(routes,list) and len(routes)==2
         and routes[0]=={'route':'upload','generation':0,'event':'begin'}
         and routes[1]=={'route':'editor','generation':1,'event':'route_change'} and baseline.get('generation')==1,'draft_claim_changed')
    expected_duration=prior.get('source_duration_seconds')
    need(type(expected_duration) in {int,float} and math.isfinite(expected_duration) and abs(expected_duration-2896/24)<1e-6
         and prior.get('upload_route_baseline')=={k:baseline[k] for k in ('initial_route','current_route','generation','routes','route_history_truncated')},'draft_claim_changed')
    base=_load_base(config);reader,Workflow=base._load_leaves(config);metadata,authority=base._metadata(config)
    selected=read(request['file_selection_claim'])
    need(selected.get('schema')=='manual_file_selection_claim/v4' and selected.get('media')==metadata['media']
         and selected.get('metadata')==config['metadata'] and selected.get('authority')==config['authority']
         and all(selected.get(k)==config[k] for k in ('owner_id','generation','tab_id'))
         and selected.get('plan')==request['prior_upload_plan'] and selected.get('action_claim')==request['prior_upload_action'],'draft_claim_changed')
    original=resource.session;deadline=time.monotonic()+180
    immutable={k:request[k] for k in fields-{'schema','action'}};immutable['action_claim']=action_ref
    immutable['upload_journal']=journal_ref
    def guard():
        need(time.monotonic()+45<=deadline,'draft_deadline_reached')
        need(resource.session is original and original._proc is not None and original._proc.poll() is None,'draft_session_changed')
        runtime.validate_live(actor,resource,config)
        for ref in immutable.values():need(reference(ref['path'])==ref,'draft_binding_changed')
        b=resource.runtime.bindings.get(config['account_key']);p=resource.runtime.profiles.get(config['account_key'])
        need(b.account_uuid==p.account_uuid==config['account_id'] and reader._binding_version(SimpleNamespace(binding=b,profile=p))==config['binding_version']
             and str(b.public_uid)==authority['expected_public_uid'],'draft_session_changed')
    guard();raw=original.get_page(config['tab_id']);guard()
    need(raw._session is original and raw.tab_id==config['tab_id'],'draft_session_changed')
    folder.mkdir(parents=True,exist_ok=True)
    class Gate:
        def __init__(self):self.fields={};self.fills={};self.tags={};self.mutated=False;self.expanded=False;self.expand_index=None
        def read(self,kind,**kw):
            guard();r=original.cmd(kind,tab_id=raw.tab_id,**kw);guard();return r
        def same(self,selector,index,css):
            need(self.read('evaluate',selector=selector,index=index,js=equality_script(css)).get('value') is True,'draft_field_not_unique')
        def draft_fence(self):
            proof=self.read('upload_check_proof',operation='observe',selection_nonce=nonce).get('proof',{})
            diagnostic=proof.get('diagnostic',{})
            need(proof.get('schema')=='upload_check_transition/v2' and proof.get('selection_nonce')==nonce
                 and diagnostic.get('current_route')=='editor' and diagnostic.get('initial_route')=='upload'
                 and diagnostic.get('generation')==baseline['generation'] and diagnostic.get('routes')==routes
                 and diagnostic.get('route_history_truncated') is False,'draft_editor_unconfirmed')
            video=self.read('evaluate',selector='',index=-1,js=VIDEO_PROBE).get('value',{})
            duration=video.get('duration');ready=video.get('ready_state')
            need(video.get('origin')=='https://creator.douyin.com' and video.get('path')=='/creator-micro/content/post/video'
                 and video.get('visible_video_count')==1 and type(duration) in {int,float} and math.isfinite(duration)
                 and abs(duration-expected_duration)<=.5 and type(ready) is int and ready>=1,'draft_editor_unconfirmed')
            return dict(schema='manual_existing_draft_fence/v5',native_upload_proof=proof,video=video,source_duration_seconds=expected_duration,
                original_journal=journal_ref,selection_nonce=nonce,new_main_frame_event_observed=False,
                fresh_document_handle_claimed=False,platform_media_sha_verified=False,checker_verified_claimed=False)
        def cmd(self,kind,**kw):
            need(kw.pop('tab_id',raw.tab_id)==raw.tab_id,'draft_session_changed');guard()
            if kind=='fill':
                sel=kw.get('selector');need(sel in self.fields and self.fills.get(sel,0)==0 and kw.get('value')==self.fields[sel][1],'draft_rpc_not_allowed')
                self.draft_fence();self.same(sel,kw.get('index',-1),self.fields[sel][0]);self.fills[sel]=1;self.mutated=True
            elif kind=='type_hashtag':
                tag=kw.get('tag');sels=kw.get('selectors',[])
                need(tag in metadata['hashtags'] and self.tags.get(tag,0)<2 and len(sels)==1,'draft_rpc_not_allowed')
                self.draft_fence();self.same(sels[0],0,EDITOR);self.tags[tag]=self.tags.get(tag,0)+1;self.mutated=True
            elif kind=='click':
                sel=kw.get('selector')
                if sel==TRIGGER:
                    need(self.expand_index is not None and not self.expanded and kw.get('index')==self.expand_index,'draft_rpc_not_allowed')
                    proof=self.read('evaluate',selector=sel,index=self.expand_index,js=trigger_check_script()).get('value',{})
                    need(proof.get('unique') and proof.get('same') and not proof.get('expanded'),'draft_rpc_not_allowed');self.expanded=True
                else:
                    need(sel in self.fields and self.fields[sel][0]==EDITOR,'draft_rpc_not_allowed');self.same(sel,kw.get('index',-1),EDITOR)
            else:need(kind in {'current_url','evaluate','locator_count','inner_text','get_attribute','wait_for_timeout'},'draft_rpc_not_allowed')
            return self.read(kind,**kw)
    gate=Gate();page=base.Page(gate,raw.tab_id)
    try:
        from urllib.parse import urlsplit
        url=urlsplit(page._cmd('current_url')['url'])
        need(url.scheme=='https' and url.hostname=='creator.douyin.com' and url.path=='/creator-micro/content/post/video','draft_editor_unconfirmed')
        projection=page.evaluate(field_projection_script());project_ref=once(folder/'FIELD_PROJECTION.json',projection)
        fence_ref=once(folder/'DRAFT_FENCE.json',gate.draft_fence())
        title_sel=_choose(projection,TITLE);editor_sel=_choose(projection,EDITOR)
        gate.fields={title_sel:(TITLE,metadata['title']),editor_sel:(EDITOR,metadata['description'])}
        gate.same(title_sel,0,TITLE);gate.same(editor_sel,0,EDITOR)
        once(folder/'DRAFT_MUTATION_INTENT.json',dict(schema='manual_existing_draft_mutation/v5',action_claim=action_ref,
            file_selection_claim=request['file_selection_claim'],metadata=config['metadata'],same_tab=raw.tab_id,
            allowed=['frozen_title','frozen_description','frozen_hashtags','proven_declaration_disclosure'],file_selection_allowed=False,submission_allowed=False))
        page.locator(title_sel).fill(metadata['title']);page.locator(editor_sel).click();page.locator(editor_sel).fill(metadata['description'])
        description=page.locator(editor_sel).evaluate(base.FIELD_PROBE)
        need(description_exact(description.get('content'),metadata['description']),'draft_readback_unconfirmed')
        class BoundPage:
            def locator(self,selector):
                # Existing hashtag leaves see exactly the same visible editor.
                return page.locator(editor_sel if selector in base.EDITORS else selector)
            def wait_for_timeout(self,*a):return page.wait_for_timeout(*a)
        original_snapshot=Workflow._hashtag_snapshot
        def bound_snapshot(self,bound_page):
            snapshot=original_snapshot(self,bound_page)
            # The leaf formats its input selector into :nth-match; bind this
            # output too, so a hidden original root cannot be selected later.
            gate.same(editor_sel,0,EDITOR);snapshot['selector']=editor_sel
            return snapshot
        Workflow._hashtag_snapshot=bound_snapshot  # isolated compiled class only
        workflow=Workflow(None);journal=folder/'FORM_JOURNAL.jsonl'
        with journal.open('xb'):pass
        workflow._journal_path=journal
        workflow._add_hashtags(BoundPage(),metadata['hashtags'],expected_description=metadata['description'])
        workflow._confirm_hashtag_form(BoundPage(),metadata['hashtags'],metadata['description'])
        gate.same(title_sel,0,TITLE);gate.same(editor_sel,0,EDITOR)
        title=page.locator(title_sel).evaluate(base.FIELD_PROBE);editor=workflow._hashtag_snapshot(BoundPage())
        need(title.get('content')==metadata['title'] and workflow._description_preserved(editor,metadata['description'])
             and all(t in editor['tokens'] for t in metadata['hashtags']),'draft_readback_unconfirmed')
        form=once(folder/'FORM_READBACK.json',dict(title=title,editor_text=editor['text'],hashtag_tokens=list(editor['tokens']),description_preserved=True))
        trigger_ref=once(folder/'DECLARATION_TRIGGER_PROJECTION.json',page.evaluate(trigger_projection_script()))
        count=page.locator(TRIGGER).count();need(count<=80,'draft_editor_unconfirmed')
        good=[]
        for i in range(count):
            check=page.locator(TRIGGER).nth(i).evaluate(trigger_check_script())
            if check.get('unique') and check.get('same'):good.append((i,check))
        if len(good)==1 and not good[0][1].get('expanded'):
            gate.expand_index=good[0][0];page.locator(TRIGGER).nth(gate.expand_index).click();page.wait_for_timeout(300)
        inventory=page.evaluate(base.declaration_inventory_script())
        need(inventory.get('location')==projection['location'] and inventory.get('hidden_state_read') is False,'draft_editor_unconfirmed')
        inv=once(folder/'EDITOR_DECLARATIONS.json',inventory);guard()
        result=dict(schema='manual_republication_existing_draft/v5',action='prepare_existing_draft',status='metadata_prepared_declarations_observed',
            action_claim=action_ref,file_selection_claim=request['file_selection_claim'],metadata=config['metadata'],media=metadata['media'],
            field_projection=project_ref,draft_fence=fence_ref,form_readback=form,title_readback=title,description_readback=description,hashtag_readback_verified=True,
            metadata_readback_matched=True,editor_inventory=inv,declaration_trigger_projection=trigger_ref,declaration_entry_expanded=gate.expanded,
            journal=reference(journal),submitted=False,declaration_selected=False,navigation_performed=False,file_selected=False,
            publication_ready=False,tab_id=raw.tab_id,limits=['Same original draft only. No fresh independent creator identity assertion.',
            'Declaration choices are observed, never selected. Missing native disclosure semantics leave the entry closed.'])
        once(folder/'PREPARED_RESULT.json',result);return result
    except Exception as error:
        code='draft_mutation_unknown' if gate.mutated else error.code if type(error) is ExistingDraftBlocked else 'draft_editor_unconfirmed'
        failure=dict(schema='manual_existing_draft_failure/v5',reason_code=code,cause_code=getattr(error,'code',None) if getattr(error,'code',None) in SAFE_REASONS else None,
            error_type=type(error).__name__,metadata_mutation_dispatched=gate.mutated,file_selected=False,navigation_performed=False,submitted=False)
        if not (folder/'PREPARE_FAILURE.json').exists():once(folder/'PREPARE_FAILURE.json',failure)
        raise ExistingDraftBlocked(code) from error
