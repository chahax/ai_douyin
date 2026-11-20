"""Coordinator acceptance in isolated files; no provider or account traffic."""
from copy import deepcopy
import hashlib
import json
import sys
import threading
from types import SimpleNamespace

import pytest

import src.content_factory as factory_package
from src.content_factory import corpus_production_v3 as production
from src.content_factory import creative_workflow_roles


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def sources(tmp_path, count=3):
    entries = []
    for index in range(1, count + 1):
        text = (f'第{index}章的院子里有一张旧木桌。\n'
                f'小周把第{index}份交接单放到桌上，老陈当面确认。\n'
                '这是用于代码测试的合成材料，不来自真实小说。')
        chapter = {'book_id': 'fixture-book', 'index': index, 'title': f'章{index}',
                   'text': text, 'sha256': hashlib.sha256(text.encode()).hexdigest()}
        path = put(tmp_path / f'chapter_{index:03d}.json', chapter)
        entries.append({'index': index, 'path': str(path), 'sha256': chapter['sha256']})
    manifest = put(tmp_path / 'MANIFEST.json', {
        'book_id': 'fixture-book', 'book_name': '隔离合成材料',
        'status': 'accessible_catalogue_complete', 'chapters': entries})
    history = put(tmp_path / 'HISTORY.json', {'cumulative_calls': 51,
                                           'cumulative_reported_tokens': 1173516,
                                           'pending': None})
    return manifest, history


class Classifier:
    def __init__(self, mode='valid'):
        self.mode = mode
        self.requests = []
        self.lock = threading.Lock()

    def call(self, role, messages, **kwargs):
        payload = json.loads(messages[-1]['content'])
        with self.lock:
            self.requests.append({'role': role, 'payload': payload, 'kwargs': kwargs})
        if self.mode == 'unknown':
            raise TimeoutError('fixture provider outcome is unknown')
        if self.mode == 'invalid':
            value = {'group_id': payload['group_id'], 'assignments': [],
                     'selected_core_passage_ids': []}
        else:
            core = [p for p in payload['source_passages'] if p['scope'] == 'core']
            chosen = {}
            for passage in core:
                chosen.setdefault(passage['chapter_index'], passage['id'])
            value = {'group_id': payload['group_id'],
                     'assignments': [{'passage_id': p['id'], 'categories': ['location', 'event'],
                                      'importance': 'core'} for p in core],
                     'selected_core_passage_ids': list(chosen.values())}
            if self.mode in ('priority_missing', 'classification_missing', 'core_missing'):
                first_chapter = min(p['chapter_index'] for p in core)
                candidates = [p['id'] for p in core if p['chapter_index'] == first_chapter]
                value['selected_core_passage_ids'] = candidates[:len(payload['chapter_indices'])]
                if self.mode == 'classification_missing':
                    value['assignments'].pop()
                if self.mode == 'core_missing':
                    last = max(p['chapter_index'] for p in core)
                    supporting = {p['id'] for p in core if p['chapter_index'] == last}
                    for row in value['assignments']:
                        if row['passage_id'] in supporting:
                            row['importance'] = 'supporting'
        text = json.dumps(value, ensure_ascii=False)
        return SimpleNamespace(text=text,
            metadata={'prompt_tokens': 80, 'completion_tokens': 20,
                      'total_tokens': 100, 'finish_reason': 'stop'},
            response_payload={'done': True, 'done_reason': 'stop', 'model': 'qwen3.5:9b-q4_K_M',
                              'prompt_eval_count': 80, 'eval_count': 20,
                              'message': {'role': 'assistant', 'content': text}})


