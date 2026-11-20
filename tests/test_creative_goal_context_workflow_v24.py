"""Offline ownership checks; synthetic native judgments are not creative passes."""
from copy import deepcopy
import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from src.content_factory import creative_goal_context_workflow_v24 as w
from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
from tests.test_creative_goal_context_workflow_v23 import offline
from tests.test_creative_goal_context_workflow_v22 import new_case
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests.test_creative_goal_context_workflow_v15 import synthetic_focused
from tests.test_creative_goal_legal_usage_source_audit_v6 import synthetic_source, add_uncertain_usage

PROJECT = Path(__file__).resolve().parents[1]


def contract():
    result = {"contract_version": "creative_goal_source_v2/user_goals", "constraints": [], "audience_goals": [],
        "planning_rules": [{"id": "RG_TYPED_ORIGIN", "text": "来源与虚构分开，不证明语义真值。"}],
        "division_of_work": {"whole_plan": "因果与情绪", "complete_script": "完整对白与行为"},
        "limitations": ["Synthetic fixture, not a user adoption or production source."]}
    for identifier, row in w.REQUIREMENTS.items():
        result[row["table"]].append({"id": identifier, "text": row["text"], "source_quote": row["source_quote"]})
    return result


def profile():
    return json.loads((PROJECT / "config/creative_goal_context_model_profile_v7.json").read_text("utf-8-sig"))


def payload(prepared):
    return json.loads(prepared["request"]["messages"][1]["content"])


def case(scenario):
    """New synthetic goal only. Never repairs or adopts the actual621 output."""
    inputs, goal, opening, _, native = new_case(scenario)
    inputs["user_goal_contract"] = contract()
    projected = w.project_inputs(inputs)
    old_user = {row["id"]: row["kind"] for row in goal["claims"] if row["kind"].startswith("user_")}
    replacements, new = {}, []
    for table, kind in (("constraints", "user_constraint"), ("audience_goals", "user_audience_goal")):
        for index, row in enumerate(projected["user_goal_contract"][table]):
            new.append({"id": ("UC.n" if table == "constraints" else "UG.n") + str(index), "kind": kind,
                "text": row["text"], "origin_ids": [row["id"]]})
        target = next(row["id"] for row in new if row["kind"] == kind)
        replacements.update({key: target for key, value in old_user.items() if value == kind})
    def remap(value):
        if isinstance(value, list):
            return list(dict.fromkeys(replacements.get(item, item) for item in value))
        return value
    goal["claims"] = [row for row in goal["claims"] if row["id"] not in old_user] + new
    for row in goal["claims"]:
        if "basis_claim_refs" in row:
            row["basis_claim_refs"] = remap(row["basis_claim_refs"])
    for row in [goal["whole_plan"]["audience_path"], *goal["whole_plan"]["beats"], goal["whole_plan"]["ending"]]:
        row["claim_refs"] = remap(row["claim_refs"])
    opening["goal_sha256"] = w.digest(goal)
    return inputs, goal, opening, w.origin_ids(inputs), native


def bundle(inputs, goal):
    source_req = w.prepare_goal_source_audit_request(inputs, profile(), goal)
    drama_req = w.prepare_goal_drama_audit_request(inputs, profile(), goal)
    commitment_req = w.prepare_goal_commitment_audit_request(inputs, profile(), goal)
    source = synthetic_source(goal, source_req["source_authority_context"], w.digest(payload(source_req)))
    first = next(ref for ref in w.drama_contract.build_evidence_catalog(goal) if ref.startswith("G"))
    row = {"status": "pass", "reason": "Synthetic only", "required_revision": "", "evidence_refs": [first],
        "counterexample_analysis": "Synthetic comparison only", "counterevidence_refs": []}
    drama = {"schema": w.DRAMA_AUDIT_VERSION, "goal_sha256": w.digest(goal),
        "audit_context_sha256": w.digest(payload(drama_req)), "goal_checks": {key: deepcopy(row) for key in w.GOAL_CHECKS},
        "scope_observations": {ref: {"audible_speakers": [], "operated_props": []}
            for ref in w.drama_contract.build_scope_source_catalog(goal)}, "closed_scope_findings": []}
    focused = synthetic_focused(w.project_inputs(inputs), goal)
    focused["audit_context_sha256"] = w.digest(payload(commitment_req))
    return w.build_goal_audit_bundle(source, drama, focused)


