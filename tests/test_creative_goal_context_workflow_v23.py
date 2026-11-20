"""New source6 admission preserves frozen native setup/body/review contracts."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import pytest
from jsonschema import ValidationError
from scripts.creative_m31_flash_role_clients_v1 import M31FlashRoleClients, expected_wire_request
from src.content_factory import creative_goal_context_workflow_v23 as workflow
from tests.test_creative_goal_context_workflow_v22 import new_case
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests.test_creative_goal_context_workflow_v15 import synthetic_focused
from tests.test_creative_goal_legal_usage_source_audit_v6 import synthetic_source, add_uncertain_usage

PROJECT = Path(__file__).resolve().parents[1]


def read(p): return json.loads(p.read_text(encoding="utf-8-sig"))
def profile(): return read(PROJECT / "config/creative_goal_context_model_profile_v7.json")
def payload(p): return json.loads(p["request"]["messages"][1]["content"])


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError("workflow23 tests cannot dispatch")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(M31FlashRoleClients, "__init__", deny)
    # Exercise frozen historical fixtures at their recorded sampling time. This
    # only controls this offline test clock, never production freshness checks.
    from datetime import datetime, timezone
    from scripts import preview_goal_context_workflow_v2 as preview
    packet = read(preview.SOURCE_ROOT / "source/SOURCE_PACKET.json")
    sample_time = datetime.fromisoformat(packet["prepared_at"].replace("Z", "+00:00"))
    class FixtureClock:
        @staticmethod
        def now(tz=None): return sample_time.astimezone(tz or timezone.utc)
    monkeypatch.setattr(preview, "datetime", FixtureClock)


def fresh_bundle(inputs, goal):
    source_request = workflow.prepare_goal_source_audit_request(inputs, profile(), goal)
    drama_request = workflow.prepare_goal_drama_audit_request(inputs, profile(), goal)
    focused_request = workflow.prepare_goal_commitment_audit_request(inputs, profile(), goal)
    source = synthetic_source(goal, source_request["source_authority_context"], workflow.digest(payload(source_request)))
    first = next(ref for ref in workflow.drama_contract.build_evidence_catalog(goal) if ref.startswith("G"))
    row = {"status": "pass", "reason": "Synthetic judgment, no semantic gold", "required_revision": "",
           "evidence_refs": [first], "counterexample_analysis": "Synthetic comparison", "counterevidence_refs": []}
    drama = {"schema": workflow.DRAMA_AUDIT_VERSION, "goal_sha256": workflow.digest(goal),
        "audit_context_sha256": workflow.digest(payload(drama_request)), "goal_checks": {key: deepcopy(row) for key in workflow.GOAL_CHECKS},
        "scope_observations": {ref: {"audible_speakers": [], "operated_props": []}
            for ref in workflow.drama_contract.build_scope_source_catalog(goal)}, "closed_scope_findings": []}
    focused = synthetic_focused(inputs, goal)
    focused["audit_context_sha256"] = workflow.digest(payload(focused_request))
    return workflow.build_goal_audit_bundle(source, drama, focused)


def final_wire(prepared):
    actual = payload(prepared)
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    assert prepared["request_sha256"] == workflow.digest(prepared["request"])
    assert prepared["manifest"]["payload_identity"] == workflow.contexts._measure(actual)
    assert prepared["request"]["input_provenance"]["context_manifest_sha256"] == workflow.digest(prepared["manifest"])
    assert prepared["manifest"]["workflow_version"] == workflow.VERSION
    assert not prepared["dispatch_performed"] and prepared["sdk_max_retries"] == 0
    return actual


def test_source6_three_original_audits_setup4_author_and_split_full_review(causal_scenario, monkeypatch):
    inputs, goal, opening, ids, native = new_case(causal_scenario)
    def deny(*a, **kw): raise AssertionError("frozen source5 native admission cannot substitute source6")
    monkeypatch.setattr(workflow.frozen, "validate_goal_audit", deny)
    monkeypatch.setattr(workflow.source_audit.prior, "validate_source", deny)
    bundle = fresh_bundle(inputs, goal)
    assert bundle["schema"] == workflow.BUNDLE_VERSION
    verdict = workflow.validate_goal_audit(bundle, goal, inputs=inputs)
    assert verdict["accepted"] and verdict["source_decision"]["native_source_audit_version"] == workflow.SOURCE_AUDIT_VERSION
    assert not verdict["source_decision"]["speech_act_semantic_classification_proven"]
    authored = workflow.prepare_script_request(inputs, profile(), goal, bundle, opening_setup=opening, **ids)
    actual = final_wire(authored)
    assert actual["native_goal_document"] == goal and actual["native_opening_setup_document"] == opening
    for kind in ("source", "drama", "commitment"):
        assert authored["request"]["input_provenance"]["native_" + kind + "_audit_sha256"] == workflow.digest(bundle["native_" + kind + "_audit"])
    for part in ("semantic", "physical"):
        prepared = workflow.prepare_full_review_part_request(inputs, profile(), native, authored["views"], part)
        actual = final_wire(prepared)
        assert actual["native_goal_document"] == goal and actual["native_script_document"] == native
        assert prepared["same_source_sha256"]["goal_contract_sha256"] == workflow.digest(goal)
        assert ("reference_fulltext" in actual) is (part == "semantic")
    assert final_wire(workflow.prepare_opening_setup_request(inputs, profile(), goal))["native_goal_document"] == goal


@pytest.mark.parametrize("fault", ["old_bundle", "old_source", "source_sha", "source_claim", "source_coverage", "source_uncertain", "authority_drift"])
def test_source6_failure_blocks_author_without_native_fallback(causal_scenario, fault):
    inputs, goal, opening, ids, native = new_case(causal_scenario)
    bundle = fresh_bundle(inputs, goal)
    if fault == "old_bundle": bundle["schema"] = workflow.frozen.BUNDLE_VERSION
    elif fault == "old_source": bundle["native_source_audit"]["schema"] = workflow.source_audit.prior.VERSION
    elif fault == "source_sha": bundle["native_source_audit"]["goal_sha256"] = "0"*64
    elif fault == "source_claim": bundle["native_source_audit"]["claim_checks"].pop(next(iter(bundle["native_source_audit"]["claim_checks"])))
    elif fault == "source_coverage": bundle["native_source_audit"]["speech_act_by_ref"].pop(next(iter(bundle["native_source_audit"]["speech_act_by_ref"])))
    elif fault == "source_uncertain":
        ref = next(ref for ref in bundle["native_source_audit"]["speech_act_by_ref"] if ref.startswith("G"))
        add_uncertain_usage(bundle["native_source_audit"], goal, ref)
    else: inputs["verified_legal_context"]["facts"][0]["paraphrase"] += "新条件"
    with pytest.raises((ValueError, ValidationError, workflow.goals.GoalContractError)):
        workflow.prepare_script_request(inputs, profile(), goal, bundle, opening_setup=opening, **ids)


@pytest.mark.parametrize("stage", ["source", "drama", "commitment", "setup", "author", "review"])
def test_all_outbound_paths_still_recheck_fixed_legal_source(causal_scenario, stage):
    inputs, goal, opening, ids, native = new_case(causal_scenario)
    bundle = fresh_bundle(inputs, goal)
    bad = deepcopy(goal)
    next(row for row in bad["claims"] if row["kind"] == "verified_legal")["text"] += "叙事范围"
    if stage == "author": action = lambda: workflow.prepare_script_request(inputs,profile(),bad,bundle,opening_setup=opening,**ids)
    elif stage == "setup": action = lambda: workflow.prepare_opening_setup_request(inputs,profile(),bad)
    elif stage == "review":
        views = workflow.compile_native_views(goal,opening,**ids); views["goal"] = bad
        action = lambda: workflow.prepare_full_review_part_request(inputs,profile(),native,views,"physical")
    else: action = lambda: getattr(workflow, f"prepare_goal_{stage}_audit_request")(inputs,profile(),bad)
    with pytest.raises(workflow.goals.GoalContractError): action()


def test_source_request_exact_lossless_native_and_authority_context_rebind(causal_scenario):
    inputs, goal, _, _, _ = new_case(causal_scenario)
    prepared = workflow.prepare_goal_source_audit_request(inputs,profile(),goal)
    actual = final_wire(prepared)
    assert workflow.evidence_view.reconstruct_goal(actual["native_goal_evidence_view"]) == goal
    assert actual["verified_legal_context"] == workflow._fixed_legal_context(inputs)["verified_legal_context"]
    assert "reference_fulltext" not in actual
    source = synthetic_source(goal,prepared["source_authority_context"],prepared["source_context_sha256"])
    assert workflow.validate_goal_source_audit(source,goal,inputs=inputs,context_sha256=prepared["source_context_sha256"])["accepted"]
    with pytest.raises(ValueError):
        workflow.validate_goal_source_audit(source,goal,inputs=inputs,authority_context={},context_sha256=prepared["source_context_sha256"])
    assert prepared["request"]["parameters"]["max_completion_tokens"] == 24000
    assert prepared["request"]["input_provenance"]["native_source_audit_version"] == workflow.source_audit.VERSION


def test_complete_actual618_prepare_without_prior_report_conversion():
    from src.content_factory.creative_deepseek_strict_schema_v1 import compile_source_schema_with_manifest
    root = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_25"
    paths = [root / name for name in ("INPUTS.json", "goals/native_01.json", "call_619_goal_source_audit_01.json", "PRODUCTION_FREEZE.json")]
    original = {str(p): p.read_bytes() for p in paths}
    inputs, goal = read(paths[0]), read(paths[1])
    prepared = workflow.prepare_goal_source_audit_request(inputs, profile(), goal)
    actual = final_wire(prepared)
    assert workflow.evidence_view.reconstruct_goal(actual["native_goal_evidence_view"]) == goal
    schema = prepared["request"]["structured_schema"]
    service, manifest = compile_source_schema_with_manifest(schema)
    assert len(service["properties"]["speech_act_by_ref"]["required"]) == 175
    assert service["properties"]["speech_act_by_ref"]["additionalProperties"] is False
    assert len(service["properties"]["claim_checks"]["properties"]) == 39
    assert "no_legal_refs" not in service["properties"]
    assert len(json.dumps(service,ensure_ascii=False,separators=(",",":")).encode("utf-8")) < 50000
    assert {str(p):p.read_bytes() for p in paths} == original
