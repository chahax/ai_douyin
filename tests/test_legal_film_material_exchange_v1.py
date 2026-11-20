"""Offline source/state/timing boundaries for the material exchange only."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import pytest
from jsonschema import Draft202012Validator, ValidationError
from src.content_factory import creative_film_material_exchange_v1 as c

SOURCE = Path(__file__).resolve().parents[1] / 'data/production_revisions/legal_natural_interaction_20261010/round_05/REVIEWED_CANDIDATE/FULL_SCRIPT.json'


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('offline tests cannot access a network')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


@pytest.fixture
def current():
    script = json.loads(SOURCE.read_text(encoding='utf-8-sig'))
    actor = {'continuous_performance': '周姐边说明公司这一安排边让小林看材料，将纸笔一次送到他手边并收回手。小林等纸到位才低头，看清原因栏后当面反问，仍未碰笔。',
             'zhou_intent': '让小林把眼前材料接下并按这份材料办手续',
             'xiaolin_intent': '要求周姐解释纸上为何写成自己辞职',
             'camera': '同侧观察小林从接收材料到看清原因后的理解变化，让双方位置及纸笔去向可读，当前反问完整后才结束。',
             'delivery': '正常普通话交谈，周姐面对小林说明，小林看清字样后自然追问，不赶字。',
             'post_pause_seconds': .4}
    return script, actor


def test_native_schema_exact_four_sources_and_length_contract(current):
    script, actor = current
    schema = c.schema(script)
    Draft202012Validator(schema).validate(actor)
    assert set(schema['properties']) == set(c.NATIVE_UNIT_FIELDS)
    assert schema['additionalProperties'] is False
    assert schema['properties']['continuous_performance']['maxLength'] == 320
    assert schema['properties']['zhou_intent']['maxLength'] == 80
    assert schema['properties']['camera']['maxLength'] == 160
    assert schema['properties']['delivery']['maxLength'] == 100
    assert list(c.current_catalog(script)) == ['B1.S04', 'B1.S05', 'B1.S06', 'B1.S07']


def test_normal_timing_one_late_push_and_arrival_before_reading(current):
    script, actor = current
    result = c.compile_contract(actor, script)
    rows = {row['source_ref']: row for row in result['schedule']}
    assert rows['B1.S04']['start'] == 0
    assert rows['B1.S04']['end'] == pytest.approx(23 / 3.3, abs=1e-6)
    assert rows['B1.S05']['start'] == pytest.approx(23 / 3.3 - 2, abs=1e-6)
    assert rows['B1.S05']['end'] == rows['B1.S04']['end']
    assert rows['B1.S05']['duration_seconds'] == 2
    assert rows['B1.S06']['start'] >= rows['B1.S05']['end']
    assert rows['B1.S06']['start'] >= rows['B1.S04']['end']
    assert rows['B1.S06']['duration_seconds'] == pytest.approx(15 / 3.3, abs=1e-6)
    assert rows['B1.S07']['start'] == rows['B1.S06']['start']
    assert rows['B1.S07']['end'] == result['source_seconds']
    assert rows['B1.S07']['duration_seconds'] == 0 and rows['B1.S07']['persistent_state'] is True
    assert result['source_seconds'] == pytest.approx(38 / 3.3 + .4, abs=1e-6)
    assert result['duration_seconds'] == 12
    assert result['fit_scaled'] is False
    assert result['timing_assumption']['measured_audio'] is False
    assert result['semantic_units'][0]['overlap_pairs'] == [{'action_ref': 'B1.S05', 'dialogue_ref': 'B1.S04'}]


def test_state_and_prose_preserved_without_claiming_prior_coverage(current):
    script, actor = current
    before_script, before_actor = deepcopy(script), deepcopy(actor)
    result = c.compile_contract(actor, script)
    assert script == before_script and actor == before_actor
    assert {field: result['semantic_units'][0][field] for field in c.NATIVE_UNIT_FIELDS} == actor
    assert result['initial_state']['folder'] == result['final_state']['folder'] == 'open'
    assert result['initial_state']['paper'] == result['initial_state']['pen'] == 'zhou_side'
    assert result['final_state']['paper'] == result['final_state']['pen'] == 'xiaolin_near_edge'
    assert result['initial_state']['badge'] == result['final_state']['badge'] == 'worn_by_xiaolin'
    assert result['physical_transition']['movement_count'] == 1
    assert result['final_state']['paper_signed'] is False and result['final_state']['xiaolin_pen_touched'] is False
    assert result['complete_current_material_exchange'] is True
    assert result['current_remaining_unit_complete'] is True
    assert result['complete_B1'] is False and result['B1_coverage_pending'] is True
    assert result['prior_refs_required'] == ['B1.S01', 'B1.S02', 'B1.S03']
    assert result['whole_film_performance_complete'] is False
    assert result['creative_quality_passed'] is False and result['actual_media_readability'] is None
    assert result['requires_human_approved_service_tail_before_media'] is True


def test_prompt_approved_first_frame_exact_dialogues_once_and_no_future(current):
    script, actor = current
    candidate = c.pack_first(c.compile_contract(actor, script))
    prompt = c.render_prompt(candidate, script)
    for ref, source in c.catalog(script).items():
        if source['kind'] == 'dialogue':
            assert prompt.count(source['text']) == int(ref in c.CURRENT_SOURCE_REFS)
    assert '用户批准的上一段生成服务原始尾帧，作为first_frame' in prompt
    assert '不重新入座、开夹或戴工牌' in prompt
    assert '一次送到小林靠桌沿的位置' in prompt
    assert '不把纸推向桌子中间，不重复推' in prompt
    assert '纸笔到位且周姐完整说完后' in prompt
    assert '无字幕' in prompt and '正常谈话速度' in prompt
    assert candidate['complete_B1'] is False and candidate['full_film_complete'] is False


def test_short_cap_or_native_overflow_blocks_entire_unit_without_fitting(current, monkeypatch):
    script, actor = current
    compiled = c.compile_contract(actor, script)
    short = c.pack_first(compiled, max_seconds=10)
    assert short['dispatch_ready'] is False and short['semantic_units'] == []
    assert short['source_refs'] == [] and short['duration_seconds'] is None
    assert short['fit_scaled'] is False
    with pytest.raises(ValueError, match='unready'):
        c.render_prompt(short, script)
    # Simulate a slower necessary delivery to exercise the native hard limit.
    monkeypatch.setattr(c, 'NORMAL_SPOKEN_CHARACTERS_PER_SECOND', 1.0)
    overlong = c.compile_contract(actor, script)
    assert overlong['needs_revision'] is True and overlong['duration_seconds'] is None
    candidate = c.pack_first(overlong)
    assert candidate['dispatch_ready'] is False and candidate['fit_scaled'] is False


def test_bad_types_extra_fields_length_or_changed_source_rejected(current):
    script, actor = current
    for field, value in [('camera', {'item': 'wrong type'}), ('post_pause_seconds', 1.6), ('continuous_performance', '字' * 321)]:
        bad = deepcopy(actor)
        bad[field] = value
        with pytest.raises(ValidationError):
            c.compile_contract(bad, script)
    bad = deepcopy(actor)
    bad['source_refs'] = ['B1.S04']
    with pytest.raises(ValidationError):
        c.compile_contract(bad, script)
    changed = deepcopy(script)
    changed['beats'][0]['steps'][3]['text'] += '新字'
    with pytest.raises(ValueError, match='exact reviewed source380'):
        c.compile_contract(actor, changed)
    for ref in ['B1.S04', 'B1.S06', 'B2.S01']:
        bad = deepcopy(actor)
        bad['continuous_performance'] = c.catalog(script)[ref]['text']
        if c.catalog(script)[ref]['kind'] == 'dialogue':
            with pytest.raises(ValueError, match='dialogue copied'):
                c.compile_contract(bad, script)


def test_candidate_tampering_not_repaired_or_spliced(current):
    script, actor = current
    compiled = c.compile_contract(actor, script)
    candidate = c.pack_first(compiled)
    altered = deepcopy(candidate)
    altered['semantic_units'][0]['delivery'] = '手动回填新演法'
    with pytest.raises(ValueError, match='altered'):
        c.render_prompt(altered, script)
    altered = deepcopy(compiled)
    altered['schedule'][2]['start'] = 0
    with pytest.raises(ValueError, match='altered'):
        c.render_prompt(c.pack_first(altered), script)
    altered = deepcopy(candidate)
    altered['end_state']['paper'] = 'table_center'
    with pytest.raises(ValueError, match='altered'):
        c.render_prompt(altered, script)
