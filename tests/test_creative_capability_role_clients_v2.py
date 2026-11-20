"""Real SDK serialization, fake HTTP service; no network or paid generation."""
import base64
from copy import deepcopy
import hashlib
import json
import socket
from types import SimpleNamespace

import httpx
import pytest

from scripts import creative_capability_role_clients_v2 as adapter
from scripts import creative_bounded_format_role_clients_v1 as bounded
from scripts.creative_call_evidence_v1 import CallEvidenceJournal, digest

KEY = "offline-only-credential-never-report"
SCHEMA = {"title": "submit_creative_json", "type": "object", "additionalProperties": False,
    "required": ["payload_json"], "properties": {"payload_json": {"type": "string"}}}


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("SDK capability tests cannot use sockets")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    # Test-only provider config isolation; the production wrapper never patches
    # this frozen function or shares a mutable global expected request.
    monkeypatch.setattr(bounded, "role_config", lambda role: SimpleNamespace(
        model="MiniMax-M3" if role == "writer" else "deepseek-flash",
        api_key=KEY, base_url="https://api.minimaxi.com/v1" if role == "writer" else "https://api.deepseek.com/v1"))


def logical(role="writer"):
    return {"role": role, "model": "MiniMax-M3" if role == "writer" else "deepseek-flash",
        "stage": "offline_stage", "parameters": {"max_completion_tokens": 6000,
            "temperature": .4, "thinking": "disabled"},
        "messages": [{"role": "system", "content": "完整原生结果"},
            {"role": "user", "content": '{"full_current_script":"原句不可回填","reference_fulltext":"完整参考"}'}],
        "structured_schema": deepcopy(SCHEMA)}


def reply(role="writer", *, tools=True, finish=None):
    message = {"role": "assistant", "content": None}
    if tools:
        message["tool_calls"] = [{"id": "offline-tool", "type": "function", "function": {
            "name": adapter.TOOL_NAME, "arguments": '{"payload_json":"{}"}'}}]
    else:
        message["content"] = '{"payload_json":"{}"}'
    return json.dumps({"id": "offline-response", "model": "MiniMax-M3" if role == "writer" else "deepseek-flash",
        "choices": [{"index": 0, "message": message, "finish_reason": finish or ("tool_calls" if tools else "stop")}],
        "usage": {"prompt_tokens": 17, "completion_tokens": 9, "total_tokens": 26},
        "base_resp": {"status_code": 0}}, ensure_ascii=False).encode("utf-8")


def setup(tmp_path, request, handler, *, extra_hooks=(), redirect=False, drop_hooks=False, auth=None):
    evidence = CallEvidenceJournal(tmp_path / "call", {"ordinal": 1, "label": "offline_stage",
        "request_sha256": digest(request), "source_binding_sha256": "offline-source",
        "role": request["role"], "model": request["model"]})
    clients = []
    def factory(**kwargs):
        if redirect:
            kwargs["follow_redirects"] = True
        kwargs["event_hooks"] = {**kwargs["event_hooks"],
            "request": [*extra_hooks, *([] if drop_hooks else kwargs["event_hooks"]["request"])]}
        client = httpx.Client(transport=httpx.MockTransport(handler), auth=auth, **kwargs)
        clients.append(client)
        return client
    instance = adapter.CapabilityRoleClients(expected_request=request, http_client_factory=factory)
    return instance, evidence, clients


def call(client, request, evidence, **overrides):
    args = {"max_tokens": request["parameters"]["max_completion_tokens"],
        "temperature": request["parameters"]["temperature"], "thinking": request["parameters"]["thinking"],
        "structured_schema": request["structured_schema"], "evidence": evidence}
    args.update(overrides)
    return client.call(request["role"], request["messages"], **args)


def mutate(mutator):
    def hook(request):
        payload = json.loads(request.read())
        mutator(payload)
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request.stream = httpx.ByteStream(raw)
        request._content = raw  # Deliberate test-only corruption after SDK serialization.
        request.headers["content-length"] = str(len(raw))
    return hook


