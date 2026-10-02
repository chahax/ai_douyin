import json
from copy import deepcopy
import pytest
from src.content_factory.creative_workflow import CreativeWorkflow, CREATE_REVIEW_PROFILE
from src.content_factory.creative_plan_patch import plan_digest, build_patch_request
from src.content_factory.creative_state_plan_v6 import validate_state_plan
from src.content_factory.creative_workflow_contract import CreativeContractError
from tests.test_creative_action_plan_v1 import sample
from tests.test_creative_workflow import FakeClients


def setup(tmp_path, answers):
    clients=FakeClients(answers)
    w=CreativeWorkflow(tmp_path,clients=clients,model_profile=CREATE_REVIEW_PROFILE,
        writer_prompt_version='original_events_v3',review_policy_version='evidence_review_v6',max_calls=5,max_contract_repairs=2,max_total_tokens=250000)
    w.state={'calls_started':0,'max_calls':5,'max_total_tokens':250000,'budget_policy_version':'v4_20260923',
        'max_contract_repairs':2,'contract_repairs_used':0,'format_repairs_used':0,'revision_rounds':0,'stages':[]}
    return w,clients


def fixture():
    p,s,m=sample()
    payload={'state_plan_version':p['schema'],'script':s,'static_visual_manifest':m,'plan_thinking_mode':'disabled'}
    return p,payload,s,m


def test_contract_repair_preserves_raw_patch_and_validates_merged_plan(tmp_path):
    plan,payload,script,manifest=fixture();plan['beats'][0]['groups'][0]['duration_seconds']=-1
    patch={'source_sha256':plan_digest(plan),'patches':[{'path':'beats.0.groups.0.duration_seconds','value':1}]}
    w,clients=setup(tmp_path,[patch]);seen=[]
    def validate(value):
        seen.append(deepcopy(value));validate_state_plan(value,script,manifest)
    result=w._validate_or_repair('director_state_plan__00','director',payload,plan,validate)
    assert result['beats'][0]['groups'][0]['duration_seconds']==1
    assert seen[0]==plan and seen[-1]==result
    receipt=json.loads((tmp_path/'director_state_plan__00__contract_repair.json').read_text(encoding='utf-8'))
    assert json.loads(receipt['response_text'])==patch
    merge=json.loads(next(tmp_path.glob('*__action_patch_merge.json')).read_text(encoding='utf-8'))
    assert merge['model_patch']==patch and merge['output']==result and merge['semantic_approval'] is False
    assert clients.call_kwargs[0]['structured_schema']['properties']['source_sha256']['enum']==[plan_digest(plan)]


def test_semantic_stage_merges_fresh_patch_and_cached_replay(tmp_path):
    plan,payload,script,manifest=fixture();payload['plan_patch_base']=plan;payload['issues']=[{'reason':'give action more time'}]
    patch={'source_sha256':plan_digest(plan),'patches':[{'path':'beats.0.groups.0.duration_seconds','value':2}]}
    w,clients=setup(tmp_path,[patch]);seen=[]
    def validate(value):
        seen.append(deepcopy(value));validate_state_plan(value,script,manifest)
    result=w._stage('director_state_plan__01','director',payload,validate)
    assert result['beats'][0]['groups'][0]['duration_seconds']==2
    assert seen[-1]==result
    receipt=json.loads((tmp_path/'director_state_plan__01.json').read_text(encoding='utf-8'))
    assert json.loads(receipt['response_text'])==patch
    assert receipt['output']==result
    assert (tmp_path/'director_state_plan__01__action_patch_merge.json').exists()
    cached=w._stage('director_state_plan__01','director',payload,validate)
    assert cached==result and len(clients.calls)==1


def test_duplicate_plan_context_removed_only_when_equal():
    plan,payload,_,_=fixture();payload.update(plan_patch_base=deepcopy(plan),previous_draft=deepcopy(plan))
    _,request=build_patch_request({},payload,'x',plan)
    assert 'plan_patch_base' not in request['context'] and 'previous_draft' not in request['context']
    payload['previous_draft']['beats'][0]['purpose']='different'
    _,request=build_patch_request({},payload,'x',plan)
    assert request['context']['previous_draft']==payload['previous_draft']
    assert 'plan_patch_base' in payload

