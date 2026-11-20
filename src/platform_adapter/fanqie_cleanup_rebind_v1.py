"""Explicitly authorized exact-alias cleanup, separate from historical writes.

The caller supplies the original managed Page, fresh native snapshots and late
per-native-identity claims. Disabled native controls are recorded, never bypassed.
"""
import hashlib
import json
import os
from pathlib import Path
import secrets
import time

from .fanqie_filled_details_controls_v2 import _PUBLIC_DOM
from src.services import fanqie_promotion_identity_v2 as native


class CleanupBlocked(ValueError):
    def __init__(self,code):self.code=code;super().__init__(code)


def need(ok,code):
    if not ok:raise CleanupBlocked(code)


def reference(path):
    p=Path(path).resolve();return dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())


def read(ref):
    need(isinstance(ref,dict) and set(ref)=={'path','sha256'} and reference(ref['path'])==ref,'bound_evidence_changed')
    return json.loads(Path(ref['path']).read_text(encoding='utf-8-sig'))


def save(path,value):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf8') as f:json.dump(value,f,ensure_ascii=False,sort_keys=True);f.flush();os.fsync(f.fileno())
    return reference(p)


def target_from_row(snapshot,row):
    return dict(native_identity=native.native_identity(snapshot,row),**{k:row[k] for k in ('book_id','book_name','alias','publish_type','alias_status')})


def checked_snapshot(ref,request):
    snapshot=native.validate_snapshot(read(ref),require_fresh=True)
    need(all(snapshot.get(k)==request[k] for k in ('resource_id','binding_version','platform_identity_key'))
         and snapshot.get('pagination_complete') is True and snapshot.get('table_ready') is True
         and snapshot.get('identity_verified') is True and snapshot.get('challenge') is False,'fresh_complete_native_list_required')
    return snapshot


def native_matches(snapshot,target,*,after_delete=False):
    result=[]
    for row in snapshot['rows']:
        if row.get('identity_status')!='verified' or not row.get('native_record_id'):continue
        if native.native_identity(snapshot,row)==target['native_identity']:result.append(row)
    need(len(result)<=1,'native_identity_ambiguous')
    if result:
        actual=target_from_row(snapshot,result[0]);expected=dict(target)
        if after_delete:expected['alias_status']=actual['alias_status']
        need(actual==expected,'native_target_changed')
    return result


