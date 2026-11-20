"""Read-only identity evidence for a same-keyword replacement record.

Default snapshot/v2 bytes and semantics remain unchanged. This separate receipt
uses a complete native set delta and the previously deleted DOM/native anchor;
it never turns a raw numeric status into an approval or a backfill permission.
"""
import json
import re
from pathlib import Path

from . import fanqie_promotion_identity_v2 as native
from src.operations_accounts import fanqie_new_publication_backfill_v1 as files

SCHEMA='fanqie_replacement_native_identity_receipt/v1'
DOM_KEYS=('book_id','book_name','alias','publish_type','alias_status','book_status','valid_from','valid_until','fill_status','published_links')


def need(ok,reason):
    if not ok:raise ValueError('replacement_identity_'+reason)


def _evidence(snapshot_ref):
    snapshot=native.validate_snapshot(files.read(snapshot_ref));evidence=files.read(snapshot['evidence_ref'])
    legacy=files.read(evidence['legacy_snapshot']);observation=files.read(evidence['observation'])
    need(snapshot.get('pagination_complete') is True and legacy.get('table_ready') is True and legacy.get('pagination_complete') is True
        and legacy.get('identity_verified') is True and legacy.get('challenge') is False,'complete_clear_snapshot_required')
    records={};sources={};enums={};enum_sources={};totals=[]
    for ci,capture in enumerate(observation['captures']):
        endpoint=capture.get('endpoint',{}).get('path')
        if endpoint not in {native.PROMOTION_ENDPOINT,native.ENUM_ENDPOINT}:continue
        entries=list(native._capture_fields(capture))
        if endpoint==native.PROMOTION_ENDPOINT:
            totals.extend(x['value'] for x in capture['metadata']['response_fields'] if x['path']=='$.data.total')
            for path,value in entries:
                if not re.fullmatch(r'\$\.data\.promotion_list\[\d+\]',path):continue
                aid=value.get('alias_id');need(isinstance(aid,str) and re.fullmatch(r'\d{1,24}',aid),'native_string_id_required')
                need(aid not in records or records[aid]==value,'native_record_changed_during_observation')
                records[aid]=value;sources.setdefault(aid,[]).append(dict(capture_index=ci,record_path=path))
        else:
            for path,value in entries:
                if not re.fullmatch(r'\$\.data\.kol_alias_post_type\[\d+\]',path):continue
                number,label=value.get('value'),value.get('text');need(type(number) is int and isinstance(label,str),'native_type_enum_required')
                need(number not in enums or enums[number]==label,'native_type_enum_conflict');enums[number]=label
                enum_sources.setdefault(number,[]).append(dict(capture_index=ci,record_path=path))
    need(totals and len(set(totals))==1 and totals[0]==len(records)==len(legacy['rows']),'complete_native_records_required')
    return dict(snapshot=snapshot,evidence=evidence,legacy=legacy,observation=observation,records=records,enums=enums,
        record_sources=sources,enum_sources=enum_sources,snapshot_ref=snapshot_ref)


def _resolve(before,after,request):
    before_ids=set(before['records']);after_ids=set(after['records']);added=after_ids-before_ids
    need(before_ids<=after_ids and len(added)==1,'exactly_one_new_native_record_required')
    new_id=next(iter(added));old_id=request['replaces_native_identity']['native_record_id']
    need(old_id in before['records'] and old_id in after['records'] and before['records'][old_id]==after['records'][old_id],
         'immutable_deleted_native_anchor_changed')
    old,new=after['records'][old_id],after['records'][new_id]
    expected={'book_id':request['book_id'],'book_name':request['book_name'],'alias_name':request['alias']}
    need(all(old.get(k)==new.get(k)==v for k,v in expected.items()),'exact_book_keyword_required')
    post=new.get('alias_post_type');need(type(post) is int and before['enums'].get(post)==after['enums'].get(post)=='AIGC'
        and old.get('alias_post_type')==post,'same_observed_aigc_enum_required')
    candidates=[r for r in after['records'].values() if all(r.get(k)==v for k,v in expected.items()) and r.get('alias_post_type')==post]
    need({r['alias_id'] for r in candidates}=={old_id,new_id},'native_keyword_identity_ambiguous')
    def group(rows):return [r for r in rows if all(r.get(k)==request[k] for k in ('book_id','book_name','alias')) and r.get('publish_type')=='AIGC']
    old_dom=group(before['legacy']['rows']);need(len(old_dom)==1 and old_dom[0].get('alias_status')=='已删除','original_deleted_dom_anchor_required')
    old_projection={k:old_dom[0].get(k) for k in DOM_KEYS}
    need(old_dom[0].get('valid_from')==old.get('alias_start_time') and old_dom[0].get('valid_until')==old.get('alias_end_time'),
         'old_native_dom_dates_conflict')
    dom=group(after['legacy']['rows']);anchored=[r for r in dom if {k:r.get(k) for k in DOM_KEYS}==old_projection]
    need(len(dom)==2 and len(anchored)==1,'unique_deleted_dom_anchor_required')
    remaining=[r for r in dom if r is not anchored[0]];need(len(remaining)==1,'unique_new_dom_row_required');new_dom=remaining[0]
    need(new_dom.get('alias_status')!='已删除','new_native_row_is_deleted')
    for dk,nk in (('valid_from','alias_start_time'),('valid_until','alias_end_time')):
        need(new_dom.get(dk) in (None,'',new.get(nk)),'new_dom_native_dates_conflict')
    return new_id,new,new_dom,old_id,old_dom[0]


