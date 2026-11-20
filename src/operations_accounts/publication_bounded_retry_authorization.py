"""Three fixed, sequential publication slots; no retry after uncertainty or human gates."""
from datetime import datetime, timezone
import hashlib
import json
import os
import sqlite3

from . import publication_two_run_authorization as quota
from .browser_control import BrowserControlStore, _json

APPROVAL_SHA256 = 'c9fc63c22e39b70f4ee015a24cc2802664aef39f349ad55842122510c1fb91c1'
PREVIOUS_COMMAND_ID = '64c924271976403bb0f1e5921db446f3'
PUBLISH_KEYS = [f'user-bounded-publication-retry-20261019:slot{i}' for i in (1, 2, 3)]
AUTH_SCHEMA = 'publication_bounded_retry_user_authorization/20261019/v1'
PROOF_SCHEMA = 'publication_bounded_retry_continuation/20261019/v1'


def _read_command(command_id):
    db = sqlite3.connect((quota.ROOT / 'data/account_browser_control.db').resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    try:
        return BrowserControlStore._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (command_id,)).fetchone())
    finally:
        db.close()


def _json_file(path):
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError, TypeError):
        quota._reject()


def _known_failure(value, command_ref, journal_ref, *, previous_key, previous_authorization, previous_index=None):
    before, _ = quota._load_reference(command_ref)
    result = before.get('result') or {}
    payload = before.get('payload') or {}
    if (before != _read_command(before.get('command_id')) or before.get('task_id') != before.get('command_id')
            or before.get('kind') != 'publish' or before.get('state') != 'failed'
            or before.get('account_id') != value['account_uuid'] or result.get('success') is not False
            or result.get('post_id') or result.get('publish_url')
            or before.get('idempotency_key') != previous_key
            or payload.get('quota_authorization') != previous_authorization
            or payload.get('quota_attempt_index') != previous_index
            or payload.get('account_uuid') != value['account_uuid'] or payload.get('account_key') != value['account_key']):
        quota._reject()
    quota.validate_publication_payload(value, payload)
    path, data, _ = quota._read(journal_ref['path'], journal_ref['sha256'])
    rows = [json.loads(line) for line in data.decode('utf-8').splitlines() if line.strip()]
    if not rows or rows[0].get('stage') != 'prepared':
        quota._reject()
    # Only native codes/flags are inspected, never guessed from arbitrary prose.
    blocked = ('unknown', 'human_required', 'captcha', 'login_required', 'login_expired', 'identity_mismatch', 'identity_unavailable')
    for item in [result, {'error_code': before.get('error_code')}, *rows]:
        if (item.get('human_required') or item.get('outcome_unknown') or item.get('post_id') or item.get('publish_url')
                or any(any(word in str(item.get(field, '')).lower() for word in blocked)
                    for field in ('stage', 'status', 'error_code', 'error_type'))
                or str(item.get('stage', '')).startswith('submission_') or item.get('stage') == 'published'):
            quota._reject()
    status, last = result.get('status'), rows[-1]
    known = status in {'upload_failed', 'ai_declaration_unverified', 'fiction_declaration_unverified'} and last.get('stage') == status
    hashtag_error = (status == 'error' and last.get('stage') == 'failed' and last.get('error_type') == 'HashtagReadbackError'
        and any(r.get('stage') == 'hashtags_readback' and r.get('phase') == 'failed' for r in rows))
    if not (known or hashtag_error):
        quota._reject()
    first = rows[0]
    runs = (quota.ROOT / 'data/publish_runs').resolve()
    key = hashlib.sha256(json.dumps({'platform_identity_key': first.get('platform_identity_key'),
        'video_sha256': value['video']['sha256']}, sort_keys=True).encode()).hexdigest()
    legacy = hashlib.sha256(json.dumps({'account': value['account_key'],
        'video_sha256': value['video']['sha256']}, sort_keys=True).encode()).hexdigest()
    if (path.parent != runs or not first.get('platform_identity_key') or not path.name.startswith(key + '.')
            or first.get('account') != value['account_key'] or first.get('account_uuid') != value['account_uuid']
            or first.get('video_sha256') != value['video']['sha256'] or first.get('video_path') != value['video']['path']
            or first.get('title') != payload['request']['title']
            or not before['created_at'] <= datetime.fromisoformat(first['at_bjt']).timestamp() <= before['updated_at']
            or (runs / (key + '.submitted.json')).exists() or (runs / (legacy + '.submitted.json')).exists()):
        quota._reject()
    return before, first


