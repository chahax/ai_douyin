from pathlib import Path
from copy import deepcopy
import json
import pytest
from jsonschema import Draft202012Validator
from scripts import creative_review_wire_v13 as wire
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/resume_20261005_v12'

def case():
    r=json.loads((RUN/'call_155_full_review_s6_d6_view12_r1.json').read_text(encoding='utf-8'))
    return r['output'],json.loads(r['request']['messages'][1]['content'])

def test_real_missing_comparisons_rejected_before_semantic_validation():
    bad,ctx=case()
    with pytest.raises(Exception):Draft202012Validator(wire.schema(ctx)).validate(bad)

def test_all_existing_source_relations_encoded_without_changing_conclusions():
    bad,ctx=case();schema=wire.schema(ctx)
    leaves={}
    def walk(v,p=''):
        if isinstance(v,dict):
            for k,x in v.items():walk(x,(p+'.' if p else '')+k)
        elif isinstance(v,list):
            for i,x in enumerate(v):walk(x,p+'.'+str(i))
        elif isinstance(v,(str,int,float)) and not isinstance(v,bool) and str(v).strip():leaves[p]=str(v)
    walk(ctx)
    fixture=deepcopy(bad)
    for i,row in enumerate(fixture['coverage']):
        for j,check in enumerate(row[1:]):
            rules=schema['properties']['coverage']['prefixItems'][i]['prefixItems'][j+1]['prefixItems'][2].get('allOf',[])
            for rule in rules:
                target=rule['contains']['prefixItems'][0]
                path=next(p for p in leaves if Draft202012Validator(target).is_valid(p))
                if not any(ref[0]==path for ref in check[2]):check[2].append([path,leaves[path]])
    # Schema-only diagnostic fixture stays in memory, never an adopted review.
    Draft202012Validator(schema).validate(fixture)
    fixture['coverage'][1][3][2]=[r for r in fixture['coverage'][1][3][2] if not r[0].startswith('state_plan.')]
    with pytest.raises(Exception):Draft202012Validator(schema).validate(fixture)
