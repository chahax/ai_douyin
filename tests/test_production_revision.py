"""Bounded photography edits with synthetic fixtures; no model or approval."""
import copy

import pytest

from src.trend_intelligence.production_revision import (
    apply_production_revision, parse_unique_json, validate_production_revision_fields,
)
from test_script_screenplay import screenplay, production_v2


@pytest.mark.parametrize('kind', ['short', 'long'])
def test_valid_revision_only_changes_requested_production_text(kind):
    story = screenplay(kind)
    parent = production_v2(story, kind)
    replacements = {
        '/scene_design/composition': '两人在上方主体区，桌面手部清楚可见。',
        '/scene_design/lighting': '左前方柔和窗光，右侧弱补光。',
        '/scene_design/shot_size': '中景',
        '/scene_design/camera_angle': '桌侧平视双人机位。',
        '/scene_design/camera_movement': '固定',
        '/shots/0/composition': ' 林岚在画面左侧，陈宁在右侧。 ',
        '/shots/1/emotion_and_performance': '陈宁保持原有视线，神情专注。',
        '/interpretation/presentation_mode': 'conflict_drama',
        '/interpretation/account_fit': '面向需要核对争议材料的观众。',
        '/interpretation/source_pattern_rationale': '仅借鉴已引用原片的表达方式。',
        '/interpretation/protagonist': '陈宁',
    }
    fields = list(replacements)
    before = copy.deepcopy((story, parent, replacements, fields))
    expected = copy.deepcopy(parent)
    expected['scene_design'].update({p.rsplit('/', 1)[1]: v for p, v in replacements.items()
                                     if p.startswith('/scene_design/')})
    expected['shots'][0]['composition'] = replacements['/shots/0/composition']
    expected['shots'][1]['emotion_and_performance'] = replacements['/shots/1/emotion_and_performance']
    expected['interpretation'].update({p.rsplit('/', 1)[1]: v for p, v in replacements.items()
                                      if p.startswith('/interpretation/')})
    assert validate_production_revision_fields(parent, fields) == tuple(fields)
    result = apply_production_revision(story, parent, replacements, fields, kind)
    assert result == expected
    assert (story, parent, replacements, fields) == before
    assert not {'passed', 'approved', 'review', 'decision'} & set(result)
    result['shots'][0]['shot_id'] = 'only-changing-returned-object'
    result['scene_design']['lighting'] = 'only-changing-returned-object'
    assert (story, parent, replacements, fields) == before


def test_long_can_revise_existing_per_shot_camera_without_adding_new_fields():
    story = screenplay('long')
    parent = production_v2(story, 'long')
    parent['shots'][0].update(shot_size='中景', camera_angle='平视。', camera_movement='固定')
    replacements = {'/shots/0/shot_size': '近景', '/shots/0/camera_angle': '人物同侧平视机位。',
                    '/shots/0/camera_movement': '固定'}
    expected = copy.deepcopy(parent)
    expected['shots'][0].update(shot_size='近景', camera_angle='人物同侧平视机位。', camera_movement='固定')
    result = apply_production_revision(story, parent, replacements, tuple(replacements), 'long')
    assert result == expected
    assert parent['shots'][0]['shot_size'] == '中景'


@pytest.mark.parametrize('kind', ['short', 'long'])
@pytest.mark.parametrize('field', ['shot_size', 'camera_angle', 'camera_movement'])
def test_revision_cannot_add_a_missing_camera_leaf_even_for_long(kind, field):
    story = screenplay(kind)
    parent = production_v2(story, kind)
    pointer = '/shots/0/' + field
    with pytest.raises(ValueError):
        validate_production_revision_fields(parent, [pointer])
    with pytest.raises(ValueError):
        apply_production_revision(story, parent, {pointer: '固定'}, [pointer], kind)


