"""New-authority replacement forms after native cleanup; old once locks remain.

Only the explicitly preferred same keyword is supported here. A different
keyword requires a separately verified public-caption contract, not this path.
"""
from datetime import datetime
import json
from pathlib import Path
import time

from .fanqie_cleanup_rebind_v1 import need,read,save,reference,_PUBLIC_DOM,checked_snapshot
from . import fanqie_new_post_backfill_v1 as old_form
from src.services import fanqie_promotion_identity_v2 as native
from src.services import fanqie_replacement_snapshot_v1 as anchor


def source_paths(action):
    from src.operations_accounts import fanqie_cleanup_rebind_v1 as runtime
    root=Path(__file__).resolve().parents[2]
    return runtime.source_paths(action)+tuple(root/p for p in ('src/platform_adapter/fanqie_promotion_preflight_v1.py','src/platform_adapter/fanqie_form_feedback_v1.py'))+(anchor.SOURCES if action in {'bind_new_publication','inspect_replacement_editor'} else ())


def _anchor_mode(request):
    version=request.get('replacement_snapshot_version')
    need(version in (None,'anchor_v1'),'replacement_snapshot_version_not_supported')
    return version=='anchor_v1'


def _checked_snapshot(ref,request):
    if not _anchor_mode(request):return checked_snapshot(ref,request)
    value=anchor.validate_snapshot(read(ref),require_fresh=True)
    evidence=read(value['evidence_ref'])
    need(evidence['identity_observation']==request['replacement_identity_observation']
         and all(value.get(k)==request[k] for k in native.SCOPE),'replacement_anchor_scope_changed')
    return value


def _identity(snapshot,row):
    return anchor.native_identity(snapshot,row) if snapshot.get('schema')==anchor.SCHEMA else native.native_identity(snapshot,row)


def _assert_publishable(snapshot,row):
    return anchor.assert_publishable(snapshot,row) if snapshot.get('schema')==anchor.SCHEMA else native.assert_publishable(snapshot,row)


def cleanup_receipt(request):
    if request.get('cleanup_reconciliation') is not None:
        result=_native_deletion_receipt(request)
        observed=read(request['cleanup_state_result']);receipt=read(request['cleanup_state_receipt']);source_request=read(observed['request'])
        native_result=observed.get('result',{}).get('native_result',{})
        need(observed.get('schema')=='fanqie_cleanup_rebind_command_result/v1' and observed.get('broker_state')=='succeeded'
             and observed.get('result',{}).get('status')=='cleanup_state_observed' and source_request.get('action')=='inspect_cleanup_state'
             and source_request.get('authority')==request['authority'] and all(source_request.get(k)==request[k] for k in native.SCOPE)
             and receipt==dict(schema='fanqie_cleanup_rebind_result_binding/v1',request=observed['request'],subject=observed['subject'],result=request['cleanup_state_result'])
             and native_result.get('click_count')==0 and native_result.get('delete_claims_created')==0,'read_only_cleanup_state_required')
        targets=native_result.get('targets',[]);original_request=read(result['request'])
        need(source_request.get('targets')==original_request.get('targets') and len(targets)==len(source_request['targets'])
             and all(t.get('native_delete_available') is False and t.get('target') in source_request['targets'] for t in targets)
             and native_result.get('old_records_changed') is False,'remaining_native_controls_must_be_read')
        old=[t for t in targets if t.get('target',{}).get('native_identity')==request['replaces_native_identity']]
        need(len(old)==1 and old[0].get('live_target',{}).get('alias_status')=='已删除','read_only_softdelete_state_required')
        state=native.validate_snapshot(read(native_result['native_snapshot']))
        need(any(r.get('identity_status')=='verified' and r.get('native_record_id')==request['replaces_native_identity']['native_record_id'] and r.get('alias_status')=='已删除' for r in state['rows']),
             'native_current_deleted_state_required')
        return result
    result=read(request['cleanup_result']);receipt=read(request['cleanup_receipt']);old_request=read(result['request'])
    need(result.get('schema')=='fanqie_cleanup_rebind_command_result/v1' and result.get('broker_state')=='succeeded'
         and result.get('result',{}).get('status')=='cleanup_observed' and old_request.get('authority')==request['authority']
         and all(old_request.get(k)==request[k]==result.get('subject',{}).get(k) for k in native.SCOPE)
         and receipt==dict(schema='fanqie_cleanup_rebind_result_binding/v1',request=result['request'],subject=result['subject'],result=request['cleanup_result']),
         'exact_cleanup_receipt_required')
    original=request['replaces_native_identity'];matches=[r for r in result['result']['native_result']['results'] if r.get('target',{}).get('native_identity')==original]
    need(original.get('platform_identity_key')==request['platform_identity_key'] and original.get('native_kind')=='promotion_alias'
         and isinstance(original.get('native_record_id'),str) and original['native_record_id'].isdigit(),'original_native_scope_changed')
    need(len(matches)==1 and matches[0].get('status')=='deleted_not_observed_in_fresh_native_list'
         and all(matches[0]['target'].get(k)==request[k] for k in ('book_id','book_name','alias','publish_type')),'original_alias_not_deleted')
    after=native.validate_snapshot(read(matches[0]['after_snapshot']))
    need(not any(r.get('native_record_id')==original['native_record_id'] and r.get('identity_status')=='verified' for r in after['rows']),
         'original_native_alias_still_observed')
    return result


