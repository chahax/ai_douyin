"""Synthetic, offline checks for the story-to-production approval boundary."""
import copy
import hashlib
import json

import pytest

from scripts import run_screenplay_stage as stage
from src.trend_intelligence.script_screenplay import STORY_REVIEW_CHECKS
from test_script_screenplay import screenplay
from story_review_fixture import enrich_story_review


CHECKS = tuple(sorted(STORY_REVIEW_CHECKS))
WORKFLOW_SHA = hashlib.sha256(b'synthetic workflow').hexdigest()
SOURCE_SHA = hashlib.sha256(b'synthetic evidence').hexdigest()


@pytest.fixture(autouse=True)
def forbid_model_requests(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('These review-boundary tests must never call a model')
    monkeypatch.setattr(stage, 'LLMClient', forbidden)


@pytest.fixture
def bound_story_review():
    story = screenplay()
    shots = story['version']['shots']
    raw = json.dumps(story, ensure_ascii=False).encode('utf-8')
    report = {
        'schema': 'screenplay_editorial_review/v1', 'decision': 'passed',
        'candidate_sha256': hashlib.sha256(raw).hexdigest(),
        'workflow_request_sha256': WORKFLOW_SHA,
        'source_evidence_sha256': SOURCE_SHA,
        'unresolved_issues': [], 'checks': {key: True for key in CHECKS},
        'shot_reviews': [{'shot_id': shot['shot_id'], 'decision': 'passed',
                          'action_quote': shot['action'],
                          'finding': '仅验证合成记录的协议，不认证真实剧情。'}
                         for shot in shots],
        'result_review': {'shot_id': 'S06', 'decision': 'passed',
                          'action_quote': shots[-1]['action'],
                          'finding': '合成结果引用实际动作字段；不是生产语义结论。'},
    }
    return raw, enrich_story_review(report, story)


def verify(raw, report):
    return stage.verify_story_review(raw, report, workflow_sha=WORKFLOW_SHA,
                                     source_sha=SOURCE_SHA)


def test_exact_bound_complete_review_permits_production_check_without_mutation(bound_story_review):
    raw, report = bound_story_review
    original = copy.deepcopy(report)
    assert verify(raw, report) is None
    assert report == original


@pytest.mark.parametrize('field', [
    'candidate_sha256', 'workflow_request_sha256', 'source_evidence_sha256',
])
@pytest.mark.parametrize('defect', ['missing', 'different'])
def test_review_cannot_transfer_to_other_story_workflow_or_evidence(bound_story_review, field, defect):
    raw, report = bound_story_review
    if defect == 'missing':
        report.pop(field)
    else:
        report[field] = 'f' * 64
    with pytest.raises(ValueError):
        verify(raw, report)


def test_editing_story_bytes_invalidates_an_existing_review(bound_story_review):
    raw, report = bound_story_review
    old_action = json.loads(raw)['version']['shots'][0]['action'].encode('utf-8')
    changed = raw.replace(old_action, '修改后的合成动作1'.encode('utf-8'))
    assert changed != raw
    with pytest.raises(ValueError):
        verify(changed, report)


@pytest.mark.parametrize('check', CHECKS)
def test_any_failed_content_check_blocks_production(bound_story_review, check):
    raw, report = bound_story_review
    report['checks'][check] = False
    with pytest.raises(ValueError):
        verify(raw, report)


@pytest.mark.parametrize('value', [None, 'unknown', 1])
def test_unknown_or_truthy_nonboolean_check_is_not_approval(bound_story_review, value):
    raw, report = bound_story_review
    report['checks']['ending_complete'] = value
    with pytest.raises(ValueError):
        verify(raw, report)


@pytest.mark.parametrize('defect', ['missing_check', 'extra_check', 'no_checks'])
def test_all_and_only_current_content_checks_are_required(bound_story_review, defect):
    raw, report = bound_story_review
    if defect == 'missing_check':
        report['checks'].pop('prop_continuity')
    elif defect == 'extra_check':
        report['checks']['unknown_check'] = True
    else:
        report.pop('checks')
    with pytest.raises(ValueError):
        verify(raw, report)


@pytest.mark.parametrize('field,value', [
    ('schema', 'old_review/v0'), ('decision', 'failed'), ('decision', 'unknown'),
    ('unresolved_issues', ['合成未解决问题']), ('unresolved_issues', None),
])
def test_report_status_and_open_issues_cannot_be_ignored(bound_story_review, field, value):
    raw, report = bound_story_review
    report[field] = value
    with pytest.raises(ValueError):
        verify(raw, report)


@pytest.mark.parametrize('defect', ['missing', 'duplicate', 'out_of_order', 'empty'])
def test_shot_reviews_cover_six_actual_shots_exactly_in_order(bound_story_review, defect):
    raw, report = bound_story_review
    rows = report['shot_reviews']
    if defect == 'missing':
        rows.pop(2)
    elif defect == 'duplicate':
        rows[2] = copy.deepcopy(rows[1])
    elif defect == 'out_of_order':
        rows[1], rows[2] = rows[2], rows[1]
    else:
        rows.clear()
    with pytest.raises(ValueError):
        verify(raw, report)


@pytest.mark.parametrize('defect', [
    'failed', 'unknown', 'fake_quote', 'other_shot_quote', 'blank_quote', 'blank_finding',
])
def test_each_shot_needs_its_own_action_quote_and_actual_finding(bound_story_review, defect):
    raw, report = bound_story_review
    row = report['shot_reviews'][0]
    if defect in ('failed', 'unknown'):
        row['decision'] = defect
    elif defect == 'fake_quote':
        row['action_quote'] = '不存在于当前动作中的虚构引文。'
    elif defect == 'other_shot_quote':
        row['action_quote'] = report['shot_reviews'][1]['action_quote']
    elif defect == 'blank_quote':
        row['action_quote'] = '  '
    else:
        row['finding'] = '  '
    with pytest.raises(ValueError):
        verify(raw, report)


@pytest.mark.parametrize('defect', [
    'missing', 'invented_shot', 'fake_quote', 'metadata_only_quote',
    'failed', 'unknown', 'blank_quote', 'blank_finding',
])
def test_result_requires_an_actual_shot_action_not_a_promised_metadata_result(bound_story_review, defect):
    raw, report = bound_story_review
    row = report['result_review']
    if defect == 'missing':
        report.pop('result_review')
    elif defect == 'invented_shot':
        row['shot_id'] = 'S99'
    elif defect == 'fake_quote':
        row['action_quote'] = '并未执行的合成结局动作。'
    elif defect == 'metadata_only_quote':
        row['action_quote'] = json.loads(raw)['version']['resolution']
    elif defect in ('failed', 'unknown'):
        row['decision'] = defect
    elif defect == 'blank_quote':
        row['action_quote'] = '  '
    else:
        row['finding'] = '  '
    with pytest.raises(ValueError):
        verify(raw, report)
