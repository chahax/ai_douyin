"""State-only correction contracts; synthetic text, no model/media approval."""
import copy

import pytest

from src.trend_intelligence.script_drama import (
    validate_state_revision_fields, apply_state_revision,
)
from test_script_screenplay import screenplay, sources


@pytest.mark.parametrize('kind,duration', [('short', 45), ('long', 180)])
def test_state_revision_only_replaces_requested_existing_leaves(kind, duration):
    story = screenplay(kind)
    last = len(story['version']['shots']) - 1
    fields = ['/version/initial_state/people/林岚', '/version/initial_state/props/pen',
              f'/version/shots/{last}/end_state/people/陈宁',
              f'/version/shots/{last}/end_state/props/paper']
    replacements = dict(zip(fields, ['双手在桌面，坐在北侧。', ' 陈宁右侧桌面。 ',
                                    '仍坐在桌子南侧。', '桌面中间，未签署。']))
    expected = copy.deepcopy(story)
    expected['version']['initial_state']['people']['林岚'] = replacements[fields[0]]
    expected['version']['initial_state']['props']['pen'] = replacements[fields[1]]
    expected['version']['shots'][-1]['end_state']['people']['陈宁'] = replacements[fields[2]]
    expected['version']['shots'][-1]['end_state']['props']['paper'] = replacements[fields[3]]
    before = copy.deepcopy((story, replacements, fields))
    assert validate_state_revision_fields(story, fields) == tuple(fields)
    result = apply_state_revision(story, replacements, fields, kind, duration,
                                  sources(), reference_source_ids=('douyin:1',))
    assert result == expected
    assert (story, replacements, fields) == before
    assert not {'passed', 'approved', 'review', 'decision'} & set(result)
    result['version']['shots'][0]['action'] += '只改返回副本。'
    result['version']['initial_state']['props']['pen'] = '只改返回副本。'
    assert (story, replacements, fields) == before


def escaped_key_story():
    story = screenplay()
    story['version']['props'][0]['id'] = 'paper~/copy'
    states = [story['version']['initial_state']] + [s['end_state'] for s in story['version']['shots']]
    for state in states:
        state['props']['paper~/copy'] = state['props'].pop('paper')
    return story


def test_existing_key_rfc6901_escaping_is_decoded_without_renaming_the_key():
    story = escaped_key_story()
    pointer = '/version/shots/0/end_state/props/paper~0~1copy'
    assert validate_state_revision_fields(story, [pointer]) == (pointer,)
    result = apply_state_revision(story, {pointer: '仍是桌上原纸件。'}, [pointer], 'short', 45, sources())
    assert result['version']['shots'][0]['end_state']['props']['paper~/copy'] == '仍是桌上原纸件。'
    assert set(result['version']['shots'][0]['end_state']['props']) == {'paper~/copy', 'pen'}
    assert story['version']['shots'][0]['end_state']['props']['paper~/copy'] != '仍是桌上原纸件。'


@pytest.mark.parametrize('pointer', [
    '/version/shots/0/end_state/props/paper~/copy',
    '/version/shots/0/end_state/props/paper~0/copy',
    '/version/shots/0/end_state/props/paper~2~1copy',
    '/version/shots/0/end_state/props/paper~01copy',
    '/version/shots/0/end_state/props/paper~',
])
def test_escaped_state_keys_have_no_invalid_or_ambiguous_alias(pointer):
    story = escaped_key_story()
    with pytest.raises(ValueError):
        validate_state_revision_fields(story, [pointer])


