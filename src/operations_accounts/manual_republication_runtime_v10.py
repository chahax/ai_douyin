"""One original-draft disclosure inspection; never select or publish."""
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import types
import time
from datetime import datetime,timedelta,timezone

from . import manual_republication_runtime_v9 as base

ROOT=Path(__file__).resolve().parents[2]
RUN=ROOT/'data/production_trials/fanqie_declared_republication_20261117_v1'
ARM=RUN/'manual_runtime_v10/ARM.json'
SOURCE_PATHS=dict(base.SOURCE_PATHS,runtime_v10=Path(__file__).resolve(),flow_v10=ROOT/'src/operations_accounts/manual_republication_flow_v10.py')
CONFIG_SCHEMA='manual_republication_runtime_config/v10'
REQUEST_SCHEMA='manual_republication_operator_request/v10'
PLAN_SCHEMA='manual_republication_runtime_plan/v10'
ACTION='inspect_current_declaration_controls'
PUBLISH_ACTION='set_declaration_and_publish_once'
CONTINUE_ACTION='continue_selected_declaration_and_publish_once'
METADATA_ACTION='read_submitted_work_metadata'
VERIFY_ACTION='verify_submitted_candidate'
CAPTION_ACTION='inspect_current_public_caption'
WORK_LIST_URL='https://creator.douyin.com/janus/douyin/creator/pc/work_list?status=0&count=20&max_cursor=0&scene=star_atlas&device_platform=android&aid=1128'
SUBMIT_CLAIM=RUN/'SUBMIT_CLAIM.json'
PUBLISH_FIELDS=('controls_result','controls_receipt','declaration_contract','submission_authority')
CONTINUE_FIELDS=(*PUBLISH_FIELDS,'selected_state_contract')
METADATA_FIELDS=('metadata_read_intent',)
VERIFY_FIELDS=('verification_intent',)
CAPTION_FIELDS=('caption_read_intent',)
PRIOR_FIELDS=('prior_result','prior_receipt','options_inventory')
reference,_read,_once=base.reference,base._read,base._once


def _refs(value):base._refs(value)


def _projection(config):
    return dict(config,sources={key:config['sources'][key] for key in base.SOURCE_PATHS})


def _scope(config,verify_media=False):
    if not isinstance(config.get('sources'),dict) or set(config['sources'])!=set(SOURCE_PATHS):raise ValueError('declaration_exact_sources_required')
    for key,path in SOURCE_PATHS.items():
        if reference(path)!=config['sources'][key]:raise ValueError('declaration_source_changed:'+key)
    base._scope(_projection(config),verify_media=verify_media)


def _config(ref):
    value=_read(ref)
    fields={'schema','backend_pid','backend_create_time','account_key','account_id','owner_id','generation','binding_version','browser_db','control_db','control_snapshot','manual_command_id','manual_request_sha256','tab_id','authority','operator_authority','metadata','sources'}
    if not isinstance(value,dict) or set(value)!=fields or value['schema']!=CONFIG_SCHEMA:raise ValueError('declaration_config_invalid')
    _scope(value,True);return value


def _request(ref,config_ref):
    value=_read(ref)
    if not isinstance(value,dict):raise ValueError('declaration_request_invalid')
    fields=PRIOR_FIELDS if value.get('action')==ACTION else PUBLISH_FIELDS if value.get('action')==PUBLISH_ACTION else CONTINUE_FIELDS if value.get('action')==CONTINUE_ACTION else METADATA_FIELDS if value.get('action')==METADATA_ACTION else VERIFY_FIELDS if value.get('action')==VERIFY_ACTION else CAPTION_FIELDS if value.get('action')==CAPTION_ACTION else ()
    if (not fields or set(value)!={'schema','config','action',*fields}
            or value['schema']!=REQUEST_SCHEMA or value['config']!=config_ref):raise ValueError('declaration_inspection_only')
    return value


def _read_prior(config,request):
    result=_read(request['prior_result']);receipt=_read(request['prior_receipt']);plan=_read(result['plan']);claim=_read(result['claim'])
    previous=_read(plan['config']);old_request=_read(plan['request']);folder=Path(result['plan']['path']).resolve().parent;value=result.get('inspection',{})
    if (not folder.is_relative_to(RUN.resolve()) or result.get('schema')!='manual_republication_runtime_result/v9' or result.get('status')!='declaration_options_observed'
            or result.get('submitted') is not False or result.get('file_selection_claim')!=value.get('file_selection_claim')
            or receipt!={'schema':'manual_republication_result_binding/v9','plan':result['plan'],'claim':result['claim'],'result':request['prior_result']}
            or Path(request['prior_result']['path']).resolve()!=folder/'RESULT.json' or Path(request['prior_receipt']['path']).resolve()!=folder/'RESULT_BINDING.json'
            or result['claim']!=reference(folder/'ACTION_CLAIM.json') or plan.get('schema')!=base.PLAN_SCHEMA or plan.get('action')!=base.ACTION
            or previous.get('schema')!=base.CONFIG_SCHEMA or any(previous.get(k)!=config[k] for k in config if k not in {'schema','sources'})
            or any(previous['sources'][k]!=config['sources'][k] for k in ('runtime_v9','flow_v9'))
            or claim.get('schema')!='manual_republication_declaration_action_claim/v9' or claim.get('action')!=base.ACTION
            or claim.get('plan')!=result['plan'] or claim.get('config')!=plan['config'] or claim.get('request')!=plan['request']
            or any(claim.get(k)!=config[k] for k in ('owner_id','generation','tab_id'))
            or value.get('schema')!='manual_republication_declaration_inspection/v9' or value.get('action')!=base.ACTION
            or value.get('action_claim')!=result['claim'] or value.get('metadata_readback_matched') is not True
            or value.get('same_tab')!=config['tab_id'] or value.get('scroll_performed') is not True or value.get('trigger_click_count')!=1
            or value.get('options_inventory')!=request['options_inventory'] or value.get('options_observed') is not True
            or any(value.get(k) is not False for k in ('submitted','declaration_selected','confirmed','navigation_performed','file_selected','fields_written','publication_ready'))):
        raise ValueError('controls_original_open_modal_required')
    _refs(result)
    inventory=_read(request['options_inventory']);events=_read(value['disclosure_events'])
    if (inventory.get('schema')!='manual_native_declaration_options/v9' or inventory.get('complete_visible_capture') is not True or inventory.get('truncated') is not False
            or inventory.get('location')!={'origin':'https://creator.douyin.com','path':'/creator-micro/content/post/video'}
            or '请选择声明类型（单选）' not in inventory.get('visible_text','') or events!={'allowed_clicks':1,'blocked_events':0}):raise ValueError('controls_actual_single_modal_required')
    prior=base._prior(_projection(config),old_request)
    if prior['file_selection_claim']!=result['file_selection_claim']:raise ValueError('controls_original_file_claim_changed')
    return dict(prior,**{key:request[key] for key in PRIOR_FIELDS},current_modal_read_only=True)


