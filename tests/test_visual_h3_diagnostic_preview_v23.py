"""Explicit diagnostic override does not convert quality failure into approval."""
from copy import deepcopy
from pathlib import Path
import subprocess
import pytest
from src.content_factory import visual_h3_diagnostic_preview_v23 as d
from tests.test_visual_h3_reference_full_minute_v20 import system,prepare,review,write

f=d.base


def enable(s):
    prepare(s)
    for i in (0,1):s['complete'](s['segments'][i]['delivery_run'])
    review(s,0,True);review(s,1,False)
    request=s['run']/'USER_DIAGNOSTIC_PREVIEW_REQUEST.json'
    write(request,dict(user_statement='你不用拦，我需要看的是自动化出来的成片，分析是调整还是换线路',
                       scope='Original four-segment diagnostic preview only; no repair or publication.',
                       do_not_duplicate_execute=True,quality_rejected=['S02']))
    return d.enable(s['run'],request=request)


def test_explicit_preview_continues_without_rewriting_false_or_waiting_future_quality_review(system):
    s=system;enable(s);file=s['run']/'segments/S02/ROOT_SEGMENT_REVIEW.json';original=file.read_bytes()
    result=f.tick(s['run']);assert result['diagnostic_preview'] and result['quality_failed']==['S02']
    assert s['posts']==[s['segments'][2]['delivery_run']]
    s['complete'](s['segments'][2]['delivery_run']);f.tick(s['run'])
    assert s['posts']==[r['delivery_run'] for r in s['segments'][2:]]
    s['complete'](s['segments'][3]['delivery_run'])
    assert f.tick(s['run'])['stage']=='all_preview_segments_saved'
    assert file.read_bytes()==original and f.status(s['run'])['reviewed']==1
    with pytest.raises(f.MinuteRunError,match='four_saved_and_root_reviewed'):f.assemble(s['run'])


def test_override_cannot_replay_unknown_or_replace_a_known_native_id(system):
    s=system;enable(s);state=s['states'][s['segments'][2]['delivery_run']];state['status']='outcome_unknown'
    assert f.tick(s['run'])['stage']=='blocked_outcome_unknown' and not s['posts']
    state['status']='prepared'
    s['states'][s['segments'][0]['delivery_run']]['prompt_id']='other_known_id'
    with pytest.raises(f.MinuteRunError):f.tick(s['run'])
    assert not s['posts']


@pytest.mark.parametrize('target',['request','false_review','source_copy'])
def test_preview_bindings_and_original_source_protections_remain_strict(system,target):
    s=system;enable(s)
    if target=='request':(s['run']/'USER_DIAGNOSTIC_PREVIEW_REQUEST.json').write_bytes(b'changed request')
    elif target=='false_review':
        path=s['run']/'segments/S02/ROOT_SEGMENT_REVIEW.json';value=f.native.read(path);value['approved_for_next']=True;write(path,value)
    else:Path(s['segments'][3]['source_prompt_file']['path']).write_bytes(b'changed S04 prompt')
    with pytest.raises(f.MinuteRunError):f.tick(s['run'])
    assert not s['posts']


def test_preview_assembly_keeps_failed_label_distinct_inputs_and_exact_clock(system,monkeypatch):
    s=system;enable(s)
    with pytest.raises(f.MinuteRunError,match='four_original_saved'):d.assemble(s['run'])
    for i in (2,3):s['complete'](s['segments'][i]['delivery_run'])
    calls=[]
    monkeypatch.setattr(f.clock,'_scope',lambda *args:pytest.fail('old production scope must not be called'))
    monkeypatch.setattr(f,'_clock_input',lambda path,sha:dict(decoded_48k_samples=724000,target_samples=724000))
    def encode(command,**kwargs):
        calls.append(command);Path(command[-1]).write_bytes(b'CPU diagnostic protocol fixture, not actual movie')
        return subprocess.CompletedProcess(command,0,stdout='',stderr='')
    monkeypatch.setattr(d.subprocess,'run',encode)
    metadata=dict(streams=[dict(codec_type='video',width=736,height=1312,nb_frames='1448',nb_read_frames='1448',r_frame_rate='24/1',avg_frame_rate='24/1',start_time='0',duration_ts=1448,time_base='1/24'),
        dict(codec_type='audio',sample_rate='48000',channels=2,start_time='0',duration_ts=2896000,time_base='1/48000')],format=dict(duration='60.333333'))
    monkeypatch.setattr(f,'_probe',lambda path:deepcopy(metadata))
    result=d.assemble(s['run'])
    assert result['quality_failed']==['S02'] and result['quality_unreviewed']==['S03','S04']
    assert result['diagnostic_preview'] and not result['production_approved'] and not result['publication']
    assert result['clock']['native_frames']==1448 and result['clock']['audio_samples']==2896000
    assert len(result['native_ids'])==4 and len(calls)==1 and not s['posts']
    assert d.assemble(s['run'])==result and len(calls)==1
    originalreview=f.native.read(s['run']/'segments/S02/ROOT_SEGMENT_REVIEW.json')
    assert originalreview['approved_for_next'] is False
    Path(result['file']['path']).write_bytes(b'changed output')
    with pytest.raises(f.MinuteRunError):d.assemble(s['run'])
