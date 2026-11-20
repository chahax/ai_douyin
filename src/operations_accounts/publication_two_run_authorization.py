"""One frozen, explicitly registered publication exception; default limits stay 20."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from .browser_control import BrowserControlRejected

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / 'data/account_browser_control_authorizations/publication_two_run_20261019.ref.json'
SCHEMA = 'publication_two_run_exception/20261019/v1'
REGISTRY_V2 = ROOT / 'data/account_browser_control_authorizations/publication_two_run_20261019.v2.ref.json'
SCHEMA_V2 = 'publication_two_run_exception/20261019/v2'
REGISTRY_V3 = ROOT / 'data/account_browser_control_authorizations/publication_single_retry_20261019.v3.ref.json'
SCHEMA_V3 = 'publication_single_retry/20261019/v3'
REGISTRY_V4 = ROOT / 'data/account_browser_control_authorizations/publication_fast_upload_retry_20261019.v4.ref.json'
SCHEMA_V4 = 'publication_fast_upload_retry/20261019/v4'
REGISTRY_V5 = ROOT / 'data/account_browser_control_authorizations/publication_bounded_retry_20261019.v5.ref.json'
SCHEMA_V5 = 'publication_bounded_retry/20261019/v5'
REGISTRY_V6 = ROOT / 'data/account_browser_control_authorizations/publication_monitored_resume_20261019.v6.ref.json'
SCHEMA_V6 = 'publication_monitored_resume/20261019/v6'
REGISTRY_V7 = ROOT / 'data/account_browser_control_authorizations/publication_scoped_popup_retry_20261019.v7.ref.json'
SCHEMA_V7 = 'publication_scoped_popup_retry/20261019/v7'
REGISTRY_V8 = ROOT / 'data/account_browser_control_authorizations/publication_native_scroll_retry_20261019.v8.ref.json'
SCHEMA_V8 = 'publication_native_scroll_retry/20261019/v8'


def _reject():
    raise BrowserControlRejected('quota_authorization_invalid', '本次两次运行授权、原文件或控制版本不匹配，未扩大原配额。')


def _registry_for(schema):
    if schema == SCHEMA:
        return REGISTRY
    if schema == SCHEMA_V2:
        return REGISTRY_V2
    if schema == SCHEMA_V3:
        return REGISTRY_V3
    if schema == SCHEMA_V4:
        return REGISTRY_V4
    if schema == SCHEMA_V5:
        return REGISTRY_V5
    if schema == SCHEMA_V6:
        return REGISTRY_V6
    if schema == SCHEMA_V7:
        return REGISTRY_V7
    if schema == SCHEMA_V8:
        return REGISTRY_V8
    _reject()


def _read(path, expected_sha=None):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
        _reject()
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if expected_sha is not None and sha != expected_sha:
        _reject()
    return path, data, sha


def _load_reference(reference):
    if not isinstance(reference, dict) or set(reference) != {'path', 'sha256'}:
        _reject()
    if (not isinstance(reference['path'], str) or not isinstance(reference['sha256'], str)
            or len(reference['sha256']) != 64
            or any(char not in '0123456789abcdef' for char in reference['sha256'])):
        _reject()
    try:
        path, data, sha = _read(reference['path'], reference['sha256'])
        value = json.loads(data)
        if not isinstance(value, dict):
            _reject()
        return value, {'path': str(path), 'sha256': sha}
    except (OSError, ValueError, TypeError):
        _reject()


def validate_authorization(reference, *, require_registered=True, allow_expired=False):
    value, reference = _load_reference(reference)
    if value.get('schema') == SCHEMA_V8:
        from .publication_native_scroll_authorization import validate_native_scroll_authorization
        return validate_native_scroll_authorization(reference, require_registered=require_registered,
            allow_expired=allow_expired)
    if value.get('schema') == SCHEMA_V7:
        from .publication_scoped_popup_authorization import validate_scoped_popup_authorization
        return validate_scoped_popup_authorization(reference, require_registered=require_registered,
            allow_expired=allow_expired)
    if value.get('schema') == SCHEMA_V6:
        from .publication_monitored_resume_authorization import validate_monitored_authorization
        return validate_monitored_authorization(reference, require_registered=require_registered,
            allow_expired=allow_expired)
    if value.get('schema') == SCHEMA_V5:
        from .publication_bounded_retry_authorization import validate_bounded_authorization
        return validate_bounded_authorization(reference, require_registered=require_registered,
            allow_expired=allow_expired)
    if value.get('schema') == SCHEMA_V4:
        from .publication_fast_upload_authorization import validate_fast_upload_authorization
        return validate_fast_upload_authorization(reference, require_registered=require_registered,
            allow_expired=allow_expired)
    registry = _registry_for(value.get('schema'))
    second = value.get('schema') == SCHEMA_V2
    third = value.get('schema') == SCHEMA_V3
    if require_registered:
        try:
            registered = json.loads(registry.read_bytes())
        except (OSError, ValueError, TypeError):
            _reject()
        if registered != reference:
            _reject()
    required = {'schema', 'utc_day', 'account_uuid', 'account_key', 'baseline_daily_runs',
        'max_daily_runs', 'video', 'prepared', 'idempotency_keys',
        'recovery_control_revision', 'user_statement'}
    if third:
        required.remove('recovery_control_revision')
        required.update({'active_control_revision', 'scope', 'closure_authorization', 'archive_receipt'})
    elif not second:
        required.add('cancel_manual_command_id')
    if (set(value) != required
            or value.get('utc_day') != '2026-10-19'
            or (not allow_expired and value.get('utc_day') != datetime.now(timezone.utc).date().isoformat())
            or type(value.get('baseline_daily_runs')) is not int or value['baseline_daily_runs'] != (25 if third else 23 if second else 20)
            or type(value.get('max_daily_runs')) is not int or value['max_daily_runs'] != (26 if third else 25 if second else 22)
            or (not third and (type(value.get('recovery_control_revision')) is not int or value['recovery_control_revision'] <= 0))
            or (second and value['recovery_control_revision'] != 41)
            or (third and (type(value.get('active_control_revision')) is not int
                or value['active_control_revision'] != 42 or value.get('scope') != 'publish_only'))
            or not all(isinstance(value.get(k), str) and value[k].strip()
                for k in (('account_uuid', 'account_key', 'user_statement') if second or third else
                    ('account_uuid', 'account_key', 'cancel_manual_command_id', 'user_statement')))):
        _reject()
    keys = value.get('idempotency_keys')
    if (not isinstance(keys, dict) or set(keys) != ({'publish'} if third else {'recovery', 'publish'})
            or not all(isinstance(k, str) and 0 < len(k) <= 200 for k in keys.values())
            or (not third and keys['recovery'] == keys['publish'])):
        _reject()
    prepared, prepared_ref = _load_reference(value['prepared'])
    if (prepared_ref != value['prepared']
            or prepared.get('decision_source') != 'explicit_user_statement'
            or prepared.get('full_film_accepted_for_publication') is not True
            or not prepared.get('user_statement') or prepared.get('ai_generated') is not True
            or prepared.get('fictional_story') is not True
            or prepared.get('account_uuid') != value['account_uuid']
            or prepared.get('account_key') != value['account_key']
            or prepared.get('video') != value['video']):
        _reject()
    video = value['video']
    if not isinstance(video, dict) or set(video) != {'path', 'sha256'}:
        _reject()
    try:
        video_path, _, _ = _read(video['path'], video['sha256'])
        if str(video_path) != video['path']:
            _reject()
    except (OSError, ValueError, TypeError):
        _reject()
    if second or third:
        # The second human exception cannot become a new account, film or
        # authorization chain, and does not replace the first registry.
        try:
            previous_ref = json.loads((REGISTRY_V2 if third else REGISTRY).read_bytes())
        except (OSError, ValueError, TypeError):
            _reject()
        previous_value, _ = _load_reference(previous_ref)
        if previous_value.get('schema') != (SCHEMA_V2 if third else SCHEMA):
            _reject()
        previous = validate_authorization(previous_ref, allow_expired=allow_expired)
        if (any(value[name] != previous[name] for name in ('account_uuid', 'account_key', 'video', 'prepared'))
                or set(keys.values()) & set(previous['idempotency_keys'].values())):
            _reject()
    if third:
        first_ref = json.loads(REGISTRY.read_bytes())
        first = validate_authorization(first_ref, allow_expired=allow_expired)
        if keys['publish'] in first['idempotency_keys'].values():
            _reject()
        from .publication_unknown_closure import validate_archived_publication_retry
        approval = validate_archived_publication_retry(value['closure_authorization'], value['archive_receipt'])
        if (any(value[name] != approval.get(name) for name in ('account_uuid', 'account_key', 'video', 'prepared',
                'baseline_daily_runs', 'max_daily_runs', 'utc_day', 'active_control_revision', 'user_statement'))):
            _reject()
    return value


def build_single_publish_authorization(prepared_path, *, account_uuid, account_key, publish_key,
        user_statement, closure_authorization, archive_receipt):
    path, data, sha = _read(prepared_path)
    prepared = json.loads(data)
    return {'schema': SCHEMA_V3, 'scope': 'publish_only',
        'utc_day': datetime.now(timezone.utc).date().isoformat(),
        'account_uuid': account_uuid, 'account_key': account_key,
        'baseline_daily_runs': 25, 'max_daily_runs': 26, 'active_control_revision': 42,
        'video': prepared['video'], 'prepared': {'path': str(path), 'sha256': sha},
        'idempotency_keys': {'publish': publish_key}, 'user_statement': user_statement,
        'closure_authorization': dict(closure_authorization), 'archive_receipt': dict(archive_receipt)}


def build_authorization(prepared_path, *, account_uuid, account_key, recovery_key, publish_key,
                        recovery_control_revision, cancel_manual_command_id=None, user_statement, version=1):
    """Build JSON only; the human-authorized caller saves and registers it once."""
    path, data, sha = _read(prepared_path)
    prepared = json.loads(data)
    if type(version) is not int or version not in (1, 2) or (version == 2 and cancel_manual_command_id is not None):
        _reject()
    value = {'schema': SCHEMA_V2 if version == 2 else SCHEMA, 'utc_day': datetime.now(timezone.utc).date().isoformat(),
        'account_uuid': account_uuid, 'account_key': account_key,
        'baseline_daily_runs': 23 if version == 2 else 20,
        'max_daily_runs': 25 if version == 2 else 22, 'video': prepared['video'],
        'prepared': {'path': str(path), 'sha256': sha},
        'idempotency_keys': {'recovery': recovery_key, 'publish': publish_key},
        'recovery_control_revision': recovery_control_revision, 'user_statement': user_statement}
    if version == 1:
        value['cancel_manual_command_id'] = cancel_manual_command_id
    return value


def register_authorization(path, sha256):
    reference = {'path': str(Path(path).resolve()), 'sha256': sha256}
    value = validate_authorization(reference, require_registered=False)
    registry = _registry_for(value['schema'])
    registry.parent.mkdir(parents=True, exist_ok=True)
    try:
        with registry.open('x', encoding='utf-8') as handle:
            json.dump(reference, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            import os
            os.fsync(handle.fileno())
    except FileExistsError:
        if json.loads(registry.read_bytes()) != reference:
            _reject()
    return reference


def control_snapshot(account_uuid):
    """Only the original control row's state/revision, with no token exposure."""
    from src.scheduler.account_refresh import DB
    connection = sqlite3.connect(Path(DB).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute('SELECT account_uuid,account_key,state,revision FROM account_controls WHERE account_uuid=?',
            (account_uuid,)).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def registered_recovery(account_key, control=None):
    registry = REGISTRY_V2 if REGISTRY_V2.exists() else REGISTRY
    if not registry.exists():
        return None
    try:
        reference = json.loads(registry.read_bytes())
        value, reference = _load_reference(reference)
        if _registry_for(value.get('schema')) != registry:
            _reject()
    except (OSError, ValueError, TypeError):
        _reject()
    if value.get('account_key') != account_key:
        return None
    value = validate_authorization(reference, allow_expired=True)
    if control is None:
        control = control_snapshot(value['account_uuid'])
    if (value['utc_day'] != datetime.now(timezone.utc).date().isoformat()
            or not isinstance(control, dict) or control.get('state') != 'recovering'
            or control.get('revision') != value['recovery_control_revision']
            or control.get('account_uuid') != value['account_uuid']):
        return None
    return reference, value


def validate_publication_payload(value, payload):
    prepared, _ = _load_reference(value['prepared'])
    request = payload.get('request')
    if (not isinstance(request, dict)
            or payload.get('video_sha256') != value['video']['sha256']
            or not isinstance(payload.get('authorization'), dict)
            or payload['authorization'].get('path') != value['prepared']['path']
            or payload['authorization'].get('sha256') != value['prepared']['sha256']
            or request.get('video_path') != value['video']['path']
            or any(request.get(name) != prepared.get(name)
                for name in ('title', 'description', 'hashtags', 'visibility'))
            or request.get('ai_generated') is not True or request.get('fictional_story') is not True):
        _reject()


def authorized_daily_limit(ctx, operation, *, default=20, account_uuid=None, control=None):
    """Called both at admission and inside the original operation lease."""
    if ctx is None or default != 20:
        return default
    kind = ctx.command['kind']
    if (kind, operation) not in {('recovery', 'identity-recovery'), ('publish', 'publish')}:
        return default
    payload = ctx.command['payload']
    reference = payload.get('quota_authorization')
    if reference is None:
        return default
    value = validate_authorization(reference)
    if kind not in value['idempotency_keys']:
        _reject()
    limit = value['max_daily_runs']
    expected_key = value['idempotency_keys'][kind]
    if value['schema'] in {SCHEMA_V6, SCHEMA_V7, SCHEMA_V8} and 'quota_attempt_index' in payload:
        _reject()
    if value['schema'] == SCHEMA_V5:
        from .publication_bounded_retry_authorization import _validate_attempt
        index = payload.get('quota_attempt_index')
        limit = _validate_attempt(value, reference, index)
        expected_key = value['idempotency_keys']['publish'][index - 1]
    if (ctx.account_id != value['account_uuid'] or account_uuid != value['account_uuid']
            or payload.get('account_key') != value['account_key']
            or payload.get('account_uuid') != value['account_uuid']
            or ctx.command['idempotency_key'] != expected_key):
        _reject()
    expected_state = 'recovering' if kind == 'recovery' else 'active'
    expected_revision = (value['active_control_revision'] if value['schema'] in {SCHEMA_V3, SCHEMA_V4, SCHEMA_V5, SCHEMA_V6, SCHEMA_V7, SCHEMA_V8} else
        value['recovery_control_revision'] + (kind == 'publish'))
    if (not isinstance(control, dict) or control.get('state') != expected_state
            or control.get('account_uuid') != value['account_uuid']
            or control.get('account_key') != value['account_key']
            or control.get('revision') != expected_revision):
        _reject()
    if kind == 'recovery':
        if payload.get('identity_probe_only') is not True:
            _reject()
    else:
        validate_publication_payload(value, payload)
    return limit
