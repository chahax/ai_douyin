"""Read the current original-draft declaration modal and native associations.

Stage one only. No selection, confirmation, publication, navigation or files.
Native checked state is read only for controls associated with a visible label
inside this exact modal, or for a native control itself visibly rendered there.
Input values and private framework state are never accessed.
"""
import json
import hashlib
import math
import os
from pathlib import Path
import re
import secrets
import threading
import time
import types
from types import SimpleNamespace
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[2]
LOCATION={'origin':'https://creator.douyin.com','path':'/creator-micro/content/post/video'}
ACTION='inspect_current_declaration_controls'
KNOWN_LABELS=('内容由AI生成','内容为个人观点或见解','内容为转载信息','内容含营销推广信息','虚构演绎，仅供娱乐','无需添加自主声明')
SAFE_REASONS=frozenset('controls_'+s for s in ('request_invalid','binding_changed','claim_changed','output_changed',
    'session_changed','deadline_reached','editor_unconfirmed','modal_unconfirmed','rpc_not_allowed','inspection_unknown',
    'contract_invalid','settings_unconfirmed','form_changed','selection_unconfirmed','confirmation_unconfirmed','publish_unconfirmed','submission_unknown','request_already_dispatched','metadata_read_unknown','public_verify_unknown','caption_read_unknown'))


class DeclarationControlsBlocked(ValueError):
    def __init__(self,code,diagnostics_ref=None):self.code=code;self.diagnostics_ref=diagnostics_ref;super().__init__(code)


def need(ok,code):
    if not ok:raise DeclarationControlsBlocked('controls_'+code)


def modal_controls_script():
    return r"""() => {
 if(location.origin!=='https://creator.douyin.com'||location.pathname!=='/creator-micro/content/post/video')
   return {schema:'manual_native_declaration_controls/v10',location:{origin:location.origin,path:location.pathname},render_complete:false,origin_blocked:true};
 const visible=e=>!!e&&e.isConnected&&e.getClientRects().length>0&&!e.closest('[hidden],[aria-hidden="true"],[inert]')&&(()=>{for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||['hidden','collapse'].includes(s.visibility)||Number(s.opacity)===0)return false}return true})();
 const text=e=>String(e?.innerText||'').trim().replace(/\s+/g,' ');
 const modals=[...document.querySelectorAll('div.semi-modal')].filter(visible);const root=modals.length===1?modals[0]:null;
 const base={schema:'manual_native_declaration_controls/v10',location:{origin:location.origin,path:location.pathname},visible_modal_count:modals.length,
   input_values_read:false,private_state_read:false,selection_performed:false,confirmation_clicked:false,publish_clicked:false};
 if(!root)return {...base,render_complete:false,reason:'unique_visible_observed_modal_required'};
 const all=[...root.querySelectorAll('*')];const shown=all.filter(visible);const truncated=all.length>800||shown.length>600||(root.innerText||'').length>30000;
 const inputs=[...root.querySelectorAll('input[type="radio"],input[type="checkbox"]')];
 const labels=[...root.querySelectorAll('label')].filter(visible);
 const native=inputs.slice(0,40).map((control,index)=>{const associated=labels.filter(label=>label.control===control);
   const readable=visible(control)||associated.length>0;
   return {index,tag:'input',type:control.type,id:(control.id||'').slice(0,200),name:(control.getAttribute('name')||'').slice(0,200),
     native_visible:visible(control),associated_visible_labels:associated.map(text),label_indices:associated.map(l=>labels.indexOf(l)),
     checked_read_allowed:readable,checked:readable?control.checked:null,disabled:control.disabled===true,
     aria_checked:control.getAttribute('aria-checked'),form_id:control.form?(control.form.id||'').slice(0,200):null,
     form_inside_modal:control.form?root.contains(control.form):null};});
 const labelData=labels.slice(0,60).map((label,index)=>({index,text:text(label).slice(0,1200),id:(label.id||'').slice(0,200),
   html_for:(label.htmlFor||'').slice(0,200),class_name:(label.getAttribute('class')||'').slice(0,300),
   control_index:inputs.indexOf(label.control),association:label.control?(label.contains(label.control)?'native_wrapping_label':label.htmlFor?'native_for_control':'native_label_control'):'unassociated',
   associated_control_inside_modal:!!label.control&&root.contains(label.control)}));
 const roleControls=shown.filter(e=>['radio','checkbox'].includes(e.getAttribute('role'))).slice(0,60).map(e=>({
   tag:e.tagName.toLowerCase(),role:e.getAttribute('role'),text:text(e).slice(0,1200),aria_checked:e.getAttribute('aria-checked'),
   class_name:(e.getAttribute('class')||'').slice(0,300),disabled:e.matches(':disabled,[aria-disabled="true"]')}));
 const leaves=shown.filter(e=>![...e.children].some(c=>visible(c)&&text(c))).map(e=>({tag:e.tagName.toLowerCase(),role:e.getAttribute('role'),
   class_name:(e.getAttribute('class')||'').slice(0,300),text:text(e).slice(0,1600)})).filter(e=>e.text);
 const buttonData=[...root.querySelectorAll('button')].filter(visible).slice(0,30).map((e,index)=>({index,tag:'button',type:e.type,text:text(e),
   class_name:(e.getAttribute('class')||'').slice(0,300),disabled:e.disabled===true||e.getAttribute('aria-disabled')==='true'}));
 const leafTexts=leaves.map(e=>e.text);const known=KNOWN;
 const titleCount=leafTexts.filter(t=>t==='对作品内容添加声明').length;
 const singleCount=leafTexts.filter(t=>t==='请选择声明类型（单选）').length;
 const observedLabels=known.map(value=>({text:value,visible_leaf_count:leafTexts.filter(t=>t===value).length,
   native_label_indices:labelData.filter(l=>l.text===value).map(l=>l.index)}));
 const associationsComplete=observedLabels.every(x=>x.native_label_indices.length===1&&labelData[x.native_label_indices[0]].control_index>=0&&labelData[x.native_label_indices[0]].associated_control_inside_modal)
   &&new Set(observedLabels.map(x=>labelData[x.native_label_indices[0]]?.control_index)).size===known.length;
 const names=[...new Set(native.filter(x=>x.checked_read_allowed&&x.type==='radio').map(x=>x.name))];
 return {...base,modal:{tag:'div',class_name:(root.getAttribute('class')||'').slice(0,300),role:root.getAttribute('role'),visible_text:(root.innerText||'').slice(0,30000)},
   node_count:all.length,visible_node_count:shown.length,visible_leaves:leaves.slice(0,200),labels:labelData,native_controls:native,
   role_controls:roleControls,buttons:buttonData,known_label_observations:observedLabels,native_associations_complete:associationsComplete,
   semantics:{explicit_single_choice_copy:singleCount===1,all_associated_controls_are_native_radio:associationsComplete&&native.length===known.length&&native.every(x=>x.type==='radio'),
     same_nonempty_native_radio_name:names.length===1&&!!names[0],native_radio_names:names},
   truncated:truncated||inputs.length>40||labels.length>60||leaves.length>200,
   render_complete:titleCount===1&&singleCount===1&&observedLabels.every(x=>x.visible_leaf_count===1)&&!truncated&&inputs.length<=40&&labels.length<=60&&leaves.length<=200,
   stage2_implemented:false};
 }""".replace('KNOWN',json.dumps(KNOWN_LABELS,ensure_ascii=False))


def _previous(config,reference):
    path=ROOT/'src/operations_accounts/manual_republication_flow_v7.py'
    need(reference(path)==config['sources']['flow_v7'],'binding_changed')
    module=types.ModuleType('src.operations_accounts._controls_parent_'+config['sources']['flow_v7']['sha256'][:16])
    module.__file__,module.__package__=str(path),'src.operations_accounts'
    exec(compile(path.read_bytes(),str(path),'exec'),module.__dict__)
    return module,module._load(config)


