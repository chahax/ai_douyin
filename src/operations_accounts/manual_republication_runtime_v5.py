"""Continue metadata in the same uploaded draft; no navigation/file/publish."""
import json
import os
from pathlib import Path
import threading
import time
import types

from . import manual_republication_runtime_v4 as v4

ROOT=Path(__file__).resolve().parents[2]
RUN=ROOT/'data/production_trials/fanqie_declared_republication_20261117_v1'
ARM=RUN/'manual_runtime_v5/ARM.json'
SOURCE_PATHS=dict(v4.SOURCE_PATHS,runtime_v5=Path(__file__).resolve(),flow_v5=ROOT/'src/operations_accounts/manual_republication_flow_v5.py')
CONFIG_SCHEMA='manual_republication_runtime_config/v5'
REQUEST_SCHEMA='manual_republication_operator_request/v5'
PLAN_SCHEMA='manual_republication_runtime_plan/v5'
reference,_read,_once=v4.reference,v4._read,v4._once
PRIOR_FIELDS=('prior_upload_plan','prior_upload_action','file_selection_claim','prior_unknown','prior_failure','post_upload_editor')


def _projection(config):
    return dict(config,sources={key:config['sources'][key] for key in v4.SOURCE_PATHS})


def _scope(config,verify_media=False):
    if not isinstance(config.get('sources'),dict) or set(config['sources'])!=set(SOURCE_PATHS):raise ValueError('draft_exact_sources_required')
    for key,path in SOURCE_PATHS.items():
        if reference(path)!=config['sources'][key]:raise ValueError('draft_source_changed:'+key)
    v4._scope(_projection(config),verify_media=verify_media)


def _config(ref):
    value=_read(ref)
    fields={'schema','backend_pid','backend_create_time','account_key','account_id','owner_id','generation','binding_version','browser_db','control_db','control_snapshot','manual_command_id','manual_request_sha256','tab_id','authority','operator_authority','metadata','sources'}
    if not isinstance(value,dict) or set(value)!=fields or value['schema']!=CONFIG_SCHEMA:raise ValueError('draft_config_invalid')
    _scope(value,True);return value


def _request(ref,config_ref):
    value=_read(ref)
    if (not isinstance(value,dict) or set(value)!={'schema','config','action',*PRIOR_FIELDS}
            or value['schema']!=REQUEST_SCHEMA or value['config']!=config_ref or value['action']!='prepare_existing_draft'):
        raise ValueError('draft_metadata_only')
    return value