def check_wire(prepared, inputs):
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    assert prepared["request_sha256"] == w.digest(prepared["request"])
    assert prepared["manifest"]["workflow_version"] == w.VERSION
    assert prepared["manifest"]["payload_identity"] == w.contexts._measure(payload(prepared))
    assert prepared["request"]["input_provenance"]["context_manifest_sha256"] == w.digest(prepared["manifest"])
    assert prepared["manifest"]["requirement_ownership"] == w.ownership_evidence(inputs)
    assert prepared["request"]["input_provenance"]["requirement_ownership_sha256"] == w.digest(w.ownership_evidence(inputs))
    assert prepared["sdk_max_retries"] == 0 and not prepared["dispatch_performed"]
    assert prepared["manifest"]["structured_schema_sha256"] == w.digest(prepared["request"]["structured_schema"])


def test_exact_ownership_is_lossless_idempotent_and_not_narrative_process_claims():
    inputs = {"user_goal_contract": contract(), "kept": "all other input fields unchanged"}
    before = deepcopy(inputs)
    projected = w.project_inputs(inputs)
    user = projected["user_goal_contract"]
    assert inputs == before and w.project_inputs(projected) == projected
    assert w.original_user_goal_contract(projected) == inputs["user_goal_contract"]
    assert user["requirement_ownership"]["original_user_goal_contract_sha256"] == w.digest(inputs["user_goal_contract"])
    assert {row["id"] for row in user["constraints"]} == {
        "UC_REFERENCE_MECHANISM", "UC_NARRATIVE_ACTION", "UC_CONFIRMED_SUPERMARKET_DIRECTION"}
    assert {row["id"] for row in user["execution_requirements"]} == {
        "UC_COMPLETE_NATIVE", "UC_REFERENCE_MECHANISM", "UC_AUTONOMOUS_NATIVE"}
    reference = next(row for row in user["constraints"] if row["id"] == "UC_REFERENCE_MECHANISM")
    assert reference["text"] == "借鉴参考片的表达机制，不照搬剧情。"
    assert reference["source_quote"] == w.REQUIREMENTS[reference["id"]]["source_quote"]
    assert user["planning_rules"] == inputs["user_goal_contract"]["planning_rules"]
    assert not user["requirement_ownership"]["execution_compliance_proven"]


@pytest.mark.parametrize("fault", ["unknown_id", "changed_text", "changed_quote", "deleted", "duplicate", "unmapped_top_level",
    "changed_projection", "changed_original", "changed_hash", "execution_dropped", "partial_projection"])
def test_unknown_changed_or_tampered_requirements_cannot_be_silently_projected(fault):
    inputs = {"user_goal_contract": contract()}
    if fault in {"changed_projection", "changed_original", "changed_hash", "execution_dropped", "partial_projection"}:
        inputs = w.project_inputs(inputs)
    user = inputs["user_goal_contract"]
    if fault == "unknown_id": user["constraints"][0]["id"] = "UC_NEW_UNCLASSIFIED"
    elif fault == "changed_text": user["constraints"][0]["text"] += "新含义"
    elif fault == "changed_quote": user["constraints"][0]["source_quote"] += "新批准"
    elif fault == "deleted": user["constraints"].pop()
    elif fault == "duplicate": user["constraints"].append(deepcopy(user["constraints"][0]))
    elif fault == "unmapped_top_level": user["new_requirements"] = ["不可丢掉"]
    elif fault == "changed_projection": user["constraints"][0]["text"] += "新含义"
    elif fault == "changed_original": user["requirement_ownership"]["mappings"][0]["original_row_sha256"] = "0" * 64
    elif fault == "changed_hash": user["requirement_ownership"]["original_user_goal_contract_sha256"] = "0" * 64
    elif fault == "execution_dropped": user["execution_requirements"].pop()
    else: user.pop("execution_requirements")
    before = deepcopy(inputs)
    with pytest.raises(w.OwnershipError): w.project_inputs(inputs)
    assert inputs == before


