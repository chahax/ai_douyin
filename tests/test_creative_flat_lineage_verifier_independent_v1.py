"""Independent synthetic epoch audit. Never runs historical guards/provider clients."""
from copy import deepcopy
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3

import pytest

from src.content_factory import creative_flat_lineage_verifier_v1 as verifier
from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def native_json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")


@pytest.fixture
def synthetic_parent(tmp_path):
    project = tmp_path / "synthetic_project"
    parent = project / "terminal_parent"
    parent.mkdir(parents=True)
    source = project / "guard_source.py"
    source.write_text("# synthetic guard code; no provider client\n", encoding="utf-8")
    snapshot = parent / "source_at_dispatch" / "guard_source.py"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_bytes(source.read_bytes())
    write_json(parent / "AUTHORIZATION.json", {"synthetic": True, "automatic_retry": False})
    write_json(parent / "USER_SCOPE.json", {"schema": "synthetic_independent_flat_review/v1", "grant_id": "synthetic_independent_flat_review"})
    starting = {"calls_started": 540, "reported_tokens": 10308368,
        "calls_with_known_usage": 538, "unknown_token_reservations": 93117,
        "pending_ordinals": [70, 160]}
    ledger = {"starting_spend": starting, "calls": [], "max_total_tokens": None,
        "automatic_retry": False, "old_budget_reset": False, "old_governance_migrated": False,
        "authorization_sha256": sha(parent / "AUTHORIZATION.json"),
        "source_manifest": {"guard_source.py": sha(source)},
        "model_configs": {"writer": {"model": "MiniMax-M3.1-Flash-Preview"},
            "director": {"model": "deepseek-flash"}}}
    write_json(parent / "CALL_LEDGER.json", ledger)
    with sqlite3.connect(parent / "TASKS.sqlite3") as connection:
        connection.execute("CREATE TABLE attempts (graph_id TEXT,status TEXT,request TEXT,result TEXT,claim_id TEXT,request_sha TEXT,result_sha TEXT)")
    external = project / "external_authority"
    external.mkdir()
    authority = external / "history.json"
    write_json(authority, {"pending": [70, 160], "reservation": 93117})
    summary = {"effective_calls_started": 540, "effective_reported_tokens": 10308368,
        "effective_calls_with_known_usage": 538, "unknown_token_reservations": 93117,
        "historical_pending_ordinals": [70, 160], "old_budget_reset": False, "media_calls": 0}
    return project, parent, source, external, authority, ledger, summary


def certify(fixture, *, directory_method="glob", missing_sentinel=None):
    project, parent, source, external, authority, _, summary = fixture
    calls = []
    def synthetic_check():
        calls.append("synthetic_check")
        json.loads(authority.read_text(encoding="utf-8"))
        if directory_method == "glob":
            list(external.glob("*"))
        elif directory_method == "listdir":
            os.listdir(external)
        elif directory_method == "exists":
            assert missing_sentinel is not None and not missing_sentinel.exists()
        return deepcopy(summary)
    certificate = verifier.build_lineage_certificate(project, parent,
        certified_check=synthetic_check, expected_summary=summary,
        dependency_paths=[parent / "AUTHORIZATION.json"], guard_code_paths=[source])
    assert calls == ["synthetic_check"]
    return certificate


def verify(certificate, *, source_gate=lambda: {"blockers": []}, expected=None):
    return verifier.verify_lineage_certificate(certificate,
        expected_certificate_sha256=verifier.digest(certificate),
        fresh_source_gate=source_gate, expected_inherited=expected)


