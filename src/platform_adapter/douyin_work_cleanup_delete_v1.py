"""Original native batch UI, including a separately claimed exact confirmation."""
import json
import re
import hashlib
from pathlib import Path
import time


ENTRY='div.FmoW3iJu:visible >> xpath=self::*[normalize-space(.)="批量管理"]'
_COMMON=r'''
 const loc={origin:location.origin,path:location.pathname};
 const allowed=location.origin==='https://www.douyin.com'&&location.pathname==='/user/self';
 const visible=e=>!!e&&e.isConnected&&e.getClientRects().length>0&&!e.closest('[hidden],[aria-hidden="true"],[inert]')&&getComputedStyle(e).visibility!=='hidden';
 const text=e=>(e?.innerText||'').trim();
 const id=href=>{try{const u=new URL(href,location.href),m=u.pathname.match(/^\/video\/(\d{10,24})\/?$/);return u.protocol==='https:'&&!u.username&&!u.password&&['douyin.com','www.douyin.com'].includes(u.host)&&m?m[1]:null}catch{return null}};
 const ids=e=>e?[...new Set([...e.querySelectorAll('a[href]')].filter(visible).map(a=>id(a.getAttribute('href'))).filter(Boolean))]:[];
 const meta=e=>({tag:e.tagName.toLowerCase(),role:e.getAttribute('role')||'',class_name:(e.getAttribute('class')||'').slice(0,300),text:text(e).slice(0,700),
   type:e.tagName==='BUTTON'?e.type:e.getAttribute('type')||'',disabled:e.matches(':disabled,[aria-disabled="true"]')});
'''
ENTRY_PROBE='el=>{'+_COMMON+r'''
 if(!allowed)return {eligible:false,location:loc};
 const matches=[...document.querySelectorAll('div.FmoW3iJu')].filter(e=>visible(e)&&text(e)==='批量管理');
 return {location:loc,unique_count:matches.length,metadata:meta(el),eligible:matches.length===1&&el===matches[0]&&el.tagName==='DIV'&&
   !el.matches('[aria-disabled="true"],[role="checkbox"],[role="radio"]')&&!el.querySelector('button,a,input,select,textarea')&&getComputedStyle(el).pointerEvents!=='none'};
}'''
BATCH_JS='()=>{'+_COMMON+r'''
 if(!allowed)return {schema:'douyin_batch_controls/v1',location:loc,ready:false,reason:'original_profile_required'};
 const native=[...document.querySelectorAll('input[type="checkbox"],input[type="radio"]')];
 const labels=[...document.querySelectorAll('label')].filter(visible);
 const nativeRows=native.slice(0,80).map((e,index)=>{const ls=labels.filter(l=>l.control===e);const readable=visible(e)||ls.length>0;
   const groups=[...new Set([e.closest('li'),...ls.map(l=>l.closest('li'))].filter(x=>visible(x)))];
   const postIds=[...new Set(groups.flatMap(ids))];
   return {index,tag:'input',type:e.type,name:(e.getAttribute('name')||'').slice(0,200),id:(e.id||'').slice(0,200),class_name:(e.getAttribute('class')||'').slice(0,300),
     native_visible:visible(e),label_associations:ls.map(l=>({text:text(l).slice(0,700),class_name:(l.getAttribute('class')||'').slice(0,300),
       association:l.contains(e)?'native_wrapping_label':l.htmlFor?'native_for_control':'native_label_control',post_ids:ids(l.closest('li'))})),
     checked_read_allowed:readable,checked:readable?e.checked:null,aria_checked:e.getAttribute('aria-checked'),disabled:e.disabled===true,post_ids:postIds,unique_native_post_id:postIds.length===1?postIds[0]:null};});
 const roles=[...document.querySelectorAll('[role="checkbox"],[role="radio"]')].filter(visible);
 const roleRows=roles.slice(0,80).map((e,index)=>({index,...meta(e),aria_checked:e.getAttribute('aria-checked'),post_ids:ids(e.closest('li'))}));
 const buttons=[...document.querySelectorAll('button,[role="button"]')].filter(visible);
 const modals=[...document.querySelectorAll('[role="dialog"],.semi-modal')].filter(visible);
 const leaves=[...document.querySelectorAll('span,div,p')].filter(e=>visible(e)&&!e.children.length&&!e.closest('input,textarea,[contenteditable="true"]'));
 return {schema:'douyin_batch_controls/v1',location:loc,ready:true,native_controls:nativeRows,role_controls:roleRows,
   native_control_count:native.length,role_control_count:roles.length,buttons:buttons.slice(0,80).map(meta),
   visible_modal_count:modals.length,modals:modals.slice(0,5).map(e=>({tag:e.tagName.toLowerCase(),role:e.getAttribute('role')||'',class_name:(e.getAttribute('class')||'').slice(0,300),text:text(e).slice(0,8000)})),
   visible_text_lines:leaves.slice(0,180).map(e=>text(e).slice(0,700)),truncated:native.length>80||roles.length>80||buttons.length>80||modals.length>5||leaves.length>180,
   input_values_read:false,private_state_read:false,selection_performed:false,delete_performed:false,confirmation_performed:false};
}'''


