"""Narrow synthetic phase controls; no actual report is converted or repaired."""
from copy import deepcopy
import json
from pathlib import Path
import socket

import pytest

from scripts import creative_world_scene_source_state_audit_v4 as m
from scripts import creative_world_scene_replanned_workflow_v2 as workflow
from test_creative_world_scene_source_state_audit_v2 import source_context as old_context
from test_creative_world_scene_source_state_audit_v2 import quantity_chain, quantity_step, attach_chain, proof, beat_proof
from test_creative_world_scene_source_state_audit_v3 import synthetic_report as previous_fixture

ROOT = Path(__file__).resolve().parents[1]
load = lambda p: json.loads(Path(p).read_text("utf-8-sig"))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **k): raise AssertionError("no provider or network authorized")
    monkeypatch.setattr(socket.socket, "connect", deny); monkeypatch.setattr(socket, "create_connection", deny)


def source_context():
    inputs, profile, goal, setup = old_context()
    for beat, text in zip(goal["whole_plan"]["beats"], ("OFFLINE合成：完成计数0，开始观察本次动作。",
            "OFFLINE合成：本次动作完成，计数增至1。", "OFFLINE合成：另一独立动作完成，计数增至2。",
            "OFFLINE合成：重述此前同一次完成，不是新动作。")):
        beat["visible_change"] = text
    setup["goal_sha256"] = m.digest(goal)
    return inputs, profile, goal, setup


def synthetic_report(prepared, local_conflict=False):
    """Fresh OFFLINE report only, never actual671/new-source semantic approval."""
    native = previous_fixture(prepared, local_conflict=local_conflict)
    native["schema"] = m.VERSION
    return native


def observed_then_complete(p):
    native = synthetic_report(p); chain = quantity_chain(p); chain["initial_value"] = 0
    chain["steps"] = [quantity_step(p, 0, 0, 0, 0, "observe", event="EV_ONE"),
        quantity_step(p, 1, 0, 1, 1, "add", event="EV_ONE"),
        quantity_step(p, 2, 1, 1, 2, "add", event="EV_TWO")]
    attach_chain(native, chain, "quantity")
    return native


def test_observation_completion_next_event_and_intent_are_not_all_completion():
    p = m.prepare(*source_context()); native = observed_then_complete(p); d = m.validate(native, p)
    assert d["valid"] and d["accepted"]
    assert [(row["applied"], row["state_after"]) for row in d["typed_replay"]] == [(False, 0), (True, 1), (True, 2)]
    native["quantity_chains"][0]["steps"][0]["reading"] = "intent"
    assert m.validate(native, p)["accepted"]


def test_duplicate_nonzero_completion_once_but_observations_after_it_still_check_current():
    p = m.prepare(*source_context()); native = observed_then_complete(p); chain = native["quantity_chains"][0]
    repeated = deepcopy(chain["steps"][1]); repeated["beat_id"] = p["views"]["goal"]["whole_plan"]["beats"][3]["id"]
    repeated["evidence"] = [beat_proof(p, 3)]; chain["steps"].append(repeated)
    d = m.validate(native, p); assert d["accepted"] and not d["typed_replay"][-1]["applied"]
    chain["steps"].append(quantity_step(p, 3, 2, 0, 2, "maintain", event="EV_ONE"))
    assert m.validate(native, p)["accepted"]
    chain["steps"][-1]["before"] = chain["steps"][-1]["after"] = 0
    assert any(row["code"] == "QUANTITY_PRECONDITION_CONFLICT" for row in m.validate(native, p)["findings"])


def test_conflicting_completed_event_is_rejected_and_original_native_stays_exact():
    p = m.prepare(*source_context()); native = observed_then_complete(p)
    native["quantity_chains"][0]["steps"][2]["event_id"] = "EV_ONE"
    before = deepcopy(native); d = m.validate(native, p)
    assert not d["valid"] and not d["accepted"]
    assert any(row["code"] == "EVENT_ID_TYPED_CONFLICT" for row in d["contract_findings"])
    assert native == before