def _native_deletion_receipt(request):
    """Recompute a separate observed soft-delete without changing failed writer."""
    from .fanqie_cleanup_rebind_v1 import native_matches
    report=read(request['cleanup_reconciliation']);need(report.get('schema')=='fanqie_native_deletion_reconciliation/v1'
        and report.get('accepted') is True and report.get('native_deleted') is True,'typed_native_deletion_required')
    result=read(report['result']);receipt=read(report['result_binding']);old_request=read(report['request']);subject=report['subject'];target=report['target']
    need(result.get('schema')=='fanqie_cleanup_rebind_command_result/v1' and result.get('broker_state')=='failed'
         and result.get('result',{}).get('reason')=='native_target_changed' and result.get('request')==report['request'] and result.get('subject')==subject
         and subject.get('task_id')==report['command_id'] and old_request.get('authority')==request['authority']
         and receipt==dict(schema='fanqie_cleanup_rebind_result_binding/v1',request=report['request'],subject=subject,result=report['result'])
         and all(subject.get(k)==old_request.get(k)==request[k] for k in native.SCOPE)
         and target.get('native_identity')==request['replaces_native_identity'] and all(target.get(k)==request[k] for k in ('book_id','book_name','alias','publish_type')),
         'original_native_delete_receipt_changed')
    before=native.validate_snapshot(read(report['before_snapshot']));after=native.validate_snapshot(read(report['after_snapshot']))
    before_rows=native_matches(before,target);after_rows=native_matches(after,target,after_delete=True)
    claim=read(report['claim']);preflight=read(report['preflight']);confirm=read(report['confirm_intent']);modal=read(report['modal'])
    need(len(before_rows)==len(after_rows)==1 and before_rows[0]['alias_status']=='生效中' and after_rows[0]['alias_status']=='已删除'
         and read(before['evidence_ref'])['managed_subject']==subject==read(after['evidence_ref'])['managed_subject']
         and all(before.get(k)==after.get(k)==request[k] for k in native.SCOPE)
         and claim.get('schema')=='fanqie_cleanup_delete_claim/v1' and claim.get('request')==report['request'] and claim.get('subject')==subject
         and claim.get('target')==target and claim.get('preflight')==report['preflight']
         and preflight.get('request')==report['request'] and preflight.get('subject')==subject and preflight.get('target')==target
         and preflight.get('native_snapshot')==report['before_snapshot'] and preflight.get('modal')==report['modal']
         and modal.get('eligible') is True and modal.get('expected_content') is True
         and confirm==dict(claim=report['claim'],confirmation_limit=1)
         and before['observed_at']<=claim['at_epoch']<=after['observed_at'],'observed_native_softdelete_required')
    sources=read(report['source_seal'])['sources']
    for copy in report.get('actual_source_snapshots',[]):
        need(copy['original'] in sources and reference(copy['snapshot']['path'])==copy['snapshot'] and copy['snapshot']['sha256']==copy['original']['sha256'],
             'historical_deletion_source_changed')
    need(len(report.get('actual_source_snapshots',[]))==len(sources),'historical_deletion_sources_required')
    return result


def _deleted_original(row,request):
    return (row.get('identity_status')=='verified' and row.get('native_record_id')==request['replaces_native_identity']['native_record_id']
            and row.get('alias_status')=='已删除' and all(row.get(k)==request[k] for k in ('book_id','book_name','alias','publish_type')))


def validate_action_request(request,authority):
    from src.operations_accounts import fanqie_new_publication_backfill_v1 as files
    from .fanqie_cleanup_rebind_v1 import reference
    root=Path(__file__).resolve().parents[2]
    seal=read(request['source_seal']);source_map={Path(r['path']).resolve():r for r in seal['sources']}
    for dependency in ('src/platform_adapter/fanqie_promotion_preflight_v1.py','src/platform_adapter/fanqie_form_feedback_v1.py'):
        path=root/dependency;need(source_map.get(path)==reference(path),'replacement_leaf_source_changed')
    need('known_preconfirm_failure' not in request,'cleanup_successor_field_not_applicable_to_forms')
    cleanup_receipt(request)
    need(request.get('application_limit')==1 if request['action']=='replacement_apply' else request.get('backfill_limit')==(0 if request['action']=='inspect_replacement_editor' else 1),'single_replacement_action_required')
    if request['action'] in {'bind_new_publication','inspect_replacement_editor'}:
        verified=read(request['verified_publication']);result=read(verified['verification_result']);receipt=read(verified['verification_receipt'])
        files.refs(verified);files.refs(result)
        need(verified.get('schema')=='verified_declared_publication/v1' and verified.get('account_uuid')==authority['account_uuid']
             and verified.get('expected_public_uid')==authority['expected_public_uid'] and verified.get('canonical_url')==authority['new_link_to_bind']
             and all(verified.get(k) is True for k in ('post_verified','full_metadata_verified','numeric_duration_verified','native_AI_statement_verified'))
             and result.get('external_publication_verified') is True and result.get('full_metadata_verified') is True
             and receipt==dict(schema='manual_republication_result_binding/v10',plan=result['plan'],claim=result['claim'],result=verified['verification_result']),
             'original_verified_new_publication_required')
        metadata=read(verified['metadata']);need(authority['preferred_recreated_alias'] in metadata['description'] and '《'+request['book_name']+'》' in metadata['description'],'caption_must_still_match_keyword')
        new=request['new_publication'];need(new==dict(post_id=verified['post_id'],canonical_url=verified['canonical_url'],
            publish_date=datetime.fromisoformat(verified['published_at']).date().isoformat(),native_created_epoch=verified['native_created_epoch']),
            'native_publication_date_changed')
        readonly=request['action']=='inspect_replacement_editor';add=request.get('add_empty_douyin_draft_row') is True
        need(not add or (not readonly and request.get('known_backfill_preparation_failure') is not None and request.get('empty_douyin_draft_add_limit')==1),'explicit_first_douyin_row_scope_required')
        need(request.get('remove_empty_other_draft_row') is (not readonly and not add) and request.get('empty_draft_removal_limit')==(0 if readonly or add else 1),'explicit_empty_draft_row_scope_required')
        if add:_validate_empty_editor_review(request)
        need(request.get('new_native_identity',{}).get('native_record_id')!=request['replaces_native_identity']['native_record_id'],'distinct_new_native_alias_required')
        frozen=native.validate_snapshot(read(request['replacement_snapshot']))
        if _anchor_mode(request):
            for path in anchor.SOURCES:need(source_map.get(path)==reference(path),'replacement_anchor_source_changed')
            seed=anchor.validate_identity_observation(request['replacement_identity_observation'])
            need(seed['after_snapshot']==request['replacement_snapshot'] and seed['native_identity']==request['new_native_identity']
                 and seed['old_native_identity']==request['replaces_native_identity']
                 and all(seed.get(k)==request[k] for k in ('book_id','book_name','alias','publish_type'))
                 and all(seed['subject'].get(k)==request[k] for k in native.SCOPE)
                 and seed['dom_status']=='生效中' and seed['book_status']=='可用','replacement_anchor_seed_subject_changed')
        else:
            matches=[r for r in frozen['rows'] if r.get('identity_status')=='verified' and r.get('native_record_id') and native.native_identity(frozen,r)==request['new_native_identity']]
            need(len(matches)==1 and all(matches[0].get(k)==request[k] for k in ('book_id','book_name','alias','publish_type')),'replacement_snapshot_subject_changed')


