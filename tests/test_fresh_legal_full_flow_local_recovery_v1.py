from copy import deepcopy
from types import SimpleNamespace
import pytest

from test_fresh_legal_full_flow_resume_v1 import prepared_inputs
from scripts import run_fresh_legal_full_flow_local_recovery_v1 as recovery

control = recovery.control


@pytest.fixture
def local_inputs(prepared_inputs, monkeypatch):
    p = prepared_inputs
    monkeypatch.setattr(recovery, "PROJECT", recovery.resume.PROJECT)
    recovery.resume.prepare(p.root, process_alive=lambda _: False)
    old = {"schema": "fresh_legal_known_human_resume_claim/v1", "started_at_utc": "2026-10-12T10:03:00+00:00",
        "pid": 114, "resume_freeze_sha256": control.sha_file(p.root / recovery.resume.FREEZE_NAME),
        "original_run_claim_sha256": control.sha_file(p.root / "RUN_CLAIM.json"),
        "original_grant_id": recovery.original.GRANT_ID,
        "login_confirmation_sha256": control.sha_file(p.root / recovery.resume.CONFIRMATION_NAME),
        "original_request_redispatch": False, "automatic_restart": False, "budget_reset": False}
    control.write(p.root / recovery.resume.CLAIM_NAME, old, True)
    control.write(p.root / "RESUME_COLLECTION_PROCESS_RESULT_01.json", {"exit_code": 1,
        "finished_at_utc": "2026-10-12T10:03:00.700000+00:00",
        "original_request_redispatch": False, "automatic_retry": False}, True)
    (p.root / "RESUME_COLLECTION.stdout.log").write_text("", encoding="utf-8")
    (p.root / "RESUME_COLLECTION.stderr.log").write_text(
        'Traceback (most recent call last):\n  File "' + str(recovery.PROJECT / "scripts/run_fresh_legal_collection_resume_v1.py")
        + '", line 100, in verify_continuation_parent\nResultBindingError: ACTIVE_PARENT_CONTINUATION_CLAIM_REQUIRED\n', encoding="utf-8")
    control.write(p.root / "ORIGINAL_STOP_STATE_BEFORE_LOCAL_RECONCILIATION_01.json",
        {"status": "stopped_exception", "exception_type": "FileNotFoundError"}, True)
    rec = {"schema": "fresh_legal_local_dispatch_failure_reconciliation/v1",
        "status": "known_local_prerequisite_rejected", "failure_code": "ACTIVE_PARENT_CONTINUATION_CLAIM_REQUIRED",
        "stage": "collector_parent_binding_before_directory_and_claim", "child_exit_code": 1,
        "original_worker_pid": 114, "original_worker_running": False, "collection_submitted": False,
        "browser_started": False, "result_unknown": False, "old_budget_reset": False,
        "original_claims_preserved": True, "new_model_calls": 0, "new_media_calls": 0, "new_collected_videos": 0,
        "evidence_sha256": {str((p.root / name).resolve()): control.sha_file(p.root / name) for name in recovery._PROOF[:5]}}
    control.write(p.root / "LOCAL_DISPATCH_FAILURE_RECONCILIATION_01.json", rec, True)
    for name in recovery._CODE:
        target = recovery.PROJECT / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# new code\n", encoding="utf-8")
    interpreter = recovery.PROJECT / ".venv/Scripts/python.exe"
    interpreter.parent.mkdir(parents=True, exist_ok=True)
    interpreter.write_bytes(b"fixture interpreter bytes")
    symbols = {"allowed_python_executables": [str(interpreter)],
        "recovery_worker_script": str(recovery.PROJECT / recovery._CODE[0])}
    monkeypatch.setattr(recovery, "execution_resource_symbols", lambda: deepcopy(symbols))
    return p


def test_local_prepare_preserves_both_old_claims_and_limits(local_inputs):
    p = local_inputs
    before = {f.name: f.read_bytes() for f in p.root.iterdir() if f.is_file()}
    freeze = recovery.prepare(p.root, process_alive=lambda _: False)
    assert freeze["inherited"] == p.base["inherited"]
    assert freeze["models"] == p.base["models"]
    assert freeze["new_generation_calls"] == 0 and freeze["budget_reset"] is False
    assert freeze["local_pre_dispatch_repair_only"] is True
    for name, raw in before.items():
        assert (p.root / name).read_bytes() == raw
    assert not (p.root / recovery.CLAIM_NAME).exists()
    assert recovery.verify_local_recovery_freeze(p.root) == freeze
    assert recovery.prepare(p.root, process_alive=lambda _: False) == freeze


