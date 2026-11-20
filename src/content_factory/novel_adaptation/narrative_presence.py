"""Replay narrative occupancy through the existing event interpreter.

Projection evidence must still be independently checked for semantic completeness.
This adapter does not certify prop or source fidelity.
"""
from copy import deepcopy
from dataclasses import asdict
from . import contracts as c
from .scenes import play_beat


def error_record(error):
    result={'type':type(error).__name__,'message':str(error)[:10000]}
    if isinstance(error,c.ContractError):result['issues']=[asdict(issue) for issue in error.issues]
    if hasattr(error,'replay_diagnostic'):result['replay_diagnostic']=deepcopy(error.replay_diagnostic)
    return result


def body_schema(candidate, people, places):
    """Model supplies semantic data; the request owner supplies artifact identity."""
    result=schema(candidate,people,places)
    result['required'].remove('candidate_sha256')
    del result['properties']['candidate_sha256']
    return result


def bind_body(candidate, body, requested_sha256, people, places):
    if c.digest(candidate)!=requested_sha256:raise ValueError('request_candidate_changed')
    errors=c.schema_issues(body,body_schema(candidate,people,places),'presence_body')
    if errors:raise c.ContractError(errors)
    return {'candidate_sha256':requested_sha256,**deepcopy(body)}


def schema(candidate, people, places):
    ids=[b['id'] for s in candidate['scenes'] for b in s['segments']]
    move=c.obj(person=c.choices(people),origin=c.choices(places),destination=c.choices(places),
        phase=c.choices(['start','end','after_audio']),after_audio_index={'type':['integer','null'],'minimum':0},
        evidence_field=c.choices(['action','entry_continuity','exit_continuity','continuity_obligations']),quote=c.TEXT)
    segment=c.obj(id=c.choices(ids),moves=c.array(move))
    segment['properties']['sensory_windows']=c.array(c.obj(place=c.choices(places),
        through_audio_index={'type':'integer','minimum':-1},visible={'type':'boolean'},audible={'type':'boolean'},
        evidence_field=c.choices(['action','camera','continuity_obligations']),quote=c.TEXT))
    segment['properties']['sensory_windows']['items']['properties']['from_audio_index']={'type':'integer','minimum':-1}
    return c.obj(candidate_sha256=c.choices([c.digest(candidate)]),
        initial_locations=c.obj(**{p:c.choices(places) for p in people}),
        segments=c.array(segment,len(ids)),
        uncertainties=c.array(c.TEXT))


def replay(candidate, projection, people, places, *, prop_plan=None, prop_projection=None):
    errors=c.schema_issues(projection,schema(candidate,people,places),'presence_projection')
    if errors:raise c.ContractError(errors)
    expected=[b['id'] for s in candidate['scenes'] for b in s['segments']]
    if [r['id'] for r in projection['segments']]!=expected:raise ValueError('projection_segment_coverage')
    state={'locations':deepcopy(projection['initial_locations']),'props':{}}
    prop_rows={};prop_receipts=[]
    if (prop_plan is None)!=(prop_projection is None):raise ValueError('prop_plan_and_projection_required')
    if prop_plan is not None:
        from .narrative_props import prepare
        state,prop_rows,prop_receipts=prepare(candidate,projection,prop_plan,prop_projection,people,places)
    trace=[];index=0
    for scene in candidate['scenes']:
        if scene['place'] not in places:raise ValueError('unknown_scene_place')
        for j,b in enumerate(scene['segments']):
            row=projection['segments'][index];index+=1;moves=[]
            for m in row['moves']:
                field=m['evidence_field']
                if field=='entry_continuity':
                    if j!=0:raise ValueError('entry_evidence_wrong_segment')
                    evidence=[scene[field]]
                elif field=='exit_continuity':
                    if j!=len(scene['segments'])-1:raise ValueError('exit_evidence_wrong_segment')
                    evidence=[scene[field]]
                else:evidence=b[field] if isinstance(b[field],list) else [b[field]]
                if not any(m['quote'] in text for text in evidence):raise ValueError('move_quote_not_exact')
                if (m['phase']=='after_audio') != (m['after_audio_index'] is not None):
                    raise ValueError('move_audio_phase_mismatch')
                if m['phase']=='after_audio' and m['after_audio_index']>=len(b['audio']):
                    raise ValueError('move_audio_anchor_missing')
                moves.append({k:v for k,v in m.items() if k not in ('quote','evidence_field') and v is not None})
            beat={k:[] for k in ('transfers','prop_uses','gestures','unpacks','packs','transforms','requires_information')}
            beat.update(id=b['id'],moves=moves,audio=deepcopy(b['audio']),shot_subjects=b['visible_people'])
            if prop_rows:beat.update(deepcopy(prop_rows[b['id']]))
            found=[]
            def fail(path,code,message):found.append(c.Issue('presence',path,code,message))
            before=deepcopy(state)
            windows=row.get('sensory_windows',[])
            for window in windows:
                evidence=b[window['evidence_field']]
                evidence=evidence if isinstance(evidence,list) else [evidence]
                if not any(window['quote'] in text for text in evidence):raise ValueError('sensory_quote_not_exact')
            audiences=play_beat(state,beat,scene['place'],scene['id'],'/'+b['id'],fail,sensory_windows=windows)
            if found:
                error=c.ContractError(found)
                error.replay_diagnostic={'candidate_sha256':c.digest(candidate),'projection_sha256':c.digest(projection),
                    'failed_segment_id':b['id'],'completed_segment_count':len(trace),
                    'state_before_failed_segment':before,'attempted_events':deepcopy(beat),
                    'completed_trace':deepcopy(trace),'partial_after_state_accepted':False}
                raise error
            trace.append({'segment_id':b['id'],'before_locations':before['locations'],
                          'after_locations':deepcopy(state['locations']),'audio_audiences':audiences,
                          'before_props':before['props'],'after_props':deepcopy(state['props']),
                          'after_containers':deepcopy(state.get('containers',{}))})
            if 'postures' in state or 'postures' in before:
                trace[-1]['before_postures']=deepcopy(before.get('postures',{}))
                trace[-1]['after_postures']=deepcopy(state.get('postures',{}))
    return {'candidate_sha256':c.digest(candidate),'projection_sha256':c.digest(projection),
            'status':'projected_presence_replayed_not_semantic_acceptance',
            'trace':trace,'end_state':state,'uncertainties':projection['uncertainties'],
            'prop_projection_sha256':c.digest(prop_projection) if prop_projection is not None else None,
            'prop_evidence_receipts':prop_receipts,
            'prop_uncertainties':prop_projection['uncertainties'] if prop_projection is not None else [],
            'limits':['Projection may omit transitions: source-to-projection completeness requires review.',
                      'Initial placements are proposed, not automatically verified.',
                      'Only supplied prop events are replayed; omissions and evidence meaning require review.',
                      'Timing and source fidelity are not certified by this adapter.']}