def derive(application_result_ref,*,current_snapshot_ref=None,readonly_command_ref=None):
    """Pure validation over immutable receipts; optional newer read is explicit."""
    result=files.read(application_result_ref);request=files.read(result['request']);value=result.get('result',{}).get('native_result',{})
    need(result.get('schema')=='fanqie_cleanup_rebind_command_result/v1' and request.get('action')=='replacement_apply'
        and value.get('status')=='application_unknown' and value.get('claim') is not None,'original_once_application_required')
    claim=files.read(value['claim']);preflight=files.read(claim['preflight']);response=files.read(value['submit_response'])
    need(claim.get('schema')=='fanqie_replacement_apply_claim/v1' and claim.get('request')==result['request'] and claim.get('subject')==result['subject']
         and preflight.get('request')==result['request'] and preflight.get('subject')==result['subject']
         and response.get('submitted') is True,'actual_single_submit_required')
    before_ref=preflight['native_snapshot'];after_ref=current_snapshot_ref or value['after_snapshot']
    before=_evidence(before_ref);after=_evidence(after_ref)
    need(before['evidence']['managed_subject']==result['subject'] and all(before['snapshot'].get(k)==after['snapshot'].get(k)==request[k] for k in native.SCOPE),
         'original_managed_scope_changed')
    if current_snapshot_ref is None:
        need(after['evidence']['managed_subject']==result['subject'],'original_after_owner_changed')
    else:
        command=files.read(readonly_command_ref);subject=after['evidence']['managed_subject']
        need(command.get('kind')=='fanqie_promotion_list' and command.get('state')=='succeeded' and command.get('command_id')==subject['task_id']
             and command.get('account_id')==request['resource_id'] and command.get('binding_version')==request['binding_version']
             and command.get('owner_id')==subject['owner_id'] and command.get('generation')==subject['generation']
             and command.get('payload')==dict(environment_key=request['environment_key'],snapshot_version='v2')
             and command.get('result',{}).get('promotion_snapshot')==after_ref,'explicit_readonly_observation_required')
    new_id,new,dom,old_id,old_dom=_resolve(before,after,request)
    identity=dict(platform_identity_key=request['platform_identity_key'],native_kind='promotion_alias',native_record_id=new_id)
    return dict(schema=SCHEMA,application_result=application_result_ref,request=result['request'],application_claim=value['claim'],submit_response=value['submit_response'],
        before_snapshot=before_ref,after_snapshot=after_ref,readonly_command=readonly_command_ref,subject=after['evidence']['managed_subject'],
        identity_verified=True,native_identity=identity,book_id=request['book_id'],book_name=request['book_name'],alias=request['alias'],publish_type='AIGC',
        native_record_sources=after['record_sources'][new_id],native_observation=after['evidence']['observation'],
        native_status_raw=new.get('alias_status'),native_status_text_inferred=False,dom_status=dom['alias_status'],book_status=dom.get('book_status'),
        create_time_raw=new.get('create_time'),native_valid_from=new.get('alias_start_time'),native_valid_until=new.get('alias_end_time'),
        dom_valid_from=dom.get('valid_from'),dom_valid_until=dom.get('valid_until'),fill_status=dom.get('fill_status'),
        post_type_evidence=dict(native_value=new['alias_post_type'],text=after['enums'][new['alias_post_type']],sources=after['enum_sources'][new['alias_post_type']]),
        old_native_identity=request['replaces_native_identity'],old_native_status_raw=after['records'][old_id].get('alias_status'),old_dom_status=old_dom['alias_status'],
        join_criteria=['complete_native_id_set_delta','immutable_deleted_native_record','exact_book_id_and_name','exact_alias','same_observed_aigc_enum','unique_deleted_dom_with_exact_dates','unique_remaining_dom_row'],
        order_used_as_identity=False,publishable=False,backfill_allowed=False,
        workflow_state='awaiting_platform_review' if dom['alias_status']=='待审核' else 'requires_separate_fresh_publishability_admission',
        original_application_result_changed=False,platform_calls=0,business_writes=0)


def prepare_receipt(application_result_ref,output_path,*,current_snapshot_ref=None,readonly_command_ref=None):
    value=derive(application_result_ref,current_snapshot_ref=current_snapshot_ref,readonly_command_ref=readonly_command_ref)
    return files.once(output_path,value)
