from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.content_factory.screenplay_roles_v5 import (ROLES, CHECKS, allocate, validate_stage, evidence_from, digest, messages_for, output_schema, repair_payload)
from src.content_factory.screenplay_role_runner_v5 import prepare, execute, benchmark, local_routes, hybrid_routes, read, validate_routes, report, record_evaluation


def fixtures():
    source = {'chapters': [{'index': 1, 'text': '小林把自己的钥匙交给母亲。母亲收好钥匙，提醒他路上小心。'}],
              'episode_intent': '出门交钥匙', 'target_seconds': 30}
    source['evidence'] = evidence_from(source['chapters'])
    evidence = ['CH1-P1']
    facts = {'world': '家中出门前', 'characters': [
        {'id': 'C1', 'name': '小林', 'relationship': '儿子', 'evidence_ids': evidence},
        {'id': 'C2', 'name': '母亲', 'relationship': '小林母亲', 'evidence_ids': evidence}],
        'facts': [{'id': f'F{i}', 'statement': text, 'evidence_ids': evidence} for i, text in enumerate(
            ['钥匙属于小林', '小林交给母亲', '母亲收好钥匙'], 1)]}
    brief = {'episode': '交接钥匙', 'opening': '小林拿钥匙', 'ending': '母亲收好', 'scope': '一次出门交接',
             'cast': ['C1', 'C2'], 'required_fact_ids': ['F1', 'F2', 'F3'], 'relevant_evidence_ids': evidence}
    outline = {'beats': [{'id': f'B{i}', 'event': event, 'location': '家门口', 'cast': ['C1', 'C2'],
                          'start_state': start, 'end_state': end, 'transition_from_previous': '连续',
                          'fact_ids': [f'F{i}'], 'dialogue': [{'speaker': speaker, 'listener': listener, 'text': text}],
                          'serial_seconds': 1, 'parallel_action': '看向对方'}
                         for i, event, start, end, speaker, listener, text in [
                             (1, '出示', '小林持钥匙', '小林举起钥匙', 'C1', 'C2', '钥匙在这。'),
                             (2, '交接', '小林举着', '母亲拿着', 'C1', 'C2', '帮我收好。'),
                             (3, '收好', '母亲拿着', '母亲放入包里', 'C2', 'C1', '路上小心。')]]}
    staging = {'scenes': [{'beat_id': f'B{i}', 'action': '按节点交接钥匙', 'expressions_and_gaze': '母子对视',
                          'environment_light': '窗边自然光照亮家门口', 'camera_and_transition': '连续中景跟随交接'} for i in range(1, 4)]}
    review = {'decision': 'pass', 'checks': [{'name': k, 'passed': True, 'reason': '对照来源与当前稿可成立'} for k in CHECKS],
              'issues': [], 'summary': '本次通过'}
    source_review = {'checks': [{'id': r['id'], 'supported': True, 'reason': '与引用原文相符', 'evidence_ids': evidence}
                                for r in facts['characters'] + facts['facts']],
                     'world_supported': True, 'world_reason': '来源明确'}
    result = {'facts': facts, 'source_review': source_review, 'brief': brief, 'outline': outline, 'staging': staging, 'review': review}
    result['allocated_beats'] = allocate(outline, 30)
    result['integrate'] = render(result)
    return source, result


def render(artifacts):
    names = {c['id']: c['name'] for c in artifacts['facts']['characters']}
    result = '世界框架：母子在家门口交接钥匙。\n'
    for beat in artifacts['allocated_beats']:
        result += f'### 【{beat["range"]}秒】\n地点：家门口。动作：{beat["event"]}，双方视线跟随钥匙。\n'
        result += '\n'.join(names[d['speaker']] + '：“' + d['text'] + '”' for d in beat['dialogue']) + '\n'
    return result