def _inspect_action(actor,resource,config,request,outdir,runtime_bridge=None):
    runtime=runtime_bridge
    if runtime is None:
        from . import manual_republication_runtime_v10 as runtime
    reference,read,once=runtime.reference,runtime._read,runtime._once
    need(isinstance(request,dict) and set(request)=={'schema','config','action','prior_result','prior_receipt','options_inventory'}
         and request['schema']=='manual_republication_operator_request/v10' and request['action']==ACTION,'request_invalid')
    need(read(request['config'])==config,'binding_changed')
    folder=Path(outdir).resolve();need(folder.name=='inspection' and folder.is_relative_to(ROOT/'data'),'output_changed')
    action_ref=reference(folder.parent/'ACTION_CLAIM.json');claim=read(action_ref);plan=read(claim['plan'])
    need(claim.get('schema')=='manual_republication_controls_action_claim/v10' and claim.get('action')==ACTION
         and claim.get('config')==request['config'] and read(claim['request'])==request and plan.get('config')==request['config'] and plan.get('request')==claim['request']
         and all(claim.get(k)==config[k] for k in ('owner_id','generation','tab_id')) and claim.get('actor_thread_id')==threading.get_ident()
         and claim.get('navigation_allowed') is False and claim.get('file_selection_allowed') is False
         and all(type(claim.get(k)) is int and claim[k]==0 for k in ('selections_allowed','confirmations_allowed','submissions_allowed'))
         and folder==Path(claim['plan']['path']).resolve().parent/'inspection','claim_changed')
    parent,previous=_previous(config,reference);leaf=previous._load_base(config);reader,_=leaf._load_leaves(config);metadata,authority=leaf._metadata(config)
    prior=plan['prior'];nonce=prior['selection_nonce'];baseline=prior['upload_route_baseline'];duration=prior['source_duration_seconds'];original=resource.session
    need(read(prior['file_selection_claim']).get('media')==metadata['media'],'claim_changed')
    immutable=[action_ref,request['config'],prior['upload_journal'],prior['file_selection_claim'],*[request[k] for k in ('prior_result','prior_receipt','options_inventory')]]
    deadline=time.monotonic()+75
    def guard():
        need(time.monotonic()+10<deadline,'deadline_reached')
        need(resource.session is original and original._proc is not None and original._proc.poll() is None,'session_changed')
        runtime.validate_live(actor,resource,config)
        for ref in immutable:need(reference(ref['path'])==ref,'binding_changed')
        b=resource.runtime.bindings.get(config['account_key']);p=resource.runtime.profiles.get(config['account_key'])
        need(b.account_uuid==p.account_uuid==config['account_id'] and reader._binding_version(SimpleNamespace(binding=b,profile=p))==config['binding_version']
             and str(b.public_uid)==authority['expected_public_uid'],'session_changed')
    guard();raw=original.get_page(config['tab_id']);guard();need(raw._session is original and raw.tab_id==config['tab_id'],'session_changed')
    folder.mkdir(parents=True,exist_ok=True);trace=folder/'RPC_TRACE.jsonl'
    with trace.open('xb'):pass
    def record(value):
        with trace.open('a',encoding='utf8') as stream:stream.write(json.dumps(dict(at_epoch=time.time(),**value),ensure_ascii=False)+'\n');stream.flush();os.fsync(stream.fileno())
    class ReadGate:
        def cmd(self,kind,**kw):
            need(kw.pop('tab_id',raw.tab_id)==raw.tab_id,'session_changed');guard()
            if kind=='upload_check_proof':need(kw.get('operation')=='observe' and kw.get('selection_nonce')==nonce,'rpc_not_allowed')
            elif kind=='screenshot':need(Path(kw.get('path','')).resolve()==folder/'CURRENT_DECLARATION_CONTROLS.png' and not Path(kw['path']).exists(),'rpc_not_allowed')
            else:need(kind in {'current_url','evaluate','wait_for_timeout'},'rpc_not_allowed')
            record(dict(event='rpc_dispatched',action=kind));value=original.cmd(kind,tab_id=raw.tab_id,**kw);guard();record(dict(event='rpc_returned',action=kind));return value
    page=leaf.Page(ReadGate(),raw.tab_id)
    try:
        current=urlsplit(page._cmd('current_url')['url']);need(current.scheme=='https' and current.hostname=='creator.douyin.com' and current.path==LOCATION['path'],'editor_unconfirmed')
        proof=page._cmd('upload_check_proof',operation='observe',selection_nonce=nonce).get('proof',{});diag=proof.get('diagnostic',{})
        need(proof.get('schema')=='upload_check_transition/v2' and proof.get('selection_nonce')==nonce and all(diag.get(k)==v for k,v in baseline.items()),'editor_unconfirmed')
        video=page.evaluate(previous.VIDEO_PROBE);d=video.get('duration')
        need(video.get('origin')==LOCATION['origin'] and video.get('path')==LOCATION['path'] and video.get('visible_video_count')==1
             and type(d) in {int,float} and math.isfinite(d) and abs(d-duration)<=.5 and type(video.get('ready_state')) is int and video['ready_state']>=1,'editor_unconfirmed')
        fence=once(folder/'DRAFT_FENCE.json',dict(native_upload_proof=proof,video=video,platform_media_sha_verified=False,fresh_document_handle_claimed=False))
        samples=[];previous_signature=None;stable=0;observed=None
        for _ in range(8):
            observed=page.evaluate(modal_controls_script());samples.append(observed)
            signature=json.dumps(observed,ensure_ascii=False,sort_keys=True)
            stable=stable+1 if signature==previous_signature and observed.get('render_complete') is True else 1 if observed.get('render_complete') is True else 0
            previous_signature=signature
            if stable>=2:break
            page.wait_for_timeout(150)
        samples_ref=once(folder/'CONTROL_OBSERVATION_SAMPLES.json',dict(samples=samples));controls=once(folder/'CURRENT_DECLARATION_CONTROLS.json',observed)
        need(stable>=2 and observed.get('render_complete') is True and observed.get('truncated') is False,'modal_unconfirmed')
        try:
            image=folder/'CURRENT_DECLARATION_CONTROLS.png';page._cmd('screenshot',path=str(image),full_page=False);shot=dict(status='saved',file=reference(image))
        except Exception as error:shot=dict(status='unavailable',error_type=type(error).__name__)
        guard();result=dict(schema='manual_republication_declaration_controls/v10',action=ACTION,status='current_controls_observed',action_claim=action_ref,
            modal_controls=controls,observation_samples=samples_ref,draft_fence=fence,screenshot=shot,render_complete=True,
            native_associations_complete=observed['native_associations_complete'],same_tab=raw.tab_id,rpc_trace=reference(trace),
            input_performed=False,selection_performed=False,declaration_confirmed=False,publish_clicked=False,navigation_performed=False,
            file_selected=False,submitted=False,publication_ready=False,stage2_implemented=False)
        once(folder/'INSPECTION_RESULT.json',result);return result
    except Exception as error:
        code=error.code if type(error) is DeclarationControlsBlocked else 'controls_inspection_unknown'
        failure=once(folder/'INSPECTION_FAILURE.json',dict(schema='manual_declaration_controls_failure/v10',reason_code=code,error_type=type(error).__name__,rpc_trace=reference(trace),
            input_performed=False,selection_performed=False,declaration_confirmed=False,publish_clicked=False,navigation_performed=False,file_selected=False,submitted=False))
        raise DeclarationControlsBlocked(code,failure) from error


PUBLISH_ACTION='set_declaration_and_publish_once'
CONTINUE_ACTION='continue_selected_declaration_and_publish_once'
LABEL_SELECTOR='div.semi-modal:visible label.semi-radio'
CONFIRM_SELECTOR='div.semi-modal:visible button >> xpath=self::*[normalize-space(.)="确定"]'
PUBLISH_SELECTOR='button:visible >> xpath=self::*[normalize-space(.)="发布"]'


def draft_state_script():
    """One public snapshot; exact authorized composer values plus native settings."""
    return r"""() => {
 const loc={origin:location.origin,path:location.pathname};
 if(loc.origin!=='https://creator.douyin.com'||loc.path!=='/creator-micro/content/post/video')return {schema:'manual_publish_dom_state/v10',location:loc,origin_blocked:true};
 const visible=e=>!!e&&e.isConnected&&e.getClientRects().length>0&&!e.closest('[hidden],[aria-hidden="true"],[inert]')&&(()=>{for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||['hidden','collapse'].includes(s.visibility)||Number(s.opacity)===0)return false}return true})();
 const text=e=>String(e?.innerText||'').trim().replace(/\s+/g,' ');
 const titles=[...document.querySelectorAll('input[placeholder="填写作品标题，为作品获得更多流量"]')].filter(visible);
 const editors=[...document.querySelectorAll('div[data-slate-editor="true"].editor[contenteditable="true"]')].filter(visible);
 const root=editors.length===1?editors[0]:null;const raw=root?(root.innerText||''):'';
 const topicSelector='[class*="topic"],[class*="hashtag"],[data-type="topic"],[data-type="hashtag"]';
 const chips=root?[...root.querySelectorAll(topicSelector+',[data-slate-inline="true"],[data-slate-void="true"],[contenteditable="false"]')].filter(visible):[];
 const names=['公开','好友可见','仅自己可见','立即发布','定时发布'];
 const labels=[...document.querySelectorAll('label')].filter(visible).filter(e=>names.includes(text(e)));
 const rows=labels.map(e=>{const c=e.control;const linked=!!c&&e.contains(c)&&c instanceof HTMLInputElement&&['radio','checkbox'].includes(c.type);
   return {text:text(e),tag:'label',class_name:(e.className||'').slice(0,300),native_associated:linked,
     control:linked?{tag:'input',type:c.type,name:c.getAttribute('name')||'',class_name:(c.className||'').slice(0,300),checked:c.checked,disabled:c.disabled===true}:null};});
 const anchor=(title,options)=>{const first=labels.find(e=>text(e)===options[0]);if(!first)return null;
   for(let p=first.parentElement,depth=0;p&&depth<7;p=p.parentElement,depth++){
     if(p.querySelectorAll('*').length>350)continue;
     const header=[...p.querySelectorAll('*')].filter(e=>visible(e)&&text(e)===title&&! [...e.children].some(c=>visible(c)&&text(c)===title));
     if(header.length===1&&options.every(t=>labels.filter(e=>p.contains(e)&&text(e)===t).length===1))return {header:title,tag:p.tagName.toLowerCase(),class_name:(p.className||'').slice(0,300),ancestor_depth:depth};}
   return null;};
 const checkedExactly=(options,selected)=>options.every(t=>{const all=rows.filter(r=>r.text===t);return all.length===1&&all[0].native_associated&&all[0].control.disabled===false&&all[0].control.checked===(t===selected)});
 const publicAnchor=anchor('谁可以看',names.slice(0,3)),timeAnchor=anchor('发布时间',names.slice(3));
 const buttons=[...document.querySelectorAll('button')].filter(e=>visible(e)&&text(e)==='发布');const button=buttons.length===1?buttons[0]:null;
 let center=false,rect=null,outside=null;if(button){const r=button.getBoundingClientRect();rect={x:r.x,y:r.y,width:r.width,height:r.height};const x=r.left+r.width/2,y=r.top+r.height/2,hit=document.elementFromPoint(x,y);outside=x<0||y<0||x>=innerWidth||y>=innerHeight;center=!outside&&!!hit&&(hit===button||button.contains(hit));}
 const sections=[...document.querySelectorAll('section.wrapper-MLZdnB')].filter(e=>visible(e)&&[...e.querySelectorAll(':scope > div.labelWrapper-p6osJm > div.title-cnbkZe')].filter(t=>visible(t)&&text(t)==='自主声明').length===1);
 const values=sections.flatMap(e=>[...e.querySelectorAll(':scope > div.controlWrapper-Kt_9Xm > div.selectBox-buZRzi > div.selectText-XSrMFZ')].filter(visible));
 const videos=[...document.querySelectorAll('video')].filter(visible);
 const safe=[];let n,count=0;const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
 while((n=walker.nextNode())&&count++<15000){const p=n.parentElement;if(!visible(p)||p.closest('script,style,input,textarea,[contenteditable="true"],[role="textbox"]'))continue;const v=n.nodeValue.trim();if(v&&safe.length<180)safe.push(v.slice(0,600));}
 return {schema:'manual_publish_dom_state/v10',location:loc,observed_native_modal_count:[...document.querySelectorAll('div.semi-modal')].filter(visible).length,
  title:{unique_count:titles.length,content:titles.length===1?titles[0].value:null,disabled:titles.length===1?titles[0].disabled:null},
  editor:{unique_count:editors.length,text:raw.slice(0,12000),truncated:raw.length>12000||chips.length>40,chips:chips.slice(0,40).map(e=>({text:(e.innerText||'').slice(0,256),explicit_topic:e.matches(topicSelector)}))},
  settings:{schema:'manual_native_publication_settings/v10',native_labels:rows,public_anchor:publicAnchor,immediate_anchor:timeAnchor,
   public_verified:!!publicAnchor&&checkedExactly(names.slice(0,3),'公开'),immediate_verified:!!timeAnchor&&checkedExactly(names.slice(3),'立即发布'),unrelated_input_values_read:false},
  statement:{section_count:sections.length,value_count:values.length,value:values.length===1?text(values[0]):null},
  publish_button:{unique_count:buttons.length,visible:!!button,enabled:!!button&&!button.disabled&&button.getAttribute('aria-disabled')!=='true',center_hit:center,out_of_viewport:outside,text:button?text(button):null,type:button?button.type:null,rect},
  viewport:{inner_width:innerWidth,inner_height:innerHeight,scroll_x:scrollX,scroll_y:scrollY},
  video:{origin:loc.origin,path:loc.path,visible_video_count:videos.length,duration:videos.length===1&&Number.isFinite(videos[0].duration)?videos[0].duration:null,ready_state:videos.length===1?videos[0].readyState:null},
  safe_visible_body:safe,authorized_field_values_read:true,unrelated_input_values_read:false,private_state_read:false};
 }"""


