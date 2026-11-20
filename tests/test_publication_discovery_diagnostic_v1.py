"""Original-read diagnostic: CPU, private broker, real core, fake page only."""
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS
import time

import pytest

from test_publication_verification_recovery import incident, Page, Session
from test_publication_claim_hot_bridge_v1 import example
from src.operations_accounts import publication_discovery_diagnostic_v1 as api
from src.operations_accounts import publication_verification_recovery as core
from src.operations_accounts import browser_control_runtime as managed
from src.operations_accounts import publication_claim_hot_bridge_v1 as bridge
from src.operations_accounts.browser_control import BrowserControlStore, BrowserCommandResult, BrowserControlRejected, _json


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    return bridge.reference(path)


def grant_for(folder, original, account_key='novel', candidate_id='candidate-original'):
    authority = put(folder / 'AUTHORITY.json', dict(user_statement='自动查找和修复原视频流程，不重复发布。'))
    return put(folder / 'GRANT.json', dict(schema='publication_discovery_diagnostic_grant/v1', purpose=api.PURPOSE,
        account_key=account_key, account_uuid=original['account_id'], original_command_id=original['command_id'],
        candidate_id=candidate_id, media_sha256=original['payload']['video_sha256'], authority_reference=authority,
        user_statement='沿既有指令修复可观测性；前4次已知失败后做一次诊断。不是新增平台状态报告。',
        scope=api.SCOPE, instrumentation=api._self_ref()))


@pytest.fixture
def exhausted(incident, monkeypatch):
    i = incident
    root = i.journal.parents[2]
    monkeypatch.setattr(api, 'ROOT', root)
    monkeypatch.setattr(managed, 'binding_version', lambda context: 'binding')
    for index in range(3):
        command = core.queue_due(i.store, i.context, 'binding')
        i.store.claim_next(i.context.account_uuid, 'binding', 'backend:123:abc', 1)
        i.store.transition(command['command_id'], 'backend:123:abc', 1, 'failed',
            result={'status': 'verification_pending', 'reason': 'independent_card_unbound'})
        i.now[0] += 301
        with i.store._db(write=True) as db:
            db.execute('UPDATE browser_control_owners SET heartbeat=?,updated_at=?', (i.now[0], i.now[0]))
    source = core._source(i.context, i.original)
    extra = i.store.submit(i.context.account_uuid, 'binding', 'publication_verify', 'explicit-fourth',
        dict(account_key='novel', account_uuid=i.context.account_uuid, original_command_id=i.original['command_id'],
             original_snapshot_sha256=core._digest(i.original), source=source, attempt=4), 400)
    i.store.claim_next(i.context.account_uuid, 'binding', 'backend:123:abc', 1)
    i.store.transition(extra['command_id'], 'backend:123:abc', 1, 'failed',
        result={'status': 'verification_pending', 'reason': 'independent_card_unbound'})
    i.runtime = NS(resolve=lambda key, **kw: i.context)
    i.grant = grant_for(root / 'data', i.original)
    i.candidate = lambda cid: dict(command_id=i.original['command_id'],
        frozen_json=json.dumps(dict(media={'sha256': 'a' * 64}, account={'account_uuid': i.context.account_uuid})))
    return i


def prepare(i, name='diagnostic'):
    return api.prepare(i.grant, api.ROOT / 'data' / name, store=i.store, runtime=i.runtime, candidate_reader=i.candidate)


def test_prepare_readonly_and_enqueue_once_preserves_four_and_submission(exhausted):
    i = exhausted
    with i.store._db() as db:
        before = core._attempts(i.store, db, i.original['command_id'])
    lock, journal = i.lock.read_bytes(), i.journal.read_bytes()
    ref = prepare(i)
    with i.store._db() as db:
        assert core._attempts(i.store, db, i.original['command_id']) == before
    first = api.enqueue(ref, store=i.store, runtime=i.runtime)
    second = api.enqueue(ref, store=i.store, runtime=i.runtime)
    assert first['command_id'] == second['command_id'] and first['payload']['attempt'] == 5
    assert first['kind'] == 'publication_verify' and first['payload']['discovery_diagnostic'] == ref
    assert 'explicit_recheck' not in first['payload']
    assert core.MAX_ATTEMPTS == 3 and core.queue_due(i.store, i.context, 'binding') is None
    assert i.store.get(i.original['command_id']) == i.original
    assert all(i.store.get(old['command_id']) == old for old in before)
    assert i.lock.read_bytes() == lock and i.journal.read_bytes() == journal


