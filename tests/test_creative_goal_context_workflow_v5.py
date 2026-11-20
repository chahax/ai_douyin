"""Split native audit fixtures prove contracts, not production creative quality."""
from copy import deepcopy
import json

import pytest
from jsonschema import ValidationError

from src.content_factory import creative_goal_context_workflow_v5 as workflow
from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
from tests.test_creative_goal_context_workflow_v3 import scenario as prior_scenario


@pytest.fixture
def scenario(prior_scenario):
    inputs, profile, goal, _, ids, native_script = prior_scenario
    source = workflow.prepare_goal_source_audit_request(inputs, profile, goal)
    drama = workflow.prepare_goal_drama_audit_request(inputs, profile, goal)
    row = {"status": "pass", "reason": "合成合同判断，不是生产质量结论", "required_revision": ""}
    source_doc = {"schema": workflow.SOURCE_AUDIT_VERSION, "goal_sha256": workflow.digest(goal),
        "audit_context_sha256": workflow.digest(payload(source)),
        "claim_checks": {claim["id"]: deepcopy(row) for claim in goal["claims"]}}
    ref = next(iter(workflow.citations.build_evidence_catalog(goal)))
    drama_doc = {"schema": workflow.DRAMA_AUDIT_VERSION, "goal_sha256": workflow.digest(goal),
        "audit_context_sha256": workflow.digest(payload(drama)),
        "goal_checks": {key: {**deepcopy(row), "evidence_refs": [ref]} for key in workflow.GOAL_CHECKS}}
    return inputs, profile, goal, ids, native_script, source, drama, workflow.build_goal_audit_bundle(source_doc, drama_doc)


def payload(prepared):
    return json.loads(prepared["request"]["messages"][1]["content"])


def validate(scenario, bundle=None):
    inputs, _, goal, *rest = scenario
    return workflow.validate_goal_audit(bundle if bundle is not None else scenario[-1], goal, inputs=inputs)


def test_actual_payloads_separate_source_authority_from_complete_drama(scenario):
    inputs, _, goal, _, _, source, drama, _ = scenario
    source_payload, drama_payload = payload(source), payload(drama)
    assert set(source_payload) == {"source_packet", "verified_legal_context", "user_goal_contract",
        "origin_catalog", "native_goal_claims", "native_goal_sha256"}
    assert source_payload["native_goal_claims"] == goal["claims"]
    assert "whole_plan" not in json.dumps(source_payload)
    assert set(drama_payload) == {"native_goal_document", "reference_fulltext", "user_goal_contract",
        "production_preferences", "goal_check_criteria", "goal_evidence_catalog"}
    assert drama_payload["native_goal_document"] == goal
    assert drama_payload["reference_fulltext"] == inputs["reference_fulltext"]
    assert source["manifest"]["reference_occurrences"] == 0
    assert drama["manifest"]["reference_occurrences"] == 1
    assert all(set(row) == {"document_path"} for row in drama_payload["goal_evidence_catalog"].values())
    assert "source_quote" not in json.dumps(source_payload) + json.dumps(drama_payload)
    assert "expression_standard" not in source_payload and "expression_standard" not in drama_payload
    for key in ("facts", "sources"):
        assert source_payload["verified_legal_context"][key] == inputs["verified_legal_context"][key]


def test_wire_identities_are_distinct_but_native_goal_matches(scenario):
    _, _, goal, _, _, source, drama, _ = scenario
    assert payload(source) != payload(drama)
    for prepared in (source, drama):
        request = prepared["request"]
        assert request["stage"] == "goal_audit" and request["role"] == "director"
        assert request["structured_schema"]["properties"]["goal_sha256"]["const"] == workflow.digest(goal)
        assert request["structured_schema"]["properties"]["audit_context_sha256"]["const"] == workflow.digest(payload(prepared))
        assert request["input_provenance"]["workflow_version"] == workflow.VERSION
        assert prepared["wire"] == expected_wire_request(request)
        assert prepared["request_sha256"] == workflow.digest(request)
        assert not prepared["dispatch_performed"] and prepared["sdk_max_retries"] == 0
    assert workflow.digest(payload(source)) != workflow.digest(payload(drama))


def test_bundle_combines_original_decisions_without_modifying_native_documents(scenario):
    before = deepcopy(scenario)
    result = validate(scenario)
    assert result["valid"] and result["accepted"] and result["combined_decisions_only"]
    assert not result["native_review_modified"] and not result["human_approved"]
    assert not result["semantic_truth_deterministically_proven"]
    assert scenario == before
    assert result["source_decision"]["audit_sha256"] == workflow.digest(scenario[-1]["native_source_audit"])
    assert result["drama_decision"]["audit_sha256"] == workflow.digest(scenario[-1]["native_drama_audit"])


@pytest.mark.parametrize("alter", ["missing_source", "missing_drama", "old_schema", "hand_pass", "source_extra_table", "drama_extra_table",
    "missing_claim", "extra_claim", "missing_goal", "extra_goal", "wrong_goal", "source_context_swap", "drama_context_swap", "bad_ref", "too_many_refs", "pass_revision"])
