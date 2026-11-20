"""Finite exact references and same-native scope evidence, offline only.

New-shaped responses below are fresh synthetic fixtures, not converted provider
responses or aesthetic gold examples. The original 554/555/556 files stay intact.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

from jsonschema import ValidationError
import pytest

from src.content_factory import creative_goal_drama_audit_contract_v8 as audit

ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / "data/production_trials/goal_context_text_production_20261013/round_08"
SOURCE_CONTEXT = "1" * 64
DRAMA_CONTEXT = "2" * 64


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("offline contract tests cannot call a provider")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


@pytest.fixture
def goal():
    return json.loads((ROUND / "goals/native_02.json").read_bytes())


def synthetic_drama(goal):
    first = next(iter(audit.citations.build_evidence_catalog(goal)))
    judgment = {"status": "pass", "reason": "合成合同夹具，不是创作质量结论", "required_revision": "",
                "evidence_refs": [first], "counterexample_analysis": "仅测试原生字段与反例证据绑定，不证明语义",
                "counterevidence_refs": []}
    return {"schema": audit.DRAMA_AUDIT_VERSION, "goal_sha256": audit.digest(goal),
            "audit_context_sha256": DRAMA_CONTEXT,
            "goal_checks": {key: deepcopy(judgment) for key in audit.GOAL_CHECKS},
            "scope_observations": {beat["id"]: {"audible_speakers": [], "operated_props": []}
                                   for beat in goal["whole_plan"]["beats"]}}


def synthetic_source(goal):
    judgment = {"status": "pass", "reason": "合成来源结构夹具，不证明来源实义", "required_revision": ""}
    return {"schema": audit.SOURCE_AUDIT_VERSION, "goal_sha256": audit.digest(goal),
            "audit_context_sha256": SOURCE_CONTEXT,
            "claim_checks": {claim["id"]: deepcopy(judgment) for claim in goal["claims"]}}


def validate(document, goal):
    return audit.validate_drama(document, goal, context_sha256=DRAMA_CONTEXT)


def scope_item(goal, beat_id, *, declared=None, prop=False):
    catalog = audit.citations.build_evidence_catalog(goal)
    ref = audit.build_production_scope_catalog(goal)["beat_scopes"][beat_id]["evidence_refs"][0]
    return {"source_ref": ref, "quote": catalog[ref]["quote"],
            "declared_prop_id" if prop else "declared_character_id": declared}


def set_scope_failure(document, status="fail"):
    document["goal_checks"]["closed_production_scope"].update(
        status=status, required_revision="由模型完整新规划修正未登记范围" if status == "fail" else "")


def test_limit_tracks_the_actual_finite_catalog_and_preserves_judgment_conditions(goal):
    schema = audit.build_drama_schema(goal, context_sha256=DRAMA_CONTEXT)
    refs = schema["$defs"]["evidence_refs"]
    assert len(audit.citations.build_evidence_catalog(goal)) == 106
    assert refs["maxItems"] == len(refs["items"]["enum"]) == 106
    assert refs["minItems"] == 1 and refs["uniqueItems"]
    judgment = schema["$defs"]["goal_judgment"]
    assert judgment["allOf"][:2] == audit.citations._judgment()["allOf"]
    assert len(judgment["allOf"]) == 3
    assert judgment["properties"]["counterevidence_refs"]["maxItems"] == 106
    assert schema["additionalProperties"] is False
    assert "scope_observations" in schema["required"]


def test_new_synthetic_10_17_32_20_reference_rows_are_not_arbitrarily_rejected(goal):
    document = synthetic_drama(goal)
    refs = list(audit.citations.build_evidence_catalog(goal))
    for key, count in zip(audit.GOAL_CHECKS, [10, 17, 32, 20]):
        document["goal_checks"][key]["evidence_refs"] = refs[:count]
    before = deepcopy(document)
    result = validate(document, goal)
    assert result["valid"] and result["accepted"]
    assert document == before and result["native_review_modified"] is False
    assert result["scope_observations_complete_extraction_proven"] is False
    assert result["semantic_truth_deterministically_proven"] is False and not result["human_approved"]


def test_whole_catalog_reference_and_counterreference_compilation_is_exact(goal):
    document = synthetic_drama(goal)
    catalog = audit.citations.build_evidence_catalog(goal)
    refs = list(catalog)
    key = audit.GOAL_CHECKS[0]
    row = document["goal_checks"][key]
    row.update(status="fail", required_revision="提交完整新计划", evidence_refs=refs,
               counterevidence_refs=list(reversed(refs)))
    result = validate(document, goal)
    assert result["valid"] and not result["accepted"]
    assert result["citations"][key] == [catalog[ref] for ref in refs]
    assert result["counterevidence_citations"][key] == [catalog[ref] for ref in reversed(refs)]
    assert result["findings"][0]["target"] == "complete_native_goal"


@pytest.mark.parametrize("bad_refs", [[], ["G999"], ["G001", "G001"], "G001", [1]])
def test_empty_forged_duplicate_and_wrong_type_references_reject(goal, bad_refs):
    document = synthetic_drama(goal)
    document["goal_checks"][audit.GOAL_CHECKS[0]]["evidence_refs"] = bad_refs
    with pytest.raises(ValidationError):
        validate(document, goal)


@pytest.mark.parametrize("status,revision,counter", [
    ("pass", "返修非空", []), ("fail", "", []), ("fail", " \t\n", []),
    ("pass", "", ["G001"]), ("okay", "", []),
])
def test_pass_fail_revision_and_unresolved_counterevidence_rules_remain_closed(goal, status, revision, counter):
    document = synthetic_drama(goal)
    document["goal_checks"][audit.GOAL_CHECKS[0]].update(
        status=status, required_revision=revision, counterevidence_refs=counter)
    with pytest.raises(ValidationError):
        validate(document, goal)


@pytest.mark.parametrize("bad_analysis", ["", " \t\n", None, []])
def test_counterexample_analysis_needs_substantive_text(goal, bad_analysis):
    document = synthetic_drama(goal)
    document["goal_checks"][audit.GOAL_CHECKS[0]]["counterexample_analysis"] = bad_analysis
    with pytest.raises((ValidationError, ValueError)):
        validate(document, goal)


@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_valid_content_failure_or_uncertainty_is_never_accepted(goal, status):
    document = synthetic_drama(goal)
    set_scope_failure(document, status)
    result = validate(document, goal)
    assert result["valid"] and not result["accepted"]
    assert bool(result["findings"]) == (status == "fail")
    assert bool(result["uncertainties"]) == (status == "unknown")


def test_source_contract_remains_the_frozen_v7_shape(goal):
    source = synthetic_source(goal)
    assert audit.SOURCE_AUDIT_VERSION == "creative_goal_context_workflow/v7/source_audit"
    assert audit.prior.validate_goal_source_audit(source, goal, context_sha256=SOURCE_CONTEXT)["accepted"]
    extra = deepcopy(source)
    extra["scope_observations"] = {}
    with pytest.raises(ValidationError):
        audit.prior.validate_goal_source_audit(extra, goal, context_sha256=SOURCE_CONTEXT)


def test_scope_catalog_uses_native_path_indices_without_prose_inference(goal):
    scope = audit.build_production_scope_catalog(goal)
    catalog = audit.citations.build_evidence_catalog(goal)
    assert scope["declared_actor_ids"] == [row["id"] for row in goal["whole_plan"]["characters"]]
    assert scope["declared_prop_ids"] == [row["id"] for row in goal["whole_plan"]["props"]]
    for index, beat in enumerate(goal["whole_plan"]["beats"]):
        expected = f"whole_plan.beats.{index}"
        assert scope["beat_scopes"][beat["id"]]["document_path"] == expected
        assert scope["beat_scopes"][beat["id"]]["evidence_refs"] == [
            ref for ref, row in catalog.items() if row["document_path"].startswith(expected + ".")]


@pytest.mark.parametrize("mutation", ["missing_beat", "extra_beat", "missing_table", "extra_table", "extra_item_field"])
def test_scope_coverage_and_owned_fields_are_closed(goal, mutation):
    document = synthetic_drama(goal)
    first = goal["whole_plan"]["beats"][0]["id"]
    scope = document["scope_observations"]
    if mutation == "missing_beat":
        scope.pop(first)
    elif mutation == "extra_beat":
        scope["foreign_beat"] = deepcopy(scope[first])
    elif mutation == "missing_table":
        scope[first].pop("operated_props")
    elif mutation == "extra_table":
        scope[first]["scene_changes"] = []
    else:
        item = scope_item(goal, first, declared=goal["whole_plan"]["characters"][0]["id"])
        item["summary"] = "extra annotation"
        scope[first]["audible_speakers"] = [item]
    with pytest.raises(ValidationError):
        validate(document, goal)


@pytest.mark.parametrize("table,field,prop", [("audible_speakers", "declared_character_id", False),
                                             ("operated_props", "declared_prop_id", True)])
def test_scope_id_enum_cannot_invent_actor_or_prop(goal, table, field, prop):
    document = synthetic_drama(goal)
    first = goal["whole_plan"]["beats"][0]["id"]
    item = scope_item(goal, first, declared="undeclared_id", prop=prop)
    document["scope_observations"][first][table] = [item]
    with pytest.raises(ValidationError):
        validate(document, goal)


@pytest.mark.parametrize("mutation", ["wrong_beat", "wrong_quote", "whitespace_quote", "duplicate_item", "wrong_ref_type"])
def test_scope_source_must_be_its_actual_beat_and_exact_nonempty_substring(goal, mutation):
    document = synthetic_drama(goal)
    first, second = [row["id"] for row in goal["whole_plan"]["beats"][:2]]
    item = scope_item(goal, first, declared=goal["whole_plan"]["characters"][0]["id"])
    if mutation == "wrong_beat":
        item = scope_item(goal, second, declared=item["declared_character_id"])
    elif mutation == "wrong_quote":
        item["quote"] = "this sentence is absent from the native source"
    elif mutation == "whitespace_quote":
        item["quote"] = " \t\n"
    elif mutation == "wrong_ref_type":
        item["source_ref"] = 1
    document["scope_observations"][first]["audible_speakers"] = [item, deepcopy(item)] if mutation == "duplicate_item" else [item]
    with pytest.raises((ValidationError, ValueError)):
        validate(document, goal)


@pytest.mark.parametrize("prop", [False, True])
def test_undeclared_voice_or_operation_cannot_coexist_with_closed_scope_pass(goal, prop):
    document = synthetic_drama(goal)
    beat = goal["whole_plan"]["beats"][2]["id"]
    document["scope_observations"][beat]["operated_props" if prop else "audible_speakers"] = [scope_item(goal, beat, prop=prop)]
    with pytest.raises(ValueError, match="undeclared"):
        validate(document, goal)


@pytest.mark.parametrize("status", ["fail", "unknown"])
@pytest.mark.parametrize("prop", [False, True])
def test_honest_undeclared_scope_observation_retains_fail_unknown_stop(goal, status, prop):
    document = synthetic_drama(goal)
    beat = goal["whole_plan"]["beats"][2]["id"]
    document["scope_observations"][beat]["operated_props" if prop else "audible_speakers"] = [scope_item(goal, beat, prop=prop)]
    set_scope_failure(document, status)
    before = deepcopy(document)
    result = validate(document, goal)
    assert result["valid"] and not result["accepted"]
    assert len(result["undeclared_scope_observations"]) == 1
    assert result["scope_observations_complete_extraction_proven"] is False
    assert document == before


def test_declared_scope_substring_compiles_exact_original_quote_and_path(goal):
    document = synthetic_drama(goal)
    beat = goal["whole_plan"]["beats"][0]["id"]
    item = scope_item(goal, beat, declared=goal["whole_plan"]["characters"][0]["id"])
    item["quote"] = item["quote"][:4]
    document["scope_observations"][beat]["audible_speakers"] = [item]
    result = validate(document, goal)
    compiled = result["scope_observation_evidence"][beat]["audible_speakers"][0]
    original = audit.citations.build_evidence_catalog(goal)[item["source_ref"]]
    assert compiled["quote"] == item["quote"]
    assert compiled["original_quote"] == original["quote"]
    assert compiled["document_path"] == original["document_path"]
    assert result["accepted"] and not result["scope_observations_complete_extraction_proven"]


def test_bundle_contains_two_unmodified_native_shapes_and_exact_identities(goal):
    source, drama = synthetic_source(goal), synthetic_drama(goal)
    bundle = audit.build_bundle(source, drama)
    before = deepcopy(bundle)
    result = audit.validate_bundle(bundle, goal, source_context_sha256=SOURCE_CONTEXT,
                                   drama_context_sha256=DRAMA_CONTEXT)
    assert result["valid"] and result["accepted"] and result["combined_decisions_only"]
    assert not result["native_single_combined_audit"] and not result["human_approved"]
    assert bundle == before and source == before["native_source_audit"] and drama == before["native_drama_audit"]
    source["claim_checks"].clear()
    assert bundle == before, "bundle is an owned copy, not a writable alias of source"


@pytest.mark.parametrize("mutation", ["missing_part", "extra_header", "old_bundle", "source_goal", "drama_goal", "source_context", "drama_context", "old_drama"])
def test_missing_mixed_or_legacy_native_bundle_is_never_accepted(goal, mutation):
    bundle = audit.build_bundle(synthetic_source(goal), synthetic_drama(goal))
    if mutation == "missing_part":
        bundle.pop("native_drama_audit")
    elif mutation == "extra_header":
        bundle["passed"] = True
    elif mutation == "old_bundle":
        bundle["schema"] = audit.prior.BUNDLE_VERSION
    elif mutation == "old_drama":
        bundle["native_drama_audit"]["schema"] = audit.prior.DRAMA_AUDIT_VERSION
    else:
        part, field = mutation.split("_")
        key = "goal_sha256" if field == "goal" else "audit_context_sha256"
        bundle["native_" + part + "_audit"][key] = "9" * 64
    with pytest.raises((ValidationError, ValueError)):
        audit.validate_bundle(bundle, goal, source_context_sha256=SOURCE_CONTEXT, drama_context_sha256=DRAMA_CONTEXT)


@pytest.mark.parametrize("part,status", [("source", "fail"), ("source", "unknown"), ("drama", "fail"), ("drama", "unknown")])
def test_either_native_part_failure_or_unknown_blocks_bundle(goal, part, status):
    bundle = audit.build_bundle(synthetic_source(goal), synthetic_drama(goal))
    rows = bundle["native_" + part + "_audit"]["claim_checks" if part == "source" else "goal_checks"]
    next(iter(rows.values())).update(status=status, required_revision="完整新规划" if status == "fail" else "")
    result = audit.validate_bundle(bundle, goal, source_context_sha256=SOURCE_CONTEXT, drama_context_sha256=DRAMA_CONTEXT)
    assert result["valid"] and not result["accepted"]
    assert bool(result["findings"]) == (status == "fail")
    assert bool(result["uncertainties"]) == (status == "unknown")


@pytest.mark.parametrize("context", [None, "bad", "A" * 64, "g" * 64, "2" * 63, 2])
def test_actual_context_identity_cannot_be_malformed(goal, context):
    with pytest.raises(ValueError, match="SHA-256"):
        audit.build_drama_schema(goal, context_sha256=context)


def test_same_context_cannot_masquerade_as_two_distinct_audit_payloads(goal):
    bundle = audit.build_bundle(synthetic_source(goal), synthetic_drama(goal))
    with pytest.raises(ValueError, match="distinct"):
        audit.validate_bundle(bundle, goal, source_context_sha256=SOURCE_CONTEXT, drama_context_sha256=SOURCE_CONTEXT)


def test_original_556_remains_rejected_without_native_transformation(goal):
    paths = [ROUND / name for name in ["call_554_goal_plan_12.json", "call_555_goal_source_audit_02.json",
                                      "call_556_goal_drama_audit_02.json"]]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    receipt = json.loads(paths[-1].read_bytes())
    original = receipt["output"]
    assert receipt["status"] == "contract_rejected"
    assert max(len(row["evidence_refs"]) for row in original["goal_checks"].values()) == 32
    with pytest.raises(ValidationError):
        audit.prior.validate_goal_drama_audit(original, goal, context_sha256=original["audit_context_sha256"])
    with pytest.raises(ValidationError):
        audit.validate_drama(original, goal, context_sha256=original["audit_context_sha256"])
    assert {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths} == before
