"""Read-only complete direction diagnostics; never patch model documents or dispatch."""
from collections import Counter
from jsonschema import Draft202012Validator
from scripts.step_index_physical_adapter_v5 import _shots, _raw_sources, _component_members
from scripts.creative_surface_state_v1 import parse_surface_location, support_surface_ids

def inspect_direction(document, context, schema):
    faults=[{'code':'SCHEMA_INVALID','path':'.'.join(map(str,e.absolute_path)), 'message':e.message}
            for e in Draft202012Validator(schema).iter_errors(document)]
    raw=context['raw_linear_script'];sources=_raw_sources(context);rank={ref:i for i,ref in enumerate(sources)}
    shots=[]
    for bi,beat in enumerate(document.get('beats',[])):
        if not isinstance(beat,dict):continue
        shots.extend(beat.get('shots',[]))
        if bi>=len(raw['beats']):continue
        expected=[f'raw_linear_script.beats.{bi}.steps.{si}' for si in range(len(raw['beats'][bi]['steps']))]
        actual=[ref for shot in beat.get('shots',[]) for ref in shot.get('source_step_refs',[])]
        if actual!=expected:faults.append({'code':'SOURCE_COVERAGE','path':f'beats.{bi}.shots','expected':expected,'actual':actual})
    ids=Counter(s.get('shot_id') for s in shots)
    for key,n in ids.items():
        if n>1:faults.append({'code':'DUPLICATE_SHOT_ID','path':str(key)})
    owners={ref:s.get('shot_id') for s in shots for ref in s.get('source_step_refs',[])}
    requirements=[]
    for shot in shots:
        for req in shot.get('performance_requirements',[]):
            if not isinstance(req,dict):continue
            requirements.append(req);stim=req.get('stimulus_ref');reaction=req.get('reaction_ref');rel=req.get('relation')
            path=req.get('id','performance_requirements')
            if stim not in sources or reaction not in sources:continue
            if reaction not in shot.get('source_step_refs',[]):faults.append({'code':'REACTION_NOT_CURRENT_SHOT','path':path})
            if owners.get(stim)!=shot.get('shot_id') and rel!='after':faults.append({'code':'CROSS_SHOT_NOT_AFTER','path':path})
            if rel=='during' and (sources[stim]['kind']!='dialogue' or reaction!=stim):faults.append({'code':'DURING_NOT_SAME_DIALOGUE','path':path})
            if rel in ('before','after'):
                valid=rank[reaction]<rank[stim] if rel=='before' else rank[reaction]>rank[stim]
                if not valid:faults.append({'code':'SOURCE_WINDOW_ORDER_IMPOSSIBLE','path':path,'stimulus':stim,'reaction':reaction,'relation':rel})
    for key,n in Counter(q.get('id') for q in requirements).items():
        if n>1:faults.append({'code':'DUPLICATE_REQUIREMENT_ID','path':str(key)})
    surfaces=support_surface_ids(context['static_visual_manifest'])
    for member in _component_members(context):
        state=document.get('initial_state',{}).get(member,{})
        if state.get('holder')=='none':
            try:parse_surface_location(state.get('location'),surfaces,'initial_state.'+member+'.location')
            except Exception as exc:faults.append({'code':'COMPONENT_SURFACE_INVALID','path':'initial_state.'+member+'.location','message':str(exc)})
    return {'schema':'complete_direction_readonly_diagnostics/v1','faults':faults,'fault_count':len(faults),
            'document_modified':False,'model_calls':0,'mechanical_only':True,'semantic_approval':False}
