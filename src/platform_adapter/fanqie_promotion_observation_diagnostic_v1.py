"""One opt-in, guarded, same-Page passive metadata observation diagnostic.

Does not own browsers, submit platform forms, replay API requests or produce a
business promotion contract. The managed caller supplies its actual owner
subject and dispatch/identity guard. An interrupted START is never replayed.
"""
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

from .fanqie_promotion_observer_v1 import (
    ORIGIN, VERSION as OBSERVER_SCHEMA, save_observation, validate_subject,
)

VERSION = 'fanqie_promotion_observation_diagnostic/v1'
REQUEST_SCHEMA = 'fanqie_promotion_observer_request/v1'
PURPOSE = 'read_only_promotion_metadata_diagnosis'
SCOPE = {'resource_id', 'binding_version', 'platform_identity_key', 'environment_key'}
ROOT = Path(__file__).resolve().parents[2]


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _bind(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def _read(binding):
    if (not isinstance(binding, dict) or set(binding) != {'path', 'sha256'}
            or _bind(binding['path']) != binding):
        raise ValueError('diagnostic_evidence_binding_changed')
    return json.loads(Path(binding['path']).read_bytes())


def _save(path, value):
    with path.open('xb') as out:
        out.write(_bytes(value))
    return _bind(path)


def validate_request_scope(binding, scope):
    """Queue-time read-only preflight; no fabricated owner/task is necessary."""
    if (not isinstance(scope, dict) or set(scope) != SCOPE
            or any(not isinstance(v, str) or not v.strip() for v in scope.values())):
        raise ValueError('diagnostic_exact_resource_scope_required')
    request = _read(binding)
    if (not isinstance(request, dict) or set(request) != SCOPE | {
            'schema', 'endpoint_paths', 'wait_ms', 'purpose'}
            or request.get('schema') != REQUEST_SCHEMA
            or request.get('purpose') != PURPOSE
            or any(request.get(k) != scope[k] for k in SCOPE)
            or type(request.get('wait_ms')) is not int
            or not 0 <= request['wait_ms'] <= 5000):
        raise ValueError('diagnostic_exact_read_only_request_required')
    paths = request.get('endpoint_paths')
    if (not isinstance(paths, list) or not 1 <= len(paths) <= 8
            or any(not isinstance(p, str) or not p.startswith('/api/')
                   or '?' in p or '#' in p or len(p) > 256 for p in paths)
            or len(set(paths)) != len(paths)):
        raise ValueError('diagnostic_observed_endpoint_paths_required')
    return request


def validate_request(binding, subject):
    subject = validate_subject(subject)
    return validate_request_scope(binding, {k: subject[k] for k in SCOPE})


def _location(url):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname != 'kol.fanqieopen.com'
                or parsed.port not in (None, 443) or parsed.username or parsed.password
                or parsed.path != '/page/promotion-list'):
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError('diagnostic_requires_current_promotion_list_page') from None
    return {'origin': ORIGIN, 'path': parsed.path}


def _cached(directory, request_binding, subject):
    result = json.loads((directory / 'RESULT.json').read_bytes())
    if (result.get('schema') != VERSION or result.get('request') != request_binding
            or result.get('subject') != subject):
        raise ValueError('diagnostic_cached_subject_changed')
    _read(result['request'])
    for binding in result['evidence'].values():
        _read(binding)
    return result


def _check_observation(value, subject, paths, page_id=None):
    if (not isinstance(value, dict) or value.get('schema') != OBSERVER_SCHEMA
            or value.get('subject') != subject
            or value.get('selected_endpoint_paths') != sorted(paths)
            or value.get('page_location') != {'origin': ORIGIN, 'path': '/page/promotion-list'}
            or not value.get('worker_page_id')
            or (page_id is not None and value['worker_page_id'] != page_id)):
        raise ValueError('diagnostic_observer_page_or_subject_changed')
    return value


