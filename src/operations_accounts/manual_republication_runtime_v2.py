"""One explicit upload preparation in the original waiting manual session.

The v1 inspector stays frozen. This version has one mutation capability only:
the reviewed prepare_upload flow, never declaration selection or publication.
The intent-wide UPLOAD_CLAIM survives changed requests/output directories.
"""
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import types

from . import manual_republication_runtime_v1 as files

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'data/production_trials/fanqie_declared_republication_20261117_v1'
ARM = RUN / 'manual_runtime_v2/ARM.json'
UPLOAD_CLAIM = RUN / 'UPLOAD_CLAIM.json'
SOURCE_PATHS = {
    'guard_v1': ROOT / 'src/operations_accounts/manual_republication_runtime_v1.py',
    'runtime_v2': Path(__file__).resolve(),
    'flow_v2': ROOT / 'src/operations_accounts/manual_republication_flow_v2.py',
    'flow_v1': ROOT / 'src/operations_accounts/manual_republication_flow_v1.py',
    'browser_session': ROOT / 'src/platform_adapter/browser_session.py',
    'publish_workflow': ROOT / 'src/platform_adapter/publish_workflow.py',
    'publish_verification': ROOT / 'src/platform_adapter/publish_verification.py',
    'upload_diagnostic': ROOT / 'src/platform_adapter/upload_surface_diagnostic.py',
    'app': ROOT / 'src/web/app.py',
    'host': ROOT / 'src/operations_accounts/browser_control_runtime.py',
}
CONFIG_SCHEMA = 'manual_republication_runtime_config/v2'
REQUEST_SCHEMA = 'manual_republication_operator_request/v2'
PLAN_SCHEMA = 'manual_republication_runtime_plan/v2'
reference, _read, _once, _digest = files.reference, files._read, files._once, files._digest


def _sources(config):
    if not isinstance(config.get('sources'), dict) or set(config['sources']) != set(SOURCE_PATHS):
        raise ValueError('upload_exact_sources_required')
    for name, path in SOURCE_PATHS.items():
        if reference(path) != config['sources'][name]:
            raise ValueError('upload_source_changed:' + name)


def _load(config, key):
    path = SOURCE_PATHS[key]
    if reference(path) != config['sources'][key]:
        raise ValueError('upload_source_changed:' + key)
    name = 'src.operations_accounts._manual_upload_' + key + '_' + config['sources'][key]['sha256'][:16]
    module = types.ModuleType(name)
    module.__file__, module.__package__ = str(path), 'src.operations_accounts'
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def _scope(config, *, verify_media=False):
    _sources(config)
    if (type(config['backend_pid']) is not int or type(config['generation']) is not int
            or config['generation'] < 1
            or type(config['backend_create_time']) not in (int, float)
            or not config['owner_id'].startswith('backend:' + str(config['backend_pid']) + ':')
            or files._process(config['backend_pid']) != config['backend_create_time']):
        raise ValueError('upload_original_process_changed')
    if (Path(config['authority']['path']).resolve() != (RUN / 'USER_AUTHORIZATION.json').resolve()
            or Path(config['operator_authority']['path']).resolve() != (RUN / 'BACKEND_OPERATION_AUTHORIZATION.json').resolve()
            or Path(config['metadata']['path']).resolve() != (RUN / 'PUBLICATION_METADATA_V2.json').resolve()):
        raise ValueError('upload_exact_intent_files_required')
    auth, op, metadata = _read(config['authority']), _read(config['operator_authority']), _read(config['metadata'])
    if (auth.get('schema') != 'explicit_republication_intent/v1' or not auth.get('user_statement')
            or auth.get('account_key') != config['account_key'] or auth.get('account_uuid') != config['account_id']
            or not isinstance(auth.get('expected_public_uid'), str) or not auth['expected_public_uid']
            or type(auth.get('new_publication_limit')) is not int or auth['new_publication_limit'] != 1
            or auth.get('model_media_calls_allowed') is not False or auth.get('old_records_unchanged') is not True
            or not auth.get('old_post_id') or not auth.get('declaration_requirement')):
        raise ValueError('upload_parent_authority_invalid')
    if (op.get('schema') != 'original_session_backend_operator_authorization/v1'
            or op.get('parent_authority') != config['authority'] or not op.get('user_statement')
            or op.get('later_writes_require_reviewed_stage_plan') is not True
            or op.get('no_new_profile_or_owner_takeover') is not True
            or op.get('no_direct_private_platform_posting_endpoint') is not True
            or op.get('preserve_original_unknown_locks') is not True):
        raise ValueError('upload_operator_authority_invalid')
    fields = {'schema', 'account_uuid', 'account_key', 'media', 'title', 'description', 'hashtags',
              'ai_generated', 'fictional_story', 'visibility'}
    if (not isinstance(metadata, dict) or set(metadata) != fields
            or metadata['schema'] != 'manual_republication_metadata/v1'
            or metadata['account_uuid'] != config['account_id'] or metadata['account_key'] != config['account_key']
            or metadata['media'] != auth.get('media') or metadata['ai_generated'] is not True
            or metadata['fictional_story'] is not True or metadata['visibility'] != 'public'
            or not isinstance(metadata['title'], str) or not 1 <= len(metadata['title']) <= 500
            or not isinstance(metadata['description'], str) or not 1 <= len(metadata['description']) <= 10000
            or '剧情虚构，非真实事件。' not in metadata['description']
            or not isinstance(metadata['hashtags'], list) or len(metadata['hashtags']) != 5
            or any(not isinstance(tag, str) or not tag.strip() or len(tag) > 100 for tag in metadata['hashtags'])
            or len(set(metadata['hashtags'])) != 5):
        raise ValueError('upload_frozen_metadata_invalid')
    if verify_media and reference(auth['media']['path']) != auth['media']:
        raise ValueError('upload_authorized_media_changed')
    return auth, metadata


