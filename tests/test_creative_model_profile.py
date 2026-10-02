from copy import deepcopy
import json
import pytest
from test_creative_workflow import FakeClients, _answers
from test_reusable_production import design_for
from src.content_factory.creative_workflow import CreativeWorkflow, CREATE_REVIEW_PROFILE, LEGACY_MODEL_PROFILE
from src.content_factory.creative_workflow_inputs import load_materials
from src.content_factory.reusable_production import read, write


def setup(tmp_path):
    answers=_answers()
    answers[0]['candidates'][0].update(start_quote='',end_quote='')
    brief=tmp_path/'brief.json'
    write(brief,{'schema':'creative_brief/v1','theme':'和解'})
    bundle=load_materials(source_driver='original',title='测试',brief_path=brief)
    return answers,bundle


def test_minimax_creates_every_artifact_deepseek_reviews_complete_package(tmp_path):
    a,bundle=setup(tmp_path)
    design=design_for(a[3])
    clients=FakeClients([*a[:4],design,a[4]])
    run=tmp_path/'run'
    wf=CreativeWorkflow(run,clients=clients,model_profile=CREATE_REVIEW_PROFILE)
    state=wf.run(bundle)
    assert state['model_profile']==CREATE_REVIEW_PROFILE
    assert [r for r,_ in clients.calls]==['writer']*5+['director']
    receipt=read(run/'director_shots.json')
    assert receipt['response_metadata']['logical_role']=='director'
    assert receipt['response_metadata']['transport_config_role']=='writer'
    assert receipt['context_budget']['model']=='MiniMax-M3'
    assert 'max_completion_tokens' in receipt['request']['parameters']
    check=read(run/'writer_check__00.json')
    assert check['context_budget']['provider']=='deepseek'
    assert check['response_metadata']['transport_config_role']=='director'
    assert 'max_tokens' in check['request']['parameters']
    assert '独立审查员' in check['request']['messages'][0]['content']
    assert '不是独立第三审核模型' not in check['request']['messages'][0]['content']
    payload=json.loads(check['request']['messages'][-1]['content'])
    assert payload['production_design']==design
    assert read(run/'PRODUCTION_DESIGN.json')==design
    assert state['assistant_review_required'] is True
    restored=CreativeWorkflow(run,clients=FakeClients([]))
    assert restored.model_profile==CREATE_REVIEW_PROFILE
    assert restored.run(bundle)['calls_started']==6
    with pytest.raises(RuntimeError,match='模型分工'):
        CreativeWorkflow(run,model_profile=LEGACY_MODEL_PROFILE)


def test_deepseek_issues_return_to_minimax_then_are_rechecked(tmp_path):
    a,bundle=setup(tmp_path)
    design=design_for(a[3])
    issue={'story_preserved':True,'issues':[{'owner':'director','location':'SH01',
        'evidence':'首帧提前完成本镜动作','impact':'画面动作会重复','proposal':'根据初态修正首帧',
        'severity':'major'}],'calibration_focus':[]}
    clients=FakeClients([*a[:4],design,issue,a[3],design,a[4]])
    run=tmp_path/'run'
    state=CreativeWorkflow(run,clients=clients,model_profile=CREATE_REVIEW_PROFILE).run(bundle)
    assert state['status']=='media_handoff_pending_capability'
    assert [r for r,_ in clients.calls]==['writer']*5+['director','writer','writer','director']
    revision=read(run/'director_revise__01.json')
    assert revision['response_metadata']['transport_config_role']=='writer'
    assert json.loads(revision['request']['messages'][-1]['content'])['issues']==issue['issues']
    design_call=read(run/'director_production_design__review_01.json')
    assert json.loads(design_call['request']['messages'][-1]['content'])['issues']==issue['issues']
    assert state['revision_rounds']==1


def test_review_failure_cannot_be_promoted_to_handoff(tmp_path):
    a,bundle=setup(tmp_path)
    issue={'story_preserved':True,'issues':[{'owner':'director','location':'SH01',
        'evidence':'资产服装不匹配','impact':'人物换装','proposal':'修正资产选择','severity':'major'}],
        'calibration_focus':[]}
    clients=FakeClients([*a[:4],design_for(a[3]),issue])
    run=tmp_path/'run'
    state=CreativeWorkflow(run,clients=clients,model_profile=CREATE_REVIEW_PROFILE,max_revisions=0).run(bundle)
    assert state['status']=='needs_revision'
    assert not (run/'MEDIA_HANDOFF.json').exists()
    assert clients.calls[-1][0]=='director'


def test_old_task_without_profile_cannot_silently_switch(tmp_path):
    write(tmp_path/'state.json',{'schema':'creative_workflow_state/v1'})
    assert CreativeWorkflow(tmp_path).model_profile==LEGACY_MODEL_PROFILE
    with pytest.raises(RuntimeError,match='模型分工'):
        CreativeWorkflow(tmp_path,model_profile=CREATE_REVIEW_PROFILE)


def test_new_profile_reserves_asset_rebuild_before_starting_revision(tmp_path):
    a,bundle=setup(tmp_path)
    issue={'story_preserved':True,'issues':[{'owner':'director','location':'SH01',
        'evidence':'首帧提前完成动作','impact':'动作重复','proposal':'修正首帧','severity':'major'}],
        'calibration_focus':[]}
    clients=FakeClients([*a[:4],design_for(a[3]),issue])
    wf=CreativeWorkflow(tmp_path/'run',clients=clients,model_profile=CREATE_REVIEW_PROFILE,max_calls=8)
    with pytest.raises(RuntimeError,match='预算不足'):
        wf.run(bundle)
    assert len(clients.calls)==6
    assert wf.state['revision_rounds']==0


def test_reviewer_format_repair_stays_on_deepseek(tmp_path):
    a,bundle=setup(tmp_path)
    invalid=deepcopy(a[4]);invalid['story_preserved']='true'
    clients=FakeClients([*a[:4],design_for(a[3]),invalid,a[4]])
    state=CreativeWorkflow(tmp_path/'run',clients=clients,model_profile=CREATE_REVIEW_PROFILE).run(bundle)
    assert state['status']=='media_handoff_pending_capability'
    assert [role for role,_ in clients.calls][-2:]==['director','director']
    assert state['contract_repairs_used']==1