def _ready(value,expected_uid,delete_ids,protected_ids):
    cards=value.get('cards',[])
    observed={c.get('native_post_id'):c for c in cards if c.get('native_id_bound') is True}
    if (value.get('surface')!='original_self_profile' or value.get('public_uids')!=[expected_uid] or value.get('truncated') is not False
            or len(cards)!=4 or set(observed)!=set(delete_ids)|set(protected_ids)
            or any(observed[p].get('status_text')!='流量减少' or observed[p].get('reduced_traffic_label_count')!=1 for p in delete_ids)):
        raise ValueError('cleanup_current_exact_native_targets_required')


def open_batch_controls(page,*,guard,checkpoint,inventory_script,expected_uid,delete_ids,protected_ids):
    owner,tab=getattr(page,'_session',None),getattr(page,'tab_id',None)
    def rpc(method,*args,**kwargs):
        guard()
        if getattr(page,'_session',None) is not owner or getattr(page,'tab_id',None)!=tab:raise ValueError('cleanup_original_page_changed')
        value=method(*args,**kwargs);guard();return value
    initial=rpc(page.evaluate,inventory_script);checkpoint('before_native_cards',initial);_ready(initial,expected_uid,delete_ids,protected_ids)
    entry=page.locator(ENTRY).nth(0);proof=rpc(entry.evaluate,ENTRY_PROBE)
    checkpoint('batch_entry_proof',proof)
    if proof.get('eligible') is not True:raise ValueError('cleanup_unique_observed_batch_entry_required')
    checkpoint('batch_entry_intent',dict(native_click_limit=1,entry=proof,selections_allowed=0,deletions_allowed=0,confirmations_allowed=0))
    _ready(rpc(page.evaluate,inventory_script),expected_uid,delete_ids,protected_ids)
    if rpc(entry.evaluate,ENTRY_PROBE)!=proof:raise ValueError('cleanup_batch_entry_changed')
    ack=False;error=None
    try:rpc(entry.click,timeout=8000);ack=True
    except Exception as exc:error=type(exc).__name__
    samples=[];prior=None;stable=0
    for _ in range(8):
        value=rpc(page.evaluate,BATCH_JS);samples.append(value);signature=json.dumps(value,sort_keys=True,ensure_ascii=False)
        stable=stable+1 if signature==prior else 1;prior=signature
        if stable>=2:break
        rpc(page.wait_for_timeout,200)
    checkpoint('batch_controls_samples',dict(samples=samples,ack_returned=ack,error_type=error))
    return dict(schema='manual_work_batch_controls/v1',status='batch_controls_observed' if stable>=2 else 'batch_controls_unconfirmed',inventory=value,stable=stable>=2,
        batch_entry_click_count=1,entry_ack_returned=ack,entry_error_type=error,navigations_count=0,api_request_count=0,
        selection_performed=False,delete_performed=False,confirmation_performed=False,input_values_read=False,private_state_read=False,delete_allowed=False)


DELETE_ENTRY=':is(div,span,button):visible >> xpath=self::*[normalize-space(.)="删除" and not(.//*[normalize-space(.)="删除"])]'


def checkbox_selector(post_id):
    if not isinstance(post_id,str) or not post_id.isdecimal():raise ValueError('cleanup_exact_post_id_required')
    return 'li:has(a:is([href="/video/'+post_id+'"],[href="https://www.douyin.com/video/'+post_id+'"],[href="https://douyin.com/video/'+post_id+'"] )) input.semi-checkbox-input[type="checkbox"]:visible'


def display_selector(post_id):
    return checkbox_selector(post_id).rsplit(' input.semi-checkbox-input',1)[0]+' span.semi-checkbox-inner-display:visible'


def display_probe_script():
    return 'el=>{'+_COMMON+r'''
 const value=(SELECTION)();
 const li=el.closest('li'),postIds=ids(li),component=el.closest('.semi-checkbox');
 const inputs=component?[...component.querySelectorAll('input.semi-checkbox-input[type="checkbox"]')]:[];
 const displays=component?[...component.querySelectorAll('span.semi-checkbox-inner-display')].filter(visible):[];
 const r=el.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
 return {selection:value,display:{post_ids:postIds,tag:el.tagName.toLowerCase(),class_name:(el.getAttribute('class')||'').slice(0,300),
   eligible:allowed&&visible(el)&&el.matches('span.semi-checkbox-inner-display')&&displays.length===1&&displays[0]===el&&inputs.length===1&&!inputs[0].disabled&&
     getComputedStyle(el).pointerEvents!=='none'&&Number(getComputedStyle(el).opacity)>0&&!!hit&&(hit===el||el.contains(hit)),
   center_hit:hit?meta(hit):null,native_input_count:inputs.length,display_count:displays.length}};
}'''.replace('SELECTION',selection_script())


