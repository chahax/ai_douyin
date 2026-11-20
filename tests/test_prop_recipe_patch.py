from copy import deepcopy
import pytest
from test_narrative_props import fixture
from src.content_factory.novel_adaptation import prop_recipe_patch as patch
from src.content_factory.novel_adaptation.contracts import digest


def sample():
    c,p,plan,events=fixture()
    plan['props'] += [{'id':id,'owner':'kitchen'} for id in ('potato','cut_cabbage','cut_potato')]
    plan['recipes']=[{'id':'prep','kind':'transformation','action':'处理菜',
        'inputs':['cabbage','potato'],'outputs':['cut_cabbage','cut_potato'],
        'retained_inputs':[],'source_ids':['CH1-P001']}]
    events['plan_sha256']=digest(plan)
    parts=[{'id':f'prep__part{i+1}','kind':'transformation','action':'处理',
        'inputs':[id],'outputs':['cut_'+id],'retained_inputs':[],'source_ids':['CH1-P001']}
        for i,id in enumerate(('cabbage','potato'))]
    row={'id':'B','events':[{'kind':'transforms','event':{'actor':'a','recipe':r['id'],'destination':'kitchen'},
         'evidence_ids':['B:action:0']} for r in parts],
         'action_order':[{'field':'transforms','index':i} for i in range(2)]}
    identity={'candidate_sha256':digest(c),'plan_sha256':digest(plan),'projection_sha256':digest(events)}
    return c,plan,events,{'recipes':parts,'segment':row},identity


def test_recipe_partition_preserves_inventory_and_inputs():
    c,plan,events,body,identity=sample();before=deepcopy((c,plan,events,body))
    new,bound=patch.apply(c,plan,events,body,['a'],'prep','B',identity)
    assert new['props']==plan['props'] and new['initial_locations']==plan['initial_locations']
    assert [r['id'] for r in new['recipes']]==['prep__part1','prep__part2']
    assert bound['segments'][0]==body['segment']
    assert (c,plan,events,body)==before


@pytest.mark.parametrize('case',['duplicate_input','lost_output','stale','wrong_segment','unknown_source'])
def test_bad_partition_or_scope_rejected(case):
    c,plan,events,body,identity=sample()
    if case=='duplicate_input':body['recipes'][1]['inputs']=['cabbage']
    elif case=='lost_output':body['recipes'][1]['outputs']=['cut_cabbage']
    elif case=='stale':identity['plan_sha256']='old'
    elif case=='wrong_segment':body['segment']['id']='unapproved'
    elif case=='unknown_source':body['recipes'][0]['source_ids']=['invented']
    with pytest.raises(ValueError):patch.apply(c,plan,events,body,['a'],'prep','B',identity)


def test_recipe_with_vessel_constraints_cannot_silently_lose_them():
    c,plan,events,body,identity=sample()
    plan['recipes'][0]['input_containers']={'cabbage':'basin'}
    with pytest.raises(ValueError,match='extra_constraints'):
        patch.context(plan,'prep')