def publish_scroll_script(mode,nonce):
    need(mode in {'locate','scroll','cleanup'} and re.fullmatch('[a-f0-9]{32}',nonce),'request_invalid')
    key=json.dumps('__manual_publish_view_'+nonce)
    if mode=='cleanup':return '()=>{delete window['+key+'];return {cleaned:true};}'
    return 'el=>{const key='+key+',mode='+json.dumps(mode)+';const state=('+draft_state_script()+r""")();
      const visible=e=>!!e&&e.isConnected&&e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden'&&!e.closest('[hidden],[aria-hidden="true"]');
      const buttons=[...document.querySelectorAll('button')].filter(e=>visible(e)&&(e.innerText||'').trim()==='发布');
      const exact=state.location?.origin==='https://creator.douyin.com'&&state.location?.path==='/creator-micro/content/post/video'&&buttons.length===1&&buttons[0]===el;
      if(mode==='locate'){if(window[key]||!exact||state.publish_button?.out_of_viewport!==true)return {located:false,state};window[key]={node:el,scrolls:0};return {located:true,same:true,state};}
      const old=window[key];if(!old||old.node!==el||old.scrolls!==0||!exact||state.publish_button?.out_of_viewport!==true)return {scrolled:false,same:false,state};
      old.scrolls=1;el.scrollIntoView({block:'center',inline:'nearest'});return {scrolled:true,same:window[key].node===el,scroll_count:1,state:(STATE)()};
    }""".replace('STATE',draft_state_script())


def native_action_probe(kind):
    need(kind in {'select','confirm','confirm_component','publish'},'request_invalid')
    if kind=='publish':
        return 'el=>{const s=('+draft_state_script()+')();return {same:el.tagName===\'BUTTON\'&&(el.innerText||\'\').trim()===\'发布\',state:s};}'
    return r"""el=>{
 const visible=e=>!!e&&e.isConnected&&e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden'&&!e.closest('[hidden],[aria-hidden="true"],[inert]');
 const root=el.closest('div.semi-modal');const labels=root?[...root.querySelectorAll('label.semi-radio')].filter(visible):[];
 const texts=labels.map(e=>(e.innerText||'').trim());const controls=labels.map(e=>e.control);
 const linked=labels.length===6&&texts.every((t,i)=>t===KNOWN[i])&&controls.every((c,i)=>!!c&&labels[i].contains(c)&&root.contains(c)&&c.type==='radio'&&c.name==='default'&&!c.disabled);
 const checked=controls.map(c=>c?c.checked:null);const selected=linked&&checked.every((v,i)=>v===(i===0));
 const component=linked&&labels.every((label,index)=>label.classList.contains('semi-radio-checked')===(index===0))&&
   checked.every((value,index)=>typeof value==='boolean'&&(index===0||value===false))&&
   [...root.querySelectorAll('*')].filter(e=>visible(e)&&(e.innerText||'').trim()==='作者声明：内容由AI生成'&&![...e.children].some(c=>visible(c)&&(c.innerText||'').trim()==='作者声明：内容由AI生成')).length===1;
 const targets=KIND==='select'?labels:[...root?.querySelectorAll('button')||[]].filter(e=>visible(e)&&(e.innerText||'').trim()==='确定'&&e.type==='button'&&!e.disabled);
 const same=KIND==='select'?labels[0]===el:targets.length===1&&targets[0]===el;
 return {linked,same,checked,selected,native_selected:selected,component_selected:component,
   eligible:linked&&same&&(KIND==='select'?checked.every(v=>v===false):KIND==='confirm_component'?component:selected),input_values_read:false};
 }""".replace('KNOWN',json.dumps(KNOWN_LABELS,ensure_ascii=False)).replace('KIND',json.dumps(kind))


def post_submit_script():
    return r"""() => {
 const visible=e=>!!e&&e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden'&&!e.closest('[hidden],[aria-hidden="true"]');
 const canonical=v=>{try{const u=new URL(v,location.href);if(u.protocol==='https:'&&['www.douyin.com','douyin.com'].includes(u.hostname)&&/^\/video\/\d+$/.test(u.pathname))return {id:u.pathname.split('/').pop(),url:'https://www.douyin.com'+u.pathname};}catch{}return null};
 const loc={origin:location.origin,path:location.pathname};
 if(!['https://creator.douyin.com','https://www.douyin.com','https://douyin.com'].includes(loc.origin))return {schema:'manual_post_submit_native_observation/v10',location:loc,origin_blocked:true,cards:[],visible_modals:[],safe_visible_body:[],input_values_read:false};
 const safeText=value=>String(value||'').replace(/https?:\/\/[^\s<>"']+/g,s=>{try{const u=new URL(s);return u.origin+u.pathname}catch{return '[url omitted]'}});
 const body=[];let node,count=0;const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
 while((node=walker.nextNode())&&count++<15000){const p=node.parentElement;if(!visible(p)||p.closest('script,style,input,textarea,[contenteditable="true"],[role="textbox"]'))continue;const value=node.nodeValue.trim();if(value&&body.length<200)body.push(safeText(value).slice(0,700));}
 const modalNodes=[...document.querySelectorAll('div.semi-modal,[role="dialog"],[role="modal"]')].filter(visible);
 const modalRoots=modalNodes.filter(e=>!modalNodes.some(other=>other!==e&&other.contains(e)));
 const modals=modalRoots.slice(0,8).map(e=>({tag:e.tagName.toLowerCase(),role:e.getAttribute('role'),class_name:typeof e.className==='string'?e.className.slice(0,300):'',
   visible_text:safeText(e.innerText).slice(0,12000),buttons:[...e.querySelectorAll('button')].filter(visible).slice(0,30).map(b=>({text:safeText(b.innerText).trim().slice(0,300),type:b.type,disabled:b.disabled===true,aria_disabled:b.getAttribute('aria-disabled')}))}));
 const known=[...document.querySelectorAll('[class*="video-card-"],[data-video-id],[data-e2e-vid]')].filter(visible);
 const cards=known.filter(e=>!known.some(other=>other!==e&&e.contains(other))).slice(0,40).map(e=>{const text=(e.innerText||'').slice(0,7000);
   const titles=[...e.querySelectorAll('[class*="info-title-text"]')].filter(visible).map(t=>(t.innerText||'').trim());
   const links=[...e.querySelectorAll('a[href]')].filter(visible).map(a=>canonical(a.getAttribute('href'))).filter(Boolean);
   const ids=['data-video-id','data-e2e-vid'].map(name=>({name,value:e.getAttribute(name)})).filter(x=>/^\d{10,24}$/.test(x.value||''));
   return {tag:e.tagName.toLowerCase(),class_name:typeof e.className==='string'?e.className.slice(0,400):'',titles,canonical_links:links,native_ids:ids,
     visible_text:text,native_date_texts:text.match(/20\d{2}[年./-]\d{1,2}[月./-]\d{1,2}日?(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?/g)||[],native_duration_texts:text.match(/(?:^|\s)\d{1,2}:\d{2}(?:\s|$)/g)||[]};});
 return {schema:'manual_post_submit_native_observation/v10',location:loc,current_canonical:canonical(location.href),cards,visible_modals:modals,
   safe_visible_body:body,body_capture_truncated:count>=15000||body.length>=200,modal_capture_truncated:modalRoots.length>8,
   card_capture_truncated:known.length>40,old_title_alone_is_not_new_post_evidence:true,input_values_read:false,private_state_read:false};
 }"""


