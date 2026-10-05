from copy import deepcopy
import json,pytest
from jsonschema import Draft202012Validator
from scripts import run_creative_s7_review_evidence_repair_v45 as r

@pytest.fixture(scope="module")
def current():
    ctx,compiled=r.previous.reviewed_final_context(1)
    raw=r.control.read(next(r.previous.ROOT.glob('call_264_*.json')))['output']
    return ctx,raw

def test_compact_wire_shape_accepts_real_complete_reply_but_business_rejects_missing_refs(current):
    ctx,raw=current;wire=r.transport_schema(ctx);Draft202012Validator.check_schema(wire)
    Draft202012Validator(wire).validate(raw)
    with pytest.raises(Exception):Draft202012Validator(r.ids.schema(ctx)).validate(raw)
    assert len(json.dumps(wire))<len(json.dumps(r.ids.schema(ctx)))

def test_conclusion_change_rejected(current):
    ctx,raw=current;changed=deepcopy(raw);changed['coverage'][0][1][1]+=' changed'
    with pytest.raises(ValueError):r.ids.validate_repair_preserves_conclusions(raw,changed)

def test_evidence_only_change_preserves_all_conclusions(current):
    ctx,raw=current;changed=deepcopy(raw);changed['coverage'][0][-1][2].append(next(k for k,v in r.ids.catalog(ctx).items() if v['path']=='shots.shots.0.composition'))
    r.ids.validate_repair_preserves_conclusions(raw,changed)
