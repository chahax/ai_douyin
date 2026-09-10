"""Pure text/schema tests: no model, media, or network calls."""
import copy
import json
from types import SimpleNamespace

import pytest


def test_fixed_camera_no_zoom_instruction_is_not_a_zoom_operation():
    from src.trend_intelligence.script_screenplay import _camera
    row = {'shot_size': '中景', 'camera_movement': '固定',
           'camera_angle': '视线轴同侧固定机位，不越轴、不变焦，容纳两人脸部与桌面。'}
    original = dict(row)
    _camera(row, 'regression')
    assert row == original


@pytest.mark.parametrize('movement', ['随后变焦', '结尾拉近', '切到对面', '正反打'])
def test_no_zoom_phrase_does_not_hide_another_camera_operation(movement):
    from src.trend_intelligence.script_screenplay import _camera
    with pytest.raises(ValueError, match='one camera position'):
        _camera({'shot_size': '中景', 'camera_movement': '固定',
                 'camera_angle': '固定机位，不变焦，' + movement}, 'regression')

from src.trend_intelligence.script_screenplay import (
    BEAT_ROLES, SCHEMA, PRODUCTION_SCHEMA_V2, compile_screenplay, render_state, validate_screenplay,
)


def sources():
    return [{'source_id': 'douyin:1', 'media_evidence': {'duration_seconds': 30},
             'expression_analysis': {'evidence': [
                 {'id': 'A0001', 'channel': 'asr', 'start_seconds': 0,
                  'end_seconds': 2, 'text': '先看清楚眼前这张纸。'},
                 {'id': 'V0001', 'channel': 'visual', 'start_seconds': 2,
                  'end_seconds': 2, 'text': '人物把纸放到桌上。'}]}},
            {'source_id': 'douyin:2', 'media_evidence': {'duration_seconds': 30},
             'expression_analysis': {'evidence': [
                 {'id': 'A0002', 'channel': 'asr', 'start_seconds': 0,
                  'end_seconds': 2, 'text': '同一批次另一条原句。'}]}}]


def screenplay(kind='short'):
    lengths = [7, 7, 8, 8, 8, 7] if kind == 'short' else [20] * 9
    beats = list(BEAT_ROLES) if kind == 'short' else [
        'setup', 'conflict', 'escalation', 'escalation', 'turn',
        'resolution', 'resolution', 'closure', 'closure']
    initial = {'people': {'林岚': '坐在桌子北侧，双手在桌面。',
                          '陈宁': '坐在桌子南侧，双手在桌面。'},
               'props': {'paper': '桌面中间，展开，未签字。', 'pen': '陈宁右侧桌面。'}}
    rows = []
    for i, (length, beat) in enumerate(zip(lengths, beats), 1):
        state = copy.deepcopy(initial)
        state['props']['paper'] = f'第{i}镜桌面中间，展开，未签字。'
        rows.append({'shot_id': f'S{i:02d}', 'duration_seconds': length, 'beat': beat,
                     'dialogue_speaker': '林岚' if i % 2 else '陈宁',
                     'dialogue': ('长版' if kind == 'long' else '') + f'第{i}次当场确认。',
                     'action': f'林岚在第{i}次核对时按住纸面。',
                     'end_state': state})
    return {'schema': SCHEMA, 'core_message': '眼前材料有争议时先完成当场决定。',
            'characters': [
                {'name': '林岚', 'identity': '委托人', 'appearance': '短发，圆脸。',
                 'wardrobe': '白衬衣。', 'voice': '成年女性中音，清楚急促。',
                 'performance_arc': '从急于处理到冷静核对。'},
                {'name': '陈宁', 'identity': '经办人', 'appearance': '黑色短发。',
                 'wardrobe': '蓝衬衣。', 'voice': '成年男性低音，利落清楚。',
                 'performance_arc': '从催促到接受当前决定。'}],
            'version': {'title': '当前这份纸', 'premise': '同一份争议文本的' + kind + '处理经过。',
                        'dramatic_question': '当前这份是否签？', 'goal': '决定当前是否签字。',
                        'obstacle': '双方没有确认眼前内容。', 'stakes': '可能留下未确认的签名。',
                        'resolution': '双方当场停止当前文本签署。',
                        'legal_review_note': '虚构场景，只呈现当事人选择，不作普遍法律结论。',
                        'scene': '办公室桌前。', 'spatial_layout': '林岚坐北，陈宁坐南，隔桌相对。',
                        'props': [{'id': 'paper', 'name': '争议文本'}, {'id': 'pen', 'name': '签字笔'}],
                        'initial_state': initial, 'shots': rows,
                        'reference_usage': [{'source_id': 'douyin:1', 'evidence_ids': ['A0001', 'V0001'],
                                             'borrowed_expression': '通过纸面物件辅助理解。',
                                             'adaptation': '本片两人争议及当场处理均为原创。',
                                             'shot_ids': ['S02']}]}}