def recorder_script(nonce,mode,delete_ids):
    if not isinstance(nonce,str) or not re.fullmatch(r'[0-9a-f]{32}',nonce) or mode not in {'install','snapshot','stop'}:raise ValueError('cleanup_event_recorder_contract_required')
    return '()=>{'+_COMMON+r'''
 const nonce=NONCE,mode=MODE,wanted=TARGETS,key='__manualWorkCleanupVisibleRecorderV1';
 if(!allowed)return {ready:false,reason:'recorder_original_profile_required'};
 const previous=window[key];
 if(mode!=='install'){
   if(!previous||previous.nonce!==nonce||previous.document!==document)return {ready:false,reason:'recorder_nonce_or_document_missing'};
   if(mode==='stop')previous.stop();return previous.snapshot();
 }
 if(previous&&previous.active&&previous.nonce!==nonce)return {ready:false,reason:'other_active_recorder'};
 if(previous&&previous.nonce===nonce)return previous.snapshot();
 const bindings=wanted.map(post=>{const lis=[...document.querySelectorAll('li')].filter(li=>visible(li)&&JSON.stringify(ids(li))===JSON.stringify([post]));
   if(lis.length!==1)return null;const ds=[...lis[0].querySelectorAll('span.semi-checkbox-inner-display')].filter(visible);
   return ds.length===1?{post,li:lis[0],display:ds[0],component:ds[0].closest('.semi-checkbox')}:null;});
 if(bindings.some(b=>!b||!b.component))return {ready:false,reason:'recorder_unique_native_targets_required'};
 const events=[],counts=Object.fromEntries(wanted.map(p=>[p,0]));let blocked=0,outside=0,active=true;
 const capture=event=>{
   const component=event.target?.closest?.('.semi-checkbox');if(!component)return;
   const binding=bindings.find(b=>b.component===component);const display=event.target?.closest?.('.semi-checkbox-inner-display');
   if(!binding){if(event.type==='click'&&event.isTrusted)outside++;return;}
   if(display!==binding.display)return;
   const valid=binding.display.isConnected&&binding.li.isConnected&&binding.li.contains(binding.display)&&visible(binding.display)&&
     JSON.stringify(ids(binding.li))===JSON.stringify([binding.post])&&binding.display.closest('.semi-checkbox')===binding.component;
   const duplicate=event.type==='click'&&event.isTrusted&&counts[binding.post]>0;
   const denied=!valid||duplicate;
   if(denied){event.preventDefault();event.stopImmediatePropagation();blocked++;}
   if(event.type==='click'&&event.isTrusted&&!denied)counts[binding.post]++;
   if(events.length<80)events.push({type:event.type,post_id:binding.post,is_trusted:event.isTrusted,blocked:denied,at_performance_ms:performance.now(),target:meta(event.target)});
 };
 const names=['pointerdown','mousedown','mouseup','click'];for(const name of names)document.addEventListener(name,capture,true);
 const record={nonce,document,get active(){return active},stop(){if(active){for(const name of names)document.removeEventListener(name,capture,true);active=false}},
   snapshot(){return {schema:'manual_visible_checkbox_events/v1',ready:true,nonce,active,same_document:record.document===document,
     trusted_display_click_counts:{...counts},blocked_event_count:blocked,outside_target_trusted_clicks:outside,events:[...events],truncated:events.length>=80}}};
 window[key]=record;return record.snapshot();
}'''.replace('NONCE',json.dumps(nonce)).replace('MODE',json.dumps(mode)).replace('TARGETS',json.dumps(delete_ids))