@pytest.fixture
def providers_configured(monkeypatch):
    monkeypatch.setattr(production, 'preflight', lambda route: {**route, 'digest': 'fixture-local-digest'})
    def role_config(role):
        return SimpleNamespace(provider='minimax' if role == 'writer' else 'deepseek',
                               model='MiniMax-M3' if role == 'writer' else 'deepseek-flash',
                               base_url='https://api.minimaxi.com/v1' if role == 'writer'
                                        else 'https://api.deepseek.com/v1')
    monkeypatch.setattr(creative_workflow_roles, 'role_config', role_config)
    def forbidden_cloud():
        raise AssertionError('local classification must not construct a cloud client')
    monkeypatch.setattr(production, 'NaturalDirectorRoleClients', forbidden_cloud)


@pytest.fixture
def configured(providers_configured, monkeypatch):
    # The contract itself has separate tests. This module tests coordinator gates.
    def forbidden_contract(*args, **kwargs):
        raise AssertionError('a rejected dispatch must not reach the cloud contract')
    stub = SimpleNamespace(run_production=forbidden_contract)
    monkeypatch.setitem(sys.modules, 'src.content_factory.corpus_production_contract_v3', stub)
    monkeypatch.setattr(factory_package, 'corpus_production_contract_v3', stub, raising=False)
    return stub


def prepare_run(tmp_path, configured, count=3, **kwargs):
    manifest, history = sources(tmp_path, count)
    run = tmp_path / 'run'
    plan = production.prepare(manifest, run, user_statement='新版全章本地分类后生产文本，测试范围。',
                              previous_status=history, **kwargs)
    return run, plan


def materials_ready(tmp_path, configured):
    run, plan = prepare_run(tmp_path, configured)
    client = Classifier()
    production.execute_local(run, client)
    return run, plan, client


def test_all_69_fixture_chapters_classified_and_preserved_without_cloud(tmp_path, configured):
    run, plan = prepare_run(tmp_path, configured, count=69, workers=3, group_chars=210)
    classifier = Classifier()
    state = production.execute_local(run, classifier)
    index = production.read(run / 'MATERIALS_INDEX.json')
    pack = production.read(run / 'CLOUD_SOURCE_PACK.json')
    assert state['status'] == 'materials_ready'
    assert state['source_chapters'] == index['source_chapter_count'] == 69
    assert [row['chapter_index'] for row in index['chapter_coverage']] == list(range(1, 70))
    assert {p['chapter_index'] for p in pack['selected_core_passages']} == set(range(1, 70))
    source = production.read(run / 'SOURCE.json')
    for chapter in source['chapters']:
        recovered = ''.join(p['text'] for p in index['passage_catalog']
                            if p['chapter_index'] == chapter['index'])
        assert recovered == chapter['text']
    assert len(classifier.requests) == len(plan['groups'])
    assert all(row['role'] == 'director' for row in classifier.requests)
    assert production.read(run / 'cloud' / 'STATE.json')['calls_started'] == 0
    assert not list(run.glob('*.md'))
    assert state['content_acceptance'] is False and state['pending'] is None
    assert state['total_calls_with_history'] == 51 + len(plan['groups'])
    assert state['total_tokens_with_history'] == 1173516 + 100 * len(plan['groups'])
    assert production.execute_local(run, classifier) == state
    assert len(classifier.requests) == len(plan['groups'])


@pytest.mark.parametrize('artifact,field,value', [
    ('SOURCE.json', 'chapters', []),
    ('PLAN.json', 'workers', 4),
    ('local/PLAN.json', 'new_call_limit', 1000),
    ('cloud/PLAN.json', 'new_token_limit', 99999999),
])
def test_frozen_inputs_changed_before_any_call(tmp_path, configured, artifact, field, value):
    run, _ = prepare_run(tmp_path, configured)
    data = production.read(run / artifact)
    data[field] = value
    put(run / artifact, data)
    client = Classifier()
    with pytest.raises(ValueError, match='frozen_'):
        production.execute_local(run, client)
    assert client.requests == []


def test_authorization_mutation_rejected_before_cloud(tmp_path, configured):
    run, _, client = materials_ready(tmp_path, configured)
    auth = production.read(run / 'AUTHORIZATION.json')
    auth['destinations']['writer']['model'] = 'other-model'
    put(run / 'AUTHORIZATION.json', auth)
    with pytest.raises(ValueError, match='authorization|frozen_'):
        production.execute_cloud(run, client)
    assert production.read(run / 'cloud' / 'STATE.json')['calls_started'] == 0


