"""Strict positive review evidence: bindings and coverage, never synthetic media approval."""
import copy
import json
from dataclasses import asdict, replace

import pytest

import src.trend_intelligence.script_pair as module
from script_pair_fixture import enrich_review_report, fixture_source_evidence, pair_payload
from test_script_pair import parse


class EvidenceReviewer:
    def __init__(self):
        self.calls = []
    def chat_completion_tracked(self, messages, **kwargs):
        self.calls.append((copy.deepcopy(messages), kwargs))
        payload = json.loads(next(m['content'] for m in messages if m['role'] == 'user'))
        report = enrich_review_report({'checks': {key: True for key in module.REVIEW_CHECKS},
            'issues': [], 'summary': '合成测试报告，不代表真实语义审核。'}, payload)
        return json.dumps(report, ensure_ascii=False)


@pytest.fixture
def review_case():
    client = EvidenceReviewer()
    scripts = parse(pair_payload())
    result = module.review_pair(client, scripts, {'source_evidence': fixture_source_evidence()})
    payload = json.loads(client.calls[0][0][1]['content'])
    raw = enrich_review_report({'checks': {key: True for key in module.REVIEW_CHECKS},
        'issues': [], 'summary': '合成测试报告。'}, payload)
    return payload, raw, result


def test_current_payload_binding_complete_evidence_and_real_structural_facts(review_case):
    payload, raw, result = review_case
    assert module.script_review_binding(payload) == {key: result[key] for key in ('candidate_sha256', 'evidence_sha256')}
    assert len(result['shot_audit']) == 18 and len(result['result_audit']) == 4
    assert result['passed'] is True and result['legal_review_status'] == 'pending_human_review'
    assert all(row['legal_review_note'] for row in payload['scripts'])
    assert payload['validated_structure']['verification'] == 'recomputed_from_current_review_scripts_not_inherited_approval'
    assert 'passed' not in raw  # Validation must not mutate the model's raw record.
    assert module.validate_script_review_report(raw, payload)['passed'] is True


def test_all_true_without_positive_evidence_is_rejected(review_case):
    payload, raw, _ = review_case
    old = {key: raw[key] for key in ('checks', 'issues', 'summary')}
    with pytest.raises(ValueError, match='shot_audit'):
        module.validate_script_review_report(old, payload)


def test_saved_report_can_be_rechecked_with_derived_metadata(review_case):
    payload, _, result = review_case
    result['source_review_scope'] = {'notice': '本次实际引用范围'}
    verified = module.validate_saved_script_review_report(result, payload)
    assert verified == result and verified is not result


@pytest.mark.parametrize('defect', ['changed_candidate', 'forged_passed', 'old_schema'])
def test_saved_report_does_not_bypass_current_evidence_gate(review_case, defect):
    payload, _, result = review_case
    if defect == 'changed_candidate':
        payload['scripts'][0]['resolution'] += '旧镜头没有执行的新结局'
        payload.update(module.script_review_binding(payload))
    elif defect == 'forged_passed':
        result['shot_audit'][0]['decision'] = 'failed'
    else:
        result['schema'] = 'legacy_checks_only/v1'
    with pytest.raises(ValueError):
        module.validate_saved_script_review_report(result, payload)


@pytest.mark.parametrize('defect', ['missing_shot', 'duplicate_shot', 'unknown_shot', 'unknown_script',
    'unknown_decision', 'empty_continuity', 'empty_voice', 'empty_action', 'invented_quote', 'other_shot_action',
    'audio_instead_of_action', 'missing_result', 'duplicate_result', 'unknown_target', 'empty_explanation',
    'metadata_instead_of_executed_action'])
