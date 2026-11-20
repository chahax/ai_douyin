"""Named no-navigation observation after a verified preselection failure.

No upload resume, declaration selection or publication exists in this version.
The original v2 UPLOAD_CLAIM and UNKNOWN remain unchanged.
"""
import os
from pathlib import Path
import threading
import time
import types

from . import manual_republication_runtime_v2 as v2

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'data/production_trials/fanqie_declared_republication_20261117_v1'
ARM = RUN / 'manual_runtime_v3/ARM.json'
SOURCE_PATHS = dict(v2.SOURCE_PATHS, runtime_v3=Path(__file__).resolve(),
    flow_v3=ROOT / 'src/operations_accounts/manual_republication_flow_v3.py')
CONFIG_SCHEMA = 'manual_republication_runtime_config/v3'
REQUEST_SCHEMA = 'manual_republication_operator_request/v3'
PLAN_SCHEMA = 'manual_republication_runtime_plan/v3'
reference, _read, _once = v2.reference, v2._read, v2._once


def _projection(config):
    return dict(config, sources={key: config['sources'][key] for key in v2.SOURCE_PATHS})


def _scope(config, *, verify_media=False):
    if not isinstance(config.get('sources'), dict) or set(config['sources']) != set(SOURCE_PATHS):
        raise ValueError('observation_exact_sources_required')
    for name, path in SOURCE_PATHS.items():
        if reference(path) != config['sources'][name]:
            raise ValueError('observation_source_changed:' + name)
    v2._scope(_projection(config), verify_media=verify_media)


def _config(ref):
    config = _read(ref)
    fields = {'schema', 'backend_pid', 'backend_create_time', 'account_key', 'account_id', 'owner_id',
        'generation', 'binding_version', 'browser_db', 'control_db', 'control_snapshot',
        'manual_command_id', 'manual_request_sha256', 'tab_id', 'authority', 'operator_authority', 'metadata', 'sources'}
    if not isinstance(config, dict) or set(config) != fields or config['schema'] != CONFIG_SCHEMA:
        raise ValueError('observation_config_invalid')
    _scope(config, verify_media=True)
    return config


def _request(ref, config_ref):
    value = _read(ref)
    if (not isinstance(value, dict) or set(value) != {'schema', 'config', 'action', 'prior_upload_claim', 'prior_failure'}
            or value['schema'] != REQUEST_SCHEMA or value['config'] != config_ref or value['action'] != 'observe_current'):
        raise ValueError('observation_current_page_only')
    return value


def _prior(config, request):
    claim_ref = request['prior_upload_claim']
    if Path(claim_ref['path']).resolve() != (RUN / 'UPLOAD_CLAIM.json').resolve():
        raise ValueError('observation_original_upload_claim_required')
    claim = _read(claim_ref)
    plan, previous = _read(claim['plan']), _read(claim['config'])
    old_request = _read(claim['request'])
    if (claim.get('schema') != 'manual_republication_upload_claim/v1' or claim.get('action') != 'prepare_upload'
            or claim.get('submissions_allowed') != 0 or claim.get('authority') != config['authority']
            or claim.get('metadata') != config['metadata'] or claim.get('media') != _read(config['authority'])['media']
            or any(claim.get(key) != config[key] for key in ('owner_id', 'generation', 'tab_id'))
            or plan.get('schema') != v2.PLAN_SCHEMA or plan.get('config') != claim['config']
            or plan.get('request') != claim['request'] or plan.get('action') != 'prepare_upload'
            or previous.get('schema') != v2.CONFIG_SCHEMA
            or any(previous.get(key) != config[key] for key in config if key not in {'schema', 'sources'})
            or old_request != {'schema': v2.REQUEST_SCHEMA, 'config': claim['config'], 'action': 'prepare_upload'}):
        raise ValueError('observation_prior_subject_changed')
    for name in ('runtime_v2', 'flow_v2'):
        if previous['sources'][name] != config['sources'][name]:
            raise ValueError('observation_preselection_instrumentation_changed')
    folder = Path(claim['plan']['path']).parent.resolve()
    if not folder.is_relative_to(RUN.resolve()):
        raise ValueError('observation_original_plan_outside_intent')
    prep = folder / 'preparation'
    if Path(request['prior_failure']['path']).resolve() != prep / 'PREPARE_FAILURE.json':
        raise ValueError('observation_exact_failure_required')
    failure = _read(request['prior_failure'])
    unknown_ref = reference(folder / 'UNKNOWN.json')
    unknown = _read(unknown_ref)
    if (failure.get('schema') != 'manual_prepare_upload_failure/v1'
            or failure.get('global_upload_claim') != claim_ref or failure.get('error_type') != 'BrowserNavigationTimeout'
            or failure.get('reason_code') != 'prepare_upload_surface_unconfirmed'
            or failure.get('upload_attempted') is not False or failure.get('submitted') is not False
            or failure.get('upload_completion_claimed') is not False
            or unknown.get('schema') != 'manual_republication_upload_unknown/v1'
            or unknown.get('claim') != claim_ref or unknown.get('plan') != claim['plan']
            or unknown.get('status') != 'outcome_unknown' or unknown.get('scope') != 'upload_preparation'
            or unknown.get('automatic_replay_allowed') is not False
            or {p.name for p in prep.iterdir()} != {'PREPARE_FAILURE.json'}):
        raise ValueError('observation_known_preselection_proof_required')
    return {'upload_claim': claim_ref, 'failure': request['prior_failure'], 'v2_unknown': unknown_ref,
        'v2_plan': claim['plan'], 'v2_config': claim['config'], 'v2_request': claim['request'],
        'file_selection_proven_not_started': True, 'navigation_stage_established': False}


