"""Named zero-file continuation; the media slot is reserved at selection only."""
import os
from pathlib import Path
import threading
import time
import types

from . import manual_republication_runtime_v3 as v3

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'data/production_trials/fanqie_declared_republication_20261117_v1'
ARM = RUN / 'manual_runtime_v4/ARM.json'
FILE_SELECTION_CLAIM = RUN / 'FILE_SELECTION_CLAIM.json'
SOURCE_PATHS = dict(v3.SOURCE_PATHS, runtime_v4=Path(__file__).resolve(),
    flow_v4=ROOT / 'src/operations_accounts/manual_republication_flow_v4.py')
CONFIG_SCHEMA = 'manual_republication_runtime_config/v4'
REQUEST_SCHEMA = 'manual_republication_operator_request/v4'
PLAN_SCHEMA = 'manual_republication_runtime_plan/v4'
reference, _read, _once = v3.reference, v3._read, v3._once


def _projection(config):
    return dict(config, sources={key: config['sources'][key] for key in v3.SOURCE_PATHS})


def _scope(config, *, verify_media=False):
    if not isinstance(config.get('sources'), dict) or set(config['sources']) != set(SOURCE_PATHS):
        raise ValueError('resume_exact_sources_required')
    for key, path in SOURCE_PATHS.items():
        if reference(path) != config['sources'][key]:
            raise ValueError('resume_source_changed:' + key)
    v3._scope(_projection(config), verify_media=verify_media)


def _config(ref):
    value = _read(ref)
    fields = {'schema', 'backend_pid', 'backend_create_time', 'account_key', 'account_id', 'owner_id',
        'generation', 'binding_version', 'browser_db', 'control_db', 'control_snapshot', 'manual_command_id',
        'manual_request_sha256', 'tab_id', 'authority', 'operator_authority', 'metadata', 'sources'}
    if not isinstance(value, dict) or set(value) != fields or value['schema'] != CONFIG_SCHEMA:
        raise ValueError('resume_config_invalid')
    _scope(value, verify_media=True)
    return value


def _request(ref, config_ref):
    value = _read(ref)
    if (not isinstance(value, dict) or set(value) != {'schema', 'config', 'action', 'prior_upload_claim', 'prior_failure', 'observation'}
            or value['schema'] != REQUEST_SCHEMA or value['config'] != config_ref
            or value['action'] != 'resume_prepare_upload'):
        raise ValueError('resume_prepare_only')
    return value


def _prior(config, request):
    prior = v3._prior(_projection(config), request)
    observed = _read(request['observation'])
    folder = Path(request['observation']['path']).parent
    receipt = reference(folder / 'RESULT_BINDING.json')
    proof = _read(receipt)
    plan = _read(observed['plan'])
    previous = _read(plan['config'])
    observation_request = _read(plan['request'])
    data = observed.get('observation', {})
    if (observed.get('schema') != 'manual_republication_runtime_result/v3' or observed.get('status') != 'observed_current'
            or proof.get('schema') != 'manual_republication_result_binding/v3'
            or proof.get('result') != request['observation'] or proof.get('plan') != observed['plan']
            or proof.get('claim') != observed['claim'] or v3.status(observed['plan'])['status'] != 'observed_current'
            or previous.get('schema') != v3.CONFIG_SCHEMA
            or any(previous.get(key) != config[key] for key in config if key not in {'schema', 'sources'})
            or any(previous['sources'][key] != config['sources'][key] for key in ('runtime_v3', 'flow_v3'))
            or observation_request.get('prior_upload_claim') != request['prior_upload_claim']
            or observation_request.get('prior_failure') != request['prior_failure']
            or data.get('schema') != 'manual_republication_observation/v3'
            or data.get('action') != 'observe_current'
            or data.get('owner_id') != config['owner_id'] or data.get('generation') != config['generation']
            or data.get('tab_id') != config['tab_id']
            or data.get('location') != {'origin': 'https://www.douyin.com', 'path': '/user/self'}
            or data.get('observed_public_uids') != [_read(config['authority'])['expected_public_uid']]
            or data.get('stable_render_observed') is not True
            or data.get('same_page_rendered_expected_uid_observed') is not True
            or any(data.get(key) is not False for key in ('uploaded', 'submitted', 'input_performed', 'navigation_performed', 'file_selected'))):
        raise ValueError('resume_same_subject_zero_effect_observation_required')
    return dict(prior, observation=request['observation'], observation_binding=receipt,
                historical_observation_is_write_identity=False, fresh_uid_required_before_selection=True)


