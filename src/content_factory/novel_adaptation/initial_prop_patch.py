"""Narrow initial-owner repair, retaining known event extraction byte-for-byte."""
from copy import deepcopy
from . import contracts as c,narrative_patch,narrative_props


def owner_paths(plan, prop_ids):
    ids=[p['id'] for p in plan['props']]
    if len(ids)!=len(set(ids)) or len(prop_ids)!=len(set(prop_ids)) or not set(prop_ids)<=set(ids):
        raise ValueError('initial_owner_scope')
    return [f'/props/{ids.index(p)}/owner' for p in prop_ids]


def schema(plan, prop_ids, owners):
    return c.obj(replacements=c.array({'oneOf':[
        c.obj(path=c.choices([path]),value=c.choices(owners)) for path in owner_paths(plan,prop_ids)]},len(prop_ids)))


def apply(plan, body, prop_ids, owners, requested_plan_sha256):
    if c.digest(plan)!=requested_plan_sha256:raise ValueError('initial_plan_changed')
    errors=c.schema_issues(body,schema(plan,prop_ids,owners),'initial_owner_patch')
    if errors:raise c.ContractError(errors)
    return narrative_patch.apply(plan,{'candidate_sha256':requested_plan_sha256,**body},
                                  owner_paths(plan,prop_ids),requested_plan_sha256)


def reuse_events(candidate, old_plan, new_plan, projection, prop_ids, people):
    if projection['candidate_sha256']!=c.digest(candidate) or projection['plan_sha256']!=c.digest(old_plan):
        raise ValueError('event_origin_binding_mismatch')
    expected=deepcopy(old_plan)
    for path in owner_paths(old_plan,prop_ids):
        index=int(path.split('/')[2]);expected['props'][index]['owner']=new_plan['props'][index]['owner']
    if expected!=new_plan:raise ValueError('event_reuse_exceeds_initial_owner_scope')
    body={key:deepcopy(value) for key,value in projection.items() if key not in ('candidate_sha256','plan_sha256')}
    return narrative_props.bind_body(candidate,new_plan,body,
        {'candidate_sha256':c.digest(candidate),'plan_sha256':c.digest(new_plan)},
        {'entities':[{'id':p,'kind':'character'} for p in people]})