def test_unknown_local_call_keeps_original_pending_and_never_replays(tmp_path, configured):
    run, _ = prepare_run(tmp_path, configured, workers=1, group_chars=80)
    client = Classifier('unknown')
    with pytest.raises(production.AnalysisStopped, match='local_materials_incomplete'):
        production.execute_local(run, client)
    phase = production.read(run / 'local' / 'STATE.json')
    parent = production.read(run / 'STATE.json')
    assert phase['status'] == 'outcome_unknown'
    assert phase['pending'] and phase['pending_calls'] and parent['pending']
    pending = deepcopy(phase['pending'])
    before = len(client.requests)
    production.execute_local(run, client)
    assert len(client.requests) == before == 1
    assert production.read(run / 'local' / 'STATE.json')['pending'] == pending
    assert production.read(run / 'cloud' / 'STATE.json')['calls_started'] == 0
    assert not (run / 'EXECUTION.lock').exists()


def test_complete_invalid_classification_gets_one_repair_then_stops_without_cloud(tmp_path, configured):
    run, _ = prepare_run(tmp_path, configured, workers=1)
    client = Classifier('invalid')
    with pytest.raises(production.AnalysisStopped, match='local_materials_incomplete'):
        production.execute_local(run, client)
    assert len(client.requests) == 2
    phase = production.read(run / 'local' / 'STATE.json')
    assert phase['status'] == 'needs_attention' and phase['pending'] is None
    assert phase['reported_tokens'] == 200
    assert (run / 'local/groups/G001/INITIAL_REJECTED.json').exists()
    assert (run / 'local/groups/G001/REPAIR_REJECTED.json').exists()
    assert production.read(run / 'cloud' / 'STATE.json')['calls_started'] == 0
    production.execute_local(run, client)
    assert len(client.requests) == 2
    with pytest.raises(ValueError, match='all_local_materials_required'):
        production.execute_cloud(run, client)


def test_cloud_cannot_start_from_prepared_or_partial_local_state(tmp_path, configured):
    run, _ = prepare_run(tmp_path, configured)
    client = Classifier()
    with pytest.raises(ValueError, match='all_local_materials_required'):
        production.execute_cloud(run, client)
    assert client.requests == []


@pytest.mark.parametrize('artifact', ['MATERIALS_INDEX.json', 'CLOUD_SOURCE_PACK.json', 'MATERIALS_BINDING.json'])
def test_cloud_refuses_changed_local_materials_before_any_call(tmp_path, configured, artifact):
    run, _, client = materials_ready(tmp_path, configured)
    value = production.read(run / artifact)
    if artifact == 'MATERIALS_BINDING.json':
        value['index_sha256'] = 'changed'
    else:
        value['book_name'] = 'a different corpus'
    put(run / artifact, value)
    with pytest.raises(ValueError, match='source_materials_binding_changed'):
        production.execute_cloud(run, client)
    assert production.read(run / 'cloud' / 'STATE.json')['calls_started'] == 0


def test_old_or_new_explicit_approval_gate_is_not_bypassed(tmp_path, configured):
    run, _, client = materials_ready(tmp_path, configured)
    marker = {'status': 'not_started_auto_review_rejected', 'cloud_calls_started': 0}
    put(run / 'APPROVAL_REQUIRED.json', marker)
    with pytest.raises(ValueError, match='approval_disposition'):
        production.execute_cloud(run, client)
    assert production.read(run / 'APPROVAL_REQUIRED.json') == marker
    assert production.read(run / 'cloud' / 'STATE.json')['calls_started'] == 0


