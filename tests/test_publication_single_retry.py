"""Human closes unknown history; exact lock archive; one original counted retry."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts import publication_two_run_authorization as quota
from src.operations_accounts import publication_unknown_closure as closure
from src.operations_accounts.browser_control import BrowserControlActor, BrowserControlStore, BrowserCommandResult, BrowserControlRejected
from src.operations_accounts.repository import AccountBindingRepository
from src.operations_accounts.runtime import AccountRuntimeContext, AccountRuntimeService
from src.scheduler import account_refresh
from test_publication_second_two_run_exception import second
from test_publication_two_run_exception import frozen, sha


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return closure.file_reference(path)


@pytest.fixture
def incident(second, monkeypatch):
    f = second
    monkeypatch.setattr(closure, 'ROOT', f.root)
    # Establish the original active42 through the real scheduler completion.
    assert account_refresh.request_account_recovery('acct:one', 'one', path=f.scheduler)
    token = account_refresh._claim_recovery('acct:one', 'one', path=f.scheduler)
    assert token and account_refresh._finish_recovery('acct:one', 'one', token,
        healthy=True, status='active', path=f.scheduler)
    assert quota.control_snapshot('acct:one')['revision'] == 42
    repository = AccountBindingRepository(f.root / 'account.db')
    with repository.connection() as db:
        db.execute("INSERT INTO douyin_accounts(account_uuid,account_key,created_at,updated_at) VALUES('acct:one','one','old','old')")
    repository.get_runtime_state('acct:one')
    with repository.connection() as db:
        db.execute("UPDATE account_runtime_state SET day_key=?,daily_runs=25 WHERE account_uuid='acct:one'",
            (datetime.now(timezone.utc).date().isoformat(),))
    binding = NS(account_uuid='acct:one', account_key='one', platform_identity_key='public:original',
        browser_environment_key='env:one', browser_profile_dir='profile/one', storage_state_path='state/one',
        confirmed_by='user', created_at='2026', status='active')
    profile = NS(account_uuid='acct:one', account_key='one', profile_version=1, status='active')
    context = AccountRuntimeContext(profile, binding, 'env:one', 'profile/one', 'state/one')
    runtime = object.__new__(AccountRuntimeService)
    runtime.resolve = lambda *a, **k: context
    runtime.profiles = NS(get=lambda *a: profile)
    runtime.bindings = NS(get_runtime_state=repository.get_runtime_state, get=lambda *a: binding,
        acquire_runtime=repository.acquire_runtime, release_runtime=repository.release_runtime,
        connection=repository.connection)
    resource = bridge.AccountBrowserResource(context, runtime)
    store = BrowserControlStore(f.root / 'data/account_browser_control.db')
    monkeypatch.setattr(bridge, '_runtime', lambda: runtime)
    monkeypatch.setattr(bridge, '_store', lambda: store)
    monkeypatch.setattr(bridge, '_legacy_manual_gate', lambda *a: None)
    monkeypatch.setattr(bridge, '_controls', lambda *a: account_refresh.snapshot(f.scheduler)['controls'][0])
    runs = f.root / 'data/publish_runs'
    runs.mkdir(parents=True)
    key = hashlib.sha256(json.dumps({'platform_identity_key': binding.platform_identity_key,
        'video_sha256': f.value['video']['sha256']}, sort_keys=True).encode()).hexdigest()
    journal = runs / (key + '.original.jsonl')
    lock = runs / (key + '.submitted.json')
    def original_unknown(ctx, payload):
        first = {'stage': 'prepared', 'at_bjt': datetime.now(timezone.utc).isoformat(),
            'account': 'one', 'account_uuid': 'acct:one', 'platform_identity_key': binding.platform_identity_key,
            'video_sha256': f.value['video']['sha256'], 'video_path': str(f.video), 'title': 'Approved'}
        journal.write_text('\n'.join(json.dumps(v) for v in (first,
            {'stage': 'submission_started'}, {'stage': 'submission_unknown'})), encoding='utf-8')
        write(lock, {'journal': str(journal), 'status': 'submission_started'})
        return BrowserCommandResult('outcome_unknown', {'status': 'submission_unknown',
            'success': False, 'post_id': '', 'publish_url': '', 'message': 'original timeout'})
    actor = BrowserControlActor(store, 'acct:one', bridge.binding_version(context), 'original-owner',
        {'publish': original_unknown}, context=resource)
    original = bridge.queue_prepared_publication(f.prepared, quota_authorization=f.ref)
    before = actor.run_next()
    reported = dict(before)
    reported.pop('task_id')  # Native SQL report has no derived Store alias.
    report_path = f.root / 'USER_WORK_NOT_FOUND_REPORT.json'
    report = write(report_path, {'decision_source': 'explicit_user_statement', 'user_statement': '没有找到该作品',
        'question': '是否已有本作品或审核中记录？', 'observation_type': 'human_report_work_not_found',
        'account_uuid': 'acct:one', 'account_key': 'one', 'original_command_id': original['command_id'],
        'original_command_snapshot': reported})
    approval = {'schema': closure.AUTH_SCHEMA, 'decision_source': 'explicit_user_statement',
        'user_statement': '可以', 'approval_question': '允许保留原证据、人工结清并归档旧锁，再追加本视频发布1次？',
        'original_command_id': original['command_id'], 'account_uuid': 'acct:one', 'account_key': 'one',
        'video': f.value['video'], 'prepared': f.value['prepared'], 'journal': closure.file_reference(journal),
        'submission_lock': closure.file_reference(lock), 'human_report': report,
        'operator_close_unknown_publication': True, 'archive_submission_lock': True,
        'retain_original_history': True, 'original_outcome_known': False,
        'additional_publication_runs': 1, 'additional_recovery_runs': 0, 'new_media_authorized': False,
        'baseline_daily_runs': 25, 'max_daily_runs': 26, 'active_control_revision': 42,
        'utc_day': datetime.now(timezone.utc).date().isoformat()}
    approval_path = f.root / 'USER_AUTHORIZATION.json'
    authority = write(approval_path, approval)
    destination = runs / 'operator_closed' / lock.name
    value = NS(f=f, actor=actor, before=before, store=store, repository=repository,
        resource=resource, runtime=runtime, journal=journal, lock=lock, report=report_path,
        authority=authority, approval=approval, approval_path=approval_path, destination=destination)
    yield value
    actor.stop_heartbeat()


def close_original(i):
    return i.store.operator_close_unknown_publication(i.before['command_id'], i.actor.owner_id,
        i.actor.generation, expected_snapshot_sha256=closure.snapshot_sha256(i.before),
        authorization=i.authority, reason='explicit operator closure; external result remains unknown', requested_by='authorized-root')


def archived(i):
    closed = close_original(i)
    receipt = closure.archive_submission_lock(i.store, i.before['command_id'], i.actor.owner_id, i.actor.generation,
        expected_snapshot_sha256=closure.snapshot_sha256(closed), authorization=i.authority, destination=i.destination)
    return closed, receipt


def test_closed_unknown_and_exact_archive_then_only_one_counted_publication25_to26(incident):
    i = incident
    old_lock = i.lock.read_bytes()
    old_journal = i.journal.read_bytes()
    closed, receipt = archived(i)
    assert closed['result']['before_snapshot'] == i.before
    assert closed['result']['original_outcome_known'] is False
    assert closed['error_code'] == 'operator_closed_external_outcome_unknown'
    assert not i.lock.exists() and i.destination.read_bytes() == old_lock
    assert i.journal.read_bytes() == old_journal
    value = quota.build_single_publish_authorization(i.f.prepared, account_uuid='acct:one', account_key='one',
        publish_key='one-human-authorized-retry', user_statement='可以',
        closure_authorization=i.authority, archive_receipt=receipt)
    path = i.f.root / 'V3_FROZEN.json'
    reference = write(path, value)
    prior_registry = quota.REGISTRY.read_bytes(), quota.REGISTRY_V2.read_bytes()
    assert quota.register_authorization(path, reference['sha256']) == reference
    assert quota.registered_recovery('one') is None  # v3 creates no recovery grant.
    original_payload = {'account_key': 'one', 'account_uuid': 'acct:one',
        'quota_authorization': reference, 'identity_probe_only': True}
    fake_recovery = NS(account_id='acct:one', command={'kind': 'recovery', 'idempotency_key': value['idempotency_keys']['publish'],
        'payload': original_payload})
    with pytest.raises(BrowserControlRejected):
        quota.authorized_daily_limit(fake_recovery, 'identity-recovery', account_uuid='acct:one',
            control={'account_uuid':'acct:one','account_key':'one','state':'recovering','revision':42})
    events = []
    @bridge._with_active
    def publish(ctx, payload):
        with bridge._publication_lease(i.resource):
            events.append(i.repository.get_runtime_state('acct:one').daily_runs)
        return {'published_once': True}
    i.actor.handlers['publish'] = publish
    i.actor.admission = bridge._admission
    queued = bridge.queue_prepared_publication(i.f.prepared, quota_authorization=reference)
    assert queued['priority'] == 250
    assert i.actor.run_next()['state'] == 'succeeded'
    assert events == [26] and i.repository.get_runtime_state('acct:one').daily_runs == 26
    assert quota.REGISTRY.read_bytes() == prior_registry[0] and quota.REGISTRY_V2.read_bytes() == prior_registry[1]
    assert bridge.queue_prepared_publication(i.f.prepared, quota_authorization=reference)['command_id'] == queued['command_id']
    assert i.actor.run_next() is None


@pytest.mark.parametrize('change', ['cas', 'owner', 'generation', 'question', 'report', 'journal', 'lock', 'video', 'task_id'])
def test_closure_rejects_any_changed_identity_snapshot_or_frozen_evidence(incident, change):
    i = incident
    args = dict(expected_snapshot_sha256=closure.snapshot_sha256(i.before), authorization=i.authority,
        reason='explicit disposal', requested_by='root')
    if change == 'cas': args['expected_snapshot_sha256'] = 'wrong'
    if change == 'question':
        i.approval['approval_question'] = ''
        args['authorization'] = write(i.approval_path, i.approval)
    for name in ('report', 'journal', 'lock', 'video'):
        if change == name:
            target = i.f.video if name == 'video' else getattr(i, name)
            target.write_bytes(target.read_bytes() + b' ')
    if change == 'task_id':
        report = json.loads(i.report.read_bytes())
        report['original_command_snapshot']['task_id'] = 'other-id'
        i.approval['human_report'] = write(i.report, report)
        args['authorization'] = write(i.approval_path, i.approval)
    with pytest.raises(BrowserControlRejected):
        i.store.operator_close_unknown_publication(i.before['command_id'],
            'wrong' if change == 'owner' else i.actor.owner_id, i.actor.generation + (change == 'generation'), **args)
    assert i.store.get(i.before['command_id']) == i.before


@pytest.mark.parametrize('change', ['existing_destination', 'wrong_cas', 'lock_changed', 'journal_changed'])
def test_archive_rejects_mismatch_without_removing_original_history(incident, change):
    i = incident
    closed = close_original(i)
    if change == 'existing_destination':
        i.destination.parent.mkdir(parents=True)
        i.destination.write_bytes(b'must not overwrite')
    if change == 'lock_changed': i.lock.write_bytes(i.lock.read_bytes() + b' ')
    if change == 'journal_changed': i.journal.write_bytes(i.journal.read_bytes() + b' ')
    original = i.lock.read_bytes()
    with pytest.raises(BrowserControlRejected):
        closure.archive_submission_lock(i.store, i.before['command_id'], i.actor.owner_id, i.actor.generation,
            expected_snapshot_sha256='wrong' if change == 'wrong_cas' else closure.snapshot_sha256(closed),
            authorization=i.authority, destination=i.destination)
    assert i.lock.read_bytes() == original and not i.destination.with_name(i.destination.name + '.receipt.json').exists()


@pytest.mark.parametrize('change', ['cap', 'revision', 'recovery', 'oldkey', 'receipt'])
def test_v3_rejects_additional_scope_or_detached_closure(incident, change):
    i = incident
    closed, receipt = archived(i)
    value = quota.build_single_publish_authorization(i.f.prepared, account_uuid='acct:one', account_key='one',
        publish_key='single-retry', user_statement='可以', closure_authorization=i.authority, archive_receipt=receipt)
    if change == 'cap': value['max_daily_runs'] = 27
    if change == 'revision': value['active_control_revision'] = 43
    if change == 'recovery': value['idempotency_keys']['recovery'] = 'not-authorized'
    if change == 'oldkey': value['idempotency_keys']['publish'] = i.f.value['idempotency_keys']['publish']
    if change == 'receipt':
        receipt_path = i.f.root / 'other_receipt.json'
        value['archive_receipt'] = write(receipt_path, {'schema': closure.ARCHIVE_SCHEMA, 'phase': 'archived'})
    candidate = i.f.root / 'INVALID_V3.json'
    reference = write(candidate, value)
    with pytest.raises(BrowserControlRejected): quota.validate_authorization(reference, require_registered=False)
