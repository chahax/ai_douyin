import hashlib
import json

import pytest

from src.content_factory.visual_source_voice_v13 import source_direction


def case():
    text = '老六（画外，童声，带着点怯）：「二哥，今天没偷到钱，怎么办呀？」'
    spoken = '二哥，今天没偷到钱，怎么办呀？'
    unit = dict(start=995, end=995+len(text), text=text,
                sha256=hashlib.sha256(text.encode()).hexdigest())
    start = 995 + text.index(spoken)
    return dict(source_evidence=[unit]), dict(text=spoken, source_start=start, source_end=start+len(spoken))


def test_exact_source_child_voice_annotation_is_kept():
    shot, audio = case()
    assert source_direction(shot, audio) == '老六（画外，童声，带着点怯）'


def test_legacy_audio_never_gets_invented_age_or_voice():
    assert source_direction({}, dict(text='二哥')) is None


def test_no_source_unit_does_not_invent_direction():
    _, audio = case()
    assert source_direction({}, audio) is None


def test_changed_source_prefix_fails_before_it_reaches_video():
    shot, audio = case()
    shot['source_evidence'][0]['text'] = shot['source_evidence'][0]['text'].replace('童声', '低沉男声')
    with pytest.raises(ValueError, match='evidence_changed'):
        source_direction(shot, audio)


def test_audio_must_match_exact_source_range():
    shot, audio = case()
    audio['text'] = '新增对白'
    with pytest.raises(ValueError, match='text_mismatch'):
        source_direction(shot, audio)


def test_overlapping_units_cannot_choose_an_attribution():
    shot, audio = case()
    shot['source_evidence'].append(dict(shot['source_evidence'][0]))
    with pytest.raises(ValueError, match='ambiguous'):
        source_direction(shot, audio)


def test_narrative_before_unquoted_audio_is_not_a_voice_direction():
    text = '他走到门口。天已经黑了。'
    audio = dict(text='天已经黑了。', source_start=6, source_end=len(text))
    unit = dict(start=0, end=len(text), text=text, sha256=hashlib.sha256(text.encode()).hexdigest())
    assert source_direction(dict(source_evidence=[unit]), audio) is None


def test_an_action_before_a_quote_is_not_promoted_to_voice_casting():
    text = '老六听了立刻跪倒在地：「别打哥哥。」'
    spoken = '别打哥哥。'
    a = text.index(spoken)
    unit = dict(start=0, end=len(text), text=text, sha256=hashlib.sha256(text.encode()).hexdigest())
    assert source_direction(dict(source_evidence=[unit]),
                            dict(text=spoken, source_start=a, source_end=a+len(spoken))) is None


def test_h3_keeps_exact_voice_direction_beside_original_text_and_offscreen_mode():
    from src.content_factory.visual_h3_handoff_v3 import prompt_for
    shot, audio = case()
    audio.update(speaker='ye_xijue', mode='offscreen_dialogue', source_speaker='叶西决')
    shot.update(visual_prompt='苏墨闭眼躺着。', visible_cast=['su_mo'], audio=[audio])
    original = dict(audio)
    prompt = prompt_for(shot, dict(requested_seconds=12, native_seconds=12))
    payload = json.loads(prompt.split('\n', 1)[1])
    assert payload['audio'][0]['source_direction'] == '老六（画外，童声，带着点怯）'
    assert payload['audio'][0]['text'] == original['text']
    assert payload['audio'][0]['mode'] == 'offscreen_dialogue'
    assert payload['visible_cast'] == ['su_mo']
    assert audio == original