def _config(ref):
    value = _read(ref)
    fields = {'schema', 'backend_pid', 'backend_create_time', 'account_key', 'account_id', 'owner_id',
              'generation', 'binding_version', 'browser_db', 'control_db', 'control_snapshot',
              'manual_command_id', 'manual_request_sha256', 'tab_id', 'authority', 'operator_authority',
              'metadata', 'sources'}
    if not isinstance(value, dict) or set(value) != fields or value['schema'] != CONFIG_SCHEMA:
        raise ValueError('upload_config_invalid')
    for key in ('account_key', 'account_id', 'owner_id', 'binding_version', 'browser_db', 'control_db',
                'manual_command_id', 'manual_request_sha256', 'tab_id'):
        if not isinstance(value[key], str) or not value[key]:
            raise ValueError('upload_scope_required:' + key)
    if (not isinstance(value['control_snapshot'], dict)
            or set(value['control_snapshot']) != {'state', 'revision'}
            or value['control_snapshot']['state'] not in {'active', 'paused'}
            or type(value['control_snapshot']['revision']) is not int):
        raise ValueError('upload_control_snapshot_invalid')
    _scope(value, verify_media=True)
    return value


def _request(ref, config_ref):
    value = _read(ref)
    if (not isinstance(value, dict) or set(value) != {'schema', 'config', 'action'}
            or value['schema'] != REQUEST_SCHEMA or value['config'] != config_ref
            or value['action'] != 'prepare_upload'):
        raise ValueError('upload_prepare_only')
    return value


def validate_live(actor, resource, config):
    """Called before/after each flow RPC; never changes owner/manual/control."""
    _scope(config)
    return _load(config, 'guard_v1').validate_live(actor, resource, config)


def _state(config):
    return _load(config, 'guard_v1')._state(config)


def prepare(config_ref, request_ref, output_directory):
    folder = Path(output_directory).resolve()
    if not folder.is_relative_to(RUN.resolve()) or folder.exists():
        raise ValueError('upload_new_plan_directory_required')
    if UPLOAD_CLAIM.exists():
        raise ValueError('upload_intent_slot_already_claimed')
    config = _config(config_ref)
    request = _request(request_ref, config_ref)
    return _once(folder / 'PLAN.json', dict(schema=PLAN_SCHEMA, config=config_ref, request=request_ref,
        action=request['action'], state=_state(config), metadata=config['metadata'], authority=config['authority'],
        upload_limit=1, submit_allowed=False, declaration_selection_allowed=False, prepared_only=True))


def _plan(ref):
    value = _read(ref)
    if (value.get('schema') != PLAN_SCHEMA or not Path(ref['path']).resolve().is_relative_to(RUN.resolve())
            or value.get('submit_allowed') is not False or value.get('declaration_selection_allowed') is not False
            or value.get('upload_limit') != 1):
        raise ValueError('upload_plan_invalid')
    config = _config(value['config'])
    request = _request(value['request'], value['config'])
    if (value.get('action') != 'prepare_upload' or value.get('metadata') != config['metadata']
            or value.get('authority') != config['authority']):
        raise ValueError('upload_plan_binding_changed')
    return value, config, request


