"""Source-event reconciliation tests, using isolated mock services only.

These fixtures specify routing cases rather than creative quality golds.
The frozen v1/v2 tests and production receipts are not edited.
"""
from copy import deepcopy
import json
import hashlib

import pytest

from src.content_factory import creative_autonomous_text_contract_v3 as contract
from tests.test_creative_autonomous_text_pipeline_v1 import plan_for
from tests.test_creative_autonomous_text_pipeline_v2 import (
    case_v2, review_v2, audit_v2, pipeline_workspace_v2,
)


def obligation(id_, fact, *, mode="event", actor="", kind="dialogue", functions=None):
    return {"id": id_, "fact_id": fact, "mode": mode,
            "description": "来源要求的" + id_, "actor_id": actor,
            "required_kind": kind, "allowed_speech_functions": functions or ["statement"]}


def plan_v3(script, brief):
    value = plan_for(script, brief)
    facts = [row["id"] for row in brief["facts"]]
    value["source_obligations"] = [obligation("state_" + fact, fact, mode="state", kind="either",
                                            functions=contract.FUNCTIONS) for fact in facts]
    value["source_order"] = []
    if brief["selected_candidate_id"] == "fixture_legal":
        value["source_obligations"] += [
            obligation("notice", facts[0], actor="hr", functions=["statement"]),
            obligation("query", facts[0], actor="worker", functions=["question"]),
            obligation("refusal", facts[0], actor="worker", functions=["refusal"]),
            obligation("collect", facts[-1], actor="hr", kind="action", functions=["action"]),
        ]
        value["source_order"] = [{"before_id": a, "after_id": b} for a, b in
                                 [("notice", "query"), ("query", "refusal"), ("refusal", "collect")]]
    return value


def audit_v3(script, brief, plan):
    value = audit_v2(script, brief)
    action_actor = {"fixture_legal": "hr", "fixture_family": "parent", "fixture_product": "owner"}
    for event in value["literal_events"]:
        event["actual_actor"] = event["speaker"] if event["kind"] == "dialogue" else action_actor[brief["selected_candidate_id"]]
    legal_refs = {"notice": "E0001", "query": "E0003", "refusal": "E0005", "collect": "E0006"}
    value["obligation_evidence"] = [
        {"obligation_id": row["id"], "actual_refs": [legal_refs.get(row["id"], "E0001")],
         "status": "pass", "explanation": "明确的来源事件路由夹具，不代表审美金标。"}
        for row in plan["source_obligations"]]
    return value


def source_case(topic="legal"):
    brief, raw, script = case_v2(topic)
    plan = plan_v3(script, brief)
    return brief, raw, script, plan, review_v2(script, brief), audit_v3(script, brief, plan)


def proof(audit, id_):
    return next(row for row in audit["obligation_evidence"] if row["obligation_id"] == id_)


def codes(decision):
    return {row["code"] for row in decision["revision_requirements"]}


@pytest.mark.parametrize("topic,count", [("legal", 4), ("family", 3), ("product", 2)])
def test_v3_source_contract_is_generic_for_variable_topics_and_beat_counts(topic, count):
    brief, raw, script, plan, review, audit = source_case(topic)
    assert len(script["beats"]) == count
    assert contract.validate_plan(plan, brief)["source_obligation_count"] == len(plan["source_obligations"])
    assert contract.validate_audit(audit, script, brief, plan)["plan_sha256"] == contract._digest(plan)
    assert contract.compile_script(raw, brief) == script
    result = contract.combine_decisions(review, audit, script, brief, plan)
    assert result["status"] == "text_ready_for_director"
    assert result["executable_source_events_required"] is True
    assert result["human_approved"] is False and result["automatic_media_submit"] is False


