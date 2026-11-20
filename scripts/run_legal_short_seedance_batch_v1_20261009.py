"""Authorized short remake only; reuse identity/office reference then native tails."""
from pathlib import Path
import argparse,json,sys,subprocess,time
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from src.content_factory import creative_legal_short_seedance_execution_v1 as execute
from src.content_factory.creative_stage_contracts import persist,digest
from src.content_factory.creative_legal_short_video_projection_v1 import project,render_prompt,MODEL
from src.content_factory.creative_legal_short_director_performance_v1 import compile_complete
from src.content_factory.seedance_client import SeedanceClient,SeedanceConfig
from src.content_factory.media_review_policy import validate_source_bindings
OUT=PROJECT/'data/video_generation/legal_short_remake_20261009/batch_v1'
# Same resignation-story reservation ledger: no failure/call reset by new folder.
LOGICAL='legal_trend_text_trial_20261008_adopted_r8'
DEFAULT=PROJECT/'data/production_revisions/legal_short_remake_20261009/round_03/DELIVERABLE_short'
def immutable(p,v):persist(p,v,immutable=True)
def prepare(bundle):
 bundle=Path(bundle).resolve();s=execute.read(bundle/'FULL_SCRIPT.json');d=execute.read(bundle/'WHOLE_FILM_DIRECTION.json');p=execute.read(bundle/'ACTUAL_BEAT_PERFORMANCES.json');c=execute.read(bundle/'COMPILED_PERFORMANCE.json');review=execute.read(bundle/'FULL_TEXT_REVIEW.json');scope=execute.read(bundle/'USER_SCOPE.json');asset=execute.read(bundle/'ASSET_FEEDBACK.json')
 if compile_complete(s,d,p)!=c or review['issues'] or not review['story_preserved']:raise ValueError('exact complete reviewed short production required')
 if scope['user_statements'][-1]!='本次整批生成，最后统一审核' or scope['interpreted_current_script_sha256']!=digest(s) or scope['max_duration_seconds']!=180:raise ValueError('current explicit remake scope required')
 speech=[r['original_text'] for r in c['schedule'] if r['source_kind']=='dialogue'];ds=project(c)
 for row in ds:row['prompt']=render_prompt(row,speech);row['prompt_sha256']=digest(row['prompt'])
 OUT.mkdir(parents=True,exist_ok=True)
 bindings={name:{'path':str(bundle/name),'sha256':execute.sha(bundle/name)} for name in ['FULL_SCRIPT.json','WHOLE_FILM_DIRECTION.json','ACTUAL_BEAT_PERFORMANCES.json','COMPILED_PERFORMANCE.json','FULL_TEXT_REVIEW.json','USER_SCOPE.json','ASSET_FEEDBACK.json','PRODUCTION_HANDOFF.json']}
 manifest={'schema':'legal_short_batch_manifest/v1','script_sha256':digest(s),'compiled_sha256':digest(c),'segments':ds,'source_bindings':bindings,'planned_service_seconds':sum(x['duration_seconds'] for x in ds),'original_source_steps':14,'original_speeches':5,'subtitle_rendering':False,'audio_binding':'native generated Mandarin; original tail contains no voice reference, continuity unverified'}
 immutable(OUT/'BATCH_MANIFEST.json',manifest)
 auth={'schema':'legal_short_batch_authorization/v1','user_statement':'本次整批生成，最后统一审核','question_call_id':'call_61f0a83eba2b4aabacd1783b79e84d84','script_sha256':digest(s),'manifest_sha256':execute.sha(OUT/'BATCH_MANIFEST.json'),'media_model':MODEL,'resolution':'480p','new_submissions_max':len(ds),'new_segment_ids':[x['segment_id'] for x in ds],'automatic_retry':False,'publishing_authorized':False,'quality_approved':False,'max_duration_seconds':180,'scope':'only current reviewed short original resignation story, first identity/environment image reference, then service-native original tail chain'}
 immutable(OUT/'BATCH_USER_AUTHORIZATION.json',auth)
 registry={'schema':'legal_same_story_remake_registration/v1','same_logical_story':LOGICAL,'budget_root':str(execute.media_reservation_root({'logical_task_id':LOGICAL})),'prior_full_film':'data/video_generation/legal_trend_20261008/remaining_batch_v1/ASSEMBLY_RECEIPT.json','prior_full_film_status':'rejected_by_user','prior_individual_receipts_unchanged':True,'new_script_sha256':digest(s),'budget_reset':False,'automatic_retry':False,'human_known_full_film_failures':1}
 immutable(OUT/'SAME_STORY_REGISTRATION.json',registry)
 immutable(OUT/'PROJECTION_VERIFICATION.json',{'source_rows_coverage':[r['source_ref'] for r in c['schedule']]==[ref for row in ds for ref in row['source_refs']],'every_original_whole_speech_once':all(sum(x['prompt'].count(t) for x in ds)==1 for t in speech),'no_speech_split':True,'source_performance_unchanged':True,'current_exact_speech_reference_projection':'only exact current full utterance inside active delivery cue labelled 本句; original complete model prose retained','full_future_direction_sent_to_video':False,'actual_media_quality_checked':False,'offline_only':True,'planned_service_seconds':manifest['planned_service_seconds']})
 body=['# 实际服务提示词：辞职剧情短版','',f"计划{manifest['planned_service_seconds']}秒，{len(ds)}段。对白未拆分，普通话，无字幕。",'']
 for row in ds:body.extend(['## '+row['segment_id']+' / '+','.join(row['source_refs'])+' / '+str(row['duration_seconds'])+'秒','',row['prompt'],''])
 path=OUT/'ACTUAL_PROMPTS.md';text='\n'.join(body)
 if path.exists() and path.read_text(encoding='utf-8')!=text:raise ValueError('actual prompt history changed')
 if not path.exists():path.write_text(text,encoding='utf-8')
 return manifest,auth,asset