@pytest.mark.parametrize('pointer', [
    '/schema', '/scene_design', '/scene_design/blocking', '/scene_design/action',
    '/shots/0', '/shots/0/shot_id', '/shots/0/participants', '/shots/0/blocking',
    '/shots/0/action', '/shots/0/dialogue', '/shots/0/end_state',
    '/story/core_message', '/version/shots/0/action', '/interpretation',
    '/interpretation/resolution', '/shots/6/composition', '/shots/-1/composition',
    '/shots/01/composition', '/shots/+0/composition', '/shots/0/composition/',
    '/shots/0/~0composition', 'shots/0/composition', ' /shots/0/composition',
])
def test_unknown_noncanonical_or_frozen_pointer_is_rejected(pointer):
    story = screenplay()
    parent = production_v2(story)
    before = copy.deepcopy((story, parent))
    with pytest.raises(ValueError):
        validate_production_revision_fields(parent, [pointer])
    with pytest.raises(ValueError):
        apply_production_revision(story, parent, {pointer: '越权改写'}, [pointer], 'short')
    assert (story, parent) == before


@pytest.mark.parametrize('fields', [None, [], (), '', '/scene_design/composition',
    [None], [123], ['/scene_design/composition', '/scene_design/composition']])
def test_field_list_must_be_nonempty_unique_strings(fields):
    story = screenplay()
    parent = production_v2(story)
    with pytest.raises(ValueError):
        validate_production_revision_fields(parent, fields)


@pytest.mark.parametrize('replacement', [None, [], 'text', {},
    {'/shots/0/composition': '构图', '/scene_design/lighting': '夹带修改'},
    {'/shots/0/composition': ''}, {'/shots/0/composition': ' \n\t'},
    {'/shots/0/composition': None}, {'/shots/0/composition': 1},
    {'/shots/0/composition': False}, {'/shots/0/composition': {'text': '构图'}},
])
def test_replacement_mapping_is_exact_and_nonempty_text(replacement):
    story = screenplay()
    parent = production_v2(story)
    before = copy.deepcopy((story, parent, replacement))
    with pytest.raises(ValueError):
        apply_production_revision(story, parent, replacement, ['/shots/0/composition'], 'short')
    assert (story, parent, replacement) == before


@pytest.mark.parametrize('pointer,value', [
    ('/scene_design/shot_size', '中景然后特写'),
    ('/scene_design/camera_movement', '非法运镜'),
    ('/scene_design/camera_angle', '先平视，再切到对方。'),
    ('/interpretation/protagonist', '未定义的第三人'),
    ('/interpretation/protagonist', '陈宁律师'),
])
def test_allowed_text_patch_still_must_compile(pointer, value):
    story = screenplay()
    parent = production_v2(story)
    before = copy.deepcopy((story, parent))
    with pytest.raises(ValueError):
        apply_production_revision(story, parent, {pointer: value}, [pointer], 'short')
    assert (story, parent) == before


@pytest.mark.parametrize('defect', ['legacy_schema', 'bad_original_camera', 'duplicate_character_name'])
def test_revision_does_not_accept_invalid_original_story_or_production(defect):
    story = screenplay()
    parent = production_v2(story)
    if defect == 'legacy_schema': parent['schema'] = 'screenplay_production/v1'
    elif defect == 'bad_original_camera': parent['scene_design']['shot_size'] = '非法景别'
    else: story['characters'][1]['name'] = story['characters'][0]['name']
    with pytest.raises(ValueError):
        apply_production_revision(story, parent, {'/shots/0/composition': '只修构图'},
                                  ['/shots/0/composition'], 'short')


@pytest.mark.parametrize('raw', [
    '{"/shots/0/composition":"第一值","/shots/0/composition":"重复值"}',
    '{"outer":{"nested":"第一值","nested":"重复值"}}',
])
def test_duplicate_json_keys_are_rejected_before_a_value_can_be_overwritten(raw):
    with pytest.raises(ValueError, match='duplicate JSON key'):
        parse_unique_json(raw)


def test_shape_valid_performance_prose_is_not_automatic_story_approval():
    story = screenplay()
    parent = production_v2(story)
    pointer = '/shots/0/emotion_and_performance'
    result = apply_production_revision(story, parent, {pointer: '擅自声称签字并收款。'}, [pointer], 'short')
    assert story['version']['shots'][0]['action'] == '林岚在第1次核对时按住纸面。'
    assert result['shots'][0]['emotion_and_performance'] == '擅自声称签字并收款。'
    assert not {'passed', 'approved', 'review', 'decision'} & set(result)
