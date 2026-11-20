"""Synthetic complete-chain contracts and unchanged actual negative sources.

Fabricated native judgments certify no semantics or creative quality. The
positive story is a newly constructed two-person scheduling conversation;
actual627/631/634/635 are never converted into fabricated passing reports.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

import pytest
from jsonschema import Draft202012Validator

from src.content_factory import creative_goal_context_workflow_v26 as w
from scripts import creative_review_injected_text_driver_v2 as driver
from scripts import creative_fresh_source_session_v1 as shared
from scripts.creative_m31_flash_role_clients_v1 import M31FlashRoleClients, expected_wire_request
from tests.test_creative_goal_context_workflow_v23 import offline as historical_clock
from tests.test_creative_goal_context_workflow_v24 import case
from tests.test_creative_goal_context_workflow_v25 import bundle as old_four_bundle
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests.test_creative_paired_narrative_review_v1 import make_native as fake_comparison
from tests.test_creative_split_full_review_contract_v4 import synthetic_consistency
from tests import test_goal_context_text_production_v4 as full_helpers

ROOT = Path(__file__).resolve().parents[1]
ACTUAL = ROOT / "data/production_trials/legal_scoped_text_session_20261015/round_01"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError("v26 tests cannot construct live clients or contact providers")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(M31FlashRoleClients, "__init__", deny)


def profile():
    return json.loads((ROOT / "config/creative_fresh_source_session_profile_v2.json").read_text("utf-8-sig"))


def payload(prepared):
    return json.loads(prepared["request"]["messages"][1]["content"])


def synthetic_case(scenario):
    inputs, goal, opening, ids, native = case(scenario)
    whole = goal["whole_plan"]
    whole["premise"] = "仅供离线合同接线：员工询问明天排班，人事明确确认不变，员工保持坐姿。"
    for actor in whole["characters"]:
        actor["want"] = "问清明天是否上班" if actor["id"] == "worker" else "明确告知明天排班不变"
        actor["pressure"] = "尚未得到答复" if actor["id"] == "worker" else "需要当场给出明确回复"
    for row in goal["claims"]:
        if row["kind"] == "creative_choice":
            row["text"] = "合成合同样例：员工问明天是否照常上班，人事明确答复照常，员工留坐，物件不移动。"
    for i, beat in enumerate(whole["beats"]):
        beat.update(actor_id="worker" if i == 0 else "hr", goal="得到明确排班答复" if i == 0 else "确认明天照常上班",
            resistance="排班尚未当面确认", stimulus="员工需要知道明天安排" if i == 0 else "员工问明天能否照常上班",
            response="员工问明天是否照常上班" if i == 0 else "人事回答明天照常来，排班不改",
            visible_change="问题明确交给人事" if i == 0 else "员工留坐，记录本和笔仍留在柜内",
            strategy={"before": "等待明确答复", "after": "当面问清" if i == 0 else "给出明确答复", "effect": "changes"})
    ending = whole["ending"]
    ending.update(attempt_result="员工得知明天照常上班", visible_consequence="员工保持坐姿，记录本和笔仍留在柜内",
        emotional_landing="得知安排后安定下来", open_legal_question="未来安排未展开，本场只确认明天排班")
    opening["goal_sha256"] = w.digest(goal)
    native["title"] = "离线完整接线合成样例"
    native["premise"] = whole["premise"]
    native["beats"][0].update(event="询问明天排班", trigger="尚未得到明确答复")
    native["beats"][0]["steps"][0]["text"] = "明天我还照常来上班吗？"
    native["beats"][1].update(event="得到明确答复", trigger="员工询问明天排班")
    native["beats"][1]["steps"][0]["text"] = "明天照常来，排班不改。"
    native["beats"][1]["steps"][1]["text"] = "员工保持坐姿，记录本留在柜内搁板上，笔仍夹在封面内侧。"
    return inputs, goal, opening, w.origin_ids(inputs), native


def synthetic_bundle(inputs, goal):
    # Only a newly constructed synthetic goal may use this fake native maker.
    assert goal["whole_plan"]["premise"].startswith("仅供离线合同接线")
    old = old_four_bundle(inputs, goal)
    prepared = w.prepare_goal_drama_audit_request(inputs, profile(), goal)
    frame = w.paired._frame(goal)
    original = deepcopy(old["native_drama_audit"])
    original.update(schema=w.DRAMA_AUDIT_VERSION, audit_context_sha256=w.digest(payload(prepared)),
        paired_checks=fake_comparison(frame), revision_target="none")
    return w.build_goal_audit_bundle(old["native_scope_audit"], old["native_source_audit"], old["native_commitment_audit"], original)


def synthetic_full_reports(inputs, goal, opening, native, bundle):
    assert goal["whole_plan"]["premise"].startswith("仅供离线合同接线")
    adapter = w.make_review_adapter(inputs, profile(), bundle)
    authored = adapter.workflow.prepare_script_request(inputs, profile(), goal, bundle, opening_setup=opening, **w.origin_ids(inputs))
    views = authored["views"]
    script = w.validate_script_document(native, views, inputs["production_preferences"])["script"]
    reports, prepared = {}, {}
    for part in ("semantic", "physical"):
        req = adapter.prepare_full_review_part_request(inputs, profile(), native, views, part)
        prepared[part] = req
        old = full_helpers.full_review({"full_current_script": script, "brief": views["brief"], "creative_scene_plan": views["plan"],
            "native_goal_document": goal, "verified_legal_context": req["review_legal_context"]})
        old["opening_setup_sha256"] = w.digest(opening)
        entries = w.full.checks.reviews.base.base.prior.contract.evidence_catalog(script)
        for row in old["goal_checks"].values():
            row["evidence"] = [{"source_ref": "E0002", "quote": entries["E0002"]["quote"]}]
        old.update(synthetic_consistency(script, views["brief"], views["plan"], goal_contract=goal))
        props = req["request"]["structured_schema"]["properties"]
        report = {key: deepcopy(old[key]) for key in props if key in old}
        report.update(schema=w.FULL_REVIEW_VERSION, part=part, context_sha256=req["context_sha256"], revision_target="none")
        if part == "semantic":
            for table, identifier, row in w.full._judgement_rows(report):
                refs = row.pop("source_refs", None)
                row.pop("evidence", None)
                row.update(evidence=refs if refs is not None else [row["source_ref"]], counterevidence=[])
            audit = w.validate_goal_audit(bundle, goal, inputs=inputs)
            frame = w.paired._script_frame(native, goal, audit["accepted_goal_comparison_snapshot"],
                native_comparison=bundle["native_drama_audit"]["paired_checks"], goal_context_sha256=audit["paired_context_sha256"],
                bundle_sha256=w.digest(bundle), compiled_script=script, request_same_source_sha256=payload(req)["same_source_sha256"])
            report["paired_checks"] = fake_comparison(frame)
        reports[part] = report
    return adapter, authored, script, prepared, reports


def check_wire(prepared):
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    assert prepared["request_sha256"] == w.digest(prepared["request"])
    assert prepared["request"]["input_provenance"]["context_manifest_sha256"] == w.digest(prepared["manifest"])
    assert prepared["manifest"]["structured_schema_sha256"] == w.digest(prepared["request"]["structured_schema"])
    assert prepared["manifest"]["payload_identity"] == w.contexts._measure(payload(prepared))
    assert prepared["sdk_max_retries"] == 0 and not prepared["dispatch_performed"] and not prepared["production_dispatch_eligible"]


def test_complete_synthetic_four_audits_snapshot_and_same_source_full_parts(causal_scenario):
    inputs, goal, opening, ids, native = synthetic_case(causal_scenario)
    bundle = synthetic_bundle(inputs, goal)
    original = deepcopy((inputs, goal, opening, native, bundle))
    decision = w.validate_goal_audit(bundle, goal, inputs=inputs)
    assert decision["valid"] and decision["accepted"] and decision["four_native_audits_bound"], decision
    adapter, author, script, prepared, reports = synthetic_full_reports(inputs, goal, opening, native, bundle)
    assert payload(author)["accepted_goal_comparison_snapshot"] == decision["accepted_goal_comparison_snapshot"]
    assert payload(author)["native_goal_document"] == goal and payload(author)["native_opening_setup_document"] == opening
    assert w.contexts._reference_occurrences(payload(author), inputs["reference_fulltext"]) == 1
    check_wire(author)
    for part in ("semantic", "physical"):
        check_wire(prepared[part])
        Draft202012Validator(prepared[part]["request"]["structured_schema"]).validate(reports[part])
        result = adapter.validate_part(reports[part], part, script, author["views"]["brief"], author["views"]["plan"],
            prepared[part]["review_legal_context"], context_sha256=prepared[part]["context_sha256"], goal_contract=goal, opening_setup=opening)
        assert result["valid"] and result["accepted"], result
        assert result["native_part_sha256"] == w.digest(reports[part])
        assert result["native_script_sha256"] == w.digest(native) != result["compiled_script_sha256"]
        assert not result["compiler_projection_is_native_review"] and not result["native_response_rewritten"]
    result = adapter.validate_bundle(adapter.build_review_bundle(reports["semantic"], reports["physical"]), script,
        author["views"]["brief"], author["views"]["plan"], prepared["semantic"]["review_legal_context"],
        semantic_context_sha256=prepared["semantic"]["context_sha256"], physical_context_sha256=prepared["physical"]["context_sha256"],
        goal_contract=goal, opening_setup=opening)
    assert result["valid"] and result["accepted"] and result["status"] == "text_ready_for_director", result
    assert result["full_review_protocol_version"] == w.FULL_REVIEW_VERSION
    assert not result["human_quality_approved"] and not result["creative_quality_passed"]
    assert (inputs, goal, opening, native, bundle) == original


@pytest.mark.parametrize("fault", ["missing_paired", "bad_quote", "fail", "unknown", "wrong_context", "counter_pass"])
def test_native_drama_and_paired_AND_gate_stops_before_writer(causal_scenario, fault):
    inputs, goal, opening, ids, _ = synthetic_case(causal_scenario)
    bundle = synthetic_bundle(inputs, goal); drama = bundle["native_drama_audit"]
    row = drama["paired_checks"]["records_by_target"]["ending"]
    if fault == "missing_paired": drama.pop("paired_checks")
    elif fault == "bad_quote": next(iter(row["readings"].values()))[0]["quote"] = "not from this goal"
    elif fault in ("fail", "unknown"):
        row.update(status=fault, required_revision="完整新规划澄清" if fault == "fail" else "")
        drama["revision_target"] = "plan" if fault == "fail" else "none"
    elif fault == "wrong_context": drama["paired_checks"]["context_sha256"] = "0" * 64
    else: row["counterevidence"] = list(row["evidence"])
    with pytest.raises(ValueError): w.prepare_script_request(inputs, profile(), goal, bundle, opening_setup=opening, **ids)


@pytest.mark.parametrize("target,status", [("script", "fail"), ("plan", "fail"), ("none", "unknown")])
def test_paired_only_failure_keeps_native_explicit_revision_target_and_counterproof(causal_scenario, target, status):
    inputs, goal, opening, ids, native = synthetic_case(causal_scenario)
    bundle = synthetic_bundle(inputs, goal)
    adapter, author, script, prepared, reports = synthetic_full_reports(inputs, goal, opening, native, bundle)
    row = reports["semantic"]["paired_checks"]["records_by_target"]["ending"]
    row.update(status=status, required_revision="完整新稿处理结尾" if status == "fail" else "", counterevidence=list(row["evidence"]))
    reports["semantic"]["revision_target"] = target
    result = adapter.validate_part(reports["semantic"], "semantic", script, author["views"]["brief"], author["views"]["plan"],
        prepared["semantic"]["review_legal_context"], context_sha256=prepared["semantic"]["context_sha256"], goal_contract=goal, opening_setup=opening)
    assert result["valid"] and not result["accepted"], result
    assert result["revision_target"] == target and result["requires_new_goal_plan"] == (target == "plan")
    assert result["native_part_sha256"] == w.digest(reports["semantic"])
    assert result["findings" if status == "fail" else "uncertainties"][-1]["finding"] == row


def test_bound_author_rejects_another_valid_audit_for_same_goal_and_full_prepare_rejects_profile_drift(causal_scenario):
    inputs, goal, opening, ids, native = synthetic_case(causal_scenario)
    first = synthetic_bundle(inputs, goal); second = deepcopy(first)
    second["native_drama_audit"]["paired_checks"]["records_by_target"]["ending"]["comparison"] += " Another synthetic native comparison."
    assert w.validate_goal_audit(second, goal, inputs=inputs)["accepted"]
    adapter = w.make_review_adapter(inputs, profile(), first)
    with pytest.raises(ValueError, match="bound authoring"):
        adapter.workflow.prepare_script_request(inputs, profile(), goal, second, opening_setup=opening, **ids)
    author = adapter.workflow.prepare_script_request(inputs, profile(), goal, first, opening_setup=opening, **ids)
    wrong = profile(); wrong["director"]["parameters"]["temperature"] += .1
    with pytest.raises(ValueError, match="profile"):
        adapter.prepare_full_review_part_request(inputs, wrong, native, author["views"], "semantic")
    with pytest.raises(AttributeError): adapter.workflow.prepare_script_request = None


def test_original_cast_preference_gate_remains_in_new_author(causal_scenario):
    inputs, goal, opening, ids, native = synthetic_case(causal_scenario)
    inputs["production_preferences"]["max_characters"] = 1
    with pytest.raises(ValueError):
        w.prepare_script_request(inputs, profile(), goal, synthetic_bundle(inputs, goal), opening_setup=opening, **ids)


def test_actual627_new_drama_keeps_exact_path_catalog_and_original631_is_not_accepted():
    load = lambda name: json.loads((ACTUAL / name).read_text("utf-8"))
    inputs, goal, old = load("INPUTS.json"), load("call_627_whole_plan_04.json")["output"], load("call_631_drama_audit_04.json")["output"]
    before = {name: hashlib.sha256((ACTUAL / name).read_bytes()).hexdigest() for name in ("call_627_whole_plan_04.json", "call_631_drama_audit_04.json", "call_634_complete_script_01.json", "call_635_full_review_semantic_01.json")}
    prepared = w.prepare_goal_drama_audit_request(inputs, profile(), goal); actual = payload(prepared)
    check_wire(prepared)
    assert actual["native_goal_document"] == goal and "native_goal_evidence_view" not in actual
    assert w.contexts._reference_occurrences(actual, inputs["reference_fulltext"]) == 1
    assert "goal_structure" not in prepared["request"]["messages"][0]["content"] and "$goal_evidence_ref" not in prepared["request"]["messages"][0]["content"]
    catalog = w.drama_contract.build_evidence_catalog(goal)
    assert actual["paired_narrative_comparison"]["comparison_targets"]["source_index"] == {k: {"document_path": row["document_path"]} for k, row in catalog.items()}
    rejected = w.validate_goal_drama_audit(old, goal, context_sha256=w.digest(actual), inputs=inputs)
    assert not rejected["valid"] and not rejected["accepted"]
    assert before == {name: hashlib.sha256((ACTUAL / name).read_bytes()).hexdigest() for name in before}


def test_actual634_635_cannot_bypass_new_paired_gate_with_old_native_planning_bundle():
    load = lambda name: json.loads((ACTUAL / name).read_text("utf-8"))
    inputs, goal = load("INPUTS.json"), load("call_627_whole_plan_04.json")["output"]
    opening, native = load("call_633_opening_setup_02.json")["output"], load("call_634_complete_script_01.json")["output"]
    old_review = load("call_635_full_review_semantic_01.json")
    bundle = w.build_goal_audit_bundle(*(load(name)["output"] for name in (
        "call_628_scope_audit_04.json", "call_629_source_audit_04.json", "call_630_commitment_audit_04.json", "call_631_drama_audit_04.json")))
    # This is deliberately unaccepted historical material, never a fabricated
    # passing comparison for the real contradictory story.
    assert not w.validate_goal_audit(bundle, goal, inputs=inputs)["accepted"]
    views = w.compile_native_views(goal, opening, **w.origin_ids(inputs))
    compiled = w.validate_script_document(native, views, inputs["production_preferences"])["script"]
    assert w.digest(native) != w.digest(compiled)
    with pytest.raises(ValueError):
        w.prepare_full_review_part_request(inputs, profile(), native, views, "semantic", native_goal_audit=bundle)
    adapter = w.make_review_adapter(inputs, profile(), bundle)
    result = adapter.validate_part(old_review["output"], "semantic", compiled, views["brief"], views["plan"],
        json.loads(old_review["request"]["messages"][1]["content"])["verified_legal_context"],
        context_sha256=old_review["output"]["context_sha256"], goal_contract=goal, opening_setup=opening)
    assert not result["valid"] and not result["accepted"]


def test_bad_paired_contract_diagnostic_has_only_message_and_path_without_schema_instance_dump():
    load = lambda name: json.loads((ACTUAL / name).read_text("utf-8"))
    inputs, goal = load("INPUTS.json"), load("call_627_whole_plan_04.json")["output"]
    original = load("call_631_drama_audit_04.json")["output"]
    before = deepcopy(original)
    prepared = w.prepare_goal_drama_audit_request(inputs, profile(), goal)
    negative = {**deepcopy(original), "schema": w.DRAMA_AUDIT_VERSION,
        "audit_context_sha256": w.digest(payload(prepared)), "revision_target": "none", "paired_checks": []}
    # An explicit malformed negative derived in memory, never stored/adopted as
    # a new provider result or a corrected historical native report.
    rejected = w.validate_goal_drama_audit(negative, goal, context_sha256=w.digest(payload(prepared)), inputs=inputs)
    finding = rejected["findings"][0]
    assert not rejected["valid"] and finding["path"] == "paired_checks"
    assert len(finding["reason"]) <= 1200
    assert "Failed validating" not in finding["reason"] and "On instance" not in finding["reason"]
    assert "records_by_target" not in finding["reason"] and "native_goal_document" not in finding["reason"]
    assert original == before


def driver_fixture(tmp_path, scenario, fault=None):
    inputs, goal, opening, ids, native = synthetic_case(scenario); bundle = synthetic_bundle(inputs, goal)
    adapter, author, compiled, prepared, reports = synthetic_full_reports(inputs, goal, opening, native, bundle)
    calls, writer_payloads, outputs = [], [], {}
    second_native = deepcopy(native)
    second_native["title"] += "（完整合成新稿二）"
    second_reports = synthetic_full_reports(inputs, goal, opening, second_native, bundle)[-1] if fault == "script_fail" else None
    class Session:
        version = "synthetic_v26_driver_fixture/v1"
        root = tmp_path
        wf = adapter.workflow
        profile = profile()
        def invoke(self, runtime, label, request, validator):
            calls.append(label)
            if label.startswith("complete_script"):
                writer_payloads.append(payload(request))
                output = deepcopy(second_native if label.endswith("02") else native)
            else:
                part = label.split("_")[2]
                output = deepcopy(second_reports[part] if label.endswith("02") and second_reports is not None else reports[part])
                if fault == "malformed" and part == "semantic": output.pop("paired_checks")
                if fault in ("unknown", "plan_fail") and part == "semantic":
                    row = output["paired_checks"]["records_by_target"]["ending"]
                    row.update(status="unknown" if fault == "unknown" else "fail", required_revision="" if fault == "unknown" else "完整新规划修订")
                    output["revision_target"] = "none" if fault == "unknown" else "plan"
                if fault == "script_fail" and label == "full_review_semantic_01":
                    row = output["paired_checks"]["records_by_target"]["ending"]
                    row.update(status="fail", required_revision="仅供合成分支验证：完整新稿澄清结尾", counterevidence=list(row["evidence"]))
                    output["revision_target"] = "script"
            outputs[label] = deepcopy(output)
            result = validator(output)
            return {"ordinal": len(calls), "output": output, "validation": result,
                "status": "contract_valid" if result.get("valid", True) else "contract_rejected"}
        def known(self, receipt, stage, *, require_valid=True):
            if require_valid and receipt["status"] != "contract_valid": raise shared.Halt("halt_contract_requires_pipeline_diagnosis")
            return receipt["output"]
        _review_stop = staticmethod(shared.Session._review_stop)
        def _diagnosis(self, receipt): return receipt["validation"]
        def execution_evidence(self, *a, **kw): return {"synthetic_only_no_raw_sdk_or_production_claim": True}
        def state(self, runtime, status, **kwargs): return {"status": status, **kwargs}
        writer_requests = writer_payloads
        native_outputs = outputs
    return Session(), inputs, goal, opening, bundle, adapter, calls, native


def test_real_driver2_with_bound_facade_reaches_synthetic_same_source_handoff(tmp_path, causal_scenario):
    session, inputs, goal, opening, bundle, adapter, calls, native = driver_fixture(tmp_path, causal_scenario)
    result = driver.body(session, None, inputs, goal, bundle, opening, 1, reviews=adapter)
    assert result["status"] == "text_ready_for_director"
    assert calls == ["complete_script_01", "full_review_semantic_01", "full_review_physical_01"]
    handoff = json.loads((tmp_path / "TEXT_HANDOFF.json").read_text("utf-8"))
    assert handoff["native_script"] == native and handoff["native_goal_audit"] == bundle
    assert handoff["native_script_sha256"] != handoff["compiled_script_sha256"]
    assert handoff["review_protocol_version"] == w.FULL_REVIEW_VERSION
    assert not handoff["media_authorized"] and not handoff["production_dispatch_eligible"] and not handoff["human_quality_approved"]


def test_real_driver2_paired_only_script_failure_requests_complete_new_native_with_exact_feedback(tmp_path, causal_scenario):
    session, inputs, goal, opening, bundle, adapter, calls, native = driver_fixture(tmp_path, causal_scenario, "script_fail")
    result = driver.body(session, None, inputs, goal, bundle, opening, 1, reviews=adapter)
    assert result["status"] == "text_ready_for_director"
    assert calls == ["complete_script_01", "full_review_semantic_01", "complete_script_02", "full_review_semantic_02", "full_review_physical_02"]
    assert session.writer_requests[1]["previous_complete_document"] == native
    feedback = session.writer_requests[1]["revision_diagnostics"]
    assert feedback["native_part_reviews"]["semantic"] == session.native_outputs["full_review_semantic_01"]
    assert feedback["complete_same_source_part_review"]["revision_target"] == "script"
    assert feedback["complete_same_source_part_review"]["paired_decision"]["findings"]
    handoff = json.loads((tmp_path / "TEXT_HANDOFF.json").read_text("utf-8"))
    assert handoff["native_script"] == session.native_outputs["complete_script_02"] != native
    assert handoff["native_goal_audit"] == bundle


@pytest.mark.parametrize("fault", ["malformed", "unknown", "plan_fail"])
def test_real_driver2_malformed_or_unaccepted_paired_review_stops_without_another_writer(tmp_path, causal_scenario, fault):
    session, inputs, goal, opening, bundle, adapter, calls, native = driver_fixture(tmp_path, causal_scenario, fault)
    with pytest.raises(shared.Halt): driver.body(session, None, inputs, goal, bundle, opening, 1, reviews=adapter)
    assert calls == ["complete_script_01", "full_review_semantic_01"]
    assert not (tmp_path / "TEXT_HANDOFF.json").exists()
