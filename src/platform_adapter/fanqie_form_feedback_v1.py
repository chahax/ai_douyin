"""Bounded public form observations, never server/native outcome evidence.

Only an already identity-verified book modal may be supplied. Authentication
storage and unrelated field values are never read. The current authorized
public alias may be supplied by the form caller solely for subject binding;
inventory still reads no input values. No requests, hidden text or writes occur.
"""
import json
import math
import hashlib
from pathlib import Path

VERSION = 'fanqie_form_feedback/v1'
NAMING_CONFLICT_MESSAGES = {
    '与热门书籍/短剧/作者相似度高': 'alias_name_similarity_high',
    '仅支持汉字及阿拉伯数字，字数限制为4-8字': 'alias_format_invalid'}

PUBLIC_FORM_HELPERS_JS = '\n const fqNamingRules='+json.dumps(NAMING_CONFLICT_MESSAGES,ensure_ascii=False)+';'+r"""
 const fqVisible=e=>!!e&&e.isConnected&&!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const fqClean=(value,limit=400)=>String(value||'').replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g,'')
  .replace(/https?:\/\/[^\s<>"']+/gi,'[link omitted]')
  .replace(/\b(token|session|cookie|secret|authorization|password)\s*[:=]\s*[^\s,;]+/gi,'$1=[redacted]')
  .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi,'[email omitted]').trim().slice(0,limit);
 const fqText=(e,limit=400)=>fqVisible(e)?fqClean(e.innerText||'',limit):'';
 function fqMessages(modal){
  if(!modal||!fqVisible(modal))return [];
  return Array.from(modal.querySelectorAll('.err-list-h4mOz7,[role="alert"]')).slice(0,20)
   .map(e=>({source:e.matches('.err-list-h4mOz7')?'known_error_list':'form_alert',
    visible:fqVisible(e),attached:e.isConnected,text:fqVisible(e)?fqText(e,500):null}));
 }
 function fqTitles(){
  return Array.from(document.querySelectorAll('.title-azi_qL')).filter(fqVisible).slice(0,10)
   .map(e=>({source:'known_result_title',visible:true,attached:e.isConnected,text:fqText(e,300)}));
 }
 function fqInventory(modal){
  const visible=!!modal&&fqVisible(modal);
  return {schema:'fanqie_public_form_inventory/v1',visible,
   public_text_lines:visible?(modal.innerText||'').split(/\r?\n/).map(t=>fqClean(t,200)).filter(Boolean).slice(0,60):[],
   known_alias_inputs:visible?Array.from(modal.querySelectorAll('.alias-input-EBp1Sw')).filter(fqVisible).slice(0,4).map(e=>({
    tag:e.tagName.toLowerCase(),type:(e.type||'').slice(0,30),placeholder:fqClean(e.getAttribute('placeholder'),200),
    min_length:Number.isInteger(e.minLength)&&e.minLength>=0?e.minLength:null,
    max_length:Number.isInteger(e.maxLength)&&e.maxLength>=0?e.maxLength:null,
    pattern:e.hasAttribute('pattern')?fqClean(e.getAttribute('pattern'),200):null,
    input_mode:fqClean(e.getAttribute('inputmode'),40),enter_key_hint:fqClean(e.getAttribute('enterkeyhint'),40),
    required:!!e.required,disabled:!!e.disabled,read_only:!!e.readOnly})):[],
   fields:visible?Array.from(modal.querySelectorAll('.arco-form-item')).filter(fqVisible).slice(0,16).map(field=>({
    label:fqText(field.querySelector('.arco-form-item-label'),100),public_text:fqText(field,500),
    controls:Array.from(field.querySelectorAll('input,textarea,.arco-select')).filter(fqVisible).slice(0,6).map(e=>({
     tag:e.tagName.toLowerCase(),type:(e.type||'').slice(0,30),placeholder:fqClean(e.getAttribute('placeholder'),120),
     required:!!e.required,disabled:!!e.disabled,read_only:!!e.readOnly,
     min_length:Number.isInteger(e.minLength)&&e.minLength>=0?e.minLength:null,
     max_length:Number.isInteger(e.maxLength)&&e.maxLength>=0?e.maxLength:null}))})):[],
   messages:fqMessages(modal),input_values_read:false,hidden_message_text_read:false,
   server_response_evidence:false,platform_business_outcome_verified:false};
 }
 function fqNewMessages(current,baseline){
  const prior=new Set(baseline.filter(e=>e.visible&&e.text).map(e=>e.source+'\n'+e.text));
  return current.filter(e=>e.visible&&e.attached&&e.text&&!prior.has(e.source+'\n'+e.text));
 }
 function fqValidationSample(current,want,stage,phase){
  const observed=current.observed,same_book=observed.modal_count===1&&observed.book_identity_verified===true;
  const buttons=same_book?Array.from(current.modal.querySelectorAll('button')).filter(e=>fqVisible(e)&&
   ['提交','确认申请','提交申请'].includes(fqText(e,100))):[];
  return {stage,phase,observed_at:Date.now()/1000,book_id:want.book_id,book_name:want.book_name,alias:want.alias,
   observed_book_ids:observed.observed_book_ids,same_book,
   modal_count:observed.modal_count,alias_input_count:observed.alias_input_count,
   alias_input_attached:observed.alias_attached,
   same_alias:same_book&&observed.alias_value===want.alias,current_alias:observed.alias_value,
   alias_input_disabled:observed.alias_disabled,alias_input_read_only:observed.alias_read_only,
   messages:same_book?fqMessages(current.modal):[],
   submit_buttons:buttons.slice(0,5).map(e=>({text:fqText(e,100),disabled:!!e.disabled,
    aria_disabled:e.getAttribute('aria-disabled')==='true',class_disabled:/disabled/.test(e.className),
    enabled:!e.disabled&&e.getAttribute('aria-disabled')!=='true'&&!/disabled/.test(e.className)})),
   source:'visible_DOM',server_response_evidence:false,platform_business_outcome_verified:false};
 }
 function fqNamingAssessment(sample,reference,cleared=false){
  if(!sample.same_book||!sample.same_alias)return null;
  const messages=sample.messages.filter(e=>e.visible&&e.attached&&e.text),named=[],unknown=[];
  for(const message of messages){
   for(const line of message.text.split(/\r?\n/).map(t=>t.trim()).filter(Boolean)){
    const rule=fqNamingRules[line];
    if(rule)named.push({...message,text:line,rule_id:rule});else unknown.push({...message,text:line});
   }
  }
  if(!messages.length)return null;
  const fresh_named=fqNewMessages(messages,reference?.messages||[]).some(e=>
   e.text.split(/\r?\n/).some(t=>fqNamingRules[t.trim()]));
  const freshness=sample.stage==='post_click'?(fresh_named?'new_post_click_validation':null):
   reference?.same_book&&reference?.same_alias?'current_alias_baseline':
   fresh_named?'new_visible_naming_validation':cleared?'observed_clear_then_validation':null;
  if(named.length&&!unknown.length&&freshness)return {classification:'alias_validation_failed',
   validation:{schema:'fanqie_alias_validation/v1',classification:'alias_validation_failed',same_book:true,same_alias:true,fresh:true,
    book_id:sample.book_id,book_name:sample.book_name,alias:sample.alias,current_alias:sample.current_alias,
    observed_book_ids:sample.observed_book_ids,stage:sample.stage,observed_at:sample.observed_at,
    rule_id:named[0].rule_id,known_message:named[0].text,naming_messages:named,freshness,
    observation:sample,reference,source:'visible_DOM',server_response_evidence:false,platform_business_outcome_verified:false}};
  return {classification:'form_validation_unconfirmed'};
 }
 function fqClearedNamingAssessment(history,ui){
  const sample=history.latest,reference=history.pre_click;
  const emptyMessages=s=>!(s?.messages||[]).some(e=>e.visible&&e.attached&&e.text);
  const scoped=s=>s?.same_book===true&&s.modal_count===1&&s.alias_input_count===1&&s.alias_input_attached===true;
  const enabled=s=>s?.submit_buttons?.length===1&&s.submit_buttons[0].enabled===true;
  if(!scoped(reference)||!reference.same_alias||reference.phase!=='final_fresh'||!enabled(reference)||!emptyMessages(reference)||
     !scoped(sample)||sample.stage!=='post_click'||sample.current_alias!==''||sample.same_alias!==false||
     history.clicked!==true||history.click_count!==1||history.post_click_field_writes!==0)return null;
  if(JSON.stringify(ui?.baseline?.messages)!==JSON.stringify(reference.messages)||
     (ui?.baseline?.titles||[]).some(e=>e.visible&&e.attached&&e.text?.includes('成功'))||
     history.observations.filter(s=>s.stage!=='post_click').some(s=>!scoped(s)||!s.same_alias||s.current_alias!==reference.alias||!emptyMessages(s)))return null;
  if(!history.post_click.length||history.post_click.at(-1)!==sample||ui?.observations?.length!==history.post_click.length)return null;
  for(let i=0;i<history.post_click.length;i++){
   const s=history.post_click[i],u=ui.observations[i];
   if(!scoped(s)||![reference.alias,''].includes(s.current_alias)||s.same_alias!==(s.current_alias===reference.alias)||
      s.observed_at<reference.observed_at||!u.same_book_modal||u.modal_count!==1||
      JSON.stringify(u.messages)!==JSON.stringify(s.messages)||
      (u.titles||[]).some(e=>e.visible&&e.attached&&e.text?.includes('成功')))return null;
   for(const e of s.messages.filter(e=>e.visible&&e.attached&&e.text))for(const line of e.text.split(/\r?\n/).map(t=>t.trim()).filter(Boolean))
    if(!fqNamingRules[line])return null;
  }
  const named=[];
  for(const e of sample.messages.filter(e=>e.visible&&e.attached&&e.text))for(const line of e.text.split(/\r?\n/).map(t=>t.trim()).filter(Boolean))
   named.push({...e,text:line,rule_id:fqNamingRules[line]});
  const button=sample.submit_buttons?.[0];
  if(!named.length||sample.submit_buttons?.length!==1||button.enabled!==false||
     !(button.disabled===true||button.aria_disabled===true||button.class_disabled===true))return null;
  if(!fqNewMessages(sample.messages,reference.messages).length)return null;
  return {classification:'alias_validation_failed',validation:{schema:'fanqie_alias_validation/v2',
   classification:'alias_validation_failed',same_book:true,same_alias:false,fresh:true,
   book_id:sample.book_id,book_name:sample.book_name,alias:sample.alias,current_alias:'',submitted_alias:reference.current_alias,
   submitted_alias_bound:true,observed_book_ids:sample.observed_book_ids,stage:'post_click',observed_at:sample.observed_at,
   rule_id:named[0].rule_id,known_message:named[0].text,naming_messages:named,freshness:'new_post_click_validation',
   alias_binding:{type:'pre_click_exact_then_empty',evidence_mode:'live_observation',
    alternative_alias_scope:'not_observed_in_captured_samples',react_internal_state_verified:false},
   observation:sample,reference,source:'visible_DOM',server_response_evidence:false,platform_business_outcome_verified:false}};
 }
"""


