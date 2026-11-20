"""One independent four-part reference movie, resumed only by native IDs.

Preparation/status are read-only with respect to delivery/asset plans.  Only
tick/execute may call the existing v20 delivery submitter, after root review.
No graph construction, model rewrite, service repair or semantic retry here.
"""
from copy import deepcopy
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

from . import visual_h3_reference_delivery_v20 as delivery
from . import visual_h3_prompt_parity_v19 as clock

native=delivery.native
jobs=delivery.jobs
SCHEMA='reviewed_reference_full_minute/v20'
IDS=('S01','S02','S03','S04')
FRAMES=362
WIDTH,HEIGHT,FPS,RATE=736,1312,24,48000
RUN=Path(__file__).resolve().parents[2]/'data/video_generation/h3_reference_full_minute_20261107_v1'
PROJECT=Path(__file__).resolve().parents[2]
QA_SCRIPT=PROJECT/'scripts/qa_h3_reference_full_minute_cpu.py'
TERMINAL_BAD={'outcome_unknown','failed','interrupted','rejected'}


class MinuteRunError(ValueError):pass


def binding(path):
    path=Path(path).resolve();return dict(path=str(path),sha256=native.file_sha(path))


def _check(value):
    if not isinstance(value,dict) or set(value)!={'path','sha256'} or binding(value['path'])!=value:
        raise MinuteRunError('bound_file_changed')
    return Path(value['path'])


def check(value):return native.read(_check(value))


