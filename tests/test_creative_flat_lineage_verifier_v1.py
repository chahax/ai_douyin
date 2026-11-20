from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from scripts import creative_m31_flash_role_clients_v1 as mapper
from scripts import run_fresh_legal_full_flow_v1 as original
from src.content_factory import creative_flat_lineage_verifier_v1 as flat


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def native_parent(tmp_path):
    project, root = tmp_path, tmp_path / "parent"
    root.mkdir()
    code, source, claim = project / "guard.py", project / "source.json", project / "authority.json"
    code.write_text("# synthetic full guard implementation", encoding="utf-8")
    dump(source, {"tag": "劳动争议"})
    dump(claim, {"human_authorized": True})
    manifest = {"source.json": sha(source), "authority.json": sha(claim)}
    for rel in manifest:
        path = root / "source_at_dispatch" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((project / rel).read_bytes())
    starting = {"calls_started": 538, "reported_tokens": 10247607, "calls_with_known_usage": 536,
                "unknown_token_reservations": 93117, "pending_ordinals": [70, 160]}
    dump(root / "AUTHORIZATION.json", {"starting_spend": starting, "old_budget_reset": False})
    scope = {"schema": "goal_context_text_production/v6/user_scope", "grant_id": "native_fixture"}
    dump(root / "USER_SCOPE.json", scope)
    request = {"role": "writer", "model": mapper.WRITER_MODEL, "stage": "goal_plan",
        "messages": [{"role": "user", "content": "完整原文"}],
        "parameters": {"temperature": .4, "thinking": "adaptive", "max_completion_tokens": 16000},
        "structured_schema": {"type": "object", "properties": {"text": {"type": "string"}}}}
    output = {"text": "完整规划原文"}
    argument = json.dumps(output, ensure_ascii=False)
    payload = {"id": "native_unique_539", "model": request["model"], "usage": {"total_tokens": 5},
        "choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [{"type": "function",
            "function": {"name": mapper.TOOL_NAME, "arguments": argument}}]}}]}
    evidence = root / "call_evidence" / "call_539"
    evidence.mkdir(parents=True)
    identity = {"ordinal": 539, "label": "goal_plan_07", "request_sha256": flat.digest(request),
        "source_binding_sha256": flat.digest(manifest), "role": "writer", "model": request["model"]}
    identity_sha = flat.digest(identity)
    dump(evidence / "IDENTITY.json", {"identity": identity, "identity_sha256": identity_sha})
    wire = mapper.expected_wire_request(request)
    dump(evidence / "request_body.raw", wire)
    raw_request = (evidence / "request_body.raw").read_bytes()
    raw_request_sha = sha(evidence / "request_body.raw")
    dump(evidence / "REQUEST_BODY_MANIFEST.json", {"identity_sha256": identity_sha,
        "body_file": "request_body.raw", "body_complete": True, "raw_bytes_preserved": True,
        "credential_redacted": False, "stored_sha256": raw_request_sha, "original_sha256": raw_request_sha,
        "bytes": len(raw_request)})
    dump(evidence / "M31_WIRE_PREFLIGHT.json", {"schema": mapper.VERSION + "/outbound_proof",
        "identity_sha256": identity_sha, "logical_request_sha256": flat.digest(request),
        "expected_wire_sha256": flat.digest(wire), "actual_wire_sha256": flat.digest(wire),
        "original_body_sha256": raw_request_sha, "actual_request_body_sha256": raw_request_sha,
        "body_bytes": len(raw_request), "full_wire_equals_mapped_logical_request": True,
        "messages_sha256": flat.digest(request["messages"]), "structured_schema_sha256": flat.digest(request["structured_schema"]),
        "status": "wire_verified_before_send", "mapped_fields": sorted(wire), "SDK_max_retries": 0,
        "provider_endpoint_host": "api.minimax.cn", "verified_endpoint_sha256": flat.digest(["POST", "https://api.minimax.cn/v1/chat/completions"]),
        "writer_reasoning_effort": "medium", "server_stream_requested": False, "server_schema_guarantee": False,
        "new_provider_acceptance_verified": False, "provider_received_request": None, "calls_authorized_by_proof": False,
        "HTTP_follow_redirects": False, "endpoint_method": "POST", "endpoint_path": "/v1/chat/completions",
        "provider_endpoint_host_matched": True, "automatic_retry": False})
    dump(evidence / "response_body.raw", payload)
    raw = (evidence / "response_body.raw").read_bytes()
    raw_sha = sha(evidence / "response_body.raw")
    dump(evidence / "RESPONSE_BODY_MANIFEST.json", {"identity_sha256": identity_sha, "body_file": "response_body.raw",
        "stored_sha256": raw_sha, "original_sha256": raw_sha, "bytes": len(raw), "body_complete": True,
        "raw_bytes_preserved": True, "credential_redacted": False, "http_metadata": {"http_status_code": 200}})
    receipt = {"ordinal": 539, "label": "goal_plan_07", "request": request,
        "request_sha256": flat.digest(request), "source_binding_sha256": flat.digest(manifest),
        "token_reservation": 18000, "status": "contract_valid", "response_text": argument,
        "response_payload": payload, "output": output, "call_evidence": {"directory": "call_evidence/call_539", "identity_sha256": identity_sha},
        "response_metadata": {"http_status_code": 200, "response_body_complete": True, "raw_body_sha256": raw_sha,
            "finish_reason": "tool_calls", "total_tokens": 5, "output_mode": "tool_call",
            "requested_model": request["model"], "response_model": request["model"], "response_id": "native_unique_539"}}
    filename = "call_539_goal_plan_07.json"
    dump(root / filename, receipt)
    row = {"ordinal": 539, "label": receipt["label"], "receipt": filename, "token_reservation": 18000,
           "receipt_sha256": sha(root / filename)}
    ledger = {"starting_spend": starting, "max_total_tokens": None,
        "authorization_sha256": sha(root / "AUTHORIZATION.json"), "source_manifest": manifest,
        "model_configs": {"writer": {"model": request["model"]}}, "calls": [row],
        "automatic_retry": False, "old_budget_reset": False, "old_governance_migrated": False}
    dump(root / "CALL_LEDGER.json", ledger)
    known, outcome, tool = original.classify_receipt(receipt)
    task_request = {"provider_id": request["model"], "payload": request}
    task_result = {"claim_id": "one_claim", "request_sha256": flat.digest(task_request), "outcome": outcome,
        "result_known": known, "usage_known": True, "usage": {"unit": "reported_tokens", "amount": 5},
        "complete": True, "complete_end": True, "schema_tool_status": tool,
        "raw_receipt": {"encoding": "base64", "body": base64.b64encode(raw).decode(), "sha256": raw_sha, "http_status": 200},
        "output": {"ordinal": 539, "native_output": output}}
    gid = "call_" + flat.digest({"grant": scope["grant_id"], "label": receipt["label"]})[:24]
    with sqlite3.connect(root / "TASKS.sqlite3") as connection:
        connection.execute("CREATE TABLE attempts (graph_id,status,request,result,claim_id,request_sha,result_sha)")
        connection.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?)", (gid, outcome,
            json.dumps(task_request, ensure_ascii=False), json.dumps(task_result, ensure_ascii=False), "one_claim",
            flat.digest(task_request), flat.digest(task_result)))
    summary = {"effective_calls_started": 539, "effective_reported_tokens": 10247612,
        "effective_calls_with_known_usage": 537, "unknown_token_reservations": 93117,
        "historical_pending_ordinals": [70, 160], "old_budget_reset": False, "media_calls": 0}
    dump(root / "STATE.json", {"status": "halt_complete", "spend": summary})
    calls = []
    def guard():
        calls.append(True)
        json.loads((root / "CALL_LEDGER.json").read_text("utf-8"))
        list(root.glob("call_*.json"))
        assert sha(source) == manifest["source.json"]
        return deepcopy(summary)
    return {"project": project, "root": root, "source": source, "claim": claim, "code": code,
        "receipt": root / filename, "evidence": evidence, "summary": summary, "guard": guard, "guard_calls": calls}


