"""Opt-in editorial constraints, not universal measures of story quality."""
from . import contracts as c

REACTIONS={'look_at','smile_at','nod_to','clench_fists'}


def validate_pacing(scene,policy):
    if not policy:return {'status':'not_requested'}
    errors=[]
    maximum=policy.get('max_scene_seconds')
    if maximum is not None and scene['beats'][-1]['end']>maximum:
        errors.append(c.Issue('timing','/beats','scene_duration_above_brief',str(maximum)))
    limit=policy.get('max_silent_reaction_seconds')
    for b in scene['beats']:
        only_reaction=not any(b.get(k) for k in ('moves','transfers','unpacks','packs','transforms')) and all(g['verb'] in REACTIONS for g in b.get('gestures',[]))
        if limit is not None and only_reaction and not b.get('audio') and b['end']-b['start']>limit:
            errors.append(c.Issue('timing','/beats/'+b['id'],'silent_reaction_exceeds_brief',str(limit)))
    if errors:raise c.ContractError(errors)
    return {'status':'configured_checks_passed','scope':'duration and silent reaction beats only; semantic density requires review'}