def _bind(value):return deepcopy(value) if isinstance(value,dict) else binding(value)
def _hash_text(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _scope(run):
    run=Path(run).resolve()
    if not re.fullmatch(r'h3_reference_full_minute_[a-zA-Z0-9_-]+',run.name):
        raise MinuteRunError('independent_reference_minute_namespace_required')
    return run


def _original(request):
    texts=[x.get('text') for x in request.get('content',[]) if x.get('type')=='text']
    if len(texts)!=1 or not isinstance(texts[0],str) or not texts[0].strip():raise MinuteRunError('unique_original_request_text_required')
    return texts[0]


def _dialogues(text,spans):
    if not isinstance(spans,list) or not spans:raise MinuteRunError('explicit_dialogue_span_audit_required')
    values=[];last=-1
    for span in spans:
        a,b=span.get('start'),span.get('end');value=span.get('text')
        if (type(a) is not int or type(b) is not int or not 0<=a<b<=len(text) or a<last
                or not isinstance(value,str) or text[a:b]!=value):raise MinuteRunError('dialogue_span_not_exact_original_text')
        last=b
        values.append(value[1:-1] if len(value)>1 and (value[0],value[-1]) in (('“','”'),('「','」')) else value)
    quoted=re.findall(r'“([^”]+)”|「([^」]+)」',text,re.S)
    if quoted and [a or b for a,b in quoted]!=values:raise MinuteRunError('dialogue_span_coverage_changed')
    return values


def _adaptation(audit_binding,approval_binding):
    audit=check(audit_binding);approval=check(approval_binding)
    if audit.get('schema')!='reference_prompt_adaptation/v21' or [r.get('id') for r in audit.get('segments',[])]!=list(IDS):
        raise MinuteRunError('four_segment_adaptation_audit_required')
    if (approval.get('schema')!='root_reference_prompt_approval/v21' or approval.get('reviewed_by')!='root_agent'
            or approval.get('approved_for_generation') is not True or approval.get('audit')!=audit_binding):
        raise MinuteRunError('root_prompt_approval_required')
    for row in audit['segments']:
        original=_original(check(row['original_request']))
        _check(row['original_prompt_file']);_check(row['adapted_prompt_file'])
        before=Path(row['original_prompt_file']['path']).read_bytes().decode('utf-8')
        after=Path(row['adapted_prompt_file']['path']).read_bytes().decode('utf-8')
        if (before!=original or _hash_text(before)!=row['original_prompt_utf8_sha256']
                or _hash_text(after)!=row['adapted_prompt_utf8_sha256']):raise MinuteRunError('original_or_adapted_prompt_binding_changed')
        if _dialogues(before,row['original_dialogue_spans'])!=_dialogues(after,row['adapted_dialogue_spans']):
            raise MinuteRunError('adaptation_changed_original_dialogue')
        if approval.get('adapted_prompt_sha256',{}).get(row['id'])!=row['adapted_prompt_utf8_sha256']:
            raise MinuteRunError('root_approved_prompt_sha_changed')
    return audit


def _references(bundle):
    refs=bundle.get('references',[]);cast=bundle.get('source_shot',{}).get('visible_cast',[])
    people=[r for r in refs if r.get('kind')=='character'];places=[r for r in refs if r.get('kind')=='place']
    if (len(refs)!=5 or len(cast)!=3 or len(set(cast))!=3 or len(people)!=3
            or {r['entity_id'] for r in people}!=set(cast) or any(r['view']!='front' for r in people)
            or len(places)!=2 or len({r['entity_id'] for r in places})!=1
            or {r['view'] for r in places}!={'front','side'}):raise MinuteRunError('each_segment_requires_same_three_people_and_room_five_refs')
    records=[{k:deepcopy(r[k]) for k in ('reference_id','entity_id','kind','view','image')} for r in refs]
    return native.fingerprint(records)


def _delivery_row(segment,current=False):
    path=Path(segment['delivery_run']).resolve();_,plan=delivery._load(path,current=current)
    if (plan.get('schema')!=delivery.SCHEMA or len(plan.get('shots',[]))!=1
            or plan['shots'][0]['id']!=segment['shot_id'] or plan['config']['width']!=WIDTH or plan['config']['height']!=HEIGHT):
        raise MinuteRunError('only_new_v20_single_segment_plans_allowed')
    row=plan['shots'][0];folder=path/'shots'/row['id'];graph=native.read(folder/'workflow_api.json')
    inputs=graph['condition']['inputs'];slots=[k for k in inputs if k.startswith('ref_images.')]
    if (graph['condition']['class_type']!='MiniMaxH3ReferenceToVideo'
            or graph['127']['inputs']['unet_name']!='minimax_h3_ref2va_pruned_int8_convrot.safetensors'
            or set(slots)!={'ref_images.ref_image_'+str(i) for i in range(5)}
            or (inputs.get('width'),inputs.get('height'),graph['130']['inputs']['fps'])!=(WIDTH,HEIGHT,FPS)
            or any(k in inputs for k in ('first_frame','last_frame','ref_images'))
            or row['timing']['native_frames']!=FRAMES or abs(row['timing']['native_seconds']-FRAMES/FPS)>1e-8):
        raise MinuteRunError('real_five_reference_362_frame_ref2va_required')
    bundle=native.read(folder/'REFERENCE_BUNDLE.json');global_sha=_references(bundle)
    text=(folder/'SOURCE_PROMPT.txt').read_bytes().decode('utf8')
    if _hash_text(text)!=segment['adapted_prompt_utf8_sha256'] or row['source_prompt_sha256']!=segment['adapted_prompt_utf8_sha256']:
        raise MinuteRunError('delivery_did_not_use_approved_adapted_prompt')
    if row.get('source_prompt_file')!=segment['source_prompt_file']:raise MinuteRunError('delivery_source_file_changed')
    return path,plan,row,folder,global_sha


def _shared_reuse(plans):
    """All four immutable routes use one donor/source authority, not four copies."""
    manifests=[p.get('reuse_manifest') for p in plans]
    if (not manifests or any(p.get('reuse_contract')!='reviewed_donor_assets/v21' for p in plans)
            or any(m!=manifests[0] for m in manifests)):
        raise MinuteRunError('same_reviewed_reuse_manifest_required_for_all_four_segments')
    _check(manifests[0])
    return manifests[0]


def prepare(run,segments,*,adaptation_audit,prompt_approval,authorization):
    run=_scope(run);audit_binding=_bind(adaptation_audit);approval_binding=_bind(prompt_approval);auth_binding=_bind(authorization)
    auth=check(auth_binding)
    budgets=[auth[k] for k in ('max_submissions','max_new_native_submissions') if k in auth]
    if not auth.get('user_statement') or not budgets or any(type(n) is not int or n!=4 for n in budgets):
        raise MinuteRunError('explicit_four_native_submissions_authorization_required')
    audit=_adaptation(audit_binding,approval_binding)
    if [r.get('id') for r in segments]!=list(IDS):raise MinuteRunError('four_ordered_segments_required')
    _shared_reuse([native.read(Path(s['delivery_run'])/'PLAN.json') for s in segments])
    planned=[]
    for given,source in zip(segments,audit['segments']):
        segment=dict(id=given['id'],delivery_run=str(Path(given['delivery_run']).resolve()),shot_id=given['shot_id'],
            source_request=source['original_request'],original_prompt_file=source['original_prompt_file'],
            original_prompt_utf8_sha256=source['original_prompt_utf8_sha256'],source_prompt_file=_bind(given.get('source_prompt_file',source['adapted_prompt_file'])),
            audited_adapted_prompt_file=source['adapted_prompt_file'],
            adapted_prompt_utf8_sha256=source['adapted_prompt_utf8_sha256'])
        _check(segment['source_prompt_file'])
        if Path(segment['source_prompt_file']['path']).read_bytes()!=Path(source['adapted_prompt_file']['path']).read_bytes():
            raise MinuteRunError('delivery_copy_differs_from_approved_adapted_prompt')
        path,plan,row,folder,refs=_delivery_row(segment,current=False)
        segment.update(delivery_plan=binding(path/'PLAN.json'),reference_manifest=binding(folder/'REFERENCE_BUNDLE.json'),
            global_references_sha256=refs,protected_pause=plan['protected_pause'])
        planned.append(segment)
    if (len({r['delivery_run'] for r in planned})!=4 or len({r['adapted_prompt_utf8_sha256'] for r in planned})!=4
            or len({r['global_references_sha256'] for r in planned})!=1
            or any(r['protected_pause']!=planned[0]['protected_pause'] for r in planned)):
        raise MinuteRunError('independent_segments_same_global_references_and_pause_required')
    # One complete current validation covers the shared source, both donors and
    # all five identical reference assets; the other three frozen graphs/texts
    # have already been checked above. No donor-validation bypass is introduced.
    if _delivery_row(planned[0],current=True)[4]!=planned[0]['global_references_sha256']:
        raise MinuteRunError('global_reference_set_changed')
    plan=dict(schema=SCHEMA,segments=planned,adaptation_audit=audit_binding,prompt_approval=approval_binding,authorization=auth_binding,
        global_references_sha256=planned[0]['global_references_sha256'],protected_pause=planned[0]['protected_pause'],
        width=WIDTH,height=HEIGHT,fps=FPS,frames_per_segment=FRAMES,total_frames=4*FRAMES,max_submissions=4,
        require_root_review=True,semantic_retry=False,publication=False,production_approved=False,old_batch_resume=False)
    run.mkdir(parents=True,exist_ok=True)
    with jobs.run_lock(run,'PREPARE.lock'):
        native.freeze(run/'RUNNER_PLAN.json',plan)
        native.freeze(run/'PREPARATION.json',dict(plan=binding(run/'RUNNER_PLAN.json'),executor=binding(__file__),media_dispatched=False))
        if not (run/'STATE.json').exists():native.write(run/'STATE.json',dict(stage='prepared',pid=None))
    return status(run)


def _load(run,current=False,*,fresh=True):
    run=_scope(run);prep=native.read(run/'PREPARATION.json');plan=check(prep['plan'])
    if (Path(prep['plan']['path']).resolve()!=run/'RUNNER_PLAN.json' or plan.get('schema')!=SCHEMA
            or [r['id'] for r in plan.get('segments',[])]!=list(IDS) or plan.get('total_frames')!=1448
            or plan.get('require_root_review') is not True or plan.get('max_submissions')!=4):raise MinuteRunError('frozen_minute_plan_changed')
    delivery_plans=[]
    for row in plan['segments']:
        delivery_plans.append(check(row['delivery_plan']));check(row['reference_manifest'])
        _check(row['source_prompt_file']);_check(row['source_request'])
        if _delivery_row(row,current=False)[4]!=plan['global_references_sha256']:raise MinuteRunError('global_reference_set_changed')
    _shared_reuse(delivery_plans)
    if current:
        _check(prep['executor']);_check(plan['authorization']);_check(plan['protected_pause']);_adaptation(plan['adaptation_audit'],plan['prompt_approval'])
        if 'diagnostic_preview_override' in prep:_check(prep['diagnostic_preview_override'])
        if 'predecessor' in prep:
            previous=check(prep['predecessor']['preparation']);_check(prep['predecessor']['executor'])
            if previous['plan']!=prep['plan'] or previous['executor']['sha256']!=prep['predecessor']['executor']['sha256']:
                raise MinuteRunError('executor_predecessor_audit_changed')
            _check(prep['cpu_tests'])
        if fresh and _delivery_row(plan['segments'][0],current=True)[4]!=plan['global_references_sha256']:
            raise MinuteRunError('global_reference_set_changed')
    return run,plan


def _result(segment):
    path,plan,row,folder,refs=_delivery_row(segment,current=False);state=delivery.status(path)['shots'][0]
    if state['status']!='technical_saved':raise MinuteRunError('segment_not_technically_saved')
    result=native.read(folder/'RESULT.json')
    if (result.get('schema')!=delivery.SCHEMA or result.get('shot_id')!=row['id'] or result.get('prompt_id')!=state.get('prompt_id')
            or result.get('source_prompt_sha256')!=segment['adapted_prompt_utf8_sha256']
            or result.get('reference_bundle_sha256')!=row['bundle_sha256'] or refs!=segment['global_references_sha256']):
        raise MinuteRunError('native_result_not_current_reference_segment')
    return result,folder/'RESULT.json'


def _root_review(run,plan,segment,result):
    file=run/'segments'/segment['id']/'ROOT_SEGMENT_REVIEW.json'
    if not file.exists():return None
    review=native.read(file)
    expected=dict(schema='root_reference_segment_review/v20',segment_id=segment['id'],shot_id=segment['shot_id'],prompt_id=result['prompt_id'],
        video={k:result['files']['video'][k] for k in ('path','sha256')},source_prompt_sha256=segment['adapted_prompt_utf8_sha256'],
        global_references_sha256=plan['global_references_sha256'],runner_plan_sha256=native.file_sha(run/'RUNNER_PLAN.json'),reviewed_by='root_agent')
    if any(review.get(k)!=v for k,v in expected.items()) or type(review.get('approved_for_next')) is not bool:
        raise MinuteRunError('root_segment_review_not_bound_to_current_native')
    evidence=review.get('evidence',{})
    for key in ('contact','last','asr'):_check(evidence[key])
    if evidence['last']!={k:result['files']['last'][k] for k in ('path','sha256')}:raise MinuteRunError('root_review_last_frame_changed')
    _objective(segment,result,evidence['asr'])
    cpu_file=run/'segments'/segment['id']/'CPU_QA_RESULT.json'
    if not cpu_file.exists():return None
    cpu=native.read(cpu_file)
    if cpu.get('manifest')!=evidence['asr'] or cpu.get('contact')!=evidence['contact']:raise MinuteRunError('root_review_CPU_evidence_changed')
    return review


def status(run=RUN):
    run,plan=_load(run);rows=[];ids=[]
    for segment in plan['segments']:
        s=delivery.status(segment['delivery_run'])
        if len(s['shots'])!=1:raise MinuteRunError('single_native_segment_required')
        state=s['shots'][0];item=dict(id=segment['id'],delivery_run=segment['delivery_run'],state=state,paused=s['paused'],video_enabled=s['video_enabled'],root_review=None)
        if state.get('prompt_id'):ids.append(state['prompt_id'])
        if state['status']=='technical_saved':item['root_review']=_root_review(run,plan,segment,_result(segment)[0])
        rows.append(item)
    if len(ids)!=len(set(ids)):raise MinuteRunError('duplicate_native_id_across_segments')
    preview=None
    if (run/'USER_PREVIEW_OVERRIDE.json').exists():
        from . import visual_h3_diagnostic_preview_v23 as diagnostic
        preview=diagnostic.validate(run,plan)
    return dict(schema=SCHEMA,run=str(run),segments=rows,technical_saved=sum(x['state']['status']=='technical_saved' for x in rows),
        reviewed=sum(bool(x['root_review'] and x['root_review']['approved_for_next']) for x in rows),
        paused=(run/'PAUSE.json').exists(),total=4,global_references_sha256=plan['global_references_sha256'],
        diagnostic_preview=bool(preview),quality_failed=[x['id'] for x in rows if x['root_review'] is not None and not x['root_review']['approved_for_next']],
        production_approved=False,publication=False)


def _event(run,kind,detail):
    with (run/'LOG.md').open('a',encoding='utf8') as stream:stream.write(datetime.now(timezone.utc).isoformat()+' '+kind+' '+str(detail)+'\n')


def _evidence(run,plan,snapshot):
    ledger=native.read(run/'NATIVE_IDS.json') if (run/'NATIVE_IDS.json').exists() else {}
    for segment,item in zip(plan['segments'],snapshot['segments']):
        pid=item['state'].get('prompt_id');sid=segment['id'];folder=run/'segments'/sid;folder.mkdir(parents=True,exist_ok=True)
        if pid:
            if sid in ledger and ledger[sid]!=pid:raise MinuteRunError('original_native_id_cannot_be_replaced')
            if sid not in ledger:
                if pid in ledger.values():raise MinuteRunError('duplicate_native_id_across_segments')
                ledger[sid]=pid;native.write(run/'NATIVE_IDS.json',ledger)
                _event(run,'NATIVE_ID',sid+' '+pid)
    ids_file=run/'job_ids.txt';existing=ids_file.read_text(encoding='utf8').splitlines() if ids_file.exists() else []
    expected=[sid+' '+ledger[sid] for sid in IDS if sid in ledger]
    if len(existing)!=len(set(existing)) or any(line not in expected for line in existing):raise MinuteRunError('native_id_text_log_changed')
    with ids_file.open('a',encoding='utf8') as stream:
        for line in expected:
            if line not in existing:stream.write(line+'\n')
        stream.flush();os.fsync(stream.fileno())
    # The native-ID ledger is durable before any potentially slow CPU ASR.
    for segment,item in zip(plan['segments'],snapshot['segments']):
        if item['state']['status']=='technical_saved':
            sid=segment['id'];folder=run/'segments'/sid;result,result_file=_result(segment)
            cpu=_ensure_cpu_qa(run,segment,result)
            native.freeze(folder/'QA_READY.json',dict(segment_id=sid,prompt_id=result['prompt_id'],source_prompt_sha256=segment['adapted_prompt_utf8_sha256'],
                global_references_sha256=plan['global_references_sha256'],result=binding(result_file),files=deepcopy(result['files']),
                cpu_qa=cpu,content_status='root_actual_contact_last_and_CPU_ASR_review_required',actual_video_approved=False))


def _objective(segment,result,manifest):
    data=check(manifest);target=data.get('binding',{})
    _,result_file=_result(segment)
    if (Path(target.get('delivery_run','')).resolve()!=Path(segment['delivery_run']).resolve()
            or Path(target.get('result_path','')).resolve()!=result_file.resolve()
            or target.get('result_sha256')!=native.file_sha(result_file)
            or target.get('source_prompt')!=segment['source_prompt_file']
            or target.get('prompt_id')!=result['prompt_id']
            or any(target.get('video',{}).get(k)!=result['files']['video'][k] for k in ('path','sha256'))):
        raise MinuteRunError('CPU_QA_not_bound_to_current_native_video')
    return data


def _ensure_cpu_qa(run,segment,result):
    folder=run/'segments'/segment['id'];folder.mkdir(parents=True,exist_ok=True);receipt=folder/'CPU_QA_RESULT.json'
    if receipt.exists():value=native.read(receipt)
    else:
        command=[str(PROJECT/'.venv/Scripts/python.exe'),str(QA_SCRIPT),'segment','--run',str(run),'--segment',segment['id'],
            '--delivery-run',segment['delivery_run'],'--source-prompt',segment['source_prompt_file']['path'],'--asr']
        native.freeze(folder/'CPU_QA_REQUEST.json',dict(command=command,video_sha256=result['files']['video']['sha256'],prompt_id=result['prompt_id']))
        process=subprocess.run(command,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=1800)
        if process.returncode:
            native.write(folder/'CPU_QA_ERROR.latest.json',dict(returncode=process.returncode,stdout=process.stdout,stderr=process.stderr))
            raise MinuteRunError('CPU_QA_failed_video_preserved_no_media_retry')
        try:value=json.loads(process.stdout)
        except (ValueError,TypeError) as error:raise MinuteRunError('CPU_QA_single_JSON_response_required') from error
        _objective(segment,result,value['manifest']);_check(value['contact'])
        native.freeze(receipt,value)
    if (value.get('status')!='cpu_qa_complete' or value.get('segment')!=segment['id'] or value.get('prompt_id')!=result['prompt_id']
            or value.get('video_sha256')!=result['files']['video']['sha256'] or value.get('production_approved') is not False):
        raise MinuteRunError('CPU_QA_response_target_changed')
    _objective(segment,result,value['manifest']);_check(value['contact'])
    return value


def _tick(run,deadline=None):
    run,plan=_load(run)
    # Even when paused, collect only known original IDs; never discard outputs.
    before=status(run)
    for row in before['segments']:
        s=row['state']
        if s.get('prompt_id') and s['status'] not in ('technical_saved','failed','interrupted','rejected'):
            delivery.poll_collect(row['delivery_run'])
    snapshot=status(run);_evidence(run,plan,snapshot)
    preview=snapshot['diagnostic_preview'];stage='all_preview_segments_saved' if preview else 'all_segments_reviewed'
    for index,(segment,item) in enumerate(zip(plan['segments'],snapshot['segments'])):
        state=item['state'];sid=segment['id']
        future_claimed=any(x['state'].get('prompt_id') or x['state']['status']!='prepared' for x in snapshot['segments'][index+1:])
        prior_approved=state['status']=='technical_saved' and (preview or item['root_review'] is not None and item['root_review']['approved_for_next'])
        if future_claimed and not prior_approved:
            stage='blocked_out_of_order_existing_submission';break
        if state['status'] in TERMINAL_BAD:stage='blocked_'+state['status'];break
        if state['status']=='technical_saved':
            if preview:continue
            review=item['root_review']
            if review is None:stage='waiting_root_review';break
            if not review['approved_for_next']:stage='stopped_root_rejected';break
            continue
        if snapshot['paused'] or item['paused']:stage='paused';break
        if not item['video_enabled']:stage='video_policy_disabled';break
        if state['status']=='prepared':
            if deadline is not None and time.monotonic()>=deadline:stage='bounded_wait_ended_original_ids_preserved';break
            # submit_next performs its own full current validation of this
            # exact shared reuse manifest immediately before its protected POST.
            # Rechecking four equivalent donor graphs here only wastes GPU idle
            # time; retain all four frozen graph/text checks and our local gates.
            _load(run,current=True,fresh=False)
            if deadline is not None and time.monotonic()>=deadline:stage='bounded_wait_ended_original_ids_preserved';break
            delivery.submit_next(segment['delivery_run'])
            snapshot=status(run);_evidence(run,plan,snapshot);stage='native_submitted_or_waiting_queue'
        else:stage='collecting_original_native_id'
        break
    else:sid=None
    result=dict(snapshot,stage=stage,current_segment=sid,pid=os.getpid(),heartbeat=time.time())
    previous=native.read(run/'STATE.json') if (run/'STATE.json').exists() else {}
    if (previous.get('stage'),previous.get('current_segment'))!=(stage,sid):_event(run,stage,sid)
    native.write(run/'STATE.json',result)
    return result


@contextmanager
def _runner_locks(run):
    _,plan=_load(run)
    with ExitStack() as stack:
        stack.enter_context(jobs.run_lock(run,'RUNNER.lock'))
        for segment in plan['segments']:
            stack.enter_context(jobs.run_lock(Path(segment['delivery_run']),'RUNNER.lock'))
        yield


def tick(run=RUN):
    run=_scope(run)
    with _runner_locks(run):return _tick(run)


def execute(run=RUN,*,poll_seconds=30,max_seconds=86400):
    if not 1<=poll_seconds<=60 or not 0<max_seconds<=86400:raise MinuteRunError('bounded_poll_window_required')
    run=_scope(run)
    with _runner_locks(run):
        start=time.monotonic()
        try:
            while True:
                result=_tick(run,deadline=start+max_seconds)
                if result['stage'].startswith(('blocked','stopped')) or result['stage'] in ('video_policy_disabled','all_segments_reviewed','all_preview_segments_saved'):
                    return result
                active=any(r['state'].get('prompt_id') and r['state']['status'] in ('submitted','running') for r in result['segments'])
                if result['paused'] and not active:return dict(result,stage='paused')
                if result['stage']=='bounded_wait_ended_original_ids_preserved':return result
                if time.monotonic()-start>=max_seconds:return dict(result,dispatch='bounded_wait_ended_original_ids_preserved')
                time.sleep(poll_seconds)
        except BaseException as error:
            _event(run,'RUNNER_STOP',type(error).__name__+' '+str(error));raise


def _probe(path):
    return json.loads(subprocess.check_output(['ffprobe','-v','error','-threads','1','-count_frames','-show_streams','-show_format','-of','json',str(path)],text=True,encoding='utf8',timeout=180))


def _duration(stream):return Fraction(int(stream['duration_ts']))*Fraction(stream['time_base'])


def _clock_input(path,sha):
    if native.file_sha(path)!=sha:raise MinuteRunError('assembly_input_changed')
    meta=_probe(path);video=next(x for x in meta['streams'] if x['codec_type']=='video');audio=next(x for x in meta['streams'] if x['codec_type']=='audio')
    if ((video['width'],video['height'],int(video.get('nb_frames',-1)),int(video.get('nb_read_frames',-1)),video['r_frame_rate'],video['avg_frame_rate'])!=(WIDTH,HEIGHT,FRAMES,FRAMES,'24/1','24/1')
            or _duration(video)!=Fraction(FRAMES,FPS)):
        raise MinuteRunError('native_input_video_clock_changed')
    target=Fraction(FRAMES,FPS)
    if max(abs(_duration(audio)-target),abs(Fraction(audio['start_time'])),abs(Fraction(audio['start_time'])+_duration(audio)-target))>Fraction(1,4):
        raise MinuteRunError('native_source_audio_skew_too_large')
    pcm=subprocess.check_output(['ffmpeg','-nostdin','-v','error','-threads','1','-i',str(path),'-map','0:a:0','-af','aresample=48000:async=0:first_pts=0','-ar','48000','-ac','2','-c:a','pcm_s16le','-f','s16le','pipe:1'],stderr=subprocess.PIPE,timeout=180)
    if not pcm or len(pcm)%4:raise MinuteRunError('native_audio_decode_failed')
    samples=len(pcm)//4
    if abs(Fraction(samples,RATE)-target)>Fraction(1,4)+Fraction(1024,int(audio['sample_rate']))+Fraction(1,RATE):raise MinuteRunError('native_decoded_audio_clock_changed')
    if native.file_sha(path)!=sha:raise MinuteRunError('assembly_input_changed')
    return dict(native_metadata=meta,decoded_48k_samples=samples,target_samples=FRAMES*2000,
        trim_tail_samples=max(0,samples-FRAMES*2000),pad_tail_samples=max(0,FRAMES*2000-samples))


def assemble(run=RUN):
    run,plan=_load(run,current=True)
    with jobs.run_lock(run,'ASSEMBLY.lock'):
        snapshot=status(run)
        if snapshot['technical_saved']!=4 or snapshot['reviewed']!=4:raise MinuteRunError('four_saved_and_root_reviewed_segments_required')
        rows=[_result(s)[0] for s in plan['segments']]
        ids=[r['prompt_id'] for r in rows];videos=[r['files']['video'] for r in rows]
        if any(len(set(values))!=4 for values in (ids,[v['sha256'] for v in videos],[v['path'] for v in videos],[v['source_path'] for v in videos])):
            raise MinuteRunError('four_distinct_original_native_videos_required')
        final_review=native.read(run/'ROOT_FINAL_REVIEW.json') if (run/'ROOT_FINAL_REVIEW.json').exists() else {}
        expected=dict(schema='root_reference_final_review/v20',reviewed_by='root_agent',approved_for_assembly=True,
            runner_plan_sha256=native.file_sha(run/'RUNNER_PLAN.json'),global_references_sha256=plan['global_references_sha256'],native_ids=ids,video_sha256=[v['sha256'] for v in videos])
        if any(final_review.get(k)!=v for k,v in expected.items()):raise MinuteRunError('root_four_segment_final_review_required')
        inputs=dict(plan=binding(run/'RUNNER_PLAN.json'),results=[binding(_result(s)[1]) for s in plan['segments']],
            root_reviews=[binding(run/'segments'/s['id']/'ROOT_SEGMENT_REVIEW.json') for s in plan['segments']],final_review=binding(run/'ROOT_FINAL_REVIEW.json'),native_ids=ids,video_sha256=[v['sha256'] for v in videos])
        digest=native.fingerprint(inputs);final=run/'FINAL_RESULT.json';output=run/'h3_reference_full_minute_736x1312.mp4'
        if final.exists():
            result=native.read(final);_check(result['file'])
            if result['assembly_inputs_sha256']!=digest:raise MinuteRunError('final_assembly_inputs_changed')
            return result
        if output.exists():raise MinuteRunError('unreceipted_final_output_preserved')
        timings=[_clock_input(v['path'],v['sha256']) for v in videos]
        filters=run/'ASSEMBLY_FILTER.txt';command,text=clock.assembly_command([v['path'] for v in videos],filters,output,frames=FRAMES)
        if filters.exists() and filters.read_text(encoding='utf8')!=text:raise MinuteRunError('assembly_filter_changed')
        filters.write_text(text,encoding='utf8');native.freeze(run/'ASSEMBLY_REQUEST.json',dict(inputs=inputs,inputs_sha256=digest,command=command,clock_adjustments=timings))
        process=subprocess.run(command,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=1800)
        (run/'ASSEMBLY.stderr.log').write_text(process.stderr,encoding='utf8');process.check_returncode()
        result_clock=clock.verify_clock(_probe(output),frames=1448,width=WIDTH,height=HEIGHT)
        # Recheck all original IDs/files after CPU encoding.
        if [binding(_result(s)[1]) for s in plan['segments']]!=inputs['results']:raise MinuteRunError('assembly_source_result_changed')
        result=dict(schema=SCHEMA,file=binding(output),assembly_inputs_sha256=digest,native_ids=ids,clock=result_clock,
            source_clock_adjustments=timings,content_status='root_complete_movie_review_required',production_approved=False,publication=False)
        native.freeze(final,result);_event(run,'FINAL_ASSEMBLED',str(output));return result


def qa(run=RUN,segment_id='S01'):
    """Explicit CPU-only QA retry, never a media retry or content approval."""
    run,plan=_load(run);segment=next((s for s in plan['segments'] if s['id']==segment_id),None)
    if segment is None:raise MinuteRunError('known_segment_required')
    with jobs.run_lock(run,'RUNNER.lock'):
        result,_=_result(segment);return _ensure_cpu_qa(run,segment,result)
