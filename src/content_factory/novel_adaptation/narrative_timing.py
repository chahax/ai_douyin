"""Deterministic planning estimate, not measured speech or a semantic approval."""
import math
from .contracts import digest


def repair_feedback(candidate, maximum_seconds=240):
    """Locate actual speech pressure without changing durations or writing prose."""
    timing=schedule(candidate,maximum_seconds=maximum_seconds)
    rows=[]
    indexed={b['id']:(si,bi) for si,s in enumerate(candidate['scenes']) for bi,b in enumerate(s['segments'])}
    for row in timing['segments']:
        extra=round(row['scheduled_seconds']-row['authored_seconds'],3)
        if extra<=0:continue
        si,bi=indexed[row['segment_id']]
        rows.append({'segment_id':row['segment_id'],'authored_seconds':row['authored_seconds'],
            'estimated_seconds':row['scheduled_seconds'],'speech_excess_seconds':extra,
            'audio_paths':[f'/scenes/{si}/segments/{bi}/audio/{a["index"]}/text' for a in row['audio_estimate']]})
    return {'candidate_sha256':digest(candidate),'maximum_seconds':maximum_seconds,
            'estimated_seconds':timing['total_seconds'],
            'minimum_total_reduction_seconds':round(max(0,timing['total_seconds']-maximum_seconds),3),
            'speech_pressure':sorted(rows,key=lambda x:-x['speech_excess_seconds']),
            'policy':timing['policy'],'semantic_acceptance':False,
            'instruction':'Compress actual content only where approved; never reduce labels alone. Preserve source causality, conditions and all unapproved fields. Speech pressure is diagnostic, not permission to edit.'}


def schedule(candidate, characters_per_second=4.0, turn_gap_seconds=.25, maximum_seconds=240):
    if any(not isinstance(x,(int,float)) or isinstance(x,bool) or not math.isfinite(x)
           for x in (characters_per_second,turn_gap_seconds,maximum_seconds)):
        raise ValueError('invalid_timing_policy')
    if characters_per_second<=0 or turn_gap_seconds<0 or maximum_seconds<=0:raise ValueError('invalid_timing_policy')
    elapsed=0;rows=[];seen=set()
    for scene in candidate['scenes']:
        for b in scene['segments']:
            if b['id'] in seen:raise ValueError('duplicate_timing_segment')
            seen.add(b['id']);audio=[];cursor=0
            for i,a in enumerate(b['audio']):
                count=sum(ch.isalnum() for ch in a['text'])
                if not count:raise ValueError('nonverbal_pause_encoded_as_speech')
                if i:cursor+=turn_gap_seconds
                end=cursor+count/characters_per_second
                audio.append({'index':i,'text_sha256':digest(a['text']),'start':round(elapsed+cursor,3),
                              'end':round(elapsed+end,3),'spoken_character_count':count})
                cursor=end
            authored=b['seconds']
            if type(authored) not in (int,float) or not math.isfinite(authored) or authored<=0:
                raise ValueError('invalid_authored_duration')
            duration=max(authored,math.ceil((cursor-1e-9)*10)/10)
            rows.append({'scene_id':scene['id'],'segment_id':b['id'],'authored_seconds':authored,
                         'scheduled_seconds':duration,'start':round(elapsed,3),'end':round(elapsed+duration,3),
                         'audio_estimate':audio})
            elapsed+=duration
    return {'candidate_sha256':digest(candidate),'policy':{'characters_per_second':characters_per_second,
        'turn_gap_seconds':turn_gap_seconds,'counting':'Unicode alphanumeric characters; Chinese planning heuristic'},
        'segments':rows,'total_seconds':round(elapsed,3),'within_brief':elapsed<=maximum_seconds,
        'status':'estimated_schedule_not_measured_performance',
        'limits':['Audio and visual action may overlap; visual duration is not added to speech duration.',
                  'Does not prove pronunciation, acting pauses, shot feasibility or story quality.']}
