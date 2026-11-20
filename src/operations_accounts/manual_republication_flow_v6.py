"""Missing-only metadata repair of one existing draft, with durable RPC diagnosis.

No navigation, file selection, declaration selection or publication. Only bound
metadata values are read; native failures are bounded and sanitized in a journal.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import types
from types import SimpleNamespace
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[2]
SAFE_REASONS=frozenset('repair_'+s for s in ('request_invalid','binding_changed','claim_changed','output_changed',
    'session_changed','deadline_reached','editor_unconfirmed','field_not_unique','readback_unconfirmed','rpc_not_allowed','mutation_unknown'))
PREVIEW_TIP_SELECTOR='button:has-text("我知道了")'
PREVIEW_TIP_TITLE='视频预览功能'
PREVIEW_TIP_BODY='视频素材已按原始分辨率上传，为保证预览体验，视频会被压缩预览，实际播放时根据环境自动选组最佳分辨率播放。'


def preview_tip_script(element=False):
    body=r"""const visible=e=>!!e&&e.isConnected&&e.getClientRects().length>0&&!e.closest('[hidden],[aria-hidden="true"]')&&getComputedStyle(e).visibility!=='hidden';
      const norm=s=>String(s||'').replace(/\s/g,'');const title=TITLE,body=BODY;
      const buttons=[...document.querySelectorAll('button')].filter(e=>visible(e)&&norm(e.innerText)==='我知道了');
      const candidates=buttons.map(button=>{if(button.type!=='button'||button.disabled||button.getAttribute('aria-disabled')==='true')return null;
        for(let box=button.parentElement,depth=0;box&&depth<6;box=box.parentElement,depth++){
          if(box.querySelectorAll('*').length>100)continue;
          const text=norm(box.innerText);const controls=[...box.querySelectorAll('button,input,select,textarea,a[href],[contenteditable="true"],[role="option"],[role="radio"],[role="checkbox"],[role="switch"]')].filter(visible);
          if(text===norm(title+body+'我知道了')&&controls.length===1&&controls[0]===button)
            return {button,depth,title,body,button_text:'我知道了',button_type:button.type,visible_control_count:1};
        }return null;}).filter(Boolean);
      const selected=candidates.length===1?candidates[0]:null;
      return {schema:'manual_exact_preview_tip/v6',location:{origin:location.origin,path:location.pathname},visible_exact_button_count:buttons.length,
        candidate_count:candidates.length,eligible:buttons.length===1&&!!selected,same:typeof el==='undefined'?null:!!selected&&selected.button===el,
        evidence:selected?{title:selected.title,body:selected.body,button_text:selected.button_text,button_type:selected.button_type,visible_control_count:1,ancestor_depth:selected.depth}:null};"""
    body=body.replace('TITLE',json.dumps(PREVIEW_TIP_TITLE,ensure_ascii=False)).replace('BODY',json.dumps(PREVIEW_TIP_BODY,ensure_ascii=False))
    return ('el' if element else '()')+' => {'+body+'}'


class ExistingDraftRepairBlocked(ValueError):
    def __init__(self,code,diagnostics_ref=None):self.code=code;self.diagnostics_ref=diagnostics_ref;super().__init__(code)


def need(ok,code):
    if not ok:raise ExistingDraftRepairBlocked('repair_'+code)


def reference(path):
    p=Path(path).resolve();need(p.is_relative_to(ROOT) and p.is_file(),'binding_changed')
    with p.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    return dict(path=str(p),sha256=sha)


def read(ref):
    need(isinstance(ref,dict) and set(ref)=={'path','sha256'} and reference(ref['path'])==ref,'binding_changed')
    return json.loads(Path(ref['path']).read_text(encoding='utf8'))


def once(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as stream:
        stream.write((json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode());stream.flush();os.fsync(stream.fileno())
    return reference(path)


def safe_message(error):
    value=str(error).replace('\x00','')
    def public_url(match):
        try:
            u=urlsplit(match.group());host=u.hostname or ''
            if ':' in host:host='['+host+']'
            try:port=':'+str(u.port) if u.port is not None else ''
            except ValueError:port=''
            return u.scheme+'://'+host+port+u.path
        except ValueError:return '[url omitted]'
    value=re.sub(r'https?://[^\s\]\)\"\']+',public_url,value)
    value=re.sub(r'(?im)(authorization|cookie|set-cookie|access[_-]?token|refresh[_-]?token|password|storage_state)\s*[:=].*$',r'\1=[redacted]',value)
    return ''.join(c for c in value if c in '\n\t' or ord(c)>=32)[:1800]


def _load(config):
    path=ROOT/'src/operations_accounts/manual_republication_flow_v5.py';ref=config['sources']['flow_v5']
    need(reference(path)==ref,'binding_changed')
    module=types.ModuleType('src.operations_accounts._draft_repair_'+ref['sha256'][:16])
    module.__file__,module.__package__=str(path),'src.operations_accounts'
    exec(compile(path.read_bytes(),str(path),'exec'),module.__dict__)
    return module


def run_action(actor,resource,config,request,outdir):
    from . import manual_republication_runtime_v6 as runtime
    fields={'schema','config','action','prior_draft_plan','prior_draft_action','prior_unknown','prior_failure','field_projection','draft_fence'}
    need(isinstance(request,dict) and set(request)==fields and request['schema']=='manual_republication_operator_request/v6'
         and request['action']=='repair_existing_draft','request_invalid')
    need(read(request['config'])==config,'binding_changed')
    for key in fields-{'schema','config','action'}:read(request[key])
    folder=Path(outdir).resolve();need(folder.is_relative_to(ROOT/'data') and folder.name=='preparation','output_changed')
    action_ref=reference(folder.parent/'ACTION_CLAIM.json');action=read(action_ref);plan=read(action['plan'])
    need(action.get('schema')=='manual_republication_existing_draft_action_claim/v6' and action.get('action')==request['action']
         and action.get('config')==request['config'] and read(action['request'])==request
         and action.get('owner_id')==actor.owner_id and action.get('generation')==actor.generation
         and action.get('tab_id')==config['tab_id'] and action.get('actor_thread_id')==threading.get_ident()
         and action.get('navigation_allowed') is False and action.get('file_selection_allowed') is False
         and type(action.get('submissions_allowed')) is int and action['submissions_allowed']==0
         and plan.get('config')==request['config'] and plan.get('request')==action['request']
         and folder==Path(action['plan']['path']).resolve().parent/'preparation','claim_changed')
    need(not (folder/'DRAFT_REPAIR_INTENT.json').exists(),'claim_changed')
    previous_plan=read(request['prior_draft_plan']);previous_request=read(previous_plan['request'])
    selection_ref=previous_request['file_selection_claim'];selected=read(selection_ref)
    previous=_load(config);base=previous._load_base(config);reader,Workflow=base._load_leaves(config);metadata,authority=base._metadata(config)
    need(selected.get('schema')=='manual_file_selection_claim/v4' and selected.get('media')==metadata['media']
         and selected.get('metadata')==config['metadata'] and selected.get('authority')==config['authority']
         and all(selected.get(k)==config[k] for k in ('owner_id','generation','tab_id')),'claim_changed')
    prior=plan.get('prior',{});journal_ref=prior.get('upload_journal');nonce=prior.get('selection_nonce');baseline=prior.get('upload_route_baseline')
    need(isinstance(journal_ref,dict) and reference(journal_ref['path'])==journal_ref and isinstance(nonce,str) and re.fullmatch('[a-f0-9]{32}',nonce)
         and isinstance(baseline,dict),'claim_changed')
    rows=[json.loads(line) for line in Path(journal_ref['path']).read_text(encoding='utf8').splitlines() if line.strip()]
    proofs=[e['proof']['diagnostic'] for e in rows if e.get('stage')=='upload_check_transition_observed' and e.get('selection_nonce')==nonce and isinstance(e.get('proof'),dict)]
    keys=('initial_route','current_route','generation','routes','route_history_truncated')
    need(proofs and baseline=={k:proofs[-1].get(k) for k in keys} and baseline['initial_route']=='upload' and baseline['current_route']=='editor'
         and baseline['generation']==1 and baseline['route_history_truncated'] is False
         and baseline['routes']==[dict(route='upload',generation=0,event='begin'),dict(route='editor',generation=1,event='route_change')],'claim_changed')
    duration=prior.get('source_duration_seconds');need(type(duration) in {int,float} and math.isfinite(duration) and abs(duration-2896/24)<1e-6,'claim_changed')
    original=resource.session;deadline=time.monotonic()+180
    immutable=[request[k] for k in fields-{'schema','action'}]+[action_ref,selection_ref,journal_ref]
    def guard():
        need(time.monotonic()+45<=deadline,'deadline_reached')
        need(resource.session is original and original._proc is not None and original._proc.poll() is None,'session_changed')
        runtime.validate_live(actor,resource,config)
        for ref in immutable:need(reference(ref['path'])==ref,'binding_changed')
        b=resource.runtime.bindings.get(config['account_key']);p=resource.runtime.profiles.get(config['account_key'])
        need(b.account_uuid==p.account_uuid==config['account_id'] and reader._binding_version(SimpleNamespace(binding=b,profile=p))==config['binding_version']
             and str(b.public_uid)==authority['expected_public_uid'],'session_changed')
    guard();raw=original.get_page(config['tab_id']);guard();need(raw._session is original and raw.tab_id==config['tab_id'],'session_changed')
    folder.mkdir(parents=True,exist_ok=True);trace=folder/'RPC_TRACE.jsonl'
    with trace.open('xb'):pass
    phase='initial_read';last_error=None;last_exception=None
    def record(value):
        with trace.open('a',encoding='utf8') as stream:
            stream.write(json.dumps(dict(at_epoch=time.time(),**value),ensure_ascii=False)+'\n');stream.flush();os.fsync(stream.fileno())
    class Gate:
        def __init__(self):self.fields={};self.fills={};self.tags={};self.mutated=False;self.expanded=False;self.expand_index=None;self.tip_armed=False;self.tip_clicked=False
        def read(self,kind,**kw):
            nonlocal last_error,last_exception
            guard();info=dict(phase=phase,action=kind,selector=str(kw.get('selector',''))[:600],index=kw.get('index'))
            record(dict(**info,event='rpc_dispatched'))
            try:result=original.cmd(kind,tab_id=raw.tab_id,**kw)
            except Exception as error:
                last_exception=error;last_error=dict(**info,error_type=type(error).__name__,message=safe_message(error));record(dict(**last_error,event='rpc_error'));raise
            record(dict(**info,event='rpc_returned',return_status=str(result.get('status','ok'))[:80] if isinstance(result,dict) else 'non_dict'))
            guard();return result
        def same(self,sel,index,css):need(self.read('evaluate',selector=sel,index=index,js=previous.equality_script(css)).get('value') is True,'field_not_unique')
        def fence(self):
            proof=self.read('upload_check_proof',operation='observe',selection_nonce=nonce).get('proof',{});diag=proof.get('diagnostic',{})
            need(proof.get('schema')=='upload_check_transition/v2' and proof.get('selection_nonce')==nonce and all(diag.get(k)==baseline[k] for k in keys),'editor_unconfirmed')
            video=self.read('evaluate',selector='',index=-1,js=previous.VIDEO_PROBE).get('value',{})
            d=video.get('duration');ready=video.get('ready_state')
            need(video.get('origin')=='https://creator.douyin.com' and video.get('path')=='/creator-micro/content/post/video'
                 and video.get('visible_video_count')==1 and type(d) in {int,float} and math.isfinite(d) and abs(d-duration)<=.5
                 and type(ready) is int and ready>=1,'editor_unconfirmed')
            return dict(schema='manual_existing_draft_fence/v6',native_upload_proof=proof,video=video,original_journal=journal_ref,
                fresh_document_handle_claimed=False,platform_media_sha_verified=False,checker_verified_claimed=False)
        def cmd(self,kind,**kw):
            need(kw.pop('tab_id',raw.tab_id)==raw.tab_id,'session_changed');guard()
            if kind=='fill':
                sel=kw.get('selector');need(sel in self.fields and kw.get('value')==self.fields[sel][1] and not self.fills.get(sel),'rpc_not_allowed')
                self.fence();self.same(sel,kw.get('index',-1),self.fields[sel][0]);self.fills[sel]=1;self.mutated=True
            elif kind=='type_hashtag':
                tag=kw.get('tag');sels=kw.get('selectors',[])
                need(tag in metadata['hashtags'] and self.tags.get(tag,0)<2 and len(sels)==1,'rpc_not_allowed')
                self.fence();self.same(sels[0],0,previous.EDITOR);self.tags[tag]=self.tags.get(tag,0)+1;self.mutated=True
            elif kind=='click':
                if kw.get('selector')==PREVIEW_TIP_SELECTOR:
                    need(self.tip_armed and not self.tip_clicked and kw.get('index',-1) in {-1,0},'rpc_not_allowed')
                    self.fence();proof=self.read('evaluate',selector=PREVIEW_TIP_SELECTOR,index=0,js=preview_tip_script(True)).get('value',{})
                    need(proof.get('eligible') is True and proof.get('same') is True,'rpc_not_allowed');self.tip_clicked=True
                else:
                    need(kw.get('selector')==previous.TRIGGER and self.expand_index is not None and kw.get('index')==self.expand_index and not self.expanded,'rpc_not_allowed')
                    proof=self.read('evaluate',selector=previous.TRIGGER,index=self.expand_index,js=previous.trigger_check_script()).get('value',{})
                    need(proof.get('unique') and proof.get('same') and not proof.get('expanded'),'rpc_not_allowed');self.expanded=True
            elif kind=='screenshot':
                path=Path(kw.get('path','')).resolve();need(path.is_relative_to(folder) and not path.exists(),'rpc_not_allowed')
            else:need(kind in {'current_url','evaluate','locator_count','inner_text','get_attribute','wait_for_timeout'},'rpc_not_allowed')
            return self.read(kind,**kw)
    gate=Gate();page=base.Page(gate,raw.tab_id)
    def screenshot(name):
        try:
            path=folder/name;page._cmd('screenshot',path=str(path),full_page=False);return dict(file=reference(path),status='saved')
        except Exception as error:return dict(status='unavailable',error_type=type(error).__name__,message=safe_message(error))
    try:
        url=urlsplit(page._cmd('current_url')['url']);need(url.scheme=='https' and url.hostname=='creator.douyin.com' and url.path=='/creator-micro/content/post/video','editor_unconfirmed')
        projection=page.evaluate(previous.field_projection_script());project=once(folder/'INITIAL_FIELD_PROJECTION.json',projection)
        initialshot=screenshot('INITIAL_SCREENSHOT.png');once(folder/'INITIAL_SCREENSHOT_STATUS.json',initialshot)
        fence_ref=once(folder/'DRAFT_FENCE.json',gate.fence())
        phase='known_preview_tip_observation';tip_before=page.evaluate(preview_tip_script());tip_before_ref=once(folder/'PREVIEW_TIP_BEFORE.json',tip_before)
        tip_after_ref=None
        if tip_before.get('eligible') is True:
            once(folder/'PREVIEW_TIP_DISMISS_INTENT.json',dict(schema='manual_exact_preview_tip_dismiss/v6',action_claim=action_ref,
                tip=tip_before_ref,allowed_clicks=1,legal_or_verification_acceptance=False))
            phase='dismiss_known_preview_tip';gate.tip_armed=True;page.locator(PREVIEW_TIP_SELECTOR).first().click();samples=[]
            for _ in range(20):
                observed=page.evaluate(preview_tip_script());samples.append(observed)
                if observed.get('candidate_count')==observed.get('visible_exact_button_count')==0:break
                page.wait_for_timeout(100)
            tip_after_ref=once(folder/'PREVIEW_TIP_AFTER.json',dict(schema='manual_exact_preview_tip_after/v6',samples=samples,clicked_once=True))
            need(samples[-1].get('candidate_count')==samples[-1].get('visible_exact_button_count')==0,'editor_unconfirmed')
            projection=page.evaluate(previous.field_projection_script());once(folder/'POST_TIP_FIELD_PROJECTION.json',projection)
        title_sel=previous._choose(projection,previous.TITLE);editor_sel=previous._choose(projection,previous.EDITOR)
        gate.fields={title_sel:(previous.TITLE,metadata['title']),editor_sel:(previous.EDITOR,metadata['description'])}
        gate.same(title_sel,0,previous.TITLE);gate.same(editor_sel,0,previous.EDITOR)
        title=page.locator(title_sel).evaluate(base.FIELD_PROBE)
        class BoundPage:
            def locator(self,selector):return page.locator(editor_sel if selector in base.EDITORS else selector)
            def wait_for_timeout(self,*a):return page.wait_for_timeout(*a)
        original_snapshot=Workflow._hashtag_snapshot
        def snapshot(self,bound):
            value=original_snapshot(self,bound);gate.same(editor_sel,0,previous.EDITOR);value['selector']=editor_sel;return value
        Workflow._hashtag_snapshot=snapshot
        workflow=Workflow(None);before=workflow._hashtag_snapshot(BoundPage())
        description_core=before['text']
        for tag in before['tokens']:description_core=re.sub(r'[#＃]\s*'+re.escape(tag)+r'(?!\w)','',description_core)
        # Only ignore confirmed formatting. Unknown extra words force a full
        # authorized description replacement; a matching description is kept.
        title_missing=title.get('content')!=metadata['title']
        desc_missing=not previous.description_exact(description_core,metadata['description']) or any(t not in metadata['hashtags'] for t in before['tokens'])
        once(folder/'DRAFT_REPAIR_INTENT.json',dict(schema='manual_draft_repair_intent/v6',action_claim=action_ref,
            metadata=config['metadata'],file_selection_claim=selection_ref,title_fill_needed=title_missing,description_fill_needed=desc_missing,
            navigation_allowed=False,file_selection_allowed=False,submission_allowed=False))
        phase='fill_title' if title_missing else 'title_already_matches'
        if title_missing:page.locator(title_sel).fill(metadata['title'])
        phase='fill_description' if desc_missing else 'description_already_matches'
        if desc_missing:page.locator(editor_sel).fill(metadata['description'])
        phase='description_readback';description=page.locator(editor_sel).evaluate(base.FIELD_PROBE)
        if desc_missing:need(previous.description_exact(description.get('content'),metadata['description']),'readback_unconfirmed')
        phase='missing_hashtags';journal=folder/'FORM_JOURNAL.jsonl'
        with journal.open('xb'):pass
        workflow._journal_path=journal
        workflow._add_hashtags(BoundPage(),metadata['hashtags'],expected_description=metadata['description'])
        workflow._confirm_hashtag_form(BoundPage(),metadata['hashtags'],metadata['description'])
        phase='final_readback';gate.same(title_sel,0,previous.TITLE);gate.same(editor_sel,0,previous.EDITOR)
        title=page.locator(title_sel).evaluate(base.FIELD_PROBE);after=workflow._hashtag_snapshot(BoundPage())
        core=after['text']
        for tag in after['tokens']:core=re.sub(r'[#＃]\s*'+re.escape(tag)+r'(?!\w)','',core)
        need(title.get('content')==metadata['title'] and previous.description_exact(core,metadata['description']) and set(after['tokens'])==set(metadata['hashtags']),'readback_unconfirmed')
        # Return actual observed core text, not a metadata literal; hashtag
        # tokens and the full editor text stay in the separate exact receipt.
        desc_read=dict(description,content=core,content_basis='actual_visible_editor_text_with_observed_hashtag_tokens_removed')
        form=once(folder/'FORM_READBACK.json',dict(title=title,editor_text=after['text'],description_core=core,hashtag_tokens=list(after['tokens']),description_exact=True))
        phase='declaration_inventory';trigger=once(folder/'DECLARATION_TRIGGER_PROJECTION.json',page.evaluate(previous.trigger_projection_script()))
        count=page.locator(previous.TRIGGER).count();need(count<=80,'editor_unconfirmed');good=[]
        for i in range(count):
            check=page.locator(previous.TRIGGER).nth(i).evaluate(previous.trigger_check_script())
            if check.get('unique') and check.get('same'):good.append((i,check))
        if len(good)==1 and not good[0][1].get('expanded'):
            gate.expand_index=good[0][0];phase='expand_proven_declaration';page.locator(previous.TRIGGER).nth(gate.expand_index).click();page.wait_for_timeout(300)
        phase='declaration_readback';inventory=page.evaluate(base.declaration_inventory_script());need(inventory.get('location')==projection['location'],'editor_unconfirmed')
        inv=once(folder/'EDITOR_DECLARATIONS.json',inventory);guard();phase='complete'
        result=dict(schema='manual_republication_existing_draft/v6',action='repair_existing_draft',status='metadata_prepared_declarations_observed',
            action_claim=action_ref,file_selection_claim=selection_ref,metadata=config['metadata'],media=metadata['media'],initial_field_projection=project,
            initial_screenshot=initialshot,draft_fence=fence_ref,title_fill_skipped=not title_missing,description_fill_skipped=not desc_missing,
            title_readback=title,description_readback=desc_read,metadata_readback_matched=True,hashtag_readback_verified=True,form_readback=form,
            declaration_trigger_projection=trigger,editor_inventory=inv,declaration_entry_expanded=gate.expanded,rpc_trace=reference(trace),journal=reference(journal),
            preview_tip_before=tip_before_ref,preview_tip_after=tip_after_ref,preview_tip_dismissed=gate.tip_clicked,
            submitted=False,declaration_selected=False,navigation_performed=False,file_selected=False,publication_ready=False,tab_id=raw.tab_id)
        once(folder/'PREPARED_RESULT.json',result);return result
    except Exception as error:
        original_error=last_error if last_exception is error else dict(phase=phase,action=None,selector=None,index=None,error_type=type(error).__name__,message=safe_message(error))
        phase='failure_readonly_capture';capture={}
        try:
            guard();data=page.evaluate(previous.field_projection_script());capture['field_projection']=once(folder/'FAILURE_FIELD_PROJECTION.json',data)
            capture['screenshot']=screenshot('FAILURE_SCREENSHOT.png')
        except Exception as capture_error:capture['unavailable']=dict(error_type=type(capture_error).__name__,message=safe_message(capture_error))
        code='repair_mutation_unknown' if gate.mutated else error.code if type(error) is ExistingDraftRepairBlocked else 'repair_editor_unconfirmed'
        failure=dict(schema='manual_existing_draft_failure/v6',reason_code=code,cause_code=getattr(error,'code',None),safe_error=original_error,
            metadata_mutation_dispatched=gate.mutated,failure_capture=capture,rpc_trace=reference(trace),file_selected=False,navigation_performed=False,submitted=False)
        failure_ref=once(folder/'PREPARE_FAILURE.json',failure)
        raise ExistingDraftRepairBlocked(code,failure_ref) from error