def _publish_prior(config,request):
    result=_read(request['controls_result']);receipt=_read(request['controls_receipt']);plan=_read(result['plan']);claim=_read(result['claim'])
    old_config=_read(plan['config']);old_request=_read(plan['request']);folder=Path(result['plan']['path']).resolve().parent;value=result.get('inspection',{})
    if (not folder.is_relative_to(RUN.resolve()) or result.get('schema')!='manual_republication_runtime_result/v10'
            or result.get('status')!='declaration_controls_observed' or result.get('submitted') is not False
            or receipt!={'schema':'manual_republication_result_binding/v10','plan':result['plan'],'claim':result['claim'],'result':request['controls_result']}
            or Path(request['controls_result']['path']).resolve()!=folder/'RESULT.json' or Path(request['controls_receipt']['path']).resolve()!=folder/'RESULT_BINDING.json'
            or result['claim']!=reference(folder/'ACTION_CLAIM.json') or claim.get('schema')!='manual_republication_controls_action_claim/v10'
            or claim.get('action')!=ACTION or claim.get('plan')!=result['plan'] or claim.get('config')!=plan['config'] or claim.get('request')!=plan['request']
            or plan.get('schema')!=PLAN_SCHEMA or plan.get('action')!=ACTION or old_request.get('action')!=ACTION
            or old_config.get('schema')!=CONFIG_SCHEMA or any(old_config.get(k)!=config[k] for k in config if k not in {'schema','sources'})
            or result.get('producer_source_snapshot')!=plan.get('producer_source_snapshot')
            or value.get('schema')!='manual_republication_declaration_controls/v10' or value.get('action')!=ACTION
            or value.get('action_claim')!=result['claim'] or value.get('render_complete') is not True or value.get('same_tab')!=config['tab_id']
            or any(value.get(k) is not False for k in ('input_performed','selection_performed','declaration_confirmed','publish_clicked','navigation_performed','file_selected','submitted'))):
        raise ValueError('publish_actual_controls_receipt_required')
    validate_producer_snapshot(plan,old_config,result['plan']);_refs(result)
    prior=_read_prior(config,old_request)
    if prior!=plan['prior'] or result.get('file_selection_claim')!=prior['file_selection_claim']:raise ValueError('publish_original_draft_changed')
    controls=_read(value['modal_controls']);contract=_read(request['declaration_contract']);authority=_read(config['authority'])
    if (controls.get('schema')!='manual_native_declaration_controls/v10' or controls.get('render_complete') is not True or controls.get('truncated') is not False
            or controls.get('native_associations_complete') is not True or controls.get('semantics',{}).get('explicit_single_choice_copy') is not True
            or controls.get('semantics',{}).get('same_nonempty_native_radio_name') is not True
            or controls.get('location')!={'origin':'https://creator.douyin.com','path':'/creator-micro/content/post/video'}
            or request['submission_authority']!=config['authority'] or contract.get('schema')!='native_statement_selection_contract/v1'
            or contract.get('inspection_result')!=request['controls_result'] or contract.get('inspection_receipt')!=request['controls_receipt']
            or contract.get('native_controls')!=value['modal_controls'] or contract.get('metadata')!=config['metadata']
            or contract.get('file_selection_claim')!=prior['file_selection_claim'] or contract.get('selection_semantics')!='single'
            or contract.get('selected_label')!='内容由AI生成' or contract.get('required_final_statement')!=contract['selected_label']
            or contract.get('native_marketing_also_selected') is not False or contract.get('caption_must_remain_unchanged') is not True
            or contract.get('no_file_selection_allowed') is not True or contract.get('no_navigation_before_submission') is not True
            or any(type(contract.get(k)) is not int or contract[k]!=1 for k in ('new_publication_limit','new_backfill_limit'))
            or contract.get('native_confirmation')!={'tag':'button','type':'button','text':'确定'}):raise ValueError('publish_exact_native_contract_required')
    labels=controls.get('labels',[]);radios=controls.get('native_controls',[])
    selected=[l for l in labels if l.get('text')==contract['selected_label']]
    if (len(labels)!=6 or len(radios)!=6 or len(selected)!=1 or selected[0]!=contract.get('native_label')
            or selected[0].get('associated_control_inside_modal') is not True or selected[0].get('association')!='native_wrapping_label'
            or radios[selected[0]['control_index']]!=contract.get('native_radio')
            or set(contract.get('expected_all_other_labels',[]))!={l['text'] for l in labels if l is not selected[0]}
            or any(r.get('type')!='radio' or r.get('name')!='default' or r.get('checked') is not False or r.get('disabled') is not False or r.get('checked_read_allowed') is not True for r in radios)):
        raise ValueError('publish_native_single_radio_binding_required')
    _refs(contract);priority=_read(contract['priority_decision']);verification=_read(contract['post_submit_verification_requirements'])
    if (priority.get('schema')!='native_statement_priority_decision/v1' or priority.get('choice')!=contract['selected_label']
            or priority.get('single_choice_observed') is not True or priority.get('native_marketing_also_selected') is not False
            or priority.get('does_not_authorize_additional_publication') is not True
            or verification.get('schema')!='republication_verification_requirements/v1' or verification.get('authority')!=config['authority']
            or verification.get('metadata')!=config['metadata'] or verification.get('statement_priority')!=contract['priority_decision']
            or verification.get('expected_public_uid')!=authority['expected_public_uid']
            or verification.get('expected_native_statement')!=contract['selected_label'] or verification.get('no_submit_retry') is not True
            or authority.get('old_post_id') not in verification.get('excluded_old_post_ids',[])
            or abs(verification.get('expected_duration_seconds',0)-prior['source_duration_seconds'])>1e-6
            or verification.get('duration_tolerance_seconds')!=.5):raise ValueError('publish_new_post_verification_contract_required')
    return dict(prior,**{key:request[key] for key in PUBLISH_FIELDS},modal_controls=value['modal_controls'],selected_label=contract['selected_label'])


def _prior(config,request):
    return _read_prior(config,request) if request['action']==ACTION else _continue_prior(config,request) if request['action']==CONTINUE_ACTION else _metadata_prior(config,request) if request['action']==METADATA_ACTION else _verify_prior(config,request) if request['action']==VERIFY_ACTION else _caption_prior(config,request) if request['action']==CAPTION_ACTION else _publish_prior(config,request)


def _caption_prior(config,request):
    intent=_read(request['caption_read_intent']);helper=intent.get('helper_ref')
    helper_path=ROOT/'src/shared/published_work_metadata_scope_v1.py';base_path=ROOT/'src/shared/published_work_scope.py'
    if (intent.get('schema')!='current_public_caption_read_intent/v1' or intent.get('draft_only') is not False
            or not isinstance(helper,dict) or Path(helper.get('path','')).resolve()!=helper_path.resolve()
            or intent.get('planned_helper_path')!=str(helper_path) or reference(helper_path)!=helper
            or intent.get('base_scope_source')!=reference(base_path) or intent.get('base_scope_snapshot',{}).get('sha256')!=intent['base_scope_source']['sha256']
            or reference(intent['base_scope_snapshot']['path'])!=intent['base_scope_snapshot']
            or intent.get('authority')!=config['authority'] or intent.get('operator_authority')!=config['operator_authority'] or intent.get('metadata')!=config['metadata']
            or intent.get('scoped_reads_allowed')!=1 or intent.get('screenshots_allowed')!=1
            or any(intent.get(k)!=0 for k in ('navigations_allowed','api_requests_allowed','new_tabs_allowed','publications_allowed','selections_allowed','confirmations_allowed','files_allowed'))
            or intent.get('fields_written_allowed') is not False):raise ValueError('caption_final_scoped_helper_intent_required')
    result=_read(intent['legacy_verification_result']);receipt=_read(intent['legacy_verification_receipt']);plan=_read(result['plan']);claim=_read(result['claim'])
    oldconfig=_read(plan['config']);oldrequest=_read(plan['request']);folder=Path(result['plan']['path']).resolve().parent;value=result.get('verification',{})
    if (folder!=RUN.resolve()/'manual_runtime_v10/verify_new_001' or result.get('schema')!='manual_republication_runtime_result/v10'
            or result.get('status')!='submitted_candidate_not_verified' or result.get('external_publication_verified') is not False
            or receipt!={'schema':'manual_republication_result_binding/v10','plan':result['plan'],'claim':result['claim'],'result':intent['legacy_verification_result']}
            or result['claim']!=reference(folder/'ACTION_CLAIM.json') or plan.get('schema')!=PLAN_SCHEMA or plan.get('action')!=VERIFY_ACTION
            or claim.get('schema')!='manual_republication_verify_action_claim/v10' or claim.get('action')!=VERIFY_ACTION or claim.get('plan')!=result['plan']
            or claim.get('config')!=plan['config'] or claim.get('request')!=plan['request'] or oldrequest.get('action')!=VERIFY_ACTION
            or any(oldconfig.get(k)!=config[k] for k in config if k not in {'schema','sources'})
            or result.get('producer_source_snapshot')!=plan.get('producer_source_snapshot') or value.get('schema')!='manual_republication_public_verification/v10'
            or value.get('action')!=VERIFY_ACTION or value.get('post_verified') is not False or value.get('numeric_duration_verified') is not True
            or value.get('published_evidence')!=intent['legacy_scope_evidence'] or result.get('prior_submission_claim')!=intent['submission_claim']
            or intent['submission_claim']!=reference(SUBMIT_CLAIM)):
        raise ValueError('caption_original_legacy_scope_failure_required')
    validate_producer_snapshot(plan,oldconfig,result['plan']);_refs(result);_refs(intent)
    prior=_verify_prior(config,oldrequest)
    if prior!=plan['prior'] or intent.get('candidate')!=prior['candidate'] or intent.get('post_id')!=prior['post_id'] or intent.get('canonical_url')!=prior['canonical_url']:
        raise ValueError('caption_original_native_candidate_changed')
    legacy=_read(intent['legacy_scope_evidence']);player=_read(intent['public_player_observed']);video=_read(value['video_probe']);duration=video.get('duration')
    if (legacy.get('verified') is not False or legacy.get('reason')!='native_caption_title_mismatch' or legacy.get('scope_kind')!='observed_video_detail'
            or legacy.get('expected_post_id')!=prior['post_id'] or legacy.get('url')!=prior['canonical_url'] or legacy.get('player_id_matches') is not True
            or any(legacy.get(k)!=1 for k in ('detail_nodes','player_nodes','caption_nodes'))
            or player.get('schema')!='native_public_player_observed/v1' or player.get('verification_result')!=intent['legacy_verification_result']
            or player.get('verification_receipt')!=intent['legacy_verification_receipt'] or player.get('strict_scope_evidence')!=intent['legacy_scope_evidence']
            or player.get('native_probe')!=value['video_probe'] or player.get('numeric_duration_verified') is not True or player.get('full_caption_scope_verified') is not False
            or player.get('post_id')!=prior['post_id'] or player.get('canonical_url')!=prior['canonical_url'] or player.get('native_created_epoch')!=prior['native_created_epoch']
            or player.get('published_at')!=prior['native_created_iso'] or player.get('duration_seconds')!=duration
            or type(duration) not in {int,float} or not math.isfinite(duration) or abs(duration-prior['source_duration_seconds'])>.5
            or intent.get('expected_duration_seconds')!=prior['source_duration_seconds'] or intent.get('duration_tolerance_seconds')!=.5):
        raise ValueError('caption_known_identity_and_native_player_required')
    return dict(prior,caption_read_intent=request['caption_read_intent'],legacy_verification_result=intent['legacy_verification_result'],legacy_verification_receipt=intent['legacy_verification_receipt'],
        public_player_observed=intent['public_player_observed'],legacy_scope_evidence=intent['legacy_scope_evidence'],helper_ref=helper,base_scope_source=intent['base_scope_source'],base_scope_snapshot=intent['base_scope_snapshot'])


