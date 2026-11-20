"""Scoped plan revision: preserve registered assets, world facts and opening state."""
from copy import deepcopy
from . import contracts as c,scenes as sc


def schema(design,packet):
    base=sc.plan_schema([e['id'] for e in packet['entities']],[f['id'] for f in packet['facts']])
    return c.obj(scenes=base['properties']['scenes'],new_places=c.array(base['properties']['places']['items']),
        new_props=c.array(base['properties']['props']['items']),planned_props=c.array(c.TEXT),
        container_actions={'type':'boolean'},recipes=base['properties']['recipes'])


def apply(design,proposal,packet,source,expected_sha):
    if c.digest(design)!=expected_sha:raise ValueError('design_changed')
    errors=c.schema_issues(proposal,schema(design,packet),'design_patch')
    if errors:raise c.ContractError(errors)
    result=deepcopy(design)
    for field,new in [('places','new_places'),('props','new_props')]:
        ids=[r['id'] for r in proposal[new]]
        if len(ids)!=len(set(ids)) or set(ids)&{r['id'] for r in design[field]}:
            raise ValueError('asset_redefinition:'+field)
        result[field]+=deepcopy(proposal[new])
    for field in ('scenes','planned_props','container_actions','recipes'):
        result[field]=deepcopy(proposal[field])
    places={r['id'] for r in result['places']}
    ids=[r['id'] for r in result['scenes']]
    if len(ids)!=len(set(ids)) or any(r['place'] not in places for r in result['scenes']):
        raise ValueError('invalid_scene_registry')
    prop_ids={r['id'] for r in result['props']};missing=[]
    for prop in result['planned_props']:
        if prop not in prop_ids:missing.append('planned_props:'+prop)
    for recipe in result['recipes']:
        if not set(recipe['source_ids'])<=c.catalog(source).keys():raise ValueError('recipe_source_unknown')
        for field in ('inputs','outputs','retained_inputs'):
            missing.extend(recipe['id']+'.'+field+':'+p for p in recipe[field] if p not in prop_ids)
    if missing:raise ValueError('unregistered_design_props:'+','.join(missing))
    sc.initial_state(result,{'entities':packet['entities']})
    return result
