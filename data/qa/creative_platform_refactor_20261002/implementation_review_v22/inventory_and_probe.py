from pathlib import Path
import ast,json,hashlib,os,sys,socket
from tempfile import TemporaryDirectory
ROOT=Path(__file__).resolve().parents[4];OUT=Path(__file__).resolve().parent
os.chdir(ROOT);sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
os.environ['DATABASE_URL']='sqlite:///'+str(OUT/'review_runtime.sqlite3').replace(chr(92),'/')
os.environ['LLM_PROVIDER']='mock'
def blocked(*a,**kw):raise RuntimeError('Implementation review prohibits network access')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked
files=['src/content_factory/creative_workflow.py','src/content_factory/creative_stage_runtime.py','src/content_factory/creative_stage_contracts.py','src/content_factory/creative_stage_debug.py','src/content_factory/creative_segment_execution.py','src/content_factory/creative_media_workbench.py','src/content_factory/creative_delivery.py','src/content_factory/creative_quality_evidence.py','src/web/creative_workflow_dashboard.py','scripts/creative_workbench.py']
summary=[]
for relative in files:
 path=ROOT/relative;source=path.read_text(encoding='utf-8-sig');tree=ast.parse(source)
 funcs=[{'name':n.name,'line':n.lineno,'lines':n.end_lineno-n.lineno+1} for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
 summary.append({'path':relative,'lines':len(source.splitlines()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'function_count':len(funcs),'largest_functions':sorted(funcs,key=lambda r:r['lines'],reverse=True)[:4]})
from test_creative_workflow import FakeClients,_answers,_bundle
from src.content_factory.creative_workflow import CreativeWorkflow
from src.content_factory.creative_stage_debug import CreativeStageCommandService
from copy import deepcopy
with TemporaryDirectory(prefix='inflight_feedback_',dir=OUT) as tmp:
 base=Path(tmp);run=base/'run';bundle=_bundle(base)
 first=CreativeWorkflow(run,clients=FakeClients(_answers()),stop_after_stage='director_brief').run(bundle)
 assert first['status']=='debug_breakpoint'
 events={}
 class InjectingClients(FakeClients):
  def call(self,*args,**kwargs):
   service=CreativeStageCommandService(run)
   shown=next(row for row in service.inspect()['stages'] if row['stage_id']=='director_brief')
   feedback=service.feedback('director_brief','FIXTURE user reports a director issue while the downstream model is running',disposition='must_fix',expected_input_sha256=shown['input_sha256'],expected_output_sha256=shown['output_sha256'])
   events['expected_version_hashes_supplied']=True
   state=json.loads((run/'state.json').read_text(encoding='utf-8'))
   (OUT/'feedback_state_during_call.json').write_text(json.dumps({'state':state,'feedback_receipt':feedback},ensure_ascii=False,indent=2),encoding='utf-8')
   events.update(feedback_id=feedback['feedback_id'],feedback_present_during_call=any(r['feedback_id']==feedback['feedback_id'] for r in state['debug_feedback']),feedback_status_during_call=state.get('debug_feedback_status'))
   return super().call(*args,**kwargs)
 clients=InjectingClients([deepcopy(_answers()[2])])
 final=CreativeWorkflow(run,clients=clients,stop_after_stage='writer_script').run(bundle)
 saved=json.loads((run/'state.json').read_text(encoding='utf-8'))
 (OUT/'feedback_state_after_call.json').write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf-8')
 events.update(final_status=saved['status'],final_feedback_status=saved.get('debug_feedback_status'),feedback_present_after_call=any(r['feedback_id']==events['feedback_id'] for r in saved.get('debug_feedback',[])),pending_feedback_count=sum(r.get('disposition')=='must_fix' and not r.get('resolved_by_output_sha256') for r in saved.get('debug_feedback',[])),feedback_receipt_retained=any(p.stem==events['feedback_id'] for p in (run/'.creative_debug/feedback').rglob('*.json')),model_calls=len(clients.calls))
 continued_clients=FakeClients([deepcopy(_answers()[3])])
 continued=CreativeWorkflow(run,clients=continued_clients,stop_after_stage='director_shots').run(bundle)
 events.update(downstream_calls_after_lost_feedback=len(continued_clients.calls),continued_status=continued['status'],continued_breakpoint=continued.get('debug_breakpoint',{}).get('stage_id'))
 (OUT/'feedback_state_after_continuation.json').write_text(json.dumps(continued,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'code_inventory.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(OUT/'inflight_feedback_probe.json').write_text(json.dumps(events,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'inventory':summary,'inflight_feedback':events},ensure_ascii=False))
