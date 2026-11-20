"""Independent finite-reference/native-scope audit. No provider or old guard."""
from copy import deepcopy
import json
from pathlib import Path
import socket

import pytest
from jsonschema import ValidationError

from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
from src.content_factory import creative_goal_context_workflow_v9 as workflow
from src.content_factory import creative_goal_drama_audit_contract_v8 as contract
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("independent audit must not contact provider")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def payload(prepared):
    return json.loads(prepared["request"]["messages"][1]["content"])


def synthetic_drama(goal, context, refs=None):
    catalog = contract.citations.build_evidence_catalog(goal)
    judgment = {"status": "pass", "reason": "Synthetic protocol control, not semantic gold",
        "required_revision": "", "evidence_refs": refs or [next(iter(catalog))],
        "counterexample_analysis": "Synthetic source comparison only", "counterevidence_refs": []}
    return {"schema": contract.DRAMA_AUDIT_VERSION, "goal_sha256": contract.digest(goal),
        "audit_context_sha256": context,
        "goal_checks": {key: deepcopy(judgment) for key in contract.GOAL_CHECKS},
        "scope_observations": {row["id"]: {"audible_speakers": [], "operated_props": []}
                               for row in goal["whole_plan"]["beats"]}}


@pytest.fixture
def audit_scenario(causal_scenario):
    inputs, profile, goal, opening, old_bundle, ids, native = deepcopy(causal_scenario)
    source_request = workflow.prepare_goal_source_audit_request(inputs, profile, goal)
    drama_request = workflow.prepare_goal_drama_audit_request(inputs, profile, goal)
    source = deepcopy(old_bundle["native_source_audit"])
    source["audit_context_sha256"] = contract.digest(payload(source_request))
    drama = synthetic_drama(goal, contract.digest(payload(drama_request)))
    return inputs, profile, goal, opening, contract.build_bundle(source, drama), ids, native


def validate(scenario):
    return workflow.validate_goal_audit(scenario[4], scenario[2], inputs=scenario[0])


def scope_item(goal, *, table, declared=True):
    scopes = contract.build_production_scope_catalog(goal)
    beat = next(iter(scopes["beat_scopes"]))
    ref = scopes["beat_scopes"][beat]["evidence_refs"][0]
    quote = contract.citations.build_evidence_catalog(goal)[ref]["quote"]
    key = "declared_character_id" if table == "audible_speakers" else "declared_prop_id"
    ids = scopes["declared_actor_ids"] if table == "audible_speakers" else scopes["declared_prop_ids"]
    return beat, {"source_ref": ref, "quote": quote, key: ids[0] if declared else None}


def test_finite_catalog_replaces_eight_limit_without_unbounded_or_duplicate_refs(audit_scenario):
    goal = audit_scenario[2]
    catalog = contract.citations.build_evidence_catalog(goal)
    assert len(catalog) > 8
    drama = audit_scenario[4]["native_drama_audit"]
    drama["goal_checks"]["concrete_conflict"]["evidence_refs"] = list(catalog)
    before = deepcopy(drama)
    result = validate(audit_scenario)
    assert result["valid"] and result["accepted"]
    assert drama == before and not result["semantic_truth_deterministically_proven"]
    schema = contract.build_drama_schema(goal, context_sha256=drama["audit_context_sha256"])
    assert schema["$defs"]["evidence_refs"]["maxItems"] == len(catalog)
    assert schema["$defs"]["evidence_refs"]["uniqueItems"]


@pytest.mark.parametrize("fault", ["duplicate", "unknown", "empty"])
def test_refs_still_exact_unique_and_nonempty(audit_scenario, fault):
    refs = audit_scenario[4]["native_drama_audit"]["goal_checks"]["concrete_conflict"]["evidence_refs"]
    refs[:] = refs * 2 if fault == "duplicate" else ["G_NOT_CURRENT"] if fault == "unknown" else []
    with pytest.raises(ValidationError):
        validate(audit_scenario)


@pytest.mark.parametrize("fault", ["pass_revision", "fail_empty_revision", "pass_counterevidence"])
def test_judgment_base_allof_is_retained_with_counterevidence_condition(audit_scenario, fault):
    row = audit_scenario[4]["native_drama_audit"]["goal_checks"]["closed_production_scope"]
    if fault == "pass_revision":
        row["required_revision"] = "Cannot coexist with pass"
    elif fault == "fail_empty_revision":
        row["status"] = "fail"
    else:
        row["counterevidence_refs"] = row["evidence_refs"]
    with pytest.raises(ValidationError):
        validate(audit_scenario)