def certificate(data, guard=None):
    return flat.build_lineage_certificate(data["project"], data["root"],
        certified_check=guard or data["guard"], expected_summary=data["summary"],
        dependency_paths=[data["root"] / "STATE.json"], guard_code_paths=[data["code"]])


def verify(value, **overrides):
    options = {"expected_certificate_sha256": flat.digest(value), "fresh_source_gate": lambda: {"blockers": []}}
    options.update(overrides)
    return flat.verify_lineage_certificate(value, **options)


def test_actual_native_request_response_and_sql_result_supported(native_parent):
    value = certificate(native_parent)
    result = verify(value)
    assert len(native_parent["guard_calls"]) == 1
    assert result["inherited"] == {"calls_started": 539, "reported_tokens": 10247612,
        "calls_with_known_usage": 537, "unknown_token_reservations": 93117, "pending_ordinals": [70, 160]}
    assert all(count == 1 for count in result["file_read_counts"].values())


@pytest.mark.parametrize("target", ["source", "claim", "receipt", "code"])
def test_bound_content_change_rejected(native_parent, target):
    value = certificate(native_parent)
    native_parent[target].write_bytes(native_parent[target].read_bytes() + b" ")
    with pytest.raises(flat.LineageVerificationError, match="SHA changed"):
        verify(value)