def production(story, kind='short'):
    version = story['version']
    shots = version['shots']
    beats = [{'role': role, 'because': '前一阶段造成当前处境。',
              'change': '本阶段推进' + role,
              'shot_ids': [s['shot_id'] for s in shots if s['beat'] == role]} for role in BEAT_ROLES]
    turn = next(s['shot_id'] for s in shots if s['beat'] == 'turn')
    return {'scene_design': {'composition': '人物与桌面属于同一办公室。',
                             'lighting': '左前方窗户柔光，色温偏中性，右侧弱补光。',
                             'shot_size': '中景', 'camera_angle': '桌侧平视双人机位。',
                             'camera_movement': '固定', 'blocking': version['spatial_layout']},
            'shots': [{'shot_id': s['shot_id'], 'composition': '双人分居画面左右，纸面位于中间。',
                       'shot_size': '中景', 'camera_angle': '桌侧平视双人机位。', 'camera_movement': '固定',
                       'emotion_and_performance': '人物专注对方，动作利落。',
                       'transition': '连续承接下一镜。'} for s in shots],
            'expression_plan': {'presentation_mode': 'conflict_drama', 'account_fit': '服务合同咨询观众。',
                                'source_pattern_rationale': '借鉴原片纸面辅助说明方式，情境原创。',
                                'protagonist': '林岚',
                                **{k: version[k] for k in ('goal', 'obstacle', 'stakes')},
                                'action_chain': [
                                    {'shot_ids': ['S01', 'S02'], 'visible_action': '当场核对纸面。',
                                     'state_change': '发现双方确认状态不同。'},
                                    {'shot_ids': [shots[-1]['shot_id']], 'visible_action': '停止当前签署。',
                                     'state_change': '当前未签状态得到当场确认。'}],
                                'turn': {'shot_ids': [turn], 'visible_trigger': '当场核对的结果。',
                                         'result': '改变当前选择。'},
                                'ending': {'shot_ids': [shots[-1]['shot_id']],
                                           'visible_result': version['resolution'],
                                           'core_answer': story['core_message']}},
            'story_beats': beats}


def production_v2(story, kind='short'):
    legacy = production(story, kind)
    return {'schema': PRODUCTION_SCHEMA_V2,
            'scene_design': {key: value for key, value in legacy['scene_design'].items() if key != 'blocking'},
            'shots': [{key: row[key] for key in ('shot_id', 'composition', 'emotion_and_performance')}
                      for row in legacy['shots']],
            'interpretation': {key: legacy['expression_plan'][key] for key in
                               ('presentation_mode', 'account_fit', 'source_pattern_rationale', 'protagonist')}}


@pytest.mark.parametrize('kind,duration', [('short', 45), ('long', 180)])
def test_valid_story_is_returned_without_mutation(kind, duration):
    data = screenplay(kind)
    before = copy.deepcopy(data)
    assert validate_screenplay(data, kind, duration, sources(), ('douyin:1',)) is data
    assert data == before