def add_known_call(fixture, *, unknown=False, role="writer"):
    """Create a synthetic native wire/body/task triangle, without any SDK client."""
    project, parent, _, _, _, ledger, summary = fixture
    label, ordinal = ("goal_plan_synthetic" if role == "writer" else "whole_goal_review_synthetic"), 541
    parameters = {"temperature": .4, "thinking": "adaptive", "reasoning_effort": "medium", "max_completion_tokens": 16000} if role == "writer" else {
        "temperature": .4, "thinking": "disabled", "max_completion_tokens": 8000}
    request = {"stage": "goal_plan" if role == "writer" else "whole_goal_review", "role": role,
        "model": "MiniMax-M3.1-Flash-Preview" if role == "writer" else "deepseek-flash",
        "messages": [{"role": "system", "content": "synthetic contract only"}, {"role": "user", "content": "no dispatch"}],
        "parameters": parameters,
        "structured_schema": {"type": "object", "properties": {"synthetic": {"type": "string"}}, "required": ["synthetic"], "additionalProperties": False}}
    wire = expected_wire_request(request)
    output = {"synthetic": "complete native synthetic result"}
    arguments = json.dumps(output, ensure_ascii=False)
    total = None if unknown else 7
    payload = {"id": "synthetic_response_541", "model": request["model"],
        "choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [{"type": "function",
            "function": {"name": wire["tools"][0]["function"]["name"], "arguments": arguments}}]}}],
        "usage": {"total_tokens": total}}
    directory = parent / "call_evidence/call_541"
    directory.mkdir(parents=True)
    identity = {"ordinal": ordinal, "label": label, "request_sha256": verifier.digest(request),
        "source_binding_sha256": verifier.digest(ledger["source_manifest"]), "role": role, "model": request["model"]}
    identity_sha = verifier.digest(identity)
    write_json(directory / "IDENTITY.json", {"identity": identity, "identity_sha256": identity_sha})
    wire_raw, response_raw = native_json_bytes(wire), native_json_bytes(payload)
    wire_sha, response_sha = hashlib.sha256(wire_raw).hexdigest(), hashlib.sha256(response_raw).hexdigest()
    (directory / "request_body.raw").write_bytes(wire_raw)
    (directory / "response_body.raw").write_bytes(response_raw)
    common = {"identity_sha256": identity_sha, "body_complete": True, "raw_bytes_preserved": True, "credential_redacted": False}
    write_json(directory / "REQUEST_BODY_MANIFEST.json", {**common, "body_file": "request_body.raw", "stored_sha256": wire_sha,
        "original_sha256": wire_sha, "bytes": len(wire_raw), "original_bytes": len(wire_raw)})
    write_json(directory / "RESPONSE_BODY_MANIFEST.json", {**common, "body_file": "response_body.raw", "stored_sha256": response_sha,
        "original_sha256": response_sha, "bytes": len(response_raw), "original_bytes": len(response_raw),
        "http_metadata": {"http_status_code": 200}})
    host = "api.minimax.cn" if role == "writer" else "api.deepseek.com"
    proof = {"schema": "creative_m31_flash_role_clients/v1/outbound_proof", "identity_sha256": identity_sha,
        "logical_request_sha256": verifier.digest(request), "expected_wire_sha256": verifier.digest(wire),
        "actual_wire_sha256": verifier.digest(wire), "actual_request_body_sha256": wire_sha,
        "body_bytes": len(wire_raw), "full_wire_equals_mapped_logical_request": True,
        "messages_sha256": verifier.digest(request["messages"]), "structured_schema_sha256": verifier.digest(request["structured_schema"]),
        "status": "wire_verified_before_send", "mapped_fields": sorted(wire), "SDK_max_retries": 0,
        "provider_endpoint_host": host, "verified_endpoint_sha256": verifier.digest(["POST", "https://" + host + "/v1/chat/completions"]),
        "writer_reasoning_effort": "medium" if role == "writer" else None,
        "server_stream_requested": False, "server_schema_guarantee": False,
        "new_provider_acceptance_verified": False, "provider_received_request": None, "calls_authorized_by_proof": False,
        "HTTP_follow_redirects": False, "endpoint_method": "POST", "endpoint_path": "/v1/chat/completions",
        "automatic_retry": False}
    write_json(directory / "M31_WIRE_PREFLIGHT.json", proof)
    receipt = {"ordinal": ordinal, "label": label, "request": request, "request_sha256": verifier.digest(request),
        "source_binding_sha256": verifier.digest(ledger["source_manifest"]), "token_reservation": 16000,
        "status": "contract_valid", "call_evidence": {"directory": str(directory), "identity_sha256": identity_sha},
        "response_metadata": {"http_status_code": 200, "response_body_complete": True, "finish_reason": "tool_calls",
            "total_tokens": total, "raw_body_sha256": response_sha, "requested_model": request["model"],
            "response_model": request["model"], "output_mode": "tool_call", "response_id": payload["id"]},
        "response_payload": payload, "response_text": arguments, "output": output}
    filename = f"call_{ordinal}_{label}.json"
    write_json(parent / filename, receipt)
    ledger["calls"] = [{"ordinal": ordinal, "label": label, "receipt": filename,
        "receipt_sha256": sha(parent / filename), "token_reservation": 16000}]
    write_json(parent / "CALL_LEDGER.json", ledger)
    claim = "synthetic_claim_541"
    task_request = {"provider_id": request["model"], "payload": request}
    result = {"claim_id": claim, "request_sha256": verifier.digest(task_request), "outcome": "completed",
        "result_known": True, "usage_known": not unknown, "complete": True, "complete_end": True,
        "usage": {"unit": "reported_tokens", "amount": total}, "schema_tool_status": "accepted",
        "raw_receipt": {"encoding": "base64", "body": base64.b64encode(response_raw).decode("ascii"),
            "sha256": response_sha, "http_status": 200}, "output": {"ordinal": ordinal, "native_output": output}}
    graph = "call_" + verifier.digest({"grant": "synthetic_independent_flat_review", "label": label})[:24]
    with sqlite3.connect(parent / "TASKS.sqlite3") as connection:
        connection.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,?)", (graph, "completed", json.dumps(task_request), json.dumps(result),
            claim, verifier.digest(task_request), verifier.digest(result)))
    summary.update(effective_calls_started=541, effective_reported_tokens=summary["effective_reported_tokens"] + (total or 0),
        effective_calls_with_known_usage=summary["effective_calls_with_known_usage"] + int(not unknown))
    return receipt, directory