def _publish_action(actor,resource,config,request,outdir,runtime):
    reference,read,once=runtime.reference,runtime._read,runtime._once
    continuing=request.get('action')==CONTINUE_ACTION
    fields={'schema','config','action','controls_result','controls_receipt','declaration_contract','submission_authority'}
    if continuing:fields.add('selected_state_contract')
    need(isinstance(request,dict) and set(request)==fields and request['schema']=='manual_republication_operator_request/v10'
         and request['action'] in {PUBLISH_ACTION,CONTINUE_ACTION} and request['submission_authority']==config['authority'],'request_invalid')
    need(read(request['config'])==config,'binding_changed')
    folder=Path(outdir).resolve();need(folder.name=='publication' and folder.is_relative_to(ROOT/'data'),'output_changed')
    action_ref=reference(folder.parent/'ACTION_CLAIM.json');action=read(action_ref);plan=read(action['plan'])
    need(action.get('schema')=='manual_republication_publish_action_claim/v10' and action.get('action')==request['action']
         and action.get('config')==request['config'] and read(action['request'])==request and plan.get('config')==request['config'] and plan.get('request')==action['request']
         and all(action.get(k)==config[k] for k in ('owner_id','generation','tab_id')) and action.get('actor_thread_id')==threading.get_ident()
         and action.get('navigation_allowed') is False and action.get('file_selection_allowed') is False
         and type(action.get('selections_allowed')) is int and action['selections_allowed']==int(not continuing)
         and all(type(action.get(k)) is int and action[k]==1 for k in ('confirmations_allowed','submissions_allowed'))
         and folder==Path(action['plan']['path']).resolve().parent/'publication','claim_changed')
    contract=read(request['declaration_contract']);original_controls=read(contract['native_controls']);requirements=read(contract['post_submit_verification_requirements'])
    need(contract.get('schema')=='native_statement_selection_contract/v1' and contract.get('inspection_result')==request['controls_result']
         and contract.get('inspection_receipt')==request['controls_receipt'] and contract.get('selected_label')==contract.get('required_final_statement')==KNOWN_LABELS[0]
         and contract.get('selection_semantics')=='single' and contract.get('expected_all_other_labels')==list(KNOWN_LABELS[1:])
         and contract.get('caption_must_remain_unchanged') is True and contract.get('no_file_selection_allowed') is True
         and contract.get('no_navigation_before_submission') is True and contract.get('native_marketing_also_selected') is False
         and all(type(contract.get(k)) is int and contract[k]==1 for k in ('new_publication_limit','new_backfill_limit'))
         and contract.get('native_label')==original_controls.get('labels',[None])[0]
         and contract.get('native_radio')==original_controls.get('native_controls',[None])[0]
         and contract.get('native_confirmation')=={'tag':'button','type':'button','text':'确定'},'contract_invalid')
    need(requirements.get('schema')=='republication_verification_requirements/v1' and requirements.get('authority')==config['authority']
         and requirements.get('metadata')==config['metadata'] and set(requirements.get('excluded_old_post_ids',[]))=={'7709043480894524722','7708948487446056192'}
         and requirements.get('no_submit_retry') is True,'contract_invalid')
    parent,previous=_previous(config,reference);leaf=previous._load_base(config);reader,Workflow=leaf._load_leaves(config);metadata,authority=leaf._metadata(config)
    prior=plan['prior'];nonce=prior['selection_nonce'];baseline=prior['upload_route_baseline'];duration=prior['source_duration_seconds'];original=resource.session
    need(contract['metadata']==config['metadata'] and contract['file_selection_claim']==prior['file_selection_claim'],'contract_invalid')
    display_contract=read(request['selected_state_contract']) if continuing else None
    if continuing:
        basis=display_contract.get('component_selection_basis',{})
        need(display_contract.get('schema')=='semi_radio_selection_display_contract/v1' and display_contract.get('parent_selection_contract')==request['declaration_contract']
             and display_contract.get('authority')==config['authority'] and display_contract.get('expected_selected_label')==KNOWN_LABELS[0]
             and display_contract.get('native_checked_must_not_be_falsified') is True
             and display_contract.get('observed_native_input_checked')==[False]*6
             and basis=={'unique_selected_label_class':'semi-radio-checked','only_label_index':0,'all_other_labels_without_selected_class':True,
                 'native_label_associations_unchanged':True,'exact_preview_text':'作者声明：内容由AI生成',
                 'unique_confirmation_button':{'text':'确定','type':'button','disabled':False},'all_12_stable_samples_match':True}
             and all(display_contract.get(k) is True for k in ('no_original_action_replay','no_new_upload','logical_publication_intent_unchanged'))
             and all(type(display_contract.get(k)) is int and display_contract[k]==v for k,v in (
                 ('continuation_selections_allowed',0),('continuation_confirmations_allowed',1),('continuation_publications_allowed',1))),'contract_invalid')
        blocked=read(display_contract['blocked_result']);failure=read(display_contract['failure'])
        need(blocked.get('status')=='blocked_no_submission' and blocked.get('submitted') is False and blocked.get('submission_not_attempted') is True
             and failure.get('selection_click_dispatched') is True
             and all(failure.get(k) is False for k in ('confirmation_click_dispatched','publish_click_dispatched','submission_claimed')),'contract_invalid')
    deadline=time.monotonic()+420;immutable=[action_ref,request['config'],request['controls_result'],request['controls_receipt'],request['declaration_contract'],
        request['submission_authority'],contract['native_controls'],contract['post_submit_verification_requirements'],prior['file_selection_claim'],prior['upload_journal']]
    if continuing:
        immutable.extend([request['selected_state_contract'],*[display_contract[k] for k in (
            'blocked_result','blocked_receipt','failure','selected_samples','rpc_trace','screenshot','independent_terminal_review')]])
    def guard():
        need(time.monotonic()+45<deadline,'deadline_reached')
        need(resource.session is original and original._proc is not None and original._proc.poll() is None,'session_changed')
        runtime.validate_live(actor,resource,config)
        for ref in immutable:need(reference(ref['path'])==ref,'binding_changed')
        b=resource.runtime.bindings.get(config['account_key']);p=resource.runtime.profiles.get(config['account_key'])
        need(b.account_uuid==p.account_uuid==config['account_id'] and reader._binding_version(SimpleNamespace(binding=b,profile=p))==config['binding_version']
             and str(b.public_uid)==authority['expected_public_uid'],'session_changed')
    guard();raw=original.get_page(config['tab_id']);guard();need(raw._session is original and raw.tab_id==config['tab_id'],'session_changed')
    folder.mkdir(parents=True,exist_ok=True);trace=folder/'RPC_TRACE.jsonl'
    with trace.open('xb'):pass
    phase='preselection_settings';selected=False;confirmed=False;selection_observed=False;selection_reused_observed=False;confirmation_observed=False;publish_dispatched=False;submission_claim=None;preflight_ref=None
    publish_scrolled=False;scroll_before_ref=None;scroll_after_ref=None
    def record(value):
        with trace.open('a',encoding='utf8') as stream:stream.write(json.dumps(dict(at_epoch=time.time(),phase=phase,**value),ensure_ascii=False)+'\n');stream.flush();os.fsync(stream.fileno())
    class Gate:
        def cmd(self,kind,**kw):
            nonlocal selected,confirmed,publish_dispatched,submission_claim
            need(kw.pop('tab_id',raw.tab_id)==raw.tab_id,'session_changed');guard()
            if kind=='click':
                selector=kw.get('selector')
                if selector==LABEL_SELECTOR:
                    need(not continuing and not selected and not confirmed and not publish_dispatched and kw.get('index')==0,'rpc_not_allowed')
                    proof=self.cmd('evaluate',selector=LABEL_SELECTOR,index=0,js=native_action_probe('select')).get('value',{})
                    need(proof.get('eligible') is True,'selection_unconfirmed');selected=True
                elif selector==CONFIRM_SELECTOR:
                    need((selected or selection_reused_observed) and not confirmed and not publish_dispatched,'rpc_not_allowed')
                    proof=self.cmd('evaluate',selector=CONFIRM_SELECTOR,index=0,js=native_action_probe('confirm_component' if continuing else 'confirm')).get('value',{})
                    need(proof.get('eligible') is True and proof.get('component_selected' if continuing else 'selected') is True,'confirmation_unconfirmed');confirmed=True
                elif selector==PUBLISH_SELECTOR:
                    need((selected or selection_reused_observed) and confirmed and not publish_dispatched and preflight_ref is not None,'rpc_not_allowed')
                    last=self.cmd('evaluate',selector=PUBLISH_SELECTOR,index=0,js=native_action_probe('publish')).get('value',{})
                    state=last.get('state',{});form(state);settings=state.get('settings',{});button=state.get('publish_button',{})
                    need(last.get('same') is True and state.get('observed_native_modal_count')==0
                         and state.get('statement',{}).get('value')==KNOWN_LABELS[0]
                         and settings.get('public_verified') is True and settings.get('immediate_verified') is True
                         and button.get('unique_count')==1 and button.get('visible') is True and button.get('enabled') is True
                         and button.get('center_hit') is True and button.get('text')=='发布','publish_unconfirmed')
                    fence(state);once(folder/'LAST_PUBLISH_ELEMENT_PROBE.json',last)
                    submission_claim=runtime.claim_submission(actor,resource,config,request,preflight_ref)
                    need(reference(submission_claim['path'])==submission_claim,'claim_changed')
                    publish_dispatched=True
                else:need(False,'rpc_not_allowed')
            elif kind=='upload_check_proof':need(kw.get('operation')=='observe' and kw.get('selection_nonce')==nonce,'rpc_not_allowed')
            elif kind=='screenshot':need(Path(kw.get('path','')).resolve().parent==folder and not Path(kw['path']).exists(),'rpc_not_allowed')
            else:need(kind in {'current_url','evaluate','locator_count','wait_for_timeout'},'rpc_not_allowed')
            record(dict(event='rpc_dispatched',action=kind,selector=kw.get('selector'),index=kw.get('index')))
            try:value=original.cmd(kind,tab_id=raw.tab_id,**kw)
            except Exception as error:record(dict(event='rpc_error',action=kind,error_type=type(error).__name__));raise
            guard();record(dict(event='rpc_returned',action=kind));return value
    page=leaf.Page(Gate(),raw.tab_id)
    normalize=lambda s:''.join(str(s).replace('\u200b','').split())
    def form(state):
        title=state.get('title',{});editor=state.get('editor',{})
        need(state.get('location')==LOCATION and title.get('unique_count')==editor.get('unique_count')==1 and not title.get('disabled') and editor.get('truncated') is False,'form_changed')
        snapshot={'text':editor['text'],'chips':editor['chips']};tokens=Workflow._hashtag_tokens(snapshot);core=editor['text']
        for tag in tokens:core=re.sub(r'[#＃]\s*'+re.escape(tag)+r'(?!\w)','',core)
        need(title.get('content')==metadata['title'] and normalize(core)==normalize(metadata['description']) and set(tokens)==set(metadata['hashtags']),'form_changed')
        return dict(title=dict(content=title['content']),description_core=core,editor_text=editor['text'],hashtag_tokens=list(tokens),hashtag_sources=tokens,description_exact=True)
    def fence(state):
        proof=page._cmd('upload_check_proof',operation='observe',selection_nonce=nonce).get('proof',{});diag=proof.get('diagnostic',{});video=state['video'];d=video.get('duration')
        need(proof.get('schema')=='upload_check_transition/v2' and proof.get('selection_nonce')==nonce and all(diag.get(k)==v for k,v in baseline.items())
             and video.get('origin')==LOCATION['origin'] and video.get('path')==LOCATION['path'] and video.get('visible_video_count')==1
             and type(d) in {int,float} and math.isfinite(d) and abs(d-duration)<=.5 and type(video.get('ready_state')) is int and video['ready_state']>=1,'editor_unconfirmed')
        return dict(native_upload_proof=proof,video=video,platform_media_sha_verified=False,fresh_document_handle_claimed=False)
    def controls_valid(current,after=False):
        labels=current.get('labels',[]);old_labels=original_controls.get('labels',[])
        need(current.get('render_complete') is True and current.get('native_associations_complete') is True and len(labels)==len(old_labels)==6
             and all('semi-radio' in a.get('class_name','').split() and {k:v for k,v in a.items() if k!='class_name'}=={k:v for k,v in b.items() if k!='class_name'} for a,b in zip(labels,old_labels)),'selection_unconfirmed')
        current_native=current['native_controls'];old_native=original_controls['native_controls']
        need(len(current_native)==len(old_native)==6 and all({k:v for k,v in a.items() if k not in {'checked','aria_checked'}}=={k:v for k,v in b.items() if k not in {'checked','aria_checked'}} for a,b in zip(current_native,old_native))
             and all(n.get('aria_checked') in {None,str(n.get('checked')).lower()} for n in current_native)
             and all(n.get('checked') is (i==0 if after else False) for i,n in enumerate(current_native)),'selection_unconfirmed')
    def component_selected(current):
        labels=current.get('labels',[]);natives=current.get('native_controls',[]);old_labels=original_controls.get('labels',[]);old_native=original_controls.get('native_controls',[])
        need(current.get('render_complete') is True and current.get('native_associations_complete') is True and len(labels)==len(natives)==len(old_labels)==len(old_native)==6
             and all({k:v for k,v in a.items() if k!='class_name'}=={k:v for k,v in b.items() if k!='class_name'}
                     and 'semi-radio' in a.get('class_name','').split() and ('semi-radio-checked' in a['class_name'].split())==(i==0)
                     for i,(a,b) in enumerate(zip(labels,old_labels)))
             and all({k:v for k,v in a.items() if k not in {'checked','aria_checked'}}=={k:v for k,v in b.items() if k not in {'checked','aria_checked'}} for a,b in zip(natives,old_native))
             and all(type(n.get('checked')) is bool and (i==0 or n['checked'] is False) for i,n in enumerate(natives)),'selection_unconfirmed')
        previews=[e for e in current.get('visible_leaves',[]) if e.get('text')=='作者声明：内容由AI生成']
        confirmations=[e for e in current.get('buttons',[]) if e.get('text')=='确定' and e.get('type')=='button' and e.get('disabled') is False]
        need(len(previews)==len(confirmations)==1,'selection_unconfirmed')
        return dict(schema='semi_radio_component_selection_evidence/v1',selected_state_contract=request['selected_state_contract'],
            component_selected_label=KNOWN_LABELS[0],component_selection_observed=True,native_checked_actual=[n['checked'] for n in natives],
            native_checked_falsified=False,preview_text=previews[0]['text'],confirmation=confirmations[0],declaration_confirmed=False,
            selection_by_this_action=False)
    try:
        initial=page.evaluate(draft_state_script());once(folder/'INITIAL_PUBLIC_SETTINGS_AND_FORM.json',initial)
        need(initial.get('settings',{}).get('public_verified') is True and initial['settings'].get('immediate_verified') is True,'settings_unconfirmed')
        before_form=once(folder/'FORM_BEFORE.json',form(initial));before_fence=once(folder/'DRAFT_FENCE_BEFORE.json',fence(initial))
        controls=page.evaluate(modal_controls_script());once(folder/'CONTROLS_BEFORE.json',controls)
        if continuing:
            phase='reuse_observed_component_selection'
            selected_ref=once(folder/'COMPONENT_SELECTED_GROUP.json',dict(raw_controls=controls,evidence=component_selected(controls)))
            selection_reused_observed=True
        else:
            controls_valid(controls)
            once(folder/'STATEMENT_SELECTION_INTENT.json',dict(action_claim=action_ref,declaration_contract=request['declaration_contract'],label=KNOWN_LABELS[0],selection_limit=1))
            phase='native_select_ai_label';page.locator(LABEL_SELECTOR).nth(0).click(timeout=10000)
            phase='read_selected_native_group';samples=[];stable=0
            for _ in range(12):
                current=page.evaluate(modal_controls_script());samples.append(current)
                try:controls_valid(current,True);stable+=1
                except DeclarationControlsBlocked:stable=0
                if stable>=2:break
                page.wait_for_timeout(150)
            selected_ref=once(folder/'NATIVE_SELECTED_GROUP.json',dict(samples=samples));need(stable>=2,'selection_unconfirmed')
            selection_observed=True
        once(folder/'STATEMENT_CONFIRM_INTENT.json',dict(action_claim=action_ref,selected_group=selected_ref,confirmation_limit=1))
        phase='native_confirm_ai_statement';page.locator(CONFIRM_SELECTOR).first().click(timeout=10000)
        phase='read_confirmed_statement';states=[];state=None
        for _ in range(12):
            state=page.evaluate(draft_state_script());states.append(state)
            if state.get('observed_native_modal_count')==0 and state.get('statement',{}).get('section_count')==state['statement'].get('value_count')==1 and state['statement'].get('value')==KNOWN_LABELS[0]:break
            page.wait_for_timeout(150)
        confirmed_ref=once(folder/'CONFIRMED_STATEMENT_STATES.json',dict(samples=states))
        need(state.get('observed_native_modal_count')==0 and state.get('statement',{}).get('value')==KNOWN_LABELS[0],'confirmation_unconfirmed')
        confirmation_observed=True
        phase='final_publish_preflight';fresh=page.evaluate(draft_state_script());form(fresh)
        need(fresh.get('observed_native_modal_count')==0 and fresh.get('statement',{}).get('value')==KNOWN_LABELS[0]
             and fresh.get('settings',{}).get('public_verified') is True and fresh['settings'].get('immediate_verified') is True,'publish_unconfirmed')
        button=fresh.get('publish_button',{})
        if button.get('out_of_viewport') is True:
            need(button.get('unique_count')==1 and button.get('visible') is True and button.get('enabled') is True and button.get('text')=='发布','publish_unconfirmed')
            phase='scroll_original_publish_button';token=secrets.token_hex(16)
            located=page.locator(PUBLISH_SELECTOR).first().evaluate(publish_scroll_script('locate',token))
            scroll_before_ref=once(folder/'PUBLISH_VIEWPORT_BEFORE_SCROLL.json',located)
            need(located.get('located') is True and located.get('same') is True,'publish_unconfirmed');form(located['state'])
            need(located['state'].get('settings',{}).get('public_verified') is True and located['state']['settings'].get('immediate_verified') is True
                 and located['state'].get('statement',{}).get('value')==KNOWN_LABELS[0] and located['state'].get('observed_native_modal_count')==0,'publish_unconfirmed')
            once(folder/'PUBLISH_SCROLL_INTENT.json',dict(action_claim=action_ref,original_node_probe=scroll_before_ref,allowed_scrolls=1,
                method='scrollIntoView',arguments={'block':'center','inline':'nearest'},selection_or_submission_allowed=False))
            try:
                moved=page.locator(PUBLISH_SELECTOR).first().evaluate(publish_scroll_script('scroll',token))
                scroll_after_ref=once(folder/'PUBLISH_VIEWPORT_AFTER_SCROLL.json',moved)
                need(moved.get('scrolled') is True and moved.get('same') is True and moved.get('scroll_count')==1,'publish_unconfirmed');publish_scrolled=True
                fresh=moved['state']
                for _ in range(4):
                    if fresh.get('publish_button',{}).get('center_hit') is True:break
                    page.wait_for_timeout(150);fresh=page.evaluate(draft_state_script())
            finally:page.evaluate(publish_scroll_script('cleanup',token))
        final_form=once(folder/'FORM_READBACK.json',form(fresh))
        settings_ref=once(folder/'PUBLICATION_SETTINGS.json',fresh.get('settings',{}));need(fresh['settings'].get('public_verified') is True and fresh['settings'].get('immediate_verified') is True,'settings_unconfirmed')
        need(fresh.get('observed_native_modal_count')==0 and fresh.get('statement',{}).get('value')==KNOWN_LABELS[0],'confirmation_unconfirmed')
        final_fence=once(folder/'DRAFT_FENCE.json',fence(fresh));button=fresh.get('publish_button',{})
        need(button.get('unique_count')==1 and button.get('visible') is True and button.get('enabled') is True and button.get('center_hit') is True and button.get('text')=='发布','publish_unconfirmed')
        preflight_ref=once(folder/'PUBLISH_PREFLIGHT.json',dict(schema='manual_republication_publish_preflight/v10',action_claim=action_ref,
            declaration_contract=request['declaration_contract'],file_selection_claim=prior['file_selection_claim'],metadata=config['metadata'],observed_at=time.time(),
            declaration_confirmed=True,selected_label=KNOWN_LABELS[0],modal_closed=True,form_readback=final_form,draft_fence=final_fence,settings=settings_ref,publish_button=button,
            confirmed_statement_states=confirmed_ref,native_selected_group=selected_ref))
        phase='publish_click_once';page.locator(PUBLISH_SELECTOR).first().click(timeout=15000)
        phase='post_submit_readonly';observations=[];candidates={};excluded=set(requirements['excluded_old_post_ids'])
        for _ in range(12):
            observation=page.evaluate(post_submit_script());observations.append(observation)
            direct=observation.get('current_canonical')
            if direct and direct['id'] not in excluded:candidates[direct['id']]=dict(direct,source='native_current_canonical_url',verification_pending=True)
            for card in observation.get('cards',[]):
                if len(card.get('titles',[]))!=1 or normalize(card['titles'][0])!=normalize(metadata['title']):continue
                ids={x['id'] for x in card['canonical_links']}|{x['value'] for x in card['native_ids']}
                if len(ids)!=1:continue
                post_id=next(iter(ids))
                if post_id in excluded:continue
                candidates[post_id]=dict(id=post_id,url='https://www.douyin.com/video/'+post_id,source='native_exact_card_id_or_href',
                    native_date_texts=card['native_date_texts'],native_duration_texts=card['native_duration_texts'],verification_pending=True)
            if candidates:break
            page.wait_for_timeout(500)
        observed_ref=once(folder/'POST_SUBMIT_OBSERVATIONS.json',dict(schema='manual_post_submit_observations/v10',observations=observations,
            new_post_candidates=list(candidates.values()),excluded_old_post_ids=sorted(excluded),post_verified=False,native_publication_time_verified=False))
        try:
            image=folder/'POST_SUBMIT.png';page._cmd('screenshot',path=str(image),full_page=False)
            post_screenshot=dict(status='saved',file=reference(image))
        except Exception as screenshot_error:post_screenshot=dict(status='unavailable',error_type=type(screenshot_error).__name__)
        result=dict(schema='manual_republication_publish_once/v10',action=request['action'],status='submitted_verification_pending',action_claim=action_ref,
            submission_claim=submission_claim,preflight=preflight_ref,form_before=before_form,draft_fence_before=before_fence,post_submit_observations=observed_ref,
            selection_performed=not continuing,selection_reused=selection_reused_observed,declaration_confirmed=True,publish_clicked=True,submitted=True,file_selected=False,navigation_performed=False,fields_written=False,
            new_post_candidates=list(candidates.values()),post_verified=False,native_publication_time_verified=False,metadata_readback_matched=True,
            selected_label=KNOWN_LABELS[0],post_submit_screenshot=post_screenshot,rpc_trace=reference(trace),post_submit_requirements=contract['post_submit_verification_requirements'],automatic_submit_retry=False)
        result.update(publish_scroll_performed=publish_scrolled,publish_viewport_before_scroll=scroll_before_ref,publish_viewport_after_scroll=scroll_after_ref)
        if continuing:result['selected_state_contract']=request['selected_state_contract']
        result['last_publish_probe']=reference(folder/'LAST_PUBLISH_ELEMENT_PROBE.json')
        once(folder/'PUBLICATION_RESULT.json',result);return result
    except Exception as error:
        diagnostics={}
        try:
            guard();state=page.evaluate(draft_state_script() if not publish_dispatched else post_submit_script());diagnostics['native_state']=once(folder/'FAILURE_NATIVE_STATE.json',state)
            image=folder/'FAILURE_SCREENSHOT.png';page._cmd('screenshot',path=str(image),full_page=False);diagnostics['screenshot']=reference(image)
        except Exception as capture_error:diagnostics['capture_error_type']=type(capture_error).__name__
        code='controls_submission_unknown' if submission_claim is not None else error.code if type(error) is DeclarationControlsBlocked else 'controls_inspection_unknown'
        failure=once(folder/'SUBMISSION_FAILURE.json',dict(schema='manual_declaration_publication_failure/v10',reason_code=code,phase=phase,error_type=type(error).__name__,
            selection_performed=selection_observed,selection_click_dispatched=selected,declaration_confirmed=confirmation_observed,confirmation_click_dispatched=confirmed,
            selection_reused=selection_reused_observed,
            publish_click_dispatched=publish_dispatched,submission_claimed=submission_claim is not None,
            submission_claim=submission_claim,native_diagnostics=diagnostics,rpc_trace=reference(trace),fields_written=False,file_selected=False,navigation_performed=False,
            automatic_submit_retry=False))
        raise DeclarationControlsBlocked(code,failure) from error