def test_incomplete_or_false_positive_evidence_never_passes(review_case, defect):
    payload, raw, _ = review_case
    shot = raw['shot_audit'][0]
    if defect == 'missing_shot': raw['shot_audit'].pop()
    elif defect == 'duplicate_shot': raw['shot_audit'].append(copy.deepcopy(shot))
    elif defect == 'unknown_shot': shot['shot_id'] = 'S99'
    elif defect == 'unknown_script': shot['script'] = 'invented'
    elif defect == 'unknown_decision': shot['decision'] = 'unknown'
    elif defect == 'empty_continuity': shot['continuity_note'] = ''
    elif defect == 'empty_voice': shot['voice_note'] = ''
    elif defect == 'empty_action': shot['action_evidence'] = []
    elif defect == 'invented_quote': shot['action_evidence'][0]['quote'] = '不存在的打印机吐出两张已签合同'
    elif defect == 'other_shot_action': shot['action_evidence'][0]['shot_id'] = 'S02'
    elif defect == 'audio_instead_of_action':
        shot['action_evidence'][0].update(field='audio', quote=payload['scripts'][0]['shots'][0]['audio'])
    elif defect == 'missing_result': raw['result_audit'].pop()
    elif defect == 'duplicate_result': raw['result_audit'].append(copy.deepcopy(raw['result_audit'][0]))
    elif defect == 'unknown_target': raw['result_audit'][0]['target'] = 'title'
    elif defect == 'empty_explanation': raw['result_audit'][0]['explanation'] = ''
    elif defect == 'metadata_instead_of_executed_action':
        raw['result_audit'][0]['action_evidence'] = [{'script': 'short', 'shot_id': '',
            'field': 'resolution', 'quote': payload['scripts'][0]['resolution']}]
    with pytest.raises(ValueError):
        module.validate_script_review_report(raw, payload)


@pytest.mark.parametrize('failed_part', ['shot_audit', 'result_audit', 'issues', 'check'])
def test_one_failure_cannot_be_outvoted_by_other_true_checks(review_case, failed_part):
    payload, raw, _ = review_case
    if failed_part in ('shot_audit', 'result_audit'):
        raw[failed_part][0]['decision'] = 'failed'
    elif failed_part == 'issues':
        raw['issues'] = [{'problem': '合成实质问题', 'evidence': raw['shot_audit'][0]['action_evidence']}]
    else:
        raw['checks']['reasoning_coherent'] = False
    assert module.validate_script_review_report(raw, payload)['passed'] is False


@pytest.mark.parametrize('change', ['action', 'legal_note', 'feedback', 'source_text', 'stale_echo'])
def test_changed_candidate_or_evidence_invalidates_old_review(review_case, change):
    payload, raw, _ = review_case
    if change == 'action': payload['scripts'][0]['shots'][0]['action'] += '追加的新动作'
    elif change == 'legal_note': payload['scripts'][0]['legal_review_note'] += '新增条件'
    elif change == 'feedback': payload['evidence']['editor_feedback'] = '新增编辑要求'
    elif change == 'source_text': payload['evidence']['source_evidence'][0]['expression_analysis']['evidence'][0]['text'] += '新条件'
    else: raw['candidate_sha256'] = '0' * 64
    if change != 'stale_echo': payload.update(module.script_review_binding(payload))
    with pytest.raises(ValueError, match='SHA'):
        module.validate_script_review_report(raw, payload)


@pytest.mark.parametrize('defect', ['duration', 'closing_line', 'speaker'])
def test_review_recomputes_claimed_structure_before_any_client_call(defect):
    scripts = list(parse(pair_payload()))
    short = scripts[0]
    if defect == 'duration': scripts[0] = replace(short, target_duration_seconds=45)
    elif defect == 'closing_line': scripts[0] = replace(short, closing_line='与实际末镜不同')
    else:
        first = replace(short.shots[0], dialogue_speaker='不存在的角色')
        scripts[0] = replace(short, shots=(first, *short.shots[1:]))
    client = EvidenceReviewer()
    with pytest.raises(ValueError):
        module.review_pair(client, scripts, {'source_evidence': fixture_source_evidence()})
    assert client.calls == []


