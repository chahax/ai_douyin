"""Verify existing evidence that an entire segment waveform reached local ASR.

This never decodes media, invokes ASR or assesses audible quality. A verified
input scope does not assert that recognition or speaker attribution is correct.
"""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import wave

PROJECT = Path(__file__).resolve().parents[2]
SCHEMA = 'full_audio_inspection/v1'


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def local(value):
    p = Path(value)
    require(p.is_absolute() and '://' not in str(value), 'absolute_project_path_required')
    p = p.resolve()
    require(p.is_relative_to(PROJECT), 'audio_evidence_outside_project')
    return p


def bind(value):
    p = local(value)
    with p.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(p), 'sha256': sha}


def checked(value):
    require(isinstance(value, dict) and set(value) == {'path', 'sha256'}, 'exact_binding_required')
    p = local(value['path'])
    require(bind(p) == value, 'audio_evidence_changed')
    return p


def read(value):
    return json.loads(checked(value).read_text(encoding='utf-8-sig'))


def _successful_process(binding):
    process = read(binding)
    require(type(process.get('exit_code')) is int and process['exit_code'] == 0
            and not process.get('outcome_unknown') and not process.get('timed_out'),
            'completed_audio_process_required')
    command = process.get('command')
    require(isinstance(command, list) and all(isinstance(x, str) for x in command),
            'recorded_audio_process_argv_required')
    return command