def run_action(actor,resource,config,request,outdir,runtime_bridge=None):
    runtime=runtime_bridge
    if runtime is None:
        from . import manual_republication_runtime_v10 as runtime
    if isinstance(request,dict) and request.get('action')==METADATA_ACTION:
        return _metadata_read_action(actor,resource,config,request,outdir,runtime)
    if isinstance(request,dict) and request.get('action')==VERIFY_ACTION:
        return _verify_public_action(actor,resource,config,request,outdir,runtime)
    if isinstance(request,dict) and request.get('action')==CAPTION_ACTION:
        return _caption_read_action(actor,resource,config,request,outdir,runtime)
    if isinstance(request,dict) and request.get('action') in {PUBLISH_ACTION,CONTINUE_ACTION}:
        return _publish_action(actor,resource,config,request,outdir,runtime)
    return _inspect_action(actor,resource,config,request,outdir,runtime_bridge=runtime)


METADATA_ACTION='read_submitted_work_metadata'
WORK_LIST_URL='https://creator.douyin.com/janus/douyin/creator/pc/work_list?status=0&count=20&max_cursor=0&scene=star_atlas&device_platform=android&aid=1128'


def project_work_metadata(response,metadata,submission_at,observed_at,excluded):
    """Project a transient native response; never return its body or media URLs."""
    status=response.get('status') if isinstance(response,dict) else None
    body=response.get('body') if isinstance(response,dict) else None
    raw=body.encode('utf8') if isinstance(body,str) else None
    output=dict(schema='submitted_work_metadata_projection/v10',http_status=status if type(status) is int else None,
        body_sha256=hashlib.sha256(raw).hexdigest() if raw is not None else None,body_bytes=len(raw) if raw is not None else None,
        api_business_success=False,response_state='unconfirmed_response',rows=[],candidates=[],post_verified=False,numeric_duration_verified=False,
        author_uid_not_equated_to_public_uid=True,raw_body_saved=False,response_headers_saved=False,signed_media_urls_saved=False)
    if raw is None:output['response_state']='unsupported_body_type';return output
    if len(raw)>8*1024*1024:output['response_state']='response_body_limit';return output
    try:value=json.loads(body)
    except (ValueError,TypeError):output['response_state']='invalid_json_response';return output
    business=value.get('status_code') if isinstance(value,dict) else None
    output['business_status']=business if type(business) in {int,str} else None
    if type(status) is not int or status!=200:output['response_state']='http_not_success';return output
    if not (type(business) is int and business==0 or type(business) is str and business=='0'):output['response_state']='business_not_success';return output
    records=value.get('aweme_list')
    if not isinstance(records,list):output['response_state']='aweme_list_not_list';return output
    output.update(api_business_success=True,response_state='work_list_observed',total_returned=len(records),rows_truncated=len(records)>20)
    norm=lambda s:''.join(s.replace('\u200b','').split())
    for index,record in enumerate(records[:20]):
        if not isinstance(record,dict):output['rows'].append(dict(index=index,match_reasons=['row_not_object']));continue
        raw_id=record.get('aweme_id');post_id=raw_id if isinstance(raw_id,str) and re.fullmatch(r'\d{10,24}',raw_id) else str(raw_id) if type(raw_id) is int and raw_id>=0 else None
        if post_id and not re.fullmatch(r'\d{10,24}',post_id):post_id=None
        caption=record.get('caption');title=record.get('item_title');created=record.get('create_time')
        row=dict(index=index,aweme_id=post_id,caption=caption[:16000] if isinstance(caption,str) else None,
            item_title=title[:1000] if isinstance(title,str) else None,create_time=created if type(created) in {int,float} or isinstance(created,str) and len(created)<=100 else None,
            string_fields_truncated=isinstance(caption,str) and len(caption)>16000 or isinstance(title,str) and len(title)>1000,
            public_status={},numeric_duration_fields=[],match_reasons=[])
        for container,prefix in ((record,''),(record.get('status'),'status.')):
            if not isinstance(container,dict):continue
            for key in ('is_private','private_status','review_status','reviewed','is_prohibited','allow_share','is_delete','item_status','visibility'):
                v=container.get(key)
                if type(v) in {bool,int,float} and (type(v) is not float or math.isfinite(v)):row['public_status'][prefix+key]=v
                elif isinstance(v,str) and len(v)<=100 and not re.search(r'https?://',v):row['public_status'][prefix+key]=v
        for container,prefix in ((record,''),(record.get('video'),'video.')):
            if not isinstance(container,dict):continue
            for key in ('duration','video_duration','duration_ms','duration_seconds'):
                v=container.get(key)
                if type(v) in {int,float} and math.isfinite(v):row['numeric_duration_fields'].append(dict(field=prefix+key,value=v,unit='unknown_not_converted'))
        id_new=bool(post_id and post_id not in excluded)
        epoch_ok=type(created) is int and 0<created<10**11
        time_candidate=epoch_ok and created+1>submission_at and created<=observed_at+1
        if epoch_ok:row['creation_second_window']=dict(start=created,end_exclusive=created+1,submission_at=submission_at,
            relation='after_claim' if created>=submission_at else 'overlaps_claim_second' if created+1>submission_at else 'before_claim',precision_seconds=1)
        exact_title=isinstance(title,str) and title==metadata['title']
        words=caption if isinstance(caption,str) else ''
        tokens=set(re.findall(r'[#＃]\s*(\w+)',words));core=words
        for tag in tokens:core=re.sub(r'[#＃]\s*'+re.escape(tag)+r'(?!\w)','',core)
        caption_full=not row['string_fields_truncated'] and (norm(core)==norm(metadata['description']) or norm(core)==norm(metadata['title']+metadata['description']))
        tags_match=set(metadata['hashtags'])==tokens
        row.update(new_id=id_new,creation_window_candidate=bool(time_candidate),item_title_exact=exact_title,
            full_caption_match=caption_full,required_hashtags_present=tags_match,full_metadata_match=exact_title and caption_full and tags_match)
        if not post_id:row['match_reasons'].append('missing_or_unsafe_aweme_id')
        elif not id_new:row['match_reasons'].append('excluded_old_post_id')
        if not time_candidate:row['match_reasons'].append('creation_window_not_after_submission_or_unit_unconfirmed')
        if not exact_title:row['match_reasons'].append('item_title_not_exact')
        if not caption_full:row['match_reasons'].append('full_caption_not_confirmed')
        if not tags_match:row['match_reasons'].append('required_hashtags_not_confirmed')
        output['rows'].append(row)
        if id_new and time_candidate:output['candidates'].append(dict(aweme_id=post_id,canonical_url='https://www.douyin.com/video/'+post_id,
            row_index=index,full_metadata_match=row['full_metadata_match'],creation_second_window=row['creation_second_window'],post_verified=False,numeric_duration_verified=False))
    return output