def _prior(config,request):
    if Path(request['file_selection_claim']['path']).resolve()!=(RUN/'FILE_SELECTION_CLAIM.json').resolve():raise ValueError('draft_original_file_claim_required')
    file_claim=_read(request['file_selection_claim']);action=_read(request['prior_upload_action']);plan=_read(request['prior_upload_plan'])
    unknown=_read(request['prior_unknown']);failure=_read(request['prior_failure']);editor=_read(request['post_upload_editor'])
    folder=Path(request['prior_upload_plan']['path']).parent.resolve();prep=folder/'preparation'
    previous=_read(plan['config']);old_request=_read(plan['request'])
    if (not folder.is_relative_to(RUN.resolve()) or plan.get('schema')!=v4.PLAN_SCHEMA
            or action.get('schema')!='manual_republication_resume_action_claim/v4' or action.get('plan')!=request['prior_upload_plan']
            or action.get('config')!=plan['config'] or action.get('request')!=plan['request']
            or previous.get('schema')!=v4.CONFIG_SCHEMA or any(previous.get(k)!=config[k] for k in config if k not in {'schema','sources'})
            or any(previous['sources'][k]!=config['sources'][k] for k in ('runtime_v4','flow_v4'))
            or file_claim.get('schema')!='manual_file_selection_claim/v4' or file_claim.get('action_claim')!=request['prior_upload_action']
            or file_claim.get('plan')!=request['prior_upload_plan'] or file_claim.get('config')!=plan['config'] or file_claim.get('request')!=plan['request']
            or file_claim.get('authority')!=config['authority'] or file_claim.get('metadata')!=config['metadata']
            or file_claim.get('media')!=_read(config['authority'])['media']
            or any(file_claim.get(k)!=config[k] or action.get(k)!=config[k] for k in ('owner_id','generation','tab_id'))
            or unknown.get('schema')!='manual_republication_resume_unknown/v4' or unknown.get('plan')!=request['prior_upload_plan']
            or unknown.get('claim')!=request['prior_upload_action'] or unknown.get('scope')!='resume_preparation' or unknown.get('file_selection_claimed') is not True
            or failure.get('schema')!='manual_resume_failure/v4' or failure.get('reason_code')!='resume_post_selection_unknown'
            or failure.get('cause_code')!='prepare_field_not_unique' or failure.get('upload_attempted') is not True
            or failure.get('file_claim_created') is not True or failure.get('file_selection_dispatched') is not True or failure.get('submitted') is not False
            or editor.get('schema')!='manual_editor_declaration_inventory/v1'
            or editor.get('location')!={'origin':'https://creator.douyin.com','path':'/creator-micro/content/post/video'}
            or editor.get('submission_performed') is not False or editor.get('declaration_selected_by_this_action') is not False):
        raise ValueError('draft_uploaded_subject_or_failure_changed')
    for key,path in [('prior_upload_action',folder/'ACTION_CLAIM.json'),('prior_unknown',folder/'UNKNOWN.json'),('prior_failure',prep/'PREPARE_FAILURE.json'),('post_upload_editor',prep/'POST_UPLOAD_EDITOR.json')]:
        if Path(request[key]['path']).resolve()!=path:raise ValueError('draft_exact_prior_path_required')
    # Verify earlier 0-file and original SELF observation chain without replay.
    v4._prior(_projection(config),old_request)
    journal=reference(prep/'UPLOAD_JOURNAL.jsonl')
    rows=[json.loads(line) for line in Path(journal['path']).read_text(encoding='utf-8').splitlines() if line.strip()]
    nonces={row['selection_nonce'] for row in rows if row.get('selection_nonce')}
    transitions=[row['proof'] for row in rows if row.get('stage')=='upload_check_transition_observed' and isinstance(row.get('proof'),dict)]
    if len(nonces)!=1 or not transitions or not any(row.get('stage')=='upload_ui_diagnostic' and row.get('event')=='success_marker' for row in rows):raise ValueError('draft_upload_journal_identity_required')
    baseline={key:transitions[-1].get('diagnostic',{}).get(key) for key in ('initial_route','current_route','generation','routes','route_history_truncated')}
    if baseline['initial_route']!='upload' or baseline['current_route']!='editor' or baseline['route_history_truncated'] is not False:raise ValueError('draft_original_editor_route_required')
    return {**{key:request[key] for key in PRIOR_FIELDS},'upload_journal':journal,'selection_nonce':next(iter(nonces)),
        'upload_route_baseline':baseline,'source_duration_seconds':2896/24,
        'duration_semantics':'fixed approved 2896/24 source clock; not native media hash proof',
        'stale_document_flags_used':False,'original_checker_verified_claimed':False}


def validate_live(actor,resource,config):
    _scope(config);return v4.validate_live(actor,resource,_projection(config))


def prepare(config_ref,request_ref,output_directory):
    folder=Path(output_directory).resolve()
    if not folder.is_relative_to(RUN.resolve()) or folder.exists():raise ValueError('draft_new_plan_directory_required')
    config,request=_config(config_ref),_request(request_ref,config_ref)
    return _once(folder/'PLAN.json',dict(schema=PLAN_SCHEMA,config=config_ref,request=request_ref,action='prepare_existing_draft',
        state=v4.v3._state(v4._projection(_projection(config))),prior=_prior(config,request),navigation_allowed=False,file_selection_allowed=False,submissions_allowed=0))


