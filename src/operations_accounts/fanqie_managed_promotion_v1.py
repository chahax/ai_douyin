"""Promotion reads/applications on a caller-owned, identity-fenced Fanqie tab.

This module never creates a browser. Missing platform IDs remain pending;
submission is one exact intent, never the legacy first-book/alias retry path.
"""
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

from .browser_control import BrowserCommandResult, BrowserControlRejected
from src.platform_adapter.fanqie_fill_status_v1 import FILL_DETAIL_JS, normalize_row as normalize_fill_status

ROOT=Path(__file__).resolve().parents[2]
LIST_URL='https://kol.fanqieopen.com/page/promotion-list?tab_type=2&top_tab_genre=-1'
CONTENT_URL='https://kol.fanqieopen.com/page/content?tab_type=2&top_tab_genre=-1'
PROMOTION_ENTRY_LABEL='别名推广'
FIELDS=('platform_task_id','book_id','book_name','alias_id','alias','promotion_path','publish_type',
        'alias_status','book_status','valid_from','valid_until','published_links','fill_status')
REQUIRED=('platform_task_id','book_id','book_name','alias_id','alias','promotion_path','publish_type',
          'alias_status','book_status','valid_from','valid_until')

# Same observed Arco table/header and book hooks as FanqiePromotionService.
# Stable IDs are only explicit attributes, named columns or URL parameters.
LIST_JS='() => { const fillDetail='+FILL_DETAIL_JS+r""";
 const text=e=>(e?.innerText||e?.textContent||'').trim().replace(/\s+/g,' ');
 const visible=e=>!!e&&e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden';
 const header=document.querySelector('thead .arco-table-tr,thead tr');
 const headers=header?Array.from(header.querySelectorAll('th,.arco-table-th')).map(text):[];
 const map={'关键词':'alias','书本信息':'book','发文类型':'publish_type','别名状态':'alias_status',
 '书籍状态':'book_status','发文详情':'fill_status','推广路径':'promotion_path','有效期':'valid_range',
 '推广任务ID':'platform_task_id','任务ID':'platform_task_id','别名ID':'alias_id','生效时间':'valid_from','失效时间':'valid_until'};
 const required=['关键词','书本信息','发文类型','别名状态','书籍状态','发文详情'];
 const rows=Array.from(document.querySelectorAll('tbody .arco-table-tr,tbody tr')).map(row=>{
  const item={published_links:[],identity_attributes:[],identity_links:[],identity_columns:[]};
  Array.from(row.querySelectorAll('.arco-table-td,td')).forEach((cell,i)=>{
   const key=map[headers[i]];if(!key)return;
   if(key==='book'){
    item.book_name=text(cell.querySelector('.book-name-iHil3A,[class*="book-name"]'));
    const m=text(cell).match(/\bid\s*[:：]\s*(\d{10,24})/i);item.book_id=m?m[1]:null;
   }else if(key==='fill_status'){
    item.fill_status_evidence=fillDetail(cell);
    item.fill_status=item.fill_status_evidence.canonical_status||(
      item.fill_status_evidence.raw_visible_text==='未填写'?'未确认':item.fill_status_evidence.raw_visible_text);
   }else item[key]=text(cell);
   if(['任务ID','推广任务ID','别名ID','推广路径'].includes(headers[i]))item.identity_columns.push({header:headers[i],value:text(cell)});
  });
  const attr={platform_task_id:'data-task-id',book_id:'data-book-id',alias_id:'data-alias-id',promotion_path:'data-promotion-path',valid_from:'data-valid-from',valid_until:'data-valid-until'};
  for(const [k,a] of Object.entries(attr))if(row.hasAttribute(a))item[k]=row.getAttribute(a);
  const attrs=['data-alias-id','data-promotion-alias-id','data-platform-task-id','data-promotion-task-id','data-task-id','data-promotion-path'];
  for(const node of [row,...row.querySelectorAll(attrs.map(x=>'['+x+']').join(','))])for(const name of attrs)if(node.hasAttribute(name))item.identity_attributes.push({name,value:node.getAttribute(name)});
  for(const a of row.querySelectorAll('a[href]')){
   item.identity_links.push(a.href);
   let u;try{u=new URL(a.href,location.href)}catch{continue}
   if(u.origin===location.origin){for(const [k,names] of Object.entries({platform_task_id:['promotion_task_id','task_id'],book_id:['book_id'],alias_id:['alias_id']})){
    const values=names.map(n=>u.searchParams.get(n)).filter(Boolean);if(new Set(values).size===1&&!item[k])item[k]=values[0];
   }}
   if(u.protocol==='https:'&&['www.douyin.com','douyin.com','v.douyin.com'].includes(u.hostname))item.published_links.push(u.href);
  }
  return item;
 }).filter(x=>x.alias||x.book_name||x.book_id);
 const next=Array.from(document.querySelectorAll('.arco-pagination-item-next,[aria-label="下一页"]')).filter(visible);
 const disabled=e=>e.matches(':disabled,[aria-disabled="true"]')||/disabled/.test(e.className);
 return {items:rows,all_headers:headers,table_ready:!!header&&required.every(x=>headers.includes(x)),
 loading:Array.from(document.querySelectorAll('.arco-spin-loading,.arco-spin-loading-layer,[aria-busy="true"]')).some(visible),
 empty_state:Array.from(document.querySelectorAll('.arco-empty,.arco-table-empty')).some(visible),
 pagination_ambiguous:next.length>1,has_next:next.length===1&&!disabled(next[0])};
}"""
NEXT_JS=r"""() => {const xs=Array.from(document.querySelectorAll('.arco-pagination-item-next,[aria-label="下一页"]')).filter(e=>e.getClientRects().length&&!e.matches(':disabled,[aria-disabled="true"]')&&!/disabled/.test(e.className));if(xs.length!==1)return {clicked:false};xs[0].click();return {clicked:true};}"""


def reject(code,message):raise BrowserControlRejected(code,message)


def _bind(path):
    path=Path(path).resolve()
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def _read(binding):
    if not isinstance(binding,dict) or set(binding)!={'path','sha256'}:reject('promotion_binding_invalid','需要固定文件证据')
    path=Path(binding['path'])
    if not path.is_absolute() or not path.resolve().is_relative_to(ROOT) or _bind(path)!=binding:
        reject('promotion_binding_changed','推广请求或授权证据已变化')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _freeze(path,value):
    from .fanqie_account_control import write_json
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8'))!=value:reject('promotion_evidence_changed','原推广证据不可覆盖')
        return _bind(path)
    return write_json(path,value)