def validate_live(actor, resource, config):
    _scope(config)
    state = v3.validate_live(actor, resource, _projection(config))
    if FILE_SELECTION_CLAIM.exists():
        claim = _read(reference(FILE_SELECTION_CLAIM))
        if (claim.get('schema') != 'manual_file_selection_claim/v4'
                or claim.get('authority') != config['authority'] or claim.get('metadata') != config['metadata']
                or any(claim.get(key) != config[key] for key in ('owner_id', 'generation', 'tab_id'))):
            raise ValueError('resume_file_claim_subject_changed')
    return state


def prepare(config_ref, request_ref, output_directory):
    folder = Path(output_directory).resolve()
    if not folder.is_relative_to(RUN.resolve()) or folder.exists():
        raise ValueError('resume_new_plan_directory_required')
    if FILE_SELECTION_CLAIM.exists():
        raise ValueError('resume_file_selection_slot_already_claimed')
    config, request = _config(config_ref), _request(request_ref, config_ref)
    return _once(folder / 'PLAN.json', dict(schema=PLAN_SCHEMA, config=config_ref, request=request_ref,
        action='resume_prepare_upload', state=v3._state(_projection(config)), prior=_prior(config, request),
        file_selection_limit=1, declaration_selection_allowed=False, submit_allowed=False))


def _plan(ref):
    plan = _read(ref)
    if (plan.get('schema') != PLAN_SCHEMA or not Path(ref['path']).resolve().is_relative_to(RUN.resolve())
            or plan.get('file_selection_limit') != 1 or plan.get('declaration_selection_allowed') is not False
            or plan.get('submit_allowed') is not False):
        raise ValueError('resume_plan_invalid')
    config, request = _config(plan['config']), _request(plan['request'], plan['config'])
    if plan.get('action') != 'resume_prepare_upload' or _prior(config, request) != plan['prior']:
        raise ValueError('resume_prior_changed')
    return plan, config, request


def _action(outdir, config, request):
    folder = Path(outdir).resolve()
    claim_ref = reference(folder.parent / 'ACTION_CLAIM.json')
    claim = _read(claim_ref)
    if (claim.get('schema') != 'manual_republication_resume_action_claim/v4'
            or folder != Path(claim['plan']['path']).parent.resolve() / 'preparation'
            or _read(claim['config']) != config or _read(claim['request']) != request
            or claim.get('action') != 'resume_prepare_upload'
            or claim.get('actor_thread_id') != threading.get_ident()
            or any(claim.get(key) != config[key] for key in ('owner_id', 'generation', 'tab_id'))):
        raise ValueError('resume_exact_action_context_required')
    return claim_ref, claim


def claim_file_selection(actor, resource, config, request, outdir, media, selection_evidence):
    """Only the reviewed flow calls this immediately before its sole file RPC."""
    validate_live(actor, resource, config)
    claim_ref, action = _action(outdir, config, request)
    plan, checked, req = _plan(action['plan'])
    if checked != config or req != request or media != _read(config['authority'])['media'] or reference(media['path']) != media:
        raise ValueError('resume_selection_media_or_plan_changed')
    proof = _read(selection_evidence)
    identity, surface = proof.get('identity', {}), proof.get('preselection', {})
    now = time.time()
    if (Path(selection_evidence['path']).resolve() != Path(outdir).resolve() / 'FILE_SELECTION_PREFLIGHT.json'
            or proof.get('schema') != 'manual_file_selection_preflight/v4'
            or proof.get('action_claim') != claim_ref or proof.get('media') != media
            or any(proof.get(key) != config[key] for key in ('owner_id', 'generation', 'tab_id'))
            or proof.get('actor_thread_id') != threading.get_ident()
            or type(proof.get('observed_at')) not in (int, float) or not 0 <= now-proof['observed_at'] <= 10
            or identity.get('verified') is not True or identity.get('actual_public_uid') != _read(config['authority'])['expected_public_uid']
            or type(identity.get('observed_at')) not in (int, float) or not 0 <= now-identity['observed_at'] <= 60
            or surface.get('schema') != 'manual_upload_preselection/v1'
            or surface.get('origin') != 'https://creator.douyin.com' or surface.get('path') != '/creator-micro/content/upload'
            or type(surface.get('file_count')) is not int or surface['file_count'] != 1
            or type(surface.get('visible_file_count')) is not int or surface['visible_file_count'] != 1
            or type(surface.get('upload_button_count')) is not int or surface['upload_button_count'] != 1
            or type(surface.get('editor_count')) is not int or surface['editor_count'] != 0
            or surface.get('file_disabled') is not False):
        raise ValueError('resume_fresh_selection_boundary_required')
    value = dict(schema='manual_file_selection_claim/v4', action_claim=claim_ref, plan=action['plan'],
        config=action['config'], request=action['request'], authority=config['authority'], metadata=config['metadata'],
        prior_upload_claim=request['prior_upload_claim'], prior_failure=request['prior_failure'], observation=request['observation'],
        selection_evidence=selection_evidence, media=media, owner_id=actor.owner_id, generation=actor.generation,
        tab_id=config['tab_id'], actor_thread_id=threading.get_ident(), at_epoch=now, automatic_reselection_allowed=False)
    try:
        return _once(FILE_SELECTION_CLAIM, value)
    except FileExistsError:
        raise ValueError('resume_file_selection_slot_already_claimed') from None