def test_success_binds_external_positive_reads_glob_directory_and_unknown_history(synthetic_parent):
    certificate = certify(synthetic_parent)
    _, _, _, external, authority, _, summary = synthetic_parent
    assert str(authority.resolve()) in certificate["files"]
    assert str(external.resolve()) in certificate["directories"]
    result = verify(certificate)
    assert result["inherited"]["pending_ordinals"] == [70, 160]
    assert result["inherited"]["unknown_token_reservations"] == 93117
    assert result["inherited"]["calls_started"] == summary["effective_calls_started"]
    assert result["inherited"]["reported_tokens"] == summary["effective_reported_tokens"]
    assert all(count == 1 for count in result["file_read_counts"].values())
    assert result["old_budget_reset"] is False and result["media_calls"] == 0


def test_sha_epoch_is_fresh_even_if_size_and_mtime_are_unchanged(synthetic_parent):
    certificate = certify(synthetic_parent)
    authority = synthetic_parent[4]
    verify(certificate)
    old = authority.stat()
    raw = authority.read_bytes()
    authority.write_bytes(raw.replace(b"93117", b"93118"))
    os.utime(authority, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert authority.stat().st_size == old.st_size and authority.stat().st_mtime_ns == old.st_mtime_ns
    with pytest.raises(verifier.LineageVerificationError, match="SHA changed"):
        verify(certificate)


def test_same_cycle_reads_once_but_conflicting_expectation_is_rejected(synthetic_parent):
    path = synthetic_parent[2]
    cycle = verifier.VerificationCycle()
    cycle.verify(path, sha(path))
    cycle.sha(path)
    cycle.read_bytes(path)
    assert cycle.read_counts[str(path.resolve())] == 1
    with pytest.raises(verifier.LineageVerificationError, match="conflicting"):
        cycle.verify(path, "f" * 64)


@pytest.mark.parametrize("alter", ["authorization", "source", "snapshot", "ledger", "task_database", "external_read"])
def test_each_certified_dependency_change_blocks_epoch(synthetic_parent, alter):
    certificate = certify(synthetic_parent)
    project, parent, source, _, authority, ledger, _ = synthetic_parent
    path = {"authorization": parent / "AUTHORIZATION.json", "source": source,
        "snapshot": parent / "source_at_dispatch/guard_source.py", "ledger": parent / "CALL_LEDGER.json",
        "task_database": parent / "TASKS.sqlite3", "external_read": authority}[alter]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(verifier.LineageVerificationError, match="SHA changed"):
        verify(certificate)


def test_new_ancestor_claim_or_receipt_file_blocks_epoch_before_dispatch(synthetic_parent):
    certificate = certify(synthetic_parent)
    write_json(synthetic_parent[1] / "RUN_CLAIM_EXTRA.json", {"synthetic": True})
    with pytest.raises(verifier.LineageVerificationError, match="new/missing"):
        verify(certificate)


def test_glob_observed_external_directory_addition_blocks_epoch(synthetic_parent):
    certificate = certify(synthetic_parent)
    write_json(synthetic_parent[3] / "new_claim.json", {"synthetic": True})
    with pytest.raises(verifier.LineageVerificationError, match="new/missing"):
        verify(certificate)


def test_tampered_certificate_without_new_frozen_sha_is_rejected(synthetic_parent):
    certificate = certify(synthetic_parent)
    expected = verifier.digest(certificate)
    changed = deepcopy(certificate)
    changed["inherited"]["pending_ordinals"] = []
    with pytest.raises(verifier.LineageVerificationError, match="canonical SHA"):
        verifier.verify_lineage_certificate(changed, expected_certificate_sha256=expected,
            fresh_source_gate=lambda: {"blockers": []})


@pytest.mark.parametrize("counter", ["calls_started", "reported_tokens", "calls_with_known_usage", "unknown_token_reservations", "pending_ordinals"])
def test_external_expected_inheritance_cannot_clear_unknown_or_reset_any_counter(synthetic_parent, counter):
    certificate = certify(synthetic_parent)
    expected = deepcopy(certificate["inherited"])
    expected[counter] = [] if counter == "pending_ordinals" else 0
    with pytest.raises(verifier.LineageVerificationError, match="inherited accumulation"):
        verify(certificate, expected=expected)


def test_source_time_gate_is_reexecuted_every_epoch_and_exception_stops(synthetic_parent):
    certificate = certify(synthetic_parent)
    gates = []
    def gate():
        gates.append("freshness")
        if len(gates) > 1:
            raise ValueError("synthetic source expired")
        return {"blockers": []}
    verify(certificate, source_gate=gate)
    with pytest.raises(ValueError, match="source expired"):
        verify(certificate, source_gate=gate)
    assert gates == ["freshness", "freshness"]


def test_observer_restores_original_io_after_certification_failure(synthetic_parent):
    project, parent, source, *_ = synthetic_parent
    original_open, original_scan = verifier.builtins.open, os.scandir
    def failing():
        raise RuntimeError("synthetic checkpoint failure")
    with pytest.raises(RuntimeError):
        verifier.build_lineage_certificate(project, parent, certified_check=failing,
            expected_summary=synthetic_parent[-1], dependency_paths=[], guard_code_paths=[source])
    assert verifier.builtins.open is original_open and os.scandir is original_scan


def test_duplicate_and_nonfinite_json_never_become_certified_dependency():
    for raw in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":1e999}', '[]'):
        with pytest.raises(verifier.LineageVerificationError):
            verifier.strict_json(raw)


def test_actual_pure_mapper_native_response_and_task_spend_are_consistent(synthetic_parent):
    receipt, directory = add_known_call(synthetic_parent)
    certificate = certify(synthetic_parent)
    result = verify(certificate)
    assert result["inherited"]["calls_started"] == 541
    assert result["inherited"]["calls_with_known_usage"] == 539
    assert result["inherited"]["reported_tokens"] == 10308375
    assert result["inherited"]["pending_ordinals"] == [70, 160]
    assert str((directory / "request_body.raw").resolve()) in certificate["files"]
    assert str((directory / "response_body.raw").resolve()) in certificate["files"]


def test_new_unknown_usage_cannot_be_certified_as_a_safe_continuation(synthetic_parent):
    add_known_call(synthetic_parent, unknown=True)
    with pytest.raises(verifier.LineageVerificationError, match="unresolved new dispatch"):
        certify(synthetic_parent)


def test_unreconciled_durable_claim_blocks_before_new_certificate(synthetic_parent):
    parent = synthetic_parent[1]
    with sqlite3.connect(parent / "TASKS.sqlite3") as connection:
        connection.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,?)", ("synthetic_unknown", "claimed", "{}", None,
            "unknown_claim", "f" * 64, None))
    with pytest.raises(verifier.LineageVerificationError, match="unreconciled"):
        certify(synthetic_parent)