def normalise_snapshot(raw,*,resource_id,binding_version,platform_identity_key,observed_at=None,
                       environment_key=None,identity_verified=False,challenge=None,evidence_ref=None,
                       normalizer_version='v1.1'):
    if normalizer_version not in ('legacy_v1','v1.1'):
        reject('promotion_normalizer_version_unsupported','该推广快照解析版本暂不支持')
    from src.platform_adapter.fanqie_backfill import normalize_promotion_rows
    raw=normalize_promotion_rows(raw,now=observed_at)
    rows=[]
    for source in raw.get('items',[]):
        if not isinstance(source,dict):continue
        row={key:source.get(key) for key in FIELDS}
        row['fill_status'], fill_evidence = normalize_fill_status(source)
        if fill_evidence is not None:row['fill_status_evidence']=fill_evidence
        if not row['valid_from'] or not row['valid_until']:
            separator=r'(?:~|至|—)' if normalizer_version=='legacy_v1' else r'(?:~|～|至|—)'
            dates=re.fullmatch(r'\s*(\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2})?)\s*'+separator+r'\s*(\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2})?)\s*',source.get('valid_range') or '')
            if dates:row['valid_from'],row['valid_until']=dates.groups()
        row['published_links']=list(dict.fromkeys(x for x in (source.get('published_links') or []) if isinstance(x,str)))
        row['source_raw_valid_range']=source.get('valid_range')
        row['stable_identity_evidence']=source.get('stable_identity_evidence',{})
        row['stable_identity_status']=source.get('stable_identity_status','needs_sync')
        row['missing_identity_fields']=source.get('missing_identity_fields',[])
        row['conflicting_identity_fields']=source.get('conflicting_identity_fields',[])
        row['pending_fields']=[key for key in REQUIRED if not isinstance(row[key],str) or not row[key].strip()]
        row['pending_fields']+=source.get('conflicting_identity_fields',[])
        row['status']='pending' if row['pending_fields'] else 'ready'
        rows.append(row)
    result=dict(schema='fanqie_promotion_snapshot/v1',resource_id=resource_id,binding_version=binding_version,
        platform_identity_key=platform_identity_key,environment_key=environment_key,
        observed_at=time.time() if observed_at is None else observed_at,identity_verified=identity_verified,
        challenge=challenge,table_ready=bool(raw.get('table_ready') and not raw.get('loading')),
        pagination_complete=raw.get('pagination_complete') is True,evidence_ref=evidence_ref,rows=rows)
    if normalizer_version!='legacy_v1':result['normalizer_version']=normalizer_version
    return result


def validate_snapshot(value):
    if value.get('schema')!='fanqie_promotion_snapshot/v1' or not isinstance(value.get('rows'),list):
        reject('promotion_snapshot_invalid','推广快照格式错误')
    for row in value['rows']:
        if not isinstance(row,dict) or any(k not in row for k in FIELDS):
            reject('promotion_snapshot_invalid','推广行缺少标准字段')
    evidence=_read(value.get('evidence_ref'))
    version=value.get('normalizer_version','legacy_v1')
    if version not in ('legacy_v1','v1.1'):reject('promotion_normalizer_version_unsupported','该推广快照解析版本暂不支持')
    if evidence.get('normalizer_version','legacy_v1')!=version:
        reject('promotion_normalizer_version_mismatch','推广快照与原观察版本不一致')
    subject=evidence.get('subject') or {}
    if evidence.get('schema')!='fanqie_promotion_DOM_evidence/v1' or any(value.get(k)!=v for k,v in subject.items()) or set(subject)!={
            'resource_id','binding_version','environment_key','platform_identity_key','observed_at','identity_verified','challenge'}:
        reject('promotion_snapshot_subject_changed','推广快照脱离原账号观察证据')
    rebuilt=normalise_snapshot(evidence['raw'],**subject,evidence_ref=value['evidence_ref'],normalizer_version=version)
    if rebuilt!=value:reject('promotion_snapshot_rows_changed','推广快照与原DOM证据不一致')
    return value


def capture(page,guard,*,resource_id,binding_version,identity,evidence_path):
    pages=[];all_items=[];complete=False;last_page=None
    for number in range(20):
        previous=None;stable=0;raw={};settled=False
        for poll in range(12):
            guard();raw=page.evaluate(LIST_JS) or {}
            signature=json.dumps(raw,sort_keys=True,ensure_ascii=False)
            stable=stable+1 if signature==previous else 1;previous=signature
            current=json.dumps(raw.get('items') or [],sort_keys=True,ensure_ascii=False)
            if (raw.get('table_ready') and not raw.get('loading') and stable>=2 and current!=last_page
                    and (raw.get('items') or raw.get('empty_state'))):settled=True;break
            page.wait_for_timeout(250)
        if not settled:
            raw=dict(raw,table_ready=False);pages.append(raw);break
        if last_page is not None and json.dumps(raw.get('items') or [],sort_keys=True,ensure_ascii=False)==last_page:break
        pages.append(raw);all_items.extend(raw.get('items') or [])
        last_page=json.dumps(raw.get('items') or [],sort_keys=True,ensure_ascii=False)
        if not raw.get('table_ready') or raw.get('loading') or raw.get('pagination_ambiguous'):break
        if not raw.get('has_next'):complete=True;break
        guard()
        if not page.evaluate(NEXT_JS).get('clicked'):break
        page.wait_for_timeout(250)
    raw=dict(items=all_items,table_ready=all(p.get('table_ready') for p in pages),
             loading=any(p.get('loading') for p in pages),pagination_complete=complete,pages=pages)
    guard();probe=identity()
    subject=dict(resource_id=resource_id,binding_version=binding_version,
        platform_identity_key=probe['platform_identity_key'],environment_key=probe['environment_key'],
        identity_verified=probe.get('verified') is True,challenge=probe.get('challenge'),observed_at=time.time())
    evidence=_freeze(evidence_path,dict(schema='fanqie_promotion_DOM_evidence/v1',normalizer_version='v1.1',raw=raw,subject=subject,identity_probe=probe))
    from src.platform_adapter.fanqie_promotion_observer_v1 import discover_resources
    try:inventory=discover_resources(page)
    except (AttributeError,ValueError) as error:
        if str(error)=='promotion_observer_requires_same_promotion_list_page':
            reject('promotion_resource_page_changed','推广资源诊断仅允许当前推广列表页')
        inventory=dict(schema='fanqie_promotion_resource_inventory/v1',status='unavailable',resources=[],
            reason='native_performance_api_unavailable',native_requests_issued=0,query_values_saved=False)
    inventory['managed_subject']=subject
    name='RESOURCE_PATHS.json' if evidence_path.stem=='LIST_BEFORE_RAW' else 'RESOURCE_PATHS_AFTER.json'
    _freeze(evidence_path.parent/name,inventory)
    return normalise_snapshot(raw,resource_id=resource_id,binding_version=binding_version,
        platform_identity_key=probe['platform_identity_key'],environment_key=probe['environment_key'],
        identity_verified=probe.get('verified') is True,challenge=probe.get('challenge'),
        observed_at=subject['observed_at'],evidence_ref=evidence)


