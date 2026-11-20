"""CPU timing-only fixtures. Never native output/identity or production acceptance."""
from copy import deepcopy
from fractions import Fraction
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

SOURCE=Path(__file__).resolve().parents[1]/'data/video_generation/novel_5min_20261106_v1/run_production.py'
spec=importlib.util.spec_from_file_location('novel5min_clock_test_only',SOURCE)
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)


def metadata(frames=7292):
    return dict(streams=[dict(codec_type='video',width=736,height=1312,r_frame_rate='24/1',avg_frame_rate='24/1',
        nb_frames=frames,nb_read_frames=frames,start_time='0',duration_ts=frames*512,time_base='1/12288'),
        dict(codec_type='audio',codec_name='aac',start_time='0',sample_rate='48000',channels=2,duration_ts=frames*2000,time_base='1/48000')],
        format=dict(duration=str(frames/24)))


@pytest.mark.parametrize('change,message',[
    (lambda m:m['streams'][0].update(start_time='0.041016'),'start_not_zero'),
    (lambda m:m['streams'][1].update(start_time='0.001'),'start_not_zero'),
    (lambda m:m['streams'][0].update(nb_read_frames=7291),'wrong_format'),
    (lambda m:m['streams'][0].update(nb_frames=7312,nb_read_frames=7312),'wrong_format'),
    (lambda m:m['streams'][1].update(duration_ts=7292*2000+2),'audio_clock'),
    (lambda m:m['streams'][0].update(duration_ts=7292*512+1),'video_clock'),
])
def test_final_gate_checks_decoded_count_both_origins_and_both_clocks(change,message):
    value=metadata();assert runner._verify_assembly_metadata(value,dict(source_seconds=7292/24))==7292/24
    change(value)
    with pytest.raises(runner.Blocked,match=message):runner._verify_assembly_metadata(value,dict(source_seconds=7292/24))


def test_more_than_quarter_second_native_audio_skew_stops_before_decode(monkeypatch,tmp_path):
    value=metadata(24);value['streams'][1].update(sample_rate='32000',duration_ts=40001,time_base='1/32000')
    calls=[]
    def output(*args,**kwargs):calls.append(args[0]);return json.dumps(value)
    monkeypatch.setattr(runner.subprocess,'check_output',output)
    with pytest.raises(runner.Blocked,match='native_audio_video_duration_skew'):
        runner._inspect_assembly_clip(tmp_path/'TIMING_ONLY.mp4',24)
    assert len(calls)==1 and calls[0][0]=='ffprobe'


def ffmpeg(args):
    return subprocess.run(['ffmpeg','-nostdin','-v','error','-threads','1','-filter_threads','1','-filter_complex_threads','1',*args],
                          check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)


def probe(path):
    return json.loads(subprocess.check_output(['ffprobe','-v','error','-threads','1','-count_frames','-show_streams','-show_format','-of','json',str(path)],encoding='utf-8'))


