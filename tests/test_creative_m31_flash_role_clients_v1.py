"""Actual installed SDK serialization against MockTransport; no provider calls."""
from copy import deepcopy
import hashlib
import json
import socket
from types import SimpleNamespace

import httpx
import pytest

from scripts import creative_m31_flash_role_clients_v1 as adapter
from scripts.creative_call_evidence_v1 import CallEvidenceJournal, digest

KEY = "offline-m31-key-never-report"
SCHEMA = {"type": "object", "additionalProperties": False,
          "properties": {"payload_json": {"type": "string"}}, "required": ["payload_json"]}


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("M3.1 transport tests cannot use sockets")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    # Only the new module's import binding is isolated. No old client globals
    # or live credentials/configuration are altered by production code.
    monkeypatch.setattr(adapter, "role_config", lambda role: SimpleNamespace(
        model="MiniMax-M3" if role == "writer" else "deepseek-flash", api_key=KEY,
        base_url="https://api.minimaxi.com/v1" if role == "writer" else "https://api.deepseek.com/v1"))


def logical(role="writer"):
    return {"role": role, "model": adapter.WRITER_MODEL if role == "writer" else adapter.REVIEW_MODEL,
        "input_provenance": {"source_binding_sha256": "offline-source"},
        "parameters": {"max_completion_tokens": 16000 if role == "writer" else 6000,
            "temperature": .4, "thinking": "adaptive" if role == "writer" else "disabled"},
        "messages": [{"role": "system", "content": "提交完整新稿"},
                     {"role": "user", "content": '{"reference_fulltext":"完整参考","source":"原生来源"}'}],
        "structured_schema": deepcopy(SCHEMA)}


def reply(role="writer", *, tools=True, finish=None, model=None, usage="valid", arguments=None):
    message = {"role": "assistant", "content": None}
    if tools:
        message["tool_calls"] = [{"id": "offline-tool", "type": "function", "function": {
            "name": adapter.TOOL_NAME, "arguments": '{"payload_json":"{}"}' if arguments is None else arguments}}]
    else:
        message["content"] = '{"payload_json":"{}"}'
    payload = {"id": "offline-response", "model": model or (
        adapter.WRITER_MODEL if role == "writer" else adapter.REVIEW_MODEL),
        "choices": [{"index": 0, "message": message,
            "finish_reason": finish or ("tool_calls" if tools else "stop")}],
        "base_resp": {"status_code": 0}}
    if usage == "valid":
        payload["usage"] = {"prompt_tokens": 19, "completion_tokens": 11, "total_tokens": 30}
    elif usage != "absent":
        payload["usage"] = usage
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def setup(tmp_path, request, handler, *, extra_hooks=(), redirect=False, drop_hooks=False, auth=None):
    evidence = CallEvidenceJournal(tmp_path / "call", {"ordinal": 1, "label": "offline_m31",
        "request_sha256": digest(request), "source_binding_sha256": "offline-source",
        "role": request["role"], "model": request["model"]})
    clients = []
    def factory(**kwargs):
        if redirect:
            kwargs["follow_redirects"] = True
        kwargs["event_hooks"] = {**kwargs["event_hooks"], "request": [
            *extra_hooks, *([] if drop_hooks else kwargs["event_hooks"]["request"])]}
        client = httpx.Client(transport=httpx.MockTransport(handler), auth=auth, **kwargs)
        clients.append(client)
        return client
    client = adapter.M31FlashRoleClients(expected_request=request, http_client_factory=factory)
    return client, evidence, clients


def call(client, request, evidence, **overrides):
    args = {"max_tokens": request["parameters"]["max_completion_tokens"],
        "temperature": request["parameters"]["temperature"],
        "thinking": request["parameters"]["thinking"],
        "structured_schema": request["structured_schema"], "evidence": evidence}
    args.update(overrides)
    return client.call(request["role"], request["messages"], **args)


def mutate(mutator):
    def hook(request):
        body = json.loads(request.read())
        mutator(body)
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request.stream = httpx.ByteStream(raw)
        request._content = raw
        request.headers["content-length"] = str(len(raw))
    return hook


