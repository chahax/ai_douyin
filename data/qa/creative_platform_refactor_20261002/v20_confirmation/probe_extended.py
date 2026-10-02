from pathlib import Path
from tempfile import TemporaryDirectory
from copy import deepcopy
import os,sys,socket,json
ROOT=Path(__file__).resolve().parents[4];OUT=Path(__file__).resolve().parent
os.chdir(ROOT);sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
os.environ['DATABASE_URL']='sqlite:///'+str(OUT/'extended_runtime.sqlite3').replace('\\','/')
os.environ['LLM_PROVIDER']='mock'
def blocked(*args,**kwargs):raise RuntimeError('Independent v20 verification prohibits networking')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked
from test_recovery_boundaries import prepared,resume,read
from test_creative_workflow import FakeClients,_answers
from src.content_factory.creative_stage_debug import CreativeStageCommandService
from src.content_factory.creative_workflow import _hash

def probe():
 with TemporaryDirectory(prefix='two_feedback_rounds_',dir=OUT) as tmp:
  run,bundle,feedback=prepared(Path(tmp),stop='writer_script')
  revised=deepcopy(_answers()[1]);revised['visual_strategy']='FIXTURE first director revision'
  first_clients=FakeClients([revised]);first=resume(run,bundle,first_clients,'director_brief')
  assert first['status']=='debug_breakpoint' and first['debug_feedback_status']=='resolved'
  script=deepcopy(_answers()[2]);script['title']='FIXTURE rebuilt script'
  build_clients=FakeClients([script]);built=resume(run,bundle,build_clients,'writer_script')
  assert built['status']=='debug_breakpoint' and len(build_clients.calls)==1
  negotiation_before=read(run/'DIRECTOR_FEEDBACK_CANDIDATE_REVISION.json')
  archives=list(run.glob('DIRECTOR_FEEDBACK_CANDIDATE_REVISION__history_*.json'))
  prior_director=[row for row in built['debug_feedback'] if row['stage_id']=='director_brief'][0]
  second_feedback=CreativeStageCommandService(run).feedback('writer_script','FIXTURE second feedback: revise script title',disposition='must_fix')
  state_after_feedback=read(run/'state.json');current_script=read(run/'writer_script.json')
  second_script=deepcopy(script);second_script['title']='FIXTURE second script revision'
  second_clients=FakeClients([second_script]);second=resume(run,bundle,second_clients,'writer_script')
  return {'first_repair_and_resume_passed':True,'second_feedback_output_sha256':second_feedback['output_sha256'],'current_script_output_sha256':current_script['output_sha256'],'second_feedback_binds_current_output':second_feedback['output_sha256']==current_script['output_sha256'],'upstream_director_validity_after_second_feedback':state_after_feedback['debug_stage_validity'].get('director_brief'),'stage_history_before_second_feedback':[row['name'] for row in built['stages']],'calls_before_second_feedback':built['calls_started'],'new_feedback_stage':'writer_script','already_resolved_upstream_stage':'director_brief','first_resolution_matches_current_output':prior_director['resolved_by_output_sha256']==_hash(revised),'second_repair_status':second.get('status'),'second_repair_error':second.get('last_error'),'second_repair_model_calls':len(second_clients.calls),'second_repair_reached_target':second.get('status')=='debug_breakpoint' and second.get('debug_breakpoint',{}).get('stage_id')=='writer_script','feedback_status_after_second_resume':second.get('debug_feedback_status'),'derived_receipt_history_count':len(archives),'derived_history_hash_names_valid':all(p.stem.endswith(_hash(read(p))) for p in archives),'derived_current_director_sha256':negotiation_before['director_brief_sha256'],'derived_current_matches_revised_director':negotiation_before['director_brief_sha256']==_hash(revised)}
result=probe()
(OUT/'extended_probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))

