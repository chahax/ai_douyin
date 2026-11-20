"""Mock process protocol only; no model, real-media decode, ASR or network."""
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
from types import SimpleNamespace
import uuid
import wave

import pytest

from src.content_factory import audio_full_scope_v1 as scope
from src.content_factory import local_audio_inspector_v1 as inspector


@pytest.fixture
def fixture(monkeypatch):
    helper_path=scope.PROJECT/'tests/test_audio_repair_routing_v1.py'
    spec=importlib.util.spec_from_file_location('synthetic_router_case',helper_path)
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    folder=scope.PROJECT/'data/test_runs'/('inspector_'+uuid.uuid4().hex)
    original=helper.make_case(folder/'source')
    put=original['put']
    source_case=scope.read(original['case']['conformance_case'])['source_case']
    assets=put('SYNTHETIC_ASSETS.json',dict(synthetic=True))
    source=scope.read(original['candidate'])
    source.update(source_case=source_case,asset_manifest=assets)
    source_binding=put('CANDIDATE.json',source)
    old_receipt=scope.read(original['case']['conformance_case'])['asr_receipt']
    full=put('SOURCE_FULL_SCOPE.json',scope.verify(old_receipt,source_binding))
    trial=folder/'trial';trial.mkdir()
    parent=put('PARENT.json',dict(schema='audio_quality_execution_authority/v1',trial_run=str(trial),
        source_candidate=source_binding,source_case=source_case,asset_manifest=assets,confirmed_by='user',
        trial_scope='audio_only_test',max_CPU_edits=1,max_ASR_calls=1,max_H3_calls=0,
        allow_ambient_loss=True,assembly_allowed=False))
    media_path=trial/'DERIVED_PROTOCOL_MEDIA.bin';media_path.write_bytes(b'new local edit bytes, never decoded')
    media=scope.bind(media_path);native='local-edit-'+uuid.uuid4().hex
    native_result=put('NEW_RESULT.json',dict(schema='media_repair_audio_result/v1',native_id=native,media=media))
    nominal=dict(frames=360,fps=24)
    clock=put('NEW_CLOCK.json',dict(schema='media_repair_candidate_clock/v1',native_id=native,media=media,
        result=native_result,nominal_frame_clock=nominal,normalization_verified=True,content_trimmed=False))
    candidate=put('NEW_CANDIDATE.json',dict(schema='media_repair_candidate/v1',native_id=native,
        attempt_id='local-A001',segment_id=source['segment_id'],result=native_result,media=media,
        source_case=source_case,asset_manifest=assets,audio_clock_receipt=clock,nominal_frame_clock=nominal,
        completion_known=True,outcome_unknown=False))
    gap_plan=put('GAP_PLAN.json',dict(schema='audio_gap_repair/v1',details=dict(media=source['media'],frame_clock=nominal)))
    gap_proof=put('GAP_PROOF.json',dict(schema='audio_gap_repair_proof/v1',input=source['media'],output=media,
                                     video_frames_PTS_and_decoded_hashes_unchanged=True))
    gap_result=put('GAP_RESULT.json',dict(schema='audio_gap_repair/v1',plan=gap_plan,proof=gap_proof,file=media))
    derivation=put('DERIVATION.json',dict(schema='media_audio_derivation/v1',source_candidate=source_binding,
        source_case=source_case,asset_manifest=assets,source_native_id=source['native_id'],source_media=source['media'],
        native_id=native,media=media,operation='cleanup_gap',processor_plan=gap_plan,processor_result=gap_result,
        processor_proof=gap_proof,evidence=[gap_plan,gap_result,gap_proof],parent_authority=parent))
    models=folder/'FAKE_MODEL_BUNDLE'
    for name in ('paraformer-zh','fsmn-vad'):
        (models/name).mkdir(parents=True)
        (models/name/'config.yaml').write_text('synthetic: true',encoding='utf-8')
        (models/name/'model.pt').write_bytes(b'synthetic placeholder, never loaded')
    authority=dict(schema='local_audio_inspection_authority/v1',issued_by='audio_quality_execution_v1',
        confirmed_by='parent_authority_delegation',parent_authority=parent,candidate=candidate,
        source_full_audio_inspection=full,derivation=derivation,max_ASR_calls=1,
        model_root=str(models),transcriber=scope.bind(scope.PROJECT/'scripts/transcribe_video_local.py'),
        timeout_seconds=60)
    calls=[]

    def forbidden(*args,**kwargs):
        raise AssertionError('No real process/network/ASR allowed')

    monkeypatch.setattr(subprocess,'Popen',forbidden)
    monkeypatch.setattr(socket,'socket',forbidden)
    monkeypatch.setattr(socket,'create_connection',forbidden)

    def fake_process(command,**kwargs):
        calls.append((command,kwargs))
        env=kwargs['env']
        assert env['HF_HUB_OFFLINE']==env['MODELSCOPE_OFFLINE']=='1'
        assert env['CUDA_VISIBLE_DEVICES']==''
        assert '-ss' not in command and '-t' not in command
        if command[0]=='ffmpeg':
            with wave.open(command[-1],'wb') as stream:
                stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(16000)
                stream.writeframes(bytes(240000*2))
        else:
            assert command[-3:]==['--without-punctuation','--hotword','']
            wav,output=command[4:6]
            Path(output).write_text(json.dumps(dict(schema='local_video_transcript/v1',audio=wav,
                result=[dict(text='新 识 别',timestamp=[[0,100],[100,200],[200,300]])])),encoding='utf-8')
        return SimpleNamespace(returncode=0,stdout=b'synthetic process receipt',stderr=b'')

    monkeypatch.setattr(subprocess,'run',fake_process)
    return dict(folder=folder,run=trial/'inspection',put=put,parent=parent,authority=authority,candidate=candidate,
                calls=calls,original=original,fake_process=fake_process)