def _named_messages(sample):
    named=[]
    for message in sample.get('messages',[]):
        if not isinstance(message,dict):raise ValueError('alias_message_shape_invalid')
        if message.get('visible')is not True or message.get('attached')is not True or not message.get('text'):continue
        if not isinstance(message['text'],str):raise ValueError('alias_message_text_required')
        if message.get('source')not in ('known_error_list','form_alert'):raise ValueError('alias_message_source_invalid')
        for text in message['text'].splitlines():
            text=text.strip()
            if not text:continue
            if text not in NAMING_CONFLICT_MESSAGES:raise ValueError('alias_naming_message_not_observed_rule')
            named.append(dict(message,text=text,rule_id=NAMING_CONFLICT_MESSAGES[text]))
    return named


def _same_subject(sample,expected):
    return (isinstance(sample,dict)and sample.get('same_book')is True and sample.get('same_alias')is True
        and sample.get('source')=='visible_DOM'and sample.get('observed_book_ids')==[expected['book_id']]
        and sample.get('current_alias')==expected['alias']
        and all(sample.get(k)==expected[k]for k in ('book_id','book_name','alias')))


def _validate_alias_validation(feedback,expected):
    """Verify the current UI naming failure, not a server/native outcome.

    Accepts the exact FORM_PREPARED/SUBMIT_RESPONSE document. Old bare reasons,
    another alias/book, mixed unknown hints and stale post-click text all fail.
    """
    if not isinstance(feedback,dict)or not isinstance(expected,dict):raise ValueError('alias_validation_document_required')
    if any(not isinstance(expected.get(k),str)or not expected[k]for k in ('book_id','book_name','alias')):
        raise ValueError('alias_validation_expected_subject_required')
    if feedback.get('alias_validation',{}).get('schema')=='fanqie_alias_validation/v2':
        return _validate_cleared_validation(feedback,expected)
    value=feedback.get('alias_validation');history=feedback.get('form_feedback')
    if (not isinstance(value,dict)or value.get('schema')!='fanqie_alias_validation/v1'
            or value.get('classification')!='alias_validation_failed'or value.get('fresh')is not True
            or feedback.get('result')!='alias_validation_failed'or feedback.get('retry_with_new_alias')is not True
            or feedback.get('alias_reusable')is not False or not _same_subject(value,expected)
            or not isinstance(history,dict)or history.get('schema')!='fanqie_application_form_feedback/v1'):
        raise ValueError('alias_validation_subject_or_classification_invalid')
    observation=value.get('observation');reference=value.get('reference');stage=value.get('stage')
    samples=history.get('observations',[])
    if not isinstance(samples,list):raise ValueError('alias_validation_samples_required')
    if (not _same_subject(observation,expected)or observation.get('stage')!=stage
            or stage not in ('baseline','after_fill','pre_click','post_click')
            or observation not in samples and observation!=history.get('latest')
            or value.get('observed_at')!=observation.get('observed_at')
            or type(value.get('observed_at'))not in (int,float)or not math.isfinite(value['observed_at'])
            or value['observed_at']<=0 or value.get('source')!='visible_DOM'
            or value.get('server_response_evidence')is not False or value.get('platform_business_outcome_verified')is not False):
        raise ValueError('alias_validation_observation_unbound')
    named=_named_messages(observation)
    if (not named or value.get('naming_messages')!=named or value.get('known_message')!=named[0]['text']
            or value.get('rule_id')!=named[0]['rule_id']):raise ValueError('alias_validation_known_rule_required')
    submitted=feedback.get('submitted')
    if type(submitted)is not bool or history.get('clicked')is not submitted:
        raise ValueError('alias_validation_click_state_unbound')
    expected_reference=history.get('pre_click')if stage=='post_click'else history.get('baseline')
    if reference!=expected_reference or not isinstance(reference,dict):raise ValueError('alias_validation_reference_unbound')
    if reference.get('observed_at',0)>observation['observed_at']:raise ValueError('alias_validation_time_reversed')
    prior={(m.get('source'),m.get('text'))for m in reference.get('messages',[])
        if isinstance(m,dict)and m.get('visible')is True and m.get('text')}
    fresh_named=any(isinstance(m,dict)and m.get('visible')is True and m.get('attached')is True
        and (m.get('source'),m.get('text'))not in prior
        and any(line.strip()in NAMING_CONFLICT_MESSAGES for line in m.get('text','').splitlines())
        for m in observation.get('messages',[]))
    basis=value.get('freshness')
    if stage=='post_click':
        if (not submitted or basis!='new_post_click_validation'or not _same_subject(reference,expected)or not fresh_named):
            raise ValueError('alias_validation_fresh_post_click_required')
    elif submitted:raise ValueError('alias_validation_pre_click_cannot_claim_submitted')
    elif basis=='current_alias_baseline':
        if not _same_subject(reference,expected):raise ValueError('alias_validation_current_baseline_required')
    elif basis=='new_visible_naming_validation':
        if not fresh_named:raise ValueError('alias_validation_new_visible_message_required')
    elif basis=='observed_clear_then_validation':
        if not any(_same_subject(s,expected)and s.get('stage')=='after_fill'and not s.get('messages')
            and reference.get('observed_at',0)<=s.get('observed_at',0)<=observation['observed_at']for s in samples):
            raise ValueError('alias_validation_clear_evidence_required')
    else:raise ValueError('alias_validation_freshness_unverified')
    return value