class FakeClient:
    def __init__(self, mode='pass'):
        self.mode = mode; self.calls = []; self.review_count = 0

    def preflight(self, routes):
        return {r: {'model': v['model'], 'digest': 'test-weight'} for r, v in routes.items()}

    def call(self, role, route, messages):
        self.calls.append((role, deepcopy(route), deepcopy(messages)))
        if self.mode == 'timeout':
            raise TimeoutError('simulated unknown')
        source, a = fixtures()
        payload = json.loads(messages[-1]['content'])
        if role == 'integrate':
            a.update(facts=payload['facts'], allocated_beats=payload['allocated_beats'])
            value = render(a)
        else:
            value = deepcopy(a[role])
        if self.mode == 'bad_evidence' and role == 'facts':
            value['facts'][0]['evidence_ids'] = ['CH999-P1']
        if self.mode == 'bad_semantic_source' and role == 'source_review':
            value['checks'][0].update(supported=False, reason='关系与原文冲突')
        if role == 'review':
            self.review_count += 1
            if self.mode == 'revise' and self.review_count == 1:
                value['decision'] = 'revise'; value['checks'][0]['passed'] = False
                value['issues'] = [{'owner': 'staging', 'beat_id': 'B1', 'draft_quote': '双方视线跟随钥匙',
                                    'evidence_ids': [], 'reason': '补足听者反应', 'requested_change': '具体化反应'}]
        return {'text': value if isinstance(value, str) else json.dumps(value, ensure_ascii=False),
                'done': self.mode != 'length', 'native': {'fixture': True}, 'response_model': route['model'],
                'input_tokens': 10, 'output_tokens': 20}


def prepared(tmp_path, client):
    source, _ = fixtures(); run = tmp_path / 'run'
    prepare(run, source['chapters'], source['episode_intent'], local_routes(), user_statement='开发测试',
            target_seconds=30, client=client)
    return run


def test_pipeline_routes_roles_persists_source_and_requires_separate_acceptance(tmp_path):
    client = FakeClient(); run = prepared(tmp_path, client)
    state = execute(run, client)
    assert state['status'] == 'machine_review_passed' and state['calls_started'] == 7
    assert [c[0] for c in client.calls] == list(ROLES)
    assert state['quality_acceptance'] == 'awaiting_independent_acceptance'
    assert not state['automatic_media_dispatch']
    execute(run, client); assert len(client.calls) == 7


def test_semantic_repair_invalidates_only_responsible_stage_and_successors(tmp_path):
    client = FakeClient('revise'); run = prepared(tmp_path, client)
    result = execute(run, client)
    assert result['status'] == 'machine_review_passed'
    assert [c[0] for c in client.calls][7:] == ['staging', 'integrate', 'review']
    assert read(run / 'INVALIDATION_01.json')['invalidated'] == ['staging', 'integrate', 'review']
    assert (run / 'ACCEPTED_integrate_00.json').exists() and (run / 'ACCEPTED_integrate_01.json').exists()


def test_unknown_call_preserves_original_and_never_replays(tmp_path):
    client = FakeClient('timeout'); run = prepared(tmp_path, client)
    with pytest.raises(TimeoutError): execute(run, client)
    assert read(run / 'STATE.json')['pending'] == 1
    execute(run, client); assert len(client.calls) == 1


def test_truncation_is_not_a_content_retry(tmp_path):
    client = FakeClient('length'); run = prepared(tmp_path, client)
    with pytest.raises(ValueError, match='incomplete'): execute(run, client)
    assert len(client.calls) == 1 and read(run / 'STATE.json')['pending'] is None


def test_invalid_evidence_stops_after_one_owned_repair(tmp_path):
    client = FakeClient('bad_evidence'); run = prepared(tmp_path, client)
    with pytest.raises(ValueError, match='validation_failed'): execute(run, client)
    assert [c[0] for c in client.calls] == ['facts', 'facts']
    assert not (run / 'ACCEPTED_facts_00.json').exists()


