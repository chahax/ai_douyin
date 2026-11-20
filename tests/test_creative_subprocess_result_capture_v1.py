from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import subprocess

import pytest

from src.content_factory import creative_subprocess_result_capture_v1 as capture

PROJECT = Path(__file__).resolve().parents[1]


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")


@pytest.fixture
def durable(tmp_path):
    root = tmp_path
    identity = {"account_key": "account01", "account_uuid": "account:legal", "profile_version": 1,
        "workflow_run_id": "research:" + "b" * 32}
    payload = {**identity, "status": "blocked", "stopped_reason": "insufficient_research_sample",
        "unique_videos": 90, "sample_gate": {"passed": False, "total_likes": 465497}}
    authority = root / "AUTHORITY.json"
    save(authority, payload)
    wrapper = {"status": "blocked", "exit_code": 1, "result": payload,
        "known_research_result": True, "authoritative_full_result_equal": True,
        "authoritative_result_sha256": hashlib.sha256(authority.read_bytes()).hexdigest(),
        "original_request_redispatched": False, "automatic_retry": False,
        "new_model_calls": 0, "new_media_calls": 0, "eligible_for_source_validation": False}
    output = root / "DURABLE.json"
    save(output, wrapper)
    live = root / "IDENTITY.json"
    live_identity = {"healthy": True, "account_key": "account01", "profile_version": 1, "actual_public_id": "legal-account"}
    save(live, live_identity)
    return SimpleNamespace(root=root, output=output, authority=authority, wrapper=wrapper,
        payload=payload, identity=identity, live=live, live_identity=live_identity)


def reconcile(p, *, exit_code=1):
    return capture.reconcile_durable_result(observed_exit_code=exit_code, durable_result_path=p.output,
        authoritative_result_path=p.authority, expected_identity=p.identity,
        identity_evidence_path=p.live, expected_evidence_identity=p.live_identity)


def test_cp936_console_capture_preserves_bytes_and_uses_no_text_thread_decoder(tmp_path):
    raw = "分析已阻止：点赞数还不足".encode("cp936")
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 1, stdout=raw, stderr=b"")
    result = capture.run_binary_subprocess(["python", "collector.py"], cwd=tmp_path,
        artifact_root=tmp_path / "capture", dispatch_identity={"source_sha256": "a" * 64}, runner=run)
    assert len(calls) == 1
    assert calls[0][1]["text"] is False and calls[0][1]["shell"] is False
    assert "encoding" not in calls[0][1]
    assert (tmp_path / "capture/PROCESS.stdout.raw").read_bytes() == raw
    assert result["observed_exit_code"] == 1 and result["process_completed"] is True
    assert result["streams"]["stdout"]["display_encoding"] == "gb18030"
    assert (tmp_path / "capture/PROCESS.stdout.display.log").read_text(encoding="utf-8") == "分析已阻止：点赞数还不足"


def test_actual_windows_child_cp936_bytes_are_complete(tmp_path):
    raw = "账号相关度预检：分析已阻止".encode("cp936")
    code = "import sys; sys.stdout.buffer.write(bytes.fromhex('" + raw.hex() + "')); sys.exit(1)"
    result = capture.run_binary_subprocess([str(PROJECT / ".venv/Scripts/python.exe"), "-c", code],
        cwd=PROJECT, artifact_root=tmp_path / "actual_capture", dispatch_identity={"purpose": "local_no_network_smoke"})
    assert result["process_completed"] is True and result["observed_exit_code"] == 1
    assert (tmp_path / "actual_capture/PROCESS.stdout.raw").read_bytes() == raw
    assert result["streams"]["stdout"]["sha256"] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("raw,encoding,lossless", [(b"ASCII", "utf-8-sig", True),
    ("登录成功".encode("utf-8"), "utf-8-sig", True), ("登录成功".encode("cp936"), "gb18030", True),
    (b"\xff", "utf-8-replacement", False)])
def test_diagnostic_decode_never_claims_structured_acceptance(raw, encoding, lossless):
    decoded = capture.decode_diagnostic_log(raw)
    assert decoded["encoding"] == encoding and decoded["lossless_decode"] is lossless
    assert decoded["raw_sha256"] == hashlib.sha256(raw).hexdigest()
    assert decoded["structured_result_source"] is False