@pytest.mark.parametrize('path,value', [
    (('schema',), 'script_screenplay/v2'),
    (('approved',), True),
    (('characters', 0, 'name'), '陈宁'),
    (('characters', 0, 'voice'), ''),
    (('characters', 0, 'identity'), '旁白'),
    (('version', 'goal'), ''),
    (('version', 'props', 1, 'id'), 'paper'),
    (('version', 'props', 0, 'appearance'), '额外字段'),
    (('version', 'initial_state', 'people', '陌生人'), '站在一旁。'),
    (('version', 'initial_state', 'props', 'phone'), '凭空出现。'),
    (('version', 'initial_state', 'props', 'paper'), ''),
    (('version', 'shots', 1, 'end_state', 'people', '陌生人'), '坐下。'),
    (('version', 'shots', 1, 'end_state', 'props', 'phone'), '未知道具。'),
    (('version', 'shots', 1, 'shot_id'), 'S03'),
    (('version', 'shots', 1, 'duration_seconds'), True),
    (('version', 'shots', 1, 'duration_seconds'), 7.0),
    (('version', 'shots', 1, 'duration_seconds'), 3),
    (('version', 'shots', 1, 'duration_seconds'), 16),
    (('version', 'shots', 1, 'beat'), 'setup'),
    (('version', 'shots', 1, 'beat'), 'closure'),
    (('version', 'shots', 1, 'dialogue_speaker'), '旁白'),
    (('version', 'shots', 1, 'dialogue_speaker'), '林岚、陈宁'),
    (('version', 'shots', 1, 'dialogue_speaker'), ''),
    (('version', 'shots', 1, 'dialogue'), ''),
    (('version', 'shots', 1, 'dialogue'), '字' * 36),
    (('version', 'shots', 1, 'action'), '旁白说明这一变化。'),
    (('version', 'shots', 1, 'start_state'), {}),
    (('version', 'shots', 5, 'dialogue'), '下集再说。'),
    (('version', 'shots', 5, 'dialogue'), '是否签字？'),
    (('version', 'reference_usage', 0, 'source_id'), 'douyin:unknown'),
    (('version', 'reference_usage', 0, 'evidence_ids'), ['A0002']),
    (('version', 'reference_usage', 0, 'evidence_ids'), ['A0001', 'A0001']),
    (('version', 'reference_usage', 0, 'shot_ids'), ['S99']),
    (('version', 'reference_usage', 0, 'contribution'), .5),
])
def test_rejects_story_schema_state_and_evidence_errors(path, value):
    data = screenplay()
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        validate_screenplay(data, 'short', 45, sources())


@pytest.mark.parametrize('category,key', [('people', '林岚'), ('props', 'pen')])
def test_all_states_must_repeat_every_defined_entity(category, key):
    data = screenplay()
    del data['version']['shots'][3]['end_state'][category][key]
    with pytest.raises(ValueError):
        validate_screenplay(data, 'short', 45, sources())


def test_silence_is_allowed_before_final_shot_and_never_gets_invented_audio():
    data = screenplay()
    data['version']['shots'][1].update(dialogue_speaker='', dialogue='')
    validate_screenplay(data, 'short', 45, sources())
    shot = compile_screenplay(data, production(data), 'short')['shots'][1]
    assert (shot['dialogue_mode'], shot['dialogue_speaker'], shot['dialogue']) == ('none', '', '')
    assert shot['audio'] == '本镜无人说话。'
    data['version']['shots'][-1].update(dialogue_speaker='', dialogue='')
    with pytest.raises(ValueError, match='final dialogue'):
        validate_screenplay(data, 'short', 45, sources())


def test_rejects_total_spoken_budget_and_wrong_total_duration():
    data = screenplay()
    for shot in data['version']['shots']:
        shot['dialogue'] = '字' * (shot['duration_seconds'] * 4 + 1)
    with pytest.raises(ValueError, match='total dialogue'):
        validate_screenplay(data, 'short', 45, sources())
    data = screenplay()
    data['version']['shots'][0]['duration_seconds'] += 1
    with pytest.raises(ValueError, match='total duration'):
        validate_screenplay(data, 'short', 45, sources())
    with pytest.raises(ValueError, match='duration must'):
        validate_screenplay(screenplay(), 'short', 46, sources())


@pytest.mark.parametrize('selected', [('douyin:2',), ('unknown',), ('douyin:1', 'douyin:1'), 'douyin:1'])
def test_only_explicit_detailed_references_are_allowed(selected):
    with pytest.raises(ValueError):
        validate_screenplay(screenplay(), 'short', 45, sources(), selected)