def test_missing_audit_retries_review_format_only_then_stops():
    class IncompleteReviewer(EvidenceReviewer):
        def chat_completion_tracked(self, messages, **kwargs):
            raw = json.loads(super().chat_completion_tracked(messages, **kwargs))
            raw['shot_audit'] = []
            return json.dumps(raw, ensure_ascii=False)
    client = IncompleteReviewer()
    with pytest.raises(RuntimeError, match='审稿结果格式无效'):
        module.review_pair(client, parse(pair_payload()), {'source_evidence': fixture_source_evidence()})
    assert len(client.calls) == module.SCRIPT_REVIEW_MAX_FORMAT_ATTEMPTS
    assert all(kwargs['caller'] == 'pre_video_script_review' for _, kwargs in client.calls)


def test_quote_typo_retry_identifies_field_and_keeps_failed_judgment():
    class TypoReviewer(EvidenceReviewer):
        def chat_completion_tracked(self, messages, **kwargs):
            payload = json.loads(messages[1]['content'])
            if payload.get('schema') == 'script_review_evidence_patch/v1':
                self.calls.append((copy.deepcopy(messages), kwargs))
                return json.dumps({target['path']: target['source_text']
                    for target in payload['evidence_targets']}, ensure_ascii=False)
            raw = json.loads(super().chat_completion_tracked(messages, **kwargs))
            raw['checks']['spoken_fit'] = False
            if len(self.calls) == 1:
                row = raw['shot_audit'][0]
                row['cross_field_evidence']['audio'] += '引文误增字'
            return json.dumps(raw, ensure_ascii=False)

    client = TypoReviewer()
    result = module.review_pair(client, parse(pair_payload()),
                                {'source_evidence': fixture_source_evidence()})
    assert len(client.calls) == 2
    patch_request = json.loads(client.calls[1][0][1]['content'])
    assert patch_request['allowed_paths'] == ['/shot_audit/0/cross_field_evidence/audio']
    assert patch_request['evidence_targets'][0]['required_match'] == 'full'
    assert patch_request['parent_report']['shot_audit'][0]['cross_field_evidence']['audio'].endswith('引文误增字')
    assert result['passed'] is False and result['checks']['spoken_fit'] is False
    assert result['format_attempts'] == 2


def test_spliced_and_cross_citations_are_collected_together_without_changing_failure():
    original = 'P1在左侧；P2在中央；P3在右侧。'
    other_original = 'P1在左侧；本场尚未签署；P3在右侧。'
    spliced = 'P1在左侧；P3在右侧。'
    data = pair_payload()
    data['short']['shots'][3]['end_frame'] = original
    data['short']['shots'][4]['end_frame'] = other_original
    data['long']['shots'][1]['start_frame'] = '当事人仍坐在桌左侧，付款记录在桌面右侧。'

    class SplicedReviewer(EvidenceReviewer):
        def chat_completion_tracked(self, messages, **kwargs):
            raw = json.loads(super().chat_completion_tracked(messages, **kwargs))
            raw['checks']['shot_continuity'] = False
            raw['issues'] = [{'problem': '合成测试保留的实质连续性问题', 'evidence': [
                {'script': 'short', 'shot_id': shot_id, 'field': 'end_frame',
                 'quote': spliced if len(self.calls) == 1 else text}
                for shot_id, text in [('S04', original), ('S05', other_original)]]}]
            if len(self.calls) == 1:
                row = next(row for row in raw['shot_audit'] if row['script'] == 'long' and row['shot_id'] == 'S02')
                row['cross_field_evidence']['start_frame'] = row['cross_field_evidence']['start_frame'].replace('仍', '')
            return json.dumps(raw, ensure_ascii=False)

    client = SplicedReviewer()
    result = module.review_pair(client, parse(data), {'source_evidence': fixture_source_evidence()})
    assert len(client.calls) == 2 and result['format_attempts'] == 2
    feedback = client.calls[1][0][-1]['content']
    assert 'contiguous_excerpt' in feedback and 'short/S04/end_frame' in feedback
    assert 'short/S05/end_frame' in feedback and 'long.S02.start_frame' in feedback
    assert 'received_quote' in feedback and spliced in feedback
    assert 'source_field' in feedback and original in feedback and '不能跳过中间文字、跨段拼接' in feedback
    assert '同一原报告的只读引文诊断' in feedback
    first_raw = json.loads(client.calls[1][0][-2]['content'])
    payload = json.loads(client.calls[0][0][1]['content'])
    before = copy.deepcopy(first_raw)
    diagnostics = module._review_evidence_diagnostics(first_raw, payload)
    assert len(diagnostics) == 3 and first_raw == before
    assert any('$.shot_audit[' in item['path'] for item in diagnostics)
    assert result['passed'] is False and result['checks']['shot_continuity'] is False
    assert [ref['quote'] for ref in result['issues'][0]['evidence']] == [original, other_original]
    assert all(kwargs['caller'] == 'pre_video_script_review' for _, kwargs in client.calls)
    assert data['short']['shots'][3]['end_frame'] == original


