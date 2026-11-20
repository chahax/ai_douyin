"""Complete current form with stable observed editor semantics; never publish."""
import json
import os
from pathlib import Path
import threading
import time
import types

from . import manual_republication_runtime_v6 as base

ROOT=Path(__file__).resolve().parents[2]
RUN=ROOT/'data/production_trials/fanqie_declared_republication_20261117_v1'
ARM=RUN/'manual_runtime_v7/ARM.json'
SOURCE_PATHS=dict(base.SOURCE_PATHS,runtime_v7=Path(__file__).resolve(),flow_v7=ROOT/'src/operations_accounts/manual_republication_flow_v7.py')
CONFIG_SCHEMA='manual_republication_runtime_config/v7'
REQUEST_SCHEMA='manual_republication_operator_request/v7'
PLAN_SCHEMA='manual_republication_runtime_plan/v7'
reference,_read,_once=base.reference,base._read,base._once
PRIOR_FIELDS=('prior_repair_plan','prior_repair_action','prior_unknown','prior_failure','initial_field_projection','failure_screenshot')


def _prior(config,request):
    plan=_read(request['prior_repair_plan']);action=_read(request['prior_repair_action'])
    unknown=_read(request['prior_unknown']);failure=_read(request['prior_failure']);projection=_read(request['initial_field_projection'])
    if reference(request['failure_screenshot']['path'])!=request['failure_screenshot']:raise ValueError('form_failure_screenshot_changed')
    folder=Path(request['prior_repair_plan']['path']).parent.resolve();prep=folder/'preparation'
    previous=_read(plan['config']);old_request=_read(plan['request'])
    if (not folder.is_relative_to(RUN.resolve()) or plan.get('schema')!=base.PLAN_SCHEMA
            or action.get('schema')!='manual_republication_existing_draft_action_claim/v6'
            or action.get('plan')!=request['prior_repair_plan'] or action.get('config')!=plan['config'] or action.get('request')!=plan['request']
            or action.get('action')!='repair_existing_draft' or action.get('submissions_allowed')!=0
            or any(action.get(k)!=config[k] for k in ('owner_id','generation','tab_id'))
            or previous.get('schema')!=base.CONFIG_SCHEMA or any(previous.get(k)!=config[k] for k in config if k not in {'schema','sources'})
            or any(previous['sources'][k]!=config['sources'][k] for k in ('runtime_v6','flow_v6'))
            or unknown.get('schema')!='manual_republication_repair_unknown/v6' or unknown.get('scope')!='existing_draft_metadata'
            or unknown.get('plan')!=request['prior_repair_plan'] or unknown.get('claim')!=request['prior_repair_action']
            or unknown.get('diagnostics')!=request['prior_failure'] or unknown.get('automatic_replay_allowed') is not False
            or failure.get('schema')!='manual_existing_draft_failure/v6' or failure.get('reason_code')!='repair_editor_unconfirmed'
            or failure.get('cause_code')!='draft_field_not_unique' or failure.get('metadata_mutation_dispatched') is not False
            or any(failure.get(k) is not False for k in ('file_selected','navigation_performed','submitted'))
            or failure.get('failure_capture',{}).get('screenshot',{}).get('file')!=request['failure_screenshot']
            or failure.get('failure_capture',{}).get('screenshot',{}).get('status')!='saved'
            or projection.get('schema')!='manual_draft_field_projection/v5'
            or projection.get('location')!={'origin':'https://creator.douyin.com','path':'/creator-micro/content/post/video'}
            or projection.get('authorized_field_values_read') is not True or projection.get('unrelated_input_values_read') is not False):
        raise ValueError('form_original_bound_editor_failure_required')
    for key,path in [('prior_repair_action',folder/'ACTION_CLAIM.json'),('prior_unknown',folder/'UNKNOWN.json'),
                     ('prior_failure',prep/'PREPARE_FAILURE.json'),('initial_field_projection',prep/'INITIAL_FIELD_PROJECTION.json'),('failure_screenshot',prep/'FAILURE_SCREENSHOT.png')]:
        if Path(request[key]['path']).resolve()!=path:raise ValueError('form_exact_prior_path_required')
    prior=base._prior(_projection(config),old_request)
    return dict(prior,**{key:request[key] for key in PRIOR_FIELDS},fresh_actual_field_projection_required=True,
        stable_slate_semantics_authorized=True,previous_field_values_must_be_reread=True)


def _state(config):
    return base._state(_projection(config))


def prepare(config_ref,request_ref,output_directory):
    folder=Path(output_directory).resolve()
    if not folder.is_relative_to(RUN.resolve()) or folder.exists():raise ValueError('form_new_plan_directory_required')
    config,request=_config(config_ref),_request(request_ref,config_ref)
    return _once(folder/'PLAN.json',dict(schema=PLAN_SCHEMA,config=config_ref,request=request_ref,action='complete_existing_form',
        state=_state(config),prior=_prior(config,request),navigation_allowed=False,file_selection_allowed=False,submissions_allowed=0))