def test_same_baseline_competing_grants_share_global_slot(exhausted):
    i = exhausted
    first = prepare(i)
    grant = json.loads(Path(i.grant['path']).read_text(encoding='utf-8'))
    grant['user_statement'] += '另一份措辞'
    i.grant = put(api.ROOT / 'data' / 'OTHER_GRANT.json', grant)
    second = prepare(i, 'other_diagnostic')
    a, b = json.loads(Path(first['path']).read_text(encoding='utf-8')), json.loads(Path(second['path']).read_text(encoding='utf-8'))
    assert a['idempotency_key'] == b['idempotency_key']
    api.enqueue(first, store=i.store, runtime=i.runtime)
    with pytest.raises(BrowserControlRejected, match='immutable request'):
        api.enqueue(second, store=i.store, runtime=i.runtime)


@pytest.mark.parametrize('change', ['upload', 'purpose', 'source'])
def test_wrong_grant_or_source_rejected(exhausted, change):
    i = exhausted
    value = json.loads(Path(i.grant['path']).read_text(encoding='utf-8'))
    if change == 'upload':
        value['scope']['upload_allowed'] = True
    elif change == 'purpose':
        value['purpose'] = 'user_reports_new_platform_change'
    else:
        value['instrumentation']['sha256'] = '0' * 64
    i.grant = put(api.ROOT / 'data' / 'BAD_GRANT.json', value)
    with pytest.raises(ValueError):
        prepare(i)


def test_unknown_prior_is_not_replayed(exhausted):
    i = exhausted
    with i.store._db(write=True) as db:
        db.execute("UPDATE browser_control_commands SET state='outcome_unknown' WHERE idempotency_key='explicit-fourth'")
    with pytest.raises(ValueError, match='four_known_failed'):
        prepare(i)


def test_tampered_request_or_original_rejected(exhausted):
    i = exhausted
    ref = prepare(i)
    with i.store._db(write=True) as db:
        db.execute("UPDATE browser_control_commands SET result='{}' WHERE command_id=?", (i.original['command_id'],))
    with pytest.raises(ValueError, match='original_changed'):
        api.enqueue(ref, store=i.store, runtime=i.runtime)


def discovery(reason='independent_card_unbound', verified=False):
    return dict(schema='published_work_discovery/v1', reason=reason, verified=verified,
        post_id='1234567890123456789' if verified else '',
        publish_url='https://www.douyin.com/video/1234567890123456789' if verified else '',
        diagnostic=dict(route='manage', title_candidates=1, loading_markers=0, scan_truncated=False,
            candidates_excessive=False, bound_title_structure=dict(schema='bound_title_structure/v2', connected=True,
                projection='title_path_control_shells_known_operation_text_and_image_alt_only',
                ancestors=[dict(tag='DIV', own_text='剧情片段', projected_outer_html='<div title="token=SECRET">作品</div>',
                                headers={'cookie': 'SECRET'}, cookie='SECRET')])) )


def test_sanitizer_keeps_structure_but_not_credentials_or_url_query():
    value = discovery()
    value['diagnostic']['bound_title_structure']['url'] = 'https://creator.douyin.com/manage?token=SECRET#fragment'
    clean = api.sanitize_discovery(value)
    text = json.dumps(clean, ensure_ascii=False)
    assert 'SECRET' not in text and '?token' not in text and 'fragment' not in text
    assert clean['diagnostic']['bound_title_structure']['ancestors'][0]['tag'] == 'DIV'
    assert 'projected_outer_html' in text