@pytest.mark.parametrize("name", ["CALL_LEDGER.json", "TEXT_STATE.json", "call_521_lost.json", "source", "TASKS.sqlite3"])
def test_model_or_source_evidence_stops_local_recovery(local_inputs, name):
    (local_inputs.root / name).write_text("original", encoding="utf-8")
    with pytest.raises(ValueError, match="execution exists"):
        recovery.prepare(local_inputs.root, process_alive=lambda _: False)
    assert (local_inputs.root / name).read_text(encoding="utf-8") == "original"


def test_collection_directory_even_empty_stops_before_recovery(local_inputs):
    (local_inputs.root / recovery.resume.COLLECTION_NAME).mkdir()
    with pytest.raises(ValueError, match="collection already"):
        recovery.prepare(local_inputs.root, process_alive=lambda _: False)


def test_previous_worker_alive_stops_local_recovery(local_inputs):
    with pytest.raises(ValueError, match="worker still active"):
        recovery.prepare(local_inputs.root, process_alive=lambda pid: pid == 114)


@pytest.mark.parametrize("field,value", [("status", "result_unknown"), ("failure_code", "HTTP_502"),
    ("stage", "after_browser_started"), ("collection_submitted", True), ("browser_started", True),
    ("result_unknown", True), ("old_budget_reset", True), ("new_model_calls", 1), ("new_media_calls", 1)])
def test_only_exact_zero_dispatch_failure_can_be_repaired(local_inputs, field, value):
    path = local_inputs.root / "LOCAL_DISPATCH_FAILURE_RECONCILIATION_01.json"
    rec = control.read(path)
    rec[field] = value
    control.write(path, rec)
    with pytest.raises(ValueError):
        recovery.prepare(local_inputs.root, process_alive=lambda _: False)
    assert not (local_inputs.root / recovery.FREEZE_NAME).exists()


@pytest.mark.parametrize("stream,value", [("stdout", "remote result"), ("stderr", "unknown error"),
    ("stderr", "Traceback (most recent call last):\nResultBindingError: ACTIVE_PARENT_CONTINUATION_CLAIM_REQUIRED\n"),
    ("stderr", "Traceback (most recent call last):\nTraceback (most recent call last):\nResultBindingError: ACTIVE_PARENT_CONTINUATION_CLAIM_REQUIRED")])
def test_booleans_cannot_override_actual_process_failure_proof(local_inputs, stream, value):
    (local_inputs.root / ("RESUME_COLLECTION." + stream + ".log")).write_text(value, encoding="utf-8")
    with pytest.raises(ValueError, match="local parent rejection evidence"):
        recovery.prepare(local_inputs.root, process_alive=lambda _: False)


@pytest.mark.parametrize("field,value", [("exit_code", 0), ("exit_code", True), ("automatic_retry", True),
    ("finished_at_utc", "2026-10-12T10:05:00+00:00")])
def test_exit_and_time_proof_are_bound(local_inputs, field, value):
    path = local_inputs.root / "RESUME_COLLECTION_PROCESS_RESULT_01.json"
    result = control.read(path)
    result[field] = value
    control.write(path, result)
    with pytest.raises(ValueError):
        recovery.prepare(local_inputs.root, process_alive=lambda _: False)


@pytest.mark.parametrize("member", ["code", "old_claim", "stderr", "local_reconciliation"])
def test_added_freeze_requires_all_members(local_inputs, member):
    root = local_inputs.root
    freeze = recovery.prepare(root, process_alive=lambda _: False)
    paths = {"code": recovery.PROJECT / recovery._CODE[1], "old_claim": root / recovery.resume.CLAIM_NAME,
        "stderr": root / "RESUME_COLLECTION.stderr.log", "local_reconciliation": root / "LOCAL_DISPATCH_FAILURE_RECONCILIATION_01.json"}
    freeze["files"].pop(str(paths[member].resolve()))
    control.write(root / recovery.FREEZE_NAME, freeze)
    with pytest.raises(ValueError, match="local additive freeze"):
        recovery.verify_local_recovery_freeze(root)