def test_local_call_cache_tamper_never_causes_redispatch(tmp_path, configured):
    run, _ = prepare_run(tmp_path, configured)
    client = Classifier()
    plan, source = production.read(run / 'PLAN.json'), production.read(run / 'SOURCE.json')
    from src.content_factory import corpus_materials_v3 as materials
    group = plan['groups'][0]
    payload = materials.group_payload(source['chapters'], group, source['manifest']['book_name'])
    call = production._calls(run, 'local', client)
    original = call('MATERIALS_G001', 'director', 'JSON', payload)
    assert original['group_id'] == 'G001'
    put(run / 'local/MATERIALS_G001.json', {'group_id': 'changed'})
    with pytest.raises(ValueError, match='cached_call_binding_changed'):
        call('MATERIALS_G001', 'director', 'JSON', payload)
    assert len(client.requests) == 1


@pytest.mark.parametrize('limit', [0, 25, True])
def test_cloud_call_limit_must_be_frozen_bounded_integer(tmp_path, configured, limit):
    manifest, history = sources(tmp_path)
    with pytest.raises(ValueError, match='cloud_call_limit_out_of_range'):
        production.prepare(manifest, tmp_path / 'run', user_statement='测试',
                           previous_status=history, cloud_call_limit=limit)
    assert not (tmp_path / 'run').exists()


def test_source_mutation_detected_during_prepare(tmp_path, configured):
    manifest, history = sources(tmp_path)
    row = production.read(manifest)['chapters'][0]
    chapter = production.read(row['path'])
    chapter['text'] += '被篡改的文字'
    put(type(tmp_path)(row['path']), chapter)
    with pytest.raises(ValueError, match='source_changed'):
        production.prepare(manifest, tmp_path / 'run', user_statement='测试', previous_status=history)
    assert not (tmp_path / 'run').exists()


def test_pending_history_never_transfers_to_new_scope(tmp_path, configured):
    manifest, history = sources(tmp_path)
    put(history, {'calls_started': 8, 'reported_tokens': 900, 'pending': ['old-call']})
    with pytest.raises(ValueError, match='history_pending'):
        production.prepare(manifest, tmp_path / 'run', user_statement='测试', previous_status=history)
    assert not (tmp_path / 'run').exists()


def test_prepare_rejects_oversized_local_request_before_any_artifact(tmp_path, configured):
    manifest, history = sources(tmp_path)
    with pytest.raises(ValueError, match='local_group_input_exceeds_frozen_context'):
        production.prepare(manifest, tmp_path / 'run', user_statement='测试', previous_status=history,
            local_route={'provider': 'ollama', 'model': 'fixture', 'endpoint': 'http://127.0.0.1:11435',
                         'max_tokens': 8192, 'context': 8192})
    assert not (tmp_path / 'run').exists()


def test_accepted_group_tamper_blocks_new_groups_before_dispatch(tmp_path, configured):
    from src.content_factory import corpus_materials_v3 as materials
    run, plan = prepare_run(tmp_path, configured, workers=2, group_chars=80)
    source = production.read(run / 'SOURCE.json')
    group = plan['groups'][0]
    client = Classifier()
    payload = materials.group_payload(source['chapters'], group, source['manifest']['book_name'])
    production._phase(run / 'local', run / 'local/groups' / group['id'],
        'MATERIALS_' + group['id'], 'director', materials.CLASSIFY_PROMPT, payload,
        materials.group_schema(group, payload),
        lambda raw: materials.validate(raw, source['chapters'], group),
        production._calls(run, 'local', client))
    original = run / 'local/groups' / group['id'] / 'INITIAL.json'
    changed = production.read(original)
    changed['selected_core_passage_ids'] = []
    put(original, changed)
    with pytest.raises(production.AnalysisStopped, match='accepted_analysis_changed'):
        production.execute_local(run, client)
    assert len(client.requests) == 1
    assert production.read(run / 'local/STATE.json')['calls_started'] == 1
    assert production.read(run / 'cloud/STATE.json')['calls_started'] == 0


