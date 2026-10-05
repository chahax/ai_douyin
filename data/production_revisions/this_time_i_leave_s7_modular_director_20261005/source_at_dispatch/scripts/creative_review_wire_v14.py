"""Scalar-only source references and complete review evidence-repair comparison."""
from copy import deepcopy
from scripts import creative_review_wire_v13 as base
VERSION='creative_review_wire/v14'

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
    result=deepcopy(base.schema(ctx));paths=sorted(scalar_leaves(ctx))
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

def format_addendum(ctx):return base.format_addendum(ctx)