def _plan(ref):
    plan=_read(ref)
    if (plan.get('schema')!=PLAN_SCHEMA or not Path(ref['path']).resolve().is_relative_to(RUN.resolve()) or plan.get('navigation_allowed') is not False
            or plan.get('file_selection_allowed') is not False or plan.get('submissions_allowed')!=0):raise ValueError('draft_plan_invalid')
    config=_config(plan['config']);request=_request(plan['request'],plan['config'])
    if plan.get('action')!='prepare_existing_draft' or _prior(config,request)!=plan['prior']:raise ValueError('draft_prior_changed')
    return plan,config,request


def status(plan_ref):
    plan=_read(plan_ref);folder=Path(plan_ref['path']).parent
    if plan.get('schema')!=PLAN_SCHEMA or not folder.resolve().is_relative_to(RUN.resolve()):raise ValueError('draft_plan_invalid')
    claim,result,binding=folder/'ACTION_CLAIM.json',folder/'RESULT.json',folder/'RESULT_BINDING.json'
    if result.exists() and binding.exists():
        proof=_read(reference(binding));value=_read(proof['result'])
        if proof.get('plan')!=plan_ref or proof.get('claim')!=reference(claim) or proof.get('result')!=reference(result) or value.get('status')!='draft_prepared_no_submission' or value.get('plan')!=plan_ref:raise ValueError('draft_cached_result_changed')
        v4.v3.v2.files._validate_refs(value)
        return {'status':'draft_prepared_no_submission','result':proof['result'],'receipt':reference(binding)}
    return {'status':'outcome_unknown','scope':'existing_draft_metadata','automatic_replay_allowed':False} if claim.exists() else {'status':'prepared','plan':plan_ref}


def _perform(actor,resource,plan_ref,arm_ref,run_action):
    plan,config,request=_plan(plan_ref)
    if status(plan_ref)['status']!='prepared':return status(plan_ref)
    if os.getpid()!=config['backend_pid'] or reference(ARM)!=arm_ref or validate_live(actor,resource,config)!=plan['state']:raise ValueError('draft_original_context_changed')
    folder=Path(plan_ref['path']).parent
    claim=dict(schema='manual_republication_existing_draft_action_claim/v5',plan=plan_ref,config=plan['config'],request=plan['request'],
        owner_id=actor.owner_id,generation=actor.generation,tab_id=config['tab_id'],actor_thread_id=threading.get_ident(),at_epoch=time.time(),
        action='prepare_existing_draft',navigation_allowed=False,file_selection_allowed=False,submissions_allowed=0)
    try:claim_ref=_once(folder/'ACTION_CLAIM.json',claim)
    except FileExistsError:return status(plan_ref)
    try:
        value=run_action(actor,resource,config,request,folder/'preparation');_plan(plan_ref)
        if reference(ARM)!=arm_ref or validate_live(actor,resource,config)!=plan['state']:raise ValueError('draft_context_changed_after_metadata')
        if (value.get('schema')!='manual_republication_existing_draft/v5' or value.get('action')!='prepare_existing_draft'
                or value.get('metadata_readback_matched') is not True or value.get('hashtag_readback_verified') is not True
                or any(value.get(k) is not False for k in ('submitted','declaration_selected','navigation_performed','file_selected'))):raise ValueError('draft_metadata_only_complete_receipt_required')
        metadata=_read(config['metadata'])
        if value.get('title_readback',{}).get('content')!=metadata['title'] or ''.join(value.get('description_readback',{}).get('content','').replace('\u200b','').split())!=''.join(metadata['description'].replace('\u200b','').split()):raise ValueError('draft_actual_metadata_mismatch')
        v4.v3.v2.files._validate_refs(value)
        ref=_once(folder/'RESULT.json',dict(schema='manual_republication_runtime_result/v5',status='draft_prepared_no_submission',plan=plan_ref,claim=claim_ref,
            preparation=value,file_selection_claim=request['file_selection_claim'],submitted=False,old_claims_and_unknown_unchanged=True,account_pause_changed=False))
        receipt=_once(folder/'RESULT_BINDING.json',dict(schema='manual_republication_result_binding/v5',plan=plan_ref,claim=claim_ref,result=ref))
        return {'status':'draft_prepared_no_submission','result':ref,'receipt':receipt}
    except Exception as error:
        value=dict(schema='manual_republication_draft_unknown/v5',plan=plan_ref,claim=claim_ref,scope='existing_draft_metadata',error_type=type(error).__name__,automatic_replay_allowed=False)
        if type(error) is getattr(run_action,'_blocked_class',None) and getattr(error,'code',None) in getattr(run_action,'_safe_codes',()):value['reason_code']=error.code
        if not (folder/'UNKNOWN.json').exists():_once(folder/'UNKNOWN.json',value)
        return status(plan_ref)