@pytest.mark.parametrize('changed_field', ['provider', 'model', 'base_url'])
def test_pinned_cloud_client_refuses_runtime_route_drift(configured, monkeypatch, changed_field):
    expected = production._cloud_routes()
    invoked = []
    underlying = SimpleNamespace(call=lambda *args, **kwargs: invoked.append((args, kwargs)))
    monkeypatch.setattr(production, 'NaturalDirectorRoleClients', lambda: underlying)
    pinned = production.PinnedCloudClient(expected)
    changed = deepcopy(expected)
    changed['director'][changed_field] = 'different'
    monkeypatch.setattr(production, '_cloud_routes', lambda: changed)
    with pytest.raises(ValueError, match='cloud_provider_or_model_changed'):
        pinned.call('director', [{'role': 'user', 'content': 'JSON'}])
    assert invoked == []


def test_unknown_cloud_call_is_not_replayed_and_keeps_its_scope(tmp_path, configured):
    run, plan, _ = materials_ready(tmp_path, configured)
    invoked = []
    def run_contract(call, *args, **kwargs):
        return call('WORLD_BIBLE', 'director', 'JSON', {'fixture': True})
    configured.run_production = run_contract
    def unknown(*args, **kwargs):
        invoked.append(1)
        raise TimeoutError('fixture cloud transport outcome unknown')
    client = SimpleNamespace(call=unknown)
    with pytest.raises(TimeoutError):
        production.execute_cloud(run, client)
    phase = production.read(run / 'cloud/STATE.json')
    assert phase['status'] == 'outcome_unknown' and phase['pending']
    request = production.read(run / 'cloud/CALL_001.json')
    assert request['analysis_route']['models'] == plan['cloud_models']
    assert request['source_sha256'] == plan['source_sha256']
    assert production.read(run / 'STATE.json')['pending'] == phase['pending']
    with pytest.raises(ValueError, match='all_local_materials_required'):
        production.execute_cloud(run, client)
    assert invoked == [1]


class CompleteProductionClient:
    """Model response fixture; all production orchestration/validators are real."""
    def __init__(self, framework, mode):
        self.framework = framework
        self.mode = mode
        self.events = []
        self.design = ('世界：小镇老屋，林月和弟弟林河共同生活。\n'
                       '画风与小环境：门边自然日光，低饱和木色为明确的美术补足。\n'
                       '人物和时间：林河回屋，林月接过钥匙；修门仍是明日计划。\n'
                       '镜头：先交代屋内两人的关系与站位，再跟随交接动作切近景。')
        self.draft = ('世界与人物：小镇老屋中的林月和弟弟林河。\n'
                      '地点与时间：老屋门边，白天；钥匙起初在林河手里。\n'
                      '### 【0—20秒】\n'
                      '动作：林河将钥匙交给林月，林月接过后看向弟弟，镜头跟随交接。\n'
                      '林月：“明天再修门。”')

    def call(self, role, messages, **kwargs):
        from src.content_factory.screenplay_revision_v3 import source_sha
        from test_screenplay_review_cycle_v2 import review_for as screenplay_review
        payload = json.loads(messages[-1]['content'])
        self.events.append((role, payload, kwargs))
        if 'reviewed_artifact_sha256' in payload:
            schema = payload['output_schema']['properties']
            out = {'reviewed_artifact_sha256': payload['reviewed_artifact_sha256'],
                   'decision': 'pass',
                   'checked_source_passage_ids': schema['checked_source_passage_ids']['items']['enum'],
                   'checked_chapter_indices': schema['checked_chapter_indices']['items']['enum'],
                   'checks': {key: 'pass' for key in schema['checks']['properties']},
                   'issues': [], 'summary': '隔离测试响应，不是实际内容验收。'}
        elif 'chapter_coverage' in payload:
            out = deepcopy(self.framework)
        elif role == 'writer' and 'source_fact_contract' not in payload:
            out = self.design
        elif 'source_sha256' in payload and 'screenplay' not in payload:
            chapters = payload['selected_original_chapters']
            chapter = next(row for row in chapters if row['index'] == 2)
            out = {'source_sha256': source_sha(chapters),
                   'facts': [{'id': 'F1', 'kind': 'ownership', 'statement': '林河将钥匙交给林月。',
                              'source_evidence': [{'chapter_index': 2, 'quote': chapter['text']}]}]}
        elif role == 'writer':
            out = self.draft
        elif 'screenplay' in payload:
            out = screenplay_review(payload)
            if 'segment_timing' in messages[0]['content']:
                measured = payload['measured_segments']
                out['segment_timing'] = [{
                    'range': row['range'],
                    'serial_actions': [{'evidence_id': row['evidence'][0]['id'],
                                        'seconds': 21 if self.mode == 'timing_overflow' else 2}],
                    'parallel_actions': [], 'reason': '测试动作持续时间。'} for row in measured]
        else:
            raise AssertionError(f'unrecognized real-production input: {sorted(payload)}')
        return SimpleNamespace(text=out if isinstance(out, str) else json.dumps(out, ensure_ascii=False),
            metadata={'prompt_tokens': 80, 'completion_tokens': 20, 'total_tokens': 100,
                      'finish_reason': 'stop'}, response_payload={})


