from copy import deepcopy
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import json
import pytest
from scripts import run_fresh_legal_full_flow_v1 as job
from scripts import creative_resume_dispatch_v3 as control


def receipt(status="contract_valid", *, code=None, category=None, output=None):
    return {"status": status, "output": {} if output is None else output,
        "failure": {"code": code, "category": category, "response_received": True},
        "response_metadata": {"http_status_code": 200, "response_body_complete": True,
            "finish_reason": "tool_calls", "total_tokens": 10}}


@pytest.mark.parametrize("code", ["REQUIRED_TOOL_MISSING", "INVALID_JSON_RESPONSE", "TOOL_NAME_MISMATCH"])
def test_interface_faults_are_protocol_not_content_repair(code):
    row = receipt("interface_rejected", code=code, category="response_contract")
    known, outcome, schema = job.classify_receipt(row)
    assert known and outcome == "protocol_rejected"
    assert schema == ("missing" if code == "REQUIRED_TOOL_MISSING" else "rejected")


def test_complete_native_rejection_distinct_from_unknown():
    assert job.classify_receipt(receipt("contract_rejected", category="state_contract")) == (True, "content_rejected", "accepted")
    for key, value in (("http_status_code", 200.0), ("finish_reason", "length"), ("total_tokens", None), ("response_body_complete", False)):
        row = receipt(); row["response_metadata"][key] = value
        assert job.classify_receipt(row) == (False, "unknown", "unknown")


def test_budget_scope_unknown_stage_cannot_dispatch(tmp_path):
    with pytest.raises(ValueError, match="outside frozen"):
        job.call_phase("unplanned_stage", tmp_path)
    assert job.call_phase("fresh_theme_01_format_recovery", tmp_path) == ("theme", 4)
    assert job.call_phase("whole_direction_v4_0", tmp_path) == ("direction", 3)


def test_historical_unknown_reservations_remain_visible():
    rt = SimpleNamespace(inherited={"unknown_token_reservations": 93117, "pending_ordinals": [70, 160]},
        summary=lambda: {"unknown_token_reservations": 500})
    value = job.spend_summary(rt)
    assert value["unknown_token_reservations"] == 93617
    assert value["new_unknown_token_reservations"] == 500
    assert value["historical_pending_ordinals"] == [70, 160]


def test_account_circuit_wait_does_not_reset_or_start_network(tmp_path):
    now = datetime.now(timezone.utc)
    calls = []
    initial = SimpleNamespace(circuit_open_until=(now + timedelta(seconds=5)).isoformat(), lock_expires_at="", lock_owner="", consecutive_failures=4)
    ready = SimpleNamespace(circuit_open_until="", lock_expires_at="", lock_owner="", consecutive_failures=4)
    readings = [initial, ready]
    service = SimpleNamespace(resolve=lambda account: SimpleNamespace(account_uuid="account"),
        bindings=SimpleNamespace(get_runtime_state=lambda account: readings.pop(0)))
    job.wait_for_account_gate(tmp_path, {"files": {}}, service_factory=lambda: service, sleeper=lambda sec: calls.append(sec))
    saved = control.read(tmp_path / "STATE.json")
    assert saved["status"] == "waiting_account_protection" and saved["collection_submitted"] is False
    assert saved["failures_preserved"] == 4 and len(calls) == 1 and calls[0] <= 30


def test_duplicate_run_preserves_active_state(tmp_path, monkeypatch):
    control.write(tmp_path / "JOB_FREEZE.json", {"files": {}}, True)
    control.write(tmp_path / "RUN_CLAIM.json", {"pid": 99}, True)
    control.write(tmp_path / "STATE.json", {"status": "running", "pid": 99})
    with pytest.raises(job.OriginalJobExists):
        job.run(tmp_path)
    assert control.read(tmp_path / "STATE.json") == {"status": "running", "pid": 99}


@pytest.mark.parametrize("fault", [None, "spend", "resource"])
def test_pre_dispatch_code_revision_preserves_original_scope_and_sources(tmp_path, fault):
    code = str((job.PROJECT / "src/content_factory/creative_fresh_legal_text_pipeline_v1.py").resolve())
    resource = str(tmp_path / "RESOURCE_CONFIG.json")
    original = {"files": {code: "a" * 64, resource: "b" * 64}, "inherited": {"calls_started": 520},
        "models": {"writer": "MiniMax-M3"}, "raw_parent_ordinals": [518, 519, 520], "new_generation_calls": 0}
    revised = deepcopy(original); revised["files"][code] = "c" * 64
    if fault == "spend": revised["inherited"]["calls_started"] = 0
    elif fault == "resource": revised["files"][resource] = "d" * 64
    control.write(tmp_path / "JOB_FREEZE.json", original, True)
    control.write(tmp_path / "JOB_FREEZE_v2.json", revised, True)
    control.write(tmp_path / "PRE_DISPATCH_FREEZE_REVISION.json", {
        "original_freeze_sha256": control.sha_file(tmp_path / "JOB_FREEZE.json"),
        "revised_freeze_sha256": control.sha_file(tmp_path / "JOB_FREEZE_v2.json"),
        "changed_paths": sorted(p for p in original["files"] if original["files"][p] != revised["files"][p])}, True)
    if fault:
        with pytest.raises(ValueError): job.load_job_freeze(tmp_path)
    else:
        assert job.load_job_freeze(tmp_path) == revised
        assert control.read(tmp_path / "JOB_FREEZE.json") == original


def test_real_saved_sdk_identity_and_original_response_offline():
    rt = job.parent.runtime()
    ledger = control.read(rt.ledger)
    row = control.read(rt.root / ledger["calls"][0]["receipt"])
    directory = job.verify_receipt_evidence(rt, row, row["request"])
    assert (directory / "response_body.raw").is_file()
    changed = deepcopy(row)
    changed["response_metadata"]["total_tokens"] += 1
    with pytest.raises(ValueError, match="usage mismatch"):
        job.verify_receipt_evidence(rt, changed, row["request"])
