"""One local H3 comparison; preparation is offline, unknown submissions never replay."""
from __future__ import annotations
import argparse
import copy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.assistant_seedance_batch import durable,process_lock

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'data/video_generation/h3_six_children_s01_720p_20261102'
SOURCE=ROOT/'data/video_generation/h3_dense_office_trial_20261018/workflow_api.json'
SEEDANCE=ROOT/'data/video_generation/six_children_seedance_60s_20261102_trusted'
MODEL_ROOT=Path('D:/IT/AI_vido/ComfyUI/models')
URL='http://127.0.0.1:8190'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def binding(p):return dict(path=str(Path(p).resolve()),sha256=sha(p))
def now():return datetime.now(timezone.utc).isoformat()
def log(run,message):
    with (run/'LOG.md').open('a',encoding='utf-8') as f:f.write(now()+' '+message+'\n')
    print(message,flush=True)
def original_copy(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        if sha(source)!=sha(target):raise ValueError('existing_output_differs')
    else:shutil.copyfile(source,target)
    return binding(target)
def compile_graph(source,prompt):
    if len(source)!=20 or source['condition']['class_type']!='MiniMaxH3ImageToVideo':raise ValueError('wrong_source_graph')
    if source['127']['inputs']['unet_name']!='minimax_h3_fl2va_pruned_int8_convrot.safetensors' or source['124']['inputs']['steps']!=12:raise ValueError('wrong_source_model_or_steps')
    graph=copy.deepcopy(source)
    graph['condition']['inputs'].update(prompt=prompt,width=736,height=1312,length=362)
    graph['ref_scene']['inputs']['image']='opening.original.jpeg'
    graph['129']['inputs']['noise_seed']=2026110200
    for role in ('video','audio','first','last'):graph['save_'+role]['inputs']['filename_prefix']='S01/'+role
    return graph
def prepare(run=RUN):
    if (run/'PLAN.json').exists():raise ValueError('already_prepared')
    for name in ('input','output','deliverables'): (run/name).mkdir(parents=True,exist_ok=True)
    prompt=SEEDANCE/'segments/S01/PROMPT.txt';opening=SEEDANCE/'assets/opening.original.jpeg'
    original_copy(prompt,run/'PROMPT.txt');original_copy(opening,run/'input/opening.original.jpeg');original_copy(SOURCE,run/'SOURCE_GRAPH.json')
    graph=compile_graph(read(SOURCE),prompt.read_text(encoding='utf-8'))
    durable(run/'workflow_api.json',graph,immutable=True)
    model_paths=[MODEL_ROOT/'diffusion_models'/graph['127']['inputs']['unet_name'],MODEL_ROOT/'text_encoders'/graph['128']['inputs']['clip_name']]+[MODEL_ROOT/'vae'/graph[n]['inputs']['vae_name'] for n in ('119','120')]
    models=[dict(path=str(p),bytes=p.stat().st_size,mtime_ns=p.stat().st_mtime_ns) for p in model_paths]
    plan=dict(schema='h3_same_pixel_trial/v1',user_request='本地minimax的模型同像素跑下',
        scope='S01 only, one local generation, no cloud, no publish',source_prompt=binding(prompt),source_image=binding(opening),
        source_graph=binding(SOURCE),prompt=binding(run/'PROMPT.txt'),opening=binding(run/'input/opening.original.jpeg'),
        graph=binding(run/'workflow_api.json'),code=binding(__file__),models=models,
        native_width=736,native_height=1312,delivery_width=720,delivery_height=1280,length=362,fps=24,steps=12,
        crop='720:1280:8:16',automatic_retry=False,max_submissions=1,content_status='awaiting_human_review')
    durable(run/'PLAN.json',plan,immutable=True)
    durable(run/'STATE.json',dict(status='prepared',submissions=0,prompt_id=None,content_status='awaiting_human_review'))
    log(run,'PREPARED; no media submitted');return plan
def validate(run):
    plan=read(run/'PLAN.json')
    for key in ('source_prompt','source_image','source_graph','prompt','opening','graph','code'):
        item=plan[key]
        if sha(item['path'])!=item['sha256']:raise ValueError('frozen_input_changed:'+key)
    for row in plan['models']:
        st=Path(row['path']).stat()
        if st.st_size!=row['bytes'] or st.st_mtime_ns!=row['mtime_ns']:raise ValueError('model_file_changed')
    return plan
class Client:
    def __init__(self):self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def get(self,path):
        with self.opener.open(URL+path,timeout=60) as r:return json.load(r)
    def post(self,request):
        req=urllib.request.Request(URL+'/prompt',data=json.dumps(request,ensure_ascii=False).encode(),headers={'Content-Type':'application/json'})
        with self.opener.open(req,timeout=120) as r:return json.load(r)
def status(run=RUN):
    value=read(run/'STATE.json')
    if value.get('prompt_id'):
        c=Client();value['live_history']=c.get('/history/'+value['prompt_id']);value['live_queue']=c.get('/queue')
    print(json.dumps(value,ensure_ascii=False));return value
def preflight(run,client,plan):
    validation=read(run/'NATIVE_VALIDATION.json')
    if not validation.get('valid') or validation.get('node_errors') or validation.get('node_execution_performed') is not False or validation.get('graph_sha256')!=plan['graph']['sha256']:raise ValueError('native_validation_required')
    review=read(run/'PRIMARY_DISPATCH_REVIEW.json')
    if review.get('approved_for_single_submission') is not True or review.get('plan_sha256')!=sha(run/'PLAN.json') or review.get('native_validation_sha256')!=sha(run/'NATIVE_VALIDATION.json'):raise ValueError('primary_review_required')
    stats=client.get('/system_stats');argv=stats['system']['argv']
    for flag,name in [('--input-directory','input'),('--output-directory','output')]:
        if flag not in argv or Path(argv[argv.index(flag)+1]).resolve()!=(run/name).resolve():raise ValueError('wrong_service_paths')
    if '--offline' not in argv or '--disable-all-custom-nodes' not in argv:raise ValueError('wrong_service_mode')
    queue=client.get('/queue')
    if queue.get('queue_running') or queue.get('queue_pending'):raise ValueError('service_busy')
    durable(run/'SERVICE_PREFLIGHT.json',dict(system_stats=stats,queue=queue,at=now()),immutable=True)
def execute(run=RUN,client=None,sleep=time.sleep,collect_fn=None):
    client=client or Client();collect_fn=collect_fn or collect
    with process_lock(run/'.run.lock'):
        plan=validate(run);state=read(run/'STATE.json')
        if state['status']=='saved':return state
        if state['status'] in ('failed','request_rejected'):raise ValueError('terminal_attempt_not_replayed')
        if not state.get('prompt_id') and (run/'SUBMISSION_RESPONSE.json').exists():
            response=read(run/'SUBMISSION_RESPONSE.json')
            if response.get('prompt_id'):state.update(prompt_id=response['prompt_id'],status='submitted');durable(run/'STATE.json',state)
        if not state.get('prompt_id'):
            if (run/'SUBMISSION_CLAIM.json').exists():raise ValueError('unknown_submission_not_replayed')
            preflight(run,client,plan)
            request=dict(prompt=read(run/'workflow_api.json'),client_id=str(uuid.uuid4()))
            durable(run/'REQUEST.actual.json',request,immutable=True)
            durable(run/'SUBMISSION_CLAIM.json',dict(at=now(),request=binding(run/'REQUEST.actual.json'),plan=binding(run/'PLAN.json')),immutable=True)
            state.update(status='submit_outcome_unknown',submissions=1);durable(run/'STATE.json',state)
            response=client.post(request);durable(run/'SUBMISSION_RESPONSE.json',response,immutable=True)
            if not response.get('prompt_id') or response.get('node_errors'):
                state['status']='request_rejected';durable(run/'STATE.json',state);raise ValueError('submission_not_accepted')
            state.update(status='submitted',prompt_id=response['prompt_id']);durable(run/'STATE.json',state)
            (run/'job_ids.txt').write_text(state['prompt_id']+'\n',encoding='utf-8');log(run,'SUBMITTED '+state['prompt_id'])
        deadline=time.monotonic()+14400
        while True:
            history=client.get('/history/'+state['prompt_id'])
            if history:
                durable(run/'HISTORY.latest.json',history)
                entry=history.get(state['prompt_id'])
                if entry:
                    if entry['prompt'][1]!=state['prompt_id'] or entry['prompt'][2]!=read(run/'workflow_api.json'):raise ValueError('history_identity_mismatch')
                    if entry['status']['status_str']=='error':
                        state['status']='failed';durable(run/'STATE.json',state);raise ValueError('native_execution_failed')
                    if entry['status'].get('completed') and entry['status']['status_str']=='success':
                        durable(run/'HISTORY.json',history,immutable=True);return collect_fn(run,entry,state)
            if time.monotonic()>deadline:raise TimeoutError('original_id_retained')
            queue=client.get('/queue');durable(run/'QUEUE.latest.json',dict(at=now(),queue=queue));sleep(30)
def metadata(path):
    return json.loads(subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,text=True,check=True).stdout)
