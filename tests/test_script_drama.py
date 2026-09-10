"""Pure drama/state projection contracts; no model or media approval is inferred."""
import copy

import pytest

from src.trend_intelligence.script_drama import (
    validate_drama, merge_drama_states, validate_revision_fields, apply_drama_revision,
)
from test_script_screenplay import screenplay, sources


def split_story(kind='short'):
    original = screenplay(kind)
    drama = copy.deepcopy(original)
    drama['schema'] = 'script_drama/v1'
    initial = drama['version'].pop('initial_state')
    endings = [{'shot_id': shot['shot_id'], **shot.pop('end_state')} for shot in drama['version']['shots']]
    return original, drama, {'initial_state': initial, 'end_states': endings}


@pytest.mark.parametrize('kind,duration', [('short', 45), ('long', 180)])
def test_drama_validation_keeps_the_exact_model_story_without_states_or_approval(kind, duration):
    _, drama, _ = split_story(kind)
    before = copy.deepcopy(drama)
    result = validate_drama(drama, kind, duration, sources(), reference_source_ids=('douyin:1',))
    assert result == before and drama == before
    assert 'initial_state' not in result['version']
    assert all('end_state' not in s for s in result['version']['shots'])
    assert not {'passed', 'approved', 'review', 'decision'} & set(result)


@pytest.mark.parametrize('kind,duration', [('short', 45), ('long', 180)])
def test_state_merge_preserves_all_other_story_fields_and_inputs_exactly(kind, duration):
    original, drama, states = split_story(kind)
    before_drama, before_states = copy.deepcopy(drama), copy.deepcopy(states)
    result = merge_drama_states(drama, states, kind, duration, sources(), reference_source_ids=('douyin:1',))
    assert result == original
    assert drama == before_drama and states == before_states
    assert result['schema'] == 'script_screenplay/v1'
    assert not {'passed', 'approved', 'review', 'decision'} & set(result)
    # Output ownership must not alias either authoring input.
    result['version']['shots'][0]['action'] += '修改合并副本。'
    result['version']['initial_state']['props']['pen'] = '只修改返回对象。'
    result['version']['shots'][0]['end_state']['props']['pen'] = '仍只修改返回对象。'
    assert drama == before_drama and states == before_states


@pytest.mark.parametrize('defect', ['schema', 'unknown_top', 'initial_state', 'shot_end_state',
    'missing_action', 'unknown_shot', 'wrong_duration', 'unknown_speaker', 'unknown_source', 'unknown_evidence'])
def test_invalid_drama_or_smuggled_state_is_rejected(defect):
    _, drama, states = split_story()
    first = drama['version']['shots'][0]
    if defect == 'schema': drama['schema'] = 'script_screenplay/v1'
    elif defect == 'unknown_top': drama['approved'] = True
    elif defect == 'initial_state': drama['version']['initial_state'] = states['initial_state']
    elif defect == 'shot_end_state': first['end_state'] = states['end_states'][0]
    elif defect == 'missing_action': first.pop('action')
    elif defect == 'unknown_shot': first['shot_id'] = 'S99'
    elif defect == 'wrong_duration': first['duration_seconds'] += 1
    elif defect == 'unknown_speaker': first['dialogue_speaker'] = '未经定义的第三人'
    elif defect == 'unknown_source': drama['version']['reference_usage'][0]['source_id'] = 'douyin:999'
    else: drama['version']['reference_usage'][0]['evidence_ids'] = ['A9999']
    before = copy.deepcopy(drama)
    with pytest.raises(ValueError):
        validate_drama(drama, 'short', 45, sources())
    assert drama == before


@pytest.mark.parametrize('selected', [('douyin:2',), ('unknown',), ('douyin:1', 'douyin:1')])
def test_reference_scope_cannot_be_changed_by_drama_or_state_projection(selected):
    _, drama, states = split_story()
    with pytest.raises(ValueError):
        validate_drama(drama, 'short', 45, sources(), reference_source_ids=selected)
    with pytest.raises(ValueError):
        merge_drama_states(drama, states, 'short', 45, sources(), reference_source_ids=selected)


@pytest.mark.parametrize('field', ['core_message', 'name', 'identity'])
def test_companion_core_and_character_identity_are_not_rewritten(field):
    _, drama, states = split_story('long')
    companion = screenplay('short')
    if field == 'core_message': drama[field] = '完全不同的共同核心。'
    else: drama['characters'][0][field] = '被改写的' + field
    with pytest.raises(ValueError):
        validate_drama(drama, 'long', 180, sources(), companion=companion)
    with pytest.raises(ValueError):
        merge_drama_states(drama, states, 'long', 180, sources(), companion=companion)


def test_matching_companion_allows_an_independent_long_process():
    original, drama, states = split_story('long')
    companion = screenplay('short')
    before = copy.deepcopy(companion)
    assert validate_drama(drama, 'long', 180, sources(), companion=companion) == drama
    assert merge_drama_states(drama, states, 'long', 180, sources(), companion=companion) == original
    assert companion == before


