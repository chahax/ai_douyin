"""Offline source-field coverage and exact native findings, not media review."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

from jsonschema import Draft202012Validator, ValidationError
import pytest

from src.content_factory import creative_goal_drama_audit_contract_v10 as old
from src.content_factory import creative_goal_drama_audit_contract_v11 as audit

SOURCE_CONTEXT, DRAMA_CONTEXT = "a" * 64, "b" * 64
PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("scope tests must never contact providers")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


@pytest.fixture
def goal():
    return {"claims": [{"id": "CC_END", "kind": "creative_choice", "text": "纸要放回文件夹。"}],
        "whole_plan": {"characters": [{"id": "worker", "name": "员工"}, {"id": "boss", "name": "主管"}],
            "scenes": [{"id": "office", "description": "办公室"}],
            "props": [{"id": "paper", "description": "单据", "owner_character_id": "boss"},
                      {"id": "phone", "description": "手机", "owner_character_id": "worker"}],
            "beats": [{"id": "b1", "stimulus": "员工说等一等。", "response": "主管翻开单据。",
                       "claim_refs": ["CC_END"]},
                      {"id": "b2", "goal": "留在办公室", "visible_change": "单据被放回文件夹。",
                       "claim_refs": ["CC_END"]}],
            "ending": {"visible_consequence": "单据留在文件夹里。", "emotional_landing": "员工不再说话。",
                       "claim_refs": ["CC_END"]}}}


def synthetic_drama(goal, context=DRAMA_CONTEXT):
    """A newly constructed synthetic report; never convert provider reviews."""
    first = next(iter(audit.build_scope_source_catalog(goal)))
    judgment = {"status": "pass", "reason": "Synthetic structure fixture, not semantic approval",
        "required_revision": "", "evidence_refs": [first],
        "counterexample_analysis": "Synthetic counterexample comparison only", "counterevidence_refs": []}
    return {"schema": audit.VERSION, "goal_sha256": audit.digest(goal),
        "audit_context_sha256": context,
        "goal_checks": {key: deepcopy(judgment) for key in audit.GOAL_CHECKS},
        "scope_observations": {ref: {"audible_speakers": [], "operated_props": []}
                               for ref in audit.build_scope_source_catalog(goal)},
        "closed_scope_findings": []}


def synthetic_source(goal):
    return {"schema": audit.SOURCE_AUDIT_VERSION, "goal_sha256": audit.digest(goal),
        "audit_context_sha256": SOURCE_CONTEXT, "claim_checks": {row["id"]: {
            "status": "pass", "reason": "Synthetic source fixture", "required_revision": ""}
            for row in goal["claims"]}}


def validate(document, goal):
    return audit.validate_drama(document, goal, context_sha256=DRAMA_CONTEXT)


def ref_for(goal, path):
    return next(ref for ref, row in audit.build_evidence_catalog(goal).items() if row["document_path"] == path)


def add_observation(document, goal, ref, kind="prop", identifier=None, quote=None):
    table, field = audit.OBSERVATION_TABLES[kind]
    row = {"source_ref": ref, "quote": quote or audit.build_evidence_catalog(goal)[ref]["quote"], field: identifier}
    document["scope_observations"][ref][table].append(row)
    return row


def indexed_finding(document, goal, ref, kind="prop", status="fail", identifier=None):
    observed = add_observation(document, goal, ref, kind, identifier)
    table, _ = audit.OBSERVATION_TABLES[kind]
    row = {"kind": "undeclared_" + kind, "status": status, "source_ref": ref,
        "quote": observed["quote"], "table": table,
        "observation_index": len(document["scope_observations"][ref][table]) - 1,
        "explanation": "Synthetic unregistered observed entity"}
    if status == "unknown": row.update(kind="uncertain_identity", entity_kind=kind)
    return row


def report(document, findings, status=None):
    document["closed_scope_findings"] = findings
    expected = "fail" if any(row["status"] == "fail" for row in findings) else "unknown" if findings else "pass"
    row = document["goal_checks"]["closed_production_scope"]
    row.update(status=status or expected, required_revision="Submit whole new native plan" if (status or expected) == "fail" else "")
    refs = [item["source_ref"] for finding in findings
            for item in (finding["evidence"] if finding["kind"] == "explicit_state_contradiction" else [finding])]
    row["evidence_refs"] = list(dict.fromkeys(row["evidence_refs"] + refs))
    row["counterevidence_refs"] = list(dict.fromkeys(refs)) if row["status"] != "pass" else []


def test_exact_every_beat_field_and_ending_coverage_without_duplicate_commitments(goal):
    schema = audit.build_drama_schema(goal, context_sha256=DRAMA_CONTEXT)
    Draft202012Validator.check_schema(schema)
    assert "commitment_checks" not in schema["properties"]
    assert "commitment_judgment" not in schema["$defs"]
    assert "commitment_checks" in old.build_drama_schema(goal, context_sha256=DRAMA_CONTEXT)["properties"]
    sources = audit.build_scope_source_catalog(goal)
    assert len(sources) == 6
    assert {row["document_path"] for row in sources.values()} == {
        "whole_plan.beats.0.stimulus", "whole_plan.beats.0.response", "whole_plan.beats.1.goal",
        "whole_plan.beats.1.visible_change", "whole_plan.ending.visible_consequence", "whole_plan.ending.emotional_landing"}
    assert audit.build_production_scope_catalog(goal)["source_scopes"] == sources
    document = synthetic_drama(goal)
    before, original = deepcopy(document), deepcopy(goal)
    result = validate(document, goal)
    assert result["accepted"] and result["scope_source_coverage_complete"]
    assert not result["scope_observations_complete_extraction_proven"]
    assert not result["semantic_truth_deterministically_proven"]
    assert not result["commitments_reviewed_in_this_packet"] and not result["human_approved"]
    assert document == before and goal == original


@pytest.mark.parametrize("path", ["whole_plan.beats.0.stimulus", "whole_plan.beats.1.visible_change",
                                  "whole_plan.ending.visible_consequence", "whole_plan.ending.emotional_landing"])
def test_omitting_any_source_field_is_a_contract_failure(goal, path):
    document = synthetic_drama(goal)
    document["scope_observations"].pop(ref_for(goal, path))
    with pytest.raises(ValidationError): validate(document, goal)


@pytest.mark.parametrize("fault", ["extra_g", "c_key", "beat_key", "missing_table", "legacy_commitments",
                                  "wrong_goal", "wrong_context", "old_version"])
def test_exact_key_set_current_identity_and_no_old_shape(goal, fault):
    document = synthetic_drama(goal)
    first = next(iter(document["scope_observations"]))
    if fault == "extra_g": document["scope_observations"]["G999"] = deepcopy(document["scope_observations"][first])
    elif fault == "c_key": document["scope_observations"]["C:CC_END"] = deepcopy(document["scope_observations"][first])
    elif fault == "beat_key": document["scope_observations"]["b1"] = document["scope_observations"].pop(first)
    elif fault == "missing_table": document["scope_observations"][first].pop("operated_props")
    elif fault == "legacy_commitments": document["commitment_checks"] = {}
    elif fault == "wrong_goal": document["goal_sha256"] = "0" * 64
    elif fault == "wrong_context": document["audit_context_sha256"] = "0" * 64
    else: document["schema"] = old.VERSION
    with pytest.raises(ValidationError): validate(document, goal)


@pytest.mark.parametrize("kind,status", [("prop", "fail"), ("prop", "unknown"), ("voice", "fail"), ("voice", "unknown")])
@pytest.mark.parametrize("path", ["whole_plan.beats.1.visible_change", "whole_plan.ending.visible_consequence"])
def test_null_beat_or_ending_identity_requires_native_typed_finding_and_blocks(goal, kind, status, path):
    document = synthetic_drama(goal)
    ref = ref_for(goal, path)
    finding = indexed_finding(document, goal, ref, kind, status)
    report(document, [finding])
    before = deepcopy(document)
    result = validate(document, goal)
    assert not result["accepted"] and document == before
    rows = result["findings"] if status == "fail" else result["uncertainties"]
    assert rows[0]["closed_scope_finding_evidence"][0]["observation_path"].startswith("/scope_observations/" + ref)
    assert result["undeclared_scope_observations"][0]["source_ref"] == ref


@pytest.mark.parametrize("kind,identifier", [("prop", "paper"), ("voice", "worker")])
def test_registered_native_entities_cannot_be_reported_as_missing(goal, kind, identifier):
    document = synthetic_drama(goal)
    ref = ref_for(goal, "whole_plan.beats.1.visible_change")
    finding = indexed_finding(document, goal, ref, kind, identifier=identifier)
    report(document, [finding])
    with pytest.raises(audit.ScopeEvidenceContractError, match="known declared"):
        validate(document, goal)


@pytest.mark.parametrize("fault", ["cross_source", "wrong_quote", "blank_quote", "wrong_id", "duplicate_observation",
                                  "null_without_finding", "missing_index", "different_finding_quote", "unreviewed_ref",
                                  "duplicate_finding", "legacy_beat_locator"])
def test_observations_and_findings_are_exact_and_self_consistent(goal, fault):
    document = synthetic_drama(goal)
    ref = ref_for(goal, "whole_plan.beats.1.visible_change")
    finding = indexed_finding(document, goal, ref)
    report(document, [finding])
    observed = document["scope_observations"][ref]["operated_props"][0]
    if fault == "cross_source": observed["source_ref"] = ref_for(goal, "whole_plan.ending.visible_consequence")
    elif fault == "wrong_quote": observed["quote"] = "不是当前原句"
    elif fault == "blank_quote": observed["quote"] = " "
    elif fault == "wrong_id": observed["declared_prop_id"] = "worker"
    elif fault == "duplicate_observation": document["scope_observations"][ref]["operated_props"].append(deepcopy(observed))
    elif fault == "null_without_finding": report(document, [])
    elif fault == "missing_index": finding["observation_index"] = 1
    elif fault == "different_finding_quote": finding["quote"] = "文件夹"
    elif fault == "unreviewed_ref":
        document["goal_checks"]["closed_production_scope"].update(evidence_refs=["C:CC_END"], counterevidence_refs=[])
    elif fault == "duplicate_finding":
        duplicate = deepcopy(finding);duplicate["explanation"] = "Same indexed item again"
        report(document, [finding, duplicate])
    else: finding["beat_id"] = "b2"
    with pytest.raises((ValidationError, audit.ScopeEvidenceContractError)): validate(document, goal)


def test_multiple_operated_entities_and_people_can_share_an_exact_source(goal):
    document = synthetic_drama(goal)
    ref = ref_for(goal, "whole_plan.beats.0.response")
    add_observation(document, goal, ref, identifier="paper")
    add_observation(document, goal, ref, identifier="phone")
    add_observation(document, goal, ref, kind="voice", identifier="worker")
    add_observation(document, goal, ref, kind="voice", identifier="boss")
    result = validate(document, goal)
    assert len(result["scope_observation_evidence"][ref]["operated_props"]) == 2
    assert len(result["scope_observation_evidence"][ref]["audible_speakers"]) == 2
    assert result["accepted"]  # extraction meaning is intentionally not proved


@pytest.mark.parametrize("kind,status", [("visible_actor", "fail"), ("visible_actor", "unknown"),
                                         ("scene", "fail"), ("scene", "unknown")])
def test_visible_actor_scene_and_unknown_finding_ability_preserved(goal, kind, status):
    document = synthetic_drama(goal)
    ref = ref_for(goal, "whole_plan.ending.visible_consequence")
    finding = {"kind": "undeclared_" + kind, "status": status, "source_ref": ref,
        "quote": audit.build_evidence_catalog(goal)[ref]["quote"], "entity_label": "unlisted entity",
        "declared_entity_id": None, "explanation": "Synthetic visible entity finding"}
    if status == "unknown": finding.update(kind="uncertain_identity", entity_kind=kind)
    report(document, [finding])
    assert not validate(document, goal)["accepted"]


def test_state_contradiction_keeps_exact_entity_type_and_two_distinct_current_quotes(goal):
    document = synthetic_drama(goal)
    refs = [ref_for(goal, "whole_plan.beats.1.visible_change"), ref_for(goal, "whole_plan.ending.visible_consequence")]
    finding = {"kind": "explicit_state_contradiction", "status": "fail", "entity_kind": "prop", "entity_id": "paper",
        "explanation": "Synthetic contradictory reported state", "evidence": [
            {"source_ref": ref, "quote": audit.build_evidence_catalog(goal)[ref]["quote"]} for ref in refs]}
    report(document, [finding])
    assert not validate(document, goal)["accepted"]
    finding["entity_id"] = "worker"
    with pytest.raises(ValidationError): validate(document, goal)
    finding["entity_id"] = "paper"
    finding["evidence"][1] = {"source_ref": refs[0], "quote": "文件夹"}
    with pytest.raises(audit.ScopeEvidenceContractError, match="distinct"):
        validate(document, goal)


def test_compiled_finding_preserves_original_native_partial_quote(goal):
    document = synthetic_drama(goal)
    ref = ref_for(goal, "whole_plan.beats.1.visible_change")
    finding = indexed_finding(document, goal, ref)
    finding["quote"] = "文件夹"
    document["scope_observations"][ref]["operated_props"][0]["quote"] = "文件夹"
    report(document, [finding])
    evidence = validate(document, goal)["closed_scope_finding_evidence"][0]["evidence"][0]
    assert evidence["quote"] == "文件夹"
    assert evidence["original_quote"] == "单据被放回文件夹。"


def test_closed_scope_status_cannot_mask_native_failure_or_unknown(goal):
    document = synthetic_drama(goal)
    ref = ref_for(goal, "whole_plan.beats.1.visible_change")
    finding = indexed_finding(document, goal, ref)
    report(document, [finding], status="unknown")
    with pytest.raises(audit.ScopeEvidenceContractError, match="native typed findings"):
        validate(document, goal)
    report(document, [], status="fail")
    with pytest.raises(audit.ScopeEvidenceContractError): validate(document, goal)


def test_two_current_native_documents_bundle_and_context_gate_preserved(goal):
    bundle = audit.build_bundle(synthetic_source(goal), synthetic_drama(goal))
    result = audit.validate_bundle(bundle, goal, source_context_sha256=SOURCE_CONTEXT, drama_context_sha256=DRAMA_CONTEXT)
    assert result["accepted"] and result["combined_decisions_only"]
    assert not result["native_single_combined_audit"] and not result["human_approved"]
    with pytest.raises(ValueError, match="distinct"):
        audit.validate_bundle(bundle, goal, source_context_sha256=SOURCE_CONTEXT, drama_context_sha256=SOURCE_CONTEXT)
    bundle["schema"] = old.BUNDLE_VERSION
    with pytest.raises(ValueError, match="never a converted"):
        audit.validate_bundle(bundle, goal, source_context_sha256=SOURCE_CONTEXT, drama_context_sha256=DRAMA_CONTEXT)


@pytest.mark.parametrize("value", [None, "", "B" * 64, "b" * 63, "z" * 64])
def test_context_identity_strict(value, goal):
    with pytest.raises(ValueError): audit.build_drama_schema(goal, context_sha256=value)


def test_real_585_588_omitted_G083_and_ending_rejected_and_new_synthetic_folder_failure():
    root = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_15"
    goal_path, receipt_path = root / "goals/native_01.json", root / "call_588_goal_drama_audit_01.json"
    if not goal_path.exists() or not receipt_path.exists():
        pytest.skip("read-only actual585/588 evidence absent")
    native_goal_bytes, receipt_bytes = goal_path.read_bytes(), receipt_path.read_bytes()
    goal = json.loads(native_goal_bytes.decode("utf-8-sig"))
    old_review = json.loads(receipt_bytes.decode("utf-8-sig"))["output"]
    assert audit.digest(goal) == "da246aed10b05d86db28d5df7e32026ea9d964057fd07f97bc3c01b7a4f1c6f6"
    assert audit.digest(old_review) == "7f77b02264e5fb6dc7d761b8bfd579e2f7a81bf3c9ad4a154de22396ea3aab86"
    assert old_review["goal_checks"]["closed_production_scope"]["status"] == "pass"
    assert "G083" in old_review["goal_checks"]["closed_production_scope"]["evidence_refs"]
    assert not any(item["source_ref"] == "G083" for item in old_review["scope_observations"]["b10"]["operated_props"])
    with pytest.raises(ValidationError): validate(old_review, goal)
    # NEW explicit synthetic v11 structure. It is not provider output or a
    # converted/accepted old review, and it does not automate Chinese meaning.
    synthetic = synthetic_drama(goal)
    expected = audit.build_scope_source_catalog(goal)
    assert "G083" in expected and "G107" in expected
    for missing in ["G083", "G104", "G105", "G106", "G107"]:
        incomplete = deepcopy(synthetic)
        incomplete["scope_observations"].pop(missing)
        with pytest.raises(ValidationError): validate(incomplete, goal)
    add_observation(synthetic, goal, "G083", identifier="pr_leave_form")
    folder = indexed_finding(synthetic, goal, "G083")
    report(synthetic, [folder])
    result = validate(synthetic, goal)
    assert not result["accepted"] and result["scope_source_coverage_complete"]
    assert result["findings"][0]["closed_scope_finding_evidence"][0]["observation_path"] == "/scope_observations/G083/operated_props/1"
    assert not result["scope_observations_complete_extraction_proven"]
    unreported = deepcopy(synthetic)
    report(unreported, [])
    with pytest.raises(audit.ScopeEvidenceContractError): validate(unreported, goal)
    assert goal_path.read_bytes() == native_goal_bytes and receipt_path.read_bytes() == receipt_bytes
    assert hashlib.sha256(receipt_bytes).hexdigest() == "6d41afbf100149fc5fc2d4e5c4213bc181da145eaff7a826634a7f0b7f5b35fd"
