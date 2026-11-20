import json
from contextlib import nullcontext
from pathlib import Path

import pytest

from scripts import run_isolated_nodes_trial as m
from src.content_factory.novel_adaptation import audio_first as a, contracts as c, isolated_nodes as n
from tests.test_audio_first import sample, layout


PRIOR = Path('data/corpus_production_trials/20261030_isolated_nodes_review')
AUDIO = Path('data/corpus_production_trials/20261030_isolated_nodes')


def test_grouped_audio_is_lossless_but_not_semantic_acceptance():
    packet, raw = sample()
    bank = a.build_bank(raw, packet)
    grouped = layout().replace('声音[A001]\n声音[A002]\n声音[A003]', '声音[A001][A002][A003]')
    result = a.render_layout(grouped, bank, packet)
    assert result['rendered'] == a.render_layout(layout(), bank, packet)['rendered']
    assert result['format_passed'] and not result['semantic_acceptance']
    for ref in ('声音[A002][A001][A003]', '声音[A001][A001][A003]', '声音[A001][A002][A999]', '声音[A001][A002]附加对白'):
        bad = a.render_layout(grouped.replace('声音[A001][A002][A003]', ref), bank, packet)
        assert not bad['format_passed'] and bad['rendered'] is None


def test_tilde_ranges_still_reject_cross_chapter_and_missing_source():
    packet, _ = sample()
    for value in ('CH1-P001~CH1-P003', 'CH1-P001～P003'):
        assert a.expand_target_range(value, packet) == ['CH1-P001', 'CH1-P002', 'CH1-P003']
    for value in ('CH1-P001~CH2-P003', 'CH1-P003~P001', 'CH1-P001~P004'):
        assert a.expand_target_range(value, packet) is None


def test_old_output_is_not_rewritten_or_silently_accepted():
    text = (AUDIO/'layout.txt').read_text('utf-8')
    result = a.render_layout(text, m.read(AUDIO/'AUDIO_BANK.json'), m.read(AUDIO/'INPUT.json'))
    assert result['layout_sha256'] == c.digest(text)
    assert not result['format_passed']  # Extra 地点补充 line is still outside the contract.
    assert not any(x['code'] == 'audio_sequence_mismatch' for x in result['issues'])
    assert '商场外便利店' in text and not result['semantic_acceptance']


def test_picture_trial_freezes_audio_and_calls_only_picture_review(tmp_path, monkeypatch):
    run = tmp_path/'trial'
    m.prepare_picture(run, PRIOR, AUDIO, '用户授权修改画面后测一轮')
    before = m.read(PRIOR/'STATE.json')
    assert m.read(run/'PLAN.json')['max_calls'] == before['calls_started'] + 2
    assert m.read(run/'AUDIO_BANK.json') == m.read(AUDIO/'AUDIO_BANK.json')
    assert m.read(run/'STATE.json')['retained_unknowns'] == before['retained_unknowns']
    calls = []

    class Fake:
        def __init__(self, run, plan, state, client): self.run, self.state = run, state
        def save(self): (self.run/'STATE.json').write_text(json.dumps(self.state), encoding='utf-8')
        def call(self, name, role, prompt, payload, schema):
            calls.append((name, prompt, payload)); self.state['calls_started'] += 1
            if name == 'picture':
                refs = '声音' + ''.join('['+i['audio_id']+']' for i in payload['audio_items'])
                return {'text': '场次：1\n时间：夜里\n地点：屋内\n人物：孩子们\n画面[CH20-P001~P002]：孩子点头。\n'+refs+'\n原段：CH20-P001~P002', 'gaps': []}
            return {'text': '只是调度测试，正文覆盖不足，语义未通过。'}

    monkeypatch.setattr(m, 'DirectLedger', Fake); monkeypatch.setattr(m, 'TextLedger', Fake)
    monkeypatch.setattr(m, 'NativeClient', lambda *args: None); monkeypatch.setattr(m, 'run_lock', lambda *args: nullcontext())
    m.execute(run)
    assert [x[0] for x in calls] == ['picture', 'comparison']
    assert calls[0][1] == n.PICTURE and calls[1][1] == n.REVIEW
    assert calls[0][2]['audio_items'][0]['speaker'] == '叶东'  # Known old error must not be hand-fixed.
    assert calls[1][2]['gaps'] == []
    assert m.read(run/'STATE.json')['calls_started'] == before['calls_started'] + 2
    assert m.read(PRIOR/'STATE.json') == before
    assert not m.read(run/'REVIEW_BINDING.json')['semantic_acceptance']
    with pytest.raises(ValueError, match='not_fresh'): m.execute(run)


def test_changed_audio_stops_before_any_new_call(tmp_path, monkeypatch):
    run = tmp_path/'trial'; m.prepare_picture(run, PRIOR, AUDIO, '用户授权修改画面后测一轮')
    bank = m.read(run/'AUDIO_BANK.json'); bank['items'][0]['speaker'] = ''
    (run/'AUDIO_BANK.json').write_text(json.dumps(bank), encoding='utf-8')
    monkeypatch.setattr(m, 'NativeClient', lambda *args: None)
    monkeypatch.setattr(m.DirectLedger, 'call', lambda *args: pytest.fail('Must stop before model call'))
    m.execute(run)
    assert m.read(run/'ERROR.json')['message'] == 'reused_audio_changed'
    assert m.read(run/'STATE.json')['calls_started'] == 323


def test_missing_authorization_does_not_prepare(tmp_path):
    with pytest.raises(ValueError, match='authorization_required'):
        m.prepare_picture(tmp_path/'trial', PRIOR, AUDIO, '')
    assert not (tmp_path/'trial').exists()


def test_schema_keeps_visual_only_gap_claim_for_review_instead_of_regex_deleting_it():
    packet, _ = sample()
    raw = {'text': '场景候选', 'gaps': [{'source_id': 'CH1-P001', 'missing_content': '抬头没有声音'}]}
    assert n.validate_picture(raw, packet) == raw
    # Structural validation cannot decide whether a proposed audio gap is semantically real.
    payload = n.review_payload(packet, a.build_bank(sample()[1], packet), '候选', raw['gaps'], {'issues': []})
    assert payload['gaps'] == raw['gaps']