@pytest.mark.parametrize('category,key,value', [
    ('people', '未定义人物', '坐在旁边'), ('props', 'new_paper', '刚出现的新纸'),
    ('people', '林岚', None), ('props', 'pen', None), ('props', 'pen', ''),
])
@pytest.mark.parametrize('location', ['initial_state', 'end_states'])
def test_every_state_covers_only_the_registered_people_and_props(location, category, key, value):
    _, drama, states = split_story()
    target = states['initial_state'] if location == 'initial_state' else states['end_states'][2]
    if value is None: target[category].pop(key)
    else: target[category][key] = value
    before = copy.deepcopy(states)
    with pytest.raises(ValueError):
        merge_drama_states(drama, states, 'short', 45, sources())
    assert states == before


@pytest.mark.parametrize('defect', ['missing', 'duplicate', 'reordered', 'unknown_id', 'override_action',
    'override_dialogue', 'override_core', 'override_version', 'extra_schema'])
def test_state_phase_cannot_omit_reorder_or_override_frozen_story(defect):
    _, drama, states = split_story()
    rows = states['end_states']
    if defect == 'missing': rows.pop()
    elif defect == 'duplicate': rows[2] = copy.deepcopy(rows[1])
    elif defect == 'reordered': rows[0], rows[1] = rows[1], rows[0]
    elif defect == 'unknown_id': rows[0]['shot_id'] = 'S99'
    elif defect == 'override_action': rows[0]['action'] = '擅自改成签字。'
    elif defect == 'override_dialogue': rows[0]['dialogue'] = '新台词。'
    elif defect == 'override_core': states['core_message'] = '已完成交易。'
    elif defect == 'override_version': states['version'] = {'resolution': '已经回款。'}
    else: states['schema'] = 'state_approval/v1'
    with pytest.raises(ValueError):
        merge_drama_states(drama, states, 'short', 45, sources())


def test_well_formed_state_prose_is_not_automatic_semantic_approval():
    _, drama, states = split_story()
    # The shape gate cannot prove that this prose follows the frozen action.
    states['end_states'][0]['props']['paper'] = '声称已签署，但实际动作并未写签字。'
    result = merge_drama_states(drama, states, 'short', 45, sources())
    assert result['version']['shots'][0]['action'] == drama['version']['shots'][0]['action']
    assert not {'passed', 'approved', 'review', 'decision'} & set(result)


REVISION_METADATA_FIELDS = (
    'title', 'premise', 'dramatic_question', 'goal', 'obstacle', 'stakes',
    'resolution', 'legal_review_note', 'scene', 'spatial_layout',
)


@pytest.mark.parametrize('kind,duration', [('short', 45), ('long', 180)])
def test_bounded_revision_changes_exactly_the_requested_text_and_never_approves(kind, duration):
    _, drama, _ = split_story(kind)
    fields = ['/version/shots/0/dialogue', '/version/shots/1/action',
              '/characters/0/performance_arc', '/characters/1/performance_arc']
    replacements = {
        fields[0]: '这份先别签。', fields[1]: ' 陈宁收回按住纸面的手。 ',
        fields[2]: '从着急落笔到坚持核对。', fields[3]: '从催签到接受核对。',
    }
    expected = copy.deepcopy(drama)
    expected['version']['shots'][0]['dialogue'] = replacements[fields[0]]
    expected['version']['shots'][1]['action'] = replacements[fields[1]]
    expected['characters'][0]['performance_arc'] = replacements[fields[2]]
    expected['characters'][1]['performance_arc'] = replacements[fields[3]]
    for key in REVISION_METADATA_FIELDS:
        pointer = '/version/' + key
        fields.append(pointer)
        replacements[pointer] = expected['version'][key] = '当前修改说明：' + key
    if kind == 'long':
        fields.append('/version/shots/3/beat')
        replacements[fields[-1]] = 'turn'
        expected['version']['shots'][3]['beat'] = 'turn'
    before = copy.deepcopy((drama, replacements, fields))
    assert validate_revision_fields(drama, fields) == tuple(fields)
    result = apply_drama_revision(drama, replacements, fields, kind, duration,
                                  sources(), reference_source_ids=('douyin:1',))
    assert result == expected
    assert (drama, replacements, fields) == before
    assert not {'passed', 'approved', 'review', 'decision'} & set(result)
    result['version']['props'][0]['name'] = '只改返回对象。'
    result['characters'][0]['identity'] = '仍只改返回对象。'
    assert (drama, replacements, fields) == before


@pytest.mark.parametrize('fields', [None, [], (), '', '/version/title',
    ['/version/title', '/version/title'], [None], [123]])
def test_revision_field_list_is_nonempty_unique_and_not_coerced(fields):
    _, drama, _ = split_story()
    with pytest.raises(ValueError):
        validate_revision_fields(drama, fields)
    with pytest.raises(ValueError):
        apply_drama_revision(drama, {'/version/title': '修订标题'}, fields,
                             'short', 45, sources())


