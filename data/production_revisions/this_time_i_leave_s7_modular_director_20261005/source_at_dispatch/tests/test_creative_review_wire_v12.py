from pathlib import Path
from copy import deepcopy
import json
import pytest
from jsonschema import Draft202012Validator
from scripts import creative_review_wire_v12 as wire
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/resume_20261005_v11'

def case():
    r=json.loads((RUN/'call_154_full_review_s6_d6_view11_r1.json').read_text(encoding='utf-8'))
    return r['output'],json.loads(r['request']['messages'][1]['content'])

def test_real_numeric_quote_fault_rejected_by_transmitted_schema():
    bad,ctx=case()
    with pytest.raises(Exception):Draft202012Validator(wire.schema(ctx)).validate(bad)
    # Diagnostic schema-only fixture, never an adopted or saved model review.
    valid=deepcopy(bad)
    for row in valid['coverage']:
        for check in row[1:]:
            for pair in check[2]:pair[1]=str(pair[1])
    Draft202012Validator(wire.schema(ctx)).validate(valid)
    again=deepcopy(valid);again['coverage'][0][2][2][0][1]=''
    with pytest.raises(Exception):Draft202012Validator(wire.schema(ctx)).validate(again)

def test_row_order_cardinality_and_suggestion_extras_rejected():
    bad,ctx=case();schema=wire.schema(ctx)
    for row in bad['coverage']:
        for check in row[1:]:
            for pair in check[2]:pair[1]=str(pair[1])
    for kind in ['order','missing','suggestion']:
        x=deepcopy(bad)
        if kind=='order':x['coverage'][0],x['coverage'][1]=x['coverage'][1],x['coverage'][0]
        elif kind=='missing':x['coverage'][0].pop()
        else:x['suggestions'][0]['evidence_refs']=[]
        with pytest.raises(Exception):Draft202012Validator(schema).validate(x)
