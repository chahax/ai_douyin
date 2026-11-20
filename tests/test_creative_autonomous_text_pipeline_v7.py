"""Only frozen source metadata is compiled; model judgments stay untouched."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from src.content_factory import creative_autonomous_text_contract_v7 as contract
from tests.test_creative_autonomous_text_pipeline_v5 import case_v5, audit_v5, source_audit_v5
from tests.test_creative_autonomous_text_pipeline_v6 import (
    wire_plan, wire_source_audit, pipeline_workspace_v6, pipeline_workspace_v5,
    pipeline_workspace_v3, pipeline_workspace_v2,
)


def wire_checks(value):
    result = deepcopy(value)
    for row in result["fact_checks"]:
        row.pop("expected_fact")
    for row in result["initial_state_checks"]:
        row.pop("expected_state")
    return result


@pytest.mark.parametrize("kind", ["review", "audit"])
def test_source_metadata_compiler_preserves_native_fail_observation_and_all_decisions(kind):
    brief, _, script, plan, review, audit = case_v5()
    native = wire_checks(review if kind == "review" else audit)
    native["fact_checks"][0].update(status="fail", observed_fact="当前实际没有演出所要求的拒签。", required_revision="提交完整新稿，不能改源事实。")
    before = deepcopy(native)
    compiled = contract.compile_review(native, script, brief) if kind == "review" else contract.compile_audit(native, script, brief, plan)
    assert native == before and wire_checks(compiled) == before
    facts = {r["id"]: r["text"] for r in brief["facts"]}
    states = {(kind_, r["id"]): r["expected_state"] for kind_, table in [("character", "character_states"), ("prop", "prop_states")] for r in brief["initial_state"][table]}
    assert all(r["expected_fact"] == facts[r["fact_id"]] for r in compiled["fact_checks"])
    assert all(r["expected_state"] == states[r["entity_type"], r["entity_id"]] for r in compiled["initial_state_checks"])
    result = contract.decide_review(native, script, brief) if kind == "review" else contract.decide_audit(native, script, brief, plan)
    assert result["status"] == "needs_whole_revision"


@pytest.mark.parametrize("kind", ["review", "audit"])
def test_legacy_projection_drops_only_source_metadata_without_changing_model_judgments(kind):
    brief, _, script, plan, review, audit = case_v5()
    legacy = review if kind == "review" else audit
    legacy["fact_checks"][0]["expected_fact"] = "旧接口把来源复述为另一说法"
    legacy["initial_state_checks"][0]["expected_state"] = "另一段初态描述"
    before = deepcopy(legacy)
    projected = contract.project_legacy_review(legacy, script, brief) if kind == "review" else contract.project_legacy_audit(legacy, script, brief, plan)
    assert legacy == before and projected == wire_checks(before)
    legacy["unrecognized_extra_content"] = "不能默默删掉其它字段"
    with pytest.raises(ValueError):
        if kind == "review":
            contract.project_legacy_review(legacy, script, brief)
        else:
            contract.project_legacy_audit(legacy, script, brief, plan)


def test_wire_source_expected_fields_and_fake_ids_are_rejected():
    brief, _, script, plan, review, audit = case_v5()
    for kind, legacy in [("review", review), ("audit", audit)]:
        native = wire_checks(legacy)
        native["fact_checks"][0]["expected_fact"] = "自造来源"
        with pytest.raises(ValueError):
            contract.compile_review(native, script, brief) if kind == "review" else contract.compile_audit(native, script, brief, plan)
        native = wire_checks(legacy)
        native["fact_checks"][0]["fact_id"] = "invented_fact"
        with pytest.raises(ValueError):
            contract.compile_review(native, script, brief) if kind == "review" else contract.compile_audit(native, script, brief, plan)


def test_wrong_script_identity_is_not_fixed_by_source_compiler_or_legacy_projection():
    brief, _, script, plan, review, audit = case_v5()
    for kind, legacy in [("review", review), ("audit", audit)]:
        legacy["script_sha256"] = "0" * 64
        with pytest.raises(ValueError):
            contract.project_legacy_review(legacy, script, brief) if kind == "review" else contract.project_legacy_audit(legacy, script, brief, plan)


def test_actual_449_complete_native_review_is_preserved_except_explicit_metadata_projection():
    root = Path(__file__).resolve().parents[1] / "data/production_trials/autonomous_text_pipeline_20261011/legal_resignation_06"
    brief = json.loads((root / "INPUT.json").read_text(encoding="utf-8"))["brief"]
    draft = json.loads((root / "call_448_whole_draft_01.json").read_text(encoding="utf-8"))
    receipt = json.loads((root / "call_449_whole_review_01.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "contract_rejected" and receipt["response_metadata"]["total_tokens"] == 14619
    native = deepcopy(receipt["output"])
    facts = {r["id"]: r["text"] for r in brief["facts"]}
    assert any(r["expected_fact"] != facts[r["fact_id"]] for r in native["fact_checks"])
    script = contract.compile_script(draft["output"], brief)
    projected = contract.project_legacy_review(native, script, brief)
    compiled = contract.compile_review(projected, script, brief)
    assert native == receipt["output"] and projected == wire_checks(native) and wire_checks(compiled) == projected
    assert all(r["expected_fact"] == facts[r["fact_id"]] for r in compiled["fact_checks"])


@pytest.fixture
def resume_workspace_v7(pipeline_workspace_v6):
    from scripts import run_autonomous_text_pipeline_v7 as runner
    _, root, parent, brief, raw, script = pipeline_workspace_v6
    _, _, _, source_plan, review, probe = case_v5()
    native_plan = wire_plan(source_plan)
    plan = contract.compile_plan(native_plan, brief)
    source = wire_source_audit(source_audit_v5(plan, brief))
    probe = audit_v5(script, brief, plan)
    next(r for r in probe["obligation_evidence"] if r["obligation_id"] == "refusal")["occurrence_refs"] = ["E0003"]
    review["fact_checks"][0]["expected_fact"] = "旧完整回执复述来源，全部判断原样保留"
    metadata = {"response_body_complete": True, "finish_reason": "tool_calls"}
    names = {444: "scene_plan_01", 445: "scene_plan_02", 446: "source_contract_audit_02", 447: "literal_gate_regression_probe", 448: "whole_draft_01", 449: "whole_review_01"}
    outputs = {444: deepcopy(native_plan), 445: native_plan, 446: source, 447: probe, 448: raw, 449: review}
    # These are isolated routing fixtures. Their spend matches the unchanged
    # real lineage, while all mocked judgments are explicitly not quality gold.
    tokens = {444: 8946, 445: 11014, 446: 7829, 447: 14905, 448: 8473, 449: 14619}
    ledger = json.loads((parent / "CALL_LEDGER.json").read_text(encoding="utf-8"))
    manifest = {"receipts": {}}
    keys = {445: "plan", 446: "source_audit", 447: "probe", 448: "draft", 449: "review"}
    for ordinal in range(444, 450):
        receipt = {"ordinal": ordinal, "label": names[ordinal], "status": "contract_valid", "output": outputs[ordinal], "response_metadata": {**metadata, "total_tokens": tokens[ordinal]}}
        if ordinal == 444:
            receipt.update(status="contract_rejected", failure={"category": "validation", "code": "MOCK_KNOWN_FULL_PLAN_REJECTION", "response_received": True})
        if ordinal == 449:
            receipt.update(status="contract_rejected", failure={"category": "validation", "code": "fact check changed the brief's expected source fact", "response_received": True})
        path = parent / f"call_{ordinal}_{names[ordinal]}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        ledger["calls"].append({"ordinal": ordinal, "receipt": path.name, "receipt_sha256": sha})
        if ordinal in keys:
            manifest["receipts"][keys[ordinal]] = {"path": str(path.resolve()), "sha256": sha, "original_ordinal": ordinal}
    (parent / "CALL_LEDGER.json").write_text(json.dumps(ledger), encoding="utf-8")
    (root / "RESUME_RECEIPTS.json").write_text(json.dumps(manifest), encoding="utf-8")
    probe_fixture = {"full_script": script, "expected_fail_codes": ["SOURCE_EVENT_refusal"], "expected_defect_groups": {"missing_refusal": ["SOURCE_EVENT_refusal"]}, "source_identity": "mock_source_identity"}
    (root / "PROBE.json").write_text(json.dumps(probe_fixture, ensure_ascii=False), encoding="utf-8")
    setup = json.loads((root / "SETUP.json").read_text(encoding="utf-8"))
    setup.update(resume_receipts_file="RESUME_RECEIPTS.json", regression_probe_file="PROBE.json")
    (root / "SETUP.json").write_text(json.dumps(setup), encoding="utf-8")
    yield runner, root, parent, brief, script, plan, review


class AuditOnlyMock:
    def __init__(self, brief, plan):
        self.brief, self.plan = deepcopy(brief), deepcopy(plan)
        self.requests = []

    def call(self, role, messages, **kwargs):
        from src.content_factory.creative_workflow_roles import RoleResult
        payload = json.loads(messages[-1]["content"])
        self.requests.append({"role": role, "payload": payload})
        assert "full_current_script" in payload and "literal_events" in kwargs["structured_schema"]["properties"]
        output = wire_checks(audit_v5(payload["full_current_script"], self.brief, self.plan))
        return RoleResult(text=json.dumps(output, ensure_ascii=False), metadata={"response_body_complete": True, "finish_reason": "tool_calls", "output_mode": "tool_call", "response_id": "v7_mock_audit", "total_tokens": 100}, response_payload={"mock": True})


def test_resume_known_full_449_projects_metadata_and_dispatches_only_missing_audit_without_reset(resume_workspace_v7):
    runner, root, parent, brief, script, plan, native_review = resume_workspace_v7
    before = (parent / "CALL_LEDGER.json").read_bytes()
    service = AuditOnlyMock(brief, plan)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "text_ready_for_director" and len(service.requests) == 1, result
    assert service.requests[0]["payload"]["full_current_script"] == script
    assert result["spend"]["effective_calls_started"] == 450 and result["spend"]["effective_reported_tokens"] == 6959092
    assert result["spend"]["unknown_token_reservations"] == 93117 and result["spend"]["old_budget_reset"] is False
    assert json.loads((root / "versions/01/ORIGINAL_NATIVE_REVIEW.json").read_text(encoding="utf-8")) == native_review
    revalidated = json.loads((root / "versions/01/REVALIDATED_REVIEW.json").read_text(encoding="utf-8"))
    assert revalidated["original_status"] == "contract_rejected" and revalidated["output"] == wire_checks(native_review)
    old_probe = json.loads((root / "REVALIDATED_REGRESSION_PROBE.json").read_text(encoding="utf-8"))
    assert old_probe["status"] == "needs_whole_revision" and "SOURCE_EVENT_refusal" in {r["code"] for r in old_probe["revision_requirements"]}
    imported = json.loads((root / "IMPORTED_EVIDENCE.json").read_text(encoding="utf-8"))
    assert imported["old_review_status"] == "contract_rejected" and imported["new_paid_upstream_calls"] == 0
    assert (parent / "CALL_LEDGER.json").read_bytes() == before
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"] and len(service.requests) == 1


def change_resume_receipt(root, parent, change):
    manifest = json.loads((root / "RESUME_RECEIPTS.json").read_text(encoding="utf-8"))
    item = manifest["receipts"]["review"]
    if change == "manifest_sha":
        item["sha256"] = "0" * 64
    elif change == "manifest_ordinal":
        item["original_ordinal"] = 450
    else:
        path = Path(item["path"])
        value = json.loads(path.read_text(encoding="utf-8"))
        if change == "unknown":
            value.update(status="outcome_unknown")
            value.pop("output")
        else:
            value["output"]["script_sha256"] = "0" * 64
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        item["sha256"] = sha
        ledger = json.loads((parent / "CALL_LEDGER.json").read_text(encoding="utf-8"))
        next(r for r in ledger["calls"] if r["ordinal"] == 449)["receipt_sha256"] = sha
        (parent / "CALL_LEDGER.json").write_text(json.dumps(ledger), encoding="utf-8")
    (root / "RESUME_RECEIPTS.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.parametrize("change", ["unknown", "manifest_sha", "manifest_ordinal", "wrong_script"])
def test_unknown_changed_or_wrong_script_review_cannot_import_or_dispatch(change, resume_workspace_v7):
    runner, root, parent, brief, _, plan, _ = resume_workspace_v7
    change_resume_receipt(root, parent, change)
    service = AuditOnlyMock(brief, plan)
    with pytest.raises((ValueError, RuntimeError)):
        runner.Pipeline(root, client_factory=lambda: service).run()
    assert service.requests == []
