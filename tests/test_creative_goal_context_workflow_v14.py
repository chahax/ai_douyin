"""Actual wire and source-bound three-audit gates; no provider dispatch."""
from copy import deepcopy
import json
from pathlib import Path
import socket

import pytest
from jsonschema import ValidationError

from scripts.creative_m31_flash_role_clients_v1 import M31FlashRoleClients, expected_wire_request
from src.content_factory import creative_goal_context_workflow_v14 as workflow
from src.content_factory import creative_goal_context_workflow_v13 as frozen
from src.content_factory import creative_goal_evidence_view_v1 as evidence
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests.test_creative_goal_context_workflow_v13 import fake_current_bundle, occurrences
from tests.test_creative_goal_commitment_audit_v1 import synthetic as synthetic_focus

PROJECT = Path(__file__).resolve().parents[1]
ACTUAL = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_13"


def read(path): return json.loads(path.read_text(encoding="utf-8-sig"))
def payload(prepared): return json.loads(prepared["request"]["messages"][1]["content"])
def profile(): return read(PROJECT / "config/creative_goal_context_model_profile_v3.json")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError("request gate tests cannot contact providers")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(M31FlashRoleClients, "__init__", deny)


def fresh_bundle(inputs, goal):
    # Synthetic control-flow fixture, not converted actual provider output.
    dual = fake_current_bundle(frozen, inputs, profile(), goal)
    focus = synthetic_focus(goal)
    focus["audit_context_sha256"] = workflow.digest(payload(
        workflow.prepare_goal_commitment_audit_request(inputs, profile(), goal)))
    return workflow.build_goal_audit_bundle(dual["native_source_audit"], dual["native_drama_audit"], focus)


def test_actual_focused_wire_contains_complete_goal_once_and_no_other_fulltext():
    inputs, goal = read(ACTUAL / "INPUTS.json"), read(ACTUAL / "goals/native_02.json")
    before = deepcopy((inputs, goal))
    prepared = workflow.prepare_goal_commitment_audit_request(inputs, profile(), goal)
    actual = payload(prepared)
    assert set(actual) == {"native_goal_evidence_view", "creative_commitment_usage_catalog", "stage_responsibility_contract"}
    view = actual["native_goal_evidence_view"]
    assert evidence.reconstruct_goal(view) == goal
    assert occurrences(actual, view) == occurrences(actual, view["evidence_catalog"]) == 1
    assert occurrences(actual, goal) == 0
    assert workflow.contexts._reference_occurrences(actual, inputs["reference_fulltext"]) == 0
    assert actual["creative_commitment_usage_catalog"] == workflow.drama_contract.build_commitment_usage_catalog(goal)
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    assert prepared["wire"]["tools"][0]["function"]["parameters"] == prepared["request"]["structured_schema"]
    assert prepared["wire"]["model"] == "deepseek-flash"
    assert prepared["wire"]["thinking"] == {"type": "disabled"}
    manifest = prepared["manifest"]
    assert manifest["payload_identity"] == workflow.contexts._measure(actual)
    assert manifest["context_policy"] == {"max_payload_characters": 100000, "max_payload_utf8_bytes": 300000}
    assert manifest["full_native_goal_losslessly_preserved"]
    assert prepared["request"]["input_provenance"]["substage"] == "commitment_relation_audit"
    assert prepared["request"]["input_provenance"]["context_manifest_sha256"] == workflow.digest(manifest)
    assert prepared["sdk_max_retries"] == 0 and not prepared["dispatch_performed"]
    assert (inputs, goal) == before


def test_three_native_current_packets_bind_author_request(causal_scenario):
    inputs, _, goal, opening, _, ids, _ = deepcopy(causal_scenario)
    bundle = fresh_bundle(inputs, goal)
    before = deepcopy(bundle)
    assert workflow.validate_goal_audit(bundle, goal, inputs=inputs)["accepted"]
    prepared = workflow.prepare_script_request(inputs, profile(), goal, bundle, opening_setup=opening, **ids)
    actual = payload(prepared)
    assert actual["native_goal_document"] == goal
    assert actual["native_opening_setup_document"] == opening
    assert actual["reference_fulltext"] == inputs["reference_fulltext"]
    assert workflow.contexts._reference_occurrences(actual, inputs["reference_fulltext"]) == 1
    provenance = prepared["request"]["input_provenance"]
    for kind in ("source", "drama", "commitment"):
        assert provenance[f"native_{kind}_audit_sha256"] == workflow.digest(bundle[f"native_{kind}_audit"])
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    assert bundle == before


