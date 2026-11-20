"""Scoped focused-request wiring and three-native-audit gates; offline only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

from jsonschema import ValidationError
import pytest

from scripts.creative_m31_flash_role_clients_v1 import M31FlashRoleClients, expected_wire_request
from src.content_factory import creative_goal_context_workflow_v14 as frozen
from src.content_factory import creative_goal_context_workflow_v15 as workflow
from src.content_factory import creative_goal_evidence_view_v1 as evidence
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests.test_creative_goal_context_workflow_v13 import fake_current_bundle, occurrences
from tests.test_creative_goal_context_workflow_v14 import fresh_bundle as old_bundle

PROJECT = Path(__file__).resolve().parents[1]
ACTUAL = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_14"
PREVIOUS = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_13"


def read(path): return json.loads(path.read_text(encoding="utf-8-sig"))
def profile(): return read(PROJECT / "config/creative_goal_context_model_profile_v3.json")
def payload(prepared): return json.loads(prepared["request"]["messages"][1]["content"])


@pytest.fixture(autouse=True)
def zero_dispatch(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError("scoped workflow tests may not contact providers")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(M31FlashRoleClients, "__init__", deny)


def final_wire(prepared):
    actual = payload(prepared)
    manifest, provenance = prepared["manifest"], prepared["request"]["input_provenance"]
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    assert prepared["wire"]["tools"][0]["function"]["parameters"] == prepared["request"]["structured_schema"]
    assert prepared["request_sha256"] == workflow.digest(prepared["request"])
    assert manifest["payload_identity"] == workflow.contexts._measure(actual)
    assert provenance["context_manifest_sha256"] == workflow.digest(manifest)
    assert provenance["workflow_version"] == manifest["workflow_version"] == workflow.VERSION
    assert prepared["sdk_max_retries"] == 0 and not prepared["dispatch_performed"]
    return actual


def synthetic_focused(inputs, goal):
    """Fresh fake v2 report; not rewritten actual584 and not semantic gold."""
    api = workflow.commitment_audit
    catalog = api.build_evidence_catalog(goal)
    global_g = [ref for ref in catalog if ref.startswith("G")]
    checks = {}
    for identifier, usage in api.build_commitment_usage_catalog(goal).items():
        uses = {}
        for key, item in usage["usages"].items():
            comparison = next((ref for ref in global_g if ref not in item["evidence_refs"]), global_g[0])
            uses[key] = {"evidence_refs": [item["evidence_refs"][0]], "comparison_refs": [comparison],
                "requirement_scope": "background_consistency",
                "actual_interpretation": "Synthetic native usage; meaning is not proved",
                "relationship": "compatible"}
        checks[identifier] = {"claim_ref": usage["claim_ref"],
            "literal_requirement": "Synthetic requirement; not a semantic gold label",
            "actual_usages": uses, "status": "pass", "reason": "Synthetic source-bound control flow",
            "required_revision": "", "counterevidence_refs": []}
    prepared = workflow.prepare_goal_commitment_audit_request(inputs, profile(), goal)
    return {"schema": api.VERSION, "goal_sha256": api.digest(goal),
            "audit_context_sha256": workflow.digest(payload(prepared)), "commitment_checks": checks}


def fresh_bundle(inputs, goal):
    dual = fake_current_bundle(frozen, inputs, profile(), goal)
    return workflow.build_goal_audit_bundle(dual["native_source_audit"], dual["native_drama_audit"],
                                          synthetic_focused(inputs, goal))


def test_actual582_focus_request_contains_lossless_original_once_and_new_scope_schema():
    if not ACTUAL.exists(): pytest.skip("read-only actual582 fixture absent")
    inputs, goal = read(ACTUAL / "INPUTS.json"), read(ACTUAL / "goals/native_02.json")
    paths = [ACTUAL / name for name in ("goals/native_02.json", "call_582_goal_plan_21.json",
        "call_584_goal_commitment_audit_02.json", "STATE.json", "CALL_LEDGER.json", "PRODUCTION_FREEZE.json")]
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    original = deepcopy((inputs, goal))
    prepared = workflow.prepare_goal_commitment_audit_request(inputs, profile(), goal)
    actual = final_wire(prepared)
    assert set(actual) == {"native_goal_evidence_view", "creative_commitment_usage_catalog", "stage_responsibility_contract"}
    view = actual["native_goal_evidence_view"]
    assert evidence.reconstruct_goal(view) == goal and workflow.digest(evidence.reconstruct_goal(view)) == workflow.digest(goal)
    assert occurrences(actual, view) == occurrences(actual, view["evidence_catalog"]) == 1
    assert occurrences(actual, goal) == 0
    assert workflow.contexts._reference_occurrences(actual, inputs["reference_fulltext"]) == 0
    old = frozen.prepare_goal_commitment_audit_request(inputs, profile(), goal)
    assert actual == payload(old)
    schema = prepared["request"]["structured_schema"]
    assert schema["properties"]["schema"]["const"] == "creative_goal_commitment_audit/v2"
    assert schema["properties"]["goal_sha256"]["const"] == workflow.digest(goal)
    assert schema["properties"]["audit_context_sha256"]["const"] == workflow.digest(actual)
    assert prepared["wire"]["model"] == "deepseek-flash" and prepared["wire"]["thinking"] == {"type": "disabled"}
    assert prepared["manifest"]["context_policy"] == {"max_payload_characters": 100000, "max_payload_utf8_bytes": 300000}
    assert workflow.COMMITMENT_FOCUS_RULE in prepared["wire"]["messages"][0]["content"]
    for text in ("claim_refs是使用关联", "comparison_refs", "背景定义不证明动态行为", "同一物件", "不能用人物pressure"):
        assert text in prepared["wire"]["messages"][0]["content"]
    assert (inputs, goal) == original
    assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def test_actual582_global_G_comparison_enum_and_own_usage_evidence_enum_remain_distinct():
    if not ACTUAL.exists(): pytest.skip("read-only actual582 fixture absent")
    inputs, goal = read(ACTUAL / "INPUTS.json"), read(ACTUAL / "goals/native_02.json")
    prepared = workflow.prepare_goal_commitment_audit_request(inputs, profile(), goal)
    schema = prepared["request"]["structured_schema"]
    usages = workflow.commitment_audit.build_commitment_usage_catalog(goal)
    all_g = [ref for ref in workflow.commitment_audit.build_evidence_catalog(goal) if ref.startswith("G")]
    for identifier, item in usages.items():
        rows = schema["properties"]["commitment_checks"]["properties"][identifier]["properties"]["actual_usages"]["properties"]
        assert set(rows) == set(item["usages"])
        for key, usage in item["usages"].items():
            assert rows[key]["properties"]["evidence_refs"]["items"]["enum"] == usage["evidence_refs"]
            assert rows[key]["properties"]["comparison_refs"]["items"]["enum"] == all_g
            assert rows[key]["properties"]["comparison_refs"]["minItems"] == 0
            assert set(rows[key]["properties"]["requirement_scope"]["enum"]) == {
                "background_consistency", "local_event", "cross_beat_relation", "mixed"}
            assert {"comparison_refs", "requirement_scope"}.issubset(rows[key]["required"])
    assert {"G063", "G091"}.issubset(all_g)


def test_three_current_native_audits_preserve_author_provenance_and_original_body_rules(causal_scenario):
    inputs, _, goal, opening, _, ids, _ = deepcopy(causal_scenario)
    bundle = fresh_bundle(inputs, goal)
    before = deepcopy(bundle)
    result = workflow.validate_goal_audit(bundle, goal, inputs=inputs)
    assert result["accepted"] and result["three_native_audits_bound"]
    assert not result["semantic_truth_deterministically_proven"]
    prepared = workflow.prepare_script_request(inputs, profile(), goal, bundle, opening_setup=opening, **ids)
    actual = final_wire(prepared)
    old = frozen.prepare_script_request(inputs, profile(), goal, old_bundle(inputs, goal), opening_setup=opening, **ids)
    assert actual == payload(old) and prepared["request"]["structured_schema"] == old["request"]["structured_schema"]
    assert actual["native_goal_document"] == goal and actual["native_opening_setup_document"] == opening
    assert workflow.contexts._reference_occurrences(actual, inputs["reference_fulltext"]) == 1
    for kind in ("source", "drama", "commitment"):
        assert prepared["request"]["input_provenance"][f"native_{kind}_audit_sha256"] == workflow.digest(bundle[f"native_{kind}_audit"])
    assert bundle == before


@pytest.mark.parametrize("fault", ["missing_source", "missing_drama", "missing_commitment", "old_bundle", "old_focus", "missing_scope", "missing_comparison", "C_comparison", "foreign_comparison", "other_usage_as_own", "missing_usage", "foreign_usage", "missing_claim", "cross_context", "cross_goal", "fail", "unknown"])
def test_three_audit_gate_rejects_missing_cross_source_malformed_or_failed_focus(causal_scenario, fault):
    inputs, _, goal, opening, _, ids, _ = deepcopy(causal_scenario)
    bundle = fresh_bundle(inputs, goal)
    focused = bundle["native_commitment_audit"]
    identifier, row = next(iter(focused["commitment_checks"].items()))
    key, usage = next(iter(row["actual_usages"].items()))
    if fault.startswith("missing_") and fault in ("missing_source", "missing_drama", "missing_commitment"):
        bundle.pop("native_" + fault[8:] + "_audit")
    elif fault == "old_bundle": bundle["schema"] = frozen.BUNDLE_VERSION
    elif fault == "old_focus": focused["schema"] = frozen.commitment_audit.VERSION
    elif fault == "missing_scope": usage.pop("requirement_scope")
    elif fault == "missing_comparison": usage.pop("comparison_refs")
    elif fault == "C_comparison": usage["comparison_refs"] = [row["claim_ref"]]
    elif fault == "foreign_comparison": usage["comparison_refs"] = ["G999"]
    elif fault == "other_usage_as_own": usage["evidence_refs"] = list(usage["comparison_refs"])
    elif fault == "missing_usage": row["actual_usages"].pop(key)
    elif fault == "foreign_usage": row["actual_usages"]["foreign"] = deepcopy(usage)
    elif fault == "missing_claim": focused["commitment_checks"].pop(identifier)
    elif fault == "cross_context": focused["audit_context_sha256"] = "0" * 64
    elif fault == "cross_goal": focused["goal_sha256"] = "0" * 64
    else:
        usage["relationship"] = "contradicts" if fault == "fail" else "unknown"
        row.update(status=fault, required_revision="Submit complete native revision" if fault == "fail" else "")
    with pytest.raises((ValueError, ValidationError)):
        workflow.prepare_script_request(inputs, profile(), goal, bundle, opening_setup=opening, **ids)


def test_actual584_old_native_report_is_not_relabelled_or_adopted():
    if not ACTUAL.exists(): pytest.skip("read-only actual584 fixture absent")
    path = ACTUAL / "call_584_goal_commitment_audit_02.json"
    raw = path.read_bytes()
    report = json.loads(raw)["output"]
    inputs, goal = read(ACTUAL / "INPUTS.json"), read(ACTUAL / "goals/native_02.json")
    prepared = workflow.prepare_goal_commitment_audit_request(inputs, profile(), goal)
    with pytest.raises(ValidationError):
        workflow.validate_goal_commitment_audit(report, goal, context_sha256=workflow.digest(payload(prepared)))
    assert path.read_bytes() == raw and report["schema"] == frozen.commitment_audit.VERSION


@pytest.mark.parametrize("stage", ["source", "drama", "setup"])
def test_source_drama_setup_keep_v14_payload_schema_prompt_and_model_settings(causal_scenario, stage):
    inputs, _, goal, _, _, _, _ = deepcopy(causal_scenario)
    method = {"source": "prepare_goal_source_audit_request", "drama": "prepare_goal_drama_audit_request", "setup": "prepare_opening_setup_request"}[stage]
    old, new = getattr(frozen, method)(inputs, profile(), goal), getattr(workflow, method)(inputs, profile(), goal)
    actual = final_wire(new)
    assert actual == payload(old)
    assert new["request"]["structured_schema"] == old["request"]["structured_schema"]
    assert new["request"]["messages"][0]["content"] == old["request"]["messages"][0]["content"]
    assert new["wire"]["model"] == old["wire"]["model"]
    if stage == "drama": assert "commitment_checks" in new["request"]["structured_schema"]["required"]


@pytest.mark.parametrize("part", ["semantic", "physical"])
def test_actual579_full_review_keeps_current_split_v3_and_original_source_payload(part):
    if not PREVIOUS.exists(): pytest.skip("read-only actual579 fixture absent")
    inputs, goal = read(PREVIOUS / "INPUTS.json"), read(PREVIOUS / "goals/native_02.json")
    opening, native = read(PREVIOUS / "setups/native_01.json"), read(PREVIOUS / "scripts/version_01/NATIVE_SCRIPT.json")
    views = workflow.compile_native_views(goal, opening, **workflow.origin_ids(inputs))
    old = frozen.prepare_full_review_part_request(inputs, profile(), native, views, part)
    prepared = workflow.prepare_full_review_part_request(inputs, profile(), native, views, part)
    actual = final_wire(prepared)
    assert actual == payload(old) and prepared["request"]["structured_schema"] == old["request"]["structured_schema"]
    assert actual["native_goal_document"] == goal and actual["native_opening_setup_document"] == opening
    assert actual["native_script_document"] == native
    assert prepared["request"]["structured_schema"]["properties"]["schema"]["const"] == "creative_split_full_review_part/v3"


def test_context_budget_remains_explicit_and_smaller_cap_rejects_without_changing_native():
    if not ACTUAL.exists(): pytest.skip("read-only actual582 fixture absent")
    inputs, goal = read(ACTUAL / "INPUTS.json"), read(ACTUAL / "goals/native_02.json")
    policy = {"max_payload_characters": 80000, "max_payload_utf8_bytes": 120000}
    inputs["context_policy"] = policy
    prepared = workflow.prepare_goal_commitment_audit_request(inputs, profile(), goal)
    assert prepared["manifest"]["context_policy"] == policy
    inputs["context_policy"] = {"max_payload_characters": 10000, "max_payload_utf8_bytes": 30000}
    before = deepcopy((inputs, goal))
    with pytest.raises(ValueError, match="exceeds"):
        workflow.prepare_goal_commitment_audit_request(inputs, profile(), goal)
    assert (inputs, goal) == before