_SELECTION_BODY=r'''
 if(!allowed)return {schema:'douyin_cleanup_selection/v1',location:loc,ready:false};
 const controls=[...document.querySelectorAll('input.semi-checkbox-input[type="checkbox"]')].filter(visible);
 const nodes=controls.map((e,index)=>{const row=e.closest('li'),postIds=ids(row),ancestors=[];
   for(let p=e.parentElement,d=0;p&&p!==row&&d<4;p=p.parentElement,d++){
     if(visible(p))ancestors.push({tag:p.tagName.toLowerCase(),class_name:(p.getAttribute('class')||'').slice(0,300),aria_checked:p.getAttribute('aria-checked'),component_checked_class:p.classList.contains('semi-checkbox-checked')});}
   const aria=e.getAttribute('aria-checked');const component=ancestors.some(p=>p.component_checked_class||p.aria_checked==='true');
   return {index,native_checked:e.checked,aria_checked:aria,indeterminate:e.indeterminate,disabled:e.disabled===true,ancestors,
     post_ids:postIds,post_id:postIds.length===1?postIds[0]:null,public_selected:e.checked===true||aria==='true'||component,
     same_element:ELEMENT===e,class_name:(e.getAttribute('class')||'').slice(0,300)};});
 const leaves=[...document.querySelectorAll('div,span,p,button')].filter(e=>visible(e)&&![...e.children].some(c=>visible(c)&&text(c)));
 const counts=leaves.map(text).map(t=>t.match(/^已选\s*(\d+)\s*个作品$/)).filter(Boolean).map(m=>Number(m[1]));
 const del=leaves.filter(e=>text(e)==='删除'&&!e.closest('li,form,[role="dialog"],.semi-modal'));
 const candidate=del.length===1?del[0]:null;let toolbar=null;const chain=[];
 if(candidate)for(let p=candidate.parentElement,d=0;p&&!p.matches('body,html')&&d<10;p=p.parentElement,d++){
   const s=text(p);chain.push({tag:p.tagName.toLowerCase(),class_name:(p.getAttribute('class')||'').slice(0,300),text:s.slice(0,1000),native_post_ids:ids(p)});
   if(!p.querySelector('li')&&ids(p).length===0&&/已选\s*\d+\s*个作品/.test(s)&&s.includes('全选')&&s.includes('权限设置')){toolbar=p;break;}}
 const deleteEligible=!!toolbar&&candidate&&!candidate.matches(':disabled,[aria-disabled="true"],input,label,a')&&
   (!candidate.matches('button')||candidate.type==='button')&&getComputedStyle(candidate).pointerEvents!=='none';
 return {schema:'douyin_cleanup_selection/v1',location:loc,ready:true,controls:nodes,visible_native_checkbox_count:controls.length,
   count_labels:counts,selected_count:counts.length===1?counts[0]:null,
   delete_entry:{unique_count:del.length,eligible:!!deleteEligible,metadata:candidate?meta(candidate):null,same_element:!!candidate&&ELEMENT===candidate,toolbar_ancestors:chain},
   input_values_read:false,private_state_read:false};
'''


def selection_script(element=False):
    return ('el=>{' if element else '()=>{')+_COMMON+_SELECTION_BODY.replace('ELEMENT','el' if element else 'null')+'}'


def _selected(value,expected,delete_ids,protected_ids):
    if not value.get('ready') or value.get('visible_native_checkbox_count')!=5:raise ValueError('cleanup_five_native_checkbox_scope_required')
    controls=value['controls'];rows=[c for c in controls if c['post_id'] is not None];global_controls=[c for c in controls if c['post_id'] is None]
    if (len(rows)!=4 or {c['post_id'] for c in rows}!=set(delete_ids)|set(protected_ids) or any(c['disabled'] for c in controls)
            or len(global_controls)!=1 or global_controls[0]['native_checked'] is not False or global_controls[0]['aria_checked']=='true'
            or value.get('selected_count')!=len(expected)
            or {c['post_id'] for c in rows if c['public_selected']}!=set(expected)):
        raise ValueError('cleanup_exact_public_selection_unconfirmed')


