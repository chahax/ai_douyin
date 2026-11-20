"""Source projections and real handoff preparation, not visual model scoring."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.content_factory import visual_h3_continuity_input_v33 as core
from src.content_factory import visual_opening_frame as opening
from src.content_factory import visual_spatial_stills_v24 as stills
from test_visual_h3_continuity_input_v33 import make_entry, update_review, write


REAL = Path(__file__).resolve().parents[1] / 'data/qa/h3_prompt_identity_v33_20261108/REAL_CASE_r4/SPEC.json'


def real(sid):
    row = next(x for x in json.loads(REAL.read_text(encoding='utf-8'))['shots'] if x['shot_id'] == sid)
    row['first_frame_policy'] = opening.POLICY
    return row


@pytest.mark.parametrize('sid,cast,faces,room', [
    ('S01', ['ye_nan', 'ye_xijue'], ['ye_xijue'], True),
    ('S02', ['su_mo'], ['su_mo'], False),
    ('S03', ['ye_xijue'], ['ye_xijue'], False),
    ('S04', ['su_mo'], ['su_mo'], False),
])
def test_actual_novel_first_shot_is_not_whole_clip_union(sid, cast, faces, room):
    row = real(sid)
    full = core.validate_entry(row)
    first = opening.requirements(row, full)
    assert first['visible_actors'] == cast and first['required_faces'] == faces
    assert first['room_required'] is room
    assert full['visible_actors'] == ['su_mo', 'ye_nan', 'ye_xijue']
    assert len(first['opening_frame']['canonical_characters']) == 3
    assert first['opening_frame']['opening_camera_beat'] == row['camera_beats'][0]
    assert opening.contract(row)['actions_to_begin_after_first_instant']


def observed(row):
    review = core.read(row['coverage_review'])
    value = opening.contract(row)
    review['opening_frame'] = dict(
        contract_sha256=opening.digest(value), visible_actor_ids=value['opening_visible_actors'],
        framing=value['opening_camera_beat']['framing'],
        checks=dict(source_start_state_matches=True, source_attention_matches=True))
    # This observer belongs to a controlled fixture; no actual media pass implied.
    row['coverage_review'] = write(row['coverage_review']['path'], review)
    return review


def test_optin_needs_actual_opening_observation_not_old_true_flags(tmp_path):
    row = make_entry(tmp_path)
    row['first_frame_policy'] = opening.POLICY
    out = core.evaluate(row)
    assert out['status'] == 'reanchor_required'
    assert 'opening_frame_observation_missing_or_stale' in out['work_order']['reasons']
    observed(row)
    assert core.evaluate(row)['status'] == 'ready'


def test_first_shot_closeup_does_not_require_a_later_wide_room_or_face(tmp_path):
    row = make_entry(tmp_path)
    row['first_frame_policy'] = opening.POLICY
    first = row['camera_beats'][0]
    first.update(end=2, framing='face_close', source_span_ids=[])
    row['camera_beats'].append(dict(start=2, end=5, cut=True, framing='wide',
                                  actors=deepcopy(first['actors']), source_span_ids=['s2']))
    update_review(row, checks=dict(room_identity=None))
    observed(row)
    assert core.evaluate(row)['status'] == 'ready'
    update_review(row, checks=dict(room_identity=False))
    assert 'opening_visible_room_conflict' in core.evaluate(row)['work_order']['reasons']
    update_review(row, checks=dict(room_identity=None))
    row.pop('first_frame_policy')
    assert core.evaluate(row)['status'] == 'reanchor_required'


@pytest.mark.parametrize('change,reason', [
    (lambda v: v.update(framing='wide'), 'opening_framing_mismatch_or_unknown'),
    (lambda v: v.update(visible_actor_ids=['su_mo', 'ye_nan']), 'opening_visible_cast_mismatch_or_unknown'),
    (lambda v: v.update(contract_sha256='0' * 64), 'opening_frame_observation_missing_or_stale'),
    (lambda v: v['checks'].update(source_attention_matches=None), 'opening_source_attention_matches_bad_or_unknown'),
    (lambda v: v['checks'].update(source_start_state_matches=False), 'opening_source_start_state_matches_bad_or_unknown'),
])
def test_wrong_or_unknown_observation_cannot_approve_first_frame(tmp_path, change, reason):
    row = make_entry(tmp_path)
    row['first_frame_policy'] = opening.POLICY
    review = observed(row)
    change(review['opening_frame'])
    row['coverage_review'] = write(row['coverage_review']['path'], review)
    result = core.evaluate(row)
    assert result['status'] == 'reanchor_required' and reason in result['work_order']['reasons']


def test_world_members_and_bread_ownership_survive_render_selection():
    from src.content_factory import visual_spatial_reanchor_v34 as spatial
    shot = spatial.plan_from_spec()['shots'][1]
    before = deepcopy(shot['start_state'])
    shot['opening_frame'] = dict(policy=opening.POLICY, in_frame_actor_ids=['su_mo'], framing='face_close')
    depicted = opening.render_state(shot, shot['start_state'])
    assert shot['start_state'] == before
    assert all(a['visible'] for a in before['actors'].values())
    assert depicted['props'] == before['props']
    assert depicted['props']['bread_bag']['holder'] == 'ye_xijue'
    assert [who for who, a in depicted['actors'].items() if a['visible']] == ['su_mo']
    assert stills._state({'shots': [shot]}, shot['id'] + '_start') == depicted


def test_first_frame_prompt_does_not_reintroduce_whole_body_portrait():
    from src.content_factory import visual_spatial_reanchor_v34 as spatial
    shot = spatial.plan_from_spec(first_frame_policy=opening.POLICY)['shots'][1]
    state = opening.render_state(shot, shot['start_state'])
    text = stills._prompt('S02_start', state, ['su_mo'], material_contract={},
                         opening_frame=shot['opening_frame'])
    assert 'head-and-shoulders close-up' in text
    assert 'photographed visible body parts' in text and 'complete live-action human' not in text
    assert 'Ye Nan' not in text and 'Ye Xijue' not in text
    assert 'empty hands' not in text and 'hand grips' not in text


def test_offframe_prop_is_not_reintroduced_by_first_frame_prompt():
    from src.content_factory import visual_spatial_reanchor_v34 as spatial
    plan = spatial.plan_from_spec(first_frame_policy=opening.POLICY)
    shot = plan['shots'][2]  # Source holds bag, but first shot shows face/torso.
    state = opening.render_state(shot, shot['start_state'])
    text = stills._prompt('S03_start', state, ['ye_xijue'], material_contract={},
                         opening_frame=shot['opening_frame'])
    assert state['props']['bread_bag']['holder'] == 'ye_xijue'
    assert state['_opening_bread_visible'] is False
    assert 'transparent plastic bag' not in text and 'natural hands' not in text
    last = plan['shots'][3]
    last_text = stills._prompt('S04_start', opening.render_state(last, last['start_state']),
                              ['su_mo'], material_contract={}, opening_frame=last['opening_frame'])
    assert 'transparent plastic bag' in last_text


@pytest.mark.parametrize('field,value', [('framing', 'wide'), ('policy', 'legacy'),
                                         ('camera_beat_sha256', '0' * 64),
                                         ('in_frame_actor_ids', ['su_mo', 'ye_nan'])])
def test_still_producer_descriptor_cannot_override_its_source_beat(field, value):
    from src.content_factory import visual_spatial_reanchor_v34 as spatial
    selected = spatial.plan_from_spec(first_frame_policy=opening.POLICY)['shots'][1]['opening_frame']
    selected[field] = value
    with pytest.raises(ValueError, match='opening_selection_not_bound'):
        opening.still_instruction(selected)


def test_unknown_policy_and_modified_source_are_rejected(tmp_path):
    row = make_entry(tmp_path)
    row['first_frame_policy'] = 'magic_avoid_portrait'
    with pytest.raises(ValueError, match='unsupported_first_frame'):
        core.evaluate(row)
    row['first_frame_policy'] = opening.POLICY
    Path(row['source']['path']).write_text('changed', encoding='utf-8')
    with pytest.raises(ValueError, match='bound_input'):
        core.evaluate(row)


def test_later_cast_descriptions_do_not_claim_to_be_in_single_person_first_image():
    row = real('S02')
    before = Path(row['source']['path']).read_bytes()
    text = core.compile_prompt(row)['compiled_prompt']
    assert '叶南是本段的哥哥' in text and '叶西决是本段的弟弟' in text
    assert '叶南是首图中的' not in text and '叶西决是首图中的' not in text
    row.pop('first_frame_policy')
    old = core.compile_prompt(row)['compiled_prompt']
    assert '叶南是首图中的哥哥' in old
    assert core.QUOTE.findall(text) == core.QUOTE.findall(old)
    assert Path(row['source']['path']).read_bytes() == before


def test_no_policy_keeps_legacy_contract_and_entire_audio_unchanged():
    for sid in ('S01', 'S02', 'S03', 'S04'):
        row = real(sid)
        first = core.compile_prompt(row)
        row.pop('first_frame_policy')
        old = core.compile_prompt(row)
        validated = core.validate_entry(row)
        assert opening.requirements(row, validated) is validated
        assert opening.contract(row) is None
        assert core.QUOTE.findall(first['compiled_prompt']) == core.QUOTE.findall(old['compiled_prompt'])
        expected = '\n'.join(line.replace('首图中的', '本段的') if line.startswith('人物身份与服装：')
                             else line for line in old['compiled_prompt'].split('\n'))
        assert expected == first['compiled_prompt'].replace(
            '首图就是下列0秒开始的第一个剧情镜头，人物按当时动作与注意对象演出；随后按时间推进并切换镜头。\n', '')


def test_real_native_preparation_binds_first_beat_and_all_later_actors(tmp_path):
    from test_visual_h3_continuity_input_v33 import _three_adapter
    from src.content_factory import visual_h3_handoff_v3 as native
    row, _, cfg, _ = _three_adapter(tmp_path)
    row['first_frame_policy'] = opening.POLICY
    # Protocol fixture only. Keep the actual all-character packet and speech.
    observed(row)
    binding = write(tmp_path / 'new_opening_spec.json', dict(schema=core.SCHEMA, shots=[row]))
    cfg.pop('continuity_input_plan', None)
    run = Path(cfg['runs_root']) / 'native_new_opening'
    native.prepare_from_continuity(binding, run, cfg)
    result = json.loads((run / 'PLAN.json').read_text(encoding='utf-8'))
    shot = result['shots'][0]
    assert shot['first_frame']['sha256'] == row['actual_first_image']['sha256']
    graph = json.loads((run / 'shots' / row['shot_id'] / 'workflow_api.json').read_text(encoding='utf-8'))
    assert '首图就是下列0秒开始' in graph['condition']['inputs']['prompt']
    assert len(core.handoff_snapshot(binding, cfg)[2]['shots'][0]['visible_cast']) == 3
    assert not (run / 'shots' / row['shot_id'] / 'REQUEST.json').exists()
