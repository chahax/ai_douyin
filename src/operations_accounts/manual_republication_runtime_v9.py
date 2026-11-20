"""One original-draft disclosure inspection; never select or publish."""
import json
import os
from pathlib import Path
import threading
import types
import time

from . import manual_republication_runtime_v8 as base

ROOT=Path(__file__).resolve().parents[2]
RUN=ROOT/'data/production_trials/fanqie_declared_republication_20261117_v1'
ARM=RUN/'manual_runtime_v9/ARM.json'
SOURCE_PATHS=dict(base.SOURCE_PATHS,runtime_v9=Path(__file__).resolve(),flow_v9=ROOT/'src/operations_accounts/manual_republication_flow_v9.py')
CONFIG_SCHEMA='manual_republication_runtime_config/v9'
REQUEST_SCHEMA='manual_republication_operator_request/v9'
PLAN_SCHEMA='manual_republication_runtime_plan/v9'
ACTION='inspect_declaration_options_after_scroll'
PRIOR_FIELDS=('prior_inspection_plan','prior_inspection_action','prior_unknown','prior_failure','trigger_before')
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
    if (not isinstance(value,dict) or set(value)!={'schema','config','action',*PRIOR_FIELDS}
            or value['schema']!=REQUEST_SCHEMA or value['config']!=config_ref or value['action']!=ACTION):raise ValueError('declaration_inspection_only')
    return value


def _prior(config,request):
    plan=_read(request['prior_inspection_plan']);claim=_read(request['prior_inspection_action'])
    unknown=_read(request['prior_unknown']);failure=_read(request['prior_failure']);trigger=_read(request['trigger_before'])
    folder=Path(request['prior_inspection_plan']['path']).resolve().parent
    previous=_read(plan['config']);old_request=_read(plan['request'])
    if (not folder.is_relative_to(RUN.resolve()) or plan.get('schema')!=base.PLAN_SCHEMA or plan.get('action')!=base.ACTION
            or previous.get('schema')!=base.CONFIG_SCHEMA or any(previous.get(k)!=config[k] for k in config if k not in {'schema','sources'})
            or any(previous['sources'][k]!=config['sources'][k] for k in ('runtime_v8','flow_v8'))
            or claim.get('schema')!='manual_republication_declaration_action_claim/v8' or claim.get('action')!=base.ACTION
            or claim.get('plan')!=request['prior_inspection_plan'] or claim.get('config')!=plan['config'] or claim.get('request')!=plan['request']
            or any(claim.get(k)!=config[k] for k in ('owner_id','generation','tab_id'))
            or unknown.get('schema')!='manual_republication_declaration_unknown/v8' or unknown.get('scope')!='declaration_disclosure'
            or unknown.get('plan')!=request['prior_inspection_plan'] or unknown.get('claim')!=request['prior_inspection_action']
            or unknown.get('diagnostics')!=request['prior_failure'] or unknown.get('automatic_replay_allowed') is not False
            or unknown.get('reason_code')!='declaration_trigger_unconfirmed'
            or failure.get('schema')!='manual_declaration_inspection_failure/v8' or failure.get('reason_code')!='declaration_trigger_unconfirmed'
            or failure.get('trigger_click_dispatched') is not False
            or any(failure.get(k) is not False for k in ('submitted','declaration_selected','confirmed','fields_written','file_selected','navigation_performed'))
            or trigger.get('schema')!='manual_native_declaration_trigger/v8' or trigger.get('location')!={'origin':'https://creator.douyin.com','path':'/creator-micro/content/post/video'}
            or any(trigger.get(k)!=1 for k in ('section_count','control_count','value_count')) or trigger.get('value')!='请选择自主声明'
            or trigger.get('cursor')!='pointer' or trigger.get('view_only_eligible') is not True or trigger.get('center_hit') is not False
            or trigger.get('armed') is not False):raise ValueError('declaration_known_zero_click_required')
    for key,path in [('prior_inspection_action',folder/'ACTION_CLAIM.json'),('prior_unknown',folder/'UNKNOWN.json'),
                     ('prior_failure',folder/'inspection/INSPECTION_FAILURE.json'),('trigger_before',folder/'inspection/TRIGGER_BEFORE.json')]:
        if Path(request[key]['path']).resolve()!=path:raise ValueError('declaration_exact_zero_click_artifact_required')
    if any((folder/name).exists() for name in ('RESULT.json','RESULT_BINDING.json','inspection/DISCLOSURE_CLICK_INTENT.json','inspection/DISCLOSURE_EVENTS.json')):
        raise ValueError('declaration_prior_click_must_not_exist')
    _refs(failure)
    # Runtime saved this immutable trace after cleanup; no click/selection may
    # have entered the worker, regardless of the rendered outcome.
    for line in Path(failure['rpc_trace']['path']).read_text(encoding='utf8').splitlines():
        event=json.loads(line)
        if event.get('event')=='rpc_dispatched' and event.get('action') not in {'current_url','evaluate','locator_count','inner_text','get_attribute','wait_for_timeout','upload_check_proof','screenshot'}:
            raise ValueError('declaration_prior_mutation_dispatched')
    prior=base._prior(_projection(config),old_request)
    return dict(prior,**{key:request[key] for key in PRIOR_FIELDS},fixed_trigger_scrolls_allowed=1)