def validate_live(actor, resource, config):
    _scope(config)
    return v2._load(_projection(config), 'guard_v1').validate_live(actor, resource, config)


def _state(config):
    return v2._state(_projection(config))


def prepare(config_ref, request_ref, output_directory):
    folder = Path(output_directory).resolve()
    if not folder.is_relative_to(RUN.resolve()) or folder.exists():
        raise ValueError('observation_new_plan_directory_required')
    config, request = _config(config_ref), _request(request_ref, config_ref)
    return _once(folder / 'PLAN.json', dict(schema=PLAN_SCHEMA, config=config_ref, request=request_ref,
        action='observe_current', state=_state(config), prior=_prior(config, request),
        navigation_allowed=False, input_allowed=False, file_selection_allowed=False))


def _plan(ref):
    plan = _read(ref)
    if (plan.get('schema') != PLAN_SCHEMA or not Path(ref['path']).resolve().is_relative_to(RUN.resolve())
            or any(plan.get(key) is not False for key in ('navigation_allowed', 'input_allowed', 'file_selection_allowed'))):
        raise ValueError('observation_plan_invalid')
    config = _config(plan['config'])
    request = _request(plan['request'], plan['config'])
    if plan.get('action') != 'observe_current' or _prior(config, request) != plan['prior']:
        raise ValueError('observation_prepared_prior_changed')
    return plan, config, request


def status(plan_ref):
    plan = _read(plan_ref)
    folder = Path(plan_ref['path']).parent
    if plan.get('schema') != PLAN_SCHEMA or not folder.resolve().is_relative_to(RUN.resolve()):
        raise ValueError('observation_plan_invalid')
    claim, result, binding = folder / 'ACTION_CLAIM.json', folder / 'RESULT.json', folder / 'RESULT_BINDING.json'
    if result.exists() and binding.exists():
        proof = _read(reference(binding))
        if proof.get('plan') != plan_ref or proof.get('claim') != reference(claim) or proof.get('result') != reference(result):
            raise ValueError('observation_cached_result_changed')
        value = _read(proof['result'])
        if value.get('plan') != plan_ref or value.get('claim') != proof['claim'] or value.get('status') != 'observed_current':
            raise ValueError('observation_cached_subject_changed')
        v2.files._validate_refs(value)
        return {'status': 'observed_current', 'result': proof['result'], 'receipt': reference(binding)}
    return ({'status': 'outcome_unknown', 'scope': 'current_page_observation', 'automatic_replay_allowed': False}
            if claim.exists() else {'status': 'prepared', 'plan': plan_ref})


def _perform(actor, resource, plan_ref, arm_ref, run_action):
    plan, config, request = _plan(plan_ref)
    if status(plan_ref)['status'] != 'prepared':
        return status(plan_ref)
    if os.getpid() != config['backend_pid'] or reference(ARM) != arm_ref or validate_live(actor, resource, config) != plan['state']:
        raise ValueError('observation_original_context_changed')
    folder = Path(plan_ref['path']).parent
    claim = dict(schema='manual_republication_observation_claim/v3', plan=plan_ref, config=plan['config'],
        request=plan['request'], prior_upload_claim=request['prior_upload_claim'], prior_failure=request['prior_failure'],
        action='observe_current', at_epoch=time.time(), actor_thread_id=threading.get_ident(),
        navigation_allowed=False, input_allowed=False, file_selection_allowed=False)
    try:
        claim_ref = _once(folder / 'ACTION_CLAIM.json', claim)
    except FileExistsError:
        return status(plan_ref)
    try:
        observation = run_action(actor, resource, config, request, folder / 'observation')
        _plan(plan_ref)
        if reference(ARM) != arm_ref or validate_live(actor, resource, config) != plan['state']:
            raise ValueError('observation_context_changed_after_read')
        if (observation.get('schema') != 'manual_republication_observation/v3'
                or observation.get('action') != 'observe_current'
                or any(observation.get(key) is not False for key in ('uploaded', 'submitted', 'input_performed',
                                                                    'navigation_performed', 'file_selected'))):
            raise ValueError('observation_readonly_result_required')
        v2.files._validate_refs(observation)
        ref = _once(folder / 'RESULT.json', dict(schema='manual_republication_runtime_result/v3',
            status='observed_current', plan=plan_ref, claim=claim_ref, observation=observation,
            old_upload_claim_unchanged=True, original_manual_unchanged=True, account_pause_changed=False))
        receipt = _once(folder / 'RESULT_BINDING.json', dict(schema='manual_republication_result_binding/v3',
            plan=plan_ref, claim=claim_ref, result=ref))
        return {'status': 'observed_current', 'result': ref, 'receipt': receipt}
    except Exception as error:
        if not (folder / 'UNKNOWN.json').exists():
            value = dict(schema='manual_republication_observation_unknown/v3',
                plan=plan_ref, claim=claim_ref, scope='current_page_observation', error_type=type(error).__name__,
                automatic_replay_allowed=False, old_upload_claim_unchanged=True)
            if (type(error) is getattr(run_action, '_safe_blocked_class', None)
                    and getattr(error, 'code', None) in getattr(run_action, '_safe_codes', ())):
                value['reason_code'] = error.code
            _once(folder / 'UNKNOWN.json', value)
        return {'status': 'outcome_unknown', 'scope': 'current_page_observation', 'automatic_replay_allowed': False}


