from copy import deepcopy
import pytest
from jsonschema import Draft202012Validator
from scripts import run_creative_s7_review_timing_binding_v42 as r
from scripts import creative_review_id_transport_v17 as ids

@pytest.fixture(scope="module")
def ctx():return r.reviewed_final_context(1)[0]

def test_full_real_ten_shot_schema_preflight(ctx):
    value=ids.schema(ctx);Draft202012Validator.check_schema(value)
    assert len(value["properties"]["coverage"]["prefixItems"])==10
    assert value["properties"]["schema"]["const"]==ids.VERSION

def test_changed_original_still_rejected_at_schema(ctx):
    bad=deepcopy(ctx);bad["raw_linear_script"]["title"]+=" changed"
    with pytest.raises(r.joint.JointSourceBindingError):ids.schema(bad)

def test_evidence_expansion_is_exact_original_leaf(ctx):
    directory=ids.catalog(ctx);key=next(k for k,v in directory.items() if v["path"]=="raw_linear_script.beats.4.steps.1.text")
    raw={"schema":ids.VERSION,"issues":[],"coverage":[["SH05",["pass","original conclusion",[key],[]]]]}
    expanded=ids.expand(raw,ctx)
    assert expanded["coverage"][0][1]==["pass","original conclusion",[[directory[key]["path"],"这次我先走。"]],[]]
    assert raw["coverage"][0][1][2]==[key]

def test_unknown_evidence_id_rejected(ctx):
    with pytest.raises(ValueError):ids.expand({"schema":ids.VERSION,"issues":[],"coverage":[["SH05",["pass","reason",["unknown"],[]]]]},ctx)