@pytest.mark.parametrize("role", ["writer", "director"])
def test_real_sdk_wire_and_original_capture_precede_single_send(tmp_path, role):
    request, sent = logical(role), []
    snapshot = deepcopy(request)
    def handler(outgoing):
        sent.append(outgoing.read())
        proof = json.loads((evidence.root / "M31_WIRE_PREFLIGHT.json").read_text(encoding="utf-8"))
        assert proof["actual_request_body_sha256"] == hashlib.sha256(sent[0]).hexdigest()
        assert (evidence.root / "request_body.raw").read_bytes() == sent[0]
        assert outgoing.headers["authorization"] == "Bearer " + KEY
        assert outgoing.url.host == ("api.minimax.cn" if role == "writer" else "api.deepseek.com")
        return httpx.Response(200, content=reply(role))
    client, evidence, resources = setup(tmp_path, request, handler)
    result = call(client, request, evidence,
                  writer_model=adapter.WRITER_MODEL if role == "writer" else None)
    assert len(sent) == 1 and request == snapshot
    wire = json.loads(sent[0])
    assert wire == adapter.expected_wire_request(request)
    assert wire["tools"][0]["function"]["parameters"] == SCHEMA
    assert "strict" not in wire["tools"][0]["function"] and "stream" not in wire
    if role == "writer":
        assert wire["model"] == "MiniMax-M3.1-Flash-Preview"
        assert wire["max_completion_tokens"] == 16000 and wire["reasoning_effort"] == "medium"
        assert not ({"thinking", "reasoning_split", "tool_choice", "max_tokens"} & set(wire))
    else:
        assert wire["max_tokens"] == 6000 and wire["thinking"] == {"type": "disabled"}
        assert wire["tool_choice"]["function"]["name"] == adapter.TOOL_NAME
        assert "reasoning_effort" not in wire
    assert result.metadata["total_tokens"] == 30
    assert result.metadata["requested_model"] == request["model"]
    assert result.metadata["server_schema_guarantee"] is False
    assert (evidence.root / "response_body.raw").read_bytes() == reply(role)
    proof = json.loads((evidence.root / "M31_WIRE_PREFLIGHT.json").read_text(encoding="utf-8"))
    manifest = json.loads((evidence.root / "REQUEST_BODY_MANIFEST.json").read_text(encoding="utf-8"))
    assert proof["logical_request_sha256"] == digest(request)
    assert proof["actual_request_body_sha256"] == manifest["original_sha256"] == manifest["stored_sha256"]
    assert proof["SDK_max_retries"] == 0 and proof["HTTP_follow_redirects"] is False
    assert proof["new_provider_acceptance_verified"] is False and proof["provider_received_request"] is None
    assert resources[0].is_closed
    assert KEY.encode() not in b"".join(path.read_bytes() for path in evidence.root.iterdir())


@pytest.mark.parametrize("mutation,code", [
    (lambda body: body["parameters"].update(thinking="disabled"), "M31_REASONING_MODE_INVALID"),
    (lambda body: body["parameters"].update(thinking="none"), "M31_REASONING_MODE_INVALID"),
    (lambda body: body["parameters"].update(reasoning_effort="high"), "M31_REASONING_MODE_INVALID"),
    (lambda body: body["parameters"].update(max_completion_tokens=6500), "M31_WRITER_OUTPUT_LIMIT_NOT_VERIFIED"),
    (lambda body: body["parameters"].update(max_completion_tokens=True), "M31_OUTPUT_LIMIT_INVALID"),
    (lambda body: body["parameters"].update(temperature=True), "M31_TEMPERATURE_INVALID"),
    (lambda body: body["parameters"].update(temperature=float("nan")), "M31_TEMPERATURE_INVALID"),
    (lambda body: body["parameters"].update(tool_choice="required"), "M31_LOGICAL_PARAMETERS_NOT_MAPPED"),
    (lambda body: body.update(model="MiniMax-M3"), "M31_ROLE_MODEL_MISMATCH"),
    (lambda body: body.update(tools=[]), "M31_LOGICAL_FIELDS_NOT_MAPPED"),
    (lambda body: body.update(structured_schema=None), "M31_STRUCTURED_SCHEMA_REQUIRED"),
    (lambda body: body["messages"][0].update(content=[{"type": "image_url"}]), "M31_TEXT_MESSAGES_REQUIRED"),
])
def test_unverified_logical_parameters_fail_without_sdk_or_send(mutation, code):
    request = logical()
    mutation(request)
    with pytest.raises(adapter.EvidenceCallError) as error:
        adapter.M31FlashRoleClients(expected_request=request)
    assert error.value.code == code and error.value.provider_dispatch_started is False


@pytest.mark.parametrize("value", ["https://api.minimaxi.com/v1", "https://api.minimax.io/v1",
    "http://api.minimax.cn/v1", "https://api.minimax.cn/beta", "https://api.minimax.cn/v1?key=not-real",
    "https://u:p@api.minimax.cn/v1", "https://api.minimax.cn:444/v1"])
