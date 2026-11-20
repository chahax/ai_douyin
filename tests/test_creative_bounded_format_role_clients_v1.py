"""Final SDK wire evidence and strict acceptance; MockTransport only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import httpx
import pytest

from scripts import creative_bounded_format_role_clients_v1 as clients
from scripts.creative_call_evidence_v1 import CallEvidenceJournal


SCHEMA = {"type": "object", "additionalProperties": False,
          "properties": {"payload_json": {"type": "string"}}, "required": ["payload_json"]}
KEY = "offline-only-credential-do-not-publish"
ACTUAL_501 = Path("data/production_revisions/selected_script_video_trial_20261011/script487_continuation_v2/call_evidence/call_501/response_body.raw")


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("bounded-format test cannot use a network")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(clients, "role_config", lambda role: SimpleNamespace(
        model="MiniMax-M3" if role == "writer" else "deepseek-chat",
        api_key=KEY, base_url="https://offline.invalid/v1"))


def original_reply(role="writer", *, tools=True):
    message = {"role": "assistant", "content": None}
    if tools:
        message["tool_calls"] = [{"id": "offline-tool-1", "type": "function", "function": {
            "name": clients.TOOL_NAME, "arguments": '{"payload_json":"{}"}'}}]
    else:
        message["content"] = '{"payload_json":"{}"}'
    return json.dumps({"id": "offline-response-1", "model": "MiniMax-M3" if role == "writer" else "deepseek-chat",
                       "choices": [{"index": 0, "finish_reason": "tool_calls" if tools else "stop", "message": message}],
                       "usage": {"prompt_tokens": 13, "completion_tokens": 7, "total_tokens": 20},
                       "base_resp": {"status_code": 0}}, ensure_ascii=False).encode()


def setup_client(tmp_path, handler):
    evidence = CallEvidenceJournal(tmp_path / "call", {"ordinal": 1, "request_identity": "offline fixture"})
    http_clients = []
    def factory(**kwargs):
        result = httpx.Client(transport=httpx.MockTransport(handler), **kwargs)
        http_clients.append(result)
        return result
    return clients.BoundedFormatRoleClients(http_client_factory=factory), evidence, http_clients


@pytest.mark.parametrize("role", ["writer", "director"])
def test_actual_sdk_serialized_body_and_role_policy(tmp_path, role):
    sent = []
    reply = original_reply(role)
    def handler(request):
        sent.append(request.read())
        assert request.headers["authorization"] == "Bearer " + KEY
        return httpx.Response(200, content=reply, headers={"x-request-id": "offline-response-id"})
    client, evidence, http_clients = setup_client(tmp_path, handler)
    messages = [{"role": "system", "content": "完整结果"}, {"role": "user", "content": "current source"}]
    old_messages, old_schema = deepcopy(messages), deepcopy(SCHEMA)
    result = client.call(role, messages, max_tokens=6000, temperature=.4,
                         thinking="disabled", structured_schema=SCHEMA,
                         writer_model="MiniMax-M3" if role == "writer" else None, evidence=evidence)
    assert len(sent) == 1
    wire = json.loads(sent[0])
    assert wire["messages"] == messages and wire["temperature"] == .4
    assert wire["thinking"] == {"type": "disabled"}
    assert wire["tools"][0]["type"] == "function"
    assert wire["tools"][0]["function"]["parameters"] == SCHEMA
    assert "strict" not in wire["tools"][0]["function"] and "stream" not in wire
    if role == "writer":
        assert "tool_choice" not in wire and wire["max_completion_tokens"] == 6000
    else:
        assert wire["tool_choice"] == {"type": "function", "function": {"name": clients.TOOL_NAME}}
        assert wire["max_tokens"] == 6000
    stored = (evidence.root / "request_body.raw").read_bytes()
    manifest = json.loads((evidence.root / "REQUEST_BODY_MANIFEST.json").read_text(encoding="utf-8"))
    assert stored == sent[0]
    assert manifest["identity_sha256"] == evidence.identity_sha256
    assert manifest["original_sha256"] == manifest["stored_sha256"] == hashlib.sha256(sent[0]).hexdigest()
    assert manifest["body_complete"] is True and manifest["raw_bytes_preserved"] is True
    assert manifest["provider_received_request"] is None and manifest["contains_request_headers"] is False
    assert manifest["tool_choice_policy"] == clients.tool_choice_policy(role)
    assert result.text == '{"payload_json":"{}"}' and result.metadata["total_tokens"] == 20
    assert result.response_payload == json.loads(reply)
    assert (evidence.root / "response_body.raw").read_bytes() == reply
    assert messages == old_messages and SCHEMA == old_schema
    assert http_clients[0].is_closed
    all_saved = b"".join(p.read_bytes() for p in evidence.root.iterdir())
    assert KEY.encode() not in all_saved and b"Authorization" not in all_saved


def test_actual501_content_only_is_not_converted_or_retried(tmp_path):
    original = ACTUAL_501.read_bytes()
    sends = []
    def handler(request):
        sends.append(request.read())
        return httpx.Response(200, content=original)
    client, evidence, _ = setup_client(tmp_path, handler)
    with pytest.raises(clients.EvidenceCallError) as captured:
        client.call("writer", [{"role": "user", "content": "offline replay"}],
                    max_tokens=6000, thinking="disabled", structured_schema=SCHEMA,
                    writer_model="MiniMax-M3", evidence=evidence)
    error = captured.value
    assert len(sends) == 1 and error.code == "REQUIRED_TOOL_MISSING"
    assert error.response_received is True and error.provider_outcome_known is True
    assert error.response_metadata["total_tokens"] == 6240
    assert error.response_metadata["finish_reason"] == "stop"
    assert error.response_metadata["response_body_complete"] is True
    assert error.response_payload == json.loads(original) and error.response_text is None
    assert (evidence.root / "response_body.raw").read_bytes() == original
    assert "result_ready" not in [e["phase"] for e in evidence.events()]


def test_credential_in_body_is_redacted_only_in_saved_evidence(tmp_path):
    sent = []
    def handler(request):
        sent.append(request.read())
        return httpx.Response(200, content=original_reply())
    client, evidence, _ = setup_client(tmp_path, handler)
    client.call("writer", [{"role": "user", "content": "accidental " + KEY}],
                structured_schema=SCHEMA, evidence=evidence)
    assert KEY.encode() in sent[0]  # The hook never rewrites creative input.
    stored = (evidence.root / "request_body.raw").read_bytes()
    manifest = json.loads((evidence.root / "REQUEST_BODY_MANIFEST.json").read_text(encoding="utf-8"))
    assert KEY.encode() not in stored and b"[REDACTED]" in stored
    assert manifest["credential_redacted"] is True and manifest["raw_bytes_preserved"] is False
    assert manifest["original_sha256"] == hashlib.sha256(sent[0]).hexdigest()
    assert manifest["stored_sha256"] == hashlib.sha256(stored).hexdigest()
    assert manifest["original_sha256"] != manifest["stored_sha256"]
    assert KEY.encode() not in b"".join(p.read_bytes() for p in evidence.root.iterdir())


def test_timeout_stays_unknown_and_has_one_serialized_request(tmp_path):
    sends = []
    def handler(request):
        sends.append(request.read())
        raise httpx.ReadTimeout("offline response unknown", request=request)
    client, evidence, _ = setup_client(tmp_path, handler)
    with pytest.raises(clients.EvidenceCallError) as captured:
        client.call("writer", [{"role": "user", "content": "one attempt"}],
                    structured_schema=SCHEMA, evidence=evidence)
    error = captured.value
    assert len(sends) == 1 and error.code == "TRANSPORT_EXCEPTION"
    assert error.provider_dispatch_started is True and error.provider_outcome_known is False
    assert error.response_received is False and error.response_metadata is None
    assert (evidence.root / "request_body.raw").read_bytes() == sends[0]
    assert not (evidence.root / "response_body.raw").exists()
    configured = next(e["details"] for e in evidence.events() if e["phase"] == "client_configured")
    assert configured["max_retries"] == 0 and configured["follow_redirects"] is False


def test_capture_failure_prevents_http_send(tmp_path, monkeypatch):
    sends = []
    def handler(request):
        sends.append(request.read())
        return httpx.Response(200, content=original_reply())
    client, evidence, _ = setup_client(tmp_path, handler)
    def broken(*args, **kwargs):
        raise OSError("offline disk failure")
    monkeypatch.setattr(clients, "save_request_body", broken)
    with pytest.raises(clients.EvidenceCallError) as captured:
        client.call("writer", [{"role": "user", "content": "one attempt"}],
                    structured_schema=SCHEMA, evidence=evidence)
    error = captured.value
    assert sends == [] and error.code == "OUTBOUND_EVIDENCE_CAPTURE_FAILED"
    assert error.provider_dispatch_started is False and error.provider_outcome_known is True
    assert error.response_received is False
