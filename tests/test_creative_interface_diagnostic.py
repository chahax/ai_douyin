"""Offline invariants for real-service diagnostic runner; no network permitted."""
import importlib.util
import json
from pathlib import Path
import pytest
from src.content_factory.creative_workflow_roles import RoleResult, RoleResponseError

@pytest.fixture
def probe(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/probe_repaired_creative_interface.py"
    spec = importlib.util.spec_from_file_location("diagnostic_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    parent = tmp_path / "parent"
    parent.mkdir()
    (parent / "state.json").write_text('{"calls_started":21}', encoding="utf-8")
    root = tmp_path / "diagnostic"
    root.mkdir()
    monkeypatch.setattr(module, "PARENT", parent)
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "LEDGER", root / "CALL_LEDGER.json")
    monkeypatch.setattr(module, "sources", lambda: {"test-source": "fixed"})
    module.write(root / "CONTEXT.json", {})
    ledger = {
        "schema": "creative_shared_text_diagnostic/v1", "parent_run": str(parent.resolve()),
        "parent_snapshot": module.snapshot(parent), "source_manifest": module.sources(),
        "context_sha256": module.digest({}), "calls": [],
        "parent_budget": {"calls_started":21, "max_calls":24, "reported_tokens":354328, "max_total_tokens":500000},
        "model": {"model":"MiniMax-M3"}, "reference_evidence":[], "limitations":[]
    }
    module.write(module.LEDGER, ledger)
    module.actual_calls = []
    def success(role, messages, **kwargs):
        module.actual_calls.append((role, kwargs))
        return RoleResult(json.dumps({"probe":"repaired_interface_20261003","accepted":True}),
                          {"response_id":"test-22","total_tokens":15,"finish_reason":"tool_calls","output_mode":"tool_call"})
    monkeypatch.setattr(module.CreativeRoleClients, "call", staticmethod(success))
    return module

def test_known_success_and_repeat_never_dispatch_twice(probe):
    before = probe.snapshot(probe.PARENT)
    assert probe.execute("micro")["status"] == "contract_validated"
    assert probe.execute("micro")["status"] == "existing_receipt_no_dispatch"
    assert len(probe.actual_calls) == 1
    ledger = probe.read(probe.LEDGER)
    assert ledger["calls"][0]["ordinal"] == 22
    report = probe.report()
    assert report["effective_calls_started"] == 22 and report["effective_reported_tokens"] == 354343
    assert probe.snapshot(probe.PARENT) == before
    assert probe.actual_calls[0][1]["temperature"] == 0.4
    assert not (probe.ROOT/"DISPATCH.lock").exists()

def test_unknown_keeps_budget_and_blocks_dependents(probe, monkeypatch):
    def unknown(*args, **kwargs):
        probe.actual_calls.append(None)
        # Reservation must already be persisted before the real transport.
        assert probe.read(probe.LEDGER)["calls"][0]["ordinal"] == 22
        raise RuntimeError("timeout with unknown service result")
    monkeypatch.setattr(probe.CreativeRoleClients, "call", staticmethod(unknown))
    assert probe.execute("micro")["status"] == "outcome_unknown"
    assert probe.execute("micro")["status"] == "existing_receipt_no_dispatch"
    with pytest.raises(RuntimeError):
        probe.execute("direction")
    report = probe.report()
    assert report["effective_calls_started"] == 22 and report["unknown_token_reservations"] > 1024
    assert report["diagnostic_reported_tokens"] == 0  # unknown reservation separately retained, never free.
    assert len(probe.actual_calls) == 1

@pytest.mark.parametrize("reason,code", [("length","RESPONSE_TRUNCATED"),("stop","REQUIRED_TOOL_MISSING")])
def test_received_fault_counts_real_usage_without_retry(probe, monkeypatch, reason, code):
    def rejected(*args, **kwargs):
        probe.actual_calls.append(None)
        raise RoleResponseError("rejected", {"response_id":"test-failure","finish_reason":reason,
                                "response_fault_code":code,"total_tokens":23}, response_text="analysis only",
                                response_payload={"choices":[]})
    monkeypatch.setattr(probe.CreativeRoleClients, "call", staticmethod(rejected))
    result=probe.execute("micro")
    assert result["failure"]["code"] == code and result["status"] == "interface_rejected"
    assert probe.report()["diagnostic_reported_tokens"] == 23
    assert probe.execute("micro")["status"] == "existing_receipt_no_dispatch"
    with pytest.raises(RuntimeError):
        probe.execute("direction")
    assert len(probe.actual_calls)==1

def test_type_error_is_contract_fault_not_interface_or_retry(probe, monkeypatch):
    monkeypatch.setattr(probe.CreativeRoleClients, "call", staticmethod(lambda *a, **k: RoleResult(
        '{"probe":"repaired_interface_20261003","accepted":"true"}',
        {"total_tokens":9,"response_id":"types","finish_reason":"tool_calls","output_mode":"tool_call"})))
    result=probe.execute("micro")
    assert result["status"] == "validation_rejected"
    assert result["failure"]["code"] == "MODULE_SCHEMA_INVALID"
    assert result["failure"]["category"] == "state_contract"
    with pytest.raises(RuntimeError):
        probe.execute("direction")

@pytest.mark.parametrize("budget_field,value", [("max_calls",21),("max_total_tokens",354329)])
def test_exhausted_shared_budget_blocks_before_transport(probe,budget_field,value):
    ledger=probe.read(probe.LEDGER)
    ledger["parent_budget"][budget_field]=value
    probe.write(probe.LEDGER,ledger)
    with pytest.raises(RuntimeError,match="budget"):
        probe.execute("micro")
    assert probe.actual_calls==[]
    assert probe.read(probe.LEDGER)["calls"]==[]

@pytest.mark.parametrize("change", ["source","parent","context","orphan","lock"])
def test_binding_or_shared_lock_blocks_before_transport(probe,monkeypatch,change):
    if change=="source":
        monkeypatch.setattr(probe,"sources",lambda: {"changed":"x"})
    elif change=="parent":
        (probe.PARENT/"state.json").write_text('{"calls_started":0}',encoding="utf-8")
    elif change=="context":
        probe.write(probe.ROOT/"CONTEXT.json",{"changed":True})
    elif change=="orphan":
        probe.write(probe.ROOT/"call_099_orphan.json",{"status":"pending_response"})
    else:
        (probe.ROOT/"DISPATCH.lock").write_text("occupied",encoding="utf-8")
    with pytest.raises((RuntimeError,FileExistsError)):
        probe.execute("micro")
    assert probe.actual_calls==[]

def test_local_binding_sha_matches_compiler_algorithm(probe,monkeypatch):
    from src.content_factory.creative_stage_contracts import digest
    fixture=Path(__file__).resolve().parents[1]/"data/qa/creative_response_and_modules_20261003/modular_fixture_input.json"
    data=probe.read(fixture)
    assert probe.digest(data)==digest(data)

def test_workflow_checks_shared_spend_before_provider(probe,monkeypatch):
    from src.content_factory.creative_workflow import CreativeWorkflow
    import src.content_factory.creative_diagnostic_spend as guard
    blocked=guard.SharedDiagnosticSpendError("test unaccounted spend")
    monkeypatch.setattr(guard,"assert_no_unreconciled_diagnostic_spend",lambda run: (_ for _ in ()).throw(blocked))
    workflow=object.__new__(CreativeWorkflow)
    workflow.run_dir=probe.PARENT
    with pytest.raises(guard.SharedDiagnosticSpendError):
        workflow._call_model("writer",[])
    with pytest.raises(guard.SharedDiagnosticSpendError):
        workflow._reserve_tokens("writer",[])
    assert blocked.provider_dispatch_started is False
