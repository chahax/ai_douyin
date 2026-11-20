"""One independent hardware concurrency test, not a narrative continuation."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
import uuid
import ctypes
from ctypes import wintypes
import os
import subprocess
import threading

import psutil

from . import h3_dense_office_trial_v1 as s01
from . import h3_dense_office_s04_v1 as previous
from .assistant_seedance_batch import durable, process_lock

h=s01.h
ROOT=h.ROOT
OUT=ROOT/'data/local_media_tests/h3_game_concurrent_20261018'
PREFIX='h3_game_concurrent_20261018/LOAD_TEST'
SOURCE_SHA='f7be6228b7f9c1f7adf6e6fa67fba15c514044ca5b07a637fde6a3ed02c2ccf8'
SOURCE_TASK_ID='dc36ab8c-0587-4307-a155-0588ef9df3ae'
GLOBAL_CLAIM=ROOT/'data/local_media_tests/h3_game_concurrent_20261018/PERMANENT_LOAD_TEST_CLAIM.json'
SERVER_LOG=ROOT/'data/video_generation/h3_assistant_screenplay_full_20261016/resume_20261018/server.stderr.log'
SCRIPT=ROOT/'scripts/run_h3_game_concurrent_20261018.py'
read,sha,bound,binding,now=h.read,h.sha,h.bound,h.binding,h.now


class UnresolvedClaimError(ValueError):
    pass


def recipe():
    return dict(schema='h3_game_concurrent_source_recipe/v1',source_graph_sha256=SOURCE_SHA,
                named_parameters=['prompt','first_frame_input','noise_seed','output_prefix'],
                first_frame_source='fixed_original_office_opening_fixture_not_story_continuation',
                fixed=dict(width=768,height=416,steps=12,fps=24,length=362,native_audio=True),
                nodes=20,automatic_retry=False)


def compile_graph(source,source_recipe,parameters):
    if source_recipe!=recipe() or set(parameters)!=set(source_recipe['named_parameters']):raise ValueError('exact LOAD_TEST named source recipe required')
    condition=source['condition']
    if (len(source)!=20 or condition['class_type']!='MiniMaxH3ImageToVideo'
            or set(condition['inputs'])!={'clip','vae','prompt','width','height','length','first_frame'}
            or condition['inputs']['first_frame']!=['ref_scene',0]
            or [condition['inputs'][k] for k in ('width','height','length')]!=[768,416,362]
            or source['127']['inputs']['unet_name']!=s01.MODEL or source['124']['inputs']['steps']!=12
            or source['130']['inputs']['fps']!=24 or source['130']['inputs']['audio']!=['121',0]
            or source['123']['inputs']['sampler_name']!='res_multistep' or source['124']['inputs']['scheduler']!='simple'
            or any(row['class_type'] in ('LoadAudio','MiniMaxH3AddGuide') or 'lora' in row['class_type'].lower() for row in source.values())):
        raise ValueError('source differs from successful S04 native first-frame FL2VA graph')
    if (parameters['first_frame_input']!='h3_game_concurrent_20261018/opening_frame.png'
            or parameters['output_prefix']!=PREFIX or type(parameters['noise_seed']) is not int
            or not isinstance(parameters['prompt'],str) or not parameters['prompt'].strip()):raise ValueError('invalid LOAD_TEST source parameters')
    graph=copy.deepcopy(source)
    graph['condition']['inputs']['prompt']=parameters['prompt']
    graph['ref_scene']['inputs']['image']=parameters['first_frame_input']
    graph['129']['inputs']['noise_seed']=parameters['noise_seed']
    for role in ('video','audio','first','last'):graph['save_'+role]['inputs']['filename_prefix']=PREFIX+'/'+role
    return graph


def failure_count(auth,out):
    if auth.get('failure_reset') is not False or auth.get('failure_limit')!=10 or auth.get('known_prior_story_failures')!=3:
        raise ValueError('known prior story failures cannot reset')
    inherited=previous.failure_count(read(previous.OUT/'AUTHORIZATION.json'),previous.OUT)
    if inherited!=3:raise ValueError('prior story failure evidence changed')
    return inherited


def admission(out=OUT):
    auth=read(out/'AUTHORIZATION.json')
    if (auth.get('schema')!='h3_game_concurrent_authorization/v1' or auth.get('user_message')!='试一试'
            or auth.get('max_new_video_submissions')!=1 or auth.get('story_segment') is not False
            or auth.get('automatic_retry') is not False or auth.get('automatic_fallback') is not False
            or auth.get('publishing_authorized') is not False or auth.get('local_video_only') is not True
            or auth.get('new_models_or_dependencies') is not False or auth.get('game_settings_changes') is not False
            or auth.get('telemetry_interval_seconds')!=10 or auth.get('external_text_model_calls')!=0
            or auth.get('game')!=dict(name='VampireSurvivors.exe',pid=37860,do_not_close_or_change=True)):
        raise ValueError('exact one-submission hardware test authorization required')
    if auth['parameters']!=dict(width=768,height=416,steps=12,fps=24,length=362,native_audio=True,turbo_lora=False):
        raise ValueError('load-test grid or native audio changed')
    for item in auth['source_bindings'].values():bound(item)
    sources=auth['source_bindings']
    if (Path(sources['source_graph']['path']).resolve()!=(previous.OUT/'workflow_api.json').resolve()
            or sources['source_graph']['sha256']!=SOURCE_SHA or auth.get('source_graph_sha256')!=SOURCE_SHA
            or Path(sources['source_receipt']['path']).resolve()!=(previous.OUT/'receipt.json').resolve()):
        raise ValueError('exact frozen successful S04 graph/receipt required')
    original=read(bound(sources['source_receipt']))
    if (original.get('technical_status')!='succeeded' or original.get('graph')!=sources['source_graph']
            or original.get('prompt_id')!=SOURCE_TASK_ID):
        raise ValueError('source graph did not technically succeed')
    archive=read(bound(original['history']))
    if not h.check_history_success(archive[original['prompt_id']]):raise ValueError('source history failed')
    h.history_graph_identity(read(bound(sources['source_graph'])),archive[original['prompt_id']],original['prompt_id'])
    frame=bound(auth['first_frame'])
    if (frame!=(s01.OUT/'opening_frame.png').resolve()
            or auth['first_frame']['sha256']!='bedda7c1d03d132a490b3ab0f00143d545a807ced2eb6f272f3b434e384875fc'):
        raise ValueError('load test requires fixed opening fixture, never a story continuation tail')
    h.png_integrity(frame);failure_count(auth,out)
    return auth,read(bound(sources['source_graph'])),original


def state(out=OUT):
    if (out/'receipt.json').exists():
        row=read(out/'receipt.json')
        if row.get('technical_status')=='succeeded':return 'saved',row
        if row.get('technical_status')=='failed':raise ValueError('known LOAD_TEST service failure; no retry')
        if row.get('prompt_id'):return 'query',row
    if (out/'SUBMISSION_RESPONSE.json').exists() and read(out/'SUBMISSION_RESPONSE.json').get('prompt_id'):
        return 'query',dict(prompt_id=read(out/'SUBMISSION_RESPONSE.json')['prompt_id'],technical_status='pending')
    if (out/'SUBMISSION_CLAIM.json').exists() or GLOBAL_CLAIM.exists():raise UnresolvedClaimError('permanent claim without original ID: submission outcome unknown, do not POST again')
    return 'new',None


def prepare(out=OUT):
    if state(out)[0]!='new':raise ValueError('existing LOAD_TEST state cannot be prepared again')
    auth,source,_=admission(out)
    relative='h3_game_concurrent_20261018/opening_frame.png'
    staged=h.copy_original(bound(auth['first_frame']),s01.INPUT_ROOT/relative)
    parameters=dict(prompt=bound(auth['source_bindings']['prompt']).read_text(encoding='utf-8'),first_frame_input=relative,
                    noise_seed=202610182135,output_prefix=PREFIX)
    graph=compile_graph(source,recipe(),parameters)
    h.copy_original(bound(auth['source_bindings']['source_graph']),out/'SOURCE_GRAPH_CAPTURE.json')
    for name,value in [('SOURCE_RECIPE.json',recipe()),('PARAMETERS.json',parameters),('workflow_api.json',graph)]:durable(out/name,value,immutable=True)
    prepared=dict(schema='h3_dense_office_game_load_preparation/v1',authorization=binding(out/'AUTHORIZATION.json'),sources=auth['source_bindings'],
                  first_frame=auth['first_frame'],staged_first_frame=binding(staged),source_graph_capture=binding(out/'SOURCE_GRAPH_CAPTURE.json'),
                  source_recipe=binding(out/'SOURCE_RECIPE.json'),parameters=binding(out/'PARAMETERS.json'),graph=binding(out/'workflow_api.json'),
                  game_identity=game_identity(auth),validator=binding(s01.speed.VALIDATOR),server_configuration=binding(s01.speed.MEDIA_ROOT/'SERVER_STARTED.json'),
                  known_same_story_failures=failure_count(auth,out),media_submissions=0)
    durable(out/'PREPARED.json',prepared,immutable=True)
    return dict(status='prepared_not_submitted',graph=prepared['graph'],media_submissions=0)


def validate_native(out=OUT):return s01.speed.validate_native(out)


def review_gate(out=OUT):
    prepared=read(out/'PREPARED.json')
    for key in ('authorization','first_frame','staged_first_frame','source_graph_capture','source_recipe','parameters','graph','validator','server_configuration'):bound(prepared[key])
    report=read(out/'NATIVE_VALIDATION.json')
    if (report.get('valid') is not True or report.get('node_errors') or report.get('node_execution_performed') is not False
            or report['graph_sha256']!=prepared['graph']['sha256']):raise ValueError('exact LOAD_TEST native validation required')
    expected=dict(runner_sha256=sha(__file__),cli_sha256=sha(SCRIPT),authorization_sha256=prepared['authorization']['sha256'],
                  prepared_sha256=sha(out/'PREPARED.json'),graph_sha256=prepared['graph']['sha256'],source_recipe_sha256=prepared['source_recipe']['sha256'],
                  native_validation_sha256=sha(out/'NATIVE_VALIDATION.json'))
    review=read(out/'PRIMARY_TRIAL_REVIEW.json')
    if review.get('approved_for_single_submission') is not True or any(review.get(k)!=v for k,v in expected.items()):raise ValueError('primary review does not bind exact LOAD_TEST runtime and graph')
    return prepared


def log(out,event,prompt_id=None,failure=False):
    path=out/'MEDIA_EVENTS.json'
    data=read(path) if path.exists() else dict(related_story_id=h.STORY_ID,test_id='H3_GAME_CONCURRENT_20261018',story_segment=False,inherited_failures=3,failure_limit=10,events=[])
    data['events'].append(dict(at=now(),kind=event,prompt_id=prompt_id,failure=failure));durable(path,data)
    print(json.dumps(dict(event=event,prompt_id=prompt_id)),flush=True)


def submit_once(client,out=OUT):
    if state(out)[0]!='new':raise ValueError('existing LOAD_TEST task or claim; no repeated POST')
    auth,source,prior=admission(out);prepared=review_gate(out);s01.speed.check_service(client,out)
    require_game(auth,prepared['game_identity'])
    graph=read(bound(prepared['graph']))
    if graph!=compile_graph(source,read(bound(prepared['source_recipe'])),read(bound(prepared['parameters']))):raise ValueError('actual LOAD_TEST graph differs from source compiler')
    if (out/'STOP_REQUESTED.json').exists():raise ValueError('stop requested before POST')
    request=dict(prompt=graph,client_id=str(uuid.uuid4()));durable(out/'REQUEST.actual.json',request,immutable=True)
    offset=dict(path=str(SERVER_LOG),pre_post_byte_offset=SERVER_LOG.stat().st_size,captured_at=now())
    durable(out/'SAMPLING_LOG_OFFSET.json',offset,immutable=True)
    claim=dict(at=now(),related_story_id=h.STORY_ID,test_id='H3_GAME_CONCURRENT_20261018',story_segment=False,max_posts=1,authorization=prepared['authorization'],prepared=binding(out/'PREPARED.json'),
               actual_request=binding(out/'REQUEST.actual.json'),graph=prepared['graph'],first_frame=prepared['first_frame'],
               source_graph_task_id=SOURCE_TASK_ID,server_log=offset,primary_review=binding(out/'PRIMARY_TRIAL_REVIEW.json'),automatic_retry=False)
    if GLOBAL_CLAIM.exists():raise ValueError('permanent LOAD_TEST claim already exists')
    durable(GLOBAL_CLAIM,claim,immutable=True);durable(out/'SUBMISSION_CLAIM.json',claim,immutable=True);log(out,'dispatch_reserved')
    if (out/'STOP_REQUESTED.json').exists():raise ValueError('stop requested after claim; no POST performed')
    admission(out);review_gate(out);require_game(auth,prepared['game_identity'])
    try:response=client.post_graph(request)
    except Exception as exc:
        durable(out/'UNKNOWN_SUBMISSION.json',dict(at=now(),error_type=type(exc).__name__,error=str(exc),automatic_retry=False));raise
    durable(out/'SUBMISSION_RESPONSE.json',response,immutable=True)
    if not response.get('prompt_id') or response.get('node_errors'):raise ValueError('no usable original LOAD_TEST ID; preserve unknown outcome without retry')
    pid=response['prompt_id'];durable(out/'job_ids.json',{'LOAD_TEST':pid})
    row=dict(schema='h3_dense_office_game_load_receipt/v1',related_story_id=h.STORY_ID,test_id='H3_GAME_CONCURRENT_20261018',story_segment=False,prompt_id=pid,submitted_at=claim['at'],
             technical_status='pending',content_status='awaiting_human_review',content_review=None,media_submissions=1,
             authorization=prepared['authorization'],sources=prepared['sources'],first_frame=prepared['first_frame'],graph=prepared['graph'],source_graph_task_id=SOURCE_TASK_ID)
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
    return dict(schema='h3_game_load_sampling_observations/v1',log_offset=offset,
                observations=[dict(step=k,reported_cumulative_seconds=v,adjacent_step_delta_seconds=v-steps[k-1] if k-1 in steps else None) for k,v in sorted(steps.items())],
                sampling_total_seconds=steps.get(12),whole_second_log_precision=True)


def collect(client,out=OUT):
    action,row=state(out)
    if action=='new':raise ValueError('LOAD_TEST has not been submitted')
    if action=='saved':
        for item in row['files'].values():bound(item)
        bound(row['delivery']);return row
    pid=row['prompt_id'];response=client.get('/history/'+pid)
    if pid not in response:return dict(row,technical_status='pending',media_submissions=1)
    prepared=read(out/'PREPARED.json');entry=response[pid]
    identity=h.history_graph_identity(read(bound(prepared['graph'])),entry,pid);durable(out/'HISTORY.json',response)
    row.update(schema='h3_dense_office_game_load_receipt/v1',related_story_id=h.STORY_ID,test_id='H3_GAME_CONCURRENT_20261018',story_segment=False,submitted_at=read(out/'SUBMISSION_CLAIM.json')['at'],
               authorization=prepared['authorization'],sources=prepared['sources'],first_frame=prepared['first_frame'],graph=prepared['graph'],
               source_graph_task_id=SOURCE_TASK_ID,history=binding(out/'HISTORY.json'),graph_identity=identity,media_submissions=1,
               content_status='awaiting_human_review',content_review=None)
    if not h.check_history_success(entry):
        row['technical_status']='failed';durable(out/'receipt.json',row);log(out,'service_failed',pid,True)
        raise ValueError('known LOAD_TEST service failure; no automatic retry')
    files={}
    for role,node,field,extension in (('video','save_video','images','.mp4'),('audio','save_audio','audio','.flac'),('first','save_first','images','.png'),('last','save_last','images','.png')):
        items=entry['outputs'][node][field]
        if len(items)!=1:raise ValueError('ambiguous original output')
        original=h.service_file(dict(output_root=str(s01.OUTPUT_ROOT)),items[0],PREFIX+'/'+role)
        if original.suffix.lower()!=extension:raise ValueError('unexpected original output encoding')
        metadata=s01.speed.probe(original,role=='audio') if role in ('video','audio') else h.png_integrity(original)
        if role in ('first','last') and (metadata['width'],metadata['height'])!=(768,416):raise ValueError('native output PNG grid differs')
        saved=h.copy_original(original,out/('native_'+role+extension));files[role]=dict(**binding(saved),bytes=saved.stat().st_size,original_service_path=str(original),metadata=metadata)
    delivered=h.copy_original(files['video']['path'],out/'deliverables/game_h3_15s_with_audio.mp4')
    timestamps={key:data.get('timestamp') for key,data in entry['status'].get('messages',[]) if key in ('execution_start','execution_success')}
    elapsed=(timestamps['execution_success']-timestamps['execution_start'])/1000 if all(type(timestamps.get(key)) in (int,float) for key in ('execution_start','execution_success')) else None
    row.update(technical_status='succeeded',files=files,delivery=binding(delivered),saved_at=now(),service_execution_elapsed_seconds=elapsed,
               service_timing_evidence=timestamps,wall_elapsed_seconds=(datetime.now(timezone.utc)-datetime.fromisoformat(row['submitted_at'])).total_seconds(),
               pixels_decoded=False,frame_extraction=False,listened=False,ASR=False)
    durable(out/'receipt.json',row);log(out,'saved_awaiting_human_review',pid)
    durable(out/'SAMPLING_OBSERVATIONS.json',sampling_observations(out));return row


def _run_original(client,out=OUT,timeout=21600,poll=30):
    if timeout<14400 or poll<1:raise ValueError('allow four hours and a positive poll interval')
    with process_lock(out/'.game_load_trial.lock'),process_lock(GLOBAL_CLAIM.with_suffix('.lock')):
        if state(out)[0]=='new':submit_once(client,out)
        started=time.monotonic()
        while True:
            row=collect(client,out)
            if row['technical_status']=='succeeded':return row
            durable(out/'STATUS.json',dict(at=now(),phase='original_id_pending',prompt_id=row['prompt_id'],media_submissions=1))
            print(json.dumps(dict(status='pending',prompt_id=row['prompt_id'],media_submissions=1)),flush=True)
            if time.monotonic()-started>=timeout:raise TimeoutError('original LOAD_TEST remains pending; do not re-POST')
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


def game_identity(auth):
    process=psutil.Process(auth['game']['pid'])
    if not process.is_running() or process.name()!=auth['game']['name']:
        raise ValueError('authorized game process is not running; no dispatch')
    return dict(pid=process.pid,name=process.name(),create_time=process.create_time())


def require_game(auth,expected):
    try:actual=game_identity(auth)
    except (psutil.Error,ValueError) as exc:
        raise ValueError('authorized game is not running; no dispatch') from exc
    if actual!=expected:raise ValueError('game PID identity changed; no dispatch')
    return actual


def windows_commit():
    class PerformanceInformation(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD)]+[(key,ctypes.c_size_t) for key in
          ('CommitTotal','CommitLimit','CommitPeak','PhysicalTotal','PhysicalAvailable',
           'SystemCache','KernelTotal','KernelPaged','KernelNonpaged','PageSize')]+[
          ('HandleCount',wintypes.DWORD),('ProcessCount',wintypes.DWORD),('ThreadCount',wintypes.DWORD)]
    value=PerformanceInformation();value.cb=ctypes.sizeof(value)
    call=ctypes.WinDLL('psapi',use_last_error=True).GetPerformanceInfo
    call.argtypes=[ctypes.POINTER(PerformanceInformation),wintypes.DWORD];call.restype=wintypes.BOOL
    if not call(ctypes.byref(value),value.cb):raise ctypes.WinError(ctypes.get_last_error())
    return dict(commit_bytes=value.CommitTotal*value.PageSize,commit_limit_bytes=value.CommitLimit*value.PageSize)


class Telemetry:
    """Read-only ten-second samples; unknown data never becomes zero or a POST retry."""
    def __init__(self,out,game):
        self.out,self.game=out,game
        self.stop_event=threading.Event();self.thread=None
        self.previous_game_cpu=None;self.previous_game_monotonic=None;self.cpu_thread_samples={}

    def sample(self,phase):
        row=dict(at=now(),monotonic_seconds=time.monotonic(),phase=phase,gpu=None,system=None,game=None,errors={})
        try:
            command=['nvidia-smi','--query-gpu=index,uuid,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu,power.draw','--format=csv,noheader,nounits']
            result=subprocess.run(command,capture_output=True,text=True,timeout=5,
                                  creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:raise RuntimeError('nvidia-smi exit '+str(result.returncode)+': '+result.stderr.strip()[:300])
            lines=[]
            for line in result.stdout.splitlines():
                parts=[value.strip() for value in line.split(',')]
                if len(parts)!=8:raise ValueError('unexpected nvidia-smi sample')
                gpu=dict(index=int(parts[0]),uuid=parts[1],memory_total_mib=None,memory_used_mib=None,memory_free_mib=None,
                         utilization_percent=None,temperature_c=None,power_w=None)
                for key,value in zip(tuple(gpu)[2:],parts[2:]):
                    try:gpu[key]=float(value)
                    except ValueError:row['errors']['gpu.'+key]='unknown: '+value
                lines.append(gpu)
            if not lines:raise ValueError('no GPU rows')
            row['gpu']=lines
        except Exception as exc:row['errors']['gpu']=type(exc).__name__+': '+str(exc)
        row['system']=dict(cpu_percent=None,cpu_sample_window_seconds=None,cpu_sample_thread_id=threading.get_ident(),
                           physical_available_bytes=None,physical_total_bytes=None,
                           commit_bytes=None,commit_limit_bytes=None)
        try:
            identity=threading.get_ident();moment=time.monotonic()
            prior_moment=self.cpu_thread_samples.get(identity)
            cpu=psutil.cpu_percent(interval=None)
            row['system']['cpu_percent']=cpu if prior_moment is not None else None
            row['system']['cpu_sample_window_seconds']=moment-prior_moment if prior_moment is not None else None
            self.cpu_thread_samples[identity]=moment
            mem=psutil.virtual_memory();row['system'].update(physical_available_bytes=mem.available,physical_total_bytes=mem.total)
        except Exception as exc:row['errors']['system']=type(exc).__name__+': '+str(exc)
        try:row['system'].update(windows_commit())
        except Exception as exc:row['errors']['system.commit']=type(exc).__name__+': '+str(exc)
        row['game']=dict(pid=self.game['pid'],name=self.game['name'],running=None,identity_matches=None,
                         rss_bytes=None,cpu_seconds=None,cpu_percent_one_core=None)
        try:
            process=psutil.Process(self.game['pid']);name=process.name();created=process.create_time()
            matches=name==self.game['name'] and created==self.game['create_time']
            running=process.is_running() and matches
            row['game'].update(running=running,identity_matches=matches,observed_name=name,observed_create_time=created)
            if running:
                times=process.cpu_times();cpu_seconds=times.user+times.system;moment=time.monotonic()
                cpu_percent=None
                if self.previous_game_cpu is not None and moment>self.previous_game_monotonic:
                    cpu_percent=100*(cpu_seconds-self.previous_game_cpu)/(moment-self.previous_game_monotonic)
                row['game'].update(rss_bytes=process.memory_info().rss,cpu_seconds=cpu_seconds,cpu_percent_one_core=cpu_percent)
                self.previous_game_cpu,self.previous_game_monotonic=cpu_seconds,moment
        except psutil.NoSuchProcess:
            row['game'].update(running=False,identity_matches=False);row['errors']['game']='NoSuchProcess'
        except Exception as exc:row['errors']['game']=type(exc).__name__+': '+str(exc)
        try:
            with (self.out/'TELEMETRY.jsonl').open('a',encoding='utf-8') as handle:
                handle.write(json.dumps(row,ensure_ascii=False)+'\n');handle.flush();os.fsync(handle.fileno())
        except Exception as exc:
            print(json.dumps(dict(event='telemetry_write_error',error_type=type(exc).__name__,error=str(exc))),flush=True)
        return row

    def loop(self):
        deadline=time.monotonic()+10
        while not self.stop_event.wait(max(0,deadline-time.monotonic())):
            self.sample('during_original_task');deadline+=10
            if deadline<=time.monotonic():deadline=time.monotonic()+10

    def start(self):
        self.sample('before_run_or_resume')
        self.thread=threading.Thread(target=self.loop,name='h3-readonly-telemetry',daemon=True);self.thread.start()

    def finish(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=7)
        self.sample('after_collect_or_local_stop')
        summarize_telemetry(self.out)


def summarize_telemetry(out=OUT):
    rows=[];parse_errors=[]
    if (out/'TELEMETRY.jsonl').exists():
        for index,line in enumerate((out/'TELEMETRY.jsonl').read_text(encoding='utf-8').splitlines(),1):
            try:rows.append(json.loads(line))
            except ValueError as exc:parse_errors.append(dict(line=index,error=str(exc)))
    def extreme(values,maximum=True):
        valid=[value for value in values if type(value) in (int,float)]
        return (max(valid) if maximum else min(valid)) if valid else None
    gpu=[item for row in rows for item in (row.get('gpu') or [])]
    systems=[row.get('system') or {} for row in rows];games=[row.get('game') or {} for row in rows]
    running=[row.get('running') for row in games]
    summary=dict(schema='h3_game_concurrent_telemetry_summary/v1',samples=len(rows),interval_target_seconds=10,
                 raw=binding(out/'TELEMETRY.jsonl') if (out/'TELEMETRY.jsonl').exists() else None,
                 first_sample_at=rows[0]['at'] if rows else None,last_sample_at=rows[-1]['at'] if rows else None,
                 sampled_peaks_only=True,unobserved_instantaneous_peaks_unknown=True,
                 gpu_memory_used_peak_mib=extreme([v.get('memory_used_mib') for v in gpu]),
                 gpu_memory_free_min_mib=extreme([v.get('memory_free_mib') for v in gpu],False),
                 gpu_utilization_peak_percent=extreme([v.get('utilization_percent') for v in gpu]),
                 gpu_temperature_peak_c=extreme([v.get('temperature_c') for v in gpu]),
                 gpu_power_peak_w=extreme([v.get('power_w') for v in gpu]),
                 system_cpu_peak_percent=extreme([v.get('cpu_percent') for v in systems]),
                 physical_available_min_bytes=extreme([v.get('physical_available_bytes') for v in systems],False),
                 commit_peak_bytes=extreme([v.get('commit_bytes') for v in systems]),
                 commit_limit_min_bytes=extreme([v.get('commit_limit_bytes') for v in systems],False),
                 game_rss_peak_bytes=extreme([v.get('rss_bytes') for v in games]),
                 game_cpu_peak_one_core_percent=extreme([v.get('cpu_percent_one_core') for v in games]),
                 game_running_all_samples=all(value is True for value in running) if rows else None,
                 game_not_running_samples=sum(value is False for value in running),
                 game_unknown_samples=sum(value is None for value in running),
                 samples_with_errors=sum(bool(row.get('errors')) for row in rows),parse_errors=parse_errors,
                 game_fps=None,game_smoothness=None,continuous_between_samples_proven=False,
                 prior_story_failures_unchanged=3,created_at=now())
    durable(out/'TELEMETRY_SUMMARY.json',summary);return summary


def run(client,out=OUT,timeout=21600,poll=30):
    # The existing single-POST lock and original-ID poll loop stay authoritative.
    action,_=state(out)
    prepared=review_gate(out)
    if action=='new':require_game(read(out/'AUTHORIZATION.json'),prepared['game_identity'])
    with process_lock(out/'.telemetry_run.lock'):
        telemetry=Telemetry(out,prepared['game_identity']);telemetry.start()
        try:return _run_original(client,out,timeout,poll)
        finally:telemetry.finish()
