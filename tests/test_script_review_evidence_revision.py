"""Offline evidence-only review repairs cannot rewrite editorial judgments."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from src.trend_intelligence import script_pair as gate
from src.trend_intelligence.review_evidence_patch import (
    PATCH_SCHEMA, FullReviewRequired, apply_evidence_patch, canonical_sha,
)
from script_pair_fixture import FixtureClient, fixture_source_evidence, pair_payload
from test_script_pair import parse
from test_script_review_gate import review_case


@pytest.fixture(autouse=True)
def review_patch_uses_isolated_output_root(monkeypatch):
    from src.trend_intelligence.pre_video_script import PreVideoScriptService
    monkeypatch.setattr(PreVideoScriptService, '_resolve_output_dir',
                        staticmethod(lambda request: Path(request.output_dir).resolve()))


def leaf(document, pointer):
    parts = pointer.lstrip('/').split('/')
    current = document
    for part in parts:
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current


def set_leaf(document, pointer, value):
    parts = pointer.lstrip('/').split('/')
    current = document
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    current[int(parts[-1]) if isinstance(current, list) else parts[-1]] = value


QUOTE_PATHS = (
    '/shot_audit/0/cross_field_evidence/audio',
    '/shot_audit/0/cross_field_evidence/dialogue',
    '/shot_audit/0/cross_field_evidence/camera_angle',
    '/shot_audit/0/cross_field_evidence/end_frame',
    '/character_audit/0/performance_arc_quote',
    '/character_audit/0/voice_quote',
    '/character_audit/0/dialogue_quotes/S01',
    '/character_audit/0/performance_quotes/S06',
)


@pytest.mark.parametrize('path', QUOTE_PATHS)
def test_only_diagnosed_existing_quote_is_replaced_without_changing_judgment(review_case, path):
    payload, valid, _ = review_case
    damaged = copy.deepcopy(valid)
    original_quote = leaf(valid, path)
    set_leaf(damaged, path, original_quote + '引文错字')
    before, payload_before = copy.deepcopy(damaged), copy.deepcopy(payload)
    targets = gate.plan_review_evidence_patch(damaged, payload)
    assert targets and {target['path'] for target in targets} == {path}
    target = targets[0]
    assert set(target) == {'path', 'source_text', 'required_match', 'empty_allowed'}
    assert original_quote in target['source_text']
    assert damaged == before and payload == payload_before
    replacements = {path: original_quote}
    result = apply_evidence_patch(damaged, replacements, targets)
    assert result == valid and result is not damaged
    assert damaged == before and replacements == {path: original_quote}
    assert gate.validate_script_review_report(result, payload)['passed'] is True
    assert result['checks'] == damaged['checks'] and result['issues'] == damaged['issues']
    assert result['summary'] == damaged['summary']


@pytest.fixture
def damaged_quote(review_case):
    payload, valid, _ = review_case
    damaged = copy.deepcopy(valid)
    path = QUOTE_PATHS[0]
    set_leaf(damaged, path, leaf(valid, path) + '与原文不一致')
    targets = gate.plan_review_evidence_patch(damaged, payload)
    return payload, valid, damaged, targets, path


def test_valid_report_does_not_request_evidence_revision(review_case):
    payload, valid, _ = review_case
    assert gate.plan_review_evidence_patch(valid, payload) is None


@pytest.mark.parametrize('defect', ['candidate_sha256', 'evidence_sha256', 'missing_shot',
    'duplicate_shot', 'unknown_shot', 'unknown_decision', 'nonstr_quote', 'missing_quote',
    'missing_character', 'unknown_check_type', 'empty_finding'])
def test_binding_structure_or_missing_review_cannot_be_laundered_as_quote_repair(damaged_quote, defect):
    payload, _, damaged, _, path = damaged_quote
    if defect in ('candidate_sha256', 'evidence_sha256'):
        damaged[defect] = '0' * 64
    elif defect == 'missing_shot': damaged['shot_audit'].pop()
    elif defect == 'duplicate_shot': damaged['shot_audit'].append(copy.deepcopy(damaged['shot_audit'][0]))
    elif defect == 'unknown_shot': damaged['shot_audit'][0]['shot_id'] = 'S99'
    elif defect == 'unknown_decision': damaged['shot_audit'][0]['decision'] = 'unreviewed'
    elif defect == 'nonstr_quote': set_leaf(damaged, path, 123)
    elif defect == 'missing_quote': damaged['shot_audit'][0]['cross_field_evidence'].pop('audio')
    elif defect == 'missing_character': damaged['character_audit'].pop()
    elif defect == 'unknown_check_type': damaged['checks']['spoken_fit'] = 'true'
    else: damaged['shot_audit'][0]['dialogue_action_note'] = ''
    assert gate.plan_review_evidence_patch(damaged, payload) is None


@pytest.mark.parametrize('block', ['issues', 'action_evidence', 'result_evidence', 'conflict_evidence'])
def test_general_citations_and_issue_text_require_full_review_not_patch(damaged_quote, block):
    payload, _, damaged, _, _ = damaged_quote
    if block == 'issues':
        damaged['issues'] = [{'problem': '合成失败问题须完整保留',
                             'evidence': copy.deepcopy(damaged['shot_audit'][0]['action_evidence'])}]
        citation = damaged['issues'][0]['evidence'][0]
    elif block == 'action_evidence': citation = damaged['shot_audit'][0]['action_evidence'][0]
    elif block == 'result_evidence': citation = damaged['result_audit'][0]['action_evidence'][0]
    else: citation = damaged['conflict_audit'][0]['evidence']['opening'][0]
    citation['quote'] += '非原文'
    assert gate.plan_review_evidence_patch(damaged, payload) is None


@pytest.mark.parametrize('path,value', [('/checks/spoken_fit', True), ('/issues', []),
    ('/summary', '改成已通过'), ('/shot_audit/0/decision', 'passed'),
    ('/shot_audit/0/continuity_note', '覆盖原发现'),
    ('/shot_audit/0/dialogue_action_note', '覆盖原发现'),
    ('/shot_audit/0/cross_checks/spatial', 'passed'),
    ('/character_audit/0/assessment', '覆盖角色判断'),
    ('/conflict_audit/0/positions', '新立场'), ('/passed', True), ('/status', 'passed')])
def test_patch_cannot_add_any_judgment_or_status_field(damaged_quote, path, value):
    _, valid, damaged, targets, allowed = damaged_quote
    before = copy.deepcopy(damaged)
    with pytest.raises(ValueError):
        apply_evidence_patch(damaged, {allowed: leaf(valid, allowed), path: value}, targets)
    assert damaged == before


@pytest.mark.parametrize('kind', ['missing', 'empty', 'spaces', 'object', 'null', 'noncanonical', 'undamaged'])
def test_patch_must_match_exact_allowed_paths_and_nonempty_strings(damaged_quote, kind):
    _, valid, damaged, targets, path = damaged_quote
    replacements = {path: leaf(valid, path)}
    if kind == 'missing': replacements = {}
    elif kind == 'empty': replacements[path] = ''
    elif kind == 'spaces': replacements[path] = '  '
    elif kind == 'object': replacements[path] = {'quote': '不允许整个对象'}
    elif kind == 'null': replacements[path] = None
    elif kind == 'noncanonical': replacements = {path.replace('/0/', '/00/'): leaf(valid, path)}
    else: replacements[QUOTE_PATHS[1]] = leaf(valid, QUOTE_PATHS[1])
    with pytest.raises(ValueError):
        apply_evidence_patch(damaged, replacements, targets)


def test_correct_quote_does_not_erase_actual_failed_checks_or_issues(damaged_quote):
    payload, valid, damaged, _, path = damaged_quote
    damaged['checks']['spoken_fit'] = False
    damaged['shot_audit'][0]['cross_checks']['voice_performance'] = 'failed'
    damaged['character_audit'][0]['decision'] = 'failed'
    damaged['issues'] = [{'problem': '合成真实失败判断，不准仅靠修引文移除',
                         'evidence': copy.deepcopy(damaged['shot_audit'][0]['action_evidence'])}]
    targets = gate.plan_review_evidence_patch(damaged, payload)
    assert targets
    repaired = apply_evidence_patch(damaged, {path: leaf(valid, path)}, targets)
    assert gate.validate_script_review_report(repaired, payload)['passed'] is False
    for field in ('checks', 'issues', 'summary'):
        assert repaired[field] == damaged[field]
    assert repaired['character_audit'][0]['decision'] == 'failed'


def test_model_can_require_substantive_reassessment_instead_of_changing_evidence(damaged_quote):
    _, _, damaged, targets, _ = damaged_quote
    before = copy.deepcopy(damaged)
    with pytest.raises(FullReviewRequired):
        apply_evidence_patch(damaged, {'full_review_required': '真实台词动摇原有通过判断，需要重新审查。'}, targets)
    assert damaged == before


def test_invented_replacement_is_still_rejected_by_evidence_gate(damaged_quote):
    payload, _, damaged, targets, path = damaged_quote
    with pytest.raises(ValueError):
        repaired = apply_evidence_patch(damaged, {path: '原稿根本没有的声线和台词'}, targets)
        gate.validate_script_review_report(repaired, payload)


def test_canonical_hash_binds_content_and_ignores_object_key_order(damaged_quote):
    _, _, damaged, _, _ = damaged_quote
    reordered = dict(reversed(list(damaged.items())))
    assert canonical_sha(reordered) == canonical_sha(damaged)
    changed = copy.deepcopy(damaged)
    changed['summary'] += '改变了实质报告'
    assert canonical_sha(changed) != canonical_sha(damaged)


class PatchReviewer(FixtureClient):
    """Saves actual synthetic full/patch responses through the production entry."""
    def __init__(self, patch_modes=('valid',), *, malformed_full=0, fail_after_refusal=False):
        super().__init__()
        self.patch_modes = patch_modes
        self.patch_count = self.full_count = 0
        self.malformed_full = malformed_full
        self.fail_after_refusal = fail_after_refusal

    def chat_completion_tracked(self, messages, **kwargs):
        payload = json.loads(next(message['content'] for message in messages if message['role'] == 'user'))
        if payload.get('schema') == PATCH_SCHEMA:
            self.calls.append((copy.deepcopy(messages), kwargs))
            mode = self.patch_modes[min(self.patch_count, len(self.patch_modes) - 1)]
            self.patch_count += 1
            replacements = {row['path']: row['source_text'] for row in payload['evidence_targets']}
            if mode == 'refusal':
                return json.dumps({'full_review_required': '实际原文使之前判断不能成立，需要完整重审。'}, ensure_ascii=False)
            if mode == 'extra_key': replacements['/summary'] = '越权修改原实质判断'
            elif mode == 'invented': replacements[next(iter(replacements))] += '仍有不存在的字'
            raw = json.dumps(replacements, ensure_ascii=False)
            if mode == 'duplicate':
                path = next(iter(replacements))
                return '{' + json.dumps(path) + ': "earlier conflicting quote", ' + raw[1:]
            return raw
        response = super().chat_completion_tracked(messages, **kwargs)
        if kwargs.get('caller') == 'pre_video_script_review':
            self.full_count += 1
            if self.full_count <= self.malformed_full:
                return '{"checks":'
            report = json.loads(response)
            if self.full_count == 1:
                report['shot_audit'][0]['cross_field_evidence']['audio'] += '首次报告抄错字'
            elif self.fail_after_refusal:
                report['checks']['spoken_fit'] = False
                report['issues'] = [{'problem': '完整复审确认的合成实质问题',
                                     'evidence': copy.deepcopy(report['shot_audit'][0]['action_evidence'])}]
            return json.dumps(report, ensure_ascii=False)
        return response


def review_with_trace(client, tmp_path):
    return gate.review_pair(client, parse(pair_payload()), {'source_evidence': fixture_source_evidence()},
                            trace_path=tmp_path / 'review_1.json')


def test_two_bad_quote_attempts_still_use_only_three_total_calls(tmp_path):
    client = PatchReviewer(('invented', 'valid'))
    result = review_with_trace(client, tmp_path)
    assert result['passed'] and result['format_attempts'] == gate.SCRIPT_REVIEW_MAX_FORMAT_ATTEMPTS == 3
    assert len(client.calls) == 3 and client.full_count == 1 and client.patch_count == 2
    assert all(kwargs['use_cache'] is False for _, kwargs in client.calls)
    for attempt in (2, 3):
        request = json.loads((tmp_path / f'review_1_request_{attempt}.json').read_bytes())
        assert json.loads(request[1]['content'])['schema'] == PATCH_SCHEMA


@pytest.mark.parametrize('mode', ['duplicate', 'extra_key', 'invented'])
def test_invalid_patch_exhaustion_requires_real_full_review_without_third_patch(tmp_path, mode):
    client = PatchReviewer((mode,))
    report = review_with_trace(client, tmp_path)
    assert report['passed'] and report['format_attempts'] == 4
    assert len(client.calls) == 4 and client.full_count == 2 and client.patch_count == 2
    assert (tmp_path / 'review_1_response_2.txt').is_file()
    assert (tmp_path / 'review_1_response_3.txt').is_file()
    fourth = json.loads((tmp_path / 'review_1_request_4.json').read_bytes())
    assert json.loads(fourth[1]['content'])['review_contract_schema'] == gate.CURRENT_SCRIPT_REVIEW_SCHEMA
    assert not (tmp_path / 'review_1_request_5.json').exists()
    if mode == 'duplicate':
        raw = (tmp_path / 'review_1_response_2.txt').read_text(encoding='utf-8')
        assert 'earlier conflicting quote' in raw
        with pytest.raises(ValueError, match='重复'):
            gate._parse_script_review_json(raw)


def test_model_refusal_triggers_real_full_review_and_preserves_its_failed_judgment(tmp_path):
    client = PatchReviewer(('refusal',), fail_after_refusal=True)
    result = review_with_trace(client, tmp_path)
    assert not result['passed'] and result['checks']['spoken_fit'] is False and result['issues']
    assert len(client.calls) == 3 and client.full_count == 2 and client.patch_count == 1
    third = json.loads((tmp_path / 'review_1_request_3.json').read_bytes())
    assert json.loads(next(m['content'] for m in third if m['role'] == 'user'))['review_contract_schema'] == gate.CURRENT_SCRIPT_REVIEW_SCHEMA
    assert not (tmp_path / 'review_1_merged_2.json').exists()


def test_malformed_full_reports_keep_original_full_retry_path(tmp_path):
    client = PatchReviewer(malformed_full=2)
    result = review_with_trace(client, tmp_path)
    assert result['passed'] and result['format_attempts'] == 3
    assert len(client.calls) == client.full_count == 3 and client.patch_count == 0
    assert (tmp_path / 'review_1_response_1.txt').read_text(encoding='utf-8') == '{"checks":'
    assert not list(tmp_path.glob('review_1_merged_*.json'))


@pytest.fixture
def saved_patch_case(tmp_path):
    from test_saved_script_review_current import isolated_service
    from test_pre_video_script import NOW
    from src.trend_intelligence.pre_video_script import PreVideoScriptRequest
    from src.web.trend_dashboard import _load_saved_script_pair
    client = PatchReviewer()
    pair = isolated_service(client, tmp_path).generate(PreVideoScriptRequest(
        account_key='account01', short_seconds=60, recent_video_types=('mixed',),
        output_dir=str(tmp_path)), now=NOW)
    return {'root': tmp_path, 'client': client, 'pair': pair,
            'items': _load_saved_script_pair(pair.short.script.account_uuid, tmp_path),
            'trace': Path(pair.short.script.generation['trace_dir'])}


def saved_status(case):
    from src.trend_intelligence.saved_script_review import current_saved_script_review
    before = len(case['client'].calls)
    result = current_saved_script_review(case['items'], allowed_root=case['root'])
    assert len(case['client'].calls) == before
    return result


def test_saved_gate_replays_actual_base_and_patch_not_a_fabricated_full_response(saved_patch_case):
    case = saved_patch_case
    trace = case['trace']
    report = json.loads((trace / 'review_1.json').read_bytes())
    base = json.loads((trace / 'review_1_response_1.txt').read_bytes())
    patch = json.loads((trace / 'review_1_response_2.txt').read_bytes())
    merged = json.loads((trace / 'review_1_merged_2.json').read_bytes())
    assert set(patch) == {'/shot_audit/0/cross_field_evidence/audio'}
    assert patch != merged and base != merged
    for key in ('checks', 'issues', 'summary'):
        assert merged[key] == base[key] == report[key]
    assert report['format_trace_sha256'] == hashlib.sha256((trace / 'review_1_attempt_chain.json').read_bytes()).hexdigest()
    assert saved_status(case)['current_passed']
    assert len(case['client'].calls) == 3  # Author, full review, actual evidence patch.


@pytest.mark.parametrize('artifact', ['review_1_response_1.txt', 'review_1_response_2.txt',
    'review_1_request_2.json', 'review_1_merged_2.json', 'review_1_attempt_chain.json'])
def test_tampered_patch_chain_or_parent_bytes_invalidates_saved_approval(saved_patch_case, artifact):
    case = saved_patch_case
    assert saved_status(case)['current_passed']
    path = case['trace'] / artifact
    path.write_bytes(path.read_bytes() + b'\n')
    result = saved_status(case)
    assert result['status'] == 'needs_review' and not result['current_passed']


def test_replacing_actual_patch_response_with_merged_full_report_is_rejected(saved_patch_case):
    case = saved_patch_case
    trace = case['trace']
    (trace / 'review_1_response_2.txt').write_bytes((trace / 'review_1_merged_2.json').read_bytes())
    assert not saved_status(case)['current_passed']


def test_removing_chain_binding_cannot_downgrade_a_patch_to_fake_legacy_full_response(saved_patch_case):
    case = saved_patch_case
    trace = case['trace']
    report_path = trace / 'review_1.json'
    report = json.loads(report_path.read_bytes())
    del report['format_trace_sha256']
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    for item in case['items']:
        path = Path(item['script_json_path'])
        script = json.loads(path.read_bytes())
        script['generation']['reviews'][0]['report'] = copy.deepcopy(report)
        path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding='utf-8')
        item['json'] = path.read_text(encoding='utf-8')
    (trace / 'review_1_response_2.txt').write_bytes((trace / 'review_1_merged_2.json').read_bytes())
    assert (trace / 'review_1_attempt_chain.json').is_file()
    result = saved_status(case)
    assert result['status'] == 'needs_review' and not result['current_passed']
    assert '不能降级' in result['reason']


def test_patch_prompt_changes_do_not_invalidate_a_full_report_only_baseline(tmp_path, monkeypatch):
    from test_saved_script_review_current import isolated_service
    from test_pre_video_script import NOW
    from src.trend_intelligence.pre_video_script import PreVideoScriptRequest
    from src.web.trend_dashboard import _load_saved_script_pair
    from src.trend_intelligence import review_evidence_patch
    client = FixtureClient()
    pair = isolated_service(client, tmp_path).generate(PreVideoScriptRequest(
        account_key='account01', short_seconds=60, recent_video_types=('mixed',),
        output_dir=str(tmp_path)), now=NOW)
    case = {'root': tmp_path, 'client': client,
            'items': _load_saved_script_pair(pair.short.script.account_uuid, tmp_path)}
    assert saved_status(case)['current_passed']
    replacement = tmp_path / 'new_patch_prompt.md'
    replacement.write_text('更新引文补丁指令，不是更新整稿审稿规则。', encoding='utf-8')
    monkeypatch.setattr(review_evidence_patch, 'PATCH_PROMPT_PATH', replacement)
    assert saved_status(case)['current_passed'] and len(client.calls) == 2
