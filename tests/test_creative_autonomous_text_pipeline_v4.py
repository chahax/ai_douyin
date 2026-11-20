"""Focused v4 regression cases: atomic source acts and complete plan revision.

Only mock RoleResult clients are used; older contracts and receipts are frozen.
"""
from copy import deepcopy
import hashlib
import json

import pytest

from src.content_factory import creative_autonomous_text_contract_v4 as contract
from tests.test_creative_autonomous_text_pipeline_v2 import review_v2
from tests.test_creative_autonomous_text_pipeline_v3 import (
    plan_v3, audit_v3, source_case, proof, codes,
    pipeline_workspace_v2, pipeline_workspace_v3,
)


def audit_v4(script, brief, plan):
    value = audit_v3(script, brief, plan)
    for row in value["literal_events"]:
        row["speech_functions"] = [row["speech_function"]]
    return value


@pytest.mark.parametrize("functions", [["action", "statement"], ["question", "refusal"], ["action", "other"]])
def test_atomic_event_function_is_constrained_by_published_tool_schema(functions):
    brief, _, _, plan, _, _ = source_case()
    row = next(r for r in plan["source_obligations"] if r["mode"] == "event")
    row["allowed_speech_functions"] = functions
    from jsonschema import Draft202012Validator
    assert list(Draft202012Validator(contract.build_plan_schema(brief)).iter_errors(plan))
    with pytest.raises(ValueError):
        contract.validate_plan(plan, brief)


@pytest.mark.parametrize("mode", ["state", "absence"])
def test_strict_order_does_not_connect_non_event_states(mode):
    brief, _, _, plan, _, _ = source_case()
    row = next(r for r in plan["source_obligations"] if r["mode"] == "state")
    row["mode"] = mode
    plan["source_order"].append({"before_id": row["id"], "after_id": "notice"})
    with pytest.raises(ValueError, match="endpoints must both be event"):
        contract.validate_plan(plan, brief)


def test_actual_compound_dialogue_can_satisfy_atomic_statement_and_request_at_same_ref():
    brief, _, script, plan, review, _ = source_case()
    row = deepcopy(next(r for r in plan["source_obligations"] if r["id"] == "notice"))
    row.update(id="request_same_utterance", allowed_speech_functions=["request"])
    plan["source_obligations"].append(row)
    audit = audit_v4(script, brief, plan)
    proof(audit, "request_same_utterance")["actual_refs"] = ["E0001"]
    audit["literal_events"][0]["speech_functions"] = ["statement", "request"]
    assert contract.combine_decisions(review, audit, script, brief, plan)["status"] == "text_ready_for_director"
    plan["source_order"].append({"before_id": "notice", "after_id": "request_same_utterance"})
    result = contract.combine_decisions(review, audit, script, brief, plan)
    assert result["status"] == "needs_whole_revision"
    assert "SOURCE_ORDER_notice_BEFORE_request_same_utterance" in codes(result)


def test_question_negation_is_not_a_refusal_without_actual_refusal_function():
    brief, _, script, plan, review, _ = source_case()
    audit = audit_v4(script, brief, plan)
    proof(audit, "refusal")["actual_refs"] = ["E0003"]
    question = next(e for e in audit["literal_events"] if e["source_ref"] == "E0003")
    question.update(negative_or_refusal=True, speech_functions=["question", "statement"])
    result = contract.combine_decisions(review, audit, script, brief, plan)
    assert result["status"] == "needs_whole_revision" and "SOURCE_EVENT_refusal" in codes(result)


@pytest.mark.parametrize("change", ["primary_not_in_array", "action_multiple", "dialogue_action", "refusal_without_negative"])
def test_literal_function_array_has_internal_contract(change):
    brief, _, script, plan, _, _ = source_case()
    audit = audit_v4(script, brief, plan)
    if change == "primary_not_in_array":
        audit["literal_events"][0]["speech_functions"] = ["request"]
    elif change == "action_multiple":
        next(e for e in audit["literal_events"] if e["kind"] == "action")["speech_functions"] = ["action", "statement"]
    elif change == "dialogue_action":
        audit["literal_events"][0]["speech_functions"] = ["statement", "action"]
    else:
        audit["literal_events"][0]["speech_functions"] = ["statement", "refusal"]
    with pytest.raises(ValueError):
        contract.validate_audit(audit, script, brief, plan)