@pytest.mark.parametrize('value,missing,expected_type', [(123, False, 'int'), (None, True, 'missing')])
def test_generic_citation_diagnostic_identifies_nonstring_and_missing_field(value, missing, expected_type):
    shot = {'shot_id': 'S04'}
    if not missing:
        shot['end_frame'] = value
    payload = {'scripts': [{'format_kind': 'short', 'shots': [shot]}]}
    with pytest.raises(ValueError) as failure:
        module._validate_review_citation({'script': 'short', 'shot_id': 'S04', 'field': 'end_frame',
                                         'quote': '实际不存在的引文'}, payload)
    detail = json.loads('{' + str(failure.value).split('；{', 1)[1])
    assert detail['source_field'] is None and detail['source_field_type'] == expected_type
    assert detail['source_field_missing'] is missing


def test_generic_citation_diagnostic_caps_and_labels_both_literal_fields():
    payload = {'scripts': [{'format_kind': 'short', 'shots': [
        {'shot_id': 'S04', 'end_frame': '原' * 4500}]}]}
    quote = '误' * 4600
    with pytest.raises(ValueError) as failure:
        module._validate_review_citation({'script': 'short', 'shot_id': 'S04', 'field': 'end_frame',
                                         'quote': quote}, payload)
    detail = json.loads('{' + str(failure.value).split('；{', 1)[1])
    assert detail['source_field'] == '原' * 4000 and detail['source_field_truncated'] is True
    assert detail['received_quote'] == '误' * 4000 and detail['received_quote_truncated'] is True
    assert detail['source_field_length'] == 4500 and detail['received_quote_length'] == 4600
    assert payload['scripts'][0]['shots'][0]['end_frame'] == '原' * 4500 and quote == '误' * 4600


def test_generic_diagnostic_aligns_midfield_quote_before_showing_missing_text():
    lead = '这是字段前文，不是本条引文的起点。'
    prefix = 'P1在本人面前，左手压住纸张保持未签状态；' * 3
    original = lead + prefix + 'P2仍位于中央；P3笔身水平。'
    quote = prefix + 'P3笔身水平。'
    payload = {'scripts': [{'format_kind': 'short', 'shots': [{'shot_id': 'S04', 'end_frame': original}]}]}
    report = {'issues': [{'evidence': [{'script': 'short', 'shot_id': 'S04', 'field': 'end_frame', 'quote': quote}]}]}
    diagnostics = module._review_evidence_diagnostics(report, payload)
    assert len(diagnostics) == 1
    detail = diagnostics[0]
    assert detail['diagnostic_alignment'] == 'exact_quote_prefix'
    assert detail['source_excerpt_offset'] == len(lead)
    assert detail['source_difference_offset'] == len(lead) + len(prefix) + 1  # P2 versus P3.
    assert 'P2仍位于中央' in detail['source_context'] and lead not in detail['source_context']


def test_evidence_diagnostics_leave_invalid_location_to_main_gate():
    report = {'shot_audit': [{'script': ['short'], 'shot_id': 'S04', 'cross_field_evidence': {'audio': '错误'}}]}
    assert module._review_evidence_diagnostics(report, {'scripts': []}) == []


