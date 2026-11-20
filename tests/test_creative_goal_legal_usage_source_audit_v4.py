"""New synthetic pragmatic/native relation tests; never normalize old reviews."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

from jsonschema import Draft202012Validator, ValidationError
import pytest

from src.content_factory import creative_goal_legal_usage_source_audit_v4 as audit
from tests.test_creative_goal_legal_usage_source_audit_v1 import authority, goal, ref_for, real594

CONTEXT = "d" * 64
PROJECT = Path(__file__).resolve().parents[1]
ROUND17 = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_17"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError("pragmatic source tests must not contact providers")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def source_usages(document, ref):
    """Return the exact current native array row, without making an old report."""
    return next(row["usages"] for row in document["source_observations"] if row["source_ref"] == ref)


def synthetic_legal_usage(goal, ref, *, relation="supported", scope="general_rule", treatment="asserted",
                          actual_case_conditions=None, interpretation_frame_evidence=None):
    return {"kind": "legal_assertion", "quote": audit.build_evidence_catalog(goal)[ref]["quote"],
        "assertion_scope": scope, "interpretation": "Synthetic legal interpretation, not local Chinese extraction",
        "authority_refs": ["L002"] if relation not in ("not_covered", "unknown") else [],
        "basis_relation": relation, "treatment": treatment,
        "actual_case_conditions": deepcopy(actual_case_conditions or []),
        "interpretation_frame_evidence": deepcopy(interpretation_frame_evidence or []),
        "reason": "Synthetic explicit relation for gate exercise",
        "required_revision": "Submit complete native plan revision" if relation in ("contradicts", "application_contradicted") and treatment == "asserted" else ""}


def synthetic_source(goal, authority, context=CONTEXT):
    """Build only an explicit synthetic structural report, never a provider pass."""
    document = {"schema": audit.VERSION, "goal_sha256": audit.digest(goal), "audit_context_sha256": context,
        "authority_context_sha256": audit.digest(authority),
        "claim_checks": {claim["id"]: {"status": "pass", "reason": "Synthetic provenance judgment only",
                                      "required_revision": ""} for claim in goal["claims"]},
        "source_observations": [{"source_ref": ref, "usages": []} for ref in audit.build_evidence_catalog(goal)]}
    for claim in goal["claims"]:
        if claim["kind"] == "verified_legal":
            row = synthetic_legal_usage(goal, "C:" + claim["id"])
            row["authority_refs"] = list(claim["origin_ids"])
            source_usages(document, "C:" + claim["id"]).append(row)
    return document


def add_legal_usage(document, goal, ref, **kwargs):
    row = synthetic_legal_usage(goal, ref, **kwargs)
    source_usages(document, ref).append(row)
    return row


def add_nonlegal_usage(document, goal, ref, function="case_offer_or_promise"):
    row = {"kind": "non_legal_context", "quote": audit.build_evidence_catalog(goal)[ref]["quote"],
        "pragmatic_function": function,
        "reason": "Synthetic classification, not proof of pragmatic meaning"}
    source_usages(document, ref).append(row)
    return row


def add_uncertain_usage(document, goal, ref):
    row = {"kind": "uncertain", "quote": audit.build_evidence_catalog(goal)[ref]["quote"],
        "interpretation": "Cannot establish whether this occurrence asserts legal meaning",
        "reason": "Synthetic meaningful uncertainty"}
    source_usages(document, ref).append(row)
    return row


def validate(document, goal, authority):
    return audit.validate_source(document, goal, authority, context_sha256=CONTEXT)


def actual_witness(goal, path="whole_plan.beats.0.response", quote=None):
    ref = ref_for(goal, path)
    return {"event_ref": ref, "quote": quote or audit.build_evidence_catalog(goal)[ref]["quote"]}


def frame_witness(goal, path="whole_plan.ending.open_legal_question", quote=None):
    ref = ref_for(goal, path)
    return {"frame_ref": ref, "quote": quote or audit.build_evidence_catalog(goal)[ref]["quote"]}


def test_three_disjoint_native_shapes_no_usage_status_or_duplicate_relation_allof(goal, authority):
    schema = audit.build_source_schema(goal, authority, context_sha256=CONTEXT)
    Draft202012Validator.check_schema(schema)
    assert set(schema["$defs"]["source_observation"]["properties"]["source_ref"]["enum"]) == set(audit.build_evidence_catalog(goal))
    assert "legal_usage_scan" not in schema["properties"]
    for kind in ("non_legal_context", "legal_assertion", "uncertain"):
        assert "status" not in schema["$defs"][kind]["properties"]
        assert "allOf" not in schema["$defs"][kind]
    assert "status" in schema["$defs"]["judgment"]["properties"]
    document = synthetic_source(goal, authority)
    before = deepcopy((goal, authority, document))
    result = validate(document, goal, authority)
    assert set(result) == audit.DECISION_FIELDS and result["schema"] == audit.DECISION_SCHEMA
    assert result["accepted"] and result["legal_usage_coverage_complete"]
    assert result["gate_origin"] == "explicit_native_relation_policy" and not result["native_usage_status_created"]
    assert not result["pragmatic_classification_proven"] and not result["mixed_utterance_extraction_proven"]
    assert not result["legal_semantic_extraction_proven"] and not result["human_approved"]
    assert (goal, authority, document) == before


@pytest.mark.parametrize("function", audit.PRAGMATIC_FUNCTIONS)
def test_nonlegal_personal_offer_fact_or_question_does_not_need_law_support(goal, authority, function):
    document = synthetic_source(goal, authority)
    ref = ref_for(goal, "whole_plan.beats.0.stimulus")
    usage = add_nonlegal_usage(document, goal, ref, function)
    assert not set(usage) & {"authority_refs", "basis_relation", "treatment", "status"}
    result = validate(document, goal, authority)
    assert result["accepted"] and result["usage_gates"][ref][0]["gate"] == "clear"
    assert not result["pragmatic_classification_proven"]  # No Chinese keyword exemption is claimed.


def test_mixed_offer_and_wrong_legal_premise_need_two_native_rows_and_still_fail(goal, authority):
    goal["whole_plan"]["beats"][0]["stimulus"] = "这周签了下周发钱；第38条自己走就没有补偿。"
    ref = ref_for(goal, "whole_plan.beats.0.stimulus")
    document = synthetic_source(goal, authority)
    offer = add_nonlegal_usage(document, goal, ref)
    offer["quote"] = "这周签了下周发钱"
    assertion = add_legal_usage(document, goal, ref, relation="contradicts")
    assertion["quote"] = "第38条自己走就没有补偿"
    result = validate(document, goal, authority)
    assert not result["accepted"] and [row["gate"] for row in result["usage_gates"][ref]] == ["clear", "fail"]
    assert result["findings"][0]["native_usage"] == assertion and "status" not in assertion


@pytest.mark.parametrize("relation,scope,treatment,gate", [
    ("supported", "general_rule", "asserted", "clear"),
    ("contradicts", "general_rule", "asserted", "fail"),
    ("not_covered", "general_rule", "asserted", "unknown"),
    ("unknown", "general_rule", "asserted", "unknown"),
    ("application_not_demonstrated", "case_application", "asserted", "unknown"),
    ("application_contradicted", "case_application", "asserted", "fail"),
    ("supported", "case_application", "asserted", "clear"),
    ("contradicts", "general_rule", "actually_corrected", "clear"),
    ("application_contradicted", "case_application", "actually_corrected", "clear"),
    ("not_covered", "general_rule", "actually_corrected", "unknown"),
    ("unknown", "general_rule", "actually_corrected", "unknown"),
])
def test_finite_gate_policy_preserves_every_uncovered_or_unknown_relation(goal, authority, relation, scope, treatment, gate):
    document = synthetic_source(goal, authority)
    row = add_legal_usage(document, goal, "C:CC6", relation=relation, scope=scope, treatment=treatment)
    if treatment == "actually_corrected" or scope == "case_application" and relation in ("supported", "application_contradicted"):
        row["actual_case_conditions"] = [actual_witness(goal)]
    result = validate(document, goal, authority)
    assert result["usage_gates"]["C:CC6"][0]["gate"] == gate
    assert result["accepted"] is (gate == "clear")
    rows = result["findings"] if gate == "fail" else result["uncertainties"] if gate == "unknown" else []
    if rows: assert rows[0]["gate_origin"] == audit.GATE_ORIGIN and rows[0]["native_usage"] == row


def test_uncertain_classification_is_meaningful_and_blocks_without_fake_legal_relation(goal, authority):
    document = synthetic_source(goal, authority)
    row = add_uncertain_usage(document, goal, "C:CC6")
    result = validate(document, goal, authority)
    assert not result["accepted"] and result["uncertainties"][0]["native_usage"] == row
    assert result["uncertainties"][0]["gate"] == "unknown"


@pytest.mark.parametrize("kind", ["non_legal_context", "uncertain", "legal_assertion"])
@pytest.mark.parametrize("extra", ["status", "portrayal"])
def test_old_redundant_fields_cannot_enter_any_new_native_branch(goal, authority, kind, extra):
    document = synthetic_source(goal, authority)
    row = add_nonlegal_usage(document, goal, "C:CC6") if kind == "non_legal_context" else (
        add_uncertain_usage(document, goal, "C:CC6") if kind == "uncertain" else add_legal_usage(document, goal, "C:CC6"))
    row[extra] = "pass" if extra == "status" else "open_or_question"
    with pytest.raises(ValidationError): validate(document, goal, authority)


@pytest.mark.parametrize("fault", ["missing_verified", "nonlegal_verified", "missing_g", "missing_c", "extra_g", "wrong_schema",
    "wrong_goal", "wrong_context", "wrong_authority", "mixed_branch_fields"])
def test_full_position_metadata_and_three_identity_bindings_remain_required(goal, authority, fault):
    document = synthetic_source(goal, authority)
    if fault == "missing_verified": source_usages(document, "C:VL2").clear()
    elif fault == "nonlegal_verified":
        source_usages(document, "C:VL2").clear();add_nonlegal_usage(document, goal, "C:VL2")
    elif fault in ("missing_g", "missing_c"):
        ref = ref_for(goal, "whole_plan.beats.0.stimulus") if fault == "missing_g" else "C:CC6"
        document["source_observations"] = [row for row in document["source_observations"] if row["source_ref"] != ref]
    elif fault == "extra_g": document["source_observations"].append({"source_ref": "G999", "usages": []})
    elif fault == "wrong_schema": document["schema"] = audit.exact.VERSION
    elif fault == "wrong_goal": document["goal_sha256"] = "0" * 64
    elif fault == "wrong_context": document["audit_context_sha256"] = "0" * 64
    elif fault == "wrong_authority": document["authority_context_sha256"] = "0" * 64
    else: add_nonlegal_usage(document, goal, "C:CC6")["authority_refs"] = ["L002"]
    with pytest.raises((ValidationError, audit.LegalUsageContractError)): validate(document, goal, authority)


@pytest.mark.parametrize("fault", ["none", "claim", "identity", "purpose", "own_g", "repeated_original", "wrong_quote"])
def test_actual_correction_needs_a_different_enacted_g_not_declaration_or_original_self_proof(goal, authority, fault):
    ref = ref_for(goal, "whole_plan.beats.0.stimulus")
    document = synthetic_source(goal, authority)
    row = add_legal_usage(document, goal, ref, relation="contradicts", treatment="actually_corrected")
    if fault == "claim": row["actual_case_conditions"] = [{"event_ref": "C:VL2", "quote": goal["claims"][1]["text"]}]
    elif fault in ("identity", "purpose"):
        path = "whole_plan.characters.0.role" if fault == "identity" else "whole_plan.beats.0.goal"
        row["actual_case_conditions"] = [actual_witness(goal, path)]
    elif fault == "own_g": row["actual_case_conditions"] = [{"event_ref": ref, "quote": row["quote"]}]
    elif fault == "repeated_original":
        goal["whole_plan"]["beats"][0]["response"] = row["quote"]
        document = synthetic_source(goal, authority)
        row = add_legal_usage(document, goal, ref, relation="contradicts", treatment="actually_corrected")
        row["actual_case_conditions"] = [actual_witness(goal)]
    elif fault == "wrong_quote": row["actual_case_conditions"] = [actual_witness(goal, quote="不在该G中的纠正")]
    with pytest.raises((ValidationError, audit.LegalUsageContractError)): validate(document, goal, authority)


@pytest.mark.parametrize("fault", ["missing_case_conditions", "missing_case_counterproof", "general_with_application", "missing_authority",
    "supported_but_corrected", "clear_with_revision", "fail_without_revision", "wrong_authority_ref", "wrong_quote"])
def test_native_legal_relation_self_consistency_and_exact_support(goal, authority, fault):
    document = synthetic_source(goal, authority)
    row = add_legal_usage(document, goal, "C:CC6")
    if fault == "missing_case_conditions": row["assertion_scope"] = "case_application"
    elif fault == "missing_case_counterproof": row.update(assertion_scope="case_application", basis_relation="application_contradicted", required_revision="Whole revision")
    elif fault == "general_with_application": row["basis_relation"] = "application_not_demonstrated"
    elif fault == "missing_authority": row["authority_refs"] = []
    elif fault == "supported_but_corrected": row.update(treatment="actually_corrected", context_evidence=[actual_witness(goal)])
    elif fault == "clear_with_revision": row["required_revision"] = "mandatory change"
    elif fault == "fail_without_revision": row["basis_relation"] = "contradicts"
    elif fault == "wrong_authority_ref": row["authority_refs"] = ["LC"]
    else: row["quote"] = "未在原句出现"
    with pytest.raises((ValidationError, audit.LegalUsageContractError)): validate(document, goal, authority)


@pytest.mark.parametrize("same_source", [True, False])
@pytest.mark.parametrize("relation", ["supported", "application_contradicted"])
def test_case_conditions_or_counterproof_cannot_be_the_same_original_assertion_even_at_another_g(goal, authority, same_source, relation):
    ref = ref_for(goal,"whole_plan.beats.0.stimulus")
    if not same_source: goal["whole_plan"]["beats"][0]["response"] = goal["whole_plan"]["beats"][0]["stimulus"]
    document = synthetic_source(goal,authority)
    row = add_legal_usage(document,goal,ref,relation=relation,scope="case_application")
    context_ref = ref if same_source else ref_for(goal,"whole_plan.beats.0.response")
    row["actual_case_conditions"] = [{"event_ref":context_ref,"quote":row["quote"]}]
    with pytest.raises(audit.LegalUsageContractError,match="own condition proof or counterproof"):
        validate(document,goal,authority)


def test_one_g_can_supply_different_exact_condition_and_conclusion_fragments(goal,authority):
    goal["whole_plan"]["beats"][0]["stimulus"] = "公司提出并且双方同意解除；该情形依法有经济补偿。"
    ref = ref_for(goal,"whole_plan.beats.0.stimulus")
    document = synthetic_source(goal,authority)
    row = add_legal_usage(document,goal,ref,scope="case_application")
    row.update(quote="该情形依法有经济补偿",authority_refs=["L001"],
        actual_case_conditions=[{"event_ref":ref,"quote":"公司提出并且双方同意解除"}])
    result = validate(document,goal,authority)
    assert result["accepted"] and not result["legal_semantic_extraction_proven"]


@pytest.mark.parametrize("field,limit", [("reason", audit.MAX_REASON_CHARS), ("interpretation", audit.MAX_INTERPRETATION_CHARS),
    ("quote", audit.MAX_QUOTE_CHARS), ("required_revision", audit.MAX_REVISION_CHARS)])
def test_finite_native_output_never_silently_truncated(goal, authority, field, limit):
    document = synthetic_source(goal, authority)
    row = add_legal_usage(document, goal, "C:CC6")
    row[field] = "长" * (limit + 1)
    before = deepcopy(document)
    with pytest.raises(ValidationError): validate(document, goal, authority)
    assert document == before


def test_true_source_classification_unknown_still_blocks_even_if_all_usage_gates_clear(goal, authority):
    document = synthetic_source(goal, authority)
    document["claim_checks"]["CC6"].update(status="unknown", reason="Provenance not established")
    result = validate(document, goal, authority)
    assert not result["accepted"] and result["uncertainties"][0]["table"] == "claim_checks"


def test_old_source1_source2_schema_or_admission_can_never_run_in_v3(goal, authority, monkeypatch):
    def deny(*args, **kwargs): raise AssertionError("old source1 admission invoked")
    monkeypatch.setattr(audit.exact, "build_source_schema", deny)
    monkeypatch.setattr(audit.exact, "validate_source", deny)
    monkeypatch.setattr(audit.relation_policy, "build_source_schema", deny)
    monkeypatch.setattr(audit.relation_policy, "validate_source", deny)
    document = synthetic_source(goal, authority)
    assert validate(document, goal, authority)["accepted"]


def test_verified_legal_can_be_uncertain_but_never_disappear_into_nonlegal_context(goal, authority):
    document = synthetic_source(goal, authority)
    source_usages(document, "C:VL2").clear()
    add_uncertain_usage(document, goal, "C:VL2")
    result = validate(document, goal, authority)
    assert not result["accepted"] and result["uncertainties"][0]["source_ref"] == "C:VL2"


@pytest.mark.parametrize("component", ["facts", "sources", "origins"])
def test_any_authority_condition_source_or_directory_drift_blocks_original_report(goal, authority, component):
    document = synthetic_source(goal, authority)
    changed = deepcopy(authority)
    if component == "facts": changed["verified_legal_context"]["facts"][1]["paraphrase"] += "changed conditions"
    elif component == "sources": changed["verified_legal_context"]["sources"][0]["version"] += "changed version"
    else: changed["origin_catalog"]["user"]["U1"]["path"] = "another path"
    with pytest.raises(ValidationError): validate(document, goal, changed)


def test_per_source_capacity_is_finite_and_overflow_is_not_silently_removed(goal, authority):
    document = synthetic_source(goal, authority)
    for index in range(audit.MAX_USAGES_PER_SOURCE):
        row = add_nonlegal_usage(document, goal, "C:CC6")
        row["reason"] = f"Synthetic distinct pragmatic item {index}"
    assert validate(document, goal, authority)["valid"]
    add_uncertain_usage(document, goal, "C:CC6")
    before = deepcopy(document)
    with pytest.raises(ValidationError): validate(document, goal, authority)
    assert document == before


def test_context_evidence_capacity_is_finite(goal, authority):
    goal["whole_plan"]["beats"][0]["visible_change"] = "主管收回表，员工仍坐着。"
    document = synthetic_source(goal, authority)
    row = add_legal_usage(document, goal, "C:CC6", scope="case_application")
    available = audit.build_actual_context_catalog(goal)
    row["actual_case_conditions"] = [{"event_ref": ref, "quote": item["quote"]}
                               for ref, item in list(available.items())[:audit.MAX_CONTEXT_EVIDENCE]]
    assert validate(document, goal, authority)["valid"]
    ref, item = list(available.items())[audit.MAX_CONTEXT_EVIDENCE]
    row["actual_case_conditions"].append({"event_ref": ref, "quote": item["quote"]})
    with pytest.raises(ValidationError): validate(document, goal, authority)


def test_repeated_assertion_positions_are_not_limited_by_an_arbitrary_global_32(goal, authority):
    goal["whole_plan"]["beats"] = [{"id": f"b{index}", "stimulus": "第38条解除与经济补偿有法定衔接。"}
                                     for index in range(40)]
    document = synthetic_source(goal, authority)
    for ref, item in audit.build_evidence_catalog(goal).items():
        if item["document_path"].startswith("whole_plan.beats."): add_legal_usage(document, goal, ref)
    result = validate(document, goal, authority)
    assert result["accepted"] and result["legal_usage_count"] == 41
    assert result["maximum_usage_count"] == len(audit.build_evidence_catalog(goal)) * audit.MAX_USAGES_PER_SOURCE


def test_empty_creative_scan_and_nonlegal_label_are_not_local_semantic_proof(goal, authority):
    document = synthetic_source(goal, authority)
    # Deliberately no local language matching: a wrong semantic label is not
    # independently recognized here. That responsibility remains explicit.
    add_nonlegal_usage(document, goal, "C:CC6")
    result = validate(document, goal, authority)
    assert result["accepted"] and not result["pragmatic_classification_proven"]
    assert not result["mixed_utterance_extraction_proven"]


def test_actual594_595_wrong_38_rule_remains_blocked_and_old_report_is_not_converted():
    goal, authority, old_source, _, hashes = real594()
    with pytest.raises(ValidationError): validate(old_source["output"], goal, authority)
    report = synthetic_source(goal, authority)
    for ref in ("C:CC6", ref_for(goal, "whole_plan.beats.5.stimulus")):
        add_legal_usage(report, goal, ref, relation="contradicts")
    result = validate(report, goal, authority)
    assert not result["accepted"] and len(result["findings"]) == 2
    assert hashes == {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in hashes}


def real602603():
    paths = [ROUND17 / "goals/native_01.json", ROUND17 / "call_603_goal_source_audit_01.json"]
    assert all(path.is_file() for path in paths), "actual frozen602/603 evidence required"
    goal, receipt = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    payload = json.loads(next(row["content"] for row in receipt["request"]["messages"] if row["role"] == "user"))
    authority = {key: deepcopy(payload[key]) for key in ("verified_legal_context", "origin_catalog")}
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    return goal, authority, receipt, hashes


def test_actual603_twenty_relation_status_errors_are_not_reclassified_into_an_accepted_native_report():
    goal, authority, receipt, hashes = real602603()
    assert receipt["status"] == "contract_rejected" and receipt["response_metadata"]["finish_reason"] == "tool_calls"
    errors = list(Draft202012Validator(receipt["request"]["structured_schema"]).iter_errors(receipt["output"]))
    assert len(errors) == 20 and all(list(error.absolute_path)[-1] == "status" for error in errors)
    with pytest.raises(ValidationError): validate(receipt["output"], goal, authority)
    # New native-shaped synthetic classifications illustrate the two duties;
    # they never overwrite, convert or adopt the old source report.
    report = synthetic_source(goal, authority)
    for path,function in [("whole_plan.beats.0.stimulus", "case_offer_or_promise"),
                          ("whole_plan.beats.2.response", "case_fact_or_intent")]:
        add_nonlegal_usage(report, goal, ref_for(goal,path), function)
    unsupported = add_legal_usage(report, goal, ref_for(goal,"whole_plan.beats.3.response"), relation="not_covered")
    unsupported["interpretation"] = "Synthetic benchmark for603's own interpretation: uncorrected assertion about notebook legal proof, authority does not cover it"
    result = validate(report, goal, authority)
    assert not result["accepted"] and len(result["uncertainties"]) == 1
    assert result["usage_gates"]["G007"][0]["gate"] == "clear" and result["usage_gates"]["G030"][0]["gate"] == "unknown"
    assert hashes == {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in hashes}


def test_actual602_written_agreement_term_does_not_demonstrate_agreement_conditions():
    goal, authority, _, _ = real602603()
    report = synthetic_source(goal, authority)
    ref = ref_for(goal,"whole_plan.beats.8.stimulus")
    row = add_legal_usage(report,goal,ref,relation="application_not_demonstrated",scope="case_application")
    row["authority_refs"] = ["L001"]
    row["actual_case_conditions"] = [actual_witness(goal,"whole_plan.beats.5.stimulus")]
    row["interpretation"] = "Synthetic conditional benchmark: if writing the term is presented as an already reached agreement, actual mutual consent has not been demonstrated"
    result = validate(report,goal,authority)
    assert not result["accepted"] and result["uncertainties"][0]["native_usage"]["basis_relation"] == "application_not_demonstrated"
    assert not result["legal_semantic_extraction_proven"]  # Not a local finding that an unsigned agreement is always invalid.


def test_actual602_native_reported_case_contradiction_routes_to_failure_without_local_signature_inference():
    goal, authority, _, _ = real602603()
    report = synthetic_source(goal, authority)
    ref = ref_for(goal,"whole_plan.beats.8.stimulus")
    row = add_legal_usage(report,goal,ref,relation="application_contradicted",scope="case_application")
    row["authority_refs"] = ["L001"]
    row["actual_case_conditions"] = [actual_witness(goal,"whole_plan.beats.5.stimulus"),
                               actual_witness(goal,"whole_plan.beats.7.stimulus")]
    row["interpretation"] = "Synthetic explicit case-contradiction relation exercises routing; only a reviewing model may interpret whether these responses negate agreement, not a local unsigned-means-no-agreement rule"
    result = validate(report,goal,authority)
    assert not result["accepted"] and result["findings"][0]["gate"] == "fail"
    assert len(result["findings"][0]["evidence"]["actual_case_conditions"]) == 2
    assert not result["semantic_truth_deterministically_proven"]


@pytest.mark.parametrize("fault", ["duplicate_equal", "duplicate_different", "omit_replace_duplicate", "wrong_ref", "missing_usages", "missing_ref"])
def test_native_observation_array_requires_exact_unique_source_keys(goal, authority, fault):
    report = synthetic_source(goal, authority)
    observations = report["source_observations"]
    if fault in ("duplicate_equal", "duplicate_different"):
        duplicated = deepcopy(observations[0])
        if fault == "duplicate_different":
            duplicated["usages"] = [{"kind": "uncertain", "quote": audit.build_evidence_catalog(goal)[duplicated["source_ref"]]["quote"],
                "interpretation": "Synthetic separate observation", "reason": "Duplicate exact source key must still fail"}]
        observations.append(duplicated)
    elif fault == "omit_replace_duplicate":
        # Keep array length exact and JSON objects distinct: uniqueItems alone
        # cannot establish uniqueness of the source_ref key.
        observations[-1] = {"source_ref": observations[0]["source_ref"], "usages": [
            {"kind": "uncertain", "quote": audit.build_evidence_catalog(goal)[observations[0]["source_ref"]]["quote"],
             "interpretation": "A different native row with the same key", "reason": "Exact-length duplicate-key fault"}]}
    elif fault == "wrong_ref": observations[-1]["source_ref"] = "G99999"
    elif fault == "missing_usages": observations[-1].pop("usages")
    else: observations[-1].pop("source_ref")
    before = deepcopy(report)
    with pytest.raises((ValidationError, audit.LegalUsageContractError)):
        validate(report, goal, authority)
    assert report == before


def test_array_order_is_not_an_invented_source_identity_or_semantic_gate(goal, authority):
    report = synthetic_source(goal, authority)
    add_nonlegal_usage(report, goal, "C:CC6")
    original = validate(report, goal, authority)
    report["source_observations"].reverse()
    reordered = validate(report, goal, authority)
    assert reordered["accepted"] and reordered["usage_gates"] == original["usage_gates"]
    assert reordered["audit_sha256"] != original["audit_sha256"]


@pytest.mark.parametrize("legal_kind", ["legal_assertion", "uncertain"])
def test_verified_legal_allows_nonlegal_alongside_required_legal_observation(goal, authority, legal_kind):
    report = synthetic_source(goal, authority)
    if legal_kind == "uncertain":
        source_usages(report, "C:VL2").clear()
        add_uncertain_usage(report, goal, "C:VL2")
    add_nonlegal_usage(report, goal, "C:VL2")
    result = validate(report, goal, authority)
    assert result["accepted"] is (legal_kind == "legal_assertion")


def test_compact_nonlegal_has_one_reason_while_legal_and_uncertain_shapes_are_unchanged(goal, authority):
    compact = audit.build_source_schema(goal, authority, context_sha256=CONTEXT)
    old = audit.relation_policy.build_source_schema(goal, authority, context_sha256=CONTEXT)
    for name in ("judgment", "uncertain"):
        assert compact["$defs"][name] == old["$defs"][name]
    old_nonlegal = deepcopy(old["$defs"]["non_legal_context"])
    old_nonlegal["properties"].pop("interpretation")
    old_nonlegal["required"].remove("interpretation")
    old_nonlegal["properties"]["pragmatic_function"]["enum"].append("narrative_scope_or_intent")
    assert compact["$defs"]["non_legal_context"] == old_nonlegal
    assert "narrative_scope_or_intent" not in audit.relation_policy.PRAGMATIC_FUNCTIONS
    report = synthetic_source(goal, authority)
    row = add_nonlegal_usage(report, goal, "C:CC6")
    assert set(row) == {"kind", "quote", "pragmatic_function", "reason"}
    row["interpretation"] = "Old duplicate field is forbidden"
    with pytest.raises(ValidationError): validate(report, goal, authority)


def test_strict_service_projection_cannot_replace_local_key_and_verified_checks(goal, authority):
    from src.content_factory.creative_deepseek_strict_schema_v1 import compile_source_schema
    schema = audit.build_source_schema(goal, authority, context_sha256=CONTEXT)
    service = compile_source_schema(schema)
    report = synthetic_source(goal, authority)
    report["source_observations"][-1] = {"source_ref": "C:VL2", "usages": []}
    Draft202012Validator(service).validate(report)
    with pytest.raises(audit.LegalUsageContractError, match="duplicate"):
        validate(report, goal, authority)
    report = synthetic_source(goal, authority)
    source_usages(report, "C:VL2").clear();add_nonlegal_usage(report, goal, "C:VL2")
    Draft202012Validator(service).validate(report)
    with pytest.raises(audit.LegalUsageContractError, match="all nonlegal"):
        validate(report, goal, authority)


@pytest.mark.parametrize("fault", ["unknown_origin", "duplicate_origin", "nonstring_origin", "origin_not_list"])
def test_claim_exact_origin_ids_still_validate_after_native_array_compaction(goal, authority, fault):
    goal["claims"][0]["origin_ids"] = {"unknown_origin": ["MISSING"], "duplicate_origin": ["U1", "U1"],
        "nonstring_origin": [1], "origin_not_list": "U1"}[fault]
    report = synthetic_source(goal, authority)
    with pytest.raises(audit.LegalUsageContractError, match="exact unique supplied source IDs"):
        validate(report, goal, authority)


@pytest.mark.parametrize("status,revision,valid", [("pass", "", True), ("pass", "mandatory", False),
    ("fail", "", False), ("fail", " ", False), ("fail", "Complete new native goal", True),
    ("unknown", "", True)])
def test_claim_judgment_conditional_remains_complete(status, revision, valid, goal, authority):
    report = synthetic_source(goal, authority)
    report["claim_checks"]["UC1"].update(status=status, required_revision=revision)
    if not valid:
        with pytest.raises(ValidationError): validate(report, goal, authority)
    else:
        result = validate(report, goal, authority)
        assert result["accepted"] is (status == "pass")
        assert result["findings"] if status == "fail" else result["uncertainties"] if status == "unknown" else not result["findings"]


def test_mixed_verified_legal_and_film_scope_can_be_two_exact_native_observations(goal, authority):
    legal = goal["claims"][1]["text"]
    scope = "本片不判定本案最后得到多少补偿。"
    goal["claims"][1]["text"] += scope
    report = synthetic_source(goal, authority)
    row = source_usages(report, "C:VL2")[0]
    row["quote"] = legal
    row["interpretation_frame_evidence"] = [{"frame_ref": "C:VL2", "quote": scope}]
    supplement = add_nonlegal_usage(report, goal, "C:VL2", "narrative_scope_or_intent")
    supplement["quote"] = scope
    result = validate(report, goal, authority)
    assert result["accepted"] and [item["kind"] for item in result["usage_gates"]["C:VL2"]] == ["legal_assertion", "non_legal_context"]
    assert result["legal_evidence_roles_separated"] and not result["frame_evidence_used_for_legal_admission"]
    assert result["legal_usage_citations"]["C:VL2"][0]["interpretation_frame_evidence"][0]["frame_ref"] == "C:VL2"


@pytest.mark.parametrize("relation,scope,treatment", [("supported", "case_application", "asserted"),
    ("application_contradicted", "case_application", "asserted"), ("contradicts", "general_rule", "actually_corrected"),
    ("application_contradicted", "case_application", "actually_corrected")])
@pytest.mark.parametrize("frame_path", ["whole_plan.ending.open_legal_question", "whole_plan.characters.0.role", "whole_plan.beats.0.goal"])
def test_frame_never_substitutes_for_actual_case_conditions_or_enacted_correction(goal, authority, relation, scope, treatment, frame_path):
    report = synthetic_source(goal, authority)
    row = add_legal_usage(report, goal, "C:CC6", relation=relation, scope=scope, treatment=treatment)
    row["interpretation_frame_evidence"] = [frame_witness(goal, frame_path)]
    with pytest.raises(audit.LegalUsageContractError) as caught:
        validate(report, goal, authority)
    assert "/actual_case_conditions" in caught.value.path


@pytest.mark.parametrize("relation,treatment,gate", [("not_covered", "asserted", "unknown"),
    ("contradicts", "asserted", "fail"), ("unknown", "actually_corrected", "unknown"),
    ("not_covered", "actually_corrected", "unknown")])
def test_frame_does_not_prove_support_or_clear_unknown_relation(goal, authority, relation, treatment, gate):
    report = synthetic_source(goal, authority)
    actual = [actual_witness(goal)] if treatment == "actually_corrected" else []
    row = add_legal_usage(report, goal, "C:CC6", relation=relation, treatment=treatment,
        actual_case_conditions=actual, interpretation_frame_evidence=[frame_witness(goal)])
    result = validate(report, goal, authority)
    assert not result["accepted"] and result["usage_gates"]["C:CC6"][0]["gate"] == gate
    finding = (result["findings"] if gate == "fail" else result["uncertainties"])[0]
    assert finding["native_usage"] == row and finding["evidence"]["interpretation_frame_evidence"]


def test_general_rule_can_have_frame_and_no_actual_conditions(goal, authority):
    report = synthetic_source(goal, authority)
    source_usages(report, "C:VL2")[0]["interpretation_frame_evidence"] = [frame_witness(goal)]
    result = validate(report, goal, authority)
    assert result["accepted"] and result["actual_condition_requirement_preserved"]


@pytest.mark.parametrize("field,fault", [("actual_case_conditions", "frame_as_event"),
    ("actual_case_conditions", "wrong_quote"), ("actual_case_conditions", "frame_key"),
    ("interpretation_frame_evidence", "wrong_ref"), ("interpretation_frame_evidence", "wrong_quote"),
    ("interpretation_frame_evidence", "event_key")])
def test_native_role_reference_names_directories_and_quotes_are_exact(goal, authority, field, fault):
    report = synthetic_source(goal, authority)
    row = add_legal_usage(report, goal, "C:CC6")
    if field == "actual_case_conditions":
        item = actual_witness(goal)
        if fault == "frame_as_event": item = {"event_ref": ref_for(goal, "whole_plan.ending.open_legal_question"), "quote": goal["whole_plan"]["ending"]["open_legal_question"]}
        elif fault == "wrong_quote": item["quote"] = "没有发生的条件"
        else: item = {"frame_ref": item["event_ref"], "quote": item["quote"]}
    else:
        item = frame_witness(goal)
        if fault == "wrong_ref": item["frame_ref"] = "G99999"
        elif fault == "wrong_quote": item["quote"] = "不在该原文中的说明"
        else: item = {"event_ref": item["frame_ref"], "quote": item["quote"]}
    row[field] = [item]
    with pytest.raises((ValidationError, audit.LegalUsageContractError)):
        validate(report, goal, authority)


def test_source3_native_schema_validation_and_report_construction_are_never_used(goal, authority, monkeypatch):
    from src.content_factory import creative_goal_legal_usage_source_audit_v3 as frozen3
    def forbid(*args, **kwargs): raise AssertionError("v3 native admission or construction called")
    monkeypatch.setattr(frozen3, "build_source_schema", forbid)
    monkeypatch.setattr(frozen3, "validate_source", forbid)
    assert validate(synthetic_source(goal, authority), goal, authority)["accepted"]


def test_actual609_610_report_is_never_renamed_or_converted_to_source4():
    root = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_22"
    paths = [root / "call_609_goal_plan_27.json", root / "call_610_goal_source_audit_01.json", root / "PRODUCTION_FREEZE.json"]
    original_hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    goal, receipt = [json.loads(path.read_text(encoding="utf-8-sig")) for path in paths[:2]]
    goal = goal["output"]
    payload = json.loads(receipt["request"]["messages"][1]["content"])
    authority = {key: payload[key] for key in ("verified_legal_context", "origin_catalog")}
    old = deepcopy(receipt["output"])
    with pytest.raises(ValidationError):
        audit.validate_source(old, goal, authority, context_sha256=payload and audit.digest(payload))
    assert receipt["output"] == old and old["schema"] == "creative_goal_legal_usage_source_audit/v3"
    # A new mock v4 report starts from the untouched current goal/authority,
    # never copies610 judgments or repairs its illegal references.
    report = synthetic_source(goal, authority)
    verified = [claim for claim in goal["claims"] if claim["kind"] == "verified_legal"]
    assert len(verified) == 3
    for claim in verified:
        ref = "C:" + claim["id"]
        supplement = add_nonlegal_usage(report, goal, ref, "case_fact_or_intent")
        supplement["reason"] = "Offline scope-split structural example, not semantic acceptance of609 or610"
    result = validate(report, goal, authority)
    assert result["accepted"] and not result["semantic_truth_deterministically_proven"]
    actual_refs = audit.build_actual_context_catalog(goal)
    all_refs = audit.build_evidence_catalog(goal)
    assert all(ref not in actual_refs and ref in all_refs for ref in ("G106", "G093", "G032"))
    assert original_hashes == {str(path): hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in original_hashes}


def test_event_ref_is_position_evidence_not_local_proof_a_future_act_occurred(goal, authority):
    goal["whole_plan"]["beats"][0]["response"] = "她说明天要去咨询，今晚没有去。"
    report = synthetic_source(goal, authority)
    row = add_legal_usage(report, goal, "C:CC6", relation="application_not_demonstrated", scope="case_application",
        actual_case_conditions=[actual_witness(goal)])
    roles = audit.build_evidence_role_catalog(goal)
    result = validate(report, goal, authority)
    assert not result["accepted"] and result["uncertainties"][0]["native_usage"] == row
    assert roles["event_ref_position_only"] and not roles["semantic_occurrence_verified"] and not roles["semantic_occurrence_proven"]
    assert not result["semantic_occurrence_verified"] and not result["semantic_occurrence_proven"]
    assert "不能证已经咨询" in audit.SOURCE_REVIEW_RULE