_DOM=_PUBLIC_DOM+r'''
 const usable=e=>!!e&&visible(e)&&!e.matches(':disabled,[aria-disabled="true"],[inert]')&&e.getAttribute('tabindex')!=='-1'
  &&!/(?:^|\s)arco-link-disabled(?:\s|$)/.test(e.className||'')&&getComputedStyle(e).cursor!=='not-allowed'&&getComputedStyle(e).pointerEvents!=='none';
 const hit=e=>{if(!usable(e))return false;const r=e.getBoundingClientRect();if(r.width<=0||r.height<=0)return false;
   const x=r.x+r.width/2,y=r.y+r.height/2;if(x<0||y<0||x>=innerWidth||y>=innerHeight)return false;
   const h=document.elementFromPoint(x,y);return h===e||e.contains(h)};
 const matching=t=>{const tables=[...document.querySelectorAll('table')].filter(visible);if(tables.length!==1)return [];
  const h=[...tables[0].querySelectorAll('thead th')].filter(visible).map(text),required=['关键词','书本信息','发文类型','别名状态','操作'];
  if(required.some(k=>h.filter(x=>x===k).length!==1))return [];
  return [...tables[0].querySelectorAll('tbody tr')].filter(visible).map((r,index)=>({r,index,c:[...r.children].filter(e=>e.tagName==='TD')}))
   .filter(x=>x.c.length===h.length&&text(x.c[h.indexOf('关键词')])===t.alias&&text(x.c[h.indexOf('发文类型')])===t.publish_type
    &&text(x.c[h.indexOf('别名状态')])===t.alias_status&&[...x.r.querySelectorAll('[class*="book-name"]')].filter(visible).map(text).join('\n')===t.book_name
    &&JSON.stringify((text(x.c[h.indexOf('书本信息')]).match(/ID\s*[:：]?\s*(\d{10,24})(?!\d)/ig)||[]).map(s=>s.match(/\d{10,24}/)[0]))===JSON.stringify([t.book_id]))
   .map(x=>({...x,op:x.c[h.indexOf('操作')]}));};
 const deletes=x=>[...x.op.querySelectorAll('button,a,span.arco-link,div.link,[role="button"]')].filter(e=>visible(e)&&text(e)==='删除');
 const deleteEligible=e=>usable(e)&&text(e)==='删除'&&!(e instanceof HTMLButtonElement&&e.type!=='button')
   &&!e.querySelector('input,textarea,select,button,a,[role="button"],[role="checkbox"],[role="radio"],[contenteditable="true"]');
 const modalState=(record)=>{const all=[...document.querySelectorAll('.arco-modal,[role="dialog"]')].filter(visible);
  const minimal=all.filter(e=>!all.some(o=>o!==e&&e.contains(o))),m=minimal.length===1?minimal[0]:null;
  const title=m?text(m.querySelector('.arco-modal-title')):'';
  const bodies=m?[...m.querySelectorAll('.arco-modal-body')].filter(visible):[],contents=m?[...m.querySelectorAll('.arco-modal-content')].filter(visible):[];
  const content=bodies.length===1?bodies[0]:bodies.length===0&&contents.length===1?contents[0]:null,body=content?text(content):'';
  const expected=['是否确认删除别名'+record.target.alias+'，该别名在结算有效期内，删除后将停止结算','是否确认删除别名'+record.target.alias+'，删除后将无法回填发文'];
  const buttons=m?[...m.querySelectorAll('button')].filter(e=>visible(e)&&text(e)==='删除'):[],b=buttons.length===1?buttons[0]:null;
  return {m,b,projection:{modal_count:minimal.length,title,body,body_source:content?.classList.contains('arco-modal-body')?'arco-modal-body':content?'arco-modal-content':null,
   body_count:bodies.length,content_count:contents.length,visible_modal_text:m?text(m).slice(0,2400):'',
   visible_child_containers:m?[...m.querySelectorAll('div,section,p')].filter(visible).slice(0,24).map(e=>({tag:e.tagName.toLowerCase(),class_name:(e.className||'').slice(0,240),text:text(e).slice(0,1600)})):[],
   expected_content:expected.includes(body),button:b?meta(b):null,
   eligible:!!m&&title==='删除别名'&&expected.includes(body)&&buttons.length===1&&b.type==='button'&&deleteEligible(b),center_hit:!!b&&hit(b)}};};
'''


def bind_script(target,token):
    public={k:target[k] for k in ('book_id','book_name','alias','publish_type','alias_status')}
    return '() => {'+_DOM+'const target='+json.dumps(public,ensure_ascii=False)+',key='+json.dumps(token)+r''';
 if(!allowed()||location.pathname!=='/page/promotion-list')return {eligible:false,reason:'origin'};
 const rows=matching(target);if(rows.length!==1)return {eligible:false,reason:'exact_row_not_unique',row_count:rows.length};
 const row=rows[0],controls=deletes(row);if(controls.length!==1)return {eligible:false,reason:'delete_control_not_unique',control_count:controls.length};
 const button=controls[0],projection={eligible:deleteEligible(button),row_count:1,control:meta(button),center_hit:hit(button)};
 window[key]={target,row:row.r,button,row_clicks:0,confirm_clicks:0};return projection;}'''


def boundary_script(token,phase,arm=False):
    return 'el => {'+_DOM+'const key='+json.dumps(token)+',phase='+json.dumps(phase)+r''';
 const record=window[key];if(!record)return {eligible:false,reason:'anchor_missing'};
 const rows=matching(record.target);const bound=rows.length===1&&rows[0].r===record.row&&record.row.isConnected;
 let button=record.button,projection={};
 if(phase==='confirm'){const state=modalState(record);button=state.b;projection=state.projection;record.modal=state.m;record.confirm=button;}
 const ok=bound&&el===button&&deleteEligible(button)&&(phase!=='confirm'||projection.eligible)&&hit(button);
 const result={eligible:!!ok,same_node:el===button,center_hit:!!button&&hit(button),modal:projection};
 ARM
 return result;}'''.replace('ARM',r'''
 if(ok){const listener=e=>{if(!e.composedPath().includes(button))return;
  const rs=matching(record.target),same=rs.length===1&&rs[0].r===record.row&&record.row.isConnected;
  const current=phase==='confirm'?modalState(record):null;
  const valid=same&&deleteEligible(button)&&hit(button)&&(phase!=='confirm'||current.m===record.modal&&current.b===button&&current.projection.eligible);
  const counter=phase==='confirm'?'confirm_clicks':'row_clicks';
  if(!valid||record[counter]!==0){e.preventDefault();e.stopImmediatePropagation();return;}record[counter]++;};
  window.addEventListener('click',listener,true);record.listener=listener;record.phase=phase;}
''' if arm else '')