def _load_flow(config):
    path = SOURCE_PATHS['flow_v3']
    if reference(path) != config['sources']['flow_v3']:
        raise ValueError('observation_flow_changed')
    module = types.ModuleType('src.operations_accounts._manual_observe_' + config['sources']['flow_v3']['sha256'][:16])
    module.__file__, module.__package__ = str(path), 'src.operations_accounts'
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    blocked, codes = getattr(module, 'ObservationBlocked', None), getattr(module, 'SAFE_REASONS', frozenset())
    if blocked is not None:
        if (not isinstance(blocked, type) or not issubclass(blocked, ValueError) or not isinstance(codes, frozenset)
                or any(not isinstance(c, str) or not 1 <= len(c) <= 100
                       or any(x not in 'abcdefghijklmnopqrstuvwxyz_' for x in c) for c in codes)):
            raise ValueError('observation_safe_diagnostics_invalid')
        module.run_action._safe_blocked_class, module.run_action._safe_codes = blocked, codes
    return module


def install_if_armed():
    if not ARM.is_file():
        return {'status': 'not_armed'}
    try:
        arm_ref = reference(ARM)
        arm = _read(arm_ref)
        if set(arm) != {'schema', 'plan'} or arm['schema'] != 'manual_republication_runtime_arm/v3':
            raise ValueError('observation_arm_invalid')
        plan, config, request = _plan(arm['plan'])
        folder = Path(arm['plan']['path']).parent
        if os.getpid() != config['backend_pid']:
            return {'status': 'different_process_no_install'}
        if status(arm['plan'])['status'] != 'prepared':
            return status(arm['plan'])
        namespaces = [t._target.__globals__ for t in threading.enumerate()
            if t.name == 'AccountBrowser-' + config['account_key'] and t.is_alive()
            and getattr(getattr(t, '_target', None), '__name__', '') == '_host'
            and Path(t._target.__code__.co_filename).resolve() == SOURCE_PATHS['host'].resolve()
            and getattr(t, '_args', ()) == (config['account_key'],)]
        if len(namespaces) != 1:
            raise ValueError('observation_unique_original_actor_required')
        namespace = namespaces[0]
        previous = namespace['_poll_manual_windows']
        if getattr(previous, '_manual_observation_plan', None) == arm['plan']:
            return {'status': 'callback_already_registered'}
        if getattr(previous, '_manual_observation_plan', None) is not None:
            raise ValueError('observation_other_plan_registered')
        flow = _load_flow(config)

        def poll(actor, resource):
            if (actor.account_id, actor.owner_id, actor.generation) != (config['account_id'], config['owner_id'], config['generation']):
                return previous(actor, resource)
            defer = False
            try:
                actor._assert_thread(); actor._check_owner()
                value = previous(actor, resource)
                if actor._stack:
                    defer = True
                    return value
                _perform(actor, resource, arm['plan'], arm_ref, flow.run_action)
            except Exception as error:
                if not (folder / 'REFUSED.json').exists():
                    _once(folder / 'REFUSED.json', dict(schema='manual_republication_observation_refusal/v3',
                        plan=arm['plan'], error_type=type(error).__name__, action_started=(folder / 'ACTION_CLAIM.json').exists()))
            finally:
                if not defer and namespace['_poll_manual_windows'] is poll:
                    namespace['_poll_manual_windows'] = previous
            return None

        poll._manual_observation_plan = arm['plan']
        namespace['_poll_manual_windows'] = poll
        return {'status': 'callback_registered_waiting_original_actor_tick'}
    except Exception as error:
        return {'status': 'refused', 'error_type': type(error).__name__,
                'reason': str(error) if isinstance(error, ValueError) else 'owner_guard_refused'}