@pytest.mark.parametrize('mode', ['pass', 'timing_overflow'])
def test_real_contract_and_v4_integrate_after_local_materials(tmp_path, providers_configured, mode):
    # Unlike the gate tests above, neither run_production nor run_cycle is stubbed.
    from src.content_factory import corpus_production_contract_v3 as contract
    from test_corpus_production_contract_v3 import inputs
    from src.content_factory.screenplay_review_cycle_v2 import text_sha
    assert callable(contract.run_production)
    framework, _, chapters = inputs()
    entries = []
    for chapter in chapters:
        chapter = {**chapter, 'book_id': 'integration-fixture'}
        path = put(tmp_path / f"chapter_{chapter['index']}.json", chapter)
        entries.append({'path': str(path), 'sha256': chapter['sha256'], 'index': chapter['index']})
    manifest = put(tmp_path / 'MANIFEST.json', {'book_id': 'integration-fixture',
        'book_name': '合成钥匙故事', 'status': 'accessible_catalogue_complete', 'chapters': entries})
    history = put(tmp_path / 'HISTORY.json', {'calls_started': 51, 'reported_tokens': 1173516})
    run = tmp_path / 'run'
    production.prepare(manifest, run, user_statement='全链隔离接口测试', previous_status=history,
                       workers=2, group_chars=50, target_seconds=20)
    local = Classifier()
    assert production.execute_local(run, local)['status'] == 'materials_ready'
    cloud = CompleteProductionClient(framework, mode)
    if mode == 'timing_overflow':
        with pytest.raises(ValueError, match='review_cycle_revision_limit_reached'):
            production.execute_cloud(run, cloud)
        assert production.read(run / 'STATE.json')['status'] == 'needs_attention'
        assert not (run / '剧本_新版全章分类生产.md').exists()
        assert not (run / 'REVIEW_BINDING.json').exists()
        assert production.read(run / 'cloud/TIMING_CONSTRAINTS_00.json')['blocking_issues']
        assert production.read(run / 'cloud/TIMING_CONSTRAINTS_01.json')['blocking_issues']
        assert production.read(run / 'cloud/STATE.json')['pending'] is None
        return
    state = production.execute_cloud(run, cloud)
    assert state['status'] == 'reviewed_draft_ready' and state['selected_chapters'] == [2, 3]
    assert state['content_acceptance'] == 'machine_review_passed_awaiting_independent_review'
    assert state['pending'] is None and not state['media_generated']
    names = [production.read(path)['name'] for path in sorted((run / 'cloud').glob('CALL_*.json'))]
    assert names == ['FRAMEWORK_0', 'FRAMEWORK_REVIEW_0', 'VISUAL_WORLD_DESIGN_0',
                     'DESIGN_REVIEW_0', 'FACT_CONTRACT', 'SCREENPLAY_FRESH',
                     'REVIEW_00', 'REVIEW_TIMING_00']
    assert [role for role, _, _ in cloud.events] == [
        'director', 'director', 'writer', 'director', 'director', 'writer', 'director', 'director']
    assert cloud.events[4][1]['episode_brief']['chapter_indices'] == [2, 3]
    writer = cloud.events[5][1]
    assert writer['global_bible'] == framework
    assert writer['visual_world_design'] == cloud.design
    assert writer['episode_brief']['chapter_indices'] == [2, 3]
    assert [row['index'] for row in writer['selected_original_chapters']] == [1, 2, 3, 4]
    assert 'previous_draft' not in writer and 'selection' not in writer
    assert cloud.events[6][1] == cloud.events[7][1]  # independent whole-draft reviews
    binding = production.read(run / 'REVIEW_BINDING.json')
    assert binding['version'] == 'screenplay_revision/v4'
    assert binding['production_contract_version'] == contract.VERSION
    assert binding['draft_sha256'] == text_sha((run / '剧本_新版全章分类生产.md').read_text(encoding='utf-8'))
    assert production.read(run / 'cloud/STATE.json')['calls_started'] == 8
    before = len(cloud.events)
    assert production.execute_cloud(run, cloud) == state
    assert len(cloud.events) == before


