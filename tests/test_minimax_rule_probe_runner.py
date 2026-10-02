"""Offline ledger invariants for newly authorized rule experiment."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from scripts import run_minimax_rule_probe as run
from src.content_factory.creative_workflow_roles import RoleResult,RoleResponseError

@pytest.fixture
def runner(tmp_path,monkeypatch):
    parent=tmp_path/"parent";parent.mkdir()
    (parent/"state.json").write_text('{"calls_started":21}',encoding="utf-8")
    root=tmp_path/"diag"/"rule";root.mkdir(parents=True)
    plan=run.read(run.PLAN)
    plan_path=tmp_path/"PLAN.json";run.write(plan_path,plan)
    monkeypatch.setattr(run,"ROOT",root)
    monkeypatch.setattr(run,"LEDGER",root/"CALL_LEDGER.json")
    monkeypatch.setattr(run,"PLAN",plan_path)
    monkeypatch.setattr(run.definition,"PARENT",parent)
    monkeypatch.setattr(run.definition,"DIAGNOSTIC",tmp_path/"diag")
    monkeypatch.setattr(run,"sources",lambda:{"test":"fixed"})
    monkeypatch.setattr(run,"safe_endpoint",lambda:{"model":"MiniMax-M3","base_url":"https://fixture.invalid","provider":"minimax"})
    ledger={"schema":"minimax_authorized_rule_probe_ledger/v1","calls":[],
        "plan_sha256":run.file_hash(plan_path),"source_manifest":run.sources(),
        "provider_config":run.safe_endpoint(),"frozen_parent_snapshot":run.parent_snapshot(),
        "prior_evidence_sha256":{},"starting_effective_budget":{"calls_started":24,"reported_tokens":379026,
                                                               "max_calls":42,"max_total_tokens":500000}}
    run.write(run.LEDGER,ledger)
    counts=[]
    def success(*args,**kwargs):
        ledger=run.read(run.LEDGER)
        assert ledger["calls"][-1]["status"]=="pending_response"
        counts.append(kwargs)
        return RoleResult(json.dumps(run.definition.EXPECTED),{"response_id":f"fixture-{len(counts)}",
            "total_tokens":100,"completion_tokens":30,"finish_reason":"tool_calls","output_mode":"tool_call"},
            {"choices":[{"message":{"content":None,"reasoning_content":None}}]})
    monkeypatch.setattr(run.CreativeRoleClients,"call",staticmethod(success))
    return counts

def test_repeat_key_reads_receipt_without_second_dispatch(runner):
    assert run.execute(1,"A")["status"]=="probe_contract_valid"
    assert run.execute(1,"A")["status"]=="existing_receipt_no_dispatch"
    assert len(runner)==1
    r=run.report()
    assert r["effective_calls_started"]==25 and r["effective_reported_tokens"]==379126
    assert r["raw_success_envelopes_saved"] is True
    assert run.read(run.definition.PARENT/"state.json")=={"calls_started":21}

def test_planned_independent_repeats_share_global_cap_and_unique_ordinals(runner):
    for round_no in (1,2,3):
        for c in "ABCDEF":run.execute(round_no,c)
    assert len(runner)==18
    assert [r["ordinal"] for r in run.read(run.LEDGER)["calls"]]==list(range(25,43))
    result=run.report()
    assert result["effective_calls_started"]==42 and result["remaining_calls"]==0
    assert result["effective_reported_tokens"]==380826
    with pytest.raises(RuntimeError):run.execute(4,"A")
    assert len(runner)==18

def test_unknown_reserves_and_stops_later_cases(runner,monkeypatch):
    def unknown(*a,**k):
        runner.append(None)
        raise RuntimeError("timeout outcome unknown")
    monkeypatch.setattr(run.CreativeRoleClients,"call",staticmethod(unknown))
    assert run.execute(1,"A")["status"]=="outcome_unknown"
    assert run.execute(1,"A")["status"]=="existing_receipt_no_dispatch"
    with pytest.raises(RuntimeError,match="unknown"):run.execute(1,"B")
    assert len(runner)==1
    assert run.report()["unknown_token_reservations"]>1024

def test_known_interface_failure_allows_only_next_planned_independent_case(runner,monkeypatch):
    def rejected(*a,**k):
        runner.append(None)
        raise RoleResponseError("missing tool",{"total_tokens":100,"response_id":f"fixture-{len(runner)}",
            "finish_reason":"stop","response_fault_code":"REQUIRED_TOOL_MISSING"},response_text="fixture")
    monkeypatch.setattr(run.CreativeRoleClients,"call",staticmethod(rejected))
    assert run.execute(1,"A")["status"]=="interface_rejected"
    assert run.execute(1,"A")["status"]=="existing_receipt_no_dispatch"
    assert run.execute(1,"B")["status"]=="interface_rejected"
    assert len(runner)==2 and run.report()["new_reported_tokens"]==200

def test_type_error_never_unwraps_or_initiates_repair(runner,monkeypatch):
    value=deepcopy(run.definition.EXPECTED)
    value["beats"][0]["performance_requirements"]={"item":value["beats"][0]["performance_requirements"]}
    monkeypatch.setattr(run.CreativeRoleClients,"call",staticmethod(lambda *a,**k:RoleResult(json.dumps(value),
        {"total_tokens":50,"response_id":"wrapped","finish_reason":"tool_calls","output_mode":"tool_call"},
        {"choices":[]})))
    result=run.execute(1,"F")
    assert result["status"]=="schema_rejected"
    record=run.read(run.ROOT/run.read(run.LEDGER)["calls"][0]["receipt"])
    assert record["output"]==value
    assert len(run.read(run.LEDGER)["calls"])==1

@pytest.mark.parametrize("kind",["source","parent","plan","orphan","lock"])
def test_source_parent_preview_or_lock_change_blocks_dispatch(runner,monkeypatch,kind):
    if kind=="source":monkeypatch.setattr(run,"sources",lambda:{"changed":"x"})
    elif kind=="parent":(run.definition.PARENT/"state.json").write_text("{}",encoding="utf-8")
    elif kind=="plan":run.write(run.PLAN,{"changed":True})
    elif kind=="orphan":run.write(run.ROOT/"call_999_orphan.json",{"status":"pending_response"})
    else:(run.definition.DIAGNOSTIC/"DISPATCH.lock").write_text("busy",encoding="utf-8")
    with pytest.raises((RuntimeError,FileExistsError)):run.execute(1,"A")
    assert not runner

def test_missing_usage_never_becomes_free_call(runner,monkeypatch):
    monkeypatch.setattr(run.CreativeRoleClients,"call",staticmethod(lambda *a,**k:RoleResult(json.dumps(run.definition.EXPECTED),
        {"finish_reason":"tool_calls","output_mode":"tool_call"},{})))
    run.execute(1,"A")
    with pytest.raises(RuntimeError,match="usage unknown"):run.execute(1,"B")
    assert run.report()["unknown_token_reservations"]>0
