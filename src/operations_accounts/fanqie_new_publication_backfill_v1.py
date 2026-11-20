"""Exact new-publication backfill; no legacy ledger or prior write is replayed."""
import hashlib
import json
import math
import os
from pathlib import Path
import time
from datetime import datetime,timedelta,timezone

from .browser_control import BrowserControlRejected

ROOT=Path(__file__).resolve().parents[2]
KIND='fanqie_new_publication_backfill'
SOURCE_PATHS=tuple(ROOT/p for p in ('src/operations_accounts/fanqie_new_publication_backfill_v1.py',
    'src/operations_accounts/fanqie_account_control.py','src/operations_accounts/fanqie_managed_promotion_v1.py','scripts/run_fanqie_account.py',
    'src/platform_adapter/fanqie_new_post_backfill_v1.py','src/platform_adapter/fanqie_backfill_editor_inspection_v1.py',
    'src/platform_adapter/fanqie_filled_details_controls_v2.py'))


def need(ok,code):
    if not ok:raise BrowserControlRejected('new_backfill_'+code,'新链接回填证据或原账号状态未通过：'+code)


def reference(path):
    p=Path(path).resolve();need(p.is_relative_to(ROOT) and p.is_file(),'project_file_required')
    with p.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    return {'path':str(p),'sha256':sha}


def read(ref):
    need(isinstance(ref,dict) and set(ref)=={'path','sha256'} and reference(ref['path'])==ref,'bound_file_changed')
    return json.loads(Path(ref['path']).read_text(encoding='utf-8-sig'))


def refs(value):
    if isinstance(value,dict):
        if set(value)=={'path','sha256'}:need(reference(value['path'])==value,'bound_file_changed')
        else:
            for v in value.values():refs(v)
    elif isinstance(value,list):
        for v in value:refs(v)