@pytest.mark.parametrize("role", ["writer", "director"])
def test_actual_sdk_sends_once_after_exact_wire_proof_and_original_capture(tmp_path, role):
    request = logical(role)
    saved = deepcopy(request)
    sent = []
    def handler(outgoing):
        sent.append(outgoing.read())
        proof = json.loads((evidence.root / "CAPABILITY_PREFLIGHT.json").read_text(encoding="utf-8"))
        assert proof["status"] == "capability_preflight_passed"
        assert proof["actual_request_body_sha256"] == hashlib.sha256(sent[0]).hexdigest()
        assert (evidence.root / "request_body.raw").read_bytes() == sent[0]
        return httpx.Response(200, content=reply(role))
    client, evidence, http_clients = setup(tmp_path, request, handler)
    result = call(client, request, evidence)
    assert len(sent) == 1 and request == saved
    assert result.metadata["total_tokens"] == 26
    assert (evidence.root / "response_body.raw").read_bytes() == reply(role)
    proof = json.loads((evidence.root / "CAPABILITY_PREFLIGHT.json").read_text(encoding="utf-8"))
    manifest = json.loads((evidence.root / "REQUEST_BODY_MANIFEST.json").read_text(encoding="utf-8"))
    assert proof["logical_request_sha256"] == digest(request)
    assert proof["identity_sha256"] == evidence.identity_sha256
    assert proof["actual_request_body_sha256"] == manifest["original_sha256"] == manifest["stored_sha256"]
    assert proof["full_wire_equals_mapped_logical_request"] is True
    assert proof["wire_capability_report"]["input_shape"] == "serialized_wire"
    assert proof["new_provider_acceptance_verified"] is False
    assert proof["calls_authorized_by_proof"] is False
    assert proof["SDK_max_retries"] == 0 and proof["HTTP_follow_redirects"] is False
    assert proof["dispatch_before_verify"] is False
    assert http_clients[0].is_closed
    assert KEY.encode() not in b"".join(path.read_bytes() for path in evidence.root.iterdir())


@pytest.mark.parametrize("mutation,code", [
    (lambda body: body.update(model="MiniMax-M3.1"), "MODEL_NOT_REGISTERED"),
    (lambda body: body.update(max_completion_tokens=9000), "CAPABILITY_SERIALIZED_WIRE_MISMATCH"),
    (lambda body: body.update(thinking={"type": "adaptive"}), "CAPABILITY_SERIALIZED_WIRE_MISMATCH"),
    (lambda body: body.update(temperature=.8), "CAPABILITY_SERIALIZED_WIRE_MISMATCH"),
    (lambda body: body.update(made_up_parameter=True), "CAPABILITY_SERIALIZED_WIRE_MISMATCH"),
    (lambda body: body["messages"][1].update(content="source changed"), "CAPABILITY_SERIALIZED_WIRE_MISMATCH"),
    (lambda body: body["tools"][0]["function"].update(parameters={"type": "object"}), "CAPABILITY_SERIALIZED_WIRE_MISMATCH"),
    (lambda body: body["tools"][0]["function"].update(strict=True), "STRICT_PROVIDER_ADAPTER_NOT_VERIFIED"),
])
def test_logical_legal_but_actual_wire_changed_has_zero_http_sends(tmp_path, mutation, code):
    request = logical()
    sent = []
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply()),
        extra_hooks=[mutate(mutation)])
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == code
    assert error.value.provider_dispatch_started is False
    assert error.value.provider_outcome_known is True
    assert sent == []
    manifest = json.loads((evidence.root / "BLOCKED_OUTBOUND_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["code"] == code and manifest["provider_received_request"] is None
    assert not (evidence.root / "response_body.raw").exists()


def test_actual_deepseek_thinking_and_named_tool_conflict_zero_sends(tmp_path):
    request = logical("director")
    sent = []
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply("director")),
        extra_hooks=[mutate(lambda body: body.update(thinking={"type": "enabled"}))])
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == "DEEPSEEK_FORCED_TOOL_THINKING_CONFLICT" and not sent


def test_client_factory_cannot_drop_the_old_capture_or_capability_hooks(tmp_path):
    request = logical()
    sent = []
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply()), drop_hooks=True)
    call(client, request, evidence)
    assert len(sent) == 1
    assert (evidence.root / "CAPABILITY_PREFLIGHT.json").exists()
    assert (evidence.root / "request_body.raw").read_bytes() == sent[0]


