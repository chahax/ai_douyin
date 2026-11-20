"""One newly requested monitored publication, preserving the exhausted three-slot grant."""
from datetime import datetime, timezone
import hashlib
import json

from . import publication_two_run_authorization as quota
from . import publication_bounded_retry_authorization as bounded

APPROVAL_SHA256 = '1b9e91a9b83cebe7e186fcc7e6c964be1380b89b714104c997adba4639d124bd'
PREVIOUS_COMMAND_ID = '06b4c87f6a4343578774748c9a3b852d'
PUBLISH_KEY = 'user-monitored-publication-resume-20261019:approved-h3-publication'
AUTH_SCHEMA = 'publication_monitored_resume_user_authorization/20261019/v1'


def validate_monitored_authorization(reference, *, require_registered=True, allow_expired=False):
    value, reference = quota._load_reference(reference)
    fields = {'schema', 'scope', 'utc_day', 'account_uuid', 'account_key', 'baseline_daily_runs', 'max_daily_runs',
        'active_control_revision', 'video', 'prepared', 'idempotency_keys', 'user_statement', 'scope_interpretation', 'user_authorization'}
    if (set(value) != fields or value.get('schema') != quota.SCHEMA_V6 or value.get('scope') != 'publish_only'
            or value.get('utc_day') != '2026-10-19'
            or (not allow_expired and value['utc_day'] != datetime.now(timezone.utc).date().isoformat())
            or type(value.get('baseline_daily_runs')) is not int or value['baseline_daily_runs'] != 30
            or type(value.get('max_daily_runs')) is not int or value['max_daily_runs'] != 31
            or type(value.get('active_control_revision')) is not int or value['active_control_revision'] != 42
            or value.get('idempotency_keys') != {'publish': PUBLISH_KEY}
            or not isinstance(value.get('user_authorization'), dict)
            or value['user_authorization'].get('sha256') != APPROVAL_SHA256):
        quota._reject()
    if require_registered and bounded._json_file(quota.REGISTRY_V6) != reference:
        quota._reject()
    approval, _ = quota._load_reference(value['user_authorization'])
    if (approval.get('schema') != AUTH_SCHEMA or approval.get('decision_source') != 'explicit_user_statement'
            or not approval.get('user_statement') or not approval.get('clarification_question')
            or approval.get('clarification_answer') != '视频的自动发布流程' or not approval.get('scope_interpretation')
            or approval.get('deployment_authorized') is not True
            or type(approval.get('additional_publication_runs')) is not int or approval['additional_publication_runs'] != 1
            or type(approval.get('additional_recovery_runs')) is not int or approval['additional_recovery_runs'] != 0
            or approval.get('new_media_authorized') is not False or approval.get('retain_original_history') is not True
            or approval.get('stop_on_unknown') is not True or approval.get('stop_on_human_required') is not True
            or approval.get('previous_command_id') != PREVIOUS_COMMAND_ID
            or any(value[k] != approval.get(k) for k in ('account_uuid', 'account_key', 'video', 'prepared', 'utc_day',
                'baseline_daily_runs', 'max_daily_runs', 'active_control_revision', 'user_statement', 'scope_interpretation'))):
        quota._reject()
    previous = quota.validate_authorization(approval['previous_authorization'], allow_expired=allow_expired)
    if (previous['schema'] != quota.SCHEMA_V5 or bounded._validate_attempt(previous, approval['previous_authorization'], 3) != 30
            or any(value[k] != previous[k] for k in ('account_uuid', 'account_key', 'video', 'prepared'))):
        quota._reject()
    for registry in (quota.REGISTRY, quota.REGISTRY_V2, quota.REGISTRY_V3, quota.REGISTRY_V4, quota.REGISTRY_V5):
        older, _ = quota._load_reference(bounded._json_file(registry))
        for key in older['idempotency_keys'].values():
            if PUBLISH_KEY == key or (isinstance(key, list) and PUBLISH_KEY in key):
                quota._reject()
    before, first = bounded._known_failure(value, approval['previous_command'], approval['previous_journal'],
        previous_key=previous['idempotency_keys']['publish'][2], previous_authorization=approval['previous_authorization'], previous_index=3)
    if before['command_id'] != PREVIOUS_COMMAND_ID or before['result']['status'] != 'ai_declaration_unverified':
        quota._reject()
    old_approval, _ = quota._load_reference(previous['user_authorization'])
    anchor, _ = quota._load_reference(old_approval['previous_command'])
    _, raw, _ = quota._read(old_approval['previous_journal']['path'], old_approval['previous_journal']['sha256'])
    anchor_identity = json.loads(raw.decode('utf-8').splitlines()[0])['platform_identity_key']
    if before['binding_version'] != anchor['binding_version'] or first['platform_identity_key'] != anchor_identity:
        quota._reject()
    final, _ = quota._load_reference(approval['previous_final_state'])
    original = dict(final.get('original_command') or {})
    original.setdefault('task_id', original.get('command_id'))
    expected_locks = []
    for identity in ({'platform_identity_key': first['platform_identity_key'], 'video_sha256': value['video']['sha256']},
            {'account': value['account_key'], 'video_sha256': value['video']['sha256']}):
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        expected_locks.append({'path': str((quota.ROOT / 'data/publish_runs' / (key + '.submitted.json')).resolve()), 'exists': False})
    commands = final.get('commands')
    if (original != before or final.get('journal') != approval['previous_journal']
            or final.get('runtime', {}).get('daily_runs') != 30 or final['runtime'].get('day_key') != value['utc_day']
            or final['runtime'].get('lock_owner') or final['runtime'].get('lock_expires_at')
            or final.get('control', {}).get('state') != 'active' or final['control'].get('revision') != 42
            or final.get('platform_submission_started') is not False or final.get('publication_completed') is not False
            or final.get('new_runs_used') != 3 or final.get('new_runs_remaining') != 0
            or final.get('submission_locks') != expected_locks
            or not isinstance(commands, list) or len(commands) != 3
            or {c.get('idempotency_key') for c in commands} != set(previous['idempotency_keys']['publish'])
            or any(c != bounded._read_command(c.get('command_id')) for c in commands)):
        quota._reject()
    return value


def build_monitored_authorization(user_authorization):
    """Build JSON only; keep the actual user text and its conservative scope interpretation."""
    approval, user_authorization = quota._load_reference(user_authorization)
    return {'schema': quota.SCHEMA_V6, 'scope': 'publish_only',
        **{k: approval[k] for k in ('utc_day', 'account_uuid', 'account_key', 'video', 'prepared', 'baseline_daily_runs',
            'max_daily_runs', 'active_control_revision', 'user_statement', 'scope_interpretation')},
        'idempotency_keys': {'publish': PUBLISH_KEY}, 'user_authorization': user_authorization}
