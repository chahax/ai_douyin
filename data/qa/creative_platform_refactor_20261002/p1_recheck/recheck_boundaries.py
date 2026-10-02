from pathlib import Path
import os,sys,socket,json,hashlib,ast
from tempfile import TemporaryDirectory
from copy import deepcopy
from datetime import datetime,timedelta
ROOT=Path(__file__).resolve().parents[4];OUT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(ROOT/'tests')];os.chdir(ROOT)
os.environ['DATABASE_URL']='sqlite:///'+str(OUT/'isolated_runtime.sqlite3').replace('\\','/')
os.environ['LLM_PROVIDER']='mock'
def blocked(*args,**kwargs):raise RuntimeError('P1 recheck prohibits network connections')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked
from test_creative_workflow import FakeClients,_answers,_bundle
from src.content_factory.creative_workflow import CreativeWorkflow
from src.content_factory.creative_stage_debug import CreativeStageCommandService
from test_media_user_review import _candidate
from src.content_factory.media_review_policy import record_user_media_decision,validate_approved_tail
from test_task_queue_claim import _sessions
from src.scheduler.models import TaskExecution,TaskStatus
from src.scheduler.queue import TaskQueue
from src.scheduler import queue as queue_module
from src.agent import registry as registry_module
from src.content_factory.creative_rule_registry import bind_registry,validate_registry_binding

results={}

def probe_downstream_gate():
 with TemporaryDirectory(prefix='feedback_',dir=OUT) as tmp:
  base=Path(tmp);run=base/'run';clients=FakeClients(_answers());bundle=_bundle(base)
  CreativeWorkflow(run,clients=clients,stop_after_stage='director_brief').run(bundle)
  CreativeStageCommandService(run).feedback('writer_analysis','FIXTURE must fix premise',disposition='must_fix')
  workflow=CreativeWorkflow(run,clients=clients)
  workflow.state=json.loads((run/'state.json').read_text(encoding='utf-8'))
  before=len(clients.calls)
  try:workflow._stage('writer_script','writer',{},lambda value:None)
  except Exception as exc:return {'downstream_blocked':len(clients.calls)==before,'exception':str(exc)}
  return {'downstream_blocked':False,'new_calls':len(clients.calls)-before}

def probe_target_reachable():
 with TemporaryDirectory(prefix='target_',dir=OUT) as tmp:
  base=Path(tmp);run=base/'run';bundle=_bundle(base);original=FakeClients(_answers())
  state=CreativeWorkflow(run,clients=original,stop_after_stage='director_brief').run(bundle)
  CreativeStageCommandService(run).feedback('director_brief','FIXTURE revise director brief',disposition='must_fix')
  fresh=FakeClients([])
  try:
   state=CreativeWorkflow(run,clients=fresh,max_new_stages=1).run(bundle)
   error=state.get('last_error')
  except Exception as exc:error=str(exc)
  state=json.loads((run/'state.json').read_text(encoding='utf-8'))
  return {'normal_resume_reached_target':bool(fresh.calls),'new_model_calls':len(fresh.calls),'workflow_status':state.get('status'),'last_error':error,'pending_feedback':state.get('debug_feedback_status')}

def probe_media_binding():
 with TemporaryDirectory(prefix='media_',dir=OUT) as tmp:
  base=Path(tmp);receipt,video,tail=_candidate(base)
  record_user_media_decision(receipt,'approved','TEST FIXTURE approval, not real media review')
  other=base/'other-fixture.bin';other.write_bytes(b'unapproved-fixture')
  row=json.loads(receipt.read_text(encoding='utf-8'))
  row.update(video_path=str(other),video_sha256=hashlib.sha256(other.read_bytes()).hexdigest(),task_id='other-task')
  receipt.write_text(json.dumps(row),encoding='utf-8')
  try:validate_approved_tail(receipt.with_name('receipt.human_review.json'),expected_tail_path=tail)
  except ValueError as exc:return {'changed_candidate_rejected':True,'exception':str(exc)}
  return {'changed_candidate_rejected':False}

def probe_late_result():
 with TemporaryDirectory(prefix='queue_',dir=OUT) as tmp:
  factory=_sessions(Path(tmp));owner_session=factory();other_session=factory()
  owner=TaskQueue(owner_session,owner_id='fixture-owner',lease_seconds=60)
  other=TaskQueue(other_session,owner_id='fixture-recovery',lease_seconds=60)
  execution=owner.claim_next();events={'result_before':deepcopy(execution.result)}
  class FixtureRegistry:
   def call(self,*args,**kwargs):
    other_session.query(TaskExecution).filter_by(id=execution.id).update({TaskExecution.lease_expires_at:datetime.utcnow()-timedelta(seconds=1)})
    other_session.commit();events['recovered']=other.recover_expired_leases()
    other_session.expire_all();events['status_after_recovery']=other_session.get(TaskExecution,execution.id).status
    return {'success':True,'data':'late-result-fixture'}
  original_registry=registry_module.SkillRegistry;original_session=queue_module.SessionLocal
  registry_module.SkillRegistry=FixtureRegistry;queue_module.SessionLocal=factory
  try:owner._execute_sync(execution,owner_session)
  finally:registry_module.SkillRegistry=original_registry;queue_module.SessionLocal=original_session
  other_session.expire_all();saved=other_session.get(TaskExecution,execution.id)
  events.update(status_after_late_result=saved.status,result_saved=saved.result)
  events['late_result_fenced']=saved.status=='outcome_unknown' and saved.result==events['result_before']
  owner_session.close();other_session.close();factory.kw['bind'].dispose()
  return events

def probe_governance():
 from src.content_factory.creative_governed_runtime import REGISTRY_DIRECTORY
 base=ROOT/REGISTRY_DIRECTORY
 manifest=json.loads((base/'runtime_sources.json').read_text(encoding='utf-8'))
 bad=[r['path'] for r in manifest['sources'] if hashlib.sha256((ROOT/r['path']).read_bytes()).hexdigest()!=r['sha256']]
 try:
  binding=bind_registry(ROOT,REGISTRY_DIRECTORY)
  validate_registry_binding(binding,ROOT,stage='review',features=['gaze','cut','seat','state','dialogue','timing','source','handoff'])
 except Exception as exc:return {'directory':REGISTRY_DIRECTORY,'runtime_mismatches':bad,'governed_stage_gate_passed':False,'exception':str(exc)}
 return {'directory':REGISTRY_DIRECTORY,'runtime_mismatches':bad,'governed_stage_gate_passed':True}

for name,func in [('downstream_feedback_gate',probe_downstream_gate),('responsible_stage_resume',probe_target_reachable),('media_identity',probe_media_binding),('worker_late_result',probe_late_result),('governance_binding',probe_governance)]:
 try:results[name]=func()
 except Exception as exc:
  import traceback
  results[name]={'probe_error':str(exc),'traceback':traceback.format_exc()}
(OUT/'boundary_results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(results,ensure_ascii=False))