def _verify_prior(config,request):
    intent=_read(request['verification_intent']);candidate=_read(intent['candidate']);result=_read(intent['metadata_result']);receipt=_read(intent['metadata_receipt'])
    plan=_read(result['plan']);claim=_read(result['claim']);oldconfig=_read(plan['config']);oldrequest=_read(plan['request']);folder=Path(result['plan']['path']).resolve().parent
    value=result.get('readback',{})
    if (intent.get('schema')!='verify_submitted_candidate_intent/v1' or intent.get('authority')!=config['authority'] or intent.get('operator_authority')!=config['operator_authority']
            or intent.get('metadata')!=config['metadata'] or folder!=RUN.resolve()/'manual_runtime_v10/readback_001'
            or result.get('schema')!='manual_republication_runtime_result/v10' or result.get('status')!='submitted_metadata_observed'
            or result.get('new_submission_actions')!=0 or result.get('external_publication_verified') is not False
            or receipt!={'schema':'manual_republication_result_binding/v10','plan':result['plan'],'claim':result['claim'],'result':intent['metadata_result']}
            or Path(intent['metadata_result']['path']).resolve()!=folder/'RESULT.json' or Path(intent['metadata_receipt']['path']).resolve()!=folder/'RESULT_BINDING.json'
            or claim.get('schema')!='manual_republication_metadata_action_claim/v10' or claim.get('action')!=METADATA_ACTION
            or claim.get('plan')!=result['plan'] or claim.get('config')!=plan['config'] or claim.get('request')!=plan['request']
            or plan.get('schema')!=PLAN_SCHEMA or plan.get('action')!=METADATA_ACTION or oldrequest.get('action')!=METADATA_ACTION
            or oldconfig.get('schema')!=CONFIG_SCHEMA or any(oldconfig.get(k)!=config[k] for k in config if k not in {'schema','sources'})
            or result.get('producer_source_snapshot')!=plan.get('producer_source_snapshot')
            or value.get('schema')!='manual_republication_work_metadata_read/v10' or value.get('action')!=METADATA_ACTION or value.get('api_business_success') is not True
            or value.get('request_count')!=1 or intent.get('submission_claim')!=result.get('prior_submission_claim')
            or intent['submission_claim']!=reference(SUBMIT_CLAIM)):
        raise ValueError('verify_actual_metadata_receipt_required')
    validate_producer_snapshot(plan,oldconfig,result['plan']);_refs(result);_refs(candidate);_refs(intent)
    prior=_metadata_prior(config,oldrequest)
    if prior!=plan['prior']:raise ValueError('verify_original_submission_subject_changed')
    projection=_read(value['projection']);item=candidate.get('candidate',{});epoch=intent.get('native_created_epoch');window=item.get('creation_second_window',{})
    post_id=intent.get('post_id');url=intent.get('canonical_url')
    if (candidate.get('schema')!='submitted_new_publication_candidate/v1' or candidate.get('metadata_result')!=intent['metadata_result'] or candidate.get('metadata_receipt')!=intent['metadata_receipt']
            or candidate.get('submission_claim')!=intent['submission_claim'] or candidate.get('projection')!=value['projection']
            or item not in value.get('candidates',[]) or item not in projection.get('candidates',[])
            or not isinstance(post_id,str) or not post_id.isdecimal() or len(post_id)<10 or item.get('aweme_id')!=post_id
            or post_id in prior['excluded_old_post_ids'] or url!='https://www.douyin.com/video/'+post_id or item.get('canonical_url')!=url
            or item.get('full_metadata_match') is not True or item.get('post_verified') is not False or item.get('numeric_duration_verified') is not False
            or type(epoch) is not int or candidate.get('native_created_epoch')!=epoch or candidate.get('native_epoch_precision_seconds')!=1
            or window.get('start')!=epoch or window.get('end_exclusive')!=epoch+1 or window.get('submission_at')!=prior['submission_at']
            or window.get('relation')!='after_claim' or epoch+1<=prior['submission_at']
            or intent.get('native_created_iso')!=datetime.fromtimestamp(epoch,tz=timezone(timedelta(hours=8))).isoformat()
            or candidate.get('native_created_iso')!=intent['native_created_iso']
            or abs(intent.get('expected_duration_seconds',0)-prior['source_duration_seconds'])>1e-6 or intent.get('duration_tolerance_seconds')!=.5
            or intent.get('canonical_navigations_allowed')!=1 or any(intent.get(k)!=0 for k in ('new_tabs_allowed','publications_allowed','selections_allowed','confirmations_allowed','files_allowed'))
            or intent.get('fields_written_allowed') is not False or intent.get('reuse_existing_strict_published_work_reader') is not True
            or intent.get('required_ai_label')!=prior['selected_label'] or intent.get('require_fiction_notice') is not True):
        raise ValueError('verify_native_new_candidate_required')
    return dict(prior,verification_intent=request['verification_intent'],candidate=intent['candidate'],metadata_result=intent['metadata_result'],metadata_receipt=intent['metadata_receipt'],
        post_id=post_id,canonical_url=url,native_created_epoch=epoch,native_created_iso=intent['native_created_iso'])