def test_two_stable_unbound_samples_stop_without_new_page_commands(tmp_path):
    values = discovery()
    events = []
    capture = api.Capture(tmp_path, {'synthetic_cpu_fixture': True}, lambda: events.append('guard'))
    original = NS(discover_published_work=lambda title: values, marker='original')
    page = api.ObservedPage(original, capture)
    assert page.marker == 'original'
    assert page.discover_published_work('title') is values
    with pytest.raises(api.CaptureComplete, match='independent_card_unbound'):
        page.discover_published_work('title')
    assert len(capture.refs) == 2 and events == ['guard', 'guard']
    assert len(list(tmp_path.glob('SAMPLE_*.json'))) == 2


def test_verified_discovery_returns_original_value_and_never_stops(tmp_path):
    capture = api.Capture(tmp_path, {}, lambda: None)
    result = discovery('exact_title_card_canonical_id', verified=True)
    assert api.ObservedPage(NS(discover_published_work=lambda title: result), capture).discover_published_work('title') is result
    assert len(capture.refs) == 1


@pytest.fixture
def runtime_example(example, monkeypatch):
    e = example
    monkeypatch.setattr(api, 'ROOT', e.folder)
    monkeypatch.setattr(core, 'ROOT', e.folder)
    monkeypatch.setattr(managed, 'binding_version', lambda context: e.config['binding_version'])
    context = NS(account_uuid=e.config['account_id'], account_key=e.config['account_key'], binding=NS(platform_identity_key='platform:test'))
    request = dict(video_path=str(e.folder / 'approved.mp4'), title='原视频', description='原说明', hashtags=['话题'],
                   visibility='public', ai_generated=True, fictional_story=True)
    payload = dict(account_key=context.account_key, account_uuid=context.account_uuid, video_sha256='a' * 64, request=request)
    with e.store._db(write=True) as db:
        db.execute('DELETE FROM browser_control_commands WHERE command_id=?', (e.queued['command_id'],))
        db.execute('UPDATE browser_control_commands SET payload=?,updated_at=? WHERE command_id=?',
                   (_json(payload), time.time(), e.original['command_id']))
    e.original = e.store.get(e.original['command_id'])
    directory = e.folder / 'data/publish_runs'
    directory.mkdir(parents=True)
    key = hashlib.sha256(json.dumps(dict(platform_identity_key='platform:test', video_sha256='a' * 64), sort_keys=True).encode()).hexdigest()
    journal = directory / (key + '.journal.jsonl')
    rows = [dict(stage='prepared', at_bjt=datetime.fromtimestamp(e.original['created_at'], timezone.utc).isoformat(),
        account=context.account_key, account_uuid=context.account_uuid, platform_identity_key='platform:test', video_sha256='a' * 64,
        title=request['title'], description=request['description'], hashtags=['话题'], video_path=request['video_path'],
        visibility='public', ai_declaration_required=True, fiction_declaration_required=True),
        dict(stage='submission_started'),
        dict(stage='ai_declaration_verified', set_selected=True, evidence=dict(verified=True, label='内容由AI生成')),
        dict(stage='ai_declaration_verified', set_selected=False, evidence=dict(verified=True, label='内容由AI生成')),
        dict(stage='publish_click_dispatching')]
    journal.write_text('\n'.join(json.dumps(x, ensure_ascii=False) for x in rows) + '\n', encoding='utf-8')
    put(directory / (key + '.submitted.json'), dict(journal=str(journal), status='submission_started'))
    source = core._source(context, e.original)
    for number in range(1, 5):
        cmd = e.store.submit(context.account_uuid, e.config['binding_version'], 'publication_verify', 'prior:' + str(number),
            dict(account_uuid=context.account_uuid, account_key=context.account_key, original_command_id=e.original['command_id'],
                 original_snapshot_sha256=core._digest(e.original), source=source, attempt=number), 400)
        with e.store._db(write=True) as db:
            db.execute("UPDATE browser_control_commands SET state='failed',result=? WHERE command_id=?",
                (_json(dict(status='verification_pending', reason='independent_card_unbound')), cmd['command_id']))
    runtime = NS(resolve=lambda key, **kwargs: context, verify_identity=lambda *a, **kw: NS(healthy=True),
                 operation_lease=lambda *a, **kw: nullcontext())
    grant = grant_for(e.folder / 'data', e.original, context.account_key, 'old-candidate')
    candidate = lambda cid: dict(command_id=e.original['command_id'], frozen_json=json.dumps(dict(
        media={'sha256': 'a' * 64}, account={'account_uuid': context.account_uuid})))
    e.request = api.prepare(grant, e.folder / 'data/diagnostic', store=e.store, runtime=runtime, candidate_reader=candidate)
    e.queued = api.enqueue(e.request, store=e.store, runtime=runtime)
    e.config.update(verification_command_id=e.queued['command_id'], verification_request_sha256=e.queued['request_sha'])
    e.config_ref = put(e.folder / 'NEW_CONFIG.json', e.config)
    e.claim_plan = bridge.prepare_plan(e.config_ref, e.folder / 'data/new_claim_plan')
    e.plan = api.prepare_runtime(e.request, e.claim_plan, e.folder / 'data/runtime_plan')
    monkeypatch.setattr(api, 'ARM', e.folder / 'data/DIAGNOSTIC_ARM.json')
    put(api.ARM, dict(schema='publication_discovery_diagnostic_arm/v1', plan=e.plan))
    e.page = Page(discovery())
    e.session = Session(e.page)
    e.resource.context, e.resource.runtime = context, runtime
    e.resource.ensure_session = lambda: None
    e.old_handler = lambda ctx, payload: {'old_handler': True}
    e.actor.handlers = {'publication_verify': e.old_handler}
    e.namespace.update(BrowserCommandResult=BrowserCommandResult, BorrowedSession=lambda resource, role: e.session,
                       _with_active=lambda fn: fn)
    original_loader = bridge._load_claim
    def load(config):
        function, rejection, proof = original_loader(config)
        function.__globals__['ROOT'] = e.folder
        return function, rejection, proof
    monkeypatch.setattr(bridge, '_load_claim', load)
    e.context = context
    return e


