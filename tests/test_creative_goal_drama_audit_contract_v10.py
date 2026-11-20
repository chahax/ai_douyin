"""Independent native v10 fixtures and read-only actual-570 counterexamples."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

from jsonschema import ValidationError
import pytest

from src.content_factory import creative_goal_drama_audit_contract_v10 as audit

SOURCE_CONTEXT, DRAMA_CONTEXT = "1" * 64, "2" * 64


@pytest.fixture(autouse=True)
def no_provider(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("offline contract tests must not contact providers")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


@pytest.fixture
def goal():
    return {"claims": [
        {"id": "CC_PHONE", "kind": "creative_choice", "text": "手机始终在观看者左手。"},
        {"id": "CC_PRESS", "kind": "creative_choice", "text": "左掌保持压着纸。"},
        {"id": "UG_GOAL", "kind": "user_audience_goal", "text": "人物有可见回应。"}],
        "whole_plan": {"characters": [
            {"id": "viewer", "name": "观看者", "want": "核对内容"},
            {"id": "owner", "name": "所有者", "want": "保留原件"}],
            "scenes": [{"id": "office", "description": "两人的办公室"}],
            "props": [{"id": "paper", "description": "表单", "owner_character_id": "owner"},
                      {"id": "phone", "description": "手机", "owner_character_id": "viewer"}],
            "beats": [
                {"id": "b1", "event": "观看者注视所有者的表单。门外传来另一个人的话。",
                 "visible_change": "手机在另一只手。", "claim_refs": ["CC_PHONE", "CC_PRESS", "UG_GOAL"]},
                {"id": "b2", "event": "观看者保留手机照片。", "visible_change": "原件仍在所有者一侧。",
                 "claim_refs": ["CC_PHONE"]}],
            "ending": {"attempt_result": "观看者拿到照片。", "claim_refs": ["CC_PHONE"]}}}


def synthetic_drama(goal, context=DRAMA_CONTEXT):
    """Build a new synthetic native document, never rewrite a provider response."""
    first = next(iter(audit.build_evidence_catalog(goal)))
    judgment = {"status": "pass", "reason": "Synthetic structure fixture; not semantic approval",
        "required_revision": "", "evidence_refs": [first],
        "counterexample_analysis": "Synthetic source comparison only", "counterevidence_refs": []}
    commitments = {}
    for identifier, usage in audit.build_commitment_usage_catalog(goal).items():
        checked = {key: [row["evidence_refs"][0]] for key, row in usage["usages"].items()}
        commitments[identifier] = {**deepcopy(judgment), "claim_ref": usage["claim_ref"],
            "evidence_refs": [usage["claim_ref"], *[refs[0] for refs in checked.values()]],
            "checked_usages": checked}
    return {"schema": audit.DRAMA_AUDIT_VERSION, "goal_sha256": audit.digest(goal),
        "audit_context_sha256": context,
        "goal_checks": {key: deepcopy(judgment) for key in audit.GOAL_CHECKS},
        "scope_observations": {beat["id"]: {"audible_speakers": [], "operated_props": []}
                               for beat in goal["whole_plan"]["beats"]},
        "commitment_checks": commitments, "closed_scope_findings": []}


def synthetic_source(goal):
    return {"schema": audit.SOURCE_AUDIT_VERSION, "goal_sha256": audit.digest(goal),
        "audit_context_sha256": SOURCE_CONTEXT, "claim_checks": {row["id"]: {
            "status": "pass", "reason": "Synthetic source fixture", "required_revision": ""}
            for row in goal["claims"]}}


def validate(document, goal):
    return audit.validate_drama(document, goal, context_sha256=DRAMA_CONTEXT)


def own_quote(goal, beat="b1"):
    ref = audit.build_production_scope_catalog(goal)["beat_scopes"][beat]["evidence_refs"][0]
    return ref, audit.build_evidence_catalog(goal)[ref]["quote"]


def observation_finding(document, goal, kind="voice", *, declared=None, status="fail"):
    table, field = audit.OBSERVATION_TABLES[kind]
    ref, quote = own_quote(goal)
    rows = document["scope_observations"]["b1"][table]
    index = len(rows)
    rows.append({"source_ref": ref, "quote": quote, field: declared})
    finding = {"kind": "undeclared_" + kind, "status": status, "beat_id": "b1", "table": table,
               "observation_index": index, "source_ref": ref, "quote": quote,
               "explanation": "Synthetic reported unlisted observed entity"}
    if status == "unknown":
        finding.update(kind="uncertain_identity", entity_kind=kind)
    return finding


def report(document, *findings, status=None):
    document["closed_scope_findings"] = list(findings)
    expected = "fail" if any(row["status"] == "fail" for row in findings) else "unknown" if findings else "pass"
    row = document["goal_checks"]["closed_production_scope"]
    row.update(status=status or expected, required_revision="Complete native replacement" if (status or expected) == "fail" else "")
    refs = [item["source_ref"] for finding in findings
            for item in (finding["evidence"] if finding["kind"] == "explicit_state_contradiction" else [finding])]
    row["evidence_refs"] = list(dict.fromkeys(row["evidence_refs"] + refs))
    row["counterevidence_refs"] = list(dict.fromkeys(refs)) if (status or expected) != "pass" else []


def test_v10_keeps_all_c_g_commitments_scope_and_native_identities(goal):
    document = synthetic_drama(goal)
    before, goal_before = deepcopy(document), deepcopy(goal)
    catalog = audit.build_evidence_catalog(goal)
    assert catalog == audit.base.build_evidence_catalog(goal)
    assert audit.build_commitment_usage_catalog(goal) == audit.base.build_commitment_usage_catalog(goal)
    schema = audit.build_drama_schema(goal, context_sha256=DRAMA_CONTEXT)
    old = audit.base.build_drama_schema(goal, context_sha256=DRAMA_CONTEXT)
    assert schema["$defs"] == old["$defs"]
    assert schema["properties"]["scope_observations"] == old["properties"]["scope_observations"]
    assert schema["properties"]["commitment_checks"] == old["properties"]["commitment_checks"]
    assert schema["properties"]["closed_scope_findings"]["maxItems"] == len(catalog) * len(audit.FINDING_KINDS)
    result = validate(document, goal)
    assert result["accepted"] and result["closed_scope_report_self_consistent"]
    assert result["closed_scope_findings"] == []
    assert not result["human_approved"] and not result["semantic_truth_deterministically_proven"]
    assert not result["scope_observations_complete_extraction_proven"]
    assert document == before and goal == goal_before
    bundle = audit.build_bundle(synthetic_source(goal), document)
    assert audit.validate_bundle(bundle, goal, source_context_sha256=SOURCE_CONTEXT,
                                 drama_context_sha256=DRAMA_CONTEXT)["accepted"]


@pytest.mark.parametrize("kind", ["voice", "prop"])
@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_genuine_null_observation_validly_fails_or_remains_unknown_and_blocks_bundle(goal, kind, status):
    document = synthetic_drama(goal)
    finding = observation_finding(document, goal, kind, status=status)
    report(document, finding)
    before = deepcopy(document)
    result = validate(document, goal)
    assert result["valid"] and not result["accepted"] and document == before
    rows = result["findings"] if status == "fail" else result["uncertainties"]
    assert rows[0]["closed_scope_findings"] == [finding]
    assert result["closed_scope_finding_evidence"][0]["observation_path"].endswith("/0")
    assert result["closed_scope_finding_evidence"][0]["evidence"][0]["quote"] == finding["quote"]
    bundle = audit.build_bundle(synthetic_source(goal), document)
    assert not audit.validate_bundle(bundle, goal, source_context_sha256=SOURCE_CONTEXT,
                                     drama_context_sha256=DRAMA_CONTEXT)["accepted"]


@pytest.mark.parametrize("kind,declared", [("voice", "viewer"), ("prop", "paper")])
@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_known_declared_observation_cannot_be_reported_as_unlisted_or_uncertain(goal, kind, declared, status):
    document = synthetic_drama(goal)
    finding = observation_finding(document, goal, kind, declared=declared, status=status)
    report(document, finding)
    with pytest.raises(audit.ScopeEvidenceContractError, match="known declared") as caught:
        validate(document, goal)
    assert caught.value.code == "CLOSED_SCOPE_EVIDENCE_CONTRACT_REJECTED"
    assert caught.value.diagnostics[0]["declared_id"] == declared


@pytest.mark.parametrize("fault", ["index_missing", "wrong_quote", "wrong_ref", "cross_beat", "unreported_ref", "duplicate_classification"])
def test_unlisted_finding_must_exactly_bind_its_own_observation_and_current_g(goal, fault):
    document = synthetic_drama(goal)
    finding = observation_finding(document, goal)
    report(document, finding)
    if fault == "index_missing":
        finding["observation_index"] = 1
    elif fault == "wrong_quote":
        finding["quote"] = finding["quote"][:3]
    elif fault == "wrong_ref":
        refs = audit.build_production_scope_catalog(goal)["beat_scopes"]["b1"]["evidence_refs"]
        finding["source_ref"] = refs[1]
        finding["quote"] = audit.build_evidence_catalog(goal)[refs[1]]["quote"]
        report(document, finding)
    elif fault == "cross_beat":
        finding["source_ref"], finding["quote"] = own_quote(goal, "b2")
        report(document, finding)
    elif fault == "unreported_ref":
        row = document["goal_checks"]["closed_production_scope"]
        row["evidence_refs"], row["counterevidence_refs"] = ["C:CC_PHONE"], []
    else:
        second = deepcopy(finding)
        second["explanation"] = "Same observation, another reported reason"
        report(document, finding, second)
    with pytest.raises(audit.ScopeEvidenceContractError):
        validate(document, goal)


@pytest.mark.parametrize("closed_status,typed_status", [("pass", "fail"), ("pass", "unknown"),
    ("unknown", "fail"), ("fail", "unknown")])
def test_closed_scope_status_cannot_disagree_with_typed_findings(goal, closed_status, typed_status):
    document = synthetic_drama(goal)
    finding = observation_finding(document, goal, status=typed_status)
    report(document, finding, status=closed_status)
    with pytest.raises(ValueError):
        validate(document, goal)


def test_fail_or_unknown_without_native_typed_findings_and_uncovered_null_are_contract_errors(goal):
    document = synthetic_drama(goal)
    for status in ("fail", "unknown"):
        report(document, status=status)
        with pytest.raises(audit.ScopeEvidenceContractError, match="match"):
            validate(document, goal)
    document = synthetic_drama(goal)
    observation_finding(document, goal)
    ref, quote = own_quote(goal)
    other = {"kind": "undeclared_visible_actor", "status": "fail", "beat_id": "b1",
        "source_ref": ref, "quote": quote, "entity_label": "new background actor",
        "declared_entity_id": None, "explanation": "Synthetic actor finding"}
    report(document, other)
    with pytest.raises(audit.ScopeEvidenceContractError, match="null scope observation"):
        validate(document, goal)


@pytest.mark.parametrize("kind", ["visible_actor", "scene"])
@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_visible_actor_and_scene_exact_evidence_and_unknown_identity_remain_blocking(goal, kind, status):
    document = synthetic_drama(goal)
    ref, quote = own_quote(goal)
    finding = {"kind": "undeclared_" + kind, "status": status, "beat_id": "b1",
        "source_ref": ref, "quote": quote, "entity_label": "unlisted native participant",
        "declared_entity_id": None, "explanation": "Model identity judgment, not deterministic truth"}
    if status == "unknown":
        finding.update(kind="uncertain_identity", entity_kind=kind)
    report(document, finding)
    assert not validate(document, goal)["accepted"]
    finding["entity_label"] = "viewer" if kind == "visible_actor" else "office"
    with pytest.raises(audit.ScopeEvidenceContractError, match="known declared ID"):
        validate(document, goal)
    finding["entity_label"] = "unlisted native participant"
    finding["declared_entity_id"] = "viewer" if kind == "visible_actor" else "office"
    with pytest.raises(ValidationError):
        validate(document, goal)


def contradiction(goal):
    ref, quote = own_quote(goal)
    return {"kind": "explicit_state_contradiction", "status": "fail", "entity_kind": "actor",
            "entity_id": "viewer", "explanation": "Model reports incompatible explicit hand states",
            "evidence": [{"source_ref": "C:CC_PHONE", "quote": goal["claims"][0]["text"]},
                         {"source_ref": ref, "quote": quote}]}


def test_explicit_state_contradiction_retains_original_two_source_quotes_and_entity(goal):
    document = synthetic_drama(goal)
    finding = contradiction(goal)
    # Substrings are exact quotations; the complete originals remain compiled.
    finding["evidence"][0]["quote"] = "观看者左手"
    report(document, finding)
    result = validate(document, goal)
    assert result["valid"] and not result["accepted"]
    assert result["closed_scope_finding_evidence"][0]["entity_id"] == "viewer"
    compiled = result["closed_scope_finding_evidence"][0]["evidence"][0]
    assert compiled["quote"] == "观看者左手" and compiled["original_quote"] == goal["claims"][0]["text"]


@pytest.mark.parametrize("fault", ["one_source", "same_source", "forged_quote", "unknown_entity", "wrong_entity_kind", "unknown_c", "no_explanation"])
def test_state_contradiction_cannot_replace_explicit_quoted_state_with_missing_detail(goal, fault):
    document = synthetic_drama(goal)
    finding = contradiction(goal)
    if fault == "one_source":
        finding["evidence"].pop()
    elif fault == "same_source":
        finding["evidence"][1] = {"source_ref": "C:CC_PHONE", "quote": "观看者"}
    elif fault == "forged_quote":
        finding["evidence"][1]["quote"] = "No corresponding explicit native statement"
    elif fault == "unknown_entity":
        finding["entity_id"] = "future_actor"
    elif fault == "wrong_entity_kind":
        finding["entity_kind"] = "prop"
    elif fault == "unknown_c":
        finding["evidence"][0]["source_ref"] = "C:NOT_THIS_PLAN"
    else:
        finding["explanation"] = " \n\t"
    report(document, finding)
    with pytest.raises((ValidationError, audit.ScopeEvidenceContractError)):
        validate(document, goal)


def test_uncertainty_cannot_hide_failure_and_no_reason_keyword_semantics_are_added(goal):
    document = synthetic_drama(goal)
    # Exact structure is checked. These words are deliberately not parsed as a
    # natural-language classifier or an automatic contradiction detector.
    document["goal_checks"]["closed_production_scope"]["reason"] = "缺登记 未声明 未知 矛盾 补逐拍登记"
    assert validate(document, goal)["accepted"]
    first = observation_finding(document, goal, "voice", status="unknown")
    second = observation_finding(document, goal, "prop", status="fail")
    report(document, first, second)
    assert validate(document, goal)["findings"]
    report(document, first, second, status="unknown")
    with pytest.raises(audit.ScopeEvidenceContractError, match="match"):
        validate(document, goal)


@pytest.mark.parametrize("fault", ["old_version", "missing_typed_field", "unknown_kind", "extra_fields",
                                  "old_bundle", "mixed_context", "wrong_commitment_g", "c_in_scope"])
def test_old_native_shapes_and_all_inherited_contract_guards_still_reject(goal, fault):
    document = synthetic_drama(goal)
    bundle = audit.build_bundle(synthetic_source(goal), document)
    document = bundle["native_drama_audit"]
    if fault == "old_version":
        document["schema"] = audit.base.DRAMA_AUDIT_VERSION
    elif fault == "missing_typed_field":
        document.pop("closed_scope_findings")
    elif fault in ("unknown_kind", "extra_fields"):
        finding = observation_finding(document, goal)
        report(document, finding)
        finding["kind"] = "reviewer_missing_table" if fault == "unknown_kind" else finding["kind"]
        if fault == "extra_fields":
            finding["made_up"] = True
    elif fault == "old_bundle":
        bundle["schema"] = audit.base.BUNDLE_VERSION
    elif fault == "mixed_context":
        document["audit_context_sha256"] = "f" * 64
    elif fault == "wrong_commitment_g":
        row = document["commitment_checks"]["CC_PHONE"]["checked_usages"]
        row["beat:b1"] = row["beat:b2"]
    else:
        document["scope_observations"]["b1"]["audible_speakers"] = [
            {"source_ref": "C:CC_PHONE", "quote": goal["claims"][0]["text"], "declared_character_id": "viewer"}]
    with pytest.raises((ValidationError, ValueError)):
        audit.validate_bundle(bundle, goal, source_context_sha256=SOURCE_CONTEXT, drama_context_sha256=DRAMA_CONTEXT)


@pytest.mark.parametrize("beat,table,declared", [
    ("b1", "operated_props", "prop_resign_form"),
    ("b2", "operated_props", "prop_resign_form"),
    ("b6", "operated_props", "prop_resign_form"),
    ("b6", "audible_speakers", "macheng"),
])
def test_actual_570_known_registered_observation_claimed_missing_is_rejected(beat, table, declared):
    root = Path(__file__).resolve().parents[1]
    directory = root / "data/production_trials/goal_context_text_production_20261013/round_11/goals"
    goal_path, review_path = directory / "native_01.json", directory / "drama_native_audit_01.json"
    before = {path: path.read_bytes() for path in (goal_path, review_path)}
    goal, old = json.loads(before[goal_path]), json.loads(before[review_path])
    historical = audit.base.validate_drama(old, goal, context_sha256=old["audit_context_sha256"])
    assert historical["valid"] and not historical["accepted"]
    field = "declared_prop_id" if table == "operated_props" else "declared_character_id"
    actual_index, actual_observation = next((i, row) for i, row in enumerate(old["scope_observations"][beat][table])
                                            if row[field] == declared)
    # Preserve the actual response's rejection/history. This newly constructed
    # offline native fixture isolates its self-contradictory classification.
    document = synthetic_drama(goal)
    document["scope_observations"][beat][table] = deepcopy(old["scope_observations"][beat][table])
    finding = {"kind": "undeclared_prop" if table == "operated_props" else "undeclared_voice",
        "status": "fail", "beat_id": beat, "table": table, "observation_index": actual_index,
        "source_ref": actual_observation["source_ref"], "quote": actual_observation["quote"],
        "explanation": "Actual 570 falsely attributes its own listed observation to missing planning registration"}
    report(document, finding)
    with pytest.raises(audit.ScopeEvidenceContractError, match="known declared"):
        validate(document, goal)
    with pytest.raises(ValidationError):
        audit.validate_drama(old, goal, context_sha256=old["audit_context_sha256"])
    for path, data in before.items():
        assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(data).digest()