def validate_bounded_authorization(reference, *, require_registered=True, allow_expired=False):
    value, reference = quota._load_reference(reference)
    required = {'schema', 'scope', 'utc_day', 'account_uuid', 'account_key', 'baseline_daily_runs', 'max_daily_runs',
        'active_control_revision', 'video', 'prepared', 'idempotency_keys', 'user_statement', 'user_authorization'}
    if (set(value) != required or value.get('schema') != quota.SCHEMA_V5 or value.get('scope') != 'publish_only'
            or value.get('utc_day') != '2026-10-19'
            or (not allow_expired and value['utc_day'] != datetime.now(timezone.utc).date().isoformat())
            or type(value.get('baseline_daily_runs')) is not int or value['baseline_daily_runs'] != 27
            or type(value.get('max_daily_runs')) is not int or value['max_daily_runs'] != 30
            or type(value.get('active_control_revision')) is not int or value['active_control_revision'] != 42
            or value.get('idempotency_keys') != {'publish': PUBLISH_KEYS}
            or not isinstance(value.get('user_authorization'), dict)
            or value['user_authorization'].get('sha256') != APPROVAL_SHA256):
        quota._reject()
    if require_registered and _json_file(quota.REGISTRY_V5) != reference:
        quota._reject()
    approval, _ = quota._load_reference(value['user_authorization'])
    if (approval.get('schema') != AUTH_SCHEMA or approval.get('decision_source') != 'explicit_user_statement'
            or approval.get('user_statement') != '可以' or not approval.get('approval_question')
            or approval.get('deployment_authorized') is not True or approval.get('additional_publication_runs') != 3
            or type(approval['additional_publication_runs']) is not int
            or approval.get('additional_recovery_runs') != 0 or type(approval['additional_recovery_runs']) is not int
            or approval.get('new_media_authorized') is not False or approval.get('retain_original_history') is not True
            or any(approval.get(k) is not True for k in ('only_known_pre_submission_failures', 'stop_on_unknown', 'stop_on_human_required'))
            or approval.get('previous_command_id') != PREVIOUS_COMMAND_ID
            or any(value[k] != approval.get(k) for k in ('account_uuid', 'account_key', 'video', 'prepared', 'utc_day',
                'baseline_daily_runs', 'max_daily_runs', 'active_control_revision', 'user_statement'))):
        quota._reject()
    previous = quota.validate_authorization(approval['previous_authorization'], allow_expired=allow_expired)
    if (previous['schema'] != quota.SCHEMA_V4
            or any(value[k] != previous[k] for k in ('account_uuid', 'account_key', 'video', 'prepared'))):
        quota._reject()
    for registry in (quota.REGISTRY, quota.REGISTRY_V2, quota.REGISTRY_V3, quota.REGISTRY_V4):
        older, _ = quota._load_reference(_json_file(registry))
        old_keys = older['idempotency_keys'].values()
        if set(PUBLISH_KEYS) & set(old_keys):
            quota._reject()
    before, first = _known_failure(value, approval['previous_command'], approval['previous_journal'],
        previous_key=previous['idempotency_keys']['publish'], previous_authorization=approval['previous_authorization'])
    final, _ = quota._load_reference(approval['previous_final_state'])
    original = dict(final.get('original_command') or {})
    original.setdefault('task_id', original.get('command_id'))
    if (before['command_id'] != PREVIOUS_COMMAND_ID or original != before or final.get('new_submission_lock_exists') is not False
            or (quota.ROOT / final.get('journal', '')).resolve() != quota._read(approval['previous_journal']['path'])[0]
            or final.get('control', {}).get('state') != 'active' or final['control'].get('revision') != 42
            or final.get('runtime', {}).get('daily_runs') != 27 or final['runtime'].get('day_key') != value['utc_day']
            or final['runtime'].get('lock_owner') or final['runtime'].get('lock_expires_at')):
        quota._reject()
    return value