def test_review_projection_is_identical_for_live_and_saved_and_detached():
    scripts = parse(pair_payload())
    saved = [asdict(script) for script in scripts]
    before = copy.deepcopy(saved)
    live = module.build_script_review_rows(scripts)
    restored = module.build_script_review_rows(saved)
    assert live == restored
    saved[0]['generation']['reviews'] = [{'schema': 'old', 'passed': True}]
    saved[0]['generation']['unrelated_cache_flag'] = True
    assert module.build_script_review_rows(saved) == live
    restored[0]['characters'][0]['performance_arc'] = 'changed projection only'
    assert saved[0]['characters'] == before[0]['characters']
    assert module.build_script_review_rows(scripts) == live


@pytest.mark.parametrize('field', ['dialogue', 'audio', 'camera_angle', 'action', 'emotion_and_performance'])
def test_saved_actual_field_changes_change_candidate_binding(field):
    saved = [asdict(script) for script in parse(pair_payload())]
    first = module.script_review_binding({'scripts': module.build_script_review_rows(saved), 'evidence': {}})
    saved[0]['shots'][0][field] += '实际改变'
    second = module.script_review_binding({'scripts': module.build_script_review_rows(saved), 'evidence': {}})
    assert first['candidate_sha256'] != second['candidate_sha256']


@pytest.mark.parametrize('defect', ['missing_quote', 'unknown_quote', 'wrong_quote_type', 'invented_quote',
    'partial_dialogue', 'partial_audio', 'partial_camera', 'missing_check', 'unknown_check',
    'unknown_check_value', 'boolean_check', 'empty_dialogue_action_note'])
def test_cross_field_missing_partial_or_unknown_evidence_rejects(review_case, defect):
    payload, raw, _ = review_case
    row = raw['shot_audit'][0]
    quotes, checks = row['cross_field_evidence'], row['cross_checks']
    if defect == 'missing_quote': quotes.pop('blocking')
    elif defect == 'unknown_quote': quotes['unknown'] = '未知'
    elif defect == 'wrong_quote_type': quotes['start_frame'] = ['原文']
    elif defect == 'invented_quote': quotes['composition'] = '同侧并排坐在沙发上'
    elif defect.startswith('partial_'):
        key = {'partial_dialogue': 'dialogue', 'partial_audio': 'audio', 'partial_camera': 'camera_angle'}[defect]
        quotes[key] = quotes[key][:2]
    elif defect == 'missing_check': checks.pop('spatial')
    elif defect == 'unknown_check': checks['new_check'] = 'passed'
    elif defect == 'unknown_check_value': checks['spatial'] = 'unknown'
    elif defect == 'boolean_check': checks['spatial'] = True
    elif defect == 'empty_dialogue_action_note': row['dialogue_action_note'] = ''
    with pytest.raises(ValueError):
        module.validate_script_review_report(raw, payload)


@pytest.mark.parametrize('check', module.REVIEW_CROSS_CHECKS)
def test_failed_cross_check_cannot_be_outvoted_even_when_row_claims_passed(review_case, check):
    payload, raw, _ = review_case
    raw['shot_audit'][0]['cross_checks'][check] = 'failed'
    assert raw['shot_audit'][0]['decision'] == 'passed'
    assert module.validate_script_review_report(raw, payload)['passed'] is False


@pytest.mark.parametrize('defect', ['missing', 'duplicate', 'unknown_character', 'unknown_version',
    'missing_spoken', 'reordered_spoken', 'extra_spoken', 'missing_dialogue', 'partial_dialogue',
    'invented_dialogue', 'wrong_arc', 'partial_voice', 'missing_performance', 'invented_performance',
    'empty_assessment', 'unknown_decision'])
