"""Whole-chapter coordinator tests: source fidelity, routing and durable stops."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from src.content_factory import corpus_production_v4 as p


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return path


def source(tmp_path, count=3, long=False):
    entries = []
    for n in range(1, count + 1):
        text = ('长章完整原文。' * 20000 if long else f'第{n}章的院子里有木桌。\n小周将文件交给老陈。\n这是合成测试素材。')
        row = {'book_id': 'fixture', 'index': n, 'title': f'章{n}', 'text': text,
               'sha256': hashlib.sha256(text.encode()).hexdigest()}
        path = put(tmp_path / f'chapter_{n}.json', row)
        entries.append({'index': n, 'path': str(path), 'sha256': row['sha256']})
    manifest = put(tmp_path / 'MANIFEST.json', {'book_id': 'fixture', 'book_name': '合成测试',
                    'status': 'accessible_catalogue_complete', 'chapters': entries})
    history = put(tmp_path / 'prior' / 'STATE.json', {'calls_started': 100, 'reported_tokens': 2000, 'pending': None})
    return manifest, history


@pytest.fixture
def configured(monkeypatch):
    routes = {'writer': {'provider': 'minimax', 'model': 'MiniMax-M3', 'base_url': 'https://fixture.invalid'},
              'director': {'provider': 'deepseek', 'model': 'deepseek-flash', 'base_url': 'https://fixture.invalid'}}
    monkeypatch.setattr(p, '_cloud_routes', lambda: deepcopy(routes))
    monkeypatch.setattr(p, 'preflight', lambda route: {**route, 'digest': 'fixture-digest'})
    return routes


class Classifier:
    def __init__(self, unknown=False):
        self.requests = []
        self.unknown = unknown

    def call(self, role, messages, **kwargs):
        payload = json.loads(messages[-1]['content'])
        self.requests.append((role, payload))
        if self.unknown:
            raise TimeoutError('fixture timeout')
        value = {'chapter_id': payload['chapter_id'], 'chapter_index': payload['chapter_index'],
                 'assignments': [{'passage_id': row['id'], 'categories': ['location', 'event'],
                                  'importance': 'core'} for row in payload['paragraph_index'] if row['scope'] == 'core']}
        return SimpleNamespace(text=json.dumps(value, ensure_ascii=False),
            metadata={'prompt_tokens': 80, 'completion_tokens': 20, 'total_tokens': 100, 'finish_reason': 'stop'},
            response_payload={'fixture': True})


def ready(tmp_path, count=3):
    manifest, history = source(tmp_path, count)
    run = tmp_path / 'run'
    plan = p.prepare(manifest, run, user_statement='隔离测试逐章流程', previous_status=history)
    client = Classifier()
    p.execute_local(run, client)
    return run, plan, client


def test_69_complete_chapters_kept_and_no_model_compression(tmp_path, configured):
    run, plan, client = ready(tmp_path, 69)
    saved = p.read(run / 'SOURCE.json')['chapters']
    assert len(client.requests) == len(saved) == len(plan['chapters']) == 69
    by_index = {c['index']: c for c in saved}
    for role, payload in client.requests:
        assert role == 'local'
        assert payload['core_chapter']['text'] == by_index[payload['chapter_index']]['text']
        for neighbor in payload['context_chapters']:
            assert neighbor['text'] == by_index[neighbor['index']]['text']
        assert all('text' not in item for item in payload['paragraph_index'])
    state = p.read(run / 'STATE.json')
    assert state['status'] == 'materials_ready'
    assert state['total_calls_with_history'] == 169
    assert state['pending'] is None and state['content_acceptance'] is False
    assert p.read(run / 'cloud' / 'STATE.json')['calls_started'] == 0
    p.execute_local(run, client)
    assert len(client.requests) == 69


def test_oversized_chapter_rejected_before_run_created(tmp_path, configured):
    manifest, history = source(tmp_path, 1, long=True)
    with pytest.raises(p.LocalInputRejected, match='no_truncation'):
        p.prepare(manifest, tmp_path / 'run', user_statement='fixture', previous_status=history)
    assert not (tmp_path / 'run').exists()


def test_unknown_never_replayed_or_adopted(tmp_path, configured):
    manifest, history = source(tmp_path, 1)
    run = tmp_path / 'run'
    p.prepare(manifest, run, user_statement='fixture', previous_status=history)
    client = Classifier(unknown=True)
    with pytest.raises(Exception, match='classification_incomplete'):
        p.execute_local(run, client)
    assert p.read(run / 'local' / 'STATE.json')['status'] == 'outcome_unknown'
    assert p.read(run / 'STATE.json')['pending']
    p.execute_local(run, client)
    assert len(client.requests) == 1
    assert not (run / 'MATERIALS_INDEX.json').exists()


@pytest.mark.parametrize('filename,field,value', [('SOURCE.json', 'chapters', []), ('PLAN.json', 'workers', 4),
                        ('AUTHORIZATION.json', 'destinations', {}), ('local/PLAN.json', 'new_call_limit', 9999)])
def test_frozen_tampering_rejected(tmp_path, configured, filename, field, value):
    run, _, _ = ready(tmp_path)
    data = p.read(run / filename)
    data[field] = value
    put(run / filename, data)
    with pytest.raises(ValueError, match='changed'):
        p.execute_local(run, Classifier())


def test_minimax_json_uses_content_not_deepseek_api_mode(configured):
    calls = []
    cloud = SimpleNamespace(call=lambda role, messages, **kwargs: calls.append((role, kwargs)))
    clients = p.StageClients({'max_tokens': 8192}, configured, cloud_client=cloud)
    clients.call('writer', [], response_format={'type': 'json_object'}, max_tokens=16000)
    clients.call('director', [], response_format={'type': 'json_object'}, max_tokens=16000)
    assert calls[0] == ('writer', {'max_tokens': 16000})
    assert calls[1][1]['response_format'] == {'type': 'json_object'}


def test_local_adapter_cannot_use_cloud_fallback(configured):
    calls = []
    local = SimpleNamespace(call=lambda role, messages, **kwargs: calls.append((role, kwargs)))
    clients = p.StageClients({'max_tokens': 8192}, configured, local_client=local)
    clients.call('local', [], response_format={'type': 'json_object'}, max_tokens=16000)
    assert calls[0][0] == 'director' and calls[0][1]['max_tokens'] == 8192
    with pytest.raises(p.LocalInputRejected):
        clients.call('local', [], max_tokens=16000)


def test_local_preflight_failure_is_known_not_sent(configured, monkeypatch):
    def missing(route):
        raise OSError('fixture ollama unavailable')
    monkeypatch.setattr(p, 'LocalAnalysisClient', missing)
    clients = p.StageClients({'max_tokens': 8192}, configured)
    with pytest.raises(p.LocalInputRejected, match='before_inference'):
        clients.call('local', [], response_format={'type': 'json_object'}, max_tokens=16000)


def test_local_inference_timeout_remains_unknown(configured):
    def unknown(*args, **kwargs):
        raise TimeoutError('fixture inference outcome unknown')
    clients = p.StageClients({'max_tokens': 8192}, configured, local_client=SimpleNamespace(call=unknown))
    with pytest.raises(TimeoutError):
        clients.call('local', [], response_format={'type': 'json_object'}, max_tokens=16000)


def test_provider_change_rejected_before_client_call(configured, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('provider must not be called')
    clients = p.StageClients({}, configured, cloud_client=SimpleNamespace(call=forbidden))
    monkeypatch.setattr(p, '_cloud_routes', lambda: {})
    with pytest.raises(p.LocalInputRejected, match='model_changed'):
        clients.call('writer', [])


def test_existing_approval_block_retained(tmp_path, configured):
    run, _, _ = ready(tmp_path)
    put(run / 'APPROVAL_REQUIRED.json', {'status': 'denied', 'reason': 'scope'})
    with pytest.raises(ValueError, match='approval_disposition'):
        p.execute_cloud(run, Classifier())
    assert p.read(run / 'cloud' / 'STATE.json')['calls_started'] == 0


def test_deepseek_before_final_rejected(tmp_path, configured, monkeypatch):
    from src.content_factory import corpus_production_contract_v4 as contract
    run, _, _ = ready(tmp_path)
    def bad(call, *args, **kwargs):
        call('FRAMEWORK', 'director', 'JSON', {})
    monkeypatch.setattr(contract, 'run_production', bad)
    with pytest.raises(ValueError, match='reserved_for_final'):
        p.execute_cloud(run, Classifier())
    assert p.read(run / 'cloud' / 'STATE.json')['calls_started'] == 0


def test_cli_dispatch_preserves_frozen_version(tmp_path):
    from scripts.run_corpus_production import coordinator
    put(tmp_path / 'PLAN.json', {'version': p.VERSION})
    assert coordinator(tmp_path) is p
    from src.content_factory import corpus_production_v3
    put(tmp_path / 'PLAN.json', {'version': corpus_production_v3.VERSION})
    assert coordinator(tmp_path) is corpus_production_v3
    put(tmp_path / 'PLAN.json', {'version': 'unknown'})
    with pytest.raises(ValueError):
        coordinator(tmp_path)


def test_fanqie_new_workflow_selects_whole_chapter_and_stops_after_failed_local(tmp_path, monkeypatch):
    from scripts import run_fanqie_corpus_workflow as workflow
    from src.content_factory import corpus_production_v9 as latest
    command = {'command_id': 'fixture', 'kind': 'fanqie_book_inspect', 'state': 'succeeded',
               'payload': {'book_name': '合成测试', 'chapters': 0}}
    class Accounts:
        db = tmp_path / 'db'
        def queue(self, *args, **kwargs):
            return command
        def folder(self, *args):
            return tmp_path / 'evidence'
    monkeypatch.setattr(workflow, 'BrowserControlStore', lambda *args: SimpleNamespace(get=lambda *_: command))
    events = []
    def launch(cmd, accounts):
        put(accounts.folder() / 'BOOK_INSPECTION.json', {'corpus': {'status': 'accessible_catalogue_complete'},
                                                       'corpus_path': str(tmp_path / 'manifest')})
    def prepare(*args, **kwargs):
        events.append('prepare_v6')
        put(Path(args[1]) / 'PLAN.json', {'version': latest.VERSION})
        put(Path(args[1]) / 'STATE.json', {'status': 'prepared'})
    from pathlib import Path
    monkeypatch.setattr(latest, 'prepare', prepare)
    monkeypatch.setattr(latest, 'execute_local', lambda *_: events.append('local_v6') or {'status': 'needs_attention'})
    def forbidden(*args):
        raise AssertionError('local failure must not dispatch cloud')
    monkeypatch.setattr(latest, 'execute_cloud', forbidden)
    result = workflow.workflow(tmp_path / 'workflow', 'fixture', '合成测试', tmp_path / 'history', 'fixture scope',
                               accounts=Accounts(), launch=launch, execute_text=True)
    assert events == ['prepare_v6', 'local_v6'] and result['status'] == 'needs_attention'
    assert p.read(tmp_path / 'workflow' / 'JOB.json')['text_pipeline'] == latest.VERSION


def test_fanqie_dispatches_legacy_plan_without_upgrade(tmp_path, monkeypatch):
    from scripts import run_fanqie_corpus_workflow as workflow
    put(tmp_path / 'PLAN.json', {'schema': 'corpus_screenplay/v4'})
    put(tmp_path / 'STATE.json', {'status': 'prepared'})
    monkeypatch.setattr(workflow, 'execute', lambda run: {'route': 'legacy'})
    assert workflow.execute_text_pipeline(tmp_path) == {'route': 'legacy'}


@pytest.mark.parametrize('phase_status,pending', [('needs_attention', None), ('outcome_unknown', ['fixture-claim'])])
def test_production_failure_cannot_be_downgraded_to_materials_ready(tmp_path, configured, phase_status, pending):
    from scripts import run_fanqie_corpus_workflow as workflow
    run, _, client = ready(tmp_path)
    cloud = p.read(run / 'cloud' / 'STATE.json')
    cloud.update(status=phase_status, calls_started=1, pending=pending)
    put(run / 'cloud' / 'STATE.json', cloud)
    state = p.read(run / 'STATE.json')
    state.update(status='needs_attention', pending=pending, reason='production failure preserved')
    put(run / 'STATE.json', state)
    preserved = p.execute_local(run, client)
    assert preserved['status'] == phase_status
    assert preserved['pending'] == pending
    assert workflow.execute_text_pipeline(run) == preserved
    assert p.read(run / 'STATE.json') == preserved
    assert len(client.requests) == 3


def test_crash_between_phase_claim_and_parent_snapshot_exposes_original_pending(tmp_path, configured):
    run, _, client = ready(tmp_path)
    cloud = p.read(run / 'cloud' / 'STATE.json')
    cloud.update(status='running', stage='MATERIAL_REVIEW_00', calls_started=1,
                 pending=['original-claim'], pending_calls={'original-claim': {'name': 'MATERIAL_REVIEW_00'}})
    put(run / 'cloud' / 'STATE.json', cloud)
    assert p.read(run / 'STATE.json')['status'] == 'materials_ready'
    state = p.execute_local(run, client)
    assert state['status'] == 'waiting_existing' and state['pending'] == ['original-claim']
    assert state['calls_started'] == 4
    assert len(client.requests) == 3


def test_local_claim_before_parent_snapshot_exposes_pending_without_inference(tmp_path, configured):
    manifest, history = source(tmp_path, 1)
    run = tmp_path / 'run'
    p.prepare(manifest, run, user_statement='fixture', previous_status=history)
    local = p.read(run / 'local' / 'STATE.json')
    local.update(status='running', stage='CLASSIFY_CH001', calls_started=1,
                 pending=['local-original'], pending_calls={'local-original': {'name': 'CLASSIFY_CH001'}})
    put(run / 'local' / 'STATE.json', local)
    client = Classifier()
    state = p.execute_local(run, client)
    assert state['status'] == 'waiting_existing'
    assert state['pending'] == ['local-original'] and state['calls_started'] == 1
    assert state['stage'] == 'CLASSIFY_CH001' and client.requests == []


@pytest.mark.parametrize('root_stage', [None, 'framework'])
def test_full_coordinator_native_receipts_and_repair_binding(tmp_path, configured, root_stage):
    from test_corpus_production_contract_v4 import fixture, Fake
    original, _, _ = fixture(2)
    entries = []
    for row in original['chapters']:
        saved = {**row, 'book_id': 'fixture'}
        path = put(tmp_path / f'original_{row["index"]}.json', saved)
        entries.append({'index': row['index'], 'path': str(path), 'sha256': row['sha256']})
    manifest = put(tmp_path / 'MANIFEST.json', {'book_id': 'fixture', 'book_name': '测试书',
                   'status': 'accessible_catalogue_complete', 'chapters': entries})
    history = put(tmp_path / 'HISTORY.json', {'calls_started': 10, 'reported_tokens': 1000, 'pending': None})
    run = tmp_path / 'run'
    p.prepare(manifest, run, user_statement='isolated full workflow fixture', previous_status=history)
    p.execute_local(run, Classifier())
    fake = Fake(p.read(run / 'SOURCE.json'), p.read(run / 'CHAPTER_MATERIALS.json'),
                p.read(run / 'CLOUD_SOURCE_PACK.json'), root_stage=root_stage)
    class NativeClient:
        def call(self, role, messages, **kwargs):
            stage = p.read(run / 'cloud' / 'STATE.json')['stage']
            payload = json.loads(messages[-1]['content'])
            value = fake(stage, role, messages[0]['content'], payload,
                         kwargs.get('response_format') == {'type': 'json_object'})
            text = json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value
            return SimpleNamespace(text=text, metadata={'prompt_tokens': 10, 'completion_tokens': 10,
                        'total_tokens': 20, 'finish_reason': 'stop'}, response_payload={'fixture': True, 'stage': stage})
    state = p.execute_cloud(run, NativeClient())
    assert state['status'] == 'reviewed_draft_ready' and state['pending'] is None
    binding = p.read(run / 'REVIEW_BINDING.json')
    assert binding['root_repairs'] == bool(root_stage)
    assert state['content_acceptance'] == 'machine_review_passed_awaiting_independent_review'
    assert len(list((run / 'cloud').glob('RESPONSE_*.json'))) == len(fake.calls)
    assert p.read(run / 'cloud' / 'STATE.json')['reported_tokens'] == 20 * len(fake.calls)
    assert state['total_calls_with_history'] == 10 + 2 + len(fake.calls)
    assert all(name.startswith(('FINAL_CONTENT_', 'FINAL_TIMING_'))
               for name, role, _ in fake.calls if role == 'director')
    previous_calls = len(fake.calls)
    assert p.execute_cloud(run, NativeClient()) == state
    assert len(fake.calls) == previous_calls