def invalid_complete_plan(script, brief, schema_error=False):
    plan = plan_v3(script, brief)
    if schema_error:
        next(r for r in plan["source_obligations"] if r["id"] == "collect")["allowed_speech_functions"] = ["action", "statement"]
    else:
        plan["source_order"].append({"before_id": plan["source_obligations"][0]["id"], "after_id": "notice"})
    return plan


@pytest.fixture
def pipeline_workspace_v4(pipeline_workspace_v3):
    from scripts import run_autonomous_text_pipeline_v4 as runner
    _, root, parent, brief, raw, script = pipeline_workspace_v3
    rejected = {"ordinal": 438, "label": "scene_plan", "status": "contract_rejected",
                "output": invalid_complete_plan(script, brief),
                "failure": {"category": "validation", "code": "VALIDATION_ERROR", "response_received": True},
                "response_metadata": {"total_tokens": 7490, "response_body_complete": True, "finish_reason": "tool_calls"}}
    name = "call_438_scene_plan.json"
    (parent / name).write_text(json.dumps(rejected, ensure_ascii=False), encoding="utf-8")
    ledger = json.loads((parent / "CALL_LEDGER.json").read_text(encoding="utf-8"))
    ledger["calls"] = [{"ordinal": 438, "receipt": name, "receipt_sha256": hashlib.sha256((parent / name).read_bytes()).hexdigest()}]
    (parent / "CALL_LEDGER.json").write_text(json.dumps(ledger), encoding="utf-8")
    yield runner, root, parent, brief, raw, script


def install_seed(root, parent, *, change=None):
    receipt = parent / "call_438_scene_plan.json"
    origin = json.loads(receipt.read_text(encoding="utf-8"))
    seed = {"receipt_path": str(receipt.resolve()), "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
            "original_ordinal": 438, "native_full_plan": deepcopy(origin["output"]),
            "revision_requirement": {"problem": "原生完整旧计划合同拒收", "required_revision": "模型提交整份新计划，冻结源不改。"}}
    if change == "patched_plan":
        seed["native_full_plan"]["title"] = "手工修改过的计划"
    elif change == "wrong_ordinal":
        seed["original_ordinal"] = 439
    elif change == "other_lineage":
        other = root / "unrelated_receipt.json"
        other.write_bytes(receipt.read_bytes())
        seed["receipt_path"] = str(other.resolve())
    (root / "SEED.json").write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")
    setup = json.loads((root / "SETUP.json").read_text(encoding="utf-8"))
    setup["seed_rejected_plan_file"] = "SEED.json"
    (root / "SETUP.json").write_text(json.dumps(setup), encoding="utf-8")