def validate_preflight(request,proof):
    target={k:request[k] for k in ('book_id','book_name','alias','publish_type')};need(proof.get('target')==target,'replacement_preflight_target_changed')
    directory=Path(request['authority']['path']).resolve().parent
    if request['action']=='replacement_apply':
        prepared=read(proof['form_prepared']);before=checked_snapshot(proof['native_snapshot'],request)
        need(proof.get('schema')=='fanqie_replacement_apply_preflight/v1' and prepared.get('ready') is True
             and proof.get('cleanup_result')==request.get('cleanup_result') and proof.get('cleanup_reconciliation')==request.get('cleanup_reconciliation')
             and proof.get('intent',{}).get('alias')==request['alias']
             and not any(r.get('book_id')==request['book_id'] and r.get('alias')==request['alias'] and not _deleted_original(r,request) for r in before['rows']),
             'fresh_replacement_application_required')
        return directory/'REPLACEMENT_APPLY_CLAIM.json','fanqie_replacement_apply_claim/v1'
    need(proof.get('schema')=='fanqie_replacement_backfill_preflight/v1' and proof.get('new_publication')==request['new_publication']
         and proof.get('native_identity')==request['new_native_identity'],'replacement_backfill_preflight_required')
    prep=proof.get('preparation',{})
    if request.get('add_empty_douyin_draft_row') is True:
        need(proof.get('empty_other_row_removed') is False and prep.get('mode')=='add_one_empty_douyin_row' and prep.get('add_row_clicks')==1
             and prep.get('remove_row_clicks')==0 and read(prep['initial_form']).get('input_count')==0
             and read(prep['add_boundary']).get('eligible') is True and read(prep['add_boundary']).get('same_node') is True
             and read(prep['add_intent']).get('add_limit')==1,'first_empty_douyin_row_preparation_required')
    else:need(proof.get('empty_other_row_removed') is True and prep.get('mode')=='remove_one_empty_other_row'
              and prep.get('add_row_clicks')==0 and prep.get('remove_row_clicks')==1,'empty_other_row_preparation_required')
    _valid_form(read(prep['blank_form']),request,blank=True)
    snapshot=_checked_snapshot(proof['native_snapshot'],request);row=_active_row(snapshot,request,exact_identity=request['new_native_identity']);_assert_publishable(snapshot,row)
    need(snapshot.get('managed_subject',read(snapshot['evidence_ref']).get('managed_subject'))==proof.get('subject'),'replacement_live_preflight_owner_changed')
    _valid_form(proof['actual_form'],request)
    return directory/'REPLACEMENT_BACKFILL_SUBMIT_CLAIM.json','fanqie_replacement_backfill_claim/v1'


def _validate_empty_editor_review(request):
    review=read(request['empty_editor_review']);result=read(review['result']);binding=read(review['result_binding']);old=read(result['request']);value=result['result']['native_result']
    need(review.get('schema')=='fanqie_first_editor_actual_inspection_review/v1' and old.get('action')=='inspect_replacement_editor'
         and old.get('read_only') is True and result.get('broker_state')=='succeeded' and result['result'].get('status')=='replacement_editor_observed'
         and binding==dict(schema='fanqie_cleanup_rebind_result_binding/v1',request=result['request'],subject=result['subject'],result=review['result'])
         and value.get('inspection')==review['inspection'] and value.get('fields_written') is False and value.get('submitted') is False
         and value.get('add_row_clicks')==value.get('delete_row_clicks')==value.get('submission_claims_created')==0
         and value.get('native_identity')==request['new_native_identity']
         and all(old.get(k)==request[k] for k in (*native.SCOPE,'authority','book_id','book_name','alias','new_publication','new_native_identity')),'actual_empty_editor_receipt_required')
    evidence=read(review['inspection']);samples=evidence['samples'];need(len(samples)>=2 and samples[-1]==samples[-2] and evidence.get('stable') is True,'actual_empty_editor_not_stable')
    current=samples[-1]['structure'];need(current.get('scope_count')==1 and current.get('inputs')==[],'actual_editor_not_initially_empty')
    for label in ('抖音发文','其他平台发文'):
        sections=[s for s in current['sections'] if s['label']==label];need(len(sections)==1,'actual_empty_section_not_unique')
        nodes=[a for a in sections[0]['ancestors'] if 'arco-form-item' in a['node']['class_name'].split()]
        need(nodes and nodes[0]['inputs']==[] and len(nodes[0]['controls'])==1 and nodes[0]['controls'][0]['text']=='添加发文'
             and nodes[0]['controls'][0]['tag']=='button' and nodes[0]['controls'][0]['type']=='button' and nodes[0]['controls'][0]['disabled'] is False,'actual_empty_section_add_not_verified')


