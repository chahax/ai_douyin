"""Single-record response contracts without changing the v1 semantic rule."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

import pytest
from jsonschema import ValidationError

from src.content_factory import creative_legal_speech_scope_v2 as scope
from src.content_factory import creative_legal_speech_scope_v1 as frozen
from tests.test_creative_goal_legal_usage_source_audit_v1 import goal

PROJECT = Path(__file__).resolve().parents[1]
QA = PROJECT / "data/qa/creative_source624_diagnosis_20261015"
ROUND = PROJECT / "data/production_trials/fresh_source_text_session_20261015/round_02"
PROBE625 = PROJECT / "data/production_trials/legal_scope_diagnostic_20261015/round_01/call_625_scope_cases_01.json"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError("single-record scope tests must be offline")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def synthetic_scope(goal):
    built = scope.build_scope_context(goal)
    catalog = scope.evidence.build_evidence_catalog(goal)
    document = {"schema": scope.VERSION, "frame_kind": "native_goal", "input_sha256": scope.digest(goal),
        "scope_context_sha256": built["manifest"]["scope_context_sha256"],
        "records_by_ref": {ref: {"act": "F"} for ref in catalog}}
    for claim in goal["claims"]:
        if claim["kind"] == "verified_legal": add_assertion(document, catalog, "C:" + claim["id"])
    return document


def add_assertion(document, catalog, ref):
    content = {"quote": catalog[ref]["quote"], "proposition": "Synthetic actual legal proposition, not locally extracted",
        "assertion_scope": "general_rule", "expression": "explicit", "reason": "Synthetic speech act judgment"}
    document["records_by_ref"][ref] = {"act": "L", "detail": content}
    return content


def add_ambiguity(document, catalog, ref):
    content = {"quote": catalog[ref]["quote"], "nonlegal_reading": "A proposed local arrangement",
        "legal_reading": "A necessary legal condition", "ambiguity_reason": "Synthetic same-text ambiguity",
        "context_evidence": [{"source_ref": ref, "quote": catalog[ref]["quote"]}]}
    document["records_by_ref"][ref] = {"act": "U", "detail": content}
    return content


def validate(document, goal):
    return scope.validate_scope(document, goal,
        context_sha256=scope.build_scope_context(goal)["manifest"]["scope_context_sha256"])


def test_semantic_rule_changes_only_the_exact_response_protocol_sentence():
    assert frozen.SCOPE_RULE.replace(scope.OLD_RESPONSE_RULE, scope.RESPONSE_RULE) == scope.SCOPE_RULE
    assert scope.SCOPE_RULE.replace(scope.RESPONSE_RULE, scope.OLD_RESPONSE_RULE) == frozen.SCOPE_RULE
    assert scope.SCOPE_RULE.count(scope.RESPONSE_RULE) == 1


def test_single_native_record_and_compiled_map_are_not_two_native_classifications(goal):
    report = synthetic_scope(goal)
    before = deepcopy((goal, report))
    result = validate(report, goal)
    assert result["single_native_record_per_ref"] and result["complete_key_coverage_verified"]
    assert result["act_by_ref"] == scope.compile_act_by_ref(report)
    assert result["act_map_is_compiled_metadata_not_native_report"]
    assert "speech_act_by_ref" not in report and "scope_observations" not in report
    assert not result["semantic_classification_proven"] and not result["creative_quality_passed"]
    assert (goal, report) == before


def test_creative_legal_assertion_and_true_u_keep_distinct_routes_and_v2_identity(goal):
    report = synthetic_scope(goal)
    add_assertion(report, scope.evidence.build_evidence_catalog(goal), "C:CC6")
    result = validate(report, goal)
    assert result["act_by_ref"]["C:CC6"] == "L" and result["scope_ready_for_authority_review"]
    projection = scope.authority_projection(report, goal)
    assert projection["schema"] == scope.VERSION + "/authority_projection"
    assert projection["scope_native_sha256"] == scope.digest(report)
    add_ambiguity(report, scope.evidence.build_evidence_catalog(goal), "C:CC6")
    result = validate(report, goal)
    assert result["route"] == "complete_native_author_clarification"
    assert not result["external_fact_or_legal_unknown_assessed"]
    with pytest.raises(scope.ScopeContractError): scope.authority_projection(report, goal)


@pytest.mark.parametrize("act", list(scope.NONLEGAL_ACTS))
def test_nonlegal_act_cannot_carry_any_legal_or_uncertain_detail(goal, act):
    report = synthetic_scope(goal)
    add_ambiguity(report, scope.evidence.build_evidence_catalog(goal), "C:CC6")
    report["records_by_ref"]["C:CC6"]["act"] = act
    with pytest.raises(ValidationError): validate(report, goal)


@pytest.mark.parametrize("fault", ["missing", "foreign_ref", "wrong_act", "list_instead_object", "two_acts", "wrong_frame",
    "wrong_input", "wrong_context", "A1_version", "parallel_map", "parallel_details", "L_without_detail", "U_wrong_detail",
    "legal_kind_redundancy", "foreign_quote", "verified_nonlegal"])
def test_fixed_single_record_contract_rejects_omissions_duplicates_and_foreign_values(goal, fault):
    report = synthetic_scope(goal)
    if fault == "missing": report["records_by_ref"].pop("C:CC6")
    elif fault == "foreign_ref": report["records_by_ref"]["G999"] = {"act": "F"}
    elif fault == "wrong_act": report["records_by_ref"]["C:CC6"]["act"] = "uncertain"
    elif fault == "list_instead_object": report["records_by_ref"]["C:CC6"] = [{"act": "F"}, {"act": "U"}]
    elif fault == "two_acts": report["records_by_ref"]["C:CC6"]["act"] = ["F", "U"]
    elif fault == "wrong_frame": report["frame_kind"] = "case_batch"
    elif fault == "wrong_input": report["input_sha256"] = "0" * 64
    elif fault == "wrong_context": report["scope_context_sha256"] = "0" * 64
    elif fault == "A1_version": report["schema"] = frozen.VERSION
    elif fault == "parallel_map": report["speech_act_by_ref"] = scope.compile_act_by_ref(report)
    elif fault == "parallel_details": report["scope_observations"] = []
    elif fault == "L_without_detail": report["records_by_ref"]["C:CC6"] = {"act": "L"}
    elif fault == "U_wrong_detail": report["records_by_ref"]["C:VL2"]["act"] = "U"
    elif fault == "legal_kind_redundancy": report["records_by_ref"]["C:VL2"]["detail"]["kind"] = "legal_assertion"
    elif fault == "foreign_quote": report["records_by_ref"]["C:VL2"]["detail"]["quote"] = "not its own text"
    else: report["records_by_ref"]["C:VL2"] = {"act": "N"}
    before = deepcopy(report)
    with pytest.raises((ValidationError, scope.ScopeContractError)): validate(report, goal)
    assert report == before


@pytest.mark.parametrize("fault", ["identical_readings", "blank_reading", "external_unknown", "foreign_context", "duplicate_context"])
def test_true_textual_ambiguity_conditions_are_unchanged(goal, fault):
    report = synthetic_scope(goal)
    row = add_ambiguity(report, scope.evidence.build_evidence_catalog(goal), "C:CC6")
    if fault == "identical_readings": row["legal_reading"] = row["nonlegal_reading"]
    elif fault == "blank_reading": row["legal_reading"] = " "
    elif fault == "external_unknown": row["unknown_external_law"] = True
    elif fault == "foreign_context": row["context_evidence"][0]["quote"] = "not current text"
    else: row["context_evidence"].append(deepcopy(row["context_evidence"][0]))
    with pytest.raises((ValidationError, scope.ScopeContractError)): validate(report, goal)


def test_known_fear_sentence_semantics_are_not_locally_changed_to_pass():
    # Synthetic U is structurally accepted and still routes to clarification;
    # this representation repair deliberately does not decide fear semantics.
    cases = {"schema": "creative_legal_scope_cases/v1", "cases": [{"source_ref": "T20", "text": "她心里发慌：我真怕签了就要不回来钱。", "role_context": "人物内心压力"}]}
    built = scope.build_case_scope_context(cases)
    document = {"schema": scope.VERSION, "frame_kind": "case_batch", "input_sha256": scope.digest(cases),
        "scope_context_sha256": built["manifest"]["scope_context_sha256"], "records_by_ref": {}}
    add_ambiguity(document, {"T20": {"quote": cases["cases"][0]["text"]}}, "T20")
    result = scope.validate_case_scope(document, cases, context_sha256=built["manifest"]["scope_context_sha256"])
    assert result["act_by_ref"]["T20"] == "U" and not result["scope_ready_for_authority_review"]
    assert not result["semantic_classification_proven"]


def test_actual623_132_and_same_blind20v2_preserved_625_never_adopted():
    paths = [ROUND / "call_623_whole_plan_03.json", QA / "BLINDED_CASES_v2.json", PROBE625]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    goal = json.loads(paths[0].read_text(encoding="utf-8"))["output"]
    cases = json.loads(paths[1].read_text(encoding="utf-8"))
    old625 = json.loads(paths[2].read_text(encoding="utf-8"))["output"]
    native, blind = scope.build_scope_context(goal), scope.build_case_scope_context(cases)
    assert native["manifest"]["source_ref_count"] == 132 and blind["manifest"]["source_ref_count"] == 20
    assert scope.views.reconstruct_goal(native["payload"]["native_goal_evidence_view"]) == goal
    assert blind["payload"]["blinded_cases"] == cases
    old_payload = frozen.build_case_scope_context(cases)["payload"]
    difference = deepcopy(blind["payload"]);difference["scope_task"]["schema"] = frozen.VERSION + "/task"
    assert difference == old_payload  # Only protocol version identity differs in the input payload.
    with pytest.raises(ValidationError): scope.validate_case_scope(old625, cases, context_sha256=blind["manifest"]["scope_context_sha256"])
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths} == before


def test_native_json_duplicate_ref_or_act_cannot_be_silently_overwritten_by_boundary_parser():
    from scripts.creative_resume_dispatch_v3 import strict_json
    for raw in ('{"records_by_ref":{"T20":{"act":"F"},"T20":{"act":"U"}}}',
                '{"records_by_ref":{"T20":{"act":"F","act":"U"}}}'):
        with pytest.raises(ValueError, match="duplicate JSON key"): strict_json(raw)