def test_supported_quote_id_does_not_allow_failed_source_entailment_to_propagate(tmp_path):
    client = FakeClient('bad_semantic_source'); run = prepared(tmp_path, client)
    with pytest.raises(ValueError, match='source_fidelity'): execute(run, client)
    assert [c[0] for c in client.calls] == ['facts', 'source_review', 'facts', 'source_review']
    assert not (run / 'ACCEPTED_brief_00.json').exists()


@pytest.mark.parametrize('mutation', ['speaker', 'unquoted', 'extra_line', 'time'])
def test_integration_cannot_silently_change_approved_dialogue_or_timing(mutation):
    source, a = fixtures(); draft = a['integrate']
    if mutation == 'speaker': draft = draft.replace('小林：“钥匙在这。”', '母亲：“钥匙在这。”')
    if mutation == 'unquoted': draft = draft.replace('“钥匙在这。”', '钥匙在这。')
    if mutation == 'extra_line': draft += '\n母亲：还有另一句话。'
    if mutation == 'time': draft = draft.replace('0—10', '0—9')
    with pytest.raises(ValueError): validate_stage('integrate', draft, source, a)


def test_outline_requires_in_scene_speakers_and_fact_coverage():
    source, a = fixtures(); b = deepcopy(a['outline']); b['beats'][0]['dialogue'][0]['speaker'] = 'C99'
    with pytest.raises(ValueError, match='not_in_scene'): validate_stage('outline', b, source, a)
    b = deepcopy(a['outline']); b['beats'][0]['fact_ids'] = ['F2']
    with pytest.raises(ValueError, match='required_facts_missing'): validate_stage('outline', b, source, a)


def test_fact_quote_ids_exist_but_do_not_establish_semantic_truth():
    source, a = fixtures(); validate_stage('facts', a['facts'], source, a)
    assert 'semantic_pass' not in a['facts']  # Semantic quality is a separate review.


def test_model_routes_cannot_silently_use_cloud_or_remote_ollama():
    routes = local_routes(); routes['facts']['endpoint'] = 'https://example.com'
    with pytest.raises(ValueError, match='loopback'): validate_routes(routes)
    routes = local_routes(); routes['integrate'].update(provider='minimax', endpoint='', model='MiniMax-M3')
    with pytest.raises(ValueError, match='cloud_scope'): validate_routes(routes)
    validate_routes(routes, cloud_authorized=True)


def test_review_cannot_pass_with_failed_checks_or_fabricated_quotes():
    source, a = fixtures(); value = deepcopy(a['review']); value['checks'][0]['passed'] = False
    with pytest.raises(ValueError, match='inconsistent'): validate_stage('review', value, source, a)
    value['decision'] = 'revise'
    value['issues'] = [{'owner': 'outline', 'beat_id': 'B1', 'draft_quote': '并未出现', 'evidence_ids': [],
                        'reason': '错误', 'requested_change': '修订'}]
    with pytest.raises(ValueError, match='evidence_invalid'): validate_stage('review', value, source, a)


def test_frozen_route_changes_are_rejected(tmp_path):
    client = FakeClient(); run = prepared(tmp_path, client); plan = read(run / 'PLAN.json')
    plan['routes']['facts']['model'] = 'other'
    (run / 'PLAN.json').write_text(json.dumps(plan), encoding='utf8')
    with pytest.raises(ValueError, match='frozen_inputs_changed'): execute(run, client)
    assert not client.calls


def test_benchmark_uses_identical_input_and_different_model_without_ranking(tmp_path):
    client = FakeClient(); run = prepared(tmp_path, client); execute(run, client)
    routes = local_routes('second-model'); out = tmp_path / 'benchmark'
    state = benchmark(run, 1, out, routes, user_statement='比较同输入', client=client)
    assert state['status'] == 'benchmark_complete'
    assert read(out / 'CALL_001.json')['messages_sha256'] == read(run / 'CALL_001.json')['messages_sha256']
    assert read(out / 'METRICS.json')['ranking'] is None
    assert client.calls[-1][1]['model'] == 'second-model'
    summary = report([run, out])
    assert summary['ranking'] is None and len(summary['identical_input_comparisons']) == 1
    assert all(row['semantic_score'] is None for row in summary['by_task_model'])


