"""An isolated legacy task remains replayable after an opt-in new-version task."""
import json
import hashlib
from src.content_factory.creative_workflow import CreativeWorkflow, CREATE_REVIEW_PROFILE
from src.content_factory.creative_state_plan_v6 import validate_state_plan
from tests.test_creative_action_plan_v1 import sample as legacy_sample
from tests.test_creative_action_plan_v2 import sample as governed_sample
from tests.test_creative_workflow import FakeClients
from tests.test_creative_governed_protocol import workflow


def test_isolated_legacy_restore_after_governed_run(tmp_path):
    legacy_root=tmp_path/'legacy';legacy_root.mkdir()
    plan,script,manifest=legacy_sample();clients=FakeClients([plan])
    original=CreativeWorkflow(legacy_root,clients=clients,model_profile=CREATE_REVIEW_PROFILE,
        writer_prompt_version='original_events_v3',review_policy_version='evidence_review_v6',
        max_calls=5,max_total_tokens=250000)
    original.state={'model_profile':CREATE_REVIEW_PROFILE,'writer_prompt_version':'original_events_v3',
        'review_policy_version':'evidence_review_v6','production_protocol':'legacy',
        'calls_started':0,'stages':[],'contract_repairs_used':0,'format_repairs_used':0,
        'budget_policy_version':'v4_20260923','revision_rounds':0}
    payload={'state_plan_version':plan['schema'],'script':script,'static_visual_manifest':manifest,'plan_thinking_mode':'disabled'}
    validator=lambda v:validate_state_plan(v,script,manifest)
    original._stage('director_state_plan__00','director',payload,validator)
    stage=legacy_root/'director_state_plan__00.json';before=hashlib.sha256(stage.read_bytes()).hexdigest()
    newroot=tmp_path/'governed';newroot.mkdir();p,s,m=governed_sample();new,newclients=workflow(newroot,[p])
    new._stage('director_state_plan__00','director',{'state_plan_version':p['schema'],'script':s,
        'static_visual_manifest':m,'plan_thinking_mode':'disabled'},lambda v:validate_state_plan(v,s,m))
    no_calls=FakeClients([]);restored=CreativeWorkflow(legacy_root,clients=no_calls,max_calls=5,max_total_tokens=250000)
    restored.state=json.loads((legacy_root/'state.json').read_text(encoding='utf-8'))
    assert restored.production_protocol=='legacy'
    assert restored._stage('director_state_plan__00','director',payload,validator)==plan
    assert not no_calls.calls and len(newclients.calls)==1
    assert hashlib.sha256(stage.read_bytes()).hexdigest()==before