def _active_row(snapshot,request,exact_identity=None):
    matches=[r for r in snapshot['rows'] if all(r.get(k)==request[k] for k in ('book_id','book_name','alias','publish_type')) and not _deleted_original(r,request)]
    need(len(matches)==1 and matches[0].get('identity_status')=='verified','unique_native_replacement_required')
    row=matches[0];need(_identity(snapshot,row)['native_record_id']!=request['replaces_native_identity']['native_record_id'],'old_native_identity_cannot_be_reused')
    if exact_identity is not None:need(_identity(snapshot,row)==exact_identity,'new_native_identity_changed')
    _assert_publishable(snapshot,row);return row


def _two_input_script(target,element=None):
    script=old_form.form_script(target,element)
    start=script.index('const valid=');end=script.index(';',start)
    # The original observed form projection is reused; only the explicitly
    # removed empty draft row changes its valid input count from four to two.
    replacement="const valid=!!scope&&inputs.length===2&&links.length===1&&!!row&&active(link)&&active(day)&&others.length===0"
    return script[:start]+replacement+script[end:]


def _valid_form(form,request,blank=False):
    new=request['new_publication'];need(form.get('eligible') is True and form.get('scope_count')==1 and form.get('input_count')==2
        and form.get('identity')==dict(book_name=request['book_name'],alias=request['alias'],aigc=True) and form.get('other_inputs')==[],
        'replacement_native_form_not_unique')
    submit=form.get('submit',{});enabled=submit.get('enabled')
    need(form.get('date',{}).get('value')==('' if blank else new['publish_date'])
         and form.get('link',{}).get('value')==('' if blank else new['canonical_url']) and type(enabled) is bool
         and submit==dict(unique_count=1,tag='button',type='button',text='提交',enabled=enabled if blank else True),'replacement_native_form_readback_mismatch')


def _opener_script(target,token,label='回填发文',*,element=False):
    return ('el => {' if element else '() => {')+_PUBLIC_DOM+'const target='+json.dumps(target,ensure_ascii=False)+',key='+json.dumps(token)+',label='+json.dumps(label,ensure_ascii=False)+',boundary='+json.dumps(element)+r''';
 if(!allowed()||location.pathname!=='/page/promotion-list')return {eligible:false};
 const choose=()=>{
 const tables=[...document.querySelectorAll('table')].filter(visible),table=tables.length===1?tables[0]:null;
 const headers=table?[...table.querySelectorAll('thead th')].map(text):[],required=['关键词','书本信息','发文类型','别名状态','书籍状态','发文详情'];
 if(required.some(k=>headers.filter(x=>x===k).length!==1)||[...document.querySelectorAll('.arco-spin-loading,.arco-spin-loading-layer,[aria-busy="true"]')].some(visible))return {eligible:false};
 const all=table?[...table.querySelectorAll('tbody tr')]:[],rows=all.filter(r=>{const cells=[...r.children].filter(c=>c.tagName==='TD');if(cells.length!==headers.length)return false;
  const cell=k=>text(cells[headers.indexOf(k)]),ids=(cell('书本信息').match(/ID\s*[:：]?\s*(\d{10,24})(?!\d)/ig)||[]).map(s=>s.match(/\d{10,24}/)[0]);
  return visible(r)&&cell('关键词')===target.alias&&JSON.stringify(ids)===JSON.stringify([target.book_id])
   &&[...r.querySelectorAll('[class*="book-name"]')].filter(visible).map(text).join('\n')===target.book_name&&cell('发文类型')==='AIGC'&&cell('别名状态')==='生效中'&&cell('书籍状态')==='可用';});
 const r=rows.length===1?rows[0]:null,buttons=r?[...r.querySelectorAll('div.link,span.arco-link,button')].filter(e=>visible(e)&&text(e)===label):[],b=buttons.length===1?buttons[0]:null;
 const detail=r?text([...r.children].filter(c=>c.tagName==='TD')[headers.indexOf('发文详情')]):'';
 const filled=/^已填写\s*[（(]\s*[1-9]\d*\s*条\s*[）)]$/.test(detail);
 const safe=!!b&&!b.matches(':disabled,[aria-disabled="true"],[inert]')&&b.getAttribute('tabindex')!=='-1'&&!/disabled/.test(b.className||'')
  &&getComputedStyle(b).pointerEvents!=='none'&&getComputedStyle(b).cursor==='pointer'
  &&(label!=='查看'||(filled&&eligible(b)))&&!b.querySelector('button,a,input,select,textarea,[role="button"],[role="link"]');
 return {eligible:!!safe,r,b,row:r?all.indexOf(r):null,button_index:r?[...r.querySelectorAll('div.link,span.arco-link,button')].indexOf(b):null,filled_status:detail};};
 const chosen=choose();
 if(!boundary){if(chosen.eligible)window[key]={row:chosen.r,button:chosen.b};}
 else {
  const record=window[key];chosen.eligible=chosen.eligible&&!!record&&record.row===chosen.r&&record.button===chosen.b&&el===record.button;
  if(chosen.eligible){let used=false;const gate=e=>{if(!e.composedPath().includes(el))return;
    const fresh=choose(),ok=!used&&fresh.eligible&&fresh.r===record.row&&fresh.b===el;
    used=true;window.removeEventListener('click',gate,true);if(!ok){e.preventDefault();e.stopImmediatePropagation();}};
   window.addEventListener('click',gate,true);}
 }
 return {eligible:!!chosen.eligible,row:chosen.row,button_index:chosen.button_index,filled_status:chosen.filled_status};}'''


