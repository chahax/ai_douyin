from src.content_factory.novel_adaptation.review_semantics import RULES,prompt
from src.content_factory.novel_adaptation.narrative_presence import replay
from src.content_factory.novel_adaptation.contracts import digest

def test_prompt_uses_same_rules_as_structured_contract():
    assert all(text in prompt() for text in RULES.values())

def test_visibility_contract_matches_runtime_not_total_presence():
    c={'scenes':[{'id':'S','place':'room','entry_continuity':'二人在屋内','exit_continuity':'仍在',
        'segments':[{'id':'B','visible_people':['a'],'action':'甲说话','camera':'近景',
                     'continuity_obligations':[],'audio':[{'kind':'dialogue','speaker':'a','text':'你好'}]}]}]}
    p={'candidate_sha256':digest(c),'initial_locations':{'a':'room','b':'room'},
       'segments':[{'id':'B','moves':[]}],'uncertainties':[]}
    r=replay(c,p,['a','b'],['room'])
    assert r['trace'][0]['audio_audiences'][0]['present']==['a','b']
    assert r['end_state']['locations']['b']=='room'