def _load_flow(config):
    path=SOURCE_PATHS['flow_v5']
    if reference(path)!=config['sources']['flow_v5']:raise ValueError('draft_flow_changed')
    module=types.ModuleType('src.operations_accounts._manual_existing_'+config['sources']['flow_v5']['sha256'][:16]);module.__file__,module.__package__=str(path),'src.operations_accounts'
    exec(compile(path.read_bytes(),str(path),'exec'),module.__dict__)
    blocked,codes=getattr(module,'ExistingDraftBlocked',None),getattr(module,'SAFE_REASONS',frozenset())
    if blocked is not None:
        if not isinstance(blocked,type) or not issubclass(blocked,ValueError) or not isinstance(codes,frozenset) or any(not isinstance(c,str) or not c.isascii() or any(x not in 'abcdefghijklmnopqrstuvwxyz_' for x in c) for c in codes):raise ValueError('draft_safe_diagnostics_invalid')
        module.run_action._blocked_class,module.run_action._safe_codes=blocked,codes
    return module


# Same reviewed owner-thread hook as v4, with this version's schema and marker.
def install_if_armed():
    if not ARM.is_file():return {'status':'not_armed'}
    try:
        arm_ref=reference(ARM);arm=_read(arm_ref)
        if set(arm)!={'schema','plan'} or arm['schema']!='manual_republication_runtime_arm/v5':raise ValueError('resume_arm_invalid')
        plan,config,request=_plan(arm['plan']);folder=Path(arm['plan']['path']).parent
        if os.getpid()!=config['backend_pid']:return {'status':'different_process_no_install'}
        if status(arm['plan'])['status']!='prepared':return status(arm['plan'])
        spaces=[t._target.__globals__ for t in threading.enumerate() if t.name=='AccountBrowser-'+config['account_key'] and t.is_alive()
            and getattr(getattr(t,'_target',None),'__name__','')=='_host' and Path(t._target.__code__.co_filename).resolve()==SOURCE_PATHS['host'].resolve() and getattr(t,'_args',())==(config['account_key'],)]
        if len(spaces)!=1:raise ValueError('resume_unique_original_actor_required')
        namespace=spaces[0];previous=namespace['_poll_manual_windows']
        if getattr(previous,'_manual_draft_plan',None)==arm['plan']:return {'status':'callback_already_registered'}
        if getattr(previous,'_manual_draft_plan',None) is not None:raise ValueError('resume_other_plan_registered')
        flow=_load_flow(config)
        def poll(actor,resource):
            if (actor.account_id,actor.owner_id,actor.generation)!=(config['account_id'],config['owner_id'],config['generation']):return previous(actor,resource)
            defer=False
            try:
                actor._assert_thread();actor._check_owner();value=previous(actor,resource)
                if actor._stack:defer=True;return value
                _perform(actor,resource,arm['plan'],arm_ref,flow.run_action)
            except Exception as error:
                if not (folder/'REFUSED.json').exists():_once(folder/'REFUSED.json',dict(schema='manual_republication_draft_refusal/v5',plan=arm['plan'],error_type=type(error).__name__,action_started=(folder/'ACTION_CLAIM.json').exists()))
            finally:
                if not defer and namespace['_poll_manual_windows'] is poll:namespace['_poll_manual_windows']=previous
            return None
        poll._manual_draft_plan=arm['plan'];namespace['_poll_manual_windows']=poll
        return {'status':'callback_registered_waiting_original_actor_tick'}
    except Exception as error:return {'status':'refused','error_type':type(error).__name__,'reason':str(error) if isinstance(error,ValueError) else 'owner_guard_refused'}