INTENT_FIELDS=('resource_id','binding_version','platform_identity_key','book_id','book_name','alias','promotion_path','publish_type')


def application_request(binding,env,identity):
    request=_read(binding)
    if set(request)!={'schema','authorization',*INTENT_FIELDS} or request['schema']!='fanqie_promotion_apply_request/v1':
        reject('promotion_request_invalid','申请必须为完整固定推广意图')
    intent={k:request[k] for k in INTENT_FIELDS}
    if (any(not isinstance(v,str) or not v.strip() or v!=v.strip() or len(v)>200 for v in intent.values())
            or intent['publish_type']!='AIGC' or intent['resource_id']!=env['resource_id']
            or intent['binding_version']!=env['binding_version']
            or intent['platform_identity_key']!=identity['platform_identity_key']):
        reject('promotion_request_mismatch','书籍、别名、路径、AIGC及绑定身份必须明确一致')
    auth=_read(request['authorization'])
    if (auth.get('schema')!='fanqie_promotion_apply_authorization/v1' or auth.get('confirmed_by')!='user'
            or auth.get('intent')!=intent or type(auth.get('max_submissions')) is not int or auth['max_submissions']!=1):
        reject('promotion_authorization_invalid','需要针对这一完整申请意图的明确授权')
    return request


def _form_js(intent,submit=False,entry_evidence=None):
    # Every selection is unique and exact. No fallback book, recommended alias,
    # alternate path/type, click retry or request injection is accepted.
    from src.platform_adapter.fanqie_form_feedback_v1 import PUBLIC_FORM_HELPERS_JS
    return 'async () => { const want='+json.dumps(intent,ensure_ascii=False)+';const entry='+json.dumps(entry_evidence or {},ensure_ascii=False)+';const submissionMode='+json.dumps(submit)+';'+PUBLIC_FORM_HELPERS_JS+r"""
 const text=e=>(e?.innerText||e?.textContent||'').trim();
 const visible=e=>!!e&&e.isConnected&&e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const sleep=ms=>new Promise(r=>setTimeout(r,ms)), observations=[];
 let latest=null;
 const formFeedback={schema:'fanqie_application_form_feedback/v1',mode:submissionMode?'submit':'prepare',
  baseline:null,after_fill:null,pre_click:null,post_click:[],observations:[],latest:null,clicked:false,
  click_count:0,post_click_field_writes:0};
 let clearedAfterFill=false;
 const entryPathConfirmed=entry.clicked===true&&entry.book_name===want.book_name&&entry.entry_label===want.promotion_path;
 // Resolve the current DOM on every observation. React may replace any of
 // these nodes after input or option events; old references prove no state.
 function read(){
  const modals=Array.from(document.querySelectorAll('.arco-modal-content')).filter(visible);
  const modal=modals.length===1?modals[0]:null;
  const content=modal?text(modal):'',exactBook=want.book_name+'（'+want.book_id+'）';
  const ids=Array.from(content.matchAll(/[（(]([0-9]{10,24})[）)]/g),m=>m[1]).slice(0,10);
  const lines=content.split(/\r?\n/).map(t=>t.trim()).filter(Boolean);
  const inputs=modal?Array.from(modal.querySelectorAll('.alias-input-EBp1Sw')).filter(visible):[];
  const fields=modal?Array.from(modal.querySelectorAll('.arco-form-item')).filter(visible):[];
  const field=label=>fields.filter(e=>text(e.querySelector('.arco-form-item-label'))===label);
  const paths=field('推广路径'),types=field('发文类型');
  const inside=rows=>rows.length===1?Array.from(rows[0].querySelectorAll('.arco-select')).filter(visible):[];
  const pathControls=inside(paths),all=modal?Array.from(modal.querySelectorAll('.arco-select')).filter(visible):[];
  const typeControls=types.length===0&&all.length===1?all:inside(types);
  const input=inputs.length===1?inputs[0]:null,path=pathControls.length===1?pathControls[0]:null,type=typeControls.length===1?typeControls[0]:null;
  const sameBook=ids.length===1&&ids[0]===want.book_id&&lines.filter(t=>t===exactBook).length===1;
  const observed={modal_count:modals.length,observed_book_ids:ids,
   book_identity_verified:sameBook,
   alias_input_count:inputs.length,alias_value:sameBook&&input&&typeof input.value==='string'?input.value.slice(0,200):null,
   alias_disabled:!!input&&!!input.disabled,alias_read_only:!!input&&!!input.readOnly,
   alias_attached:!!input&&input.isConnected,promotion_path_field_count:paths.length,
   promotion_path_control_count:pathControls.length,promotion_path_text:path?text(path).slice(0,200):null,
   promotion_path_attached:!!path&&path.isConnected,publish_type_field_count:types.length,
   publish_type_control_count:typeControls.length,publish_type_text:type?text(type).slice(0,200):null,
   publish_type_attached:!!type&&type.isConnected,entry_path_confirmed:entryPathConfirmed};
  let reason=modals.length!==1?'unique_modal_required':!observed.book_identity_verified?'modal_exact_book_unconfirmed':
   (!input||!type||paths.length>1||types.length>1||(!path&&(paths.length!==0||!entryPathConfirmed)))?'explicit_label_controls_missing':null;
  const mismatch=[];
  if(observed.alias_value!==want.alias)mismatch.push('alias');
  if(path?observed.promotion_path_text!==want.promotion_path:!entryPathConfirmed)mismatch.push('promotion_path');
  if(observed.publish_type_text!==want.publish_type)mismatch.push('publish_type');
  return {modal,input,path,type,observed,reason,mismatch};
 }
 function feedbackRecord(current,phase){
  const stage=phase.startsWith('post_click')?'post_click':phase==='initial'?(submissionMode?'pre_click':'baseline'):
   phase==='final_fresh'||phase.startsWith('pre_submit')||phase.startsWith('prepared')?'pre_click':'after_fill';
  const sample=fqValidationSample(current,want,stage,phase);
  if(!formFeedback.baseline)formFeedback.baseline=sample;
  if(stage==='after_fill')formFeedback.after_fill=sample;
  if(stage==='pre_click')formFeedback.pre_click=sample;
  if(stage==='post_click')formFeedback.post_click.push(sample);
  if(formFeedback.observations.length<80)formFeedback.observations.push(sample);
  formFeedback.latest=sample;
  if(stage==='after_fill'&&sample.same_book&&sample.same_alias&&!sample.messages.some(e=>e.visible&&e.attached&&e.text))clearedAfterFill=true;
  return sample;
 }
 function record(current,phase){
  latest={phase,observed_at:Date.now()/1000,...current.observed,mismatch_fields:current.mismatch};
  if(observations.length<80)observations.push(latest);
  feedbackRecord(current,phase);
 }
 function response(value){return {...value,form_feedback:formFeedback,readback:{schema:'fanqie_application_form_readback/v1',
  expected:{book_id:want.book_id,book_name:want.book_name,alias:want.alias,promotion_path:want.promotion_path,publish_type:want.publish_type},
  observations,latest,stable_required:2,poll_interval_ms:100,max_polls_per_stage:20}};}
 function assessment(){const sample=formFeedback.latest;
  return fqNamingAssessment(sample,sample.stage==='post_click'?formFeedback.pre_click:formFeedback.baseline,clearedAfterFill);}
 function validationResponse(block){
  if(block.classification==='alias_validation_failed')return response({ready:false,submitted:formFeedback.clicked,
   result:'alias_validation_failed',reason:'alias_validation_failed',alias_validation:block.validation,
   alias_reusable:false,retry_with_new_alias:true,server_response_evidence:false,platform_business_outcome_verified:false});
  return response({ready:false,submitted:formFeedback.clicked,result:'form_validation_unconfirmed',
   reason:'form_validation_unconfirmed',retry_with_new_alias:false});
 }
 function stopped(current){return current.validationBlock?validationResponse(current.validationBlock):
  response({ready:false,reason:current.reason||'form_readback_mismatch',retry_with_new_alias:false});}
 async function stable(keys,phase){
  let consecutive=0,current;
  for(let index=0;index<20;index++){
   if(index)await sleep(100);current=read();record(current,phase+'_'+index);
   if(current.reason==='modal_exact_book_unconfirmed'||current.observed.modal_count>1)return current;
   const block=assessment();if(block)return {...current,validationBlock:block};
   if(!current.reason&&!keys.some(key=>current.mismatch.includes(key)))consecutive++;else consecutive=0;
   if(consecutive>=2)return {...current,stable:true};
  }
  return current;
 }
 let current=read();record(current,'initial');
 if(current.reason)return response({ready:false,reason:current.reason});
 const initialBlock=assessment();if(initialBlock)return validationResponse(initialBlock);
 if(!"""+('true' if submit else 'false')+r"""){
  const input=current.input;
  if(input.disabled||input.readOnly)return response({ready:false,reason:'alias_input_not_editable',retry_with_new_alias:false});
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,want.alias);
  input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));
  current=await stable(['alias'],'after_alias_input');
  if(!current.stable||current.validationBlock)return stopped(current);
  for(const [key,value]of [['promotion_path',want.promotion_path],['publish_type',want.publish_type]]){
   current=read();record(current,'before_'+key);
   if(current.reason)return response({ready:false,reason:current.reason});
   const beforeBlock=assessment();if(beforeBlock)return validationResponse(beforeBlock);
   const control=key==='promotion_path'?current.path:current.type;
   if(!control)continue; // Only the already verified entry may stand for path.
   if(text(control)!==value){
    control.click();await sleep(150);
    current=read();record(current,'options_'+key);
    if(current.reason)return response({ready:false,reason:current.reason});
    const optionBlock=assessment();if(optionBlock)return validationResponse(optionBlock);
    const options=Array.from(document.querySelectorAll('.arco-select-option,[role=option]'))
     .filter(e=>visible(e)&&text(e)===value&&!e.disabled&&e.getAttribute('aria-disabled')!=='true'&&!/disabled/.test(e.className));
    if(options.length!==1)return response({ready:false,reason:'exact_option_missing_or_ambiguous'});
    options[0].click();
   }
   current=await stable([key],'after_'+key);
   if(!current.stable||current.validationBlock)return stopped(current);
  }
 }
 current=await stable(['alias','promotion_path','publish_type'],"""+json.dumps('pre_submit' if submit else 'prepared')+r""");
 if(!current.stable||current.validationBlock)return stopped(current);
 // This is the last fresh full-intent check before taking the current button.
 current=read();record(current,'final_fresh');
 if(current.reason||current.mismatch.length)return response({ready:false,reason:current.reason||'form_readback_mismatch'});
 const finalBlock=assessment();if(finalBlock)return validationResponse(finalBlock);
 const modal=current.modal;
 const buttons=Array.from(modal.querySelectorAll('button')).filter(e=>visible(e)&&['提交','确认申请','提交申请'].includes(text(e))&&!e.disabled&&!/disabled/.test(e.className));
 if(buttons.length!==1)return response({ready:false,reason:'unique_submit_not_enabled'});
 """+(r'''const baseline={messages:fqMessages(modal),titles:fqTitles(),public_form_inventory:fqInventory(modal)};
 const feedback={schema:'fanqie_application_UI_feedback/v1',baseline,observations:[],
  server_response_evidence:false,platform_business_outcome_verified:false};
 formFeedback.clicked=true;
 formFeedback.click_count++;
 buttons[0].click();
 for(let i=0;i<12;i++){
  await new Promise(r=>setTimeout(r,500));
  const fresh=read(),sameBook=fresh.observed.modal_count===1&&fresh.observed.book_identity_verified;
  feedbackRecord(fresh,'post_click_'+i);
  const messages=sameBook?fqMessages(fresh.modal):[],titles=fqTitles();
  const changed_messages=fqNewMessages(messages,baseline.messages),changed_titles=fqNewMessages(titles,baseline.titles);
  feedback.observations.push({index:i+1,observed_at:Date.now()/1000,same_book_modal:sameBook,
   modal_count:fresh.observed.modal_count,messages,titles,changed_messages,changed_titles});
  const namedBlock=assessment()||fqClearedNamingAssessment(formFeedback,feedback);
  if(namedBlock?.classification==='alias_validation_failed')return {...validationResponse(namedBlock),submission_feedback:feedback};
  if(changed_messages.length)return response({ready:true,submitted:true,result:'post_submit_feedback_observed',
   feedback_classification:'unverified_form_feedback',submission_feedback:feedback});
  if(changed_titles.some(e=>e.text.includes('成功')))return response({ready:true,submitted:true,result:'success_message_observed',
   feedback_classification:'visible_UI_wording_only',submission_feedback:feedback});
 }
 return response({ready:true,submitted:true,result:'confirmation_pending',submission_feedback:feedback});}''' if submit else 'return response({ready:true,submitted:false});}')


