import json
from copy import deepcopy
import pytest
from src.content_factory.creative_legal_causal_spine_v1 import build_wire,validate_spine
from test_creative_confirmed_case_graph_context_v1 import inputs

def plan(d):
    return {'title':'模拟计划','confirmed_conflict':'模拟当前冲突','events':[{'id':'e'+str(i),'caused_by':'' if i==0 else 'e'+str(i-1),
        'actor':d['characters'][i%2]['name'],'observable_event':'模拟发生事件','new_information':'模拟信息','other_character_response':'模拟反应'} for i in range(4)],
        'visible_consequence':'模拟可见后果','audience_release':'模拟释放','case_outcome_unresolved':True}

def test_spine_and_full_expansion_duties_bound_without_failed_dialogue():
    (p,f,g,s,d,c),now=inputs();spine=plan(d);assert validate_spine(spine,d)['not_final_script']
    w=build_wire(p,f,g,s,'spine',now=now,direction=d,confirmation=c,diagnosis={'known':'test'})
    x=json.loads(w['messages'][1]['content']);graph=x['supplemental_tag_graph_evidence']
    assert 'supporting_documents' not in graph and graph['support_document_ids']
    assert graph['candidate']['support_video_count']==14 and len(json.dumps(graph,ensure_ascii=False))<7500
    assert x['reference_fulltext']==p['inputs']['reference_fulltext'] and w['model']=='MiniMax-M3'
    w=build_wire(p,f,g,s,'draft',now=now,direction=d,confirmation=c,spine=spine)
    x=json.loads(w['messages'][1]['content'])
    assert x['current_model_authored_causal_spine']==spine and 'complete_content_revision' not in x
    assert x['current_stage_contract']['source_spine_sha256']==w['input_provenance']['model_authored_spine_sha256']

@pytest.mark.parametrize('bad',['future','duplicate','third_actor','case_won','missing_spine'])
def test_causal_source_gates(bad):
    (p,f,g,s,d,c),now=inputs();spine=plan(d)
    if bad=='future':spine['events'][1]['caused_by']='e3'
    elif bad=='duplicate':spine['events'][2]['id']='e1'
    elif bad=='third_actor':spine['events'][0]['actor']='第三人'
    elif bad=='case_won':spine['case_outcome_unresolved']=False
    if bad=='missing_spine':
        with pytest.raises(ValueError):build_wire(p,f,g,s,'draft',now=now,direction=d,confirmation=c)
    else:
        with pytest.raises(Exception):validate_spine(spine,d)