class MockV4:
    def __init__(self, brief, raw, *, invalid_plans=1, first_failure=None, schema_error=False):
        self.brief, self.raw = deepcopy(brief), deepcopy(raw)
        self.invalid_plans, self.first_failure, self.schema_error = invalid_plans, first_failure, schema_error
        self.requests = []
        self.plans = 0

    def call(self, role, messages, **kwargs):
        from scripts.creative_evidenced_role_clients_v1 import EvidenceCallError
        from src.content_factory.creative_workflow_roles import RoleResult
        payload = json.loads(messages[-1]["content"])
        properties = kwargs["structured_schema"]["properties"]
        self.requests.append({"role": role, "payload": deepcopy(payload), "schema": deepcopy(kwargs["structured_schema"])})
        ordinal = len(self.requests)
        if ordinal == 1 and self.first_failure == "unknown":
            raise EvidenceCallError("MOCK_SENT_UNKNOWN", started=True, received=False, outcome_known=False)
        if "literal_events" in properties:
            plan = plan_v3(contract.compile_script(self.raw, self.brief), self.brief)
            output = audit_v4(payload["full_current_script"], self.brief, plan)
        elif "dialogue_readings" in properties:
            output = review_v2(payload["full_current_script"], self.brief)
        elif "scene_plan" in payload:
            output = deepcopy(self.raw)
        else:
            self.plans += 1
            output = invalid_complete_plan(contract.compile_script(self.raw, self.brief), self.brief, self.schema_error) if self.plans <= self.invalid_plans else plan_v3(contract.compile_script(self.raw, self.brief), self.brief)
            if self.plans > self.invalid_plans:
                output["title"] = "完整新计划原生回复"
                for i, beat in enumerate(output["beats"]):
                    beat["id"] = "PLAN_NEW_" + str(i)
        metadata = {"finish_reason": "tool_calls", "output_mode": "tool_call", "total_tokens": 100,
                    "response_id": "v4_mock_" + str(ordinal), "response_body_complete": True}
        if ordinal == 1:
            if self.first_failure == "truncated":
                metadata["finish_reason"] = "length"
            elif self.first_failure == "unknown_finish":
                metadata.pop("finish_reason")
            elif self.first_failure == "incomplete":
                metadata["response_body_complete"] = False
            elif self.first_failure == "negative_usage":
                metadata["total_tokens"] = -1
        return RoleResult(text=json.dumps(output, ensure_ascii=False), metadata=metadata, response_payload={"mock": True})


@pytest.mark.parametrize("schema_error", [False, True])
def test_known_full_plan_rejection_automatically_dispatches_whole_new_plan_then_full_script_and_two_checks(schema_error, pipeline_workspace_v4):
    runner, root, parent, brief, raw, script = pipeline_workspace_v4
    parent_before = (parent / "CALL_LEDGER.json").read_bytes()
    service = MockV4(brief, raw, schema_error=schema_error)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "text_ready_for_director"
    assert len(service.requests) == 5 and service.plans == 2
    ledger = json.loads((root / "CALL_LEDGER.json").read_text(encoding="utf-8"))
    assert [r["label"] for r in ledger["calls"]] == ["scene_plan_01", "scene_plan_02", "whole_draft_01", "whole_review_01", "literal_audit_01"]
    first = json.loads((root / ledger["calls"][0]["receipt"]).read_text(encoding="utf-8"))
    assert first["status"] == "contract_rejected" and first["automatic_retry"] is False
    assert service.requests[1]["payload"]["previous_complete_plan"] == first["output"]
    assert service.requests[1]["payload"]["brief"] == brief
    native = json.loads((root / ledger["calls"][1]["receipt"]).read_text(encoding="utf-8"))["output"]
    assert json.loads((root / "SCENE_PLAN.json").read_text(encoding="utf-8")) == native
    assert all(b["id"].startswith("PLAN_NEW_") for b in native["beats"])
    assert service.requests[2]["payload"]["scene_plan"] == native
    assert json.loads((root / "DELIVERABLE" / "FULL_SCRIPT.json").read_text(encoding="utf-8")) == script
    assert result["spend"]["effective_calls_started"] == 443 and result["spend"]["effective_reported_tokens"] == 6840523
    assert result["spend"]["unknown_token_reservations"] == 93117
    assert not list(root.rglob("*assistant_decision*")) and not list(root.rglob("*human_decision*"))
    assert (parent / "CALL_LEDGER.json").read_bytes() == parent_before
    restart = runner.Pipeline(root, client_factory=lambda: service).run()
    assert restart["status"] == result["status"] and len(service.requests) == 5


@pytest.mark.parametrize("failure", ["unknown", "truncated", "unknown_finish", "incomplete", "negative_usage"])
def test_uncertain_or_incomplete_plan_cannot_trigger_new_generation_and_restart_does_not_reissue(failure, pipeline_workspace_v4):
    runner, root, _, brief, raw, _ = pipeline_workspace_v4
    service = MockV4(brief, raw, first_failure=failure)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"].startswith("halt_") and len(service.requests) == 1
    restart = runner.Pipeline(root, client_factory=lambda: service).run()
    assert restart["status"] == result["status"] and len(service.requests) == 1
    assert result["spend"]["effective_calls_started"] == 439
    assert result["spend"]["effective_reported_tokens"] >= 6840023
    assert result["spend"]["unknown_token_reservations"] >= 93117
    assert result["spend"]["old_budget_reset"] is False and not (root / "DELIVERABLE").exists()


