"""Independent known-full-source-report revision, synthetic services only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest
from scripts import run_goal_context_text_production_v22 as runner
from scripts import record_known_source_report_revision_v1 as authorizer
from tests import compact_source_service_helper_v1 as service
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests.test_creative_goal_legal_usage_source_audit_v3 import synthetic_source, add_legal_usage, source_usages
from src.content_factory import creative_goal_legal_usage_source_audit_v3 as legal

INHERITED={"calls_started":607,"reported_tokens":12381139,"calls_with_known_usage":605,
    "pending_ordinals":[70,160],"unknown_token_reservations":93117}
ACTUAL_ROOT=runner.PREFLIGHT_PARENT

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a,**k):raise AssertionError("v22 independent test must not contact providers")
    monkeypatch.setattr(socket.socket,"connect",deny)
    monkeypatch.setattr(socket,"create_connection",deny)


def rejected_source(prepared,goal):
    report=synthetic_source(goal,prepared["source_authority_context"],
        prepared["request"]["structured_schema"]["properties"]["audit_context_sha256"]["const"])
    ref=next(row["source_ref"] for row in report["source_observations"] if any(x["kind"]=="legal_assertion" for x in row["usages"]))
    source_usages(report,ref)[0]["context_evidence"]=[{"source_ref":"G_NOT_AN_ACTUAL_EVENT","quote":"Synthetic invalid condition"}]
    error=next(Draft202012Validator(prepared["request"]["structured_schema"]).iter_errors(report))
    arguments=json.dumps(report,ensure_ascii=False)
    payload={"id":"synthetic-original607","model":runner.strict_clients.REVIEW_MODEL,
        "choices":[{"index":0,"finish_reason":"tool_calls","message":{"role":"assistant","content":None,
            "tool_calls":[{"id":"synthetic-source","type":"function","function":{"name":runner.clients.TOOL_NAME,"arguments":arguments}}]}}],
        "usage":{"prompt_tokens":90,"completion_tokens":10,"total_tokens":100}}
    raw=json.dumps(payload,ensure_ascii=False).encode("utf8")
    receipt={"ordinal":607,"label":"goal_source_audit_00","status":"contract_rejected",
        "request":deepcopy(prepared["request"]),"request_sha256":runner.digest(prepared["request"]),
        "automatic_retry":False,"semantic_approval":False,"output":report,"response_text":arguments,"response_payload":payload,
        "response_metadata":{"http_status_code":200,"finish_reason":"tool_calls","response_body_complete":True,
            "output_mode":"tool_call","raw_body_sha256":hashlib.sha256(raw).hexdigest(),"requested_model":payload["model"],
            "response_model":payload["model"],"response_id":payload["id"],"usage_source":"original_provider_response",**payload["usage"]},
        "validation_error":{"path":list(error.absolute_path),"message":error.message},
        "failure":{"code":"MODULE_SCHEMA_INVALID","category":"state_contract","response_received":True,"automatic_retry":False}}
    return receipt,raw


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
    normal=runner.prepare_source_audit(inputs,profile,goal)
    receipt,raw=rejected_source(normal,goal)
    monkeypatch.setattr(runner,"known_parent_source",lambda:(deepcopy(receipt),raw,{}))
    questions=root.parent/"questions.json"
    runner.write(questions,{"schema":"root_bound_source_report_review_questions/v1","native_goal_sha256":runner.digest(goal),
        "source_context_sha256":receipt["request"]["input_provenance"]["source_context_sha256"],
        "authority_context_sha256":receipt["request"]["input_provenance"]["authority_context_sha256"],
        "original_native_report_sha256":runner.digest(receipt["output"]),"original_receipt_ordinal":607,
        "reviewer_checks":[],"pending_downstream_risks":[]},True)
    monkeypatch.setattr(runner,"REVIEW_QUESTIONS",questions)
    first=runner.prepare_source_revision(inputs,profile,goal)
    feedback=first["source_report_revision_feedback"]
    diagnostic={"native_goal_sha256":runner.digest(goal),"original_receipt_sha256":runner.digest(receipt),
        "source_report_revision_feedback":feedback}
    runner.write(root/"INHERITED_DIAGNOSTICS.json",diagnostic)
    runner.write(root/"FIRST_SOURCE_REQUEST_PREVIEW.json",first,True)
    approval=root.parent/"approval.json";runner.write(approval,{"scope":"offline synthetic only"},True)
    monkeypatch.setattr(runner,"APPROVAL",approval)
    runner.reserve_source_revision_claim(diagnostic,first,runner.sha_file(approval))
    return runtime,root,sends,diagnostic,first


def test_new_complete_source_report_first_then_same_source_double_review(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,diagnostic,first=replay(tmp_path,monkeypatch,causal_scenario)
    result=runner.run()
    assert result["status"]=="text_ready_for_director",result
    assert [service.phase(row) for row in sends[:3]]==["source","commitment","drama"]
    assert sends[0]==first["request"] and result["cumulative_goal_candidates_used"]==26
    assert runner.read(runtime.ledger)["starting_spend"]==INHERITED
    assert len(runner.read(runtime.ledger)["calls"])==7
    payload=json.loads(sends[0]["messages"][1]["content"])
    assert payload[runner.report_revision.ENVELOPE_FIELD]["previous_complete_source_report"]==diagnostic["source_report_revision_feedback"]["previous_complete_source_report"]
    assert not result["human_quality_approved"] and not result["media_authorized"]
    service.assert_no_reentry(runtime,root,sends)


@pytest.mark.parametrize("mode",["transport_unknown","usage_unknown","truncated","missing_tool","missing_scan","mixed_authority","legacy_schema"])
def test_revised_report_interface_or_schema_failure_stops_without_second_report_claim(tmp_path,monkeypatch,causal_scenario,mode):
    runtime,root,sends,diagnostic,first=replay(tmp_path,monkeypatch,causal_scenario,{("source",1):mode})
    claim_path=runner.source_revision_claim_path(diagnostic);before=claim_path.read_bytes()
    result=runner.run()
    expected="halt_strict_source_diagnostic_contract_rejected" if mode in ("missing_scan","mixed_authority","legacy_schema") else "halt_strict_source_diagnostic_interface_or_unknown"
    assert result["status"]==expected,result
    assert [service.phase(row) for row in sends]==["source"]
    assert result["cumulative_goal_candidates_used"]==26 and not (root/"TEXT_HANDOFF.json").exists()
    assert claim_path.read_bytes()==before
    service.assert_no_reentry(runtime,root,sends)


@pytest.mark.parametrize("phase,mode",[("source","legal_unknown"),("source","legal_fail"),("commitment","unknown"),("drama","goal_unknown")])
def test_known_valid_content_failure_or_uncertainty_revises_whole_goal_with_full_native_report(tmp_path,monkeypatch,causal_scenario,phase,mode):
    runtime,root,sends,diagnostic,first=replay(tmp_path,monkeypatch,causal_scenario,{(phase,1):mode})
    result=runner.run()
    assert result["status"]=="text_ready_for_director",result
    assert result["cumulative_goal_candidates_used"]==27
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


def test_persistent_report_claim_cannot_be_reclaimed_after_root_or_grant_changes(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,diagnostic,first=replay(tmp_path,monkeypatch,causal_scenario)
    path=runner.source_revision_claim_path(diagnostic);before=path.read_bytes()
    monkeypatch.setattr(runner,"ROOT",root.parent/"alternate_run")
    monkeypatch.setattr(runner,"GRANT","alternate_grant")
    assert runner.source_revision_claim_path(diagnostic)==path
    with pytest.raises(FileExistsError):runner.reserve_source_revision_claim(diagnostic,first,runner.sha_file(runner.APPROVAL))
    with pytest.raises(ValueError):runner.verify_source_revision_claim(diagnostic,first)
    assert path.read_bytes()==before and sends==[]


def test_six_goal_audits_includes_report_revision_and_stops_before_seventh(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,_,_=replay(tmp_path,monkeypatch,causal_scenario,{("drama",1):"goal_unknown",("drama",2):"goal_unknown"})
    result=runner.run()
    assert result["status"]=="halt_goal_audit_capacity_exhausted"
    assert runtime.summary()["stage_calls"]["goal_audit"]==6
    assert result["cumulative_goal_candidates_used"]==28 and not (root/"TEXT_HANDOFF.json").exists()
    service.assert_no_reentry(runtime,root,sends)


def test_revised_report_cannot_start_a_second_source_report_revision(tmp_path,monkeypatch,causal_scenario):
    _,_,_,_,first=replay(tmp_path,monkeypatch,causal_scenario)
    goal=runner.read(runner.ROOT/"INHERITED_NATIVE_GOAL.json")
    second_receipt,second_raw=rejected_source(first,goal)
    second_receipt["ordinal"]=608
    with pytest.raises(ValueError,match="original source payload"):
        runner.report_revision.verify_known_source_report(second_receipt,raw_response_body=second_raw,
            native_goal=goal,source_payload=json.loads(first["request"]["messages"][1]["content"]))


def test_actual_178_row_native_unknown_and_full_report_fit_whole_plan_revision_budget(tmp_path,monkeypatch):
    receipt=runner.read(ACTUAL_ROOT/"call_607_goal_source_audit_00.json")
    goal=runner.read(ACTUAL_ROOT/"INHERITED_NATIVE_GOAL.json")
    inputs=runner.read(ACTUAL_ROOT/"INPUTS.json")
    report=deepcopy(receipt["output"])
    # Explicit synthetic fixture only, never a new service report or adoption.
    for observation in report["source_observations"]:
        for usage in observation["usages"]:
            if usage.get("kind")=="legal_assertion":
                usage["context_evidence"]=[item for item in usage["context_evidence"] if item["source_ref"]!="G106"]
    usage=next(usage for row in report["source_observations"] for usage in row["usages"] if usage["kind"]=="legal_assertion")
    usage["basis_relation"]="unknown"
    usage["reason"]="Synthetic unresolved interpretation for native whole-plan revision test"
    context=json.loads(receipt["request"]["messages"][1]["content"])
    authority={key:context[key] for key in ("verified_legal_context","origin_catalog")}
    decision=legal.validate_source(report,goal,authority,context_sha256=report["audit_context_sha256"])
    assert decision["valid"] and not decision["accepted"] and decision["uncertainties"]
    questions=runner.read(runner.REVIEW_QUESTIONS)
    diagnostics={"complete_same_source_goal_audits":[decision],
        "complete_native_same_source_goal_audit_reports":{"native_source_audit":report},
        "original_pending_downstream_risks":{"original_native_goal_sha256":runner.digest(goal),
            "current_native_goal_sha256":runner.digest(goal),"risks":questions["pending_downstream_risks"],
            "status":"pending_native_revision_and_current_directory_review",
            "current_native_facts_inferred_from_old_G_ids":False}}
    monkeypatch.setattr(runner,"ROOT",tmp_path/"dense_feedback")
    bound=runner.persist_goal_revision_feedback(runner.revision_planning_inputs(inputs,goal,diagnostics),1)
    planned=runner.workflow.prepare_goal_request(bound,runner.read(runner.PROFILE))
    payload=json.loads(planned["request"]["messages"][1]["content"])
    assert len(report["source_observations"])==178
    assert len(planned["request"]["messages"][1]["content"])<100000
    assert payload["previous_complete_document"]==goal
    assert payload["revision_diagnostics"]["complete_native_same_source_goal_audit_reports"]["native_source_audit"]==report
    assert payload["revision_diagnostics"]["complete_same_source_goal_audits"][0]["uncertainties"]==decision["uncertainties"]
    assert payload["revision_diagnostics"]["original_pending_downstream_risks"]==diagnostics["original_pending_downstream_risks"]
    assert "goal_revision_feedback_evidence_path" not in payload
    assert runner.read(Path(bound["goal_revision_feedback_evidence_path"]))==diagnostics


def test_true_parent_guard_and_actual_revision_preview_preserve_complete607_and_contract():
    summary=runner.prior_guard()
    binding,prepared=authorizer.build_binding()
    receipt=runner.read(ACTUAL_ROOT/"call_607_goal_source_audit_00.json")
    payload=json.loads(prepared["request"]["messages"][1]["content"])
    assert payload[runner.report_revision.ENVELOPE_FIELD]["previous_complete_source_report"]==receipt["output"]
    assert prepared["request"]["structured_schema"]==receipt["request"]["structured_schema"]
    assert prepared["request_sha256"]!=receipt["request_sha256"]
    assert len(payload[runner.report_revision.ENVELOPE_FIELD]["reviewer_checks"])==2
    assert len(payload[runner.report_revision.ENVELOPE_FIELD]["pending_downstream_risks"])==3
    assert len(prepared["source_report_revision_feedback"]["schema_errors"])==2
    assert summary["effective_calls_started"]==607 and summary["effective_reported_tokens"]==12381139
    assert summary["effective_calls_with_known_usage"]==605
    runner.verify_authorization_request_binding(binding,runner.build_revision_diagnostics(runner.read(ACTUAL_ROOT/"INHERITED_NATIVE_GOAL.json")),prepared,binding["seed_native_identity"])
    assert not runner.ROOT.exists() and not runner.CLAIM.exists()


def test_actual_report_revision_sdk_wire_and_future_lineage_mapping(tmp_path,monkeypatch):
    import httpx
    from tests import test_creative_deepseek_strict_role_clients_v2 as sdk
    from src.content_factory import creative_flat_lineage_verifier_v4 as lineage
    goal=runner.read(ACTUAL_ROOT/"INHERITED_NATIVE_GOAL.json")
    prepared=runner.prepare_source_revision(runner.read(ACTUAL_ROOT/"INPUTS.json"),runner.read(runner.PROFILE),goal)
    request,sent=prepared["request"],[]
    monkeypatch.setattr(runner.strict_clients,"role_config",lambda role:SimpleNamespace(
        model=runner.strict_clients.REVIEW_MODEL,api_key=sdk.KEY,base_url="https://api.deepseek.com/v1"))
    client,evidence,_=sdk.setup(tmp_path,request,
        lambda outgoing:sent.append(outgoing.read()) or httpx.Response(200,content=sdk.reply()))
    sdk.call(client,request,evidence)
    assert len(sent)==1 and len(sent[0])==prepared["strict_wire_measurement"]["utf8_bytes"]<600000
    actual=json.loads(sent[0])
    assert actual==prepared["wire"] and actual["max_tokens"]==24000
    assert actual["tools"][0]["function"]["strict"] is True
    assert lineage._outbound(lineage.VerificationCycle(),runner.PROJECT,evidence.root,request,evidence.identity_sha256)==actual
    proof=runner.read(evidence.root/"DEEPSEEK_STRICT_WIRE_PREFLIGHT.json")
    original=runner.read(ACTUAL_ROOT/"call_607_goal_source_audit_00.json")
    assert proof["original_contract_sha256"]==original["response_metadata"]["original_contract_sha256"]
    assert proof["service_schema_sha256"]==original["response_metadata"]["service_schema_sha256"]
    assert proof["SDK_max_retries"]==0 and proof["HTTP_follow_redirects"] is False


def test_three_known_native_uncertain_reports_stop_after_two_whole_plan_revisions(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,_,_=replay(tmp_path,monkeypatch,causal_scenario,
        {("source",1):"legal_unknown",("source",2):"legal_unknown",("source",3):"legal_unknown"})
    result=runner.run()
    assert result["status"]=="halt_goal_content_capacity_exhausted"
    assert result["cumulative_goal_candidates_used"]==28
    assert [service.phase(row) for row in sends]==["source","goal_plan","source","goal_plan","source"]
    assert runtime.summary()["stage_calls"]["goal_audit"]==3
    assert not (root/"TEXT_HANDOFF.json").exists() and not (root/"scripts").exists()
    service.assert_no_reentry(runtime,root,sends)


def test_old_pending_G_references_are_marked_historical_after_native_goal_changes(tmp_path,monkeypatch):
    goal=runner.read(ACTUAL_ROOT/"INHERITED_NATIVE_GOAL.json")
    diagnostic=runner.build_revision_diagnostics(goal)
    monkeypatch.setattr(runner,"ROOT",tmp_path/"historical_risks")
    runner.write(runner.ROOT/"INHERITED_DIAGNOSTICS.json",diagnostic,True)
    revised=deepcopy(goal)
    revised["whole_plan"]["premise"]+=" Synthetic revised complete premise for identity test."
    prepared=runner.prepare_other_goal_audit(runner.read(ACTUAL_ROOT/"INPUTS.json"),runner.read(runner.PROFILE),revised,"drama")
    payload=json.loads(prepared["request"]["messages"][1]["content"])
    pending=payload["pending_downstream_risks"]
    assert pending["original_native_goal_sha256"]==runner.digest(goal)
    assert pending["current_native_goal_sha256"]==runner.digest(revised)
    assert pending["original_G_references_are_historical_when_current_goal_changes"]
    assert not pending["current_native_facts_inferred_from_old_G_ids"]
    assert pending["risks"]==diagnostic["source_report_revision_feedback"]["pending_downstream_risks"]
    assert prepared["request"]["structured_schema"]["properties"]["audit_context_sha256"]["const"]==runner.digest(payload)
    assert prepared["manifest"]["payload_identity"]["sha256"]==runner.digest(payload)