def execute_runtime(e):
    assert api.install_if_armed()['status'] == 'callback_registered_waiting_actor_tick'
    assert not (e.folder / 'data/runtime_plan/ACTOR_HANDLER_INSTALLED.json').exists()
    e.namespace['_poll_manual_windows'](e.actor, e.resource)
    assert (e.folder / 'data/runtime_plan/ACTOR_HANDLER_INSTALLED.json').is_file()
    selected = BrowserControlStore.claim_next(e.store, e.config['account_id'], e.config['binding_version'],
                                              e.config['owner_id'], e.config['generation'])
    assert selected['command_id'] == e.queued['command_id']
    ctx = NS(task_id=selected['command_id'], actor=e.actor, command=selected, resource=e.resource,
             account_id=e.actor.account_id, binding_version=e.actor.binding_version, check_dispatch=e.actor._check_owner)
    return e.actor.handlers['publication_verify'](ctx, selected['payload'])


def test_real_core_single_handler_captures_unbound_and_restores(runtime_example):
    e = runtime_example
    out = execute_runtime(e)
    assert out.state == 'failed' and out.result['reason'] == 'independent_card_unbound'
    assert out.result['diagnostic_observation_completed']
    summary = json.loads(Path(out.result['diagnostic_capture']['path']).read_text(encoding='utf-8'))
    assert summary['sample_count'] == 2
    assert e.actor.handlers['publication_verify'] is e.old_handler and e.session.closed
    assert e.store.get(e.original['command_id']) == e.original
    assert e.page.visits == ['https://creator.douyin.com/creator-micro/content/manage']


def test_real_core_verified_detail_keeps_atomic_settlement(runtime_example, monkeypatch):
    e = runtime_example
    e.page.discovery = discovery('exact_title_card_canonical_id', verified=True)
    monkeypatch.setattr('src.platform_adapter.publish_verification.wait_for_published_video', lambda *a, **kw: dict(
        verified=True, expected_title='原视频', expected_hashtags=['话题'], title_verified=True, hashtags_verified=True,
        review_status='clear', ai_label_visible=True, fiction_notice_visible=True,
        player=dict(ready=True, error=False, duration=True)))
    result = execute_runtime(e)
    assert result['status'] == 'verified_published'
    original = e.store.get(e.original['command_id'])
    assert original['state'] == 'succeeded' and original['result']['original_unknown_snapshot'] == e.original
    assert e.actor.handlers['publication_verify'] is e.old_handler and e.session.closed