def test_new_model_weights_under_same_tag_stop_before_dispatch(tmp_path):
    client = FakeClient(); run = prepared(tmp_path, client)
    client.preflight = lambda routes: {r: {'model': v['model'], 'digest': 'changed'} for r, v in routes.items()}
    with pytest.raises(ValueError, match='installed_model_changed'): execute(run, client)
    assert not client.calls


def test_known_cloud_truncation_keeps_receipt_without_unknown_or_retry(tmp_path):
    from src.content_factory.creative_workflow_roles import RoleResponseError
    client = FakeClient(); run = prepared(tmp_path, client)
    usage = {'prompt_tokens': 20, 'completion_tokens': 10, 'total_tokens': 30}
    def truncated(*args):
        raise RoleResponseError('truncated', {**usage, 'response_id': 'known', 'finish_reason': 'length'},
            response_text='partial', response_payload={'id': 'known', 'usage': usage, 'choices': [{'finish_reason': 'length'}]})
    client.call = truncated
    with pytest.raises(RoleResponseError): execute(run, client)
    state = read(run / 'STATE.json')
    assert state['status'] == 'needs_attention' and state['pending'] is None
    assert state['input_tokens'] == 20 and state['output_tokens'] == 10
    assert read(run / 'ERROR_001.json')['native']['id'] == 'known'


def test_dynamic_schema_rejects_extra_world_row_before_generation():
    from jsonschema import Draft202012Validator, ValidationError
    source, a = fixtures(); schema = output_schema('source_review', {'facts': a['facts']})
    check = deepcopy(a['source_review']); check['checks'][0]['id'] = 'WORLD'
    with pytest.raises(ValidationError): Draft202012Validator(schema).validate(check)
    assert schema['properties']['checks']['minItems'] == 5


def test_dynamic_character_fact_and_speaker_constraints_are_independent():
    from jsonschema import Draft202012Validator, ValidationError
    source, a = fixtures(); schema = output_schema('outline', {'facts': a['facts'], 'brief': a['brief']})
    beat = schema['properties']['beats']['items']['properties']
    assert beat['cast']['items']['enum'] == ['C1', 'C2']
    assert beat['fact_ids']['items']['enum'] == ['F1', 'F2', 'F3']
    assert beat['dialogue']['items']['properties']['speaker']['enum'] == ['C1', 'C2']
    assert beat['dialogue']['items']['properties']['listener']['enum'] == ['C1', 'C2', 'ALL']
    Draft202012Validator(schema).validate(a['outline'])
    bad = deepcopy(a['outline']); bad['beats'][0]['cast'] = ['F1']
    with pytest.raises(ValidationError): Draft202012Validator(schema).validate(bad)


def test_hybrid_task_mapping_keeps_each_frozen_provider(tmp_path):
    source, _ = fixtures(); client = FakeClient(); run = tmp_path / 'hybrid'
    routes = hybrid_routes()
    prepare(run, source['chapters'], source['episode_intent'], routes, user_statement='离线混合接线验证',
            target_seconds=30, cloud_authorized=True, client=client)
    execute(run, client)
    assert {r: route['provider'] for r, route, _ in client.calls} == {
        'facts': 'ollama', 'source_review': 'deepseek', 'brief': 'deepseek', 'outline': 'ollama',
        'staging': 'ollama', 'integrate': 'minimax', 'review': 'deepseek'}


def test_approval_rejection_blocks_dispatch_even_when_prepared(tmp_path):
    client = FakeClient(); run = prepared(tmp_path, client)
    (run / 'APPROVAL_REQUIRED.json').write_text('{}', encoding='utf8')
    with pytest.raises(ValueError, match='approval_pending'): execute(run, client)
    assert not client.calls