def run_observation(page, *, subject, observer_request, guard, output_directory):
    """Drive resources -> arm -> one reload -> wait -> snapshot/stop/save.

    ``page`` is an existing FanqieManagedPage or tab-fenced Page RPC. No session
    construction/closure occurs. Re-entry reads final bindings only; an
    interrupted START requires separate operator review, not another reload.
    """
    subject = validate_subject(subject)
    request = validate_request(observer_request, subject)
    if not callable(guard):
        raise ValueError('diagnostic_managed_guard_required')
    directory = Path(output_directory).resolve()
    if not directory.is_relative_to(ROOT / 'data'):
        raise ValueError('diagnostic_project_data_directory_required')
    if (directory / 'RESULT.json').exists():
        return _cached(directory, observer_request, subject)
    if (directory / 'START.json').exists():
        start = json.loads((directory / 'START.json').read_bytes())
        if start.get('request') != observer_request or start.get('subject') != subject:
            raise ValueError('diagnostic_interrupted_subject_changed')
        return {'schema': VERSION, 'status': 'outcome_unknown', 'request': observer_request,
                'subject': subject, 'automatic_retry': False,
                'reason': 'original_diagnostic_start_preserved',
                'promotion_contract_verified': False}
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise ValueError('diagnostic_new_output_directory_required')
    evidence = {}
    evidence['start'] = _save(directory / 'START.json', {'schema': VERSION,
        'request': observer_request, 'subject': subject, 'started_at': time.time(),
        'automatic_retry': False, 'max_same_page_reload': 1,
        'api_requests_issued_by_helper': 0, 'business_write_allowed': False})
    rpc = getattr(page, 'page', page)
    armed, stopped, reloaded = False, False, False
    stage, error_type, status = 'resources', None, 'incomplete'
    snapshots, worker_page_id = None, None
    def checked_guard():
        validate_request(observer_request, subject)
        guard()
    try:
        checked_guard()
        current_url = page.url
        location = _location(current_url)
        inventory = rpc.fanqie_promotion_observer('resources')
        if inventory.get('page_location') != location:
            raise ValueError('diagnostic_inventory_page_changed')
        evidence['resources'] = _save(directory / 'RESOURCE_PATHS.json', inventory)
        paths = {r['path'] for r in inventory.get('resources', [])}
        if not set(request['endpoint_paths']) <= paths:
            raise ValueError('diagnostic_selected_endpoint_not_currently_observed')
        stage = 'arm'; checked_guard()
        armed_result = rpc.fanqie_promotion_observer('arm', subject=subject,
                                                   endpoint_paths=request['endpoint_paths'])
        armed = True
        _check_observation(armed_result, subject, request['endpoint_paths'])
        worker_page_id = armed_result['worker_page_id']
        evidence['armed'] = save_observation(directory / 'ARMED.json', armed_result)
        stage = 'reload'; checked_guard()
        evidence['reload_started'] = _save(directory / 'RELOAD_STARTED.json',
            {'page_location': location, 'attempt': 1, 'timeout_ms': 5000,
             'same_existing_page': True, 'at': time.time()})
        reloaded = True
        rpc.goto(current_url, wait_until='domcontentloaded', timeout=5000)
        stage = 'wait'; checked_guard()
        rpc.wait_for_timeout(request['wait_ms'])
        stage = 'snapshot'; checked_guard()
        snapshots = _check_observation(rpc.fanqie_promotion_observer('snapshot', subject=subject),
            subject, request['endpoint_paths'], worker_page_id)
        evidence['observation'] = save_observation(directory / 'OBSERVATION.json', snapshots)
        status = 'observed' if snapshots.get('captures') else 'incomplete'
    except Exception as exc:
        error_type = type(exc).__name__
        evidence['error'] = _save(directory / 'ERROR.json',
            {'stage': stage, 'error_type': error_type, 'automatic_retry': False,
             'native_error_message_saved': False})
        status = 'error'
    finally:
        if armed:
            try:
                checked_guard()
                stop = _check_observation(rpc.fanqie_promotion_observer('stop', subject=subject),
                    subject, request['endpoint_paths'], worker_page_id)
                evidence['stopped'] = save_observation(directory / 'STOPPED.json', stop)
                stopped = stop.get('active') is False
            except Exception as exc:
                evidence['stop_error'] = _save(directory / 'STOP_ERROR.json',
                    {'error_type': type(exc).__name__, 'stop_confirmed': False,
                     'native_error_message_saved': False})
                status = 'error'
    result = {'schema': VERSION, 'status': status, 'request': observer_request,
        'subject': subject, 'evidence': evidence, 'same_page_reload_attempts': int(reloaded),
        'observer_stop_confirmed': stopped, 'error_type': error_type,
        'captures': len(snapshots.get('captures', [])) if snapshots else 0,
        'native_requests_issued_by_helper': 0, 'platform_submissions': 0,
        'native_body_saved': False, 'native_body_sha256': None,
        'promotion_contract_verified': False, 'automatic_retry': False,
        'limitations': ['Sanitized observation, not native complete response evidence or business contract.',
            'Observer field/size limits mean missing values do not prove platform concepts absent.',
            'Managed owner identity authenticity is supplied by the caller guard.']}
    _save(directory / 'RESULT.json', result)
    return result