def _metadata_read_action(actor,resource,config,request,outdir,runtime):
    reference,read,once=runtime.reference,runtime._read,runtime._once
    need(isinstance(request,dict) and set(request)=={'schema','config','action','metadata_read_intent'}
         and request['schema']=='manual_republication_operator_request/v10' and request['action']==METADATA_ACTION,'request_invalid')
    need(read(request['config'])==config,'binding_changed');intent=read(request['metadata_read_intent'])
    need(intent.get('schema')=='submitted_metadata_read_intent/v1' and intent.get('authority')==config['authority']
         and intent.get('operator_authority')==config['operator_authority'] and intent.get('metadata')==config['metadata']
         and intent.get('method')=='GET' and intent.get('url')==WORK_LIST_URL and intent.get('headers')=={}
         and type(intent.get('request_limit')) is int and intent['request_limit']==1
         and all(intent.get(k) is False for k in ('request_body_allowed','navigation_allowed','new_tab_allowed','fields_written_allowed'))
         and type(intent.get('publication_actions_allowed')) is int and intent['publication_actions_allowed']==0,'request_invalid')
    folder=Path(outdir).resolve();need(folder.name=='readback' and folder.is_relative_to(ROOT/'data'),'output_changed')
    action_ref=reference(folder.parent/'ACTION_CLAIM.json');action=read(action_ref);plan=read(action['plan'])
    need(action.get('schema')=='manual_republication_metadata_action_claim/v10' and action.get('action')==METADATA_ACTION
         and action.get('config')==request['config'] and read(action['request'])==request and plan.get('config')==request['config'] and plan.get('request')==action['request']
         and all(action.get(k)==config[k] for k in ('owner_id','generation','tab_id')) and action.get('actor_thread_id')==threading.get_ident()
         and all(type(action.get(k)) is int and action[k]==0 for k in ('selections_allowed','confirmations_allowed','submissions_allowed'))
         and type(action.get('requests_allowed')) is int and action['requests_allowed']==1
         and action.get('navigation_allowed') is False and action.get('file_selection_allowed') is False
         and folder==Path(action['plan']['path']).resolve().parent/'readback','claim_changed')
    need(not (folder/'API_REQUEST_INTENT.json').exists(),'request_already_dispatched')
    metadata=read(config['metadata']);submission=read(intent['submission_claim']);prior=plan['prior']
    need(prior.get('prior_submission_claim')==intent['submission_claim'] and submission.get('metadata')==config['metadata']
         and submission.get('media')==metadata['media'] and all(submission.get(k)==config[k] for k in ('owner_id','generation','tab_id')),'claim_changed')
    submission_at=submission.get('at_epoch');need(type(submission_at) in {int,float} and math.isfinite(submission_at),'claim_changed')
    _,previous=_previous(config,reference);leaf=previous._load_base(config);reader,_=leaf._load_leaves(config);authority=read(config['authority'])
    original=resource.session;deadline=time.monotonic()+150
    refs=[action_ref,request['config'],request['metadata_read_intent'],config['metadata'],intent['submission_claim'],intent['publication_result'],intent['publication_receipt'],intent['terminal_review']]
    def guard():
        need(time.monotonic()+35<deadline,'deadline_reached')
        need(resource.session is original and original._proc is not None and original._proc.poll() is None,'session_changed')
        runtime.validate_live(actor,resource,config)
        for ref in refs:need(reference(ref['path'])==ref,'binding_changed')
        binding=resource.runtime.bindings.get(config['account_key']);profile=resource.runtime.profiles.get(config['account_key'])
        need(binding.account_uuid==profile.account_uuid==config['account_id'] and reader._binding_version(SimpleNamespace(binding=binding,profile=profile))==config['binding_version']
             and str(binding.public_uid)==authority['expected_public_uid'],'session_changed')
    guard();page=original.get_page(config['tab_id']);guard();need(page._session is original and page.tab_id==config['tab_id'],'session_changed')
    folder.mkdir(parents=True,exist_ok=True)
    marker=once(folder/'API_REQUEST_INTENT.json',dict(schema='manual_single_work_list_get/v10',action_claim=action_ref,metadata_read_intent=request['metadata_read_intent'],
        method='GET',url=WORK_LIST_URL,headers={},body_present=False,application_retry_allowed=False,request_limit=1))
    request_dispatched=False;request_ack_returned=False
    try:
        guard()
        request_dispatched=True
        response=page._cmd('api_request',method='GET',url=WORK_LIST_URL,headers={},timeout=30000)
        request_ack_returned=True
        observed_at=time.time();guard()
        projected=project_work_metadata(response.get('response') if isinstance(response,dict) else None,metadata,submission_at,observed_at,set(intent['excluded_old_post_ids']))
        projection_ref=once(folder/'WORK_METADATA_PROJECTION.json',projected)
        result=dict(schema='manual_republication_work_metadata_read/v10',action=METADATA_ACTION,status='metadata_observed' if projected['api_business_success'] else 'metadata_read_not_valid',
            action_claim=action_ref,request_intent=marker,request_count=1,request_dispatched=True,request_ack_returned=True,
            api_business_success=projected['api_business_success'],projection=projection_ref,candidates=projected['candidates'],
            observed_at=observed_at,submission_claim=intent['submission_claim'],body_sha256=projected['body_sha256'],post_verified=False,numeric_duration_verified=False,
            input_performed=False,selection_performed=False,declaration_confirmed=False,publish_clicked=False,navigation_performed=False,file_selected=False,submitted=False,fields_written=False,
            automatic_request_retry=False,raw_body_saved=False,author_uid_equated_to_public_uid=False)
        once(folder/'METADATA_READ_RESULT.json',result);return result
    except Exception as error:
        failure=once(folder/'METADATA_READ_FAILURE.json',dict(schema='manual_metadata_read_failure/v10',reason_code='controls_metadata_read_unknown',
            error_type=type(error).__name__,request_count=int(request_dispatched),request_dispatched=request_dispatched,request_ack_returned=request_ack_returned,
            request_intent=marker,automatic_request_retry=False,raw_body_saved=False,submitted=False))
        raise DeclarationControlsBlocked('controls_metadata_read_unknown',failure) from error