@pytest.mark.parametrize("filename", ["CALL_LEDGER.json", "AUTHORIZATION.json", "USER_SCOPE.json", "TASKS.sqlite3"])
def test_ledger_authority_model_and_task_bytes_rejected(native_parent, filename):
    value = certificate(native_parent)
    path = native_parent["root"] / filename
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(flat.LineageVerificationError, match="SHA changed"):
        verify(value)


@pytest.mark.parametrize("filename", ["response_body.raw", "request_body.raw", "IDENTITY.json", "M31_WIRE_PREFLIGHT.json"])
def test_native_artifacts_bound(native_parent, filename):
    value = certificate(native_parent)
    path = native_parent["evidence"] / filename
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(flat.LineageVerificationError, match="SHA changed"):
        verify(value)


def test_new_pending_ancestor_claim_rejected(native_parent):
    value = certificate(native_parent)
    dump(native_parent["root"] / "EXTRA_CLAIM.json", {"result": None})
    with pytest.raises(flat.LineageVerificationError, match="new/missing"):
        verify(value)


def test_new_epoch_no_mtime_or_permanent_hash_cache(native_parent):
    value = certificate(native_parent)
    first = verify(value)
    second = verify(value)
    assert first["file_read_counts"] == second["file_read_counts"]
    native_parent["source"].write_bytes(native_parent["source"].read_bytes() + b" ")
    with pytest.raises(flat.LineageVerificationError): verify(value)


@pytest.mark.parametrize("gate", [None, False, {}, {"blockers": ["expired"]}, {"blockers": None}])
def test_source_gate_failure_is_not_authority(native_parent, gate):
    value = certificate(native_parent)
    with pytest.raises(flat.LineageVerificationError, match="source/time gate"):
        verify(value, fresh_source_gate=lambda: gate)


def test_negative_exists_dependency_preserved(native_parent):
    missing = native_parent["project"] / "no_recovery" / "CLAIM.json"
    def guard():
        assert not missing.exists()
        return native_parent["guard"]()
    value = certificate(native_parent, guard)
    dump(missing, {"pending": True})
    with pytest.raises(flat.LineageVerificationError, match="existence/type"):
        verify(value)


def test_checkpoint_changes_and_write_attempt_fail(native_parent):
    def changing_guard():
        native_parent["source"].read_bytes()
        with pytest.raises(flat.LineageVerificationError, match="read-only"):
            native_parent["source"].write_text("changed", encoding="utf-8")
        return native_parent["guard"]()
    value = certificate(native_parent, changing_guard)
    verify(value)


def test_certificate_anchor_cannot_be_recomputed_by_caller(native_parent):
    value = certificate(native_parent)
    expected = flat.digest(value)
    changed = deepcopy(value)
    changed["inherited"]["reported_tokens"] = 0
    with pytest.raises(flat.LineageVerificationError, match="canonical SHA"):
        flat.verify_lineage_certificate(changed, expected_certificate_sha256=expected,
            fresh_source_gate=lambda: {"blockers": []})


def test_expected_start_does_not_reset_old_unknown(native_parent):
    value = certificate(native_parent)
    changed = deepcopy(value["inherited"])
    changed["pending_ordinals"] = []
    with pytest.raises(flat.LineageVerificationError, match="inherited accumulation"):
        verify(value, expected_inherited=changed)


def test_sql_unknown_result_rejected_before_certification(native_parent):
    with sqlite3.connect(native_parent["root"] / "TASKS.sqlite3") as connection:
        connection.execute("UPDATE attempts SET result=NULL")
    with pytest.raises(flat.LineageVerificationError, match="result unknown"):
        certificate(native_parent)


def test_file_path_certificate_uses_raw_byte_sha(native_parent):
    value = certificate(native_parent)
    path = native_parent["project"] / "new_entry" / "certificate.json"
    dump(path, value)
    result = flat.verify_lineage_certificate(path, expected_certificate_sha256=sha(path),
        fresh_source_gate=lambda: {"blockers": []})
    assert result["inherited"] == value["inherited"]


def test_cycle_rejects_conflicting_expectations_and_parses_once(tmp_path):
    path = tmp_path / "value.json"
    dump(path, {"value": "原始"})
    cycle = flat.VerificationCycle()
    cycle.verify(path, sha(path))
    cycle.json(path); cycle.json(path); cycle.sha(path)
    assert cycle.read_counts[str(path.resolve())] == 1
    with pytest.raises(flat.LineageVerificationError, match="conflicting"):
        cycle.verify(path, "0" * 64)
