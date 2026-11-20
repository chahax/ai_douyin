"""Protocol fixtures only: no real video decode, model, ASR or network."""
import json
from pathlib import Path
import uuid
import wave

import pytest

from src.content_factory import audio_full_scope_v1 as scope


@pytest.fixture
def evidence():
    folder = scope.PROJECT / 'data/test_runs' / ('audio_scope_' + uuid.uuid4().hex)
    folder.mkdir(parents=True)

    def put(name, value):
        p = folder / name
        p.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        return scope.bind(p)

    video = folder / 'synthetic_protocol_media.bin'
    video.write_bytes(b'Protocol subject, not a rendered media file')
    media = scope.bind(video)
    result = put('result.json', {'prompt_id': 'synthetic_scope', 'files': {'video': media}})
    nominal = {'frames': 360, 'fps': 24}
    clock = put('clock.json', dict(schema='media_repair_candidate_clock/v1', native_id='synthetic_scope',
        media=media, result=result, nominal_frame_clock=nominal, normalization_verified=True, content_trimmed=False))
    candidate = dict(schema='media_repair_candidate/v1', native_id='synthetic_scope', attempt_id='A001',
        segment_id='segment_any_name', media=media, result=result, audio_clock_receipt=clock,
        nominal_frame_clock=nominal, completion_known=True, outcome_unknown=False)
    candidate_binding = put('candidate.json', candidate)
    wav = folder / 'whole.wav'
    with wave.open(str(wav), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(bytes(240000 * 2))
    raw = put('asr.json', dict(schema='local_video_transcript/v1', audio=str(wav), result=[]))
    claim = put('claim.json', dict(native_id=candidate['native_id'], attempt_id='A001', media=media))
    extract_command = ['ffmpeg', '-nostdin', '-n', '-v', 'warning', '-threads', '1', '-i', media['path'],
        '-map', '0:a:0', '-vn', '-af', 'aresample=16000:async=0:first_pts=0', '-ar', '16000',
        '-ac', '1', '-c:a', 'pcm_s16le', str(wav)]
    script = scope.PROJECT / 'scripts/transcribe_video_local.py'
    asr_command = [str(scope.PROJECT / '.venv/Scripts/python.exe'), str(script), str(wav), raw['path'],
        '--without-punctuation', '--hotword', '']
    extract = put('extract.json', dict(command=extract_command, exit_code=0))
    transcribe = put('transcribe.json', dict(command=asr_command, exit_code=0))
    receipt = dict(schema='h3_audio_transcript_receipt/v1', native_id=candidate['native_id'], attempt_id='A001',
        media=media, raw_asr=raw, audio_wave=scope.bind(wav), audio_wave_rate=16000, audio_wave_frames=240000,
        asr_claim=claim, transcriber=scope.bind(script), processes=[extract, transcribe],
        completion_known=True, outcome_unknown=False)
    return folder, put, candidate_binding, receipt


def test_whole_wave_and_empty_recognition_are_separate_questions(evidence):
    _, put, candidate, receipt = evidence
    proof = scope.verify(put('receipt.json', receipt), candidate)
    assert proof['status'] == 'verified_full_ASR_input'
    assert proof['scope'] == 'full_segment'
    assert proof['waveform_seconds'] == '15'
    assert proof['new_ASR_calls'] == 0
    assert scope.validate_bound(put('proof.json', proof)) == proof


@pytest.mark.parametrize('bad', ['cropped_argv', 'partial_wave', 'other_media', 'partial_ASR', 'process_failed'])
def test_partial_stale_or_failed_evidence_never_proves_full_inspection(evidence, bad):
    folder, put, candidate, receipt = evidence
    if bad == 'cropped_argv':
        p = json.loads(Path(receipt['processes'][0]['path']).read_text())
        p['command'][1:1] = ['-ss', '8', '-t', '4']
        receipt['processes'][0] = put('cropped.json', p)
    elif bad == 'partial_wave':
        wav = folder / 'partial.wav'
        with wave.open(str(wav), 'wb') as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(bytes(16000 * 2))
        receipt['audio_wave'] = scope.bind(wav)
        receipt['audio_wave_frames'] = 16000
    elif bad == 'other_media':
        receipt['native_id'] = 'a_different_generation'
    elif bad == 'partial_ASR':
        p = json.loads(Path(receipt['processes'][1]['path']).read_text())
        p['command'] += ['--start', '8', '--end', '12']
        receipt['processes'][1] = put('partial_asr_process.json', p)
    else:
        p = json.loads(Path(receipt['processes'][1]['path']).read_text())
        p['exit_code'] = 1
        receipt['processes'][1] = put('failed_process.json', p)
    with pytest.raises(ValueError):
        scope.verify(put('bad_receipt.json', receipt), candidate)


def test_cached_proof_rechecks_internal_raw_ASR_and_cannot_transfer_to_new_media(evidence):
    _, put, candidate, receipt = evidence
    proof = scope.verify(put('receipt.json', receipt), candidate)
    binding = put('proof.json', proof)
    raw_path = Path(receipt['raw_asr']['path'])
    raw_path.write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='audio_evidence_changed'):
        scope.validate_bound(binding)


def test_shortcut_claim_without_process_receipts_is_evidence_insufficient(evidence):
    _, put, candidate, receipt = evidence
    del receipt['processes']
    with pytest.raises(ValueError, match='whole_audio_process_evidence_required'):
        scope.verify(put('legacy_receipt.json', receipt), candidate)


def test_wave_header_cannot_hide_truncated_PCM_body(evidence):
    _, put, candidate, receipt = evidence
    waveform = Path(receipt['audio_wave']['path'])
    waveform.write_bytes(waveform.read_bytes()[:-16000])
    receipt['audio_wave'] = scope.bind(waveform)
    with pytest.raises(ValueError, match='wave_PCM_body_shorter'):
        scope.verify(put('truncated_body_receipt.json', receipt), candidate)


def test_different_native_result_cannot_be_relabelled_by_a_candidate(evidence):
    _, put, candidate_binding, receipt = evidence
    candidate = json.loads(Path(candidate_binding['path']).read_text())
    candidate['result'] = put('wrong_native_result.json', {'prompt_id': 'another_native'})
    with pytest.raises(ValueError, match='candidate_result_native_identity_mismatch'):
        scope.verify(put('receipt.json', receipt), put('relabelled_candidate.json', candidate))
