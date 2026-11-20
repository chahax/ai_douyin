from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.temporal_obligations import validate

RULE=[{'speaker':'a','utterance':'快吃','recipes_after_speech':['serve']}]
SCENE={'beats':[{'audio':[{'kind':'dialogue','speaker':'a','text':'快吃，'}],
                'transforms':[{'recipe':'serve','phase':'after_audio','after_audio_index':0}]}]}


def test_same_beat_speech_then_distribution_is_valid():validate(SCENE,RULE)


def test_distribution_before_speech_rejected_even_with_same_end_state():
    s=deepcopy(SCENE);s['beats'][0]['transforms'][0]['phase']='start'
    with pytest.raises(ValueError,match='precedes'):validate(s,RULE)


def test_later_longer_utterance_does_not_replace_original_anchor():
    s=deepcopy(SCENE);s['beats'][0]['audio'][0]['text']='快吃！都要凉了。'
    with pytest.raises(ValueError,match='anchor'):validate(s,RULE)


def test_prior_beat_action_does_not_pass_on_equal_final_inventory():
    s=deepcopy(SCENE);s['beats'].insert(0,{'audio':[],'transforms':s['beats'][0].pop('transforms')})
    with pytest.raises(ValueError,match='precedes'):validate(s,RULE)