def _book_scope(sample,expected):
    return (isinstance(sample,dict)and sample.get('same_book')is True
        and sample.get('source')=='visible_DOM'and sample.get('observed_book_ids')==[expected['book_id']]
        and all(sample.get(k)==expected[k]for k in ('book_id','book_name','alias'))
        and sample.get('server_response_evidence')is False
        and sample.get('platform_business_outcome_verified')is False)


def _messages_empty(sample):
    return not any(m.get('visible')is True and m.get('attached')is True and m.get('text')
        for m in sample.get('messages',[]))


def _one_button(sample,*,enabled):
    buttons=sample.get('submit_buttons')
    return (isinstance(buttons,list)and len(buttons)==1 and buttons[0].get('text')in ('提交','提交申请','确认申请')
        and buttons[0].get('enabled')is enabled
        and (buttons[0].get('disabled')is False and buttons[0].get('aria_disabled')is False
             and buttons[0].get('class_disabled',False)is False
             if enabled else any(buttons[0].get(k)is True for k in ('disabled','aria_disabled','class_disabled'))))


def _cleared_value(feedback,expected,*,legacy=False):
    """Recompute this bounded visible UI sequence; never infer hidden/React state."""
    h=feedback.get('form_feedback');ui=feedback.get('submission_feedback')
    if (not isinstance(h,dict)or h.get('schema')!='fanqie_application_form_feedback/v1'
            or h.get('mode')!='submit'or h.get('clicked')is not True or feedback.get('submitted')is not True
            or not isinstance(ui,dict)or ui.get('schema')!='fanqie_application_UI_feedback/v1'
            or ui.get('server_response_evidence')is not False or ui.get('platform_business_outcome_verified')is not False):
        raise ValueError('alias_clear_click_history_required')
    if not legacy and (type(h.get('click_count'))is not int or h['click_count']!=1
            or type(h.get('post_click_field_writes'))is not int or h['post_click_field_writes']!=0):
        raise ValueError('alias_clear_one_controlled_click_required')
    if legacy and any(k in h for k in ('click_count','post_click_field_writes')):
        raise ValueError('alias_clear_legacy_must_preserve_absent_fields')
    reference=h.get('pre_click');sample=h.get('latest');posts=h.get('post_click');observations=ui.get('observations')
    if (not _same_subject(reference,expected)or reference.get('phase')!='final_fresh'
            or not _book_scope(reference,expected)or not _messages_empty(reference)or not _one_button(reference,enabled=True)
            or not isinstance(posts,list)or not 1<=len(posts)<=12 or posts[-1]!=sample
            or not isinstance(observations,list)or len(observations)!=len(posts)):
        raise ValueError('alias_clear_exact_preclick_required')
    def scoped(s):
        if not _book_scope(s,expected):return False
        # Legacy read() returns a string only for exactly one visible, attached
        # alias input in the exact-book modal. No missing legacy field is filled.
        if legacy:return type(s.get('current_alias'))is str and not any(k in s for k in ('modal_count','alias_input_count','alias_input_attached'))
        return (type(s.get('modal_count'))is int and s['modal_count']==1
            and type(s.get('alias_input_count'))is int and s['alias_input_count']==1
            and s.get('alias_input_attached')is True)
    if not scoped(reference):raise ValueError('alias_clear_unique_preclick_input_required')
    if (ui.get('baseline',{}).get('messages')!=reference.get('messages')
            or any(t.get('visible')is True and t.get('attached')is True and '成功'in str(t.get('text',''))
                   for t in ui.get('baseline',{}).get('titles',[]))
            or any(not scoped(s)or not _same_subject(s,expected)or not _messages_empty(s)
                   for s in h.get('observations',[])if s.get('stage')!='post_click')):
        raise ValueError('alias_clear_preclick_hint_not_clear')
    previous=reference['observed_at']
    if type(previous)not in (int,float)or not math.isfinite(previous):raise ValueError('alias_clear_time_required')
    for index,(s,u)in enumerate(zip(posts,observations)):
        t=s.get('observed_at')
        if (not scoped(s)or s.get('stage')!='post_click'or s.get('phase')!='post_click_'+str(index)
                or s.get('current_alias')not in (expected['alias'],'')
                or s.get('same_alias')is not (s.get('current_alias')==expected['alias'])
                or type(t)not in (int,float)or not math.isfinite(t)or t<=previous
                or t-reference['observed_at']>7 or s not in h.get('observations',[])
                or u.get('index')!=index+1 or type(u.get('modal_count'))is not int or u['modal_count']!=1
                or u.get('same_book_modal')is not True or u.get('messages')!=s.get('messages')
                or type(u.get('observed_at'))not in (int,float)or not t<=u['observed_at']<=t+0.1):
            raise ValueError('alias_clear_intermediate_scope_or_alias_unconfirmed')
        _named_messages(s) # An unknown or mixed hint cannot authorize a new alias.
        for title in u.get('titles',[])+u.get('changed_titles',[]):
            if title.get('visible')is True and title.get('attached')is True and '成功'in str(title.get('text','')):
                raise ValueError('alias_clear_success_feedback_conflict')
        previous=t
    if (sample.get('current_alias')!=''or sample.get('same_alias')is not False
            or not _one_button(sample,enabled=False)):
        raise ValueError('alias_clear_empty_current_and_disabled_required')
    named=_named_messages(sample)
    if not named:raise ValueError('alias_clear_known_fresh_hint_required')
    last=observations[-1]
    if last.get('changed_messages')!=[m for m in sample['messages']if m.get('visible')is True and m.get('attached')is True and m.get('text')]:
        raise ValueError('alias_clear_changed_hint_evidence_required')
    return dict(schema='fanqie_alias_validation/v2',classification='alias_validation_failed',same_book=True,same_alias=False,fresh=True,
        book_id=expected['book_id'],book_name=expected['book_name'],alias=expected['alias'],current_alias='',
        submitted_alias=reference['current_alias'],submitted_alias_bound=True,observed_book_ids=sample['observed_book_ids'],
        stage='post_click',observed_at=sample['observed_at'],rule_id=named[0]['rule_id'],known_message=named[0]['text'],
        naming_messages=named,freshness='new_post_click_validation',
        alias_binding=dict(type='pre_click_exact_then_empty',evidence_mode='legacy_source_bound_derivation'if legacy else'live_observation',
            alternative_alias_scope='not_observed_in_captured_samples',react_internal_state_verified=False),
        observation=sample,reference=reference,source='visible_DOM',server_response_evidence=False,platform_business_outcome_verified=False)


