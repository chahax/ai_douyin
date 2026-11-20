"""Independent continuation gates using saved sources; no real SDK calls."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import run_creative_resume_v1 as resume
from scripts import creative_resume_dispatch_v1 as dispatch
from scripts import creative_compact_review_transport_v8 as compact
from scripts import step_index_physical_adapter_v4 as physical
from scripts import creative_linear_script_v2 as linear
from src.content_factory.creative_review_v3 import CHECKS
from src.content_factory.creative_review_v6 import build_review_prompt, comparison_requirements
from src.content_factory.creative_workflow_contract import CreativeContractError
from tests.test_step_index_physical_adapter_v4 import rebind


def full_physical_case():
    context, direction, locals_ = physical.make_offline_case()
    original = resume.legacy.read(resume.legacy.ROOT / 'ORIGINAL_CONTEXT.json')
    for key in ('creative_brief', 'material_ref', 'reference_pack', 'reference_expression_rule'):
        context[key] = deepcopy(original[key])
    rebind(context, direction, locals_)
    return context, direction, locals_


def derive_fixture(raw):
    names = ['甲', '乙']
    return linear.accept_linear_script(raw, raw, character_names=names)


@pytest.fixture
def compiled_case(tmp_path, monkeypatch):
    context, direction, locals_ = full_physical_case()
    monkeypatch.setattr(resume, 'ROOT', tmp_path)
    monkeypatch.setattr(resume, 'direction_source', lambda n, revision: (deepcopy(context), deepcopy(direction)))
    monkeypatch.setattr(resume, 'local_sources', lambda n, revision, count: deepcopy(locals_[:count]))
    monkeypatch.setattr(resume, 'derive', derive_fixture)
    final_context, compiled = resume.final_context(1, 1)
    return context, direction, locals_, final_context, compiled


def leaves(value, prefix=''):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from leaves(item, f'{prefix}.{key}' if prefix else key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from leaves(item, f'{prefix}.{index}')
    elif isinstance(value, (str, int, float)) and not isinstance(value, bool) and str(value):
        yield {'path': prefix, 'quote': str(value)}


def first_ref(context, prefix):
    return next(ref for ref in leaves(context) if ref['path'].startswith(prefix))


def complete_joint_review(context):
    coverage = []
    requirements = comparison_requirements(context)
    for index, shot in enumerate(context['shots']['shots']):
        own = f'shots.shots.{index}.'
        checks = {}
        for name in CHECKS:
            refs = [first_ref(context, own)]
            for prefix in requirements[shot['id']].get(name, []):
                refs.append(first_ref(context, prefix))
            if name == 'continuity' and index:
                refs.append(first_ref(context, f'shots.shots.{index-1}.end_state'))
            checks[name] = {'status': 'pass', 'reason': '离线来源合同测试，不是模型审查或内容批准',
                            'evidence_refs': refs, 'issue_ids': []}
        coverage.append({'id': shot['id'], 'checks': checks})
    return {'story_preserved': True, 'issues': [], 'suggestions': [], 'calibration_focus': [], 'coverage': coverage}


def test_joint_request_preserves_full_context_sources_and_frozen_semantic_checks(compiled_case):
    _, _, _, context, compiled = compiled_case
    before = deepcopy(context)
    messages = resume.joint_review_messages(context)
    assert json.loads(messages[1]['content']) == context == before
    assert context['raw_linear_script'] == compiled['source_raw_linear_script']
    for key in ('reference_pack', 'reference_expression_rule', 'creative_brief', 'material_ref',
                'static_visual_manifest', 'whole_film_direction', 'execution_script',
                'execution_bindings', 'declared_performance_window_checks', 'state_plan'):
        assert key in json.loads(messages[1]['content'])
    replaced = ('唯一输出JSON顶层字段', 'evidence_refs每项为', 'coverage逐行覆盖编号')
    for line in build_review_prompt(context).splitlines():
        if not line.startswith(replaced):
            assert line in messages[0]['content']
    assert '本次同时审完整原steps、整片情绪与因果' in messages[0]['content']
    assert 'current_beat_only' not in messages[0]['content']
    assert compact.context_digest(context) in messages[0]['content']


@pytest.mark.parametrize('defect', ['empty', 'duplicate', 'single_beat'])
def test_joint_scope_defects_stop_before_message_dispatch(compiled_case, defect):
    context = deepcopy(compiled_case[3])
    if defect == 'empty': context['shots']['shots'] = []
    elif defect == 'duplicate': context['shots']['shots'][1]['id'] = context['shots']['shots'][0]['id']
    else: context['review_scope'] = 'storyboard_segment'
    with pytest.raises((RuntimeError, CreativeContractError)):
        resume.joint_review_messages(context)


def test_complete_joint_roundtrip_still_requires_previous_shot_evidence(compiled_case):
    context = compiled_case[3]
    review = complete_joint_review(context)
    raw = compact.encode_review(review, context)
    assert compact.expand_review(raw, context) == review
    raw['coverage'][1][3][2] = [pair for pair in raw['coverage'][1][3][2] if not pair[0].startswith('shots.shots.0.')]
    with pytest.raises(CreativeContractError, match='缺少对照证据'):
        compact.expand_review(raw, context)


@pytest.mark.parametrize('field', ['raw_linear_script', 'reference_pack', 'whole_film_direction', 'execution_bindings', 'declared_performance_window_checks', 'state_plan'])
def test_joint_context_sha_invalidates_every_relevant_downstream_change(compiled_case, field):
    context = compiled_case[3]
    raw = compact.encode_review(complete_joint_review(context), context)
    changed = deepcopy(context)
    changed[field] = {'offline_changed': True, 'old': changed[field]}
    with pytest.raises(CreativeContractError, match='COMPACT_CONTEXT_STALE'):
        compact.expand_review(raw, changed)


def test_recomputed_complete_artifact_cannot_use_modified_disk_result(compiled_case):
    _, _, _, _, compiled = compiled_case
    target = resume.ROOT / f'COMPLETE_s1_d1_{dispatch.digest(compiled)[:12]}.json'
    altered = deepcopy(compiled)
    altered['source_raw_linear_script']['title'] = '磁盘派生成片被改动'
    dispatch.write(target, altered)
    with pytest.raises(RuntimeError, match='immutable artifact changed'):
        resume.final_context(1, 1)


def test_latest_rejected_draft_and_local_cannot_fallback_to_prior_valid(monkeypatch):
    entries = [
        {'ordinal': 50, 'label': 'draft_s1', 'status': 'contract_valid', 'output': {'old': True}},
        {'ordinal': 51, 'label': 'draft_s2', 'status': 'contract_rejected', 'output': {'new': True}},
        {'ordinal': 52, 'label': 'local_s2_d1_p001_r1', 'status': 'contract_valid', 'output': {'old': True}},
        {'ordinal': 53, 'label': 'local_s2_d1_p001_r2', 'status': 'contract_rejected', 'output': {'new': True}},
    ]
    monkeypatch.setattr(resume, 'records', lambda: deepcopy(entries))
    with pytest.raises(RuntimeError, match='superseded'):
        resume.ensure_latest_draft(1)
    with pytest.raises(RuntimeError, match='latest stage rejected'):
        resume.ensure_latest_draft(2)
    with pytest.raises(RuntimeError, match='latest stage rejected'):
        resume.local_sources(2, 1, 1)


@pytest.mark.parametrize('has_output', [True, False])
def test_known_failed_draft_can_be_generation_reference_without_adoption(monkeypatch, has_output):
    receipt = {'ordinal': 50, 'label': 'draft_s1', 'status': 'contract_rejected' if has_output else 'interface_rejected',
               'failure': {'response_received': True, 'code': 'BAD_SCHEMA'}, 'response_text': '{"partial":"原始失败响应"}'}
    if has_output: receipt['output'] = {'title': '完整失败稿', 'beats': [{'duration_seconds': -1}], 'selected_candidate_id': 'FIXTURE'}
    before = deepcopy(receipt)
    monkeypatch.setattr(resume, 'records', lambda: [deepcopy(receipt)])
    previous = resume.previous_draft_for_revision(2)
    if has_output:
        assert previous == receipt['output']
    else:
        assert previous['rejected_response_text'] == receipt['response_text']
        assert previous['failure'] == receipt['failure']
        assert 'unadopted' in previous['source_status']
    with pytest.raises(RuntimeError, match='latest stage rejected'):
        resume.ensure_latest_draft(1)
    assert receipt == before


@pytest.mark.parametrize('status,received', [('pending_response', False), ('outcome_unknown', False), ('interface_rejected', False)])
def test_unknown_previous_draft_cannot_trigger_new_generation(monkeypatch, status, received):
    monkeypatch.setattr(resume, 'records', lambda: [{'ordinal': 50, 'label': 'draft_s1', 'status': status,
                  'failure': {'response_received': received}, 'output': {'should_not_be_used': True}}])
    with pytest.raises(RuntimeError, match='unknown'):
        resume.previous_draft_for_revision(2)


@pytest.mark.parametrize('evidence', [[], [''], [None], [{'path': 'script.beats', 'quote': '[]', 'finding': 'x'}],
    [{'path': 'script.beats.0.before', 'quote': '伪造动作', 'finding': 'x'}],
    [{'path': 'script.beats.0.before', 'quote': '许宁', 'finding': ''}]])
def test_explicit_assistant_evidence_cannot_be_blank_nonleaf_or_unquoted(evidence):
    context = {'script': {'beats': [{'before': '许宁把纸杯放到桌面。'}]}}
    with pytest.raises(RuntimeError):
        resume.verify_assistant_evidence(context, evidence)


def test_explicit_assistant_evidence_preserves_real_finding_and_does_not_mutate():
    context = {'script': {'beats': [{'before': '许宁把纸杯放到桌面。'}]}}
    evidence = [{'path': 'script.beats.0.before', 'quote': '纸杯放到桌面', 'finding': '正文明确杯的实际落点。'}]
    result = resume.verify_assistant_evidence(context, evidence)
    assert result == evidence and result is not evidence


@pytest.mark.parametrize('approved', ['false', 1, None])
def test_decision_does_not_coerce_approval_value(monkeypatch, approved):
    context = {'script': {'beats': [{'before': '实际正文。'}]}}
    monkeypatch.setattr(resume, 'effective_script_review', lambda n: (context, {'ordinal': 51}, {'issues': [], 'story_preserved': True}))
    with pytest.raises(RuntimeError, match='boolean'):
        resume.script_decision(1, approved, [{'path': 'script.beats.0.before', 'quote': '实际正文', 'finding': '核对完成。'}])


@pytest.mark.parametrize('change', ['live_source', 'snapshot', 'inherited_evidence'])
def test_runtime_source_or_inherited_evidence_change_blocks_before_sdk(tmp_path, change):
    project = tmp_path / 'project'; project.mkdir()
    source = project / 'operator.py'; source.write_text('original source', encoding='utf-8')
    prior = project / 'prior_receipt.json'; prior.write_text('{"historical":true}', encoding='utf-8')
    prior_sha = dispatch.sha_file(prior)
    def guard():
        if dispatch.sha_file(prior) != prior_sha: raise RuntimeError('prior frozen evidence changed')
    called = []
    def no_sdk():
        called.append(True)
        raise AssertionError('Model SDK must never be constructed in this test')
    runtime = dispatch.ContinuationRuntime(project, project / 'resume', [source],
        {'calls_started': 49, 'reported_tokens': 490913}, {'writer': {'model': 'offline-fixture'}},
        inherited_guard=guard, client_factory=no_sdk)
    runtime.prepare()
    if change == 'live_source': source.write_text('changed live source', encoding='utf-8')
    elif change == 'snapshot': (runtime.root / 'source_at_dispatch/operator.py').write_text('changed snapshot', encoding='utf-8')
    else: prior.write_text('{"historical":"changed"}', encoding='utf-8')
    wire = {'role': 'writer', 'model': 'offline-fixture', 'messages': [{'role': 'user', 'content': '{}'}],
            'structured_schema': None, 'parameters': {'max_completion_tokens': 512, 'temperature': 0.4, 'thinking': 'disabled'}}
    with pytest.raises(RuntimeError, match='source|evidence'):
        runtime.dispatch('offline_candidate', wire, lambda raw: {})
    assert called == []
    assert dispatch.read(runtime.ledger)['calls'] == []



def test_readable_plan_covers_both_shots_all_original_steps_and_actual_operations(compiled_case):
    _, direction, _, context, compiled = compiled_case
    before = deepcopy((context, compiled))
    text = resume.render_production_plan(context, compiled)
    assert (context, compiled) == before
    assert [shot['id'] for shot in compiled['storyboard']['shots']] == ['SH01', 'SH02']
    assert [shot['beat_id'] for shot in compiled['storyboard']['shots']] == [shot['shot_id'] for shot in physical._shots(direction)]
    assert '## SH01（0.00–4.00秒）' in text and '## SH02（4.00–8.00秒）' in text
    indexes = []
    for beat in context['raw_linear_script']['beats']:
        for step in beat['steps']:
            rendered = step['speaker']+'：'+step['text'] if step['kind']=='dialogue' else step['text']
            indexes.append(text.index(rendered))
            if step['kind']=='dialogue': assert text.count(rendered) == 1
    assert indexes == sorted(indexes)
    for entry in compiled['source_trace']:
        assert f"| {entry['start']:.2f}–{entry['end']:.2f}秒 |" in text
        assert json.dumps(entry['physical_operations'],ensure_ascii=False) in text
    assert 'awaiting_human_review' in text
    assert '使用服务返回的原始尾帧续段' in text


@pytest.mark.parametrize('changed', ['script', 'context', 'receipt', 'new_review'])
def test_adoption_decision_is_bound_to_current_script_context_and_review_receipt(tmp_path, monkeypatch, changed):
    context = {'script': {'beats': [{'before': '许宁把杯子放到桌上。'}]}, 'reference_pack': ['完整参考原文']}
    source = {'ordinal': 50, 'label': 'draft_s1', 'status': 'contract_valid', 'output': {'title': '源稿完整身份'}}
    review_receipt = {'ordinal': 51, 'label': 'script_review_s1_r1', 'status': 'contract_valid', 'output': {}}
    receipt_name = 'call_051_script_review_s1_r1.json'
    dispatch.write(tmp_path / receipt_name, review_receipt)
    dispatch.write(tmp_path / 'CALL_LEDGER.json', {'calls': [{'ordinal': 51, 'receipt': receipt_name}]})
    monkeypatch.setattr(resume, 'ROOT', tmp_path)
    monkeypatch.setattr(resume, 'ensure_latest_draft', lambda n: deepcopy(source))
    monkeypatch.setattr(resume, 'effective_script_review', lambda n: (deepcopy(context), deepcopy(review_receipt), {'issues': [], 'story_preserved': True}))
    evidence = [{'path': 'script.beats.0.before', 'quote': '杯子放到桌上', 'finding': '正文确有实际落点。'}]
    decision = resume.script_decision(1, True, evidence)
    old_path = resume.decision_path(1, review_receipt)
    assert old_path.name == 'SCRIPT_DECISION_s1_call51.json'
    assert resume.require_script_decision(1) == decision
    original_decision = old_path.read_bytes()
    if changed == 'script': source['output']['title'] += '新稿'
    elif changed == 'context': context['reference_pack'].append('新参考')
    elif changed == 'receipt': dispatch.write(tmp_path / receipt_name, {'changed_review': True})
    else:
        review_receipt['ordinal'] = 52
        review_receipt['label'] = 'script_review_s1_r2'
    with pytest.raises((RuntimeError, FileNotFoundError)):
        resume.require_script_decision(1)
    assert old_path.read_bytes() == original_decision