def test_incomplete_old_or_fabricated_native_audits_are_rejected(scenario, alter):
    bundle = deepcopy(scenario[-1])
    source, drama = bundle["native_source_audit"], bundle["native_drama_audit"]
    if alter == "missing_source": bundle.pop("native_source_audit")
    elif alter == "missing_drama": bundle.pop("native_drama_audit")
    elif alter == "old_schema": bundle["schema"] = "creative_goal_audit_citation/v1"
    elif alter == "hand_pass": bundle["accepted"] = True
    elif alter == "source_extra_table": source["goal_checks"] = {}
    elif alter == "drama_extra_table": drama["claim_checks"] = {}
    elif alter == "missing_claim": source["claim_checks"].pop(next(iter(source["claim_checks"])))
    elif alter == "extra_claim": source["claim_checks"]["invented"] = deepcopy(next(iter(source["claim_checks"].values())))
    elif alter == "missing_goal": drama["goal_checks"].pop(workflow.GOAL_CHECKS[0])
    elif alter == "extra_goal": drama["goal_checks"]["invented"] = deepcopy(next(iter(drama["goal_checks"].values())))
    elif alter == "wrong_goal": drama["goal_sha256"] = "f" * 64
    elif alter == "source_context_swap": source["audit_context_sha256"] = drama["audit_context_sha256"]
    elif alter == "drama_context_swap": drama["audit_context_sha256"] = source["audit_context_sha256"]
    elif alter == "bad_ref": drama["goal_checks"][workflow.GOAL_CHECKS[0]]["evidence_refs"] = ["invented"]
    elif alter == "too_many_refs": drama["goal_checks"][workflow.GOAL_CHECKS[0]]["evidence_refs"] = list(workflow.citations.build_evidence_catalog(scenario[2]))[:9]
    elif alter == "pass_revision": next(iter(source["claim_checks"].values()))["required_revision"] = "无需修改"
    before = deepcopy(bundle)
    with pytest.raises((ValueError, ValidationError)):
        validate(scenario, bundle)
    assert bundle == before


@pytest.mark.parametrize("kind,status", [(kind, status) for kind in ("source", "drama") for status in ("fail", "unknown")])
def test_each_native_semantic_failure_or_unknown_blocks_author(scenario, kind, status):
    inputs, profile, goal, ids, _, _, _, original = scenario
    bundle = deepcopy(original)
    rows = bundle["native_" + kind + "_audit"]["claim_checks" if kind == "source" else "goal_checks"]
    row = next(iter(rows.values()))
    row.update(status=status, required_revision="完整规划须修正当前来源或因果缺口" if status == "fail" else "")
    decision = validate(scenario, bundle)
    assert not decision["accepted"]
    assert bool(decision["findings"]) == (status == "fail")
    assert bool(decision["uncertainties"]) == (status == "unknown")
    with pytest.raises(ValueError, match="both native"):
        workflow.prepare_script_request(inputs, profile, goal, bundle, **ids)


def test_fail_requires_a_specific_nonblank_complete_revision(scenario):
    bundle = deepcopy(scenario[-1])
    row = next(iter(bundle["native_source_audit"]["claim_checks"].values()))
    row.update(status="fail", required_revision="  ")
    with pytest.raises(ValidationError): validate(scenario, bundle)


def test_native_goal_change_invalidates_both_audits(scenario):
    inputs, _, goal, *rest = scenario
    altered = deepcopy(goal)
    altered["whole_plan"]["premise"] += " changed native plan"
    with pytest.raises(ValidationError):
        workflow.validate_goal_audit(scenario[-1], altered, inputs=inputs)


def test_author_request_binds_each_native_audit_and_keeps_goal_complete(scenario):
    inputs, profile, goal, ids, native, _, _, bundle = scenario
    prepared = workflow.prepare_script_request(inputs, profile, goal, bundle, **ids)
    body = payload(prepared)
    provenance = prepared["request"]["input_provenance"]
    assert body["native_goal_document"] == goal
    assert provenance["native_source_audit_sha256"] == workflow.digest(bundle["native_source_audit"])
    assert provenance["native_drama_audit_sha256"] == workflow.digest(bundle["native_drama_audit"])
    assert provenance["goal_audit_sha256"] == workflow.digest(bundle)
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    assert workflow.validate_script_document(native, prepared["views"], inputs["production_preferences"])["necessary_conditions_only"]


def test_script_revision_does_not_change_unchanged_source_or_drama_audit_authority(scenario):
    inputs, profile, goal, ids, native, _, _, bundle = scenario
    repaired_inputs = {**deepcopy(inputs), "previous_complete_document": native,
        "revision_diagnostics": {"full_review": "known full native failure"}}
    assert workflow.validate_goal_audit(bundle, goal, inputs=repaired_inputs)["accepted"]
    prepared = workflow.prepare_script_request(repaired_inputs, profile, goal, bundle, **ids)
    assert payload(prepared)["previous_complete_document"] == native


@pytest.mark.parametrize("changed", ["user", "law"])
def test_changed_actual_user_or_legal_authority_cannot_reuse_bundle(scenario, changed):
    inputs, _, goal, *rest = scenario
    altered = deepcopy(inputs)
    if changed == "user":
        altered["user_goal_contract"]["constraints"][0]["text"] += " changed authority"
    else:
        altered["verified_legal_context"]["facts"][0]["paraphrase"] += " changed authority"
    with pytest.raises(ValidationError):
        workflow.validate_goal_audit(scenario[-1], goal, inputs=altered)


def test_full_review_identity_still_binds_actual_projected_law(scenario):
    inputs, profile, goal, ids, native, _, _, bundle = scenario
    prepared = workflow.prepare_script_request(inputs, profile, goal, bundle, **ids)
    reviewed = workflow.prepare_full_review_request(inputs, profile, native, prepared["views"])
    assert reviewed["review_legal_context"] == payload(reviewed)["verified_legal_context"]
    assert reviewed["wire"] == expected_wire_request(reviewed["request"])
    assert reviewed["request"]["input_provenance"]["workflow_version"] == workflow.VERSION