def status(plan_ref):
    """Local cache only. The global claim blocks every alternate request/plan."""
    plan = _read(plan_ref)
    folder = Path(plan_ref['path']).parent
    if plan.get('schema') != PLAN_SCHEMA or not folder.resolve().is_relative_to(RUN.resolve()):
        raise ValueError('upload_plan_invalid')
    if not UPLOAD_CLAIM.exists():
        return {'status': 'prepared', 'plan': plan_ref}
    try:
        claim_ref = reference(UPLOAD_CLAIM)
        claim = _read(claim_ref)
    except (ValueError, json.JSONDecodeError):
        return {'status': 'outcome_unknown', 'scope': 'upload_preparation', 'automatic_replay_allowed': False}
    if claim.get('plan') != plan_ref:
        return {'status': 'upload_slot_already_claimed', 'claim': claim_ref,
                'original_plan': claim.get('plan'), 'automatic_replay_allowed': False}
    result = folder / 'RESULT.json'
    receipt = folder / 'RESULT_BINDING.json'
    if result.exists() and receipt.exists():
        proof = _read(reference(receipt))
        if proof.get('plan') != plan_ref or proof.get('claim') != claim_ref or proof.get('result') != reference(result):
            raise ValueError('upload_cached_receipt_changed')
        value = _read(proof['result'])
        if (value.get('plan') != plan_ref or value.get('claim') != claim_ref or value.get('submitted') is not False
                or value.get('status') != 'prepared_no_submission' or claim.get('request') != plan['request']):
            raise ValueError('upload_cached_result_changed')
        files._validate_refs(value)
        return {'status': 'prepared_no_submission', 'result': proof['result'], 'receipt': reference(receipt)}
    unknown = folder / 'UNKNOWN.json'
    return {'status': 'outcome_unknown', 'scope': 'upload_preparation', 'claim': claim_ref,
            'unknown': reference(unknown) if unknown.exists() else None, 'automatic_replay_allowed': False}


def _perform(actor, resource, plan_ref, arm_ref, run_action):
    plan, config, request = _plan(plan_ref)
    cached = status(plan_ref)
    if cached['status'] != 'prepared':
        return cached
    if reference(ARM) != arm_ref or os.getpid() != config['backend_pid']:
        raise ValueError('upload_arm_or_process_changed')
    if validate_live(actor, resource, config) != plan['state']:
        raise ValueError('upload_prepared_scope_changed')
    auth = _read(config['authority'])
    claim = dict(schema='manual_republication_upload_claim/v1', plan=plan_ref, request=plan['request'],
        config=plan['config'], arm=arm_ref, authority=config['authority'], metadata=config['metadata'], media=auth['media'],
        action='prepare_upload', owner_id=actor.owner_id, generation=actor.generation, tab_id=config['tab_id'],
        actor_thread_id=threading.get_ident(), at_epoch=time.time(), submissions_allowed=0)
    try:
        claim_ref = _once(UPLOAD_CLAIM, claim)
    except FileExistsError:
        return status(plan_ref)
    folder = Path(plan_ref['path']).parent
    try:
        result = run_action(actor, resource, config, request, folder / 'preparation')
        _plan(plan_ref)
        if reference(ARM) != arm_ref or validate_live(actor, resource, config) != plan['state']:
            raise ValueError('upload_context_changed_after_preparation')
        if (not isinstance(result, dict) or result.get('schema') != 'manual_republication_prepare_upload/v1'
                or result.get('action') != 'prepare_upload' or result.get('submitted') is not False
                or result.get('declaration_selected') is not False
                or result.get('upload_ready') is not True or result.get('upload_completion_verified') is not True
                or result.get('uploaded') is not True or result.get('upload_attempted') is not True
                or result.get('metadata_readback_matched') is not True
                or result.get('hashtag_readback_verified') is not True):
            raise ValueError('upload_prepare_result_invalid')
        metadata = _read(config['metadata'])
        if (result.get('title_readback', {}).get('content') != metadata['title']
                or ''.join(result.get('description_readback', {}).get('content', '').split())
                    != ''.join(metadata['description'].split())):
            raise ValueError('upload_final_metadata_readback_mismatch')
        files._validate_refs(result)
        ref = _once(folder / 'RESULT.json', dict(schema='manual_republication_runtime_result/v2',
            status='prepared_no_submission', plan=plan_ref, claim=claim_ref, preparation=result,
            original_manual_unchanged=True, account_pause_changed=False, submitted=False,
            original_publication_and_locks_unchanged=True))
        receipt = _once(folder / 'RESULT_BINDING.json', dict(schema='manual_republication_result_binding/v2',
            plan=plan_ref, claim=claim_ref, result=ref))
        return {'status': 'prepared_no_submission', 'result': ref, 'receipt': receipt}
    except Exception as error:
        value = dict(schema='manual_republication_upload_unknown/v1', status='outcome_unknown',
            scope='upload_preparation', plan=plan_ref, claim=claim_ref, error_type=type(error).__name__,
            publication_outcome_changed=False, automatic_replay_allowed=False)
        if (type(error) is getattr(run_action, '_safe_blocked_class', None)
                and getattr(error, 'code', None) in getattr(run_action, '_safe_codes', ())):
            value['reason_code'] = error.code
        if not (folder / 'UNKNOWN.json').exists():
            _once(folder / 'UNKNOWN.json', value)
        return {'status': 'outcome_unknown', 'scope': 'upload_preparation', 'claim': claim_ref,
                'automatic_replay_allowed': False}