def test_quantity_initial_uses_same_prop_not_actor_posture_and_catalog_exposes_roles():
    p = m.prepare(*source_context()); native = observed_then_complete(p); chain = native["quantity_chains"][0]
    chain["initial_reading"] = "initial"
    actor = next(iter(p["views"]["setup"]["characters"]))
    chain["initial_evidence"] = [proof(p, "setup", f"/characters/{actor}/posture")]
    d = m.validate(native, p)
    assert not d["valid"] and any(row["code"] == "QUANTITY_INITIAL_OBJECT_EVIDENCE_MISSING" and "custody" not in row["reason"] for row in d["contract_findings"])
    entry = p["views"]["source_catalog"][chain["initial_evidence"][0]["ref"]]
    assert entry["entity_kind"] == "actor" and entry["entity_id"] == actor
    prop = chain["object_id"]; path = next(row["path"] for row in p["views"]["source_catalog"].values() if row.get("entity_id") == prop and row.get("source_role") == "opening_prop_state")
    chain["initial_evidence"] = [proof(p, "setup", path)]
    assert m.validate(native, p)["accepted"]


def test_unknown_stays_unknown_and_actual671_is_never_a_new_v4_native_report():
    p = m.prepare(*source_context()); native = observed_then_complete(p)
    native["quantity_chains"][0].update(initial_reading="unknown", initial_value=None)
    d = m.validate(native, p); assert d["valid"] and not d["accepted"] and d["uncertainties"]
    root = ROOT / "data/production_trials/world_scene_live_20261016/round_01"
    inputs = load(root / "INPUTS.json"); goal = load(root / "call_665_whole_plan_01.json")["output"]
    setup = load(root / "call_670_opening_setup_01_01.json")["output"]
    old = load(root / "call_671_source_state_audit_01.json")["output"]; original = deepcopy(old)
    profile = load(ROOT / "data/qa/creative_world_scene_live_20261015/LIVE_PROFILE_v1.json")
    profile["stage_parameters"]["goal_audit"]["max_completion_tokens"] = 32000
    prepared = m.prepare(inputs, profile, goal, setup); payload = json.loads(prepared["request"]["messages"][1]["content"])
    assert payload["native_goal_document"] == goal and payload["native_opening_setup_document"] == setup
    assert "source_packet" not in payload["authority_inputs"] and "source_packet" in prepared["views"]["inputs"]
    assert prepared["manifest"]["source_state_authority_projection"]["omitted_fields"]["source_packet"]["sha256"]
    assert m.prior.workflow.contexts._reference_occurrences(payload, inputs["reference_fulltext"]) == 1
    assert not m.validate(old, prepared)["valid"] and old == original


def test_thin_workflow_v4_gate_and_writer_proof_identity_are_exact():
    scenario = load(ROOT / "data/qa/creative_world_scene_workflow28_20261015/SCENARIO_HAPPY_v1.json")
    inputs, profile, docs = scenario["inputs"], scenario["profile"], scenario["documents"]
    goal, setup = docs["whole_plan_01"]["output"], docs["opening_setup_01"]["output"]
    wf = workflow.ReviewWorkflow(workflow.prior.base.workflow, None)
    prepared = wf.prepare_source_state_audit_request(inputs, profile, goal, setup); native = synthetic_report(prepared)
    assert wf.validate_source_state_audit(native, prepared)["accepted"]
    bundle = wf.build_goal_audit_bundle(*(docs[k + "_audit_01"]["output"] for k in wf.AUDITS))
    writer = wf.prepare_script_request(inputs, profile, goal, bundle, opening_setup=setup,
        source_state_audit=native, source_state_prepared=prepared, **wf.origin_ids(inputs))
    assert writer["request"]["input_provenance"]["source_state_audit_version"] == m.VERSION
    assert writer["manifest"]["source_state_admission_binding"]["source_state_audit_version"] == m.VERSION
    assert writer["manifest"]["replanned_workflow_version"] == workflow.VERSION
    assert writer["request_sha256"] == m.digest(writer["request"])