def test_external_execution_binary_cannot_change_after_freeze(local_inputs):
    freeze = recovery.prepare(local_inputs.root, process_alive=lambda _: False)
    from pathlib import Path
    Path(freeze["execution_resource_symbols"]["allowed_python_executables"][0]).write_bytes(b"different")
    with pytest.raises(ValueError, match="FROZEN_FILE_CHANGED"):
        recovery.verify_local_recovery_freeze(local_inputs.root)


def test_scope_and_spend_cannot_be_changed_in_local_freeze(local_inputs):
    root = local_inputs.root
    freeze = recovery.prepare(root, process_alive=lambda _: False)
    freeze["inherited"]["calls_started"] = 0
    control.write(root / recovery.FREEZE_NAME, freeze)
    with pytest.raises(ValueError, match="local additive freeze"):
        recovery.verify_local_recovery_freeze(root)


def test_duplicate_local_claim_keeps_active_state(local_inputs, monkeypatch):
    root = local_inputs.root
    recovery.prepare(root, process_alive=lambda _: False)
    control.write(root / recovery.CLAIM_NAME, {"pid": 999}, True)
    control.write(root / "STATE.json", {"status": "running", "pid": 999})
    monkeypatch.setattr(recovery.subprocess, "run", lambda *a, **k: pytest.fail("no duplicate dispatch"))
    for operation in (recovery.prepare, recovery.run):
        with pytest.raises(recovery.LocalDispatchRecoveryExists):
            operation(root, process_alive=lambda _: False)
    assert control.read(root / "STATE.json") == {"status": "running", "pid": 999}


@pytest.mark.parametrize("status", ["human_required", "result_unknown"])
def test_first_real_collection_failure_stops_without_model_calls(local_inputs, monkeypatch, status):
    root = local_inputs.root
    recovery.prepare(root, process_alive=lambda _: False)
    monkeypatch.setattr(recovery.original, "wait_for_account_gate", lambda *a, **k: None)
    calls = []
    def fake_child(argv, **kwargs):
        calls.append(argv)
        collection = root / recovery.resume.COLLECTION_NAME
        collection.mkdir()
        control.write(collection / "COLLECTION_RESULT.json", {"status": status, "exit_code": 1}, True)
        return SimpleNamespace(stdout="", stderr="", returncode=1)
    monkeypatch.setattr(recovery.subprocess, "run", fake_child)
    monkeypatch.setattr(recovery, "run_text_and_production", lambda *a: pytest.fail("failed source cannot dispatch"))
    recovery.run(root, process_alive=lambda _: False)
    assert len(calls) == 1 and recovery._CODE[1] in calls[0]
    assert recovery.verify_local_recovery_freeze(root)["inherited"]["calls_started"] == 520
    assert control.read(root / "STATE.json")["new_model_calls"] == 0
    with pytest.raises(recovery.LocalDispatchRecoveryExists):
        recovery.run(root, process_alive=lambda _: False)
    assert len(calls) == 1


def test_runtime_subclass_keeps_both_frozen_guards(local_inputs, monkeypatch):
    seen = []
    monkeypatch.setattr(recovery, "verify_local_recovery_freeze", lambda root: seen.append("local"))
    runtime = recovery.LocalRecoveryRuntime(recovery.PROJECT, local_inputs.root, [], local_inputs.base["inherited"],
        local_inputs.base["models"], inherited_guard=lambda: seen.append("original"))
    runtime.inherited_guard()
    assert seen == ["original", "local"]


def test_actual_saved_windows_guard_smoke_proved_one_proxy_chain():
    from pathlib import Path
    actual = Path(__file__).resolve().parents[1] / "data/qa/creative_studio_production_preflight_20261012/LOCAL_RECOVERY_WINDOWS_PROCESS_SMOKE_r1.json"
    value = control.read(actual)
    assert value["exit_code"] == 0 and value["network_calls"] == 0 and value["browser_started"] is False
    assert value["model_calls"] == 0 and value["production_claims_created"] == 0
    child = control.strict_json(value["child_stdout"])
    proof = child["verified_ancestry"]
    assert proof["authorized_worker_pid"] == value["worker_pid"]
    assert child["direct_parent_pid"] != value["worker_pid"]  # real venv shim, not a mock direct parent
