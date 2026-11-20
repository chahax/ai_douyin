"""Synthetic protocol/WAV bytes only: no decoding, recognition or dispatch."""
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import uuid
import wave

import pytest

from src.content_factory import audio_full_scope_v1 as scope
from src.content_factory import audio_gap_repair_v1 as gap
from src.content_factory import audio_repair_routing_v1 as router
from src.content_factory import h3_audio_conformance_v1 as conformance


def make_case(folder, *, extra=True, extra_times=(8940,11980)):
    """Reusable full-scope + conformance fixture; neither validator is mocked."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)

    def put(name, value):
        p = folder / name
        p.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        return scope.bind(p)

    native = 'synthetic_route_' + folder.name
    sid = 'segment_arbitrary'
    media_path = folder / 'SYNTHETIC_MEDIA.bin'
    media_path.write_bytes(b'protocol identity only; never decoded')
    media = scope.bind(media_path)
    result = put('NATIVE_RESULT.json', dict(prompt_id=native, files=dict(video=media)))
    nominal = dict(frames=360, fps=24)
    clock = put('CLOCK.json', dict(schema='media_repair_candidate_clock/v1', native_id=native,
        media=media, result=result, nominal_frame_clock=nominal,
        normalization_verified=True, content_trimmed=False))
    candidate = put('CANDIDATE.json', dict(schema='media_repair_candidate/v1', native_id=native,
        attempt_id='A001', segment_id=sid, media=media, result=result, audio_clock_receipt=clock,
        nominal_frame_clock=nominal, completion_known=True, outcome_unknown=False))
    wav = folder / 'SYNTHETIC_WHOLE.wav'
    with wave.open(str(wav), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(bytes(240000 * 2))

    def chars(text, a, b):
        text = conformance.normalize_text(text)
        return [(c, a + i * (b-a)//len(text), a + (i+1)*(b-a)//len(text)) for i, c in enumerate(text)]

    rows = chars('这是正常的第一句话。', 420, 8760)
    if extra:
        rows += chars('额外声音', *extra_times)
    rows += chars('别去了！', 12820, 14285)
    raw = put('RAW_ASR.json', dict(schema='local_video_transcript/v1', audio=str(wav), result=[
        dict(text=' '.join(c for c, _, _ in rows), timestamp=[[a,b] for _,a,b in rows])]))
    claim = put('ASR_CLAIM.json', dict(native_id=native, attempt_id='A001', media=media))
    transcriber = scope.PROJECT / 'scripts/transcribe_video_local.py'
    extract = put('EXTRACT_PROCESS.json', dict(exit_code=0, command=['ffmpeg','-nostdin','-n','-v','warning',
        '-threads','1','-i',media['path'],'-map','0:a:0','-vn','-af','aresample=16000:async=0:first_pts=0',
        '-ar','16000','-ac','1','-c:a','pcm_s16le',str(wav)]))
    transcribe = put('ASR_PROCESS.json', dict(exit_code=0, command=[str(scope.PROJECT / '.venv/Scripts/python.exe'),
        str(transcriber), str(wav), raw['path'], '--without-punctuation','--hotword','']))
    receipt = put('ASR_RECEIPT.json', dict(schema='h3_audio_transcript_receipt/v1', native_id=native,
        attempt_id='A001', media=media, raw_asr=raw, audio_wave=scope.bind(wav), audio_wave_rate=16000,
        audio_wave_frames=240000, asr_claim=claim, transcriber=scope.bind(transcriber),
        processes=[extract,transcribe],completion_known=True,outcome_unknown=False))
    source_text, spans = '', []
    for index, text in enumerate(['“这是正常的第一句话。”', '“别去了！”']):
        start = len(source_text)
        source_text += text + '\n'
        spans.append(dict(id='quote'+str(index), kind='audio', start=start, end=start+len(text),
                          text=text, sha256=hashlib.sha256(text.encode()).hexdigest()))
    txt = folder / 'SOURCE.txt'
    txt.write_text(source_text, encoding='utf-8')
    source = put('SOURCE_CASE.json', dict(schema='h3_continuity_input/v33', shots=[dict(
        shot_id=sid, duration=15, source=scope.bind(txt), source_spans=spans,
        audio=[dict(quote_index=i, quote_sha256=s['sha256'], speaker='child'+str(i), mode='onscreen',
                    start=[.42,12.82][i], end=[8.76,14.285][i]) for i,s in enumerate(spans)])]))
    case = put('CONFORMANCE_CASE.json', dict(schema='h3_audio_conformance_case/v1', native_id=native,
        segment_id=sid, attempt_id='A001', media=media, source_case=source, asr_receipt=receipt))
    report = put('CONFORMANCE_REPORT.json', conformance.evaluate_bound(case))
    proof = put('FULL_SCOPE.json', scope.verify(receipt, candidate))
    routing = dict(schema=router.CASE_SCHEMA, native_id=native, segment_id=sid, media=media,
                   conformance_case=case, conformance_report=report, full_audio_inspection=proof,
                   capabilities=[], allow_ambient_loss=True)
    evidence = put('SYNTHETIC_CONFIRMATION_EVIDENCE.json', dict(synthetic=True))

    def confirm(kind='extra_speech', **updates):
        value = dict(schema='h3_audio_user_confirmed_issue/v1', native_id=native, media=media,
            confirmed=True, confirmed_by='user', description='Synthetic confirmed audio issue',
            kind=kind, intervals_ms=[[8940,11980]], independent_of_expected_quotes=True, evidence=[evidence])
        value.update(updates)
        routing['confirmation'] = put('CONFIRMATION.json', value)
        return value

    def capability(route, **updates):
        value = dict(schema='media_repair_capability/v1', capability=route, verified=True,
            executor_module=scope.bind(gap.__file__ if route == 'cleanup_gap' else router.__file__),
            method='prepare', evidence=[evidence], preserves_duration=True,
            preserves_video_and_duration=True, confirmation_types=['user','independent_review'],
            processor_schema='audio_gap_repair_spec/v1', source_voice_preservation=dict(
                verified=True,strategy='preserve_existing_speakers',evidence=[evidence]))
        value.update(updates)
        routing['capabilities'].append(put('CAP_'+route+'.json', value))

    def evaluate():
        return router.evaluate_bound(put('ROUTING_CASE.json', routing))

    return dict(folder=folder, put=put, case=routing, confirm=confirm, capability=capability,
                evaluate=evaluate, evidence=evidence, candidate=candidate)


@pytest.fixture
def case(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('No process/network/ASR/media execution allowed')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    return make_case(scope.PROJECT / 'data/test_runs' / ('audio_route_'+uuid.uuid4().hex))


def test_real_whole_wave_and_real_conformance_accept_without_claiming_visual_pass(case):
    clean = make_case(case['folder'] / 'clean', extra=False)
    out = clean['evaluate']()
    assert out['route'] == 'accept' and out['input_valid'] and out['full_audio_inputs_verified']
    assert out['overall_video_accepted'] is False and out['processor_request'] is None


def test_ASR_extra_alone_and_legacy_user_issue_never_authorize_mute(case):
    assert case['evaluate']()['route'] == 'verify_audio'
    issue = case['confirm']()
    del issue['kind']
    case['case']['confirmation'] = case['put']('LEGACY.json', issue)
    assert case['evaluate']()['route'] == 'verify_audio'


def test_safe_actual_gap_emits_executable_original_gap_spec_without_processing(case):
    case['confirm'](intervals_ms=[[8000,12000]])
    case['capability']('cleanup_gap')
    out = case['evaluate']()
    assert out['route'] == 'cleanup_gap'
    request = out['processor_request']
    assert request['dry_run'] and not request['execute_allowed']
    assert request['patches'][0]['patch_ms'] == [8860,12060]
    details = gap._details(case['put']('PROCESSOR_SPEC.json', request['processor_spec']))
    assert details['protected_actual_quotes_ms'] == [[340,8840],[12740,14365]]
    assert request['post_repair']['requires_new_media_full_audio_inspection']
    assert not request['post_repair']['reuse_source_ASR_for_acceptance']


def test_actual_gap_quote_guard_overlap_requires_audio_regeneration_not_gap(case):
    overlapping = make_case(case['folder'] / 'overlap', extra_times=(8800,11980))
    overlapping['confirm'](intervals_ms=[[8000,12000]])
    overlapping['capability']('regenerate_audio')
    assert overlapping['evaluate']()['route'] == 'regenerate_audio'


@pytest.mark.parametrize('kind', ['wrong_words','missing_speech','wrong_speaker'])
def test_confirmed_normal_dialogue_failures_require_verified_audio_backend(case, kind):
    case['confirm'](kind)
    out = case['evaluate']()
    assert out['route'] == 'capability_missing' and out['desired_route'] == 'regenerate_audio'
    case['capability']('regenerate_audio')
    assert case['evaluate']()['route'] == 'regenerate_audio'


def test_known_visual_failure_has_priority_over_safe_audio_cleanup(case):
    case['confirm']()
    case['capability']('cleanup_gap')
    case['case']['visual_review'] = case['put']('VISUAL.json', dict(schema='media_visual_review/v1',
        native_id=case['case']['native_id'], media=case['case']['media'], status='major',
        reviewed_by='synthetic_reviewer', evidence=[case['evidence']]))
    out = case['evaluate']()
    assert out['route'] == 'capability_missing' and out['desired_route'] == 'regenerate_av'
    case['capability']('regenerate_av')
    assert case['evaluate']()['route'] == 'regenerate_av'


def test_missing_full_scope_bad_binding_and_changed_media_never_release(case):
    proof = case['case'].pop('full_audio_inspection')
    assert case['evaluate']()['route'] == 'verify_audio'
    case['case']['full_audio_inspection'] = proof
    issue = case['confirm'](media=dict(path=case['case']['media']['path'],sha256='0'*64))
    assert not case['evaluate']()['input_valid']
    case['case'].pop('confirmation')
    Path(case['case']['media']['path']).write_bytes(b'new media version requires new evidence')
    assert not case['evaluate']()['input_valid']


def test_independent_confirmation_cannot_impersonate_user_for_old_gap_backend(case):
    case['confirm'](confirmed_by='independent_review')
    case['capability']('cleanup_gap')
    out = case['evaluate']()
    assert out['route'] == 'capability_missing'
    assert 'requires_user_confirmation' in out['reason']


def test_ambient_preservation_and_unverified_capability_are_explicit_gaps(case):
    case['confirm']()
    case['capability']('cleanup_gap', verified=False)
    assert case['evaluate']()['route'] == 'capability_missing'
    case['case']['allow_ambient_loss'] = False
    assert case['evaluate']()['reason'] == 'mixed_ambient_loss_not_authorized'


def test_noise_has_own_route_and_requires_verified_backend(case):
    case['confirm']('noise_only')
    assert case['evaluate']()['desired_route'] == 'denoise_audio'
    case['capability']('denoise_audio')
    out = case['evaluate']()
    assert out['route'] == 'denoise_audio'
    assert out['processor_request']['constraints']['preserve_video']


def test_audio_regeneration_requires_same_speaker_capability_not_adult_fallback(case):
    case['confirm']('wrong_speaker')
    case['capability']('regenerate_audio', source_voice_preservation={})
    out = case['evaluate']()
    assert out['route'] == 'capability_missing'
    assert out['reason'] == 'verified_same_speaker_audio_backend_missing'
