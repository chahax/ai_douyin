"""Strict rounding evidence + real small-profile CPU video/audio fixture."""
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from src.content_factory import visual_spatial_clock_v30 as c


def metadata(delta_ticks=-4):
    return {'streams':[{'codec_type':'video','width':736,'height':1312,'nb_frames':'362','nb_read_frames':'362','r_frame_rate':'24/1','avg_frame_rate':'24/1','duration_ts':185344+delta_ticks,'time_base':'1/12288','start_time':'0.000000'},
                       {'codec_type':'audio','duration_ts':482667,'time_base':'1/32000','start_time':'0.000000','sample_rate':'32000'}]}


def frame_rows():return {'frames':[{'best_effort_timestamp':i*512,'pts':i*512,'duration':512} for i in range(362)]}


@pytest.fixture
def wired(tmp_path,monkeypatch):
    path=tmp_path/'CPU_media';path.write_bytes(b'not production media');sha=c.file_sha(path);meta=metadata();rows=frame_rows()
    monkeypatch.setattr(c,'_probe',lambda p:deepcopy(meta));monkeypatch.setattr(c,'_probe_frames',lambda p:deepcopy(rows));monkeypatch.setattr(c,'_decode_audio',lambda p,r:b'\0'*(724992*4))
    return path,sha,meta,rows


def test_submillisecond_rounding_requires_actual_uniform_frames(wired):
    path,sha,meta,rows=wired;v=c.clock_input(path,sha)
    assert v['clock_normalization']['mode']=='verified_container_rounding'
    p=v['clock_normalization']['decoded_frame_proof'];assert p['frame_count']==362 and p['last_end_seconds']=='181/12'
    assert len(p['ordered_frame_timing_sha256'])==64 and len(p['timing_records'])==362
    assert v['trim_tail_samples']==992 and v['target_samples']==724000
    assert v['native_metadata']==meta and c.file_sha(path)==sha


def test_exact_container_does_not_invent_perframe_proof(wired,monkeypatch):
    path,sha,meta,rows=wired;meta['streams'][0]['duration_ts']=185344
    monkeypatch.setattr(c,'_probe_frames',lambda p:pytest.fail('exact original contract needs no relaxed proof'))
    assert c.clock_input(path,sha)['clock_normalization']['decoded_frame_proof'] is None


@pytest.mark.parametrize('ticks',[-13,13,-40])
def test_at_or_above_one_ms_rejected(wired,ticks):
    path,sha,meta,rows=wired;meta['streams'][0]['duration_ts']=185344+ticks
    with pytest.raises(c.SpatialClockError,match='not_submillisecond'):c.clock_input(path,sha)


def test_exact_one_ms_boundary_rejected(wired):
    path,sha,meta,rows=wired;meta['streams'][0]['time_base']='1/24000';meta['streams'][0]['duration_ts']=362000+24
    with pytest.raises(c.SpatialClockError,match='not_submillisecond'):c.clock_input(path,sha)


@pytest.mark.parametrize('value',[512.2,True,None,'512.2'])
def test_fractional_or_missing_frame_timing_not_truncated(wired,value):
    path,sha,meta,rows=wired;rows['frames'][1]['duration']=value
    with pytest.raises(c.SpatialClockError):c.clock_input(path,sha)


@pytest.mark.parametrize('mutation',['shift','uneven','duration','missing_pts','missing_duration','missing_frame'])
def test_bad_actual_frame_evidence_rejected(wired,mutation):
    path,sha,meta,rows=wired
    if mutation=='shift':
        for r in rows['frames']:r['best_effort_timestamp']+=1;r['pts']+=1
    elif mutation=='uneven':rows['frames'][100]['best_effort_timestamp']+=1;rows['frames'][100]['pts']+=1
    elif mutation=='duration':rows['frames'][-1]['duration']=508
    elif mutation=='missing_pts':rows['frames'][1].pop('best_effort_timestamp')
    elif mutation=='missing_duration':rows['frames'][1].pop('duration')
    else:rows['frames'].pop()
    with pytest.raises(c.SpatialClockError):c.clock_input(path,sha)


@pytest.mark.parametrize('key,value',[('width',720),('height',1280),('nb_frames','361'),('nb_read_frames','361'),('r_frame_rate','25/1'),('start_time','.001')])
def test_wrong_profile_or_video_start_rejected(wired,key,value):
    path,sha,meta,rows=wired;meta['streams'][0][key]=value
    with pytest.raises(c.SpatialClockError):c.clock_input(path,sha)


