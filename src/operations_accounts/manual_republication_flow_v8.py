"""Inspect the observed roleless declaration disclosure on the original draft."""
import json
import math
import re
import secrets
import threading
import time
import types
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[2]
SAFE_REASONS=frozenset('declaration_'+s for s in ('request_invalid','binding_changed','claim_changed','output_changed','session_changed',
    'deadline_reached','editor_unconfirmed','form_changed','trigger_unconfirmed','options_unconfirmed','rpc_not_allowed','disclosure_unknown'))
TRIGGER='section.wrapper-MLZdnB > div.controlWrapper-Kt_9Xm > div.selectBox-buZRzi'
LOCATION={'origin':'https://creator.douyin.com','path':'/creator-micro/content/post/video'}


class DeclarationInspectionBlocked(ValueError):
    def __init__(self,code,diagnostics_ref=None):self.code=code;self.diagnostics_ref=diagnostics_ref;super().__init__(code)


def need(ok,code):
    if not ok:raise DeclarationInspectionBlocked('declaration_'+code)


def _previous(config):
    path=ROOT/'src/operations_accounts/manual_republication_flow_v7.py'
    from .manual_republication_runtime_v8 import reference
    need(reference(path)==config['sources']['flow_v7'],'binding_changed')
    module=types.ModuleType('src.operations_accounts._declaration_parent_'+config['sources']['flow_v7']['sha256'][:16])
    module.__file__,module.__package__=str(path),'src.operations_accounts'
    exec(compile(path.read_bytes(),str(path),'exec'),module.__dict__)
    return module,module._load(config)


def trigger_script(mode,nonce,element=False):
    """Only opaque nonce/node references enter the renderer, never owner IDs."""
    need(mode in {'arm','check','events','cleanup'} and re.fullmatch('[a-f0-9]{32}',nonce),'request_invalid')
    body=r"""
 const key=KEY,mode=MODE,visible=e=>!!e&&e.isConnected&&e.getClientRects().length>0&&!e.closest('[hidden],[aria-hidden="true"], [inert]')&&(()=>{for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||['hidden','collapse'].includes(s.visibility)||Number(s.opacity)===0)return false}return true})();
 const forbidden='button,input,select,textarea,a[href],form,[contenteditable="true"],[role="option"],[role="radio"],[role="checkbox"],[role="switch"],[role="button"]';
 function inspect(){
   const sections=[...document.querySelectorAll('section.wrapper-MLZdnB')].filter(s=>visible(s)&&[...s.querySelectorAll(':scope > div.labelWrapper-p6osJm > div.title-cnbkZe')].filter(e=>visible(e)&&e.innerText.trim()==='自主声明').length===1);
   const controls=sections.flatMap(s=>[...s.querySelectorAll(':scope > div.controlWrapper-Kt_9Xm > div.selectBox-buZRzi')].filter(visible));
   const e=controls.length===1?controls[0]:null;const texts=e?[...e.querySelectorAll(':scope > div.selectText-XSrMFZ')].filter(visible):[];
   let hit=false,cursor='',pointer='',usable=false;let rect=null;
   if(e){const r=e.getBoundingClientRect();rect={x:r.x,y:r.y,width:r.width,height:r.height};const x=r.left+r.width/2,y=r.top+r.height/2;
     const top=document.elementFromPoint(x,y);hit=x>=0&&y>=0&&x<innerWidth&&y<innerHeight&&!!top&&(top===e||e.contains(top));
     cursor=getComputedStyle(e).cursor;pointer=getComputedStyle(e).pointerEvents;usable=!e.matches(forbidden)&&!e.querySelector(forbidden)&&!/(发布|确认|删除|保存|重置)/.test(e.innerText);
     for(let p=e;p;p=p.parentElement){if(p.matches(':disabled,[aria-disabled="true"],[inert]')||getComputedStyle(p).pointerEvents==='none')usable=false;}}
   const eligible=location.origin==='https://creator.douyin.com'&&location.pathname==='/creator-micro/content/post/video'&&sections.length===1&&controls.length===1&&texts.length===1&&texts[0].innerText.trim()==='请选择自主声明'&&cursor==='pointer'&&pointer!=='none'&&hit&&usable;
   return {e,public:{schema:'manual_native_declaration_trigger/v8',location:{origin:location.origin,path:location.pathname},section_count:sections.length,control_count:controls.length,value_count:texts.length,
     value:texts.length===1?texts[0].innerText.trim():null,cursor,pointer_events:pointer,center_hit:hit,view_only_eligible:usable,eligible,rect}};
 }
 if(mode==='cleanup'){const old=window[key];if(old){for(const t of ['pointerdown','mousedown','click'])document.removeEventListener(t,old.gate,true);delete window[key];}return {cleaned:true};}
 if(mode==='events'){const old=window[key];return old?{allowed_clicks:old.clicks,blocked_events:old.blocked}:null;}
 const found=inspect();let record=window[key];
 if(mode==='arm'){
   if(record||!found.public.eligible)return {...found.public,armed:false};
   record={node:found.e,clicks:0,blocked:0,before:new Set([...document.querySelectorAll('body *')].filter(visible))};
   record.gate=event=>{const fresh=inspect();const target=event.target;
     const allowed=record.clicks===0&&fresh.public.eligible&&fresh.e===record.node&&record.node.isConnected&&(target===record.node||record.node.contains(target))&&!target.closest(forbidden);
     if(!allowed){event.preventDefault();event.stopImmediatePropagation();record.blocked++;}else if(event.type==='click'){record.clicks++;}};
   for(const t of ['pointerdown','mousedown','click'])document.addEventListener(t,record.gate,true);window[key]=record;
 }
 return {...found.public,armed:!!record,same:!!record&&record.node===found.e&&(typeof el==='undefined'||el===record.node),allowed_clicks:record?record.clicks:null,blocked_events:record?record.blocked:null};
 """
    return ('el' if element else '()')+' => {'+body.replace('KEY',json.dumps('__manual_decl_'+nonce)).replace('MODE',json.dumps(mode))+'}'