VERIFY_ACTION='verify_submitted_candidate'


def public_video_probe_script(post_id):
    return r"""() => {
 const loc={origin:location.origin,path:location.pathname};
 if(!['https://www.douyin.com','https://douyin.com'].includes(loc.origin)||loc.path!=='/video/'+POST)return {schema:'manual_public_video_probe/v10',...loc,canonical_matches:false,visible_video_count:0,src_read:false};
 const visible=e=>!!e&&e.isConnected&&e.getClientRects().length>0&&!e.closest('[hidden],[aria-hidden="true"],[inert]')&&(()=>{for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||['hidden','collapse'].includes(s.visibility)||Number(s.opacity)===0)return false}return true})();
 const videos=[...document.querySelectorAll('video')].filter(visible),video=videos.length===1?videos[0]:null;
 const lines=[];let node,count=0;const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
 while((node=walker.nextNode())&&count++<12000){const p=node.parentElement;if(!visible(p)||p.closest('script,style,input,textarea,[contenteditable="true"],[role="textbox"]'))continue;const text=node.nodeValue.trim();if(text&&lines.length<180)lines.push(text.slice(0,700));}
 return {schema:'manual_public_video_probe/v10',...loc,canonical_matches:true,visible_video_count:videos.length,
   duration:video&&Number.isFinite(video.duration)?video.duration:null,video_width:video?video.videoWidth:null,video_height:video?video.videoHeight:null,
   ready_state:video?video.readyState:null,player_error:video?!!video.error:null,safe_visible_body:lines,src_read:false,private_state_read:false};
 }""".replace('POST',json.dumps(post_id))


def _verify_public_action(actor,resource,config,request,outdir,runtime):
    from src.platform_adapter.browser_session import BrowserNavigationTimeout
    reference,read,once=runtime.reference,runtime._read,runtime._once
    need(isinstance(request,dict) and set(request)=={'schema','config','action','verification_intent'}
         and request['schema']=='manual_republication_operator_request/v10' and request['action']==VERIFY_ACTION,'request_invalid')
    need(read(request['config'])==config,'binding_changed');intent=read(request['verification_intent'])
    post_id=intent.get('post_id');canonical=intent.get('canonical_url')
    need(intent.get('schema')=='verify_submitted_candidate_intent/v1' and intent.get('authority')==config['authority']
         and intent.get('operator_authority')==config['operator_authority'] and intent.get('metadata')==config['metadata']
         and isinstance(post_id,str) and re.fullmatch(r'\d{10,24}',post_id)
         and post_id not in {'7709043480894524722','7708948487446056192'} and canonical=='https://www.douyin.com/video/'+post_id
         and type(intent.get('canonical_navigations_allowed')) is int and intent['canonical_navigations_allowed']==1
         and all(type(intent.get(k)) is int and intent[k]==0 for k in ('new_tabs_allowed','publications_allowed','selections_allowed','confirmations_allowed','files_allowed'))
         and intent.get('fields_written_allowed') is False and intent.get('reuse_existing_strict_published_work_reader') is True
         and intent.get('required_ai_label')==KNOWN_LABELS[0] and intent.get('require_fiction_notice') is True,'request_invalid')
    folder=Path(outdir).resolve();need(folder.name=='verification' and folder.is_relative_to(ROOT/'data'),'output_changed')
    action_ref=reference(folder.parent/'ACTION_CLAIM.json');action=read(action_ref);plan=read(action['plan'])
    need(action.get('schema')=='manual_republication_verify_action_claim/v10' and action.get('action')==VERIFY_ACTION
         and action.get('config')==request['config'] and read(action['request'])==request and plan.get('config')==request['config'] and plan.get('request')==action['request']
         and all(action.get(k)==config[k] for k in ('owner_id','generation','tab_id')) and action.get('actor_thread_id')==threading.get_ident()
         and all(type(action.get(k)) is int and action[k]==0 for k in ('requests_allowed','selections_allowed','confirmations_allowed','submissions_allowed'))
         and action.get('navigation_allowed') is True and type(action.get('canonical_navigations_allowed')) is int and action['canonical_navigations_allowed']==1
         and action.get('file_selection_allowed') is False and folder==Path(action['plan']['path']).resolve().parent/'verification','claim_changed')
    need(not (folder/'CANONICAL_NAVIGATION_INTENT.json').exists(),'request_already_dispatched')
    metadata=read(config['metadata']);authority=read(config['authority']);candidate=read(intent['candidate']);submission=read(intent['submission_claim']);prior=plan['prior']
    need(candidate.get('candidate',{}).get('aweme_id')==post_id and candidate['candidate'].get('canonical_url')==canonical
         and candidate.get('submission_claim')==intent['submission_claim'] and submission.get('metadata')==config['metadata']
         and submission.get('media')==metadata['media'] and all(submission.get(k)==config[k] for k in ('owner_id','generation','tab_id')),'claim_changed')
    expected=intent.get('expected_duration_seconds');tolerance=intent.get('duration_tolerance_seconds')
    need(type(expected) in {int,float} and math.isfinite(expected) and expected>0
         and abs(expected-prior['source_duration_seconds'])<1e-6 and type(tolerance) in {int,float} and 0<=tolerance<=.5,'request_invalid')
    _,previous=_previous(config,reference);leaf=previous._load_base(config);reader,_=leaf._load_leaves(config)
    original=resource.session;deadline=time.monotonic()+150
    refs=[action_ref,request['config'],request['verification_intent'],config['metadata'],intent['candidate'],intent['submission_claim'],intent['metadata_result'],intent['metadata_receipt']]
    def guard(check_budget=True):
        if check_budget:need(time.monotonic()+35<deadline,'deadline_reached')
        need(resource.session is original and original._proc is not None and original._proc.poll() is None,'session_changed')
        runtime.validate_live(actor,resource,config)
        for ref in refs:need(reference(ref['path'])==ref,'binding_changed')
        b=resource.runtime.bindings.get(config['account_key']);p=resource.runtime.profiles.get(config['account_key'])
        need(b.account_uuid==p.account_uuid==config['account_id'] and reader._binding_version(SimpleNamespace(binding=b,profile=p))==config['binding_version']
             and str(b.public_uid)==authority['expected_public_uid'],'session_changed')
    guard();raw=original.get_page(config['tab_id']);guard();need(raw._session is original and raw.tab_id==config['tab_id'],'session_changed')
    folder.mkdir(parents=True,exist_ok=True);trace=folder/'RPC_TRACE.jsonl'
    with trace.open('xb'):pass
    navigated=False;native_reads=0
    def record(value):
        with trace.open('a',encoding='utf8') as stream:stream.write(json.dumps(dict(at_epoch=time.time(),**value),ensure_ascii=False)+'\n');stream.flush();os.fsync(stream.fileno())
    class Gate:
        def cmd(self,kind,**kw):
            nonlocal navigated,native_reads
            need(kw.pop('tab_id',raw.tab_id)==raw.tab_id,'session_changed');guard()
            if kind=='goto':
                need(not navigated and kw.get('url')==canonical and kw.get('wait_until')=='commit' and kw.get('timeout')==30000,'rpc_not_allowed');navigated=True
            elif kind=='inspect_published_video':
                need(navigated and native_reads<6 and kw.get('post_id')==post_id and kw.get('ai_required') is True and kw.get('fiction_required') is True
                     and kw.get('required_hashtags')==metadata['hashtags'] and kw.get('expected_title')==metadata['title'] and kw.get('evidence_path') is None,'rpc_not_allowed');native_reads+=1
            elif kind=='screenshot':need(Path(kw.get('path','')).resolve()==folder/'PUBLIC_WORK.png' and not Path(kw['path']).exists(),'rpc_not_allowed')
            else:need(kind in {'evaluate','wait_for_timeout'},'rpc_not_allowed')
            record(dict(event='rpc_dispatched',action=kind))
            try:value=original.cmd(kind,tab_id=raw.tab_id,**kw)
            except Exception as error:record(dict(event='rpc_error',action=kind,error_type=type(error).__name__));raise
            guard(False);record(dict(event='rpc_returned',action=kind));return value
    page=leaf.Page(Gate(),raw.tab_id);observations=[];latest={'verified':False,'reason':'native_reader_not_observed'};video={'visible_video_count':0};numeric=False
    try:
        once(folder/'CANONICAL_NAVIGATION_INTENT.json',dict(schema='manual_exact_candidate_navigation/v10',action_claim=action_ref,
            verification_intent=request['verification_intent'],canonical_url=canonical,allowed_navigations=1,allowed_new_tabs=0))
        navigation_timeout=None
        try:page.goto(canonical,wait_until='commit',timeout=30000)
        except BrowserNavigationTimeout as error:
            evidence=error.navigation_evidence
            navigation_timeout={k:evidence.get(k) for k in ('navigation_committed','target_matched','ready_state','wait_until','timeout_ms','elapsed_ms')}
            once(folder/'NAVIGATION_TIMEOUT.json',navigation_timeout)
        for attempt in range(6):
            if time.monotonic()+40>=deadline:break
            latest=page.inspect_published_video(post_id,ai_required=True,fiction_required=True,required_hashtags=metadata['hashtags'],expected_title=metadata['title'])
            video=page.evaluate(public_video_probe_script(post_id));duration=video.get('duration')
            numeric=(video.get('canonical_matches') is True and video.get('origin') in {'https://www.douyin.com','https://douyin.com'}
                and video.get('path')=='/video/'+post_id and video.get('visible_video_count')==1 and type(duration) in {int,float} and math.isfinite(duration)
                and abs(duration-expected)<=tolerance and type(video.get('ready_state')) is int and video['ready_state']>=2 and video.get('player_error') is False
                and type(video.get('video_width')) is int and video['video_width']>0 and type(video.get('video_height')) is int and video['video_height']>0)
            observed=dict(attempt=attempt+1,published_evidence=latest,video_probe=video,numeric_duration_matches=numeric);observations.append(observed)
            evidence_url=urlsplit(latest.get('url',''))
            correct_url=evidence_url.scheme=='https' and evidence_url.hostname in {'www.douyin.com','douyin.com'} and evidence_url.path=='/video/'+post_id
            if latest.get('verified') is True and latest.get('expected_post_id')==post_id and correct_url and numeric:break
            if video.get('canonical_matches') is not True or latest.get('human_required') is True or latest.get('review_status')=='not_clear' or latest.get('moderation_markers'):break
            if attempt<5 and time.monotonic()+40<deadline:page.wait_for_timeout(600)
        observations_ref=once(folder/'PUBLIC_VERIFICATION_OBSERVATIONS.json',dict(observations=observations,navigation_timeout=navigation_timeout))
        evidence_ref=once(folder/'PUBLISHED_WORK_EVIDENCE.json',latest);video_ref=once(folder/'PUBLIC_VIDEO_PROBE.json',video)
        actual=urlsplit(latest.get('url',''));passed=bool(latest.get('verified') is True and latest.get('expected_post_id')==post_id
            and actual.scheme=='https' and actual.hostname in {'www.douyin.com','douyin.com'} and actual.path=='/video/'+post_id and numeric)
        try:
            if time.monotonic()+35>=deadline:raise DeclarationControlsBlocked('controls_deadline_reached')
            image=folder/'PUBLIC_WORK.png';page._cmd('screenshot',path=str(image),full_page=False);shot=dict(status='saved',file=reference(image))
        except Exception as error:shot=dict(status='unavailable',error_type=type(error).__name__)
        guard(False)
        result=dict(schema='manual_republication_public_verification/v10',action=VERIFY_ACTION,status='public_work_verified' if passed else 'public_verification_pending',
            action_claim=action_ref,verification_intent=request['verification_intent'],post_id=post_id,canonical_url=canonical,published_evidence=evidence_ref,video_probe=video_ref,
            observations=observations_ref,screenshot=shot,post_verified=passed,numeric_duration_verified=numeric,native_read_count=native_reads,
            canonical_navigations_count=int(navigated),api_request_count=0,input_performed=False,selection_performed=False,declaration_confirmed=False,
            publish_clicked=False,navigation_performed=navigated,file_selected=False,submitted=False,fields_written=False,rpc_trace=reference(trace),
            public_author_uid_inferred_from_author_id=False,full_audio_visual_quality_verified=False)
        once(folder/'PUBLIC_VERIFICATION_RESULT.json',result);return result
    except Exception as error:
        failure=once(folder/'PUBLIC_VERIFICATION_FAILURE.json',dict(schema='manual_public_verification_failure/v10',reason_code='controls_public_verify_unknown',error_type=type(error).__name__,
            canonical_navigation_dispatched=navigated,native_read_count=native_reads,observations=observations,rpc_trace=reference(trace),
            post_verified=False,numeric_duration_verified=False,submitted=False,automatic_navigation_retry=False))
        raise DeclarationControlsBlocked('controls_public_verify_unknown',failure) from error