def test_character_audit_cannot_skip_actual_speech_or_performance(review_case, defect):
    payload, raw, _ = review_case
    row = raw['character_audit'][0]
    if defect == 'missing': raw['character_audit'].pop()
    elif defect == 'duplicate': raw['character_audit'].append(copy.deepcopy(row))
    elif defect == 'unknown_character': row['character_name'] = '另一个人'
    elif defect == 'unknown_version': row['script'] = 'unknown'
    elif defect == 'missing_spoken': row['spoken_shot_ids'].pop()
    elif defect == 'reordered_spoken': row['spoken_shot_ids'].reverse()
    elif defect == 'extra_spoken': row['spoken_shot_ids'].append('S99')
    elif defect == 'missing_dialogue': row['dialogue_quotes'].pop('S01')
    elif defect == 'partial_dialogue': row['dialogue_quotes']['S01'] = row['dialogue_quotes']['S01'][:2]
    elif defect == 'invented_dialogue': row['dialogue_quotes']['S01'] = '根本不存在的反问'
    elif defect == 'wrong_arc': row['performance_arc_quote'] = '常用反问'
    elif defect == 'partial_voice': row['voice_quote'] = row['voice_quote'][:2]
    elif defect == 'missing_performance': row['performance_quotes'].pop('S06')
    elif defect == 'invented_performance': row['performance_quotes']['S01'] = '暴怒拍桌'
    elif defect == 'empty_assessment': row['assessment'] = ''
    elif defect == 'unknown_decision': row['decision'] = 'pending'
    with pytest.raises(ValueError):
        module.validate_script_review_report(raw, payload)


@pytest.mark.parametrize('defect', ['missing_version', 'duplicate_version', 'unknown_version', 'missing_group',
    'empty_group', 'missing_action', 'missing_dialogue', 'other_stage', 'other_version',
    'metadata_quote', 'empty_property', 'unknown_decision'])
def test_conflict_audit_requires_stage_bound_actual_action_and_dialogue(review_case, defect):
    payload, raw, _ = review_case
    row = raw['conflict_audit'][0]
    if defect == 'missing_version': raw['conflict_audit'].pop()
    elif defect == 'duplicate_version': raw['conflict_audit'].append(copy.deepcopy(row))
    elif defect == 'unknown_version': row['script'] = 'unknown'
    elif defect == 'missing_group': row['evidence'].pop('turn')
    elif defect == 'empty_group': row['evidence']['turn'] = []
    elif defect == 'missing_action': row['evidence']['turn'] = row['evidence']['turn'][1:]
    elif defect == 'missing_dialogue': row['evidence']['turn'] = row['evidence']['turn'][:1]
    elif defect == 'other_stage': row['evidence']['turn'] = copy.deepcopy(row['evidence']['opening'])
    elif defect == 'other_version': row['evidence']['turn'] = copy.deepcopy(raw['conflict_audit'][1]['evidence']['turn'])
    elif defect == 'metadata_quote': row['evidence']['turn'] = [{'script': 'short', 'shot_id': '',
        'field': 'resolution', 'quote': payload['scripts'][0]['resolution']}]
    elif defect == 'empty_property': row['disputed_property'] = ''
    elif defect == 'unknown_decision': row['decision'] = 'not_reviewed'
    with pytest.raises(ValueError):
        module.validate_script_review_report(raw, payload)


@pytest.mark.parametrize('audit', ['character_audit', 'conflict_audit'])
def test_failed_new_audit_cannot_be_outvoted(review_case, audit):
    payload, raw, _ = review_case
    raw[audit][0]['decision'] = 'failed'
    assert module.validate_script_review_report(raw, payload)['passed'] is False


def test_v1_report_cannot_be_silently_promoted_even_with_complete_v2_fields(review_case):
    payload, _, result = review_case
    assert result['schema'] == module.CURRENT_SCRIPT_REVIEW_SCHEMA
    result['schema'] = 'script_editorial_evidence_review/v1'
    with pytest.raises(ValueError, match='schema'):
        module.validate_saved_script_review_report(result, payload)


def test_silent_shot_and_silent_character_have_exact_empty_actual_speech():
    data = pair_payload()
    for kind in ('short', 'long'):
        data[kind]['characters'].append({'name': '旁听人', 'identity': '现场当事人的同伴',
            'appearance': '短发', 'wardrobe': '灰色外套', 'performance_arc': '全程安静观察'})
        for shot in data[kind]['shots']:
            shot['participants'].append('旁听人')
        data[kind]['shots'][0].update(dialogue='', dialogue_speaker='', dialogue_mode='none')
    client = EvidenceReviewer()
    report = module.review_pair(client, parse(data), {'source_evidence': fixture_source_evidence()})
    assert report['passed'] is True
    first = report['shot_audit'][0]
    assert first['cross_field_evidence']['dialogue'] == ''
    silent = next(r for r in report['character_audit'] if r['character_name'] == '旁听人')
    assert silent['spoken_shot_ids'] == [] and silent['dialogue_quotes'] == {} and silent['voice_quote'] == ''


