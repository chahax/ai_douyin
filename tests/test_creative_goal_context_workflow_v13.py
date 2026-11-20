"""Independent offline verification of actual lossless drama-request wiring."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

from jsonschema import ValidationError
import pytest

from scripts.creative_m31_flash_role_clients_v1 import M31FlashRoleClients, expected_wire_request
from src.content_factory import creative_goal_context_workflow_v12 as frozen
from src.content_factory import creative_goal_context_workflow_v13 as workflow
from src.content_factory import creative_goal_evidence_view_v1 as evidence
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests import test_creative_goal_context_workflow_v11 as helpers

PROJECT = Path(__file__).resolve().parents[1]
TRIALS = PROJECT / "data/production_trials/goal_context_text_production_20261013"


@pytest.fixture(autouse=True)
def zero_dispatch(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("workflow13 request verification does not dispatch providers")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(M31FlashRoleClients, "__init__", deny)


def read(path): return json.loads(path.read_text(encoding="utf-8-sig"))
def payload(prepared): return json.loads(prepared["request"]["messages"][1]["content"])


def occurrences(value, document):
    if type(value) is dict:
        return int(value == document) + sum(occurrences(child, document) for child in value.values())
    if type(value) is list: return sum(occurrences(child, document) for child in value)
    return 0


def final_wire(prepared):
    actual = payload(prepared)
    manifest, provenance = prepared["manifest"], prepared["request"]["input_provenance"]
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    assert prepared["wire"]["tools"][0]["function"]["parameters"] == prepared["request"]["structured_schema"]
    assert prepared["request_sha256"] == workflow.digest(prepared["request"])
    assert manifest["payload_identity"] == workflow.contexts._measure(actual)
    assert provenance["context_manifest_sha256"] == workflow.digest(manifest)
    assert provenance["workflow_version"] == manifest["workflow_version"] == workflow.VERSION
    assert not prepared["dispatch_performed"] and prepared["sdk_max_retries"] == 0
    return actual


@pytest.mark.parametrize("round_name", ["round_11", "round_12"])
def test_actual_drama_wire_one_complete_lossless_view_exact_reconstruction_and_sha(round_name):
    root = TRIALS / round_name
    if not root.exists(): pytest.skip("read-only actual fixture absent")
    inputs, goal = read(root / "INPUTS.json"), read(root / "goals/native_01.json")
    profile = read(PROJECT / "config/creative_goal_context_model_profile_v3.json")
    before = deepcopy((inputs, goal))
    paths = [root / "STATE.json", root / "CALL_LEDGER.json", root / "PRODUCTION_FREEZE.json", root / "goals/native_01.json"]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    prepared = workflow.prepare_goal_drama_audit_request(inputs, profile, goal)
    actual = final_wire(prepared)
    assert "native_goal_document" not in actual and "goal_evidence_catalog" not in actual
    view = actual["native_goal_evidence_view"]
    assert occurrences(actual, view) == occurrences(actual, view["evidence_catalog"]) == 1
    assert occurrences(actual, goal) == 0
    reconstructed = evidence.reconstruct_goal(view, expected_native_goal_sha256=workflow.digest(goal))
    assert reconstructed == goal and workflow.digest(reconstructed) == workflow.digest(goal)
    assert view["evidence_catalog"] == workflow.drama_contract.build_evidence_catalog(goal)
    assert actual["reference_fulltext"] == inputs["reference_fulltext"]
    assert workflow.contexts._reference_occurrences(actual, inputs["reference_fulltext"]) == 1
    schema = prepared["request"]["structured_schema"]
    assert schema["properties"]["goal_sha256"]["const"] == workflow.digest(goal)
    assert schema["properties"]["audit_context_sha256"]["const"] == workflow.digest(actual)
    assert schema["properties"]["schema"]["const"] == "creative_goal_drama_audit/v10"
    assert "closed_scope_findings" in schema["required"]
    manifest = prepared["manifest"]
    assert manifest["lossless_goal_view_sha256"] == workflow.digest(view)
    assert manifest["native_goal_sha256"] == workflow.digest(goal)
    assert manifest["native_goal_reconstruction_verified"] and not manifest["original_native_goal_sent_separately"]
    assert manifest["context_policy"] == {"max_payload_characters": 100_000, "max_payload_utf8_bytes": 300_000}
    assert manifest["payload_identity"]["characters"] < 100_000 and manifest["payload_identity"]["utf8_bytes"] < 300_000
    assert prepared["wire"]["model"] == "deepseek-flash" and prepared["wire"]["thinking"] == {"type": "disabled"}
    for name in ("native_goal_document", "goal_evidence_catalog"):
        rows = [row for row in manifest["field_manifest"] if row["path"] == name]
        assert len(rows) == 1 and rows[0]["disposition"] == "losslessly_represented"
    assert (inputs, goal) == before
    assert hashes == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def test_actual573_quote_reference_mismatch_stays_rejected_without_rewriting_old_response():
    root = TRIALS / "round_12"
    path = root / "call_573_goal_drama_audit_01.json"
    if not path.exists(): pytest.skip("read-only actual573 absent")
    raw = path.read_bytes()
    report = json.loads(raw)["output"]
    inputs, goal = read(root / "INPUTS.json"), read(root / "goals/native_01.json")
    profile = read(PROJECT / "config/creative_goal_context_model_profile_v3.json")
    prepared = workflow.prepare_goal_drama_audit_request(inputs, profile, goal)
    rebuilt = evidence.reconstruct_goal(payload(prepared)["native_goal_evidence_view"])
    with pytest.raises(ValueError, match="verbatim"):
        workflow.validate_goal_drama_audit(report, rebuilt, context_sha256=report["audit_context_sha256"])
    current_sha = workflow.digest(payload(prepared))
    assert current_sha != report["audit_context_sha256"]
    with pytest.raises(ValidationError):
        workflow.validate_goal_drama_audit(report, rebuilt, context_sha256=current_sha)
    assert path.read_bytes() == raw


def test_context_limits_are_explicit_and_not_enlarged_for_lossless_view():
    root = TRIALS / "round_12"
    if not root.exists(): pytest.skip("read-only actual fixture absent")
    inputs, goal = read(root / "INPUTS.json"), read(root / "goals/native_01.json")
    profile = read(PROJECT / "config/creative_goal_context_model_profile_v3.json")
    policy = {"max_payload_characters": 80_000, "max_payload_utf8_bytes": 120_000}
    inputs["context_policy"] = policy
    prepared = workflow.prepare_goal_drama_audit_request(inputs, profile, goal)
    assert prepared["manifest"]["context_policy"] == policy
    final_wire(prepared)
    inputs["context_policy"] = {"max_payload_characters": 10_000, "max_payload_utf8_bytes": 30_000}
    before = deepcopy(inputs)
    with pytest.raises(ValueError, match="exceeds"):
        workflow.prepare_goal_drama_audit_request(inputs, profile, goal)
    assert inputs == before


def fake_current_bundle(module, inputs, profile, goal):
    # Fresh synthetic control-flow fixture. Never a converted actual audit.
    bundle = helpers.synthetic_bundle(inputs, profile, goal)
    bundle["schema"] = module.BUNDLE_VERSION
    report = bundle["native_drama_audit"]
    report["schema"] = module.DRAMA_AUDIT_VERSION
    report["closed_scope_findings"] = []
    report["audit_context_sha256"] = module.digest(payload(module.prepare_goal_drama_audit_request(inputs, profile, goal)))
    return bundle


@pytest.mark.parametrize("stage", ["source", "setup", "author", "semantic", "physical"])
def test_other_stages_keep_frozen_payload_native_source_setup_full_review_and_reference_rules(causal_scenario, stage):
    inputs, _, goal, opening, _, ids, native = deepcopy(causal_scenario)
    profile = read(PROJECT / "config/creative_goal_context_model_profile_v3.json")
    before = deepcopy((inputs, goal, opening, native))
    def prepare(module):
        if stage == "source": return module.prepare_goal_source_audit_request(inputs, profile, goal)
        if stage == "setup": return module.prepare_opening_setup_request(inputs, profile, goal)
        if stage == "author":
            return module.prepare_script_request(inputs, profile, goal, fake_current_bundle(module, inputs, profile, goal),
                opening_setup=opening, **ids)
        views = module.compile_native_views(goal, opening, **ids)
        return module.prepare_full_review_part_request(inputs, profile, native, views, stage)
    old, new = prepare(frozen), prepare(workflow)
    actual = final_wire(new)
    assert actual == payload(old)
    assert new["request"]["structured_schema"] == old["request"]["structured_schema"]
    assert new["request"]["messages"][0]["content"] == old["request"]["messages"][0]["content"]
    assert "native_goal_evidence_view" not in actual
    expected_reference = 1 if stage in ("author", "semantic") else 0
    assert workflow.contexts._reference_occurrences(actual, inputs["reference_fulltext"]) == expected_reference
    if stage in ("author", "semantic", "physical"):
        assert actual["native_goal_document"] == goal and occurrences(actual, goal) == 1
        assert actual["native_opening_setup_document"] == opening
    if stage in ("semantic", "physical"):
        assert actual["native_script_document"] == native
        assert actual["same_source_sha256"] == new["same_source_sha256"]
    assert (inputs, goal, opening, native) == before