def _editor_inventory_script(target):
    """Visible public drawer structure; never reads fields or framework state."""
    return '() => {'+_PUBLIC_DOM+'const target='+json.dumps(target,ensure_ascii=False)+r''';
 if(!allowed()||location.pathname!=='/page/promotion-list')return {blocked:true};
 const surfaces=[...document.querySelectorAll('.arco-drawer,.arco-modal,[role="dialog"]')].filter(e=>visible(e)&&text(e).includes(target.book_name)&&text(e).includes(target.alias)&&text(e).includes('AIGC'));
 const minimal=surfaces.filter(e=>!surfaces.some(other=>other!==e&&e.contains(other))),scope=minimal.length===1?minimal[0]:null;
 const projection=e=>({...meta(e),rect:{x:e.getBoundingClientRect().x,y:e.getBoundingClientRect().y,width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height}});
 const controls=e=>[...e.querySelectorAll('button,a,[role="button"],div.link,span.arco-link')].filter(visible).map(projection);
 const inputs=e=>[...e.querySelectorAll('input:not([type="hidden"]),textarea,select')].filter(visible).map(i=>({tag:i.tagName.toLowerCase(),type:i.type||'',placeholder:i.getAttribute('placeholder')||'',class_name:(i.className||'').slice(0,240),disabled:i.disabled===true,read_only:i.readOnly===true}));
 const sections=[];
 if(scope)for(const label of ['抖音发文','其他平台发文']){
  const leaves=[...scope.querySelectorAll('*')].filter(e=>visible(e)&&text(e)===label&&![...e.children].some(c=>visible(c)&&text(c)===label));
  for(const leaf of leaves){const ancestors=[];for(let p=leaf,d=0;p&&p!==scope&&d<7;p=p.parentElement,d++)ancestors.push({depth:d,node:projection(p),inputs:inputs(p),controls:controls(p)});
   sections.push({label,node:projection(leaf),ancestors});}}
 const nodes=scope?[...scope.querySelectorAll('*')].filter(visible):[];
 return {schema:'fanqie_replacement_editor_visible_inventory/v1',location:{origin:location.origin,path:location.pathname},scope_count:minimal.length,
  sections,controls:scope?controls(scope):[],inputs:scope?inputs(scope):[],nodes:nodes.slice(0,250).map(projection),truncated:nodes.length>250,
  input_values_read:false,framework_state_read:false,fields_written:false,add_row_clicks:0,delete_row_clicks:0,submitted:false};}'''


def _empty_draft_script(target):
    return 'el=>{'+_PUBLIC_DOM+'const target='+json.dumps(target,ensure_ascii=False)+r''';
 const drawer=el.closest('.arco-drawer'),exact=drawer&&visible(drawer)&&text(drawer).includes(target.book_name)&&text(drawer).includes(target.alias)&&text(drawer).includes('AIGC');
 const inputs=drawer?[...drawer.querySelectorAll('input')].filter(visible):[],other=inputs.filter(e=>e.getAttribute('placeholder')==='输入发文链接'),link=other.length===1?other[0]:null;
 let row=null;for(let p=link?.parentElement;p&&p!==drawer;p=p.parentElement){const ins=[...p.querySelectorAll('input')].filter(visible),bs=[...p.querySelectorAll('button')].filter(b=>visible(b)&&text(b)==='删除');
  if(ins.length===2&&ins.includes(link)&&ins.filter(i=>i.getAttribute('placeholder')==='选择发文日期').length===1&&bs.length===1){row=p;break;}}
 const ins=row?[...row.querySelectorAll('input')].filter(visible):[],bs=row?[...row.querySelectorAll('button')].filter(b=>visible(b)&&text(b)==='删除'):[];
 let section=null;for(let p=row?.parentElement;p&&p!==drawer;p=p.parentElement){if(text(p).includes('其他平台发文')&&!text(p).includes('抖音发文')){section=p;break;}}
 const valid=!!exact&&inputs.length===4&&link===el&&!!row&&section&&ins.every(i=>i.value==='')
  &&bs[0]?.type==='button'&&!bs[0].disabled&&!row.querySelector('a[href]');
 return {eligible:!!valid,empty_inputs:ins.length===2&&ins.every(i=>i.value===''),native_row_remove_is_draft_only:!!valid};}'''


def _add_douyin_script(target,token,*,element=False):
    return ('el=>{' if element else '()=>{')+_PUBLIC_DOM+'const target='+json.dumps(target,ensure_ascii=False)+',key='+json.dumps(token)+',boundary='+json.dumps(element)+r''';
 const choose=()=>{
  if(!allowed()||location.pathname!=='/page/promotion-list')return {eligible:false};
  const drawers=[...document.querySelectorAll('.arco-drawer')].filter(e=>visible(e)&&text(e).includes(target.book_name)&&text(e).includes(target.alias)&&text(e).includes('AIGC'));
  const scope=drawers.length===1?drawers[0]:null;if(!scope)return {eligible:false};
  const section=label=>{const leaves=[...scope.querySelectorAll('*')].filter(e=>visible(e)&&text(e)===label&&![...e.children].some(c=>visible(c)&&text(c)===label));
   const rows=leaves.map(e=>e.closest('.arco-form-item.arco-form-layout-vertical')).filter(Boolean);return rows.length===1?rows[0]:null;};
  const dy=section('抖音发文'),other=section('其他平台发文'),inputs=[...scope.querySelectorAll('input,textarea,select')].filter(visible);
  const buttons=dy?[...dy.querySelectorAll('button')].filter(e=>visible(e)&&text(e)==='添加发文'):[],button=buttons.length===1?buttons[0]:null;
  const ok=!!dy&&!!other&&dy!==other&&!dy.contains(other)&&!other.contains(dy)&&inputs.length===0
   &&!!button&&button.type==='button'&&!button.matches(':disabled,[aria-disabled="true"],[inert]')&&getComputedStyle(button).pointerEvents==='auto'
   &&button.classList.contains('text-btn-DGPBPp')&&button.classList.contains('add-btn-DErxLi')
   &&[...other.querySelectorAll('button')].filter(e=>visible(e)&&text(e)==='添加发文').length===1;
  return {eligible:!!ok,scope,dy,other,button,button_index:button?[...scope.querySelectorAll('button')].filter(visible).indexOf(button):null};};
 const found=choose();let same=null;
 if(!boundary){if(found.eligible)window[key]={scope:found.scope,section:found.dy,button:found.button};}
 else {const record=window[key];same=!!record&&found.eligible&&record.scope===found.scope&&record.section===found.dy&&record.button===el&&el===found.button;
  found.eligible=!!same;if(same){let used=false;const listener=e=>{if(!e.composedPath().includes(el))return;
    const current=choose(),ok=!used&&current.eligible&&current.scope===record.scope&&current.dy===record.section&&current.button===el;
    used=true;window.removeEventListener('click',listener,true);if(!ok){e.preventDefault();e.stopImmediatePropagation();}};window.addEventListener('click',listener,true);}}
 const projection=e=>e?({...meta(e),rect:{x:e.getBoundingClientRect().x,y:e.getBoundingClientRect().y,width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height}}):null;
 return {schema:'fanqie_empty_douyin_add_boundary/v1',eligible:!!found.eligible,same_node:same,button_index:found.button_index,section_label:'抖音发文',
  scope_count:found.scope?1:0,input_count:found.scope?[...found.scope.querySelectorAll('input,textarea,select')].filter(visible).length:null,
  button:projection(found.button),section:projection(found.dy),other_inputs:found.other?[...found.other.querySelectorAll('input,textarea,select')].filter(visible).length:null};}'''