def test_unverified_writer_endpoint_aliases_rejected(value):
    with pytest.raises(adapter.EvidenceCallError) as error:
        adapter.M31FlashRoleClients(expected_request=logical(), writer_base_url=value)
    assert error.value.code == "M31_WRITER_ENDPOINT_NOT_VERIFIED"


@pytest.mark.parametrize("mutation", [
    lambda body: body.update(model="MiniMax-M3"),
    lambda body: body.update(reasoning_effort="max"),
    lambda body: body.update(thinking={"type": "disabled"}),
    lambda body: body.update(reasoning_split=True),
    lambda body: body.update(max_completion_tokens=18000),
    lambda body: body.update(tool_choice="required"),
    lambda body: body["tools"][0]["function"].update(strict=True),
    lambda body: body["messages"][1].update(content="changed source"),
    lambda body: body.update(made_up_parameter=True),
])
def test_actual_wire_difference_blocks_before_http(tmp_path, mutation):
    request, sent = logical(), []
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply()),
        extra_hooks=[mutate(mutation)])
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == "M31_SERIALIZED_WIRE_MISMATCH"
    assert not sent and error.value.provider_dispatch_started is False
    assert error.value.provider_outcome_known is True
    assert (evidence.root / "BLOCKED_OUTBOUND_MANIFEST.json").exists()
    assert not (evidence.root / "response_body.raw").exists()


@pytest.mark.parametrize("tools,finish,model,arguments,code", [
    (False, "stop", None, None, "REQUIRED_TOOL_MISSING"),
    (False, "length", None, None, "RESPONSE_TRUNCATED"),
    (True, "length", None, None, "RESPONSE_TRUNCATED"),
    (True, "tool_calls", "MiniMax-M3", None, "MODEL_MISMATCH"),
    (True, "tool_calls", "MiniMax-M3.1", None, "MODEL_MISMATCH"),
    (True, "tool_calls", None, {"payload_json": "{}"}, "EMPTY_RESPONSE"),
])
def test_response_faults_preserve_original_without_recovery(tmp_path, tools, finish, model, arguments, code):
    request, sent = logical(), []
    raw = reply(tools=tools, finish=finish, model=model, arguments=arguments)
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=raw))
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == code and len(sent) == 1
    assert error.value.response_received is True and error.value.provider_outcome_known is True
    assert error.value.response_metadata["total_tokens"] == 30
    assert error.value.response_payload == json.loads(raw)
    assert (evidence.root / "response_body.raw").read_bytes() == raw
    assert "result_ready" not in [row["phase"] for row in evidence.events()]


@pytest.mark.parametrize("usage", ["absent", None, {}, {"total_tokens": True},
    {"prompt_tokens": 19, "completion_tokens": 11, "total_tokens": -1}])
def test_unknown_usage_preserved_without_invented_zero_or_second_call(tmp_path, usage):
    request, sent = logical(), []
    raw = reply(usage=usage)
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=raw))
    result = call(client, request, evidence)
    # The existing parser is reused: the stage runner must stop on absent usage.
    # Keeping the known raw result lets it retain creative output and real cost.
    assert "total_tokens" not in result.metadata and len(sent) == 1
    assert result.response_payload == json.loads(raw)
    assert (evidence.root / "response_body.raw").read_bytes() == raw


def test_review_unverified_endpoint_does_not_enter_journal_or_transport(tmp_path, monkeypatch):
    request, sent = logical("director"), []
    hidden_url = "https://api.deepseek.com/v1?token=offline-secret-in-url"
    monkeypatch.setattr(adapter, "role_config", lambda role: SimpleNamespace(
        model="deepseek-flash", api_key=KEY, base_url=hidden_url))
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply("director")))
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == "M31_REVIEW_ENDPOINT_NOT_VERIFIED" and not sent
    assert hidden_url.encode() not in b"".join(path.read_bytes() for path in evidence.root.iterdir())


@pytest.mark.parametrize("status", [400, 429, 500, 503])
def test_http_error_status_is_saved_once_with_no_sdk_retry(tmp_path, status):
    request, sent = logical(), []
    raw = b'{"error":{"message":"offline rejection"}}'
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(status, content=raw,
            headers={"x-request-id": "offline-http-rejection"}))
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == "HTTP_ERROR_RESPONSE" and len(sent) == 1
    assert error.value.response_received and error.value.provider_outcome_known
    assert error.value.response_metadata["http_status_code"] == status
    assert "total_tokens" not in error.value.response_metadata
    assert (evidence.root / "response_body.raw").read_bytes() == raw


