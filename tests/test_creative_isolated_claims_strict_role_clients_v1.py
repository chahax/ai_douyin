"""New fixed selector through installed SDK/MockTransport; zero real sockets."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import httpx
import pytest
from jsonschema import Draft202012Validator

from scripts import creative_isolated_claims_strict_role_clients_v1 as adapter
from scripts.creative_call_evidence_v1 import CallEvidenceJournal, digest

KEY = "offline-isolated-claims-key"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError("no real sockets")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(adapter.core, "role_config", lambda role: SimpleNamespace(
        model=adapter.core.REVIEW_MODEL, api_key=KEY, base_url="https://api.deepseek.com/v1"))


def logical(kind="source_claims"):
    from scripts import creative_isolated_source_claims_v1 as native
    payload = {"actors": [{"id": "C01"}, {"id": "C02"}], "source_units": {"S0001": {}}}
    schema = native._claims_schema(payload) if kind == "source_claims" else native._comparison_schema(
        {"source_claims": {"claims": {"S0001#0": {}}}, "actual_ledger": {"source_steps": {"E:B01:0": {}}}})
    return adapter.bind_request({"role": "director", "model": adapter.core.REVIEW_MODEL, "stage": "full_review",
        "input_provenance": {"isolated_source_claims_version": adapter.NATIVE_VERSION, "stage_kind": kind},
        "parameters": {"max_completion_tokens": 16000, "temperature": .4, "thinking": "disabled"},
        "messages": [{"role": "system", "content": "offline contract boundary"}, {"role": "user", "content": "exact isolated source"}],
        "structured_schema": schema})


def reply(arguments='{"units":[{"parts":[{"tag":"context","text":"字","mode":"background"}]}]}'):
    return json.dumps({"id": "offline-response", "model": adapter.core.REVIEW_MODEL,
        "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
            "tool_calls": [{"id": "offline-tool", "type": "function", "function": {"name": adapter.TOOL_NAME, "arguments": arguments}}]}}],
        "usage": {"prompt_tokens": 19, "completion_tokens": 11, "total_tokens": 30}}, ensure_ascii=False).encode()


def invoke(tmp_path, request, response, *, mutate=None):
    sent, manifest = [], {"offline_source": "fixed"}
    identity = {"ordinal": 1, "label": "source_claims_14", "request_sha256": digest(request),
        "source_binding_sha256": digest(manifest), "role": request["role"], "model": request["model"]}
    journal = CallEvidenceJournal(tmp_path / "call_evidence/call_001", identity)
    def handler(outgoing):
        sent.append(outgoing.read())
        return httpx.Response(200, content=response)
    def factory(**kwargs):
        if mutate:
            def hook(outgoing):
                value = json.loads(outgoing.read()); mutate(value)
                raw = json.dumps(value, ensure_ascii=False).encode()
                outgoing.stream = httpx.ByteStream(raw); outgoing._content = raw
                outgoing.headers["content-length"] = str(len(raw))
            kwargs["event_hooks"]["request"].insert(0, hook)
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)
    client = adapter.make_client_factory(request, strict_claims=True, http_client_factory=factory)()
    def call(): return client.call("director", request["messages"], max_tokens=16000, temperature=.4,
        thinking="disabled", structured_schema=request["structured_schema"], evidence=journal)
    return call, sent, journal, manifest


@pytest.mark.parametrize("kind", ["source_claims", "claims_comparison"])
def test_actual_fixed_small_contracts_compile_and_ordinary_cannot_be_fallback(kind):
    request = logical(kind); before = deepcopy(request)
    manifest, wire = adapter.schema_compilation_manifest(request), adapter.expected_wire_request(request)
    assert wire["tools"][0]["function"]["strict"] is True and wire["max_tokens"] == 16000
    assert manifest["original_contract_sha256"] == digest(request["structured_schema"])
    assert manifest["selector_policy_version"] == adapter.VERSION and manifest["server_schema_guarantee"] is False
    assert request == before and adapter.bind_request(request) == request
    with pytest.raises(adapter.EvidenceCallError, match="NO_FALLBACK"): adapter.make_client_factory(request)
    changed = deepcopy(request); changed["stage"] = "goal_audit"
    with pytest.raises(adapter.EvidenceCallError, match="FIXED_CONTRACT"): adapter.expected_wire_request(changed)
    changed = deepcopy(request); changed["structured_schema"]["allOf"] = [{"required": [next(iter(changed["structured_schema"]["properties"]))]}]
    with pytest.raises(ValueError): adapter.expected_wire_request(changed)
    changed = deepcopy(request); changed["input_provenance"].pop("source_protocol_binding")
    with pytest.raises(adapter.EvidenceCallError, match="BINDING"): adapter.StrictIsolatedClaimsRoleClients(expected_request=changed)


def test_actual_sdk_new_selector_raw_receipt_verifier_and_policy_tamper(tmp_path):
    request, raw = logical(), reply()
    call, sent, journal, manifest = invoke(tmp_path, request, raw)
    result = call(); assert len(sent) == 1
    assert json.loads(sent[0]) == adapter.expected_wire_request(request)
    assert result.metadata["transport_version"] == adapter.core.VERSION
    assert result.metadata["selector_policy_version"] == adapter.VERSION
    assert result.metadata["server_schema_guarantee"] is False and result.metadata["total_tokens"] == 30
    assert (journal.root / "response_body.raw").read_bytes() == raw
    assert KEY.encode() not in b"".join(path.read_bytes() for path in journal.root.iterdir())
    receipt = {"ordinal": 1, "label": "source_claims_14", "request": request, "request_sha256": digest(request),
        "source_binding_sha256": digest(manifest), "token_reservation": 16000, "response_text": result.text,
        "response_payload": result.response_payload, "response_metadata": result.metadata,
        "output": json.loads(result.text), "status": "contract_valid", "automatic_retry": False,
        "call_evidence": {"directory": str(journal.root), "identity_sha256": journal.identity_sha256}}
    Draft202012Validator(request["structured_schema"]).validate(receipt["output"])
    path = tmp_path / "call_001_source_claims_14.json"; path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
    row = {"receipt": path.name, "receipt_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "ordinal": 1,
        "label": receipt["label"], "token_reservation": 16000}
    assert adapter.verify_original_receipt(tmp_path, row, manifest) == receipt
    proof_path = journal.root / "DEEPSEEK_STRICT_WIRE_PREFLIGHT.json"
    proof = json.loads(proof_path.read_text(encoding="utf-8")); proof["calls_authorized_by_proof"] = True
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    with pytest.raises(ValueError, match="wire differs"): adapter.verify_original_receipt(tmp_path, row, manifest)
    with pytest.raises(adapter.EvidenceCallError, match="ALREADY_USED"): call()


def test_actual_serialized_drift_is_blocked_before_send(tmp_path):
    call, sent, journal, _ = invoke(tmp_path, logical(), reply(), mutate=lambda value: value.update(max_tokens=16001))
    with pytest.raises(adapter.EvidenceCallError, match="SERIALIZED_WIRE_MISMATCH"): call()
    assert not sent and (journal.root / "BLOCKED_OUTBOUND_MANIFEST.json").is_file()


def test_invalid_native_json_retained_once_without_repair_or_fallback(tmp_path):
    call, sent, journal, _ = invoke(tmp_path, logical(), reply('{"units":{}}}'))
    with pytest.raises(adapter.EvidenceCallError, match="STRUCTURED_TOOL_JSON_INVALID") as caught: call()
    assert len(sent) == 1 and caught.value.response_metadata["total_tokens"] == 30
    assert caught.value.response_text == '{"units":{}}}'
    assert caught.value.response_metadata["selector_policy_version"] == adapter.VERSION
    assert (journal.root / "response_body.raw").read_bytes() == reply('{"units":{}}}')
    with pytest.raises(adapter.EvidenceCallError, match="ALREADY_USED"): call()
