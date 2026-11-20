"""Actual stage coordinator with native synthetic service; no paid requests."""
from copy import deepcopy
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest

from scripts import run_goal_context_text_production_v27 as runner
from scripts import record_native618_speech_act_continuation_v1 as authorizer
from src.content_factory.creative_counted_execution_v1 import CountedExecution
from tests import native618_source6_service_helper_v1 as service
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario

REAL_PARENT = runner.PREFLIGHT_PARENT


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a,**k):raise AssertionError("source6 producer tests cannot use sockets")
    monkeypatch.setattr(socket.socket,"connect",deny)
    monkeypatch.setattr(socket,"create_connection",deny)
    # Frozen synthetic fixtures are evaluated at their original sample time.
    # This changes no live production clock or production freshness gate.
    from datetime import datetime, timezone
    from scripts import preview_goal_context_workflow_v2 as preview
    packet=runner.read(preview.SOURCE_ROOT/"source/SOURCE_PACKET.json")
    sample=datetime.fromisoformat(packet["prepared_at"].replace("Z","+00:00"))
    class FixtureClock:
        @staticmethod
        def now(tz=None):return sample.astimezone(tz or timezone.utc)
    monkeypatch.setattr(preview,"datetime",FixtureClock)


def replay(tmp_path,monkeypatch,scenario,modes=None):
    monkeypatch.setattr(runner,"HISTORICAL_PROBE_CLAIM",tmp_path/"probe_claim.json")
    monkeypatch.setattr(runner,"HISTORICAL_PROBE_ROOT",tmp_path/"probe_run")
    runtime,root,sends = service.replay(tmp_path,monkeypatch,scenario,modes)
    ordinary = runner.clients
    monkeypatch.setattr(runner,"clients",SimpleNamespace(TOOL_NAME=ordinary.TOOL_NAME,
        expected_wire_request=lambda req:runner.strict_clients.expected_wire_request(req,source_strict=runner.is_strict_source(req))))
    monkeypatch.setattr(runner,"verify_seed_native",lambda goal:{"ordinal":618,"native_sha256":runner.digest(goal)})
    counter_root = tmp_path/"cadence"
    authorization = tmp_path/"COUNTER_AUTH.txt"
    authorization.write_text("Independent synthetic test only",encoding="utf-8")
    counter = CountedExecution(counter_root)
    counter.initialize(authorization)
    counter.begin_round("test-round","Native source readmission and whole text")
    monkeypatch.setattr(runner,"COUNTED_EXECUTION_ROOT",counter_root)
    monkeypatch.setattr(runner,"COUNTED_ROUND_KEY","test-round")
    runtime.admission=lambda label,request,ledger:runner.assert_counted_dispatch_allowed()
    return runtime,root,sends,counter


