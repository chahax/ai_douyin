"""One adjacent approved-tail material segment; no automatic retry or batch."""
from pathlib import Path
import argparse,json,subprocess,sys
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from scripts import run_legal_film_refusal_performance_v3_20261010 as text_operator
from scripts import creative_resume_dispatch_v3 as control
from scripts.run_confirmed_legal_script_trial_v13 import verify_files
from scripts.run_legal_current_production_v10_20261010 import validate_saved_metadata
from src.content_factory.creative_legal_short_seedance_execution_v1 import sha,read,reserve_media_attempt,payload
from src.content_factory.creative_stage_contracts import persist,digest
from src.content_factory.seedance_client import SeedanceClient,SeedanceConfig
from src.content_factory.media_review_policy import mark_saved_candidate,validate_approved_tail
ROOT=text_operator.ROOT
OUT=PROJECT/'data/video_generation/legal_film_refusal_exchange_20261010/refusal_v3'
PREVIOUS_MEDIA=text_operator.PREVIOUS_MEDIA
LOGICAL='legal_trend_text_trial_20261008_adopted_r8'
MODEL='doubao-seedance-2-0-mini-260615'
SID='FILM380_REFUSAL03'
write_text_new=text_operator.write_text

def request_for(client,plan):
 if plan['image_role']!='first_frame':raise ValueError('material continuation requires approved native first frame')
 return payload(plan,Path(plan['first_frame']['path']),client)

def media_plan(client):
 folder=ROOT/'DELIVERABLE_refusal';x=read(ROOT/'INPUT.json');script=x['background_full_script'];scope=x['scope']
 rt=text_operator.runtime();rt.check(read(rt.ledger));review=text_operator.accepted(text_operator.REVIEW_LABEL)
 c=text_operator.compiled();first=text_operator.candidate();asset=x['selected_asset_feedback'];gate=read(ROOT/'INDEPENDENT_CURRENT_PERFORMANCE_GATE.json')
 if review['validation']['needs_revision'] or gate['unresolved_mandatory_findings'] or not gate['text_sample_qualified']:raise ValueError('text review unresolved')
 expected={'FULL_SCRIPT.json':script,'CONTRACT_SPEC.json':x['contract_spec'],'FULL_MODEL_CURRENT_PERFORMANCE.json':text_operator.accepted(text_operator.WRITER_LABEL)['output'],'CURRENT_INTERACTION_COMPILED.json':c,'FIRST_SAMPLE.json':first,'FULL_SOURCE_REVIEW.json':review['output'],'INDEPENDENT_PERFORMANCE_GATE.json':gate,'ASSET_FEEDBACK.json':asset,'USER_SCOPE.json':scope}
 for name,value in expected.items():
  if read(folder/name)!=value:raise ValueError('current handoff changed: '+name)
 handoff=read(folder/'HANDOFF.json')
 if handoff['source_sha256']!=scope['script_sha256'] or handoff['compiled_sha256']!=digest(c) or handoff['human_script_adoption_recorded'] or not first['dispatch_ready'] or scope['max_new_submissions']!=1 or scope['later_segments_authorized'] or first['source_refs']!=text_operator.REFS:raise ValueError('single next segment scope changed')
 review_path=PREVIOUS_MEDIA/'receipt.human_review.json';tail=validate_approved_tail(review_path,expected_tail_path=Path(asset['path']))
 prior=read(PREVIOUS_MEDIA/'receipt.json');snapshot=read(ROOT/'PREDECESSOR_APPROVED_SNAPSHOT.json')
 for q in [prior,snapshot]:
  if q['task_id']!=scope['previous_task_id'] or q['video_sha256']!=scope['previous_video_sha256'] or q['logical_task_id']!=LOGICAL or q['last_frame_source']!='generation_service_original' or q['plan_snapshot']['script_content_sha256']!=scope['script_sha256'] or q['last_frame_sha256']!=asset['sha256'] or q['content_status']!='approved':raise ValueError('approved predecessor identity or source differs')
 if tail['sha256']!=asset['sha256'] or read(review_path)['user_statement']!=scope['user_statement']:raise ValueError('current approved tail statement differs')
 prompt=text_operator.prompt()
 sources={name:{'path':str(folder/name),'sha256':sha(folder/name)} for name in [*expected,'HANDOFF.json']}
 for p in [Path(__file__).resolve(),PROJECT/'scripts/run_legal_current_production_v10_20261010.py',PROJECT/'src/content_factory/seedance_client.py',PROJECT/'src/content_factory/creative_legal_short_seedance_execution_v1.py',PROJECT/'src/content_factory/media_review_policy.py',review_path,ROOT/'PREDECESSOR_APPROVED_SNAPSHOT.json',PREVIOUS_MEDIA/'PLAN.json',Path(prior['video_path']),Path(asset['path']),ROOT/'CALL_LEDGER.json']:
  sources[str(p.relative_to(PROJECT))]={'path':str(p),'sha256':sha(p)}
 return {'schema':'film_legal_refusal_segment/v1','logical_task_id':LOGICAL,'segment_id':SID,'shot_id':'B2_REFUSAL_AND_FORMAT','script_content_sha256':scope['script_sha256'],'sources':sources,'authorization':scope,'predecessor_user_statement':read(review_path)['user_statement'],'predecessor_task_id':prior['task_id'],'provider':'ark_api','model':MODEL,'resolution':'480p','ratio':'9:16','duration_seconds':first['duration_seconds'],'generate_audio':True,'return_last_frame':True,'image_role':'first_frame','first_frame':tail,'opening_frame_source':'preceding_human_approved_service_original_tail','prompt':prompt,'source_refs':first['source_refs'],'fit_scaled':False,'budget_reset':False,'later_segments_authorized':False,'text_qualified_not_current_video_approved':True}


