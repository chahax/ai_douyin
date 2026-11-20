"""Whole-chapter coordinator tests: source fidelity, routing and durable stops."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from src.content_factory import corpus_production_v5 as p


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
        index = payload['chapter_index']
        text = payload['core_chapter']['text']
        facts, coverage = [], []
        for n, row in enumerate(payload['paragraph_index'], 1):
            fid = f'CH{index}-F{n:03d}'
            quote = text[row['start_offset']:row['end_offset']].strip()
            facts.append({'id': fid, 'categories': ['event'], 'statement': quote,
                'entity_ids': [], 'modality': 'actual', 'event_time': 'chapter_present',
                'narrative_anchor_passage_id': row['id'],
                'source_refs': [{'paragraph_id': row['id'], 'exact_quote': quote}], 'state_changes': []})
            coverage.append({'paragraph_id': row['id'], 'fact_ids': [fid], 'no_fact_reason': ''})
        value = {'chapter_id': payload['chapter_id'], 'chapter_index': index,
                 'entities': [], 'facts': facts, 'coverage': coverage}
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
    with pytest.raises(Exception, match='facts_incomplete'):
        p.execute_local(run, client)
    assert p.read(run / 'local' / 'STATE.json')['status'] == 'outcome_unknown'
    assert p.read(run / 'STATE.json')['pending']
    p.execute_local(run, client)
    assert len(client.requests) == 1
    assert not (run / 'FACT_CATALOG.json').exists()


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
    from src.content_factory import corpus_production_contract_v5 as contract
    run, _, _ = ready(tmp_path)
    from src.content_factory.corpus_scope_v5 import record_cloud_authorization
    plan = p.read(run / 'PLAN.json')
    record_cloud_authorization(run, 'isolated fixture explicit cloud approval; no actual providers',
        approved_source_sha256=plan['source_sha256'], approved_destinations=plan['cloud_models'])
    def bad(call, *args, **kwargs):
        call('FRAMEWORK', 'director', 'JSON', {})
    monkeypatch.setattr(contract, 'run_production', bad)
    with pytest.raises(ValueError, match='reserved_for_final'):
        p.execute_cloud(run, Classifier())
    assert p.read(run / 'cloud' / 'STATE.json')['calls_started'] == 0


def test_new_run_does_not_infer_cloud_authorization_from_prepare_statement(tmp_path, configured):
    run, _, _ = ready(tmp_path)
    client = Classifier()
    with pytest.raises(ValueError, match='explicit_cloud_authorization_required'):
        p.execute_cloud(run, client)
    assert client.requests == []
    assert p.read(run / 'cloud' / 'STATE.json')['calls_started'] == 0


def test_changed_local_implementation_stops_before_any_new_inference(tmp_path, configured, monkeypatch):
    from src.content_factory import corpus_scope_v5 as scope
    manifest, history = source(tmp_path, 1)
    run = tmp_path / 'run'
    p.prepare(manifest, run, user_statement='fixture', previous_status=history)
    old = scope.implementation_pin()
    monkeypatch.setattr(scope, 'implementation_pin', lambda: {**old, 'version': 'changed'})
    client = Classifier()
    with pytest.raises(ValueError, match='local_implementation_pin_changed'):
        p.execute_local(run, client)
    assert client.requests == []


def test_cli_dispatch_preserves_frozen_version(tmp_path):
    from scripts.run_corpus_production import coordinator
    put(tmp_path / 'PLAN.json', {'version': p.VERSION})
    assert coordinator(tmp_path) is p
    from src.content_factory import corpus_production_v4
    put(tmp_path / 'PLAN.json', {'version': corpus_production_v4.VERSION})
    assert coordinator(tmp_path) is corpus_production_v4
    from src.content_factory import corpus_production_v3
    put(tmp_path / 'PLAN.json', {'version': corpus_production_v3.VERSION})
    assert coordinator(tmp_path) is corpus_production_v3
    put(tmp_path / 'PLAN.json', {'version': 'unknown'})
    with pytest.raises(ValueError):
        coordinator(tmp_path)


def test_fanqie_new_workflow_selects_facts_and_stops_after_failed_local(tmp_path, monkeypatch):
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
        events.append('prepare_latest')
        put(Path(args[1]) / 'PLAN.json', {'version': latest.VERSION})
        put(Path(args[1]) / 'STATE.json', {'status': 'prepared'})
    from pathlib import Path
    monkeypatch.setattr(latest, 'prepare', prepare)
    monkeypatch.setattr(latest, 'execute_local', lambda *_: events.append('local_latest') or {'status': 'needs_attention'})
    def forbidden(*args):
        raise AssertionError('local failure must not dispatch cloud')
    monkeypatch.setattr(latest, 'execute_cloud', forbidden)
    result = workflow.workflow(tmp_path / 'workflow', 'fixture', '合成测试', tmp_path / 'history', 'fixture scope',
                               accounts=Accounts(), launch=launch, execute_text=True)
    assert events == ['prepare_latest', 'local_latest'] and result['status'] == 'needs_attention'
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


@pytest.mark.parametrize('limit', [0, 2, 7, True])
def test_local_trial_budget_is_validated_before_run_created(tmp_path, configured, limit):
    manifest, history = source(tmp_path, 3)
    with pytest.raises(ValueError, match='local_call_limit_out_of_range'):
        p.prepare(manifest, tmp_path / 'run', user_statement='fixture', previous_status=history,
                  local_call_limit=limit)
    assert not (tmp_path / 'run').exists()


@pytest.mark.parametrize('version', ['v3', 'v4'])
def test_existing_workflow_job_preserves_preparation_route(tmp_path, monkeypatch, version):
    from scripts import run_fanqie_corpus_workflow as workflow
    route = workflow.extractive if version == 'v3' else workflow.whole_chapter
    run = tmp_path / 'workflow'
    previous = tmp_path / 'history'
    put(run / 'JOB.json', {'resource': 'fixture', 'title': 'test', 'command_id': 'old',
                           'previous_status': str(previous.resolve()), 'user_statement': 'old scope',
                           'text_pipeline': route.VERSION})
    put(tmp_path / 'evidence' / 'BOOK_INSPECTION.json',
        {'corpus': {'status': 'accessible_catalogue_complete'}, 'corpus_path': 'fixture'})
    monkeypatch.setattr(workflow, 'BrowserControlStore', lambda *_: SimpleNamespace(
        get=lambda *_: {'command_id': 'old', 'state': 'succeeded'}))
    def prepare_old(manifest, folder, **kwargs):
        put(folder / 'STATE.json', {'route': route.VERSION})
    monkeypatch.setattr(route, 'prepare', prepare_old)
    monkeypatch.setattr(p, 'prepare', lambda *args, **kwargs: pytest.fail('old job migrated'))
    accounts = SimpleNamespace(db=tmp_path / 'db', folder=lambda *_: tmp_path / 'evidence')
    result = workflow.workflow(run, 'fixture', 'test', previous, 'old scope', accounts=accounts)
    assert result == {'route': route.VERSION}


@pytest.mark.parametrize('root_stage', [None, 'snapshot'])
def test_native_ledger_complete_pipeline_and_snapshot_repair(tmp_path, configured, root_stage):
    from tests.test_corpus_production_contract_v5 import fixture, Fake, DRAFT
    from src.content_factory import corpus_chapter_facts_v5 as facts
    from src.content_factory.corpus_scope_v5 import record_cloud_authorization
    original, analyses, pack, snapshot = fixture()
    entries = []
    for row in original['chapters']:
        path = put(tmp_path / f'original_{row["index"]}.json', {**row, 'book_id': 'native-fixture'})
        entries.append({'index': row['index'], 'path': str(path), 'sha256': row['sha256']})
    manifest = put(tmp_path / 'MANIFEST.json', {'book_id': 'native-fixture',
        'book_name': pack['book_name'], 'status': 'accessible_catalogue_complete', 'chapters': entries})
    history = put(tmp_path / 'HISTORY.json', {'calls_started': 4, 'reported_tokens': 400, 'pending': None})
    run = tmp_path / 'run'
    plan = p.prepare(manifest, run, user_statement='isolated synthetic fixture',
                     previous_status=history, target_seconds=10, workers=1)
    fake = Fake(original, analyses, pack, snapshot, root_stage=root_stage)
    class Native:
        def __init__(self):
            self.count = 0
        def call(self, role, messages, **kwargs):
            self.count += 1
            payload = json.loads(messages[-1]['content'])
            if 'core_chapter' in payload and 'candidate' not in payload:
                value = facts.raw_candidate(next(row for row in analyses if row['chapter_index'] == payload['chapter_index']))
            else:
                stage = p.read(run / 'cloud' / 'STATE.json')['stage']
                value = fake(stage, role, messages[0]['content'], payload,
                             kwargs.get('response_format') == {'type': 'json_object'})
            return SimpleNamespace(text=json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value,
                metadata={'prompt_tokens': 80, 'completion_tokens': 20, 'total_tokens': 100, 'finish_reason': 'stop'},
                response_payload={'synthetic_native_fixture': True})
    native = Native()
    p.execute_local(run, native)
    record_cloud_authorization(run, 'Explicit isolated test scope; fake providers only.',
        approved_source_sha256=plan['source_sha256'], approved_destinations=plan['cloud_models'])
    result = p.execute_cloud(run, native)
    assert result['status'] == 'reviewed_draft_ready'
    assert result['pending'] is None
    assert result['calls_started'] == native.count
    assert result['total_calls_with_history'] == native.count + 4
    from src.content_factory.corpus_screenplay_v1 import visible_script
    assert (run / '剧本_章节事实与本集状态.md').read_text(encoding='utf-8') == visible_script(DRAFT)
    binding = p.read(run / 'REVIEW_BINDING.json')
    assert binding['root_repairs'] == bool(root_stage)
    assert 'snapshot' in binding['artifact_hashes']
    previous = native.count
    p.execute_cloud(run, native)
    p.execute_local(run, native)
    assert native.count == previous