@pytest.mark.parametrize('raw', [
    '{"checks":{"reasoning_coherent":false,"reasoning_coherent":true}}',
    '{"checks":{},"checks":{"reasoning_coherent":true}}',
    '{"shot_audit":[{"decision":"failed","decision":"passed"}]}',
])
def test_duplicate_json_fields_never_silently_override_failure(raw):
    with pytest.raises(ValueError, match='重复字段'):
        module._parse_script_review_json(raw)


def test_format_retry_points_to_unescaped_quote_and_preserves_substantive_failure():
    class QuoteReviewer(EvidenceReviewer):
        def chat_completion_tracked(self, messages, **kwargs):
            raw = json.loads(super().chat_completion_tracked(messages, **kwargs))
            raw['shot_audit'][0]['cross_checks']['spatial'] = 'failed'
            raw['shot_audit'][0]['continuity_note'] = '检查"对坐"是否一致'
            response = json.dumps(raw, ensure_ascii=False)
            if len(self.calls) == 1:
                response = response.replace(json.dumps('检查"对坐"是否一致', ensure_ascii=False),
                                            '"检查"对坐"是否一致"', 1)
            return response
    client = QuoteReviewer()
    report = module.review_pair(client, parse(pair_payload()), {'source_evidence': fixture_source_evidence()})
    assert len(client.calls) == 2 and report['format_attempts'] == 2 and report['passed'] is False
    repair = client.calls[1][0][-1]['content']
    assert 'line=' in repair and 'column=' in repair and 'char=' in repair
    assert '附近原文以JSON字符串转义展示=' in repair and '对坐' in repair
    assert '反斜杠转义' in repair and '保留所有实质失败判断' in repair
    assert all(kwargs['caller'] == 'pre_video_script_review' for _, kwargs in client.calls)
    assert report['shot_audit'][0]['continuity_note'] == '检查"对坐"是否一致'


def test_repeated_duplicate_keys_only_retries_report_then_stops():
    class DuplicateReviewer(EvidenceReviewer):
        def chat_completion_tracked(self, messages, **kwargs):
            raw = super().chat_completion_tracked(messages, **kwargs)
            return raw.replace('"spatial": "passed"', '"spatial": "failed", "spatial": "passed"', 1)
    client = DuplicateReviewer()
    with pytest.raises(RuntimeError, match='重复字段'):
        module.review_pair(client, parse(pair_payload()), {'source_evidence': fixture_source_evidence()})
    assert len(client.calls) == module.SCRIPT_REVIEW_MAX_FORMAT_ATTEMPTS
    assert '不能覆盖先前判断' in client.calls[1][0][-1]['content']


