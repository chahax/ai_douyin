"""One original-draft disclosure inspection; never select or publish."""
import json
import os
from pathlib import Path
import threading
import types
import time

from . import manual_republication_runtime_v7 as base

ROOT=Path(__file__).resolve().parents[2]
RUN=ROOT/'data/production_trials/fanqie_declared_republication_20261117_v1'
ARM=RUN/'manual_runtime_v8/ARM.json'
SOURCE_PATHS=dict(base.SOURCE_PATHS,runtime_v8=Path(__file__).resolve(),flow_v8=ROOT/'src/operations_accounts/manual_republication_flow_v8.py')
CONFIG_SCHEMA='manual_republication_runtime_config/v8'
REQUEST_SCHEMA='manual_republication_operator_request/v8'
PLAN_SCHEMA='manual_republication_runtime_plan/v8'
ACTION='inspect_declaration_options'
PRIOR_FIELDS=('prepared_result','prepared_receipt','form_readback','file_selection_claim','trigger_projection')
reference,_read,_once=base.reference,base._read,base._once


def _refs(value):base.base.base.v4.v3.v2.files._validate_refs(value)


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
    result=_read(request['prepared_result']);receipt=_read(request['prepared_receipt'])
    plan=_read(result['plan']);claim=_read(result['claim']);old_config=_read(plan['config']);old_request=_read(plan['request'])
    folder=Path(result['plan']['path']).resolve().parent;value=result.get('preparation',{})
    if (not folder.is_relative_to(RUN.resolve()) or result.get('schema')!='manual_republication_runtime_result/v7'
            or result.get('status')!='draft_prepared_no_submission' or result.get('submitted') is not False
            or receipt!={'schema':'manual_republication_result_binding/v7','plan':result['plan'],'claim':result['claim'],'result':request['prepared_result']}
            or Path(request['prepared_result']['path']).resolve()!=folder/'RESULT.json'
            or Path(request['prepared_receipt']['path']).resolve()!=folder/'RESULT_BINDING.json'
            or result['claim']!=reference(folder/'ACTION_CLAIM.json')
            or claim.get('plan')!=result['plan'] or claim.get('schema')!='manual_republication_complete_form_action_claim/v7'
            or claim.get('config')!=plan['config'] or claim.get('request')!=plan['request'] or claim.get('action')!='complete_existing_form'
            or plan.get('schema')!=base.PLAN_SCHEMA or old_config.get('schema')!=base.CONFIG_SCHEMA
            or any(old_config.get(k)!=config[k] for k in config if k not in {'schema','sources'})
            or any(old_config['sources'][k]!=config['sources'][k] for k in ('runtime_v7','flow_v7'))
            or value.get('schema')!='manual_republication_existing_draft/v7' or value.get('action')!='complete_existing_form'
            or value.get('action_claim')!=result['claim'] or value.get('metadata')!=config['metadata']
            or value.get('form_readback')!=request['form_readback'] or value.get('declaration_trigger_projection')!=request['trigger_projection']
            or value.get('file_selection_claim')!=request['file_selection_claim'] or result.get('file_selection_claim')!=request['file_selection_claim']
            or value.get('metadata_readback_matched') is not True or value.get('hashtag_readback_verified') is not True
            or value.get('declaration_entry_expanded') is not False
            or any(value.get(k) is not False for k in ('submitted','declaration_selected','navigation_performed','file_selected','publication_ready'))):
        raise ValueError('declaration_bound_completed_form_required')
    _refs(result)
    form=_read(request['form_readback']);projection=_read(request['trigger_projection']);metadata=_read(config['metadata'])
    if (form.get('title',{}).get('content')!=metadata['title'] or form.get('description_exact') is not True
            or ''.join(form.get('description_core','').replace('\u200b','').split())!=''.join(metadata['description'].replace('\u200b','').split())
            or len(form.get('hashtag_tokens',[]))!=len(metadata['hashtags']) or set(form['hashtag_tokens'])!=set(metadata['hashtags'])
            or projection.get('schema')!='manual_draft_declaration_trigger/v5' or projection.get('truncated') is not False):
        raise ValueError('declaration_original_form_changed')
    prior=base._prior(_projection(config),old_request)
    if prior['file_selection_claim']!=request['file_selection_claim']:raise ValueError('declaration_media_slot_changed')
    return dict(prior,**{key:request[key] for key in PRIOR_FIELDS},declaration_selections_allowed=0,trigger_clicks_allowed=1)


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
    claim=dict(schema='manual_republication_declaration_action_claim/v8',plan=plan_ref,config=plan['config'],request=plan['request'],
        owner_id=actor.owner_id,generation=actor.generation,tab_id=config['tab_id'],actor_thread_id=threading.get_ident(),at_epoch=time.time(),
        action=ACTION,navigation_allowed=False,file_selection_allowed=False,submissions_allowed=0)
    try:claim_ref=_once(folder/'ACTION_CLAIM.json',claim)
    except FileExistsError:return status(plan_ref)
    try:
        value=run_action(actor,resource,config,request,folder/'inspection');_plan(plan_ref)
        if reference(ARM)!=arm_ref or validate_live(actor,resource,config)!=plan['state']:raise ValueError('declaration_context_changed_after_inspection')
        if (value.get('schema')!='manual_republication_declaration_inspection/v8' or value.get('action')!=ACTION
                or value.get('action_claim')!=claim_ref or value.get('file_selection_claim')!=request['file_selection_claim']
                or value.get('metadata_readback_matched') is not True or value.get('trigger_click_count')!=1
                or value.get('options_observed') is not True or value.get('same_tab')!=config['tab_id']
                or any(value.get(k) is not False for k in ('submitted','declaration_selected','confirmed','navigation_performed','file_selected','fields_written','publication_ready'))):raise ValueError('declaration_inspection_receipt_required')
        _refs(value)
        options=_read(value['options_inventory'])
        if options.get('complete_visible_capture') is not True or options.get('truncated') is not False:raise ValueError('declaration_complete_options_required')
        ref=_once(folder/'RESULT.json',dict(schema='manual_republication_runtime_result/v8',status='declaration_options_observed',plan=plan_ref,claim=claim_ref,
            inspection=value,file_selection_claim=request['file_selection_claim'],submitted=False,old_claims_and_unknown_unchanged=True,account_pause_changed=False))
        receipt=_once(folder/'RESULT_BINDING.json',dict(schema='manual_republication_result_binding/v8',plan=plan_ref,claim=claim_ref,result=ref))
        return {'status':'declaration_options_observed','result':ref,'receipt':receipt}
    except Exception as error:
        value=dict(schema='manual_republication_declaration_unknown/v8',plan=plan_ref,claim=claim_ref,scope='declaration_disclosure',error_type=type(error).__name__,automatic_replay_allowed=False)
        if type(error) is getattr(run_action,'_blocked_class',None) and getattr(error,'code',None) in getattr(run_action,'_safe_codes',()):value['reason_code']=error.code
        diagnostics=folder/'inspection/INSPECTION_FAILURE.json'
        if diagnostics.is_file():value['diagnostics']=reference(diagnostics)
        if not (folder/'UNKNOWN.json').exists():_once(folder/'UNKNOWN.json',value)
        return status(plan_ref)


