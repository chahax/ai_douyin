"""Exact v4 exception; original scheduler/control/actor/transactional counting stay real."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts import publication_fast_upload_authorization as fast
from src.operations_accounts import publication_two_run_authorization as quota
from src.operations_accounts import publication_unknown_closure as closure
from src.operations_accounts.browser_control import BrowserCommandResult, BrowserControlRejected
from test_publication_single_retry import incident, archived, write
from test_publication_second_two_run_exception import second
from test_publication_two_run_exception import frozen


@pytest.fixture
def ready(incident, monkeypatch):
    i = incident
    monkeypatch.setattr(quota, 'REGISTRY_V4', i.f.root / 'registry_v4.json')
    _, receipt = archived(i)
    v3 = quota.build_single_publish_authorization(i.f.prepared, account_uuid='acct:one', account_key='one',
        publish_key='only-original-v3-publication', user_statement='可以',
        closure_authorization=i.authority, archive_receipt=receipt)
    v3path = i.f.root / 'V3.json'
    v3ref = write(v3path, v3)
    quota.register_authorization(v3path, v3ref['sha256'])
    key = hashlib.sha256(json.dumps({'platform_identity_key': 'public:original',
        'video_sha256': v3['video']['sha256']}, sort_keys=True).encode()).hexdigest()
    journal = i.f.root / 'data/publish_runs' / (key + '.known-upload-failure.jsonl')

    @bridge._with_active
    def known_upload_failure(ctx, payload):
        with bridge._publication_lease(i.resource):
            first = {'stage': 'prepared', 'at_bjt': datetime.now(timezone.utc).isoformat(),
                'account': 'one', 'account_uuid': 'acct:one', 'platform_identity_key': 'public:original',
                'video_path': v3['video']['path'], 'video_sha256': v3['video']['sha256'], 'title': 'Approved'}
            journal.write_text('\n'.join(json.dumps(v) for v in (first,
                {'stage': 'file_selected'}, {'stage': 'uploading'}, {'stage': 'upload_failed', 'post_id': '', 'publish_url': ''})), encoding='utf-8')
        return BrowserCommandResult('failed', {'status': 'upload_failed', 'success': False, 'post_id': '', 'publish_url': ''})

    i.actor.handlers['publish'] = known_upload_failure
    i.actor.admission = bridge._admission
    before = bridge.queue_prepared_publication(i.f.prepared, quota_authorization=v3ref)
    before = i.actor.run_next()
    assert before['state'] == 'failed' and i.repository.get_runtime_state('acct:one').daily_runs == 26
    monkeypatch.setattr(fast, 'PREVIOUS_COMMAND_ID', before['command_id'])
    command_ref = write(i.f.root / 'PREVIOUS.json', before)
    original = dict(before)
    original.pop('task_id')  # The native final report used SQL, not Store's alias.
    final = write(i.f.root / 'FINAL.json', {'original_command': original,
        'new_submission_lock_exists': False, 'control': {'state': 'active', 'revision': 42},
        'runtime': {'daily_runs': 26, 'day_key': v3['utc_day'], 'lock_owner': '', 'lock_expires_at': ''},
        'journal': str(journal)})
    approval = {'schema': fast.AUTH_SCHEMA, 'decision_source': 'explicit_user_statement', 'user_statement': '允许',
        'approval_question': '是否允许再追加本视频发布1次，部署修复后继续？',
        'account_uuid': 'acct:one', 'account_key': 'one', 'prepared': v3['prepared'], 'video': v3['video'],
        'previous_authorization': v3ref, 'previous_command': command_ref, 'previous_command_id': before['command_id'],
        'previous_journal': closure.file_reference(journal), 'previous_final_state': final,
        'deployment_authorized': True, 'additional_publication_runs': 1, 'additional_recovery_runs': 0,
        'new_media_authorized': False, 'utc_day': v3['utc_day'], 'baseline_daily_runs': 26, 'max_daily_runs': 27,
        'active_control_revision': 42, 'retain_original_history': True}
    authority = write(i.f.root / 'V4_USER_AUTHORIZATION.json', approval)
    monkeypatch.setattr(fast, 'APPROVAL_SHA256', authority['sha256'])
    value = fast.build_fast_upload_authorization(authority)
    path = i.f.root / 'V4_FROZEN.json'
    ref = write(path, value)
    prior = {p: p.read_bytes() for p in (quota.REGISTRY, quota.REGISTRY_V2, quota.REGISTRY_V3)}
    quota.register_authorization(path, ref['sha256'])
    return NS(i=i, value=value, path=path, ref=ref, authority=authority, journal=journal, key=key,
        before=before, prior=prior)


def test_v4_real_actor_counts26_to27_once_keeps_old_chain_and_manual20(ready):
    f, i = ready, ready.i
    events = []

    @bridge._with_active
    def publish(ctx, payload):
        with bridge._publication_lease(i.resource):
            events.append(i.repository.get_runtime_state('acct:one').daily_runs)
        return {'published_once': True}

    i.actor.handlers['publish'] = publish
    manual = i.store.submit('acct:one', bridge.binding_version(i.resource.context), 'manual', 'ordinary-manual',
        {'account_uuid': 'acct:one', 'account_key': 'one'}, priority=200)
    queued = bridge.queue_prepared_publication(i.f.prepared, quota_authorization=f.ref)
    assert queued['priority'] == 250
    assert i.actor.run_next()['state'] == 'succeeded' and events == [27]
    assert i.repository.get_runtime_state('acct:one').daily_runs == 27
    assert bridge.queue_prepared_publication(i.f.prepared, quota_authorization=f.ref)['command_id'] == queued['command_id']
    assert i.actor.run_next()['state'] == 'queued'  # Ordinary manual still sees original20.
    assert i.store.get(manual['command_id'])['state'] == 'queued' and events == [27]
    assert all(p.read_bytes() == original for p, original in f.prior.items())
    assert quota.validate_authorization(json.loads(quota.REGISTRY_V3.read_bytes()))['max_daily_runs'] == 26
    assert quota.registered_recovery('one', {'state': 'active', 'revision': 42, 'account_uuid': 'acct:one'}) is None


def test_v4_exact_scope_control_and_registry_no_general_budget_or_new_key(ready):
    f, i = ready, ready.i
    for change in ('cap', 'revision', 'key', 'recovery', 'account'):
        value = deepcopy(f.value)
        if change == 'cap': value['max_daily_runs'] = 28
        if change == 'revision': value['active_control_revision'] = 43
        if change == 'key': value['idempotency_keys']['publish'] = 'another-key'
        if change == 'recovery': value['idempotency_keys']['recovery'] = 'not-authorized'
        if change == 'account': value['account_uuid'] = 'another-account'
        reference = write(i.f.root / ('INVALID_' + change + '.json'), value)
        with pytest.raises(BrowserControlRejected):
            quota.validate_authorization(reference, require_registered=False)
    assert quota.register_authorization(f.path, f.ref['sha256']) == f.ref
    replacement = i.f.root / 'REPLACEMENT.json'
    replacement.write_bytes(f.path.read_bytes())
    with pytest.raises(BrowserControlRejected):
        quota.register_authorization(replacement, closure.file_reference(replacement)['sha256'])
    queued = bridge.queue_prepared_publication(i.f.prepared, quota_authorization=f.ref)
    for kind, operation, control in (
        ('publish', 'publish', {'state': 'active', 'revision': 43}),
        ('recovery', 'identity-recovery', {'state': 'recovering', 'revision': 42})):
        ctx = NS(account_id='acct:one', command=dict(queued, kind=kind))
        with pytest.raises(BrowserControlRejected):
            quota.authorized_daily_limit(ctx, operation, account_uuid='acct:one',
                control=dict(control, account_uuid='acct:one', account_key='one'))


def test_v4_unknown_or_changed_failed_receipt_and_evidence_never_released(ready):
    f, i = ready, ready.i
    with i.store._db(write=True) as db:
        db.execute("UPDATE browser_control_commands SET state='outcome_unknown' WHERE command_id=?", (f.before['command_id'],))
    with pytest.raises(BrowserControlRejected):
        quota.validate_authorization(f.ref)
    with i.store._db(write=True) as db:
        db.execute("UPDATE browser_control_commands SET state='failed' WHERE command_id=?", (f.before['command_id'],))
    assert quota.validate_authorization(f.ref)['max_daily_runs'] == 27
    f.journal.write_bytes(f.journal.read_bytes() + b'\n')
    with pytest.raises(BrowserControlRejected):
        quota.validate_authorization(f.ref)
    assert i.repository.get_runtime_state('acct:one').daily_runs == 26


def test_v4_new_submission_lock_blocks_queue_without_consumption(ready):
    f, i = ready, ready.i
    lock = i.f.root / 'data/publish_runs' / (f.key + '.submitted.json')
    lock.write_text('{}', encoding='utf-8')
    with pytest.raises(BrowserControlRejected):
        bridge.queue_prepared_publication(i.f.prepared, quota_authorization=f.ref)
    assert i.repository.get_runtime_state('acct:one').daily_runs == 26
    assert i.store.get(f.before['command_id']) == f.before