def _select_targets_core(page,*,guard,checkpoint,inventory_script,expected_uid,delete_ids,protected_ids,visible_display=False,event_nonce=None):
    owner,tab=getattr(page,'_session',None),getattr(page,'tab_id',None)
    def rpc(method,*args,**kwargs):
        guard()
        if getattr(page,'_session',None) is not owner or getattr(page,'tab_id',None)!=tab:raise ValueError('cleanup_original_selection_page_changed')
        value=method(*args,**kwargs);guard();return value
    _ready(rpc(page.evaluate,inventory_script),expected_uid,delete_ids,protected_ids)
    initial=rpc(page.evaluate,selection_script());checkpoint('initial_exact_selection',initial);_selected(initial,[],delete_ids,protected_ids)
    selected=[]
    for post_id in delete_ids:
        control=page.locator(display_selector(post_id) if visible_display else checkbox_selector(post_id)).nth(0)
        proof=rpc(control.evaluate,display_probe_script() if visible_display else selection_script(True))
        state=proof['selection'] if visible_display else proof;_selected(state,selected,delete_ids,protected_ids)
        if visible_display:
            if not proof['display']['eligible'] or proof['display']['post_ids']!=[post_id]:raise ValueError('cleanup_exact_visible_target_display_required')
            same=[c for c in state['controls'] if c['post_id']==post_id]
        else:same=[c for c in state['controls'] if c['same_element']]
        if len(same)!=1 or same[0]['post_id']!=post_id or same[0]['public_selected']:raise ValueError('cleanup_exact_unselected_target_input_required')
        checkpoint('select_'+post_id+'_intent',dict(post_id=post_id,proof=proof,native_click_limit=1,protected_ids=protected_ids,event_nonce=event_nonce,visible_display=visible_display))
        rpc(control.click,timeout=8000);selected.append(post_id)
        if visible_display:
            events=rpc(page.evaluate,recorder_script(event_nonce,'snapshot',delete_ids));checkpoint('events_'+post_id,events)
            if not events.get('ready') or events.get('nonce')!=event_nonce or events.get('blocked_event_count')!=0 or events.get('outside_target_trusted_clicks')!=0 or events.get('trusted_display_click_counts')!={p:int(p in selected) for p in delete_ids}:
                raise ValueError('cleanup_one_trusted_display_click_per_target_required')
        samples=[];prior=None;stable=0;confirmed=False
        for _ in range(8):
            value=rpc(page.evaluate,selection_script());samples.append(value)
            signature=json.dumps(value,sort_keys=True,ensure_ascii=False);stable=stable+1 if signature==prior else 1;prior=signature
            try:_selected(value,selected,delete_ids,protected_ids);confirmed=True
            except ValueError:confirmed=False
            if confirmed and stable>=2:break
            rpc(page.wait_for_timeout,200)
        checkpoint('selected_'+post_id,dict(samples=samples,confirmed=confirmed,stable=stable>=2))
        if not confirmed or stable<2:raise ValueError('cleanup_current_target_selection_not_confirmed')
    _ready(rpc(page.evaluate,inventory_script),expected_uid,delete_ids,protected_ids)
    delete=page.locator(DELETE_ENTRY).nth(0);proof=rpc(delete.evaluate,selection_script(True));_selected(proof,delete_ids,delete_ids,protected_ids)
    checkpoint('delete_entry_proof',proof)
    if proof['delete_entry'].get('eligible') is not True or proof['delete_entry'].get('same_element') is not True:raise ValueError('cleanup_exact_toolbar_delete_entry_required')
    checkpoint('delete_entry_intent',dict(target_ids=delete_ids,protected_ids=protected_ids,proof=proof,native_click_limit=1,final_confirmation_allowed=False))
    fresh=rpc(delete.evaluate,selection_script(True));_selected(fresh,delete_ids,delete_ids,protected_ids)
    if fresh['delete_entry']!=proof['delete_entry']:raise ValueError('cleanup_toolbar_delete_changed')
    ack=False;error=None
    try:rpc(delete.click,timeout=8000);ack=True
    except Exception as exc:error=type(exc).__name__
    samples=[];prior=None;stable=0
    for _ in range(8):
        modal=rpc(page.evaluate,BATCH_JS);samples.append(modal);signature=json.dumps(modal,sort_keys=True,ensure_ascii=False)
        stable=stable+1 if signature==prior else 1;prior=signature
        if modal.get('visible_modal_count',0)>0 and stable>=2:break
        rpc(page.wait_for_timeout,250)
    checkpoint('confirmation_modal_samples',dict(samples=samples,delete_entry_ack_returned=ack,error_type=error))
    return dict(schema='manual_work_cleanup_selection/v1',status='confirmation_observed' if modal.get('visible_modal_count',0)>0 and stable>=2 else 'confirmation_unconfirmed',
        selected_ids=selected,protected_ids=protected_ids,selection_performed=True,delete_entry_clicked=True,delete_entry_ack_returned=ack,
        confirmation=modal,confirmation_performed=False,deleted=False,delete_allowed=False,navigations_count=0,api_request_count=0,event_nonce=event_nonce,visible_display=visible_display)


def select_targets_open_confirmation(page,**kwargs):return _select_targets_core(page,**kwargs)


def select_visible_targets_open_confirmation(page,*,guard,checkpoint,inventory_script,expected_uid,delete_ids,protected_ids,event_nonce):
    guard();_ready(page.evaluate(inventory_script),expected_uid,delete_ids,protected_ids);guard()
    installed=page.evaluate(recorder_script(event_nonce,'install',delete_ids));guard();checkpoint('visible_event_recorder_installed',installed)
    if not installed.get('ready') or installed.get('nonce')!=event_nonce or any(installed.get('trusted_display_click_counts',{}).values()):raise ValueError('cleanup_fresh_visible_event_recorder_required')
    result=None
    try:
        result=_select_targets_core(page,guard=guard,checkpoint=checkpoint,inventory_script=inventory_script,expected_uid=expected_uid,delete_ids=delete_ids,protected_ids=protected_ids,visible_display=True,event_nonce=event_nonce)
        return result
    finally:
        try:
            guard();final=page.evaluate(recorder_script(event_nonce,'stop',delete_ids));guard();checkpoint('visible_event_recorder_final',final)
            if result is not None:result['event_recorder_final']=final
        except Exception as error:
            if result is not None:result['event_recorder_stop_error_type']=type(error).__name__


