"""Synthetic CPU media only. No real production media, model, HTTP or ASR."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import wave

import numpy as np
import pytest

from src.content_factory import audio_gap_repair_v1 as gap
from src.content_factory import h3_audio_conformance_v1 as conformance


def put(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');return gap.bind(path)


@pytest.fixture(scope='module')
def synthetic(tmp_path_factory):
    folder=tmp_path_factory.mktemp('synthetic_audio_gap');rate=48000;count=724000
    t=np.arange(count)/rate;v=np.zeros(count)
    for a,b,f in [(420,8760,330),(8860,12060,880),(12820,14285,440)]:
        x,y=a*48,b*48;v[x:y]=np.sin(2*np.pi*f*t[x:y])*10000
    pcm=np.column_stack((v,v*.8)).astype('<i2')
    with wave.open(str(folder/'input.wav'),'wb') as wav:
        wav.setnchannels(2);wav.setsampwidth(2);wav.setframerate(rate);wav.writeframes(pcm.tobytes())
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=size=64x96:rate=24',
        '-i',str(folder/'input.wav'),'-frames:v','362','-c:v','libx264','-preset','ultrafast','-threads','1',
        '-c:a','aac','-b:a','192k','-ar','48000','-ac','2',str(folder/'source.mp4')],capture_output=True,check=True,timeout=60)
    return gap.bind(folder/'source.mp4')


@pytest.fixture
def env(tmp_path,synthetic):
    root=tmp_path/'case';root.mkdir();media=synthetic
    quotes=['我被踹倒了疼得半天起不来','我找爸去'];raw='';spans=[]
    for i,text in enumerate(quotes):
        quoted='“'+text+'”';a=len(raw);raw+=quoted+'\n'
        spans.append(dict(id='q'+str(i),kind='audio',start=a,end=a+len(quoted),text=quoted,sha256=hashlib.sha256(quoted.encode()).hexdigest()))
    (root/'source.txt').write_text(raw,encoding='utf-8')
    source=put(root/'SOURCE_CASE.json',dict(schema='h3_continuity_input/v33',shots=[dict(shot_id='S03',duration=15,
        source=gap.bind(root/'source.txt'),source_spans=spans,audio=[dict(quote_index=i,quote_sha256=s['sha256'],speaker='child'+str(i),
            mode='onscreen',start=[.3,11.3][i],end=[10.8,12.6][i]) for i,s in enumerate(spans)])]))
    chars=[]
    for text,a,b in [(quotes[0].replace('得','的'),420,8760),('额外异常声音',8940,11980),(quotes[1],12820,14285)]:
        chars.extend((c,a+i*(b-a)//len(text),a+(i+1)*(b-a)//len(text)) for i,c in enumerate(text))
    asr=put(root/'ASR.json',dict(schema='local_video_transcript/v1',result=[dict(text=' '.join(c for c,a,b in chars),timestamp=[[a,b] for c,a,b in chars])]))
    receipt=put(root/'ASR_RECEIPT.json',dict(schema=conformance.TRANSCRIPT_SCHEMA,native_id='synthetic-native',attempt_id='A001',media=media,
        raw_asr=asr,completion_known=True,outcome_unknown=False))
    issue=put(root/'USER_ISSUE.json',dict(schema=conformance.USER_ISSUE_SCHEMA,native_id='synthetic-native',media=media,
        confirmed=True,confirmed_by='user',description='Synthetic fixture user confirms rough8-12s only.',intervals_ms=[[8000,12000]]))
    case=put(root/'CONFORMANCE_CASE.json',dict(schema=conformance.CASE_SCHEMA,attempt_id='A001',segment_id='S03',native_id='synthetic-native',
        media=media,source_case=source,asr_receipt=receipt,user_confirmed_issue=issue))
    report=put(root/'ASSESSMENT.json',conformance.evaluate_bound(case))
    spec=dict(schema='audio_gap_repair_spec/v1',native_id='synthetic-native',segment_id='S03',media=media,
        conformance_case=case,conformance_report=report,user_issue=issue,selected_unmapped_indices=[0],
        frame_clock=dict(frames=362,fps=24),audio_target=dict(rate=48000,channels=2),padding_ms=80,fade_ms=40,quote_protection_ms=80)
    sb=put(root/'SPEC.json',spec)
    return dict(root=root,media=media,spec=spec,sb=sb,run=root/'repair',case=case,report=report,issue=issue,asr=asr)


def test_prepare_uses_complete_actual_matches_not_user_coarse_or_source_windows(env,monkeypatch):
    e=env;monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('prepare may not run media commands'))
    assert gap.read(e['report']['path'])['decision']=='reject'
    result=gap.prepare(e['run'],e['sb']);p=gap.read(e['run']/'PLAN.json')['details']
    assert result['patches']==[dict(unmapped_index=0,core_ms=[8940,11980],patch_ms=[8860,12060],fade_ms=40)]
    assert p['protected_actual_quotes_ms']==[[340,8840],[12740,14365]]
    assert p['patches'][0]['patch_ms'][0]>8760


@pytest.mark.parametrize('kind',['wrong_native','unconfirmed','protected_overlap','incomplete_ASR'])
def test_unsafe_or_unconfirmed_inputs_rejected_before_plan(env,kind):
    e=env;s=deepcopy(e['spec'])
    if kind in ('wrong_native','unconfirmed'):
        issue=gap.read(e['issue']['path']);issue['native_id' if kind=='wrong_native' else 'confirmed']='other' if kind=='wrong_native' else False
        s['user_issue']=put(e['root']/'BAD_ISSUE.json',issue)
    elif kind=='protected_overlap':s['quote_protection_ms']=200
    else:
        case=gap.read(e['case']['path']);r=gap.read(e['asr']['path']);r['result'][0]['text']=r['result'][0]['text'].replace('爸','妈')
        receipt=gap.read(case['asr_receipt']['path']);receipt['raw_asr']=put(e['root']/'BAD_ASR.json',r)
        case['asr_receipt']=put(e['root']/'BAD_ASR_RECEIPT.json',receipt)
        s['conformance_case']=put(e['root']/'BAD_CASE.json',case)
        s['conformance_report']=put(e['root']/'BAD_ASSESSMENT.json',conformance.evaluate_bound(s['conformance_case']))
    with pytest.raises(ValueError):gap.prepare(e['run'],put(e['root']/'BAD_SPEC.json',s))
    assert not (e['run']/'PLAN.json').exists()


def test_failed_execute_claim_is_not_blindly_retried(env,monkeypatch):
    e=env;gap.prepare(e['run'],e['sb']);calls=[]
    def fail(*args):calls.append(args);raise RuntimeError('synthetic CPU command failed')
    monkeypatch.setattr(gap,'_command',fail)
    with pytest.raises(RuntimeError):gap.execute(e['run'])
    assert (e['run']/'EXECUTE_CLAIM.json').exists() and (e['run']/'ERROR.json').exists()
    monkeypatch.setattr(gap,'_command',lambda *a:pytest.fail('unknown claim may not rerun'))
    assert gap.execute(e['run'])['status']=='outcome_unknown' and len(calls)==1


def test_synthetic_streamcopy_PCM_boundary_AAC_core_and_deep_cached_proofs(env,monkeypatch):
    e=env;source_before=gap.bind(e['media']['path']);gap.prepare(e['run'],e['sb'])
    result=gap.execute(e['run']);assert result['status']=='verified_CPU_audio_repair'
    proof=gap.read(result['proof']['path']);audio=proof['audio_QA'];cores=audio['core_levels']
    assert proof['video_frames_PTS_and_decoded_hashes_unchanged'] and proof['video_streamcopy']
    assert cores[0]['original']['RMS']>1000 and cores[0]['edited']['peak']==0 and cores[0]['final_AAC_decoded']['RMS']<=30
    assert audio['edited_PCM_outside_patch_exact'] and audio['final_AAC_outside_correlation_passed']
    assert audio['final_AAC_PCM_byte_identical_claim'] is False
    before=np.fromfile(proof['normalized_input_PCM']['path'],dtype='<i2').reshape(-1,2)
    edited=np.fromfile(proof['edited_PCM']['path'],dtype='<i2').reshape(-1,2)
    assert np.array_equal(before[8000*48:8760*48],edited[8000*48:8760*48])
    assert np.max(np.abs(edited[8000*48:8700*48].astype(float)))>1000
    assert gap.bind(e['media']['path'])==source_before
    put(e['run']/'ROOT_CHECKPOINT.json',dict(status='root metadata changes normally'))
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('cached execute/qa must not invoke subprocess'))
    assert gap.qa(e['run'])==result and gap.execute(e['run'])==result
    put(e['run']/'ROOT_CHECKPOINT.json',dict(status='new root checkpoint'))
    assert gap.qa(e['run'])==result
    target=Path(proof['edited_PCM']['path']);data=target.read_bytes();target.write_bytes(b'changed'+data[7:])
    with pytest.raises(ValueError):gap.qa(e['run'])