@pytest.mark.parametrize("alter", ["wire", "native_tool", "durable_graph", "durable_native_output"])
def test_known_receipt_must_match_real_wire_raw_tool_and_exact_durable_task_before_certification(synthetic_parent, alter):
    receipt, directory = add_known_call(synthetic_parent)
    parent, ledger = synthetic_parent[1], synthetic_parent[5]
    if alter == "wire":
        raw = json.loads((directory / "request_body.raw").read_text(encoding="utf-8"))
        raw["model"] = "different-model"
        (directory / "request_body.raw").write_bytes(native_json_bytes(raw))
    elif alter == "native_tool":
        receipt["output"] = {"synthetic": "hand patched output"}
        write_json(parent / ledger["calls"][0]["receipt"], receipt)
        ledger["calls"][0]["receipt_sha256"] = sha(parent / ledger["calls"][0]["receipt"])
        write_json(parent / "CALL_LEDGER.json", ledger)
    elif alter == "durable_graph":
        with sqlite3.connect(parent / "TASKS.sqlite3") as connection:
            connection.execute("UPDATE attempts SET graph_id='wrong_graph'")
    else:
        with sqlite3.connect(parent / "TASKS.sqlite3") as connection:
            old = json.loads(connection.execute("SELECT result FROM attempts").fetchone()[0])
            old["output"]["native_output"] = {"synthetic": "different native result"}
            connection.execute("UPDATE attempts SET result=?,result_sha=?", (json.dumps(old), verifier.digest(old)))
    with pytest.raises(verifier.LineageVerificationError):
        certify(synthetic_parent)


