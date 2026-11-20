"""One exact displayed request, independently authorized; no approval fabrication."""
from pathlib import Path
import argparse,base64,json,subprocess,sys
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from scripts import run_legal_film_material_performance_v2_20261010 as text_operator
from scripts import creative_resume_dispatch_v3 as control
from scripts.run_confirmed_legal_script_trial_v13 import verify_files
from scripts.run_legal_current_production_v10_20261010 import validate_saved_metadata
from src.content_factory.creative_legal_short_seedance_execution_v1 import sha,read,reserve_media_attempt,payload
from src.content_factory.creative_stage_contracts import persist,digest
from src.content_factory.seedance_client import SeedanceClient,SeedanceConfig
from src.content_factory.media_review_policy import mark_saved_candidate
ROOT=text_operator.ROOT
OUT=PROJECT/'data/video_generation/legal_film_material_exchange_20261010/material_v2'
PREVIOUS_MEDIA=text_operator.PREVIOUS_MEDIA
LOGICAL='legal_trend_text_trial_20261008_adopted_r8'
MODEL='doubao-seedance-2-0-mini-260615'
SID='FILM380_MATERIAL02'
write_text_new=text_operator.write_text

def request_for(client,plan):
 if plan['image_role']!='first_frame':raise ValueError('material continuation requires the specified native first frame')
 return payload(plan,Path(plan['first_frame']['path']),client)

REQUEST_SHA='89de0df9d2040768777d64fb46423f6deade27760bdfc0d3a09087766f2e8f4b'
COMPILED_SHA='b3aba9c4c29ea4067c56bc21b643a3e6b2be780c1cac2ff1cfce9ba5112c1906'
PREVIOUS_TASK='cgt-20261010170430-j94sb'
PREVIOUS_VIDEO_SHA='e89e5585f0515e391d9360f6347cdb5811141c81ecc01865df45c206561c71d9'
FIRST_FRAME_SHA='d3146ccd39e3e11abed9311d2b454adb711bdec16a635a036c6689620e210943'


