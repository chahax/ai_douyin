"""Bind reviewed boundary references without rewriting native performance prose."""
from copy import deepcopy
from . import contracts as c


def apply(design,scenes,proposal,scope):
    if scope['design_sha256']!=c.digest(design) or scope['scenes_sha256']!=c.digest(scenes):raise ValueError('fixture_scope_stale')
    if proposal['verdict']!='supported':raise ValueError('fixture_reference_uncertain')
    fixture=proposal['fixture']
    if fixture['id']!=scope['fixture_id'] or fixture['id'] in {p['id'] for p in design['props']}:raise ValueError('fixture_identity')
    if fixture['stationary'] is not True or set(fixture['visible_from'])!=set(scope['visible_from']):raise ValueError('fixture_visibility_scope')
    if set(proposal['reference_ids'])!=set(scope['references']) or len(proposal['reference_ids'])!=len(scope['references']):
        raise ValueError('fixture_reference_coverage')
    updated=deepcopy(design);updated['props'].append(deepcopy(fixture))
    result=deepcopy(scenes)
    for key in proposal['reference_ids']:
        ref=scope['references'][key]
        beat=next(b for b in result[ref['scene_id']]['beats'] if b['id']==ref['beat_id'])
        if ref['field']=='blocking':
            event=beat['blocking'][ref['index']]
            if event.get('kind')!='gesture' or event.get('target')!=ref['before']:raise ValueError('fixture_reference_changed')
            event['target']=fixture['id']
        elif ref['field']=='shot':
            if beat['shot']['subjects'][ref['index']]!=ref['before']:raise ValueError('fixture_reference_changed')
            beat['shot']['subjects'][ref['index']]=fixture['id']
        else:raise ValueError('fixture_reference_field')
    return updated,result