def test_image_message_content_and_original_base64_bytes_are_preserved(tmp_path):
    request = logical()
    image_bytes = b"\x89PNG\r\n\x1a\nexplicit-offline-image-fixture"
    image_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    prefix = deepcopy(request["messages"])
    request["messages"].append({"role": "user", "content": [
        {"type": "text", "text": "已选图片1对应角色，附加素材不改完整来源。"},
        {"type": "image_url", "image_url": {"url": image_url}}]})
    sent = []
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply()))
    call(client, request, evidence)
    actual = json.loads(sent[0])
    assert actual["messages"][:len(prefix)] == prefix
    assert actual["messages"][-1]["content"][1]["image_url"]["url"] == image_url
    assert image_url.encode("ascii") in sent[0]
    proof = json.loads((evidence.root / "CAPABILITY_PREFLIGHT.json").read_text(encoding="utf-8"))
    image_proof = proof["image_constraints"]["images"][0]
    assert image_proof["message_index"] == 2 and image_proof["content_index"] == 1
    assert image_proof["original_image_bytes_sha256"] == hashlib.sha256(image_bytes).hexdigest()
    assert image_proof["image_content_inspected"] is False
    assert proof["image_constraints"]["human_image_approval_verified"] is False


@pytest.mark.parametrize("kind", ["format", "image_size", "body_size"])
def test_actual_image_and_body_constraints_stop_before_http(tmp_path, monkeypatch, kind):
    request = logical()
    url = "data:image/png;base64," + base64.b64encode(b"fixture-bytes").decode("ascii")
    if kind == "format":
        url = url.replace("image/png", "image/bmp")
    elif kind == "image_size":
        monkeypatch.setattr(adapter, "MAX_IMAGE_BYTES", 3)
    else:
        monkeypatch.setattr(adapter, "MAX_BODY_BYTES", 10)
    request["messages"].append({"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}}]})
    sent = []
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply()))
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == ("CAPABILITY_BODY_SIZE_EXCEEDED" if kind == "body_size" else "CAPABILITY_IMAGE_FORMAT_OR_SIZE_INVALID")
    assert not sent and error.value.provider_dispatch_started is False


def test_read_timeout_is_one_submission_with_original_unknown_evidence(tmp_path):
    request = logical()
    sent = []
    def handler(outgoing):
        sent.append(outgoing.read())
        raise httpx.ReadTimeout("offline unknown result", request=outgoing)
    client, evidence, _ = setup(tmp_path, request, handler)
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert len(sent) == 1 and error.value.code == "TRANSPORT_EXCEPTION"
    assert error.value.provider_dispatch_started is True
    assert error.value.provider_outcome_known is False
    assert error.value.response_received is False
    assert (evidence.root / "request_body.raw").read_bytes() == sent[0]
    assert (evidence.root / "CAPABILITY_PREFLIGHT.json").exists()
    assert not (evidence.root / "response_body.raw").exists()


def test_sdk_server_retry_status_does_not_resubmit(tmp_path):
    request = logical()
    sent = []
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(503, json={"error": {"message": "offline retryable status"}}))
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert len(sent) == 1
    assert error.value.response_received is True and error.value.response_metadata["http_status_code"] == 503
    assert error.value.code == "HTTP_ERROR_RESPONSE"
    configured = next(row["details"] for row in evidence.events() if row["phase"] == "client_configured")
    assert configured["max_retries"] == 0


def test_redirect_response_is_not_followed(tmp_path):
    request = logical()
    sent = []
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(302,
            headers={"location": "https://other.invalid/v1/chat/completions"}, json={"error": {"message": "offline redirect"}}))
    with pytest.raises(adapter.EvidenceCallError):
        call(client, request, evidence)
    assert len(sent) == 1


def test_factory_cannot_enable_http_redirects(tmp_path):
    request = logical()
    sent = []
    client, evidence, clients = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply()), redirect=True)
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == "CAPABILITY_HTTP_FACTORY_POLICY_MISMATCH"
    assert not sent and clients[0].is_closed


@pytest.mark.parametrize("tools,finish,code", [(False, "stop", "REQUIRED_TOOL_MISSING"), (True, "length", "RESPONSE_TRUNCATED")])
def test_original_response_rejections_are_preserved_without_recovery(tmp_path, tools, finish, code):
    request = logical()
    raw = reply(tools=tools, finish=finish)
    sent = []
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=raw))
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert len(sent) == 1 and error.value.code == code
    assert error.value.response_received is True and error.value.response_metadata["total_tokens"] == 26
    assert (evidence.root / "response_body.raw").read_bytes() == raw


def test_identity_and_call_arguments_must_match_closed_over_request(tmp_path):
    request = logical()
    sent = []
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply()))
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence, max_tokens=7000)
    assert error.value.code == "CAPABILITY_CALL_ARGUMENTS_MISMATCH" and not sent
    client, evidence, _ = setup(tmp_path / "different", request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply()))
    evidence.identity["request_sha256"] = "wrong"
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == "CAPABILITY_CALL_IDENTITY_MISMATCH" and not sent