def options_script(nonce):
    need(re.fullmatch('[a-f0-9]{32}',nonce),'request_invalid')
    return r"""() => {
 const old=window[KEY];const visible=e=>!!e&&e.isConnected&&e.getClientRects().length>0&&!e.closest('[hidden],[aria-hidden="true"],[inert]')&&(()=>{for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||['hidden','collapse'].includes(s.visibility)||Number(s.opacity)===0)return false}return true})();
 const all=[...document.querySelectorAll('body *')].filter(e=>visible(e)&&!['SCRIPT','STYLE','NOSCRIPT'].includes(e.tagName));
 const fresh=old?all.filter(e=>!old.before.has(e)):[];const set=new Set(fresh),roots=fresh.filter(e=>!set.has(e.parentElement));
 const formSelector='video,input[type="file"],input[placeholder="填写作品标题，为作品获得更多流量"],div[data-slate-editor="true"].editor[contenteditable="true"]';
 const unsafe=roots.some(e=>e.matches(formSelector)||e.querySelector(formSelector));
 const text=roots.map(e=>e.innerText||'').join('\n');const truncated=roots.length>20||fresh.length>600||text.length>30000;
 const nodes=fresh.slice(0,600).map(e=>({tag:e.tagName.toLowerCase(),class_name:typeof e.className==='string'?e.className.slice(0,300):'',role:e.getAttribute('role'),
   text:[...e.children].some(visible)?null:(e.innerText||'').trim().slice(0,1600),type:e.getAttribute('type'),
   checked:typeof e.checked==='boolean'?e.checked:null,aria_checked:e.getAttribute('aria-checked'),aria_selected:e.getAttribute('aria-selected'),
   aria_multiselectable:e.getAttribute('aria-multiselectable'),data_state:e.getAttribute('data-state'),disabled:e.matches(':disabled,[aria-disabled="true"]')}));
 const explicitMulti=fresh.some(e=>e.getAttribute('aria-multiselectable')==='true'),explicitSingle=fresh.some(e=>e.getAttribute('role')==='listbox'&&e.getAttribute('aria-multiselectable')==='false');
 return {schema:'manual_native_declaration_options/v8',location:{origin:location.origin,path:location.pathname},root_count:roots.length,node_count:fresh.length,
   roots:roots.slice(0,20).map(e=>({tag:e.tagName.toLowerCase(),class_name:typeof e.className==='string'?e.className.slice(0,300):'',role:e.getAttribute('role'),visible_text:(e.innerText||'').slice(0,30000)})),
   native_nodes:nodes,visible_text:text.slice(0,30000),truncated,complete_visible_capture:!!old&&old.clicks===1&&old.blocked===0&&roots.length>0&&fresh.length>0&&text.trim().length>0&&!truncated&&!unsafe,
   selection_semantics:explicitMulti?'explicit_multiple':explicitSingle?'explicit_single':'unknown',
   semantics_basis:'native_aria_only_no_inference_from_custom_classes',selected_state_basis:'native_checked_aria_or_raw_data_state_only',
   declaration_values_selected_by_this_action:false,confirmation_clicked:false,unsafe_full_form_replacement:unsafe};
 }""".replace('KEY',json.dumps('__manual_decl_'+nonce))