@pytest.mark.parametrize('pointer', [
    'version/title', ' /version/title', '/version/title ', '/version/title/',
    '/version//title', '/version/shots/01/action', '/version/shots/00/action',
    '/version/shots/-1/action', '/version/shots/+0/action', '/version/shots/ 0/action',
    '/version/shots/0.0/action', '/version/shots/6/action', '/version/shots/99/action',
    '/version/shots/0/action~1text', '/version/shots/0/~0action',
    '/characters/02/performance_arc', '/characters/2/performance_arc',
    '/characters/-1/performance_arc', '/version/not_a_field',
    '/schema', '/core_message', '/characters/0/name', '/characters/0/identity',
    '/characters/0/voice', '/characters/0/appearance', '/characters/0/wardrobe',
    '/version/props', '/version/props/0/name', '/version/shots/0/shot_id',
    '/version/shots/0/duration_seconds', '/version/shots/0/dialogue_speaker',
    '/version/shots/0/end_state', '/version/reference_usage',
    '/version/reference_usage/0/evidence_ids', '/version/initial_state',
])
def test_revision_rejects_noncanonical_unknown_or_frozen_pointers(pointer):
    _, drama, _ = split_story()
    before = copy.deepcopy(drama)
    with pytest.raises(ValueError):
        validate_revision_fields(drama, [pointer])
    with pytest.raises(ValueError):
        apply_drama_revision(drama, {pointer: '不允许的改动'}, [pointer], 'short', 45, sources())
    assert drama == before


@pytest.mark.parametrize('replacements', [
    None, [], 'text', {}, {'/version/title': '标题'},
    {'/version/title': '标题', '/version/goal': '目标', '/core_message': '夹带核心'},
    {'/version/title': 12, '/version/goal': '目标'},
    {'/version/title': False, '/version/goal': '目标'},
    {'/version/title': None, '/version/goal': '目标'},
    {'/version/title': {}, '/version/goal': '目标'},
    {'/version/title': '', '/version/goal': '目标'},
    {'/version/title': ' \t\n', '/version/goal': '目标'},
])
def test_revision_requires_the_exact_requested_keyset_and_nonempty_text(replacements):
    _, drama, _ = split_story()
    fields = ('/version/title', '/version/goal')
    before = copy.deepcopy((drama, replacements))
    with pytest.raises(ValueError):
        apply_drama_revision(drama, replacements, fields, 'short', 45, sources())
    assert (drama, replacements) == before


@pytest.mark.parametrize('pointer,value', [
    ('/version/shots/0/beat', 'turn'),
    ('/version/shots/0/beat', 'unknown'),
    ('/version/shots/0/dialogue', '长' * 36),
    ('/version/shots/5/dialogue', '那以后再说？'),
    ('/version/shots/0/action', '旁白解释全部经过。'),
])
def test_allowed_field_revision_still_must_pass_the_complete_drama_gate(pointer, value):
    _, drama, _ = split_story()
    before = copy.deepcopy(drama)
    with pytest.raises(ValueError):
        apply_drama_revision(drama, {pointer: value}, [pointer], 'short', 45, sources())
    assert drama == before


@pytest.mark.parametrize('defect', ['duration', 'reference', 'selected_scope', 'companion_core', 'companion_identity'])
def test_revision_cannot_hide_invalid_frozen_duration_references_or_companion(defect):
    _, drama, _ = split_story('long')
    companion = screenplay('short')
    selected = ('douyin:1',)
    if defect == 'duration': drama['version']['shots'][0]['duration_seconds'] = 19
    elif defect == 'reference': drama['version']['reference_usage'][0]['evidence_ids'] = ['A9999']
    elif defect == 'selected_scope': selected = ('douyin:2',)
    elif defect == 'companion_core': drama['core_message'] = '换成了另一核心。'
    else: drama['characters'][0]['identity'] = '换了人物身份。'
    before = copy.deepcopy((drama, companion))
    with pytest.raises(ValueError):
        apply_drama_revision(drama, {'/version/title': '只修改标题'}, ['/version/title'],
                             'long', 180, sources(), selected, companion)
    assert (drama, companion) == before


def test_revision_with_matching_companion_keeps_all_frozen_shared_fields():
    _, drama, _ = split_story('long')
    companion = screenplay('short')
    before = copy.deepcopy(companion)
    result = apply_drama_revision(drama, {'/version/shots/3/beat': 'turn'},
        ['/version/shots/3/beat'], 'long', 180, sources(), ('douyin:1',), companion)
    assert result['version']['shots'][3]['beat'] == 'turn'
    assert result['core_message'] == companion['core_message']
    assert [(c['name'], c['identity']) for c in result['characters']] == [
        (c['name'], c['identity']) for c in companion['characters']]
    assert companion == before