def test_all_pass_fact_rows_cannot_hide_question_used_as_refusal():
    brief, _, script, plan, review, audit = source_case()
    question = next(e for e in audit["literal_events"] if e["source_ref"] == "E0003")
    question["negative_or_refusal"] = True
    proof(audit, "refusal")["actual_refs"] = ["E0003"]
    assert all(row["status"] == "pass" for row in audit["fact_checks"] + audit["obligation_evidence"])
    result = contract.combine_decisions(review, audit, script, brief, plan)
    assert result["status"] == "needs_whole_revision"
    assert "SOURCE_EVENT_refusal" in codes(result)
    assert "SOURCE_ORDER_query_BEFORE_refusal" in codes(result)
    assert any(e["ref_id"] == "E0003" for r in result["revision_requirements"] for e in r["evidence_refs"])


def test_pass_obligation_with_no_actual_event_routes_whole_revision_not_fake_quote():
    brief, _, script, plan, review, audit = source_case()
    proof(audit, "refusal")["actual_refs"] = []
    result = contract.combine_decisions(review, audit, script, brief, plan)
    assert result["status"] == "needs_whole_revision"
    assert "SOURCE_EVENT_refusal" in codes(result)
    assert all(e["ref_id"] in contract.evidence_catalog(script) for r in result["revision_requirements"] for e in r["evidence_refs"])
    assert proof(audit, "refusal")["actual_refs"] == []


@pytest.mark.parametrize("field,change", [("required_kind", "action"), ("actor_id", "hr")])
def test_event_kind_or_actor_mismatch_cannot_be_overridden_by_fact_pass(field, change):
    brief, _, script, plan, review, audit = source_case()
    row = next(r for r in plan["source_obligations"] if r["id"] == "refusal")
    row[field] = change
    if field == "required_kind":
        row["allowed_speech_functions"] = ["action"]
    result = contract.combine_decisions(review, audit, script, brief, plan)
    assert result["status"] == "needs_whole_revision" and "SOURCE_EVENT_refusal" in codes(result)


def test_action_actor_mismatch_is_machine_checked():
    brief, _, script, plan, _, audit = source_case()
    next(e for e in audit["literal_events"] if e["source_ref"] == "E0006")["actual_actor"] = "worker"
    assert "SOURCE_EVENT_collect" in codes(contract.decide_audit(audit, script, brief, plan))


def test_dialogue_actor_cannot_be_company_just_because_company_is_mentioned():
    brief, _, script, plan, _, audit = source_case()
    audit["literal_events"][0]["actual_actor"] = "company"
    with pytest.raises(ValueError, match="actual_actor must equal"):
        contract.validate_audit(audit, script, brief, plan)


def test_strict_order_reverse_fails_even_with_all_pass_rows():
    brief, _, script, plan, _, audit = source_case()
    plan["source_order"] = [{"before_id": "refusal", "after_id": "query"}]
    result = contract.decide_audit(audit, script, brief, plan)
    assert result["status"] == "needs_whole_revision"
    assert "SOURCE_ORDER_refusal_BEFORE_query" in codes(result)


def add_notice_purpose(plan, audit):
    row = deepcopy(next(r for r in plan["source_obligations"] if r["id"] == "notice"))
    row["id"] = "second_purpose"
    plan["source_obligations"].append(row)
    audit["obligation_evidence"].append({"obligation_id": "second_purpose", "actual_refs": ["E0001"],
                                         "status": "pass", "explanation": "同一句完成多个目的，无固定句数。"})


def test_one_utterance_can_satisfy_multiple_purposes_without_forced_extra_sentence():
    brief, _, script, plan, review, audit = source_case()
    add_notice_purpose(plan, audit)
    result = contract.combine_decisions(review, audit, script, brief, plan)
    assert result["status"] == "text_ready_for_director"