def test_duplicate_capture_directory_never_reexecutes(tmp_path):
    calls = []
    def run(argv, **kwargs):
        calls.append(1)
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")
    args = dict(cwd=tmp_path, artifact_root=tmp_path / "capture", dispatch_identity={"source": "same"}, runner=run)
    capture.run_binary_subprocess(["python", "once.py"], **args)
    before = (tmp_path / "capture/PROCESS_CAPTURE_RESULT.json").read_bytes()
    with pytest.raises(capture.ProcessResultError, match="NO_REDISPATCH"):
        capture.run_binary_subprocess(["python", "once.py"], **args)
    assert calls == [1]
    assert (tmp_path / "capture/PROCESS_CAPTURE_RESULT.json").read_bytes() == before


def test_timeout_keeps_partial_original_bytes_and_never_retries(tmp_path):
    calls = []
    partial = "采集中".encode("cp936")
    def run(argv, **kwargs):
        calls.append(1)
        raise subprocess.TimeoutExpired(argv, 1, output=partial, stderr=b"partial")
    with pytest.raises(capture.ProcessResultError, match="PROCESS_COMPLETION_UNKNOWN"):
        capture.run_binary_subprocess(["python", "collector.py"], cwd=tmp_path,
            artifact_root=tmp_path / "capture", dispatch_identity={"source": "same"}, runner=run)
    result = json.loads((tmp_path / "capture/PROCESS_CAPTURE_RESULT.json").read_text(encoding="utf-8"))
    assert calls == [1] and result["process_completed"] is False and result["observed_exit_code"] is None
    assert (tmp_path / "capture/PROCESS.stdout.raw").read_bytes() == partial
    assert result["streams"]["stdout"]["complete"] is False and result["automatic_retry"] is False


@pytest.mark.parametrize("exit_code,stdout,stderr", [(True, b"", b""), (None, b"", b""),
    (1, None, b""), (1, "decoded stdout", b""), (1, b"", None)])
def test_incorrect_capture_types_are_never_complete(tmp_path, exit_code, stdout, stderr):
    def run(argv, **kwargs): return SimpleNamespace(returncode=exit_code, stdout=stdout, stderr=stderr)
    with pytest.raises(capture.ProcessResultError, match="BINARY_PROCESS_RESULT_REQUIRED"):
        capture.run_binary_subprocess(["python"], cwd=tmp_path, artifact_root=tmp_path / "capture",
            dispatch_identity={"source": "same"}, runner=run)
    result = json.loads((tmp_path / "capture/PROCESS_CAPTURE_RESULT.json").read_text(encoding="utf-8"))
    assert result["process_completed"] is False


def test_known_blocked_result_remains_stop_despite_console_saying_completed(durable):
    (durable.root / "stdout.log").write_text('{"status":"completed","passed":true}', encoding="utf-8")
    result = reconcile(durable)
    assert result["status"] == "known_collection_stop" and result["observed_collection_status"] == "blocked"
    assert result["reason"] == "insufficient_research_sample"
    assert result["may_run_source_validation"] is False and result["creative_source_approved"] is False
    assert result["creative_quality_passed"] is False and result["automatic_redispatch"] is False
    assert result["result"]["unique_videos"] == 90


@pytest.mark.parametrize("exit_code", [None, True, 0, 2, "1"])
def test_unknown_wrong_or_typed_exit_is_rejected(durable, exit_code):
    with pytest.raises(capture.ProcessResultError): reconcile(durable, exit_code=exit_code)


@pytest.mark.parametrize("field,value", [("status", "result_unknown"), ("known_research_result", False),
    ("authoritative_full_result_equal", False), ("automatic_retry", True), ("original_request_redispatched", True),
    ("new_model_calls", 1), ("new_media_calls", True), ("exit_code", True), ("eligible_for_source_validation", True)])
def test_unknown_partial_or_promoted_durable_envelope_rejected(durable, field, value):
    wrapper = deepcopy(durable.wrapper)
    wrapper[field] = value
    save(durable.output, wrapper)
    with pytest.raises(capture.ProcessResultError): reconcile(durable)


@pytest.mark.parametrize("field,value", [("account_uuid", "different"), ("account_key", "other"),
    ("profile_version", True), ("profile_version", "1"), ("workflow_run_id", "research:other")])
