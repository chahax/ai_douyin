from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.narrative_patch import apply,proposal_schema
from src.content_factory.novel_adaptation.contracts import digest,schema_issues

C={'world':'old','scenes':[{'action':'before','audio':['keep'],'seconds':8}]}
def proposal(path='/scenes/0/action',value='after'):
    return {'candidate_sha256':digest(C),'replacements':[{'path':path,'value':value}]}

def test_only_selected_leaf_changes_original_preserved():
    original=deepcopy(C);result=apply(C,proposal(),['/scenes/0/action'],digest(C))
    assert result['scenes'][0]=={'action':'after','audio':['keep'],'seconds':8}
    assert result['world']=='old' and C==original

def test_schema_and_apply_share_same_path_and_type_contract():
    schema=proposal_schema(C,['/scenes/0/action'])
    assert not schema_issues(proposal(),schema,'patch')
    assert schema_issues(proposal('/world','bad'),schema,'patch')
    assert schema_issues(proposal(value=['bad']),schema,'patch')

def test_span_only_scope_requires_no_field_edits():
    p={'candidate_sha256':digest(C),'replacements':[]};s=proposal_schema(C,[])
    assert not schema_issues(p,s,'patch')
    assert apply(C,p,[],digest(C))==C
    assert schema_issues(proposal(),s,'patch')

@pytest.mark.parametrize('case',['stale','unauthorized','duplicate','overlap','bad_index','type'])
def test_reject_scope_escape(case):
    p=proposal();scope=['/scenes/0/action'];sha=digest(C)
    if case=='stale':sha='old'
    elif case=='unauthorized':p=proposal('/world','replace')
    elif case=='duplicate':p['replacements']*=2
    elif case=='overlap':scope=['/scenes','/scenes/0/action']
    elif case=='bad_index':p=proposal('/scenes/00/action');scope=['/scenes/00/action']
    elif case=='type':p=proposal(value=['rewrite'])
    with pytest.raises(ValueError):apply(C,p,scope,sha)
