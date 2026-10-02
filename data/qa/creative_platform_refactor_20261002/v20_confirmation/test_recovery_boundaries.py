from pathlib import Path
import json,hashlib
from copy import deepcopy
import pytest
from test_creative_workflow import FakeClients,_answers,_bundle
from src.content_factory.creative_workflow import CreativeWorkflow,CREATE_REVIEW_PROFILE
from src.content_factory.creative_stage_debug import CreativeStageCommandService

def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def write(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def prepared(tmp_path,stop='director_brief'):
 run=tmp_path/'run';bundle=_bundle(tmp_path);clients=FakeClients(_answers())
 state=CreativeWorkflow(run,clients=clients,stop_after_stage=stop).run(bundle)
 assert state['status']=='debug_breakpoint'
 feedback=CreativeStageCommandService(run).feedback('director_brief','FIXTURE improve visual strategy',disposition='must_fix')
 return run,bundle,feedback

def resume(run,bundle,clients,stop):
 try:return CreativeWorkflow(run,clients=clients,stop_after_stage=stop).run(bundle)
 except Exception:
  return read(run/'state.json')

@pytest.mark.parametrize('damage',['prompt_hash','input_hash','output_hash','uncertain_status','invalidated','missing_receipt'])
def test_unverified_upstream_cannot_skip_feedback_target(tmp_path,damage):
 run,bundle,feedback=prepared(tmp_path);cached=run/'writer_analysis.json'
 if damage=='missing_receipt':cached.unlink()
 elif damage=='invalidated':
  state=read(run/'state.json');state.setdefault('debug_stage_validity',{})['writer_analysis']='invalidated';write(run/'state.json',state)
 else:
  row=read(cached)
  key={'prompt_hash':'prompt_sha256','input_hash':'input_sha256','output_hash':'output_sha256','uncertain_status':'status'}[damage]
  row[key]='call_failed_or_uncertain' if damage=='uncertain_status' else '0'*64
  write(cached,row)
 clients=FakeClients([]);state=resume(run,bundle,clients,'director_brief')
 assert not clients.calls
 assert state['debug_feedback_status']=='revision_required'
 assert not state['debug_feedback'][0].get('resolved_by_output_sha256')
 assert state['status']!='completed'

def test_unchanged_repair_output_cannot_resolve_must_fix(tmp_path):
 run,bundle,feedback=prepared(tmp_path);clients=FakeClients([deepcopy(_answers()[1])])
 state=resume(run,bundle,clients,'director_brief')
 assert len(clients.calls)==1
 assert state['debug_feedback_status']=='revision_required'
 assert not state['debug_feedback'][0].get('resolved_by_output_sha256')
 assert state['status']=='needs_attention'

def test_repair_breakpoint_then_next_resume_reaches_invalidated_downstream(tmp_path):
 run,bundle,feedback=prepared(tmp_path,stop='writer_script')
 old=read(run/'director_brief.json');upstream=hashlib.sha256((run/'writer_analysis.json').read_bytes()).hexdigest()
 revised=deepcopy(_answers()[1]);revised['visual_strategy']='FIXTURE revised visual strategy'
 clients=FakeClients([revised]);state=resume(run,bundle,clients,'director_brief')
 assert state['status']=='debug_breakpoint' and len(clients.calls)==1
 assert state['debug_feedback_status']=='resolved'
 assert state['debug_stage_validity']['writer_script']=='invalidated'
 assert hashlib.sha256((run/'writer_analysis.json').read_bytes()).hexdigest()==upstream
 archive=run/('director_brief__before_feedback_'+feedback['feedback_id']+'.json')
 assert read(archive)['output_sha256']==old['output_sha256']
 script=deepcopy(_answers()[2]);script['title']='FIXTURE downstream revised script'
 next_clients=FakeClients([script]);next_state=resume(run,bundle,next_clients,'writer_script')
 assert next_state['status']=='debug_breakpoint',next_state.get('last_error')
 assert next_state['debug_breakpoint']['stage_id']=='writer_script'
 assert len(next_clients.calls)==1
 assert next_state['calls_started']==5
 assert next_state['debug_stage_validity']['writer_script']=='current'

def test_old_v18_task_binding_is_rejected_without_silent_rebind(tmp_path):
 from src.content_factory.creative_governed_runtime import verify_rules
 from src.content_factory.creative_rule_registry import file_hash
 from test_creative_governed_protocol import workflow
 root=Path(__file__).resolve().parents[4];old='data/creative_governance/20261002_v18_platform_refactor'
 w,clients=workflow(tmp_path,[])
 binding={'schema_version':'creative_rule_registry_binding/v1','registry_dir':old,'artifact_manifest_sha256':file_hash(root/old/'artifact_manifest.json'),'rules_sha256':file_hash(root/old/'rules.json'),'repository_wide_complete':False,'automatic_rule_activation':False}
 w.state.update(model_profile=CREATE_REVIEW_PROFILE,writer_prompt_version='original_events_v3',review_policy_version='evidence_review_v6')
 w.state['rule_registry_binding']=deepcopy(binding);w._save();before=(tmp_path/'state.json').read_bytes()
 restored=CreativeWorkflow(tmp_path,clients=FakeClients([]),model_profile=CREATE_REVIEW_PROFILE,writer_prompt_version='original_events_v3',review_policy_version='evidence_review_v6',production_protocol='governed_production_v1')
 restored.state=read(tmp_path/'state.json')
 with pytest.raises(ValueError,match='RUNTIME_SOURCE_CHANGED'):verify_rules(restored,'director_brief')
 assert restored.state['rule_registry_binding']==binding
 assert (tmp_path/'state.json').read_bytes()==before
 assert not clients.calls

