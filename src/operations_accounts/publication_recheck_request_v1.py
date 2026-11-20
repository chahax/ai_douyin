"""One explicit, original-bound read after the automatic verification budget.

This is a new user-requested observation, not a reset of MAX_ATTEMPTS.  The
existing publication_verify handler remains the only browser/settlement path.
Authority is checked and frozen at enqueue; no mutable runtime grant is added.
"""
import hashlib
import json
import math
from pathlib import Path

from .browser_control import BrowserControlRejected, _json
from . import publication_verification_recovery as core
from .browser_control_runtime import binding_version

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = 'publication_recheck_request/v1'
REPORT_SCHEMA = 'publication_platform_change_report/v1'
SCOPE = {'operation': 'read_original_publication', 'max_new_verifications': 1,
         'upload_allowed': False, 'publish_click_allowed': False,
         'comment_allowed': False, 'backfill_allowed': False,
         'automatic_attempt_limit_changed': False}


def _require(ok, code):
    if not ok:
        raise BrowserControlRejected(code, '原作品只读续查依据不匹配；原提交和所有历史核验保持。')


def _hash(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _path(value):
    path = Path(value).resolve()
    _require(path.is_relative_to(ROOT / 'data'), 'recheck_project_evidence_required')
    return path


def _read(reference):
    _require(isinstance(reference, dict) and set(reference) == {'path', 'sha256'}, 'recheck_binding_required')
    raw = _path(reference['path']).read_bytes()
    _require(len(raw) <= 1024 * 1024 and hashlib.sha256(raw).hexdigest() == reference['sha256'],
             'recheck_evidence_changed')
    value = json.loads(raw)
    _require(isinstance(value, dict), 'recheck_evidence_object_required')
    return value


def _services(store, runtime):
    from . import browser_control_runtime as managed
    return store if store is not None else managed._store(), runtime if runtime is not None else managed._runtime()


def _report(reference):
    report = _read(reference)
    _require(report.get('schema') == REPORT_SCHEMA
             and report.get('reported_change') == 'user_reports_original_video_link_now_available'
             and isinstance(report.get('user_statement'), str)
             and 0 < len(report['user_statement'].strip()) <= 4000
             and isinstance(report.get('scope'), str) and bool(report['scope'].strip()),
             'explicit_platform_change_report_required')
    for field in ('original_publish_command_id', 'account_uuid', 'account_key', 'candidate_id', 'media_sha256'):
        _require(isinstance(report.get(field), str) and bool(report[field]), 'platform_change_subject_required')
    created = report.get('created_at')
    _require(type(created) in (int, float) and math.isfinite(created) and created > 0,
             'platform_change_time_required')
    return report


def _subject(report, context, version, original):
    _require(original is not None and original['kind'] == 'publish'
             and original['command_id'] == report['original_publish_command_id']
             and original['account_id'] == report['account_uuid'] == context.account_uuid
             and original['binding_version'] == version
             and report['account_key'] == context.account_key
             and original['payload'].get('account_key') == context.account_key
             and original['payload'].get('video_sha256') == report['media_sha256'],
             'recheck_original_subject_mismatch')


def _key(original, prior, source):
    # The slot belongs to the original exhausted baseline, NOT to a new report.
    # Competing reports therefore collide on the broker's existing atomic UNIQUE.
    baseline = {'original': core._digest(original), 'prior': [core._digest(r) for r in prior], 'source': source}
    return 'publication-verify-recheck:' + original['command_id'] + ':' + _hash(baseline)


def _prior_valid(prior, original, report, now):
    _require(len(prior) == core.MAX_ATTEMPTS == 3
             and len({r['command_id'] for r in prior}) == 3
             and all(r['kind'] == core.KIND and r['state'] == 'failed'
                     and r['account_id'] == original['account_id']
                     and r['binding_version'] == original['binding_version']
                     and r['payload'].get('original_command_id') == original['command_id']
                     and r['payload'].get('attempt') == i
                     and (r.get('result') or {}).get('status') == 'verification_pending'
                     for i, r in enumerate(prior, 1)), 'automatic_verification_baseline_not_exhausted')
    _require(max(r['updated_at'] for r in prior) <= report['created_at'] <= now + 5,
             'platform_change_must_follow_previous_checks')


def prepare(report_reference, *, output_path, store=None, runtime=None):
    """Read repositories and freeze a request. Never enqueue or open a browser."""
    report = _report(report_reference)
    store, runtime = _services(store, runtime)
    context = runtime.resolve(report['account_key'], require_healthy=False)
    version = binding_version(context)
    with store._db() as db:
        original = core._original(store, db, context.account_uuid)
        _subject(report, context, version, original)
        prior = core._attempts(store, db, original['command_id'])
        _prior_valid(prior, original, report, store.clock())
        titles = [r for r in db.execute("SELECT payload FROM browser_control_commands WHERE account_id=? AND kind='publish'",
                                       (context.account_uuid,))
                  if json.loads(r[0]).get('request', {}).get('title') == original['payload']['request']['title']]
        _require(len(titles) == 1, 'publication_title_ambiguous')
    source = core._source(context, original)
    _require(all(r['payload'].get('original_snapshot_sha256') == core._digest(original)
                 and r['payload'].get('source') == source for r in prior), 'recheck_prior_source_changed')
    value = {'schema': SCHEMA, 'account_uuid': context.account_uuid, 'account_key': context.account_key,
             'binding_version': version, 'original': original, 'source': source,
             'prior_verifications': prior, 'user_change': {'reference': report_reference, 'content': report},
             'scope': SCOPE, 'attempt': 4, 'idempotency_key': _key(original, prior, source)}
    path = _path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (_json(value) + '\n').encode('utf-8')
    if path.exists():
        _require(path.read_bytes() == raw, 'existing_recheck_request_preserved')
    else:
        with path.open('xb') as handle:
            handle.write(raw)
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}