def status(plan_ref):
    plan = _read(plan_ref)
    folder = Path(plan_ref['path']).parent
    if plan.get('schema') != PLAN_SCHEMA or not folder.resolve().is_relative_to(RUN.resolve()):
        raise ValueError('resume_plan_invalid')
    action, result, binding = folder/'ACTION_CLAIM.json', folder/'RESULT.json', folder/'RESULT_BINDING.json'
    if result.exists() and binding.exists():
        proof = _read(reference(binding))
        if proof.get('plan') != plan_ref or proof.get('claim') != reference(action) or proof.get('result') != reference(result):
            raise ValueError('resume_cached_result_changed')
        value = _read(proof['result'])
        if value.get('plan') != plan_ref or value.get('status') != 'prepared_no_submission' or value.get('file_selection_claim') != reference(FILE_SELECTION_CLAIM):
            raise ValueError('resume_cached_subject_changed')
        v3.v2.files._validate_refs(value)
        return {'status':'prepared_no_submission','result':proof['result'],'receipt':reference(binding)}
    if action.exists():
        return {'status':'outcome_unknown','scope':'resume_preparation','automatic_replay_allowed':False,
                'file_selection_claimed':FILE_SELECTION_CLAIM.exists()}
    return {'status':'file_selection_slot_already_claimed' if FILE_SELECTION_CLAIM.exists() else 'prepared','plan':plan_ref}


def _perform(actor, resource, plan_ref, arm_ref, run_action):
    plan, config, request = _plan(plan_ref)
    if status(plan_ref)['status'] != 'prepared':
        return status(plan_ref)
    if os.getpid()!=config['backend_pid'] or reference(ARM)!=arm_ref or validate_live(actor,resource,config)!=plan['state']:
        raise ValueError('resume_original_context_changed')
    folder=Path(plan_ref['path']).parent
    action=dict(schema='manual_republication_resume_action_claim/v4',plan=plan_ref,config=plan['config'],request=plan['request'],
        prior_upload_claim=request['prior_upload_claim'],prior_failure=request['prior_failure'],observation=request['observation'],
        action='resume_prepare_upload',owner_id=actor.owner_id,generation=actor.generation,tab_id=config['tab_id'],
        actor_thread_id=threading.get_ident(),at_epoch=time.time(),file_selection_limit=1,submit_allowed=False)
    try: action_ref=_once(folder/'ACTION_CLAIM.json',action)
    except FileExistsError:return status(plan_ref)
    try:
        result=run_action(actor,resource,config,request,folder/'preparation')
        _plan(plan_ref)
        if reference(ARM)!=arm_ref or validate_live(actor,resource,config)!=plan['state']:
            raise ValueError('resume_context_changed_after_preparation')
        file_ref=reference(FILE_SELECTION_CLAIM); file_claim=_read(file_ref)
        if file_claim.get('action_claim')!=action_ref or result.get('file_selection_claim')!=file_ref:
            raise ValueError('resume_selection_receipt_mismatch')
        if (result.get('schema')!='manual_republication_prepare_upload/v4' or result.get('action')!='resume_prepare_upload'
                or any(result.get(k) is not True for k in ('upload_ready','upload_completion_verified','uploaded','upload_attempted','metadata_readback_matched','hashtag_readback_verified'))
                or result.get('submitted') is not False or result.get('declaration_selected') is not False):
            raise ValueError('resume_complete_preparation_required')
        metadata=_read(config['metadata'])
        if (result.get('title_readback',{}).get('content')!=metadata['title']
                or ''.join(result.get('description_readback',{}).get('content','').split())!=''.join(metadata['description'].split())):
            raise ValueError('resume_metadata_readback_mismatch')
        v3.v2.files._validate_refs(result)
        ref=_once(folder/'RESULT.json',dict(schema='manual_republication_runtime_result/v4',status='prepared_no_submission',
            plan=plan_ref,claim=action_ref,file_selection_claim=file_ref,preparation=result,submitted=False,
            old_upload_claim_unchanged=True,original_manual_unchanged=True,account_pause_changed=False))
        receipt=_once(folder/'RESULT_BINDING.json',dict(schema='manual_republication_result_binding/v4',plan=plan_ref,claim=action_ref,result=ref))
        return {'status':'prepared_no_submission','result':ref,'receipt':receipt}
    except Exception as error:
        value=dict(schema='manual_republication_resume_unknown/v4',plan=plan_ref,claim=action_ref,scope='resume_preparation',
            error_type=type(error).__name__,file_selection_claimed=FILE_SELECTION_CLAIM.exists(),automatic_replay_allowed=False)
        if type(error) is getattr(run_action,'_blocked_class',None) and getattr(error,'code',None) in getattr(run_action,'_safe_codes',()):value['reason_code']=error.code
        if not (folder/'UNKNOWN.json').exists():_once(folder/'UNKNOWN.json',value)
        return status(plan_ref)