def _load_flow(config):
    path=SOURCE_PATHS['flow_v8']
    if reference(path)!=config['sources']['flow_v8']:raise ValueError('declaration_flow_changed')
    module=types.ModuleType('src.operations_accounts._declaration_inspection_'+config['sources']['flow_v8']['sha256'][:16]);module.__file__,module.__package__=str(path),'src.operations_accounts'
    exec(compile(path.read_bytes(),str(path),'exec'),module.__dict__)
    module.run_action._blocked_class,module.run_action._safe_codes=module.DeclarationInspectionBlocked,module.SAFE_REASONS
    return module


def install_if_armed():
    if not ARM.is_file():return {'status':'not_armed'}
    try:
        arm_ref=reference(ARM);arm=_read(arm_ref)
        if set(arm)!={'schema','plan'} or arm['schema']!='manual_republication_runtime_arm/v8':raise ValueError('declaration_arm_invalid')
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
                if not (folder/'REFUSED.json').exists():_once(folder/'REFUSED.json',dict(schema='manual_republication_declaration_refusal/v8',plan=arm['plan'],error_type=type(error).__name__,action_started=(folder/'ACTION_CLAIM.json').exists()))
            finally:
                if not defer and namespace['_poll_manual_windows'] is poll:namespace['_poll_manual_windows']=previous
            return None
        poll._manual_declaration_plan=arm['plan'];namespace['_poll_manual_windows']=poll
        return {'status':'callback_registered_waiting_original_actor_tick'}
    except Exception as error:return {'status':'refused','error_type':type(error).__name__,'reason':str(error) if isinstance(error,ValueError) else 'owner_guard_refused'}