@pytest.mark.parametrize("relation", ["strict_order", "explicit_distinct"])
def test_same_ref_cannot_fake_two_distinct_or_strictly_ordered_occurrences(relation):
    brief, _, script, plan, _, audit = source_case()
    add_notice_purpose(plan, audit)
    if relation == "strict_order":
        plan["source_order"].append({"before_id": "notice", "after_id": "second_purpose"})
    else:
        next(r for r in plan["source_obligations"] if r["id"] == "second_purpose")["distinct_from_ids"] = ["notice"]
    result = contract.decide_audit(audit, script, brief, plan)
    assert result["status"] == "needs_whole_revision"
    assert any(c.startswith("SOURCE_ORDER_") if relation == "strict_order" else c == "SOURCE_EVENT_second_purpose" for c in codes(result))


def test_two_refusals_cannot_borrow_the_only_refusal_after_tactic_change():
    brief, _, script, plan, _, audit = source_case()
    first = deepcopy(next(r for r in plan["source_obligations"] if r["id"] == "refusal"))
    first["id"] = "refusal_after_change"
    first["distinct_from_ids"] = ["refusal"]
    plan["source_obligations"].append(first)
    plan["source_order"].append({"before_id": "refusal", "after_id": "refusal_after_change"})
    audit["obligation_evidence"].append({"obligation_id": "refusal_after_change", "actual_refs": ["E0005"], "status": "pass", "explanation": "错误地借用唯一拒绝。"})
    result = contract.decide_audit(audit, script, brief, plan)
    assert result["status"] == "needs_whole_revision"
    assert "SOURCE_EVENT_refusal_after_change" in codes(result)
    assert "SOURCE_ORDER_refusal_BEFORE_refusal_after_change" in codes(result)


def test_unknown_obligation_has_priority_over_other_known_failures():
    brief, _, script, plan, review, audit = source_case()
    proof(audit, "refusal").update(status="unknown", actual_refs=[])
    result = contract.combine_decisions(review, audit, script, brief, plan)
    assert result["status"] == "halt_review_uncertain" and result["uncertainties"]


@pytest.mark.parametrize("error", ["missing_obligation", "duplicate_obligation", "fake_actual_ref", "reorder_literals"])
def test_incomplete_or_fabricated_source_proof_is_rejected(error):
    brief, _, script, plan, _, audit = source_case()
    if error == "missing_obligation":
        audit["obligation_evidence"].pop()
    elif error == "duplicate_obligation":
        audit["obligation_evidence"][-1] = deepcopy(audit["obligation_evidence"][0])
    elif error == "fake_actual_ref":
        proof(audit, "refusal")["actual_refs"] = ["E9999"]
    else:
        audit["literal_events"][0], audit["literal_events"][1] = audit["literal_events"][1], audit["literal_events"][0]
    with pytest.raises(ValueError):
        contract.validate_audit(audit, script, brief, plan)


@pytest.mark.parametrize("error", ["missing_fact", "duplicate_id", "cycle", "unknown_order_id", "unknown_distinct_id", "self_distinct"])
def test_bad_source_plan_blocks_before_creative_body(error):
    brief, _, _, plan, _, _ = source_case()
    if error == "missing_fact":
        plan["source_obligations"] = [r for r in plan["source_obligations"] if r["fact_id"] != "unsigned"]
    elif error == "duplicate_id":
        plan["source_obligations"][-1]["id"] = plan["source_obligations"][0]["id"]
    elif error == "cycle":
        plan["source_order"].append({"before_id": "collect", "after_id": "notice"})
    elif error == "unknown_order_id":
        plan["source_order"].append({"before_id": "notice", "after_id": "not_declared"})
    else:
        plan["source_obligations"][0]["distinct_from_ids"] = ["not_declared" if error == "unknown_distinct_id" else plan["source_obligations"][0]["id"]]
    with pytest.raises(ValueError):
        contract.validate_plan(plan, brief)