def _state(config):return base._state(_projection(config))


def validate_live(actor,resource,config):
    _scope(config);return base.validate_live(actor,resource,_projection(config))


def prepare(config_ref,request_ref,output_directory):
    folder=Path(output_directory).resolve()
    if not folder.is_relative_to(RUN.resolve()) or folder.exists():raise ValueError('declaration_new_plan_directory_required')
    config,request=_config(config_ref),_request(request_ref,config_ref)
    return _once(folder/'PLAN.json',dict(schema=PLAN_SCHEMA,config=config_ref,request=request_ref,action=ACTION,
        state=_state(config),prior=_prior(config,request),navigation_allowed=False,file_selection_allowed=False,submissions_allowed=0))


def _plan(ref):
    plan=_read(ref)
    if (plan.get('schema')!=PLAN_SCHEMA or not Path(ref['path']).resolve().is_relative_to(RUN.resolve())
            or plan.get('navigation_allowed') is not False or plan.get('file_selection_allowed') is not False or plan.get('submissions_allowed')!=0):raise ValueError('declaration_plan_invalid')
    config=_config(plan['config']);request=_request(plan['request'],plan['config'])
    if plan.get('action')!=ACTION or _prior(config,request)!=plan['prior']:raise ValueError('declaration_prior_changed')
    return plan,config,request


def status(plan_ref):
    plan=_read(plan_ref);folder=Path(plan_ref['path']).parent
    if plan.get('schema')!=PLAN_SCHEMA or not folder.resolve().is_relative_to(RUN.resolve()):raise ValueError('declaration_plan_invalid')
    claim,result,binding=folder/'ACTION_CLAIM.json',folder/'RESULT.json',folder/'RESULT_BINDING.json'
    if result.exists() and binding.exists():
        proof=_read(reference(binding));value=_read(proof['result'])
        if proof.get('plan')!=plan_ref or proof.get('claim')!=reference(claim) or proof.get('result')!=reference(result) or value.get('status')!='declaration_options_observed' or value.get('plan')!=plan_ref:raise ValueError('declaration_cached_result_changed')
        _refs(value)
        return {'status':'declaration_options_observed','result':proof['result'],'receipt':reference(binding)}
    return {'status':'outcome_unknown','scope':'declaration_disclosure','automatic_replay_allowed':False} if claim.exists() else {'status':'prepared','plan':plan_ref}


