"""Focused settled-session accounting checks. No provider or admission calls."""
from copy import deepcopy
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import socket

import pytest

from scripts import creative_session_spend_anchor_v1 as anchor
from src.content_factory.creative_counted_execution_v1 import CountedExecution

ACTUAL = anchor.PROJECT / "data/production_trials/fresh_source_text_session_20261015/round_01"


@pytest.fixture(autouse=True)
def readonly_offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("readonly accounting must not dispatch or require old round admission")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(CountedExecution, "assert_dispatch_allowed", deny)


@pytest.fixture
def records():
    ledger = anchor.read(ACTUAL / "CALL_LEDGER.json")
    return [ledger, [anchor.read(ACTUAL / row["receipt"]) for row in ledger["calls"]],
        anchor.read(ACTUAL / "STATE.json"), anchor.read(ACTUAL / "PRODUCTION_FREEZE.json"),
        anchor.read(ACTUAL / "USER_SCOPE.json"), anchor.read(ACTUAL / "AUTHORIZATION.json"), deepcopy(ledger["starting_spend"])]


def test_actual621_known_native_content_rejection_keeps_all_consumption(records):
    result = anchor.validate_records(*records)
    assert result == {"calls_started": 621, "reported_tokens": 12967256, "calls_with_known_usage": 619,
        "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}


@pytest.mark.parametrize("fault", ["nonterminal", "unknown", "truncated", "unknown_usage", "bool_usage",
    "reset_inherited", "reset_pending", "terminal_usage", "terminal_bool", "duplicate_call", "false_media"])
def test_unsafe_or_inconsistent_terminal_accounting_rejected(records, fault):
    ledger, receipts, state, freeze, scope, auth, inherited = records
    receipt = receipts[0]
    if fault == "nonterminal": state["status"] = "prepared"
    elif fault == "unknown": receipt["status"] = "outcome_unknown"
    elif fault == "truncated": receipt["response_metadata"]["finish_reason"] = "length"
    elif fault == "unknown_usage": receipt["response_metadata"]["total_tokens"] = None
    elif fault == "bool_usage": receipt["response_metadata"]["completion_tokens"] = True
    elif fault == "reset_inherited": ledger["starting_spend"]["reported_tokens"] = 0
    elif fault == "reset_pending": inherited["pending_ordinals"] = []
    elif fault == "terminal_usage": state["spend"]["effective_reported_tokens"] -= 1
    elif fault == "terminal_bool": state["spend"]["new_calls"] = True
    elif fault == "duplicate_call": ledger["calls"].append(deepcopy(ledger["calls"][0])); receipts.append(deepcopy(receipt))
    else: scope["media_authorized"] = True
    with pytest.raises(ValueError): anchor.validate_records(*records)


def test_accounting_has_no_fixed621_future_call_count(records):
    ledger, receipts, state, freeze, scope, auth, inherited = records
    inherited.update(calls_started=10, reported_tokens=1000, calls_with_known_usage=8,
        pending_ordinals=[1, 2], unknown_token_reservations=33)
    for obj, key in ((ledger, "starting_spend"), (freeze, "inherited"), (scope, "inherited"), (auth, "starting_spend")):
        obj[key] = deepcopy(inherited)
    ledger["calls"].append(deepcopy(ledger["calls"][0])); receipts.append(deepcopy(receipts[0]))
    for index, (row, receipt) in enumerate(zip(ledger["calls"], receipts), 11):
        row.update(ordinal=index, label="whole_plan_" + str(index))
        receipt.update(ordinal=index, label=row["label"], request_sha256=str(index) * 32)
        receipt["response_metadata"]["response_id"] = "offline-known-" + str(index)
    state["spend"].update(new_calls=2, effective_calls_started=12, new_reported_tokens=51464,
        effective_reported_tokens=52464, unknown_token_reservations=33, inherited_unknown_token_reservations=33,
        historical_pending_ordinals=[1, 2], new_calls_with_known_usage=2, effective_calls_with_known_usage=10)
    state["spend"]["stage_calls"]["goal_plan"] = 2
    assert anchor.validate_records(*records) == {"calls_started": 12, "reported_tokens": 52464,
        "calls_with_known_usage": 10, "pending_ordinals": [1, 2], "unknown_token_reservations": 33}


def copied_receipt(tmp_path, records):
    ledger, receipts, *_ = records
    row, receipt = deepcopy(ledger["calls"][0]), deepcopy(receipts[0])
    root = tmp_path / "native_copy"; root.mkdir()
    rel = Path(receipt["call_evidence"]["directory"])
    shutil.copytree(ACTUAL / rel, root / rel)
    path = root / row["receipt"]
    path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
    row["receipt_sha256"] = anchor.sha_file(path)
    return root, row, receipt, ledger["source_manifest"]


@pytest.mark.parametrize("fault", [None, "request_raw", "response_raw", "parsed_output", "sdk_retries"])
def test_original_sdk_wire_response_tool_and_no_retry_evidence(tmp_path, records, fault):
    root, row, receipt, manifest = copied_receipt(tmp_path, records)
    directory = root / receipt["call_evidence"]["directory"]
    if fault in ("request_raw", "response_raw"):
        path = directory / ("request_body.raw" if fault == "request_raw" else "response_body.raw")
        path.write_bytes(path.read_bytes() + b" ")
    elif fault == "parsed_output":
        receipt["output"]["whole_plan"]["premise"] += " altered"
        path = root / row["receipt"]; path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
        row["receipt_sha256"] = anchor.sha_file(path)
    elif fault == "sdk_retries":
        path = directory / "M31_WIRE_PREFLIGHT.json"; proof = anchor.read(path); proof["SDK_max_retries"] = 1
        path.write_text(json.dumps(proof), encoding="utf-8")
    if fault is None:
        assert anchor.verify_original_receipt(root, row, manifest) == receipt
    else:
        with pytest.raises(ValueError): anchor.verify_original_receipt(root, row, manifest)


def test_source6_v5_strict_projection_wire_is_supported_without_legacy_v27(tmp_path):
    request = {"stage": "goal_audit", "role": "director", "model": "deepseek-flash",
        "messages": [{"role": "user", "content": "offline source6 evidence fixture"}],
        "parameters": {"temperature": .4, "thinking": "disabled", "max_completion_tokens": 24000},
        "structured_schema": {"type": "object", "properties": {"schema": {"const": anchor.strict.SOURCE_VERSION},
            "speech_act_by_ref": {"type": "object", "properties": {"G001": {"enum": ["F", "L", "U"]}},
                "required": ["G001"], "additionalProperties": False}},
            "required": ["schema", "speech_act_by_ref"], "additionalProperties": False}, "input_provenance": {}}
    request["input_provenance"]["source_protocol_binding"] = anchor.strict.protocol_binding(request)
    wire = anchor.strict.expected_wire_request(request)
    compilation = anchor.strict.schema_compilation_manifest(request)
    identity = "a" * 64
    raw = json.dumps(wire, ensure_ascii=False).encode()
    raw_sha = hashlib.sha256(raw).hexdigest()
    proof = {"schema": anchor.strict.VERSION + "/outbound_proof", "status": "wire_verified_before_send",
        "identity_sha256": identity, "logical_request_sha256": anchor.digest(request), "expected_wire_sha256": anchor.digest(wire),
        "actual_wire_sha256": anchor.digest(wire), "actual_request_body_sha256": raw_sha, "body_bytes": len(raw),
        "max_wire_utf8_bytes": 600000, "full_wire_equals_mapped_logical_request": True, "mapped_fields": sorted(wire),
        "messages_sha256": anchor.digest(request["messages"]), "structured_schema_sha256": anchor.digest(request["structured_schema"]),
        "provider_endpoint_host": "api.deepseek.com", "endpoint_method": "POST", "endpoint_path": "/beta/chat/completions",
        "verified_endpoint_sha256": anchor.digest(["POST", "https://api.deepseek.com/beta/chat/completions"]),
        "writer_reasoning_effort": None, "SDK_max_retries": 0, "HTTP_follow_redirects": False, "server_stream_requested": False,
        "server_schema_guarantee": False, "new_provider_acceptance_verified": False, "calls_authorized_by_proof": False,
        "automatic_retry": False, "provider_received_request": None,
        "source_protocol_binding_sha256": anchor.digest(request["input_provenance"]["source_protocol_binding"]),
        "schema_compilation_manifest_sha256": anchor.digest(compilation),
        "original_contract_sha256": anchor.digest(request["structured_schema"]),
        "service_schema_sha256": anchor.digest(wire["tools"][0]["function"]["parameters"]),
        "function_strict": True, "server_strict_schema_requested": True, "original_local_contract_validation_required": True}
    manifest = {"body_file": "request_body.raw", "identity_sha256": identity, "body_complete": True,
        "raw_bytes_preserved": True, "credential_redacted": False, "stored_sha256": raw_sha,
        "original_sha256": raw_sha, "bytes": len(raw)}
    (tmp_path / "request_body.raw").write_bytes(raw)
    for name, value in (("REQUEST_BODY_MANIFEST", manifest), ("DEEPSEEK_STRICT_WIRE_PREFLIGHT", proof),
        ("DEEPSEEK_STRICT_SCHEMA_MANIFEST", compilation)):
        (tmp_path / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    assert anchor._wire(anchor.Reader(), tmp_path, request, identity) == (wire, True)
    proof["schema"] = "creative_deepseek_strict_role_clients/v999/outbound_proof"
    (tmp_path / "DEEPSEEK_STRICT_WIRE_PREFLIGHT.json").write_text(json.dumps(proof), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported strict"):
        anchor._wire(anchor.Reader(), tmp_path, request, identity)


def test_actual621_build_and_reverify_do_not_need_active_old_round_or_write_claims():
    before = {str(p): anchor.sha_file(p) for p in ACTUAL.rglob("*") if p.is_file()}
    result = anchor.build_anchor(ACTUAL)
    verified = anchor.verify_anchor(result, expected_anchor_sha256=anchor.digest(result))
    assert verified["inherited"]["calls_started"] == 621
    assert verified["root"] == str(ACTUAL)
    assert verified["whole_goal_candidates_used"] == 1
    assert verified["latest_native_goal_receipt"]["ordinal"] == 621
    assert verified["parent_identity"]["end_ordinal"] == 621
    assert not verified["authorizes_new_dispatch"] and not result["current_source_freshness_checked"]
    assert not result["creates_successor_claim"] and result["new_reported_tokens"] == 25732
    assert before == {str(p): anchor.sha_file(p) for p in ACTUAL.rglob("*") if p.is_file()}


def test_no_result_file_is_required_when_original_state_and_ledger_are_complete(monkeypatch):
    original = Path.exists
    monkeypatch.setattr(Path, "exists", lambda path: False if path.resolve() == ACTUAL / "RESULT.json" else original(path))
    result = anchor.build_anchor(ACTUAL)
    assert result["inherited"]["reported_tokens"] == 12967256
    assert str(ACTUAL / "RESULT.json") not in result["verified_files"]


def test_changed_anchor_rejected_even_if_attacker_recomputes_its_canonical_digest(monkeypatch):
    original = {"schema": anchor.VERSION, "root": str(ACTUAL), "inherited": {"calls_started": 621}}
    monkeypatch.setattr(anchor, "build_anchor", lambda *a, **kw: deepcopy(original))
    changed = deepcopy(original); changed["inherited"]["calls_started"] = 620
    with pytest.raises(ValueError, match="SHA/schema"):
        anchor.verify_anchor(changed, expected_anchor_sha256=anchor.digest(original))
    with pytest.raises(ValueError, match="changed since"):
        anchor.verify_anchor(changed, expected_anchor_sha256=anchor.digest(changed))


def test_unknown_session_schema_is_rejected_without_live_gates(monkeypatch):
    original = anchor.Reader.json
    def changed(reader, path):
        value = original(reader, path)
        if Path(path).resolve() == ACTUAL / "PRODUCTION_FREEZE.json":
            value["schema"] = "creative_fresh_source_session/v999/freeze"
        return value
    monkeypatch.setattr(anchor.Reader, "json", changed)
    with pytest.raises(ValueError, match="unsupported or mismatched"):
        anchor.build_anchor(ACTUAL)


def test_known_semantic_uncertainty_preserves_consumption(records):
    records[2]["status"] = "halt_goal_audit_uncertain"
    assert anchor.validate_records(*records)["reported_tokens"] == 12967256


def test_durable_task_unknown_result_rejected_even_with_recomputed_sql_digest(tmp_path, records):
    ledger, receipts, *_ = records
    path = tmp_path / "TASKS.sqlite3"
    shutil.copyfile(ACTUAL / "TASKS.sqlite3", path)
    with sqlite3.connect(path) as conn:
        claim, raw = conn.execute("SELECT claim_id,result FROM attempts").fetchone()
        result = json.loads(raw); result["result_known"] = False
        conn.execute("UPDATE attempts SET result=?,result_sha=? WHERE claim_id=?",
            (json.dumps(result, ensure_ascii=False), anchor.digest(result), claim))
    conn.close()
    reader = anchor.Reader()
    original = reader.bytes
    reader.bytes = lambda source: path.read_bytes() if Path(source).resolve() == ACTUAL / "TASKS.sqlite3" else original(source)
    with pytest.raises(ValueError, match="durable original claim/result differs"):
        anchor._tasks(reader, ACTUAL, ledger, receipts, "fresh_source_text_session_20261015_01")


def _synthetic_v2_session(tmp_path, monkeypatch, records):
    """Child integration fixture; ancestor admission is explicitly mocked.

    Actual621 ancestry has its separate full read-only test above. No original
    file, production claim, provider or network resource is mutated here.
    """
    ledger, receipts, state, _, scope, auth, _ = deepcopy(records)
    root, parent = tmp_path / "session", tmp_path / "parent"
    root.mkdir(); parent.mkdir()
    def put(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    parent_spend = {"calls_started": 621, "reported_tokens": 12967256, "calls_with_known_usage": 619,
        "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
    for name, value in (("STATE", state), ("CALL_LEDGER", ledger), ("PRODUCTION_FREEZE", {"offline_ancestor": True})):
        put(parent / (name + ".json"), value)
    identity = {"root": str(parent), "terminal_state_sha256": anchor.sha_file(parent / "STATE.json"),
        "native_ledger_sha256": anchor.sha_file(parent / "CALL_LEDGER.json"),
        "production_freeze_sha256": anchor.sha_file(parent / "PRODUCTION_FREEZE.json"), "end_ordinal": 621}
    parent_anchor = {"schema": anchor.VERSION, "root": str(parent), "inherited": parent_spend,
        "parent_identity": identity, "parent_identity_sha256": anchor.digest(identity),
        "lineage_whole_plan_candidates_used": 1, "inherited_whole_goal_candidates_used": 30}
    parent_path = tmp_path / "parent_anchor.json"; put(parent_path, parent_anchor)
    canonical = anchor.digest(parent_anchor)
    grant = "offline_v2_session_anchor"
    old_config = anchor.read(ACTUAL / "SESSION_CONFIG.json")
    profile = anchor.read(old_config["profile_path"])
    profile_path, auth_path = tmp_path / "profile.json", tmp_path / "authorization.json"
    put(profile_path, profile)
    receipt = receipts[0]
    receipt.update(ordinal=622, label="whole_plan_02")
    receipt["response_payload"]["id"] = receipt["response_metadata"]["response_id"] = "offline-v2-known-response-622"
    response_raw = json.dumps(receipt["response_payload"], ensure_ascii=False).encode()
    response_sha = hashlib.sha256(response_raw).hexdigest()
    receipt["response_metadata"]["raw_body_sha256"] = response_sha
    inputs = {"fixture": "offline v2 consumption inheritance"}
    scope.update(schema="creative_fresh_source_session/v2/derived_authorization", root=str(root), grant_id=grant,
        anchor_sha256=canonical, inherited=deepcopy(parent_spend), inputs_sha256=anchor.digest(inputs),
        shared_run_claim_protocol="creative_fresh_source_session/v1/run_claim")
    put(auth_path, scope)
    config = {"root": str(root), "anchor_path": str(parent_path), "anchor_sha256": canonical,
        "grant_id": grant, "profile_path": str(profile_path), "authorization_path": str(auth_path)}
    first = {"request": receipt["request"], "request_sha256": receipt["request_sha256"]}
    for name, value in (("SESSION_CONFIG", config), ("INPUTS", inputs), ("INPUT_EVIDENCE", {"offline": True}),
        ("FIRST_REQUEST_PREVIEW", first), ("USER_SCOPE", scope)):
        put(root / (name + ".json"), value)
    auth_sha = anchor.sha_file(auth_path)
    claim_path = tmp_path / "data/creative_fresh_background_claims" / grant / "CLAIM.json"
    claim = {"schema": "creative_fresh_source_session/v2/claim", "root": str(root), "grant_id": grant,
        "authorization_sha256": auth_sha, "old_budget_reset": False}
    put(claim_path, claim)
    successor = tmp_path / "data/creative_consumption_successors" / canonical / "CLAIM.json"
    parent_claim = tmp_path / "data/creative_consumption_successors/by_parent_session" / anchor.digest(os.path.normcase(str(parent))) / "CLAIM.json"
    binding = {"schema": "creative_fresh_source_session/v2/successor_claim", "anchor_sha256": canonical,
        "parent_session_root": str(parent), "parent_state_sha256": identity["terminal_state_sha256"],
        "parent_ledger_sha256": identity["native_ledger_sha256"], "parent_end_ordinal": 621,
        "parent_identity": identity, "parent_identity_sha256": anchor.digest(identity), "root": str(root),
        "grant_id": grant, "authorization_sha256": auth_sha, "old_budget_reset": False}
    put(successor, binding); put(parent_claim, binding)
    files = {str(path): anchor.sha_file(path) for path in [*(root / (n + ".json") for n in
        ("SESSION_CONFIG", "INPUTS", "INPUT_EVIDENCE", "FIRST_REQUEST_PREVIEW", "USER_SCOPE")),
        profile_path, parent_path, auth_path, successor, parent_claim]}
    freeze = {"schema": "creative_fresh_source_session/v2/freeze", "files": files,
        "claim_sha256": anchor.sha_file(claim_path), "inherited": parent_spend, "inputs_sha256": anchor.digest(inputs),
        "shared_run_claim_protocol": "creative_fresh_source_session/v1/run_claim",
        "parent_successor_claim": {"path": str(parent_claim), "sha256": anchor.sha_file(parent_claim), "binding": binding}}
    put(root / "PRODUCTION_FREEZE.json", freeze)
    for path in files:
        target = root / "source_at_dispatch" / Path(path).relative_to(tmp_path)
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
    manifest = {Path(path).relative_to(tmp_path).as_posix(): value for path, value in files.items()}
    receipt["source_binding_sha256"] = anchor.digest(manifest)
    ident = {"ordinal": 622, "label": "whole_plan_02", "request_sha256": receipt["request_sha256"],
        "source_binding_sha256": receipt["source_binding_sha256"], "role": "writer", "model": receipt["request"]["model"]}
    ident_sha = anchor.digest(ident)
    directory = root / "call_evidence/call_622"
    shutil.copytree(ACTUAL / receipts[0]["call_evidence"]["directory"], directory)
    receipt["call_evidence"] = {"directory": "call_evidence/call_622", "identity_sha256": ident_sha}
    put(directory / "IDENTITY.json", {"schema": "creative_call_evidence/v1", "identity": ident, "identity_sha256": ident_sha})
    for path in directory.glob("*.json"):
        if path.name == "IDENTITY.json": continue
        value = anchor.read(path); value["identity_sha256"] = ident_sha
        if path.name == "RESPONSE_BODY_MANIFEST.json": value.update(stored_sha256=response_sha, original_sha256=response_sha, bytes=len(response_raw))
        put(path, value)
    (directory / "response_body.raw").write_bytes(response_raw)
    row = deepcopy(ledger["calls"][0]); row.update(ordinal=622, label="whole_plan_02", receipt="call_622_whole_plan_02.json")
    put(root / row["receipt"], receipt); row["receipt_sha256"] = anchor.sha_file(root / row["receipt"])
    ledger.update(starting_spend=parent_spend, calls=[row], source_manifest=manifest)
    auth["starting_spend"] = parent_spend; put(root / "AUTHORIZATION.json", auth)
    ledger["authorization_sha256"] = anchor.sha_file(root / "AUTHORIZATION.json")
    put(root / "CALL_LEDGER.json", ledger)
    put(root / "requests/whole_plan_02.json", first)
    put(root / "RUN_CLAIM.json", {"schema": "creative_fresh_source_session/v1/run_claim", "automatic_restart": False})
    put(root / "DISPATCH_POLICY.json", {"schema": "creative_fresh_source_session/v2/runtime_policy", "profile": profile,
        "stage_limits": scope["stage_limits"], "automatic_retry": False, "old_budget_reset": False, "media_authorized": False})
    state.update(schema="creative_fresh_source_session/v2/state", receipt_ordinal=622)
    state["spend"].update(effective_calls_started=622, effective_reported_tokens=12992988, effective_calls_with_known_usage=620)
    put(root / "STATE.json", state)
    database = root / "TASKS.sqlite3"; shutil.copyfile(ACTUAL / "TASKS.sqlite3", database)
    conn = sqlite3.connect(database); conn.row_factory = sqlite3.Row; conn.execute("PRAGMA journal_mode=DELETE")
    old_gid, definition = conn.execute("SELECT graph_id,definition FROM graphs").fetchone()
    gid = "call_" + anchor.digest([grant, receipt["label"]])[:24]
    graph = json.loads(definition); graph["graph_id"] = gid
    graph["nodes"][0]["input"]["source_manifest"] = anchor.digest(manifest)
    graph["nodes"][1]["input"]["label"] = receipt["label"]
    source_input_sha = anchor.digest(graph["nodes"][0]["input"])
    source_sha = anchor.digest({"source": source_input_sha})
    bindings = [{"node_id": "source", "revision": 1, "input_sha256": source_input_sha, "output_sha256": source_input_sha}]
    for table in ("nodes", "revisions", "attempts", "authorizations"):
        conn.execute("UPDATE " + table + " SET graph_id=?", (gid,))
    conn.execute("UPDATE graphs SET graph_id=?,definition=?,sha=?", (gid, json.dumps(graph), anchor.digest(graph)))
    for node in graph["nodes"]:
        body = node["input"]; output = body if node["node_id"] == "source" else None
        conn.execute("UPDATE revisions SET input=?,input_sha=?,output=?,output_sha=? WHERE node_id=?",
            (json.dumps(body), anchor.digest(body), json.dumps(output) if output is not None else None,
             anchor.digest(output) if output is not None else None, node["node_id"]))
    grant_body = json.loads(conn.execute("SELECT body FROM authorizations").fetchone()[0])
    grant_body.update(authorization_id=gid + ":scope", graph_id=gid, source_sha256=source_sha,
        evidence_ref=str(root / "USER_SCOPE.json") + "#goal_plan", evidence_sha256=anchor.sha_file(root / "USER_SCOPE.json"))
    conn.execute("UPDATE authorizations SET authorization_id=?,body=?,sha=?", (gid + ":scope", json.dumps(grant_body), anchor.digest(grant_body)))
    attempt = dict(conn.execute("SELECT * FROM attempts").fetchone()); result = json.loads(attempt["result"])
    result["output"]["ordinal"] = 622
    result["raw_receipt"].update(body=base64.b64encode(response_raw).decode(), sha256=response_sha)
    claim_identity = {"graph_id": gid, "node_id": "result", "revision": 1, "request_sha256": attempt["request_sha"],
        "source_sha256": source_sha, "bindings": bindings}
    conn.execute("UPDATE attempts SET authorization_id=?,identity_sha=?,bindings=?,result=?,result_sha=?",
        (gid + ":scope", anchor.digest(claim_identity), json.dumps(bindings), json.dumps(result), anchor.digest(result)))
    conn.commit(); conn.close()
    monkeypatch.setattr(anchor, "PROJECT", tmp_path)
    def ancestor(value, *, expected_sha256, session_version, ancestors):
        assert session_version == "creative_fresh_source_session/v2" and anchor.digest(value) == expected_sha256 == canonical
        return {"verified": True, "inherited": deepcopy(parent_spend)}
    monkeypatch.setattr(anchor, "_verify_parent", ancestor)
    return root, freeze, parent_claim


def test_v2_settled_session_inherits_parent_consumption_and_rechecks_two_claims(tmp_path, monkeypatch, records):
    root, freeze, parent_claim = _synthetic_v2_session(tmp_path, monkeypatch, records)
    result = anchor.build_anchor(root)
    assert result["inherited"]["calls_started"] == 622 and result["inherited"]["reported_tokens"] == 12992988
    assert result["whole_goal_candidates_used"] == 2 and result["latest_native_goal_receipt"]["ordinal"] == 622
    assert result["session_schema"] == "creative_fresh_source_session/v2"
    # Replacing only the real-parent claim cannot create a second successor.
    changed = anchor.read(parent_claim); changed["root"] = str(tmp_path / "different_successor")
    parent_claim.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="frozen file changed|successor claims differ"):
        anchor.build_anchor(root)