@pytest.mark.parametrize("checker", ["review", "audit"])
def test_repair_instruction_cannot_authorize_changing_frozen_brief(checker):
    brief, _, script, plan, review, audit = source_case()
    value = review if checker == "review" else audit
    value["initial_state_checks"][-3].update(status="fail", required_revision="把brief初态改成文件夹里，以保留当前动作。")
    result = contract.decide_review(value, script, brief) if checker == "review" else contract.decide_audit(value, script, brief, plan)
    repair = next(r for r in result["revision_requirements"] if r["code"] == "INITIAL_PROP_application")
    assert repair["required_revision"] == contract.FROZEN_SOURCE_REPAIR
    assert value["initial_state_checks"][-3]["required_revision"].startswith("把brief")
    assert "冻结来源不得修改" in repair["required_revision"]


@pytest.fixture
def pipeline_workspace_v3(pipeline_workspace_v2):
    from scripts import run_autonomous_text_pipeline_v3 as runner
    _, root, parent, brief, raw, script = pipeline_workspace_v2
    ledger = json.loads((parent / "CALL_LEDGER.json").read_text(encoding="utf-8"))
    inherited = ledger["starting_spend"]
    inherited.update(calls_started=437, reported_tokens=6832533, calls_with_known_usage=435)
    auth = {"schema": "authorized_creative_continuation/v3", "starting_spend": inherited,
            "max_total_tokens": None, "old_budget_reset": False}
    (parent / "AUTHORIZATION.json").write_text(json.dumps(auth), encoding="utf-8")
    ledger["authorization_sha256"] = hashlib.sha256((parent / "AUTHORIZATION.json").read_bytes()).hexdigest()
    (parent / "CALL_LEDGER.json").write_text(json.dumps(ledger), encoding="utf-8")
    yield runner, root, parent, brief, raw, script


class MockTextServiceV3:
    def __init__(self, brief, raw, *, wrong_first_mapping=True, unknown_at=None, usage_unknown_at=None,
                 review_unknown=False, audit_unknown=False, probe_miss=False):
        self.brief, self.raw = deepcopy(brief), deepcopy(raw)
        self.wrong_first_mapping, self.unknown_at, self.usage_unknown_at = wrong_first_mapping, unknown_at, usage_unknown_at
        self.review_unknown, self.audit_unknown, self.probe_miss = review_unknown, audit_unknown, probe_miss
        self.requests = []
        self.drafts = self.reviews = self.audits = 0

    def call(self, role, messages, **kwargs):
        from scripts.creative_evidenced_role_clients_v1 import EvidenceCallError
        from src.content_factory.creative_workflow_roles import RoleResult
        payload = json.loads(messages[-1]["content"])
        properties = kwargs["structured_schema"]["properties"]
        self.requests.append({"role": role, "messages": deepcopy(messages), "payload": payload, "schema": deepcopy(kwargs["structured_schema"])})
        ordinal = len(self.requests)
        if ordinal == self.unknown_at:
            raise EvidenceCallError("MOCK_TIMEOUT_AFTER_SEND", started=True, received=False, outcome_known=False)
        if "literal_events" in properties:
            self.audits += 1
            source_plan = plan_v3(contract.compile_script(self.raw, self.brief), self.brief)
            output = audit_v3(payload["full_current_script"], self.brief, source_plan)
            if self.wrong_first_mapping and self.audits == 1 and not self.probe_miss:
                proof(output, "refusal")["actual_refs"] = ["E0003"]
            if self.audit_unknown:
                proof(output, "refusal")["status"] = "unknown"
        elif "dialogue_readings" in properties:
            self.reviews += 1
            output = review_v2(payload["full_current_script"], self.brief)
            if self.review_unknown:
                output["criteria"][0]["status"] = "unknown"
        elif "scene_plan" in payload:
            self.drafts += 1
            output = deepcopy(self.raw)
            if self.drafts > 1:
                output["title"] = "第二个完整原生稿"
                output["beats"][0]["steps"] += output["beats"][1]["steps"]
                del output["beats"][1]
                for i, beat in enumerate(output["beats"], 1):
                    beat["id"] = "V3_NEW" + str(i)
        else:
            output = plan_v3(contract.compile_script(self.raw, self.brief), self.brief)
        metadata = {"finish_reason": "tool_calls", "output_mode": "tool_call", "total_tokens": 100,
                    "response_id": "isolated_v3_mock_" + str(ordinal), "response_body_complete": True}
        if ordinal == self.usage_unknown_at:
            metadata.pop("total_tokens")
        return RoleResult(text=json.dumps(output, ensure_ascii=False), metadata=metadata, response_payload={"mock": True})


