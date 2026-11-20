"""One explicitly added publication after the frozen scoped-popup repair."""
from datetime import datetime, timezone
import hashlib
import json

from . import publication_two_run_authorization as quota
from . import publication_bounded_retry_authorization as bounded

APPROVAL_SHA256 = '76bd7054d5d0fc6520755b22bf54ab9ce47e05c186bd08eeeac777ef7b9c21ed'
PREVIOUS_COMMAND_ID = '8fac1b26ff9e4d2e98bbf48bb42ed277'
PUBLISH_KEY = 'user-scoped-popup-publication-retry-20261019:approved-h3-publication'
AUTH_SCHEMA = 'publication_scoped_popup_retry_user_authorization/20261019/v1'
REPAIR_SHA256 = 'c93d80129b534b2dcae7638f869c55ae4f4e4c2e551f4e9eb97d8dc1509dfe28'
REPAIR_SNAPSHOT = 'data/development_checkpoints/ai_scoped_popup_20261019/final/src/platform_adapter/ai_content_declaration.py'


def validate_scoped_popup_authorization(reference, *, require_registered=True, allow_expired=False):
    value, reference = quota._load_reference(reference)
    fields = {'schema', 'scope', 'utc_day', 'account_uuid', 'account_key', 'baseline_daily_runs', 'max_daily_runs',
        'active_control_revision', 'video', 'prepared', 'idempotency_keys', 'user_statement', 'repair_source', 'user_authorization'}
    repair = {'path': str((quota.ROOT / 'src/platform_adapter/ai_content_declaration.py').resolve()), 'sha256': REPAIR_SHA256}
    if (set(value) != fields or value.get('schema') != quota.SCHEMA_V7 or value.get('scope') != 'publish_only'
            or value.get('utc_day') != '2026-10-19'
            or (not allow_expired and value['utc_day'] != datetime.now(timezone.utc).date().isoformat())
            or type(value.get('baseline_daily_runs')) is not int or value['baseline_daily_runs'] != 31
            or type(value.get('max_daily_runs')) is not int or value['max_daily_runs'] != 32
            or type(value.get('active_control_revision')) is not int or value['active_control_revision'] != 42
            or value.get('idempotency_keys') != {'publish': PUBLISH_KEY} or value.get('repair_source') != repair
            or not isinstance(value.get('user_authorization'), dict)
            or value['user_authorization'].get('sha256') != APPROVAL_SHA256):
        quota._reject()
    if require_registered and bounded._json_file(quota.REGISTRY_V7) != reference:
        quota._reject()
    quota._read(quota.ROOT / REPAIR_SNAPSHOT, REPAIR_SHA256)
    approval, _ = quota._load_reference(value['user_authorization'])
    if (approval.get('schema') != AUTH_SCHEMA or approval.get('decision_source') != 'explicit_user_statement'
            or approval.get('user_statement') != '追加' or not approval.get('approval_question')
            or approval.get('deployment_authorized') is not True
            or type(approval.get('additional_publication_runs')) is not int or approval['additional_publication_runs'] != 1
            or type(approval.get('additional_recovery_runs')) is not int or approval['additional_recovery_runs'] != 0
            or approval.get('new_media_authorized') is not False or approval.get('retain_original_history') is not True
            or approval.get('stop_on_unknown') is not True or approval.get('stop_on_human_required') is not True
            or approval.get('previous_command_id') != PREVIOUS_COMMAND_ID
            or any(value[k] != approval.get(k) for k in ('account_uuid', 'account_key', 'video', 'prepared', 'utc_day',
                'baseline_daily_runs', 'max_daily_runs', 'active_control_revision', 'user_statement', 'repair_source'))):
        quota._reject()
    previous = quota.validate_authorization(approval['previous_authorization'], allow_expired=allow_expired)
    if (previous['schema'] != quota.SCHEMA_V6
            or any(value[k] != previous[k] for k in ('account_uuid', 'account_key', 'video', 'prepared'))):
        quota._reject()
    for registry in (quota.REGISTRY, quota.REGISTRY_V2, quota.REGISTRY_V3, quota.REGISTRY_V4, quota.REGISTRY_V5, quota.REGISTRY_V6):
        older, _ = quota._load_reference(bounded._json_file(registry))
        for key in older['idempotency_keys'].values():
            if PUBLISH_KEY == key or (isinstance(key, list) and PUBLISH_KEY in key):
                quota._reject()
    before, first = bounded._known_failure(value, approval['previous_command'], approval['previous_journal'],
        previous_key=previous['idempotency_keys']['publish'], previous_authorization=approval['previous_authorization'], previous_index=None)
    if before['command_id'] != PREVIOUS_COMMAND_ID or before['result']['status'] != 'ai_declaration_unverified':
        quota._reject()
    old_approval, _ = quota._load_reference(previous['user_authorization'])
    anchor, _ = quota._load_reference(old_approval['previous_command'])
    _, raw, _ = quota._read(old_approval['previous_journal']['path'], old_approval['previous_journal']['sha256'])
    if (before['binding_version'] != anchor['binding_version']
            or first['platform_identity_key'] != json.loads(raw.decode('utf-8').splitlines()[0])['platform_identity_key']):
        quota._reject()
    final, _ = quota._load_reference(approval['previous_final_state'])
    original = dict(final.get('original_command') or {})
    original.setdefault('task_id', original.get('command_id'))
    locks = []
    for identity in ({'platform_identity_key': first['platform_identity_key'], 'video_sha256': value['video']['sha256']},
            {'account': value['account_key'], 'video_sha256': value['video']['sha256']}):
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        locks.append({'path': str((quota.ROOT / 'data/publish_runs' / (key + '.submitted.json')).resolve()), 'exists': False})
    if (original != before or final.get('journal') != approval['previous_journal']
            or final.get('runtime', {}).get('daily_runs') != 31 or final['runtime'].get('day_key') != value['utc_day']
            or final['runtime'].get('lock_owner') or final['runtime'].get('lock_expires_at')
            or final.get('control', {}).get('state') != 'active' or final['control'].get('revision') != 42
            or final.get('platform_submission_started') is not False or final.get('publication_completed') is not False
            or final.get('new_runs_used') != 1 or final.get('new_runs_remaining') != 0
            or final.get('submission_locks') != locks or final.get('offline_helper_sha256') != REPAIR_SHA256
            or final.get('no_second_run_dispatched') is not True):
        quota._reject()
    return value


def build_scoped_popup_authorization(user_authorization):
    """Build only; verify the current repair once, retain frozen identity for history."""
    approval, user_authorization = quota._load_reference(user_authorization)
    quota._read(approval['repair_source']['path'], approval['repair_source']['sha256'])
    return {'schema': quota.SCHEMA_V7, 'scope': 'publish_only',
        **{k: approval[k] for k in ('utc_day', 'account_uuid', 'account_key', 'video', 'prepared', 'baseline_daily_runs',
            'max_daily_runs', 'active_control_revision', 'user_statement', 'repair_source')},
        'idempotency_keys': {'publish': PUBLISH_KEY}, 'user_authorization': user_authorization}