def test_overview_does_not_count_as_original_evidence():
    data = sources()
    data[0]['expression_analysis'] = {'core_message': '原片概览'}
    with pytest.raises(ValueError, match='overview'):
        validate_screenplay(screenplay(), 'short', 45, data)


@pytest.mark.parametrize('change', [
    {'channel': 'summary'}, {'start_seconds': -1}, {'end_seconds': 40},
    {'start_seconds': float('nan')}, {'end_seconds': True}, {'text': ''},
])
def test_cited_records_must_be_real_timed_audio_or_visual_evidence(change):
    data = sources()
    data[0]['expression_analysis']['evidence'][0].update(change)
    with pytest.raises(ValueError):
        validate_screenplay(screenplay(), 'short', 45, data)


def test_duplicate_source_and_original_evidence_ids_are_rejected():
    data = sources()
    data.append(copy.deepcopy(data[0]))
    with pytest.raises(ValueError, match='duplicate source'):
        validate_screenplay(screenplay(), 'short', 45, data)
    data = sources()
    records = data[0]['expression_analysis']['evidence']
    records.append(copy.deepcopy(records[0]))
    with pytest.raises(ValueError, match='duplicate ID'):
        validate_screenplay(screenplay(), 'short', 45, data)


def test_rendering_uses_definition_order_and_preserves_original_text():
    data = screenplay()
    state = copy.deepcopy(data['version']['initial_state'])
    state['people'] = dict(reversed(list(state['people'].items())))
    state['props'] = dict(reversed(list(state['props'].items())))
    text = render_state(state, data['characters'], data['version']['props'])
    assert text.index('林岚：') < text.index('陈宁：') < text.index('paper（') < text.index('pen（')
    assert all(value in text for values in state.values() for value in values.values())
    assert text == render_state(data['version']['initial_state'], data['characters'], data['version']['props'])


def test_compilation_freezes_story_and_inherits_every_previous_end():
    story = screenplay()
    photo = production(story)
    originals = copy.deepcopy((story, photo))
    compiled = compile_screenplay(story, photo, 'short')
    assert (story, photo) == originals
    assert set(compiled) == {'title', 'premise', 'dramatic_question', 'resolution', 'closing_line',
                             'legal_review_note', 'reference_usage', 'characters', 'expression_plan',
                             'story_beats', 'shots'}
    cursor = 0
    for index, (source, shot) in enumerate(zip(story['version']['shots'], compiled['shots'])):
        assert shot['action'] == source['action']
        assert shot['dialogue'] == source['dialogue']
        assert shot['dialogue_speaker'] == source['dialogue_speaker']
        assert (shot['start_seconds'], shot['end_seconds']) == (cursor, cursor + source['duration_seconds'])
        cursor = shot['end_seconds']
        assert shot['scene'] == story['version']['scene']
        assert shot['blocking'] == story['version']['spatial_layout']
        voice = next(c['voice'] for c in story['characters'] if c['name'] == source['dialogue_speaker'])
        assert voice in shot['audio']
        if index:
            assert shot['start_frame'] == compiled['shots'][index - 1]['end_frame']
    assert compiled['closing_line'] == story['version']['shots'][-1]['dialogue']
    assert compiled['reference_usage'] == story['version']['reference_usage']
    assert compiled['shots'][-1]['end_seconds'] == 45
    assert 'passed' not in compiled and 'approved' not in compiled
    compiled['reference_usage'][0]['adaptation'] = '修改输出不改输入'
    assert story == originals[0]


@pytest.mark.parametrize('field', ['action', 'dialogue', 'end_state', 'duration_seconds',
                                   'dialogue_speaker', 'scene', 'start_frame', 'audio'])
def test_photography_cannot_supply_any_frozen_story_fields(field):
    story = screenplay()
    photo = production(story)
    photo['shots'][0][field] = '新的内容'
    with pytest.raises(ValueError, match='fields must'):
        compile_screenplay(story, photo, 'short')


@pytest.mark.parametrize('field', ['goal', 'obstacle', 'stakes'])
def test_photography_plan_cannot_rewrite_frozen_goal_obstacle_stakes(field):
    story = screenplay()
    photo = production(story)
    photo['expression_plan'][field] += '多写一点'
    with pytest.raises(ValueError, match='frozen story'):
        compile_screenplay(story, photo, 'short')