def test_v3_actual_runner_reconciles_all_pass_fact_contradiction_and_generates_complete_second_draft(pipeline_workspace_v3):
    runner, root, parent, brief, raw, script = pipeline_workspace_v3
    parent_before = (parent / "CALL_LEDGER.json").read_bytes()
    service = MockTextServiceV3(brief, raw)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "text_ready_for_director" and result["full_draft_versions"] == 2
    assert len(service.requests) == 7
    assert [r["role"] for r in service.requests] == ["writer", "writer", "director", "director", "writer", "director", "director"]
    first = json.loads((root / "versions" / "01" / "AUTOMATIC_DECISION.json").read_text(encoding="utf-8"))
    assert first["status"] == "needs_whole_revision" and "SOURCE_EVENT_refusal" in codes(first)
    assert service.requests[4]["payload"]["previous_complete_script"] == script
    assert service.requests[4]["payload"]["revision_requirements"] == first["revision_requirements"]
    final = json.loads((root / "DELIVERABLE" / "FULL_SCRIPT.json").read_text(encoding="utf-8"))
    native = json.loads((root / "DELIVERABLE" / "RAW_MODEL_SCRIPT.json").read_text(encoding="utf-8"))
    assert final == contract.compile_script(native, brief) and len(final["beats"]) == 3
    assert all(b["id"].startswith("V3_NEW") for b in final["beats"])
    assert service.requests[5]["payload"]["full_current_script"] == service.requests[6]["payload"]["full_current_script"] == final
    for i in [3, 6]:
        assert set(service.requests[i]["payload"]) == {"brief", "full_current_script", "evidence_catalog", "source_contract"}
        assert set(service.requests[i]["payload"]["source_contract"]) == {"source_obligations", "source_order"}
    assert all(service.requests[i]["payload"]["reference_fulltext"] for i in [0, 1, 2, 4, 5])
    assert not list(root.rglob("*assistant_decision*")) and not list(root.rglob("*human_decision*"))
    assert (parent / "CALL_LEDGER.json").read_bytes() == parent_before
    assert result["spend"]["effective_calls_started"] == 444
    assert result["spend"]["effective_reported_tokens"] == 6833233
    assert result["spend"]["unknown_token_reservations"] == 93117
    assert result["human_quality_approved"] is False and result["video_calls"] == 0


def test_v3_source_manifest_freezes_both_v1_and_v2_contract_dependencies(pipeline_workspace_v3):
    runner, root, _, _, _, _ = pipeline_workspace_v3
    runner.Pipeline(root).prepare()
    ledger = json.loads((root / "CALL_LEDGER.json").read_text(encoding="utf-8"))
    for version in [1, 2, 3]:
        assert f"src/content_factory/creative_autonomous_text_contract_v{version}.py" in ledger["source_manifest"]


def test_v3_completed_restart_keeps_seven_requests_and_all_spend(pipeline_workspace_v3):
    runner, root, _, brief, raw, _ = pipeline_workspace_v3
    service = MockTextServiceV3(brief, raw)
    first = runner.Pipeline(root, client_factory=lambda: service).run()
    second = runner.Pipeline(root, client_factory=lambda: service).run()
    assert first["status"] == second["status"] == "text_ready_for_director"
    assert len(service.requests) == 7 and first["spend"] == second["spend"]