def validate_single_request_authorization(auth,preview,scope,handoff,prior,snapshot,asset):
 """Validate this human instruction only; it never records a content approval."""
 required={
  'schema':'film_material_single_request_authorization/v1',
  'user_statement':'\u63d0\u4ea4\u89c6\u9891\u8bf7\u6c42',
  'authorization_type':'one_exact_displayed_request_and_specified_native_tail',
  'single_request_waiting_gate_override':True,'request_sha256':REQUEST_SHA,
  'source_sha256':text_operator.contract.SOURCE_SHA,'compiled_sha256':COMPILED_SHA,
  'performance_ordinal':394,'review_ordinal':395,'segment_id':SID,'duration_seconds':13,
  'source_refs':text_operator.REFS,'previous_task_id':PREVIOUS_TASK,
  'previous_video_sha256':PREVIOUS_VIDEO_SHA,'first_frame_sha256':FIRST_FRAME_SHA,
  'max_new_submissions':1,'batch_authorized':False,'later_segments_authorized':False,
  'publish_authorized':False,'automatic_retry':False,'budget_reset':False,
  'human_script_adoption_recorded':False,'previous_content_approval_recorded':False,
  'previous_content_status_at_authorization':'awaiting_human_review',
  'previous_human_decision_at_authorization':None,
  'approval_interpretation':'submission of this exact displayed request only; not a content evaluation, script adoption, or future continuation approval'}
 if any(auth.get(k)!=v or type(auth.get(k)) is not type(v) for k,v in required.items()):
  raise ValueError('exact single request authorization required; scope cannot expand')
 if not isinstance(auth.get('recorded_at'),str) or not auth['recorded_at']:
  raise ValueError('authorization recording time required')
 expected_keys=set(required)|{'recorded_at','preapproval_preview_sha256','predecessor_snapshot_sha256','base_user_scope_sha256','base_handoff_sha256'}
 if set(auth)!=expected_keys:raise ValueError('unexpected authorization contract field')
 if not scope['requires_previous_human_approval'] or not handoff['requires_previous_candidate_explicit_human_approval']:
  raise ValueError('historical approval requirement must remain intact')
 if handoff['performance_ordinal']!=394 or handoff['review_ordinal']!=395 or handoff['source_sha256']!=auth['source_sha256'] or handoff['compiled_sha256']!=COMPILED_SHA:
  raise ValueError('reviewed current source differs')
 if scope['previous_task_id']!=PREVIOUS_TASK or scope['previous_video_sha256']!=PREVIOUS_VIDEO_SHA or scope['script_sha256']!=auth['source_sha256']:
  raise ValueError('base source or predecessor differs')
 if digest(preview['request'])!=REQUEST_SHA or preview['request_sha256']!=REQUEST_SHA or preview['previous_task_id']!=PREVIOUS_TASK or preview['first_frame_sha256']!=FIRST_FRAME_SHA:
  raise ValueError('authorized exact displayed request differs')
 if preview['provider_create_called'] is not False or preview['dispatch_allowed'] is not False or preview['requires_previous_human_approval'] is not True:
  raise ValueError('historical unsubmitted preview changed')
 req=preview['request']
 if req['duration']!=13 or req['model']!=MODEL or req['resolution']!='480p' or req['ratio']!='9:16' or req['generate_audio'] is not True or req['return_last_frame'] is not True:
  raise ValueError('authorized native request parameters differ')
 images=[q for q in req['content'] if q['type']=='image_url']
 if len(images)!=1 or images[0]['role']!='first_frame':raise ValueError('one native literal first frame required')
 if base64.b64decode(images[0]['image_url']['url'].split(',',1)[1],validate=True)!=Path(asset['path']).read_bytes():
  raise ValueError('preview image differs from service original bytes')
 identity={'task_id':PREVIOUS_TASK,'video_sha256':PREVIOUS_VIDEO_SHA,'last_frame_sha256':FIRST_FRAME_SHA,
  'logical_task_id':LOGICAL,'last_frame_source':'generation_service_original','technical_status':'succeeded'}
 for record in (prior,snapshot):
  if any(record.get(k)!=v for k,v in identity.items()) or record['plan_snapshot']['script_content_sha256']!=auth['source_sha256']:
   raise ValueError('original saved predecessor identity differs')
  if record['content_status']=='rejected' or record.get('human_decision')=='rejected':
   raise ValueError('rejected predecessor cannot continue')
  if Path(record['last_frame']).resolve()!=Path(asset['path']).resolve():raise ValueError('native predecessor frame path differs')
  if sha(record['video_path'])!=PREVIOUS_VIDEO_SHA or sha(record['last_frame'])!=FIRST_FRAME_SHA:
   raise ValueError('saved original predecessor bytes changed')
 if snapshot['content_status']!='awaiting_human_review' or snapshot.get('human_decision') is not None:
  raise ValueError('snapshot must preserve actual pending content review')
 if asset['sha256']!=FIRST_FRAME_SHA or asset['source_task_id']!=PREVIOUS_TASK or asset['source_video_sha256']!=PREVIOUS_VIDEO_SHA or asset['source']!='generation_service_original' or asset['role']!='first_frame':
  raise ValueError('specified native tail provenance differs')
 return {'path':str(Path(asset['path']).resolve()),'sha256':FIRST_FRAME_SHA,'source':'generation_service_original','source_task_id':PREVIOUS_TASK,'human_approval_recorded':False,'use_basis':'explicit_single_request_user_instruction'}