def test_photography_cannot_move_people_or_change_scene_or_references():
    story = screenplay()
    photo = production(story)
    photo['scene_design']['blocking'] = '两人改成并排坐。'
    with pytest.raises(ValueError, match='spatial_layout'):
        compile_screenplay(story, photo, 'short')
    for field in ('scene', 'reference_usage', 'characters', 'core_message'):
        photo = production(story)
        photo[field] = '摄影不改故事'
        with pytest.raises(ValueError, match='fields must'):
            compile_screenplay(story, photo, 'short')


def test_short_shared_camera_expands_references_and_rejects_conflicts():
    story = screenplay()
    photo = production(story)
    for shot in photo['shots'][1:]:
        shot['shot_size'] = '同S01'
        del shot['camera_angle']
        del shot['camera_movement']
    compiled = compile_screenplay(story, photo, 'short')
    assert {s['shot_size'] for s in compiled['shots']} == {'中景'}
    assert {s['camera_angle'] for s in compiled['shots']} == {'桌侧平视双人机位。'}
    photo['shots'][1]['camera_movement'] = '横移'
    with pytest.raises(ValueError, match='shared camera'):
        compile_screenplay(story, photo, 'short')


def test_long_camera_variation_and_speaker_visibility():
    story = screenplay('long')
    photo = production(story, 'long')
    photo['shots'][0].update(shot_size='近景', camera_angle='北侧人物平视单人机位。', participants=['林岚'])
    compiled = compile_screenplay(story, photo, 'long')
    assert compiled['shots'][0]['shot_size'] == '近景'
    assert compiled['shots'][0]['participants'] == ['林岚']
    assert compiled['shots'][-1]['end_seconds'] == 180
    photo['shots'][0]['participants'] = ['陈宁']
    with pytest.raises(ValueError, match='speaking character'):
        compile_screenplay(story, photo, 'long')


@pytest.mark.parametrize('participants', [['林岚'], ['林岚', '陌生人'], ['林岚', '林岚'], []])
def test_short_keeps_exactly_both_people_visible(participants):
    story = screenplay()
    photo = production(story)
    photo['shots'][0]['participants'] = participants
    with pytest.raises(ValueError):
        compile_screenplay(story, photo, 'short')


def test_production_cannot_reorder_shots_or_reassign_frozen_beats():
    story = screenplay()
    photo = production(story)
    photo['shots'][0], photo['shots'][1] = photo['shots'][1], photo['shots'][0]
    with pytest.raises(ValueError, match='reordering'):
        compile_screenplay(story, photo, 'short')
    photo = production(story)
    photo['story_beats'][0]['shot_ids'] = ['S02']
    with pytest.raises(ValueError, match='frozen beat'):
        compile_screenplay(story, photo, 'short')


def test_compiled_pair_is_compatible_with_existing_structural_parser():
    from src.trend_intelligence.script_pair import parse_pair, validate_continuous_short
    short, long = screenplay(), screenplay('long')
    raw = {'core_message': short['core_message'],
           'short': compile_screenplay(short, production(short), 'short'),
           'long': compile_screenplay(long, production(long, 'long'), 'long')}
    validate_continuous_short(raw)
    profile = SimpleNamespace(account_uuid='account:test', domain_strategy_id='legal_services', strategy_version='test')
    scripts = parse_pair(json.dumps(raw, ensure_ascii=False), profile=profile,
                         created_at='2026-09-10T12:00:00+08:00', short_seconds=45, long_seconds=180,
                         generation={}, source_evidence=sources())
    assert len(scripts[0].shots) == 6
    assert len(scripts[1].shots) == 9
    assert scripts[0].shots[0].action == short['version']['shots'][0]['action']
    assert scripts[1].shots[0].dialogue == long['version']['shots'][0]['dialogue']