@pytest.mark.parametrize("source_result", [False, {"fresh": False}, {"status": "unknown"}, None])
def test_explicit_invalid_source_gate_result_must_not_produce_verified_epoch(synthetic_parent, source_result):
    certificate = certify(synthetic_parent)
    with pytest.raises(verifier.LineageVerificationError):
        verify(certificate, source_gate=lambda: source_result)


def test_listdir_observed_external_directory_is_closed_against_new_claim(synthetic_parent):
    certificate = certify(synthetic_parent, directory_method="listdir")
    write_json(synthetic_parent[3] / "new_claim.json", {"synthetic": True})
    with pytest.raises(verifier.LineageVerificationError):
        verify(certificate)


def test_absent_path_dependency_is_not_ignored_after_it_appears(synthetic_parent):
    external = synthetic_parent[0] / "negative_authority"
    external.mkdir()
    sentinel = external / "unresolved_claim.json"
    certificate = certify(synthetic_parent, directory_method="exists", missing_sentinel=sentinel)
    write_json(sentinel, {"synthetic_pending": True})
    with pytest.raises(verifier.LineageVerificationError):
        verify(certificate)


def rewrite_synthetic_receipt(fixture, receipt):
    """Change only a disposable fixture and keep its explicit byte binding exact."""
    parent, ledger = fixture[1], fixture[5]
    path = parent / ledger["calls"][0]["receipt"]
    write_json(path, receipt)
    ledger["calls"][0]["receipt_sha256"] = sha(path)
    write_json(parent / "CALL_LEDGER.json", ledger)