def media_plan(client):
 folder=ROOT/'DELIVERABLE_material';x=read(ROOT/'INPUT.json');script=x['background_full_script'];scope=x['scope']
 rt=text_operator.runtime();rt.check(read(rt.ledger));review=text_operator.accepted(text_operator.REVIEW_LABEL)
 c=text_operator.compiled();first=text_operator.candidate();asset=x['selected_asset_feedback'];gate=read(ROOT/'INDEPENDENT_CURRENT_PERFORMANCE_GATE.json')
 if review['validation']['needs_revision'] or gate['unresolved_mandatory_findings'] or not gate['text_sample_qualified']:raise ValueError('text review unresolved')
 if digest(c)!=COMPILED_SHA or first['duration_seconds']!=13 or first['source_refs']!=text_operator.REFS:raise ValueError('exact compiled current interaction differs')
 expected={'FULL_SCRIPT.json':script,'FULL_MODEL_CURRENT_PERFORMANCE.json':text_operator.accepted(text_operator.WRITER_LABEL)['output'],'CURRENT_INTERACTION_COMPILED.json':c,'FIRST_SAMPLE.json':first,'FULL_SOURCE_REVIEW.json':review['output'],'INDEPENDENT_PERFORMANCE_GATE.json':gate,'ASSET_FEEDBACK.json':asset,'USER_SCOPE.json':scope}
 for name,value in expected.items():
  if read(folder/name)!=value:raise ValueError('current handoff changed: '+name)
 handoff=read(folder/'HANDOFF.json')
 if handoff['source_sha256']!=scope['script_sha256'] or handoff['human_script_adoption_recorded'] or not handoff['combined_B1_text_coverage_complete'] or not first['dispatch_ready'] or scope['max_new_submissions']!=1 or scope['later_segments_authorized']:raise ValueError('single continuation scope changed')
 auth_path=OUT/'SINGLE_REQUEST_AUTHORIZATION.json';preview_path=OUT/'REQUEST.preapproval.preview.json';snapshot_path=OUT/'PREDECESSOR_TECHNICAL_SNAPSHOT.json'
 auth=read(auth_path);preview=read(preview_path);snapshot=read(snapshot_path);prior=read(PREVIOUS_MEDIA/'receipt.json')
 bindings={'preapproval_preview_sha256':preview_path,'predecessor_snapshot_sha256':snapshot_path,'base_user_scope_sha256':folder/'USER_SCOPE.json','base_handoff_sha256':folder/'HANDOFF.json'}
 if any(auth.get(k)!=sha(p) for k,p in bindings.items()):raise ValueError('single request frozen authorization bindings changed')
 tail=validate_single_request_authorization(auth,preview,scope,handoff,prior,snapshot,asset)
 prompt=text_operator.contract.render_prompt(first,script)
 if preview['request']['content'][0]!={'type':'text','text':prompt}:raise ValueError('actual reviewed prompt differs from authorized preview')
 sources={name:{'path':str(folder/name),'sha256':sha(folder/name)} for name in [*expected,'HANDOFF.json']}
 for p in [Path(__file__).resolve(),PROJECT/'scripts/run_legal_current_production_v10_20261010.py',PROJECT/'src/content_factory/seedance_client.py',PROJECT/'src/content_factory/creative_legal_short_seedance_execution_v1.py',PROJECT/'src/content_factory/media_review_policy.py',auth_path,preview_path,snapshot_path,PREVIOUS_MEDIA/'PLAN.json',Path(prior['video_path']),Path(asset['path']),ROOT/'CALL_LEDGER.json']:
  sources[str(p.relative_to(PROJECT))]={'path':str(p),'sha256':sha(p)}
 plan={'schema':'film_legal_material_single_request/v3','logical_task_id':LOGICAL,'segment_id':SID,'shot_id':'B1_MATERIAL_EXCHANGE','script_content_sha256':scope['script_sha256'],'sources':sources,'authorization':auth,'base_authorization':scope,'predecessor_task_id':prior['task_id'],'provider':'ark_api','model':MODEL,'resolution':'480p','ratio':'9:16','duration_seconds':13,'generate_audio':True,'return_last_frame':True,'image_role':'first_frame','first_frame':tail,'opening_frame_source':'specified_service_original_tail_under_single_request_authorization','prompt':prompt,'source_refs':first['source_refs'],'fit_scaled':False,'budget_reset':False,'later_segments_authorized':False,'previous_content_approval_recorded':False,'text_qualified_not_current_video_approved':True}
 if request_for(client,plan)!=preview['request']:raise ValueError('built request differs from exact user-authorized request')
 return plan


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
    r={'schema':'film_legal_material_single_request_receipt/v3','status':'submitting','technical_status':'running','content_status':'not_available',
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