@pytest.mark.parametrize("table", ["audible_speakers", "operated_props"])
def test_native_scope_compiles_exact_own_beat_quote_and_original_id(audit_scenario, table):
    drama = audit_scenario[4]["native_drama_audit"]
    beat, item = scope_item(audit_scenario[2], table=table)
    drama["scope_observations"][beat][table] = [item]
    original = deepcopy(drama)
    result = validate(audit_scenario)["drama_decision"]
    compiled = result["scope_observation_evidence"][beat][table][0]
    assert compiled["quote"] == item["quote"] and compiled["source_ref"] == item["source_ref"]
    assert compiled["document_path"].startswith("whole_plan.beats.0.")
    assert drama == original and not result["scope_observations_complete_extraction_proven"]


@pytest.mark.parametrize("table", ["audible_speakers", "operated_props"])
@pytest.mark.parametrize("status", ["pass", "fail", "unknown"])
def test_observed_unregistered_entity_cannot_pass_but_honest_fail_unknown_halts(audit_scenario, table, status):
    drama = audit_scenario[4]["native_drama_audit"]
    beat, item = scope_item(audit_scenario[2], table=table, declared=False)
    drama["scope_observations"][beat][table] = [item]
    row = drama["goal_checks"]["closed_production_scope"]
    row.update(status=status, required_revision="Complete new native plan" if status == "fail" else "")
    if status == "pass":
        with pytest.raises(ValueError, match="undeclared"):
            validate(audit_scenario)
    else:
        result = validate(audit_scenario)
        assert result["valid"] and not result["accepted"]
        assert bool(result["uncertainties"]) == (status == "unknown")
        inputs, profile, goal, opening, bundle, ids, _ = audit_scenario
        with pytest.raises(ValueError, match="must pass"):
            workflow.prepare_script_request(inputs, profile, goal, bundle, opening_setup=opening, **ids)


@pytest.mark.parametrize("fault", ["crossbeat", "wrongquote", "missingbeat", "extra_beat", "foreign_id", "duplicate_item"])
def test_scope_observations_cannot_forge_source_or_coverage(audit_scenario, fault):
    drama, goal = audit_scenario[4]["native_drama_audit"], audit_scenario[2]
    beat, item = scope_item(goal, table="audible_speakers")
    drama["scope_observations"][beat]["audible_speakers"] = [item]
    if fault == "crossbeat":
        scopes = contract.build_production_scope_catalog(goal)
        other = list(scopes["beat_scopes"])[1]
        item["source_ref"] = scopes["beat_scopes"][other]["evidence_refs"][0]
        item["quote"] = contract.citations.build_evidence_catalog(goal)[item["source_ref"]]["quote"]
    elif fault == "wrongquote":
        item["quote"] = "NO SUCH WORDS IN THE NATIVE LEAF"
    elif fault == "missingbeat":
        drama["scope_observations"].pop(beat)
    elif fault == "extra_beat":
        drama["scope_observations"]["b_foreign"] = {"audible_speakers": [], "operated_props": []}
    elif fault == "foreign_id":
        item["declared_character_id"] = "not_registered"
    else:
        drama["scope_observations"][beat]["audible_speakers"].append(deepcopy(item))
    with pytest.raises((ValidationError, ValueError)):
        validate(audit_scenario)


@pytest.mark.parametrize("fault", ["goal", "source_context", "drama_context", "old_bundle", "missing_source"])
def test_same_source_bundle_identity_is_not_convertible_or_mixable(audit_scenario, fault):
    bundle = audit_scenario[4]
    if fault == "goal":
        bundle["native_drama_audit"]["goal_sha256"] = "f" * 64
    elif fault.endswith("context"):
        part = "native_source_audit" if fault.startswith("source") else "native_drama_audit"
        bundle[part]["audit_context_sha256"] = "f" * 64
    elif fault == "old_bundle":
        bundle["schema"] = "creative_goal_context_workflow/v7/audit_bundle"
    else:
        bundle.pop("native_source_audit")
    with pytest.raises((ValueError, ValidationError)):
        validate(audit_scenario)


