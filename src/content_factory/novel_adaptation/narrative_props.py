"""Bind critical-prop events to narrative evidence and the shared interpreter.

This is a projection contract, not a semantic extractor or approval of its evidence.
Ordinary set dressing need not be registered as a tracked story prop.
"""
from copy import deepcopy
from . import contracts as c
from .scenes import initial_state, scene_schema
from .presence_evidence import catalog as performance_catalog

FIELDS = ('transfers', 'prop_uses', 'gestures', 'unpacks', 'packs', 'transforms')


def catalog(candidate):
    result=performance_catalog(candidate)
    for scene in candidate['scenes']:
        first=scene['segments'][0]['id'];text=scene['entry_continuity']
        result[f'{first}:entry_continuity:0']={'segment_id':first,'field':'entry_continuity',
            'index':0,'text':text,'text_sha256':c.digest(text)}
    return result


def audit_event_structure(presence, projection):
    """Report global replay invariants without inventing state after a failure."""
    movement={row['id']:row['moves'] for row in presence['segments']}
    recipes={};issues=[]
    for segment in projection['segments']:
        grouped={field:[] for field in FIELDS}
        for event in segment['events']:grouped[event['kind']].append(event['event'])
        expected={('moves',i) for i in range(len(movement[segment['id']]))}
        expected|={(field,i) for field,rows in grouped.items() for i in range(len(rows))}
        order=[(r['field'],r['index']) for r in segment['action_order']]
        if len(order)!=len(set(order)) or set(order)!=expected:
            issues.append({'code':'action_order_coverage','segment_id':segment['id']})
        for index,row in enumerate(grouped['transforms']):
            recipes.setdefault(row['recipe'],[]).append({'segment_id':segment['id'],'transform_index':index,
                                                        'actor':row['actor']})
    for recipe,uses in recipes.items():
        if len(uses)>1:issues.append({'code':'recipe_applied_multiple_times','recipe':recipe,'uses':uses})
    return {'issues':issues,'scope':'Static order coverage and globally single-use recipe IDs only.',
            'semantic_acceptance':False}


def body_schema(candidate, plan, entities):
    result=schema(candidate,plan,entities)
    for field in ('candidate_sha256','plan_sha256'):
        result['required'].remove(field)
        del result['properties'][field]
    return result


def bind_body(candidate, plan, body, request_identity, entities):
    identity={'candidate_sha256':c.digest(candidate),'plan_sha256':c.digest(plan)}
    if identity!=request_identity:raise ValueError('prop_request_inputs_changed')
    errors=c.schema_issues(body,body_schema(candidate,plan,entities),'prop_body')
    if errors:raise c.ContractError(errors)
    return {**identity,**deepcopy(body)}


def schema(candidate, plan, entities):
    beat = scene_schema(plan, entities, [], {'chapters': []})['properties']['beats']['items']
    events = []
    for field in FIELDS:
        spec = beat['properties'][field]
        if spec.get('maxItems') == 0:
            continue
        events.append(c.obj(kind=c.choices([field]), event=deepcopy(spec['items']),
                            evidence_ids={'$ref':'#/$defs/evidence_ids'}))
    segment_ids = [b['id'] for s in candidate['scenes'] for b in s['segments']]
    result=c.obj(candidate_sha256=c.choices([c.digest(candidate)]),
                 plan_sha256=c.choices([c.digest(plan)]),
                 segments=c.array(c.obj(id=c.choices(segment_ids),
                     events=c.array({'oneOf': events}),
                     action_order=deepcopy(beat['properties']['action_order'])), len(segment_ids)),
                 uncertainties=c.array(c.TEXT))
    result['$defs']={'evidence_ids':c.refs(catalog(candidate))}
    return result


def prepare(candidate, presence, plan, projection, people, places):
    entities = {'entities': [{'id': p, 'kind': 'character'} for p in people]}
    errors = c.schema_issues(projection, schema(candidate, plan, entities), 'prop_projection')
    if errors:
        raise c.ContractError(errors)
    if set(p['id'] for p in plan['places']) != set(places):
        raise ValueError('prop_plan_places_mismatch')
    state = initial_state(plan, entities)
    if state['locations'] != presence['initial_locations']:
        raise ValueError('prop_plan_initial_locations_mismatch')
    expected = [b['id'] for s in candidate['scenes'] for b in s['segments']]
    if [r['id'] for r in projection['segments']] != expected:
        raise ValueError('prop_projection_segment_coverage')
    evidence = catalog(candidate)
    rows = {}; receipts = []
    for row in projection['segments']:
        actions = {field: [] for field in FIELDS}
        for selection in row['events']:
            refs = [evidence[key] for key in selection['evidence_ids']]
            if any(ref['segment_id'] != row['id'] for ref in refs):
                raise ValueError('prop_evidence_wrong_segment')
            # Camera framing alone cannot authorize a transfer or transformation.
            posture=selection['event'].get('posture_change',{})
            entry_establishment=(selection['kind']=='gestures' and posture.get('before')=='unknown'
                and selection['event'].get('phase','start')=='start'
                and any(ref['field']=='entry_continuity' for ref in refs))
            if not entry_establishment and not any(ref['field'] in ('action', 'continuity_obligations') for ref in refs):
                raise ValueError('prop_event_requires_action_evidence')
            actions[selection['kind']].append(deepcopy(selection['event']))
            receipts.append({'segment_id': row['id'], 'selection': deepcopy(selection),
                             'resolved_evidence': deepcopy(refs)})
        actions['action_order'] = deepcopy(row['action_order'])
        rows[row['id']] = actions
    return state, rows, receipts