# Static reuse of the reviewed immediate-parent owner/cache/metadata gates.
def _projection(config):
    return dict(config,sources={key:config['sources'][key] for key in base.SOURCE_PATHS})

def _scope(config,verify_media=False):
    if not isinstance(config.get('sources'),dict) or set(config['sources'])!=set(SOURCE_PATHS):raise ValueError('draft_exact_sources_required')
    for key,path in SOURCE_PATHS.items():
        if reference(path)!=config['sources'][key]:raise ValueError('draft_source_changed:'+key)
    base._scope(_projection(config),verify_media=verify_media)

def _config(ref):
    value=_read(ref)
    fields={'schema','backend_pid','backend_create_time','account_key','account_id','owner_id','generation','binding_version','browser_db','control_db','control_snapshot','manual_command_id','manual_request_sha256','tab_id','authority','operator_authority','metadata','sources'}
    if not isinstance(value,dict) or set(value)!=fields or value['schema']!=CONFIG_SCHEMA:raise ValueError('draft_config_invalid')
    _scope(value,True);return value

def _request(ref,config_ref):
    value=_read(ref)
    if (not isinstance(value,dict) or set(value)!={'schema','config','action',*PRIOR_FIELDS}
            or value['schema']!=REQUEST_SCHEMA or value['config']!=config_ref or value['action']!='complete_existing_form'):
        raise ValueError('draft_metadata_only')
    return value

def validate_live(actor,resource,config):
    _scope(config);return base.validate_live(actor,resource,_projection(config))

def _plan(ref):
    plan=_read(ref)
    if (plan.get('schema')!=PLAN_SCHEMA or not Path(ref['path']).resolve().is_relative_to(RUN.resolve()) or plan.get('navigation_allowed') is not False
            or plan.get('file_selection_allowed') is not False or plan.get('submissions_allowed')!=0):raise ValueError('draft_plan_invalid')
    config=_config(plan['config']);request=_request(plan['request'],plan['config'])
    if plan.get('action')!='complete_existing_form' or _prior(config,request)!=plan['prior']:raise ValueError('draft_prior_changed')
    return plan,config,request

def status(plan_ref):
    plan=_read(plan_ref);folder=Path(plan_ref['path']).parent
    if plan.get('schema')!=PLAN_SCHEMA or not folder.resolve().is_relative_to(RUN.resolve()):raise ValueError('draft_plan_invalid')
    claim,result,binding=folder/'ACTION_CLAIM.json',folder/'RESULT.json',folder/'RESULT_BINDING.json'
    if result.exists() and binding.exists():
        proof=_read(reference(binding));value=_read(proof['result'])
        if proof.get('plan')!=plan_ref or proof.get('claim')!=reference(claim) or proof.get('result')!=reference(result) or value.get('status')!='draft_prepared_no_submission' or value.get('plan')!=plan_ref:raise ValueError('draft_cached_result_changed')
        base.base.v4.v3.v2.files._validate_refs(value)
        return {'status':'draft_prepared_no_submission','result':proof['result'],'receipt':reference(binding)}
    return {'status':'outcome_unknown','scope':'existing_draft_metadata','automatic_replay_allowed':False} if claim.exists() else {'status':'prepared','plan':plan_ref}

def _perform(actor,resource,plan_ref,arm_ref,run_action):
    plan,config,request=_plan(plan_ref)
    if status(plan_ref)['status']!='prepared':return status(plan_ref)
    if os.getpid()!=config['backend_pid'] or reference(ARM)!=arm_ref or validate_live(actor,resource,config)!=plan['state']:raise ValueError('draft_original_context_changed')
    folder=Path(plan_ref['path']).parent
    claim=dict(schema='manual_republication_complete_form_action_claim/v7',plan=plan_ref,config=plan['config'],request=plan['request'],
        owner_id=actor.owner_id,generation=actor.generation,tab_id=config['tab_id'],actor_thread_id=threading.get_ident(),at_epoch=time.time(),
        action='complete_existing_form',navigation_allowed=False,file_selection_allowed=False,submissions_allowed=0)
    try:claim_ref=_once(folder/'ACTION_CLAIM.json',claim)
    except FileExistsError:return status(plan_ref)
    try:
        value=run_action(actor,resource,config,request,folder/'preparation');_plan(plan_ref)
        if reference(ARM)!=arm_ref or validate_live(actor,resource,config)!=plan['state']:raise ValueError('draft_context_changed_after_metadata')
        if (value.get('schema')!='manual_republication_existing_draft/v7' or value.get('action')!='complete_existing_form'
                or value.get('metadata_readback_matched') is not True or value.get('hashtag_readback_verified') is not True
                or any(value.get(k) is not False for k in ('submitted','declaration_selected','navigation_performed','file_selected'))):raise ValueError('draft_metadata_only_complete_receipt_required')
        metadata=_read(config['metadata'])
        if value.get('title_readback',{}).get('content')!=metadata['title'] or ''.join(value.get('description_readback',{}).get('content','').replace('\u200b','').split())!=''.join(metadata['description'].replace('\u200b','').split()):raise ValueError('draft_actual_metadata_mismatch')
        base.base.v4.v3.v2.files._validate_refs(value)
        ref=_once(folder/'RESULT.json',dict(schema='manual_republication_runtime_result/v7',status='draft_prepared_no_submission',plan=plan_ref,claim=claim_ref,
            preparation=value,file_selection_claim=plan['prior']['file_selection_claim'],submitted=False,old_claims_and_unknown_unchanged=True,account_pause_changed=False))
        receipt=_once(folder/'RESULT_BINDING.json',dict(schema='manual_republication_result_binding/v7',plan=plan_ref,claim=claim_ref,result=ref))
        return {'status':'draft_prepared_no_submission','result':ref,'receipt':receipt}
    except Exception as error:
        value=dict(schema='manual_republication_form_unknown/v7',plan=plan_ref,claim=claim_ref,scope='existing_draft_metadata',error_type=type(error).__name__,automatic_replay_allowed=False)
        if type(error) is getattr(run_action,'_blocked_class',None) and getattr(error,'code',None) in getattr(run_action,'_safe_codes',()):value['reason_code']=error.code
        diagnostics=folder/'preparation/PREPARE_FAILURE.json'
        if diagnostics.is_file():value['diagnostics']=reference(diagnostics)
        if not (folder/'UNKNOWN.json').exists():_once(folder/'UNKNOWN.json',value)
        return status(plan_ref)

