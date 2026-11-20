from copy import deepcopy
from src.content_factory.novel_adaptation.narrative_render import render


def test_all_candidate_prose_included_without_mutating_source():
    b={'id':'B1','seconds':3,'visible_people':['a'],'action':'递信','expression':'迟疑',
       'camera':'近景','audio':[{'kind':'inner','speaker':'a','text':'要不要说'}],
       'source_ids':['CH2-P001'],'visual_additions':['纸边折痕'],'continuity_obligations':['信由甲持有']}
    value={'title':'候选','world_and_relationships':'父女','visual_direction':'暖色',
           'scenes':[{'id':'S1','place':'room','entry_continuity':'入室','segments':[b],
                      'exit_continuity':'仍在室内'}],
           'condensation_notes':[{'source_ids':['CH2-P003'],'treatment':'省略走路'}]}
    original=deepcopy(value);out=render(value)
    def strings(v):
        if isinstance(v,str):yield v
        elif isinstance(v,dict):
            for x in v.values():yield from strings(x)
        elif isinstance(v,list):
            for x in v:yield from strings(x)
    assert all(text in out for text in strings(value))
    assert '0–3秒' in out and '未验收' in out
    assert value==original
