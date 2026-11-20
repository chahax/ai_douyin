"""One explicit 26->27 publication after an exact known pre-submission upload failure."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from . import publication_two_run_authorization as quota
from .browser_control import BrowserControlStore

APPROVAL_SHA256 = '1abadd49594b71ecaba4c9a22c6023864fdcc7c7b71aad2311dec8830bff691a'
PREVIOUS_COMMAND_ID = '6730f85e9f9b45bc9c0520f2e23c5cd3'
PUBLISH_KEY = 'user-fast-upload-publication-retry-20261019:approved-h3-publication'
AUTH_SCHEMA = 'publication_fast_upload_retry_user_authorization/20261019/v1'


def _command_snapshot(value):
    value = dict(value)
    if 'task_id' not in value:
        value['task_id'] = value.get('command_id')
    return value


def validate_fast_upload_authorization(reference, *, require_registered=True, allow_expired=False):
    value, reference = quota._load_reference(reference)
    required = {'schema', 'scope', 'utc_day', 'account_uuid', 'account_key', 'baseline_daily_runs',
        'max_daily_runs', 'active_control_revision', 'video', 'prepared', 'idempotency_keys',
        'user_statement', 'user_authorization'}
    if (set(value) != required or value.get('schema') != quota.SCHEMA_V4
            or value.get('scope') != 'publish_only' or value.get('utc_day') != '2026-10-19'
            or (not allow_expired and value['utc_day'] != datetime.now(timezone.utc).date().isoformat())
            or type(value.get('baseline_daily_runs')) is not int or value['baseline_daily_runs'] != 26
            or type(value.get('max_daily_runs')) is not int or value['max_daily_runs'] != 27
            or type(value.get('active_control_revision')) is not int or value['active_control_revision'] != 42
            or value.get('idempotency_keys') != {'publish': PUBLISH_KEY}
            or not isinstance(value.get('user_authorization'), dict)
            or value.get('user_authorization', {}).get('sha256') != APPROVAL_SHA256):
        quota._reject()
    if require_registered:
        try:
            registered = json.loads(quota.REGISTRY_V4.read_bytes())
        except (OSError, ValueError, TypeError):
            quota._reject()
        if registered != reference:
            quota._reject()
    approval, _ = quota._load_reference(value['user_authorization'])
    if (approval.get('schema') != AUTH_SCHEMA or approval.get('decision_source') != 'explicit_user_statement'
            or approval.get('user_statement') != '允许' or not approval.get('approval_question')
            or approval.get('deployment_authorized') is not True
            or approval.get('additional_publication_runs') != 1 or type(approval['additional_publication_runs']) is not int
            or approval.get('additional_recovery_runs') != 0 or type(approval['additional_recovery_runs']) is not int
            or approval.get('new_media_authorized') is not False or approval.get('retain_original_history') is not True
            or approval.get('previous_command_id') != PREVIOUS_COMMAND_ID
            or any(value[k] != approval.get(k) for k in ('account_uuid', 'account_key', 'video', 'prepared',
                'utc_day', 'baseline_daily_runs', 'max_daily_runs', 'active_control_revision', 'user_statement'))):
        quota._reject()
    previous = quota.validate_authorization(approval['previous_authorization'], allow_expired=allow_expired)
    if (previous['schema'] != quota.SCHEMA_V3
            or any(value[k] != previous[k] for k in ('account_uuid', 'account_key', 'video', 'prepared'))):
        quota._reject()
    # Also forbid reusing any earlier publish or recovery key without modifying any registry.
    for registry in (quota.REGISTRY, quota.REGISTRY_V2, quota.REGISTRY_V3):
        older, _ = quota._load_reference(json.loads(registry.read_bytes()))
        if PUBLISH_KEY in older['idempotency_keys'].values():
            quota._reject()
    before, _ = quota._load_reference(approval['previous_command'])
    final, _ = quota._load_reference(approval['previous_final_state'])
    db = sqlite3.connect((quota.ROOT / 'data/account_browser_control.db').resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    try:
        current = BrowserControlStore._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',
            (PREVIOUS_COMMAND_ID,)).fetchone())
    finally:
        db.close()
    if (current != before or before.get('command_id') != PREVIOUS_COMMAND_ID
            or before.get('task_id') != PREVIOUS_COMMAND_ID or before.get('kind') != 'publish'
            or before.get('state') != 'failed' or before.get('account_id') != value['account_uuid']
            or before.get('idempotency_key') != previous['idempotency_keys']['publish']
            or before['payload'].get('quota_authorization') != approval['previous_authorization']
            or before['payload'].get('account_key') != value['account_key']
            or before['payload'].get('account_uuid') != value['account_uuid']
            or before.get('result', {}).get('status') != 'upload_failed'
            or before['result'].get('success') is not False
            or before['result'].get('post_id') or before['result'].get('publish_url')
            or _command_snapshot(final.get('original_command', {})) != before
            or final.get('new_submission_lock_exists') is not False
            or final.get('control', {}).get('state') != 'active' or final['control'].get('revision') != 42
            or final.get('runtime', {}).get('daily_runs') != 26 or final['runtime'].get('day_key') != value['utc_day']
            or final['runtime'].get('lock_owner') or final['runtime'].get('lock_expires_at')):
        quota._reject()
    quota.validate_publication_payload(value, before['payload'])
    journal_path, data, _ = quota._read(approval['previous_journal']['path'], approval['previous_journal']['sha256'])
    runs = (quota.ROOT / 'data/publish_runs').resolve()
    rows = [json.loads(line) for line in data.decode('utf-8').splitlines() if line.strip()]
    if (journal_path.parent != runs or not rows or rows[0].get('stage') != 'prepared'
            or rows[-1].get('stage') != 'upload_failed'
            or any(row.get('stage', '').startswith('submission_') or row.get('stage') == 'published' for row in rows)
            or (quota.ROOT / final.get('journal', '')).resolve() != journal_path):
        quota._reject()
    first = rows[0]
    key = hashlib.sha256(json.dumps({'platform_identity_key': first.get('platform_identity_key'),
        'video_sha256': value['video']['sha256']}, sort_keys=True).encode()).hexdigest()
    legacy = hashlib.sha256(json.dumps({'account': value['account_key'],
        'video_sha256': value['video']['sha256']}, sort_keys=True).encode()).hexdigest()
    if (not first.get('platform_identity_key') or not journal_path.name.startswith(key + '.')
            or first.get('account_uuid') != value['account_uuid'] or first.get('account') != value['account_key']
            or first.get('video_sha256') != value['video']['sha256'] or first.get('video_path') != value['video']['path']
            or first.get('title') != before['payload']['request']['title']
            or not before['created_at'] <= datetime.fromisoformat(first['at_bjt']).timestamp() <= before['updated_at']
            or rows[-1].get('post_id') or rows[-1].get('publish_url')
            or (runs / (key + '.submitted.json')).exists() or (runs / (legacy + '.submitted.json')).exists()):
        quota._reject()
    return value


def build_fast_upload_authorization(user_authorization):
    """Build frozen JSON only. Registration uses the existing exclusive registry API."""
    approval, user_authorization = quota._load_reference(user_authorization)
    return {'schema': quota.SCHEMA_V4, 'scope': 'publish_only',
        **{key: approval[key] for key in ('utc_day', 'account_uuid', 'account_key', 'video', 'prepared',
            'baseline_daily_runs', 'max_daily_runs', 'active_control_revision', 'user_statement')},
        'idempotency_keys': {'publish': PUBLISH_KEY}, 'user_authorization': user_authorization}