def _load_flow(config):
    path=SOURCE_PATHS['flow_v7']
    if reference(path)!=config['sources']['flow_v7']:raise ValueError('draft_flow_changed')
    module=types.ModuleType('src.operations_accounts._manual_existing_'+config['sources']['flow_v7']['sha256'][:16]);module.__file__,module.__package__=str(path),'src.operations_accounts'
    exec(compile(path.read_bytes(),str(path),'exec'),module.__dict__)
    blocked,codes=getattr(module,'ExistingDraftRepairBlocked',None),getattr(module,'SAFE_REASONS',frozenset())
    if blocked is not None:
        if not isinstance(blocked,type) or not issubclass(blocked,ValueError) or not isinstance(codes,frozenset) or any(not isinstance(c,str) or not c.isascii() or any(x not in 'abcdefghijklmnopqrstuvwxyz_' for x in c) for c in codes):raise ValueError('draft_safe_diagnostics_invalid')
        module.run_action._blocked_class,module.run_action._safe_codes=blocked,codes
    return module

def install_if_armed():
    if not ARM.is_file():return {'status':'not_armed'}
    try:
        arm_ref=reference(ARM);arm=_read(arm_ref)
        if set(arm)!={'schema','plan'} or arm['schema']!='manual_republication_runtime_arm/v7':raise ValueError('resume_arm_invalid')
        plan,config,request=_plan(arm['plan']);folder=Path(arm['plan']['path']).parent
        if os.getpid()!=config['backend_pid']:return {'status':'different_process_no_install'}
        if status(arm['plan'])['status']!='prepared':return status(arm['plan'])
        spaces=[t._target.__globals__ for t in threading.enumerate() if t.name=='AccountBrowser-'+config['account_key'] and t.is_alive()
            and getattr(getattr(t,'_target',None),'__name__','')=='_host' and Path(t._target.__code__.co_filename).resolve()==SOURCE_PATHS['host'].resolve() and getattr(t,'_args',())==(config['account_key'],)]
        if len(spaces)!=1:raise ValueError('resume_unique_original_actor_required')
        namespace=spaces[0];previous=namespace['_poll_manual_windows']
        if getattr(previous,'_manual_form_plan',None)==arm['plan']:return {'status':'callback_already_registered'}
        if getattr(previous,'_manual_form_plan',None) is not None:raise ValueError('resume_other_plan_registered')
        flow=_load_flow(config)
        def poll(actor,resource):
            if (actor.account_id,actor.owner_id,actor.generation)!=(config['account_id'],config['owner_id'],config['generation']):return previous(actor,resource)
            defer=False
            try:
                actor._assert_thread();actor._check_owner();value=previous(actor,resource)
                if actor._stack:defer=True;return value
                _perform(actor,resource,arm['plan'],arm_ref,flow.run_action)
            except Exception as error:
                if not (folder/'REFUSED.json').exists():_once(folder/'REFUSED.json',dict(schema='manual_republication_form_refusal/v7',plan=arm['plan'],error_type=type(error).__name__,action_started=(folder/'ACTION_CLAIM.json').exists()))
            finally:
                if not defer and namespace['_poll_manual_windows'] is poll:namespace['_poll_manual_windows']=previous
            return None
        poll._manual_form_plan=arm['plan'];namespace['_poll_manual_windows']=poll
        return {'status':'callback_registered_waiting_original_actor_tick'}
    except Exception as error:return {'status':'refused','error_type':type(error).__name__,'reason':str(error) if isinstance(error,ValueError) else 'owner_guard_refused'}