@pytest.mark.parametrize("fault", ["missing_source", "missing_drama", "missing_commitment", "old_bundle", "cross_context", "cross_goal", "fail", "unknown"])
def test_incomplete_cross_source_or_failed_focus_never_prepares_author(causal_scenario, fault):
    inputs, _, goal, opening, _, ids, _ = deepcopy(causal_scenario)
    bundle = fresh_bundle(inputs, goal)
    if fault.startswith("missing_"): bundle.pop("native_" + fault[8:] + "_audit")
    elif fault == "old_bundle": bundle["schema"] = frozen.BUNDLE_VERSION
    elif fault == "cross_context": bundle["native_commitment_audit"]["audit_context_sha256"] = "0" * 64
    elif fault == "cross_goal": bundle["native_commitment_audit"]["goal_sha256"] = "0" * 64
    else:
        row = next(iter(bundle["native_commitment_audit"]["commitment_checks"].values()))
        usage = next(iter(row["actual_usages"].values()))
        row.update(status=fault, required_revision="new native plan" if fault == "fail" else "")
        usage["relationship"] = "contradicts" if fault == "fail" else "unknown"
    with pytest.raises((ValueError, ValidationError)):
        workflow.prepare_script_request(inputs, profile(), goal, bundle, opening_setup=opening, **ids)


@pytest.mark.parametrize("part", ["semantic", "physical"])
def test_actual579_full_request_uses_native_v3_without_changing_body_or_authority(part):
    inputs, goal = read(ACTUAL / "INPUTS.json"), read(ACTUAL / "goals/native_02.json")
    opening, native = read(ACTUAL / "setups/native_01.json"), read(ACTUAL / "scripts/version_01/NATIVE_SCRIPT.json")
    views = workflow.compile_native_views(goal, opening, **workflow.origin_ids(inputs))
    prepared = workflow.prepare_full_review_part_request(inputs, profile(), native, views, part)
    actual = payload(prepared)
    assert actual["native_script_document"] == native
    assert actual["native_goal_document"] == goal
    assert actual["native_opening_setup_document"] == opening
    schema = prepared["request"]["structured_schema"]
    assert schema["properties"]["schema"]["const"] == workflow.split_reviews.VERSION
    assert schema["properties"]["context_sha256"]["const"] == workflow.digest(actual)
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    if part == "semantic":
        restriction = schema["properties"]["dialogue_checks"]["properties"]["E0016"]["allOf"][1]["properties"]
        assert "E0015" not in restriction["reaction_refs"]["items"]["enum"]
        assert "E0017" in restriction["reaction_refs"]["items"]["enum"]
        assert "E0016" not in restriction["stimulus_ref"]["enum"]
    assert prepared["sdk_max_retries"] == 0


@pytest.mark.parametrize("stage", ["source", "drama", "setup"])
def test_unchanged_stages_keep_frozen_payload_schema_and_provider_settings(causal_scenario, stage):
    inputs, _, goal, _, _, _, _ = deepcopy(causal_scenario)
    name = {"source": "prepare_goal_source_audit_request", "drama": "prepare_goal_drama_audit_request", "setup": "prepare_opening_setup_request"}[stage]
    old = getattr(frozen, name)(inputs, profile(), goal)
    new = getattr(workflow, name)(inputs, profile(), goal)
    assert payload(new) == payload(old)
    assert new["request"]["structured_schema"] == old["request"]["structured_schema"]
    assert new["wire"]["model"] == old["wire"]["model"]
    assert new["wire"].get("thinking") == old["wire"].get("thinking")
