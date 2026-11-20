"""Actual 463/464 broad-context false pass, with immutable original judgments."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from src.content_factory import creative_autonomous_text_contract_v11 as contract
from src.content_factory import creative_autonomous_text_contract_v10 as previous
from tests.test_creative_autonomous_text_pipeline_v9 import actual_case, read, codes
from tests.test_creative_autonomous_text_pipeline_v10 import (
    subset, actual_461, adjudication_for, context_verdict,
    resume_workspace_v10, resume_workspace_v9, resume_workspace_v8, resume_workspace_v7,
    pipeline_workspace_v6, pipeline_workspace_v5, pipeline_workspace_v3, pipeline_workspace_v2,
    extract_for, add_claim, unsupported_claim, wire_checks, review_v2, audit_v5,
)


PROJECT = Path(__file__).resolve().parents[1]
ROOT10 = PROJECT / "data/production_trials/autonomous_text_pipeline_20261011/legal_resignation_10"


def actual_464():
    brief, script, plan, audit, review, scope = actual_case()
    extract = read(ROOT10 / "call_463_factual_scope_extract_03.json")["output"]
    verdict = read(ROOT10 / "call_464_finding_adjudication_03.json")["output"]
    return brief, script, plan, audit, review, scope, extract, verdict


def verdict_subset(value, extract, id_):
    result = deepcopy(value)
    result["extract_sha256"] = contract._digest(extract)
    result["findings"] = [row for row in result["findings"] if row["finding_id"] == id_]
    return result


def test_actual_464_false_pass_is_blocked_by_new_contract_without_editing_any_native_judgment():
    brief, script, plan, audit, review, scope, extract, verdict = actual_464()
    before = deepcopy((extract, verdict, script))
    assert previous.combine_adjudicated_decisions(review, audit, extract, verdict, script, brief, plan, scope)["status"] == "text_ready_for_director"
    result = contract.combine_adjudicated_decisions(review, audit, extract, verdict, script, brief, plan, scope)
    assert result["status"] == "needs_whole_revision"
    assert {"ADJUDICATION_CONTEXT_C-FU-01", "ADJUDICATION_CONTEXT_C-BP-01", "ADJUDICATION_CONTEXT_C-BP-03"}.issubset(codes(result))
    assert (extract, verdict, script) == before


@pytest.mark.parametrize("context_type", ["private_pressure", "scene_timing", "existing_source_event"])
def test_generic_context_cannot_authorize_actual_future_business_action_or_completion(context_type):
    brief, script, _, _, _, scope, full, native = actual_464()
    for id_ in ["C-FU-01", "C-BP-01"]:
        extract = subset(full, id_)
        verdict = verdict_subset(native, extract, id_)
        verdict["findings"][0]["context_type"] = context_type
        assert "ADJUDICATION_CONTEXT_" + id_ in codes(contract.decide_adjudication(verdict, extract, script, brief, scope))


def test_actual_personal_refusal_still_has_valid_source_context_f3_f4():
    brief, script, _, _, _, scope, full, native = actual_464()
    extract = subset(full, "C-LR-01")
    verdict = verdict_subset(native, extract, "C-LR-01")
    assert verdict["findings"][0]["context_type"] == "employee_refusal"
    assert {row["fact_id"] for row in verdict["findings"][0]["source_evidence"]} == {"F3", "F4"}
    assert contract.decide_adjudication(verdict, extract, script, brief, scope)["status"] == "text_ready_for_director"


def test_actual_461_declared_current_refusal_remains_allowed_but_date_does_not():
    brief, script, _, scope, full = actual_461()
    refusal = subset(full, "C-FUU-03")
    verdict = adjudication_for(refusal, script, brief, scope)
    context_verdict(verdict["findings"][0], brief)
    assert contract.decide_adjudication(verdict, refusal, script, brief, scope)["status"] == "text_ready_for_director"
    date = subset(full, "C-EDT-01")
    verdict = adjudication_for(date, script, brief, scope)
    context_verdict(verdict["findings"][0], brief)
    assert "FACT_SCOPE_C-EDT-01" in codes(contract.decide_adjudication(verdict, date, script, brief, scope))


def test_false_context_does_not_override_real_payment_literal_or_invented_source_quote():
    brief, script, _, scope, _ = actual_461()
    raw = {k: deepcopy(v) for k, v in script.items() if k != "selected_candidate_id"}
    raw["beats"][0]["steps"][1]["text"] = "公司说给你1000元。"
    script = contract.compile_script(raw, brief)
    extract = extract_for(script, brief, scope)
    add_claim(extract, "wage_or_payment", unsupported_claim("pay", "E0002", "公司说给你1000元。", "1000", "payment_amount", "company"))
    verdict = adjudication_for(extract, script, brief, scope)
    context_verdict(verdict["findings"][0], brief)
    assert "FACT_SCOPE_pay" in codes(contract.decide_adjudication(verdict, extract, script, brief, scope))
    verdict["findings"][0]["source_evidence"][0]["quote"] = "这个原文不存在"
    with pytest.raises(ValueError):
        contract.validate_adjudication(verdict, extract, script, brief, scope)


@pytest.fixture
def resume_workspace_v11(resume_workspace_v10):
    """Isolated native-shaped routing fixture; never changes real 451--464."""
    from scripts import run_autonomous_text_pipeline_v11 as runner
    _, root, parent, brief, script, plan, native = resume_workspace_v10
    ledger, manifest = read(parent / "CALL_LEDGER.json"), read(root / "RESUME_RECEIPTS.json")

    def replace(key, output):
        item = manifest["receipts"][key]
        path = Path(item["path"])
        receipt = read(path)
        receipt["output"] = deepcopy(output)
        path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        item["sha256"] = sha
        next(r for r in ledger["calls"] if r["ordinal"] == receipt["ordinal"])["receipt_sha256"] = sha
        return receipt

    # The synthetic source must explicitly state the same actor's intention;
    # ordinary all-pass fixtures do not establish real semantic source support.
    source = read(manifest["receipts"]["scope_source"]["path"])["output"]
    fact = brief["facts"][0]
    source["allowed_claims"].append({"id": "allow_refusal", "category": "employee_intention",
        "source_fact_ids": [fact["id"]], "source_quotes": [{"fact_id": fact["id"], "quote": fact["text"]}],
        "actor_id": "worker", "value": "小林没有提出辞职"})
    source["source_fact_coverage"][0]["allowed_claim_ids"].append("allow_refusal")
    replace("scope_source", source)
    scope = contract.compile_source_fact_scope(source, brief)
    native = deepcopy(native)
    native["output"]["scope_sha256"] = contract._digest(scope)
    replace("sensitive_probe", native["output"])
    old_script = contract.compile_script(read(manifest["receipts"]["sensitive_probe_draft"]["path"])["output"], brief)
    probe_verdict = adjudication_for(native["output"], old_script, brief, scope)
    context_verdict(next(r for r in probe_verdict["findings"] if r["finding_id"] == "C-FUU-03"), brief, fact["id"], fact["text"])

    raw = {k: deepcopy(v) for k, v in script.items() if k != "selected_candidate_id"}
    raw["beats"][0]["steps"][0]["text"] = "公司让我通知你，这次要你离开，签了我明天去送表。"
    script = contract.compile_script(raw, brief)
    replace("draft", raw)
    replace("review", wire_checks(review_v2(script, brief)))
    replace("audit", wire_checks(audit_v5(script, brief, plan)))
    current_extract = extract_for(script, brief, scope)
    add_claim(current_extract, "follow_up_undertaking", unsupported_claim("C-FU-01", "E0001",
        "签了我明天去送表", "明天去送表", "future_business_action", "hr"))
    current_verdict = adjudication_for(current_extract, script, brief, scope)
    current_verdict["findings"][0].update(disposition="context_or_source_supported", basis_kind="non_business_context",
        source_evidence=[{"fact_id": fact["id"], "quote": fact["text"]}], source_attribute_type="context",
        context_type="private_pressure", explanation="模拟旧裁决泛私人压力豁免；只验证新门拒绝它，不作为真实语义金标。")
    for ordinal, key, label, output, tokens in [
        (462, "sensitive_adjudication", "sensitive_regression_adjudication", probe_verdict, 17143),
        (463, "extract", "factual_scope_extract_03", current_extract, 19250),
        (464, "adjudication", "finding_adjudication_03", current_verdict, 15598),
    ]:
        receipt = {"ordinal": ordinal, "label": label, "status": "contract_valid", "output": output,
            "response_metadata": {"response_body_complete": True, "finish_reason": "tool_calls", "total_tokens": tokens}}
        path = parent / f"call_{ordinal}_{label}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        ledger["calls"].append({"ordinal": ordinal, "receipt": path.name, "receipt_sha256": sha})
        manifest["receipts"][key] = {"path": str(path.resolve()), "sha256": sha, "original_ordinal": ordinal}
    (parent / "CALL_LEDGER.json").write_text(json.dumps(ledger), encoding="utf-8")
    (root / "RESUME_RECEIPTS.json").write_text(json.dumps(manifest), encoding="utf-8")
    setup = read(root / "SETUP.json")
    setup["minimum_new_whole_drafts"] = 1
    (root / "SETUP.json").write_text(json.dumps(setup), encoding="utf-8")
    yield runner, root, parent, brief, script, plan, current_extract, current_verdict


class MockV11:
    def __init__(self, brief, script, plan, *, unknown_at=None, always_bad=False):
        self.brief, self.script, self.plan = deepcopy(brief), deepcopy(script), deepcopy(plan)
        self.requests, self.unknown_at, self.always_bad = [], unknown_at, always_bad

    def call(self, role, messages, **kwargs):
        from scripts.creative_evidenced_role_clients_v1 import EvidenceCallError
        from src.content_factory.creative_workflow_roles import RoleResult
        payload = json.loads(messages[-1]["content"])
        fields = kwargs["structured_schema"]["properties"]
        self.requests.append({"role": role, "payload": deepcopy(payload)})
        ordinal = len(self.requests)
        if ordinal == self.unknown_at:
            raise EvidenceCallError("MOCK_SENT_UNKNOWN", started=True, received=False, outcome_known=False)
        if "extract_sha256" in fields:
            output = adjudication_for(payload["original_detection"], payload["full_current_script"], self.brief, payload["source_fact_scope"])
        elif "category_extracts" in fields:
            output = extract_for(payload["full_current_script"], self.brief, payload["source_fact_scope"])
            if self.always_bad:
                add_claim(output, "follow_up_undertaking", unsupported_claim("new_promise", "E0001",
                    "签了我明天去送表", "明天去送表", "future_business_action", "hr"))
        elif "literal_events" in fields:
            output = wire_checks(audit_v5(payload["full_current_script"], self.brief, self.plan))
        elif "dialogue_readings" in fields:
            output = wire_checks(review_v2(payload["full_current_script"], self.brief))
        else:
            output = {k: deepcopy(v) for k, v in self.script.items() if k != "selected_candidate_id"}
            output["title"] = "模型完整第4稿"
            if not self.always_bad:
                output["beats"][0]["steps"][0]["text"] = "公司让我通知你，这次要你离开。"
            for i, beat in enumerate(output["beats"]): beat["id"] = "COMPLETE_FOURTH_" + str(i)
        return RoleResult(text=json.dumps(output, ensure_ascii=False), metadata={"response_body_complete": True,
            "finish_reason": "tool_calls", "output_mode": "tool_call", "response_id": "v11_mock_" + str(ordinal),
            "total_tokens": 100}, response_payload={"mock": True})


def test_inherited_464_is_revalidated_without_repay_then_one_new_whole_draft_has_all_four_reviews(resume_workspace_v11):
    runner, root, parent, brief, script, plan, extract, verdict = resume_workspace_v11
    before = (parent / "CALL_LEDGER.json").read_bytes()
    service = MockV11(brief, script, plan)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "text_ready_for_director" and result["full_draft_versions"] == 4, result
    assert [r["role"] for r in service.requests] == ["writer", "director", "director", "director", "director"]
    assert read(root / "versions/03/FACTUAL_SCOPE_EXTRACT.json") == extract
    assert read(root / "versions/03/FINDING_ADJUDICATION.json") == verdict
    assert "ADJUDICATION_CONTEXT_C-FU-01" in codes(read(root / "versions/03/AUTOMATIC_DECISION.json"))
    rewrite = service.requests[0]["payload"]
    assert "previous_complete_script" not in rewrite and rewrite["reference_fulltext"]
    assert rewrite["previous_complete_script_sha256"] == contract._digest(script)
    assert result["spend"]["effective_calls_started"] == 469
    assert result["spend"]["effective_reported_tokens"] == 7185444
    assert result["spend"]["unknown_token_reservations"] == 93117 and not result["spend"]["old_budget_reset"]
    assert (parent / "CALL_LEDGER.json").read_bytes() == before
    handoff = read(root / "DELIVERABLE/HANDOFF.json")
    assert handoff["manual_assistant_gate_calls"] == 0 and not handoff["human_quality_approved"]
    assert all(b["id"].startswith("COMPLETE_FOURTH_") for b in read(root / "DELIVERABLE/RAW_MODEL_SCRIPT.json")["beats"])
    assert not list(root.rglob("*human_decision*")) and not list(root.rglob("*assistant_decision*"))
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == 5


@pytest.mark.parametrize("unknown_at", [1, 3, 4, 5])
def test_unknown_writer_audit_extract_or_adjudication_stops_and_resume_does_not_redispatch(unknown_at, resume_workspace_v11):
    runner, root, _, brief, script, plan, _, _ = resume_workspace_v11
    service = MockV11(brief, script, plan, unknown_at=unknown_at)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_outcome_unknown" and len(service.requests) == unknown_at, result
    assert result["spend"]["effective_calls_started"] == 464 + unknown_at
    assert result["spend"]["effective_reported_tokens"] == 7184944 + 100 * (unknown_at - 1)
    assert result["spend"]["unknown_token_reservations"] > 93117 and not result["spend"]["old_budget_reset"]
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == unknown_at


def test_failed_fourth_draft_cannot_be_reset_or_replaced_by_a_fifth(resume_workspace_v11):
    runner, root, _, brief, script, plan, _, _ = resume_workspace_v11
    service = MockV11(brief, script, plan, always_bad=True)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "creative_stalled" and result["full_draft_versions"] == 4, result
    assert len(service.requests) == 5 and sum(r["role"] == "writer" for r in service.requests) == 1
    assert result["spend"]["effective_calls_started"] == 469 and not result["spend"]["old_budget_reset"]
    assert runner.Pipeline(root, client_factory=lambda: service).run()["status"] == result["status"]
    assert len(service.requests) == 5
