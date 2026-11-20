from copy import deepcopy
from src.content_factory.novel_adaptation.narrative_props import audit_event_structure


def test_duplicate_recipe_across_segments_reports_all_uses_not_first_failure():
    presence={'segments':[{'id':'A','moves':[]},{'id':'B','moves':[]}]}
    rows=[{'id':id,'events':[{'kind':'transforms','event':{'recipe':'prep','actor':actor}}],
           'action_order':[{'field':'transforms','index':0}]} for id,actor in [('A','one'),('B','two')]]
    projection={'segments':rows};before=deepcopy(projection)
    report=audit_event_structure(presence,projection)
    assert report['issues'][0]['code']=='recipe_applied_multiple_times'
    assert [r['segment_id'] for r in report['issues'][0]['uses']]==['A','B']
    assert projection==before
    rows[1]['events'][0]['event']['recipe']='prep_second'
    assert audit_event_structure(presence,projection)['issues']==[]


def test_order_requires_each_movement_and_prop_action_once():
    presence={'segments':[{'id':'A','moves':[{'person':'one'}]}]}
    projection={'segments':[{'id':'A','events':[],'action_order':[]}]}
    assert audit_event_structure(presence,projection)['issues'][0]['code']=='action_order_coverage'
    projection['segments'][0]['action_order']=[{'field':'moves','index':0}]
    assert audit_event_structure(presence,projection)['issues']==[]
