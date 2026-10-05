from pathlib import Path
from copy import deepcopy
import json
import pytest
from jsonschema import Draft202012Validator
from scripts import creative_review_id_transport_v15 as wire
from scripts import creative_joint_source_binding_v11 as joint
from scripts import creative_compact_review_transport_v8 as compact
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/resume_20261005_v14'

def fixture():
    r=json.loads((RUN/'call_157_full_review_s6_d6_view14_r1.json').read_text(encoding='utf-8'))
    ctx=json.loads(r['request']['messages'][1]['content']);original=r['output'];raw=deepcopy(original);raw['schema']=wire.VERSION
    bypath={v['path']:k for k,v in wire.catalog(ctx).items()}
    for row in raw['coverage']:
        for c in row[1:]:c[2]=[bypath[p] for p,q in c[2]]
    return original,raw,ctx

def test_context_bound_ids_roundtrip_through_complete_unchanged_business_review():
    original,raw,ctx=fixture();Draft202012Validator(wire.schema(ctx)).validate(raw)
    decoded=wire.expand(raw,ctx);wire.validate_repair_preserves_conclusions(original,decoded)
    joint.validate_joint_review(compact.expand_review(decoded,ctx),ctx)
    assert original!=decoded and wire.diagnostics(decoded,ctx)==[]
    assert all(v['quote'] for v in wire.catalog(ctx).values())
    # Entire fixture is offline/in memory; not a model response or adopted review.

def test_wrong_id_changed_context_or_conclusions_cannot_be_adopted():
    original,raw,ctx=fixture();raw['coverage'][0][1][2][0]='stale-ID'
    with pytest.raises(Exception):wire.expand(raw,ctx)
    original,raw,ctx=fixture();bad=deepcopy(ctx);bad['raw_linear_script']['title']+='changed'
    with pytest.raises(Exception):wire.expand(raw,bad)
    decoded=wire.expand(raw,ctx);decoded['coverage'][0][1][1]+='changed'
    with pytest.raises(Exception):wire.validate_repair_preserves_conclusions(original,decoded)
