"""Real source/image CPU regressions; no synthetic content-acceptance claims."""
from pathlib import Path
from copy import deepcopy
import json

import pytest

from scripts import prepare_h3_continuity_case_v33 as case
from src.content_factory import visual_h3_continuity_input_v33 as flow


@pytest.fixture
def real(tmp_path):
    spec_path = case.build(tmp_path / 'real_case')
    return flow.binding(spec_path), json.loads(spec_path.read_text(encoding='utf-8'))


def test_real_four_source_scripts_keep_all_ten_audio_occurrences(real):
    binding, spec = real
    assert sum(len(s['audio']) for s in spec['shots']) == 10
    for shot in spec['shots']:
        compiled = flow.preview_prompt(binding, shot['shot_id'])
        assert compiled['source_coverage_complete'] is True
        assert compiled['dispatchable'] is False
        assert flow.QUOTE.findall(compiled['compiled_prompt']) == flow.QUOTE.findall(
            Path(shot['source']['path']).read_text(encoding='utf-8'))


def test_camera_connector_does_not_delete_bread_handoff_actions(real):
    _, spec = real
    second = spec['shots'][1]
    action = ''.join(s['text'] for s in second['source_spans'] if s['kind'] == 'action')
    assert '他尚未伸手接' in action
    assert '苏墨低头看面包与孩子' in action
    third = ''.join(s['text'] for s in spec['shots'][2]['source_spans'] if s['kind'] == 'action')
    assert '没有立刻接面包' in third
    assert '只把面包从叶西决手里拿走' in third


def test_actual_partial_first_frames_cannot_be_inherited_as_complete_identity(real):
    binding, _ = real
    for sid in ('S01', 'S02', 'S03', 'S04'):
        result = flow.preflight(binding, sid)
        assert result['status'] == 'reanchor_required'
        assert result['model_calls'] == 0
    last = flow.preflight(binding, 'S04')
    assert 'su_mo' in json.dumps(last, ensure_ascii=False)
    assert last.get('first_image') is None


def test_hands_insert_and_father_closeup_are_distinct_source_bound_shots(real):
    _, spec = real
    beats = spec['shots'][1]['camera_beats']
    assert beats[-2]['framing'] == 'hands_close'
    assert all('face' not in a['visible_parts'] for a in beats[-2]['actors'].values())
    assert beats[-1]['cut'] is True
    assert list(beats[-1]['actors']) == ['su_mo']
    assert beats[-1]['framing'] == 'face_close'
    # The brother's visible shock must not be scheduled in a hands-only frame.
    assert 'face' in spec['shots'][2]['camera_beats'][-1]['actors']['ye_nan']['visible_parts']


def test_photographic_prompts_keep_role_mapping_without_engineering_tags(real):
    binding, _ = real
    for sid in ('S01', 'S02', 'S03', 'S04'):
        text = flow.preview_prompt(binding, sid)['compiled_prompt']
        assert '灰色翻领短袖上衣' in text
        assert '米色圆领短袖上衣' in text
        assert '深色夹克' in text
        assert '普通话对白与原生同步音轨' in text
        assert '苏墨自然中低男声' in text
        assert '叶南稚嫩但较稳的男童声' in text
        for marker in ('<d>', '[Mandarin Chinese]', 'face_close', 'visible_parts', 'says in', '<Picture'):
            assert marker not in text


def test_family_size_in_voice_does_not_expand_visible_actors(real):
    _, spec = real
    second = flow.validate_entry(spec['shots'][1])
    assert set(second['visible_actors']) == {'su_mo', 'ye_nan', 'ye_xijue'}
    assert set(second['required_faces']) == {'su_mo', 'ye_nan', 'ye_xijue'}


def test_deleted_audio_or_half_quote_window_is_rejected_on_real_source(real):
    _, spec = real
    shot = deepcopy(spec['shots'][-1])
    shot['audio'] = []
    with pytest.raises(flow.ContinuityError):
        flow.validate_entry(shot)
    shot = deepcopy(spec['shots'][-1])
    first_audio = next(s for s in shot['source_spans'] if s['kind'] == 'audio')
    shot['source_scope']['start'] = first_audio['start'] + 1
    with pytest.raises(flow.ContinuityError):
        flow.validate_entry(shot)