def test_v2_projects_s05_actor_and_every_action_from_reviewed_story_without_reauthoring():
    story = screenplay()
    story['version']['shots'][4]['action'] = '陈宁把paper沿桌面推回林岚面前，林岚双手不动。'
    photo = production_v2(story)
    original = copy.deepcopy((story, photo))
    compiled = compile_screenplay(story, photo, 'short')
    assert (story, photo) == original
    plan = compiled['expression_plan']
    for role, step, beat in zip(BEAT_ROLES, plan['action_chain'], compiled['story_beats']):
        group = [s for s in story['version']['shots'] if s['beat'] == role]
        action = '\n'.join(s['action'] for s in group)
        assert step['shot_ids'] == [s['shot_id'] for s in group]
        assert step['visible_action'] == beat['change'] == action
        assert step['state_change'] == '动作：' + action + '\n末态：' + render_state(
            group[-1]['end_state'], story['characters'], story['version']['props'])
    s05 = plan['action_chain'][4]
    assert s05['visible_action'] == story['version']['shots'][4]['action']
    assert s05['visible_action'].startswith('陈宁把paper')
    assert not s05['visible_action'].startswith('林岚把paper')
    assert compiled['shots'][4]['action'] == s05['visible_action']
    assert compiled['reference_usage'] == story['version']['reference_usage']
    for field in ('goal', 'obstacle', 'stakes'):
        assert plan[field] == story['version'][field]
    assert plan['ending']['core_answer'] == story['version']['resolution']
    assert plan['ending']['shot_ids'] == ['S06']
    assert story['version']['shots'][-1]['action'] in plan['ending']['visible_result']


def test_v2_because_is_previous_actual_dialogue_or_action_not_invented_causality():
    story = screenplay()
    story['version']['shots'][0].update(dialogue='', dialogue_speaker='')
    compiled = compile_screenplay(story, production_v2(story), 'short')
    beats = compiled['story_beats']
    assert beats[0]['because'] == story['version']['premise']
    assert beats[1]['because'] == story['version']['shots'][0]['action']
    assert beats[2]['because'] == story['version']['shots'][1]['dialogue']


def test_v2_turn_contains_every_frozen_turn_shot_and_their_actual_end_state():
    story = screenplay('long')
    story['version']['shots'][5]['beat'] = 'turn'
    compiled = compile_screenplay(story, production_v2(story, 'long'), 'long')
    turn = compiled['expression_plan']['turn']
    assert turn['shot_ids'] == ['S05', 'S06']
    assert turn['visible_trigger'] == '\n'.join(s['action'] for s in story['version']['shots'][4:6])
    assert turn['result'] == render_state(story['version']['shots'][5]['end_state'],
                                         story['characters'], story['version']['props'])


def test_v2_same_end_pose_retains_distinct_actual_action_context_without_fabricated_changes():
    story = screenplay()
    for shot in story['version']['shots']:
        shot['end_state'] = copy.deepcopy(story['version']['initial_state'])
    compiled = compile_screenplay(story, production_v2(story), 'short')
    chain = compiled['expression_plan']['action_chain']
    assert len({step['state_change'] for step in chain}) == 6
    for shot, step in zip(story['version']['shots'], chain):
        assert step['state_change'] == '动作：' + shot['action'] + '\n末态：' + render_state(
            shot['end_state'], story['characters'], story['version']['props'])


@pytest.mark.parametrize('field', ['blocking', 'transition', 'action', 'dialogue', 'initial_state',
                                  'end_state', 'expression_plan', 'story_beats', 'reference_usage'])
def test_v2_no_top_level_route_for_model_to_override_projected_story(field):
    story = screenplay()
    photo = production_v2(story)
    photo[field] = '模型试图再写故事'
    with pytest.raises(ValueError, match='fields must'):
        compile_screenplay(story, photo, 'short')


@pytest.mark.parametrize('field', ['blocking', 'transition', 'action', 'dialogue', 'end_state',
                                  'start_frame', 'audio', 'narrative_purpose'])
def test_v2_no_per_shot_route_for_story_or_transition_rewriting(field):
    story = screenplay()
    photo = production_v2(story)
    photo['shots'][4][field] = '林岚执行原本属于陈宁的动作'
    with pytest.raises(ValueError, match='fields must'):
        compile_screenplay(story, photo, 'short')