@pytest.fixture(scope='module')
def timing_fixtures(tmp_path_factory):
    home=tmp_path_factory.mktemp('TIMING_ONLY_h3_buckets');result=[]
    # Actual H3 frame buckets, deliberately tiny pictures and explicit fixture names.
    for n,extra in [(175,512),(277,-3200),(362,512)]:
        samples=-(-n*32000//24)+extra;path=home/f'TIMING_ONLY_{n}_{extra}.mp4'
        filters=f'[0:v]trim=end_frame={n},setpts=N/(24*TB)[v];[1:a]atrim=end_sample={samples},asetpts=N/SR/TB[a]'
        ffmpeg(['-f','lavfi','-i','testsrc2=size=64x80:rate=24','-f','lavfi','-i','sine=frequency=440:sample_rate=32000',
            '-filter_complex',filters,'-map','[v]','-map','[a]','-c:v','libx264','-preset','ultrafast','-crf','0','-threads','1',
            '-c:a','aac','-ar','32000','-ac','2','-video_track_timescale','12288',str(path)])
        result.append((n,path))
    return home,result


def test_source_timing_audit_counts_real_decoded_padding_and_short_audio(timing_fixtures):
    _,clips=timing_fixtures
    inspected=[runner._inspect_assembly_clip(p,n,expected_sha256=runner.assets.file_sha(p)) for n,p in clips]
    assert [x['native_frames'] for x in inspected]==[175,277,362]
    assert inspected[0]['trim_tail_samples']>0 and inspected[1]['pad_tail_samples']>0
    for (n,_),row in zip(clips,inspected):
        assert row['target_audio_samples']==n*2000
        assert row['normalized_decoded_samples']-row['trim_tail_samples']+row['pad_tail_samples']==n*2000
        assert row['source_metadata']['streams'][0]['nb_read_frames']==str(n)


def test_actual_frame_sample_clock_matches_each_input_and_starts_at_zero(timing_fixtures):
    home,clips=timing_fixtures;rows=[(dict(source_native_frames=n),{},path) for n,path in clips]
    script=home/'TIMING_ONLY.filter';output=home/'TIMING_ONLY_joined.mp4'
    command,filters=runner._assembly_command(rows,script,output,preset='ultrafast');script.write_text(filters,encoding='utf-8')
    subprocess.run(command,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)
    value=probe(output);video=next(s for s in value['streams'] if s['codec_type']=='video');audio=next(s for s in value['streams'] if s['codec_type']=='audio')
    total=sum(n for n,_ in clips)
    assert (video['width'],video['height'])==(64,80)  # Explicitly never a formal 736x1312 deliverable.
    assert int(video['nb_frames'])==int(video['nb_read_frames'])==total
    assert video['r_frame_rate']==video['avg_frame_rate']=='24/1'
    assert Fraction(video['start_time'])==Fraction(audio['start_time'])==0
    assert runner._duration(video)==runner._duration(audio)==Fraction(total,24)
    assert int(audio['duration_ts'])==total*2000
    assert '-f' not in command and 'fps=24' not in filters and 'async=1' not in filters


def test_audio_concat_preserves_exact_trimmed_or_padded_pcm_boundaries(timing_fixtures):
    home,clips=timing_fixtures;reference=b''
    for n,path in clips:
        raw=ffmpeg(['-i',str(path),'-map','0:a:0','-af','aresample=48000:async=0:first_pts=0',
                    '-ar','48000','-ac','2','-c:a','pcm_s16le','-f','s16le','pipe:1']).stdout
        wanted=n*2000*4;reference+=raw[:wanted]+b'\0'*max(0,wanted-len(raw))
    rows=[(dict(source_native_frames=n),{},path) for n,path in clips]
    _,filters=runner._assembly_command(rows,home/'unused.filter',home/'unused.mp4')
    script=home/'TIMING_ONLY_audio_exact.filter';script.write_text(filters+';[video]nullsink\n',encoding='utf-8')
    inputs=[]
    for _,path in clips:inputs+=['-threads','1','-i',str(path)]
    actual=ffmpeg([*inputs,'-filter_complex_script',str(script),'-map','[audio]',
                   '-c:a','pcm_s16le','-f','s16le','pipe:1']).stdout
    assert len(actual)==sum(n for n,_ in clips)*2000*4
    assert actual==reference  # Independent per-source PCM counts and all sample boundaries.


def test_timing_fixture_is_not_a_native_result_and_cannot_open_production_gate(timing_fixtures):
    home,clips=timing_fixtures
    rows=[dict(id=f'TIMING_ONLY_{i}',h3_run=str(home/f'NOT_NATIVE_{i}')) for i in range(27)]
    with pytest.raises(runner.Blocked,match='still_incomplete'):runner.completed_video_rows(dict(shots=rows))
    assert not (home/'FINAL_RESULT.json').exists() and not (home/'novel_opening_5m_736x1312.mp4').exists()