def _load_flow(config):
    path=SOURCE_PATHS['flow_v4']
    if reference(path)!=config['sources']['flow_v4']:raise ValueError('resume_flow_changed')
    module=types.ModuleType('src.operations_accounts._manual_resume_'+config['sources']['flow_v4']['sha256'][:16])
    module.__file__,module.__package__=str(path),'src.operations_accounts'
    exec(compile(path.read_bytes(),str(path),'exec'),module.__dict__)
    blocked,codes=getattr(module,'ResumePrepareBlocked',None),getattr(module,'SAFE_REASONS',frozenset())
    if blocked is not None:
        if not isinstance(blocked,type) or not issubclass(blocked,ValueError) or not isinstance(codes,frozenset) or any(not isinstance(c,str) or not c.isascii() or any(x not in 'abcdefghijklmnopqrstuvwxyz_' for x in c) for c in codes):raise ValueError('resume_safe_diagnostics_invalid')
        module.run_action._blocked_class,module.run_action._safe_codes=blocked,codes
    return module


def install_if_armed():
    if not ARM.is_file():return {'status':'not_armed'}
    try:
        arm_ref=reference(ARM);arm=_read(arm_ref)
        if set(arm)!={'schema','plan'} or arm['schema']!='manual_republication_runtime_arm/v4':raise ValueError('resume_arm_invalid')
        plan,config,request=_plan(arm['plan']);folder=Path(arm['plan']['path']).parent
        if os.getpid()!=config['backend_pid']:return {'status':'different_process_no_install'}
        if status(arm['plan'])['status']!='prepared':return status(arm['plan'])
        spaces=[t._target.__globals__ for t in threading.enumerate() if t.name=='AccountBrowser-'+config['account_key'] and t.is_alive()
            and getattr(getattr(t,'_target',None),'__name__','')=='_host' and Path(t._target.__code__.co_filename).resolve()==SOURCE_PATHS['host'].resolve() and getattr(t,'_args',())==(config['account_key'],)]
        if len(spaces)!=1:raise ValueError('resume_unique_original_actor_required')
        namespace=spaces[0];previous=namespace['_poll_manual_windows']
        if getattr(previous,'_manual_resume_plan',None)==arm['plan']:return {'status':'callback_already_registered'}
        if getattr(previous,'_manual_resume_plan',None) is not None:raise ValueError('resume_other_plan_registered')
        flow=_load_flow(config)
        def poll(actor,resource):
            if (actor.account_id,actor.owner_id,actor.generation)!=(config['account_id'],config['owner_id'],config['generation']):return previous(actor,resource)
            defer=False
            try:
                actor._assert_thread();actor._check_owner();value=previous(actor,resource)
                if actor._stack:defer=True;return value
                _perform(actor,resource,arm['plan'],arm_ref,flow.run_action)
            except Exception as error:
                if not (folder/'REFUSED.json').exists():_once(folder/'REFUSED.json',dict(schema='manual_republication_resume_refusal/v4',plan=arm['plan'],error_type=type(error).__name__,action_started=(folder/'ACTION_CLAIM.json').exists()))
            finally:
                if not defer and namespace['_poll_manual_windows'] is poll:namespace['_poll_manual_windows']=previous
            return None
        poll._manual_resume_plan=arm['plan'];namespace['_poll_manual_windows']=poll
        return {'status':'callback_registered_waiting_original_actor_tick'}
    except Exception as error:return {'status':'refused','error_type':type(error).__name__,'reason':str(error) if isinstance(error,ValueError) else 'owner_guard_refused'}
