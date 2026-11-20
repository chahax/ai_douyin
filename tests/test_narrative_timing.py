from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.narrative_timing import schedule, repair_feedback

def candidate():
    return {'scenes':[{'id':'S','segments':[{'id':'B','seconds':1,'audio':[{'text':'一二三四。'},{'text':'五六七八！'}]}]}]}

def test_schedule_preserves_text_and_expands_without_truncation():
    c=candidate();original=deepcopy(c);r=schedule(c)
    assert c==original and r['total_seconds']==2.3
    assert r['segments'][0]['audio_estimate'][1]['start']==1.25
    assert r['segments'][0]['audio_estimate'][1]['end']==2.25

def test_budget_overrun_reported_not_squeezed():
    r=schedule(candidate(),maximum_seconds=2)
    assert not r['within_brief'] and r['total_seconds']==2.3

def test_visual_time_not_added_again():
    c=candidate();c['scenes'][0]['segments'][0]['seconds']=6
    assert schedule(c)['total_seconds']==6


def test_repair_feedback_locates_speech_without_granting_edit_scope():
    c=candidate();old=deepcopy(c);r=repair_feedback(c,2)
    assert r['minimum_total_reduction_seconds']==.3
    assert r['speech_pressure'][0]['audio_paths']==['/scenes/0/segments/0/audio/0/text','/scenes/0/segments/0/audio/1/text']
    assert r['speech_pressure'][0]['speech_excess_seconds']==1.3
    assert c==old and r['semantic_acceptance'] is False


def test_visual_overrun_is_not_misdiagnosed_as_long_speech():
    c=candidate();c['scenes'][0]['segments'][0]['seconds']=10
    r=repair_feedback(c,5)
    assert r['minimum_total_reduction_seconds']==5 and r['speech_pressure']==[]

@pytest.mark.parametrize('rate',[0,-1,float('nan'),float('inf'),True])
def test_invalid_policy(rate):
    with pytest.raises(ValueError):schedule(candidate(),characters_per_second=rate)