_LEGACY_SOURCE_SHA={
    'managed':'5c56f1a8c3a7dddf96d88707e8b7066dbf1fc3ebfc14f67e837508421889e5e6',
    'feedback':'799b98616b0086b2ab7a4ec57f93a17c8ec8e44c1403c0ac43a06e412947a675'}
_LIVE_SOURCE_SHA={
    'managed':'0b2e41e55c4a48f221947c0e450a9606e5ffc7fd70879d2492b24daee65fb44f',
    'feedback':'961e781c389004a1c48b165b3346de2198a297df523a72dfb07a5c781122b6a7'}


def _read_bound(ref,*,json_content=True):
    root=Path(__file__).resolve().parents[2]
    if not isinstance(ref,dict)or set(ref)!={'path','sha256'}:raise ValueError('alias_derivation_binding_required')
    p=Path(ref['path'])
    if not p.is_absolute()or not p.resolve().is_relative_to(root):raise ValueError('alias_derivation_project_path_required')
    raw=p.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ref['sha256']:raise ValueError('alias_derivation_evidence_changed')
    return json.loads(raw)if json_content else raw


def derive_alias_validation(feedback_ref,expected,*,form_prepared_ref,submit_claim_ref,
                            code_manifest_ref,managed_source_ref,feedback_source_ref,
                            execution_approval_ref,execution_plan_ref,execution_state_ref):
    """Return a separate typed document; no original receipt, row or claim is written.

    Only the two explicitly reviewed legacy source hashes have the string/null
    semantics required here. This proves captured UI feedback, not acceptance,
    rejection by a server, React/chips state, or hidden alternatives.
    """
    return _derive_alias_validation(feedback_ref,expected,form_prepared_ref=form_prepared_ref,
        submit_claim_ref=submit_claim_ref,code_manifest_ref=code_manifest_ref,managed_source_ref=managed_source_ref,
        feedback_source_ref=feedback_source_ref,execution_approval_ref=execution_approval_ref,
        execution_plan_ref=execution_plan_ref,execution_state_ref=execution_state_ref,live=False)