@pytest.mark.parametrize('pointer', [
    '/initial_state/props/pen', '/end_states/0/props/pen',
    '/version/initial_state', '/version/initial_state/props',
    '/version/shots/0/end_state', '/version/shots/0/end_state/people',
    '/version/initial_state/people/陌生人', '/version/shots/0/end_state/props/new_prop',
    '/version/shots/0/end_state/props/pen/position',
    '/version/shots/01/end_state/props/pen', '/version/shots/-1/end_state/props/pen',
    '/version/shots/+0/end_state/props/pen', '/version/shots/6/end_state/props/pen',
    'version/initial_state/props/pen', ' /version/initial_state/props/pen',
    '/version/initial_state/props/pen/',
    '/version/shots/0/action', '/version/shots/0/dialogue',
    '/version/shots/0/dialogue_speaker', '/version/shots/0/beat',
    '/version/shots/0/duration_seconds', '/version/shots/0/shot_id',
    '/core_message', '/version/resolution', '/version/reference_usage/0/evidence_ids',
    '/version/props/0/name', '/characters/0/name', '/characters/0/performance_arc',
])
def test_state_revision_rejects_objects_aliases_unknown_keys_and_all_nonstate_fields(pointer):
    story = screenplay()
    before = copy.deepcopy(story)
    with pytest.raises(ValueError):
        validate_state_revision_fields(story, [pointer])
    with pytest.raises(ValueError):
        apply_state_revision(story, {pointer: '不允许的改动'}, [pointer], 'short', 45, sources())
    assert story == before


@pytest.mark.parametrize('fields', [None, [], (), '', '/version/initial_state/props/pen',
    [None], [123], ['/version/initial_state/props/pen', '/version/initial_state/props/pen']])
def test_state_revision_requires_nonempty_unique_pointer_list(fields):
    story = screenplay()
    with pytest.raises(ValueError):
        validate_state_revision_fields(story, fields)


@pytest.mark.parametrize('replacement', [None, [], 'text', {},
    {'/version/initial_state/props/pen': '原位置', '/version/resolution': '夹带结局'},
    {'/version/initial_state/props/pen': ''},
    {'/version/initial_state/props/pen': ' \t\n'},
    {'/version/initial_state/props/pen': None},
    {'/version/initial_state/props/pen': 1},
    {'/version/initial_state/props/pen': False},
    {'/version/initial_state/props/pen': {'position': '原位置'}},
])
def test_state_replacement_keys_are_exact_and_values_are_nonempty_strings(replacement):
    story = screenplay()
    before = copy.deepcopy((story, replacement))
    with pytest.raises(ValueError):
        apply_state_revision(story, replacement, ['/version/initial_state/props/pen'],
                             'short', 45, sources())
    assert (story, replacement) == before


@pytest.mark.parametrize('defect', ['duration', 'reference', 'selected_scope',
    'missing_other_prop', 'extra_person', 'companion_core', 'companion_identity'])
def test_state_correction_cannot_bypass_complete_story_or_companion_validation(defect):
    story, companion = screenplay('long'), screenplay('short')
    selected = ('douyin:1',)
    if defect == 'duration': story['version']['shots'][0]['duration_seconds'] = 19
    elif defect == 'reference': story['version']['reference_usage'][0]['evidence_ids'] = ['A9999']
    elif defect == 'selected_scope': selected = ('douyin:2',)
    elif defect == 'missing_other_prop': story['version']['shots'][1]['end_state']['props'].pop('paper')
    elif defect == 'extra_person': story['version']['shots'][1]['end_state']['people']['陌生人'] = '站着。'
    elif defect == 'companion_core': story['core_message'] = '修改了共同核心。'
    else: story['characters'][0]['identity'] = '修改了角色身份。'
    pointer = '/version/initial_state/props/pen'
    before = copy.deepcopy((story, companion))
    with pytest.raises(ValueError):
        apply_state_revision(story, {pointer: '陈宁右侧桌面。'}, [pointer],
                             'long', 180, sources(), selected, companion)
    assert (story, companion) == before


def test_state_text_still_requires_actual_semantic_review_after_shape_passes():
    story = screenplay()
    pointer = '/version/shots/0/end_state/props/paper'
    result = apply_state_revision(story, {pointer: '声称已签署，但冻结动作没有写签字。'},
                                 [pointer], 'short', 45, sources())
    assert result['version']['shots'][0]['action'] == story['version']['shots'][0]['action']
    assert not {'passed', 'approved', 'review', 'decision'} & set(result)