def modal_script(token):
    return '() => {'+_DOM+'const r=window['+json.dumps(token)+'];return r?modalState(r).projection:{eligible:false,reason:"anchor_missing"};}'


def run_cleanup(page,*,request,request_ref,subject,guard,evidence_directory,refresh_native_snapshot,claim_delete):
    """One native confirmation per named native identity, no API/private state."""
    need(read(request_ref)==request and request.get('schema')=='fanqie_cleanup_rebind_request/v1' and request.get('action')=='cleanup_aliases','cleanup_request_required')
    need(request.get('delete_authorized') is True and isinstance(request.get('targets'),list) and 0<len(request['targets'])<=20,'explicit_targets_required')
    need(set(subject)=={'resource_id','binding_version','environment_key','platform_identity_key','owner_id','generation','task_id'}
         and all(subject[k]==request[k] for k in ('resource_id','binding_version','environment_key','platform_identity_key')),'managed_subject_changed')
    folder=Path(evidence_directory);folder.mkdir(parents=True,exist_ok=True)
    original,tab=getattr(page,'_session',None),getattr(page,'tab_id',None);results=[];deadline=time.monotonic()+420
    def check():
        need(time.monotonic()<deadline,'bounded_deadline');guard();need(reference(request_ref['path'])==request_ref,'request_changed')
        need(getattr(page,'_session',None) is original and getattr(page,'tab_id',None)==tab,'original_page_changed')
    def rpc(fn,*args,**kwargs):check();value=fn(*args,**kwargs);check();return value
    for number,target in enumerate(request['targets'],1):
        target_dir=folder/('%02d'%number);target_dir.mkdir()
        before_ref=refresh_native_snapshot('before_%02d'%number);snapshot=checked_snapshot(before_ref,request)
        need(native_matches(snapshot,target),'authorized_native_target_missing')
        nonce='__fanqie_cleanup_'+secrets.token_hex(16);before=rpc(page.evaluate,bind_script(target,nonce));save(target_dir/'DELETE_CONTROL.json',before)
        need(before.get('row_count')==1 and isinstance(before.get('control'),dict),'exact_native_delete_row_required')
        if before.get('eligible') is not True:
            results.append(dict(target=target,status='native_delete_unavailable',control=before));continue
        # The exact anchor is tagged with an opaque token; no owner/account IDs
        # enter the page. Native clicks still go through the existing Page RPC.
        # Use a fixed selector generated from the already verified row index;
        # same-node boundary checks reject any row replacement/reordering.
        location=rpc(page.evaluate,'() => {const r=window['+json.dumps(nonce)+'];return {row:[...r.row.closest("table").querySelectorAll("tbody tr")].indexOf(r.row),control:[...r.row.querySelectorAll("button,a,span.arco-link,div.link,[role=button]")].indexOf(r.button)};}')
        selector='table:visible tbody tr:nth-child('+str(location['row']+1)+') >> button,a,span.arco-link,div.link,[role="button"]'
        control=page.locator(selector).nth(location['control'])
        rpc(control.evaluate,'el=>{el.scrollIntoView({block:"center",inline:"nearest"});return true;}')
        proof=rpc(control.evaluate,boundary_script(nonce,'row',arm=True));save(target_dir/'DELETE_DISCLOSURE_PREFLIGHT.json',proof);need(proof.get('eligible') is True,'delete_disclosure_not_confirmed')
        save(target_dir/'DELETE_DISCLOSURE_INTENT.json',dict(target=target,native_delete_disclosure_limit=1))
        rpc(control.click,timeout=8000)
        modal=None
        for _ in range(12):
            modal=rpc(page.evaluate,modal_script(nonce))
            if modal.get('eligible') is True:break
            rpc(page.wait_for_timeout,150)
        modal_ref=save(target_dir/'DELETE_MODAL.json',modal);need(modal.get('eligible') is True,'native_confirmation_not_confirmed')
        # Locator.filter is not a reliable Page RPC filter. Use exact XPath.
        confirm=page.locator('.arco-modal:visible button >> xpath=self::*[normalize-space(.)="删除"]')
        proof=rpc(confirm.evaluate,boundary_script(nonce,'confirm',arm=True));need(proof.get('eligible') is True,'native_confirm_boundary_changed')
        preflight=save(target_dir/'DELETE_PREFLIGHT.json',dict(schema='fanqie_cleanup_delete_preflight/v1',request=request_ref,subject=subject,target=target,
            native_snapshot=before_ref,modal=modal_ref,boundary=proof,observed_at=time.time(),delete_limit=1))
        claim=claim_delete(preflight);need(reference(claim['path'])==claim,'delete_claim_changed');claimed=read(claim)
        need(claimed.get('schema')=='fanqie_cleanup_delete_claim/v1' and claimed.get('request')==request_ref and claimed.get('subject')==subject
             and claimed.get('target')==target and claimed.get('preflight')==preflight,'delete_claim_not_bound')
        save(target_dir/'DELETE_CONFIRM_INTENT.json',dict(claim=claim,confirmation_limit=1));check();ack=False
        try:confirm.click(timeout=8000);ack=True;check()
        except Exception as error:
            save(target_dir/'DELETE_UNKNOWN.json',dict(error_type=type(error).__name__,claim=claim,automatic_retry=False))
            return dict(schema='fanqie_cleanup_result/v1',status='deletion_unknown',results=results,target=target,claim=claim,automatic_retry=False)
        after_ref=refresh_native_snapshot('after_%02d'%number);after=checked_snapshot(after_ref,request)
        remaining=native_matches(after,target,after_delete=True);soft_deleted=bool(remaining and remaining[0].get('alias_status')=='已删除')
        result=dict(target=target,status='native_deleted_observed' if soft_deleted else 'deleted_not_observed_in_fresh_native_list' if not remaining else 'deletion_unknown',claim=claim,ack_returned=ack,after_snapshot=after_ref,
            row_retained_as_history=soft_deleted)
        save(target_dir/'DELETE_RESULT.json',result);results.append(result)
        if remaining and not soft_deleted:return dict(schema='fanqie_cleanup_result/v1',status='deletion_unknown',results=results,automatic_retry=False)
    return dict(schema='fanqie_cleanup_result/v1',status='cleanup_observed',results=results,automatic_retry=False,
        disabled_targets=[r['target'] for r in results if r['status']=='native_delete_unavailable'],uploaded=False,published=False,backfill_submitted=False)


