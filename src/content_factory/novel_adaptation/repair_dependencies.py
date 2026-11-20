"""Expand an explicit repair to dependent shot fields, without rewriting prose."""
from copy import deepcopy


def expand_transform_shots(scene,scope,design):
    result=deepcopy(scope);recipes={r['id']:r for r in design.get('recipes',[])}
    rows={b['id']:b for b in scene['beats']};outputs=set();changes=[]
    for key,permission in result['records'].items():
        if 'audio' in permission.get('fields',[]) and 'blocking' not in permission['fields'] and any(a.get('phase')=='after_audio' for a in rows[key]['blocking']):
            permission['fields'].append('blocking')
            changes.append({'beat_id':key,'added_field':'blocking','reason':'Replacing an audio array can remove or reorder action audio anchors.'})
    for key,permission in result['records'].items():
        if 'blocking' in permission.get('fields',[]):
            for action in rows[key]['blocking']:
                if action['kind']=='transform':outputs.update(recipes[action['recipe']]['outputs'])
    for key,permission in result['records'].items():
        affected=sorted(set(rows[key]['shot']['subjects'])&outputs)
        if 'blocking' in permission.get('fields',[]) and affected and 'shot' not in permission['fields']:
            permission['fields'].append('shot')
            changes.append({'beat_id':key,'added_field':'shot','affected_outputs':affected,
                            'reason':'Transform timing repair can change whether these planned outputs are visible.'})
    return result,changes
