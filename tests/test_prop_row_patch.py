from copy import deepcopy
import pytest
from test_narrative_props import fixture
from src.content_factory.novel_adaptation import prop_row_patch as patch
from src.content_factory.novel_adaptation.contracts import digest


def sample():
    c,p,plan,events=fixture()
    second=deepcopy(c['scenes'][0]['segments'][0]);second['id']='C'
    c['scenes'][0]['segments'].append(second);events['candidate_sha256']=digest(c)
    events['segments'].append({'id':'C','events':[],'action_order':[]})
    identity={'candidate_sha256':digest(c),'plan_sha256':digest(plan),'projection_sha256':digest(events)}
    return c,plan,events,identity


def test_only_selected_row_changes_and_prior_uncertainties_preserved():
    c,plan,events,identity=sample();old=deepcopy((c,plan,events))
    row=deepcopy(events['segments'][0]);row['events'][0]['event']['destination']='kitchen'
    result=patch.apply(c,plan,events,{'segments':[row]},['a'],['B'],identity)
    assert result['segments'][1]==events['segments'][1]
    assert result['uncertainties']==events['uncertainties']
    assert (c,plan,events)==old


@pytest.mark.parametrize('case',['outside','duplicate','stale','missing'])
def test_scope_and_binding_rejections(case):
    c,plan,events,identity=sample();body={'segments':[deepcopy(events['segments'][0])]}
    if case=='outside':body['segments'][0]['id']='C'
    elif case=='duplicate':body['segments']*=2
    elif case=='stale':identity['projection_sha256']='old'
    elif case=='missing':body['segments']=[]
    with pytest.raises(ValueError):patch.apply(c,plan,events,body,['a'],['B'],identity)


def test_new_uncertainty_can_be_reported_without_erasing_existing_issue():
    c,plan,events,identity=sample();events['uncertainties']=['旧问题仍未决']
    identity['projection_sha256']=digest(events)
    body={'segments':[deepcopy(events['segments'][0])],'new_uncertainties':['新发现原稿矛盾','旧问题仍未决']}
    result=patch.apply(c,plan,events,body,['a'],['B'],identity)
    assert result['uncertainties']==['旧问题仍未决','新发现原稿矛盾']