def run_action(actor,resource,config,request,outdir):
    from . import manual_republication_runtime_v8 as runtime
    reference,read,once=runtime.reference,runtime._read,runtime._once
    need(isinstance(request,dict) and set(request)=={'schema','config','action',*runtime.PRIOR_FIELDS}
         and request['schema']==runtime.REQUEST_SCHEMA and request['action']==runtime.ACTION,'request_invalid')
    need(read(request['config'])==config,'binding_changed')
    folder=Path(outdir).resolve();need(folder.name=='inspection' and folder.is_relative_to(ROOT/'data'),'output_changed')
    action_ref=reference(folder.parent/'ACTION_CLAIM.json');action=read(action_ref);plan=read(action['plan'])
    need(action.get('schema')=='manual_republication_declaration_action_claim/v8' and action.get('action')==request['action']
         and action.get('config')==request['config'] and read(action['request'])==request and plan.get('config')==request['config'] and plan.get('request')==action['request']
         and all(action.get(k)==config[k] for k in ('owner_id','generation','tab_id')) and action.get('actor_thread_id')==threading.get_ident()
         and action.get('navigation_allowed') is False and action.get('file_selection_allowed') is False and action.get('submissions_allowed')==0
         and folder==Path(action['plan']['path']).resolve().parent/'inspection','claim_changed')
    parent,previous=_previous(config);leaf=previous._load_base(config);reader,Workflow=leaf._load_leaves(config);metadata,authority=leaf._metadata(config)
    prior=plan['prior'];nonce=prior['selection_nonce'];baseline=prior['upload_route_baseline'];duration=prior['source_duration_seconds'];original=resource.session
    need(prior['file_selection_claim']==request['file_selection_claim'],'claim_changed')
    deadline=time.monotonic()+90;immutable=[action_ref,*[request[k] for k in runtime.PRIOR_FIELDS],request['config'],prior['upload_journal']]
    def guard():
        need(time.monotonic()+10<deadline,'deadline_reached')
        need(resource.session is original and original._proc is not None and original._proc.poll() is None,'session_changed')
        runtime.validate_live(actor,resource,config)
        for ref in immutable:need(reference(ref['path'])==ref,'binding_changed')
        binding=resource.runtime.bindings.get(config['account_key']);profile=resource.runtime.profiles.get(config['account_key'])
        need(binding.account_uuid==profile.account_uuid==config['account_id'] and reader._binding_version(SimpleNamespace(binding=binding,profile=profile))==config['binding_version']
             and str(binding.public_uid)==authority['expected_public_uid'],'session_changed')
    guard();raw=original.get_page(config['tab_id']);guard();need(raw._session is original and raw.tab_id==config['tab_id'],'session_changed')
    folder.mkdir(parents=True,exist_ok=True);trace=folder/'RPC_TRACE.jsonl'
    with trace.open('xb'):pass
    token=secrets.token_hex(32)[:32];clicked=False;armed=False;phase='initial_read'
    def record(value):
        with trace.open('a',encoding='utf8') as stream:stream.write(json.dumps(dict(at_epoch=time.time(),phase=phase,**value),ensure_ascii=False)+'\n');stream.flush()
    class Gate:
        def cmd(self,kind,**kw):
            nonlocal clicked
            need(kw.pop('tab_id',raw.tab_id)==raw.tab_id,'session_changed');guard()
            if kind=='click':
                need(armed and not clicked and kw.get('selector')==TRIGGER+':visible' and kw.get('index',-1) in {-1,0},'rpc_not_allowed')
                proof=self.cmd('evaluate',selector=TRIGGER+':visible',index=0,js=trigger_script('check',token,True)).get('value',{})
                need(proof.get('eligible') is True and proof.get('same') is True and proof.get('allowed_clicks')==0,'trigger_unconfirmed');clicked=True
            elif kind=='screenshot':need(Path(kw.get('path','')).resolve()==folder/'DECLARATION_OPTIONS.png' and not Path(kw['path']).exists(),'rpc_not_allowed')
            elif kind=='upload_check_proof':need(kw.get('operation')=='observe' and kw.get('selection_nonce')==nonce,'rpc_not_allowed')
            else:need(kind in {'current_url','evaluate','locator_count','inner_text','get_attribute','wait_for_timeout'},'rpc_not_allowed')
            record(dict(event='rpc_dispatched',action=kind,selector=kw.get('selector'),index=kw.get('index')))
            result=original.cmd(kind,tab_id=raw.tab_id,**kw);guard();record(dict(event='rpc_returned',action=kind));return result
    gate=Gate();page=leaf.Page(gate,raw.tab_id)
    def fence():
        proof=page._cmd('upload_check_proof',operation='observe',selection_nonce=nonce).get('proof',{});diag=proof.get('diagnostic',{})
        need(proof.get('schema')=='upload_check_transition/v2' and proof.get('selection_nonce')==nonce and all(diag.get(k)==v for k,v in baseline.items()),'editor_unconfirmed')
        video=page.evaluate(previous.VIDEO_PROBE);d=video.get('duration')
        need(video.get('origin')==LOCATION['origin'] and video.get('path')==LOCATION['path'] and video.get('visible_video_count')==1
             and type(d) in {int,float} and math.isfinite(d) and abs(d-duration)<=.5 and type(video.get('ready_state')) is int and video['ready_state']>=1,'editor_unconfirmed')
        return dict(schema='manual_declaration_draft_fence/v8',native_upload_proof=proof,video=video,original_journal=prior['upload_journal'],
            fresh_document_handle_claimed=False,platform_media_sha_verified=False,checker_verified_claimed=False)
    def form():
        projection=page.evaluate(previous.field_projection_script());title_sel=previous._choose(projection,previous.TITLE);editor_sel=previous._choose(projection,previous.EDITOR)
        need(page.locator(title_sel).evaluate(previous.equality_script(previous.TITLE)) and page.locator(editor_sel).evaluate(previous.equality_script(previous.EDITOR)),'form_changed')
        title=page.locator(title_sel).evaluate(leaf.FIELD_PROBE)
        class Bound:
            def locator(self,selector):return page.locator(editor_sel)
        snapshot=Workflow(None)._hashtag_snapshot(Bound());core=snapshot['text']
        for tag in snapshot['tokens']:core=re.sub(r'[#＃]\s*'+re.escape(tag)+r'(?!\w)','',core)
        need(title.get('content')==metadata['title'] and previous.description_exact(core,metadata['description']) and set(snapshot['tokens'])==set(metadata['hashtags']),'form_changed')
        return dict(title=title,description_core=core,editor_text=snapshot['text'],hashtag_tokens=list(snapshot['tokens']),description_exact=True)
    try:
        location=urlsplit(page._cmd('current_url')['url']);need(location.scheme=='https' and location.hostname=='creator.douyin.com' and location.path==LOCATION['path'],'editor_unconfirmed')
        fence_ref=once(folder/'DRAFT_FENCE.json',fence());before_form=once(folder/'FORM_BEFORE.json',form())
        before=page.evaluate(trigger_script('arm',token));armed=before.get('armed') is True
        before_ref=once(folder/'TRIGGER_BEFORE.json',before);need(armed and before.get('eligible') is True and before.get('same') is True,'trigger_unconfirmed')
        fence();once(folder/'DISCLOSURE_CLICK_INTENT.json',dict(schema='manual_declaration_disclosure_intent/v8',action_claim=action_ref,trigger=before_ref,allowed_clicks=1,allowed_selections=0,allowed_confirmations=0))
        phase='open_native_declaration';page.locator(TRIGGER+':visible').first().click()
        phase='observe_options';samples=[];last=None;stable=0;inventory=None
        for _ in range(12):
            inventory=page.evaluate(options_script(token));signature=json.dumps(inventory,sort_keys=True,ensure_ascii=False)
            stable=stable+1 if signature==last else 1;last=signature;samples.append(dict(complete=inventory.get('complete_visible_capture'),root_count=inventory.get('root_count'),node_count=inventory.get('node_count')))
            if stable>=2 and inventory.get('complete_visible_capture') is True:break
            page.wait_for_timeout(200)
        options=once(folder/'DECLARATION_OPTIONS.json',inventory);once(folder/'OPTION_OBSERVATION_SAMPLES.json',samples)
        events=page.evaluate(trigger_script('events',token));events_ref=once(folder/'DISCLOSURE_EVENTS.json',events)
        need(events=={'allowed_clicks':1,'blocked_events':0} and inventory.get('location')==LOCATION and inventory.get('complete_visible_capture') is True and inventory.get('truncated') is False,'options_unconfirmed')
        after_form=once(folder/'FORM_AFTER.json',form());shot={'status':'unavailable'}
        try:
            path=folder/'DECLARATION_OPTIONS.png';page._cmd('screenshot',path=str(path),full_page=False);shot={'status':'saved','file':reference(path)}
        except Exception as error:shot={'status':'unavailable','error_type':type(error).__name__}
        result=dict(schema='manual_republication_declaration_inspection/v8',action=runtime.ACTION,action_claim=action_ref,file_selection_claim=request['file_selection_claim'],
            prepared_result=request['prepared_result'],form_before=before_form,form_after=after_form,metadata_readback_matched=True,draft_fence=fence_ref,
            trigger=before_ref,trigger_click_count=1,disclosure_events=events_ref,options_inventory=options,options_observed=True,screenshot=shot,rpc_trace=reference(trace),same_tab=raw.tab_id,
            submitted=False,declaration_selected=False,confirmed=False,navigation_performed=False,file_selected=False,fields_written=False,publication_ready=False)
        once(folder/'INSPECTION_RESULT.json',result);return result
    except Exception as error:
        ref=once(folder/'INSPECTION_FAILURE.json',dict(schema='manual_declaration_inspection_failure/v8',reason_code=getattr(error,'code','declaration_disclosure_unknown'),error_type=type(error).__name__,
            phase=phase,trigger_click_dispatched=clicked,rpc_trace=reference(trace),submitted=False,declaration_selected=False,confirmed=False,fields_written=False,file_selected=False,navigation_performed=False))
        raise DeclarationInspectionBlocked(error.code if type(error) is DeclarationInspectionBlocked else 'declaration_disclosure_unknown',ref) from error
    finally:
        if armed:
            # Remove only our inert event fence after the final trace SHA was
            # bound. Do not append to that sealed trace during cleanup.
            try:guard();original.cmd('evaluate',tab_id=raw.tab_id,selector='',index=-1,js=trigger_script('cleanup',token))
            except Exception:pass
