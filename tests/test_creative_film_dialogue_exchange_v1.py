"""Disconnected contract boundaries; no service or media calls."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import pytest
from jsonschema import ValidationError
from src.content_factory import creative_film_dialogue_exchange_v1 as c
from src.content_factory import creative_film_material_exchange_v1 as material

SOURCE = (Path(__file__).resolve().parents[1] / 'data/production_revisions'
          / 'legal_natural_interaction_20261010/round_05/REVIEWED_CANDIDATE/FULL_SCRIPT.json')


@pytest.fixture(autouse=True)
def disconnected(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('offline contract tests cannot connect')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)


@pytest.fixture
def current():
    script = json.loads(SOURCE.read_text(encoding='utf-8'))
    ordered = list(c.catalog(script))
    spec = {'schema': c.SPEC_VERSION, 'source_sha256': c.digest(script),
            'beat_id': 'B2', 'interaction_id': 'refusal_and_format',
            'source_refs': ['B2.S01', 'B2.S02'],
            'prior_source_refs': ordered[:ordered.index('B2.S01')],
            'initial_state': deepcopy(material.FINAL_STATE),
            'final_state': deepcopy(material.FINAL_STATE),
            'brief': {'current_change': '拒绝被周姐以惯例绕开异议。',
                      'observation': '观察小林表态及接收到格式答复的变化。',
                      'cut_condition': '当前两句完整说完，答复被接收后结束。'}}
    raw = {'continuous_performance': '小林面向周姐说清自己的选择；周姐听完后以公司惯例回应，小林接收到这次回避，纸笔仍留原位。',
           'zhou_intent': '让小林把眼前异议视为惯例办理',
           'xiaolin_intent': '让对方承认本人意愿不能被材料代替',
           'camera': '同侧观察小林表态及周姐回应，完整答复被接收后才结束。',
           'delivery': '正常普通话交谈，重点来自关系，不逐字摆声。',
           'post_pause_seconds': 1.2}
    return script, spec, raw


def test_native_schema_reuses_six_fields_and_lengths(current):
    script, spec, _ = current
    assert c.schema(script, spec) == material.schema(script)
    assert set(c.schema(script, spec)['properties']) == set(material.NATIVE_UNIT_FIELDS)


def test_normal_speech_is_sequential_without_added_interturn_pause(current):
    script, spec, raw = current
    compiled = c.compile_contract(raw, script, spec)
    first, second = compiled['schedule']
    assert first['duration_seconds'] == pytest.approx(26 / 3.3, abs=1e-6)
    assert second['duration_seconds'] == pytest.approx(17 / 3.3, abs=1e-6)
    assert second['start'] == first['end']
    assert compiled['source_seconds'] == pytest.approx(43 / 3.3 + 1.2, abs=1e-6)
    assert compiled['duration_seconds'] == 15
    assert compiled['timing_assumption']['measured_audio'] is False
    assert compiled['timing_assumption']['fixed_inter_turn_pause_seconds'] == 0


def test_spec_rejects_gaps_actions_reordering_and_incomplete_prefix(current):
    script, spec, raw = current
    changes = [
        {'source_refs': ['B2.S01', 'B2.S03']},
        {'beat_id': 'B1', 'source_refs': ['B1.S05', 'B1.S06'],
         'prior_source_refs': list(c.catalog(script))[:4]},
        {'source_refs': ['B2.S02', 'B2.S01']},
        {'prior_source_refs': []},
    ]
    for change in changes:
        bad = {**deepcopy(spec), **change}
        with pytest.raises(ValueError):
            c.compile_contract(raw, script, bad)


def test_state_source_and_native_values_are_preserved_and_coverage_pending(current):
    script, spec, raw = current
    before = deepcopy((script, spec, raw))
    compiled = c.compile_contract(raw, script, spec)
    assert (script, spec, raw) == before
    unit = compiled['semantic_units'][0]
    assert {field: unit[field] for field in c.NATIVE_UNIT_FIELDS} == raw
    assert unit['start_state'] == unit['end_state'] == material.FINAL_STATE
    assert unit['overlap_pairs'] == unit['state_sources'] == []
    assert compiled['complete_current_interaction'] is True
    assert compiled['complete_beat'] is False
    assert compiled['coverage_pending'] is True
    assert compiled['unbuilt_source_refs'][0] == 'B2.S03'
    assert compiled['creative_quality_passed'] is False
    bad = deepcopy(spec)
    bad['final_state']['paper'] = 'centre'
    with pytest.raises(ValueError, match='preserve physical state'):
        c.compile_contract(raw, script, bad)
    bad = deepcopy(spec)
    bad['final_state']['paper_signed'] = 0
    with pytest.raises(ValueError, match='preserve physical state'):
        c.compile_contract(raw, script, bad)


def test_prompt_only_current_original_dialogue_once_with_tail_and_no_subtitles(current):
    script, spec, raw = current
    candidate = c.pack_first(c.compile_contract(raw, script, spec))
    prompt = c.render_prompt(candidate, script, spec)
    for ref, row in c.catalog(script).items():
        if row['kind'] == 'dialogue':
            assert prompt.count(row['text']) == int(ref in spec['source_refs'])
    assert '上一段生成服务原始尾帧' in prompt
    assert '用户批准' not in prompt
    assert '无字幕' in prompt and '不重复上一段操作' in prompt
    assert candidate['requires_human_approved_service_tail_before_media'] is True


def test_excess_duration_blocks_whole_exchange_without_speed_fit(current, monkeypatch):
    script, spec, raw = current
    compiled = c.compile_contract(raw, script, spec)
    short = c.pack_first(compiled, max_seconds=12)
    assert short['dispatch_ready'] is False
    assert short['semantic_units'] == short['source_refs'] == []
    assert short['fit_scaled'] is False
    monkeypatch.setattr(c, 'NORMAL_SPOKEN_CHARACTERS_PER_SECOND', 1)
    long = c.compile_contract(raw, script, spec)
    candidate = c.pack_first(long)
    assert long['needs_revision'] and long['duration_seconds'] is None
    assert candidate['dispatch_ready'] is False
    with pytest.raises(ValueError, match='unready'):
        c.render_prompt(candidate, script, spec)


def test_explicit_source_identity_and_another_pure_dialogue_interval(current):
    script, spec, raw = current
    altered = deepcopy(script)
    altered['title'] = '另一个明确绑定的版本'
    with pytest.raises(ValueError, match='source identity'):
        c.compile_contract(raw, altered, spec)
    rebound = deepcopy(spec)
    rebound['source_sha256'] = c.digest(altered)
    assert c.compile_contract(raw, altered, rebound)['script_sha256'] == c.digest(altered)
    next_spec = deepcopy(spec)
    next_spec['source_refs'] = ['B2.S03', 'B2.S04']
    next_spec['prior_source_refs'] += spec['source_refs']
    compiled = c.compile_contract(raw, script, next_spec)
    assert compiled['source_refs'] == next_spec['source_refs']
    assert list(c.current_catalog(script, next_spec)) == next_spec['source_refs']


def test_native_types_lengths_extra_fields_and_copied_dialogue_rejected(current):
    script, spec, raw = current
    for field, value in [('camera', {'item': 'wrong'}), ('post_pause_seconds', True),
                         ('post_pause_seconds', 1.6), ('delivery', '字' * 101)]:
        bad = {**raw, field: value}
        with pytest.raises(ValidationError):
            c.compile_contract(bad, script, spec)
    with pytest.raises(ValidationError):
        c.compile_contract({**raw, 'source_refs': spec['source_refs']}, script, spec)
    for ref in ['B2.S01', 'B3.S02']:
        bad = {**raw, 'continuous_performance': c.catalog(script)[ref]['text']}
        with pytest.raises(ValueError, match='dialogue copied'):
            c.compile_contract(bad, script, spec)


def test_render_recompiles_and_rejects_native_or_timing_tampering(current):
    script, spec, raw = current
    compiled = c.compile_contract(raw, script, spec)
    candidate = c.pack_first(compiled)
    for field, value in [('delivery', '手动改写'), ('post_pause_seconds', 0)]:
        bad = deepcopy(candidate)
        bad['semantic_units'][0][field] = value
        with pytest.raises(ValueError, match='altered'):
            c.render_prompt(bad, script, spec)
    bad_compiled = deepcopy(compiled)
    bad_compiled['schedule'][1]['start'] = 0
    with pytest.raises(ValueError, match='altered'):
        c.render_prompt(c.pack_first(bad_compiled), script, spec)