def _perform(actor,resource,plan_ref,arm_ref,run_action):
    plan,config,request=_plan(plan_ref)
    if status(plan_ref)['status']!='prepared':return status(plan_ref)
    if os.getpid()!=config['backend_pid'] or reference(ARM)!=arm_ref or validate_live(actor,resource,config)!=plan['state']:raise ValueError('declaration_original_context_changed')
    folder=Path(plan_ref['path']).parent
    claim=dict(schema='manual_republication_declaration_action_claim/v9',plan=plan_ref,config=plan['config'],request=plan['request'],
        owner_id=actor.owner_id,generation=actor.generation,tab_id=config['tab_id'],actor_thread_id=threading.get_ident(),at_epoch=time.time(),
        action=ACTION,navigation_allowed=False,file_selection_allowed=False,submissions_allowed=0)
    try:claim_ref=_once(folder/'ACTION_CLAIM.json',claim)
    except FileExistsError:return status(plan_ref)
    try:
        value=run_action(actor,resource,config,request,folder/'inspection');_plan(plan_ref)
        if reference(ARM)!=arm_ref or validate_live(actor,resource,config)!=plan['state']:raise ValueError('declaration_context_changed_after_inspection')
        if (value.get('schema')!='manual_republication_declaration_inspection/v9' or value.get('action')!=ACTION
                or value.get('action_claim')!=claim_ref or value.get('file_selection_claim')!=plan['prior']['file_selection_claim']
                or value.get('metadata_readback_matched') is not True or value.get('trigger_click_count')!=1 or value.get('scroll_performed') is not True
                or value.get('options_observed') is not True or value.get('same_tab')!=config['tab_id']
                or any(value.get(k) is not False for k in ('submitted','declaration_selected','confirmed','navigation_performed','file_selected','fields_written','publication_ready'))):raise ValueError('declaration_inspection_receipt_required')
        _refs(value)
        options=_read(value['options_inventory'])
        if options.get('complete_visible_capture') is not True or options.get('truncated') is not False:raise ValueError('declaration_complete_options_required')
        ref=_once(folder/'RESULT.json',dict(schema='manual_republication_runtime_result/v9',status='declaration_options_observed',plan=plan_ref,claim=claim_ref,
            inspection=value,file_selection_claim=plan['prior']['file_selection_claim'],submitted=False,old_claims_and_unknown_unchanged=True,account_pause_changed=False))
        receipt=_once(folder/'RESULT_BINDING.json',dict(schema='manual_republication_result_binding/v9',plan=plan_ref,claim=claim_ref,result=ref))
        return {'status':'declaration_options_observed','result':ref,'receipt':receipt}
    except Exception as error:
        value=dict(schema='manual_republication_declaration_unknown/v9',plan=plan_ref,claim=claim_ref,scope='declaration_disclosure',error_type=type(error).__name__,automatic_replay_allowed=False)
        if type(error) is getattr(run_action,'_blocked_class',None) and getattr(error,'code',None) in getattr(run_action,'_safe_codes',()):value['reason_code']=error.code
        diagnostics=folder/'inspection/INSPECTION_FAILURE.json'
        if diagnostics.is_file():value['diagnostics']=reference(diagnostics)
        if not (folder/'UNKNOWN.json').exists():_once(folder/'UNKNOWN.json',value)
        return status(plan_ref)


def _load_flow(config):
    path=SOURCE_PATHS['flow_v9']
    if reference(path)!=config['sources']['flow_v9']:raise ValueError('declaration_flow_changed')
    module=types.ModuleType('src.operations_accounts._declaration_inspection_'+config['sources']['flow_v9']['sha256'][:16]);module.__file__,module.__package__=str(path),'src.operations_accounts'
    exec(compile(path.read_bytes(),str(path),'exec'),module.__dict__)
    module.run_action._blocked_class,module.run_action._safe_codes=module.DeclarationInspectionBlocked,module.SAFE_REASONS
    return module


def install_if_armed():
    if not ARM.is_file():return {'status':'not_armed'}
    try:
        arm_ref=reference(ARM);arm=_read(arm_ref)
        if set(arm)!={'schema','plan'} or arm['schema']!='manual_republication_runtime_arm/v9':raise ValueError('declaration_arm_invalid')
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
                if not (folder/'REFUSED.json').exists():_once(folder/'REFUSED.json',dict(schema='manual_republication_declaration_refusal/v9',plan=arm['plan'],error_type=type(error).__name__,action_started=(folder/'ACTION_CLAIM.json').exists()))
            finally:
                if not defer and namespace['_poll_manual_windows'] is poll:namespace['_poll_manual_windows']=previous
            return None
        poll._manual_declaration_plan=arm['plan'];namespace['_poll_manual_windows']=poll
        return {'status':'callback_registered_waiting_original_actor_tick'}
    except Exception as error:return {'status':'refused','error_type':type(error).__name__,'reason':str(error) if isinstance(error,ValueError) else 'owner_guard_refused'}
