"""Fixed original-law claims, sparse source5 and unchanged native setup/body chain."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

from jsonschema import Draft202012Validator, ValidationError
import pytest

from scripts.creative_m31_flash_role_clients_v1 import M31FlashRoleClients, expected_wire_request
from src.content_factory import creative_goal_context_workflow_v22 as workflow
from src.content_factory import creative_goal_context_workflow_v21 as frozen
from src.content_factory import creative_goal_legal_usage_source_audit_v4 as old_source
from tests import test_creative_goal_context_workflow_v21 as helpers
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests.test_creative_goal_context_workflow_v15 import synthetic_focused
from tests.test_creative_goal_legal_usage_source_audit_v5 import synthetic_source, add_legal_usage, add_uncertain_usage

PROJECT = Path(__file__).resolve().parents[1]
ACTUAL = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_24"


def read(p): return json.loads(p.read_text(encoding="utf-8-sig"))
def profile(): return read(PROJECT / "config/creative_goal_context_model_profile_v7.json")
def payload(p): return json.loads(p["request"]["messages"][1]["content"])


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError("workflow22 must not dispatch")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(M31FlashRoleClients, "__init__", deny)


def synthetic_fixed_goal(inputs, fixture_goal):
    """New test fixture only; never called to repair original provider616."""
    goal = deepcopy(fixture_goal)
    catalog = workflow.fixed_legal_claim_catalog(inputs)
    for row in goal["claims"]:
        if row["kind"] == "verified_legal":
            row["text"] = catalog[row["origin_ids"][0]]["text"]
    return goal


def new_case(causal_scenario):
    inputs, old, opening, ids, native = helpers.new_case(causal_scenario)
    goal = synthetic_fixed_goal(inputs, old)
    opening["goal_sha256"] = workflow.digest(goal)
    return inputs, goal, opening, ids, native


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


def test_dynamic_planning_schema_exact_one_l_and_original_text_on_actual_wire(causal_scenario):
    inputs, goal, _, _, _ = new_case(causal_scenario)
    before = deepcopy((inputs, goal))
    planned = workflow.prepare_goal_request(inputs, profile())
    actual = final_wire(planned)
    schema = planned["request"]["structured_schema"]
    assert schema == workflow.build_goal_request_schema(inputs)
    Draft202012Validator(schema).validate(goal)
    assert workflow.validate_goal_document(goal, inputs=inputs) == goal
    assert workflow.FIXED_LEGAL_SOURCE_RULE in planned["wire"]["messages"][0]["content"]
    original = workflow._fixed_legal_context(inputs)
    assert actual["verified_legal_context"] == original["verified_legal_context"]
    assert workflow.contexts._reference_occurrences(actual, inputs["reference_fulltext"]) == 1
    assert planned["request"]["input_provenance"]["fixed_legal_source_rule_version"] == workflow.FIXED_LEGAL_SOURCE_RULE_VERSION
    assert (inputs, goal) == before


@pytest.mark.parametrize("fault", ["text_append_scope", "text_condition", "text_trim", "text_whitespace", "two_l", "zero_l", "unknown_l", "user_origin", "law_wrong_text"])
def test_model_native_legal_drift_fails_schema_and_planning_validator_without_rewriting(causal_scenario, fault):
    inputs, goal, _, _, _ = new_case(causal_scenario)
    row = next(row for row in goal["claims"] if row["kind"] == "verified_legal")
    catalog = workflow.fixed_legal_claim_catalog(inputs)
    if fault == "text_append_scope": row["text"] += "本片人物不会讨论该规则。"
    elif fault == "text_condition": row["text"] = "协商解除必须由单位提出；" + row["text"]
    elif fault == "text_trim": row["text"] = row["text"][:-1]
    elif fault == "text_whitespace": row["text"] += " "
    elif fault == "two_l": row["origin_ids"] = list(catalog)[:2]
    elif fault == "zero_l": row["origin_ids"] = []
    elif fault == "unknown_l": row["origin_ids"] = ["L999"]
    elif fault == "user_origin": row["origin_ids"] = [workflow.origin_ids(inputs)["user_constraint_ids"][0]]
    else: row["text"] = next(value["text"] for ref, value in catalog.items() if ref != row["origin_ids"][0])
    before = deepcopy(goal)
    with pytest.raises(ValidationError): Draft202012Validator(workflow.build_goal_request_schema(inputs)).validate(goal)
    with pytest.raises(workflow.goals.GoalContractError): workflow.validate_goal_document(goal, inputs=inputs)
    assert not workflow.diagnose_goal_document(goal, inputs=inputs)["valid"] and goal == before


@pytest.mark.parametrize("stage", ["source", "drama", "commitment", "setup", "author", "review"])
def test_every_outbound_stage_rechecks_fixed_source_not_only_producer(causal_scenario, stage):
    inputs, goal, opening, ids, native = new_case(causal_scenario)
    bundle = fresh_bundle(inputs, goal)
    views = workflow.compile_native_views(goal, opening, **ids)
    bad = deepcopy(goal)
    next(row for row in bad["claims"] if row["kind"] == "verified_legal")["text"] += "人物叙事说明"
    if stage == "review":
        views["goal"] = bad
        action = lambda: workflow.prepare_full_review_part_request(inputs, profile(), native, views, "physical")
    elif stage == "setup": action = lambda: workflow.prepare_opening_setup_request(inputs, profile(), bad)
    elif stage == "author": action = lambda: workflow.prepare_script_request(inputs, profile(), bad, bundle, opening_setup=opening, **ids)
    else: action = lambda: getattr(workflow, f"prepare_goal_{stage}_audit_request")(inputs, profile(), bad)
    with pytest.raises(workflow.goals.GoalContractError): action()


def test_source5_three_current_audits_setup4_author_and_double_review_wire(causal_scenario, monkeypatch):
    inputs, goal, opening, ids, native = new_case(causal_scenario)
    def deny(*a, **kw): raise AssertionError("source4 native admission must not be reused")
    monkeypatch.setattr(old_source, "build_source_schema", deny)
    monkeypatch.setattr(old_source, "validate_source", deny)
    bundle = fresh_bundle(inputs, goal)
    verdict = workflow.validate_goal_audit(bundle, goal, inputs=inputs)
    assert verdict["accepted"] and not verdict["semantic_truth_deterministically_proven"]
    authored = workflow.prepare_script_request(inputs, profile(), goal, bundle, opening_setup=opening, **ids)
    actual = final_wire(authored)
    assert actual["native_goal_document"] == goal and actual["native_opening_setup_document"] == opening
    for kind in ("source", "drama", "commitment"):
        assert authored["request"]["input_provenance"]["native_" + kind + "_audit_sha256"] == workflow.digest(bundle["native_" + kind + "_audit"])
    for part in ("semantic", "physical"):
        prepared = workflow.prepare_full_review_part_request(inputs, profile(), native, authored["views"], part)
        full = final_wire(prepared)
        assert full["native_goal_document"] == goal and full["native_opening_setup_document"] == opening
        assert full["native_script_document"] == native
        assert full["same_source_sha256"]["opening_setup_sha256"] == workflow.digest(opening)
        assert workflow.contexts._reference_occurrences(full, inputs["reference_fulltext"]) == (1 if part == "semantic" else 0)


@pytest.mark.parametrize("fault", ["missing_source", "missing_drama", "missing_commitment", "old_source", "unknown_usage"])
def test_current_sparse_source_and_three_native_audit_admission_remain_required(causal_scenario, fault):
    inputs, goal, opening, ids, _ = new_case(causal_scenario)
    bundle = fresh_bundle(inputs, goal)
    if fault.startswith("missing_"): bundle.pop("native_" + fault[8:] + "_audit")
    elif fault == "old_source": bundle["native_source_audit"]["schema"] = old_source.VERSION
    else: add_uncertain_usage(bundle["native_source_audit"], goal, bundle["native_source_audit"]["no_legal_refs"][0])
    with pytest.raises((ValueError, ValidationError)): workflow.prepare_script_request(inputs, profile(), goal, bundle, opening_setup=opening, **ids)


def test_native_sparse_feedback_keeps_entire_report_negative_refs_findings_conditions_and_unknown(causal_scenario, tmp_path):
    inputs, goal, _, _, _ = new_case(causal_scenario)
    bundle = fresh_bundle(inputs, goal)
    source = bundle["native_source_audit"]
    refs = source["no_legal_refs"][:2]
    add_legal_usage(source, goal, refs[0], relation="contradicts")
    add_uncertain_usage(source, goal, refs[1])
    decision = workflow.validate_goal_audit(bundle, goal, inputs=inputs)["source_decision"]
    diagnostics = {"complete_native_same_source_goal_audit_reports": {"source": deepcopy(source)},
                   "complete_same_source_goal_audits": [decision]}
    path = tmp_path / "source5_original_diagnostics.json"
    path.write_text(json.dumps(diagnostics, ensure_ascii=False), encoding="utf-8")
    before = deepcopy(diagnostics)
    revision = {**inputs, "previous_complete_document": goal, "revision_diagnostics": diagnostics,
                "goal_revision_feedback_evidence_path": str(path)}
    prepared = workflow.prepare_goal_request(revision, profile())
    actual = final_wire(prepared)
    assert actual["previous_complete_document"] == goal
    assert actual["revision_diagnostics"]["complete_native_same_source_goal_audit_reports"]["source"] == source
    retained = actual["revision_diagnostics"]["complete_same_source_goal_audits"][0]
    for key in ("findings", "uncertainties", "no_legal_refs"):
        assert retained[key] == decision[key]
    for key in workflow.SOURCE5_COMPILED_FEEDBACK_TABLES:
        reference = retained[key]
        assert workflow.feedback._resolve_pointer(diagnostics, reference["original_json_pointer"]) == decision[key]
        assert reference["original_value_sha256"] == workflow.digest(decision[key])
    assert retained["findings"][0]["native_usage"] == source["source_observations"][-2]["usages"][0]
    assert diagnostics == before and read(path) == diagnostics


@pytest.mark.parametrize("fault", ["foreign_context", "foreign_goal", "partition_overlap", "semantic_claim", "unknown_version"])
def test_source5_compiler_projection_is_only_for_exact_current_bound_partition(causal_scenario, fault):
    inputs, goal, _, _, _ = new_case(causal_scenario)
    bundle = fresh_bundle(inputs, goal)
    decision = workflow.validate_goal_audit(bundle, goal, inputs=inputs)["source_decision"]
    if fault == "foreign_context": decision["audit_context_sha256"] = "0" * 64
    elif fault == "foreign_goal": decision["native_goal_sha256"] = "0" * 64
    elif fault == "partition_overlap": decision["no_legal_refs"].append(next(iter(decision["usage_gates"])))
    elif fault == "semantic_claim": decision["negative_classification_proven"] = True
    else: decision["schema"] = "unknown_source/decision"
    diagnostics = {"complete_same_source_goal_audits": [decision]}
    original = deepcopy(diagnostics)
    projected = workflow._project_goal_revision_feedback(diagnostics, inputs=inputs, native_goal=goal)
    retained = projected["projected_diagnostics"]["complete_same_source_goal_audits"][0]
    for key in workflow.SOURCE5_COMPILED_FEEDBACK_TABLES:
        assert retained[key] == decision[key]
    assert projected["projection_manifest"]["source5_compiled_tables_externalized"] == []
    assert diagnostics == original


def test_creative_kind_never_proves_absence_of_legal_premises(causal_scenario):
    inputs, goal, _, _, _ = new_case(causal_scenario)
    row = next(row for row in goal["claims"] if row["kind"] == "creative_choice")
    row["text"] = "合成反例：人物声称协商解除一律必须由单位先提出。"
    assert workflow.validate_goal_document(goal, inputs=inputs) == goal  # Only fixed verified quotes are local facts.
    request = workflow.prepare_goal_source_audit_request(inputs, profile(), goal)
    actual = final_wire(request)
    assert workflow.evidence_view.reconstruct_goal(actual["native_goal_evidence_view"]) == goal
    source = synthetic_source(goal, request["source_authority_context"], request["source_context_sha256"])
    ref = "C:" + row["id"]
    assert ref in source["no_legal_refs"]
    shape_only = workflow.validate_goal_source_audit(source, goal, context_sha256=request["source_context_sha256"],
        authority_context=request["source_authority_context"])
    assert not shape_only["negative_classification_proven"] and not shape_only["legal_semantic_extraction_proven"]
    add_uncertain_usage(source, goal, ref)
    pending = workflow.validate_goal_source_audit(source, goal, context_sha256=request["source_context_sha256"],
        authority_context=request["source_authority_context"])
    assert not pending["accepted"] and pending["uncertainties"][0]["source_ref"] == ref


def test_actual616_is_only_revision_seed_and_all_original_legal_text_drift_is_rejected():
    paths = [ACTUAL / name for name in ("INPUTS.json", "call_616_goal_plan_28.json", "call_617_goal_source_audit_01.json", "PRODUCTION_FREEZE.json")]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    inputs, goal, receipt = read(paths[0]), read(paths[1])["output"], read(paths[2])
    diagnosis = workflow.diagnose_goal_document(goal, inputs=inputs)
    errors = [row for row in diagnosis["findings"] if row["code"] == "GOAL_FIXED_LEGAL_TEXT_CHANGED"]
    assert len(errors) == 3 and any(row["origin_ref"] == "L001" and "用人单位提出" in row["native_text"] for row in errors)
    with pytest.raises(workflow.goals.GoalContractError): workflow._validate_planning_input(inputs, goal)
    with pytest.raises(workflow.goals.GoalContractError): workflow.prepare_goal_source_audit_request(inputs, profile(), goal)
    with pytest.raises(workflow.goals.GoalContractError):
        workflow.prepare_script_request(inputs, profile(), goal, {}, opening_setup={}, **workflow.origin_ids(inputs))
    with pytest.raises(ValidationError): Draft202012Validator(workflow.build_goal_request_schema(inputs)).validate(goal)
    revision = {**inputs, "previous_complete_document": goal, "revision_diagnostics": {
        "complete_original_rejected_source_report": receipt["output"], "fixed_legal_source_diagnostics": diagnosis,
        "known_complete_original_schema_failure": deepcopy(receipt.get("validation_error"))}}
    planned = workflow.prepare_goal_request(revision, profile())
    actual = final_wire(planned)
    assert actual["previous_complete_document"] == goal
    assert actual["revision_diagnostics"]["complete_original_rejected_source_report"] == receipt["output"]
    assert planned["manifest"]["payload_identity"]["characters"] <= 100000
    assert {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths} == before


def test_actual616_size_only_source5_schema_keeps_every_original_input_and_all_claims():
    from src.content_factory.creative_deepseek_strict_schema_v1 import compile_source_schema_with_manifest
    inputs = read(ACTUAL / "INPUTS.json")
    goal = read(ACTUAL / "call_616_goal_plan_28.json")["output"]
    authority_context = {key: workflow._fixed_legal_context(inputs)[key] for key in ("verified_legal_context", "origin_catalog")}
    # Schema size measurement only; workflow22 refuses this old goal before any source request.
    schema = workflow.source_audit.build_source_schema(goal, authority_context, context_sha256="d" * 64)
    service, manifest = compile_source_schema_with_manifest(schema)
    assert len(service["properties"]["claim_checks"]["properties"]) == len(goal["claims"])
    assert set(schema["properties"]["no_legal_refs"]["items"]["enum"]) == set(workflow.source_audit.build_evidence_catalog(goal))
    assert len(json.dumps(service, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) < 40000
    assert workflow.source_audit.build_evidence_role_catalog(goal)["actual_event_refs"] == list(workflow.source_audit.build_actual_context_catalog(goal))
    assert "interpretation_frame_refs" not in workflow.source_audit.build_evidence_role_catalog(goal)
