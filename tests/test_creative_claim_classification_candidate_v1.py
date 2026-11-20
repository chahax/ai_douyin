"""Test the isolated public candidate API, never a production runner.

Independent atom classifications below are mock routing inputs, not a new
judgment of the frozen seventh draft. Original detector types remain archived.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.content_factory import creative_autonomous_text_contract_v13 as current
from src.content_factory import creative_autonomous_text_contract_v10 as original_findings
from src.content_factory import creative_autonomous_text_contract_v11 as compatibility
from src.content_factory import creative_claim_atoms_contract_v1 as candidate


def actual_case():
    root = Path(__file__).resolve().parents[1] / "data/production_trials/autonomous_text_pipeline_20261011/legal_resignation_15"
    def read(name): return json.loads((root / name).read_text(encoding="utf-8"))
    return root, read("INPUT.json")["brief"], read("versions/07/FULL_SCRIPT.json"), read("SOURCE_FACT_SCOPE.json"), \
        read("call_490_factual_scope_extract_07.json")["output"], read("call_491_finding_adjudication_07.json")["output"]


def atom(id_, quote, *, kind, speech="assertion", context="none", attribute="none", value="", support=None, relation="unknown", actor="zhou"):
    return {"id": id_, "quote": quote, "actual_actor_id": actor, "claim_kind": kind,
        "speech_function": speech, "context_action": context, "business_attribute_type": attribute,
        "attribute_value": value, "source_allowance_ids": support or [], "source_relation": relation}


def isolated_detection(native_finding, script, brief, scope):
    """Reduce only a new mock input, never change the archived native extract."""
    projected = current.project_sensitive_scope(scope, brief)
    extract = {"script_sha256": candidate._digest(script), "brief_sha256": candidate._digest(brief),
        "scope_sha256": candidate._digest(scope),
        "category_extracts": [{"category": q, "claims": []} for q in projected["protected_categories"]],
        "dialogue_findings": [], "unknown_items": [],
        "step_coverage": [{"source_ref": ref, "claim_ids": [], "dialogue_finding_ids": [], "unknown_ids": []}
                          for ref in current.evidence_catalog(script)]}
    row = deepcopy(native_finding["row"])
    if native_finding["kind"] == "claim":
        next(q for q in extract["category_extracts"] if q["category"] == native_finding["category"])["claims"].append(row)
        key = "claim_ids"
    elif native_finding["kind"] == "language":
        extract["dialogue_findings"].append(row); key = "dialogue_finding_ids"
    else:
        extract["unknown_items"].append(row); key = "unknown_ids"
    next(q for q in extract["step_coverage"] if q["source_ref"] == row["source_ref"])[key].append(row["id"])
    return extract


def wire(native_finding, atoms, script, brief, scope):
    extract = isolated_detection(native_finding, script, brief, scope)
    source_allowances = {q["id"]: q for q in scope["allowed_claims"]}
    rows = []
    for original in atoms:
        q = deepcopy(original)
        q["quote_start"] = native_finding["row"]["quote"].index(q["quote"])
        q["quote_end"] = q["quote_start"] + len(q["quote"])
        q["represented_actor_id"] = ""
        if q["speech_function"] == "assertion": q["speech_function"] = "statement"
        q["source_support"] = [{"allowance_id": id_, "source_quote": source_allowances[id_]["source_quotes"][0]["quote"],
             "source_claim_kind": "non_business_action", "source_attribute_type": "none", "source_attribute_value": ""}
             for id_ in q.pop("source_allowance_ids")]
        q["explanation"] = "独立原子分类的离线模拟，只验证合同与路由，不能证明模型语义判断准确。"
        rows.append(q)
    value = {"extract_sha256": candidate._digest(extract), "script_sha256": candidate._digest(script),
         "brief_sha256": candidate._digest(brief), "scope_sha256": candidate._digest(scope),
         "findings": [{"finding_id": native_finding["row"]["id"], "atoms": rows}]}
    return value, extract


def candidate_decide(native_finding, atoms, script, brief, scope):
    value, extract = wire(native_finding, atoms, script, brief, scope)
    result = candidate.decide(value, extract, script, brief, scope)
    result["failed_atom_ids"] = [q["atom_id"] for q in result["revision_requirements"]]
    result["unknown_atom_ids"] = [q["atom_id"] for q in result["uncertainties"]]
    result["original_detector_type"] = native_finding["row"].get("attribute_type")
    return result


def get_finding(extract, id_):
    return original_findings._findings(extract)[id_]


def test_actual_490_491_private_request_is_blocked_by_original_business_promise_type():
    _, brief, script, scope, extract, verdict = actual_case()
    before = deepcopy((extract, verdict))
    result = current.decide_adjudication(verdict, extract, script, brief, scope)
    row = get_finding(extract, "C-FUU-01")["row"]
    assert row["attribute_type"] == "business_promise" and "未承诺" in row["attribute_value"]
    assert "private_pressure" not in result["contextual_compatibility"]["C-FUU-01"]["allowed_context_types"]
    assert "ADJUDICATION_CONTEXT_C-FUU-01" in {q["code"] for q in result["revision_requirements"]}
    assert (extract, verdict) == before


def test_actual_current_signature_failure_is_source_category_and_actor_mismatch_not_same_type_rule():
    _, brief, script, scope, extract, verdict = actual_case()
    finding = get_finding(extract, "C-BP-01")
    entry = next(q for q in verdict["findings"] if q["finding_id"] == "C-BP-01")
    table = compatibility.contextual_compatibility(extract, brief)["C-BP-01"]
    assert "private_pressure" in table["allowed_context_types"]
    assert finding["row"]["actor_id"] == "company"
    assert current.evidence_catalog(script)[finding["row"]["source_ref"]]["speaker"] == "zhou"
    a4 = next(q for q in scope["allowed_claims"] if q["id"] == "A4")
    assert a4["category"] == "procedural_action" and a4["actor_id"] == "zhou"
    assert not compatibility._compatible_source(entry, finding, scope, brief)


def test_isolated_independent_private_action_can_reclassify_detector_type_without_changing_original():
    _, brief, script, scope, extract, _ = actual_case()
    finding = get_finding(extract, "C-FUU-01")
    before = deepcopy(finding)
    atoms = [atom("private", finding["row"]["quote"], kind="non_business_action", speech="request",
                  context="private_request", support=["A6"], relation="source_supported")]
    result = candidate_decide(finding, atoms, script, brief, scope)
    assert result["status"] == "claim_atoms_ready" and result["original_detector_type"] == "business_promise"
    assert finding == before


def test_current_request_and_unknown_preparation_are_separate_atoms_not_whole_sentence_exemption():
    _, brief, script, scope, extract, _ = actual_case()
    finding = get_finding(extract, "C-BP-01")
    atoms = [atom("preparation", "流程都备好了", kind="unknown", actor="zhou"),
        atom("request", "这张申请你照着签一下", kind="non_business_action", speech="request",
             context="current_signature_request", support=["A4"], relation="source_supported", actor="zhou")]
    result = candidate_decide(finding, atoms, script, brief, scope)
    assert result["status"] == "halt_review_uncertain" and result["unknown_atom_ids"] == ["preparation"]
    with pytest.raises(ValueError, match="coverage"):
        candidate_decide(finding, atoms[1:], script, brief, scope)


def test_private_request_atom_cannot_dismiss_a_neighboring_real_future_business_guarantee():
    _, brief, script, scope, extract, _ = actual_case()
    script, finding = deepcopy(script), deepcopy(get_finding(extract, "C-FUU-01"))
    quote = "你体谅一下姐，签了我明天替你办完。"
    script["beats"][2]["steps"][2]["text"] = quote
    finding["row"].update(quote=quote, attribute_value="明天替你办完")
    atoms = [atom("private", "你体谅一下姐", kind="non_business_action", speech="request", context="private_request",
                   support=["A6"], relation="source_supported"),
             atom("promise", "签了我明天替你办完", kind="business_assertion", attribute="business_promise",
                  value="明天替你办完", relation="unsupported")]
    result = candidate_decide(finding, atoms, script, brief, scope)
    assert result["status"] == "needs_whole_revision" and result["failed_atom_ids"] == ["promise"]


def test_confirmed_deadline_language_and_unknown_original_preparation_still_block_actual_seventh():
    _, brief, script, scope, extract, verdict = actual_case()
    result = current.decide_adjudication(verdict, extract, script, brief, scope)
    assert {"FACT_SCOPE_C-EDT-01", "LANGUAGE_FOCUSED_D-01", "FACT_SCOPE_U-01"}.issubset(
        {q["code"] for q in result["revision_requirements"]})
    assert "ADJUDICATION_UNKNOWN_U-02" in {q["code"] for q in result["uncertainties"]}
    assert result["status"] == "needs_whole_revision"


def test_candidate_actual_speaker_and_true_source_quotes_cannot_be_faked():
    _, brief, script, scope, extract, _ = actual_case()
    finding = get_finding(extract, "C-FUU-01")
    a = atom("private", finding["row"]["quote"], kind="non_business_action", speech="request",
             context="private_request", support=["A6"], relation="source_supported", actor="company")
    with pytest.raises(ValueError):
        candidate_decide(finding, [a], script, brief, scope)
    a["actual_actor_id"] = "zhou"
    fake_scope = deepcopy(scope)
    next(q for q in fake_scope["allowed_claims"] if q["id"] == "A6")["source_quotes"][0]["quote"] = "源没有这个承诺"
    with pytest.raises(ValueError, match="source citation|source scope quote|invalid"):
        candidate_decide(finding, [a], script, brief, fake_scope)


def private_wire():
    _, brief, script, scope, extract, _ = actual_case()
    finding = get_finding(extract, "C-FUU-01")
    atoms = [atom("private", finding["row"]["quote"], kind="non_business_action", speech="request",
                  context="private_request", support=["A6"], relation="source_supported")]
    value, isolated = wire(finding, atoms, script, brief, scope)
    return value, isolated, script, brief, scope


def test_public_schema_and_complete_original_archival_are_real_candidate_outputs():
    from jsonschema import Draft202012Validator
    value, extract, script, brief, scope = private_wire()
    before = deepcopy((value, extract, script, brief, scope))
    schema = candidate.build_schema(extract, script, brief, scope)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)
    result = candidate.decide(value, extract, script, brief, scope)
    assert result["status"] == "claim_atoms_ready"
    assert result["original_detection"] == extract
    assert result["original_detection_sha256"] == candidate._digest(extract)
    assert result["candidate_not_integrated_into_production"] and not result["semantic_quality_proven"]
    assert not result["human_quality_approved"]
    assert (value, extract, script, brief, scope) == before


@pytest.mark.parametrize("field", ["extract_sha256", "script_sha256", "brief_sha256", "scope_sha256"])
def test_whole_input_binding_rejects_each_changed_sha(field):
    value, extract, script, brief, scope = private_wire()
    value[field] = "0" * 64
    with pytest.raises(ValueError):
        candidate.validate(value, extract, script, brief, scope)


def test_missing_finding_and_changed_quote_span_are_rejected():
    value, extract, script, brief, scope = private_wire()
    missing = deepcopy(value); missing["findings"] = []
    with pytest.raises(ValueError): candidate.validate(missing, extract, script, brief, scope)
    value["findings"][0]["atoms"][0]["quote_end"] -= 1
    with pytest.raises(ValueError, match="quote span"):
        candidate.validate(value, extract, script, brief, scope)


def test_registered_source_quote_cannot_be_replaced_by_normalized_value_or_foreign_fragment():
    value, extract, script, brief, scope = private_wire()
    value["findings"][0]["atoms"][0]["source_support"][0]["source_quote"] = "公司要求小林离开"
    with pytest.raises(ValueError, match="own registered allowance"):
        candidate.validate(value, extract, script, brief, scope)


def test_actual_literal_deadline_cannot_be_omitted_by_private_context_reclassification():
    _, brief, script, scope, extract, _ = actual_case()
    finding = get_finding(extract, "C-EDT-01")
    a = atom("deadline", finding["row"]["quote"], kind="business_assertion", attribute="departure_time",
             value=finding["row"]["attribute_value"], relation="unsupported")
    result = candidate_decide(finding, [a], script, brief, scope)
    assert result["status"] == "needs_whole_revision" and result["failed_atom_ids"] == ["deadline"]
    a.update(claim_kind="non_business_action", speech_function="request", context_action="private_request",
             business_attribute_type="none", attribute_value="", source_allowance_ids=["A6"], source_relation="source_supported")
    with pytest.raises(ValueError): candidate_decide(finding, [a], script, brief, scope)


def test_concrete_future_business_atom_cannot_use_private_source_as_business_permission():
    _, brief, script, scope, extract, _ = actual_case()
    script, finding = deepcopy(script), deepcopy(get_finding(extract, "C-FUU-01"))
    quote = "签了我明天替你办完。"
    script["beats"][2]["steps"][2]["text"] = quote
    finding["row"].update(quote=quote, attribute_value="明天替你办完")
    a = atom("promise", quote, kind="business_assertion", attribute="business_promise", value="明天替你办完",
             support=["A6"], relation="source_supported")
    result = candidate_decide(finding, [a], script, brief, scope)
    assert result["status"] == "needs_whole_revision" and result["failed_atom_ids"] == ["promise"]


def test_employee_refusal_keeps_actual_speaker_distinct_from_represented_company():
    _, brief, script, scope, extract, _ = actual_case()
    catalog = current.evidence_catalog(script)
    ref, entry = next((ref, q) for ref, q in catalog.items() if q["kind"] == "dialogue" and q["speaker"] == "xiaolin" and "不签" in q["quote"])
    finding = {"kind": "claim", "category": "business_procedure", "row": {"id": "MOCK-REFUSAL", "source_ref": ref,
        "quote": entry["quote"], "actor_id": "company", "attribute_type": "business_requirement", "attribute_value": "拒签",
        "modality": "assertion", "source_alignment": {"status": "unsupported", "allowance_id": "", "source_attribute_quote": "",
            "source_attribute_type": "none", "explanation": "独立模拟；实际行为由原子合同另行分类。"}}}
    a = atom("refusal", entry["quote"], actor="xiaolin", kind="non_business_action", speech="refusal", context="employee_refusal",
             support=["A5"], relation="source_supported")
    value, isolated = wire(finding, [a], script, brief, scope)
    value["findings"][0]["atoms"][0]["represented_actor_id"] = "company"
    assert candidate.decide(value, isolated, script, brief, scope)["status"] == "claim_atoms_ready"


def test_every_original_finding_is_preserved_and_unknown_cannot_be_handoff():
    _, brief, script, scope, extract, _ = actual_case()
    originals = original_findings._findings(extract)
    catalog = current.evidence_catalog(script)
    value = {"extract_sha256": candidate._digest(extract), "script_sha256": candidate._digest(script),
        "brief_sha256": candidate._digest(brief), "scope_sha256": candidate._digest(scope), "findings": []}
    for id_, finding in originals.items():
        row = finding["row"]
        value["findings"].append({"finding_id": id_, "atoms": [{"id": "unknown_" + id_, "quote_start": 0,
            "quote_end": len(row["quote"]), "quote": row["quote"], "actual_actor_id": catalog[row["source_ref"]]["speaker"],
            "represented_actor_id": "", "speech_function": "unknown", "claim_kind": "unknown", "context_action": "none",
            "business_attribute_type": row.get("attribute_type", "unknown"), "attribute_value": row.get("attribute_value", ""),
            "source_support": [], "source_relation": "unknown", "explanation": "全部保留未知，不把未证语义当通过。"}]})
    before = deepcopy(extract)
    result = candidate.decide(value, extract, script, brief, scope)
    assert result["status"] == "halt_review_uncertain"
    assert len(result["uncertainties"]) == len(originals) and result["original_detection"] == before == extract
    value["findings"].pop()
    with pytest.raises(ValueError): candidate.validate(value, extract, script, brief, scope)


def test_explicit_atom_failure_requires_whole_revision_while_preparation_unknown_is_retained():
    _, brief, script, scope, extract, _ = actual_case()
    finding = get_finding(extract, "C-BP-01")
    atoms = [atom("preparation", "流程都备好了", kind="unknown"),
        atom("request", "这张申请你照着签一下", kind="non_business_action", speech="request",
             context="current_signature_request", relation="unsupported")]
    result = candidate_decide(finding, atoms, script, brief, scope)
    assert result["status"] == "needs_whole_revision"
    assert result["failed_atom_ids"] == ["request"] and result["unknown_atom_ids"] == ["preparation"]
