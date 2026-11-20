"""Offline native v9 fixtures, never conversions of provider responses."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

from jsonschema import ValidationError
import pytest

from src.content_factory import creative_goal_drama_audit_contract_v9 as audit

SOURCE_CONTEXT, DRAMA_CONTEXT = "1" * 64, "2" * 64


@pytest.fixture(autouse=True)
def no_provider(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("offline tests must not contact clients or sockets")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


@pytest.fixture
def goal():
    return {"claims": [
        {"id": "CC_PHONE", "kind": "creative_choice", "text": "手机始终在观看者左手。"},
        {"id": "CC_PRESS", "kind": "creative_choice", "text": "左掌保持压着纸。"},
        {"id": "CC_UNUSED", "kind": "creative_choice", "text": "未直接使用的选择仍保留。"},
        {"id": "UG_GOAL", "kind": "user_audience_goal", "text": "人物有可见回应。"}],
        "whole_plan": {"characters": [
            {"id": "viewer", "name": "观看者", "want": "核对纸上内容"},
            {"id": "owner", "name": "所有者", "want": "保存原件"}],
            "props": [{"id": "paper", "description": "表单", "owner_character_id": "owner"},
                      {"id": "phone", "description": "手机", "owner_character_id": "viewer"}],
            "beats": [
                {"id": "b1", "event": "观看者注视所有者的表单。", "visible_change": "手机在另一只手。",
                 "claim_refs": ["CC_PHONE", "CC_PRESS", "UG_GOAL"]},
                {"id": "b2", "event": "观看者保留手机照片。", "visible_change": "原件仍在所有者一侧。",
                 "claim_refs": ["CC_PHONE"]}],
            "ending": {"attempt_result": "观看者拿到照片。", "claim_refs": ["CC_PHONE"]}}}


def synthetic_drama(goal):
    first = next(iter(audit.build_evidence_catalog(goal)))
    judgment = {"status": "pass", "reason": "合成结构夹具，不证明内容正确", "required_revision": "",
        "evidence_refs": [first], "counterexample_analysis": "只验证报告的比较及引用合同", "counterevidence_refs": []}
    checks = {}
    for identifier, usage in audit.build_commitment_usage_catalog(goal).items():
        checked = {key: [row["evidence_refs"][0]] for key, row in usage["usages"].items()}
        checks[identifier] = {**deepcopy(judgment), "claim_ref": usage["claim_ref"],
            "evidence_refs": [usage["claim_ref"], *[refs[0] for refs in checked.values()]],
            "checked_usages": checked}
    return {"schema": audit.DRAMA_AUDIT_VERSION, "goal_sha256": audit.digest(goal),
        "audit_context_sha256": DRAMA_CONTEXT,
        "goal_checks": {key: deepcopy(judgment) for key in audit.GOAL_CHECKS},
        "scope_observations": {row["id"]: {"audible_speakers": [], "operated_props": []}
                               for row in goal["whole_plan"]["beats"]}, "commitment_checks": checks}


def synthetic_source(goal):
    return {"schema": audit.SOURCE_AUDIT_VERSION, "goal_sha256": audit.digest(goal),
        "audit_context_sha256": SOURCE_CONTEXT, "claim_checks": {row["id"]: {
            "status": "pass", "reason": "合成来源夹具", "required_revision": ""} for row in goal["claims"]}}


def validate(document, goal):
    return audit.validate_drama(document, goal, context_sha256=DRAMA_CONTEXT)


def test_c_and_original_g_bindings_are_exact_and_finite(goal):
    original = deepcopy(goal)
    old_g = audit.citations.build_evidence_catalog(goal)
    catalog = audit.build_evidence_catalog(goal)
    assert {ref: row for ref, row in catalog.items() if ref.startswith("G")} == old_g
    for index, claim in enumerate(goal["claims"]):
        assert catalog["C:" + claim["id"]] == {"document_path": f"claims.{index}.text", "quote": claim["text"]}
    assert audit.build_evidence_manifest(goal) == {
        ref: {"document_path": row["document_path"]} for ref, row in catalog.items()}
    usages = audit.build_commitment_usage_catalog(goal)
    assert set(usages) == {"CC_PHONE", "CC_PRESS"}
    assert list(usages["CC_PHONE"]["usages"]) == ["beat:b1", "beat:b2", "ending"]
    assert list(usages["CC_PRESS"]["usages"]) == ["beat:b1"]
    schema = audit.build_drama_schema(goal, context_sha256=DRAMA_CONTEXT)
    assert schema["$defs"]["evidence_refs"]["maxItems"] == len(catalog) > 8
    document = synthetic_drama(goal)
    document["goal_checks"][audit.GOAL_CHECKS[0]]["evidence_refs"] = list(catalog)
    document["commitment_checks"]["CC_PHONE"]["evidence_refs"].append("C:CC_PRESS")
    before = deepcopy(document)
    result = validate(document, goal)
    assert result["accepted"] and result["commitment_usage_coverage_complete"]
    assert result["commitment_check_evidence"]["CC_PHONE"]["evidence"][-1] == catalog["C:CC_PRESS"]
    assert goal == original and document == before and not result["native_review_modified"]


@pytest.mark.parametrize("fault", ["wrong_claim_const", "forged_c", "missing_own_c", "future_g",
                                   "usage_c", "missing_usage", "extra_usage", "empty_usage", "duplicate_g"])
def test_wrong_c_and_wrong_usage_or_future_g_are_rejected(goal, fault):
    document = synthetic_drama(goal)
    row = document["commitment_checks"]["CC_PHONE"]
    if fault == "wrong_claim_const":
        row["claim_ref"] = "C:CC_PRESS"
    elif fault == "forged_c":
        row["evidence_refs"].append("C:NOT_NATIVE")
    elif fault == "missing_own_c":
        row["evidence_refs"].remove("C:CC_PHONE")
    elif fault == "future_g":
        row["checked_usages"]["beat:b1"] = row["checked_usages"]["beat:b2"]
    elif fault == "usage_c":
        row["checked_usages"]["beat:b1"] = ["C:CC_PHONE"]
    elif fault == "missing_usage":
        row["checked_usages"].pop("ending")
    elif fault == "extra_usage":
        row["checked_usages"]["beat:NOT_NATIVE"] = row["checked_usages"]["beat:b1"]
    elif fault == "empty_usage":
        row["checked_usages"]["ending"] = []
    else:
        row["checked_usages"]["ending"] *= 2
    with pytest.raises(ValidationError):
        validate(document, goal)


def test_scope_observation_keeps_own_g_only_and_exact_quote(goal):
    document = synthetic_drama(goal)
    ref = audit.build_production_scope_catalog(goal)["beat_scopes"]["b1"]["evidence_refs"][0]
    quote = audit.build_evidence_catalog(goal)[ref]["quote"]
    item = {"source_ref": ref, "quote": quote, "declared_character_id": "viewer"}
    document["scope_observations"]["b1"]["audible_speakers"] = [item]
    assert validate(document, goal)["scope_observation_evidence"]["b1"]["audible_speakers"][0]["original_quote"] == quote
    item["source_ref"], item["quote"] = "C:CC_PHONE", goal["claims"][0]["text"]
    with pytest.raises(ValidationError):
        validate(document, goal)


@pytest.mark.parametrize("fault", ["old_drama", "missing_commitment", "old_bundle", "mixed_goal", "mixed_context"])
def test_old_or_mixed_native_shapes_cannot_be_accepted(goal, fault):
    bundle = audit.build_bundle(synthetic_source(goal), synthetic_drama(goal))
    if fault == "old_drama":
        bundle["native_drama_audit"]["schema"] = audit.base.DRAMA_AUDIT_VERSION
    elif fault == "missing_commitment":
        bundle["native_drama_audit"].pop("commitment_checks")
    elif fault == "old_bundle":
        bundle["schema"] = audit.base.BUNDLE_VERSION
    elif fault == "mixed_goal":
        bundle["native_drama_audit"]["goal_sha256"] = "f" * 64
    else:
        bundle["native_drama_audit"]["audit_context_sha256"] = "f" * 64
    with pytest.raises((ValidationError, ValueError)):
        audit.validate_bundle(bundle, goal, source_context_sha256=SOURCE_CONTEXT, drama_context_sha256=DRAMA_CONTEXT)


@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_valid_commitment_failure_and_unknown_block_whole_bundle(goal, status):
    document = synthetic_drama(goal)
    row = document["commitment_checks"]["CC_PHONE"]
    row.update(status=status, required_revision="模型提交完整新规划" if status == "fail" else "",
        counterevidence_refs=["C:CC_PRESS"])
    result = validate(document, goal)
    assert result["valid"] and not result["accepted"]
    assert bool(result["findings"]) == (status == "fail")
    assert bool(result["uncertainties"]) == (status == "unknown")
    findings = result["findings"] or result["uncertainties"]
    assert findings[0]["table"] == "commitment_checks"
    bundle = audit.build_bundle(synthetic_source(goal), document)
    assert not audit.validate_bundle(bundle, goal, source_context_sha256=SOURCE_CONTEXT,
                                     drama_context_sha256=DRAMA_CONTEXT)["accepted"]


@pytest.mark.parametrize("fault", ["pass_counter", "pass_revision", "fail_no_revision", "empty_analysis"])
def test_commitment_judgment_cannot_hide_reported_counterexample(goal, fault):
    document = synthetic_drama(goal)
    row = document["commitment_checks"]["CC_PHONE"]
    if fault == "pass_counter":
        row["counterevidence_refs"] = ["C:CC_PRESS"]
    elif fault == "pass_revision":
        row["required_revision"] = "修正"
    elif fault == "fail_no_revision":
        row["status"] = "fail"
    else:
        row["counterexample_analysis"] = " \t\n"
    with pytest.raises((ValidationError, ValueError)):
        validate(document, goal)


def test_owner_and_observer_are_not_inferred_as_conflict_or_operation(goal):
    document = synthetic_drama(goal)
    assert goal["whole_plan"]["props"][0]["owner_character_id"] == "owner"
    assert "观看者注视所有者" in goal["whole_plan"]["beats"][0]["event"]
    document["goal_checks"]["closed_production_scope"]["reason"] = "只注视未操作，归属不等于当前持有"
    result = validate(document, goal)
    assert result["accepted"] and not result["undeclared_scope_observations"]
    # The conflicting synthetic promises can still be missed by a model. A
    # catalog/coverage validator must not claim it automatically understood them.
    assert result["semantic_truth_deterministically_proven"] is False
    assert result["commitment_semantic_extraction_proven"] is False
    assert result["scope_observations_complete_extraction_proven"] is False
    assert not result["human_approved"]


def test_source_v7_bundle_is_unchanged_and_owned(goal):
    source, drama = synthetic_source(goal), synthetic_drama(goal)
    assert audit.SOURCE_AUDIT_VERSION == audit.base.SOURCE_AUDIT_VERSION == "creative_goal_context_workflow/v7/source_audit"
    bundle = audit.build_bundle(source, drama)
    before = deepcopy(bundle)
    assert audit.validate_bundle(bundle, goal, source_context_sha256=SOURCE_CONTEXT,
                                 drama_context_sha256=DRAMA_CONTEXT)["accepted"]
    assert bundle == before
    source["claim_checks"].clear()
    assert bundle == before


def test_actual_561_original_g_and_all_explicit_uses_stay_exact_without_rewriting():
    root = Path(__file__).resolve().parents[1]
    path = root / "data/production_trials/goal_context_text_production_20261013/round_10/goals/native_01.json"
    before = path.read_bytes()
    native = json.loads(before)
    old = audit.citations.build_evidence_catalog(native)
    catalog = audit.build_evidence_catalog(native)
    assert {ref: row for ref, row in catalog.items() if ref.startswith("G")} == old
    assert catalog["C:CC_FINGER_HOLD"]["quote"] == next(row["text"] for row in native["claims"] if row["id"] == "CC_FINGER_HOLD")
    usage = audit.build_commitment_usage_catalog(native)
    assert set(usage["CC_PHOTO_TIMING"]["usages"]) == {"beat:b7"}
    assert set(usage["CC_FINGER_HOLD"]["usages"]) == {"beat:b1", "beat:b2"}
    assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(before).digest()