def test_timeout_is_unknown_result_after_one_submission(tmp_path):
    request, sent = logical(), []
    def handler(outgoing):
        sent.append(outgoing.read())
        raise httpx.ReadTimeout("offline timeout", request=outgoing)
    client, evidence, _ = setup(tmp_path, request, handler)
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == "TRANSPORT_EXCEPTION" and len(sent) == 1
    assert error.value.provider_dispatch_started and not error.value.provider_outcome_known
    assert not error.value.response_received
    assert (evidence.root / "request_body.raw").read_bytes() == sent[0]
    assert not (evidence.root / "response_body.raw").exists()


def test_factory_cannot_drop_required_hook_or_enable_redirects(tmp_path):
    request, sent = logical(), []
    handler = lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply())
    client, evidence, _ = setup(tmp_path, request, handler, drop_hooks=True)
    call(client, request, evidence)
    assert len(sent) == 1 and (evidence.root / "M31_WIRE_PREFLIGHT.json").exists()
    client, evidence, resources = setup(tmp_path / "redirect", request, handler, redirect=True)
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == "M31_HTTP_FACTORY_POLICY_MISMATCH" and len(sent) == 1
    assert resources[0].is_closed


def test_redirect_response_not_followed_and_instance_cannot_submit_twice(tmp_path):
    request, sent = logical(), []
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(302,
            headers={"location": "https://other.invalid/"}, json={"error": "redirect"}))
    with pytest.raises(adapter.EvidenceCallError):
        call(client, request, evidence)
    assert len(sent) == 1
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == "M31_CLIENT_ALREADY_USED" and len(sent) == 1


def test_identity_argument_and_endpoint_mismatch_never_send(tmp_path):
    request, sent = logical(), []
    handler = lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply())
    client, evidence, _ = setup(tmp_path, request, handler)
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence, writer_model="MiniMax-M3")
    assert error.value.code == "M31_CALL_ARGUMENTS_MISMATCH" and not sent
    client, evidence, _ = setup(tmp_path / "identity", request, handler)
    evidence.identity["model"] = "MiniMax-M3"
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == "M31_CALL_IDENTITY_MISMATCH" and not sent
    def change_host(outgoing):
        outgoing.url = httpx.URL("https://api.minimaxi.com/v1/chat/completions")
    client, evidence, _ = setup(tmp_path / "host", request, handler, extra_hooks=[change_host])
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == "M31_ENDPOINT_PROTOCOL_MISMATCH" and not sent


def test_capture_failure_and_post_capture_mutation_block_transport(tmp_path, monkeypatch):
    request, sent = logical(), []
    handler = lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply())
    original = adapter.bounded.save_request_body
    def broken(*args, **kwargs):
        raise OSError("offline disk failure")
    monkeypatch.setattr(adapter.bounded, "save_request_body", broken)
    client, evidence, _ = setup(tmp_path, request, handler)
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == "M31_OUTBOUND_EVIDENCE_OR_WIRE_INVALID" and not sent
    outgoing_refs = []
    def remember(outgoing):
        outgoing_refs.append(outgoing)
    def changed(evidence, raw, *, role):
        result = original(evidence, raw, role=role)
        mutate(lambda body: body.update(reasoning_effort="max"))(outgoing_refs[0])
        return result
    monkeypatch.setattr(adapter.bounded, "save_request_body", changed)
    client, evidence, _ = setup(tmp_path / "changed", request, handler, extra_hooks=[remember])
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == "M31_WIRE_CHANGED_AFTER_PREFLIGHT" and not sent
    assert error.value.provider_dispatch_started is False


def test_second_http_auth_send_is_blocked(tmp_path):
    class Twice(httpx.Auth):
        def auth_flow(self, request):
            yield request
            yield request
    request, sent = logical(), []
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply()), auth=Twice())
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == "M31_MULTIPLE_OUTBOUND_REQUESTS_BLOCKED" and len(sent) == 1
    assert error.value.provider_dispatch_started and not error.value.provider_outcome_known


def test_factory_snapshots_logical_request_not_shared_mutable_global(tmp_path):
    request, sent = logical(), []
    snapshot = deepcopy(request)
    factory = adapter.make_client_factory(request,
        http_client_factory=lambda **kwargs: httpx.Client(transport=httpx.MockTransport(
            lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply())), **kwargs))
    request["messages"][0]["content"] = "external changed"
    evidence = CallEvidenceJournal(tmp_path / "call", {"request_sha256": digest(snapshot),
        "role": snapshot["role"], "model": snapshot["model"]})
    call(factory(), snapshot, evidence)
    assert len(sent) == 1 and json.loads(sent[0])["messages"] == snapshot["messages"]