def test_actual_new_bundle_reaches_author_wire_without_audit_pass_prompt_or_old_protocol(audit_scenario):
    inputs, profile, goal, opening, bundle, ids, _ = audit_scenario
    author = workflow.prepare_script_request(inputs, profile, goal, bundle, opening_setup=opening, **ids)
    assert author["wire"] == expected_wire_request(author["request"])
    assert author["request_sha256"] == workflow.digest(author["request"])
    proof = author["request"]["input_provenance"]
    assert proof["native_drama_audit_sha256"] == workflow.digest(bundle["native_drama_audit"])
    assert proof["native_goal_audit_bundle_version"] == contract.BUNDLE_VERSION
    assert payload(author)["native_goal_document"] == goal
    assert payload(author)["native_opening_setup_document"] == opening
    assert "native_drama_audit" not in payload(author) and "native_source_audit" not in payload(author)
    assert not author["dispatch_performed"]
    assert workflow._validate_planning_input is workflow.audit_contexts._validate_planning_input


def test_new_drama_actual_wire_contains_exact_native_scope_and_bounded_schema(audit_scenario):
    inputs, profile, goal, *_ = audit_scenario
    request = workflow.prepare_goal_drama_audit_request(inputs, profile, goal)
    actual = payload(request)
    assert actual["native_goal_document"] == goal
    assert actual["production_scope_catalog"] == contract.build_production_scope_catalog(goal)
    assert request["wire"] == expected_wire_request(request["request"])
    assert request["request_sha256"] == workflow.digest(request["request"])
    assert request["request"]["structured_schema"]["properties"]["audit_context_sha256"]["const"] == workflow.digest(actual)
    assert "不超过8" not in request["request"]["messages"][0]["content"]
    assert request["manifest"]["reference_occurrences"] == 1


def test_all_seven_actual_stages_bind_current_manifest_after_workflow_marker(audit_scenario):
    inputs, profile, goal, opening, bundle, ids, native = audit_scenario
    author = workflow.prepare_script_request(inputs, profile, goal, bundle, opening_setup=opening, **ids)
    requests = [workflow.prepare_goal_request(inputs, profile),
        workflow.prepare_goal_source_audit_request(inputs, profile, goal),
        workflow.prepare_goal_drama_audit_request(inputs, profile, goal),
        workflow.prepare_opening_setup_request(inputs, profile, goal), author,
        workflow.prepare_full_review_part_request(inputs, profile, native, author["views"], "semantic"),
        workflow.prepare_full_review_part_request(inputs, profile, native, author["views"], "physical")]
    for request in requests:
        provenance = request["request"]["input_provenance"]
        assert provenance["workflow_version"] == workflow.VERSION
        assert request["manifest"]["workflow_version"] == workflow.VERSION
        assert provenance["context_manifest_sha256"] == workflow.digest(request["manifest"])
        assert request["wire"] == expected_wire_request(request["request"])
        assert request["request_sha256"] == workflow.digest(request["request"])


def test_actual_556_stays_rejected_without_native_scope_response_and_original_files_stay_identical():
    root = Path("data/production_trials/goal_context_text_production_20261013/round_08")
    paths = [root / "call_554_goal_plan_12.json", root / "call_556_goal_drama_audit_02.json"]
    before = [p.read_bytes() for p in paths]
    goal, receipt = json.loads(before[0])["output"], json.loads(before[1])
    assert receipt["status"] == "contract_rejected" and receipt["output"]["goal_checks"]["closed_production_scope"]["status"] == "pass"
    with pytest.raises(ValidationError):
        contract.validate_drama(receipt["output"], goal, context_sha256=receipt["output"]["audit_context_sha256"])
    assert len(contract.citations.build_evidence_catalog(goal)) == 106
    assert "主管" in goal["whole_plan"]["beats"][2]["stimulus"]
    # A new synthetic negative response is not a conversion of556 to success.
    response = synthetic_drama(goal, "a" * 64)
    response["scope_observations"]["b3"]["audible_speakers"] = [{"source_ref": "G023",
        "quote": "主管在那边只问了一句：明天这个人上不上班，你一句话回我。", "declared_character_id": None}]
    with pytest.raises(ValueError, match="undeclared"):
        contract.validate_drama(response, goal, context_sha256="a" * 64)
    response["goal_checks"]["closed_production_scope"].update(status="fail", required_revision="Complete native replacement")
    rejected = contract.validate_drama(response, goal, context_sha256="a" * 64)
    assert rejected["valid"] and not rejected["accepted"]
    assert [p.read_bytes() for p in paths] == before
