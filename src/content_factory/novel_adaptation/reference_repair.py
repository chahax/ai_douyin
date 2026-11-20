"""Correct invalid access references without rewriting story or dropping claims."""
from copy import deepcopy
from . import contracts as c


def invalid_references(scene,previous):
    result=[]
    for beat in scene['beats']:
        for index,ref in enumerate(beat.get('requires_information',[])):
            history=previous.get('information',{}).get(ref['person'],[])
            if ref['event_id'] not in {e['id'] for e in history}:
                result.append({'beat_id':beat['id'],'index':index,'person':ref['person'],
                    'old_event_id':ref['event_id'],'available_history':deepcopy(history)})
    return result


def repair_schema(scope):
    variants=[]
    for row in scope:
        ids=[e['id'] for e in row['available_history']]
        if ids:variants.append(c.obj(beat_id=c.choices([row['beat_id']]),index={'type':'integer','const':row['index']},
            event_id=c.choices(ids),reason=c.TEXT))
    corrections=c.array({'oneOf':variants}) if variants else {'type':'array','maxItems':0,'items':False}
    return c.obj(verdict=c.choices(['corrected','uncertain']),corrections=corrections)


def apply_reference_repair(scene,previous,proposal,expected_sha):
    if c.digest(scene)!=expected_sha:raise ValueError('stale_reference_candidate')
    scope=invalid_references(scene,previous)
    issues=c.schema_issues(proposal,repair_schema(scope),'reference_repair')
    if issues:raise c.ContractError(issues)
    if proposal['verdict']!='corrected':raise ValueError('reference_meaning_uncertain')
    expected={(r['beat_id'],r['index']) for r in scope}
    actual=[(r['beat_id'],r['index']) for r in proposal['corrections']]
    if len(set(actual))!=len(actual) or set(actual)!=expected:raise ValueError('reference_scope_coverage')
    out=deepcopy(scene);beats={b['id']:b for b in out['beats']}
    for row in proposal['corrections']:
        beats[row['beat_id']]['requires_information'][row['index']]['event_id']=row['event_id']
    return out


def checkpoint(scene,source,design,previous):
    return {'scene':deepcopy(scene),'scene_sha256':c.digest(scene),'source_sha256':c.digest(source),
        'design_sha256':c.digest(design),'previous_sha256':c.digest(previous)}


def adopt_checkpoint(value,source,design,previous):
    for key,expected in [('scene_sha256',c.digest(value['scene'])),('source_sha256',c.digest(source)),
                         ('design_sha256',c.digest(design)),('previous_sha256',c.digest(previous))]:
        if value.get(key)!=expected:raise ValueError('stale_native_checkpoint:'+key)
    return deepcopy(value['scene'])