def _metadata_prior(config,request):
    intent=_read(request['metadata_read_intent']);result=_read(intent['publication_result']);receipt=_read(intent['publication_receipt'])
    plan=_read(result['plan']);claim=_read(result['claim']);oldconfig=_read(plan['config']);oldrequest=_read(plan['request'])
    folder=Path(result['plan']['path']).resolve().parent;publication=result.get('publication',{})
    if (intent.get('schema')!='submitted_metadata_read_intent/v1' or intent.get('authority')!=config['authority'] or intent.get('operator_authority')!=config['operator_authority']
            or intent.get('metadata')!=config['metadata'] or intent.get('method')!='GET' or intent.get('url')!=WORK_LIST_URL or intent.get('headers')!={}
            or type(intent.get('request_limit')) is not int or intent['request_limit']!=1 or intent.get('publication_actions_allowed')!=0
            or any(intent.get(k) is not False for k in ('request_body_allowed','navigation_allowed','new_tab_allowed','fields_written_allowed'))
            or folder!=_publish_folder(CONTINUE_ACTION) or result.get('schema')!='manual_republication_runtime_result/v10'
            or result.get('status')!='publication_submitted_verification_pending' or result.get('submitted') is not True or result.get('external_publication_verified') is not False
            or receipt!={'schema':'manual_republication_result_binding/v10','plan':result['plan'],'claim':result['claim'],'result':intent['publication_result']}
            or Path(intent['publication_result']['path']).resolve()!=folder/'RESULT.json' or Path(intent['publication_receipt']['path']).resolve()!=folder/'RESULT_BINDING.json'
            or result['claim']!=reference(folder/'ACTION_CLAIM.json') or plan.get('schema')!=PLAN_SCHEMA or plan.get('action')!=CONTINUE_ACTION
            or oldconfig.get('schema')!=CONFIG_SCHEMA or any(oldconfig.get(k)!=config[k] for k in config if k not in {'schema','sources'})
            or claim.get('schema')!='manual_republication_publish_action_claim/v10' or claim.get('action')!=CONTINUE_ACTION
            or claim.get('plan')!=result['plan'] or claim.get('config')!=plan['config'] or claim.get('request')!=plan['request']
            or result.get('producer_source_snapshot')!=plan.get('producer_source_snapshot')
            or publication.get('schema')!='manual_republication_publish_once/v10' or publication.get('action')!=CONTINUE_ACTION
            or publication.get('status')!='submitted_verification_pending' or any(publication.get(k) is not True for k in ('publish_clicked','submitted','declaration_confirmed'))
            or any(publication.get(k) is not False for k in ('navigation_performed','file_selected'))
            or result.get('submission_claim')!=intent['submission_claim'] or publication.get('submission_claim')!=intent['submission_claim']
            or intent['submission_claim']!=reference(SUBMIT_CLAIM)):
        raise ValueError('metadata_original_submitted_once_required')
    validate_producer_snapshot(plan,oldconfig,result['plan']);_refs(result);_refs(intent)
    prior=_continue_prior(config,oldrequest)
    if prior!=plan['prior']:raise ValueError('metadata_original_intent_changed')
    submission=_read(intent['submission_claim']);stamp=submission.get('at_epoch')
    if (submission.get('schema')!='manual_republication_submit_claim/v10' or submission.get('plan')!=result['plan'] or submission.get('action_claim')!=result['claim']
            or submission.get('config')!=plan['config'] or submission.get('request')!=plan['request'] or submission.get('authority')!=config['authority']
            or submission.get('metadata')!=config['metadata'] or submission.get('file_selection_claim')!=prior['file_selection_claim']
            or any(submission.get(k)!=config[k] for k in ('owner_id','generation','tab_id'))
            or submission.get('allowed_publish_clicks')!=1 or submission.get('automatic_replay_allowed') is not False
            or type(stamp) not in {int,float} or not math.isfinite(stamp)):
        raise ValueError('metadata_original_submit_claim_changed')
    requirements=_read(_read(oldrequest['declaration_contract'])['post_submit_verification_requirements'])
    if set(intent.get('excluded_old_post_ids',[]))!=set(requirements['excluded_old_post_ids']):raise ValueError('metadata_old_post_exclusions_changed')
    return dict(prior,metadata_read_intent=request['metadata_read_intent'],publication_result=intent['publication_result'],publication_receipt=intent['publication_receipt'],
        prior_submission_claim=intent['submission_claim'],submission_at=stamp,excluded_old_post_ids=intent['excluded_old_post_ids'])


def _continue_prior(config,request):
    prior=_publish_prior(config,request);contract=_read(request['selected_state_contract'])
    result=_read(contract['blocked_result']);receipt=_read(contract['blocked_receipt']);oldplan=_read(result['plan']);oldclaim=_read(result['claim'])
    oldconfig=_read(oldplan['config']);oldrequest=_read(oldplan['request']);folder=Path(result['plan']['path']).resolve().parent
    failure=_read(contract['failure'])
    if (contract.get('schema')!='semi_radio_selection_display_contract/v1' or contract.get('parent_selection_contract')!=request['declaration_contract']
            or contract.get('authority')!=config['authority'] or contract.get('expected_selected_label')!=prior['selected_label']
            or contract.get('observed_native_input_checked')!=[False]*6 or contract.get('native_checked_must_not_be_falsified') is not True
            or contract.get('declaration_confirmed') is not False or contract.get('required_confirmed_section_value')!=prior['selected_label']
            or contract.get('continuation_selections_allowed')!=0 or contract.get('continuation_confirmations_allowed')!=1 or contract.get('continuation_publications_allowed')!=1
            or any(contract.get(k) is not True for k in ('no_original_action_replay','no_new_upload','logical_publication_intent_unchanged'))
            or folder!=RUN.resolve()/'manual_runtime_v10/publish_001'
            or result.get('schema')!='manual_republication_runtime_result/v10' or result.get('status')!='blocked_no_submission'
            or result.get('submitted') is not False or result.get('submission_not_attempted') is not True
            or receipt!={'schema':'manual_republication_result_binding/v10','plan':result['plan'],'claim':result['claim'],'result':contract['blocked_result']}
            or result.get('failure',{}).get('diagnostics')!=contract['failure'] or result['failure'].get('reason_code')!='controls_selection_unconfirmed'
            or Path(contract['blocked_result']['path']).resolve()!=folder/'RESULT.json' or Path(contract['blocked_receipt']['path']).resolve()!=folder/'RESULT_BINDING.json'
            or result['claim']!=reference(folder/'ACTION_CLAIM.json') or oldplan.get('schema')!=PLAN_SCHEMA or oldplan.get('action')!=PUBLISH_ACTION
            or oldrequest.get('action')!=PUBLISH_ACTION or oldclaim.get('schema')!='manual_republication_publish_action_claim/v10' or oldclaim.get('action')!=PUBLISH_ACTION
            or oldclaim.get('plan')!=result['plan'] or oldclaim.get('config')!=oldplan['config'] or oldclaim.get('request')!=oldplan['request']
            or any(oldconfig.get(k)!=config[k] for k in config if k not in {'schema','sources'})
            or any(oldrequest.get(k)!=request[k] for k in PUBLISH_FIELDS)
            or result.get('producer_source_snapshot')!=oldplan.get('producer_source_snapshot')
            or failure.get('schema')!='manual_declaration_publication_failure/v10' or failure.get('phase')!='read_selected_native_group'
            or failure.get('reason_code')!='controls_selection_unconfirmed' or failure.get('selection_click_dispatched') is not True
            or any(failure.get(k) is not False for k in ('confirmation_click_dispatched','declaration_confirmed','publish_click_dispatched','submission_claimed','file_selected','navigation_performed','fields_written'))
            or failure.get('submission_claim') is not None or failure.get('rpc_trace')!=contract['rpc_trace']
            or failure.get('native_diagnostics',{}).get('screenshot')!=contract['screenshot']):raise ValueError('continue_exact_known_preconfirmation_block_required')
    validate_producer_snapshot(oldplan,oldconfig,result['plan']);_refs(result);_refs(contract)
    if _publish_prior(config,oldrequest)!=oldplan['prior']:raise ValueError('continue_original_publish_subject_changed')
    if any((folder/'publication'/name).exists() for name in ('PUBLISH_PREFLIGHT.json','POST_SUBMIT.json','POST_SUBMIT_OBSERVATIONS.json')):raise ValueError('continue_original_must_not_have_submitted')
    basis=contract.get('component_selection_basis',{})
    if (basis.get('unique_selected_label_class')!='semi-radio-checked' or basis.get('only_label_index')!=0
            or any(basis.get(k) is not True for k in ('all_other_labels_without_selected_class','native_label_associations_unchanged','all_12_stable_samples_match'))
            or basis.get('exact_preview_text')!='作者声明：'+prior['selected_label']
            or basis.get('unique_confirmation_button')!={'text':'确定','type':'button','disabled':False}):raise ValueError('continue_public_ui_semantics_required')
    baseline=_read(prior['modal_controls']);samples=_read(contract['selected_samples']).get('samples')
    if not isinstance(samples,list) or len(samples)!=12:raise ValueError('continue_twelve_real_samples_required')
    for sample in samples:
        labels=sample.get('labels',[]);radios=sample.get('native_controls',[])
        confirmations=[b for b in sample.get('buttons',[]) if b.get('text')=='确定']
        selected=[l for l in labels if 'semi-radio-checked' in l.get('class_name','').split()]
        stable_labels=len(labels)==6 and all({k:v for k,v in label.items() if k!='class_name'}=={k:v for k,v in original.items() if k!='class_name'} for label,original in zip(labels,baseline['labels']))
        if (sample.get('schema')!='manual_native_declaration_controls/v10' or sample.get('render_complete') is not True or sample.get('truncated') is not False
                or sample.get('location')!=baseline['location'] or sample.get('native_associations_complete') is not True
                or not stable_labels or radios!=baseline['native_controls'] or len(selected)!=1 or selected[0].get('text')!=prior['selected_label'] or selected[0].get('index')!=0
                or len(confirmations)!=1 or confirmations[0].get('type')!='button' or confirmations[0].get('disabled') is not False
                or not any(leaf.get('text')==basis['exact_preview_text'] and 'declaratonBar-v3zoOB' in leaf.get('class_name','').split() for leaf in sample.get('visible_leaves',[]))):
            raise ValueError('continue_unchanged_component_selection_evidence_required')
    rows=[json.loads(line) for line in Path(contract['rpc_trace']['path']).read_text(encoding='utf8').splitlines() if line.strip()]
    mutations=[row for row in rows if row.get('event')=='rpc_dispatched' and row.get('action') not in {'current_url','evaluate','locator_count','inner_text','get_attribute','wait_for_timeout','screenshot','upload_check_proof'}]
    if (len(mutations)!=1 or mutations[0].get('action')!='click' or mutations[0].get('phase')!='native_select_ai_label'
            or mutations[0].get('selector')!='div.semi-modal:visible label.semi-radio' or mutations[0].get('index')!=0):raise ValueError('continue_original_one_selection_only_required')
    return dict(prior,selected_state_contract=request['selected_state_contract'],blocked_result=contract['blocked_result'],blocked_receipt=contract['blocked_receipt'],
        submission_failure=contract['failure'],selected_samples=contract['selected_samples'],selection_trace=contract['rpc_trace'],selection_reused=True)


