from copy import deepcopy
import pytest
from test_narrative_props import fixture
from src.content_factory.novel_adaptation import initial_prop_patch as patch
from src.content_factory.novel_adaptation.contracts import digest


def test_only_initial_owner_changes_event_body_and_old_artifacts_stay_intact():
    c,p,plan,events=fixture();before=deepcopy((c,p,plan,events))
    body={'replacements':[{'path':'/props/0/owner','value':'a'}]}
    new=patch.apply(plan,body,['cabbage'],['a','kitchen'],digest(plan))
    rebound=patch.reuse_events(c,plan,new,events,['cabbage'],['a'])
    assert rebound['segments']==events['segments']
    assert rebound['plan_sha256']==digest(new)
    assert (c,p,plan,events)==before


@pytest.mark.parametrize('case',['stale','outside_scope','changed_recipe','changed_candidate','changed_original_binding'])
def test_unapproved_changes_cannot_reuse_known_events(case):
    c,p,plan,events=fixture();new=deepcopy(plan);new['props'][0]['owner']='a'
    if case=='stale':
        with pytest.raises(ValueError):patch.apply(plan,{'replacements':[]},['cabbage'],['a','kitchen'],'bad')
        return
    if case=='outside_scope':new['props'][1]['owner']='a'
    elif case=='changed_recipe':new['recipes']=[]
    elif case=='changed_candidate':c['scenes'][0]['segments'][0]['action']='另一动作'
    elif case=='changed_original_binding':events['plan_sha256']='bad'
    with pytest.raises(ValueError):patch.reuse_events(c,plan,new,events,['cabbage'],['a'])
