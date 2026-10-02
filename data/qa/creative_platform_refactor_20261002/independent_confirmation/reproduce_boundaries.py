from pathlib import Path
import os, sys, socket, json, hashlib, traceback
ROOT=Path(__file__).resolve().parents[4]
OUT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
os.environ['DATABASE_URL']='sqlite:///'+str(OUT/'isolated_runtime.sqlite3').replace('\\','/')
os.environ['LLM_PROVIDER']='mock'
def blocked(*args,**kwargs):raise RuntimeError('Independent confirmation forbids network connections')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked
from tempfile import TemporaryDirectory
results={}

def check_feedback():
 from test_creative_workflow import FakeClients,_answers,_bundle
 from src.content_factory.creative_workflow import CreativeWorkflow
 from src.content_factory.creative_stage_debug import CreativeStageCommandService
 with TemporaryDirectory(prefix='feedback_',dir=OUT) as temp:
  base=Path(temp);run=base/'run';clients=FakeClients(_answers());bundle=_bundle(base)
  before=CreativeWorkflow(run,clients=clients,stop_after_stage='director_brief').run(bundle)
  service=CreativeStageCommandService(run)
  service.feedback('writer_analysis','Fixture must-fix: story premise needs revision',disposition='must_fix')
  after=CreativeWorkflow(run,clients=clients,max_new_stages=1).run(bundle)
  snapshot=service.inspect()
  return {'before_calls':before['calls_started'],'after_calls':after['calls_started'],'after_status':after['status'],'next_stage':after.get('debug_breakpoint',{}).get('stage_id'),'feedback_status':after.get('debug_feedback_status'),'validity':{r['stage_id']:r['validity'] for r in snapshot['stages']},'must_fix_prevented_progression':after['calls_started']==before['calls_started']}

def check_media():
 from test_media_user_review import _candidate
 from src.content_factory.media_review_policy import record_user_media_decision,validate_approved_tail
 with TemporaryDirectory(prefix='media_',dir=OUT) as temp:
  base=Path(temp);receipt,video,tail=_candidate(base)
  record_user_media_decision(receipt,'approved','TEST FIXTURE approval, not a real user media decision')
  before=json.loads(receipt.read_text(encoding='utf-8'))
  other=base/'unapproved-fixture.bin';other.write_bytes(b'new-unapproved-fixture-bytes')
  changed={**before,'video_path':str(other),'video_sha256':hashlib.sha256(other.read_bytes()).hexdigest(),'task_id':'different-provider-task'}
  receipt.write_text(json.dumps(changed),encoding='utf-8')
  try:
   binding=validate_approved_tail(receipt.with_name('receipt.human_review.json'),expected_tail_path=tail)
  except Exception as exc:return {'mutated_source_receipt_rejected':True,'exception':str(exc)}
  return {'mutated_source_receipt_rejected':False,'tail_binding_returned':binding,'review_approved_video_is_current_receipt_video':str(video)==changed['video_path']}

def check_queue():
 from test_task_queue_claim import _sessions
 from src.scheduler.models import TaskExecution
 from src.scheduler.queue import TaskQueue
 from src.agent import registry as registry_module
 from datetime import datetime,timedelta
 with TemporaryDirectory(prefix='queue_',dir=OUT) as temp:
  factory=_sessions(Path(temp));owner_session=factory();other_session=factory()
  owner=TaskQueue(owner_session,owner_id='fixture-owner',lease_seconds=60)
  other=TaskQueue(other_session,owner_id='fixture-recovery',lease_seconds=60)
  execution=owner.claim_next();events={}
  class FixtureRegistry:
   def call(self,*args,**kwargs):
    other_session.query(TaskExecution).filter_by(id=execution.id).update({TaskExecution.lease_expires_at:datetime.utcnow()-timedelta(seconds=1)})
    other_session.commit();events['recovered_count']=other.recover_expired_leases()
    other_session.expire_all();events['status_after_recovery']=other_session.get(TaskExecution,execution.id).status
    return {'success':True,'data':'fixture-success'}
  original=registry_module.SkillRegistry;registry_module.SkillRegistry=FixtureRegistry
  try:owner._execute_sync(execution,owner_session)
  finally:registry_module.SkillRegistry=original
  other_session.expire_all();events['status_after_old_worker_returned']=other_session.get(TaskExecution,execution.id).status
  events['old_worker_blocked_after_lease_lost']=events['status_after_old_worker_returned']==events['status_after_recovery']
  owner_session.close();other_session.close();factory.kw['bind'].dispose()
  return events
for name,func in [('must_fix_feedback',check_feedback),('media_receipt_integrity',check_media),('expired_lease_late_result',check_queue)]:
 try:results[name]=func()
 except Exception as exc:results[name]={'probe_error':type(exc).__name__+': '+str(exc),'traceback':traceback.format_exc()}
(OUT/'boundary_reproductions.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(results,ensure_ascii=False))
