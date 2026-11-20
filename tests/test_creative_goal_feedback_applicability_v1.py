"""Immutable621 regression and negative feedback routing; no clients/claims."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import socket

import pytest

from scripts import creative_resume_dispatch_v3 as io
from src.content_factory import creative_goal_feedback_applicability_v1 as flow

PROJECT=Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*a,**k):raise AssertionError("feedback compilation must not contact providers")
    monkeypatch.setattr(socket.socket,"connect",deny);monkeypatch.setattr(socket,"create_connection",deny)


@pytest.fixture
def original():
    root=PROJECT/"data/production_trials/fresh_source_text_session_20261015"
    return (io.read(root/"round_01/call_621_whole_plan_01.json"),io.read(root/"round_01/FIRST_REQUEST_PREVIEW.json"),
        io.read(root/"round_02/INPUTS.json"),io.read(PROJECT/"config/creative_fresh_source_session_profile_v2.json"))


def test_same_native_v4_history_six_current_eight_and_execution_missing_is_not_obligation(original):
    before=deepcopy(original);result=flow.compile_applicability(*original)
    assert original==before
    assert len(result["historical_diagnostics"]["validation_error"]["detail"]["findings"])==6
    assert len(result["current_structural_revision_obligations"])==8 and not result["blockers"]
    old,current=result["historical_identity"],result["current_identity"]
    assert old["native_contract_version"]==current["native_contract_version"]=="creative_goal_source_v4"
    assert old["structured_schema_sha256"]!=current["structured_schema_sha256"]
    assert old["origin_catalog_sha256"]!=current["origin_catalog_sha256"]
    assert old["workflow_version"]!=current["workflow_version"] and old["ownership_present"] is False and current["ownership_present"] is True
    rows=result["historical_applicability"]
    assert rows[0]["origin_ids"]==["UC_AUTONOMOUS_NATIVE"] and rows[0]["disposition"]=="execution_only_no_narrative_obligation"
    assert [r["disposition"] for r in rows[1:]]==["still_current_structural_obligation"]*5
    assert not any(r.get("missing_origin_ids")==["UC_AUTONOMOUS_NATIVE"] for r in result["current_structural_revision_obligations"])


def test_full_receipt_prepared_and_all_old_diagnostics_are_losslessly_reconstructible(original):
    result=flow.compile_applicability(*original);restored=flow.restore_historical(result)
    assert restored["receipt"]==original[0] and restored["prepared_request"]==original[1]
    assert restored["diagnostics"]=={key:original[0][key] for key in ("failure","validation_error","validation") if key in original[0]}
    altered=deepcopy(result);altered["historical_diagnostics"]["validation_error"]["detail"]["findings"].clear()
    with pytest.raises(flow.ApplicabilityError,match="reconstruction"):flow.restore_historical(altered)


def test_actual_next_request_has_original_native_and_r01_once_and_only_current_obligations(original):
    result=flow.prepare_revision_request(*original);prepared=result["prepared"];payload=json.loads(prepared["request"]["messages"][1]["content"])
    reference=original[2]["reference_fulltext"];native=original[0]["output"]
    def count(value,target):
        if value==target:return 1
        if isinstance(value,dict):return sum(count(child,target) for child in value.values())
        if isinstance(value,list):return sum(count(child,target) for child in value)
        return 0
    assert count(payload,native)==1 and count(payload,reference)==1
    feedback=payload["revision_diagnostics"]
    assert feedback["current_structural_revision_obligations"]==result["artifact"]["current_diagnostics"]["findings"]
    assert len(feedback["current_structural_revision_obligations"])==8
    assert "validation_error" not in feedback and "historical_diagnostics" not in feedback
    assert feedback["historical_feedback_reference"]["historical_findings_are_not_additional_obligations"] is True
    assert "current_structural_revision_obligations" in prepared["request"]["messages"][0]["content"]
    assert prepared["request_sha256"]==io.digest(prepared["request"])
    assert prepared["request"]["input_provenance"]["context_manifest_sha256"]==io.digest(prepared["manifest"])
    assert prepared["manifest"]["payload_identity"]==flow.current_workflow.contexts._measure(payload)
    assert result["dispatch_authorized"] is False and result["artifact"]["semantic_feedback_marked_passed"] is False


@pytest.mark.parametrize("which",["old_code","old_category","current_code","old_family","old_row_shape"])
def test_unknown_diagnostic_retained_and_stops_not_silently_dropped(original,which):
    receipt,prepared,inputs,profile=deepcopy(original);adapter=flow.current_workflow
    if which=="old_code":receipt["validation_error"]["detail"]["findings"][0]["code"]="FUTURE_SEMANTIC_CONDITION_UNKNOWN"
    elif which=="old_category":receipt["failure"]["category"]="future_semantic_category"
    elif which=="old_family":receipt["validation_error"]["code"]="FUTURE_PLANNING_REVIEW"
    elif which=="old_row_shape":receipt["validation_error"]["detail"]["findings"][0]=["future diagnostic shape must be preserved"]
    else:
        prior=adapter
        adapter=SimpleNamespace(**{key:getattr(prior,key) for key in dir(prior) if not key.startswith("__")})
        def diagnose(*a,**k):
            value=prior.diagnose_goal_document(*a,**k);value["findings"][0]["code"]="FUTURE_CURRENT_CATEGORY";return value
        adapter.diagnose_goal_document=diagnose
    result=flow.prepare_revision_request(receipt,prepared,inputs,profile,workflow_adapter=adapter)
    assert result["prepared"] is None and result["artifact"]["blockers"]
    assert flow.restore_historical(result["artifact"])["receipt"]==receipt
    assert result["artifact"]["semantic_feedback_marked_passed"] is False


def test_semantic_uncertainty_kept_even_if_current_structure_were_valid(original):
    receipt,prepared,inputs,profile=deepcopy(original);prior=flow.current_workflow
    adapter=SimpleNamespace(**{key:getattr(prior,key) for key in dir(prior) if not key.startswith("__")})
    def structurally_valid(*a,**k):
        report=prior.diagnose_goal_document(*a,**k);report.update(valid=True,findings=[]);return report
    adapter.diagnose_goal_document=structurally_valid
    semantic={"schema":"future_source_review","valid":True,"accepted":False,"uncertainties":[{"ref":"C0001","status":"unknown","reason":"Mixed legal premise not settled"}]}
    result=flow.prepare_revision_request(receipt,prepared,inputs,profile,workflow_adapter=adapter,semantic_feedback=semantic)
    assert result["artifact"]["retained_semantic_feedback"]==semantic and result["prepared"] is None
    assert any(row["code"]=="SEMANTIC_FEEDBACK_REQUIRES_EXPLICIT_CURRENT_REVIEW" for row in result["artifact"]["blockers"])
    assert not result["artifact"]["semantic_feedback_marked_passed"]


@pytest.mark.parametrize("fault",["usage_unknown","truncated","native_changed","prepared_changed"])
def test_unknown_or_tampered_historical_identity_cannot_become_revision_request(original,fault):
    receipt,prepared,inputs,profile=deepcopy(original)
    if fault=="usage_unknown":receipt["response_metadata"]["total_tokens"]=None
    elif fault=="truncated":receipt["response_metadata"]["finish_reason"]="length"
    elif fault=="native_changed":receipt["output"]["whole_plan"]["premise"]+=" changed"
    else:prepared["request"]["structured_schema"]["description"]="changed"
    with pytest.raises(flow.ApplicabilityError):flow.prepare_revision_request(receipt,prepared,inputs,profile)


def test_source_or_law_change_does_not_reuse_old_cross_contract_route(original):
    receipt,prepared,inputs,profile=deepcopy(original);inputs["verified_legal_context"]["facts"][0]["paraphrase"]+=" changed"
    with pytest.raises(flow.ApplicabilityError,match="source/law/reference"):flow.prepare_revision_request(receipt,prepared,inputs,profile)


def test_same_effective_contract_different_revision_request_not_called_contract_change(original):
    receipt,_,inputs,profile=original;wf=flow.current_workflow
    first=flow._identity(wf.prepare_goal_request(inputs,profile))
    revision={**deepcopy(inputs),"previous_complete_document":deepcopy(receipt["output"]),"revision_diagnostics":{"specific_prior_failure":"different request context"}}
    second=flow._identity(wf.prepare_goal_request(revision,profile))
    assert first["request_sha256"]!=second["request_sha256"] and first["context_manifest_sha256"]!=second["context_manifest_sha256"]
    assert flow.effective_contract_identity(first)==flow.effective_contract_identity(second)


@pytest.mark.parametrize("validation",[None,[],["future nonobject validation"]])
def test_none_validation_is_retained_no_decision_and_nonobject_validation_stops(original,validation):
    receipt,prepared,inputs,profile=deepcopy(original);receipt["validation"]=validation
    result=flow.prepare_revision_request(receipt,prepared,inputs,profile)
    assert result["artifact"]["historical_diagnostics"]["validation"]==validation
    assert flow.restore_historical(result["artifact"])["receipt"]==receipt
    assert (result["prepared"] is not None)==(validation is None)


@pytest.mark.parametrize("fault",["fault_code","response_not_received","automatic_retry","wrong_tool","extra_choice"])
def test_protocol_and_retry_metadata_cannot_be_used_as_structural_revision_feedback(original,fault):
    receipt,prepared,inputs,profile=deepcopy(original)
    if fault=="fault_code":receipt["response_metadata"]["response_fault_code"]="UNEXPECTED_TOOL_CALL"
    elif fault=="response_not_received":receipt["failure"]["response_received"]=False
    elif fault=="automatic_retry":receipt["automatic_retry"]=True
    elif fault=="wrong_tool":receipt["response_payload"]["choices"][0]["message"]["tool_calls"][0]["function"]["name"]="other_tool"
    else:receipt["response_payload"]["choices"].append(deepcopy(receipt["response_payload"]["choices"][0]))
    with pytest.raises(flow.ApplicabilityError):flow.prepare_revision_request(receipt,prepared,inputs,profile)
