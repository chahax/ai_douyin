"""One authorized, full-track local CPU ASR pass; immutable receipts on success.

Claims survive failures and timeouts. A claimed subject is never automatically
transcribed again, including from another run directory. Cached verification
only reads pinned evidence and never starts a process.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import wave

from . import audio_full_scope_v1 as scope
from .visual_image_jobs_v3 import run_lock

PROJECT = scope.PROJECT
SCHEMA = 'local_audio_inspection/v1'


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def _read(path):
    return json.loads(scope.local(path).read_text(encoding='utf-8-sig'))


def _freeze(path, value):
    path = scope.local(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(_read(path) == value, 'frozen_inspection_evidence_changed')
    else:
        with path.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
    return scope.bind(path)


def _models(root):
    root = scope.local(root)
    files = []
    for model in ('paraformer-zh', 'fsmn-vad'):
        folder = root / model
        require(folder.is_dir() and (folder/'config.yaml').is_file()
                and (folder/'model.pt').is_file(), 'complete_local_ASR_model_required')
        for path in sorted(folder.rglob('*')):
            if path.is_file() and not any(p in ('example','fig','.git') for p in path.relative_to(folder).parts):
                files.append(scope.bind(path))
    return files


def _inputs(run, candidate_binding, authority_binding):
    run = scope.local(run)
    candidate = scope.read(candidate_binding)
    require(candidate.get('schema') == 'media_repair_candidate/v1'
            and candidate.get('completion_known') is True and candidate.get('outcome_unknown') is False,
            'completed_candidate_required')
    for key in ('native_id','attempt_id','segment_id'):
        require(isinstance(candidate.get(key),str) and candidate[key], 'candidate_identity_required')
    scope.checked(candidate['media'])
    result = scope.read(candidate['result'])
    require(result.get('prompt_id',result.get('native_id')) == candidate['native_id']
            and {k:result.get('files',{}).get('video',result.get('media',{})).get(k)
                 for k in ('path','sha256')} == candidate['media'], 'candidate_result_subject_mismatch')
    clock = scope.read(candidate['audio_clock_receipt'])
    require(clock.get('schema') == 'media_repair_candidate_clock/v1'
            and clock.get('native_id') == candidate['native_id'] and clock.get('media') == candidate['media']
            and clock.get('result') == candidate['result']
            and clock.get('nominal_frame_clock') == candidate['nominal_frame_clock']
            and clock.get('normalization_verified') is True and clock.get('content_trimmed') is False,
            'candidate_clock_subject_mismatch')
    for item in clock.get('evidence',[]):
        scope.checked(item)
    authority = scope.read(authority_binding)
    require(authority.get('schema') == 'local_audio_inspection_authority/v1'
            and authority.get('issued_by') == 'audio_quality_execution_v1'
            and authority.get('confirmed_by') == 'parent_authority_delegation'
            and authority.get('candidate') == candidate_binding
            and type(authority.get('max_ASR_calls')) is int and authority['max_ASR_calls'] == 1,
            'exact_delegated_single_ASR_authority_required')
    parent = scope.read(authority['parent_authority'])
    require(parent.get('schema') == 'audio_quality_execution_authority/v1'
            and parent.get('confirmed_by') == 'user' and parent.get('trial_scope') == 'audio_only_test'
            and type(parent.get('max_CPU_edits')) is int and parent['max_CPU_edits'] == 1
            and type(parent.get('max_ASR_calls')) is int and parent['max_ASR_calls'] == 1
            and type(parent.get('max_H3_calls')) is int and parent['max_H3_calls'] == 0
            and parent.get('allow_ambient_loss') is True and parent.get('assembly_allowed') is False,
            'bounded_parent_audio_only_authority_required')
    trial = scope.local(parent['trial_run'])
    require(run.is_relative_to(trial) and run != trial, 'inspection_run_outside_parent_trial')
    source = scope.read(parent['source_candidate'])
    for item in (parent['source_case'],parent['asset_manifest']):
        scope.checked(item)
    require(source.get('source_case') == parent['source_case']
            and source.get('asset_manifest') == parent['asset_manifest']
            and candidate.get('source_case') == parent['source_case']
            and candidate.get('asset_manifest') == parent['asset_manifest'], 'parent_source_materials_mismatch')
    full = scope.validate_bound(authority['source_full_audio_inspection'])
    require(full['candidate'] == parent['source_candidate']
            and full['native_id'] == source['native_id'] and full['media'] == source['media'],
            'parent_source_scope_mismatch')
    derivation = scope.read(authority['derivation'])
    require(derivation.get('schema') == 'media_audio_derivation/v1'
            and derivation.get('parent_authority') == authority['parent_authority']
            and derivation.get('source_candidate') == parent['source_candidate']
            and derivation.get('source_case') == parent['source_case']
            and derivation.get('asset_manifest') == parent['asset_manifest']
            and derivation.get('source_native_id') == source['native_id']
            and derivation.get('source_media') == source['media']
            and derivation.get('native_id') == candidate['native_id']
            and derivation.get('media') == candidate['media'], 'exact_authorized_derivation_required')
    require(derivation.get('operation') == 'cleanup_gap'
            and candidate['native_id'] != source['native_id'] and candidate['media'] != source['media']
            and scope.checked(candidate['media']).is_relative_to(trial),
            'parent_audio_only_scope_requires_new_trial_gap_edit')
    evidence = derivation.get('evidence',[])
    require(isinstance(evidence,list) and evidence, 'derivation_evidence_required')
    for item in evidence:
        scope.checked(item)
    if derivation['operation'] == 'cleanup_gap':
        plan = scope.read(derivation['processor_plan'])
        repaired = scope.read(derivation['processor_result'])
        proof = scope.read(derivation['processor_proof'])
        require(candidate['native_id'] != source['native_id']
                and plan.get('schema') == 'audio_gap_repair/v1'
                and plan.get('details',{}).get('media') == source['media']
                and plan['details'].get('frame_clock') == candidate['nominal_frame_clock']
                and candidate['nominal_frame_clock'] == source['nominal_frame_clock'] == full['frame_clock']
                and repaired.get('schema') == 'audio_gap_repair/v1'
                and repaired.get('plan') == derivation['processor_plan']
                and repaired.get('proof') == derivation['processor_proof']
                and repaired.get('file') == candidate['media']
                and proof.get('schema') == 'audio_gap_repair_proof/v1'
                and proof.get('input') == source['media'] and proof.get('output') == candidate['media']
                and proof.get('video_frames_PTS_and_decoded_hashes_unchanged') is True,
                'cleanup_derivation_processor_subject_mismatch')
        require(all(derivation[k] in evidence for k in ('processor_plan','processor_result','processor_proof')),
                'cleanup_processor_evidence_not_listed')
    timeout = authority.get('timeout_seconds')
    require(type(timeout) is int and 1 <= timeout <= 3600, 'bounded_process_timeout_required')
    script = scope.checked(authority['transcriber'])
    require(script == PROJECT/'scripts/transcribe_video_local.py', 'pinned_local_transcriber_required')
    models = _models(authority['model_root'])
    return dict(candidate=candidate_binding, authority=authority_binding, code=scope.bind(__file__),
        verifier=scope.bind(scope.__file__), parent_authority=authority['parent_authority'],
        model_files=models, transcriber=authority['transcriber'],
        model_root=str(scope.local(authority['model_root'])), timeout_seconds=timeout,
        native_id=candidate['native_id'], attempt_id=candidate['attempt_id'], segment_id=candidate['segment_id'],
        media=candidate['media'])


def _subject_key(plan):
    value={'native_id':plan['native_id']}
    value['media_sha256']=plan['media']['sha256']
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _environment():
    values=dict(HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1',TRANSFORMERS_OFFLINE='1',MODELSCOPE_OFFLINE='1',
        HF_HUB_DISABLE_TELEMETRY='1',CUDA_VISIBLE_DEVICES='',NVIDIA_VISIBLE_DEVICES='none',
        SOURCE_ANALYSIS_LOW_MEMORY='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',
        NUMEXPR_NUM_THREADS='2',PYTHONIOENCODING='utf-8')
    return values


def _process(run,label,command,timeout):
    env=_environment()
    started=time.time()
    try:
        completed=subprocess.run(command,capture_output=True,timeout=timeout,env=dict(os.environ,**env))
        data=dict(schema='local_audio_inspection_process/v1',command=command,exit_code=completed.returncode,
            outcome_unknown=False,timed_out=False,started_at_epoch=started,finished_at_epoch=time.time(),
            controlled_environment=env,stdout_sha256=hashlib.sha256(completed.stdout).hexdigest(),
            stderr=completed.stderr.decode('utf-8',errors='replace'))
        binding=_freeze(run/'processes'/(label+'.json'),data)
        require(type(completed.returncode) is int and completed.returncode == 0,'inspection_process_failed:'+label)
        return binding
    except subprocess.TimeoutExpired as error:
        _freeze(run/'processes'/(label+'.json'),dict(schema='local_audio_inspection_process/v1',command=command,
            exit_code=None,outcome_unknown=True,timed_out=True,started_at_epoch=started,finished_at_epoch=time.time(),
            controlled_environment=env,description=str(error)))
        raise


def _header(path):
    with wave.open(str(path),'rb') as stream:
        values=dict(rate=stream.getframerate(),frames=stream.getnframes(),channels=stream.getnchannels(),
                    sample_width=stream.getsampwidth(),compression=stream.getcomptype())
        count=0
        while True:
            data=stream.readframes(65536)
            if not data:break
            count+=len(data)
    require(values['rate']==16000 and values['channels']==1 and values['sample_width']==2
            and values['compression']=='NONE' and count==values['frames']*2,'actual_full_PCM_WAV_required')
    return dict(schema='local_audio_wave_header/v1',waveform=scope.bind(path),**values)


def _artifacts(run):
    return [scope.bind(run/name) for name in ('PLAN.json','ASR_CLAIM.json','WHOLE.wav','RAW_ASR.json',
        'WAVE_HEADER.json','ASR_RECEIPT.json','FULL_AUDIO_INSPECTION.json')]+[
        scope.bind(run/'processes'/name) for name in ('extract.json','transcribe.json')]


def _parent_ledger(plan):
    return PROJECT/'data/local_audio_inspection_parent_claims_v1'/plan['parent_authority']['sha256']


def verify(run):
    """Validate completed cache with no subprocess, ASR, or media decoding."""
    run=scope.local(run)
    plan=_read(run/'PLAN.json')
    require(plan==_inputs(run,plan['candidate'],plan['authority']),'inspection_plan_inputs_changed')
    result=_read(run/'RESULT.json')
    require(result.get('schema')==SCHEMA and result.get('status')=='saved'
            and result.get('plan')==scope.bind(run/'PLAN.json'),'inspection_cache_plan_mismatch')
    require(result.get('artifacts')==_artifacts(run),'inspection_cache_artifact_set_changed')
    for item in result['artifacts']:
        scope.checked(item)
    receipt=scope.read(result['asr_receipt'])
    expected=scope.verify(result['asr_receipt'],plan['candidate'])
    require(expected==scope.read(result['full_audio_inspection']),'inspection_cached_scope_changed')
    require(receipt['asr_claim']==scope.bind(run/'ASR_CLAIM.json')
            and scope.read(result['wave_header'])==_header(scope.checked(receipt['audio_wave'])),
            'inspection_cached_wave_or_claim_changed')
    ledger=PROJECT/'data/local_audio_inspection_claims_v1'/_subject_key(plan)
    global_claim=_read(ledger/'CLAIM.json')
    require(global_claim.get('run')==str(run) and global_claim.get('claim')==receipt['asr_claim']
            and global_claim.get('candidate')==plan['candidate'], 'inspection_subject_ledger_mismatch')
    parent_claim=_read(_parent_ledger(plan)/'CLAIM.json')
    require(parent_claim==dict(run=str(run),claim=receipt['asr_claim'],candidate=plan['candidate'],
            authority=plan['authority'],parent_authority=plan['parent_authority']),
            'inspection_parent_once_ledger_mismatch')
    return dict(status='saved',asr_receipt=result['asr_receipt'],full_audio_inspection=result['full_audio_inspection'],
                receipt=scope.bind(run/'RESULT.json'),no_subprocess_on_reentry=True)


def inspect(run,candidate_binding,authority_binding):
    """Perform at most one authorized ASR pass; do not retry an unknown claim."""
    run=scope.local(run);run.mkdir(parents=True,exist_ok=True)
    plan=_inputs(run,candidate_binding,authority_binding)
    ledger=PROJECT/'data/local_audio_inspection_claims_v1'/_subject_key(plan)
    ledger.mkdir(parents=True,exist_ok=True)
    parent_ledger=_parent_ledger(plan);parent_ledger.mkdir(parents=True,exist_ok=True)
    with run_lock(parent_ledger,'PARENT.lock'),run_lock(ledger,'SUBJECT.lock'),run_lock(run,'INSPECTION.lock'):
        _freeze(run/'PLAN.json',plan)
        if (run/'RESULT.json').exists():return verify(run)
        if (parent_ledger/'CLAIM.json').exists() or (ledger/'CLAIM.json').exists() or (run/'ASR_CLAIM.json').exists():
            return dict(status='outcome_unknown',automatic_retry=False,reason='claimed_ASR_subject_not_replayed')
        require(not (run/'WHOLE.wav').exists() and not (run/'RAW_ASR.json').exists(),
                'unreceipted_inspection_outputs_preserved')
        claim=_freeze(run/'ASR_CLAIM.json',dict(schema='local_audio_inspection_claim/v1',plan=scope.bind(run/'PLAN.json'),
            candidate=candidate_binding,authority=authority_binding,native_id=plan['native_id'],attempt_id=plan['attempt_id'],
            media=plan['media'],at_epoch=time.time(),max_ASR_calls=1,automatic_retry=False))
        _freeze(ledger/'CLAIM.json',dict(run=str(run),claim=claim,candidate=candidate_binding,authority=authority_binding))
        _freeze(parent_ledger/'CLAIM.json',dict(run=str(run),claim=claim,candidate=candidate_binding,
            authority=authority_binding,parent_authority=plan['parent_authority']))
        try:
            wav=run/'WHOLE.wav';raw=run/'RAW_ASR.json'
            extract=['ffmpeg','-nostdin','-n','-v','warning','-threads','1','-i',plan['media']['path'],
                '-map','0:a:0','-vn','-af','aresample=16000:async=0:first_pts=0','-ar','16000','-ac','1',
                '-c:a','pcm_s16le',str(wav)]
            first=_process(run,'extract',extract,plan['timeout_seconds'])
            header=_freeze(run/'WAVE_HEADER.json',_header(wav))
            command=[str(PROJECT/'.venv/Scripts/python.exe'),'-X','utf8',plan['transcriber']['path'],str(wav),str(raw),
                '--model-root',plan['model_root'],'--without-punctuation','--hotword','']
            second=_process(run,'transcribe',command,plan['timeout_seconds'])
            transcript=_read(raw)
            require(transcript.get('schema')=='local_video_transcript/v1'
                    and scope.local(transcript['audio'])==wav and isinstance(transcript.get('result'),list),
                    'complete_local_transcript_required')
            actual=_header(wav)
            require(actual==scope.read(header),'ASR_input_wave_changed_during_execution')
            receipt=_freeze(run/'ASR_RECEIPT.json',dict(schema='h3_audio_transcript_receipt/v1',
                native_id=plan['native_id'],attempt_id=plan['attempt_id'],media=plan['media'],
                raw_asr=scope.bind(raw),audio_wave=scope.bind(wav),audio_wave_rate=actual['rate'],
                audio_wave_frames=actual['frames'],asr_claim=claim,transcriber=plan['transcriber'],
                processes=[first,second],completion_known=True,outcome_unknown=False))
            full=_freeze(run/'FULL_AUDIO_INSPECTION.json',scope.verify(receipt,candidate_binding))
            require(plan==_inputs(run,candidate_binding,authority_binding),'inspection_input_changed_during_execution')
            artifacts=_artifacts(run)
            _freeze(run/'RESULT.json',dict(schema=SCHEMA,status='saved',plan=scope.bind(run/'PLAN.json'),
                asr_receipt=receipt,full_audio_inspection=full,wave_header=header,artifacts=artifacts,
                ASR_calls=1,HTTP_calls=0,overall_video_accepted=False))
            return verify(run)
        except Exception as error:
            _freeze(run/'ERROR.json',dict(schema=SCHEMA,status='outcome_unknown',type=type(error).__name__,
                message=str(error),automatic_retry=False,claim=claim))
            return dict(status='outcome_unknown',automatic_retry=False,error=scope.bind(run/'ERROR.json'),claim=claim)
