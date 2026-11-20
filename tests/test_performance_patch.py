from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.performance_patch import inspect


def candidate(text):
    return {'scenes':[{'segments':[{'visual_additions':[text],
        'audio':[{'text':'不要卖我们。'}], 'continuity_obligations':['不再从盆里取肉']}]}]}


@pytest.mark.parametrize('text',['孩子吃肉（不新添盛汤、盛菜动作）。','本段只生成吃饭。',
    '按审核要求保留肉片。','碗里有肉，禁止生成汤。'])
def test_reports_instructions_without_silently_stripping(text):
    c=candidate(text);before=deepcopy(c)
    r=inspect(c,['/scenes/0/segments/0/visual_additions/0'])
    assert r['issues'] and r['issues'][0]['matched_text'] in text
    assert c==before and r['semantic_acceptance'] is False


@pytest.mark.parametrize('text',['孩子不敢吃，握紧筷子。','苏墨摇头，没有夹肉。',
    '孩子埋头吃肉（腮帮鼓动）。'])
def test_actor_negation_and_performance_parentheses_are_not_process_instructions(text):
    assert not inspect(candidate(text),['/scenes/0/segments/0/visual_additions/0'])['issues']


def test_scope_does_not_treat_dialogue_or_continuity_constraints_as_visual_output():
    c=candidate('本段只生成吃饭。')
    assert not inspect(c,['/scenes/0/segments/0/audio/0/text',
        '/scenes/0/segments/0/continuity_obligations/0'])['issues']


def test_replacing_parent_segment_array_still_checks_nested_performance():
    c=candidate('按审核要求保留肉片。');before=deepcopy(c)
    result=inspect(c,['/scenes/0/segments'])
    assert result['issues'][0]['path']=='/scenes/0/segments/0/visual_additions/0'
    assert c==before