def _publish_folder(action):
    return RUN.resolve()/'manual_runtime_v10'/('continuation_selected_001' if action==CONTINUE_ACTION else 'publish_001')


def _snapshot_sources(folder,config):
    refs={}
    for key in ('runtime_v10','flow_v10','app'):
        original=SOURCE_PATHS[key];path=folder/'producer_source_snapshot'/(key+'.py');path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(original.read_bytes());stream.flush();os.fsync(stream.fileno())
        ref=reference(path)
        if ref['sha256']!=config['sources'][key]['sha256']:raise ValueError('controls_producer_changed_during_prepare')
        refs[key]=ref
    return refs


def validate_producer_snapshot(plan,config,plan_ref):
    # Historical stage-one evidence stays verifiable after a separately reviewed
    # same-version writer delta. Never execute these archived source bytes.
    refs=plan.get('producer_source_snapshot')
    if not isinstance(refs,dict) or set(refs)!={'runtime_v10','flow_v10','app'}:raise ValueError('controls_producer_snapshot_required')
    for key,ref in refs.items():
        if (Path(ref['path']).resolve()!=Path(plan_ref['path']).resolve().parent/'producer_source_snapshot'/(key+'.py')
                or reference(ref['path'])!=ref or ref['sha256']!=config['sources'][key]['sha256']):raise ValueError('controls_producer_snapshot_changed')
    return refs


def _state(config):return base._state(_projection(config))


def validate_live(actor,resource,config):
    _scope(config);return base.validate_live(actor,resource,_projection(config))


def prepare(config_ref,request_ref,output_directory):
    folder=Path(output_directory).resolve()
    if not folder.is_relative_to(RUN.resolve()) or folder.exists():raise ValueError('declaration_new_plan_directory_required')
    config,request=_config(config_ref),_request(request_ref,config_ref)
    publishing=request['action'] in {PUBLISH_ACTION,CONTINUE_ACTION}
    if publishing and (folder!=_publish_folder(request['action']) or SUBMIT_CLAIM.exists()):raise ValueError('publish_unique_new_intent_slot_required')
    if request['action']==METADATA_ACTION and folder!=RUN.resolve()/'manual_runtime_v10/readback_001':raise ValueError('metadata_unique_read_slot_required')
    if request['action']==VERIFY_ACTION and folder!=RUN.resolve()/'manual_runtime_v10/verify_new_001':raise ValueError('verify_unique_read_slot_required')
    if request['action']==CAPTION_ACTION and folder!=RUN.resolve()/'manual_runtime_v10/caption_scope001':raise ValueError('caption_unique_read_slot_required')
    state,prior=_state(config),_prior(config,request)
    snapshots=_snapshot_sources(folder,config)
    return _once(folder/'PLAN.json',dict(schema=PLAN_SCHEMA,config=config_ref,request=request_ref,action=request['action'],
        state=state,prior=prior,producer_source_snapshot=snapshots,navigation_allowed=request['action']==VERIFY_ACTION,canonical_navigations_allowed=int(request['action']==VERIFY_ACTION),file_selection_allowed=False,
        selections_allowed=int(request['action']==PUBLISH_ACTION),confirmations_allowed=int(publishing),submissions_allowed=int(publishing),requests_allowed=int(request['action']==METADATA_ACTION),
        scoped_reads_allowed=int(request['action']==CAPTION_ACTION),screenshots_allowed=int(request['action']==CAPTION_ACTION)))


def _plan(ref):
    plan=_read(ref)
    if (plan.get('schema')!=PLAN_SCHEMA or not Path(ref['path']).resolve().is_relative_to(RUN.resolve())
            or plan.get('file_selection_allowed') is not False):raise ValueError('declaration_plan_invalid')
    config=_config(plan['config']);request=_request(plan['request'],plan['config'])
    publishing=request['action'] in {PUBLISH_ACTION,CONTINUE_ACTION}
    if (plan.get('action')!=request['action'] or _prior(config,request)!=plan['prior']
            or plan.get('navigation_allowed') is not (request['action']==VERIFY_ACTION)
            or type(plan.get('canonical_navigations_allowed')) is not int or plan['canonical_navigations_allowed']!=int(request['action']==VERIFY_ACTION)
            or type(plan.get('selections_allowed')) is not int or plan['selections_allowed']!=int(request['action']==PUBLISH_ACTION)
            or any(type(plan.get(k)) is not int or plan[k]!=int(publishing) for k in ('confirmations_allowed','submissions_allowed'))
            or type(plan.get('requests_allowed')) is not int or plan['requests_allowed']!=int(request['action']==METADATA_ACTION)
            or any(type(plan.get(k)) is not int or plan[k]!=int(request['action']==CAPTION_ACTION) for k in ('scoped_reads_allowed','screenshots_allowed'))
            or publishing and Path(ref['path']).resolve().parent!=_publish_folder(request['action'])
            or request['action']==METADATA_ACTION and Path(ref['path']).resolve().parent!=RUN.resolve()/'manual_runtime_v10/readback_001'
            or request['action']==VERIFY_ACTION and Path(ref['path']).resolve().parent!=RUN.resolve()/'manual_runtime_v10/verify_new_001'
            or request['action']==CAPTION_ACTION and Path(ref['path']).resolve().parent!=RUN.resolve()/'manual_runtime_v10/caption_scope001'):raise ValueError('declaration_prior_changed')
    validate_producer_snapshot(plan,config,ref)
    return plan,config,request


def status(plan_ref):
    plan=_read(plan_ref);folder=Path(plan_ref['path']).parent
    if plan.get('schema')!=PLAN_SCHEMA or not folder.resolve().is_relative_to(RUN.resolve()):raise ValueError('declaration_plan_invalid')
    claim,result,binding=folder/'ACTION_CLAIM.json',folder/'RESULT.json',folder/'RESULT_BINDING.json'
    if result.exists() and binding.exists():
        proof=_read(reference(binding));value=_read(proof['result'])
        statuses={'declaration_controls_observed'} if plan['action']==ACTION else {'submitted_metadata_observed'} if plan['action']==METADATA_ACTION else {'submitted_candidate_verified','submitted_candidate_not_verified'} if plan['action']==VERIFY_ACTION else {'current_caption_verified','current_caption_not_verified'} if plan['action']==CAPTION_ACTION else {'publication_submitted_verification_pending','blocked_no_submission'}
        if proof.get('plan')!=plan_ref or proof.get('claim')!=reference(claim) or proof.get('result')!=reference(result) or value.get('status') not in statuses or value.get('plan')!=plan_ref:raise ValueError('declaration_cached_result_changed')
        _refs(value)
        return {'status':value['status'],'result':proof['result'],'receipt':reference(binding)}
    return {'status':'outcome_unknown','scope':'manual_publication' if plan['action'] in {PUBLISH_ACTION,CONTINUE_ACTION} else 'submitted_work_metadata' if plan['action']==METADATA_ACTION else 'submitted_public_verification' if plan['action']==VERIFY_ACTION else 'current_public_caption' if plan['action']==CAPTION_ACTION else 'declaration_disclosure','automatic_replay_allowed':False} if claim.exists() else {'status':'prepared','plan':plan_ref}