@pytest.mark.parametrize("unknown_at", [1, 2, 3, 4])
def test_v3_unknown_request_stops_and_restart_never_reissues(unknown_at, pipeline_workspace_v3):
    runner, root, _, brief, raw, _ = pipeline_workspace_v3
    service = MockTextServiceV3(brief, raw, unknown_at=unknown_at)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_outcome_unknown" and len(service.requests) == unknown_at
    restart = runner.Pipeline(root, client_factory=lambda: service).run()
    assert restart["status"] == result["status"] and len(service.requests) == unknown_at
    assert result["spend"]["effective_calls_started"] == 437 + unknown_at
    assert result["spend"]["effective_reported_tokens"] == 6832533 + 100 * (unknown_at - 1)
    assert result["spend"]["unknown_token_reservations"] > 93117
    assert result["spend"]["old_budget_reset"] is False and not (root / "DELIVERABLE").exists()


@pytest.mark.parametrize("kind", ["review_unknown", "audit_unknown", "usage_unknown"])
def test_v3_unknown_gate_or_usage_blocks_extra_dispatch(kind, pipeline_workspace_v3):
    runner, root, _, brief, raw, _ = pipeline_workspace_v3
    args = {kind: True} if kind != "usage_unknown" else {"usage_unknown_at": 4}
    service = MockTextServiceV3(brief, raw, **args)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == ("halt_usage_unknown" if kind == "usage_unknown" else "halt_review_uncertain")
    assert len(service.requests) == (3 if kind == "review_unknown" else 4)
    assert not (root / "DELIVERABLE").exists()


def test_v3_blind_probe_uses_new_plan_but_no_expected_failure_hints_and_halts_before_draft(pipeline_workspace_v3):
    runner, root, _, brief, raw, script = pipeline_workspace_v3
    setup = json.loads((root / "SETUP.json").read_text(encoding="utf-8"))
    setup["regression_probe_file"] = "KNOWN_FAILURE_PROBE.json"
    (root / "SETUP.json").write_text(json.dumps(setup), encoding="utf-8")
    (root / "KNOWN_FAILURE_PROBE.json").write_text(json.dumps({"full_script": script, "expected_fail_codes": [],
        "expected_defect_groups": {"missing_first_refusal": ["SOURCE_EVENT_refusal", "SOURCE_ORDER_query_BEFORE_refusal"]},
        "source_identity": {"kind": "mock routing fixture, not creative gold"}}, ensure_ascii=False), encoding="utf-8")
    service = MockTextServiceV3(brief, raw, wrong_first_mapping=False, probe_miss=True)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_gate_regression_failed" and len(service.requests) == 2
    assert service.drafts == 0
    payload = service.requests[1]["payload"]
    assert "source_contract" in payload
    assert "expected_fail_codes" not in payload and "expected_defect_groups" not in payload
    assert "missing_first_refusal" not in json.dumps(payload)
    assert "scene_plan" not in payload and "previous_full_review" not in payload
    assert (root / "REGRESSION_PROBE.json").exists() and not (root / "DELIVERABLE").exists()


def test_v3_finish_recomputes_current_plan_bound_combined_decision(pipeline_workspace_v3):
    runner, root, _, brief, raw, script = pipeline_workspace_v3
    op = runner.Pipeline(root)
    op.prepare()
    plan, review_value = plan_v3(script, brief), review_v2(script, brief)
    audit_value = audit_v3(script, brief, plan)
    decision = contract.combine_decisions(review_value, audit_value, script, brief, plan)
    review = {"output": review_value, "validation": {"script_sha256": contract._digest(script)}, "ordinal": 440}
    audit = {"output": audit_value, "validation": {"script_sha256": contract._digest(script)}, "ordinal": 441}
    with pytest.raises(ValueError, match="derive from these two complete"):
        op.finish(script, plan, {"output": raw, "ordinal": 439}, review, audit, {**decision, "unproved_approval": True}, 1)
    assert not (root / "DELIVERABLE").exists()
