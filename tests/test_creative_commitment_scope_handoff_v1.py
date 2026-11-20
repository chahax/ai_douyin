"""Exact advisory handoff contracts; actual630 is never fabricated as new drama."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

import pytest

from src.content_factory import creative_commitment_scope_handoff_v1 as scope
from src.content_factory import creative_goal_context_workflow_v27 as w
from scripts import creative_review_injected_text_driver_v2 as driver
from scripts import creative_fresh_source_session_v1 as shared
from scripts.creative_m31_flash_role_clients_v1 import M31FlashRoleClients
from tests.test_creative_goal_context_workflow_v26 import (synthetic_case, synthetic_bundle, synthetic_full_reports,
    profile, payload, check_wire)
from tests.test_creative_goal_context_workflow_v23 import offline as historical_clock
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario

ROOT = Path(__file__).resolve().parents[1]
ACTUAL = ROOT / "data/production_trials/legal_scoped_text_session_20261015/round_01"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError("scope handoff tests cannot contact providers")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(M31FlashRoleClients, "__init__", deny)


@pytest.fixture
def source_case(causal_scenario):
    inputs, goal, opening, ids, native = synthetic_case(causal_scenario)
    return inputs, goal, opening, ids, native, synthetic_bundle(inputs, goal)


def scoped_reports(source_case, *, second=False):
    inputs, goal, opening, ids, native, bundle = source_case
    native = deepcopy(native)
    if second: native["title"] += "（完整合成新稿二）"
    _, _, _, _, reports = synthetic_full_reports(inputs, goal, opening, native, bundle)
    adapter = w.make_review_adapter(inputs, profile(), bundle)
    author = adapter.workflow.prepare_script_request(inputs, profile(), goal, bundle, opening_setup=opening, **ids)
    compiled = w.validate_script_document(native, author["views"], inputs["production_preferences"])["script"]
    prepared = {part: adapter.prepare_full_review_part_request(inputs, profile(), native, author["views"], part) for part in ("semantic", "physical")}
    # Entire new synthetic native reports, not converted actual provider output.
    for part, report in reports.items(): report["context_sha256"] = prepared[part]["context_sha256"]
    return adapter, author, native, compiled, prepared, reports


def test_actual630_complete_native_advisory_keeps_all19_uses_reasons_and_may_not_override_original_C():
    goal_path, audit_path = ACTUAL / "call_627_whole_plan_04.json", ACTUAL / "call_630_commitment_audit_04.json"
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (goal_path, audit_path)}
    goal, report = (json.loads(path.read_text("utf-8"))["output"] for path in (goal_path, audit_path))
    advisory = scope.read_native_advisory(goal, report, context_sha256=report["audit_context_sha256"])
    assert set(advisory) == {"schema", "authority", "native_commitment_audit"}
    assert advisory["authority"] == "fallible_model_interpretation_not_source_override"
    carried = advisory["native_commitment_audit"]
    assert carried == report and carried is not report
    assert len(carried["commitment_checks"]) == 9
    assert sum(len(row["actual_usages"]) for row in carried["commitment_checks"].values()) == 19
    assert carried["commitment_checks"]["CC.eleven_years"]["actual_usages"]["beat:B1"]["requirement_scope"] == "background_consistency"
    original = next(row["text"] for row in goal["claims"] if row["id"] == "CC.schedule_leverage")
    interpretation = carried["commitment_checks"]["CC.schedule_leverage"]["actual_usages"]["beat:B8"]["actual_interpretation"]
    assert "末拍" in original and "B6" in interpretation
    assert carried["goal_sha256"] == w.digest(goal) and w.digest(carried) == w.digest(report)
    assert before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (goal_path, audit_path)}


def test_scope_attach_verifies_the_complete_native_bundle_only_once(source_case, monkeypatch):
    inputs, goal, opening, ids, native, bundle = source_case
    base = w.prior.prepare_script_request(inputs, profile(), goal, bundle, opening_setup=opening, **ids)
    original = scope.workflow.validate_goal_audit
    seen = []
    def verified(*args, **kwargs): seen.append(1); return original(*args, **kwargs)
    monkeypatch.setattr(scope.workflow, "validate_goal_audit", verified)
    attached = scope.build_and_attach(payload(base), inputs, profile(), goal, bundle)
    assert len(seen) == 1 and scope.FIELD in attached


@pytest.mark.parametrize("fault", ["scope", "interpretation", "literal", "missing_usage", "extra_usage", "own_refs", "comparison_refs", "profile", "bundle", "paired", "native_report"])
def test_scope_snapshot_rejects_changed_native_data_or_any_binding(source_case, fault):
    inputs, goal, opening, ids, native, bundle = source_case
    snapshot = scope.build_snapshot(inputs, profile(), goal, bundle)
    row = next(iter(snapshot["native_commitment_audit"]["commitment_checks"].values()))
    usage_key, usage = next(iter(row["actual_usages"].items()))
    if fault == "scope": usage["requirement_scope"] = "local_event" if usage["requirement_scope"] != "local_event" else "mixed"
    elif fault == "interpretation": usage["actual_interpretation"] += " changed"
    elif fault == "literal": row["literal_requirement"] += " must be spoken"
    elif fault == "missing_usage": row["actual_usages"].pop(usage_key)
    elif fault == "extra_usage": row["actual_usages"]["beat:FOREIGN"] = deepcopy(usage)
    elif fault == "own_refs": usage["evidence_refs"] = []
    elif fault == "comparison_refs": usage["comparison_refs"] = ["E0001"]
    elif fault == "profile": snapshot["profile_sha256"] = "0" * 64
    elif fault == "bundle": snapshot["native_goal_audit_bundle_sha256"] = "0" * 64
    elif fault == "paired": snapshot["accepted_paired_snapshot_sha256"] = "0" * 64
    else: snapshot["native_commitment_audit"]["schema"] = "foreign/native"
    with pytest.raises(ValueError): scope.validate_snapshot(snapshot, inputs, profile(), goal, bundle)


def test_bound_v27_author_rejects_another_accepted_bundle_and_changed_original_input(source_case):
    inputs, goal, opening, ids, native, first = source_case
    second = deepcopy(first)
    second["native_drama_audit"]["paired_checks"]["records_by_target"]["ending"]["comparison"] += " Different accepted synthetic reading."
    assert w.validate_goal_audit(second, goal, inputs=inputs)["accepted"]
    adapter = w.make_review_adapter(inputs, profile(), first)
    with pytest.raises(ValueError, match="bound authoring"):
        adapter.workflow.prepare_script_request(inputs, profile(), goal, second, opening_setup=opening, **ids)
    changed = deepcopy(inputs); changed["user_goal_contract"]["constraints"][0]["text"] += " changed original source"
    with pytest.raises(ValueError):
        adapter.workflow.prepare_script_request(changed, profile(), goal, first, opening_setup=opening, **ids)
    changed_profile = profile(); changed_profile["director"]["parameters"]["temperature"] += .1
    with pytest.raises(ValueError):
        adapter.workflow.prepare_script_request(inputs, changed_profile, goal, first, opening_setup=opening, **ids)


@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_failed_or_unknown_native_commitment_never_reaches_a_writer(source_case, status):
    inputs, goal, opening, ids, native, bundle = source_case
    row = next(iter(bundle["native_commitment_audit"]["commitment_checks"].values()))
    row.update(status=status, required_revision="完整新计划" if status == "fail" else "")
    usage = next(iter(row["actual_usages"].values())); usage["relationship"] = "not_demonstrated" if status == "fail" else "unknown"
    with pytest.raises(ValueError): w.prepare_script_request(inputs, profile(), goal, bundle, opening_setup=opening, **ids)


def test_new_drama_gate_is_required_for_actual630_before_any_scope_snapshot_or_writer():
    load = lambda name: json.loads((ACTUAL / name).read_text("utf-8"))
    inputs, goal = load("INPUTS.json"), load("call_627_whole_plan_04.json")["output"]
    bundle = w.build_goal_audit_bundle(*(load(name)["output"] for name in (
        "call_628_scope_audit_04.json", "call_629_source_audit_04.json", "call_630_commitment_audit_04.json", "call_631_drama_audit_04.json")))
    with pytest.raises(ValueError): scope.build_snapshot(inputs, profile(), goal, bundle)
    with pytest.raises(ValueError):
        w.prepare_script_request(inputs, profile(), goal, bundle, opening_setup=load("call_633_opening_setup_02.json")["output"], **w.origin_ids(inputs))


def test_advisory_is_once_in_actual_writer_and_semantic_payload_and_absent_from_physical(source_case):
    inputs, goal, opening, ids, raw, bundle = source_case
    adapter, author, native, compiled, prepared, reports = scoped_reports(source_case)
    snapshot = payload(author)[scope.FIELD]
    assert snapshot["native_commitment_audit"] == bundle["native_commitment_audit"]
    assert set(snapshot) == {"schema", "authority", "native_commitment_audit", "native_goal_audit_bundle_sha256",
                             "accepted_paired_snapshot_sha256", "profile_sha256"}
    assert payload(prepared["semantic"])[scope.FIELD] == snapshot
    assert scope.FIELD not in payload(prepared["physical"])
    assert scope.RULE not in prepared["physical"]["request"]["messages"][0]["content"]
    assert payload(author)["native_goal_document"] == payload(prepared["semantic"])["native_goal_document"] == goal
    assert payload(author)["native_opening_setup_document"] == opening
    assert payload(prepared["semantic"])["native_script_document"] == native
    for request in (author, prepared["semantic"], prepared["physical"]): check_wire(request)
    assert w.contexts._reference_occurrences(payload(author), inputs["reference_fulltext"]) == 1
    assert w.contexts._reference_occurrences(payload(prepared["semantic"]), inputs["reference_fulltext"]) == 1
    assert prepared["semantic"]["manifest"]["response_tables_added_for_scope_handoff"] == 0
    assert "可以质疑" in scope.RULE and "不是新事实" in scope.RULE
    with pytest.raises(ValueError): scope.attach(payload(author), snapshot, inputs, profile(), goal, bundle)
    for part in ("semantic", "physical"):
        result = adapter.validate_part(reports[part], part, compiled, author["views"]["brief"], author["views"]["plan"],
            prepared[part]["review_legal_context"], context_sha256=prepared[part]["context_sha256"], goal_contract=goal, opening_setup=opening)
        assert result["valid"] and result["accepted"], result
        assert result["native_part_sha256"] == w.digest(reports[part]) and result["native_context_sha256"] == reports[part]["context_sha256"]
        assert result["native_script_sha256"] == w.digest(native) != result["compiled_script_sha256"]
    result = adapter.validate_bundle(adapter.build_review_bundle(reports["semantic"], reports["physical"]), compiled,
        author["views"]["brief"], author["views"]["plan"], prepared["semantic"]["review_legal_context"],
        semantic_context_sha256=prepared["semantic"]["context_sha256"], physical_context_sha256=prepared["physical"]["context_sha256"],
        goal_contract=goal, opening_setup=opening)
    assert result["valid"] and result["accepted"] and not result["human_quality_approved"]


def test_semantic_may_challenge_accepted_scope_interpretation_through_existing_native_finding_route(source_case):
    inputs, goal, opening, ids, raw, bundle = source_case
    adapter, author, native, compiled, prepared, reports = scoped_reports(source_case)
    report = reports["semantic"]
    row = next(iter(report["fact_checks"].values()))
    row.update(status="fail", required_revision="完整规划修复原C明示时点与实际事件矛盾",
        reason="合成审查者质疑上游scope解释：cross_beat分类不能免除原C的指定发生时点。", counterevidence=list(row["evidence"]))
    report["revision_target"] = "plan"
    result = adapter.validate_part(report, "semantic", compiled, author["views"]["brief"], author["views"]["plan"],
        prepared["semantic"]["review_legal_context"], context_sha256=prepared["semantic"]["context_sha256"], goal_contract=goal, opening_setup=opening)
    assert result["valid"] and not result["accepted"] and result["requires_new_goal_plan"], result
    assert result["native_part_sha256"] == w.digest(report)
    assert result["findings"][0]["finding"] == row


def driver_case(tmp_path, source_case, *, rewrite=False):
    inputs, goal, opening, ids, raw, bundle = source_case
    adapter, author, native, compiled, prepared, reports = scoped_reports(source_case)
    second = scoped_reports(source_case, second=True) if rewrite else None
    calls, writer_payloads, outputs = [], [], {}
    class Session:
        version = "synthetic_scope27_driver_fixture/v1"
        root = tmp_path
        profile = profile()
        wf = adapter.workflow
        def invoke(self, runtime, label, prepared, validator):
            calls.append(label)
            if label.startswith("complete_script"):
                writer_payloads.append(payload(prepared))
                value = deepcopy(second[2] if label.endswith("02") else native)
            else:
                part = label.split("_")[2]
                value = deepcopy(second[-1][part] if label.endswith("02") else reports[part])
                if rewrite and label == "full_review_semantic_01":
                    row = value["paired_checks"]["records_by_target"]["ending"]
                    row.update(status="fail", required_revision="完整合成新稿修复", counterevidence=list(row["evidence"]))
                    value["revision_target"] = "script"
            outputs[label] = deepcopy(value)
            decision = validator(value)
            return {"ordinal": len(calls), "output": value, "validation": decision,
                "status": "contract_valid" if decision.get("valid", True) else "contract_rejected"}
        def known(self, receipt, stage, *, require_valid=True):
            if require_valid and receipt["status"] != "contract_valid": raise shared.Halt("halt_contract_requires_pipeline_diagnosis")
            return receipt["output"]
        _review_stop = staticmethod(shared.Session._review_stop)
        def _diagnosis(self, receipt): return receipt["validation"]
        def execution_evidence(self, *a, **kw): return {"synthetic_only_no_provider_or_claim": True}
        def state(self, runtime, status, **kwargs): return {"status": status, **kwargs}
    result = driver.body(Session(), None, inputs, goal, bundle, opening, 1, reviews=adapter)
    return result, calls, writer_payloads, outputs


@pytest.mark.parametrize("rewrite", [False, True])
def test_real_driver2_scope_facade_keeps_complete_native_handoff_and_bounded_rewrite(tmp_path, source_case, rewrite):
    result, calls, writers, outputs = driver_case(tmp_path, source_case, rewrite=rewrite)
    assert result["status"] == "text_ready_for_director"
    expected = ["complete_script_01", "full_review_semantic_01"]
    if rewrite: expected += ["complete_script_02", "full_review_semantic_02"]
    expected += ["full_review_physical_02" if rewrite else "full_review_physical_01"]
    assert calls == expected
    assert scope.FIELD in writers[0]
    if rewrite:
        assert writers[1][scope.FIELD] == writers[0][scope.FIELD]
        assert writers[1]["previous_complete_document"] == outputs["complete_script_01"]
        assert writers[1]["revision_diagnostics"]["native_part_reviews"]["semantic"] == outputs["full_review_semantic_01"]
    handoff = json.loads((tmp_path / "TEXT_HANDOFF.json").read_text("utf-8"))
    assert handoff["native_script"] == outputs["complete_script_02" if rewrite else "complete_script_01"]
    assert not handoff["production_dispatch_eligible"] and not handoff["human_quality_approved"] and not handoff["media_authorized"]