def test_native_identity_and_types_cannot_change(durable, field, value):
    wrapper = deepcopy(durable.wrapper)
    wrapper["result"][field] = value
    save(durable.output, wrapper)
    with pytest.raises(capture.ProcessResultError, match="IDENTITY_MISMATCH"): reconcile(durable)


def test_live_identity_evidence_must_match(durable):
    live = deepcopy(durable.live_identity)
    live["actual_public_id"] = "other"
    save(durable.live, live)
    with pytest.raises(capture.ProcessResultError, match="LIVE_IDENTITY"): reconcile(durable)


def test_missing_durable_result_is_unknown_and_rejected(durable):
    missing = durable.root / "missing-result.json"
    with pytest.raises(capture.ProcessResultError, match="DURABLE_EVIDENCE_UNAVAILABLE"):
        capture.reconcile_durable_result(observed_exit_code=1, durable_result_path=missing,
            authoritative_result_path=durable.authority, expected_identity=durable.identity)


def test_missing_subprocess_result_type_is_rejected(tmp_path):
    with pytest.raises(capture.ProcessResultError, match="BINARY_PROCESS_RESULT_REQUIRED"):
        capture.run_binary_subprocess(["python"], cwd=tmp_path, artifact_root=tmp_path / "capture",
            dispatch_identity={"source": "same"}, runner=lambda *a, **k: None)


def test_authoritative_full_result_and_hash_are_required(durable):
    altered = deepcopy(durable.payload)
    altered["unique_videos"] = 900
    save(durable.authority, altered)
    with pytest.raises(capture.ProcessResultError, match="AUTHORITATIVE_COMPLETE"): reconcile(durable)


@pytest.mark.parametrize("raw", [b'{"status":"blocked"', b'{"status":"blocked","status":"completed"}',
    b'{"status":NaN}', b'{"value":1e400}', b'[]', b'\xff'])
def test_truncated_duplicate_nonfinite_or_nonobject_durable_rejected(durable, raw):
    durable.output.write_bytes(raw)
    with pytest.raises(capture.ProcessResultError): reconcile(durable)


def test_completed_envelope_does_not_grant_creative_acceptance(durable):
    payload = deepcopy(durable.payload)
    payload.update(status="completed", stopped_reason="")
    save(durable.authority, payload)
    wrapper = deepcopy(durable.wrapper)
    wrapper.update(status="completed", exit_code=0, result=payload,
        authoritative_result_sha256=hashlib.sha256(durable.authority.read_bytes()).hexdigest())
    save(durable.output, wrapper)
    result = reconcile(durable, exit_code=0)
    assert result["status"] == "durable_result_known" and result["may_run_source_validation"] is True
    assert result["creative_source_approved"] is False and result["creative_quality_passed"] is False


def test_actual_saved_collection_is_read_only_and_remains_blocked():
    root = PROJECT / "data/production_trials/fresh_legal_full_flow_20261012/round_01/collection_live_02"
    plan = PROJECT / "data/production_trials/fresh_legal_full_flow_20261012/round_01/seed_plan_labor/LEGAL_CORE_PLAN.json"
    before = {p: p.read_bytes() for p in (root / "COLLECTION_RESULT.json", root / "COLLECTION_CLAIM.json", root / "LIVE_IDENTITY_CHECK.json")}
    result = capture.reconcile_collection_durable_result(project_root=PROJECT, collection_root=root,
        observed_exit_code=1, expected_account_key="account01", expected_account_uuid="account:9e5f9e75192fa45becb945bc",
        expected_profile_version=1, expected_public_id="dy4qyzku18yu",
        expected_workflow_run_id="research:7cdd86282656467f83bf8dc340c2ba4a", expected_plan_path=plan,
        expected_plan_sha256="f7e3833dc5a2895e83b06655c131d9b574cf116fdc972df85a611a166b2bc283")
    assert result["status"] == "known_collection_stop" and result["reason"] == "insufficient_research_sample"
    assert result["result"]["unique_videos"] == 90 and result["result"]["collected_observations"] == 208
    assert result["result"]["sample_gate"]["total_likes"] == 465497
    assert result["may_run_source_validation"] is False and result["automatic_redispatch"] is False
    for path, raw in before.items(): assert path.read_bytes() == raw
