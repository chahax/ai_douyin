from copy import deepcopy
from types import SimpleNamespace
import json
import pytest
from src.content_factory.creative_state_plan_binding import bind_reviewed_state_plan
from src.content_factory.creative_state_plan_v6 import compile_state_plan
from src.content_factory.creative_review_gate import make_packet,template,digest
from src.content_factory.creative_workflow import CreativeWorkflow
from src.content_factory.creative_workflow_contract import CreativeContractError
from tests.test_creative_state_plan_v2 import sample


def fixture(tmp_path):
    plan,script,manifest=sample();shots=compile_state_plan(plan,script,manifest)
    stage='director_state_plan__00';review='writer_check__state_plan_00'
    record={'schema':'creative_reviewed_state_plan/v1','source_stage':stage,'review_stage':review,'plan':plan}
    context={'script':script,'shots':shots,'state_plan':plan,'static_visual_manifest':manifest}
    packet=make_packet(review,{'story_preserved':True,'issues':[],'suggestions':[],'calibration_focus':[]},context)
    decision=template(packet);decision.update(reviewed_full_text=True,summary='Offline fixture review, not production approval')
    for name,value in [('STATE_PLAN',record),(stage,{'output':plan}),('static_visual_manifest',{'output':manifest}),
                       (review+'__review_packet',packet),(review+'__assistant_decision',decision)]:
        (tmp_path/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    state={'segmented_director_binding':{'version':'reviewed_beat_storyboard_v6'},
           'evidence_review_decisions':{review:{'packet_sha256':digest(packet),'decision_sha256':digest(decision)}}}
    workflow=SimpleNamespace(run_dir=tmp_path,state=state,_save=lambda:None)
    return workflow,script,shots,record


def test_lineage_requires_real_review_and_reproduces_shots(tmp_path):
    workflow,script,shots,record=fixture(tmp_path)
    context,sha=bind_reviewed_state_plan(workflow,script,shots)
    assert context['state_plan']==record['plan']
    assert sha==digest(record)==workflow.state['accepted_state_plan_sha256']
    assert bind_reviewed_state_plan(workflow,script,shots)==(context,sha)


def test_free_form_shot_mutation_cannot_escape_plan(tmp_path):
    workflow,script,shots,_=fixture(tmp_path);shots['shots'][0]['start_state']='already seated'
    with pytest.raises(RuntimeError,match='审核上下文'): bind_reviewed_state_plan(workflow,script,shots)


def test_missing_assistant_approval_cannot_be_replaced_by_plan_file(tmp_path):
    workflow,script,shots,_=fixture(tmp_path);workflow.state['evidence_review_decisions']={}
    with pytest.raises(RuntimeError,match='实际助手审核'): bind_reviewed_state_plan(workflow,script,shots)


def test_locked_plan_hash_cannot_change(tmp_path):
    workflow,script,shots,_=fixture(tmp_path);workflow.state['accepted_state_plan_sha256']='different'
    with pytest.raises(RuntimeError,match='发生改变'): bind_reviewed_state_plan(workflow,script,shots)


def test_legacy_does_not_read_new_plan_files(tmp_path):
    workflow=SimpleNamespace(run_dir=tmp_path,state={'segmented_director_binding':{'version':'reviewed_beat_storyboard_v5'}})
    assert bind_reviewed_state_plan(workflow,{}, {})==({},None)


def test_v6_old_revision_entry_points_are_blocked_before_any_call():
    workflow=object.__new__(CreativeWorkflow)
    workflow.state={'segmented_director_binding':{'version':'reviewed_beat_storyboard_v6'}}
    workflow.run=lambda *_:pytest.fail('must block before invoking production')
    with pytest.raises(CreativeContractError,match='状态计划'):workflow.revise_from_assistant(None,None)
    with pytest.raises(CreativeContractError,match='状态计划'):workflow.promote_reviewed_assistant_revision(None)

@pytest.mark.parametrize('has_issue',[False,True])
def test_formal_v6_passes_plan_and_stops_before_free_form_repair(tmp_path,monkeypatch,has_issue):
    import src.content_factory.creative_workflow as module
    import src.content_factory.creative_state_plan_binding as binding
    from test_creative_model_profile import setup
    from test_creative_event_script import as_events
    from test_creative_workflow import FakeClients
    from test_reusable_production import design_for
    from src.content_factory.creative_original_prompt import VERSION as WRITER_VERSION
    a,bundle=setup(tmp_path);bundle.metadata['creative_brief']['duration_seconds']=[20,20]
    clients=FakeClients([a[0],a[1],as_events(a[2]),design_for(a[3])])
    plan={'fixture':'reviewed typed plan'};manifest={'fixture':'static assets'};plan_hash='locked-plan-hash'
    def bind(workflow,script,shots):
        (workflow.run_dir/'STATE_PLAN.json').write_text(json.dumps(plan),encoding='utf-8')
        return {'state_plan':plan,'static_visual_manifest':manifest},plan_hash
    monkeypatch.setattr(binding,'bind_reviewed_state_plan',bind)
    monkeypatch.setattr(module,'generate_reviewed_beats',lambda *_:deepcopy(a[3]))
    monkeypatch.setattr(module.CreativeWorkflow,'_review_script_before_directing',lambda self,script,**kwargs:script)
    seen=[];original=module.CreativeWorkflow._stage
    issue={'owner':'director','location':'SH01','evidence':'fixture state mismatch','impact':'invalid first frame','proposal':'revise typed plan','severity':'major'}
    def stage(self,name,role,payload,validator):
        seen.append(name)
        if name.startswith(('director_production_design','writer_check')):
            assert payload['state_plan']==plan
            assert payload['static_visual_manifest']==manifest
        if name.startswith('writer_check'):
            return {'story_preserved':not has_issue,'issues':[issue] if has_issue else [],'suggestions':[],'calibration_focus':[]}
        return original(self,name,role,payload,validator)
    monkeypatch.setattr(module.CreativeWorkflow,'_stage',stage)
    monkeypatch.setattr(module.CreativeWorkflow,'_verified_review',lambda self,key,review,context:review['issues'])
    workflow=module.CreativeWorkflow(tmp_path/'run',clients=clients,model_profile=module.CREATE_REVIEW_PROFILE,
        writer_prompt_version=WRITER_VERSION,review_policy_version='evidence_review_v6')
    state=workflow.run(bundle)
    assert not any(name.startswith('director_revise') for name in seen)
    if has_issue:
        assert state['status']=='needs_revision'
        assert state['blocked_state_plan_sha256']==plan_hash
        assert not (workflow.run_dir/'MEDIA_HANDOFF.json').exists()
    else:
        assert state['status']=='media_handoff_pending_capability'
        handoff=json.loads((workflow.run_dir/'MEDIA_HANDOFF.json').read_text(encoding='utf-8'))
        assert handoff['state_plan_sha256']==plan_hash
        output=json.loads((workflow.run_dir/'CREATIVE_OUTPUT_MANIFEST.json').read_text(encoding='utf-8'))
        assert 'STATE_PLAN.json' in json.dumps(output)