CURRENT_SELECTION_INSPECTION_JS='()=>{'+_COMMON+r'''
 if(!allowed)return {schema:'douyin_current_selection_inspection/v1',location:loc,ready:false,reason:'original_self_profile_required'};
 const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,top:r.top,bottom:r.bottom,left:r.left,right:r.right}};
 const style=e=>{const s=getComputedStyle(e);return {display:s.display,visibility:s.visibility,opacity:s.opacity,cursor:s.cursor,pointer_events:s.pointerEvents}};
 const bounded=e=>({tag:e.tagName.toLowerCase(),role:e.getAttribute('role')||'',class_name:(e.getAttribute('class')||'').slice(0,300),rect:rect(e),style:style(e)});
 const inputs=[...document.querySelectorAll('input.semi-checkbox-input[type="checkbox"]')];
 const controls=inputs.slice(0,20).map((e,index)=>{const r=e.getBoundingClientRect(),cx=r.x+r.width/2,cy=r.y+r.height/2;
   const inViewport=r.width>0&&r.height>0&&cx>=0&&cy>=0&&cx<innerWidth&&cy<innerHeight;
   const hit=inViewport?document.elementFromPoint(cx,cy):null;const stack=inViewport?document.elementsFromPoint(cx,cy).slice(0,8):[];
   const li=e.closest('li'),component=e.closest('.semi-checkbox');const chain=[];
   for(let p=e.parentElement,d=0;p&&p!==li&&d<6;p=p.parentElement,d++)chain.push({...bounded(p),aria_checked:p.getAttribute('aria-checked'),component_checked_class:p.classList.contains('semi-checkbox-checked')});
   return {index,...bounded(e),native_visible:visible(e),native_checked:e.checked,aria_checked:e.getAttribute('aria-checked'),indeterminate:e.indeterminate,
     disabled:e.disabled===true,post_ids:ids(li),ancestors:chain,center:{x:cx,y:cy,in_viewport:inViewport},
     center_hit:hit?bounded(hit):null,center_hit_is_input:hit===e,center_hit_inside_input:!!hit&&e.contains(hit),
     center_hit_inside_component:!!hit&&!!component&&component.contains(hit),hit_stack:stack.map(bounded)};});
 const leaves=[...document.querySelectorAll('div,span,p')].filter(e=>visible(e)&&![...e.children].some(c=>visible(c)&&text(c)));
 const counts=leaves.map(text).filter(t=>/^已选\s*\d+\s*个作品$/.test(t));
 const modals=[...document.querySelectorAll('[role="dialog"],.semi-modal')].filter(visible);
 return {schema:'douyin_current_selection_inspection/v1',location:loc,ready:true,viewport:{width:innerWidth,height:innerHeight},
   checkbox_count:inputs.length,controls,selected_count_texts:counts,visible_modal_count:modals.length,
   modals:modals.slice(0,5).map(e=>({...meta(e),text:text(e).slice(0,8000)})),truncated:inputs.length>20||modals.length>5,
   original_attempt_event_recorder:{installed_by_original_producer:false,nonce:null,capture_event_count:null,reason:'No recorder was installed in b80d/d1ec. Worker dispatch is not a DOM event.'},
   input_values_read:false,private_state_read:false,native_events_dispatched:0};
}'''


def inspect_current_selection(page,*,guard,checkpoint):
    original,tab=getattr(page,'_session',None),getattr(page,'tab_id',None);samples=[]
    for _ in range(2):
        guard()
        if getattr(page,'_session',None) is not original or getattr(page,'tab_id',None)!=tab:raise ValueError('cleanup_original_inspection_page_changed')
        samples.append(page.evaluate(CURRENT_SELECTION_INSPECTION_JS));guard()
    checkpoint('current_selection_native',dict(samples=samples))
    return dict(schema='manual_work_current_selection/v1',status='current_selection_observed',observation=samples[-1],samples=samples,
        native_events_dispatched=0,selection_performed=False,delete_entry_clicked=False,confirmation_performed=False,deleted=False,delete_allowed=False,navigations_count=0,api_request_count=0)


FINAL_CONFIRM='button:visible >> xpath=self::*[normalize-space(.)="确认删除"]'


