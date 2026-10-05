"""Encode unchanged comparative source requirements in the request Schema."""
from copy import deepcopy
import re
from scripts import creative_review_wire_v12 as base
from scripts import creative_joint_source_binding_v12 as joint
from src.content_factory.creative_review_v6 import comparison_requirements
VERSION='creative_review_wire/v16'
CHECKS=['requirements','timing','continuity','dialogue_timing','first_frame','assets']

def relation_schema(ctx):
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

def scalar_leaves(ctx):
    leaves={}
    def walk(v,p=''):
        if isinstance(v,dict):
            for k,x in v.items():walk(x,(p+'.' if p else '')+k)
        elif isinstance(v,list):
            for i,x in enumerate(v):walk(x,p+'.'+str(i))
        elif isinstance(v,(str,int,float)) and not isinstance(v,bool) and str(v).strip():leaves[p]=str(v)
    walk(ctx);return leaves

def schema(ctx):
    result=deepcopy(relation_schema(ctx));paths=sorted(scalar_leaves(ctx))
    result['$defs']={'EvidencePair':{'type':'array','minItems':2,'maxItems':2,'prefixItems':[{'type':'string','enum':paths},{'type':'string','minLength':1}],'items':False}}
    for row in result['properties']['coverage']['prefixItems']:
        for check in row['prefixItems'][1:]:check['prefixItems'][2]['items']={'$ref':'#/$defs/EvidencePair'}
    result['properties']['issues']['items']['properties']['evidence_refs']['items']={'$ref':'#/$defs/EvidencePair'}
    return result


def conclusions(value):
    out=deepcopy(value)
    for issue in out['issues']:issue['evidence_refs']=[]
    for row in out['coverage']:
        for check in row[1:]:check[2]=[]
    return out

def validate_repair_preserves_conclusions(original,corrected):
    if conclusions(original)!=conclusions(corrected):raise ValueError('complete review evidence repair changed conclusions')

def diagnostics(value,ctx):
    leaves=scalar_leaves(ctx);bad=[]
    refs=[('issues',q['evidence_refs']) for q in value['issues']]+[(f'coverage.{i}.{j}',c[2]) for i,row in enumerate(value['coverage']) for j,c in enumerate(row[1:])]
    for loc,rs in refs:
        for path,quote in rs:
            if path not in leaves or quote not in leaves[path]:bad.append({'location':loc,'path':path,'quote':quote,'cause':'path is not a scalar leaf or quote is not verbatim'})
    return bad

