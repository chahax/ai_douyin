"""One authorized 768x416/12-step H3 trial; a claim never becomes another POST."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from fractions import Fraction
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from . import assistant_h3_full_batch as helpers
from .assistant_seedance_batch import durable, process_lock
from .h3_positive_prompt_v2 import validate_references

ROOT=helpers.ROOT
OUT=ROOT/'data/video_generation/h3_positive_speed_trial_20261018'
SOURCE=ROOT/'data/video_generation/h3_positive_revision_20261018'
MEDIA_ROOT=ROOT/'data/local_media_tests/minimax_h3_20261015'
INPUT_ROOT=MEDIA_ROOT/'input'
OUTPUT_ROOT=MEDIA_ROOT/'output'
PREFIX='h3_positive_speed_trial_20261018/S01'
SOURCE_SHA='44f4e5cade5e926c6d9940af2084aaa278485f0171b11faeebea5cd7dcbc77dd'
GLOBAL_CLAIM=ROOT/'data/video_generation/h3_project_script_20261015/H3_SPEED_TRIAL_20261018_PERMANENT_CLAIM.json'
VALIDATOR=ROOT/'data/video_generation/h3_assistant_screenplay_full_20261016/runtime/validate_graph.py'
SCRIPT=ROOT/'scripts/run_h3_positive_speed_trial_20261018.py'
read,sha,bound,binding,now=helpers.read,helpers.sha,helpers.bound,helpers.binding,helpers.now


def environment():
    configured=read(MEDIA_ROOT/'SERVER_STARTED.json')['cache_env']
    env=os.environ.copy()
    for key,value in configured.items():
        helpers.checked_d(value)
        Path(value).mkdir(parents=True,exist_ok=True)
        env[key]=value
    env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    return env


def recipe():
    return dict(schema='h3_single_speed_trial_recipe/v1',source_graph_sha256=SOURCE_SHA,
                named_parameters=['width','height','steps','noise_seed','output_prefix'],
                fixed=dict(width=768,height=416,steps=12,fps=24,length=362,turbo_lora=False),
                input_mode='three_original_images_native_audio_output',
                source_nodes=22,automatic_retry=False)


def compile_graph(source,source_recipe,parameters):
    if source_recipe!=recipe() or set(parameters)!=set(source_recipe['named_parameters']):
        raise ValueError('exact source recipe and named parameter keys required')
    if ([parameters[key] for key in ('width','height','steps')]!=[768,416,12]
            or parameters['output_prefix']!=PREFIX or type(parameters['noise_seed']) is not int
            or parameters['noise_seed']<0):
        raise ValueError('only the authorized speed trial parameters are allowed')
    if (len(source)!=22 or source['condition']['class_type']!='MiniMaxH3ReferenceToVideo'
            or [source['condition']['inputs'][key] for key in ('width','height','length')]!=[1280,704,362]
            or source['124']['inputs']['steps']!=20 or source['130']['inputs']['fps']!=24
            or source['123']['inputs']['sampler_name']!='res_multistep'
            or source['124']['inputs']['scheduler']!='simple'
            or source['127']['inputs']['unet_name']!='minimax_h3_ref2va_pruned_int8_convrot.safetensors'
            or any(node['class_type'] in ('LoadAudio','MiniMaxH3AddGuide') or 'lora' in node['class_type'].lower() for node in source.values())
            or any('ref_audio' in key or key=='audio_vae' for key in source['condition']['inputs'])
            or source['126']['inputs']['conditioning']!=['condition',0]
            or source['125']['inputs']['latent_image']!=['condition',1]
            or source['130']['inputs']['audio']!=['121',0]
            or source['121']['class_type']!='VAEDecodeAudio'):
        raise ValueError('source is not the frozen reference-only native-audio S01 graph')
    graph=copy.deepcopy(source)
    graph['condition']['inputs'].update(width=768,height=416)
    graph['124']['inputs']['steps']=12
    graph['129']['inputs']['noise_seed']=parameters['noise_seed']
    for role in ('video','audio','first','last'):
        graph['save_'+role]['inputs']['filename_prefix']=PREFIX+'/'+role
    return graph


def same_story_count(auth,out):
    policy=auth['failure_accounting']
    if (policy.get('reset') is not False or policy.get('limit')!=10
            or policy.get('known_same_story_human_rejections')!=2):
        raise ValueError('same story rejection history cannot reset or become unknown')
    for evidence in policy['evidence']:
        bound(evidence)
    old_plan=read(helpers.OUT/'BATCH_PLAN.json')
    inherited=helpers.failure_count(old_plan,helpers.OUT)
    # The old ledger retains the first rejection; the completed H3 rejection adds one.
    if inherited!=1:
        raise ValueError('historical same-story failures changed; explicit reconciliation required')
    count=inherited+1
    path=out/'MEDIA_EVENTS.json'
    if path.exists():
        events=read(path)['events']
        if any(type(event.get('failure')) is not bool for event in events):
            raise ValueError('unknown current technical failure count')
        count+=sum(event['failure'] for event in events)
    if count>=10:
        raise ValueError('same story failure limit exhausted')
    return count


def admission(out=OUT):
    helpers.checked_d(out)
    auth=read(out/'AUTHORIZATION.json')
    if (auth.get('schema')!='h3_single_speed_trial_authorization/v1' or auth.get('user_message')!='再来一段试试'
            or auth.get('story_id')!=helpers.STORY_ID or auth.get('segment_id')!='S01'
            or auth.get('max_new_video_submissions')!=1 or auth.get('max_submissions_per_segment')!=1
            or auth.get('automatic_retry') is not False or auth.get('automatic_fallback') is not False
            or auth.get('following_segment_authorized') is not False or auth.get('publishing_authorized') is not False
            or auth.get('local_only') is not True or auth.get('new_software_or_models') is not False
            or auth.get('human_content_approved') is not False):
        raise ValueError('exact one-sample local authorization required')
    p=auth['parameters']
    if [p[key] for key in ('width','height','steps','fps','length','requested_story_seconds','turbo_lora')]!=[768,416,12,24,362,15,False]:
        raise ValueError('authorized resolution, steps or temporal grid changed')
    bound(auth['plan'])
    for row in auth['source_bindings'].values():
        bound(row)
    if auth['source_bindings']['graph']['sha256']!=SOURCE_SHA:
        raise ValueError('wrong positive S01 source graph')
    source=read(auth['source_bindings']['graph']['path'])
    if source['condition']['inputs']['prompt']!=bound(auth['source_bindings']['prompt']).read_text(encoding='utf-8'):
        raise ValueError('source prompt and graph disagree')
    refs=read(auth['source_bindings']['references']['path']);validate_references(refs)
    for row,node in zip(refs,('ref_scene','ref_C01','ref_C02')):
        staged=(INPUT_ROOT/source[node]['inputs']['image']).resolve()
        if not staged.is_relative_to(INPUT_ROOT.resolve()) or sha(staged)!=row['source']['sha256']:
            raise ValueError('original staged reference identity changed')
        if source[node]['inputs']['image']!=row['staged_image_relative_path']:
            raise ValueError('reference socket order differs from reviewed map')
    same_story_count(auth,out)
    return auth,source


def state(out=OUT):
    receipt=out/'receipt.json'
    if receipt.exists():
        row=read(receipt)
        if row.get('technical_status')=='succeeded':return 'saved',row
        if row.get('technical_status')=='failed':raise ValueError('known service failure; no media retry')
        if row.get('prompt_id'):return 'query',row
    response=out/'SUBMISSION_RESPONSE.json'
    if response.exists() and read(response).get('prompt_id'):
        return 'query',dict(prompt_id=read(response)['prompt_id'],technical_status='pending')
    if (out/'SUBMISSION_CLAIM.json').exists() or GLOBAL_CLAIM.exists():
        raise ValueError('permanent claim without known original ID; unknown outcome must not be re-POSTed')
    return 'new',None


def prepare(out=OUT):
    action,_=state(out)
    if action!='new':raise ValueError('existing trial task found; prepare cannot replace or dispatch it')
    auth,source=admission(out)
    parameters=dict(width=768,height=416,steps=12,noise_seed=202610181601,output_prefix=PREFIX)
    graph=compile_graph(source,recipe(),parameters)
    helpers.copy_original(bound(auth['source_bindings']['graph']),out/'SOURCE_GRAPH_CAPTURE.json')
    durable(out/'SOURCE_RECIPE.json',recipe(),immutable=True)
    durable(out/'PARAMETERS.json',parameters,immutable=True)
    durable(out/'workflow_api.json',graph,immutable=True)
    prepared=dict(schema='h3_single_speed_trial_preparation/v1',authorization=binding(out/'AUTHORIZATION.json'),
                  sources=auth['source_bindings'],source_graph_capture=binding(out/'SOURCE_GRAPH_CAPTURE.json'),
                  source_recipe=binding(out/'SOURCE_RECIPE.json'),parameters=binding(out/'PARAMETERS.json'),
                  graph=binding(out/'workflow_api.json'),validator=binding(VALIDATOR),
                  source_primary_review=binding(SOURCE/'PRIMARY_VERIFICATION.json'),
                  server_configuration=binding(MEDIA_ROOT/'SERVER_STARTED.json'),
                  known_same_story_failures=same_story_count(auth,out),media_submissions=0)
    durable(out/'PREPARED.json',prepared,immutable=True)
    return dict(status='prepared_not_submitted',graph=prepared['graph'],media_submissions=0)


def validate_native(out=OUT):
    prepared=read(out/'PREPARED.json')
    command=['D:/IT/AI_vido/ComfyUI/.venv/Scripts/python.exe','-B',str(bound(prepared['validator'])),
             '--graph',str(bound(prepared['graph'])),'--report',str(out/'NATIVE_VALIDATION.json'),'--input-root',str(INPUT_ROOT)]
    with (out/'native_validate.stdout.log').open('w',encoding='utf-8') as stdout,(out/'native_validate.stderr.log').open('w',encoding='utf-8') as stderr:
        result=subprocess.run(command,cwd='D:/IT/AI_vido/ComfyUI',stdout=stdout,stderr=stderr,env=environment(),timeout=600)
    report=read(out/'NATIVE_VALIDATION.json')
    if (result.returncode or report.get('valid') is not True or report.get('node_errors')
            or report.get('graph_sha256')!=prepared['graph']['sha256'] or report.get('node_execution_performed') is not False):
        raise ValueError('native validator rejected the actual graph')
    return dict(status='native_validation_passed',graph_sha256=report['graph_sha256'],media_submissions=0)


def review_gate(out=OUT):
    prepared=read(out/'PREPARED.json')
    for key in ('authorization','source_graph_capture','source_recipe','parameters','graph','validator','source_primary_review','server_configuration'):
        bound(prepared[key])
    report=read(out/'NATIVE_VALIDATION.json')
    if (report.get('valid') is not True or report.get('node_errors') or report.get('node_execution_performed') is not False
            or report['graph_sha256']!=prepared['graph']['sha256']):
        raise ValueError('exact graph native validation missing')
    expected=dict(runner_sha256=sha(__file__),cli_sha256=sha(SCRIPT),authorization_sha256=prepared['authorization']['sha256'],
                  prepared_sha256=sha(out/'PREPARED.json'),graph_sha256=prepared['graph']['sha256'],
                  source_recipe_sha256=prepared['source_recipe']['sha256'],native_validation_sha256=sha(out/'NATIVE_VALIDATION.json'))
    review=read(out/'PRIMARY_TRIAL_REVIEW.json')
    if review.get('approved_for_single_submission') is not True or any(review.get(key)!=value for key,value in expected.items()):
        raise ValueError('primary review does not bind exact authorized trial runtime and graph')
    return prepared


def log(out,kind,*,prompt_id=None,failure=False):
    path=out/'MEDIA_EVENTS.json'
    events=read(path) if path.exists() else dict(story_id=helpers.STORY_ID,trial_id='h3_positive_speed_trial_20261018',inherited_failures=2,failure_limit=10,events=[])
    events['events'].append(dict(at=now(),kind=kind,prompt_id=prompt_id,failure=failure))
    durable(path,events)
    print(json.dumps(dict(event=kind,prompt_id=prompt_id)),flush=True)


def check_service(client,out):
    stats=client.get('/system_stats');argv=stats['system']['argv']
    for flag,value in (('--input-directory',str(INPUT_ROOT)),('--output-directory',str(OUTPUT_ROOT))):
        if flag not in argv or Path(argv[argv.index(flag)+1]).resolve()!=Path(value).resolve():
            raise ValueError('live service uses a different input/output root')
    if '--offline' not in argv or '--disable-all-custom-nodes' not in argv:
        raise ValueError('live service offline/core mode changed')
    queue=client.get('/queue')
    if queue.get('queue_running') or queue.get('queue_pending'):
        raise ValueError('generation queue is occupied; do not interrupt or add a trial')
    durable(out/'SERVICE_PREFLIGHT.json',dict(at=now(),system_stats=stats,queue=queue))


def submit_once(client,out=OUT):
    if state(out)[0]!='new':raise ValueError('a trial state already exists; never repeat POST')
    auth,source=admission(out);prepared=review_gate(out)
    check_service(client,out)
    graph=read(bound(prepared['graph']))
    expected=compile_graph(source,read(bound(prepared['source_recipe'])),read(bound(prepared['parameters'])))
    if graph!=expected:raise ValueError('actual graph differs from named compiler output')
    if (out/'STOP_REQUESTED.json').exists():raise ValueError('stop requested before trial POST')
    request=dict(prompt=graph,client_id=str(uuid.uuid4()))
    durable(out/'REQUEST.actual.json',request,immutable=True)
    claim=dict(at=now(),story_id=helpers.STORY_ID,max_posts=1,authorization=prepared['authorization'],
               prepared=binding(out/'PREPARED.json'),actual_request=binding(out/'REQUEST.actual.json'),
               primary_review=binding(out/'PRIMARY_TRIAL_REVIEW.json'),graph=prepared['graph'],automatic_retry=False)
    GLOBAL_CLAIM.parent.mkdir(parents=True,exist_ok=True)
    if GLOBAL_CLAIM.exists():raise ValueError('permanent revision claim exists')
    durable(GLOBAL_CLAIM,claim,immutable=True)
    durable(out/'SUBMISSION_CLAIM.json',claim,immutable=True)
    log(out,'dispatch_reserved')
    if (out/'STOP_REQUESTED.json').exists():raise ValueError('stop requested after claim; no POST performed')
    admission(out);review_gate(out)
    try:
        response=client.post_graph(request)
    except Exception as exc:
        durable(out/'UNKNOWN_SUBMISSION.json',dict(at=now(),error_type=type(exc).__name__,error=str(exc),automatic_retry=False))
        raise
    durable(out/'SUBMISSION_RESPONSE.json',response,immutable=True)
    pid=response.get('prompt_id')
    if not pid or response.get('node_errors'):
        raise ValueError('no usable original task ID; preserve evidence without re-POST')
    durable(out/'job_ids.json',{'S01':pid})
    row=dict(schema='h3_single_speed_trial_receipt/v1',story_id=helpers.STORY_ID,segment_id='S01',prompt_id=pid,
             submitted_at=claim['at'],technical_status='pending',content_status='awaiting_human_review',content_review=None,
             authorization=prepared['authorization'],sources=prepared['sources'],graph=prepared['graph'])
    durable(out/'receipt.json',row);log(out,'submitted',prompt_id=pid)
    return row


def probe(path,audio_only=False):
    fields='stream=codec_type,codec_name,width,height,avg_frame_rate,nb_frames,nb_read_packets,sample_rate,channels,duration:format=duration,size'
    command=['ffprobe','-v','error','-count_packets','-show_entries',fields,'-of','json',str(path)]
    result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=180,env=environment())
    if result.returncode:raise ValueError('native file packet/container integrity check failed')
    metadata=json.loads(result.stdout);streams=metadata['streams']
    video=[row for row in streams if row['codec_type']=='video'];audio=[row for row in streams if row['codec_type']=='audio']
    if len(audio)!=1 or any(int(row.get('nb_read_packets',0))<=0 for row in video+audio):
        raise ValueError('native audio/video packets are absent')
    if audio_only:
        if video or audio[0]['codec_name']!='flac':raise ValueError('original native FLAC required')
    elif (len(video)!=1 or [video[0].get(k) for k in ('width','height')]!=[768,416]
          or int(video[0].get('nb_frames',0))!=362 or Fraction(video[0]['avg_frame_rate'])!=24):
        raise ValueError('output resolution or 362-frame/24fps grid differs')
    if abs(float(metadata['format']['duration'])-362/24)>.6:raise ValueError('native duration differs')
    return metadata


def collect(client,out=OUT):
    action,row=state(out)
    if action=='new':raise ValueError('trial has not been submitted')
    if action=='saved':
        for item in row['files'].values():bound(item)
        bound(row['delivery']);return row
    pid=row['prompt_id'];response=client.get('/history/'+pid)
    if pid not in response:return dict(row,technical_status='pending')
    prepared=read(out/'PREPARED.json');graph=read(bound(prepared['graph']));entry=response[pid]
    identity=helpers.history_graph_identity(graph,entry,pid)
    durable(out/'HISTORY.json',response)
    row.update(schema='h3_single_speed_trial_receipt/v1',story_id=helpers.STORY_ID,segment_id='S01',
               submitted_at=read(out/'SUBMISSION_CLAIM.json')['at'],authorization=prepared['authorization'],
               sources=prepared['sources'],graph=prepared['graph'],history=binding(out/'HISTORY.json'),graph_identity=identity,
               content_status='awaiting_human_review',content_review=None)
    if not helpers.check_history_success(entry):
        row.update(technical_status='failed');durable(out/'receipt.json',row);log(out,'service_failed',prompt_id=pid,failure=True)
        raise ValueError('known service failure; no automatic media retry')
    files={}
    for role,node,field,extension in (('video','save_video','images','.mp4'),('audio','save_audio','audio','.flac'),
                                      ('first','save_first','images','.png'),('last','save_last','images','.png')):
        items=entry['outputs'][node][field]
        if len(items)!=1:raise ValueError('ambiguous service original output')
        original=helpers.service_file(dict(output_root=str(OUTPUT_ROOT)),items[0],PREFIX+'/'+role)
        if original.suffix.lower()!=extension:raise ValueError('unexpected original output encoding')
        metadata=probe(original,role=='audio') if role in ('video','audio') else helpers.png_integrity(original)
        if role in ('first','last') and (metadata['width'],metadata['height'])!=(768,416):raise ValueError('native PNG dimensions differ')
        local=helpers.copy_original(original,out/('native_'+role+extension))
        files[role]=dict(**binding(local),bytes=local.stat().st_size,original_service_path=str(original),metadata=metadata)
    delivered=helpers.copy_original(files['video']['path'],out/'deliverables/S01_768x416_12step_with_audio.mp4')
    timestamps={}
    for message in entry['status'].get('messages',[]):
        if len(message)==2 and message[0] in ('execution_start','execution_success'):
            timestamps[message[0]]=message[1].get('timestamp')
    elapsed=None
    if all(type(timestamps.get(key)) in (int,float) for key in ('execution_start','execution_success')):
        elapsed=(timestamps['execution_success']-timestamps['execution_start'])/1000
    row.update(technical_status='succeeded',files=files,delivery=binding(delivered),saved_at=now(),
               wall_elapsed_seconds=(datetime.now(timezone.utc)-datetime.fromisoformat(row['submitted_at'])).total_seconds(),
               service_execution_elapsed_seconds=elapsed,service_timing_evidence=timestamps,
               pixels_decoded=False,frame_extraction=False,listened=False,ASR=False)
    durable(out/'receipt.json',row);log(out,'saved_awaiting_human_review',prompt_id=pid)
    return row


def run(client,out=OUT,timeout=21600,poll=30):
    if timeout<14400 or poll<1:raise ValueError('allow at least four hours and a positive polling interval')
    with process_lock(out/'.single_trial.lock'),process_lock(GLOBAL_CLAIM.with_suffix('.lock')):
        action,row=state(out)
        if action=='new':row=submit_once(client,out)
        started=time.monotonic()
        while True:
            row=collect(client,out)
            if row['technical_status']=='succeeded':return row
            durable(out/'STATUS.json',dict(at=now(),phase='original_id_pending',prompt_id=row['prompt_id']))
            print(json.dumps(dict(status='pending',prompt_id=row['prompt_id'])),flush=True)
            if time.monotonic()-started>=timeout:raise TimeoutError('original ID remains pending; no repeated POST')
            time.sleep(poll)


def status(client,out=OUT):
    action,row=state(out);result=dict(local_state=action,media_submissions=0)
    if row and row.get('prompt_id'):
        pid=row['prompt_id'];response=client.get('/history/'+pid)
        result.update(prompt_id=pid,service_status=response.get(pid,{}).get('status',{}))
    return result
