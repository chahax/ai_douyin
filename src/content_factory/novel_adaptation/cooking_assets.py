"""Structural validation of a source-backed asset proposal, not semantic approval."""
from copy import deepcopy
from .contracts import digest


def apply_reviewed_selection(proposal,design,source,review):
    if review.get('verdict')!='accepted_selection':raise ValueError('cooking_selection_unreviewed')
    for field,obj in [('proposal',proposal),('design',design),('source',source)]:
        if review.get(field+'_sha256')!=digest(obj):raise ValueError('cooking_selection_stale:'+field)
    selected=review['selection'];props=set(selected['new_prop_ids']);bindings={tuple(x) for x in selected['bindings']}
    subset={'new_props':[deepcopy(x) for x in proposal['new_props'] if x['id'] in props],
            'bindings':[deepcopy(x) for x in proposal['bindings'] if (x['recipe'],x['input_prop']) in bindings],
            'existing_display_names':[],'action_requirements':[]}
    if len(subset['new_props'])!=len(props) or len(subset['bindings'])!=len(bindings):raise ValueError('cooking_selection_missing_or_duplicate')
    validate_proposal(subset,design)
    out=deepcopy(design);out['action_contract_version']=2
    # Source/design annotations stay in the selected proposal; runtime props only
    # receive unchanged physical metadata from the native proposal.
    out['props'] += [{k:deepcopy(v) for k,v in x.items() if k not in ('source_ids','evidence_type')} for x in subset['new_props']]
    recipes={r['id']:r for r in out['recipes']}
    for row in subset['bindings']:
        mapping=recipes[row['recipe']].setdefault('input_containers',{})
        if row['input_prop'] in mapping:raise ValueError('cooking_binding_already_defined')
        mapping[row['input_prop']]=row['vessel']
    return out,subset


def validate_proposal(proposal,design):
    existing={p['id'] for p in design['props']}
    added=[p['id'] for p in proposal['new_props']]
    if len(added)!=len(set(added)) or set(added)&existing:raise ValueError('cooking_asset_id_collision')
    ids=existing|set(added);recipes={r['id']:r for r in design['recipes']};seen=set()
    for row in proposal['bindings']:
        key=(row['recipe'],row['input_prop'])
        if key in seen:raise ValueError('duplicate_cooking_binding')
        seen.add(key);recipe=recipes[row['recipe']]
        if row['input_prop'] not in recipe['inputs']:raise ValueError('binding_not_recipe_input')
        if row['vessel'] not in ids:raise ValueError('cooking_vessel_unknown')
        if row['vessel']==row['input_prop']:raise ValueError('cooking_self_containment')
        if row['vessel'] in set(recipe['outputs'])|(set(recipe['inputs'])-set(recipe['retained_inputs'])):
            raise ValueError('cooking_vessel_not_retained')
    names=[r['id'] for r in proposal['existing_display_names']]
    if len(names)!=len(set(names)):raise ValueError('duplicate_cooking_display_name')
    for row in proposal['action_requirements']:
        if row['target'] not in ids:raise ValueError('cooking_action_target_unknown')
        if row['instrument'] and row['instrument'] not in ids:raise ValueError('cooking_instrument_unknown')
        if row['instrument']==row['target']:raise ValueError('cooking_instrument_is_target')