def rebuild_live_validation(feedback_ref,expected,*,form_prepared_ref,submit_claim_ref,
                            code_manifest_ref,managed_source_ref,feedback_source_ref,
                            execution_approval_ref,execution_plan_ref,execution_state_ref):
    """Independently type a missing-rule result with all original live v2 fields.

    The observed field counts/click count are mandatory. Unlike the explicitly
    separate legacy function, no absent field is inferred from source semantics.
    Returns a document only; original receipt/unknown/claim are never updated.
    """
    return _derive_alias_validation(feedback_ref,expected,form_prepared_ref=form_prepared_ref,
        submit_claim_ref=submit_claim_ref,code_manifest_ref=code_manifest_ref,managed_source_ref=managed_source_ref,
        feedback_source_ref=feedback_source_ref,execution_approval_ref=execution_approval_ref,
        execution_plan_ref=execution_plan_ref,execution_state_ref=execution_state_ref,live=True)


def _derive_alias_validation(feedback_ref,expected,*,form_prepared_ref,submit_claim_ref,
                            code_manifest_ref,managed_source_ref,feedback_source_ref,
                            execution_approval_ref,execution_plan_ref,execution_state_ref,live):
    raw=_read_bound(feedback_ref);prepared=_read_bound(form_prepared_ref);claim=_read_bound(submit_claim_ref)
    manifest=_read_bound(code_manifest_ref)
    folder=Path(feedback_ref['path']).parent
    if (Path(feedback_ref['path']).name!='SUBMIT_RESPONSE.json'
            or Path(form_prepared_ref['path'])!=folder/'FORM_PREPARED.json'
            or Path(submit_claim_ref['path'])!=folder/'SUBMIT_CLAIM.json'
            or claim.get('command_id')!=folder.name or claim.get('automatic_retry')is not False
            or not isinstance(claim.get('generation'),int)or not claim.get('owner_id')):
        raise ValueError('alias_derivation_same_command_required')
    intent=claim.get('intent',{})
    if any(intent.get(k)!=expected[k]for k in ('book_id','book_name','alias')):
        raise ValueError('alias_derivation_claim_subject_mismatch')
    request=_read_bound(claim.get('request'))
    if (request.get('schema')!='fanqie_promotion_apply_request/v1'
            or any(request.get(k)!=v for k,v in intent.items())):
        raise ValueError('alias_derivation_request_subject_mismatch')
    authority=_read_bound(request.get('authorization'))
    if authority.get('intent')!=intent or authority.get('max_submissions')!=1 or authority.get('confirmed_by')!='user':
        raise ValueError('alias_derivation_original_authorization_required')
    approval=_read_bound(execution_approval_ref);plan=_read_bound(execution_plan_ref);state=_read_bound(execution_state_ref)
    last=state.get('last_application',{});lastresult=last.get('result',{})
    approval_schema='fanqie_postclick_binding_continuation_approval/v1'if live else'fanqie_alias_flow_search_scope_fix_approval/v1'
    if (approval.get('schema')!=approval_schema
            or approval.get('source_manifest')!=code_manifest_ref or approval.get('continuation_spec')!=plan.get('spec')
            or plan.get('schema')!='fanqie_alias_flow/v1'or state.get('schema')!='fanqie_alias_flow/v1'
            or state.get('spec')!=plan.get('spec')or last.get('command_id')!=claim['command_id']
            or last.get('alias')!=expected['alias']or lastresult.get('feedback_ref')!=feedback_ref
            or lastresult.get('form_prepared')!=form_prepared_ref
            or len([o for o in state.get('operations',[])if o.get('kind')=='apply'and o.get('command_id')==claim['command_id']
                and o.get('alias')==expected['alias']])!=1):
        raise ValueError('alias_derivation_execution_batch_unbound')
    spec=_read_bound(plan['spec'])
    if (any(spec.get('book',{}).get(k)!=intent.get(k)for k in ('book_id','book_name','promotion_path','publish_type'))
            or any(spec.get('resource_binding',{}).get(k)!=intent.get(k)for k in ('resource_id','binding_version','platform_identity_key'))
            or expected['alias']not in spec.get('aliases',[])):
        raise ValueError('alias_derivation_flow_subject_mismatch')
    if manifest.get('schema')!='fanqie_alias_flow_source_seal/v1':raise ValueError('alias_derivation_original_source_manifest_required')
    for key,ref in [('managed',managed_source_ref),('feedback',feedback_source_ref)]:
        _read_bound(ref,json_content=False)
        filename='fanqie_managed_promotion_v1.py'if key=='managed'else'fanqie_form_feedback_v1.py'
        canonical=Path(__file__).resolve().parents[2]/('src/operations_accounts'if key=='managed'else'src/platform_adapter')/filename
        if ref['sha256']!=(_LIVE_SOURCE_SHA if live else _LEGACY_SOURCE_SHA)[key]or not any(v=={'path':str(canonical),'sha256':ref['sha256']}for v in manifest.get('sources',[])):
            raise ValueError('alias_derivation_reviewed_legacy_source_required')
    h=prepared.get('form_feedback',{});baseline=h.get('baseline',{});pre=h.get('pre_click',{})
    if (prepared.get('ready')is not True or prepared.get('submitted')is not False or h.get('clicked')is not False
            or not _book_scope(baseline,expected)or baseline.get('current_alias')!=''
            or not _one_button(baseline,enabled=False)or not _messages_empty(baseline)
            or not _same_subject(pre,expected)or not _one_button(pre,enabled=True)or not _messages_empty(pre)
            or pre.get('phase')!='final_fresh'or pre!=h.get('latest')
            or pre.get('observed_at',0)>claim.get('at_epoch',0)
            or claim.get('at_epoch',0)>raw.get('form_feedback',{}).get('pre_click',{}).get('observed_at',0)):
        raise ValueError('alias_derivation_prepared_controlled_transition_required')
    readings=prepared.get('readback',{}).get('observations',[])
    if not any(s.get('alias_value')==expected['alias']and s.get('alias_input_count')==1 and s.get('alias_attached')is True
               and s.get('book_identity_verified')is True and s.get('mismatch_fields')==[] for s in readings):
        raise ValueError('alias_derivation_prepared_readback_required')
    value=_cleared_value(raw,expected,legacy=not live)
    if live:value['alias_binding']['evidence_mode']='source_bound_live_rule_derivation'
    refs=dict(feedback=feedback_ref,form_prepared=form_prepared_ref,submit_claim=submit_claim_ref,
        code_manifest=code_manifest_ref,managed_source=managed_source_ref,feedback_source=feedback_source_ref,
        execution_approval=execution_approval_ref,execution_plan=execution_plan_ref,execution_state=execution_state_ref)
    return dict(raw,schema='fanqie_alias_validation_derivation/v2'if live else'fanqie_alias_validation_derivation/v1',ready=False,result='alias_validation_failed',
        reason='alias_validation_failed',alias_validation=value,alias_reusable=False,retry_with_new_alias=True,
        original_result=raw.get('result'),derivation=dict(schema='fanqie_postclick_alias_derivation/v2'if live else'fanqie_postclick_alias_derivation/v1',
            evidence=refs,original_command_id=claim['command_id'],original_records_changed=False,
            legacy_missing_observation_fields_preserved=not live,server_response_evidence=False,platform_business_outcome_verified=False))


