from copy import deepcopy
import pytest
from test_recovery_boundaries import prepared,resume,read,write
from test_creative_workflow import FakeClients,_answers
from src.content_factory.creative_stage_debug import CreativeStageCommandService

def rebuilt(tmp_path):
 run,bundle,feedback=prepared(tmp_path,stop='writer_script')
 brief=deepcopy(_answers()[1]);brief['visual_strategy']='FIXTURE first repaired director brief'
 first=resume(run,bundle,FakeClients([brief]),'director_brief')
 assert first['status']=='debug_breakpoint' and first['debug_feedback_status']=='resolved'
 script=deepcopy(_answers()[2]);script['title']='FIXTURE rebuilt writer script'
 second=resume(run,bundle,FakeClients([script]),'writer_script')
 assert second['status']=='debug_breakpoint' and second['calls_started']==5
 return run,bundle,script

def test_new_feedback_after_rebuild_binds_current_output(tmp_path):
 run,bundle,script=rebuilt(tmp_path)
 current=read(run/'writer_script.json')
 feedback=CreativeStageCommandService(run).feedback('writer_script','FIXTURE second feedback',disposition='must_fix')
 assert feedback['output_sha256']==current['output_sha256'],'feedback bound an obsolete writer_script output'
 assert read(run/'state.json')['debug_stage_validity']['director_brief']=='current'

def test_second_feedback_reaches_target_after_prior_stage_revision(tmp_path):
 run,bundle,script=rebuilt(tmp_path)
 CreativeStageCommandService(run).feedback('writer_script','FIXTURE second feedback',disposition='must_fix')
 revised=deepcopy(script);revised['title']='FIXTURE second writer repair'
 clients=FakeClients([revised]);state=resume(run,bundle,clients,'writer_script')
 assert state['status']=='debug_breakpoint',state.get('last_error')
 assert state['debug_breakpoint']['stage_id']=='writer_script'
 assert state['debug_feedback_status']=='resolved'
 assert len(clients.calls)==1 and state['calls_started']==6

def test_clean_replay_after_rebuild_preserves_budget_without_model_calls(tmp_path):
 run,bundle,script=rebuilt(tmp_path);clients=FakeClients([])
 state=resume(run,bundle,clients,'writer_script')
 assert state['status']=='debug_breakpoint' and state['calls_started']==5
 assert state['debug_feedback_status']=='resolved' and not clients.calls

@pytest.mark.parametrize('receipt',['feedback','resolution'])
def test_tampered_resolved_feedback_receipt_stops_before_model_call(tmp_path,receipt):
 run,bundle,script=rebuilt(tmp_path);state=read(run/'state.json');summary=state['debug_feedback'][0]
 path=run/summary['receipt' if receipt=='feedback' else 'resolution_receipt']
 value=read(path)
 if receipt=='feedback':value['message']='TAMPERED FIXTURE feedback'
 else:value['resolved_by_output_sha256']='0'*64
 write(path,value)
 clients=FakeClients([]);result=resume(run,bundle,clients,'writer_script')
 assert not clients.calls
 assert result['status']=='needs_attention'
 assert 'resolved feedback replay binding changed' in result.get('last_error','')
