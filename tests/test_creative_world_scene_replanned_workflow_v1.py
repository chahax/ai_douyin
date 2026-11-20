"""Pure actual request construction; no provider or claim is created."""
from copy import deepcopy
import json
from pathlib import Path
import socket

import pytest

from scripts import creative_world_scene_replanned_workflow_v1 as m
from test_creative_world_scene_source_state_audit_v3 import synthetic_report
from test_creative_world_scene_source_state_audit_v2 import source_context

ROOT = Path(__file__).resolve().parents[1]
load = lambda p: json.loads(Path(p).read_text("utf-8-sig"))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **k): raise AssertionError("pure workflow cannot send a request")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def actual_seed():
    root = ROOT / "data/production_trials/world_scene_live_20261015/round_02"
    inputs = load(root / "INPUTS.json")
    goal = load(root / "call_645_whole_plan_02.json")["output"]
    setup = load(root / "call_650_opening_setup_01.json")["output"]
    audit = load(ROOT / "data/production_trials/world_scene_source_state_audit_20261016/round_02/call_664_source_state_audit_01.json")
    profile = load(ROOT / "data/qa/creative_world_scene_live_20261015/LIVE_PROFILE_v1.json")
    return inputs, profile, goal, setup, audit


def object_occurrences(value, target):
    if value == target: return 1
    if type(value) is dict: return sum(object_occurrences(v, target) for v in value.values())
    if type(value) is list: return sum(object_occurrences(v, target) for v in value)
    return 0


def test_actual664_seed_exact_native_once_reference_once_not_an_approved_report():
    inputs, profile, goal, setup, audit = actual_seed(); before = deepcopy((inputs, profile, goal, setup, audit))
    wf = m.ReviewWorkflow(m.base.workflow, None)
    feedback = wf.seed_feedback(goal, setup, audit["output"], audit["validation"],
        prepared={"request": audit["request"]}, failed_kind="historical_diagnostic")
    prepared = wf.prepare_goal_request({**inputs, **feedback}, profile)
    payload = json.loads(prepared["request"]["messages"][1]["content"])
    assert payload["previous_complete_document"] == goal
    diagnostics = payload["revision_diagnostics"]
    assert diagnostics["schema"] == m.FEEDBACK_VERSION and not diagnostics["diagnostic_is_admission"]
    assert diagnostics["complete_failed_native_report"] == audit["output"]
    assert diagnostics["complete_native_opening_setup"] == setup
    assert all(object_occurrences(payload, obj) == 1 for obj in (goal, setup, audit["output"]))
    assert m.base.workflow.contexts._reference_occurrences(payload, inputs["reference_fulltext"]) == 1
    assert "full_prior_script" not in payload["production_preferences"]["prior_story_scope"]
    assert m.PLANNING_RULE in prepared["request"]["messages"][0]["content"]
    clean_payload = json.loads(m.base.workflow.prepare_goal_request(inputs, profile)["request"]["messages"][1]["content"])
    assert payload["user_goal_contract"] == clean_payload["user_goal_contract"]
    assert prepared["request_sha256"] == m.base.digest(prepared["request"])
    assert (inputs, profile, goal, setup, audit) == before


def test_writer_direct_schema_actual_rules_and_same_canonical_local_action_contract():
    scenario = load(ROOT / "data/qa/creative_world_scene_workflow28_20261015/SCENARIO_HAPPY_v1.json")
    inputs, profile, docs = scenario["inputs"], scenario["profile"], scenario["documents"]
    goal = docs["whole_plan_01"]["output"]; setup = docs["opening_setup_01"]["output"]
    wf = m.ReviewWorkflow(m.base.workflow, None)
    bundle = wf.build_goal_audit_bundle(*(docs[k + "_audit_01"]["output"] for k in wf.AUDITS))
    source_prepared = wf.prepare_source_state_audit_request(inputs, profile, goal, setup)
    source_report = synthetic_report(source_prepared)
    prepared = wf.prepare_script_request(inputs, profile, goal, bundle, opening_setup=setup,
        source_state_audit=source_report, source_state_prepared=source_prepared, **wf.origin_ids(inputs))
    assert m.WRITER_RULE in prepared["request"]["messages"][0]["content"]
    assert m.contract.RELATION_RULE in prepared["request"]["messages"][0]["content"]
    assert prepared["request"]["structured_schema"] == m.direct.prepare_schema(goal)["schema"]
    native = docs["complete_script_01"]["output"]
    assert wf.validate_script_document(native, prepared["views"], inputs["production_preferences"])["script"]
    changed = deepcopy(native)
    action = next(step for beat in changed["beats"] for step in beat["steps"] if step["kind"] == "action")
    action["speaker"] = goal["whole_plan"]["characters"][0]["id"]
    with pytest.raises(ValueError): wf.validate_script_document(changed, prepared["views"], inputs["production_preferences"])
    with pytest.raises(ValueError, match="state audit"):
        wf.prepare_script_request(inputs, profile, goal, bundle, opening_setup=setup, **wf.origin_ids(inputs))
    rejected = deepcopy(source_report); rejected["semantic_checks"]["action_purpose"]["status"] = "fail"
    with pytest.raises(ValueError, match="accepted state"):
        wf.prepare_script_request(inputs, profile, goal, bundle, opening_setup=setup,
            source_state_audit=rejected, source_state_prepared=source_prepared, **wf.origin_ids(inputs))


def test_only_source_state_substage_cap_is_projected_and_exact_wrapper_is_rebuilt():
    inputs, profile, goal, setup = source_context(); profile["stage_parameters"]["goal_audit"]["max_completion_tokens"] = 16000
    original = deepcopy(profile); wf = m.ReviewWorkflow(m.base.workflow, None)
    prepared = wf.prepare_source_state_audit_request(inputs, profile, goal, setup)
    assert profile == original and prepared["request"]["parameters"]["max_completion_tokens"] == 32000
    expected = deepcopy(profile); expected["stage_parameters"]["goal_audit"]["max_completion_tokens"] = 32000
    assert prepared["views"]["profile"] == expected
    native = synthetic_report(prepared, local_conflict=True)
    decision = wf.validate_source_state_audit(native, prepared)
    assert decision["valid"] and not decision["accepted"] and decision["computed_state_findings"]
    report_map = {name: {"schema": "OFFLINE_" + name} for name in wf.AUDITS}
    bundle = {"schema": wf.BUNDLE_VERSION, **{"native_" + name + "_audit": value for name, value in report_map.items()}}
    feedback = wf.seed_feedback(goal, setup, native, decision, prepared=prepared, passed_audits=bundle)
    assert set(feedback["revision_diagnostics"]["passed_audit_identities"]) == set(wf.AUDITS)
    assert feedback["revision_diagnostics"]["complete_failed_native_report"] == native
    assert not any(object_occurrences(feedback, report) for report in report_map.values())
    changed = deepcopy(prepared); changed["coordinator_profile_projection"]["source_state_only_output_cap_override"] = 16000
    with pytest.raises(ValueError): wf.validate_source_state_audit(native, changed)
    feedback = wf.seed_feedback(goal, None, None, {"valid": False, "findings": [{"path": "/whole_plan", "reason": "OFFLINE结构错误"}]}, failed_kind="goal_contract")
    assert not feedback["revision_diagnostics"]["native_audit_present"]
    assert "complete_failed_native_report" not in feedback["revision_diagnostics"]
