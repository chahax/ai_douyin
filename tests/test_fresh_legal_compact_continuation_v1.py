"""Independent offline checks for the same-ledger compact continuation entry.

Fixtures never invoke an SDK, account browser or collector.  Production files
are not copied or mutated; all durable mutations remain in pytest's directory.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import os
import sqlite3
import sys

import pytest

from scripts import run_fresh_legal_compact_continuation_v1 as entry


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def stopped(monkeypatch, tmp_path):
    root = tmp_path / "round_01"
    root.mkdir()
    directory = root / entry.OPERATOR_DIR
    monkeypatch.setattr(entry, "location", lambda value: (root, directory))
    monkeypatch.setattr(entry.extension, "verify_sample_extension_freeze", lambda value: {})
    monkeypatch.setattr(entry.extension, "previous_worker_instance_active", lambda value: False)
    monkeypatch.setattr(entry, "verify_known_task_history", lambda *args: None)
    monkeypatch.setattr(entry.extension, "execution_resource_symbols", lambda: {
        "allowed_python_executables": [str(Path(sys._base_executable).resolve())]})
    spend = {"calls_started": 520, "reported_tokens": 7964215,
        "calls_with_known_usage": 518, "unknown_token_reservations": 93117,
        "pending_ordinals": [70, 160], "parent_ledger_sha256": "a" * 64}
    ledger = {"schema": "fixture", "starting_spend": spend, "max_total_tokens": None,
        "authorization_sha256": "b" * 64, "source_manifest": {"fixture/original.py": "c" * 64},
        "model_configs": {"writer": {"model": "MiniMax-M3"}, "director": {"model": "deepseek-flash"}},
        "calls": [], "automatic_retry": False, "old_budget_reset": False, "old_governance_migrated": False}
    receipts = []
    for ordinal, label in zip(entry.PREFIX_ORDINALS,
            ["fresh_theme_01", "fresh_theme_02", "fresh_plan_01", "fresh_plan_02"]):
        request = {"fixture_ordinal": ordinal, "messages": [
            {"role": "system", "content": "fixture"}, {"role": "user", "content": "{}"}]}
        receipt = {"ordinal": ordinal, "label": label, "request": request,
            "request_sha256": entry.control.digest(request), "source_binding_sha256": entry.SOURCE_BINDING,
            "status": "contract_valid" if ordinal == 522 else "contract_rejected",
            "output": {"theme": "immutable accepted theme"} if ordinal == 522 else {},
            "response_metadata": {"http_status_code": 200, "response_body_complete": True,
                "finish_reason": "stop", "total_tokens": ordinal, "response_id": f"response-{ordinal}"}}
        if ordinal == 524:
            receipt.update(status="interface_rejected", failure={"code": "REQUIRED_TOOL_MISSING"})
        name = f"call_{ordinal}_{label}.json"
        save(root / name, receipt)
        ledger["calls"].append({"ordinal": ordinal, "label": label, "receipt": name,
            "token_reservation": 1000, "receipt_sha256": entry.control.sha_file(root / name)})
        receipts.append(receipt)
        evidence = root / "call_evidence" / f"call_{ordinal:03}"
        for name in ("IDENTITY.json", "REQUEST_BODY_MANIFEST.json", "CAPABILITY_PREFLIGHT.json",
                     "RESPONSE_BODY_MANIFEST.json", "request_body.raw", "response_body.raw"):
            save(evidence / name, {"immutable_fixture": ordinal})
    state = {"status": "halt_required_tool_missing", "original_ordinal": 524,
        "source_binding_sha256": entry.SOURCE_BINDING, "versions": {"theme": 2, "plan": 2, "draft": 0},
        "limits": {"theme": 3, "plan": 3, "draft": 3}, "format_recovery_claims": {},
        "native_theme": receipts[1]["output"], "receipts": receipts}
    save(root / "CALL_LEDGER.json", ledger)
    save(root / "TEXT_STATE.json", state)
    save(root / "TEXT_RESULT.json", state)
    save(root / "USER_SCOPE.json", {"native_limits": {"theme": 3, "plan": 3, "draft": 3, "new_director": 3}})
    runtime = SimpleNamespace(ledger=root / "CALL_LEDGER.json", check=lambda value: None,
        evidence_path=lambda ordinal: root / "call_evidence" / f"call_{ordinal:03}")
    monkeypatch.setattr(entry, "original_runtime", lambda *args, **kwargs: runtime)
    monkeypatch.setattr(entry.control, "digest", entry.control.digest)
    # Only bypass the deliberately tiny fixture source manifest's digest. All
    # document/SDK digests retain the real canonical SHA implementation.
    real_digest = entry.control.digest
    monkeypatch.setattr(entry.control, "digest", lambda value:
        entry.SOURCE_BINDING if value == ledger["source_manifest"] else real_digest(value))
    monkeypatch.setattr(entry, "verified_sdk_evidence", lambda rt, receipt, request: rt.evidence_path(receipt["ordinal"]))
    monkeypatch.setattr(entry.original.clients, "expected_wire_request", lambda request: deepcopy(request))
    monkeypatch.setattr(entry, "inputs", lambda value: {"packet": {}, "legal_context": {},
        "reference_fulltext": "R01", "expression_standards": {}, "production_preferences": {},
        "provider_evidence": {}, "source_binding_sha256": entry.SOURCE_BINDING})
    monkeypatch.setattr(entry, "modules", lambda: (
        SimpleNamespace(compact_context=lambda **kwargs: {"fixture_preview": True},
            compact_payload=lambda payload, binding, **kwargs: deepcopy(payload),
            payload_projection_evidence=lambda *args, **kwargs: {"fixture_projection": True}),
        SimpleNamespace(compile_missing_tool_seed=lambda *args, **kwargs: {"fixture_seed": 524})))
    return SimpleNamespace(root=root, directory=directory, ledger=ledger, state=state,
        receipts=receipts, runtime=runtime)


def prepared(stopped):
    freeze = entry.prepare(stopped.root)
    return freeze, stopped.directory / entry.FREEZE


def test_validate_known_stop_preserves_counts_and_prefix(stopped):
    ledger, state, failed, _ = entry.validate_stop(stopped.root)
    assert ledger["starting_spend"] == stopped.ledger["starting_spend"]
    assert state["versions"] == {"theme": 2, "plan": 2, "draft": 0}
    assert state["format_recovery_claims"] == {}
    assert failed["ordinal"] == 524


@pytest.mark.parametrize("mutation", ["ordinal", "source", "spend", "versions", "limits", "format", "theme", "state_result", "later"])
def test_validate_stop_rejects_changed_history(stopped, mutation):
    if mutation in {"ordinal", "source", "spend"}:
        ledger = deepcopy(stopped.ledger)
        if mutation == "ordinal": ledger["calls"][0]["ordinal"] = 520
        elif mutation == "source": ledger["source_manifest"]["fixture/new.py"] = "d" * 64
        else: ledger["starting_spend"]["reported_tokens"] = 0
        save(stopped.root / "CALL_LEDGER.json", ledger)
    elif mutation == "later":
        (stopped.root / "LOOP_STATE.json").write_text("{}", encoding="utf-8")
    else:
        value = deepcopy(stopped.state)
        if mutation == "versions": value["versions"]["plan"] = 0
        elif mutation == "limits": value["limits"]["plan"] = 4
        elif mutation == "format": value["format_recovery_claims"] = {"plan": {"already": True}}
        elif mutation == "theme": value["native_theme"] = {"replacement": True}
        elif mutation == "state_result": value["status"] = "prepared"
        save(stopped.root / "TEXT_STATE.json", value)
        if mutation != "state_result": save(stopped.root / "TEXT_RESULT.json", value)
    with pytest.raises((ValueError, RuntimeError)):
        entry.validate_stop(stopped.root)
    assert not stopped.directory.exists()


@pytest.mark.parametrize("value", [None, True, -1, "470019"])
def test_unknown_or_bad_original_usage_stops_before_prepare(stopped, value):
    receipt = deepcopy(stopped.receipts[-1])
    receipt["response_metadata"]["total_tokens"] = value
    save(stopped.root / stopped.ledger["calls"][-1]["receipt"], receipt)
    for name in ("TEXT_STATE.json", "TEXT_RESULT.json"):
        state = deepcopy(stopped.state)
        state["receipts"][-1] = receipt
        save(stopped.root / name, state)
    with pytest.raises(ValueError): entry.prepare(stopped.root)
    assert not stopped.directory.exists()


def test_active_original_process_stops_before_directory(stopped, monkeypatch):
    save(stopped.root / "RUN_CLAIM.json", {"pid": 1, "started_at_utc": "fixture"})
    monkeypatch.setattr(entry.extension, "previous_worker_instance_active", lambda value: True)
    with pytest.raises(ValueError, match="active"): entry.prepare(stopped.root)
    assert not stopped.directory.exists()


def test_prepare_reuses_original_manifest_and_writes_no_original_files(stopped):
    before = {p: p.read_bytes() for p in stopped.root.glob("*.json")}
    freeze, _ = prepared(stopped)
    assert freeze["original_source_manifest"] == stopped.ledger["source_manifest"]
    assert freeze["original_versions"] == {"theme": 2, "plan": 2, "draft": 0}
    assert freeze["format_recovery_maximum"] == 1
    assert freeze["format_recovery_is_additional_to_native_version_limit"] is True
    assert freeze["new_media_calls"] == 0
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert not (stopped.directory / entry.CLAIM).exists()


def test_existing_claim_does_not_prepare_or_overwrite_state(stopped):
    save(stopped.directory / entry.CLAIM, {"consumed": True})
    save(stopped.directory / "STATE.json", {"status": "original_running"})
    state = (stopped.directory / "STATE.json").read_bytes()
    with pytest.raises(entry.ContinuationAlreadyClaimed): entry.prepare(stopped.root)
    assert (stopped.directory / "STATE.json").read_bytes() == state
    assert not (stopped.directory / entry.FREEZE).exists()


def test_prepared_freeze_readback_does_not_reset_history(stopped):
    freeze, path = prepared(stopped)
    before = (stopped.root / "CALL_LEDGER.json").read_bytes()
    assert entry.prepare(stopped.root) == freeze
    assert path.exists()
    assert (stopped.root / "CALL_LEDGER.json").read_bytes() == before


@pytest.mark.parametrize("member", [
    "scripts/run_fresh_legal_compact_continuation_v1.py",
    "src/content_factory/creative_compact_legal_context_v1.py",
    "src/content_factory/creative_known_plan_continuation_v1.py",
    "docs/CREATIVE_FRESH_LEGAL_COMPACT_CONTINUATION_PLAN_20261012.md",
    "TEXT_STATE.json", "TEXT_RESULT.json", "ORIGINAL_LEDGER_SNAPSHOT.json",
    "VERIFIED_FORMAT_SEED_524.json", "COMPACT_CONTEXT_PREVIEW.json", "request_body.raw",
])
def test_freeze_member_removal_cannot_skip_required_guard(stopped, member):
    freeze, path = prepared(stopped)
    matching = [name for name in freeze["files"] if name.replace("\\", "/").endswith(member)]
    assert matching
    for name in matching: freeze["files"].pop(name)
    save(path, freeze)
    with pytest.raises(ValueError): entry.verify_operator(stopped.root)


@pytest.mark.parametrize("key,value", [
    ("original_source_manifest", {}), ("original_versions", {"theme": 0, "plan": 0, "draft": 0}),
    ("original_limits", {"theme": 4, "plan": 4, "draft": 4}),
    ("format_recovery_maximum", True), ("new_media_calls", 1), ("automatic_restart", True),
    ("old_budget_reset", True), ("format_recovery_is_additional_to_native_version_limit", False),
])
def test_freeze_cap_and_source_contract_cannot_change(stopped, key, value):
    freeze, path = prepared(stopped)
    freeze[key] = value
    save(path, freeze)
    with pytest.raises(ValueError): entry.verify_operator(stopped.root)


def test_external_executable_member_removal_is_not_subset_validation(stopped):
    freeze, path = prepared(stopped)
    freeze["external_resource_hashes"] = {}
    save(path, freeze)
    with pytest.raises(ValueError): entry.verify_operator(stopped.root)


def test_ledger_prefix_changed_after_prepare_closes_guard(stopped):
    prepared(stopped)
    ledger = deepcopy(stopped.ledger)
    ledger["calls"][3]["receipt_sha256"] = "f" * 64
    save(stopped.root / "CALL_LEDGER.json", ledger)
    with pytest.raises(ValueError): entry.verify_operator(stopped.root)


def test_static_ledger_source_or_spend_change_closes_guard(stopped):
    prepared(stopped)
    ledger = deepcopy(stopped.ledger)
    ledger["starting_spend"]["calls_started"] = 524
    save(stopped.root / "CALL_LEDGER.json", ledger)
    with pytest.raises(ValueError): entry.verify_operator(stopped.root)


def test_new_ledger_rows_may_append_without_rewriting_prefix(stopped):
    prepared(stopped)
    ledger = deepcopy(stopped.ledger)
    ledger["calls"].append({"ordinal": 525, "label": "fresh_plan_02_format_recovery"})
    save(stopped.root / "CALL_LEDGER.json", ledger)
    assert entry.verify_operator(stopped.root)["original_calls_prefix"] == stopped.ledger["calls"]


@pytest.fixture
def sdk_case(monkeypatch, tmp_path):
    directory = tmp_path / "sdk"
    request = {"messages": [{"role": "user", "content": "same full context"}], "structured_schema": {"type": "object"}}
    expected = {"model": "MiniMax-M3", "messages": request["messages"], "tools": [{"fixture": True}]}
    raw = json.dumps(expected).encode("utf-8")
    directory.mkdir()
    (directory / "request_body.raw").write_bytes(raw)
    digest = entry.control.sha_file(directory / "request_body.raw")
    ident = "1" * 64
    manifest = {"body_file": "request_body.raw", "identity_sha256": ident,
        "body_complete": True, "raw_bytes_preserved": True, "credential_redacted": False,
        "stored_sha256": digest, "original_sha256": digest, "bytes": len(raw), "original_bytes": len(raw)}
    proof = {"identity_sha256": ident, "logical_request_sha256": entry.control.digest(request),
        "expected_wire_sha256": entry.control.digest(expected), "actual_wire_sha256": entry.control.digest(expected),
        "original_body_sha256": digest, "actual_request_body_sha256": digest, "body_bytes": len(raw),
        "full_wire_equals_mapped_logical_request": True, "messages_sha256": entry.control.digest(request["messages"]),
        "structured_schema_sha256": entry.control.digest(request["structured_schema"]),
        "status": "capability_preflight_passed", "dispatch_before_verify": False,
        "schema": entry.original.clients.VERSION + "/outbound_capability_proof", "automatic_retry": False,
        "SDK_max_retries": 0, "HTTP_follow_redirects": False,
        "endpoint_method": "POST", "endpoint_path": "/v1/chat/completions", "provider_endpoint_host_matched": True}
    save(directory / "REQUEST_BODY_MANIFEST.json", manifest)
    save(directory / "CAPABILITY_PREFLIGHT.json", proof)
    monkeypatch.setattr(entry.original, "verify_receipt_evidence", lambda *args: directory)
    monkeypatch.setattr(entry.original.clients, "expected_wire_request", lambda value: expected)
    return SimpleNamespace(directory=directory, request=request, expected=expected,
        receipt={"call_evidence": {"identity_sha256": ident}}, manifest=manifest, proof=proof)


def test_sdk_body_evidence_accepts_only_exact_mapping(sdk_case):
    assert entry.verified_sdk_evidence(None, sdk_case.receipt, sdk_case.request) == sdk_case.directory


@pytest.mark.parametrize("file,key,value", [
    ("REQUEST_BODY_MANIFEST.json", "identity_sha256", "2" * 64),
    ("REQUEST_BODY_MANIFEST.json", "body_complete", False),
    ("REQUEST_BODY_MANIFEST.json", "raw_bytes_preserved", False),
    ("REQUEST_BODY_MANIFEST.json", "credential_redacted", True),
    ("REQUEST_BODY_MANIFEST.json", "original_bytes", 0),
    ("CAPABILITY_PREFLIGHT.json", "logical_request_sha256", "2" * 64),
    ("CAPABILITY_PREFLIGHT.json", "expected_wire_sha256", "2" * 64),
    ("CAPABILITY_PREFLIGHT.json", "actual_wire_sha256", "2" * 64),
    ("CAPABILITY_PREFLIGHT.json", "body_bytes", 0),
    ("CAPABILITY_PREFLIGHT.json", "messages_sha256", "2" * 64),
    ("CAPABILITY_PREFLIGHT.json", "dispatch_before_verify", True),
    ("CAPABILITY_PREFLIGHT.json", "SDK_max_retries", 1),
    ("CAPABILITY_PREFLIGHT.json", "SDK_max_retries", False),
    ("CAPABILITY_PREFLIGHT.json", "HTTP_follow_redirects", True),
    ("CAPABILITY_PREFLIGHT.json", "automatic_retry", True),
    ("CAPABILITY_PREFLIGHT.json", "endpoint_method", "GET"),
    ("CAPABILITY_PREFLIGHT.json", "provider_endpoint_host_matched", False),
])
def test_sdk_identity_or_transport_policy_mismatch_is_rejected(sdk_case, file, key, value):
    original = sdk_case.manifest if file.startswith("REQUEST") else sdk_case.proof
    changed = deepcopy(original)
    changed[key] = value
    save(sdk_case.directory / file, changed)
    with pytest.raises(ValueError): entry.verified_sdk_evidence(None, sdk_case.receipt, sdk_case.request)


def test_sdk_actual_body_cannot_differ_even_with_matching_byte_sha(sdk_case):
    changed = {**sdk_case.expected, "model": "another-model"}
    raw = json.dumps(changed).encode("utf-8")
    (sdk_case.directory / "request_body.raw").write_bytes(raw)
    manifest = deepcopy(sdk_case.manifest)
    manifest.update(bytes=len(raw), original_bytes=len(raw), stored_sha256=entry.control.sha_file(sdk_case.directory / "request_body.raw"),
        original_sha256=entry.control.sha_file(sdk_case.directory / "request_body.raw"))
    save(sdk_case.directory / "REQUEST_BODY_MANIFEST.json", manifest)
    with pytest.raises(ValueError): entry.verified_sdk_evidence(None, sdk_case.receipt, sdk_case.request)


@pytest.fixture
def worker_case(monkeypatch, tmp_path):
    root, directory = tmp_path / "root", tmp_path / "root" / entry.OPERATOR_DIR
    directory.mkdir(parents=True)
    monkeypatch.setattr(entry, "location", lambda value: (root, directory))
    save(directory / entry.FREEZE, {"offline_frozen": True})
    exe = str(Path(sys._base_executable).resolve())
    script = str(Path(entry.__file__).resolve())
    created = datetime.now(timezone.utc).timestamp() - 5
    attrs = {"running": True, "exe": exe, "args": [exe, script, "run"], "created": created}
    process = SimpleNamespace(is_running=lambda: attrs["running"], exe=lambda: attrs["exe"],
        cmdline=lambda: attrs["args"], create_time=lambda: attrs["created"])
    import psutil
    monkeypatch.setattr(psutil, "Process", lambda pid: process)
    freeze = {"execution_resource_symbols": {"allowed_python_executables": [exe], "worker_script": script}}
    claim = {"schema": entry.VERSION + "/claim", "pid": os.getpid(),
        "operator_freeze_sha256": entry.control.sha_file(directory / entry.FREEZE),
        "source_binding_sha256": entry.SOURCE_BINDING, "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "automatic_restart": False, "old_budget_reset": False, "new_media_calls": 0}
    save(directory / entry.CLAIM, claim)
    return SimpleNamespace(root=root, directory=directory, freeze=freeze, claim=claim, attrs=attrs)


def test_current_worker_must_match_current_process_instance(worker_case):
    entry.verify_worker(worker_case.root, worker_case.freeze)


@pytest.mark.parametrize("mutation", ["dead", "exe", "script", "future_created", "old_created", "pid", "freeze_sha", "source"])
def test_worker_identity_mismatch_and_pid_reuse_close_gate(worker_case, mutation):
    if mutation == "dead": worker_case.attrs["running"] = False
    elif mutation == "exe": worker_case.attrs["exe"] = str(Path(entry.__file__).resolve())
    elif mutation == "script": worker_case.attrs["args"][1] = "another-entry.py"
    elif mutation == "future_created": worker_case.attrs["created"] += 100
    elif mutation == "old_created": worker_case.attrs["created"] -= 500
    else:
        claim = deepcopy(worker_case.claim)
        if mutation == "pid": claim["pid"] += 1
        elif mutation == "freeze_sha": claim["operator_freeze_sha256"] = "f" * 64
        elif mutation == "source": claim["source_binding_sha256"] = "f" * 64
        save(worker_case.directory / entry.CLAIM, claim)
    with pytest.raises(ValueError): entry.verify_worker(worker_case.root, worker_case.freeze)


def test_performance_stage_reads_explicit_accepted_result_not_old_failure(tmp_path, monkeypatch):
    original = tmp_path / "TEXT_RESULT.json"
    accepted = tmp_path / "operator" / "TEXT_RESULT.json"
    save(original, {"status": "halt_required_tool_missing"})
    result = {"status": "text_ready_for_director", "script": {"full": "new accepted script"},
        "source_review_binding": {"writer_ordinal": 526, "review_ordinal": 527}}
    save(accepted, result)
    save(accepted.parent / "ACCEPTED_TEXT_BINDING.json", {
        "schema": entry.VERSION + "/accepted_text_binding", "source_binding_sha256": entry.SOURCE_BINDING,
        "text_result_file_sha256": entry.control.sha_file(accepted),
        "script_sha256": entry.control.digest(result["script"]), "source_review_binding": result["source_review_binding"]})
    seen = []
    monkeypatch.setattr(entry.original.parent.old.source, "catalog", lambda script: seen.append(script) or [1, 2, 3])
    assert entry.stage("performance_seg01", accepted) == ("performance", 27)
    assert seen == [{"full": "new accepted script"}]
    assert json.loads(original.read_text())["status"] == "halt_required_tool_missing"


def test_performance_stage_blocks_failed_result_before_catalog(tmp_path, monkeypatch):
    result = tmp_path / "TEXT_RESULT.json"
    save(result, {"status": "halt_required_tool_missing"})
    save(result.parent / "ACCEPTED_TEXT_BINDING.json", {})
    monkeypatch.setattr(entry.original.parent.old.source, "catalog", lambda script: pytest.fail("failed text reached catalog"))
    with pytest.raises(ValueError): entry.stage("performance_seg01", result)


def test_exclusive_claim_race_cannot_overwrite_winner_state(stopped, monkeypatch):
    prepared(stopped)
    monkeypatch.setattr(entry, "validate_stop", lambda value: None)
    original_open = Path.open
    claim_path = stopped.directory / entry.CLAIM
    winner_state = {"status": "winner_running"}
    def raced_open(path, mode="r", *args, **kwargs):
        if path == claim_path and mode == "x":
            save(claim_path, {"winner_claim": True})
            save(stopped.directory / "STATE.json", winner_state)
            raise FileExistsError("peer won wx creation")
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", raced_open)
    with pytest.raises(entry.ContinuationAlreadyClaimed): entry.run(stopped.root)
    assert entry.control.read(stopped.directory / "STATE.json") == winner_state


def test_runtime_reuses_ledger_source_members_and_starting_spend(tmp_path, monkeypatch):
    captured = []
    def construct(*args, **kwargs):
        captured.append((args, kwargs))
        return SimpleNamespace(ledger=tmp_path / "CALL_LEDGER.json")
    monkeypatch.setattr(entry.control, "ContinuationRuntime", construct)
    source = {"src/frozen_original.py": "a" * 64}
    inherited = {"calls_started": 520, "reported_tokens": 7964215, "unknown_token_reservations": 93117,
        "pending_ordinals": [70, 160]}
    models = {"writer": {"model": "MiniMax-M3"}, "director": {"model": "deepseek-flash"}}
    guard = lambda: None
    entry.original_runtime(tmp_path, {"source_manifest": source, "starting_spend": inherited, "model_configs": models}, guard)
    args, kwargs = captured[0]
    assert args[2] == [entry.PROJECT / "src/frozen_original.py"]
    assert args[3] == inherited and args[4] == models
    assert kwargs["inherited_guard"] is guard and kwargs["quota_state"] is None
    assert not (tmp_path / "CALL_LEDGER.json").exists()


@pytest.mark.parametrize("mutation", ["result_file", "script_sha", "source", "review_identity", "expected_binding", "status"])
def test_accepted_text_binding_detects_replacement_before_performance(tmp_path, mutation):
    result = {"status": "text_ready_for_director", "script": {"complete": "immutable new story"},
        "source_review_binding": {"writer_ordinal": 526, "review_ordinal": 527}}
    path = tmp_path / "TEXT_RESULT.json"
    save(path, result)
    binding = {"schema": entry.VERSION + "/accepted_text_binding", "source_binding_sha256": entry.SOURCE_BINDING,
        "text_result_file_sha256": entry.control.sha_file(path), "script_sha256": entry.control.digest(result["script"]),
        "source_review_binding": result["source_review_binding"], "human_adopted": False, "video_content_passed": False}
    expected = deepcopy(binding)
    if mutation == "result_file":
        result["script"] = {"complete": "replacement"}
        save(path, result)
    elif mutation == "script_sha": binding["script_sha256"] = "f" * 64
    elif mutation == "source": binding["source_binding_sha256"] = "f" * 64
    elif mutation == "review_identity": binding["source_review_binding"] = {"writer_ordinal": 520, "review_ordinal": 521}
    elif mutation == "expected_binding": binding["human_adopted"] = True
    elif mutation == "status":
        result["status"] = "halt_review_uncertain"
        save(path, result)
        binding["text_result_file_sha256"] = entry.control.sha_file(path)
    save(tmp_path / "ACCEPTED_TEXT_BINDING.json", binding)
    with pytest.raises(ValueError): entry.verify_accepted_text_binding(tmp_path, expected)


def test_unrecognized_stage_never_reaches_a_task_store(tmp_path):
    with pytest.raises(ValueError, match="outside"):
        entry.stage("video_submit", tmp_path / "TEXT_RESULT.json")


def test_duplicate_claim_race_cli_keeps_winner_state(stopped, monkeypatch):
    prepared(stopped)
    monkeypatch.setattr(entry, "validate_stop", lambda value: None)
    original_open = Path.open
    claim_path = stopped.directory / entry.CLAIM
    def raced_open(path, mode="r", *args, **kwargs):
        if path == claim_path and mode == "x":
            save(claim_path, {"winner_claim": True})
            save(stopped.directory / "STATE.json", {"status": "winner_running"})
            raise FileExistsError("peer won wx creation")
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", raced_open)
    monkeypatch.setattr(sys, "argv", [str(entry.__file__), "run", "--root", str(stopped.root)])
    with pytest.raises(SystemExit) as stopped_exit: entry.main()
    assert stopped_exit.value.code == 2
    assert entry.control.read(stopped.directory / "STATE.json") == {"status": "winner_running"}


@pytest.fixture
def task_history_case(tmp_path):
    store_module = entry.original.task_store
    request = {"model": "MiniMax-M3", "role": "writer", "messages": [{"role": "user", "content": "complete fixture"}]}
    label = "fresh_draft_01"
    receipt = {"ordinal": 526, "label": label, "request": request, "status": "contract_valid", "output": {"full": "native"},
        "response_metadata": {"http_status_code": 200, "response_body_complete": True, "finish_reason": "tool_calls", "total_tokens": 123}}
    gid = "call_" + entry.control.digest({"grant_id": entry.original.GRANT_ID, "label": label})[:24]
    store = store_module.TaskStore(tmp_path / "TASKS.sqlite3")
    graph = {"schema_version": store_module.GRAPH_SCHEMA, "graph_id": gid, "nodes": [
        {"node_id": "source", "kind": "source", "input": {"frozen_source_sha256": entry.SOURCE_BINDING}, "depends_on": []},
        {"node_id": "result", "kind": "text", "input": {"label": label, "phase": "draft"}, "depends_on": ["source"]}]}
    store.register_graph(graph)
    auth = {"schema_version": store_module.AUTH_SCHEMA, "authorization_id": gid + ":scope", "graph_id": gid,
        "node_ids": ["result"], "scope": "text", "purpose": "dispatch", "source_sha256": store.snapshot(gid)["source_sha256"],
        "max_attempts": 1, "prior_attempts": 0, "allows_content_revision": False,
        "evidence_ref": "fixture#draft", "evidence_sha256": "a" * 64}
    attempt = store.claim(gid, "result", {"provider_id": request["model"], "payload": request}, auth)
    raw = b"{}"
    import hashlib
    import base64
    result = {"schema_version": store_module.RESULT_SCHEMA, "claim_id": attempt["claim_id"],
        "request_sha256": attempt["request_sha256"], "service_task_id": None,
        "outcome": "completed", "result_known": True, "usage_known": True,
        "usage": {"unit": "reported_tokens", "amount": 123}, "complete": True, "complete_end": True,
        "schema_tool_status": "accepted", "contract_valid": True,
        "raw_receipt": {"encoding": "base64", "body": base64.b64encode(raw).decode("ascii"),
            "sha256": hashlib.sha256(raw).hexdigest(), "http_status": 200},
        "output": {"receipt_sha256": entry.control.digest(receipt), "native_output": receipt["output"]}}
    store.accept_result(attempt["claim_id"], result)
    return SimpleNamespace(root=tmp_path, receipt=receipt, request=request, result=result, gid=gid, attempt=attempt)


def test_known_task_history_is_verified_readonly_without_reclaim(task_history_case):
    case = task_history_case
    database = case.root / "TASKS.sqlite3"
    before = database.read_bytes()
    entry.verify_known_task_history(case.root, [case.receipt])
    assert database.read_bytes() == before
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1


@pytest.mark.parametrize("mutation", ["claimed", "extra_claim", "graph", "request_model", "usage", "result_identity", "request_identity", "result_digest"])
def test_unresolved_or_mismatched_sqlite_task_stops_before_dispatch(task_history_case, mutation):
    case = task_history_case
    database = case.root / "TASKS.sqlite3"
    with sqlite3.connect(database) as conn:
        if mutation == "claimed":
            conn.execute("UPDATE attempts SET status='claimed',result=NULL,result_sha=NULL")
        elif mutation == "extra_claim":
            # Same real attempt table, but the ledger has not acknowledged it.
            # An extra original receipt is deliberately omitted from the audit.
            pass
        elif mutation == "graph": conn.execute("UPDATE attempts SET graph_id=?", (case.gid + "-wrong",))
        elif mutation == "request_model":
            changed = {"provider_id": "other", "payload": case.request}
            conn.execute("UPDATE attempts SET request=?", (json.dumps(changed),))
        elif mutation == "result_digest": conn.execute("UPDATE attempts SET result_sha=?", ("f" * 64,))
        else:
            changed = deepcopy(case.result)
            if mutation == "usage": changed["usage"]["amount"] = 0
            elif mutation == "result_identity": changed["claim_id"] = "other-claim"
            elif mutation == "request_identity": changed["request_sha256"] = "f" * 64
            conn.execute("UPDATE attempts SET result=?,result_sha=?", (json.dumps(changed), entry.control.digest(changed)))
    receipts = [] if mutation == "extra_claim" else [case.receipt]
    with pytest.raises(ValueError): entry.verify_known_task_history(case.root, receipts)