def claim_submission(actor,resource,config,request,preflight_ref):
    """Create the new-intent once marker only at the final native-click boundary."""
    preflight=_read(preflight_ref);folder=Path(preflight_ref['path']).resolve().parent
    if request.get('action') not in {PUBLISH_ACTION,CONTINUE_ACTION} or folder!=_publish_folder(request['action'])/'publication' or Path(preflight_ref['path']).name!='PUBLISH_PREFLIGHT.json':raise ValueError('publish_exact_preflight_path_required')
    action_ref=reference(folder.parent/'ACTION_CLAIM.json');action=_read(action_ref);plan_ref=action['plan'];plan,checked,expected_request=_plan(plan_ref)
    if (checked!=config or expected_request!=request or action.get('schema')!='manual_republication_publish_action_claim/v10'
            or action.get('action')!=request['action'] or action.get('config')!=plan['config'] or action.get('request')!=plan['request']
            or action.get('navigation_allowed') is not False or action.get('file_selection_allowed') is not False
            or type(action.get('selections_allowed')) is not int or action['selections_allowed']!=int(request['action']==PUBLISH_ACTION)
            or any(type(action.get(k)) is not int or action[k]!=1 for k in ('confirmations_allowed','submissions_allowed'))
            or action.get('actor_thread_id')!=threading.get_ident() or any(action.get(k)!=config[k] for k in ('owner_id','generation','tab_id'))
            or os.getpid()!=config['backend_pid'] or validate_live(actor,resource,config)!=plan['state']):raise ValueError('publish_preflight_original_context_required')
    observed=preflight.get('observed_at');now=time.time()
    if (preflight.get('schema')!='manual_republication_publish_preflight/v10' or preflight.get('action_claim')!=action_ref
            or preflight.get('declaration_contract')!=request['declaration_contract'] or preflight.get('file_selection_claim')!=plan['prior']['file_selection_claim']
            or preflight.get('metadata')!=config['metadata'] or type(observed) not in {int,float} or not math.isfinite(observed) or not 0<=now-observed<=30
            or preflight.get('selected_label')!=plan['prior']['selected_label'] or preflight.get('declaration_confirmed') is not True or preflight.get('modal_closed') is not True):raise ValueError('publish_fresh_confirmed_preflight_required')
    _refs(preflight);settings=_read(preflight['settings']);form=_read(preflight['form_readback']);fence=_read(preflight['draft_fence']);metadata=_read(config['metadata'])
    button=preflight.get('publish_button',{})
    if (settings.get('public_verified') is not True or settings.get('immediate_verified') is not True
            or form.get('title',{}).get('content')!=metadata['title'] or form.get('description_exact') is not True
            or ''.join(form.get('description_core','').replace('\u200b','').split())!=''.join(metadata['description'].replace('\u200b','').split())
            or len(form.get('hashtag_tokens',[]))!=len(metadata['hashtags']) or set(form['hashtag_tokens'])!=set(metadata['hashtags'])
            or button.get('unique_count')!=1 or button.get('text')!='发布' or any(button.get(k) is not True for k in ('visible','enabled','center_hit'))):raise ValueError('publish_actual_public_immediate_form_required')
    native=fence.get('native_upload_proof',{});video=fence.get('video',{});duration=video.get('duration')
    if (native.get('schema')!='upload_check_transition/v2' or native.get('selection_nonce')!=plan['prior']['selection_nonce']
            or any(native.get('diagnostic',{}).get(k)!=v for k,v in plan['prior']['upload_route_baseline'].items())
            or video.get('origin')!='https://creator.douyin.com' or video.get('path')!='/creator-micro/content/post/video'
            or video.get('visible_video_count')!=1 or type(duration) not in {int,float} or not math.isfinite(duration)
            or abs(duration-plan['prior']['source_duration_seconds'])>.5 or type(video.get('ready_state')) is not int or video['ready_state']<1):raise ValueError('publish_original_draft_fence_required')
    _scope(config,True)
    # No existing marker is returned, including for this same request: doing so
    # could authorize a second native click after a lost acknowledgement.
    return _once(SUBMIT_CLAIM,dict(schema='manual_republication_submit_claim/v10',plan=plan_ref,action_claim=action_ref,config=plan['config'],request=plan['request'],
        authority=config['authority'],declaration_contract=request['declaration_contract'],metadata=config['metadata'],media=metadata['media'],file_selection_claim=plan['prior']['file_selection_claim'],
        owner_id=actor.owner_id,generation=actor.generation,tab_id=config['tab_id'],preflight=preflight_ref,at_epoch=time.time(),allowed_publish_clicks=1,automatic_replay_allowed=False))