def test_sha_changed_rejected_before_probe(wired):
    path,sha,meta,rows=wired;path.write_bytes(b'changed')
    with pytest.raises(c.SpatialClockError,match='input_changed'):c.clock_input(path,sha)


def test_sha_changes_during_decode_rejected(wired,monkeypatch):
    path,sha,meta,rows=wired
    def decode(p,r):path.write_bytes(b'changed during read');return b'\0'*(724000*4)
    monkeypatch.setattr(c,'_decode_audio',decode)
    with pytest.raises(c.SpatialClockError,match='input_changed'):c.clock_input(path,sha)


def test_audio_skew_and_decoded_padding_still_rejected(wired,monkeypatch):
    path,sha,meta,rows=wired;meta['streams'][1]['start_time']='0.3'
    with pytest.raises(c.SpatialClockError,match='audio_skew'):c.clock_input(path,sha)
    meta['streams'][1]['start_time']='0';monkeypatch.setattr(c,'_decode_audio',lambda p,r:b'\0'*(800000*4))
    with pytest.raises(c.SpatialClockError,match='decoded_audio_clock'):c.clock_input(path,sha)


def test_probe_read_failure_never_normalized(wired,monkeypatch):
    path,sha,meta,rows=wired
    monkeypatch.setattr(c,'_probe_frames',lambda p:(_ for _ in ()).throw(OSError('read failed')))
    with pytest.raises(OSError,match='read failed'):c.clock_input(path,sha)


def test_missing_raw_duration_never_normalized(wired):
    path,sha,meta,rows=wired;meta['streams'][0].pop('duration_ts')
    with pytest.raises(c.SpatialClockError,match='evidence_missing'):c.clock_input(path,sha)


def test_real_cpu_small_profile_362_frames_and_audio_decode(tmp_path):
    video=tmp_path/'CPU_SMALL_128x96_362frames.mp4'
    command=['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=navy:s=128x96:r=24','-f','lavfi','-i','sine=frequency=440:sample_rate=32000','-frames:v','362','-t',str(float(Fraction(362,24))),'-c:v','libx264','-threads','1','-pix_fmt','yuv420p','-c:a','aac','-video_track_timescale','12288',str(video)]
    subprocess.run(command,check=True,capture_output=True,timeout=120)
    original=c.file_sha(video);v=c.clock_input(video,original,width=128,height=96)
    assert v['target_samples']==724000 and v['decoded_48k_samples']>0
    assert v['profile']['width']==128 and c.file_sha(video)==original
    with pytest.raises(c.SpatialClockError,match='geometry'):c.clock_input(video,original)
    # Change only this generated QA fixture's video mdhd duration. Real frame
    # PTS/durations remain intact and are read by actual ffprobe, not mocked.
    data=bytearray(video.read_bytes())
    def boxes(start,end):
        while start<end:
            size=int.from_bytes(data[start:start+4],'big');kind=bytes(data[start+4:start+8]);assert size>=8
            yield start,size,kind
            start+=size
    moov=next(x for x in boxes(0,len(data)) if x[2]==b'moov');changed=False
    for track in (x for x in boxes(moov[0]+8,moov[0]+moov[1]) if x[2]==b'trak'):
        mdia=next(x for x in boxes(track[0]+8,track[0]+track[1]) if x[2]==b'mdia');parts=list(boxes(mdia[0]+8,mdia[0]+mdia[1]));hdlr=next(x for x in parts if x[2]==b'hdlr')
        if bytes(data[hdlr[0]+16:hdlr[0]+20])==b'vide':
            mdhd=next(x for x in parts if x[2]==b'mdhd');assert data[mdhd[0]+8]==0;offset=mdhd[0]+24
            duration=int.from_bytes(data[offset:offset+4],'big');assert duration==185344
            data[offset:offset+4]=(duration-4).to_bytes(4,'big');changed=True
    assert changed
    rounded=tmp_path/'CPU_SMALL_ROUNDING_ONLY_128x96.mp4';rounded.write_bytes(data)
    rounded_sha=c.file_sha(rounded);proof=c.clock_input(rounded,rounded_sha,width=128,height=96)
    assert proof['clock_normalization']['mode']=='verified_container_rounding'
    assert proof['clock_normalization']['raw_container_delta_seconds']=='-1/3072'
    assert proof['clock_normalization']['decoded_frame_proof']['last_end_seconds']=='181/12'
    assert c.file_sha(rounded)==rounded_sha and c.file_sha(video)==original