@pytest.mark.parametrize('artifact', ['CLOUD_IMPLEMENTATION_PIN.json', 'CLOUD_EVIDENCE_PACK.json',
                                      'CLOUD_EVIDENCE_BINDING.json'])
def test_frozen_expanded_evidence_and_code_pin_reject_tamper_before_cloud(tmp_path, configured, artifact):
    run, _, client = materials_ready(tmp_path, configured)
    original = production.prepare_cloud(run)
    assert original == production.read(run / 'CLOUD_EVIDENCE_PACK.json')
    pin = production.read(run / 'CLOUD_IMPLEMENTATION_PIN.json')
    assert {'corpus_production_v3.py', 'corpus_production_contract_v3.py',
            'screenplay_revision_v4.py'} <= pin['source_files'].keys()
    changed = production.read(run / artifact)
    changed['tampered'] = True
    put(run / artifact, changed)
    before = len(client.requests)
    with pytest.raises(ValueError, match='frozen_production_artifact_changed'):
        production.execute_cloud(run, client)
    assert len(client.requests) == before
    assert production.read(run / 'cloud/STATE.json')['calls_started'] == 0


def failed_priority_run(tmp_path, configured, mode='priority_missing'):
    manifest, history = sources(tmp_path)
    index = production.read(manifest)
    # Three passages per chapter let a schema-valid priority list choose only
    # chapter 1 while every source passage remains classified as core.
    for row in index['chapters']:
        chapter = production.read(row['path'])
        chapter['text'] = '\n'.join(f'第{chapter["index"]}章第{n}段：' + ('院子里的木桌旁记录交接。' * 39)
                                    for n in range(1, 4))
        chapter['sha256'] = hashlib.sha256(chapter['text'].encode()).hexdigest()
        row['sha256'] = chapter['sha256']
        put(type(tmp_path)(row['path']), chapter)
    put(manifest, index)
    run = tmp_path / 'run'
    production.prepare(manifest, run, user_statement='已知完整分类的核心证据适配测试',
                       previous_status=history, workers=1, group_chars=10000)
    client = Classifier(mode)
    with pytest.raises(production.AnalysisStopped, match='local_materials_incomplete'):
        production.execute_local(run, client)
    assert len(client.requests) == 2
    assert production.read(run / 'local/STATE.json')['pending'] is None
    return run, client