def _open_book_js(intent):
    return '() => {const want='+json.dumps(intent,ensure_ascii=False)+';const entryLabel='+json.dumps(PROMOTION_ENTRY_LABEL,ensure_ascii=False)+r""";
 const text=e=>(e?.innerText||e?.textContent||'').trim();
 const cards=Array.from(document.querySelectorAll('.book-hQ7GYr')).filter(c=>{
  return text(c.querySelector('.book-title-txt-_CIhYa'))===want.book_name;});
 if(cards.length!==1)return {clicked:false,reason:'exact_book_missing_or_ambiguous'};
 const buttons=Array.from(cards[0].querySelectorAll('.c-promotions button,button')).filter(b=>text(b)===entryLabel&&!b.disabled);
 if(buttons.length!==1)return {clicked:false,reason:'exact_apply_button_missing_or_ambiguous'};
 const entry_label=text(buttons[0]);buttons[0].click();return {clicked:true,book_name:want.book_name,entry_label};}"""


def _application_unknown(reason,*,hard=False,**details):
    return BrowserCommandResult('outcome_unknown' if hard else 'succeeded',dict(reason=reason,
        status='application_outcome_unknown',application_status='outcome_unknown',confirmed=False,
        requires_read_only_sync=True,automatic_resubmit=False,**details))