def collect(run,entry,state):
    files={}
    for role,kind,suffix in [('video','images','mp4'),('audio','audio','flac'),('first','images','png'),('last','images','png')]:
        rows=entry['outputs']['save_'+role][kind]
        if len(rows)!=1 or rows[0]['type']!='output':raise ValueError('unexpected_output')
        row=rows[0];source=(run/'output'/row.get('subfolder','')/row['filename']).resolve()
        if not source.is_relative_to((run/'output').resolve()):raise ValueError('output_escape')
        files[role]=dict(original_service_path=str(source),**original_copy(source,run/f'native_{role}.{suffix}'))
    native=metadata(files['video']['path']);video=next(s for s in native['streams'] if s['codec_type']=='video');audio=next(s for s in native['streams'] if s['codec_type']=='audio')
    if (video['width'],video['height'],int(video['nb_frames']),video['r_frame_rate'])!=(736,1312,362,'24/1'):raise ValueError('unexpected_native_dimensions')
    durable(run/'NATIVE_METADATA.json',native,immutable=True)
    target=run/'deliverables/S01_h3_720x1280_with_audio.mp4'
    if not target.exists():
        command=['ffmpeg','-nostdin','-v','warning','-i',files['video']['path'],'-vf','crop=720:1280:8:16','-c:v','libx264','-crf','18','-preset','medium','-c:a','copy','-movflags','+faststart',str(target)]
        durable(run/'CROP_COMMAND.json',command,immutable=True)
        result=subprocess.run(command,capture_output=True,text=True);(run/'crop.stderr.log').write_text(result.stderr,encoding='utf-8');result.check_returncode()
    delivery=metadata(target);v=next(s for s in delivery['streams'] if s['codec_type']=='video');a=next(s for s in delivery['streams'] if s['codec_type']=='audio')
    if (v['width'],v['height'],int(v['nb_frames']))!=(720,1280,362):raise ValueError('unexpected_delivery_dimensions')
    receipt=dict(prompt_id=state['prompt_id'],technical_status='succeeded',content_status='awaiting_human_review',files=files,delivery=binding(target),native_metadata=native,delivery_metadata=delivery,video_content_reviewed=False)
    durable(run/'receipt.json',receipt,immutable=True);state.update(status='saved',delivery=str(target.resolve()));durable(run/'STATE.json',state);log(run,'SAVED '+str(target));return state
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','status','execute']);p.add_argument('--run',type=Path,default=RUN);a=p.parse_args();globals()[a.command](a.run)