def test_non_json_call_arguments_are_known_local_rejection(tmp_path):
    request = logical()
    sent = []
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply()))
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence, max_tokens=object())
    assert error.value.code == "CAPABILITY_CALL_ARGUMENTS_INVALID"
    assert error.value.provider_dispatch_started is False
    assert error.value.provider_outcome_known is True and not sent


def test_factory_binds_request_snapshot_without_mutable_shared_global(tmp_path):
    request = logical()
    snapshot = deepcopy(request)
    sent = []
    factory = adapter.make_client_factory(request,
        http_client_factory=lambda **kwargs: httpx.Client(transport=httpx.MockTransport(
            lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply())), **kwargs))
    request["messages"][1]["content"] = "external copy changed"
    evidence = CallEvidenceJournal(tmp_path / "call", {"request_sha256": digest(snapshot),
        "role": snapshot["role"], "model": snapshot["model"]})
    call(factory(), snapshot, evidence)
    assert len(sent) == 1 and json.loads(sent[0])["messages"] == snapshot["messages"]


def test_instance_cannot_be_used_to_submit_twice(tmp_path):
    request = logical()
    sent = []
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply()))
    call(client, request, evidence)
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == "CAPABILITY_CLIENT_ALREADY_USED" and len(sent) == 1


def test_http_auth_flow_second_outbound_attempt_is_blocked_before_transport(tmp_path):
    class Twice(httpx.Auth):
        def auth_flow(self, request):
            yield request
            yield request  # Deliberate test-only resend, after the first response.
    request = logical()
    sent = []
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply()), auth=Twice())
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == "CAPABILITY_MULTIPLE_OUTBOUND_REQUESTS_BLOCKED"
    assert error.value.provider_dispatch_started is True
    assert error.value.provider_outcome_known is False
    assert len(sent) == 1
    assert (evidence.root / "request_body.raw").read_bytes() == sent[0]


@pytest.mark.parametrize("target,code", [
    ("https://api.deepseek.com/v1/chat/completions", "CAPABILITY_ENDPOINT_PROTOCOL_MISMATCH"),
    ("https://api.minimaxi.com/beta/chat/completions", "CAPABILITY_ENDPOINT_OPERATION_MISMATCH"),
])
def test_wire_target_must_match_actual_registered_provider_and_protocol(tmp_path, target, code):
    request = logical()
    sent = []
    def change_target(outgoing):
        outgoing.url = httpx.URL(target)
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply()), extra_hooks=[change_target])
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == code and not sent


@pytest.mark.parametrize("changed,code", [
    ("host", "CAPABILITY_ENDPOINT_CHANGED_AFTER_PREFLIGHT"),
    ("path", "CAPABILITY_ENDPOINT_CHANGED_AFTER_PREFLIGHT"),
    ("method", "CAPABILITY_ENDPOINT_CHANGED_AFTER_PREFLIGHT"),
    ("body", "CAPABILITY_WIRE_CHANGED_AFTER_PREFLIGHT"),
])
def test_original_capture_cannot_change_verified_target_or_body_before_send(tmp_path, monkeypatch, changed, code):
    request = logical()
    sent, outgoing_refs = [], []
    original_save = bounded.save_request_body
    def record_outgoing(outgoing):
        outgoing_refs.append(outgoing)
    def changed_capture(evidence, raw, *, role):
        manifest = original_save(evidence, raw, role=role)
        outgoing = outgoing_refs[0]
        if changed == "host":
            outgoing.url = httpx.URL("https://api.deepseek.com/v1/chat/completions")
        elif changed == "path":
            outgoing.url = httpx.URL("https://api.minimaxi.com/beta/chat/completions")
        elif changed == "method":
            outgoing.method = "GET"
        else:
            mutate(lambda body: body.update(temperature=.8))(outgoing)
        return manifest
    # Test-only malicious capture, installed between the two real guards. The
    # production adapter neither replaces this function nor permits hook edits.
    monkeypatch.setattr(bounded, "save_request_body", changed_capture)
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply()),
        extra_hooks=[record_outgoing])
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == code
    assert error.value.provider_dispatch_started is False
    assert error.value.provider_outcome_known is True
    assert not sent
    proof = json.loads((evidence.root / "CAPABILITY_PREFLIGHT.json").read_text(encoding="utf-8"))
    assert proof["verified_endpoint_sha256"] == digest(["POST", "https://api.minimaxi.com/v1/chat/completions"])
    assert (evidence.root / "request_body.raw").exists()
    assert not (evidence.root / "response_body.raw").exists()