def install_if_armed():
    if not ARM.is_file():
        return {'status': 'not_armed'}
    try:
        arm_ref = reference(ARM)
        arm = _read(arm_ref)
        if set(arm) != {'schema', 'plan'} or arm['schema'] != 'manual_republication_runtime_arm/v2':
            raise ValueError('upload_arm_invalid')
        plan, config, request = _plan(arm['plan'])
        folder = Path(arm['plan']['path']).parent
        if os.getpid() != config['backend_pid']:
            return {'status': 'different_process_no_install'}
        cached = status(arm['plan'])
        if cached['status'] != 'prepared':
            return cached
        namespaces = []
        for thread in threading.enumerate():
            target = getattr(thread, '_target', None)
            if (thread.name == 'AccountBrowser-' + config['account_key'] and thread.is_alive()
                    and getattr(target, '__name__', None) == '_host'
                    and Path(target.__code__.co_filename).resolve() == SOURCE_PATHS['host'].resolve()
                    and getattr(thread, '_args', ()) == (config['account_key'],)):
                namespaces.append(target.__globals__)
        if len(namespaces) != 1:
            raise ValueError('upload_unique_original_actor_required')
        namespace = namespaces[0]
        previous_poll = namespace['_poll_manual_windows']
        current = getattr(previous_poll, '_manual_upload_plan', None)
        if current == arm['plan']:
            return {'status': 'callback_already_registered'}
        if current is not None:
            raise ValueError('upload_other_plan_registered')
        flow = _load(config, 'flow_v2')
        run_action = flow.run_action
        blocked, codes = getattr(flow, 'PrepareUploadBlocked', None), getattr(flow, 'SAFE_REASONS', frozenset())
        if blocked is not None:
            if (not isinstance(blocked, type) or not issubclass(blocked, ValueError)
                    or not isinstance(codes, frozenset)
                    or any(not isinstance(code, str) or not 1 <= len(code) <= 100
                           or any(c not in 'abcdefghijklmnopqrstuvwxyz_' for c in code) for code in codes)):
                raise ValueError('upload_safe_diagnostics_invalid')
            run_action._safe_blocked_class, run_action._safe_codes = blocked, codes

        def poll(actor, resource):
            if (actor.account_id != config['account_id'] or actor.owner_id != config['owner_id']
                    or actor.generation != config['generation']):
                return previous_poll(actor, resource)
            defer = False
            try:
                actor._assert_thread()
                actor._check_owner()
                result = previous_poll(actor, resource)
                if actor._stack:
                    defer = True
                    return result
                _perform(actor, resource, arm['plan'], arm_ref, run_action)
            except Exception as error:
                if not (folder / 'REFUSED.json').exists():
                    _once(folder / 'REFUSED.json', dict(schema='manual_republication_upload_refusal/v1',
                        plan=arm['plan'], error_type=type(error).__name__,
                        reason=str(error) if isinstance(error, ValueError) else 'owner_guard_refused',
                        action_started=UPLOAD_CLAIM.exists()))
            finally:
                if not defer and namespace['_poll_manual_windows'] is poll:
                    namespace['_poll_manual_windows'] = previous_poll
            return None

        poll._manual_upload_plan = arm['plan']
        namespace['_poll_manual_windows'] = poll
        return {'status': 'callback_registered_waiting_original_actor_tick'}
    except Exception as error:
        return {'status': 'refused', 'error_type': type(error).__name__,
                'reason': str(error) if isinstance(error, ValueError) else 'original_actor_guard_refused'}
