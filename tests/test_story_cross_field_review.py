"""Cross-field review coverage and failure routing; no semantic model is mocked as real."""
import copy
import hashlib
import json

import pytest

from src.trend_intelligence.script_screenplay import verify_story_review
from test_run_screenplay_stage import bound_story_review, WORKFLOW_SHA, SOURCE_SHA


def verify(raw, report):
    return verify_story_review(raw, report, workflow_sha=WORKFLOW_SHA, source_sha=SOURCE_SHA)


@pytest.mark.parametrize('defect', ['legacy', 'missing_dialogue', 'partial_dialogue', 'other_dialogue',
    'no_alignment', 'no_focus', 'no_spatial', 'no_scope', 'changed_scope', 'scope_skips_line',
    'no_layout', 'partial_layout', 'missing_character', 'other_voice', 'partial_voice',
    'missing_character_line', 'other_character_line', 'changed_arc', 'unknown_decision'])
def test_incomplete_cross_field_coverage_cannot_reach_photography(bound_story_review, defect):
    raw, report = bound_story_review
    shot = report['shot_reviews'][0]
    if defect == 'legacy': report['schema'] = 'screenplay_editorial_review/v1'
    elif defect == 'missing_dialogue': shot.pop('dialogue_quote')
    elif defect == 'partial_dialogue': shot['dialogue_quote'] = shot['dialogue_quote'][:2]
    elif defect == 'other_dialogue': shot['dialogue_quote'] = report['shot_reviews'][1]['dialogue_quote']
    elif defect == 'no_alignment': shot['dialogue_action_finding'] = ''
    elif defect == 'no_focus': shot['conflict_focus_finding'] = ''
    elif defect == 'no_spatial': shot['spatial_finding'] = ''
    elif defect == 'no_scope': report.pop('focus_review')
    elif defect == 'changed_scope': report['focus_review']['goal_quote'] = '把金额争议改成由谁付款'
    elif defect == 'scope_skips_line': report['focus_review']['spoken_shot_ids'].pop()
    elif defect == 'no_layout': report.pop('spatial_review')
    elif defect == 'partial_layout': report['spatial_review']['layout_quote'] = '隔桌相对。'
    elif defect == 'missing_character': report['character_reviews'].pop()
    elif defect == 'other_voice': report['character_reviews'][0]['voice_quote'] = report['character_reviews'][1]['voice_quote']
    elif defect == 'partial_voice': report['character_reviews'][0]['voice_quote'] = '成年女性中音'
    elif defect == 'missing_character_line': report['character_reviews'][0]['dialogue_quotes'].pop()
    elif defect == 'other_character_line': report['character_reviews'][0]['dialogue_quotes'][0] = report['character_reviews'][1]['dialogue_quotes'][0]
    elif defect == 'changed_arc': report['character_reviews'][0]['performance_arc_quote'] += '并签署完毕'
    else: report['character_reviews'][0]['decision'] = 'unknown'
    with pytest.raises(ValueError): verify(raw, report)


@pytest.mark.parametrize('check', ['dialogue_action_alignment', 'conflict_focus',
                                  'character_delivery_grounded', 'spatial_alignment'])
def test_any_cross_field_failure_blocks_even_when_legacy_checks_pass(bound_story_review, check):
    raw, report = bound_story_review
    report['checks'][check] = False
    with pytest.raises(ValueError): verify(raw, report)


def test_silence_is_covered_without_inventing_dialogue(bound_story_review):
    from story_review_fixture import enrich_story_review
    raw, report = bound_story_review
    story = json.loads(raw)
    story['version']['shots'][0]['dialogue'] = ''
    story['version']['shots'][0]['dialogue_speaker'] = ''
    new_raw = json.dumps(story, ensure_ascii=False).encode('utf-8')
    report = enrich_story_review(report, story)
    report['candidate_sha256'] = hashlib.sha256(new_raw).hexdigest()
    verify(new_raw, report)
    report['shot_reviews'][0]['dialogue_quote'] = '他低声说好了'
    with pytest.raises(ValueError): verify(new_raw, report)


def test_schema_upgrade_never_mutates_or_auto_approves_old_report(bound_story_review):
    raw, report = bound_story_review
    report['schema'] = 'screenplay_editorial_review/v1'
    original = copy.deepcopy(report)
    with pytest.raises(ValueError): verify(raw, report)
    assert report == original