def inspect(fixture):
    return inspector.inspect(fixture['run'],fixture['candidate'],fixture['put']('CHILD_AUTHORITY.json',fixture['authority']))


def test_fresh_subject_full_scope_and_cached_reentry_are_real_validators(fixture):
    result=inspect(fixture)
    assert result['status']=='saved' and len(fixture['calls'])==2
    proof=scope.validate_bound(result['full_audio_inspection'])
    assert proof['candidate']==fixture['candidate']
    assert proof['media']==scope.read(fixture['candidate'])['media']
    receipt=scope.read(result['asr_receipt'])
    original_receipt=scope.read(scope.read(fixture['original']['case']['conformance_case'])['asr_receipt'])
    assert receipt['raw_asr']!=original_receipt['raw_asr']
    assert receipt['media']!=original_receipt['media']
    assert inspect(fixture)==result and inspector.verify(fixture['run'])==result
    assert len(fixture['calls'])==2
    assert fixture['calls'][1][0][-3:]==['--without-punctuation','--hotword','']


@pytest.mark.parametrize('bad',['authority_candidate','parent_limit','parent_run','derivation_source'])
def test_wrong_subject_parent_or_derivation_fails_before_process(fixture,bad):
    if bad=='authority_candidate':fixture['authority']['candidate']=fixture['parent']
    elif bad=='parent_limit':
        parent=scope.read(fixture['parent']);parent['max_ASR_calls']=2
        fixture['authority']['parent_authority']=fixture['put']('BAD_PARENT.json',parent)
    elif bad=='parent_run':fixture['run']=fixture['folder']/'outside_parent'
    else:
        derivation=scope.read(fixture['authority']['derivation']);derivation['source_native_id']='another_subject'
        fixture['authority']['derivation']=fixture['put']('BAD_DERIVATION.json',derivation)
    with pytest.raises(ValueError):inspect(fixture)
    assert not fixture['calls']


def test_timeout_claim_is_unknown_and_never_replayed(fixture,monkeypatch):
    def timeout(command,**kwargs):
        if command[0]=='ffmpeg':return fixture['fake_process'](command,**kwargs)
        fixture['calls'].append(command)
        raise subprocess.TimeoutExpired(command,1)
    monkeypatch.setattr(subprocess,'run',timeout)
    result=inspect(fixture)
    assert result['status']=='outcome_unknown' and len(fixture['calls'])==2
    assert inspect(fixture)['status']=='outcome_unknown' and len(fixture['calls'])==2


def test_global_subject_claim_prevents_cross_run_duplicate_ASR(fixture):
    assert inspect(fixture)['status']=='saved'
    fixture['run']=fixture['run'].parent/'another_inspection'
    assert inspect(fixture)['status']=='outcome_unknown' and len(fixture['calls'])==2


def test_parent_once_budget_cannot_be_bypassed_with_new_attempt_or_native_id(fixture):
    assert inspect(fixture)['status']=='saved'
    candidate=scope.read(fixture['candidate'])
    candidate['native_id']+='-another'
    candidate['attempt_id']='another-attempt'
    result=scope.read(candidate['result']);result['native_id']=candidate['native_id']
    candidate['result']=fixture['put']('ANOTHER_NATIVE_RESULT.json',result)
    clock=scope.read(candidate['audio_clock_receipt'])
    clock.update(native_id=candidate['native_id'],result=candidate['result'])
    candidate['audio_clock_receipt']=fixture['put']('ANOTHER_CLOCK.json',clock)
    fixture['candidate']=fixture['put']('ANOTHER_CANDIDATE.json',candidate)
    derivation=scope.read(fixture['authority']['derivation']);derivation['native_id']=candidate['native_id']
    fixture['authority'].update(candidate=fixture['candidate'],
        derivation=fixture['put']('ANOTHER_DERIVATION.json',derivation))
    fixture['run']=fixture['run'].parent/'another_inspection'
    assert inspect(fixture)['status']=='outcome_unknown' and len(fixture['calls'])==2


def test_waveform_changed_during_ASR_never_gets_success_receipt(fixture,monkeypatch):
    def changed(command,**kwargs):
        out=fixture['fake_process'](command,**kwargs)
        if command[0]!='ffmpeg':
            with Path(command[4]).open('r+b') as stream:
                stream.seek(-1,2);stream.write(b'\x01')
        return out
    monkeypatch.setattr(subprocess,'run',changed)
    result=inspect(fixture)
    assert result['status']=='outcome_unknown'
    assert not (fixture['run']/'ASR_RECEIPT.json').exists()


@pytest.mark.parametrize('bad',['raw_ASR','model'])
def test_cache_tampering_and_model_mutation_do_not_run_processes(fixture,bad):
    result=inspect(fixture);before=len(fixture['calls'])
    if bad=='raw_ASR':
        raw=scope.read(result['asr_receipt'])['raw_asr']
        Path(raw['path']).write_text('{}',encoding='utf-8')
    else:(Path(fixture['authority']['model_root'])/'paraformer-zh/model.pt').write_bytes(b'changed')
    with pytest.raises(ValueError):inspector.verify(fixture['run'])
    assert len(fixture['calls'])==before


def test_parent_metadata_update_is_not_part_of_owned_cache(fixture):
    result=inspect(fixture)
    (fixture['run']/'ROOT_CHECKPOINT.json').write_text('{"status":"later"}',encoding='utf-8')
    assert inspector.verify(fixture['run'])==result
    assert len(fixture['calls'])==2