def plan_for(manifest,definition,asset,prior_path):
 sources={**manifest['source_bindings'],'batch_manifest':{'path':str(OUT/'BATCH_MANIFEST.json'),'sha256':execute.sha(OUT/'BATCH_MANIFEST.json')},'batch_authorization':{'path':str(OUT/'BATCH_USER_AUTHORIZATION.json'),'sha256':execute.sha(OUT/'BATCH_USER_AUTHORIZATION.json')},'asset_feedback':manifest['source_bindings']['ASSET_FEEDBACK.json']}
 if prior_path:
  r=execute.read(prior_path);frame={'path':r['last_frame'],'sha256':r['last_frame_sha256']};sources['predecessor_receipt']={'path':str(prior_path),'sha256':execute.sha(prior_path)}
 else:frame={'path':asset['path'],'sha256':asset['sha256']}
 return {'schema':'legal_short_seedance_segment_plan/v1','logical_task_id':LOGICAL,'segment_id':definition['segment_id'],'shot_id':definition['shot_id'],'segment_definition':definition,'sources':sources,'script_content_sha256':manifest['script_sha256'],'provider':'ark_api','model':MODEL,'resolution':'480p','ratio':'9:16','duration_seconds':definition['duration_seconds'],'generate_audio':True,'return_last_frame':True,'seed':20261009,'first_frame':frame,'image_role':definition['image_role'],'opening_frame_source':'preceding_service_original_tail_current_short_batch' if prior_path else 'old_native_image_as_identity_environment_reference','prompt':definition['prompt'],'prompt_sha256':definition['prompt_sha256'],'content_status':'awaiting_human_review','authorization':{'user_statement':'本次整批生成，最后统一审核','automatic_retry':False,'quality_approved':False},'budget_reset':False}

def progress(manifest,error=None):
 rows=[]
 for row in manifest['segments']:
  rp=OUT/row['segment_id']/'receipt.json';r=execute.read(rp) if rp.exists() else {};rows.append({'segment_id':row['segment_id'],'task_id':r.get('task_id'),'technical_status':r.get('technical_status','not_submitted'),'content_status':r.get('content_status','not_available'),'video_path':r.get('video_path'),'usage':r.get('final',{}).get('usage')})
 p={'stage':'short_remake_media','segments':rows,'saved':sum(x['technical_status']=='succeeded' for x in rows),'remaining':sum(x['technical_status']!='succeeded' for x in rows),'error':error,'content_status':'awaiting_human_review','automatic_retry':False};persist(OUT/'PROGRESS.json',p);return p

def run(bundle):
 manifest,auth,asset=prepare(bundle);config=SeedanceConfig.from_env('ark_api',require_key=True)
 if config.model!=MODEL:raise ValueError('configured video model differs; do not switch')
 prior=None
 with SeedanceClient(config) as client:
  for definition in manifest['segments']:
   sid=definition['segment_id'];folder=OUT/sid;folder.mkdir(exist_ok=True);rp=folder/'receipt.json';pp=folder/'PLAN.json'
   if not rp.exists():
    plan=plan_for(manifest,definition,asset,prior);immutable(pp,plan);(folder/'PROMPT.txt').write_text(plan['prompt']+'\n',encoding='utf-8');execute.execute_segment(pp,folder,'preview',client);operation='submit'
   else:
    existing=execute.read(rp)
    if existing.get('technical_status')=='failed':raise ValueError('known failed segment; no automatic regeneration')
    if not existing.get('task_id'):raise ValueError('unknown outcome/no task ID; reconcile, never resubmit')
    operation='query'
   while True:
    try:r=execute.execute_segment(pp,folder,operation,client,wait_timeout=40)
    except TimeoutError:r=execute.read(rp)
    except Exception as exc:
     if rp.exists():
      r=execute.read(rp)
      if r.get('task_id'):
       try:
        t=client.get_task(r['task_id'])
        if t['status'] in ('failed','expired','cancelled'):r.update(final=t,technical_status='failed',status='failed');persist(rp,r)
       except Exception:pass
     progress(manifest,str(exc));raise
    stat=progress(manifest);print(json.dumps({'event':'segment_state','segment_id':sid,'task_id':r.get('task_id'),'technical_status':r.get('technical_status'),'saved':stat['saved'],'remaining':stat['remaining']},ensure_ascii=False),flush=True)
    if r.get('technical_status')=='succeeded':break
    if not r.get('task_id'):raise ValueError('no task ID; no repeat dispatch')
    operation='query'
   prior=rp
 print(json.dumps({'event':'all_saved','segments':len(manifest['segments'])},ensure_ascii=False),flush=True)