def test_original_chapter_hash_is_checked():
    with pytest.raises(ValueError, match='sha256'):
        evidence_from([{'index': 1, 'text': '改过的原文', 'sha256': 'old'}])


def test_independent_evaluation_preserves_native_and_rejects_fake_evidence(tmp_path):
    client = FakeClient(); run = prepared(tmp_path, client); execute(run, client)
    before = (run / 'RESPONSE_001.json').read_bytes()
    bad = {'evaluator': 'assistant_source_review', 'semantic_pass': False,
           'findings': [{'output_quote': '从来没有的句子', 'source_ids': [], 'reason': '错'}]}
    with pytest.raises(ValueError, match='evidence'): record_evaluation(run, 1, bad)
    value = {'evaluator': 'assistant_source_review', 'semantic_pass': True, 'findings': []}
    record_evaluation(run, 1, value)
    with pytest.raises(FileExistsError): record_evaluation(run, 1, value)
    assert (run / 'RESPONSE_001.json').read_bytes() == before
    assert report([run])['by_task_model'][0]['independent_evaluations'][0]['semantic_pass']


def test_native_ollama_request_uses_schema_and_no_hidden_retry(monkeypatch):
    import io
    from src.content_factory.screenplay_role_runner_v5 import RoleClient
    import src.content_factory.screenplay_role_runner_v5 as runner
    source, a = fixtures(); requests = []
    route = local_routes()['source_review']
    def respond(request, timeout):
        requests.append(json.loads(request.data))
        native = {'model': route['model'], 'done': True, 'done_reason': 'stop', 'prompt_eval_count': 10,
                  'eval_count': 20, 'message': {'content': json.dumps(a['source_review'])}}
        return io.BytesIO(json.dumps(native).encode())
    monkeypatch.setattr(runner.urllib.request, 'urlopen', respond)
    result = RoleClient().call('source_review', route, messages_for('source_review', source, a))
    assert result['done'] and len(requests) == 1
    assert requests[0]['keep_alive'] == 0 and requests[0]['think'] is True
    assert requests[0]['format']['properties']['checks']['maxItems'] == 5


def test_benchmark_tampered_reference_stops_before_new_run(tmp_path):
    client = FakeClient(); run = prepared(tmp_path, client); execute(run, client)
    p = run / 'CALL_001.json'; claim = read(p); claim['messages_sha256'] = 'changed'
    p.write_text(json.dumps(claim), encoding='utf8')
    target = tmp_path / 'compare'
    with pytest.raises(ValueError, match='inputs_not_identical'):
        benchmark(run, 1, target, local_routes('other'), user_statement='对比', client=client)
    assert not target.exists()


def test_integrator_repair_uses_only_model_planned_dialogue_not_failed_fulltext():
    source, a = fixtures()
    repair = repair_payload('integrate', '整篇失败稿旧长句', 'bad_line_format', a)
    assert 'previous_output' not in repair and '整篇失败稿旧长句' not in json.dumps(repair, ensure_ascii=False)
    assert repair['required_dialogue_layout'][0]['lines'] == ['小林：“钥匙在这。”']


def test_report_can_read_old_role_sets_but_not_reexecute_them(tmp_path):
    client = FakeClient(); run = prepared(tmp_path, client)
    plan = read(run / 'PLAN.json'); plan['version'] = 'screenplay_roles/v5-experimental'
    plan['routes'].pop('source_review'); plan['model_pins'].pop('source_review')
    state = read(run / 'STATE.json'); state['plan_sha256'] = digest(plan)
    (run / 'PLAN.json').write_text(json.dumps(plan), encoding='utf8')
    (run / 'STATE.json').write_text(json.dumps(state), encoding='utf8')
    assert report([run])['runs'][0]['calls'] == 0
    with pytest.raises(ValueError): execute(run, client)
    assert not client.calls