def test_actual_m31_preflight_document_is_bound_without_invented_capability_fields(synthetic_parent):
    _, directory = add_known_call(synthetic_parent)
    proof = json.loads((directory / "M31_WIRE_PREFLIGHT.json").read_text(encoding="utf-8"))
    assert proof["schema"] == "creative_m31_flash_role_clients/v1/outbound_proof"
    assert "original_body_sha256" not in proof and "dispatch_before_verify" not in proof
    certificate = certify(synthetic_parent)
    assert str((directory / "M31_WIRE_PREFLIGHT.json").resolve()) in certificate["files"]
    assert verify(certificate)["inherited"]["reported_tokens"] == 10308375


def test_actual_deepseek_m31_role_uses_exact_endpoint_and_no_writer_reasoning(synthetic_parent):
    _, directory = add_known_call(synthetic_parent, role="director")
    proof = json.loads((directory / "M31_WIRE_PREFLIGHT.json").read_text(encoding="utf-8"))
    assert proof["provider_endpoint_host"] == "api.deepseek.com" and proof["writer_reasoning_effort"] is None
    assert verify(certify(synthetic_parent))["inherited"]["calls_with_known_usage"] == 539


def test_relative_native_evidence_directory_is_resolved_under_its_exact_parent(synthetic_parent):
    receipt, _ = add_known_call(synthetic_parent)
    receipt["call_evidence"]["directory"] = "call_evidence/call_541"
    rewrite_synthetic_receipt(synthetic_parent, receipt)
    assert verify(certify(synthetic_parent))["inherited"]["calls_started"] == 541


@pytest.mark.parametrize("storage", ["receipt_ordinal", "receipt_sha256"])
def test_actual_durable_output_storage_contracts_remain_native_bound(synthetic_parent, storage):
    receipt, _ = add_known_call(synthetic_parent)
    with sqlite3.connect(synthetic_parent[1] / "TASKS.sqlite3") as connection:
        result = json.loads(connection.execute("SELECT result FROM attempts").fetchone()[0])
        result["output"] = {"receipt_ordinal": receipt["ordinal"], "native_output": receipt["output"]} if storage == "receipt_ordinal" else {
            "receipt_sha256": verifier.digest(receipt)}
        connection.execute("UPDATE attempts SET result=?,result_sha=?", (json.dumps(result), verifier.digest(result)))
    assert verify(certify(synthetic_parent))["inherited"]["reported_tokens"] == 10308375


def test_settled_wal_mode_header_is_only_decoded_in_memory_and_never_rewritten(synthetic_parent):
    add_known_call(synthetic_parent)
    database = synthetic_parent[1] / "TASKS.sqlite3"
    raw = bytearray(database.read_bytes())
    raw[18:20] = b"\x02\x02"
    database.write_bytes(raw)
    before = sha(database)
    assert verify(certify(synthetic_parent))["inherited"]["calls_started"] == 541
    assert sha(database) == before and database.read_bytes()[18:20] == b"\x02\x02"


@pytest.mark.parametrize("metadata", [{"response_body_complete": False}, {"http_status_code": 400}])
def test_real_incomplete_or_http_failed_receipt_metadata_blocks_new_certificate(synthetic_parent, metadata):
    receipt, _ = add_known_call(synthetic_parent)
    receipt["response_metadata"].update(metadata)
    rewrite_synthetic_receipt(synthetic_parent, receipt)
    with pytest.raises(verifier.LineageVerificationError):
        certify(synthetic_parent)


def test_m31_proof_cannot_claim_unverified_generic_capability_schema(synthetic_parent):
    _, directory = add_known_call(synthetic_parent)
    path = directory / "M31_WIRE_PREFLIGHT.json"
    proof = json.loads(path.read_text(encoding="utf-8"))
    proof["schema"] = "creative_m31_flash_role_clients/v1/outbound_capability_proof"
    write_json(path, proof)
    with pytest.raises(verifier.LineageVerificationError, match="unverified native outbound adapter"):
        certify(synthetic_parent)