def assemble():
 m=execute.read(OUT/'BATCH_MANIFEST.json');auth=execute.read(OUT/'BATCH_USER_AUTHORIZATION.json')
 if auth['manifest_sha256']!=execute.sha(OUT/'BATCH_MANIFEST.json'):raise ValueError('scope changed')
 candidates=[];metadata=[];signature=None;duration=0
 for d in m['segments']:
  rp=OUT/d['segment_id']/'receipt.json';execute.validate(OUT/d['segment_id']/'PLAN.json');r=execute.read(rp);validate_source_bindings(r)
  if r['technical_status']!='succeeded' or r['content_status']!='awaiting_human_review' or execute.sha(r['video_path'])!=r['video_sha256']:raise ValueError('not intact unreviewed output')
  probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',r['video_path']],text=True,encoding='utf-8'));vs=[x for x in probe['streams'] if x['codec_type']=='video'];aus=[x for x in probe['streams'] if x['codec_type']=='audio']
  if len(vs)!=1 or len(aus)!=1:raise ValueError('source stream structure unexpected')
  v,a=vs[0],aus[0];sig=(v['codec_name'],v['width'],v['height'],v['r_frame_rate'],v.get('pix_fmt'),a['codec_name'],a['sample_rate'],a['channels'])
  if signature is not None and signature!=sig:raise ValueError('source streams differ')
  signature=sig;duration+=float(probe['format']['duration']);metadata.append({'segment_id':d['segment_id'],'metadata':probe});candidates.append({'receipt':str(rp),'receipt_sha256':execute.sha(rp),'video_path':r['video_path'],'video_sha256':r['video_sha256']})
 if duration>=180:raise ValueError('actual duration exceeds user requested3min; preserve sources')
 concat=OUT/'concat.txt';concat.write_text('\n'.join("file '"+x['video_path'].replace('\\','/').replace("'","'\\''")+"'" for x in candidates)+'\n',encoding='utf-8');out=OUT/'LEGAL_SHORT_FULL_REVIEW_v1.mp4'
 if out.exists():raise ValueError('existing assembly retained; do not overwrite')
 subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-n','-f','concat','-safe','0','-i',str(concat),'-map','0:v:0','-map','0:a:0','-c','copy','-movflags','+faststart',str(out)],check=True)
 final=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(out)],text=True,encoding='utf-8'));actual=float(final['format']['duration'])
 if abs(actual-duration)>.5 or actual>=180 or not out.stat().st_size:raise ValueError('assembly duration/storage mismatch')
 receipt={'schema':'legal_short_full_review_assembly/v1','technical_status':'succeeded','content_status':'awaiting_human_review','video_path':str(out),'video_sha256':execute.sha(out),'video_bytes':out.stat().st_size,'actual_duration_seconds':actual,'candidates':candidates,'metadata':final,'source_metadata':metadata,'source_duration_sum':duration,'assistant_content_inspected':False,'caption_track_added':False,'assembly':'stream copy, complete original segments, no trimming or speed change','batch_authorization_sha256':execute.sha(OUT/'BATCH_USER_AUTHORIZATION.json')};immutable(OUT/'ASSEMBLY_RECEIPT.json',receipt)
 print(json.dumps({'video_path':str(out),'seconds':actual,'segments':len(candidates),'content_status':'awaiting_human_review'},ensure_ascii=False),flush=True)

if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['prepare','run','assemble','status']);ap.add_argument('--bundle',default=str(DEFAULT));args=ap.parse_args();OUT.mkdir(parents=True,exist_ok=True);lock=OUT/'.batch.lock'
 with lock.open('x',encoding='utf-8') as f:f.write('exclusive short batch writer')
 try:
  if args.stage=='run':run(args.bundle)
  elif args.stage=='assemble':assemble()
  elif args.stage=='prepare':
   m,a,r=prepare(args.bundle);print(json.dumps({'segments':len(m['segments']),'service_seconds':m['planned_service_seconds'],'paid_calls':0},ensure_ascii=False),flush=True)
  else:print(json.dumps(progress(execute.read(OUT/'BATCH_MANIFEST.json')),ensure_ascii=False),flush=True)
 finally:lock.unlink()