def _validate_cleared_validation(feedback,expected):
    if feedback.get('derivation')is not None:
        d=feedback['derivation'];refs=d.get('evidence',{})
        builder=rebuild_live_validation if d.get('schema')=='fanqie_postclick_alias_derivation/v2'else derive_alias_validation
        rebuilt=builder(refs.get('feedback'),expected,
            form_prepared_ref=refs.get('form_prepared'),submit_claim_ref=refs.get('submit_claim'),
            code_manifest_ref=refs.get('code_manifest'),managed_source_ref=refs.get('managed_source'),feedback_source_ref=refs.get('feedback_source'),
            execution_approval_ref=refs.get('execution_approval'),execution_plan_ref=refs.get('execution_plan'),execution_state_ref=refs.get('execution_state'))
        if feedback!=rebuilt:raise ValueError('alias_derivation_document_changed')
        return rebuilt['alias_validation']
    value=_cleared_value(feedback,expected)
    if (feedback.get('result')!='alias_validation_failed'or feedback.get('retry_with_new_alias')is not True
            or feedback.get('alias_reusable')is not False or feedback.get('alias_validation')!=value):
        raise ValueError('alias_clear_typed_validation_mismatch')
    return value


def validate_alias_validation(feedback,expected):
    try:return _validate_alias_validation(feedback,expected)
    except (TypeError,KeyError,AttributeError,OverflowError)as error:
        raise ValueError('alias_validation_shape_invalid')from error


def confirmed_alias_validation(feedback,expected):
    try:validate_alias_validation(feedback,expected)
    except (ValueError,TypeError,KeyError):return False
    return True
