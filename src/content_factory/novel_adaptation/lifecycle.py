"""Mechanical object existence and explicit container/material transitions.

Recipes are authored design data, not automatic proof of source truth or physics.
"""
from copy import deepcopy
from .containers import descendants


def exists(state,prop):
    parents=state.get('containers',{});seen=set()
    while True:
        if prop in seen:return False
        seen.add(prop)
        if state.get('prop_status',{}).get(prop,'present')!='present':return False
        if prop not in parents:return True
        prop=parents[prop]


def initialize(plan,state):
    planned=set(plan.get('planned_props',[]));ids=set(state['props'])
    if not planned<=ids:raise ValueError('planned_prop_unknown')
    statuses={p:('planned' if p in planned else 'present') for p in ids}
    overrides=plan.get('initial_prop_status',{})
    if not set(overrides)<=ids or not set(overrides.values())<={'planned','present','consumed'}:raise ValueError('invalid_prop_status')
    statuses.update(overrides)
    recipes={}
    for r in plan.get('recipes',[]):
        if r['id'] in recipes:raise ValueError('duplicate_recipe')
        ins,outs,ret=set(r['inputs']),set(r['outputs']),set(r['retained_inputs'])
        consumption=r.get('kind')=='consumption'
        if consumption and (not plan.get('allow_consumption_recipes') or outs or ret):
            raise ValueError('invalid_consumption_recipe')
        if r.get('kind','transformation') not in ('transformation','consumption'):
            raise ValueError('unknown_recipe_kind')
        if not ins or (not outs and not consumption) or not (ins|outs)<=ids or ins&outs or not ret<=ins:
            raise ValueError('invalid_recipe_scope')
        if len(ins)!=len(r['inputs']) or len(outs)!=len(r['outputs']):raise ValueError('duplicate_recipe_prop')
        if not r['source_ids']:raise ValueError('recipe_source_required')
        vessels=r.get('input_containers',{})
        if not isinstance(vessels,dict) or not set(vessels)<=ins or not set(vessels.values())<=ids:
            raise ValueError('invalid_recipe_input_containers')
        if any(p==v for p,v in vessels.items()) or set(vessels.values())&(outs|(ins-ret)):
            raise ValueError('recipe_vessel_consumed_or_output')
        destinations=r.get('output_containers',{})
        if not isinstance(destinations,dict) or not set(destinations)<=outs or not set(destinations.values())<=ids:
            raise ValueError('invalid_recipe_output_containers')
        if set(destinations.values())&(outs|(ins-ret)):
            raise ValueError('recipe_output_vessel_consumed_or_output')
        recipes[r['id']]=deepcopy(r)
    completed=plan.get('recipes_completed',[])
    if len(completed)!=len(set(completed)) or not set(completed)<=recipes.keys():raise ValueError('invalid_recipe_history')
    if planned or overrides or recipes or plan.get('container_actions'):
        state['prop_status']=statuses;state['recipes']=recipes
        state['recipes_completed']=deepcopy(plan.get('recipes_completed',[]))


def apply(state,row,kind,place):
    """Validate first, then commit atomically. Raises without partial state changes."""
    out=deepcopy(state);parents=out.setdefault('containers',{})
    def local(owner):return out['locations'].get(owner)==place or owner==place
    def usable(prop):return prop in out['props'] and exists(out,prop) and local(out['props'][prop])
    if out['locations'].get(row['actor'])!=place:raise ValueError('lifecycle_actor_absent')
    if kind in ('unpack','pack'):
        prop,container=row['prop'],row['container']
        if prop in out.get('fixtures',{}):raise ValueError('stationary_fixture_relocation')
        if not usable(prop) or not usable(container):raise ValueError('container_prop_unavailable')
        if kind=='unpack':
            if parents.get(prop)!=container:raise ValueError('unpack_wrong_container')
            if not local(row['destination']):raise ValueError('unpack_remote_destination')
            del parents[prop];owner=row['destination']
        else:
            if prop in parents:raise ValueError('pack_already_contained')
            if prop==container or container in descendants(parents,prop):raise ValueError('container_cycle')
            parents[prop]=container;owner=out['props'][container]
        for p in {prop}|descendants(parents,prop):out['props'][p]=owner
    elif kind=='transform':
        participants=row.get('participants',[row['actor']])
        if (not participants or len(set(participants))!=len(participants) or row['actor'] not in participants or
            any(out['locations'].get(person)!=place for person in participants)):
            raise ValueError('transform_participants_absent_or_invalid')
        recipe=out.get('recipes',{}).get(row['recipe'])
        if recipe is None:raise ValueError('unknown_recipe')
        recipe=deepcopy(recipe)
        for field,allowed in (('input_containers',recipe['inputs']),('output_containers',recipe['outputs'])):
            supplied=row.get(field,{})
            if (not isinstance(supplied,dict) or not set(supplied)<=set(allowed) or
                not set(supplied.values())<=set(out['props'])):
                raise ValueError('event_recipe_vessel_scope')
            fixed=recipe.get(field,{})
            if any(key in fixed and fixed[key]!=value for key,value in supplied.items()):
                raise ValueError('event_recipe_vessel_conflicts_with_plan')
            recipe[field]={**fixed,**supplied}
            invalid_vessels=set(recipe['outputs'])|(set(recipe['inputs'])-set(recipe['retained_inputs']))
            if set(recipe[field].values())&invalid_vessels:
                raise ValueError('event_recipe_vessel_consumed_or_output')
        if row['recipe'] in out.get('recipes_completed',[]):raise ValueError('recipe_already_applied')
        if not local(row['destination']):raise ValueError('transform_remote_destination')
        for p in recipe['inputs']:
            if p in out.get('fixtures',{}) and p not in recipe['retained_inputs']:raise ValueError('stationary_fixture_consumption')
            vessel=recipe.get('input_containers',{}).get(p)
            if not usable(p):raise ValueError('recipe_input_unavailable_or_contained')
            if vessel is not None:
                if parents.get(p)!=vessel or not usable(vessel):raise ValueError('recipe_input_wrong_vessel')
            elif p in parents:raise ValueError('recipe_input_unavailable_or_contained')
            if p not in recipe['retained_inputs'] and descendants(parents,p):raise ValueError('consume_container_with_contents')
        for p in recipe['outputs']:
            if out.get('prop_status',{}).get(p,'present')!='planned' or p in parents:
                raise ValueError('recipe_output_not_planned')
            vessel=recipe.get('output_containers',{}).get(p)
            if vessel is not None and (not usable(vessel) or out['props'][vessel]!=row['destination']):
                raise ValueError('recipe_output_vessel_unavailable_or_owner_mismatch')
        statuses=out.setdefault('prop_status',{})
        for p in recipe['inputs']:
            if p not in recipe['retained_inputs']:
                statuses[p]='consumed';parents.pop(p,None)
        for p in recipe['outputs']:
            statuses[p]='present';out['props'][p]=row['destination']
            if p in recipe.get('output_containers',{}):parents[p]=recipe['output_containers'][p]
        out.setdefault('recipes_completed',[]).append(row['recipe'])
    else:raise ValueError('unknown_lifecycle_action')
    state.clear();state.update(out)