def test_observer_write_failure_does_not_override_verified_settlement(runtime_example, monkeypatch):
    e = runtime_example
    e.page.discovery = discovery('exact_title_card_canonical_id', verified=True)
    monkeypatch.setattr('src.platform_adapter.publish_verification.wait_for_published_video', lambda *a, **kw: dict(
        verified=True, expected_title='原视频', expected_hashtags=['话题'], title_verified=True, hashtags_verified=True,
        review_status='clear', ai_label_visible=True, fiction_notice_visible=True,
        player=dict(ready=True, error=False, duration=True)))
    monkeypatch.setattr(api.Capture, 'summary', lambda *a, **kw: (_ for _ in ()).throw(OSError('synthetic disk failure')))
    result = execute_runtime(e)
    assert result['status'] == 'verified_published'
    assert e.store.get(e.original['command_id'])['state'] == 'succeeded'
    assert e.actor.handlers['publication_verify'] is e.old_handler


def test_handler_entry_failure_still_restores(runtime_example):
    e = runtime_example
    e.resource.ensure_session = lambda: (_ for _ in ()).throw(RuntimeError('synthetic startup failure'))
    with pytest.raises(RuntimeError, match='synthetic startup'):
        execute_runtime(e)
    assert e.actor.handlers['publication_verify'] is e.old_handler


def test_other_cid_delegates_old_handler_without_observation(runtime_example):
    e = runtime_example
    api.install_if_armed()
    e.namespace['_poll_manual_windows'](e.actor, e.resource)
    assert e.actor.handlers['publication_verify'](NS(task_id='another-cid'), {}) == {'old_handler': True}
    assert not (e.folder / 'data/diagnostic/capture').exists()


def test_readiness_gate_missing_until_actor_handler_installed(runtime_example):
    e = runtime_example
    before = e.store.get(e.queued['command_id'])
    assert not api.handler_ready(before, e.config['owner_id'], e.config['generation'])
    assert BrowserControlStore.claim_next(e.store, e.config['account_id'], e.config['binding_version'],
        e.config['owner_id'], e.config['generation']) is None
    api.install_if_armed()
    assert not api.handler_ready(before, e.config['owner_id'], e.config['generation'])
    e.namespace['_poll_manual_windows'](e.actor, e.resource)
    assert api.handler_ready(before, e.config['owner_id'], e.config['generation'])
    assert e.store.get(e.queued['command_id']) == before


def test_readiness_gate_is_only_file_and_hash_read(runtime_example, monkeypatch):
    e = runtime_example
    api.install_if_armed()
    e.namespace['_poll_manual_windows'](e.actor, e.resource)
    command = e.store.get(e.queued['command_id'])
    def forbidden(*args, **kwargs):
        raise AssertionError('readiness must not query DB/process/runtime')
    monkeypatch.setattr(bridge, '_process', forbidden)
    monkeypatch.setattr(bridge, '_ro', forbidden)
    monkeypatch.setattr(managed, '_runtime', forbidden)
    assert api.handler_ready(command, e.config['owner_id'], e.config['generation'])


@pytest.mark.parametrize('change', ['owner', 'generation', 'other_cid', 'ready', 'runtime_plan'])
def test_readiness_gate_mismatch_fails_closed(runtime_example, change):
    e = runtime_example
    api.install_if_armed()
    e.namespace['_poll_manual_windows'](e.actor, e.resource)
    command = e.store.get(e.queued['command_id'])
    owner, generation = e.config['owner_id'], e.config['generation']
    assert api.handler_ready(command, owner, generation)
    if change == 'owner':
        owner += ':different'
    elif change == 'generation':
        generation += 1
    elif change == 'other_cid':
        command['command_id'] = 'another-command'
    elif change == 'ready':
        put(Path(e.request['path']).parent / 'HANDLER_READY.json', {})
    else:
        Path(e.plan['path']).write_text('{}', encoding='utf-8')
    assert not api.handler_ready(command, owner, generation)