def _perform(actor,resource,plan_ref,arm_ref,run_action):
    plan,config,request=_plan(plan_ref)
    if status(plan_ref)['status']!='prepared':return status(plan_ref)
    if os.getpid()!=config['backend_pid'] or reference(ARM)!=arm_ref or validate_live(actor,resource,config)!=plan['state']:raise ValueError('declaration_original_context_changed')
    folder=Path(plan_ref['path']).parent
    publishing=request['action'] in {PUBLISH_ACTION,CONTINUE_ACTION}
    reading=request['action']==METADATA_ACTION
    verifying=request['action']==VERIFY_ACTION
    captioning=request['action']==CAPTION_ACTION
    claim=dict(schema='manual_republication_publish_action_claim/v10' if publishing else 'manual_republication_metadata_action_claim/v10' if reading else 'manual_republication_verify_action_claim/v10' if verifying else 'manual_republication_caption_action_claim/v10' if captioning else 'manual_republication_controls_action_claim/v10',plan=plan_ref,config=plan['config'],request=plan['request'],
        owner_id=actor.owner_id,generation=actor.generation,tab_id=config['tab_id'],actor_thread_id=threading.get_ident(),at_epoch=time.time(),
        action=request['action'],navigation_allowed=verifying,canonical_navigations_allowed=int(verifying),file_selection_allowed=False,selections_allowed=int(request['action']==PUBLISH_ACTION),confirmations_allowed=int(publishing),submissions_allowed=int(publishing),requests_allowed=int(reading),scoped_reads_allowed=int(captioning),screenshots_allowed=int(captioning))
    try:claim_ref=_once(folder/'ACTION_CLAIM.json',claim)
    except FileExistsError:return status(plan_ref)
    try:
        value=run_action(actor,resource,config,request,folder/('publication' if publishing else 'readback' if reading else 'verification' if verifying else 'caption' if captioning else 'inspection'));_plan(plan_ref)
        if reference(ARM)!=arm_ref or validate_live(actor,resource,config)!=plan['state']:raise ValueError('declaration_context_changed_after_inspection')
        if captioning:
            if (value.get('schema')!='manual_republication_public_caption/v10' or value.get('action')!=CAPTION_ACTION
                    or value.get('post_id')!=plan['prior']['post_id'] or value.get('canonical_url')!=plan['prior']['canonical_url']
                    or value.get('canonical_navigations_count')!=0 or value.get('api_request_count')!=0 or value.get('scoped_read_count')!=1
                    or type(value.get('post_verified')) is not bool or type(value.get('numeric_duration_verified')) is not bool
                    or any(value.get(k) is not False for k in ('input_performed','selection_performed','declaration_confirmed','publish_clicked','file_selected','submitted','navigation_performed'))):
                raise ValueError('caption_same_page_read_only_receipt_required')
            _refs(value);native=_read(value['published_evidence']);video=_read(value['video_probe']);duration=video.get('duration')
            if value['post_verified'] and (any(native.get(k) is not True for k in ('verified','full_caption_verified','hashtags_verified','ai_label_visible','fiction_notice_visible'))
                    or native.get('expected_post_id')!=plan['prior']['post_id'] or native.get('url')!=plan['prior']['canonical_url']):raise ValueError('caption_explicit_full_metadata_scope_required')
            if value['numeric_duration_verified'] and (video.get('origin')!='https://www.douyin.com' or video.get('path')!='/video/'+plan['prior']['post_id'] or video.get('visible_video_count')!=1
                    or type(duration) not in {int,float} or not math.isfinite(duration) or abs(duration-plan['prior']['source_duration_seconds'])>.5
                    or type(video.get('ready_state')) is not int or video['ready_state']<2):raise ValueError('caption_actual_scoped_player_required')
            passed=value['post_verified'] and value['numeric_duration_verified']
            if passed and value.get('screenshot',{}).get('status')!='saved':raise ValueError('caption_native_screenshot_required')
            ref=_once(folder/'RESULT.json',dict(schema='manual_republication_runtime_result/v10',status='current_caption_verified' if passed else 'current_caption_not_verified',plan=plan_ref,claim=claim_ref,
                caption=dict(value,full_metadata_verified=passed,full_caption_verified=native.get('full_caption_verified') is True),full_metadata_verified=passed,
                scoped_evidence=value['published_evidence'],legacy_verification_result=plan['prior']['legacy_verification_result'],legacy_scope_evidence=plan['prior']['legacy_scope_evidence'],
                prior_submission_claim=plan['prior']['prior_submission_claim'],post_id=plan['prior']['post_id'],canonical_url=plan['prior']['canonical_url'],
                published_at=plan['prior']['native_created_iso'],published_at_source='native_work_list_create_time',producer_source_snapshot=plan['producer_source_snapshot'],
                submitted=False,new_submission_actions=0,external_publication_verified=passed,old_claims_and_unknown_unchanged=True,account_pause_changed=False))
            receipt=_once(folder/'RESULT_BINDING.json',dict(schema='manual_republication_result_binding/v10',plan=plan_ref,claim=claim_ref,result=ref))
            return {'status':'current_caption_verified' if passed else 'current_caption_not_verified','result':ref,'receipt':receipt}
        if verifying:
            if (value.get('schema')!='manual_republication_public_verification/v10' or value.get('action')!=VERIFY_ACTION
                    or value.get('post_id')!=plan['prior']['post_id'] or value.get('canonical_url')!=plan['prior']['canonical_url']
                    or value.get('canonical_navigations_count')!=1 or value.get('api_request_count')!=0 or value.get('navigation_performed') is not True
                    or type(value.get('post_verified')) is not bool or type(value.get('numeric_duration_verified')) is not bool
                    or any(value.get(k) is not False for k in ('input_performed','selection_performed','declaration_confirmed','publish_clicked','file_selected','submitted'))):
                raise ValueError('verify_read_only_receipt_required')
            _refs(value);native=_read(value['published_evidence']);video=_read(value['video_probe']);duration=video.get('duration')
            if value['post_verified'] and (native.get('verified') is not True or native.get('expected_post_id')!=plan['prior']['post_id'] or native.get('url')!=plan['prior']['canonical_url']):raise ValueError('verify_actual_native_detail_required')
            if value['numeric_duration_verified'] and (video.get('origin')!='https://www.douyin.com' or video.get('path')!='/video/'+plan['prior']['post_id'] or video.get('visible_video_count')!=1
                    or type(duration) not in {int,float} or not math.isfinite(duration) or abs(duration-plan['prior']['source_duration_seconds'])>.5
                    or type(video.get('ready_state')) is not int or video['ready_state']<2):raise ValueError('verify_actual_full_duration_required')
            passed=value['post_verified'] and value['numeric_duration_verified']
            if passed and value.get('screenshot',{}).get('status')!='saved':raise ValueError('verify_native_screenshot_required')
            ref=_once(folder/'RESULT.json',dict(schema='manual_republication_runtime_result/v10',status='submitted_candidate_verified' if passed else 'submitted_candidate_not_verified',plan=plan_ref,claim=claim_ref,
                verification=value,prior_submission_claim=plan['prior']['prior_submission_claim'],post_id=plan['prior']['post_id'],canonical_url=plan['prior']['canonical_url'],
                native_created_epoch=plan['prior']['native_created_epoch'],published_at=plan['prior']['native_created_iso'],published_at_source='native_work_list_create_time',
                producer_source_snapshot=plan['producer_source_snapshot'],submitted=False,new_submission_actions=0,external_publication_verified=passed,old_claims_and_unknown_unchanged=True,account_pause_changed=False))
            receipt=_once(folder/'RESULT_BINDING.json',dict(schema='manual_republication_result_binding/v10',plan=plan_ref,claim=claim_ref,result=ref))
            return {'status':'submitted_candidate_verified' if passed else 'submitted_candidate_not_verified','result':ref,'receipt':receipt}
        if reading:
            if (value.get('schema')!='manual_republication_work_metadata_read/v10' or value.get('action')!=METADATA_ACTION or value.get('request_count')!=1
                    or type(value.get('api_business_success')) is not bool
                    or any(value.get(k) is not False for k in ('input_performed','selection_performed','declaration_confirmed','publish_clicked','navigation_performed','file_selected','submitted','post_verified','numeric_duration_verified'))):
                raise ValueError('metadata_read_only_receipt_required')
            _refs(value)
            if reference(SUBMIT_CLAIM)!=plan['prior']['prior_submission_claim']:raise ValueError('metadata_original_submission_changed')
            ref=_once(folder/'RESULT.json',dict(schema='manual_republication_runtime_result/v10',status='submitted_metadata_observed',plan=plan_ref,claim=claim_ref,
                readback=value,prior_submission_claim=plan['prior']['prior_submission_claim'],producer_source_snapshot=plan['producer_source_snapshot'],submitted=False,
                new_submission_actions=0,external_publication_verified=False,old_claims_and_unknown_unchanged=True,account_pause_changed=False))
            receipt=_once(folder/'RESULT_BINDING.json',dict(schema='manual_republication_result_binding/v10',plan=plan_ref,claim=claim_ref,result=ref))
            return {'status':'submitted_metadata_observed','result':ref,'receipt':receipt}
        if publishing:
            if (value.get('schema')!='manual_republication_publish_once/v10' or value.get('action')!=request['action'] or value.get('status')!='submitted_verification_pending'
                    or any(value.get(k) is not True for k in ('publish_clicked','submitted','declaration_confirmed'))
                    or value.get('selection_performed') is not (request['action']==PUBLISH_ACTION)
                    or request['action']==CONTINUE_ACTION and (value.get('selection_reused') is not True or value.get('selected_state_contract')!=request['selected_state_contract'])
                    or any(value.get(k) is not False for k in ('navigation_performed','file_selected'))
                    or value.get('submission_claim')!=reference(SUBMIT_CLAIM)):
                raise ValueError('publish_manual_submission_receipt_required')
            _refs(value);submission=_read(value['submission_claim'])
            if submission.get('plan')!=plan_ref or submission.get('action_claim')!=claim_ref or submission.get('preflight')!=value.get('preflight'):raise ValueError('publish_submission_claim_changed')
            ref=_once(folder/'RESULT.json',dict(schema='manual_republication_runtime_result/v10',status='publication_submitted_verification_pending',plan=plan_ref,claim=claim_ref,
                publication=value,submission_claim=value['submission_claim'],producer_source_snapshot=plan['producer_source_snapshot'],submitted=True,
                external_publication_verified=False,old_claims_and_unknown_unchanged=True,account_pause_changed=False))
            receipt=_once(folder/'RESULT_BINDING.json',dict(schema='manual_republication_result_binding/v10',plan=plan_ref,claim=claim_ref,result=ref))
            return {'status':'publication_submitted_verification_pending','result':ref,'receipt':receipt}
        if (value.get('schema')!='manual_republication_declaration_controls/v10' or value.get('action')!=ACTION
                or value.get('action_claim')!=claim_ref or value.get('render_complete') is not True
                or any(value.get(k) is not False for k in ('input_performed','selection_performed','declaration_confirmed','publish_clicked','navigation_performed','file_selected','submitted'))):raise ValueError('controls_read_only_receipt_required')
        _refs(value)
        controls=_read(value['modal_controls'])
        if controls.get('render_complete') is not True:raise ValueError('controls_complete_modal_required')
        ref=_once(folder/'RESULT.json',dict(schema='manual_republication_runtime_result/v10',status='declaration_controls_observed',plan=plan_ref,claim=claim_ref,producer_source_snapshot=plan['producer_source_snapshot'],
            inspection=value,file_selection_claim=plan['prior']['file_selection_claim'],submitted=False,old_claims_and_unknown_unchanged=True,account_pause_changed=False))
        receipt=_once(folder/'RESULT_BINDING.json',dict(schema='manual_republication_result_binding/v10',plan=plan_ref,claim=claim_ref,result=ref))
        return {'status':'declaration_controls_observed','result':ref,'receipt':receipt}
    except Exception as error:
        value=dict(schema='manual_republication_declaration_unknown/v10',plan=plan_ref,claim=claim_ref,scope='manual_publication' if publishing else 'submitted_work_metadata' if reading else 'submitted_public_verification' if verifying else 'current_public_caption' if captioning else 'declaration_disclosure',error_type=type(error).__name__,automatic_replay_allowed=False)
        if type(error) is getattr(run_action,'_blocked_class',None) and getattr(error,'code',None) in getattr(run_action,'_safe_codes',()):value['reason_code']=error.code
        for diagnostics in ((folder/'publication/SUBMISSION_FAILURE.json',folder/'publication/INSPECTION_FAILURE.json') if publishing else (folder/'readback/READ_FAILURE.json',) if reading else (folder/'verification/VERIFY_FAILURE.json',) if verifying else (folder/'caption/CAPTION_FAILURE.json',) if captioning else (folder/'inspection/INSPECTION_FAILURE.json',)):
            if diagnostics.is_file():value['diagnostics']=reference(diagnostics);break
        if publishing and not SUBMIT_CLAIM.exists():
            # Under the sealed flow the only native publish RPC is downstream
            # of claim_submission. UI-selection outcome may be unknown while
            # non-submission is certain; do not describe that as a sent video.
            ref=_once(folder/'RESULT.json',dict(schema='manual_republication_runtime_result/v10',status='blocked_no_submission',plan=plan_ref,claim=claim_ref,
                failure=value,submission_not_attempted=True,submitted=False,automatic_replay_allowed=False,producer_source_snapshot=plan['producer_source_snapshot'],
                old_claims_and_unknown_unchanged=True,account_pause_changed=False))
            receipt=_once(folder/'RESULT_BINDING.json',dict(schema='manual_republication_result_binding/v10',plan=plan_ref,claim=claim_ref,result=ref))
            return {'status':'blocked_no_submission','result':ref,'receipt':receipt}
        if publishing and SUBMIT_CLAIM.is_file():value['submission_claim']=reference(SUBMIT_CLAIM)
        if not (folder/'UNKNOWN.json').exists():_once(folder/'UNKNOWN.json',value)
        return status(plan_ref)