def inspect_cleanup_state(page,*,request,request_ref,subject,guard,evidence_directory,refresh_native_snapshot):
    """Current native status plus actual controls, with no clicks or claims."""
    need(read(request_ref)==request and request.get('action')=='inspect_cleanup_state','cleanup_inspection_request_required')
    folder=Path(evidence_directory);folder.mkdir(parents=True,exist_ok=True);original,tab=getattr(page,'_session',None),getattr(page,'tab_id',None)
    snapshot_ref=refresh_native_snapshot('inspect_cleanup');snapshot=checked_snapshot(snapshot_ref,request);results=[]
    for number,target in enumerate(request['targets'],1):
        guard();need(reference(request_ref['path'])==request_ref and getattr(page,'_session',None) is original and getattr(page,'tab_id',None)==tab,'inspection_page_changed')
        matched=native_matches(snapshot,target,after_delete=True)
        if not matched:results.append(dict(target=target,status='not_observed_in_current_native_list',control=None));continue
        live_target=target_from_row(snapshot,matched[0]);token='__fanqie_cleanup_inspect_'+secrets.token_hex(16)
        control=page.evaluate(bind_script(live_target,token));guard()
        need(control.get('row_count')==1 and isinstance(control.get('control'),dict),'inspection_exact_row_required')
        evidence=save(folder/('CONTROL_%02d.json'%number),dict(target=target,live_target=live_target,control=control))
        results.append(dict(target=target,live_target=live_target,status='native_control_observed',native_delete_available=control.get('eligible') is True,evidence=evidence))
    return dict(schema='fanqie_cleanup_state_observation/v1',status='cleanup_state_observed',native_snapshot=snapshot_ref,targets=results,
        click_count=0,delete_claims_created=0,deleted=False,uploaded=False,published=False,backfill_submitted=False,old_records_changed=False)