def test_request_discloses_existing_choice_gate_and_optional_law_selection(causal_scenario):
    inputs, goal, _, _, _ = case(causal_scenario)
    prepared = w.prepare_goal_request(inputs, profile())
    check_wire(prepared, inputs)
    actual = payload(prepared)
    assert actual["user_goal_contract"] == w._fixed_legal_context(inputs)["user_goal_contract"]
    assert actual["reference_fulltext"] == inputs["reference_fulltext"]
    assert actual["verified_legal_context"] == w._fixed_legal_context(inputs)["verified_legal_context"]
    assert prepared["request"]["structured_schema"] == w.build_goal_request_schema(inputs)
    assert w.CHOICE_RULE + w.LAW_SELECTION_RULE in prepared["wire"]["messages"][0]["content"]
    fields = prepared["request"]["structured_schema"]["properties"]["whole_plan"]["properties"]
    assert "creative_choice" in fields["beats"]["items"]["properties"]["claim_refs"]["description"]
    assert "creative_choice" in fields["ending"]["properties"]["claim_refs"]["description"]
    Draft202012Validator(prepared["request"]["structured_schema"]).validate(goal)
    assert w.validate_goal_document(goal, inputs=inputs) == goal


def test_actual621_is_diagnosed_without_being_repaired_or_adopted():
    root = PROJECT / "data/production_trials/fresh_source_text_session_20261015/round_01"
    paths = [root / name for name in ("call_621_whole_plan_01.json", "INPUTS.json", "PRODUCTION_FREEZE.json")]
    original = {str(path): path.read_bytes() for path in paths}
    receipt, inputs = [json.loads(original[str(path)]) for path in paths[:2]]
    native = deepcopy(receipt["output"])
    diagnosis = w.diagnose_goal_document(native, inputs=inputs)
    assert len([row for row in diagnosis["findings"] if row["code"] == "GOAL_DRAMATIC_CHOICE_UNTRACED"]) == 5
    assert any(row["code"] == "GOAL_ORIGIN_CLASS_MISMATCH" and row.get("reference") == "UC_COMPLETE_NATIVE"
        for row in diagnosis["findings"])
    assert native == receipt["output"] and not diagnosis["valid"]
    assert {str(path): path.read_bytes() for path in paths} == original


def test_all_actual_preparations_share_one_projection_and_current_native_audits(causal_scenario):
    inputs, goal, opening, ids, native = case(causal_scenario)
    before = deepcopy((inputs, goal, opening, native))
    audit = bundle(inputs, goal)
    assert w.validate_goal_audit(audit, goal, inputs=inputs)["accepted"]
    authored = w.prepare_script_request(inputs, profile(), goal, audit, opening_setup=opening, **ids)
    prepared = [w.prepare_goal_request(inputs, profile()),
        w.prepare_goal_source_audit_request(inputs, profile(), goal),
        w.prepare_goal_drama_audit_request(inputs, profile(), goal),
        w.prepare_goal_commitment_audit_request(inputs, profile(), goal),
        w.prepare_opening_setup_request(inputs, profile(), goal), authored]
    prepared.extend(w.prepare_full_review_part_request(inputs, profile(), native, authored["views"], part)
        for part in ("semantic", "physical"))
    for request in prepared:
        check_wire(request, inputs)
        actual = payload(request)
        if "user_goal_contract" in actual:
            assert actual["user_goal_contract"] == w._fixed_legal_context(inputs)["user_goal_contract"]
        assert request["request_sha256"] == w.digest(request["request"])
    source_req = prepared[1]
    assert w.validate_goal_source_audit(audit["native_source_audit"], goal, inputs=inputs,
        context_sha256=source_req["source_context_sha256"])["accepted"]
    assert w.source_audit.VERSION == w.prior.SOURCE_AUDIT_VERSION
    assert (inputs, goal, opening, native) == before


@pytest.mark.parametrize("fault", ["missing_narrative", "missing_choice", "law_drift", "old_user_ids", "missing_audit"])
def test_new_projection_does_not_relax_narrative_law_or_three_audit_admission(causal_scenario, fault):
    inputs, goal, opening, ids, native = case(causal_scenario)
    audit = bundle(inputs, goal)
    if fault == "missing_narrative":
        row = next(row for row in goal["claims"] if row.get("origin_ids") == ["UC_NARRATIVE_ACTION"])
        row["origin_ids"] = ["UC_REFERENCE_MECHANISM"]
    elif fault == "missing_choice":
        beat = goal["whole_plan"]["beats"][0]
        beat["claim_refs"] = [next(row["id"] for row in goal["claims"] if row["kind"] == "user_constraint")]
    elif fault == "law_drift": next(row for row in goal["claims"] if row["kind"] == "verified_legal")["text"] += "丢掉条件"
    elif fault == "old_user_ids": ids["user_constraint_ids"].append("UC_AUTONOMOUS_NATIVE")
    else: audit.pop("native_commitment_audit")
    with pytest.raises(ValueError):
        w.prepare_script_request(inputs, profile(), goal, audit, opening_setup=opening, **ids)


