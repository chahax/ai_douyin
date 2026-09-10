"""Text-only outline contracts: no model, media engine or project data writes."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.trend_intelligence.script_outline import build_outline_messages, text_sha, validate_outline


def _hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


@pytest.fixture
def workflow():
    sources = []
    for index in range(20):
        source_hash, artifact_hash = _hash(f'source-{index}'), _hash(f'analysis-{index}')
        sources.append({
            'source_id': f'douyin:{index:019d}', 'title': f'来源{index}',
            'metric_kind': 'likes_user_confirmed', 'metric_value': (index + 1) * 1000,
            'expression_analysis': {'core_message': {'text': f'完整主张{index}，保留条件。', 'evidence_ids': ['A0001']},
                'expression_modes': [{'mode': 'prop_demonstration', 'evidence_ids': ['V0001']}],
                'evidence': [
                    {'id': 'A0001', 'channel': 'asr', 'text': '如果双方确认，才继续。', 'start_seconds': 0., 'end_seconds': 2.},
                    {'id': 'V0001', 'channel': 'visual', 'text': '一只手按在纸张边缘。', 'start_seconds': 1., 'end_seconds': 1.}]},
            'media_evidence': {'schema': 'local_media_evidence/v1', 'source_video_sha256': source_hash,
                'duration_seconds': 3., 'visual': {'status': 'completed', 'artifact_sha256': artifact_hash}},
            'independent_review': {'decision': 'passed_with_limits', 'source_video_sha256': source_hash,
                'artifact_sha256': artifact_hash, 'review_sha256': _hash(f'review-{index}'),
                'reviewed_at': '2026-09-10T00:00:00+08:00', 'acoustic_status': 'not_reviewed'},
        })
    payload = {'source_evidence': sources, 'short_seconds': 45, 'long_seconds': 180,
        'account_positioning': {'domain': 'legal_services'},
        'expression_patterns': {'patterns': [{'mode': 'prop_demonstration', 'support_video_count': 20,
            'metric_groups': [{'metric_kind': 'likes', 'high_group_support': 5, 'high_group_size': 5,
                               'comparison_group_support': 15, 'comparison_group_size': 15}]}],
            'interpretation': '关联不等于因果'},
        'expression_direction': '可见的行动与选择',
        'production_constraints': {'short_mode': 'continuous_fixed_two_person'}}
    return [{'role': 'system', 'content': '原工作流作者提示'},
            {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]


def _change_payload(workflow, change):
    result = copy.deepcopy(workflow)
    payload = json.loads(result[1]['content'])
    change(payload)
    result[1]['content'] = json.dumps(payload, ensure_ascii=False)
    return result


@pytest.fixture
def outline():
    def version(kind, durations):
        return {'title': kind, 'goal': '核对后决定是否签字', 'obstacle': '两份数字不同',
            'stakes': '签入不同金额会留下争议', 'ending': '双方完成一致内容的现场确认',
            'events': [{'event_id': f'E{i:02d}', 'duration_seconds': seconds,
                'visible_action': f'第{i}步按住纸边并对照已出现的材料。',
                'changed_state': f'第{i}项差异得到现场确认。', 'opponent_reaction': '对方按住另一页继续核对。',
                'spoken_intent': f'{"甲" if i % 2 else "乙"}：说明当前核对结果。'}
                for i, seconds in enumerate(durations, 1)]}
    return {'core_message': '先确认当下拟签内容再作选择。',
        'characters': [{'name': name, 'identity': identity, 'wants': '完成同一份合同',
                        'reason_not_immediately_agree': '尚未确认其中一项内容'}
                       for name, identity in [('甲', '客户'), ('乙', '施工方')]],
        'short': version('短版', [8, 7, 7, 8, 8, 7]),
        'long': version('长版', [12] * 4 + [11] * 12),
        'reference_usage': [{'source_id': 'douyin:0000000000000000000', 'evidence_ids': ['V0001', 'A0001'],
            'borrowed_expression': '纸张操作承载条件说明', 'original_adaptation': '双方对照和人物冲突为原创'}],
        'legal_boundaries': '只确认本次双方选择，不保证一般法律效果。'}


def test_all_twenty_complete_sources_and_feedback_are_preserved_without_mutation(workflow, outline):
    original = copy.deepcopy(workflow)
    feedback = '保留否定、条件和未听音限制。'
    messages = build_outline_messages(workflow, feedback, outline)
    sent = json.loads(messages[1]['content'])
    assert sent['source_evidence'] == json.loads(workflow[1]['content'])['source_evidence']
    assert len(sent['source_evidence']) == 20
    assert sent['current_editor_feedback'] == feedback
    assert sent['previous_outline'] == outline
    assert (sent['short_seconds'], sent['long_seconds']) == (45, 180)
    assert workflow == original
    assert all(isinstance(m['content'], str) for m in messages)


@pytest.mark.parametrize('defect', ['nineteen', 'duplicate', 'unreviewed', 'failed', 'blank_id',
                                    'blocked_review', 'source_hash_mismatch', 'artifact_hash_mismatch'])
def test_invalid_source_cohort_is_rejected_before_model_input(workflow, defect):
    def change(payload):
        sources = payload['source_evidence']
        if defect == 'nineteen': sources.pop()
        elif defect == 'duplicate': sources[-1]['source_id'] = sources[0]['source_id']
        elif defect == 'unreviewed': sources[-1]['independent_review']['decision'] = 'not_reviewed'
        elif defect == 'failed': sources[-1]['independent_review']['decision'] = 'failed'
        elif defect == 'blank_id': sources[-1]['source_id'] = ''
        elif defect == 'blocked_review': sources[-1]['independent_review']['blocked_for_script_generation'] = True
        elif defect == 'source_hash_mismatch': sources[-1]['independent_review']['source_video_sha256'] = '0' * 64
        elif defect == 'artifact_hash_mismatch': sources[-1]['independent_review']['artifact_sha256'] = '0' * 64
    with pytest.raises(ValueError):
        build_outline_messages(_change_payload(workflow, change), '审核后写提纲')


def test_valid_outline_remains_candidate_content_only(workflow, outline):
    original = copy.deepcopy(outline)
    assert validate_outline(outline, build_outline_messages(workflow, '')) == original
    assert outline == original
    assert 'status' not in outline


@pytest.mark.parametrize('defect', ['extra_top_status', 'missing_core', 'duplicate_character',
    'missing_character_identity', 'nested_approved', 'bad_event_id', 'bool_duration', 'fraction_duration',
    'too_short_duration', 'wrong_total', 'missing_changed_state', 'unknown_source', 'unknown_evidence',
    'duplicate_evidence', 'contribution_percent', 'unknown_speaker', 'two_speakers', 'narrator'])
def test_outline_schema_time_and_real_reference_contracts(workflow, outline, defect):
    if defect == 'extra_top_status': outline['approved'] = True
    elif defect == 'missing_core': del outline['core_message']
    elif defect == 'duplicate_character': outline['characters'][1]['name'] = '甲'
    elif defect == 'missing_character_identity': del outline['characters'][1]['identity']
    elif defect == 'nested_approved': outline['short']['events'][0]['approved'] = True
    elif defect == 'bad_event_id': outline['short']['events'][0]['event_id'] = 'E09'
    elif defect == 'bool_duration': outline['short']['events'][0]['duration_seconds'] = True
    elif defect == 'fraction_duration': outline['short']['events'][0]['duration_seconds'] = 8.0
    elif defect == 'too_short_duration': outline['short']['events'][0]['duration_seconds'] = 3
    elif defect == 'wrong_total': outline['short']['events'][0]['duration_seconds'] = 9
    elif defect == 'missing_changed_state': del outline['short']['events'][0]['changed_state']
    elif defect == 'unknown_source': outline['reference_usage'][0]['source_id'] = 'not-in-input'
    elif defect == 'unknown_evidence': outline['reference_usage'][0]['evidence_ids'] = ['V9999']
    elif defect == 'duplicate_evidence': outline['reference_usage'][0]['evidence_ids'] = ['V0001', 'V0001']
    elif defect == 'contribution_percent': outline['reference_usage'][0]['contribution_percent'] = 20
    elif defect == 'unknown_speaker': outline['short']['events'][0]['spoken_intent'] = '丙：催促签字。'
    elif defect == 'two_speakers': outline['short']['events'][0]['spoken_intent'] = '甲、乙：轮流说明并相互回应。'
    elif defect == 'narrator': outline['short']['events'][0]['spoken_intent'] = '旁白：解释此时应做什么。'
    with pytest.raises(ValueError):
        validate_outline(outline, build_outline_messages(workflow, ''))


def test_text_hash_is_utf8_content_based():
    assert text_sha('条件：不签\n下一步') == _hash('条件：不签\n下一步')
    assert text_sha('条件：不签\n下一步') != text_sha('条件：签\n下一步')
    assert text_sha('a\n') != text_sha('a\r\n')


@pytest.fixture
def cli_case(tmp_path, monkeypatch, workflow):
    script = Path(__file__).resolve().parents[1] / 'scripts/plan_script_expression.py'
    spec = importlib.util.spec_from_file_location('outline_cli_under_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fake_root = tmp_path / 'project'
    monkeypatch.setattr(module, '__file__', str(fake_root / 'scripts/plan_script_expression.py'))
    source = fake_root / 'data/pre_video_scripts/_runs/existing/request.json'
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps(workflow, ensure_ascii=False), encoding='utf-8')
    feedback = tmp_path / 'feedback.md'
    feedback.write_text('只检查已经给出的证据。\n不生成视频。', encoding='utf-8')
    output = tmp_path / 'outline-output'
    monkeypatch.setattr(module, 'settings', SimpleNamespace(SCRIPT_LLM_MODEL='Minimax-M3', LLM_MODEL='fallback',
        SCRIPT_LLM_THINKING='disabled', SCRIPT_LLM_TIMEOUT_SECONDS=30, SCRIPT_LLM_MAX_TOKENS=24000))
    monkeypatch.setattr(module.sys, 'argv', ['plan_script_expression.py', '--workflow-request', str(source),
        '--editor-feedback-file', str(feedback), '--output-dir', str(output)])
    return SimpleNamespace(module=module, source=source, feedback=feedback, output=output)


def _install_client(monkeypatch, case, raw, *, provider='openai_compatible', error=None):
    calls = []
    class FakeClient:
        provider_name = provider
        def __init__(self, **kwargs):
            calls.append(('init', kwargs))
            self.provider = SimpleNamespace(last_response_metadata={'test': 'local fixture only'})
        def chat_completion_tracked(self, messages, **kwargs):
            calls.append(('completion', copy.deepcopy(messages), kwargs))
            if error: raise error
            return raw
    monkeypatch.setattr(case.module, 'LLMClient', FakeClient)
    return calls


def test_cli_calls_text_only_once_and_never_certifies_independent_approval(cli_case, monkeypatch, outline):
    raw = json.dumps(outline, ensure_ascii=False)
    calls = _install_client(monkeypatch, cli_case, raw)
    before = cli_case.source.read_bytes()
    cli_case.module.main()
    state = json.loads((cli_case.output / 'run.json').read_text(encoding='utf-8'))
    completions = [c for c in calls if c[0] == 'completion']
    assert len(completions) == 1
    assert all(isinstance(m['content'], str) for m in completions[0][1])
    assert completions[0][2]['caller'] == 'pre_video_script_outline'
    assert completions[0][2]['use_cache'] is False
    assert state['status'] == 'candidate_pending_independent_review'
    assert state['media_generation'] is False
    assert 'approved' not in state and 'passed' not in state
    assert state['workflow_request_sha256'] == _hash(before.decode('utf-8'))
    assert state['feedback_sha256'] == _hash(cli_case.feedback.read_text(encoding='utf-8'))
    assert state['outline_sha256'] == _hash((cli_case.output / 'outline.json').read_text(encoding='utf-8'))
    assert (cli_case.output / 'model_outline.json').read_text(encoding='utf-8') == raw
    assert cli_case.source.read_bytes() == before
    assert not any(p.suffix.lower() in {'.mp4', '.wav', '.mp3', '.png', '.jpg'} for p in cli_case.output.iterdir())


def test_cli_provenance_binds_prompt_request_raw_output_and_previous(cli_case, monkeypatch, outline):
    previous = cli_case.output.parent / 'previous.json'
    previous.write_text(json.dumps(outline, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(cli_case.module.sys, 'argv', [*cli_case.module.sys.argv, '--previous-outline', str(previous)])
    raw = json.dumps(outline, ensure_ascii=False)
    _install_client(monkeypatch, cli_case, raw)
    cli_case.module.main()
    state = json.loads((cli_case.output / 'run.json').read_text(encoding='utf-8'))
    request_text = (cli_case.output / 'request.json').read_text(encoding='utf-8')
    assert state['prompt_sha256'] == _hash(json.loads(request_text)[0]['content'])
    assert state['request_sha256'] == _hash(request_text)
    assert state['model_outline_sha256'] == _hash(raw)
    assert Path(state['previous_outline_path']).resolve() == previous.resolve()
    assert state['previous_outline_sha256'] == _hash(previous.read_text(encoding='utf-8'))


@pytest.mark.parametrize('failure', ['no_response', 'invalid_json', 'invalid_outline', 'request_error', 'mock', 'init_error', 'bad_config'])
def test_cli_failure_is_recorded_and_cannot_leave_false_running_or_candidate(cli_case, monkeypatch, failure):
    raw = None if failure == 'no_response' else '{broken' if failure == 'invalid_json' else '{}'
    _install_client(monkeypatch, cli_case, raw, provider='mock' if failure == 'mock' else 'openai_compatible',
                    error=RuntimeError('fixture request failed') if failure == 'request_error' else None)
    if failure == 'init_error':
        def fail_init(**kwargs): raise RuntimeError('fixture init failed')
        monkeypatch.setattr(cli_case.module, 'LLMClient', fail_init)
    if failure == 'bad_config': cli_case.module.settings.SCRIPT_LLM_THINKING = 'unsupported'
    with pytest.raises((ValueError, RuntimeError)):
        cli_case.module.main()
    state = json.loads((cli_case.output / 'run.json').read_text(encoding='utf-8'))
    assert state['status'] == 'failed'
    assert state['finished_at']
    assert state['media_generation'] is False
    assert not (cli_case.output / 'outline.json').exists()


def test_cli_rejects_outside_workflow_request_before_client_creation(cli_case, monkeypatch):
    calls = _install_client(monkeypatch, cli_case, '{}')
    outside = cli_case.output.parent / 'request.json'
    outside.write_bytes(cli_case.source.read_bytes())
    args = list(cli_case.module.sys.argv)
    args[args.index('--workflow-request') + 1] = str(outside)
    monkeypatch.setattr(cli_case.module.sys, 'argv', args)
    with pytest.raises(ValueError, match='原始工作流'):
        cli_case.module.main()
    assert calls == []
    assert not cli_case.output.exists()


def test_focused_selection_keeps_twenty_overviews_patterns_and_two_full_sources(workflow):
    before = copy.deepcopy(workflow)
    original = json.loads(workflow[1]['content'])
    all_sources = original['source_evidence']
    selected_ids = [all_sources[-1]['source_id'], all_sources[0]['source_id']]
    messages = build_outline_messages(workflow, '聚焦只改变输入范围，不改原句。', reference_source_ids=selected_ids)
    sent = json.loads(messages[1]['content'])
    assert len(sent['source_overview']) == 20
    assert [s['source_id'] for s in sent['source_overview']] == [s['source_id'] for s in all_sources]
    for overview, full in zip(sent['source_overview'], all_sources):
        assert overview['core_message'] == full['expression_analysis']['core_message']
        assert overview['expression_modes'] == full['expression_analysis']['expression_modes']
        assert overview['independent_review'] == full['independent_review']
        assert (overview['metric_kind'], overview['metric_value']) == (full['metric_kind'], full['metric_value'])
        assert 'evidence' not in overview
    assert len(sent['source_evidence']) == 2
    assert {s['source_id']: s for s in sent['source_evidence']} == {
        s['source_id']: s for s in all_sources if s['source_id'] in selected_ids}
    assert sent['expression_patterns'] == original['expression_patterns']
    assert sent['account_positioning'] == original['account_positioning']
    assert sent['production_constraints'] == original['production_constraints']
    assert sent['planning_evidence_scope']['reviewed_source_count'] == 20
    assert sent['planning_evidence_scope']['reference_source_ids'] == selected_ids
    assert workflow == before


@pytest.mark.parametrize('selection', [
    ['not-in-cohort'], ['douyin:0000000000000000000', 'douyin:0000000000000000000'],
    ['douyin:0000000000000000000', 'unknown'], [''],
])
def test_focused_unknown_or_duplicate_selection_is_rejected(workflow, selection):
    with pytest.raises(ValueError):
        build_outline_messages(workflow, '', reference_source_ids=selection)


@pytest.mark.parametrize('defect', ['failed', 'blocked', 'hash_mismatch'])
def test_focused_mode_still_validates_unselected_source_reviews(workflow, defect):
    def change(payload):
        unselected = payload['source_evidence'][-1]['independent_review']
        if defect == 'failed': unselected['decision'] = 'failed'
        elif defect == 'blocked': unselected['blocked_for_script_generation'] = True
        else: unselected['source_video_sha256'] = '0' * 64
    with pytest.raises(ValueError):
        build_outline_messages(_change_payload(workflow, change), '',
                               reference_source_ids=['douyin:0000000000000000000', 'douyin:0000000000000000001'])


def test_focused_outline_may_reference_selected_but_not_overview_only_source(workflow, outline):
    selected = ['douyin:0000000000000000000', 'douyin:0000000000000000001']
    messages = build_outline_messages(workflow, '', reference_source_ids=selected)
    assert validate_outline(outline, messages) == outline
    outline['reference_usage'][0]['source_id'] = 'douyin:0000000000000000019'
    # This ID and A0001/V0001 really exist in the original 20-source request,
    # but only their overview was supplied to this particular outline model.
    with pytest.raises(ValueError, match='引用来源不存在'):
        validate_outline(outline, messages)


def test_empty_or_omitted_focus_preserves_original_default_full_input(workflow):
    default = build_outline_messages(workflow, '保留默认行为')
    explicit_empty = build_outline_messages(workflow, '保留默认行为', reference_source_ids=[])
    assert default == explicit_empty
    payload = json.loads(default[1]['content'])
    assert payload['source_evidence'] == json.loads(workflow[1]['content'])['source_evidence']
    assert len(payload['source_evidence']) == 20
    assert 'source_overview' not in payload and 'planning_evidence_scope' not in payload


def test_cli_repeated_focus_arguments_keep_full_request_provenance(cli_case, monkeypatch, outline):
    selected = ['douyin:0000000000000000000', 'douyin:0000000000000000019']
    argv = list(cli_case.module.sys.argv)
    for sid in selected:
        argv.extend(['--reference-source-id', sid])
    monkeypatch.setattr(cli_case.module.sys, 'argv', argv)
    before = cli_case.source.read_bytes()
    calls = _install_client(monkeypatch, cli_case, json.dumps(outline, ensure_ascii=False))
    cli_case.module.main()
    call = next(c for c in calls if c[0] == 'completion')
    sent = json.loads(call[1][1]['content'])
    assert {s['source_id'] for s in sent['source_evidence']} == set(selected)
    assert len(sent['source_overview']) == 20
    assert sent['planning_evidence_scope']['reference_source_ids'] == selected
    state = json.loads((cli_case.output / 'run.json').read_text(encoding='utf-8'))
    assert state['workflow_request_sha256'] == _hash(before.decode('utf-8'))
    assert state['request_sha256'] == _hash((cli_case.output / 'request.json').read_text(encoding='utf-8'))
    assert state['status'] == 'candidate_pending_independent_review' and state['media_generation'] is False
    assert cli_case.source.read_bytes() == before


@pytest.mark.parametrize('selection', [['missing-source'], ['douyin:0000000000000000000'] * 2])
def test_cli_invalid_focus_fails_before_model_and_output_creation(cli_case, monkeypatch, selection):
    argv = list(cli_case.module.sys.argv)
    for sid in selection:
        argv.extend(['--reference-source-id', sid])
    monkeypatch.setattr(cli_case.module.sys, 'argv', argv)
    calls = _install_client(monkeypatch, cli_case, '{}')
    with pytest.raises(ValueError):
        cli_case.module.main()
    assert calls == []
    assert not cli_case.output.exists()