def final_confirmation_script(contract,element=False):
    args={k:contract[k] for k in ('expected_title','expected_warning','confirmation_button')}
    script=_COMMON+r'''
 if(!allowed)return {schema:'douyin_exact_delete_confirmation/v1',location:loc,eligible:false};
 const expected=CONTRACT;
 const leaves=[...document.querySelectorAll('div,span,p,h1,h2,h3,h4')].filter(e=>visible(e)&&![...e.children].some(c=>visible(c)&&text(c)));
 const titles=leaves.filter(e=>text(e)===expected.expected_title),warnings=leaves.filter(e=>text(e)===expected.expected_warning);
 const buttons=[...document.querySelectorAll('button')].filter(e=>visible(e)&&text(e)==='确认删除');
 const button=buttons.length===1?buttons[0]:null;let scope=null;
 if(button&&titles.length===1&&warnings.length===1)for(let p=button.parentElement,d=0;p&&!p.matches('body,html')&&d<16;p=p.parentElement,d++){
   if(p.contains(titles[0])&&p.contains(warnings[0])&&!p.matches('form,li,[inert]')&&!p.querySelector('li,video,input,textarea,[contenteditable="true"]')&&ids(p).length===0&&p.querySelectorAll('*').length<=250&&text(p).length<=4000){scope=p;break;}}
 const bmeta=button?meta(button):null;
 const r=button?button.getBoundingClientRect():null,hit=r?document.elementFromPoint(r.x+r.width/2,r.y+r.height/2):null;
 const hitOk=!!button&&!!hit&&(hit===button||button.contains(hit));
 const exact=!!bmeta&&Object.keys(expected.confirmation_button).length===6&&Object.keys(expected.confirmation_button).every(k=>bmeta[k]===expected.confirmation_button[k]);
 return {schema:'douyin_exact_delete_confirmation/v1',location:loc,title_count:titles.length,warning_count:warnings.length,button_count:buttons.length,
   native_role_modal_count:[...document.querySelectorAll('[role="dialog"],.semi-modal')].filter(visible).length,
   semantic_scope:scope?{tag:scope.tagName.toLowerCase(),class_name:(scope.getAttribute('class')||'').slice(0,300),text:text(scope),node_count:scope.querySelectorAll('*').length}:null,
   button:bmeta,center_hit:hit?meta(hit):null,center_hit_within_button:hitOk,same_element:ELEMENT===button,
   eligible:!!scope&&exact&&button.type==='button'&&!button.disabled&&getComputedStyle(button).pointerEvents!=='none'&&Number(getComputedStyle(button).opacity)>0&&hitOk,
   private_state_read:false,input_values_read:false};
'''.replace('CONTRACT',json.dumps(args,ensure_ascii=False)).replace('ELEMENT','el' if element else 'null')
    return ('el=>{' if element else '()=>{')+script+'}'


def _final_selected(value,delete_ids,protected_ids):
    _selected(value,delete_ids,delete_ids,protected_ids)
    for node in value['controls']:
        if node['post_id'] in delete_ids and (node['native_checked'] is not True or node['aria_checked']!='true'):
            raise ValueError('cleanup_final_native_checked_targets_required')


def _absent(profile,expected_uid,delete_ids,protected_ids):
    rows=profile.get('cards',[])
    ids_now=[c.get('native_post_id') for c in rows if c.get('native_id_bound') is True]
    return (profile.get('surface')=='original_self_profile' and profile.get('public_uids')==[expected_uid] and profile.get('truncated') is False
        and profile.get('visible_card_count')==2 and len(rows)==len(ids_now)==2 and set(ids_now)==set(protected_ids) and not set(ids_now)&set(delete_ids))


def _read_reloaded_profile(rpc,page,inventory_script,expected_uid,delete_ids,protected_ids):
    """Retry only transient read-context loss; never repeat navigation or clicks."""
    samples=[];errors=[];stable=0
    for attempt in range(10):
        try:observed=rpc(page.evaluate,inventory_script)
        except RuntimeError as error:
            first=str(error).splitlines()[0] if str(error) else ''
            if not first.startswith('Page.evaluate: Execution context was destroyed'):raise
            errors.append(dict(attempt=attempt+1,error_type=type(error).__name__,safe_error=re.sub(r'https?://\S+','<url>',first)[:500]));stable=0
        else:
            samples.append(observed)
            stable=stable+1 if _absent(observed,expected_uid,delete_ids,protected_ids) else 0
            if stable>=2:return samples,errors,True
        if attempt<9:rpc(page.wait_for_timeout,300)
    return samples,errors,False


