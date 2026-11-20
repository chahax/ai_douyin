"""Read-only native-input clock verification with proven sub-ms MP4 rounding.

Never changes a media file or substitutes guessed timing. Only a nonzero
container video-duration delta strictly below 1ms may use actual per-frame
decoded PTS/duration proof. All geometry/hash/audio protections remain strict.
"""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import subprocess


class SpatialClockError(ValueError):
    pass


def file_sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def _json_command(command):
    return json.loads(subprocess.check_output(command,text=True,encoding='utf-8',stderr=subprocess.PIPE,timeout=180))


def _probe(path):
    return _json_command(['ffprobe','-v','error','-threads','1','-count_frames','-show_streams','-show_format','-of','json',str(path)])


def _probe_frames(path):
    return _json_command(['ffprobe','-v','error','-threads','1','-select_streams','v:0','-show_frames','-show_entries','frame=best_effort_timestamp,pts,duration,pkt_duration','-of','json',str(path)])


def _duration(stream):
    return Fraction(_integer(stream['duration_ts']))*Fraction(stream['time_base'])


def _integer(value):
    if type(value) is int:return value
    if isinstance(value,str) and re.fullmatch(r'-?\d+',value):return int(value)
    raise SpatialClockError('actual_integer_frame_timing_required')


def _frame_proof(document,time_base,frames,fps):
    rows=document.get('frames')
    if not isinstance(rows,list) or len(rows)!=frames:raise SpatialClockError('actual_frame_timing_count_required')
    normalized=[];tb=Fraction(time_base)
    if tb<=0:raise SpatialClockError('positive_video_time_base_required')
    for index,row in enumerate(rows):
        if not isinstance(row,dict) or 'best_effort_timestamp' not in row:raise SpatialClockError('actual_frame_pts_required')
        try:
            pts=_integer(row['best_effort_timestamp']);raw=row.get('duration',row.get('pkt_duration'))
            if raw is None:raise SpatialClockError('actual_frame_duration_required')
            duration=_integer(raw)
            if ('pts' in row and _integer(row['pts'])!=pts) or ('duration' in row and 'pkt_duration' in row and _integer(row['duration'])!=_integer(row['pkt_duration'])):
                raise SpatialClockError('actual_frame_timestamp_fields_disagree')
        except (TypeError,ValueError,OverflowError) as error:
            if isinstance(error,SpatialClockError):raise
            raise SpatialClockError('actual_integer_frame_timing_required') from error
        if Fraction(pts)*tb!=Fraction(index,fps) or Fraction(duration)*tb!=Fraction(1,fps):
            raise SpatialClockError('actual_frame_clock_not_uniform_from_zero')
        normalized.append({'best_effort_timestamp':pts,'duration':duration})
    end=Fraction(normalized[-1]['best_effort_timestamp']+normalized[-1]['duration'])*tb
    if end!=Fraction(frames,fps):raise SpatialClockError('actual_last_frame_end_changed')
    digest=hashlib.sha256(json.dumps(normalized,separators=(',',':'),sort_keys=True).encode()).hexdigest()
    return {'schema':'decoded_frame_timing_proof/v30','frame_count':frames,'time_base':str(tb),'fps':fps,'first_pts':normalized[0]['best_effort_timestamp'],
            'last_pts':normalized[-1]['best_effort_timestamp'],'last_duration':normalized[-1]['duration'],'last_end_seconds':str(end),
            'ordered_frame_timing_sha256':digest,'all_pts_equal_index_over_fps':True,'all_durations_equal_one_over_fps':True,
            'timing_records':normalized}


def _decode_audio(path,rate):
    return subprocess.check_output(['ffmpeg','-nostdin','-v','error','-threads','1','-i',str(path),'-map','0:a:0','-af',f'aresample={rate}:async=0:first_pts=0','-ar',str(rate),'-ac','2','-c:a','pcm_s16le','-f','s16le','pipe:1'],stderr=subprocess.PIPE,timeout=180)


def clock_input(path,sha,frames=362,width=736,height=1312,fps=24,rate=48000):
    if any(type(v) is not int or v<=0 for v in (frames,width,height,fps,rate)) or rate%fps:
        raise SpatialClockError('explicit_integral_clock_profile_required')
    path=Path(path)
    if file_sha(path)!=sha:raise SpatialClockError('assembly_input_changed')
    meta=_probe(path)
    try:
        video=next(s for s in meta['streams'] if s['codec_type']=='video');audio=next(s for s in meta['streams'] if s['codec_type']=='audio')
        if ((video['width'],video['height'],int(video.get('nb_frames',-1)),int(video.get('nb_read_frames',-1)),Fraction(video['r_frame_rate']),Fraction(video['avg_frame_rate']))
                !=(width,height,frames,frames,Fraction(fps),Fraction(fps))):raise SpatialClockError('native_input_video_geometry_or_count_changed')
        if Fraction(video['start_time'])!=0:raise SpatialClockError('native_input_video_start_not_zero')
        target=Fraction(frames,fps);raw_duration=_duration(video);delta=raw_duration-target
        if delta and abs(delta)>=Fraction(1,1000):raise SpatialClockError('container_video_duration_delta_not_submillisecond')
        proof=_frame_proof(_probe_frames(path),video['time_base'],frames,fps) if delta else None
        audio_duration=_duration(audio);audio_start=Fraction(audio['start_time']);sample_rate=int(audio['sample_rate'])
        if sample_rate<=0 or max(abs(audio_duration-target),abs(audio_start),abs(audio_start+audio_duration-target))>Fraction(1,4):
            raise SpatialClockError('native_source_audio_skew_too_large')
    except (KeyError,StopIteration,TypeError,ValueError,ZeroDivisionError) as error:
        if isinstance(error,SpatialClockError):raise
        raise SpatialClockError('native_timing_evidence_missing_or_invalid') from error
    pcm=_decode_audio(path,rate)
    if not pcm or len(pcm)%4:raise SpatialClockError('native_audio_decode_failed')
    samples=len(pcm)//4
    if abs(Fraction(samples,rate)-target)>Fraction(1,4)+Fraction(1024,sample_rate)+Fraction(1,rate):
        raise SpatialClockError('native_decoded_audio_clock_changed')
    if file_sha(path)!=sha:raise SpatialClockError('assembly_input_changed')
    target_samples=frames*(rate//fps)
    return {'native_metadata':meta,'decoded_48k_samples':samples,'target_samples':target_samples,
            'trim_tail_samples':max(0,samples-target_samples),'pad_tail_samples':max(0,target_samples-samples),
            'clock_normalization':{'schema':'native_video_container_rounding/v30','mode':'verified_container_rounding' if delta else 'exact_container_duration',
                                   'raw_container_video_duration_seconds':str(raw_duration),'target_video_duration_seconds':str(target),
                                   'raw_container_delta_seconds':str(delta),'raw_container_delta_milliseconds':float(delta*1000),
                                   'submillisecond_tolerance_seconds':'1/1000 (strictly below)','decoded_frame_proof':proof,'source_bytes_modified':False},
            'profile':{'frames':frames,'width':width,'height':height,'fps':fps,'audio_rate':rate}}
