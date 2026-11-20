"""Offline exact legal-use evidence and verdicts, not semantic extraction proof."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

from jsonschema import Draft202012Validator, ValidationError
import pytest

from src.content_factory import creative_goal_legal_usage_source_audit_v1 as audit
from src.content_factory import creative_goal_evidence_view_v1 as evidence_view

CONTEXT = "c" * 64
PROJECT = Path(__file__).resolve().parents[1]
ROUND16 = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_16"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("legal-use contract tests must not contact providers")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


@pytest.fixture
def authority():
    return {"verified_legal_context": {"schema": "verified_legal_story_context/v1",
        "jurisdiction": "中国大陆", "scope": "保留条件，不作个案结论",
        "sources": [{"id": "LC", "title": "劳动合同法", "url": "https://example.invalid/law",
                     "version": "synthetic offline authority", "articles": ["36", "37", "38", "46"]}],
        "facts": [{"source_id": "LC", "articles": ["36", "46(2)"],
                   "paraphrase": "单位提出并协商一致解除，依法衔接经济补偿。"},
                  {"source_id": "LC", "articles": ["37", "38", "46(1)"],
                   "paraphrase": "第38条基于单位特定违法情形解除，依法衔接经济补偿。"}],
        "creative_boundaries": ["不推定个案支持或补偿金额。"]},
        "origin_catalog": {"platform_metadata": {},
            "verified_legal": {"L001": {"path": "verified_legal_context.facts.0", "original_id": "L001",
                                       "authority": "verified_legal_with_conditions"},
                               "L002": {"path": "verified_legal_context.facts.1", "original_id": "L002",
                                       "authority": "verified_legal_with_conditions"}},
            "user": {"U1": {"path": "user_goal_contract.constraints.0", "original_id": "U1",
                            "authority": "user_constraint"}}}}


@pytest.fixture
def goal():
    return {"claims": [
        {"id": "UC1", "kind": "user_constraint", "text": "保留法律条件。", "origin_ids": ["U1"]},
        {"id": "VL2", "kind": "verified_legal", "text": "第38条解除与经济补偿有法定衔接。", "origin_ids": ["L002"]},
        {"id": "CC6", "kind": "creative_choice", "text": "虚构设定：主管说第38条自己走就没有补偿。"}],
        "whole_plan": {"premise": "同一间办公室里主管催签，员工不签。",
            "characters": [{"id": "worker", "name": "小林", "role": "员工"},
                           {"id": "boss", "name": "周姐", "role": "人事"}],
            "props": [{"id": "paper", "description": "一张未签的表。", "owner_character_id": "boss"}],
            "scenes": [{"id": "office", "description": "办公室"}],
            "beats": [{"id": "b1", "scene_id": "office", "goal": "让员工签字",
                       "stimulus": "主管说：第38条自己走就没有补偿。",
                       "response": "员工指出单位违法情形的第38条解除依法有经济补偿，拒绝这句话。",
                       "claim_refs": ["CC6"]}],
            "ending": {"visible_consequence": "员工没签，主管收回表。", "open_legal_question": "个案是否支持仍未决定。",
                       "claim_refs": ["CC6"]}}}


def synthetic_source(goal, authority, context=CONTEXT):
    """New synthetic structural report; never adapt a provider report to pass."""
    document = {"schema": audit.VERSION, "goal_sha256": audit.digest(goal),
        "audit_context_sha256": context, "authority_context_sha256": audit.digest(authority),
        "claim_checks": {row["id"]: {"status": "pass", "reason": "Synthetic source-kind judgment only",
                                      "required_revision": ""} for row in goal["claims"]},
        "legal_usage_scan": {ref: [] for ref in audit.build_evidence_catalog(goal)}}
    for claim in goal["claims"]:
        if claim["kind"] == "verified_legal":
            row = synthetic_usage(goal, "C:" + claim["id"])
            row["authority_refs"] = list(claim["origin_ids"])
            document["legal_usage_scan"]["C:" + claim["id"]].append(row)
    return document


def ref_for(goal, path):
    return next(ref for ref, row in audit.build_evidence_catalog(goal).items() if row["document_path"] == path)


def synthetic_usage(goal, ref, *, relation="supported", portrayal="direct_or_endorsed", status="pass"):
    return {"quote": audit.build_evidence_catalog(goal)[ref]["quote"],
        "legal_interpretation": "Synthetic legal proposition interpretation, not extracted by local code",
        "authority_refs": ["L002"] if relation in ("supported", "contradicts") else [],
        "context_evidence": [], "basis_relation": relation, "portrayal": portrayal,
        "status": status, "reason": "Synthetic relation judgment only",
        "required_revision": "Submit complete new native plan" if status == "fail" else ""}


def add_usage(document, goal, ref, **kwargs):
    usage = synthetic_usage(goal, ref, **kwargs)
    document["legal_usage_scan"][ref].append(usage)
    return usage


def validate(document, goal, authority):
    return audit.validate_source(document, goal, authority, context_sha256=CONTEXT)


def test_full_current_cg_schema_uses_shared_definition_and_all_original_fields(goal, authority):
    schema = audit.build_source_schema(goal, authority, context_sha256=CONTEXT)
    Draft202012Validator.check_schema(schema)
    refs = audit.build_evidence_catalog(goal)
    assert set(schema["properties"]["legal_usage_scan"]["properties"]) == set(refs)
    rows = schema["properties"]["legal_usage_scan"]["properties"]
    assert rows["C:VL2"] == {"allOf": [{"$ref": "#/$defs/legal_usage_rows"}, {"minItems": 1}]}
    assert all(row == {"$ref": "#/$defs/legal_usage_rows"} for ref, row in rows.items() if ref != "C:VL2")
    assert "C:CC6" in refs and any(row["document_path"].startswith("whole_plan.props.") for row in refs.values())
    original_goal, original_authority = deepcopy(goal), deepcopy(authority)
    document = synthetic_source(goal, authority)
    original_report = deepcopy(document)
    result = validate(document, goal, authority)
    assert result["valid"] and result["accepted"] and result["covered_source_count"] == len(refs)
    assert result["legal_usage_coverage_complete"] and result["reported_relations_self_consistent"]
    assert not result["legal_semantic_extraction_proven"] and not result["correction_semantically_proven"]
    assert not result["semantic_truth_deterministically_proven"] and not result["human_approved"]
    assert (goal, authority, document) == (original_goal, original_authority, original_report)


@pytest.mark.parametrize("path", ["claims.2.text", "whole_plan.beats.0.stimulus", "whole_plan.beats.0.goal",
    "whole_plan.ending.open_legal_question", "whole_plan.props.0.description", "whole_plan.characters.0.role", "whole_plan.premise"])
def test_any_omitted_claim_or_whole_plan_source_is_rejected(goal, authority, path):
    document = synthetic_source(goal, authority)
    document["legal_usage_scan"].pop(ref_for(goal, path))
    with pytest.raises(ValidationError): validate(document, goal, authority)


@pytest.mark.parametrize("fault", ["missing_claim", "extra_ref", "beat_key", "wrong_goal", "wrong_context",
    "wrong_authority", "old_version", "missing_scan", "extra_summary"])
def test_exact_report_keys_and_source_identity(goal, authority, fault):
    document = synthetic_source(goal, authority)
    if fault == "missing_claim": document["claim_checks"].pop("CC6")
    elif fault == "extra_ref": document["legal_usage_scan"]["G999"] = []
    elif fault == "beat_key": document["legal_usage_scan"]["b1"] = document["legal_usage_scan"].pop("C:CC6")
    elif fault == "wrong_goal": document["goal_sha256"] = "0" * 64
    elif fault == "wrong_context": document["audit_context_sha256"] = "0" * 64
    elif fault == "wrong_authority": document["authority_context_sha256"] = "0" * 64
    elif fault == "old_version": document["schema"] = "creative_goal_context_workflow/v7/source_audit"
    elif fault == "missing_scan": document.pop("legal_usage_scan")
    else: document["summary"] = "not native contract"
    with pytest.raises(ValidationError): validate(document, goal, authority)


@pytest.mark.parametrize("value", [None, "", "x" * 64, "A" * 64, "0" * 63])
def test_context_identity_is_not_optional(goal, authority, value):
    with pytest.raises(audit.LegalUsageContractError): audit.build_source_schema(goal, authority, context_sha256=value)


@pytest.mark.parametrize("relation,portrayal,status,accepted", [
    ("supported", "direct_or_endorsed", "pass", True),
    ("supported", "direct_or_endorsed", "fail", False),
    ("contradicts", "direct_or_endorsed", "fail", False),
    ("contradicts", "open_or_question", "fail", False),
    ("not_covered", "direct_or_endorsed", "unknown", False),
    ("unknown", "direct_or_endorsed", "unknown", False),
    ("supported", "unknown", "unknown", False),
])
def test_reported_relations_and_uncertainties_control_admission(goal, authority, relation, portrayal, status, accepted):
    document = synthetic_source(goal, authority)
    row = add_usage(document, goal, "C:CC6", relation=relation, portrayal=portrayal, status=status)
    result = validate(document, goal, authority)
    assert result["accepted"] is accepted
    if status != "pass":
        findings = result["findings"] if status == "fail" else result["uncertainties"]
        assert findings[0]["source_ref"] == "C:CC6" and findings[0]["basis_relation"] == relation
        assert result["citations"]["CC6"]["source_ref"] == "C:CC6"
    assert document["claim_checks"]["CC6"]["status"] == "pass"  # Classification cannot exempt the legal-use row.
    assert row["quote"] == goal["claims"][2]["text"]


@pytest.mark.parametrize("relation,portrayal", [("contradicts", "direct_or_endorsed"),
    ("contradicts", "open_or_question"), ("not_covered", "direct_or_endorsed"),
    ("unknown", "direct_or_endorsed"), ("supported", "unknown")])
def test_fictional_label_or_question_tone_cannot_make_reported_contradiction_or_unknown_pass(goal, authority, relation, portrayal):
    document = synthetic_source(goal, authority)
    add_usage(document, goal, "C:CC6", relation=relation, portrayal=portrayal)
    with pytest.raises(ValidationError): validate(document, goal, authority)


def test_corrected_character_misbelief_keeps_contradiction_and_exact_actual_correction_evidence(goal, authority):
    document = synthetic_source(goal, authority)
    usage = add_usage(document, goal, "C:CC6", relation="contradicts", portrayal="contested_and_corrected")
    response = ref_for(goal, "whole_plan.beats.0.response")
    usage["context_evidence"] = [{"source_ref": response, "quote": "第38条解除依法有经济补偿"}]
    result = validate(document, goal, authority)
    assert result["accepted"]
    evidence = result["legal_usage_citations"]["C:CC6"][0]
    assert evidence["context_evidence"][0]["document_path"] == "whole_plan.beats.0.response"
    assert evidence["context_evidence"][0]["original_quote"] == goal["whole_plan"]["beats"][0]["response"]
    assert evidence["authority_citations"][0]["fact"] == authority["verified_legal_context"]["facts"][1]
    assert evidence["origin_refs"] == ["L002"]
    assert not result["correction_semantically_proven"]


@pytest.mark.parametrize("context_kind", ["none", "c_claim", "character_definition", "prop_definition", "wrong_quote", "other_g_quote"])
def test_correction_requires_nonempty_exact_current_actual_g_not_declaration(goal, authority, context_kind):
    document = synthetic_source(goal, authority)
    usage = add_usage(document, goal, "C:CC6", relation="contradicts", portrayal="contested_and_corrected")
    response = ref_for(goal, "whole_plan.beats.0.response")
    if context_kind == "c_claim": usage["context_evidence"] = [{"source_ref": "C:VL2", "quote": goal["claims"][1]["text"]}]
    elif context_kind in ("character_definition", "prop_definition"):
        path = "whole_plan.characters.0.role" if context_kind == "character_definition" else "whole_plan.props.0.description"
        ref = ref_for(goal, path)
        usage["context_evidence"] = [{"source_ref": ref, "quote": audit.build_evidence_catalog(goal)[ref]["quote"]}]
    elif context_kind in ("wrong_quote", "other_g_quote"):
        quote = "未出现的纠正" if context_kind == "wrong_quote" else goal["whole_plan"]["beats"][0]["stimulus"]
        usage["context_evidence"] = [{"source_ref": response, "quote": quote}]
    with pytest.raises((ValidationError, audit.LegalUsageContractError)): validate(document, goal, authority)


@pytest.mark.parametrize("fault", ["wrong_quote", "blank_quote", "cross_field_quote", "wrong_authority_id", "missing_authority",
    "duplicate_authority", "missing_interpretation", "blank_interpretation", "duplicate_usage", "blank_fail_revision", "pass_revision"])
def test_legal_use_original_quotes_exact_refs_and_native_judgment_fields(goal, authority, fault):
    document = synthetic_source(goal, authority)
    usage = add_usage(document, goal, "C:CC6")
    if fault == "wrong_quote": usage["quote"] = "不在当前原句里"
    elif fault == "blank_quote": usage["quote"] = "   "
    elif fault == "cross_field_quote": usage["quote"] = goal["whole_plan"]["beats"][0]["response"]
    elif fault == "wrong_authority_id": usage["authority_refs"] = ["LC"]
    elif fault == "missing_authority": usage["authority_refs"] = []
    elif fault == "duplicate_authority": usage["authority_refs"] = ["L002", "L002"]
    elif fault == "missing_interpretation": usage.pop("legal_interpretation")
    elif fault == "blank_interpretation": usage["legal_interpretation"] = "   "
    elif fault == "duplicate_usage": document["legal_usage_scan"]["C:CC6"].append(deepcopy(usage))
    elif fault == "blank_fail_revision": usage.update(status="fail", required_revision=" ")
    else: usage["required_revision"] = "modify despite pass"
    with pytest.raises((ValidationError, audit.LegalUsageContractError)): validate(document, goal, authority)


@pytest.mark.parametrize("fault", ["extra_top", "missing_fact", "missing_directory", "duplicate_path", "wrong_original_id",
    "bad_path", "wrong_authority_kind", "unknown_source", "duplicate_source", "source_drift", "condition_drift", "origin_drift"])
def test_complete_authority_identity_and_fact_directory_are_preserved(goal, authority, fault):
    document = synthetic_source(goal, authority)
    changed = deepcopy(authority)
    if fault == "extra_top": changed["summary"] = "replacement"
    elif fault == "missing_fact": changed["verified_legal_context"]["facts"].pop()
    elif fault == "missing_directory": changed["origin_catalog"]["verified_legal"].pop("L002")
    elif fault == "duplicate_path": changed["origin_catalog"]["verified_legal"]["L002"]["path"] = "verified_legal_context.facts.0"
    elif fault == "wrong_original_id": changed["origin_catalog"]["verified_legal"]["L002"]["original_id"] = "L001"
    elif fault == "bad_path": changed["origin_catalog"]["verified_legal"]["L002"]["path"] = "verified_legal_context.facts.01"
    elif fault == "wrong_authority_kind": changed["origin_catalog"]["verified_legal"]["L002"]["authority"] = "creative_choice"
    elif fault == "unknown_source": changed["verified_legal_context"]["facts"][1]["source_id"] = "invented"
    elif fault == "duplicate_source": changed["verified_legal_context"]["sources"].append(deepcopy(changed["verified_legal_context"]["sources"][0]))
    elif fault == "source_drift": changed["verified_legal_context"]["sources"][0]["version"] = "changed"
    elif fault == "condition_drift": changed["verified_legal_context"]["facts"][1]["paraphrase"] = "removed legal conditions"
    else: changed["origin_catalog"]["user"]["U1"]["path"] = "changed"
    with pytest.raises((ValidationError, audit.LegalUsageContractError)): validate(document, goal, changed)


def test_claim_source_and_actual_legal_proposition_are_separate_admission_conditions(goal, authority):
    document = synthetic_source(goal, authority)
    document["claim_checks"]["VL2"].update(status="unknown", reason="Source applicability not established")
    result = validate(document, goal, authority)
    assert not result["accepted"] and result["uncertainties"][0]["table"] == "claim_checks"
    evidence = result["citations"]["VL2"]
    assert evidence["origin_refs"] == ["L002"]
    assert evidence["authority_citations"][0]["document_path"] == "verified_legal_context.facts.1"
    assert evidence["authority_citations"][0]["source"] == authority["verified_legal_context"]["sources"][0]


def test_questions_and_choices_do_not_require_keyword_inference_or_legal_usage(goal, authority):
    goal["claims"][2]["text"] = "虚构设定：员工问有没有补偿，她想明天继续上班。"
    goal["whole_plan"]["beats"][0]["stimulus"] = "员工问第三十八条是什么意思？"
    document = synthetic_source(goal, authority)
    result = validate(document, goal, authority)
    assert result["accepted"] and document["legal_usage_scan"]["C:CC6"] == []
    assert not result["legal_semantic_extraction_proven"]


def test_empty_scan_is_not_local_proof_even_if_source_contains_wrong_legal_words(goal, authority):
    # The structural validator must not pretend to extract Chinese semantics.
    result = validate(synthetic_source(goal, authority), goal, authority)
    assert result["accepted"] and not result["legal_semantic_extraction_proven"]


def test_verified_legal_metadata_requires_at_least_one_observation_but_creative_choice_does_not(goal, authority):
    document = synthetic_source(goal, authority)
    assert document["legal_usage_scan"]["C:CC6"] == []
    document["legal_usage_scan"]["C:VL2"] = []
    with pytest.raises(ValidationError): validate(document, goal, authority)


@pytest.mark.parametrize("table,field,maximum", [
    ("claim", "reason", audit.MAX_REASON_CHARS), ("claim", "required_revision", audit.MAX_REVISION_CHARS),
    ("usage", "reason", audit.MAX_REASON_CHARS), ("usage", "required_revision", audit.MAX_REVISION_CHARS),
    ("usage", "legal_interpretation", audit.MAX_INTERPRETATION_CHARS), ("usage", "quote", audit.MAX_QUOTE_CHARS),
])
def test_native_output_strings_have_finite_bounds_and_are_never_locally_cut(goal, authority, table, field, maximum):
    document = synthetic_source(goal, authority)
    if table == "claim":
        row = document["claim_checks"]["CC6"]
    else:
        row = add_usage(document, goal, "C:CC6")
    if field == "required_revision": row["status"] = "fail"
    row[field] = "长" * (maximum + 1)
    before = deepcopy(document)
    with pytest.raises(ValidationError): validate(document, goal, authority)
    assert document == before


def test_each_source_has_finite_proposition_capacity_without_dropping_an_overflow(goal, authority):
    document = synthetic_source(goal, authority)
    for index in range(audit.MAX_USAGES_PER_SOURCE):
        usage = add_usage(document, goal, "C:CC6")
        usage["legal_interpretation"] = f"Synthetic distinct proposition {index} in same quoted span"
    assert validate(document, goal, authority)["valid"]
    overflow = add_usage(document, goal, "C:CC6")
    overflow["legal_interpretation"] = "Synthetic fifth proposition; must not silently discard"
    before = deepcopy(document)
    with pytest.raises(ValidationError): validate(document, goal, authority)
    assert document == before


def test_correction_context_evidence_has_finite_count(goal, authority):
    document = synthetic_source(goal, authority)
    usage = add_usage(document, goal, "C:CC6", relation="contradicts", portrayal="contested_and_corrected")
    refs = [ref for ref, item in audit.build_evidence_catalog(goal).items()
            if item["document_path"].startswith(("whole_plan.beats.", "whole_plan.ending."))]
    usage["context_evidence"] = [{"source_ref": ref, "quote": audit.build_evidence_catalog(goal)[ref]["quote"]}
                                 for ref in refs[:audit.MAX_CONTEXT_EVIDENCE]]
    assert validate(document, goal, authority)["valid"]
    ref = refs[audit.MAX_CONTEXT_EVIDENCE]
    usage["context_evidence"].append({"source_ref": ref, "quote": audit.build_evidence_catalog(goal)[ref]["quote"]})
    with pytest.raises(ValidationError): validate(document, goal, authority)


def test_total_bound_is_derived_from_current_directory_not_an_arbitrary_global_32(goal, authority):
    goal["whole_plan"]["beats"] = [{"id": f"b{i}", "stimulus": "第38条解除与经济补偿有法定衔接。"}
                                     for i in range(40)]
    document = synthetic_source(goal, authority)
    for ref, source in audit.build_evidence_catalog(goal).items():
        if source["document_path"].startswith("whole_plan.beats."):
            add_usage(document, goal, ref)
    result = validate(document, goal, authority)
    assert result["legal_usage_count"] == 41 and result["accepted"]
    assert result["maximum_usage_count"] == result["covered_source_count"] * audit.MAX_USAGES_PER_SOURCE
    assert not result["legal_semantic_extraction_proven"]


def test_original_whole_goal_lossless_view_is_not_duplicate_claim_payload(goal):
    view = evidence_view.build_lossless_goal_evidence_view(goal)
    assert evidence_view.reconstruct_goal(view) == goal
    assert view["goal_structure"]["claims"][2]["text"] == {"$goal_evidence_ref": "C:CC6"}
    assert view["evidence_catalog"]["C:CC6"]["quote"] == goal["claims"][2]["text"]


def real594():
    goal_path = ROUND16 / "goals/native_02.json"
    source_path = ROUND16 / "call_595_goal_source_audit_02.json"
    focus_path = ROUND16 / "call_596_goal_commitment_audit_02.json"
    paths = (goal_path, source_path, focus_path)
    assert all(path.is_file() for path in paths), "actual frozen round16 diagnostic evidence required"
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    goal, source, focus = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    user = json.loads(next(row["content"] for row in source["request"]["messages"] if row["role"] == "user"))
    authority = {key: deepcopy(user[key]) for key in ("verified_legal_context", "origin_catalog")}
    return goal, authority, source, focus, hashes


def test_actual594_595_596_classification_pass_did_not_prove_legal_usage_and_old_reports_cannot_convert():
    goal, authority, source, focus, before = real594()
    assert source["validation"]["accepted"] and focus["validation"]["accepted"]
    assert "第三十八条" in goal["claims"][24]["text"]
    assert "人物台词设定" in source["output"]["claim_checks"]["CC6"]["reason"]
    assert "第三十八条" in goal["whole_plan"]["beats"][5]["stimulus"]
    assert source["output"]["goal_sha256"] == focus["output"]["goal_sha256"] == audit.digest(goal)
    for old in (source["output"], focus["output"]):
        with pytest.raises(ValidationError): validate(old, goal, authority)
    # This is a new synthetic relation benchmark, not a conversion of 595/596.
    document = synthetic_source(goal, authority)
    beat_ref = ref_for(goal, "whole_plan.beats.5.stimulus")
    for ref in ("C:CC6", beat_ref):
        usage = add_usage(document, goal, ref, relation="contradicts", status="fail")
        usage["legal_interpretation"] = "Synthetic interpretation: 38 path is incorrectly framed as personal consequence while L002 preserves employer violation and compensation conditions"
    result = validate(document, goal, authority)
    assert result["valid"] and not result["accepted"]
    assert {row["source_ref"] for row in result["findings"]} == {"C:CC6", beat_ref}
    assert result["legal_usage_citations"][beat_ref][0]["authority_citations"][0]["fact"] == authority["verified_legal_context"]["facts"][1]
    assert {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in before} == before


@pytest.mark.parametrize("where", ["claim_only", "actual_only"])
def test_actual594_statement_still_needs_review_when_only_claim_or_only_actual_field_retains_it(where):
    goal, authority, _, _, _ = real594()
    if where == "claim_only":
        goal["whole_plan"]["beats"][5]["stimulus"] = "她要求写明由公司提出，不引用法律。"
        ref = "C:CC6"
    else:
        goal["claims"][24]["text"] = "虚构设定：她要求写明由公司提出。"
        ref = ref_for(goal, "whole_plan.beats.5.stimulus")
    document = synthetic_source(goal, authority)
    add_usage(document, goal, ref, relation="contradicts", status="fail")
    assert not validate(document, goal, authority)["accepted"]