def test_three_format_attempts_repair_json_then_conflict_coverage_but_keep_failure():
    class SequentialReviewer(EvidenceReviewer):
        def chat_completion_tracked(self, messages, **kwargs):
            raw = json.loads(super().chat_completion_tracked(messages, **kwargs))
            raw['checks']['shot_continuity'] = False
            if len(self.calls) == 1:
                return '{invalid JSON'
            if len(self.calls) == 2:
                for conflict in raw['conflict_audit']:
                    for refs in conflict['evidence'].values():
                        refs[:] = [ref for ref in refs if ref['field'] == 'action']
            return json.dumps(raw, ensure_ascii=False)

    client = SequentialReviewer()
    result = module.review_pair(client, parse(pair_payload()), {'source_evidence': fixture_source_evidence()})
    assert len(client.calls) == module.SCRIPT_REVIEW_MAX_FORMAT_ATTEMPTS == 3
    assert result['format_attempts'] == 3 and result['passed'] is False
    assert result['checks']['shot_continuity'] is False
    third_messages = client.calls[2][0]
    second_raw = json.loads(third_messages[-2]['content'])
    before = copy.deepcopy(second_raw)
    payload = json.loads(third_messages[1]['content'])
    diagnostics = module._review_evidence_diagnostics(second_raw, payload)
    assert len(diagnostics) == 8 and second_raw == before
    assert {(d['script'], d['group']) for d in diagnostics} == {
        (kind, group) for kind in ('short', 'long') for group in module.REVIEW_CONFLICT_GROUPS}
    for item in diagnostics:
        assert item['required'] == ['action', 'dialogue']
        assert item['covered'] == ['action'] and item['missing'] == ['dialogue']
        assert item['allowed_shot_ids'] and 'quote' not in item
        assert item['location'] in third_messages[-1]['content']
    with pytest.raises(ValueError, match='short.conflict_audit.opening'):
        module.validate_script_review_report(second_raw, payload)
    assert all(kwargs['caller'] == 'pre_video_script_review' for _, kwargs in client.calls)


def test_two_characters_wrong_spoken_endpoints_are_diagnosed_together_and_failure_remains():
    data = pair_payload()
    for kind in ('short', 'long'):
        data[kind]['characters'].append({**data[kind]['characters'][0], 'name': '同伴'})
        for index, shot in enumerate(data[kind]['shots']):
            shot['participants'] = ['当事人', '同伴']
            shot['dialogue_speaker'] = ['当事人', '同伴'][index % 2]

    class SpokenEndpointReviewer(EvidenceReviewer):
        def chat_completion_tracked(self, messages, **kwargs):
            raw = json.loads(super().chat_completion_tracked(messages, **kwargs))
            raw['checks']['shot_continuity'] = False
            if len(self.calls) == 1:
                payload = json.loads(messages[1]['content'])
                short = next(script for script in payload['scripts'] if script['format_kind'] == 'short')
                for row in raw['character_audit']:
                    if row['script'] == 'short':
                        spoken = row['spoken_shot_ids']
                        row['performance_quotes'] = {shot['shot_id']: shot['emotion_and_performance']
                            for shot in short['shots'] if shot['shot_id'] in (spoken[0], spoken[-1])}
            return json.dumps(raw, ensure_ascii=False)

    client = SpokenEndpointReviewer()
    result = module.review_pair(client, parse(data), {'source_evidence': fixture_source_evidence()})
    assert len(client.calls) == 2 and module.SCRIPT_REVIEW_MAX_FORMAT_ATTEMPTS == 3
    feedback = client.calls[1][0][-1]['content']
    first_raw = json.loads(client.calls[1][0][-2]['content'])
    payload = json.loads(client.calls[0][0][1]['content'])
    before = copy.deepcopy(first_raw)
    diagnostics = module._review_evidence_diagnostics(first_raw, payload)
    assert len(diagnostics) == 2 and first_raw == before
    by_name = {item['character_name']: item for item in diagnostics}
    assert by_name['当事人']['received_shot_ids'] == ['S01', 'S05']
    assert by_name['当事人']['missing'] == ['S06'] and by_name['当事人']['extra'] == ['S05']
    assert by_name['同伴']['received_shot_ids'] == ['S02', 'S06']
    assert by_name['同伴']['missing'] == ['S01'] and by_name['同伴']['extra'] == ['S02']
    for item in diagnostics:
        assert item['required_shot_ids'] == ['S01', 'S06'] and item['location'] in feedback
        assert item['basis'] == 'participants_first_and_last_visible_shots_not_spoken_shots'
        assert 'quote' not in item and '不按dialogue_speaker' in item['notice']
    with pytest.raises(ValueError, match='required_shot_ids'):
        module.validate_script_review_report(first_raw, payload)
    assert result['passed'] is False and result['checks']['shot_continuity'] is False
    assert result['format_attempts'] == 2
    assert all(kwargs['caller'] == 'pre_video_script_review' for _, kwargs in client.calls)
