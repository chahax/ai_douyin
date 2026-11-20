"""Editorial screenplay contract independent of culinary inventory operations.

This is a candidate stage, not a replacement for continuity or semantic acceptance.
"""
from . import contracts as c


def schema(source, packet, design):
    people = [x['id'] for x in packet['entities'] if x['kind'] == 'character']
    target = [key for key in c.catalog(source)
              if any(key.startswith(f'CH{n}-') for n in design['target_chapters'])]
    segment = c.obj(id=c.TEXT, seconds={'type':'number','exclusiveMinimum':0},
        visible_people=c.refs(people,0), action=c.TEXT, expression=c.TEXT, camera=c.TEXT,
        audio=c.array(c.obj(kind=c.choices(['dialogue','inner','narration']),
            speaker=c.choices(people+['NARRATOR']), text=c.TEXT)),
        source_ids=c.refs(target), visual_additions=c.array(c.TEXT),
        continuity_obligations=c.array(c.TEXT))
    scene = c.obj(id=c.choices([s['id'] for s in design['scenes']]),
        place=c.choices([p['id'] for p in design['places']]),
        entry_continuity=c.TEXT, segments=c.array(segment,1), exit_continuity=c.TEXT)
    return c.obj(title=c.TEXT, world_and_relationships=c.TEXT,
        visual_direction=c.TEXT, scenes=c.array(scene,1),
        condensation_notes=c.array(c.obj(source_ids=c.refs(target), treatment=c.TEXT)))


def diagnose(value, source, packet, design, maximum_seconds):
    """Collect independent structural failures; never certifies source meaning."""
    errors=c.schema_issues(value,schema(source,packet,design),'narrative_revision')
    if errors: raise c.ContractError(errors)
    findings=[]
    def issue(code,path,**details):
        findings.append({'code':code,'path':path,**details})
    if [s['id'] for s in value['scenes']] != [s['id'] for s in design['scenes']]:
        issue('scene_coverage_or_order_changed','/scenes')
    ids=[b['id'] for s in value['scenes'] for b in s['segments']]
    if len(ids)!=len(set(ids)):issue('duplicate_segment_id','/scenes')
    originals={s['id']:s for s in design['scenes']}
    for si,s in enumerate(value['scenes']):
        if s['place']!=originals[s['id']]['place']:issue('unapproved_location_change',f'/scenes/{si}/place')
        for bi,b in enumerate(s['segments']):
            for ai,a in enumerate(b['audio']):
                path=f'/scenes/{si}/segments/{bi}/audio/{ai}'
                if not any(ch.isalnum() for ch in a['text']):
                    issue('nonverbal_pause_encoded_as_speech',path+'/text')
                if a['kind']=='dialogue' and a['speaker'] not in b['visible_people']:
                    issue('dialogue_speaker_not_present',path+'/speaker')
                if (a['kind']=='narration') != (a['speaker']=='NARRATOR'):
                    issue('narrator_identity_mismatch',path)
    seconds=sum(b['seconds'] for s in value['scenes'] for b in s['segments'])
    if seconds>maximum_seconds:issue('editorial_duration_limit_exceeded','/scenes',actual_seconds=seconds,maximum_seconds=maximum_seconds)
    if not any(x['code'] in ('duplicate_segment_id','nonverbal_pause_encoded_as_speech') for x in findings):
        from .narrative_timing import schedule
        timing=schedule(value,maximum_seconds=maximum_seconds)
        if not timing['within_brief']:
            issue('estimated_duration_exceeds_brief','/scenes',estimated_seconds=timing['total_seconds'],
                  maximum_seconds=maximum_seconds,policy=timing['policy'])
    return {'seconds':seconds,'issues':findings,'semantic_acceptance':False}


def validate(value, source, packet, design, maximum_seconds):
    report=diagnose(value,source,packet,design,maximum_seconds)
    if report['issues']:
        raise ValueError('; '.join(x['code']+' at '+x['path'] for x in report['issues']))
    seconds=report['seconds']
    return {'seconds':seconds,'status':'structure_only_not_content_acceptance'}