def test_single_relevant_law_is_allowed_but_fixed_text_and_source6_unknown_still_block(causal_scenario):
    inputs, goal, opening, ids, native = case(causal_scenario)
    legal = [row for row in goal["claims"] if row["kind"] == "verified_legal"]
    assert len(legal) < len(w._fixed_legal_context(inputs)["verified_legal_context"]["facts"])
    assert w.validate_goal_document(goal, inputs=inputs) == goal
    audit = bundle(inputs, goal)
    ref = next(ref for ref in audit["native_source_audit"]["speech_act_by_ref"] if ref.startswith("G"))
    add_uncertain_usage(audit["native_source_audit"], goal, ref)
    with pytest.raises(ValueError):
        w.prepare_script_request(inputs, profile(), goal, audit, opening_setup=opening, **ids)


@pytest.mark.parametrize("stage", ["source", "drama", "commitment", "setup", "semantic", "physical"])
@pytest.mark.parametrize("fault", ["missing_narrative", "law_drift"])
def test_each_outbound_stage_rechecks_projected_narrative_and_fixed_law(causal_scenario, stage, fault):
    inputs, goal, opening, ids, native = case(causal_scenario)
    views = w.compile_native_views(goal, opening, **ids)
    if fault == "missing_narrative":
        row = next(row for row in goal["claims"] if row.get("origin_ids") == ["UC_NARRATIVE_ACTION"])
        row["origin_ids"] = ["UC_REFERENCE_MECHANISM"]
    else:
        next(row for row in goal["claims"] if row["kind"] == "verified_legal")["text"] += "无条件生效"
    before = deepcopy(goal)
    if stage in ("source", "drama", "commitment"):
        action = lambda: getattr(w, "prepare_goal_" + stage + "_audit_request")(inputs, profile(), goal)
    elif stage == "setup":
        action = lambda: w.prepare_opening_setup_request(inputs, profile(), goal)
    else:
        views["goal"] = goal
        action = lambda: w.prepare_full_review_part_request(inputs, profile(), native, views, stage)
    with pytest.raises(ValueError): action()
    assert goal == before


def test_actual_new_session_and_driver_workflow_exports_are_complete():
    exports = set()
    for name in ("creative_fresh_source_session_v2.py", "creative_session_text_driver_v1.py"):
        tree = ast.parse((PROJECT / "scripts" / name).read_text("utf8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and (
                isinstance(node.value, ast.Name) and node.value.id == "wf"
                or isinstance(node.value, ast.Attribute) and node.value.attr == "wf"
                and isinstance(node.value.value, ast.Name) and node.value.value.id == "self"
            ):
                exports.add(node.attr)
    exports.update("prepare_goal_" + kind + "_audit_request" for kind in ("source", "drama", "commitment"))
    exports.update("validate_goal_" + kind + "_audit" for kind in ("source", "drama", "commitment"))
    for name in exports:
        assert hasattr(w, name), "Actual session/driver workflow export missing: " + name
    assert w.validate_opening_setup_document is w.prior.validate_opening_setup_document
    assert w.windows.VERSION == w.prior.windows.VERSION
    assert w.commitment_audit.VERSION == w.prior.commitment_audit.VERSION


def test_actual_opening_driver_executes_real_workflow_validator_without_provider(causal_scenario, tmp_path):
    from scripts import creative_session_text_driver_v1 as driver
    inputs, goal, opening, ids, native = case(causal_scenario)
    called = []
    def local_invoke(runtime, label, prepared, validator):
        check_wire(prepared, inputs)
        validated = validator(deepcopy(opening))
        assert validated["valid"] and validated["native_setup_sha256"] == w.digest(opening)
        called.append(label)
        return {"status": "contract_valid", "output": deepcopy(opening)}
    session = SimpleNamespace(wf=w, profile=profile(), root=tmp_path, invoke=local_invoke,
        known=lambda receipt, stage, **kw: receipt["output"])
    assert driver.opening(session, None, inputs, goal) == opening
    assert called == ["opening_setup_01"]
    assert json.loads((tmp_path / "setup/NATIVE_01.json").read_text("utf8")) == opening
