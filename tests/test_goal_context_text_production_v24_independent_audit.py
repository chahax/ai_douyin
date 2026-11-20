"""Independent source-v4 evidence-role admission, synthetic services only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest
from scripts import run_goal_context_text_production_v24 as runner
from scripts import record_legal_evidence_roles_continuation_v1 as authorizer
from tests import legal_evidence_roles_service_helper_v1 as service
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests.test_creative_goal_legal_usage_source_audit_v4 import synthetic_source, add_legal_usage, source_usages
from src.content_factory import creative_goal_legal_usage_source_audit_v4 as legal

INHERITED={"calls_started":610,"reported_tokens":12538733,"calls_with_known_usage":608,
    "pending_ordinals":[70,160],"unknown_token_reservations":93117}
ACTUAL_ROOT=runner.PREFLIGHT_PARENT

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a,**k):raise AssertionError("v24 independent test must not contact providers")
    monkeypatch.setattr(socket.socket,"connect",deny)
    monkeypatch.setattr(socket,"create_connection",deny)


def replay(tmp_path,monkeypatch,scenario,modes=None):
    monkeypatch.setattr(service,"runner",runner)
    monkeypatch.setattr(service,"INHERITED",deepcopy(INHERITED))
    monkeypatch.setattr(service,"synthetic_source",synthetic_source)
    monkeypatch.setattr(service,"legal_audit",legal)
    monkeypatch.setattr(service,"add_usage",lambda document,goal,ref,*,relation,status=None:add_legal_usage(document,goal,ref,relation=relation))
    original_clients=runner.clients
    monkeypatch.setattr(runner,"clients",SimpleNamespace(TOOL_NAME=original_clients.TOOL_NAME,
        expected_wire_request=lambda request:runner.strict_clients.expected_wire_request(request,source_strict=runner.is_strict_source(request))))
    runtime,root,sends=service.replay(tmp_path,monkeypatch,scenario,modes)
    inputs,profile,goal=runner.read(root/"INPUTS.json"),runner.read(runner.PROFILE),runner.read(root/"INHERITED_NATIVE_GOAL.json")
    first=runner.prepare_source_audit(inputs,profile,goal)
    runner.write(root/"FIRST_SOURCE_REQUEST_PREVIEW.json",first,True)
    return runtime,root,sends,first


def test_new_source4_complete609_then_bound_three_audits_and_body_double_review(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,first=replay(tmp_path,monkeypatch,causal_scenario)
    result=runner.run()
    assert result["status"]=="text_ready_for_director",result
    assert [service.phase(row) for row in sends[:3]]==["source","commitment","drama"]
    assert sends[0]==first["request"] and result["cumulative_goal_candidates_used"]==27
    assert result["native_goal_ordinal"]==609
    assert runner.read(runtime.ledger)["starting_spend"]==INHERITED
    assert len(runner.read(runtime.ledger)["calls"])==7
    payload=json.loads(sends[0]["messages"][1]["content"])
    assert "legal_evidence_role_catalog" in payload
    assert "previous_complete_source_report" not in payload and "known_complete_source_report_revision" not in payload
    assert not result["human_quality_approved"] and not result["media_authorized"]
    service.assert_no_reentry(runtime,root,sends)


@pytest.mark.parametrize("mode",["transport_unknown","usage_unknown","truncated","missing_tool","missing_scan","mixed_authority","legacy_schema"])
def test_source4_interface_or_schema_failure_stops_without_report_or_format_recovery(tmp_path,monkeypatch,causal_scenario,mode):
    runtime,root,sends,_=replay(tmp_path,monkeypatch,causal_scenario,{("source",1):mode})
    result=runner.run()
    expected="halt_strict_source_diagnostic_contract_rejected" if mode in ("missing_scan","mixed_authority","legacy_schema") else "halt_strict_source_diagnostic_interface_or_unknown"
    assert result["status"]==expected,result
    assert [service.phase(row) for row in sends]==["source"]
    assert result["cumulative_goal_candidates_used"]==27 and not (root/"TEXT_HANDOFF.json").exists()
    service.assert_no_reentry(runtime,root,sends)


@pytest.mark.parametrize("phase,mode",[("source","legal_unknown"),("source","legal_fail"),("commitment","unknown"),("drama","goal_unknown")])
def test_known_valid_content_failure_or_uncertainty_revises_whole_plan28_with_full_native_roles(tmp_path,monkeypatch,causal_scenario,phase,mode):
    runtime,root,sends,_=replay(tmp_path,monkeypatch,causal_scenario,{(phase,1):mode})
    result=runner.run()
    assert result["status"]=="text_ready_for_director",result
    assert result["cumulative_goal_candidates_used"]==28
    planned=next(row for row in sends if service.phase(row)=="goal_plan")
    payload=json.loads(planned["messages"][1]["content"])
    native=runner.read(root/f"goals/{phase}_native_audit_00.json")
    assert payload["revision_diagnostics"]["complete_native_same_source_goal_audit_reports"][f"native_{phase}_audit"]==native
    decision=runner.read(root/f"goals/{phase}_audit_decision_00.json")
    projected=payload["revision_diagnostics"]["complete_same_source_goal_audits"]
    assert projected[-1]["uncertainties"]==decision["uncertainties"] and projected[-1]["findings"]==decision["findings"]
    assert "goal_revision_feedback_evidence_path" not in payload
    assert runtime.summary()["stage_calls"]["goal_audit"]<=6
    service.assert_no_reentry(runtime,root,sends)


def test_six_goal_audits_and_two_new_plans_cannot_transfer_closed_parent_unused1(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,_=replay(tmp_path,monkeypatch,causal_scenario,{("drama",1):"goal_unknown",("drama",2):"goal_unknown"})
    result=runner.run()
    assert result["status"]=="halt_goal_audit_capacity_exhausted"
    assert runtime.summary()["stage_calls"]["goal_audit"]==6
    assert result["cumulative_goal_candidates_used"]==29
    assert [row["label"] for row in runner.read(runtime.ledger)["calls"] if row["label"].startswith("goal_plan_")]==["goal_plan_28","goal_plan_29"]
    assert result["parent_whole_plan_unused_capacity"]==1
    assert result["parent_unused_capacity_stays_in_closed_run"]
    assert not (root/"TEXT_HANDOFF.json").exists()
    service.assert_no_reentry(runtime,root,sends)


def test_true_parent610_guard_seed609_and_exact_new_source4_contract_preview():
    summary=runner.prior_guard();binding,prepared=authorizer.build_binding()
    original=runner.read(ACTUAL_ROOT/"call_610_goal_source_audit_01.json")
    goal=runner.read(ACTUAL_ROOT/"goals/native_01.json")
    payload=json.loads(prepared["request"]["messages"][1]["content"])
    assert prepared["request"]["structured_schema"]["properties"]["schema"]["const"]==legal.VERSION
    assert "legal_evidence_role_catalog" in payload
    assert runner.workflow.evidence_view.reconstruct_goal(payload["native_goal_evidence_view"],expected_native_goal_sha256=runner.digest(goal))==goal
    assert "previous_complete_source_report" not in payload and "known_complete_source_report_revision" not in payload
    assert prepared["request_sha256"]!=original["request_sha256"]
    assert (summary["effective_calls_started"],summary["effective_reported_tokens"],summary["effective_calls_with_known_usage"])==(610,12538733,608)
    assert binding["seed_native_identity"]["ordinal"]==609 and not binding["seed_native_identity"]["semantic_approved"]
    assert binding["parent_goal_candidates_used"]==27 and binding["parent_whole_plan_unused_capacity"]==1
    assert binding["new_cumulative_goal_candidates_maximum"]==29 and not binding["new_format_or_report_recovery_claimed"]
    runner.verify_authorization_request_binding(binding,runner.build_revision_diagnostics(goal),prepared,binding["seed_native_identity"])
    for key in ("first_action_is_source_audit", "source_only_strict_protocol",
                "known_native_goal_audit_content_uncertainty_allows_bounded_plan_revision",
                "source_interface_unknown_or_protocol_failure_stops_new_run",
                "body_requires_all_three_audits_accepted_without_uncertainty",
                "new_format_or_report_recovery_claimed"):
        drift = deepcopy(binding)
        drift[key] = not binding[key]
        with pytest.raises(ValueError, match="continuing authorization"):
            runner.verify_authorization_request_binding(drift, runner.build_revision_diagnostics(goal),
                prepared, binding["seed_native_identity"])
    assert not runner.ROOT.exists() and not runner.CLAIM.exists()


def test_actual609_dense_native_report_and_decision_use_exact_producer_revision_path(tmp_path, monkeypatch):
    from tests.test_creative_goal_legal_usage_source_audit_v4 import add_nonlegal_usage, actual_witness, frame_witness
    inputs = runner.read(ACTUAL_ROOT / "INPUTS.json")
    goal = runner.read(ACTUAL_ROOT / "goals/native_01.json")
    profile = runner.read(runner.PROFILE)
    prepared_source = runner.prepare_source_audit(inputs, profile, goal)
    report = synthetic_source(goal, prepared_source["source_authority_context"], prepared_source["source_context_sha256"])
    for observation in report["source_observations"]:
        if not observation["usages"]:
            add_nonlegal_usage(report, goal, observation["source_ref"])
    ref = next(row["source_ref"] for row in report["source_observations"] if row["source_ref"].startswith("G"))
    source_usages(report, ref).clear()
    native_usage = add_legal_usage(report, goal, ref, relation="application_not_demonstrated", scope="case_application",
        actual_case_conditions=[actual_witness(goal)], interpretation_frame_evidence=[frame_witness(goal)])
    decision = runner.workflow.validate_goal_source_audit(report, goal,
        context_sha256=prepared_source["source_context_sha256"], authority_context=prepared_source["source_authority_context"])
    diagnostic = {"complete_same_source_goal_audits": [decision],
        "complete_native_same_source_goal_audit_reports": {"native_source_audit": report}}
    assert runner.workflow.contexts._measure(diagnostic)["characters"] > 100000
    monkeypatch.setattr(runner, "ROOT", tmp_path / "round23")
    bound = runner.persist_goal_revision_feedback(runner.revision_planning_inputs(inputs, goal, diagnostic), 1)
    path = Path(bound["goal_revision_feedback_evidence_path"])
    assert runner.read(path) == diagnostic
    original_sha = runner.sha_file(path)
    prepared = runner.workflow.prepare_goal_request(bound, profile)
    actual = json.loads(prepared["request"]["messages"][1]["content"])
    assert actual["previous_complete_document"] == goal
    assert actual["reference_fulltext"] == inputs["reference_fulltext"]
    supplied = actual["revision_diagnostics"]
    assert supplied["complete_native_same_source_goal_audit_reports"]["native_source_audit"] == report
    assert supplied["complete_same_source_goal_audits"][0]["uncertainties"] == decision["uncertainties"]
    assert supplied["complete_same_source_goal_audits"][0]["findings"] == decision["findings"]
    finding = supplied["complete_same_source_goal_audits"][0]["uncertainties"][0]
    assert finding["native_usage"] == native_usage
    assert finding["evidence"]["actual_case_conditions"] and finding["evidence"]["interpretation_frame_evidence"]
    assert prepared["manifest"]["payload_identity"]["characters"] <= 100000
    assert len(prepared["manifest"]["revision_feedback_projection"]["source4_compiled_tables_externalized"]) == 2
    assert "goal_revision_feedback_evidence_path" not in actual
    assert runner.sha_file(path) == original_sha


def test_actual_source4_full609_sdk_wire_future_lineage_and_role_schema(tmp_path,monkeypatch):
    import httpx
    from tests import test_creative_deepseek_strict_role_clients_v3 as sdk
    from src.content_factory import creative_flat_lineage_verifier_v5 as lineage
    goal=runner.read(ACTUAL_ROOT/"goals/native_01.json")
    prepared=runner.prepare_source_audit(runner.read(ACTUAL_ROOT/"INPUTS.json"),runner.read(runner.PROFILE),goal)
    request,sent=prepared["request"],[]
    monkeypatch.setattr(runner.strict_clients,"role_config",lambda role:SimpleNamespace(
        model=runner.strict_clients.REVIEW_MODEL,api_key=sdk.KEY,base_url="https://api.deepseek.com/v1"))
    client,evidence,_=sdk.setup(tmp_path,request,
        lambda outgoing:sent.append(outgoing.read()) or httpx.Response(200,content=sdk.reply()))
    sdk.call(client,request,evidence)
    assert len(sent)==1 and len(sent[0])==prepared["strict_wire_measurement"]["utf8_bytes"]<600000
    actual=json.loads(sent[0]);assert actual==prepared["wire"]
    legal_schema=actual["tools"][0]["function"]["parameters"]["properties"]["source_observations"]["items"]["properties"]["usages"]["items"]
    assert "actual_case_conditions" in json.dumps(legal_schema)
    assert "interpretation_frame_evidence" in json.dumps(legal_schema)
    assert "context_evidence" not in json.dumps(legal_schema)
    assert actual["max_tokens"]==24000 and actual["tools"][0]["function"]["strict"] is True
    assert lineage._outbound(lineage.VerificationCycle(),runner.PROJECT,evidence.root,request,evidence.identity_sha256)==actual
