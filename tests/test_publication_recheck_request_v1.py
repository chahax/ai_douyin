"""Private real SQLite/broker/core fixtures; no browser, platform or model."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace as NS

import pytest

from test_publication_verification_recovery import incident, valid_evidence, Page, Session
from src.operations_accounts import publication_recheck_request_v1 as api
from src.operations_accounts import publication_verification_recovery as core
from src.operations_accounts.browser_control import BrowserControlActor, BrowserControlRejected, BrowserControlStore


def ref(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def exhausted(incident, monkeypatch):
    i = incident
    monkeypatch.setattr(api, 'ROOT', i.journal.parents[2])
    monkeypatch.setattr(api, 'binding_version', lambda context: 'binding')
    for _ in range(3):
        command = core.queue_due(i.store, i.context, 'binding')
        claimed = i.store.claim_next(i.context.account_uuid, 'binding', 'backend:123:abc', 1)
        assert claimed['command_id'] == command['command_id']
        i.store.transition(command['command_id'], 'backend:123:abc', 1, 'failed',
                           result={'status': 'verification_pending', 'reason': 'title_candidate_missing'})
        i.now[0] += 301
        with i.store._db(write=True) as db:
            db.execute('UPDATE browser_control_owners SET heartbeat=?,updated_at=?', (i.now[0], i.now[0]))
    assert core.queue_due(i.store, i.context, 'binding') is None
    i.runtime = NS(resolve=lambda key, **kw: i.context)
    report = {'schema': api.REPORT_SCHEMA, 'user_statement': '链接有了，请检索原作品并核对',
              'reported_change': 'user_reports_original_video_link_now_available',
              'original_publish_command_id': i.original['command_id'], 'account_key': i.context.account_key,
              'account_uuid': i.context.account_uuid, 'candidate_id': 'candidate-original',
              'media_sha256': 'a' * 64, 'scope': 'one original-bound read; no new upload or click',
              'created_at': i.now[0]}
    i.report_path = api.ROOT / 'data' / 'USER_CHANGE.json'
    i.report_path.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
    i.report = ref(i.report_path)
    i.request_path = api.ROOT / 'data' / 'RECHECK.json'
    return i


def prepare(i):
    return api.prepare(i.report, output_path=i.request_path, store=i.store, runtime=i.runtime)


def enqueue(i, request):
    return api.enqueue(request, store=i.store, runtime=i.runtime)


def commands(i):
    with i.store._db() as db:
        return core._attempts(i.store, db, i.original['command_id'])


def test_prepare_status_do_not_queue_and_same_report_has_one_immutable_new_request(exhausted):
    i = exhausted
    old = commands(i); lock = i.lock.read_bytes(); journal = i.journal.read_bytes()
    request = prepare(i)
    assert commands(i) == old and api.status(request, store=i.store)['state'] == 'not_queued'
    first = enqueue(i, request); second = enqueue(i, request)
    assert first['command_id'] == second['command_id'] and second['reused']
    assert len(commands(i)) == 4 and core.MAX_ATTEMPTS == 3
    command = i.store.get(first['command_id'])
    assert command['kind'] == 'publication_verify' and command['payload']['attempt'] == 4
    continuation = command['payload']['explicit_recheck']
    assert continuation['user_change']['content']['user_statement'] == '链接有了，请检索原作品并核对'
    assert continuation['prior_verifications'] == old and continuation['scope'] == api.SCOPE
    assert not continuation['scope']['upload_allowed'] and not continuation['scope']['backfill_allowed']
    assert core.queue_due(i.store, i.context, 'binding') is None
    assert i.store.get(i.original['command_id']) == i.original
    assert i.lock.read_bytes() == lock and i.journal.read_bytes() == journal


def test_same_baseline_different_reports_cannot_consume_two_slots(exhausted):
    i = exhausted; first_request = prepare(i)
    value = json.loads(i.report_path.read_text(encoding='utf-8')); value['user_statement'] += '（另一次描述）'
    other = api.ROOT / 'data' / 'OTHER_CHANGE.json'; other.write_text(json.dumps(value), encoding='utf-8')
    other_request = api.prepare(ref(other), output_path=api.ROOT / 'data' / 'OTHER_REQUEST.json',
                                store=i.store, runtime=i.runtime)
    a = json.loads(i.request_path.read_text(encoding='utf-8'))
    b = json.loads(__import__('pathlib').Path(other_request['path']).read_text(encoding='utf-8'))
    assert a['idempotency_key'] == b['idempotency_key']
    enqueue(i, first_request)
    with pytest.raises(BrowserControlRejected) as caught:
        enqueue(i, other_request)
    assert caught.value.code == 'recheck_slot_already_used'
    assert len(commands(i)) == 4


def test_concurrent_same_report_uses_existing_broker_atomic_uniqueness(exhausted):
    i = exhausted; request = prepare(i)
    def call(_):
        other = BrowserControlStore(i.store.path, clock=i.store.clock)
        return api.enqueue(request, store=other, runtime=i.runtime)
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(call, range(2)))
    assert len({r['command_id'] for r in result}) == 1 and len(commands(i)) == 4


@pytest.mark.parametrize('field,value', [('account_uuid', 'account:other'), ('account_key', 'other'),
                                       ('media_sha256', 'b' * 64), ('created_at', 1)])
def test_wrong_report_subject_or_old_change_is_rejected_without_queue(exhausted, field, value):
    i = exhausted; report = json.loads(i.report_path.read_text(encoding='utf-8'));report[field] = value
    i.report_path.write_text(json.dumps(report), encoding='utf-8');i.report = ref(i.report_path)
    with pytest.raises(BrowserControlRejected):prepare(i)
    assert len(commands(i)) == 3


@pytest.mark.parametrize('change', ['binding', 'journal', 'lock', 'report', 'prior', 'original', 'live'])
def test_enqueue_revalidates_original_binding_source_prior_and_no_live_work(exhausted, monkeypatch, change):
    i = exhausted; request = prepare(i)
    if change == 'binding':monkeypatch.setattr(api, 'binding_version', lambda context: 'changed')
    elif change == 'journal':i.journal.write_text('{}\n')
    elif change == 'lock':i.lock.write_text('{}')
    elif change == 'report':i.report_path.write_text('{}')
    else:
        with i.store._db(write=True) as db:
            if change == 'prior':db.execute("UPDATE browser_control_commands SET result='{}' WHERE command_id=?", (commands(i)[0]['command_id'],))
            elif change == 'original':db.execute("UPDATE browser_control_commands SET updated_at=updated_at+1 WHERE command_id=?", (i.original['command_id'],))
            else:
                # A new original-bound read is unresolved, not disposable merely because it is read-only.
                previous = commands(i)[-1]
                db.execute("UPDATE browser_control_commands SET state='outcome_unknown' WHERE command_id=?", (previous['command_id'],))
    with pytest.raises((BrowserControlRejected, KeyError, ValueError)):enqueue(i, request)
    assert len(commands(i)) == 3


def test_duplicate_title_is_not_a_recheck_authorization(exhausted):
    i = exhausted
    i.store.submit(i.context.account_uuid, 'binding', 'publish', 'another', i.original['payload'], 100)
    with pytest.raises(BrowserControlRejected) as caught:prepare(i)
    assert caught.value.code == 'publication_title_ambiguous'
    assert len(commands(i)) == 3


def test_existing_unchanged_core_claim_run_settle_accepts_only_new_native_proof(exhausted, monkeypatch):
    i = exhausted; request = prepare(i); new = enqueue(i, request)
    post = '1234567890123456789'; page = Page({'verified': True, 'post_id': post,
                                            'publish_url': 'https://www.douyin.com/video/' + post})
    session = Session(page); calls = []
    monkeypatch.setattr('src.platform_adapter.publish_verification.wait_for_published_video',
                        lambda *a, **kw: valid_evidence(i))
    def identity(*args, **kwargs):calls.append('fresh_original_identity');return NS(healthy=True)
    resource = NS(context=i.context, runtime=NS(verify_identity=identity))
    actor = BrowserControlActor(i.store, i.context.account_uuid, 'binding', 'backend:123:abc',
        {core.KIND: lambda ctx, payload: core.run(ctx, session)}, context=resource)
    actor.generation = 1; actor._thread_id = __import__('threading').get_ident()
    result = actor.run_next()
    assert result['command_id'] == new['command_id'] and result['state'] == 'succeeded'
    original = i.store.get(i.original['command_id'])
    assert original['result']['original_unknown_snapshot'] == i.original and original['result']['post_id'] == post
    assert calls == ['fresh_original_identity'] and session.closed and len(page.visits) == 2
    assert len(commands(i)) == 4 and core.queue_due(i.store, i.context, 'binding') is None
    assert enqueue(i, request)['command_id'] == new['command_id']
    assert api.status(request, store=i.store)['status'] == 'verified_published'
    assert json.loads(i.lock.read_text())['status'] == 'submission_started'


def test_old_core_still_rejects_source_changed_after_new_request(exhausted):
    i = exhausted; command = i.store.get(enqueue(i, prepare(i))['command_id'])
    i.journal.write_text('{}\n')
    with pytest.raises((BrowserControlRejected, KeyError)):core.inputs(i.store, command, i.context)
    assert i.store.get(i.original['command_id']) == i.original


def test_unknown_explicit_read_is_returned_without_requeue_or_source_settlement(exhausted):
    i = exhausted; request = prepare(i); first = enqueue(i, request)
    claimed = i.store.claim_next(i.context.account_uuid, 'binding', 'backend:123:abc', 1)
    assert claimed['command_id'] == first['command_id']
    i.store.transition(first['command_id'], 'backend:123:abc', 1, 'outcome_unknown',
                       result={'status': 'read_completion_unknown'})
    again = enqueue(i, request)
    assert again['reused'] and again['command_id'] == first['command_id'] and again['state'] == 'outcome_unknown'
    assert len(commands(i)) == 4 and i.store.get(i.original['command_id']) == i.original
    assert core.queue_due(i.store, i.context, 'binding') is None


def test_public_cli_prepares_or_queries_only_selected_api_and_has_no_actor_launcher(tmp_path, monkeypatch, capsys):
    from scripts import request_publication_recheck_v1 as cli
    path = tmp_path / 'report.json';path.write_text('{}', encoding='utf-8'); calls = []
    monkeypatch.setattr(api, 'prepare', lambda *a, **kw: calls.append(('prepare', a, kw)) or {'prepared': True})
    monkeypatch.setattr(api, 'status', lambda *a, **kw: calls.append(('status', a, kw)) or {'state': 'not_queued'})
    monkeypatch.setattr(api, 'enqueue', lambda *a, **kw: pytest.fail('prepare/status must not enqueue'))
    cli.main(['prepare', '--report', str(path), '--output', str(tmp_path/'request.json')])
    cli.main(['status', '--request', str(path)])
    assert [c[0] for c in calls] == ['prepare', 'status']
    assert all(c[1][0] == ref(path) for c in calls)