def build_bounded_authorization(user_authorization):
    approval, user_authorization = quota._load_reference(user_authorization)
    return {'schema': quota.SCHEMA_V5, 'scope': 'publish_only',
        **{k: approval[k] for k in ('utc_day', 'account_uuid', 'account_key', 'video', 'prepared',
            'baseline_daily_runs', 'max_daily_runs', 'active_control_revision', 'user_statement')},
        'idempotency_keys': {'publish': list(PUBLISH_KEYS)}, 'user_authorization': user_authorization}


def _continuation_path(index, suffix):
    return quota.REGISTRY_V5.parent / f'publication_bounded_retry_20261019.slot{index}.{suffix}.json'


def _validate_attempt(value, reference, index):
    if type(index) is not int or index not in (1, 2, 3):
        quota._reject()
    approval, _ = quota._load_reference(value['user_authorization'])
    initial, _ = quota._load_reference(approval['previous_command'])
    for slot in range(2, index + 1):
        proof_ref = _json_file(_continuation_path(slot, 'ref'))
        proof, canonical = quota._load_reference(proof_ref)
        if (proof_ref != canonical or set(proof) != {'schema', 'parent', 'attempt_index', 'previous_command', 'previous_journal'}
                or proof['schema'] != PROOF_SCHEMA or proof['parent'] != reference or type(proof['attempt_index']) is not int
                or proof['attempt_index'] != slot):
            quota._reject()
        before, first = _known_failure(value, proof['previous_command'], proof['previous_journal'],
            previous_key=PUBLISH_KEYS[slot - 2], previous_authorization=reference, previous_index=slot - 1)
        initial_journal, data, _ = quota._read(approval['previous_journal']['path'], approval['previous_journal']['sha256'])
        original_identity = json.loads(data.decode('utf-8').splitlines()[0])['platform_identity_key']
        if before['binding_version'] != initial['binding_version'] or first['platform_identity_key'] != original_identity:
            quota._reject()
    return 27 + index


def validate_attempt(reference, index):
    value = quota.validate_authorization(reference)
    if value['schema'] != quota.SCHEMA_V5:
        quota._reject()
    return _validate_attempt(value, reference, index)


def _exclusive_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _json(value)
    try:
        with path.open('x', encoding='utf-8') as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if path.read_text(encoding='utf-8') != body:
            quota._reject()
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def register_continuation(parent_reference, index, *, previous_command_snapshot, previous_journal):
    """Only after a native known failure; proof and its reference are never replaced."""
    value = quota.validate_authorization(parent_reference)
    if type(index) is not int or index not in (2, 3) or value['schema'] != quota.SCHEMA_V5:
        quota._reject()
    _validate_attempt(value, parent_reference, index - 1)
    before, first = _known_failure(value, previous_command_snapshot, previous_journal,
        previous_key=PUBLISH_KEYS[index - 2], previous_authorization=parent_reference, previous_index=index - 1)
    approval, _ = quota._load_reference(value['user_authorization'])
    initial, _ = quota._load_reference(approval['previous_command'])
    _, data, _ = quota._read(approval['previous_journal']['path'], approval['previous_journal']['sha256'])
    if before['binding_version'] != initial['binding_version'] or first['platform_identity_key'] != json.loads(data.decode('utf-8').splitlines()[0])['platform_identity_key']:
        quota._reject()
    proof = {'schema': PROOF_SCHEMA, 'parent': parent_reference, 'attempt_index': index,
        'previous_command': previous_command_snapshot, 'previous_journal': previous_journal}
    proof_ref = _exclusive_json(_continuation_path(index, 'proof'), proof)
    _exclusive_json(_continuation_path(index, 'ref'), proof_ref)
    return proof_ref
