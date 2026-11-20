"""Pinned repair-loop auditor; transcription occurs only in detect(candidate).

Baseline reads existing evidence. Fresh ASR has a claim before either subprocess;
an interrupted/failed call is preserved as unknown and never blindly repeated.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import traceback
import wave

from src.content_factory import h3_audio_conformance_v1 as rules
from src.content_factory.visual_image_jobs_v3 import run_lock

PROJECT = Path(__file__).resolve().parents[2]
VERSION = 'h3_repair_audio_auditor/v1'
CONFIG = 'h3_repair_audio_auditor_config/v1'


def require(value, reason):
    if not value:
        raise ValueError(reason)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def path(value):
    p = Path(value)
    require(p.is_absolute() and '://' not in str(value), 'absolute_local_path_required')
    p = p.resolve()
    require(p.is_relative_to(PROJECT.resolve()), 'path_outside_project')
    return p


def bind(value):
    p = path(value)
    with p.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(p), 'sha256': sha}


def checked(value):
    require(isinstance(value, dict) and set(value) == {'path', 'sha256'}, 'exact_file_binding_required')
    p = path(value['path'])
    require(bind(p) == value, 'bound_file_changed')
    return p


def read(value):
    return json.loads(path(value).read_text(encoding='utf-8-sig'))


def freeze(run, relative, value):
    dest = (path(run) / relative).resolve()
    require(dest.is_relative_to(path(run)) and dest != path(run), 'write_outside_repair_run')
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        require(digest(read(dest)) == digest(value), 'immutable_audio_evidence_changed')
    else:
        with dest.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
    return bind(dest)


def _native_binding(value):
    p = Path(value['path'])
    if not p.is_absolute():
        p = PROJECT / p
    item = {'path': str(path(p)), 'sha256': value['sha256']}
    checked(item)
    return item


def _inspect_saved_candidate(candidate, request, spec):
    """Pure byte/JSON checks, no ffprobe/decoding or model/service contact."""
    require(candidate.get('schema') == 'media_repair_candidate/v1'
            and candidate.get('attempt_id') == request['attempt_id']
            and candidate.get('segment_id') == request['segment_id']
            and candidate.get('native_id') not in {s['native_id'] for s in spec['segments']}
            and candidate.get('completion_known') is True and candidate.get('outcome_unknown') is False,
            'fresh_saved_candidate_identity_required')
    require(candidate.get('source_case') == spec['case_binding']
            and candidate.get('asset_manifest') == spec['asset_manifest'], 'candidate_source_or_assets_changed')
    result = read(checked(candidate['result']))
    require(result.get('prompt_id', result.get('native_id')) == candidate['native_id']
            and result.get('technical_status') in ('technical_saved', 'saved'), 'saved_native_result_required')
    roles = result.get('files', {})
    require(set(roles) == {'video', 'audio', 'first', 'last'}, 'all_four_native_originals_required')
    originals = {role: _native_binding(value) for role, value in roles.items()}
    require(originals['video'] == candidate['media'], 'native_video_must_be_exact_candidate_media')
    checked(candidate['media'])
    return originals


def _run_process(command, label, run, relative, timeout):
    """Only the fixed FFmpeg or pinned CPU transcriber argv constructed below."""
    env = dict(os.environ, CUDA_VISIBLE_DEVICES='', SOURCE_ANALYSIS_LOW_MEMORY='1')
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=timeout, env=env)
    except subprocess.TimeoutExpired as error:
        freeze(run, relative / (label + '_PROCESS.json'),
               {'command': command, 'exit_code': None, 'timed_out': True,
                'error': str(error), 'outcome_unknown': True})
        raise
    receipt = freeze(run, relative / (label + '_PROCESS.json'),
                     {'command': command, 'exit_code': result.returncode, 'stdout': result.stdout,
                      'stderr': result.stderr, 'CPU_only': True})
    require(result.returncode == 0, label + '_process_failed_preserve_claim')
    return receipt


class Auditor:
    def __init__(self, spec):
        self.spec = deepcopy(spec)
        context = read(checked(spec['adapter_context']))
        self.config = deepcopy(context['audio_auditor'])
        c = self.config
        require(c.get('schema') == CONFIG and type(c.get('max_fresh_asr')) is int
                and c['max_fresh_asr'] == 1, 'one_fresh_ASR_scope_required')
        require(type(c.get('visual_review_required')) is bool, 'explicit_visual_review_policy_required')
        require(type(c.get('asr_timeout_seconds')) is int and 30 <= c['asr_timeout_seconds'] <= 3600,
                'bounded_ASR_timeout_required')
        require(path(c['python_executable']) == PROJECT / '.venv/Scripts/python.exe', 'project_python_required')
        require(checked(c['transcriber']) == PROJECT / 'scripts/transcribe_video_local.py', 'pinned_local_CPU_transcriber_required')
        for key in ('baseline_final_result', 'baseline_final_qa', 'baseline_user_issue'):
            checked(c[key])
        checked(spec['case_binding']); checked(spec['asset_manifest'])
        self.code = [bind(__file__), bind(rules.__file__), c['transcriber']]

    def _request(self, request):
        require(request.get('schema') == 'media_repair_request/v1'
                and request.get('phase') in ('baseline', 'candidate'), 'supported_detection_request_required')
        require(request['segment_id'] == self.spec['repair_segment_id']
                and request['case_binding'] == self.spec['case_binding']
                and request['asset_manifest'] == self.spec['asset_manifest']
                and request['authorization'] == self.spec['authorization'], 'detection_request_scope_changed')
        require(digest(read(checked(request['spec']))) == digest(self.spec), 'detection_spec_changed')
        run = path(request['run'])
        require(path(request['attempt_dir']) == run / 'attempts' / request['attempt_id'], 'attempt_directory_mismatch')
        require(request['candidate']['attempt_id'] == request['attempt_id']
                and request['candidate']['segment_id'] == request['segment_id'], 'candidate_attempt_mismatch')
        require(all(bind(item['path']) == item for item in self.code), 'frozen_auditor_code_changed')
        for item in (self.spec['adapter_context'], request['case_binding'], request['asset_manifest'], request['authorization']):
            checked(item)
        checked(request['candidate']['result']); checked(request['candidate']['media'])
        return run

    def _baseline(self, request, run, relative):
        candidate = request['candidate']
        final = read(checked(self.config['baseline_final_result']))
        qa = read(checked(self.config['baseline_final_qa']))
        rows = [r for r in final['segments'] if r['id'] == request['segment_id']]
        require(len(rows) == 1, 'one_baseline_segment_required')
        original = rows[0]
        require(original['native_id'] == candidate['native_id'] and original['file'] == candidate['media']
                and original['result_binding'] == candidate['result'], 'baseline_not_completed_source_original')
        checked(final['file'])
        require(qa['file'] == final['file'], 'baseline_QA_movie_mismatch')
        speech = [r['ASR'] for r in qa['speech'] if r['segment'] == request['segment_id']]
        require(len(speech) == 1 and speech[0]['status'] == 'CPU_ASR_complete', 'completed_existing_baseline_ASR_required')
        asr = speech[0]
        claim = read(checked(asr['claim'])); report = read(checked(asr['report']))
        require(claim['native_id'] == candidate['native_id'] and claim['video'] == candidate['media']
                and report['source']['video'] == candidate['media'] and report['raw'] == asr['raw'],
                'existing_baseline_ASR_subject_mismatch')
        for item in asr['artifacts']:
            checked(item)
        checked(asr['raw'])
        return freeze(run, relative / 'ASR_RECEIPT.json', {
            'schema': rules.TRANSCRIPT_SCHEMA, 'attempt_id': request['attempt_id'],
            'native_id': candidate['native_id'], 'media': candidate['media'], 'raw_asr': asr['raw'],
            'asr_claim': asr['claim'], 'completion_known': True, 'outcome_unknown': False,
            'existing_ASR_reused_no_transcription': True,
            'source_final_result': self.config['baseline_final_result'],
            'source_final_QA': self.config['baseline_final_qa'], 'existing_report': asr['report'],
            'original_artifacts': asr['artifacts']})

    def _fresh(self, request, run):
        candidate = request['candidate']
        originals = _inspect_saved_candidate(candidate, request, self.spec)
        key = digest({'native_id': candidate['native_id'], 'media': candidate['media']})[:24]
        relative = Path('audio_auditor/asr') / key
        folder = run / relative
        registry = run / 'audio_auditor/FRESH_ASR_CLAIM.json'
        subject = {'native_id': candidate['native_id'], 'media': candidate['media'],
                   'attempt_id': request['attempt_id'], 'candidate_result': candidate['result']}
        if registry.exists():
            require(read(registry)['subject'] == subject, 'fresh_ASR_budget_exhausted')
        receipt_file = folder / 'ASR_RECEIPT.json'
        if receipt_file.exists():
            receipt = read(receipt_file)
            require(receipt['native_id'] == candidate['native_id'] and receipt['media'] == candidate['media']
                    and receipt['attempt_id'] == request['attempt_id']
                    and receipt['completion_known'] is True and receipt['outcome_unknown'] is False,
                    'saved_ASR_receipt_subject_changed')
            for item in [receipt['raw_asr'], receipt['audio_wave'], receipt['asr_claim'],
                         receipt['transcriber'], *receipt['processes']]:
                checked(item)
            require(registry.exists(), 'ASR_receipt_without_original_global_claim')
            return bind(receipt_file)
        require(not registry.exists() and not (folder / 'CLAIM.json').exists(), 'ASR_claim_outcome_unknown_no_blind_retry')
        require(not folder.exists() or not any(folder.iterdir()), 'unreceipted_ASR_outputs_preserved_no_retry')
        claim = {'schema': 'h3_repair_audio_ASR_once/v1', **subject, 'video': candidate['media'],
                 'source_case': request['case_binding'], 'asset_manifest': request['asset_manifest'],
                 'transcriber': self.config['transcriber'], 'code': self.code,
                 'no_blind_retry': True, 'hotword': '', 'without_punctuation': True}
        freeze(run, 'audio_auditor/FRESH_ASR_CLAIM.json', {'subject': subject, 'max_fresh_ASR': 1})
        claim_binding = freeze(run, relative / 'CLAIM.json', claim)
        wav, raw = folder / 'audio_16k.wav', folder / 'ASR.json'
        extract = ['ffmpeg', '-nostdin', '-n', '-v', 'warning', '-threads', '1', '-i', candidate['media']['path'],
                   '-map', '0:a:0', '-vn', '-af', 'aresample=16000:async=0:first_pts=0', '-ar', '16000',
                   '-ac', '1', '-c:a', 'pcm_s16le', str(wav)]
        transcribe = [self.config['python_executable'], str(checked(self.config['transcriber'])),
                      str(wav), str(raw), '--model-root', str(PROJECT / '.local_models/video_analysis'),
                      '--without-punctuation', '--hotword', '']
        processes = [_run_process(extract, 'WAV_EXTRACT', run, relative, self.config['asr_timeout_seconds'])]
        with wave.open(str(wav), 'rb') as stream:
            require((stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) == (1, 2, 16000)
                    and stream.getnframes() > 0, 'actual_16k_mono_PCM_required')
            wave_frames = stream.getnframes()
        wave_binding = bind(wav)
        processes.append(_run_process(transcribe, 'ASR', run, relative, self.config['asr_timeout_seconds']))
        checked(wave_binding)
        transcript = read(raw)
        require(path(transcript['audio']) == wav and transcript['models']['punctuation'] is None,
                'ASR_must_bind_exact_WAV_and_disable_punctuation')
        return freeze(run, relative / 'ASR_RECEIPT.json', {
            'schema': rules.TRANSCRIPT_SCHEMA, 'attempt_id': request['attempt_id'], 'native_id': candidate['native_id'],
            'media': candidate['media'], 'raw_asr': bind(raw), 'audio_wave': wave_binding,
            'audio_wave_rate': 16000, 'audio_wave_frames': wave_frames, 'transcriber': self.config['transcriber'],
            'asr_claim': claim_binding, 'processes': processes, 'originals': originals,
            'completion_known': True, 'outcome_unknown': False, 'hotword': '', 'without_punctuation': True,
            'CPU_only': True, 'new_ASR_calls': 1})

    def detect(self, request):
        run = self._request(request)
        with run_lock(run, 'AUDIO_AUDITOR.lock'):
            candidate = request['candidate']
            key = digest({'attempt': request['attempt_id'], 'native': candidate['native_id'], 'media': candidate['media']})[:24]
            relative = Path('audio_auditor/detections') / key
            stored = run / relative / 'AUDIT.json'
            if stored.exists():
                audit = read(stored)
                require(audit['request_digest'] == digest(request), 'saved_detection_request_changed')
                for item in [*audit['evidence'], audit['detector_receipt']]:
                    checked(item)
                return bind(stored)
            unknown = None
            try:
                asr = self._baseline(request, run, relative) if request['phase'] == 'baseline' else self._fresh(request, run)
                case = {'schema': rules.CASE_SCHEMA, 'attempt_id': request['attempt_id'], 'segment_id': request['segment_id'],
                        'native_id': candidate['native_id'], 'media': candidate['media'], 'source_case': request['case_binding'],
                        'asr_receipt': asr, 'policy': self.config.get('policy', {})}
                if request['phase'] == 'baseline':
                    case['user_confirmed_issue'] = self.config['baseline_user_issue']
                case_binding = freeze(run, relative / 'CONFORMANCE_CASE.json', case)
                assessment = rules.evaluate_bound(case_binding)
            except Exception as error:
                unknown = freeze(run, relative / 'UNKNOWN.json', {'schema': VERSION, 'outcome_unknown': True,
                                 'native_id': candidate['native_id'], 'media': candidate['media'],
                                 'error': str(error), 'traceback': traceback.format_exc(), 'automatic_retry': False})
                assessment = {'schema': rules.VERSION, 'attempt_id': request['attempt_id'],
                              'segment_id': request['segment_id'], 'native_id': candidate['native_id'],
                              'media': candidate['media'], 'decision': 'needs_review', 'route': 'review',
                              'input_valid': False, 'issues': [{'code': 'ASR_unknown_or_evidence_invalid', 'reason': str(error)}],
                              'human_listening_performed': False,
                              'new_ASR_calls': 0 if request['phase'] == 'baseline' else None,
                              'possible_fresh_ASR_attempt_must_not_be_repeated': request['phase'] == 'candidate',
                              'limitations': ['No successful ASR completion is asserted; an existing claim forbids retry.']}
            assessment_binding = freeze(run, relative / 'AUDIO_ASSESSMENT.json', assessment)
            decision = assessment['decision']
            visual_pending = request['phase'] == 'candidate' and self.config['visual_review_required'] and decision == 'accept'
            if visual_pending:
                decision = 'needs_review'
            detector = freeze(run, relative / 'DETECTOR_RECEIPT.json', {
                'schema': 'media_repair_detection/v1', 'attempt_id': request['attempt_id'],
                'segment_id': request['segment_id'], 'native_id': candidate['native_id'], 'media': candidate['media'],
                'decision': decision, 'audio_assessment': assessment_binding, 'audio_decision': assessment['decision'],
                'visual_review_required': self.config['visual_review_required'], 'actual_visual_review_performed': False,
                'visual_review_pending': visual_pending, 'code': self.code, 'outcome_unknown': unknown is not None})
            evidence = [assessment_binding, self.spec['adapter_context'], *self.code]
            if unknown:
                evidence.append(unknown)
            else:
                evidence.append(asr)
                evidence.extend(row['binding'] for row in assessment.get('evidence', []))
                # A cached audit must still verify every physical input/proof,
                # not only the immutable JSON that once named those files.
                receipt = read(checked(asr))
                for field in ('raw_asr', 'audio_wave', 'transcriber', 'asr_claim', 'existing_report',
                              'source_final_result', 'source_final_QA'):
                    if field in receipt:
                        evidence.append(receipt[field])
                evidence.extend(receipt.get('processes', []))
                evidence.extend(receipt.get('original_artifacts', []))
                evidence.extend(receipt.get('originals', {}).values())
                for item in evidence:
                    checked(item)
            findings = deepcopy(assessment.get('issues', []))
            if visual_pending:
                findings.append({'code': 'actual_visual_review_required', 'severity': 'uncertain',
                                 'note': 'Audio opinion retained; only an explicit review of this candidate may release the visual gate.'})
            return freeze(run, relative / 'AUDIT.json', {
                'schema': 'media_repair_audit/v1', 'attempt_id': request['attempt_id'], 'segment_id': request['segment_id'],
                'native_id': candidate['native_id'], 'candidate_result': candidate['result'], 'candidate_media': candidate['media'],
                'case_binding': request['case_binding'], 'asset_manifest': request['asset_manifest'],
                'fresh_detection': True, 'decision': decision, 'evidence': evidence,
                'findings': findings, 'detector_receipt': detector, 'request_digest': digest(request)})


def build_auditor(spec):
    return Auditor(spec)
