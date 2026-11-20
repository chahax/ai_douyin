"""One native FL2VA first-frame trial; independent controls, original-ID recovery."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from . import h3_positive_speed_trial_v1 as speed
from .assistant_seedance_batch import durable, process_lock

h=speed.helpers
ROOT=h.ROOT
OUT=ROOT/'data/video_generation/h3_dense_office_trial_20261018'
PREFIX='h3_dense_office_trial_20261018/S01'
SOURCE_SHA='d0e702e849136d2bbfbac7da5f4b69e0afe1a55759a4e3331978b6cd778c21b0'
MODEL='minimax_h3_fl2va_pruned_int8_convrot.safetensors'
MODEL_PATH=Path('D:/IT/AI_vido/ComfyUI/models/diffusion_models')/MODEL
GLOBAL_CLAIM=ROOT/'data/video_generation/h3_project_script_20261015/H3_DENSE_OFFICE_20261018_PERMANENT_CLAIM.json'
SCRIPT=ROOT/'scripts/run_h3_dense_office_trial_20261018.py'
INPUT_ROOT=speed.INPUT_ROOT
OUTPUT_ROOT=speed.OUTPUT_ROOT
read,sha,bound,binding,now=h.read,h.sha,h.bound,h.binding,h.now


def recipe():
    return dict(schema='h3_dense_office_first_frame_recipe/v1',source_graph_sha256=SOURCE_SHA,
                named_parameters=['prompt','opening_frame_input','noise_seed','output_prefix'],
                input_mode='MiniMaxH3ImageToVideo.first_frame',model=MODEL,
                fixed=dict(width=768,height=416,steps=12,length=362,fps=24,native_audio=True),
                remove_source_nodes=['ref_C01','ref_C02'],input_images=1,compiled_nodes=20,
                reference_audio_input=False,previous_clip_tail_input=False,turbo_lora=False)


def compile_graph(source,source_recipe,parameters):
    if source_recipe!=recipe() or set(parameters)!=set(source_recipe['named_parameters']):
        raise ValueError('exact office first-frame source recipe required')
    if (len(source)!=22 or source['condition']['class_type']!='MiniMaxH3ReferenceToVideo'
            or source['127']['inputs']['unet_name']!='minimax_h3_ref2va_pruned_int8_convrot.safetensors'
            or [source['condition']['inputs'][key] for key in ('width','height','length')]!=[768,416,362]
            or source['124']['inputs']['steps']!=12 or source['130']['inputs']['fps']!=24
            or source['123']['inputs']['sampler_name']!='res_multistep' or source['124']['inputs']['scheduler']!='simple'
            or source['130']['inputs']['audio']!=['121',0]
            or source['126']['inputs']['conditioning']!=['condition',0]
            or source['125']['inputs']['latent_image']!=['condition',1]):
        raise ValueError('wrong successful low-resolution source graph')
    relative=parameters['opening_frame_input']
    if relative!='h3_dense_office_trial_20261018/opening_frame.png' or parameters['output_prefix']!=PREFIX:
        raise ValueError('only this trial complete opening image and output prefix allowed')
    if not isinstance(parameters['prompt'],str) or not parameters['prompt'].strip() or type(parameters['noise_seed']) is not int:
        raise ValueError('exact authored prompt and integer seed required')
    graph=copy.deepcopy(source)
    graph.pop('ref_C01');graph.pop('ref_C02')
    graph['ref_scene']['inputs']['image']=relative
    graph['condition']=dict(class_type='MiniMaxH3ImageToVideo',inputs=dict(
        clip=source['condition']['inputs']['clip'],vae=source['condition']['inputs']['vae'],
        prompt=parameters['prompt'],width=768,height=416,length=362,first_frame=['ref_scene',0]))
    graph['127']['inputs']['unet_name']=MODEL
    graph['129']['inputs']['noise_seed']=parameters['noise_seed']
    for role in ('video','audio','first','last'):
        graph['save_'+role]['inputs']['filename_prefix']=PREFIX+'/'+role
    if (len(graph)!=20 or any(node['class_type'] in ('LoadAudio','MiniMaxH3AddGuide') or 'lora' in node['class_type'].lower() for node in graph.values())
            or len([node for node in graph.values() if node['class_type']=='LoadImage'])!=1):
        raise ValueError('single-frame graph includes an extra reference, tail guide or audio input')
    return graph


def failure_count(auth,out):
    if (auth.get('failure_reset') is not False or auth.get('failure_limit')!=10
            or auth.get('known_same_story_failures')!=3):
        raise ValueError('same-story three failures must remain known and unreset')
    for item in auth['failure_evidence']:bound(item)
    prior=speed.same_story_count(read(speed.OUT/'AUTHORIZATION.json'),speed.OUT)
    if prior!=2:raise ValueError('prior same-story failure count changed')
    count=prior+1
    if (out/'MEDIA_EVENTS.json').exists():
        events=read(out/'MEDIA_EVENTS.json')['events']
        if any(type(row.get('failure')) is not bool for row in events):raise ValueError('unknown trial failure count')
        count+=sum(row['failure'] for row in events)
    if count>=10:raise ValueError('same-story failure limit exhausted')
    return count


def admission(out=OUT):
    auth=read(out/'AUTHORIZATION.json')
    if (auth.get('schema')!='h3_dense_office_single_authorization/v1' or auth.get('user_message')!='用这个生成'
            or auth.get('story_id')!=h.STORY_ID or auth.get('segment_id')!='S01'
            or auth.get('max_new_video_submissions')!=1 or auth.get('automatic_retry') is not False
            or auth.get('automatic_fallback') is not False or auth.get('following_segment_authorized') is not False
            or auth.get('publishing_authorized') is not False or auth.get('local_video_only') is not True
            or auth.get('new_models_or_dependencies') is not False or auth.get('human_content_approved') is not False
            or auth.get('input_mode')!='native_H3_FL2VA_first_frame_from_complete_opening_image'):
        raise ValueError('exact one-video complete-opening-image authorization required')
    if auth['parameters']!=dict(width=768,height=416,steps=12,fps=24,length=362,native_audio=True,turbo_lora=False):
        raise ValueError('office trial grid or native-audio settings changed')
    for item in auth['source_bindings'].values():bound(item)
    for item in auth['opening_image_references']:bound(item['image'])
    if auth['prior_successful_low_res_graph']['sha256']!=SOURCE_SHA:raise ValueError('wrong prior successful graph')
    source=read(bound(auth['prior_successful_low_res_graph']))
    if not MODEL_PATH.is_file():raise ValueError('authorized local FL2VA model is unavailable; no download or fallback')
    failure_count(auth,out)
    return auth,source


def opening_binding(auth,out):
    receipt=read(out/'OPENING_IMAGE_RECEIPT.json')
    if (receipt.get('authorization')!=binding(out/'AUTHORIZATION.json') or receipt.get('generation_status')!='succeeded'
            or receipt.get('selection')!='assistant_prepared_within_current_request_not_human_approval'
            or receipt.get('human_approved') is not False):
        raise ValueError('complete opening image provenance or current request scope missing')
    image=bound(receipt['image']);h.checked_d(image)
    if image.resolve()!=(out/'opening_frame.png').resolve():raise ValueError('only the newly prepared full opening PNG is allowed')
    h.png_integrity(image)
    return receipt['image']


def state(out=OUT):
    if (out/'receipt.json').exists():
        row=read(out/'receipt.json')
        if row.get('technical_status')=='succeeded':return 'saved',row
        if row.get('technical_status')=='failed':raise ValueError('known service failure; no retry')
        if row.get('prompt_id'):return 'query',row
    if (out/'SUBMISSION_RESPONSE.json').exists() and read(out/'SUBMISSION_RESPONSE.json').get('prompt_id'):
        return 'query',dict(prompt_id=read(out/'SUBMISSION_RESPONSE.json')['prompt_id'],technical_status='pending')
    if (out/'SUBMISSION_CLAIM.json').exists() or GLOBAL_CLAIM.exists():
        raise ValueError('claim without known original ID; unknown request cannot be re-POSTed')
    return 'new',None


def prepare(out=OUT):
    if state(out)[0]!='new':raise ValueError('existing trial state; prepare cannot replace it')
    auth,source=admission(out);image=opening_binding(auth,out)
    relative='h3_dense_office_trial_20261018/opening_frame.png'
    staged=h.copy_original(bound(image),INPUT_ROOT/relative)
    parameters=dict(prompt=bound(auth['source_bindings']['prompt']).read_text(encoding='utf-8'),
                    opening_frame_input=relative,noise_seed=202610181751,output_prefix=PREFIX)
    graph=compile_graph(source,recipe(),parameters)
    h.copy_original(bound(auth['prior_successful_low_res_graph']),out/'SOURCE_GRAPH_CAPTURE.json')
    durable(out/'SOURCE_RECIPE.json',recipe(),immutable=True)
    durable(out/'PARAMETERS.json',parameters,immutable=True)
    durable(out/'workflow_api.json',graph,immutable=True)
    prepared=dict(schema='h3_dense_office_single_preparation/v1',authorization=binding(out/'AUTHORIZATION.json'),
                  sources=auth['source_bindings'],opening_image_receipt=binding(out/'OPENING_IMAGE_RECEIPT.json'),
                  opening_image=image,staged_opening_image=binding(staged),
                  source_graph_capture=binding(out/'SOURCE_GRAPH_CAPTURE.json'),source_recipe=binding(out/'SOURCE_RECIPE.json'),
                  parameters=binding(out/'PARAMETERS.json'),graph=binding(out/'workflow_api.json'),
                  validator=binding(speed.VALIDATOR),model=dict(path=str(MODEL_PATH),bytes=MODEL_PATH.stat().st_size),
                  server_configuration=binding(speed.MEDIA_ROOT/'SERVER_STARTED.json'),
                  known_same_story_failures=failure_count(auth,out),media_submissions=0)
    durable(out/'PREPARED.json',prepared,immutable=True)
    return dict(status='prepared_not_submitted',graph=prepared['graph'],nodes=len(graph),media_submissions=0)


def validate_native(out=OUT):
    return speed.validate_native(out)


def review_gate(out=OUT):
    prepared=read(out/'PREPARED.json')
    for key in ('authorization','opening_image_receipt','opening_image','staged_opening_image','source_graph_capture',
                'source_recipe','parameters','graph','validator','server_configuration'):bound(prepared[key])
    report=read(out/'NATIVE_VALIDATION.json')
    if (report.get('valid') is not True or report.get('node_errors') or report.get('node_execution_performed') is not False
            or report['graph_sha256']!=prepared['graph']['sha256']):raise ValueError('exact native graph validation required')
    expected=dict(runner_sha256=sha(__file__),cli_sha256=sha(SCRIPT),authorization_sha256=prepared['authorization']['sha256'],
                  prepared_sha256=sha(out/'PREPARED.json'),graph_sha256=prepared['graph']['sha256'],
                  source_recipe_sha256=prepared['source_recipe']['sha256'],opening_image_receipt_sha256=prepared['opening_image_receipt']['sha256'],
                  native_validation_sha256=sha(out/'NATIVE_VALIDATION.json'))
    review=read(out/'PRIMARY_TRIAL_REVIEW.json')
    if review.get('approved_for_single_submission') is not True or any(review.get(key)!=value for key,value in expected.items()):
        raise ValueError('primary review must bind this exact first-frame trial')
    return prepared


def log(out,event,prompt_id=None,failure=False):
    path=out/'MEDIA_EVENTS.json'
    data=read(path) if path.exists() else dict(story_id=h.STORY_ID,trial_id='h3_dense_office_trial_20261018',inherited_failures=3,failure_limit=10,events=[])
    data['events'].append(dict(at=now(),kind=event,prompt_id=prompt_id,failure=failure));durable(path,data)
    print(json.dumps(dict(event=event,prompt_id=prompt_id)),flush=True)


def submit_once(client,out=OUT):
    if state(out)[0]!='new':raise ValueError('existing task or claim; no repeated POST')
    auth,source=admission(out);prepared=review_gate(out);opening_binding(auth,out)
    speed.check_service(client,out)
    graph=read(bound(prepared['graph']))
    if graph!=compile_graph(source,read(bound(prepared['source_recipe'])),read(bound(prepared['parameters']))):
        raise ValueError('actual graph differs from the named first-frame compiler output')
    if (out/'STOP_REQUESTED.json').exists():raise ValueError('stop requested before POST')
    request=dict(prompt=graph,client_id=str(uuid.uuid4()));durable(out/'REQUEST.actual.json',request,immutable=True)
    claim=dict(at=now(),story_id=h.STORY_ID,max_posts=1,authorization=prepared['authorization'],prepared=binding(out/'PREPARED.json'),
               graph=prepared['graph'],actual_request=binding(out/'REQUEST.actual.json'),opening_image=prepared['opening_image'],
               primary_review=binding(out/'PRIMARY_TRIAL_REVIEW.json'),automatic_retry=False)
    if GLOBAL_CLAIM.exists():raise ValueError('permanent office trial claim exists')
    durable(GLOBAL_CLAIM,claim,immutable=True);durable(out/'SUBMISSION_CLAIM.json',claim,immutable=True)
    log(out,'dispatch_reserved')
    if (out/'STOP_REQUESTED.json').exists():raise ValueError('stop requested after claim; no POST performed')
    admission(out);review_gate(out)
    try:response=client.post_graph(request)
    except Exception as exc:
        durable(out/'UNKNOWN_SUBMISSION.json',dict(at=now(),error_type=type(exc).__name__,error=str(exc),automatic_retry=False));raise
    durable(out/'SUBMISSION_RESPONSE.json',response,immutable=True)
    if not response.get('prompt_id') or response.get('node_errors'):raise ValueError('missing usable original ID; do not retry')
    pid=response['prompt_id'];durable(out/'job_ids.json',{'S01':pid})
    row=dict(schema='h3_dense_office_single_receipt/v1',story_id=h.STORY_ID,segment_id='S01',prompt_id=pid,submitted_at=claim['at'],
             technical_status='pending',content_status='awaiting_human_review',content_review=None,
             authorization=prepared['authorization'],sources=prepared['sources'],graph=prepared['graph'],opening_image=prepared['opening_image'])
    durable(out/'receipt.json',row);log(out,'submitted',pid);return row


def collect(client,out=OUT):
    action,row=state(out)
    if action=='new':raise ValueError('office trial has not been submitted')
    if action=='saved':
        for item in row['files'].values():bound(item)
        bound(row['delivery']);return row
    pid=row['prompt_id'];response=client.get('/history/'+pid)
    if pid not in response:return dict(row,technical_status='pending')
    prepared=read(out/'PREPARED.json');entry=response[pid]
    identity=h.history_graph_identity(read(bound(prepared['graph'])),entry,pid)
    durable(out/'HISTORY.json',response)
    row.update(schema='h3_dense_office_single_receipt/v1',story_id=h.STORY_ID,segment_id='S01',
               submitted_at=read(out/'SUBMISSION_CLAIM.json')['at'],authorization=prepared['authorization'],sources=prepared['sources'],
               opening_image=prepared['opening_image'],graph=prepared['graph'],history=binding(out/'HISTORY.json'),graph_identity=identity,
               content_status='awaiting_human_review',content_review=None)
    if not h.check_history_success(entry):
        row['technical_status']='failed';durable(out/'receipt.json',row);log(out,'service_failed',pid,True)
        raise ValueError('known service failure; no automatic retry')
    files={}
    for role,node,field,extension in (('video','save_video','images','.mp4'),('audio','save_audio','audio','.flac'),
                                      ('first','save_first','images','.png'),('last','save_last','images','.png')):
        items=entry['outputs'][node][field]
        if len(items)!=1:raise ValueError('ambiguous original output')
        original=h.service_file(dict(output_root=str(OUTPUT_ROOT)),items[0],PREFIX+'/'+role)
        if original.suffix.lower()!=extension:raise ValueError('unexpected original encoding')
        metadata=speed.probe(original,role=='audio') if role in ('video','audio') else h.png_integrity(original)
        if role in ('first','last') and (metadata['width'],metadata['height'])!=(768,416):raise ValueError('native PNG grid differs')
        saved=h.copy_original(original,out/('native_'+role+extension))
        files[role]=dict(**binding(saved),bytes=saved.stat().st_size,original_service_path=str(original),metadata=metadata)
    delivered=h.copy_original(files['video']['path'],out/'deliverables/S01_office_768x416_12step_with_audio.mp4')
    timestamps={key:data.get('timestamp') for key,data in entry['status'].get('messages',[]) if key in ('execution_start','execution_success')}
    elapsed=None
    if all(type(timestamps.get(key)) in (int,float) for key in ('execution_start','execution_success')):
        elapsed=(timestamps['execution_success']-timestamps['execution_start'])/1000
    row.update(technical_status='succeeded',files=files,delivery=binding(delivered),saved_at=now(),
               wall_elapsed_seconds=(datetime.now(timezone.utc)-datetime.fromisoformat(row['submitted_at'])).total_seconds(),
               service_execution_elapsed_seconds=elapsed,service_timing_evidence=timestamps,
               pixels_decoded=False,frame_extraction=False,listened=False,ASR=False)
    durable(out/'receipt.json',row);log(out,'saved_awaiting_human_review',pid);return row


def run(client,out=OUT,timeout=21600,poll=30):
    if timeout<14400 or poll<1:raise ValueError('allow four hours and positive polling interval')
    with process_lock(out/'.office_trial.lock'),process_lock(GLOBAL_CLAIM.with_suffix('.lock')):
        if state(out)[0]=='new':submit_once(client,out)
        started=time.monotonic()
        while True:
            row=collect(client,out)
            if row['technical_status']=='succeeded':return row
            durable(out/'STATUS.json',dict(at=now(),phase='original_id_pending',prompt_id=row['prompt_id']))
            print(json.dumps(dict(status='pending',prompt_id=row['prompt_id'])),flush=True)
            if time.monotonic()-started>=timeout:raise TimeoutError('original task pending; preserve ID without re-POST')
            time.sleep(poll)


def status(client,out=OUT):
    action,row=state(out);result=dict(local_state=action,media_submissions=0)
    if row and row.get('prompt_id'):
        pid=row['prompt_id'];response=client.get('/history/'+pid)
        result.update(prompt_id=pid,service_status=response.get(pid,{}).get('status',{}))
    return result
