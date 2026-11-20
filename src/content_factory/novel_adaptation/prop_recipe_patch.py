"""Partition one recipe and replace one affected event row, never the screenplay."""
from collections import Counter
from copy import deepcopy
from . import contracts as c,narrative_props


def context(plan, recipe_id):
    rows=[(i,r) for i,r in enumerate(plan['recipes']) if r['id']==recipe_id]
    if len(rows)!=1:raise ValueError('recipe_patch_target')
    i,original=rows[0]
    if set(original)-{'id','kind','action','inputs','outputs','retained_inputs','source_ids'}:
        raise ValueError('recipe_partition_requires_preserving_extra_constraints')
    if original.get('kind','transformation')!='transformation' or len(original['inputs'])<2:
        raise ValueError('recipe_not_splittable')
    ids=[f'{recipe_id}__part{n+1}' for n in range(len(original['inputs']))]
    if set(ids)&{r['id'] for r in plan['recipes']}:raise ValueError('recipe_part_id_collision')
    return i,original,ids


def schema(candidate, plan, entities, recipe_id, segment_id):
    i,original,ids=context(plan,recipe_id)
    temporary=deepcopy(plan)
    temporary['recipes'][i:i+1]=[{**deepcopy(original),'id':id} for id in ids]
    event_schema=narrative_props.body_schema(candidate,temporary,entities)
    row=deepcopy(event_schema['properties']['segments']['items'])
    row['properties']['id']=c.choices([segment_id])
    recipe=c.obj(id=c.choices(ids),kind=c.choices(['transformation']),action=c.TEXT,
        inputs=c.refs(original['inputs']),outputs=c.refs(original['outputs']),
        retained_inputs=c.refs(original['retained_inputs'],0),source_ids=c.refs(original['source_ids']))
    result=c.obj(recipes=c.array(recipe,len(ids)),segment=row)
    result['properties']['recipes']['maxItems']=len(ids)
    result['$defs']=event_schema['$defs']
    return result


def apply(candidate, plan, projection, proposal, people, recipe_id, segment_id, request_identity):
    if request_identity!={'candidate_sha256':c.digest(candidate),'plan_sha256':c.digest(plan),
                         'projection_sha256':c.digest(projection)}:raise ValueError('recipe_patch_input_changed')
    if projection['candidate_sha256']!=c.digest(candidate) or projection['plan_sha256']!=c.digest(plan):
        raise ValueError('recipe_patch_projection_binding')
    entities={'entities':[{'id':p,'kind':'character'} for p in people]}
    errors=c.schema_issues(proposal,schema(candidate,plan,entities,recipe_id,segment_id),'recipe_patch')
    if errors:raise c.ContractError(errors)
    i,original,ids=context(plan,recipe_id);parts=proposal['recipes']
    if {r['id'] for r in parts}!=set(ids):raise ValueError('recipe_part_identity_coverage')
    for key in ('inputs','outputs','retained_inputs'):
        if Counter(v for r in parts for v in r[key])!=Counter(original[key]):
            raise ValueError('recipe_partition_'+key)
    for r in parts:
        if not set(r['retained_inputs'])<=set(r['inputs']):raise ValueError('recipe_partition_retained_scope')
    indices=[i for i,r in enumerate(projection['segments']) if r['id']==segment_id]
    if len(indices)!=1:raise ValueError('recipe_patch_segment_target')
    for row in projection['segments']:
        if row['id']!=segment_id and any(e['kind']=='transforms' and e['event']['recipe']==recipe_id for e in row['events']):
            raise ValueError('recipe_dependency_outside_patch_scope')
    new_plan=deepcopy(plan);new_plan['recipes'][i:i+1]=deepcopy(parts)
    body={k:deepcopy(v) for k,v in projection.items() if k not in ('candidate_sha256','plan_sha256')}
    body['segments'][indices[0]]=deepcopy(proposal['segment'])
    bound=narrative_props.bind_body(candidate,new_plan,body,
        {'candidate_sha256':c.digest(candidate),'plan_sha256':c.digest(new_plan)},entities)
    return new_plan,bound