@pytest.mark.parametrize("change", ["patched_plan", "wrong_ordinal", "other_lineage"])
def test_seed_must_equal_original_parent_receipt_without_local_patch_or_unaccounted_call(change, pipeline_workspace_v4):
    runner, root, parent, brief, raw, _ = pipeline_workspace_v4
    install_seed(root, parent, change=change)
    service = MockV4(brief, raw)
    with pytest.raises(RuntimeError, match="seed changed|frozen receipt lineage"):
        runner.Pipeline(root, client_factory=lambda: service).run()
    assert service.requests == []


def test_original_failed_seed_remains_counted_and_allows_only_two_new_plans_by_default(pipeline_workspace_v4):
    runner, root, parent, brief, raw, _ = pipeline_workspace_v4
    install_seed(root, parent)
    service = MockV4(brief, raw, invalid_plans=99)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "plan_stalled" and len(service.requests) == 2
    assert result["spend"]["effective_calls_started"] == 440 and result["spend"]["effective_reported_tokens"] == 6840223
    seed = json.loads((root / "SEED.json").read_text(encoding="utf-8"))
    assert service.requests[0]["payload"]["previous_complete_plan"] == seed["native_full_plan"]
    assert not (root / "DELIVERABLE").exists()


def test_seed_cannot_expand_the_plan_cap_to_three_new_paid_generations(pipeline_workspace_v4):
    runner, root, parent, brief, raw, _ = pipeline_workspace_v4
    install_seed(root, parent)
    setup = json.loads((root / "SETUP.json").read_text(encoding="utf-8"))
    setup["max_full_plans"] = 3
    (root / "SETUP.json").write_text(json.dumps(setup), encoding="utf-8")
    service = MockV4(brief, raw)
    with pytest.raises(ValueError, match="bounded plan"):
        runner.Pipeline(root, client_factory=lambda: service).run()
    assert service.requests == []


def test_negative_usage_on_valid_plan_stops_before_draft(pipeline_workspace_v4):
    runner, root, _, brief, raw, _ = pipeline_workspace_v4
    service = MockV4(brief, raw, invalid_plans=0, first_failure="negative_usage")
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_usage_unknown" and len(service.requests) == 1
    assert result["spend"]["effective_reported_tokens"] == 6840023
    assert result["spend"]["unknown_token_reservations"] > 93117


def test_runtime_freezes_all_four_explicit_contract_dependencies(pipeline_workspace_v4):
    runner, root, _, _, _, _ = pipeline_workspace_v4
    runner.Pipeline(root).prepare()
    ledger = json.loads((root / "CALL_LEDGER.json").read_text(encoding="utf-8"))
    for version in [1, 2, 3, 4]:
        assert f"src/content_factory/creative_autonomous_text_contract_v{version}.py" in ledger["source_manifest"]


def test_unrelated_state_contract_failure_is_not_reclassified_as_complete_plan_repair(pipeline_workspace_v4):
    runner, root, parent, brief, raw, _ = pipeline_workspace_v4
    receipt_path = parent / "call_438_scene_plan.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["failure"].update(category="state_contract", code="UNRELATED_STATE_CONTRACT_FAILURE")
    assert runner.known_full_plan_rejection(receipt) is False
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
    ledger = json.loads((parent / "CALL_LEDGER.json").read_text(encoding="utf-8"))
    ledger["calls"][0]["receipt_sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    (parent / "CALL_LEDGER.json").write_text(json.dumps(ledger), encoding="utf-8")
    service = MockV4(brief, raw)
    with pytest.raises(RuntimeError, match="parent unresolved"):
        runner.Pipeline(root, client_factory=lambda: service).run()
    assert service.requests == []
