from copy import deepcopy
import pytest
from scripts import run_creative_s7_group_translation_v41 as r
from scripts import creative_joint_source_binding_v12 as joint

@pytest.fixture(scope="module")
def ctx():
    original,compiled=r.final_context(1)
    original["shots"]=r.view.project_storyboard(original["shots"],original)
    original["director_input_script_timing_status"]=r.context()["script_timing_status"]
    return original

def test_original_failure_is_local_not_provider(ctx):
    old=deepcopy(ctx);old.pop("director_input_script_timing_status")
    with pytest.raises(r.joint.JointSourceBindingError,match="JOINT_SOURCE_PROJECTION_INVALID"):
        r.joint.preflight(old)

def test_full_current_compilation_accepts_authenticated_original_marker(ctx):
    before=deepcopy(ctx);proof=joint.preflight(ctx)
    assert proof["source_identity_checked"] and len(proof["mapping"])==10
    assert ctx==before and ctx["whole_film_direction"]["context_sha256"]==r.control.digest(r.context())

@pytest.mark.parametrize("key,value",[("script_timing_status","preliminary_budget_not_actual"),("director_input_script_timing_status","actual_compiled_local_schedule")])
def test_invalid_transition_blocked(ctx,key,value):
    bad=deepcopy(ctx);bad[key]=value
    with pytest.raises(joint.JointSourceBindingError):joint.preflight(bad)

def test_changed_original_still_blocked(ctx):
    bad=deepcopy(ctx);bad["raw_linear_script"]["title"]+=" changed"
    with pytest.raises(joint.JointSourceBindingError):joint.preflight(bad)

def test_changed_execution_window_still_blocked(ctx):
    bad=deepcopy(ctx);bad["execution_bindings"][0]["end"]+=.1
    with pytest.raises(joint.JointSourceBindingError):joint.preflight(bad)
