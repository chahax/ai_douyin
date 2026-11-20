"""Pure scope contracts. Synthetic semantic labels are not production gold."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

import pytest
from jsonschema import ValidationError

from src.content_factory import creative_legal_speech_scope_v1 as scope
from src.content_factory import creative_goal_evidence_view_v1 as views
from tests.test_creative_goal_legal_usage_source_audit_v1 import goal

PROJECT = Path(__file__).resolve().parents[1]
QA = PROJECT / "data/qa/creative_source624_diagnosis_20261015"
ROUND = PROJECT / "data/production_trials/fresh_source_text_session_20261015/round_02"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError("scope tests must be offline")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def synthetic_scope(goal):
    """Synthetic structure, never convert a real prior source report."""
    built = scope.build_scope_context(goal)
    catalog = scope.evidence.build_evidence_catalog(goal)
    document = {"schema": scope.VERSION, "frame_kind": "native_goal", "input_sha256": scope.digest(goal),
        "scope_context_sha256": built["manifest"]["scope_context_sha256"],
        "speech_act_by_ref": {ref: "F" for ref in catalog}, "scope_observations": []}
    for claim in goal["claims"]:
        if claim["kind"] == "verified_legal": add_assertion(document, catalog, "C:" + claim["id"])
    return document


def add_assertion(document, catalog, ref):
    document["speech_act_by_ref"][ref] = "L"
    row = {"source_ref": ref, "content": {"kind": "legal_assertion", "quote": catalog[ref]["quote"],
        "proposition": "Synthetic actual legal proposition, not deterministically extracted",
        "assertion_scope": "general_rule", "expression": "explicit", "reason": "Synthetic speech act judgment"}}
    document["scope_observations"].append(row)
    return row["content"]


def add_ambiguity(document, catalog, ref):
    document["speech_act_by_ref"][ref] = "U"
    row = {"source_ref": ref, "content": {"kind": "textual_ambiguity", "quote": catalog[ref]["quote"],
        "nonlegal_reading": "A proposed local arrangement", "legal_reading": "A necessary legal condition",
        "ambiguity_reason": "Synthetic exact text can support both interpretations",
        "context_evidence": [{"source_ref": ref, "quote": catalog[ref]["quote"]}]}}
    document["scope_observations"].append(row)
    return row["content"]


def validate(document, goal):
    return scope.validate_scope(document, goal, context_sha256=scope.build_scope_context(goal)["manifest"]["scope_context_sha256"])


def test_lossless_full_context_no_external_authority_input_and_no_truth_claim(goal):
    before = deepcopy(goal)
    built = scope.build_scope_context(goal)
    assert views.reconstruct_goal(built["payload"]["native_goal_evidence_view"]) == goal
    assert "verified_legal_context" not in built["payload"] and "source_packet" not in built["payload"]
    report = synthetic_scope(goal)
    result = validate(report, goal)
    assert result["complete_key_coverage_verified"] and result["scope_ready_for_authority_review"]
    assert not result["semantic_classification_proven"] and not result["creative_quality_passed"]
    assert goal == before


def test_creative_choice_can_contain_real_legal_assertion_and_no_label_exemption(goal):
    report = synthetic_scope(goal)
    add_assertion(report, scope.evidence.build_evidence_catalog(goal), "C:CC6")
    result = validate(report, goal)
    assert "C:CC6" in result["legal_assertions"]
    assert scope.authority_projection(report, goal)["act_by_ref"]["C:CC6"] == "L"


def test_genuine_text_ambiguity_requires_complete_author_clarification_not_external_unknown(goal):
    report = synthetic_scope(goal)
    add_ambiguity(report, scope.evidence.build_evidence_catalog(goal), "C:CC6")
    before = deepcopy((report, goal))
    result = validate(report, goal)
    assert result["route"] == "complete_native_author_clarification"
    assert result["known_text_content_requires_clarification"] and not result["external_fact_or_legal_unknown_assessed"]
    with pytest.raises(scope.ScopeContractError): scope.authority_projection(report, goal)
    assert (report, goal) == before


@pytest.mark.parametrize("fault", ["missing_key", "extra_key", "wrong_code", "wrong_frame", "wrong_input", "wrong_context",
    "old_source_schema", "missing_detail", "duplicate_detail", "extra_nonlegal_detail", "foreign_quote", "wrong_kind", "verified_nonlegal"])
def test_exact_coverage_hash_quote_and_lu_alignment(goal, fault):
    report = synthetic_scope(goal)
    if fault == "missing_key": report["speech_act_by_ref"].pop("C:CC6")
    elif fault == "extra_key": report["speech_act_by_ref"]["G999"] = "F"
    elif fault == "wrong_code": report["speech_act_by_ref"]["C:CC6"] = "uncertain"
    elif fault == "wrong_frame": report["frame_kind"] = "case_batch"
    elif fault == "wrong_input": report["input_sha256"] = "0" * 64
    elif fault == "wrong_context": report["scope_context_sha256"] = "0" * 64
    elif fault == "old_source_schema": report["schema"] = scope.evidence.VERSION
    elif fault == "missing_detail": report["scope_observations"].clear()
    elif fault == "duplicate_detail": report["scope_observations"].append(deepcopy(report["scope_observations"][0]))
    elif fault == "extra_nonlegal_detail":
        row = add_assertion(report, scope.evidence.build_evidence_catalog(goal), "C:CC6")
        report["speech_act_by_ref"]["C:CC6"] = "F"
    elif fault == "foreign_quote": report["scope_observations"][0]["content"]["quote"] = goal["claims"][2]["text"]
    elif fault == "wrong_kind":
        report["speech_act_by_ref"]["C:VL2"] = "U"
    else: report["speech_act_by_ref"]["C:VL2"] = "F"; report["scope_observations"].clear()
    before = deepcopy(report)
    with pytest.raises((ValidationError, scope.ScopeContractError)): validate(report, goal)
    assert report == before


@pytest.mark.parametrize("fault", ["same_readings", "blank_reading", "external_unknown_kind", "foreign_context", "duplicate_context"])
def test_ambiguity_needs_two_readings_and_actual_complete_context(goal, fault):
    report = synthetic_scope(goal)
    row = add_ambiguity(report, scope.evidence.build_evidence_catalog(goal), "C:CC6")
    if fault == "same_readings": row["legal_reading"] = row["nonlegal_reading"]
    elif fault == "blank_reading": row["legal_reading"] = " "
    elif fault == "external_unknown_kind": row["kind"] = "external_unknown"
    elif fault == "foreign_context": row["context_evidence"][0]["quote"] = "not original"
    else: row["context_evidence"].append(deepcopy(row["context_evidence"][0]))
    with pytest.raises((ValidationError, scope.ScopeContractError)): validate(report, goal)


def test_semantic_false_negative_cannot_be_proven_by_shape_only(goal):
    report = synthetic_scope(goal)  # Synthetic CC6 labelled F despite an actual legal premise.
    result = validate(report, goal)
    assert "C:CC6" not in result["legal_assertions"]
    assert not result["semantic_classification_proven"]  # Real blind controls are still necessary.


def test_case_frame_is_separate_and_preserves_own_role_context():
    cases = {"schema": "creative_legal_scope_cases/v1", "cases": [{"source_ref": "T01", "text": "她说必须签字。",
        "role_context": json.dumps({"same_scene_context": ["这是经理要求的本次交差动作。"]}, ensure_ascii=False)}]}
    built = scope.build_case_scope_context(cases)
    assert built["payload"]["blinded_cases"] == cases and "native_goal_sha256" not in built["payload"]
    report = {"schema": scope.VERSION, "frame_kind": "case_batch", "input_sha256": scope.digest(cases),
        "scope_context_sha256": built["manifest"]["scope_context_sha256"], "speech_act_by_ref": {"T01": "U"},
        "scope_observations": []}
    row = add_ambiguity(report, {"T01": {"quote": cases["cases"][0]["text"]}}, "T01")
    row["context_evidence"][0]["quote"] = "这是经理要求的本次交差动作。"
    result = scope.validate_case_scope(report, cases, context_sha256=built["manifest"]["scope_context_sha256"])
    assert result["source_ref_count"] == 1 and result["frame_kind"] == "case_batch"


@pytest.mark.parametrize("fault", ["extra_expected", "case_expected", "duplicate", "blank_context", "not_case_schema"])
def test_blind_case_frame_refuses_extra_labels_or_incomplete_context(fault):
    cases = {"schema": "creative_legal_scope_cases/v1", "cases": [{"source_ref": "T01", "text": "当场拒签", "role_context": "原场景上下文"}]}
    if fault == "extra_expected": cases["expected"] = "F"
    elif fault == "case_expected": cases["cases"][0]["expected"] = "F"
    elif fault == "duplicate": cases["cases"].append(deepcopy(cases["cases"][0]))
    elif fault == "blank_context": cases["cases"][0]["role_context"] = " "
    else: cases["schema"] = "native_goal"
    with pytest.raises(scope.ScopeContractError): scope.build_case_scope_context(cases)


def test_actual623_full132_and_blind20_contexts_only_preserve_original_bytes():
    paths = [ROUND / "call_623_whole_plan_03.json", ROUND / "call_624_source_audit_03.json", QA / "BLINDED_CASES_v1.json"]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    goal = json.loads(paths[0].read_text(encoding="utf-8"))["output"]
    built = scope.build_scope_context(goal)
    assert built["manifest"]["source_ref_count"] == 132
    assert views.reconstruct_goal(built["payload"]["native_goal_evidence_view"]) == goal
    cases = json.loads(paths[2].read_text(encoding="utf-8"))
    blind = scope.build_case_scope_context(cases)
    schema = scope.build_case_scope_schema(cases, context_sha256=blind["manifest"]["scope_context_sha256"])
    assert blind["manifest"]["source_ref_count"] == 20
    assert len(schema["properties"]["speech_act_by_ref"]["properties"]) == 20
    assert blind["payload"]["blinded_cases"] == cases
    old = json.loads(paths[1].read_text(encoding="utf-8"))["output"]
    with pytest.raises(ValidationError): scope.validate_scope(old, goal, context_sha256=built["manifest"]["scope_context_sha256"])
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths} == before