def _empty_remove_boundary(target):
    script=_empty_draft_script(target).replace('link===el','bs[0]===el')
    marker='return {eligible:!!valid,'
    need(script.count(marker)==1,'empty_row_projection_source_changed')
    return script.replace(marker,r'''if(valid){const listener=e=>{if(!e.composedPath().includes(el))return;
      if(!row.isConnected||!drawer.isConnected||!row.contains(el)||ins.some(i=>!i.isConnected||i.value!=='')||
         [...drawer.querySelectorAll('input')].filter(visible).length!==4){e.preventDefault();e.stopImmediatePropagation();}};
      window.addEventListener('click',listener,true);}
     return {eligible:!!valid,''')


def run_action(page,*,request,request_ref,subject,guard,evidence_directory,refresh_native_snapshot,navigate,claim_submission):
    """Only one named replacement action on the caller's original managed Page."""
    import secrets
    from src.operations_accounts import fanqie_managed_promotion_v1 as managed
    from .fanqie_exact_book_locator_v1 import locate_exact_book
    from .fanqie_filled_details_controls_v2 import BODY_JS
    from .fanqie_backfill_editor_inspection_v1 import opener_script,editor_script
    need(read(request_ref)==request,'request_changed');folder=Path(evidence_directory);folder.mkdir(parents=True,exist_ok=True)
    raw=getattr(page,'page',page);original,tab=getattr(raw,'_session',None),getattr(raw,'tab_id',None);deadline=time.monotonic()+420;claim=None;clicked=False
    target={k:request[k] for k in ('book_id','book_name','alias')};full_target=dict(target,publish_type=request['publish_type'])
    def check():
        need(time.monotonic()<deadline,'replacement_deadline');guard();need(reference(request_ref['path'])==request_ref,'request_changed')
        need(getattr(raw,'_session',None) is original and getattr(raw,'tab_id',None)==tab,'original_page_changed')
    def rpc(fn,*args,**kwargs):check();value=fn(*args,**kwargs);check();return value
    def keep(name,value):return save(folder/(name+'.json'),value)
    before_ref=refresh_native_snapshot('before_'+request['action'])
    if request['action'] in {'bind_new_publication','inspect_replacement_editor'} and _anchor_mode(request):
        before_ref=anchor.prepare_snapshot(request['replacement_identity_observation'],before_ref,folder/'anchor_before',managed_subject=subject)
    before=_checked_snapshot(before_ref,request)
    if request['action']=='replacement_apply':
        matches=[r for r in before['rows'] if r.get('book_id')==request['book_id'] and r.get('alias')==request['alias'] and not _deleted_original(r,request)]
        if matches:
            row=_active_row(before,request)
            return dict(status='replacement_alias_observed',native_identity=native.native_identity(before,row),snapshot=before_ref,application_submitted=False)
        check();page=navigate(managed.CONTENT_URL)
        location=locate_exact_book(page,**{k:request[k] for k in ('book_id','book_name')},guard=check,checkpoint=lambda stage,value:keep('SEARCH_'+stage,value),search_allowed=True)
        keep('BOOK_LOCATION',location);need(location.get('status') in {'located_current_view','located_after_exact_search'},'replacement_exact_book_not_located')
        intent={k:request[k] for k in managed.INTENT_FIELDS};opened=rpc(page.evaluate,managed._open_book_js(intent));keep('OPENED_BOOK',opened);need(opened.get('clicked') is True,'exact_book_not_opened')
        prepared=rpc(page.evaluate,managed._form_js(intent,entry_evidence=opened));prepared_ref=keep('FORM_PREPARED',prepared)
        if prepared.get('ready') is not True:return dict(status='application_not_submitted',form_prepared=prepared_ref,reason=prepared.get('reason'),application_submitted=False)
        proof=keep('APPLY_PREFLIGHT',dict(schema='fanqie_replacement_apply_preflight/v1',request=request_ref,subject=subject,target=full_target,intent=intent,
            cleanup_result=request.get('cleanup_result'),cleanup_reconciliation=request.get('cleanup_reconciliation'),native_snapshot=before_ref,form_prepared=prepared_ref,observed_at=time.time()))
        claim=claim_submission(proof);check();claimed=read(claim)
        need(claimed.get('schema')=='fanqie_replacement_apply_claim/v1' and claimed.get('request')==request_ref and claimed.get('preflight')==proof and claimed.get('subject')==subject,'replacement_claim_not_bound')
        keep('APPLY_CLICK_INTENT',dict(claim=claim,application_limit=1))
        try:
            response=rpc(page.evaluate,managed._form_js(intent,submit=True,entry_evidence=opened));response_ref=keep('SUBMIT_RESPONSE',response)
            failure=managed._alias_validation_failure(response,intent,response_ref,form_prepared=prepared_ref,submit_response=response_ref)
            if failure is not None:return dict(status='application_rejected',claim=claim,application_submitted=response.get('submitted'),typed_feedback=failure.result,submit_response=response_ref)
            if response.get('submitted') is not True:return dict(status='application_unknown',claim=claim,submit_response=response_ref,automatic_retry=False)
            check();navigate(managed.LIST_URL);after_ref=refresh_native_snapshot('after_apply');after=checked_snapshot(after_ref,request)
            try:row=_active_row(after,request)
            except ValueError:return dict(status='application_unknown',claim=claim,submit_response=response_ref,after_snapshot=after_ref,automatic_retry=False)
            return dict(status='replacement_alias_observed',claim=claim,application_submitted=True,native_identity=native.native_identity(after,row),snapshot=after_ref,submit_response=response_ref)
        except Exception as error:
            keep('APPLICATION_UNKNOWN',dict(error_type=type(error).__name__,claim=claim,automatic_retry=False))
            return dict(status='application_unknown',claim=claim,automatic_retry=False)
    row=_active_row(before,request,exact_identity=request['new_native_identity'])
    need(row.get('fill_status')=='未填写' and not row.get('published_links'),'new_native_alias_must_be_empty')
    token='__fanqie_new_backfill_'+secrets.token_hex(16);opening=rpc(raw.evaluate,_opener_script(target,token));keep('BACKFILL_OPENER',opening);need(opening.get('eligible') is True,'new_alias_backfill_opener_not_unique')
    selector='table:visible tbody tr:nth-child('+str(opening['row']+1)+') >> div.link,span.arco-link,button'
    opener=raw.locator(selector).nth(opening['button_index'])
    need(rpc(opener.evaluate,_opener_script(target,token,element=True)).get('eligible') is True,'new_alias_opener_changed')
    keep('BACKFILL_OPEN_INTENT',dict(target=target,open_limit=1));rpc(opener.click,timeout=8000)
    if request['action']=='inspect_replacement_editor':
        observations=[];previous=None;stable=0
        for _ in range(12):
            value=dict(editor=rpc(raw.evaluate,editor_script(target)),structure=rpc(raw.evaluate,_editor_inventory_script(target)))
            observations.append(value);stable=stable+1 if value==previous else 1;previous=value
            if value['editor'].get('exact_editor_scope_count')==1 and stable>=2:break
            rpc(raw.wait_for_timeout,200)
        evidence=keep('EMPTY_EDITOR_INSPECTION',dict(native_identity=request['new_native_identity'],native_snapshot=before_ref,samples=observations,stable=stable>=2))
        need(stable>=2 and value['editor'].get('exact_editor_scope_count')==1,'replacement_editor_not_confirmed')
        return dict(status='replacement_editor_observed',native_identity=request['new_native_identity'],native_snapshot=before_ref,inspection=evidence,
            editor_open_clicks=1,fields_written=False,add_row_clicks=0,delete_row_clicks=0,submitted=False,submission_claims_created=0)
    initial=None
    for _ in range(12):
        initial=rpc(raw.evaluate,old_form.form_script(target))
        if initial.get('eligible') is True or (request.get('add_empty_douyin_draft_row') is True and initial.get('scope_count')==1 and initial.get('input_count')==0):break
        rpc(raw.wait_for_timeout,200)
    initial_ref=keep('BLANK_FORM',initial)
    if request.get('add_empty_douyin_draft_row') is True:
        need(initial.get('scope_count')==1 and initial.get('input_count')==0 and initial.get('identity')==dict(book_name=request['book_name'],alias=request['alias'],aigc=True)
             and initial.get('submit',{}).get('enabled') is False,'first_empty_editor_not_confirmed')
        add_token='__fanqie_empty_douyin_'+secrets.token_hex(16);previous=None;stable=0;samples=[]
        for _ in range(12):
            state=rpc(raw.evaluate,_add_douyin_script(target,add_token));samples.append(state);stable=stable+1 if state==previous else 1;previous=state
            if state.get('eligible') is True and stable>=2:break
            rpc(raw.wait_for_timeout,200)
        before_add=keep('EMPTY_DOUYIN_ADD_BEFORE',dict(samples=samples,stable=stable>=2));need(state.get('eligible') is True and stable>=2,'empty_douyin_add_not_unique')
        add=raw.locator('.arco-drawer:visible button:visible').nth(state['button_index'])
        boundary=rpc(add.evaluate,_add_douyin_script(target,add_token,element=True));boundary_ref=keep('EMPTY_DOUYIN_ADD_BOUNDARY',boundary)
        need(boundary.get('eligible') is True and boundary.get('same_node') is True,'empty_douyin_add_boundary_changed')
        intent_ref=keep('EMPTY_DOUYIN_ADD_INTENT',dict(authorized_by=request['authority'],add_limit=1,section='抖音发文',other_row_actions_allowed=False,boundary=boundary_ref))
        rpc(add.click,timeout=8000)
        preparation=dict(mode='add_one_empty_douyin_row',add_row_clicks=1,remove_row_clicks=0,initial_form=initial_ref,add_before=before_add,add_boundary=boundary_ref,add_intent=intent_ref)
    else:
        old_form._valid_form(initial,target,request['new_publication']['publish_date'],request['new_publication']['canonical_url'],blank=True)
        other=raw.locator('.arco-drawer:visible input[placeholder="输入发文链接"]');empty=rpc(other.evaluate,_empty_draft_script(target));keep('EMPTY_OTHER_DRAFT',empty);need(empty.get('eligible') is True,'other_row_is_not_blank_draft')
        remove=raw.locator('.arco-drawer:visible input[placeholder="输入发文链接"] >> xpath=ancestor::*[count(.//input)=2 and count(.//button[normalize-space(.)="删除"])=1][1] >> button')
        boundary=rpc(remove.evaluate,_empty_remove_boundary(target));need(boundary.get('eligible') is True,'empty_draft_remove_boundary_changed')
        keep('EMPTY_OTHER_DRAFT_REMOVE_INTENT',dict(authorized_by=request['authority'],native_blank_draft_remove_limit=1,history_delete_allowed=False))
        rpc(remove.click,timeout=8000)
        preparation=dict(mode='remove_one_empty_other_row',add_row_clicks=0,remove_row_clicks=1,initial_form=initial_ref)
    blank=None
    for _ in range(12):
        blank=rpc(raw.evaluate,_two_input_script(target))
        if blank.get('eligible') is True and blank.get('input_count')==2:break
        rpc(raw.wait_for_timeout,150)
    preparation['blank_form']=keep('TWO_INPUT_BLANK_FORM',blank);_valid_form(blank,request,blank=True)
    day=raw.locator(old_form.DATE);link=raw.locator(old_form.LINK)
    need(rpc(day.evaluate,_two_input_script(target,'date')).get('same_element') is True,'date_element_changed')
    rpc(day.fill,request['new_publication']['publish_date']);rpc(day.press,'Enter');rpc(link.fill,request['new_publication']['canonical_url'])
    form=rpc(raw.evaluate,_two_input_script(target));_valid_form(form,request);rpc(raw.wait_for_timeout,200)
    second=rpc(raw.evaluate,_two_input_script(target));need(second==form,'filled_form_not_stable');_valid_form(second,request)
    button=raw.locator(old_form.SUBMIT);boundary=rpc(button.evaluate,_two_input_script(target,'submit'));need(boundary.get('same_element') is True,'submit_element_changed');_valid_form(boundary['form'],request)
    proof=keep('BACKFILL_PREFLIGHT',dict(schema='fanqie_replacement_backfill_preflight/v1',request=request_ref,subject=subject,target=full_target,
        native_snapshot=before_ref,native_identity=request['new_native_identity'],new_publication=request['new_publication'],empty_other_row_removed=preparation['remove_row_clicks']==1,
        preparation=preparation,actual_form=boundary['form'],observed_at=time.time()))
    claim=claim_submission(proof);check();claimed=read(claim)
    need(claimed.get('schema')=='fanqie_replacement_backfill_claim/v1' and claimed.get('request')==request_ref and claimed.get('preflight')==proof and claimed.get('subject')==subject,'replacement_backfill_claim_not_bound')
    try:
        keep('BACKFILL_SUBMIT_INTENT',dict(claim=claim,submission_limit=1));check();clicked=True;ack=False
        try:button.click(timeout=8000);ack=True
        except Exception as error:keep('SUBMIT_ACK_FAILURE',dict(error_type=type(error).__name__,claim=claim))
        observations=[];closed=False
        for _ in range(12):
            state=rpc(raw.evaluate,_two_input_script(target));body=rpc(raw.evaluate,BODY_JS);observations.append(dict(form=state,body=body))
            if state.get('scope_count')==0:closed=True;break
            rpc(raw.wait_for_timeout,200)
        after_ref=keep('AFTER_SUBMIT_WITH_VALIDATION_TEXT',dict(samples=observations,editor_closed=closed))
        if not closed:return dict(status='submission_unknown',claim=claim,submitted=True,submit_ack_returned=ack,after_submit=after_ref,automatic_retry=False)
        # A same-keyword deleted alias remains visible. Select only the unique
        # active/AIGC/usable row anchored by this action's native snapshot;
        # the legacy three-field reader cannot disambiguate those two rows.
        view_token='__fanqie_new_backfill_view_'+secrets.token_hex(16);samples=[];previous=None;stable=0
        for _ in range(16):
            view=rpc(raw.evaluate,_opener_script(target,view_token,'查看'));samples.append(view)
            stable=stable+1 if view==previous else 1;previous=view
            if view.get('eligible') is True and stable>=2:break
            rpc(raw.wait_for_timeout,200)
        keep('READBACK_ACTIVE_ROW',dict(native_identity=request['new_native_identity'],native_snapshot=before_ref,samples=samples))
        need(view.get('eligible') is True and stable>=2,'active_filled_view_not_unique')
        view_selector='table:visible tbody tr:nth-child('+str(view['row']+1)+') >> div.link,span.arco-link,button'
        view_button=raw.locator(view_selector).nth(view['button_index'])
        need(rpc(view_button.evaluate,_opener_script(target,view_token,'查看',element=True)).get('eligible') is True,'active_view_changed_at_boundary')
        keep('READBACK_VIEW_INTENT',dict(native_identity=request['new_native_identity'],native_read_click_limit=1));rpc(view_button.click,timeout=8000)
        observed=None;observations=[];new=request['new_publication']
        for _ in range(16):
            observed=rpc(raw.evaluate,opener_script(target,new['canonical_url']));observations.append(observed)
            if observed.get('eligible') is True:break
            rpc(raw.wait_for_timeout,200)
        keep('READBACK_DRAWER_OBSERVATIONS',dict(samples=observations))
        records=old_form._records(observed);readback=keep('READBACK_RECORDS',dict(scope=observed,records=records))
        confirmed={k:request['new_publication'][k] for k in ('canonical_url','publish_date')} in records
        return dict(status='new_backfill_confirmed' if confirmed else 'submission_unknown',claim=claim,submitted=True,submit_ack_returned=ack,readback=readback,
            new_native_identity=request['new_native_identity'],records=records,automatic_retry=False)
    except Exception as error:
        evidence=keep('BACKFILL_UNKNOWN',dict(error_type=type(error).__name__,claim=claim,submitted=clicked,automatic_retry=False))
        return dict(status='submission_unknown',claim=claim,submitted=clicked,diagnostic=evidence,automatic_retry=False)
