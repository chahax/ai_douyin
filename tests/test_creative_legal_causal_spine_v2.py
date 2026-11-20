import json
from copy import deepcopy
from jsonschema import Draft202012Validator
from src.content_factory.creative_legal_causal_spine_v2 import build_wire
from test_creative_confirmed_case_graph_context_v1 import inputs
from test_creative_legal_causal_spine_v1 import plan

def test_unadopted_tag_and_conversion_recommendations_not_active():
    (p,f,g,s,d,c),now=inputs();before=deepcopy(d)
    w=build_wire(p,f,g,s,'spine',now=now,direction=d,confirmation=c,diagnosis={'known':'offline'})
    x=json.loads(w['messages'][1]['content'])
    assert d==before and all('story_relevance' not in t for t in x['tag_choices'])
    assert {t['tag_id'] for t in x['tag_choices']}=={t['tag_id'] for t in d['tag_choices']}
    assert 'original_tag_choice_explanations_sha256' in x and 'reason' not in x['account_fit']
    assert 'account_strategy_evidence' not in x and 'publisher_later' not in x['stage_assignment']
    assert x['reference_fulltext']==p['inputs']['reference_fulltext'] and x['supplemental_tag_graph_evidence']['candidate']['support_video_count']==14
    assert 'submit_creative_json' in w['messages'][0]['content'] and w['model']=='MiniMax-M3'
    v=plan(d);validator=Draft202012Validator(w['structured_schema']);assert validator.is_valid(v)
    v['events'][0]['caused_by']='none';assert not validator.is_valid(v)