def confirm_exact_selection(page,*,guard,checkpoint,inventory_script,expected_uid,delete_ids,protected_ids,contract,contract_ref,selection_result_ref,claim_final_deletion,final_claim_path):
    owner,tab=getattr(page,'_session',None),getattr(page,'tab_id',None)
    def rpc(method,*args,**kw):
        guard()
        if getattr(page,'_session',None) is not owner or getattr(page,'tab_id',None)!=tab:raise ValueError('cleanup_final_original_page_changed')
        value=method(*args,**kw);guard();return value
    profile=rpc(page.evaluate,inventory_script);_ready(profile,expected_uid,delete_ids,protected_ids)
    selected=rpc(page.evaluate,selection_script());_final_selected(selected,delete_ids,protected_ids)
    button=page.locator(FINAL_CONFIRM).nth(0);scope=rpc(button.evaluate,final_confirmation_script(contract,True))
    checkpoint('fresh_exact_final_scope',dict(profile=profile,selection=selected,confirmation=scope))
    if scope.get('eligible') is not True or scope.get('same_element') is not True:raise ValueError('cleanup_exact_roleless_confirmation_required')
    preflight=checkpoint('final_delete_preflight',dict(schema='manual_work_final_delete_preflight/v1',deletion_contract=contract_ref,selection_result=selection_result_ref,
        delete_post_ids=delete_ids,protected_post_ids=protected_ids,profile=profile,selection=selected,confirmation=scope,observed_at=time.time(),final_confirmation_limit=1))
    if not isinstance(preflight,dict) or set(preflight)!={'path','sha256'}:raise ValueError('cleanup_durable_final_preflight_required')
    claim=claim_final_deletion(preflight)
    if (not isinstance(claim,dict) or set(claim)!={'path','sha256'} or Path(claim['path']).resolve()!=Path(final_claim_path).resolve()
            or hashlib.sha256(Path(claim['path']).read_bytes()).hexdigest()!=claim['sha256']):raise ValueError('cleanup_final_claim_not_confirmed')
    claimed=json.loads(Path(claim['path']).read_text(encoding='utf8'))
    if (claimed.get('schema')!='manual_work_final_delete_claim/v1' or claimed.get('preflight')!=preflight or claimed.get('deletion_contract')!=contract_ref
            or claimed.get('selection_result')!=selection_result_ref or claimed.get('delete_post_ids')!=delete_ids or claimed.get('protected_post_ids')!=protected_ids
            or claimed.get('final_confirmation_limit')!=1 or claimed.get('automatic_replay_allowed') is not False):
        raise ValueError('cleanup_final_claim_not_bound')
    fresh=rpc(button.evaluate,final_confirmation_script(contract,True))
    _final_selected(rpc(page.evaluate,selection_script()),delete_ids,protected_ids)
    if fresh.get('eligible') is not True or fresh.get('same_element') is not True:raise ValueError('cleanup_confirmation_changed_after_claim')
    checkpoint('final_native_click_intent',dict(claim=claim,preflight=preflight,native_click_limit=1,reselect_allowed=False))
    ack=False;error=None
    try:rpc(button.click,timeout=8000);ack=True
    except Exception as exc:error=type(exc).__name__
    before_reload=[];absent_stable=0
    for _ in range(12):
        observed=rpc(page.evaluate,inventory_script);modal=rpc(page.evaluate,final_confirmation_script(contract))
        before_reload.append(dict(profile=observed,confirmation=modal))
        absent_stable=absent_stable+1 if _absent(observed,expected_uid,delete_ids,protected_ids) and modal.get('button_count')==0 else 0
        if absent_stable>=2:break
        rpc(page.wait_for_timeout,300)
    checkpoint('post_confirmation_native_observations',dict(samples=before_reload,ack_returned=ack,error_type=error))
    reloaded=False;navigation_error=None;after=[];read_errors=[];verified=False
    if absent_stable>=2:
        checkpoint('readonly_reload_intent',dict(url=contract['post_confirm_readonly_reload_url'],allowed_navigations=1,write_actions=0));reloaded=True
        try:rpc(page.goto,contract['post_confirm_readonly_reload_url'],wait_until='commit',timeout=30000)
        except Exception as exc:
            if type(exc).__name__!='BrowserNavigationTimeout':raise
            navigation_error=type(exc).__name__
        after,read_errors,verified=_read_reloaded_profile(rpc,page,inventory_script,expected_uid,delete_ids,protected_ids)
    checkpoint('fresh_reloaded_own_profile',dict(samples=after,read_context_errors=read_errors,reload_dispatched=reloaded,navigation_error=navigation_error,deleted_ids_absent_and_protected_present=verified))
    return dict(schema='manual_work_final_delete/v1',status='deletion_verified' if verified else 'deletion_unknown',final_confirmation_dispatched=True,
        final_ack_returned=ack,final_error_type=error,final_delete_claim=claim,preflight=preflight,delete_post_ids=delete_ids,protected_post_ids=protected_ids,
        deleted=verified,selection_performed=False,final_native_click_count=1,readonly_reload_count=int(reloaded),api_request_count=0,confirmation_scope=scope)
