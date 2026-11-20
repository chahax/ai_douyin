"""Small v6 wire/compiler checks; mock routing never establishes quality gold."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from src.content_factory import creative_autonomous_text_contract_v6 as contract
from tests.test_creative_autonomous_text_pipeline_v5 import (
    case_v5, MockV5, pipeline_workspace_v5, pipeline_workspace_v3,
    pipeline_workspace_v2, plan_v5, source_audit_v5,
)


def wire_plan(compiled):
    value = deepcopy(compiled)
    for key in ["initial_conditions", "source_order"]:
        for row in value[key]:
            row.pop("source_quote")
    return value


def wire_source_audit(compiled):
    value = deepcopy(compiled)
    for key in ["fact_coverage_checks", "source_obligation_checks", "initial_condition_checks", "source_order_checks"]:
        for row in value[key]:
            row.pop("source_quote")
    return value


def test_native_plan_values_remain_exact_and_only_frozen_quotes_are_added():
    brief, _, _, plan, _, _ = case_v5()
    native = wire_plan(plan)
    before = deepcopy(native)
    compiled = contract.compile_plan(native, brief)
    assert native == before and wire_plan(compiled) == before
    states = {(kind, r["id"]): r["expected_state"] for kind, table in [("character", "character_states"), ("prop", "prop_states")] for r in brief["initial_state"][table]}
    facts = {r["id"]: r["text"] for r in brief["facts"]}
    assert all(r["source_quote"] == states[r["entity_type"], r["entity_id"]] for r in compiled["initial_conditions"])
    assert all(r["source_quote"] == facts[r["fact_id"]] for r in compiled["source_order"])
    metadata = contract.validate_plan(native, brief)
    assert metadata["raw_plan_sha256"] == contract._digest(before)
    assert metadata["compiled_plan_sha256"] == contract._digest(compiled)
    assert metadata["native_creative_values_unchanged"] is True


@pytest.mark.parametrize("id_type", ["entity", "fact"])
def test_frozen_quote_resolution_cannot_invent_unknown_ids(id_type):
    brief, _, _, plan, _, _ = case_v5()
    native = wire_plan(plan)
    if id_type == "entity":
        native["initial_conditions"][0]["entity_id"] = "invented_person"
    else:
        native["source_order"][0]["fact_id"] = "invented_fact"
    with pytest.raises(ValueError):
        contract.compile_plan(native, brief)


def test_model_source_quote_is_not_accepted_as_wire_input():
    brief, _, _, plan, _, _ = case_v5()
    native = wire_plan(plan)
    schema = contract.build_plan_schema(brief)
    assert all("source_quote" not in schema["properties"][key]["items"]["properties"] for key in ["initial_conditions", "source_order"])
    native["initial_conditions"][0]["source_quote"] = "模型复述的设置，不能冒充冻结来源"
    with pytest.raises(ValueError):
        contract.compile_plan(native, brief)


def test_compiler_does_not_repair_creative_physical_atoms_to_match_quote():
    brief, _, _, plan, _, _ = case_v5()
    native = wire_plan(plan)
    next(r for r in native["initial_conditions"] if r["entity_id"] == "application")["orientation"] = "face_down"
    compiled = contract.compile_plan(native, brief)
    paper = next(r for r in compiled["initial_conditions"] if r["entity_id"] == "application")
    assert paper["orientation"] == "face_down" and "面朝上" in paper["source_quote"]
    assert wire_plan(compiled) == native


def test_source_audit_quote_compiler_preserves_native_fail_and_all_semantic_values():
    brief, _, _, plan, _, _ = case_v5()
    native = wire_source_audit(source_audit_v5(plan, brief))
    native["source_order_checks"][0].update(status="fail", explanation="源只要求同一请求，不支持先后两次。", required_revision="完整新计划移除无来源先后。")
    before = deepcopy(native)
    compiled = contract.compile_source_audit(native, plan, brief)
    assert native == before and wire_source_audit(compiled) == before
    assert compiled["source_order_checks"][0]["source_quote"] == plan["source_order"][0]["source_quote"]
    assert contract.decide_source_audit(native, plan, brief)["status"] == "needs_whole_plan_revision"
    assert all(r["source_quote"] for key in ["fact_coverage_checks", "source_obligation_checks", "initial_condition_checks", "source_order_checks"] for r in compiled[key])


def test_source_audit_wire_cannot_accept_model_copied_or_invented_quote():
    brief, _, _, plan, _, _ = case_v5()
    native = wire_source_audit(source_audit_v5(plan, brief))
    native["source_order_checks"][0]["source_quote"] = "自造来源"
    with pytest.raises(ValueError):
        contract.compile_source_audit(native, plan, brief)


@pytest.fixture
def pipeline_workspace_v6(pipeline_workspace_v5):
    from scripts import run_autonomous_text_pipeline_v6 as runner
    _, root, parent, brief, raw, script = pipeline_workspace_v5
    actual = Path(__file__).resolve().parents[1] / "data/production_trials/autonomous_text_pipeline_20261011/legal_resignation_05"
    ledger = json.loads((parent / "CALL_LEDGER.json").read_text(encoding="utf-8"))
    ledger["calls"] = []
    for ordinal in [442, 443]:
        name = f"call_{ordinal}_scene_plan_0{ordinal - 441}.json"
        # Read the unchanged known-complete rejected parent receipts, preserving
        # both actual spends; only this isolated mock parent ledger is created.
        (parent / name).write_bytes((actual / name).read_bytes())
        ledger["calls"].append({"ordinal": ordinal, "receipt": name, "receipt_sha256": hashlib.sha256((parent / name).read_bytes()).hexdigest()})
    (parent / "CALL_LEDGER.json").write_text(json.dumps(ledger), encoding="utf-8")
    yield runner, root, parent, brief, raw, script


class MockV6(MockV5):
    def call(self, role, messages, **kwargs):
        from src.content_factory.creative_workflow_roles import RoleResult
        result = super().call(role, messages, **kwargs)
        output = json.loads(result.text)
        if "initial_conditions" in kwargs["structured_schema"]["properties"]:
            output = wire_plan(output)
            result = RoleResult(text=json.dumps(output, ensure_ascii=False), metadata=result.metadata, response_payload=result.response_payload)
        elif "fact_coverage_checks" in kwargs["structured_schema"]["properties"]:
            output = wire_source_audit(output)
            result = RoleResult(text=json.dumps(output, ensure_ascii=False), metadata=result.metadata, response_payload=result.response_payload)
        return result


def test_source_failure_regenerates_full_native_plan_and_preserves_443_spend_without_manual_gate(pipeline_workspace_v6):
    runner, root, parent, brief, raw, script = pipeline_workspace_v6
    before = (parent / "CALL_LEDGER.json").read_bytes()
    service = MockV6(brief, raw)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "text_ready_for_director" and len(service.requests) == 7
    plan = json.loads((root / "SCENE_PLAN.json").read_text(encoding="utf-8"))
    native = json.loads((root / "RAW_MODEL_PLAN.json").read_text(encoding="utf-8"))
    assert wire_plan(plan) == native and all(b["id"].startswith("SOURCE_NEW_") for b in native["beats"])
    assert service.requests[2]["payload"]["previous_complete_plan"] == wire_plan(service.requests[1]["payload"]["full_source_plan"])
    assert service.requests[4]["payload"]["scene_plan"] == plan
    assert json.loads((root / "DELIVERABLE" / "FULL_SCRIPT.json").read_text(encoding="utf-8")) == script
    assert json.loads((root / "DELIVERABLE" / "RAW_MODEL_PLAN.json").read_text(encoding="utf-8")) == native
    assert not list(root.rglob("*assistant_decision*")) and not list(root.rglob("*human_decision*"))
    assert result["spend"]["effective_calls_started"] == 450 and result["spend"]["effective_reported_tokens"] == 6893906
    assert result["spend"]["unknown_token_reservations"] == 93117 and result["spend"]["old_budget_reset"] is False
    assert (parent / "CALL_LEDGER.json").read_bytes() == before
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"] and len(service.requests) == 7


@pytest.mark.parametrize("unknown_at", [2, 5])
def test_unknown_source_or_body_audit_stops_and_restart_does_not_redispatch(unknown_at, pipeline_workspace_v6):
    runner, root, _, brief, raw, _ = pipeline_workspace_v6
    service = MockV6(brief, raw, first_source_fail=False, unknown_at=unknown_at)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_outcome_unknown" and len(service.requests) == unknown_at
    assert result["spend"]["effective_calls_started"] == 443 + unknown_at
    assert result["spend"]["effective_reported_tokens"] == 6893206 + 100 * (unknown_at - 1)
    assert result["spend"]["unknown_token_reservations"] > 93117
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"] and len(service.requests) == unknown_at


def test_all_six_contract_dependencies_are_frozen(pipeline_workspace_v6):
    runner, root, _, _, _, _ = pipeline_workspace_v6
    runner.Pipeline(root).prepare()
    ledger = json.loads((root / "CALL_LEDGER.json").read_text(encoding="utf-8"))
    assert all(f"src/content_factory/creative_autonomous_text_contract_v{i}.py" in ledger["source_manifest"] for i in range(1, 7))