def verify(asr_receipt_binding, candidate_binding):
    """Return a deterministic proof, or reject incomplete/cropped/stale evidence."""
    candidate = read(candidate_binding)
    receipt = read(asr_receipt_binding)
    require(candidate.get('schema') == 'media_repair_candidate/v1'
            and candidate.get('completion_known') is True and candidate.get('outcome_unknown') is False,
            'completed_candidate_required')
    require(receipt.get('schema') == 'h3_audio_transcript_receipt/v1'
            and receipt.get('completion_known') is True and receipt.get('outcome_unknown') is False,
            'completed_ASR_receipt_required')
    for field in ('native_id', 'attempt_id', 'media'):
        require(candidate[field] == receipt[field], 'whole_audio_subject_mismatch:' + field)
    checked(candidate['media'])
    result = read(candidate['result'])
    require(result.get('prompt_id', result.get('native_id')) == candidate['native_id'],
            'candidate_result_native_identity_mismatch')
    video = result.get('files', {}).get('video', result.get('media'))
    require(isinstance(video, dict)
            and {k: video.get(k) for k in ('path', 'sha256')} == candidate['media'],
            'candidate_result_media_identity_mismatch')
    clock = read(candidate['audio_clock_receipt'])
    require(clock.get('schema') == 'media_repair_candidate_clock/v1'
            and clock.get('native_id') == candidate['native_id'] and clock.get('media') == candidate['media']
            and clock.get('result') == candidate['result']
            and clock.get('normalization_verified') is True and clock.get('content_trimmed') is False
            and clock.get('nominal_frame_clock') == candidate['nominal_frame_clock'],
            'bound_candidate_clock_required')
    for evidence in clock.get('evidence', []):
        checked(evidence)
    frames, fps = (candidate['nominal_frame_clock'][k] for k in ('frames', 'fps'))
    require(type(frames) is int and type(fps) is int and frames > 0 and fps > 0,
            'integral_segment_frame_clock_required')
    expected = Fraction(frames, fps)
    waveform = checked(receipt['audio_wave'])
    with wave.open(str(waveform), 'rb') as stream:
        rate, samples, channels, width, compression = (stream.getframerate(), stream.getnframes(),
            stream.getnchannels(), stream.getsampwidth(), stream.getcomptype())
        pcm_bytes = 0
        while True:
            chunk = stream.readframes(65536)
            if not chunk:
                break
            pcm_bytes += len(chunk)
    require((rate, channels, width, compression) == (16000, 1, 2, 'NONE') and samples > 0,
            'full_scope_requires_current_16k_mono_PCM_contract')
    require(pcm_bytes == samples * channels * width, 'wave_PCM_body_shorter_than_declared_header')
    require(type(receipt['audio_wave_rate']) is int and type(receipt['audio_wave_frames']) is int
            and (rate, samples) == (receipt['audio_wave_rate'], receipt['audio_wave_frames']),
            'actual_wave_header_mismatch')
    require(abs(Fraction(samples, rate) - expected) <= Fraction(1, 4),
            'audio_wave_does_not_cover_entire_segment')
    raw = read(receipt['raw_asr'])
    require(raw.get('schema') == 'local_video_transcript/v1'
            and local(raw['audio']) == waveform, 'ASR_did_not_receive_same_entire_waveform')
    claim = read(receipt['asr_claim'])
    require(claim.get('native_id') == candidate['native_id']
            and claim.get('attempt_id') == candidate['attempt_id']
            and claim.get('media', claim.get('video')) == candidate['media'],
            'whole_audio_ASR_claim_subject_mismatch')
    script = checked(receipt['transcriber'])
    require(script == PROJECT / 'scripts/transcribe_video_local.py', 'current_local_transcriber_required')
    processes = receipt.get('processes')
    require(isinstance(processes, list) and len(processes) == 2, 'whole_audio_process_evidence_required')
    extract = _successful_process(processes[0])
    expected_extract = ['ffmpeg', '-nostdin', '-n', '-v', 'warning', '-threads', '1', '-i',
        candidate['media']['path'], '-map', '0:a:0', '-vn', '-af', 'aresample=16000:async=0:first_pts=0',
        '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(waveform)]
    require(extract == expected_extract, 'unverified_or_cropping_audio_extraction_argv')
    transcribe = _successful_process(processes[1])
    require(transcribe and local(transcribe[0]) == PROJECT / '.venv/Scripts/python.exe',
            'project_ASR_python_required')
    offset = 3 if transcribe[1:3] == ['-X', 'utf8'] else 1
    require(len(transcribe) >= offset + 3 and local(transcribe[offset]) == script
            and local(transcribe[offset + 1]) == waveform
            and local(transcribe[offset + 2]) == checked(receipt['raw_asr']),
            'whole_waveform_ASR_input_output_argv_mismatch')
    suffix = transcribe[offset + 3:]
    if suffix[:1] == ['--model-root']:
        require(len(suffix) >= 2, 'model_root_argument_missing')
        local(suffix[1])
        suffix = suffix[2:]
    require(suffix == ['--without-punctuation', '--hotword', ''],
            'unsupported_or_partial_ASR_argv')
    return dict(schema=SCHEMA, status='verified_full_ASR_input', scope='full_segment',
        stream_scope='primary_audio_stream_0_a_0', all_audio_streams_verified=False,
        native_id=candidate['native_id'], segment_id=candidate['segment_id'], media=candidate['media'],
        candidate=candidate_binding, asr_receipt=asr_receipt_binding,
        frame_clock={'frames': frames, 'fps': fps}, audio_wave=receipt['audio_wave'],
        waveform_rate=rate, waveform_frames=samples, waveform_seconds=str(Fraction(samples, rate)),
        nominal_segment_seconds=str(expected), duration_tolerance_seconds='1/4',
        verifier=bind(__file__), transcriber=receipt['transcriber'], process_evidence=processes,
        limitations=['This proves the whole segment waveform was supplied to ASR; it does not prove all sounds were recognized.',
                    'Speaker identity, voice age, lip sync and listening quality are not verified.'],
        new_ASR_calls=0, new_model_calls=0, HTTP_calls=0)


def validate_bound(proof_binding):
    """Recheck internal evidence; a JSON status alone is not a full-scope proof."""
    proof = read(proof_binding)
    require(proof.get('schema') == SCHEMA, 'whole_audio_inspection_schema_required')
    require(proof == verify(proof['asr_receipt'], proof['candidate']),
            'whole_audio_inspection_proof_changed')
    return proof