def _alias_validation_failure(value,intent,feedback_ref,*,form_prepared=None,submit_response=None):
    from src.platform_adapter.fanqie_form_feedback_v1 import confirmed_alias_validation
    if not confirmed_alias_validation(value,intent):return None
    submitted=value['submitted']
    result=dict(result='alias_validation_failed',reason='alias_validation_failed',
        application_status='alias_validation_failed',alias_reusable=False,retry_with_new_alias=True,
        submitted=submitted,submit_started=submitted,feedback_ref=feedback_ref,
        alias_validation=value['alias_validation'],book_id=intent['book_id'],book_name=intent['book_name'],alias=intent['alias'],
        server_response_evidence=False,platform_business_outcome_verified=False,original_claims_changed=False)
    if form_prepared is not None:result['form_prepared']=form_prepared
    if submit_response is not None:result['submit_response']=submit_response
    return BrowserCommandResult('failed',result)


def _intent_key(request):
    stable={k:request[k] for k in ('platform_identity_key','book_id','alias','promotion_path','publish_type')}
    return hashlib.sha256(json.dumps(stable,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _hard_worker_failure(error,page):
    from src.platform_adapter.browser_session import (BrowserWorkerUnavailable,
        BrowserWorkerStartupError,BrowserWorkerStartupTimeout)
    if isinstance(error,(BrowserWorkerUnavailable,BrowserWorkerStartupError,
                         BrowserWorkerStartupTimeout,EOFError,BrokenPipeError)):
        return True
    raw=getattr(page,'page',page)
    session=getattr(raw,'_session',None)
    probe=getattr(session,'worker_failure',None)
    if callable(probe):
        try:return probe() in ('worker_exited','response_channel_closed')
        except Exception:return False
    return False


def capture_native_snapshot(page,*,env,managed_subject,identity,guard,evidence_directory,
                            observer_request=None,legacy_snapshot_ref=None):
    """One explicit native-alias read on an owned evidence Page, no new session."""
    from src.platform_adapter.fanqie_promotion_observation_diagnostic_v1 import run_observation
    from src.platform_adapter.fanqie_promotion_observer_v1 import discover_resources
    from src.services import fanqie_promotion_identity_v2 as native
    folder=Path(evidence_directory);folder.mkdir(parents=True,exist_ok=True)
    guard()
    if legacy_snapshot_ref is None:
        legacy=capture(page,guard,resource_id=env['resource_id'],binding_version=env['binding_version'],
            identity=identity,evidence_path=folder/'LIST_BEFORE_RAW.json')
        legacy_snapshot_ref=_freeze(folder/'LEGACY_SNAPSHOT_V1.json',legacy)
    if observer_request is None:
        inventory=discover_resources(page)
        observed={item['path'] for item in inventory['resources']}
        paths=[native.PROMOTION_ENDPOINT,native.ENUM_ENDPOINT]
        if not set(paths)<=observed:
            reject('native_promotion_paths_not_observed','当前列表尚未观察到所需元数据资源，未猜测接口')
        observer_request=_freeze(folder/'NATIVE_OBSERVER_REQUEST.json',dict(
            schema='fanqie_promotion_observer_request/v1',
            **{key:managed_subject[key] for key in ('resource_id','binding_version','platform_identity_key','environment_key')},
            endpoint_paths=paths,wait_ms=1250,purpose='read_only_promotion_metadata_diagnosis'))
    _read(observer_request)
    diagnostic=run_observation(page,subject=managed_subject,observer_request=observer_request,
        guard=guard,output_directory=folder/'observer_diagnostic')
    _freeze(folder/'OBSERVER_DIAGNOSTIC_RESULT.json',diagnostic)
    if diagnostic.get('status')!='observed' or diagnostic.get('observer_stop_confirmed') is not True:
        reject('native_promotion_observation_incomplete','原生推广信息尚未取得完整观察证据，未放行')
    guard()
    return native.prepare_snapshot(legacy_snapshot_ref,diagnostic['evidence']['observation'],folder/'native_v2',
                                   managed_subject=managed_subject)


def make_handlers(accounts,env,*,page_provider,probe_provider):
    def handler(ctx,payload):
        folder=accounts.folder(ctx.task_id);folder.mkdir(parents=True,exist_ok=True)
        def identity():
            ctx.check_dispatch();probe=probe_provider(ctx)
            accounts.check_association(env)
            accounts.bindings().guard(env['resource_id'],env['binding_version'],ctx.actor.owner_id,ctx.actor.generation,probe)
            return probe
        def guard():identity()
        probe=identity();request=None
        if ctx.command['kind']=='fanqie_new_publication_backfill':
            from .fanqie_new_publication_backfill_v1 import execute
            return execute(ctx,accounts=accounts,env=env,page_provider=page_provider,identity_guard=guard)
        if ctx.command['kind']=='fanqie_cleanup_rebind':
            from .fanqie_cleanup_rebind_v1 import execute
            return execute(ctx,accounts=accounts,env=env,page_provider=page_provider,identity_guard=identity)
        if ctx.command['kind']=='fanqie_backfill_editor_inspect':
            from src.platform_adapter.fanqie_backfill_editor_inspection_v1 import inspect_backfill_editor,BackfillEditorNotConfirmed
            from src.platform_adapter.fanqie_filled_details_controls_v2 import _target,DetailsControlsNotConfirmed
            if (set(payload)!={'environment_key','book_id','book_name','lookup_alias','retained_url'}
                    or payload['environment_key']!=env['environment_key']
                    or not isinstance(payload['retained_url'],str)
                    or not re.fullmatch(r'https://www\.douyin\.com/video/\d{1,25}',payload['retained_url'])):
                reject('backfill_editor_inspect_payload_invalid','回填表单观察仅接受准确目标和原已填公开链接')
            _target(payload['book_id'],payload['book_name'],payload['lookup_alias'])
            managed_page=page_provider(ctx,LIST_URL)
            subject={k:env[k] for k in ('resource_id','binding_version','environment_key')}
            subject.update(platform_identity_key=probe['platform_identity_key'],owner_id=ctx.actor.owner_id,
                           generation=ctx.actor.generation,task_id=ctx.task_id)
            stages=[]
            def editor_checkpoint(stage,value):
                path=folder/('BACKFILL_EDITOR_'+stage.upper()+'.json')
                if path.exists():reject('backfill_editor_stage_already_recorded','原表单观察阶段已记录，不自动重复点击')
                stages.append(_freeze(path,dict(schema='fanqie_backfill_editor_step/v1',subject=subject,stage=stage,observation=value)))
            try:
                value=inspect_backfill_editor(managed_page.page,book_id=payload['book_id'],book_name=payload['book_name'],
                    alias=payload['lookup_alias'],retained_url=payload['retained_url'],guard=guard,checkpoint=editor_checkpoint)
            except (BackfillEditorNotConfirmed,DetailsControlsNotConfirmed) as error:
                value=dict(schema='fanqie_backfill_editor_inspection/v1',status='read_observation_not_confirmed',reason=str(error),
                    submitted=False,append_capability_verified=False)
            guard()
            evidence=_freeze(folder/'BACKFILL_EDITOR_INSPECTION.json',dict(value,managed_subject=subject,checkpoint_refs=stages))
            return BrowserCommandResult('succeeded',dict(backfill_editor_inspection=evidence,read_observation_status=value['status'],
                promotion_submitted=False,backfill_submitted=False,deleted=False,append_capability_verified=False,
                platform_business_outcome='not_evaluated',automatic_retry=False))
        if ctx.command['kind']=='fanqie_filled_details_controls':
            from src.platform_adapter.fanqie_filled_details_controls_v2 import (
                inspect_filled_details_controls,DetailsControlsNotConfirmed,_target)
            if (set(payload)!={'environment_key','book_id','book_name','lookup_alias'}
                    or payload['environment_key']!=env['environment_key']):
                reject('filled_details_controls_payload_invalid','详情控件只读观察仅接受准确原书与别名')
            try:_target(payload['book_id'],payload['book_name'],payload['lookup_alias'])
            except DetailsControlsNotConfirmed:
                reject('filled_details_controls_target_invalid','详情控件只读观察需要准确原书与别名')
            managed_page=page_provider(ctx,LIST_URL)
            subject={k:env[k] for k in ('resource_id','binding_version','environment_key')}
            subject.update(platform_identity_key=probe['platform_identity_key'],owner_id=ctx.actor.owner_id,
                           generation=ctx.actor.generation,task_id=ctx.task_id)
            stages=[]
            def controls_checkpoint(stage,value):
                path=folder/('FILLED_DETAILS_CONTROLS_'+stage.upper()+'.json')
                if stage=='view_click_intent' and path.exists():
                    reject('filled_details_view_already_claimed','原查看意图已记录，不自动重复点击')
                stages.append(_freeze(path,dict(
                    schema='fanqie_filled_details_controls_step/v2',subject=subject,stage=stage,observation=value)))
            try:
                value=inspect_filled_details_controls(managed_page.page,book_id=payload['book_id'],book_name=payload['book_name'],
                    alias=payload['lookup_alias'],guard=guard,checkpoint=controls_checkpoint)
            except DetailsControlsNotConfirmed as error:
                value=dict(schema='fanqie_filled_details_controls_observation/v2',status='read_observation_not_confirmed',
                    reason=str(error),target=_target(payload['book_id'],payload['book_name'],payload['lookup_alias']),
                    uploaded=False,submitted=False,deleted=False,append_capability_verified=False,old_ledger_changed=False)
            guard()
            evidence=_freeze(folder/'FILLED_DETAILS_CONTROLS.json',dict(value,managed_subject=subject,checkpoint_refs=stages))
            return BrowserCommandResult('succeeded',dict(filled_details_controls=evidence,read_observation_status=value['status'],
                promotion_submitted=False,backfill_submitted=False,deleted=False,append_capability_verified=False,
                platform_business_outcome='not_evaluated',automatic_retry=False))
        if ctx.command['kind']=='fanqie_filled_details':
            from src.platform_adapter.fanqie_filled_details_v1 import inspect_filled_details, _target
            if (set(payload)!={'environment_key','book_id','book_name','lookup_alias'}
                    or payload['environment_key']!=env['environment_key']):
                reject('filled_details_payload_invalid','发文详情仅接受准确原书与别名，不接受上传或提交')
            _target(payload['book_id'],payload['book_name'],payload['lookup_alias'])
            managed_page=page_provider(ctx,LIST_URL)
            subject={k:env[k] for k in ('resource_id','binding_version','environment_key')}
            subject.update(platform_identity_key=probe['platform_identity_key'],owner_id=ctx.actor.owner_id,
                           generation=ctx.actor.generation,task_id=ctx.task_id)
            def details_checkpoint(stage,value):
                _freeze(folder/('FILLED_DETAILS_'+stage.upper()+'.json'),dict(
                    schema='fanqie_filled_details_step/v1',subject=subject,stage=stage,observation=value))
            value=inspect_filled_details(managed_page.page,book_id=payload['book_id'],book_name=payload['book_name'],
                alias=payload['lookup_alias'],guard=guard,checkpoint=details_checkpoint)
            evidence=_freeze(folder/'FILLED_DETAILS.json',dict(value,managed_subject=subject))
            return BrowserCommandResult('succeeded',dict(filled_details=evidence,promotion_submitted=False,
                backfill_submitted=False,append_capability_verified=False))
        if ctx.command['kind']=='fanqie_promotion_lookup':
            from src.platform_adapter.fanqie_promotion_lookup_v1 import inspect_lookup,validate_lookup_target
            base={'environment_key','book_id','book_name','lookup_alias'}
            if set(payload) not in (base,base|{'lookup_request'})or payload['environment_key']!=env['environment_key']:
                reject('promotion_lookup_payload_invalid','只读查询不接受申请、回填或原生响应重放')
            validate_lookup_target(payload['book_id'],payload['book_name'],payload['lookup_alias'])
            page=page_provider(ctx,LIST_URL)
            subject={k:env[k]for k in ('resource_id','binding_version','environment_key')}
            subject.update(platform_identity_key=probe['platform_identity_key'],owner_id=ctx.actor.owner_id,
                generation=ctx.actor.generation,task_id=ctx.task_id)
            def lookup_checkpoint(stage,value):
                _freeze(folder/('LOOKUP_'+stage.upper()+'.json'),dict(schema='fanqie_promotion_lookup_step/v1',
                    subject=subject,stage=stage,observation=value))
            value=inspect_lookup(page,book_id=payload['book_id'],book_name=payload['book_name'],alias=payload['lookup_alias'],
                subject=subject,guard=guard,checkpoint=lookup_checkpoint,lookup_request=payload.get('lookup_request'))
            evidence=_freeze(folder/'PROMOTION_LOOKUP.json',dict(value,managed_subject=subject))
            return BrowserCommandResult('succeeded',dict(promotion_lookup=evidence,lookup_status=value['status'],
                searched=value['searched'],promotion_submitted=False,platform_business_outcome='unknown'))
        if ctx.command['kind']=='fanqie_promotion_preflight':
            from src.platform_adapter.fanqie_promotion_preflight_v1 import inspect_preflight,validate_target
            if (set(payload) not in ({'environment_key','book_id','book_name'},
                    {'environment_key','book_id','book_name','locate'})
                    or type(payload.get('locate',False)) is not bool
                    or payload['environment_key']!=env['environment_key']):
                reject('promotion_preflight_payload_invalid','预检仅接受当前环境与准确书籍，不接受申请或回填内容')
            validate_target(payload['book_id'],payload['book_name'])
            page=page_provider(ctx,CONTENT_URL)
            subject={k:env[k] for k in ('resource_id','binding_version','environment_key')}
            subject.update(platform_identity_key=probe['platform_identity_key'],owner_id=ctx.actor.owner_id,
                           generation=ctx.actor.generation,task_id=ctx.task_id)
            def checkpoint(stage,value):
                _freeze(folder/('PREFLIGHT_'+stage.upper()+'.json'),dict(
                    schema='fanqie_promotion_preflight_step/v1',subject=subject,stage=stage,observation=value))
            result=inspect_preflight(page,book_id=payload['book_id'],book_name=payload['book_name'],
                guard=guard,checkpoint=checkpoint,locate=payload.get('locate',False))
            evidence=_freeze(folder/'PROMOTION_PREFLIGHT.json',dict(result,managed_subject=subject))
            return BrowserCommandResult('succeeded',dict(promotion_preflight=evidence,
                preflight_status=result['status'],preflight_passed=result['preflight_passed'],
                promotion_submitted=False,promotion_task_active=False,chapters_read=0))
        if ctx.command['kind']=='fanqie_promotion_apply':
            request=application_request(payload.get('request'),env,probe)
            if (folder/'SUBMIT_CLAIM.json').exists():
                return _application_unknown('original_application_submit_claim_preserved')
        page=page_provider(ctx,LIST_URL)
        snapshot=capture(page,guard,resource_id=env['resource_id'],binding_version=env['binding_version'],
            identity=identity,evidence_path=folder/'LIST_BEFORE_RAW.json')
        snapshot_ref=_freeze(folder/'PROMOTION_SNAPSHOT.json',snapshot)
        if request is None:
            result={'promotion_snapshot':snapshot_ref,'resource_paths':_bind(folder/'RESOURCE_PATHS.json'),
                    'rows':len(snapshot['rows'])}
            if payload.get('snapshot_version')=='v2':
                fresh=identity()
                subject={key:env[key] for key in ('resource_id','binding_version','environment_key')}
                subject.update(platform_identity_key=fresh['platform_identity_key'],owner_id=ctx.actor.owner_id,
                    generation=ctx.actor.generation,task_id=ctx.task_id)
                result['promotion_snapshot']=capture_native_snapshot(page,env=env,managed_subject=subject,
                    identity=identity,guard=guard,evidence_directory=folder/'native_alias_sync',
                    observer_request=payload.get('observer_request'),legacy_snapshot_ref=snapshot_ref)
                result['snapshot_version']='v2'
            elif payload.get('observer_request') is not None:
                from src.platform_adapter.fanqie_promotion_observation_diagnostic_v1 import run_observation
                _read(payload['observer_request'])
                fresh=identity()
                subject={key:env[key] for key in ('resource_id','binding_version','environment_key')}
                subject.update(platform_identity_key=fresh['platform_identity_key'],owner_id=ctx.actor.owner_id,
                               generation=ctx.actor.generation,task_id=ctx.task_id)
                diagnostic=run_observation(page,subject=subject,observer_request=payload['observer_request'],
                    guard=guard,output_directory=folder/'observer_diagnostic')
                result['observer_diagnostic']=_freeze(folder/'OBSERVER_DIAGNOSTIC_RESULT.json',diagnostic)
            if ctx.command['kind']=='fanqie_promotion_list':
                from src.platform_adapter.fanqie_list_filter_inventory_v1 import LIST_FILTER_INVENTORY_JS
                guard()
                filter_inventory=page.evaluate(LIST_FILTER_INVENTORY_JS)
                guard()
                result['visible_list_filters']=_freeze(folder/'VISIBLE_LIST_FILTERS.json',dict(
                    observation=filter_inventory,observed_at=time.time(),
                    resource_id=env['resource_id'],binding_version=env['binding_version'],
                    platform_identity_key=probe['platform_identity_key'],
                    owner_id=ctx.actor.owner_id,generation=ctx.actor.generation,task_id=ctx.task_id))
            return BrowserCommandResult('succeeded',result)
        if not snapshot['table_ready'] or not snapshot['pagination_complete']:
            return BrowserCommandResult('failed',{'reason':'existing_task_scan_incomplete','promotion_snapshot':snapshot_ref})
        related=[r for r in snapshot['rows'] if r['book_id']==request['book_id'] and r['alias']==request['alias']]
        exact=[r for r in related if r['promotion_path']==request['promotion_path'] and r['publish_type']==request['publish_type']]
        if exact:
            return BrowserCommandResult('succeeded',{'status':'existing_promotion_preserved','rows':exact,
                'promotion_snapshot':snapshot_ref,'confirmed':False,'application_status':'existing_task_observed'})
        possible=[r for r in snapshot['rows'] if r['book_id'] in (None,'',request['book_id'])
                  and r['alias'] in (None,'',request['alias'])]
        if related or possible:
            return BrowserCommandResult('failed',{'reason':'existing_tasks_pending_or_intent_conflict','promotion_snapshot':snapshot_ref})
        once=accounts.evidence/'promotion_application_claims'/_intent_key(request)/'CLAIM.json'
        if once.exists():return _application_unknown('original_authorized_intent_claim_preserved',promotion_snapshot=snapshot_ref)
        page=page_provider(ctx,CONTENT_URL);guard()
        intent={k:request[k] for k in INTENT_FIELDS}
        from src.platform_adapter.fanqie_exact_book_locator_v1 import locate_exact_book
        def location_checkpoint(stage,value):
            _freeze(folder/('BOOK_LOCATION_'+stage.upper()+'.json'),dict(
                schema='fanqie_exact_book_location_step/v1',stage=stage,observation=value,
                request=payload['request'],resource_id=env['resource_id'],
                binding_version=env['binding_version'],environment_key=env['environment_key'],
                platform_identity_key=probe['platform_identity_key'],owner_id=ctx.actor.owner_id,
                generation=ctx.actor.generation,task_id=ctx.task_id))
        location=locate_exact_book(page,book_id=intent['book_id'],book_name=intent['book_name'],
            guard=guard,checkpoint=location_checkpoint,search_allowed=True)
        location_ref=_freeze(folder/'BOOK_LOCATION.json',location)
        if location['status'] not in {'located_current_view','located_after_exact_search'}:
            return BrowserCommandResult('failed',{'reason':location['status'],'book_location':location_ref,
                'submit_started':False,'alias_filled':False})
        guard()
        opened=page.evaluate(_open_book_js(intent))
        _freeze(folder/'OPENED_BOOK.json',opened)
        if not opened.get('clicked'):return BrowserCommandResult('failed',{'reason':opened.get('reason','exact_book_unconfirmed')})
        page.wait_for_timeout(300);guard()
        prepared=page.evaluate(_form_js(intent,entry_evidence=opened));prepared_ref=_freeze(folder/'FORM_PREPARED.json',prepared)
        named_failure=_alias_validation_failure(prepared,intent,prepared_ref,form_prepared=prepared_ref)
        if named_failure is not None:return named_failure
        if not prepared.get('ready'):return BrowserCommandResult('failed',dict(reason=prepared.get('reason','form_unconfirmed'),
            form_prepared=prepared_ref,feedback_ref=prepared_ref,submitted=False,submit_started=False,retry_with_new_alias=False))
        guard();application_request(payload['request'],env,identity())
        claim=dict(command_id=ctx.task_id,request=payload['request'],intent=intent,
            owner_id=ctx.actor.owner_id,generation=ctx.actor.generation,at_epoch=time.time(),automatic_retry=False)
        once.parent.mkdir(parents=True,exist_ok=True)
        try:
            with once.open('x',encoding='utf-8') as output:json.dump(claim,output,ensure_ascii=False)
        except FileExistsError:
            return _application_unknown('original_authorized_intent_claim_preserved')
        _freeze(folder/'SUBMIT_CLAIM.json',claim)
        submit_response_ref=None
        try:
            result=page.evaluate(_form_js(intent,submit=True,entry_evidence=opened));submit_response_ref=_freeze(folder/'SUBMIT_RESPONSE.json',result)
            named_failure=_alias_validation_failure(result,intent,submit_response_ref,form_prepared=prepared_ref,submit_response=submit_response_ref)
            if named_failure is not None:return named_failure
            if result.get('submitted') is not True:
                return BrowserCommandResult('failed',dict(reason=result.get('reason','submission_not_started'),
                    submit_started=False,submitted=False,retry_with_new_alias=False,feedback_ref=submit_response_ref,
                    form_prepared=prepared_ref,submit_response=submit_response_ref))
            page=page_provider(ctx,LIST_URL)
            after=capture(page,guard,resource_id=env['resource_id'],binding_version=env['binding_version'],
                identity=identity,evidence_path=folder/'LIST_AFTER_RAW.json')
            proof=_freeze(folder/'PROMOTION_AFTER.json',after)
            matches=[r for r in after['rows'] if all(r[k]==request[k] for k in ('book_id','alias','promotion_path','publish_type'))]
            if len(matches)==1 and not matches[0]['pending_fields']:
                return BrowserCommandResult('succeeded',{'status':'promotion_observed','row':matches[0],
                    'promotion_snapshot':proof,'application_status':'task_observed','confirmed':False,
                    'task_active':matches[0]['alias_status']=='生效中'})
            return _application_unknown('application_submitted_not_confirmed',promotion_snapshot=proof,
                form_prepared=prepared_ref,submit_response=submit_response_ref,feedback_ref=submit_response_ref,retry_with_new_alias=False)
        except BrowserControlRejected as error:
            _freeze(folder/'SUBMIT_UNKNOWN.json',dict(error_type=type(error).__name__,automatic_retry=False))
            return _application_unknown('application_owner_or_identity_fenced',hard=True,form_prepared=prepared_ref,
                submit_response=submit_response_ref,feedback_ref=submit_response_ref,retry_with_new_alias=False)
        except Exception as error:
            _freeze(folder/'SUBMIT_UNKNOWN.json',dict(error_type=type(error).__name__,automatic_retry=False))
            return _application_unknown('application_submission_outcome_unknown',hard=_hard_worker_failure(error,page),
                form_prepared=prepared_ref,submit_response=submit_response_ref,feedback_ref=submit_response_ref,retry_with_new_alias=False)
    return {'fanqie_promotion_list':handler,'fanqie_promotion_apply':handler,'fanqie_promotion_preflight':handler,
            'fanqie_promotion_lookup':handler,'fanqie_filled_details':handler,'fanqie_filled_details_controls':handler,
            'fanqie_backfill_editor_inspect':handler,'fanqie_new_publication_backfill':handler,'fanqie_cleanup_rebind':handler}