def test_adopt_known_priority_failure_preserves_originals_and_runs_no_models(tmp_path, configured):
    run, client = failed_priority_run(tmp_path, configured)
    old_local = production.read(run / 'local/STATE.json')
    old_root = production.read(run / 'STATE.json')
    original_files = {p: p.read_bytes() for p in (run / 'local').rglob('*') if p.is_file()}
    original_raw = production.read(run / 'local/groups/G001/REPAIR.json')
    assert production.read(run / 'local/groups/G001/REPAIR_REJECTED.json')['reason'] == 'selected_core_chapter_coverage_incomplete'
    state = production.adopt_core_materials(run)
    assert state['status'] == 'materials_ready' and state['content_acceptance'] is False
    audit = production.read(run / 'CORE_MATERIAL_ADOPTION.json')
    assert audit['old_root_state'] == old_root and audit['old_local_state'] == old_local
    assert audit['new_model_calls'] == 0 and audit['original_failures_unchanged']
    assert audit['groups'][0]['warnings'][0]['missing_chapter_indices'] == [2, 3]
    assert all(path.read_bytes() == data for path, data in original_files.items())
    assert production.read(run / 'local/STATE.json') == old_local
    assert len(client.requests) == 2
    pack = production.prepare_cloud(run)
    assert pack['priority_passage_ids'] == original_raw['selected_core_passage_ids']
    assert {row['chapter_index'] for row in pack['selected_core_passages']} == {1, 2, 3}
    assert len(pack['included_core_passage_ids']) > len(pack['priority_passage_ids'])
    assert production.read(run / 'cloud/STATE.json')['calls_started'] == 0
    assert production.adopt_core_materials(run) == state
    assert len(client.requests) == 2


@pytest.mark.parametrize('field,value', [
    ('pending', ['old-original-call']),
    ('pending_calls', {'old-original-call': {'name': 'MATERIALS_G001'}}),
    ('status', 'outcome_unknown'),
])
def test_core_adoption_cannot_settle_pending_or_unknown_local_call(tmp_path, configured, field, value):
    run, client = failed_priority_run(tmp_path, configured)
    local = production.read(run / 'local/STATE.json')
    local[field] = value
    put(run / 'local/STATE.json', local)
    with pytest.raises(ValueError, match='completed_local_classifications_required'):
        production.adopt_core_materials(run)
    assert production.read(run / 'local/STATE.json') == local
    assert not (run / 'CORE_MATERIAL_ADOPTION.json').exists()
    assert len(client.requests) == 2


@pytest.mark.parametrize('mutation,error', [
    ('not_done', 'native_completion_required'),
    ('usage', 'native_completion_required'),
    ('content', 'original_classification_receipt_changed'),
])
def test_core_adoption_requires_complete_untampered_native_receipt(tmp_path, configured, mutation, error):
    run, client = failed_priority_run(tmp_path, configured)
    response_path = run / 'local/RESPONSE_002.json'
    response = production.read(response_path)
    if mutation == 'not_done':
        response['response_payload']['done'] = False
    elif mutation == 'usage':
        response['response_payload']['eval_count'] += 1
    else:
        response['response_payload']['message']['content'] += 'changed'
    put(response_path, response)
    with pytest.raises(ValueError, match=error):
        production.adopt_core_materials(run)
    assert not (run / 'CORE_MATERIAL_ADOPTION.json').exists()
    assert production.read(run / 'cloud/STATE.json')['calls_started'] == 0
    assert len(client.requests) == 2


@pytest.mark.parametrize('mode,error', [
    ('classification_missing', 'materials_schema_invalid|passage_coverage'),
    ('core_missing', 'classification_core_chapter_coverage_incomplete'),
])
def test_adoption_does_not_relax_classification_or_core_coverage(tmp_path, configured, mode, error):
    run, client = failed_priority_run(tmp_path, configured, mode)
    local = production.read(run / 'local/STATE.json')
    with pytest.raises(ValueError, match=error):
        production.adopt_core_materials(run)
    assert production.read(run / 'local/STATE.json') == local
    assert not (run / 'MATERIALS_INDEX.json').exists()
    assert len(client.requests) == 2