CAPTION_ACTION='inspect_current_public_caption'


def _caption_read_action(actor,resource,config,request,outdir,runtime):
    reference,read,once=runtime.reference,runtime._read,runtime._once
    need(isinstance(request,dict) and set(request)=={'schema','config','action','caption_read_intent'}
         and request['schema']=='manual_republication_operator_request/v10' and request['action']==CAPTION_ACTION,'request_invalid')
    need(read(request['config'])==config,'binding_changed');intent=read(request['caption_read_intent'])
    post_id=intent.get('post_id');canonical=intent.get('canonical_url')
    need(intent.get('schema')=='current_public_caption_read_intent/v1' and intent.get('draft_only') is False
         and intent.get('authority')==config['authority'] and intent.get('operator_authority')==config['operator_authority'] and intent.get('metadata')==config['metadata']
         and isinstance(post_id,str) and re.fullmatch(r'\d{10,24}',post_id) and post_id not in {'7709043480894524722','7708948487446056192'}
         and canonical=='https://www.douyin.com/video/'+post_id
         and type(intent.get('scoped_reads_allowed')) is int and intent['scoped_reads_allowed']==1
         and type(intent.get('screenshots_allowed')) is int and intent['screenshots_allowed']==1
         and all(type(intent.get(k)) is int and intent[k]==0 for k in ('navigations_allowed','api_requests_allowed','new_tabs_allowed','publications_allowed','selections_allowed','confirmations_allowed','files_allowed'))
         and intent.get('fields_written_allowed') is False,'request_invalid')
    folder=Path(outdir).resolve();need(folder.name=='caption' and folder.is_relative_to(ROOT/'data'),'output_changed')
    action_ref=reference(folder.parent/'ACTION_CLAIM.json');action=read(action_ref);plan=read(action['plan'])
    need(action.get('schema')=='manual_republication_caption_action_claim/v10' and action.get('action')==CAPTION_ACTION
         and action.get('config')==request['config'] and read(action['request'])==request and plan.get('config')==request['config'] and plan.get('request')==action['request']
         and all(action.get(k)==config[k] for k in ('owner_id','generation','tab_id')) and action.get('actor_thread_id')==threading.get_ident()
         and all(type(action.get(k)) is int and action[k]==0 for k in ('canonical_navigations_allowed','requests_allowed','selections_allowed','confirmations_allowed','submissions_allowed'))
         and action.get('navigation_allowed') is False and action.get('file_selection_allowed') is False
         and folder==Path(action['plan']['path']).resolve().parent/'caption','claim_changed')
    metadata=read(config['metadata']);authority=read(config['authority']);candidate=read(intent['candidate']);submission=read(intent['submission_claim'])
    need(candidate.get('candidate',{}).get('aweme_id')==post_id and candidate['candidate'].get('canonical_url')==canonical
         and candidate.get('submission_claim')==intent['submission_claim'] and submission.get('metadata')==config['metadata']
         and submission.get('media')==metadata['media'] and all(submission.get(k)==config[k] for k in ('owner_id','generation','tab_id')),'claim_changed')
    helper_path=ROOT/'src/shared/published_work_metadata_scope_v1.py'
    need(Path(intent['helper_ref']['path']).resolve()==helper_path and reference(helper_path)==intent['helper_ref'],'binding_changed')
    helper=types.ModuleType('src.shared._metadata_scope_'+intent['helper_ref']['sha256'][:20]);helper.__file__,helper.__package__=str(helper_path),'src.shared'
    helper_bytes=helper_path.read_bytes();need(hashlib.sha256(helper_bytes).hexdigest()==intent['helper_ref']['sha256'],'binding_changed')
    exec(compile(helper_bytes,str(helper_path),'exec'),helper.__dict__)
    expected=intent.get('expected_duration_seconds');tolerance=intent.get('duration_tolerance_seconds')
    need(type(expected) in {int,float} and math.isfinite(expected) and abs(expected-plan['prior']['source_duration_seconds'])<1e-6
         and type(tolerance) in {int,float} and math.isfinite(tolerance) and 0<=tolerance<=.5,'request_invalid')
    helper_kwargs=dict(base_scope_source=intent['base_scope_source'],base_scope_snapshot=intent['base_scope_snapshot'])
    script=helper.build_metadata_scope_script(post_id,metadata,**helper_kwargs)
    _,previous=_previous(config,reference);leaf=previous._load_base(config);reader,_=leaf._load_leaves(config)
    original=resource.session;deadline=time.monotonic()+150
    refs=[action_ref,request['config'],request['caption_read_intent'],config['metadata'],*[intent[k] for k in (
        'candidate','submission_claim','legacy_verification_result','legacy_verification_receipt','public_player_observed','legacy_scope_evidence','terminal_review','helper_ref','base_scope_source','base_scope_snapshot')]]
    def guard(check_budget=True):
        if check_budget:need(time.monotonic()+25<deadline,'deadline_reached')
        need(resource.session is original and original._proc is not None and original._proc.poll() is None,'session_changed')
        runtime.validate_live(actor,resource,config)
        for ref in refs:need(reference(ref['path'])==ref,'binding_changed')
        b=resource.runtime.bindings.get(config['account_key']);p=resource.runtime.profiles.get(config['account_key'])
        need(b.account_uuid==p.account_uuid==config['account_id'] and reader._binding_version(SimpleNamespace(binding=b,profile=p))==config['binding_version']
             and str(b.public_uid)==authority['expected_public_uid'],'session_changed')
    guard();raw=original.get_page(config['tab_id']);guard();need(raw._session is original and raw.tab_id==config['tab_id'],'session_changed')
    folder.mkdir(parents=True,exist_ok=True);trace=folder/'RPC_TRACE.jsonl'
    with trace.open('xb'):pass
    reads=0
    def record(value):
        with trace.open('a',encoding='utf8') as stream:stream.write(json.dumps(dict(at_epoch=time.time(),**value),ensure_ascii=False)+'\n');stream.flush();os.fsync(stream.fileno())
    class Gate:
        def cmd(self,kind,**kw):
            nonlocal reads
            need(kw.pop('tab_id',raw.tab_id)==raw.tab_id,'session_changed');guard()
            if kind=='evaluate':need(reads==0 and kw.get('js')==script,'rpc_not_allowed');reads+=1
            elif kind=='screenshot':need(Path(kw.get('path','')).resolve()==folder/'CURRENT_PUBLIC_WORK.png' and not Path(kw['path']).exists(),'rpc_not_allowed')
            else:raise DeclarationControlsBlocked('controls_rpc_not_allowed')
            record(dict(event='rpc_dispatched',action=kind))
            try:value=original.cmd(kind,tab_id=raw.tab_id,**kw)
            except Exception as error:record(dict(event='rpc_error',action=kind,error_type=type(error).__name__));raise
            guard(False);record(dict(event='rpc_returned',action=kind));return value
    page=leaf.Page(Gate(),raw.tab_id)
    try:
        evidence=helper.inspect_current_metadata_scope(page,post_id,metadata,**helper_kwargs,expected_duration_seconds=expected,duration_tolerance_seconds=tolerance)
        evidence_ref=once(folder/'SCOPED_FULL_METADATA_EVIDENCE.json',evidence)
        player=evidence.get('player',{});numeric=evidence.get('numeric_duration_verified') is True
        video=dict(schema='manual_public_scoped_video_probe/v10',origin=evidence.get('origin'),path=evidence.get('path'),
            canonical_matches=evidence.get('url')==canonical,visible_video_count=player.get('visible_video_count'),duration=player.get('numeric_duration'),
            video_width=player.get('video_width'),video_height=player.get('video_height'),ready_state=player.get('ready_state'),player_error=player.get('error'),
            scope_kind=evidence.get('scope_kind'),scope_structure_verified=evidence.get('structure_verified'),src_read=False,private_state_read=False)
        video_ref=once(folder/'SCOPED_PUBLIC_VIDEO_PROBE.json',video)
        passed=bool(evidence.get('verified') is True and evidence.get('expected_post_id')==post_id and evidence.get('url')==canonical and numeric)
        try:
            image=folder/'CURRENT_PUBLIC_WORK.png';page._cmd('screenshot',path=str(image),full_page=False);shot=dict(status='saved',file=reference(image))
        except Exception as error:shot=dict(status='unavailable',error_type=type(error).__name__)
        guard(False)
        result=dict(schema='manual_republication_public_caption/v10',action=CAPTION_ACTION,status='public_work_verified' if passed else 'public_caption_not_verified',
            action_claim=action_ref,caption_read_intent=request['caption_read_intent'],post_id=post_id,canonical_url=canonical,published_evidence=evidence_ref,video_probe=video_ref,
            screenshot=shot,post_verified=passed,numeric_duration_verified=numeric,scoped_read_count=reads,canonical_navigations_count=0,api_request_count=0,
            input_performed=False,selection_performed=False,declaration_confirmed=False,publish_clicked=False,navigation_performed=False,file_selected=False,submitted=False,fields_written=False,
            rpc_trace=reference(trace),loaded_helper=intent['helper_ref'],public_author_uid_inferred_from_author_id=False,full_audio_visual_quality_verified=False)
        once(folder/'PUBLIC_CAPTION_RESULT.json',result);return result
    except Exception as error:
        failure=once(folder/'PUBLIC_CAPTION_FAILURE.json',dict(schema='manual_public_caption_failure/v10',reason_code='controls_caption_read_unknown',error_type=type(error).__name__,
            scoped_read_count=reads,rpc_trace=reference(trace),post_verified=False,submitted=False,navigation_performed=False,api_request_count=0))
        raise DeclarationControlsBlocked('controls_caption_read_unknown',failure) from error