def _request(reference):
    value = _read(reference)
    _require(value.get('schema') == SCHEMA and value.get('scope') == SCOPE and value.get('attempt') == 4,
             'recheck_request_scope_invalid')
    report = _report(value['user_change']['reference'])
    _require(report == value['user_change']['content'], 'recheck_platform_change_changed')
    _require(value.get('idempotency_key') == _key(value['original'], value['prior_verifications'], value['source']),
             'recheck_baseline_changed')
    return value, report


def _payload(value, request_sha):
    return {'account_uuid': value['account_uuid'], 'account_key': value['account_key'],
            'original_command_id': value['original']['command_id'],
            'original_snapshot_sha256': core._digest(value['original']), 'source': value['source'], 'attempt': 4,
            'explicit_recheck': {'schema': SCHEMA, 'request_sha256': request_sha,
                                'user_change': value['user_change'],
                                'prior_verifications': value['prior_verifications'], 'scope': SCOPE}}


def _existing(store, value):
    with store._db() as db:
        return store._command(db.execute('SELECT * FROM browser_control_commands WHERE account_id=? AND idempotency_key=?',
                                        (value['account_uuid'], value['idempotency_key'])).fetchone())


def enqueue(request_reference, *, store=None, runtime=None):
    """Persist one original read via the existing broker; never launch/pump it."""
    value, report = _request(request_reference)
    store, runtime = _services(store, runtime)
    context = runtime.resolve(value['account_key'], require_healthy=False)
    version = binding_version(context)
    original = value['original']
    _subject(report, context, version, original)
    _require(value['account_uuid'] == context.account_uuid and value['binding_version'] == version,
             'recheck_binding_changed')
    _prior_valid(value['prior_verifications'], original, report, store.clock())
    source = core._source(context, original)
    _require(source == value['source'], 'recheck_native_source_changed')
    _require(all(r['payload'].get('original_snapshot_sha256') == core._digest(original)
                 and r['payload'].get('source') == source for r in value['prior_verifications']),
             'recheck_prior_source_changed')
    payload = _payload(value, request_reference['sha256'])
    current = store.get(original['command_id'])
    existing = _existing(store, value)
    with store._db() as db:
        actual_prior = core._attempts(store, db, original['command_id'])
        _require(actual_prior[:3] == value['prior_verifications'], 'recheck_previous_receipts_changed')
        if existing is None:
            _require(current == original and core._original(store, db, context.account_uuid) == original,
                     'recheck_original_no_longer_eligible')
            _require(actual_prior == value['prior_verifications'], 'recheck_live_or_later_verification_exists')
    if existing is not None:
        _require(existing['kind'] == core.KIND and existing['binding_version'] == version
                 and existing['payload'] == payload and existing['priority'] == 400, 'recheck_slot_already_used')
        _require(current == original or (current and current['state'] == 'succeeded'
                 and (current.get('result') or {}).get('original_unknown_snapshot') == original),
                 'recheck_original_changed')
        return {'command_id': existing['command_id'], 'kind': core.KIND, 'state': existing['state'],
                'attempt': 4, 'reused': True, 'browser_started': False}
    # Same-baseline competing reports share this key. Existing broker uniqueness
    # either returns the exact immutable request or rejects a different report.
    command = store.submit(context.account_uuid, version, core.KIND, value['idempotency_key'], payload, 400)
    return {'command_id': command['command_id'], 'kind': core.KIND, 'state': command['state'],
            'attempt': 4, 'reused': False, 'browser_started': False}


def status(request_reference, *, store=None):
    """Read the already persisted request; never create a command/runtime."""
    value, _ = _request(request_reference)
    if store is None:
        from .browser_control_runtime import _store
        store = _store()
    existing = _existing(store, value)
    if existing is None:
        return {'state': 'not_queued', 'command_id': None, 'read_only': True}
    _require(existing['payload'] == _payload(value, request_reference['sha256']), 'recheck_slot_already_used')
    result = existing.get('result') or {}
    return {'command_id': existing['command_id'], 'state': existing['state'], 'attempt': 4,
            'status': result.get('status'), 'reason': result.get('reason'), 'post_id': result.get('post_id'),
            'read_only': True}