def media(operation):
 OUT.mkdir(parents=True,exist_ok=True);pp=OUT/'PLAN.json';rp=OUT/'receipt.json';lock=OUT/'.execution.lock'
 with lock.open('x',encoding='utf-8') as f:f.write('exclusive adjacent material segment execution')
 try:
  with SeedanceClient(SeedanceConfig.from_env('ark_api',require_key=True)) as client:
   if client.config.model!=MODEL:raise ValueError('configured model differs; no automatic switch')
   if operation=='media_prepare':
    if rp.exists():raise ValueError('existing submission; query original ID')
    plan=media_plan(client);control.write(pp,plan,True);req=request_for(client,plan)
    control.write(OUT/'REQUEST.preview.json',req,True);write_text_new(OUT/'PROMPT.txt',plan['prompt']+'\n')
    return {'status':'prepared','new_paid_calls':0,'duration_seconds':plan['duration_seconds'],'source_refs':plan['source_refs']}
   if operation=='media_submit':
    if rp.exists():raise ValueError('existing receipt; query original ID, never repeat submit')
    plan=read(pp)
    if media_plan(client)!=plan or sha(plan['first_frame']['path'])!=plan['first_frame']['sha256']:raise ValueError('current source/asset binding changed')
    verify_files({r['path']:r['sha256'] for r in plan['sources'].values()})
    req=request_for(client,plan)
    if req!=read(OUT/'REQUEST.preview.json'):raise ValueError('request preview changed')
    r={'schema':'film_legal_refusal_segment_receipt/v1','status':'submitting','technical_status':'running','content_status':'not_available',
     'logical_task_id':LOGICAL,'segment_id':SID,'shot_id':plan['shot_id'],'provider':'ark_api','model':MODEL,'plan':str(pp),'plan_sha256':sha(pp),
     'plan_snapshot':plan,'source_bindings':plan['sources'],'request_sha256':digest(req),'request':req,'created_at':control.now(),'new_submissions':1,'automatic_retry':False}
    control.write(rp,r,True)
    try:reserve_media_attempt(pp,plan,rp)
    except Exception as exc:
     r.update(status='blocked_before_submit',technical_status='not_submitted',new_submissions=0,error=str(exc));persist(rp,r);raise
    try:
     created=client.create_task(req)
     if not created.get('id'):raise ValueError('missing task ID; submission outcome unknown')
    except Exception as exc:
     code=getattr(exc,'status_code',None);known=isinstance(code,int) and 400<=code<500
     r.update(status='request_rejected' if known else 'submit_outcome_unknown',technical_status='failed' if known else 'unknown',http_status=code,error=str(exc));persist(rp,r);raise
    r.update(task_id=created['id'],created=created,status='submitted');persist(rp,r)
   elif operation=='media_query':
    r=read(rp)
    if not r.get('task_id'):raise ValueError('no task ID; reconcile, never resubmit')
   else:raise ValueError('explicit media operation required')
   if r.get('technical_status')=='succeeded':
    if sha(r['video_path'])!=r['video_sha256'] or (r.get('last_frame') and sha(r['last_frame'])!=r['last_frame_sha256']):raise ValueError('saved output changed')
    return {k:r[k] for k in ['technical_status','content_status','task_id','video_path']}
   t=client.get_task(r['task_id']);r.update(latest_response=t,last_queried_at=control.now(),status=t['status']);persist(rp,r)
   if t['status'] in ['failed','expired','cancelled']:r.update(technical_status='failed',final=t);persist(rp,r)
   elif t['status']=='succeeded':
    stage='video_download'
    try:
     video=client.download_video(t,OUT/(SID+'.mp4'))
     if not video.stat().st_size:raise ValueError('empty video output')
     r.update(final=t,provider_task_status='succeeded',video_path=str(video),video_sha256=sha(video),video_bytes=video.stat().st_size)
     persist(rp,r);stage='technical_probe'
     probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(video)],text=True,encoding='utf-8'))
     validate_saved_metadata(probe,r['plan_snapshot']);r['metadata']=probe;persist(rp,r)
     stage='tail_download'
     if t.get('content',{}).get('last_frame_url'):
      tail=client.download_last_frame(t,OUT/(SID+'.provider_last.png'))
      if not tail.stat().st_size:raise ValueError('empty original tail output')
      r.update(last_frame=str(tail),last_frame_sha256=sha(tail),last_frame_source='generation_service_original',tail_status='saved_unapproved')
     else:r.update(last_frame=None,last_frame_sha256=None,tail_status='not_returned; continuation blocked')
     r.update(completed_at=control.now(),human_decision=None,next_segment_dispatch_allowed=False,assistant_content_inspected=False)
     r.pop('artifact_error',None);r.pop('failure_stage',None)
     mark_saved_candidate(r);persist(rp,r)
    except Exception as exc:
     r.update(status='artifact_save_pending',provider_task_status='succeeded',failure_stage=stage,artifact_error=str(exc));persist(rp,r);raise
   return {k:r.get(k) for k in ['technical_status','content_status','status','task_id','video_path','tail_status']}
 finally:lock.unlink()


if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('operation',choices=['media_prepare','media_submit','media_query']);a=ap.parse_args()
 print(json.dumps(media(a.operation),ensure_ascii=False),flush=True)