def _load_flow(config):
    path=SOURCE_PATHS['flow_v10']
    if reference(path)!=config['sources']['flow_v10']:raise ValueError('declaration_flow_changed')
    module=types.ModuleType('src.operations_accounts._declaration_inspection_'+config['sources']['flow_v10']['sha256'][:16]);module.__file__,module.__package__=str(path),'src.operations_accounts'
    exec(compile(path.read_bytes(),str(path),'exec'),module.__dict__)
    # Flow must call this freshly loaded runtime's reviewed guards, never a
    # same-name module left in sys.modules by the earlier read-only stage.
    native_run=module.run_action;runtime_bridge=types.SimpleNamespace(**globals())
    def bound_run(actor,resource,config,request,outdir):
        return native_run(actor,resource,config,request,outdir,runtime_bridge=runtime_bridge)
    module.run_action=bound_run
    module.run_action._blocked_class,module.run_action._safe_codes=module.DeclarationControlsBlocked,module.SAFE_REASONS
    return module


def install_if_armed():
    if not ARM.is_file():return {'status':'not_armed'}
    try:
        arm_ref=reference(ARM);arm=_read(arm_ref)
        if set(arm)!={'schema','plan'} or arm['schema']!='manual_republication_runtime_arm/v10':raise ValueError('declaration_arm_invalid')
        route=_read(arm['plan'])
        if route.get('schema')=='manual_work_cleanup_plan/v1':
            cleanup_config=_read(route['config']);cleanup_path=Path(cleanup_config.get('sources',{}).get('cleanup_runtime',{}).get('path','')).resolve()
            if cleanup_path not in {ROOT/'src/operations_accounts/manual_work_cleanup_runtime_v1.py',ROOT/'src/operations_accounts/manual_work_cleanup_delete_runtime_v1.py',ROOT/'src/operations_accounts/manual_session_finish_runtime_v1.py'}:raise ValueError('cleanup_runtime_path_not_allowed')
            cleanup_ref=reference(cleanup_path)
            if cleanup_config.get('sources',{}).get('cleanup_runtime')!=cleanup_ref:raise ValueError('cleanup_runtime_not_pinned')
            cleanup_raw=cleanup_path.read_bytes()
            if hashlib.sha256(cleanup_raw).hexdigest()!=cleanup_ref['sha256']:raise ValueError('cleanup_runtime_changed')
            cleanup=types.ModuleType('src.operations_accounts._manual_cleanup_'+cleanup_ref['sha256'][:16]);cleanup.__file__,cleanup.__package__=str(cleanup_path),'src.operations_accounts'
            exec(compile(cleanup_raw,str(cleanup_path),'exec'),cleanup.__dict__)
            return cleanup.install_if_armed(arm['plan'],arm_ref)
        plan,config,request=_plan(arm['plan']);folder=Path(arm['plan']['path']).parent
        if os.getpid()!=config['backend_pid']:return {'status':'different_process_no_install'}
        if status(arm['plan'])['status']!='prepared':return status(arm['plan'])
        spaces=[t._target.__globals__ for t in threading.enumerate() if t.name=='AccountBrowser-'+config['account_key'] and t.is_alive()
            and getattr(getattr(t,'_target',None),'__name__','')=='_host' and Path(t._target.__code__.co_filename).resolve()==SOURCE_PATHS['host'].resolve() and getattr(t,'_args',())==(config['account_key'],)]
        if len(spaces)!=1:raise ValueError('declaration_unique_original_actor_required')
        namespace=spaces[0];previous=namespace['_poll_manual_windows']
        if getattr(previous,'_manual_declaration_plan',None)==arm['plan']:return {'status':'callback_already_registered'}
        if getattr(previous,'_manual_declaration_plan',None) is not None:raise ValueError('declaration_other_plan_registered')
        flow=_load_flow(config)
        def poll(actor,resource):
            if (actor.account_id,actor.owner_id,actor.generation)!=(config['account_id'],config['owner_id'],config['generation']):return previous(actor,resource)
            defer=False
            try:
                actor._assert_thread();actor._check_owner();value=previous(actor,resource)
                if actor._stack:defer=True;return value
                _perform(actor,resource,arm['plan'],arm_ref,flow.run_action)
            except Exception as error:
                if not (folder/'REFUSED.json').exists():_once(folder/'REFUSED.json',dict(schema='manual_republication_declaration_refusal/v10',plan=arm['plan'],error_type=type(error).__name__,action_started=(folder/'ACTION_CLAIM.json').exists()))
            finally:
                if not defer and namespace['_poll_manual_windows'] is poll:namespace['_poll_manual_windows']=previous
            return None
        poll._manual_declaration_plan=arm['plan'];namespace['_poll_manual_windows']=poll
        return {'status':'callback_registered_waiting_original_actor_tick'}
    except Exception as error:return {'status':'refused','error_type':type(error).__name__,'reason':str(error) if isinstance(error,ValueError) else 'owner_guard_refused'}


def install_fresh_if_armed():
    """Stable app entry; no module-cache replacement or service restart.

    This small loader remains valid when its own callable is cached. The new
    ARM's pinned runtime bytes supply the actual stage handler and guards.
    """
    if not ARM.is_file():return {'status':'not_armed'}
    try:
        arm=_read(reference(ARM))
        if set(arm)!={'schema','plan'} or arm['schema']!='manual_republication_runtime_arm/v10':raise ValueError('controls_loader_arm_invalid')
        plan=_read(arm['plan']);config=_read(plan['config']);path=SOURCE_PATHS['runtime_v10']
        ref=reference(path)
        if config.get('schema')!=CONFIG_SCHEMA or config.get('sources',{}).get('runtime_v10')!=ref:raise ValueError('controls_loader_source_not_pinned')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=ref['sha256'] or reference(path)!=ref:raise ValueError('controls_loader_source_changed')
        module=types.ModuleType('src.operations_accounts._fresh_manual_controls_'+ref['sha256'][:16])
        module.__file__,module.__package__=str(path),'src.operations_accounts'
        exec(compile(raw,str(path),'exec'),module.__dict__)
        return module.install_if_armed()
    except Exception as error:return {'status':'refused','error_type':type(error).__name__,'reason':str(error) if isinstance(error,ValueError) else 'controls_loader_refused'}
