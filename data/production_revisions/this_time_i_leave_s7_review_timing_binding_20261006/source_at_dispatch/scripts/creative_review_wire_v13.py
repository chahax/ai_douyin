"""Encode unchanged comparative source requirements in the request Schema."""
from copy import deepcopy
import re
from scripts import creative_review_wire_v12 as base
from scripts import creative_joint_source_binding_v11 as joint
from src.content_factory.creative_review_v6 import comparison_requirements
VERSION='creative_review_wire/v13'
CHECKS=['requirements','timing','continuity','dialogue_timing','first_frame','assets']

def schema(ctx):
    result=deepcopy(base.schema(ctx));proof=joint.preflight(ctx);legacy=comparison_requirements(ctx)
    def contains(path):
        return {'contains':{'type':'array','prefixItems':[path,{'type':'string','minLength':1}],'minItems':2,'maxItems':2,'items':False}}
    for i,m in enumerate(proof['mapping']):
        row=result['properties']['coverage']['prefixItems'][i]
        for j,name in enumerate(CHECKS):
            check=row['prefixItems'][j+1];refs=check['prefixItems'][2]
            required=list(legacy[m['storyboard_id']].get(name,[]))
            active=name!='dialogue_timing' or bool(m['dialogue_text_leaves'])
            if active:required.append(f'shots.shots.{i}.')
            if name=='continuity' and i:required.append(f'shots.shots.{i-1}.')
            rules=[contains({'type':'string','pattern':'^'+re.escape(p)}) for p in dict.fromkeys(required)]
            sets=[]
            if name=='timing':sets=[m['timing_source_leaves'],m['execution_timing_leaves']]
            if name=='dialogue_timing' and active:sets=[m['dialogue_text_leaves'],m['dialogue_window_leaves']]
            if name=='continuity':sets=[[p] for p in m['continuity_source_leaves']]
            rules.extend(contains({'enum':paths}) for paths in sets)
            if rules:refs['allOf']=rules
            if name=='dialogue_timing' and not active:
                check['prefixItems'][0]={'const':'not_applicable'};refs['maxItems']=0
    return result

def format_addendum(ctx):return base.format_addendum(ctx)