@pytest.mark.parametrize('field', ['goal', 'obstacle', 'stakes', 'turn', 'ending', 'state_change'])
def test_v2_interpretation_cannot_add_frozen_or_derived_story_fields(field):
    story = screenplay()
    photo = production_v2(story)
    photo['interpretation'][field] = '新增主张'
    with pytest.raises(ValueError, match='fields must'):
        compile_screenplay(story, photo, 'short')


@pytest.mark.parametrize('field', ['shot_size', 'camera_angle', 'camera_movement'])
def test_v2_short_camera_fields_cannot_be_repeated_even_with_same_value(field):
    story = screenplay()
    photo = production_v2(story)
    photo['shots'][1][field] = photo['scene_design'][field]
    with pytest.raises(ValueError, match='fields must'):
        compile_screenplay(story, photo, 'short')


def test_v2_blocking_has_only_one_authoritative_original_and_camera_one_shared_value():
    story = screenplay()
    photo = production_v2(story)
    compiled = compile_screenplay(story, photo, 'short')
    for field in ('shot_size', 'camera_angle', 'camera_movement'):
        assert {row[field] for row in compiled['shots']} == {photo['scene_design'][field]}
    assert {row['blocking'] for row in compiled['shots']} == {story['version']['spatial_layout']}
    photo['scene_design']['blocking'] = story['version']['spatial_layout']
    with pytest.raises(ValueError, match='fields must'):
        compile_screenplay(story, photo, 'short')


def test_v2_transition_only_inherits_end_state_and_does_not_add_time_or_actions():
    story = screenplay()
    compiled = compile_screenplay(story, production_v2(story), 'short')
    for shot, following in zip(compiled['shots'], compiled['shots'][1:]):
        assert shot['end_frame'] == following['start_frame']
        assert shot['transition'] == '本镜结束状态直接作为下一镜开始状态：' + following['start_frame']
    last = compiled['shots'][-1]
    assert last['transition'] == '在本镜既定时长内完成末态后自然结束，不追加静止时长：' + last['end_frame']
    assert last['end_seconds'] == 45
    assert [s['end_seconds'] - s['start_seconds'] for s in compiled['shots']] == [
        s['duration_seconds'] for s in story['version']['shots']]


def test_v2_long_may_override_some_camera_fields_while_other_fields_inherit_shared_design():
    story = screenplay('long')
    photo = production_v2(story, 'long')
    photo['shots'][0].update(shot_size='近景', participants=['林岚'])
    compiled = compile_screenplay(story, photo, 'long')
    assert compiled['shots'][0]['shot_size'] == '近景'
    assert compiled['shots'][0]['camera_angle'] == photo['scene_design']['camera_angle']
    assert compiled['shots'][0]['participants'] == ['林岚']
    assert compiled['shots'][1]['shot_size'] == photo['scene_design']['shot_size']


def test_unknown_production_schema_is_not_silently_treated_as_legacy():
    story = screenplay()
    photo = production_v2(story)
    photo['schema'] = 'screenplay_production/v999'
    with pytest.raises(ValueError, match='production.schema'):
        compile_screenplay(story, photo, 'short')


def test_v2_compiled_pair_uses_existing_parser_without_relaxing_legacy_checks():
    from src.trend_intelligence.script_pair import parse_pair, validate_continuous_short
    short, long = screenplay(), screenplay('long')
    pair = {'core_message': short['core_message'],
            'short': compile_screenplay(short, production_v2(short), 'short'),
            'long': compile_screenplay(long, production_v2(long, 'long'), 'long')}
    validate_continuous_short(pair)
    profile = SimpleNamespace(account_uuid='account:test', domain_strategy_id='legal_services', strategy_version='test')
    scripts = parse_pair(json.dumps(pair, ensure_ascii=False), profile=profile,
                         created_at='2026-09-10T12:00:00+08:00', short_seconds=45, long_seconds=180,
                         generation={}, source_evidence=sources())
    assert [s.target_duration_seconds for s in scripts] == [45, 180]
    for original, compiled in zip((short, long), scripts):
        assert [s.action for s in compiled.shots] == [s['action'] for s in original['version']['shots']]
        assert [s.dialogue for s in compiled.shots] == [s['dialogue'] for s in original['version']['shots']]
