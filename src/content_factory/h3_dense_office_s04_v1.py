"""The authorized S04 once, from S03's original native tail and frozen FL2VA graph."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
import uuid

from . import h3_dense_office_trial_v1 as s01
from . import h3_dense_office_s03_v1 as previous
from .assistant_seedance_batch import durable, process_lock

h=s01.h
ROOT=h.ROOT
OUT=ROOT/'data/video_generation/h3_dense_office_s04_20261018'
PREFIX='h3_dense_office_s04_20261018/S04'
SOURCE_SHA='07daa9dd2175ac94d041a7c43e7e71764b4053975e236f0b564e53516a5c7b15'
PREDECESSOR_ID='e99f734e-75fb-4b14-a5af-8110a96ea1be'
TAIL_SHA='d3f8e4c5fcc61cf28c2f2bd293efb0a5f791c39a70c3f2707e6c9dd1d4470245'
GLOBAL_CLAIM=ROOT/'data/video_generation/h3_project_script_20261015/H3_DENSE_OFFICE_S04_20261018_PERMANENT_CLAIM.json'
SERVER_LOG=ROOT/'data/video_generation/h3_assistant_screenplay_full_20261016/resume_20261018/server.stderr.log'
SCRIPT=ROOT/'scripts/run_h3_dense_office_s04_20261018.py'
read,sha,bound,binding,now=h.read,h.sha,h.bound,h.binding,h.now


class UnresolvedClaimError(ValueError):
    pass


def recipe():
    return dict(schema='h3_dense_office_s04_tail_recipe/v1',source_graph_sha256=SOURCE_SHA,
                named_parameters=['prompt','first_frame_input','noise_seed','output_prefix'],
                first_frame_source='predecessor_service_original_native_tail',
                fixed=dict(width=768,height=416,steps=12,fps=24,length=362,native_audio=True),
                nodes=20,automatic_retry=False)


def compile_graph(source,source_recipe,parameters):
    if source_recipe!=recipe() or set(parameters)!=set(source_recipe['named_parameters']):raise ValueError('exact S04 named source recipe required')
    condition=source['condition']
    if (len(source)!=20 or condition['class_type']!='MiniMaxH3ImageToVideo'
            or set(condition['inputs'])!={'clip','vae','prompt','width','height','length','first_frame'}
            or condition['inputs']['first_frame']!=['ref_scene',0]
            or [condition['inputs'][k] for k in ('width','height','length')]!=[768,416,362]
            or source['127']['inputs']['unet_name']!=s01.MODEL or source['124']['inputs']['steps']!=12
            or source['130']['inputs']['fps']!=24 or source['130']['inputs']['audio']!=['121',0]
            or source['123']['inputs']['sampler_name']!='res_multistep' or source['124']['inputs']['scheduler']!='simple'
            or any(row['class_type'] in ('LoadAudio','MiniMaxH3AddGuide') or 'lora' in row['class_type'].lower() for row in source.values())):
        raise ValueError('source differs from successful S03 native first-frame FL2VA graph')
    if (parameters['first_frame_input']!='h3_dense_office_s04_20261018/S03_native_last.png'
            or parameters['output_prefix']!=PREFIX or type(parameters['noise_seed']) is not int
            or not isinstance(parameters['prompt'],str) or not parameters['prompt'].strip()):raise ValueError('invalid S04 source parameters')
    graph=copy.deepcopy(source)
    graph['condition']['inputs']['prompt']=parameters['prompt']
    graph['ref_scene']['inputs']['image']=parameters['first_frame_input']
    graph['129']['inputs']['noise_seed']=parameters['noise_seed']
    for role in ('video','audio','first','last'):graph['save_'+role]['inputs']['filename_prefix']=PREFIX+'/'+role
    return graph


def failure_count(auth,out):
    if (auth.get('failure_reset') is not False or auth.get('failure_limit')!=10 or auth.get('known_same_story_failures')!=3):
        raise ValueError('same-story known three failures cannot reset')
    count=previous.failure_count(read(previous.OUT/'AUTHORIZATION.json'),previous.OUT)
    if count!=3:raise ValueError('inherited S03 failures changed')
    if (out/'MEDIA_EVENTS.json').exists():
        rows=read(out/'MEDIA_EVENTS.json')['events']
        if any(type(row.get('failure')) is not bool for row in rows):raise ValueError('unknown S04 failure event')
        count+=sum(row['failure'] for row in rows)
    if count>=10:raise ValueError('same story failure limit exhausted')
    return count


def admission(out=OUT):
    auth=read(out/'AUTHORIZATION.json')
    if (auth.get('schema')!='h3_dense_office_s04_authorization/v1' or auth.get('user_message')!='继续'
            or auth.get('story_id')!=h.STORY_ID or auth.get('segment_id')!='S04' or auth.get('max_new_video_submissions')!=1
            or auth.get('predecessor_prompt_id')!=PREDECESSOR_ID or auth.get('automatic_retry') is not False
            or auth.get('automatic_fallback') is not False or auth.get('following_segment_authorized') is not False
            or auth.get('publishing_authorized') is not False or auth.get('local_video_only') is not True
            or auth.get('new_models_or_dependencies') is not False or auth.get('human_content_approved') is not False):
        raise ValueError('exact S03-to-S04 one-submission user authorization required')
    if auth['parameters']!=dict(width=768,height=416,steps=12,fps=24,length=362,native_audio=True,turbo_lora=False):raise ValueError('S04 grid or audio mode changed')
    for item in auth['source_bindings'].values():bound(item)
    sources=auth['source_bindings']
    expected_paths=dict(predecessor_receipt=previous.OUT/'receipt.json',predecessor_graph=previous.OUT/'workflow_api.json',
                        continuation=previous.OUT/'USER_CONTINUATION_ACCEPTANCE.json')
    if any(Path(sources[key]['path']).resolve()!=value.resolve() for key,value in expected_paths.items()):raise ValueError('wrong original S03 source paths')
    if sources['predecessor_graph']['sha256']!=SOURCE_SHA:raise ValueError('wrong predecessor submitted graph')
    original=read(sources['predecessor_receipt']['path']);acceptance=read(sources['continuation']['path'])
    if (original.get('prompt_id')!=PREDECESSOR_ID or original.get('technical_status')!='succeeded'
            or original.get('story_id')!=h.STORY_ID or original.get('graph')!=sources['predecessor_graph']
            or original.get('content_status')!='awaiting_human_review'
            or acceptance.get('schema')!='user_segment_continuation_acceptance/v1'
            or acceptance.get('user_message')!='继续' or acceptance.get('segment_id')!='S03'
            or acceptance.get('prompt_id')!=PREDECESSOR_ID or acceptance.get('human_approved_for_continuation') is not True
            or acceptance.get('original_receipt_preserved') is not True):raise ValueError('successful original S03 and explicit continuation acceptance required')
    frame=bound(auth['first_frame']);tail=original['files']['last']
    if (auth['first_frame']['sha256']!=TAIL_SHA or tail['sha256']!=TAIL_SHA
            or frame!=(previous.OUT/'native_last.png').resolve() or frame!=Path(tail['path']).resolve()
            or Path(auth['original_service_tail_path']).resolve()!=Path(tail['original_service_path']).resolve()
            or sha(auth['original_service_tail_path'])!=TAIL_SHA):raise ValueError('first frame is not the byte-identical original S03 service tail')
    png=h.png_integrity(frame)
    if (png['width'],png['height'])!=(768,416):raise ValueError('native predecessor tail PNG grid differs')
    archive=read(bound(original['history']))
    if not h.check_history_success(archive[PREDECESSOR_ID]):raise ValueError('archived original predecessor did not succeed')
    h.history_graph_identity(read(sources['predecessor_graph']['path']),archive[PREDECESSOR_ID],PREDECESSOR_ID)
    for item in original['files'].values():bound(item)
    bound(original['delivery']);failure_count(auth,out)
    return auth,read(sources['predecessor_graph']['path']),original


def state(out=OUT):
    if (out/'receipt.json').exists():
        row=read(out/'receipt.json')
        if row.get('technical_status')=='succeeded':return 'saved',row
        if row.get('technical_status')=='failed':raise ValueError('known S04 service failure; no retry')
        if row.get('prompt_id'):return 'query',row
    if (out/'SUBMISSION_RESPONSE.json').exists() and read(out/'SUBMISSION_RESPONSE.json').get('prompt_id'):
        return 'query',dict(prompt_id=read(out/'SUBMISSION_RESPONSE.json')['prompt_id'],technical_status='pending')
    if (out/'SUBMISSION_CLAIM.json').exists() or GLOBAL_CLAIM.exists():raise UnresolvedClaimError('permanent claim without original ID: submission outcome unknown, do not POST again')
    return 'new',None


def prepare(out=OUT):
    if state(out)[0]!='new':raise ValueError('existing S04 state cannot be prepared again')
    auth,source,_=admission(out)
    relative='h3_dense_office_s04_20261018/S03_native_last.png'
    staged=h.copy_original(bound(auth['first_frame']),s01.INPUT_ROOT/relative)
    parameters=dict(prompt=bound(auth['source_bindings']['prompt']).read_text(encoding='utf-8'),first_frame_input=relative,
                    noise_seed=202610182021,output_prefix=PREFIX)
    graph=compile_graph(source,recipe(),parameters)
    h.copy_original(bound(auth['source_bindings']['predecessor_graph']),out/'SOURCE_GRAPH_CAPTURE.json')
    for name,value in [('SOURCE_RECIPE.json',recipe()),('PARAMETERS.json',parameters),('workflow_api.json',graph)]:durable(out/name,value,immutable=True)
    prepared=dict(schema='h3_dense_office_s04_preparation/v1',authorization=binding(out/'AUTHORIZATION.json'),sources=auth['source_bindings'],
                  first_frame=auth['first_frame'],staged_first_frame=binding(staged),source_graph_capture=binding(out/'SOURCE_GRAPH_CAPTURE.json'),
                  source_recipe=binding(out/'SOURCE_RECIPE.json'),parameters=binding(out/'PARAMETERS.json'),graph=binding(out/'workflow_api.json'),
                  validator=binding(s01.speed.VALIDATOR),server_configuration=binding(s01.speed.MEDIA_ROOT/'SERVER_STARTED.json'),
                  known_same_story_failures=failure_count(auth,out),media_submissions=0)
    durable(out/'PREPARED.json',prepared,immutable=True)
    return dict(status='prepared_not_submitted',graph=prepared['graph'],media_submissions=0)


def validate_native(out=OUT):return s01.speed.validate_native(out)


def review_gate(out=OUT):
    prepared=read(out/'PREPARED.json')
    for key in ('authorization','first_frame','staged_first_frame','source_graph_capture','source_recipe','parameters','graph','validator','server_configuration'):bound(prepared[key])
    report=read(out/'NATIVE_VALIDATION.json')
    if (report.get('valid') is not True or report.get('node_errors') or report.get('node_execution_performed') is not False
            or report['graph_sha256']!=prepared['graph']['sha256']):raise ValueError('exact S04 native validation required')
    expected=dict(runner_sha256=sha(__file__),cli_sha256=sha(SCRIPT),authorization_sha256=prepared['authorization']['sha256'],
                  prepared_sha256=sha(out/'PREPARED.json'),graph_sha256=prepared['graph']['sha256'],source_recipe_sha256=prepared['source_recipe']['sha256'],
                  native_validation_sha256=sha(out/'NATIVE_VALIDATION.json'))
    review=read(out/'PRIMARY_TRIAL_REVIEW.json')
    if review.get('approved_for_single_submission') is not True or any(review.get(k)!=v for k,v in expected.items()):raise ValueError('primary review does not bind exact S04 runtime and graph')
    return prepared


def log(out,event,prompt_id=None,failure=False):
    path=out/'MEDIA_EVENTS.json'
    data=read(path) if path.exists() else dict(story_id=h.STORY_ID,segment_id='S04',inherited_failures=3,failure_limit=10,events=[])
    data['events'].append(dict(at=now(),kind=event,prompt_id=prompt_id,failure=failure));durable(path,data)
    print(json.dumps(dict(event=event,prompt_id=prompt_id)),flush=True)


def submit_once(client,out=OUT):
    if state(out)[0]!='new':raise ValueError('existing S04 task or claim; no repeated POST')
    auth,source,prior=admission(out);prepared=review_gate(out);s01.speed.check_service(client,out)
    predecessor=dict(prompt_id=PREDECESSOR_ID,graph=prior['graph'],last_frame=prior['files']['last']['path'],last_frame_sha256=TAIL_SHA)
    current=h.check_predecessor(client,predecessor,dict(output_root=str(s01.OUTPUT_ROOT)))
    durable(out/'PREDECESSOR_SERVICE_RECHECK.json',current)
    graph=read(bound(prepared['graph']))
    if graph!=compile_graph(source,read(bound(prepared['source_recipe'])),read(bound(prepared['parameters']))):raise ValueError('actual S04 graph differs from source compiler')
    if (out/'STOP_REQUESTED.json').exists():raise ValueError('stop requested before POST')
    request=dict(prompt=graph,client_id=str(uuid.uuid4()));durable(out/'REQUEST.actual.json',request,immutable=True)
    offset=dict(path=str(SERVER_LOG),pre_post_byte_offset=SERVER_LOG.stat().st_size,captured_at=now())
    durable(out/'SAMPLING_LOG_OFFSET.json',offset,immutable=True)
    claim=dict(at=now(),story_id=h.STORY_ID,segment_id='S04',max_posts=1,authorization=prepared['authorization'],prepared=binding(out/'PREPARED.json'),
               actual_request=binding(out/'REQUEST.actual.json'),graph=prepared['graph'],first_frame=prepared['first_frame'],
               predecessor_prompt_id=PREDECESSOR_ID,server_log=offset,primary_review=binding(out/'PRIMARY_TRIAL_REVIEW.json'),automatic_retry=False)
    if GLOBAL_CLAIM.exists():raise ValueError('permanent S04 claim already exists')
    durable(GLOBAL_CLAIM,claim,immutable=True);durable(out/'SUBMISSION_CLAIM.json',claim,immutable=True);log(out,'dispatch_reserved')
    if (out/'STOP_REQUESTED.json').exists():raise ValueError('stop requested after claim; no POST performed')
    admission(out);review_gate(out)
    try:response=client.post_graph(request)
    except Exception as exc:
        durable(out/'UNKNOWN_SUBMISSION.json',dict(at=now(),error_type=type(exc).__name__,error=str(exc),automatic_retry=False));raise
    durable(out/'SUBMISSION_RESPONSE.json',response,immutable=True)
    if not response.get('prompt_id') or response.get('node_errors'):raise ValueError('no usable original S04 ID; preserve unknown outcome without retry')
    pid=response['prompt_id'];durable(out/'job_ids.json',{'S04':pid})
    row=dict(schema='h3_dense_office_s04_receipt/v1',story_id=h.STORY_ID,segment_id='S04',prompt_id=pid,submitted_at=claim['at'],
             technical_status='pending',content_status='awaiting_human_review',content_review=None,media_submissions=1,
             authorization=prepared['authorization'],sources=prepared['sources'],first_frame=prepared['first_frame'],graph=prepared['graph'],predecessor_prompt_id=PREDECESSOR_ID)
    durable(out/'receipt.json',row);log(out,'submitted',pid);return row


def sampling_observations(out=OUT):
    offset=read(out/'SAMPLING_LOG_OFFSET.json');path=Path(offset['path']);size=path.stat().st_size
    if size<offset['pre_post_byte_offset']:raise ValueError('server log was truncated; never use earlier run sampling data')
    with path.open('rb') as handle:
        handle.seek(offset['pre_post_byte_offset']);section=handle.read().decode('utf-8',errors='replace')
    steps={}
    for match in re.finditer(r'\|\s*(\d+)/12\s+\[(\d+):(\d+)',section):
        step=int(match.group(1))
        if step and step not in steps:steps[step]=int(match.group(2))*60+int(match.group(3))
    return dict(schema='h3_s04_sampling_observations/v1',log_offset=offset,
                observations=[dict(step=k,reported_cumulative_seconds=v,adjacent_step_delta_seconds=v-steps[k-1] if k-1 in steps else None) for k,v in sorted(steps.items())],
                sampling_total_seconds=steps.get(12),whole_second_log_precision=True)


def collect(client,out=OUT):
    action,row=state(out)
    if action=='new':raise ValueError('S04 has not been submitted')
    if action=='saved':
        for item in row['files'].values():bound(item)
        bound(row['delivery']);return row
    pid=row['prompt_id'];response=client.get('/history/'+pid)
    if pid not in response:return dict(row,technical_status='pending',media_submissions=1)
    prepared=read(out/'PREPARED.json');entry=response[pid]
    identity=h.history_graph_identity(read(bound(prepared['graph'])),entry,pid);durable(out/'HISTORY.json',response)
    row.update(schema='h3_dense_office_s04_receipt/v1',story_id=h.STORY_ID,segment_id='S04',submitted_at=read(out/'SUBMISSION_CLAIM.json')['at'],
               authorization=prepared['authorization'],sources=prepared['sources'],first_frame=prepared['first_frame'],graph=prepared['graph'],
               predecessor_prompt_id=PREDECESSOR_ID,history=binding(out/'HISTORY.json'),graph_identity=identity,media_submissions=1,
               content_status='awaiting_human_review',content_review=None)
    if not h.check_history_success(entry):
        row['technical_status']='failed';durable(out/'receipt.json',row);log(out,'service_failed',pid,True)
        raise ValueError('known S04 service failure; no automatic retry')
    files={}
    for role,node,field,extension in (('video','save_video','images','.mp4'),('audio','save_audio','audio','.flac'),('first','save_first','images','.png'),('last','save_last','images','.png')):
        items=entry['outputs'][node][field]
        if len(items)!=1:raise ValueError('ambiguous original output')
        original=h.service_file(dict(output_root=str(s01.OUTPUT_ROOT)),items[0],PREFIX+'/'+role)
        if original.suffix.lower()!=extension:raise ValueError('unexpected original output encoding')
        metadata=s01.speed.probe(original,role=='audio') if role in ('video','audio') else h.png_integrity(original)
        if role in ('first','last') and (metadata['width'],metadata['height'])!=(768,416):raise ValueError('native output PNG grid differs')
        saved=h.copy_original(original,out/('native_'+role+extension));files[role]=dict(**binding(saved),bytes=saved.stat().st_size,original_service_path=str(original),metadata=metadata)
    delivered=h.copy_original(files['video']['path'],out/'deliverables/S04_office_768x416_12step_with_audio.mp4')
    timestamps={key:data.get('timestamp') for key,data in entry['status'].get('messages',[]) if key in ('execution_start','execution_success')}
    elapsed=(timestamps['execution_success']-timestamps['execution_start'])/1000 if all(type(timestamps.get(key)) in (int,float) for key in ('execution_start','execution_success')) else None
    row.update(technical_status='succeeded',files=files,delivery=binding(delivered),saved_at=now(),service_execution_elapsed_seconds=elapsed,
               service_timing_evidence=timestamps,wall_elapsed_seconds=(datetime.now(timezone.utc)-datetime.fromisoformat(row['submitted_at'])).total_seconds(),
               pixels_decoded=False,frame_extraction=False,listened=False,ASR=False)
    durable(out/'receipt.json',row);log(out,'saved_awaiting_human_review',pid)
    durable(out/'SAMPLING_OBSERVATIONS.json',sampling_observations(out));return row


def run(client,out=OUT,timeout=21600,poll=30):
    if timeout<14400 or poll<1:raise ValueError('allow four hours and a positive poll interval')
    with process_lock(out/'.s04_trial.lock'),process_lock(GLOBAL_CLAIM.with_suffix('.lock')):
        if state(out)[0]=='new':submit_once(client,out)
        started=time.monotonic()
        while True:
            row=collect(client,out)
            if row['technical_status']=='succeeded':return row
            durable(out/'STATUS.json',dict(at=now(),phase='original_id_pending',prompt_id=row['prompt_id'],media_submissions=1))
            print(json.dumps(dict(status='pending',prompt_id=row['prompt_id'],media_submissions=1)),flush=True)
            if time.monotonic()-started>=timeout:raise TimeoutError('original S04 remains pending; do not re-POST')
            time.sleep(poll)


def status(client,out=OUT):
    try:action,row=state(out)
    except UnresolvedClaimError:
        return dict(local_state='unknown',media_submissions=None,submission_outcome='unknown',automatic_retry=False)
    except ValueError:
        if not (out/'receipt.json').exists() or read(out/'receipt.json').get('technical_status')!='failed':raise
        row=read(out/'receipt.json');return dict(local_state='failed',prompt_id=row['prompt_id'],media_submissions=1)
    result=dict(local_state=action,media_submissions=1 if row and row.get('prompt_id') else 0)
    if row and row.get('prompt_id'):
        pid=row['prompt_id'];response=client.get('/history/'+pid);result.update(prompt_id=pid,service_status=response.get(pid,{}).get('status',{}))
    return result