def once(path,value):
    path=Path(path).resolve();need(path.is_relative_to(ROOT/'data'),'project_output_required');path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as stream:stream.write((json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode());stream.flush();os.fsync(stream.fileno())
    return reference(path)


def source_seal(ref):
    value=read(ref);sources=value.get('sources')
    need(value.get('schema')=='fanqie_new_backfill_source_seal/v1' and isinstance(sources,list),'source_seal_required')
    paths={Path(s.get('path','')).resolve():s for s in sources if isinstance(s,dict)}
    need(len(paths)==len(sources) and set(SOURCE_PATHS)<=set(paths),'exact_sources_required')
    for path,binding in paths.items():need(reference(path)==binding,'source_changed')


def validate_request(request_ref,*,accounts,env,binding):
    value=read(request_ref)
    need(value.get('schema')=='fanqie_new_publication_backfill_request/v1' and value.get('draft_only') is False and value.get('source_seal') is not None,'final_request_required')
    source_seal(value['source_seal']);refs(value)
    need(all(value.get(k)==env[k] for k in ('resource_id','binding_version','environment_key')) and binding is not None
         and binding.get('status')=='active' and all(binding.get(k)==env[k] for k in ('resource_id','binding_version','environment_key'))
         and value.get('platform_identity_key')==binding['platform_identity_key'] and value.get('douyin_account_uuid')==env['douyin_account_uuid'],'environment_subject_changed')
    linked=accounts.check_association(env)
    authority=read(value['authority']);operator=read(value['operator_authority']);verified=read(value['verified_publication']);metadata=read(value['metadata']);candidate=read(value['candidate'])
    new=value.get('new_publication',{});old=value.get('retained_publication',{})
    need(authority.get('schema')=='explicit_republication_intent/v1' and authority.get('new_backfill_limit')==1 and authority.get('old_records_unchanged') is True
         and operator.get('parent_authority')==value['authority'] and authority.get('account_uuid')==value['douyin_account_uuid']==linked['account_uuid']
         and authority.get('account_key')==linked['account_key'] and linked['platform_identity_key']=='public_uid:'+authority['expected_public_uid'],'parent_authority_changed')
    need(verified.get('schema')=='verified_declared_publication/v1' and verified.get('authority')==value['authority'] and verified.get('metadata')==value['metadata']
         and verified.get('candidate')==value['candidate'] and verified.get('submission_claim')==value['submission_claim']
         and verified.get('account_uuid')==value['douyin_account_uuid'] and verified.get('account_key')==linked['account_key']
         and verified.get('expected_public_uid')==authority['expected_public_uid']
         and all(verified.get(k) is True for k in ('post_verified','full_metadata_verified','numeric_duration_verified','native_AI_statement_verified','old_records_retained'))
         and verified.get('media')==metadata.get('media')==authority.get('media'),'verified_new_publication_required')
    result=read(verified['verification_result']);receipt=read(verified['verification_receipt']);caption=result.get('caption',{});evidence=read(verified['scoped_evidence']);video=read(verified['native_video_probe'])
    publication_plan=read(result['plan']);publication_config=read(publication_plan['config']);publication_claim=read(value['submission_claim'])
    need(result.get('schema')=='manual_republication_runtime_result/v10' and result.get('status')=='current_caption_verified'
         and result.get('external_publication_verified') is True and result.get('full_metadata_verified') is True
         and result.get('scoped_evidence')==caption.get('published_evidence')==verified['scoped_evidence'] and caption.get('video_probe')==verified['native_video_probe']
         and all(caption.get(k) is True for k in ('post_verified','full_metadata_verified','full_caption_verified','numeric_duration_verified'))
         and all(evidence.get(k) is True for k in ('verified','full_caption_verified','hashtags_verified','ai_label_visible','fiction_notice_visible'))
         and publication_config.get('authority')==value['authority'] and publication_config.get('operator_authority')==value['operator_authority']
         and publication_config.get('metadata')==value['metadata'] and publication_config.get('account_id')==value['douyin_account_uuid']
         and publication_claim.get('authority')==value['authority'] and publication_claim.get('metadata')==value['metadata']
         and result.get('prior_submission_claim')==value['submission_claim']
         and receipt=={'schema':'manual_republication_result_binding/v10','plan':result['plan'],'claim':result['claim'],'result':verified['verification_result']},'actual_caption_receipt_required')
    refs(verified);refs(result)
    need(verified.get('post_id')==new.get('post_id')==result.get('post_id')==candidate.get('candidate',{}).get('aweme_id')==evidence.get('expected_post_id')
         and new.get('canonical_url')=='https://www.douyin.com/video/'+str(new.get('post_id'))==verified.get('canonical_url')==result.get('canonical_url')==evidence.get('url')
         and new.get('canonical_url')!=old.get('canonical_url') and old.get('canonical_url')=='https://www.douyin.com/video/'+authority['old_post_id'],'new_link_subject_changed')
    stamp=verified.get('native_created_epoch');date=datetime.fromisoformat(verified['published_at'])
    need(type(stamp) is int and new.get('native_created_epoch')==stamp==candidate.get('native_created_epoch') and int(date.timestamp())==stamp
         and date.tzinfo is not None and new.get('publish_date')==date.astimezone(timezone(timedelta(hours=8))).date().isoformat(),'native_publication_date_changed')
    seconds=video.get('duration');expected=candidate.get('expected_duration_seconds')
    need(type(expected) in {int,float} and math.isfinite(expected) and expected>0
         and type(seconds) in {int,float} and math.isfinite(seconds) and abs(seconds-expected)<=.5 and seconds==verified.get('duration_seconds') and video.get('visible_video_count')==1
         and video.get('origin')=='https://www.douyin.com' and video.get('path')=='/video/'+new['post_id'],'native_full_player_required')
    need(value.get('new_backfill_limit')==1 and value.get('native_mode')=='create_new_post_in_blank_backfill_form'
         and value.get('preserve_existing_records') is True and value.get('no_delete_or_replace_actions') is True
         and value.get('submit_claim_path')==str(Path(value['authority']['path']).resolve().parent/'NEW_BACKFILL_SUBMIT_CLAIM.json')
         and '《'+value.get('book_name','')+'》' in metadata.get('description','') and value.get('alias','') in metadata.get('description',''),'exact_backfill_intent_required')
    editor=read(value['editor_observation']);target={k:value[k] for k in ('book_id','book_name','alias')}
    need(editor.get('schema')=='fanqie_backfill_editor_inspection/v1' and editor.get('status')=='editor_controls_observed'
         and editor.get('target')==target and all(editor.get('managed_subject',{}).get(k)==value[k] for k in ('resource_id','binding_version','environment_key','platform_identity_key'))
         and all(editor.get(k) is False for k in ('fields_written','files_selected','submitted','deleted','old_ledger_changed')),'observed_blank_editor_required')
    return value


def idempotency_key(request):
    subject={k:request[k] for k in ('authority','resource_id','binding_version','environment_key','platform_identity_key','douyin_account_uuid','book_id','book_name','alias','new_publication','retained_publication')}
    return 'fanqie-new-publication-backfill:'+hashlib.sha256(json.dumps(subject,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def subject_for(ctx,request):
    return {**{k:request[k] for k in ('resource_id','binding_version','environment_key','platform_identity_key')},'owner_id':ctx.actor.owner_id,'generation':ctx.actor.generation,'task_id':ctx.task_id}


def begin_action(ctx,accounts,request_ref,request):
    path=accounts.folder(ctx.task_id)/'NEW_BACKFILL_ACTION_CLAIM.json'
    if path.exists():return None
    need(not Path(request['submit_claim_path']).exists(),'global_submission_already_claimed')
    ctx.check_dispatch()
    return once(path,dict(schema='fanqie_new_backfill_action_claim/v1',request=request_ref,subject=subject_for(ctx,request),at_epoch=time.time(),automatic_replay_allowed=False))


def claim_submission(ctx,accounts,env,request_ref,preflight_ref):
    ctx.check_dispatch();request=validate_request(request_ref,accounts=accounts,env=env,binding=accounts.bindings().get(env['resource_id']))
    preflight=read(preflight_ref);subject=subject_for(ctx,request);folder=accounts.folder(ctx.task_id).resolve()
    need(ctx.command.get('kind')==KIND and ctx.command.get('payload')=={'environment_key':env['environment_key'],'request':request_ref}
         and Path(preflight_ref['path']).resolve().is_relative_to(folder) and Path(preflight_ref['path']).name=='SUBMIT_PREFLIGHT.json','original_command_preflight_required')
    action=read(reference(folder/'NEW_BACKFILL_ACTION_CLAIM.json'))
    need(action.get('request')==request_ref and action.get('subject')==subject,'action_subject_changed')
    observed=preflight.get('observed_at');actual=preflight.get('actual_form',{});new=request['new_publication'];old=request['retained_publication'];target={k:request[k] for k in ('book_id','book_name','alias')}
    need(preflight.get('schema')=='fanqie_new_post_backfill_preflight/v1' and preflight.get('request')==request_ref and preflight.get('subject')==subject
         and preflight.get('target')==target and preflight.get('new_publication')==new and old in preflight.get('retained_records',[])
         and type(observed) in {int,float} and math.isfinite(observed) and 0<=time.time()-observed<=30
         and preflight.get('submission_limit')==1 and preflight.get('no_add_delete_actions') is True,'fresh_retained_and_new_form_required')
    refs(preflight)
    need(actual.get('schema')=='fanqie_new_post_form/v1' and actual.get('location',{}).get('origin')=='https://kol.fanqieopen.com'
         and actual.get('scope_count')==1 and actual.get('identity')=={'book_name':request['book_name'],'alias':request['alias'],'aigc':True}
         and actual.get('input_count')==4 and actual.get('link_count')==1 and actual.get('row_date_count')==1 and actual.get('row_input_count')==2 and actual.get('eligible') is True
         and actual.get('date',{}).get('value')==new['publish_date'] and actual.get('link',{}).get('value')==new['canonical_url']
         and len(actual.get('other_inputs',[]))==2 and all(x.get('value')=='' for x in actual['other_inputs'])
         and actual.get('submit')=={'unique_count':1,'tag':'button','type':'button','text':'提交','enabled':True}
         and actual.get('add_delete_actions_performed') is False,'exact_native_new_form_required')
    ctx.check_dispatch()
    return once(request['submit_claim_path'],dict(schema='fanqie_new_backfill_submit_claim/v1',request=request_ref,preflight=preflight_ref,subject=subject,
        authority=request['authority'],verified_publication=request['verified_publication'],new_publication=new,retained_publication=old,at_epoch=time.time(),allowed_submissions=1,automatic_replay_allowed=False))


def execute(ctx,*,accounts,env,page_provider,identity_guard):
    """Run one separately authorized new native form on the current managed Page."""
    from .browser_control import BrowserCommandResult
    from .fanqie_managed_promotion_v1 import LIST_URL,_hard_worker_failure
    from src.platform_adapter.fanqie_new_post_backfill_v1 import run_action
    payload=ctx.command['payload'];need(set(payload)=={'environment_key','request'} and payload['environment_key']==env['environment_key'],'payload_invalid')
    request_ref=payload['request'];folder=accounts.folder(ctx.task_id);folder.mkdir(parents=True,exist_ok=True)
    request=validate_request(request_ref,accounts=accounts,env=env,binding=accounts.bindings().get(env['resource_id']))
    subject=subject_for(ctx,request);result_path=folder/'NEW_BACKFILL_RESULT.json';receipt_path=folder/'NEW_BACKFILL_RESULT_BINDING.json';action_path=folder/'NEW_BACKFILL_ACTION_CLAIM.json'
    if action_path.exists():
        previous=read(reference(action_path));need(previous.get('request')==request_ref and previous.get('subject')==subject,'previous_action_changed')
        if result_path.exists() and receipt_path.exists():
            receipt=read(reference(receipt_path));result_ref=reference(result_path)
            need(receipt==dict(schema='fanqie_new_backfill_result_binding/v1',request=request_ref,subject=subject,result=result_ref),'cached_result_changed')
            previous_result=read(result_ref);refs(previous_result)
            need(previous_result.get('request')==request_ref and previous_result.get('subject')==subject,'cached_result_changed')
            return BrowserCommandResult(previous_result['broker_state'],dict(previous_result['result'],result_evidence=result_ref))
        return BrowserCommandResult('succeeded',dict(status='submission_unknown',confirmed=False,automatic_retry=False,
            requires_read_only_reconciliation=True,reason='existing_action_without_receipt',backfill_submitted=None))
    def guard():
        identity_guard()
        current=accounts.get(env['resource_id']);need(current==env,'environment_changed')
        need(validate_request(request_ref,accounts=accounts,env=current,binding=accounts.bindings().get(env['resource_id']))==request,'request_changed')
        claim_path=Path(request['submit_claim_path'])
        if claim_path.exists():
            claim=read(reference(claim_path));action=read(reference(action_path))
            need(claim.get('schema')=='fanqie_new_backfill_submit_claim/v1' and claim.get('request')==request_ref
                 and claim.get('subject')==subject and action.get('request')==request_ref and action.get('subject')==subject,'other_submission_already_claimed')
            refs(claim)
    guard();need(begin_action(ctx,accounts,request_ref,request) is not None,'action_already_claimed')
    raw=None
    try:
        managed=page_provider(ctx,LIST_URL);raw=managed.page
        value=run_action(raw,request=request,request_ref=request_ref,subject=subject,guard=guard,evidence_directory=folder/'new_backfill',
            claim_submission=lambda preflight:claim_submission(ctx,accounts,env,request_ref,preflight))
        guard();refs(value)
        need(value.get('schema')=='fanqie_new_post_backfill/v1' and value.get('status') in {'confirmed','not_submitted','submission_unknown'},'adapter_receipt_invalid')
        if value['status']=='confirmed':
            need(value.get('submitted') is True and value.get('submission_claim')==reference(request['submit_claim_path'])
                 and all(record in value.get('records',[]) for record in (request['retained_publication'],
                     {k:request['new_publication'][k] for k in ('canonical_url','publish_date')})),'native_readback_required')
        state='outcome_unknown' if _hard_worker_failure(None,raw) else 'failed' if value['status']=='not_submitted' else 'succeeded'
        result=dict(status=value['status'],confirmed=value['status']=='confirmed',backfill_submitted=value.get('submitted'),
            automatic_retry=False,requires_read_only_reconciliation=value['status']=='submission_unknown',native_result=value)
    except Exception as error:
        claimed=Path(request['submit_claim_path']).exists()
        hard=isinstance(error,BrowserControlRejected) or _hard_worker_failure(error,raw)
        state='outcome_unknown' if hard else 'succeeded' if claimed else 'failed'
        result=dict(status='submission_unknown' if claimed or hard else 'not_submitted',confirmed=False,backfill_submitted=None if claimed else False,
            automatic_retry=False,requires_read_only_reconciliation=claimed or hard,error_type=type(error).__name__)
        if isinstance(error,BrowserControlRejected):result['reason']=error.code
    result_ref=once(result_path,dict(schema='fanqie_new_backfill_command_result/v1',request=request_ref,subject=subject,broker_state=state,result=result))
    once(receipt_path,dict(schema='fanqie_new_backfill_result_binding/v1',request=request_ref,subject=subject,result=result_ref))
    return BrowserCommandResult(state,dict(result,result_evidence=result_ref))
