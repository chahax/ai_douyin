from pathlib import Path
import os,sys,socket,json,hashlib
from copy import deepcopy
from tempfile import TemporaryDirectory
ROOT=Path(__file__).resolve().parents[4];OUT=Path(__file__).resolve().parent
os.chdir(ROOT);sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
os.environ['DATABASE_URL']='sqlite:///'+str(OUT/'boundary_runtime.sqlite3').replace('\\','/')
os.environ['LLM_PROVIDER']='mock'
def blocked(*args,**kwargs):raise RuntimeError('Independent v19 verification prohibits network connections')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked
from test_creative_workflow import FakeClients,_answers,_bundle
from src.content_factory.creative_workflow import CreativeWorkflow
from src.content_factory.creative_stage_debug import CreativeStageCommandService

def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def run_probe():
 with TemporaryDirectory(prefix='repair_closure_',dir=OUT) as tmp:
  base=Path(tmp);run=base/'run';bundle=_bundle(base);original=FakeClients(_answers())
  first=CreativeWorkflow(run,clients=original,stop_after_stage='writer_script').run(bundle)
  original_brief=read(run/'director_brief.json');upstream_hash=hashlib.sha256((run/'writer_analysis.json').read_bytes()).hexdigest()
  feedback=CreativeStageCommandService(run).feedback('director_brief','FIXTURE improve visual strategy',disposition='must_fix')
  revised=deepcopy(_answers()[1]);revised['visual_strategy']='FIXTURE revised visual strategy'
  repair_clients=FakeClients([revised])
  repaired=CreativeWorkflow(run,clients=repair_clients,stop_after_stage='director_brief').run(bundle)
  after_feedback=read(run/'state.json');snapshot=CreativeStageCommandService(run).inspect()
  script=deepcopy(_answers()[2]);script['title']='FIXTURE downstream revised script'
  next_clients=FakeClients([script]);next_error=None
  try:next_state=CreativeWorkflow(run,clients=next_clients,stop_after_stage='writer_script').run(bundle)
  except Exception as exc:next_error=str(exc);next_state=read(run/'state.json')
  archive=run/('director_brief__before_feedback_'+feedback['feedback_id']+'.json')
  return {'initial_status':first.get('status'),'initial_calls':first.get('calls_started'),'repair_status':repaired.get('status'),'repair_breakpoint':repaired.get('debug_breakpoint',{}).get('stage_id'),'repair_model_calls':len(repair_clients.calls),'feedback_status':snapshot['feedback_status'],'downstream_still_invalidated':after_feedback['debug_stage_validity'].get('writer_script')=='invalidated','upstream_receipt_unchanged':hashlib.sha256((run/'writer_analysis.json').read_bytes()).hexdigest()==upstream_hash,'old_brief_archive_preserved':archive.exists() and read(archive)['output_sha256']==original_brief['output_sha256'],'next_resume_status':next_state.get('status'),'next_resume_error':next_error or next_state.get('last_error'),'next_resume_model_calls':len(next_clients.calls),'next_resume_reached_downstream':next_state.get('status')=='debug_breakpoint' and next_state.get('debug_breakpoint',{}).get('stage_id')=='writer_script'}
result=run_probe()
(OUT/'closure_probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