def test_reuses_same_native_goal_source_first_then_full_script_and_two_reviews(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,counter = replay(tmp_path,monkeypatch,causal_scenario)
    seed = runner.read(root/"INHERITED_NATIVE_GOAL.json")
    result = runner.run()
    assert result["status"]=="text_ready_for_director",result
    assert [service.phase(req) for req in sends]==["source","commitment","drama","opening_setup","complete_script","semantic","physical"]
    assert result["native_goal_ordinal"]==618 and result["new_whole_goal_calls"]==0
    assert result["cumulative_goal_candidates_used"]==29
    assert runner.read(root/"TEXT_HANDOFF.json")["native_goal"]==seed
    assert runner.read(runtime.ledger)["starting_spend"]==service.INHERITED
    assert (result["spend"]["effective_calls_started"],result["spend"]["effective_reported_tokens"],result["spend"]["effective_calls_with_known_usage"])==(626,12931623,624)
    assert result["spend"]["historical_pending_ordinals"]==[70,160]
    assert result["spend"]["unknown_token_reservations"]==93117
    assert result["old_director_capacity"]=={"used":7,"limit":7,"remaining":0}
    assert not result["human_quality_approved"] and not result["media_authorized"]
    assert counter.read()["active_round"]["key"]=="test-round" and not counter.read()["rounds"]
    service.assert_no_reentry(runtime,root,sends)


@pytest.mark.parametrize("mode",["transport_unknown","usage_unknown","truncated","missing_tool"])
def test_source_unknown_or_incomplete_has_one_send_no_body_or_report_recovery(tmp_path,monkeypatch,causal_scenario,mode):
    runtime,root,sends,_=replay(tmp_path,monkeypatch,causal_scenario,{("source",1):mode})
    result=runner.run()
    assert result["status"]=="halt_goal_audit_interface_or_unknown",result
    assert [service.phase(req) for req in sends]==["source"]
    assert not (root/"TEXT_HANDOFF.json").exists()
    assert result["spend"]["effective_calls_started"]==620
    service.assert_no_reentry(runtime,root,sends)


@pytest.mark.parametrize("mode",["missing_scan","negative_overlap","mixed_authority","legacy_schema"])
def test_source_contract_failure_stops_without_repair_or_plan30(tmp_path,monkeypatch,causal_scenario,mode):
    runtime,root,sends,_=replay(tmp_path,monkeypatch,causal_scenario,{("source",1):mode})
    result=runner.run()
    assert result["status"]=="halt_goal_audit_contract_requires_pipeline_diagnosis",result
    assert [service.phase(req) for req in sends]==["source"]
    assert result["cumulative_goal_candidates_used"]==29 and not (root/"TEXT_HANDOFF.json").exists()
    service.assert_no_reentry(runtime,root,sends)


@pytest.mark.parametrize("phase,mode",[("source","legal_unknown"),("source","legal_fail"),("commitment","unknown"),("drama","goal_unknown")])
def test_semantic_rejection_saved_for_pipeline_diagnosis_without_new_whole_plan(tmp_path,monkeypatch,causal_scenario,phase,mode):
    runtime,root,sends,_=replay(tmp_path,monkeypatch,causal_scenario,{(phase,1):mode})
    result=runner.run()
    assert result["status"]=="halt_goal_content_requires_pipeline_diagnosis",result
    assert result["audit_kind"]==phase and not result["new_whole_goal_dispatched"]
    assert runner.read(root/f"goals/{phase}_native_audit_01.json")
    assert runner.read(root/f"goals/{phase}_audit_decision_01.json")
    assert all(service.phase(req) not in ("goal_plan","complete_script") for req in sends)
    service.assert_no_reentry(runtime,root,sends)


@pytest.mark.parametrize("mode",["transport_unknown","usage_unknown","truncated","missing_tool"])
def test_setup_unknown_stops_after_one_setup_not_body(tmp_path,monkeypatch,causal_scenario,mode):
    runtime,root,sends,_=replay(tmp_path,monkeypatch,causal_scenario,{("opening_setup",1):mode})
    result=runner.run()
    assert result["status"]=="halt_opening_setup_interface_or_unknown",result
    assert [service.phase(req) for req in sends]==["source","commitment","drama","opening_setup"]
    service.assert_no_reentry(runtime,root,sends)


def test_two_known_setup_failures_exhaust_only_setup_capacity(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,_=replay(tmp_path,monkeypatch,causal_scenario,{("opening_setup",1):"null_orientation",("opening_setup",2):"null_orientation"})
    result=runner.run()
    assert result["status"]=="halt_opening_setup_content_capacity_exhausted",result
    assert result["opening_setup_calls"]==2 and result["cumulative_goal_candidates_used"]==29
    assert not any(service.phase(req)=="complete_script" for req in sends)
    second=json.loads([req for req in sends if service.phase(req)=="opening_setup"][1]["messages"][1]["content"])
    assert second["previous_opening_setup"]==runner.read(root/"setups/native_01.json")
    service.assert_no_reentry(runtime,root,sends)


def test_three_native_bodies_six_same_source_reviews_bound_content_revisions(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,_=replay(tmp_path,monkeypatch,causal_scenario,{("physical",1):"fail",("physical",2):"fail"})
    result=runner.run()
    assert result["status"]=="text_ready_for_director",result
    assert result["spend"]["stage_calls"]=={"goal_plan":1,"goal_audit":3,"complete_script":3,"full_review":6}
    assert [runner.read(root/f"scripts/version_{i:02}/NATIVE_SCRIPT.json")["title"] for i in (1,2,3)]==["合成完整正文1","合成完整正文2","合成完整正文3"]
    assert not result["human_quality_approved"]
    service.assert_no_reentry(runtime,root,sends)


def test_counter_stopped_before_run_blocks_without_runclaim_or_sends(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,counter=replay(tmp_path,monkeypatch,causal_scenario)
    evidence=tmp_path/"STOP.txt";evidence.write_text("stop proof",encoding="utf-8")
    counter.stop("ten_reviews_completed",evidence)
    with pytest.raises(ValueError,match="execution stopped"):runner.run()
    assert not sends and not (root/"RUN_CLAIM.json").exists() and not runner.read(runtime.ledger)["calls"]


def test_counter_stop_after_first_send_blocks_next_send_preserving_first_receipt(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,counter=replay(tmp_path,monkeypatch,causal_scenario)
    original=runner.invoke
    def stopping_invoke(*args,**kwargs):
        receipt=original(*args,**kwargs)
        evidence=root/"STOP_AFTER_SOURCE.txt";evidence.write_text("stop after source",encoding="utf-8")
        counter.stop("ten_reviews_completed",evidence)
        return receipt
    monkeypatch.setattr(runner,"invoke",stopping_invoke)
    with pytest.raises(ValueError,match="execution stopped"):runner.run()
    assert [service.phase(req) for req in sends]==["source"]
    assert len(runner.read(runtime.ledger)["calls"])==1
    assert not (root/"requests/goal_commitment_audit_01.json").exists()


def test_changed_first_request_preview_rejected_before_source_dispatch(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,_=replay(tmp_path,monkeypatch,causal_scenario)
    value=runner.read(root/"FIRST_NATIVE_SOURCE_REQUEST_PREVIEW.json")
    value["request"]["messages"][1]["content"]+=" changed"
    runner.write(root/"FIRST_NATIVE_SOURCE_REQUEST_PREVIEW.json",value)
    with pytest.raises(ValueError,match="immutable preview"):runner.run()
    assert not sends and not runner.read(runtime.ledger)["calls"]


@pytest.mark.parametrize("marker",["claim","ledger"])
def test_probe_anchor_exists_blocks_old619_producer_without_new_requests(tmp_path,monkeypatch,causal_scenario,marker):
    runtime,root,sends,_=replay(tmp_path,monkeypatch,causal_scenario)
    path=runner.HISTORICAL_PROBE_CLAIM if marker=="claim" else runner.HISTORICAL_PROBE_ROOT/"CALL_LEDGER.json"
    runner.write(path,{"status":"pending_or_known"})
    with pytest.raises(ValueError,match="anchor is stale"):runner.run()
    assert not sends and not (root/"RUN_CLAIM.json").exists() and not runner.read(runtime.ledger)["calls"]


def test_counter_stop_between_dag_claim_and_runtime_admission_prevents_provider(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends,counter=replay(tmp_path,monkeypatch,causal_scenario)
    original_claim=runner.tasks.TaskStore.claim
    def stopped_claim(*args,**kwargs):
        attempt=original_claim(*args,**kwargs)
        evidence=root/"STOP_IN_CLAIM.txt";evidence.write_text("stop inside task claim",encoding="utf-8")
        counter.stop("ten_reviews_completed",evidence)
        return attempt
    monkeypatch.setattr(runner.tasks.TaskStore,"claim",stopped_claim)
    with pytest.raises(ValueError,match="execution stopped"):runner.run()
    assert not sends and not runner.read(runtime.ledger)["calls"]


def test_actual_parent619_first_source_preview_preserves_native618_and_no_provider_or_claim():
    seed=runner.read(REAL_PARENT/"goals/native_01.json")
    identity=runner.verify_seed_native(seed)
    prepared=runner.prepare_source_audit(runner.read(REAL_PARENT/"INPUTS.json"),runner.read(runner.PROFILE),seed)
    assert identity["ordinal"]==618 and identity["native_goal_locally_patched"] is False
    payload=json.loads(prepared["request"]["messages"][1]["content"])
    evidence=runner.workflow.source_audit.build_evidence_catalog(seed)
    assert "native_goal_evidence_view" in payload
    assert prepared["request"]["structured_schema"]["properties"]["goal_sha256"]["const"]==runner.digest(seed)
    assert set(prepared["request"]["structured_schema"]["properties"]["speech_act_by_ref"]["properties"])==set(evidence)
    assert prepared["wire"]["tools"][0]["function"]["strict"] is True
    assert prepared["strict_wire_measurement"]["utf8_bytes"]<=600000
    assert not runner.ROOT.exists() and not runner.CLAIM.exists()


def test_actual_current_parent_source_gate_is_not_changed_to_sample_time():
    # Current real clock must continue to block an expired production source.
    from scripts import run_m31_flash_script_test_v1 as source_parent
    with pytest.raises(ValueError,match="opportunity_outside_validity"):
        source_parent.source_gate()
