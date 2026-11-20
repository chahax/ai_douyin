"""Installed SDK beta wire tests through MockTransport; no real dispatch."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import httpx
from jsonschema import Draft202012Validator, ValidationError
import pytest

from scripts import creative_deepseek_strict_role_clients_v2 as adapter
from scripts.creative_call_evidence_v1 import CallEvidenceJournal, digest

KEY = "offline-strict-key-not-a-real-credential"
SCHEMA = {"type": "object", "additionalProperties": False,
          "properties": {"schema": {"const": adapter.SOURCE_VERSION},
                         "payload_json": {"type": "string", "maxLength": 8}},
          "required": ["schema", "payload_json"]}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("strict transport tests must not use sockets")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    def config(role):
        return SimpleNamespace(model="MiniMax-M3" if role == "writer" else adapter.REVIEW_MODEL,
                               api_key=KEY, base_url="https://api.minimaxi.com/v1" if role == "writer" else "https://api.deepseek.com/v1")
    monkeypatch.setattr(adapter, "role_config", config)
    monkeypatch.setattr(adapter.ordinary, "role_config", config)


def logical(role="director", schema=None):
    return {"role": role, "model": adapter.REVIEW_MODEL if role == "director" else adapter.WRITER_MODEL,
            "stage": "goal_audit", "input_provenance": {"source_binding_sha256": "offline-source"},
            "parameters": {"max_completion_tokens": 24000 if role == "director" else 16000, "temperature": .4,
                           "thinking": "disabled" if role == "director" else "adaptive"},
            "messages": [{"role": "system", "content": "返回完整来源审查"},
                         {"role": "user", "content": "完整当前规划、来源和已确认方向"}],
            "structured_schema": deepcopy(schema if schema is not None else SCHEMA)}


def reply(*, arguments=None, tools=True, finish=None, model=None, usage="valid"):
    message = {"role": "assistant", "content": None}
    if tools:
        message["tool_calls"] = [{"id": "offline-tool", "type": "function", "function": {
            "name": adapter.TOOL_NAME, "arguments": json.dumps({"schema": adapter.SOURCE_VERSION, "payload_json": "{}"}) if arguments is None else arguments}}]
    else:
        message["content"] = "ordinary body is not the required tool result"
    payload = {"id": "offline-response", "model": model or adapter.REVIEW_MODEL,
               "choices": [{"index": 0, "message": message, "finish_reason": finish or ("tool_calls" if tools else "stop")}]}
    if usage == "valid":
        payload["usage"] = {"prompt_tokens": 19, "completion_tokens": 11, "total_tokens": 30}
    elif usage != "absent":
        payload["usage"] = usage
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def setup(tmp_path, request, handler, *, hooks=(), redirect=False, drop_hooks=False, auth=None):
    evidence = CallEvidenceJournal(tmp_path / "call", {"request_sha256": digest(request), "role": request["role"],
        "model": request["model"], "source_binding_sha256": "offline-source", "ordinal": 1})
    resources = []
    def factory(**kwargs):
        if redirect:
            kwargs["follow_redirects"] = True
        kwargs["event_hooks"] = {**kwargs["event_hooks"], "request": [*hooks, *([] if drop_hooks else kwargs["event_hooks"]["request"])]}
        resource = httpx.Client(transport=httpx.MockTransport(handler), auth=auth, **kwargs)
        resources.append(resource)
        return resource
    client = adapter.StrictDeepSeekSourceRoleClients(expected_request=request, http_client_factory=factory)
    return client, evidence, resources


def call(client, request, evidence, **overrides):
    args = {"max_tokens": request["parameters"]["max_completion_tokens"], "temperature": .4,
            "thinking": request["parameters"]["thinking"], "structured_schema": request["structured_schema"], "evidence": evidence}
    args.update(overrides)
    return client.call(request["role"], request["messages"], **args)


def mutate(mutator):
    def hook(outgoing):
        body = json.loads(outgoing.read())
        mutator(body)
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        outgoing.stream = httpx.ByteStream(raw)
        outgoing._content = raw
        outgoing.headers["content-length"] = str(len(raw))
    return hook


def test_actual_sdk_strict_beta_wire_original_capture_and_single_send(tmp_path):
    request, sent = logical(), []
    snapshot = deepcopy(request)
    binding = adapter.protocol_binding(request)
    request["input_provenance"]["source_protocol_binding"] = binding
    def handler(outgoing):
        sent.append(outgoing.read())
        assert str(outgoing.url) == "https://api.deepseek.com/beta/chat/completions"
        assert outgoing.headers["authorization"] == "Bearer " + KEY
        assert (evidence.root / "request_body.raw").read_bytes() == sent[0]
        proof = json.loads((evidence.root / "DEEPSEEK_STRICT_WIRE_PREFLIGHT.json").read_text(encoding="utf-8"))
        assert proof["source_protocol_binding_sha256"] == digest(binding)
        assert proof["actual_request_body_sha256"] == hashlib.sha256(sent[0]).hexdigest()
        return httpx.Response(200, content=reply())
    client, evidence, resources = setup(tmp_path, request, handler)
    result = call(client, request, evidence)
    assert len(sent) == 1 and request["structured_schema"] == snapshot["structured_schema"]
    wire = json.loads(sent[0])
    assert wire == adapter.expected_wire_request(request)
    function = wire["tools"][0]["function"]
    assert function["strict"] is True and function["name"] == adapter.TOOL_NAME
    assert "maxLength" not in function["parameters"]["properties"]["payload_json"]
    assert wire["thinking"] == {"type": "disabled"} and wire["max_tokens"] == 24000
    assert "stream" not in wire
    proof = json.loads((evidence.root / "DEEPSEEK_STRICT_WIRE_PREFLIGHT.json").read_text(encoding="utf-8"))
    manifest = json.loads((evidence.root / "DEEPSEEK_STRICT_SCHEMA_MANIFEST.json").read_text(encoding="utf-8"))
    assert proof["original_contract_sha256"] == digest(SCHEMA) == manifest["original_contract_sha256"]
    assert proof["service_schema_sha256"] == digest(function["parameters"]) == manifest["service_schema_sha256"]
    assert proof["function_strict"] and proof["SDK_max_retries"] == 0 and not proof["HTTP_follow_redirects"]
    assert not proof["new_provider_acceptance_verified"] and not proof["calls_authorized_by_proof"]
    assert result.metadata["strict_mode"] and result.metadata["total_tokens"] == 30
    assert result.metadata["original_local_contract_validation_required"]
    assert not result.metadata["server_schema_guarantee"]
    assert (evidence.root / "response_body.raw").read_bytes() == reply() and resources[0].is_closed
    assert KEY.encode() not in b"".join(file.read_bytes() for file in evidence.root.iterdir())


@pytest.mark.parametrize("limit", [0, -1, True, 600001, "600000"])
def test_wire_limit_is_bounded_before_any_provider_work(limit):
    with pytest.raises(adapter.EvidenceCallError, match="WIRE_LIMIT_INVALID"):
        adapter.StrictDeepSeekSourceRoleClients(expected_request=logical(), max_wire_utf8_bytes=limit)


def test_actual_sdk_bytes_over_new_bound_are_saved_blocked_and_never_sent(tmp_path):
    request, sent = logical(), []
    client, evidence, _ = setup(tmp_path, request,
        lambda req: sent.append(req.read()) or httpx.Response(200, content=reply()))
    client._max_wire_utf8_bytes = 1
    with pytest.raises(adapter.EvidenceCallError, match="BODY_SIZE_EXCEEDED") as error:
        call(client, request, evidence)
    assert not sent and not error.value.provider_dispatch_started
    assert (evidence.root / "BLOCKED_OUTBOUND_BODY.raw").stat().st_size > 1


def test_ordinary_selector_retains_original_wire_and_transport_factory():
    request=logical("writer")
    assert adapter.expected_wire_request(request,source_strict=False)==adapter.ordinary.expected_wire_request(request)
    assert isinstance(adapter.make_client_factory(request,source_strict=False)(),adapter.ordinary.M31FlashRoleClients)
    with pytest.raises(adapter.EvidenceCallError,match="SOURCE_ROLE_REQUIRED"):
        adapter.expected_wire_request(request,source_strict=True)


@pytest.mark.parametrize("fault",[None,"schema_sha","endpoint","wire_limit","logical_binding","manifest"])
def test_future_lineage_reads_actual_strict_http_proof_and_rejects_drift(tmp_path,fault):
    from src.content_factory import creative_flat_lineage_verifier_v4 as lineage
    request=logical()
    request["input_provenance"]["source_protocol_binding"]=adapter.protocol_binding(request)
    client,evidence,_=setup(tmp_path,request,lambda req:httpx.Response(200,content=reply()))
    call(client,request,evidence)
    path=evidence.root/"DEEPSEEK_STRICT_WIRE_PREFLIGHT.json"
    proof=json.loads(path.read_text(encoding="utf-8"))
    if fault=="schema_sha":proof["service_schema_sha256"]="a"*64
    elif fault=="endpoint":proof["endpoint_path"]="/v1/chat/completions"
    elif fault=="wire_limit":proof["max_wire_utf8_bytes"]=600001
    elif fault=="logical_binding":request["input_provenance"]["source_protocol_binding"]["function_strict"]=False
    elif fault=="manifest":
        m=evidence.root/"DEEPSEEK_STRICT_SCHEMA_MANIFEST.json"
        value=json.loads(m.read_text(encoding="utf-8"));value["original_local_contract_validation_required"]=False
        m.write_text(json.dumps(value),encoding="utf-8")
    if fault is not None:path.write_text(json.dumps(proof),encoding="utf-8")
    cycle=lineage.VerificationCycle()
    if fault is None:
        assert lineage._outbound(cycle,tmp_path,evidence.root,request,evidence.identity_sha256)==adapter.expected_wire_request(request)
    else:
        with pytest.raises(lineage.LineageVerificationError):
            lineage._outbound(cycle,tmp_path,evidence.root,request,evidence.identity_sha256)


@pytest.mark.parametrize("mutation", [
    lambda b: b["tools"][0]["function"].update(strict=False),
    lambda b: b["tools"][0]["function"].pop("strict"),
    lambda b: b["tools"][0]["function"]["parameters"]["properties"].pop("schema"),
    lambda b: b.update(model="deepseek-reasoner"), lambda b: b.update(max_tokens=32000),
    lambda b: b.update(thinking={"type": "enabled"}), lambda b: b["messages"][1].update(content="changed source"),
    lambda b: b.update(stream=True)])
def test_actual_wire_drift_is_blocked_before_transport(tmp_path, mutation):
    request, sent = logical(), []
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply()), hooks=[mutate(mutation)])
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == "DEEPSEEK_STRICT_SERIALIZED_WIRE_MISMATCH" and not sent
    assert not error.value.provider_dispatch_started and error.value.provider_outcome_known
    assert (evidence.root / "BLOCKED_OUTBOUND_MANIFEST.json").exists()


@pytest.mark.parametrize("endpoint", ["https://api.deepseek.com/v1", "http://api.deepseek.com/beta",
    "https://other.invalid/beta", "https://api.deepseek.com/beta?key=hidden", "https://u:p@api.deepseek.com/beta",
    "https://api.deepseek.com:444/beta", "https://api.deepseek.com/beta#fragment"])
def test_strict_endpoint_cannot_drift_to_regular_or_other_target(endpoint):
    with pytest.raises(adapter.EvidenceCallError, match="ENDPOINT_NOT_VERIFIED"):
        adapter.StrictDeepSeekSourceRoleClients(expected_request=logical(), review_base_url=endpoint)


def test_endpoint_operation_and_post_capture_drift_block_send(tmp_path, monkeypatch):
    request, sent, outgoing = logical(), [], []
    def wrong_path(req):
        req.url = httpx.URL("https://api.deepseek.com/v1/chat/completions")
    client, evidence, _ = setup(tmp_path, request,
        lambda req: sent.append(req.read()) or httpx.Response(200, content=reply()), hooks=[wrong_path])
    with pytest.raises(adapter.EvidenceCallError, match="ENDPOINT_OPERATION_MISMATCH"):
        call(client, request, evidence)
    original = adapter.bounded.save_request_body
    def changed(journal, raw, *, role):
        value = original(journal, raw, role=role)
        outgoing[0].url = httpx.URL("https://api.deepseek.com/v1/chat/completions")
        return value
    monkeypatch.setattr(adapter.bounded, "save_request_body", changed)
    client, evidence, _ = setup(tmp_path / "after", request,
        lambda req: sent.append(req.read()) or httpx.Response(200, content=reply()), hooks=[lambda req: outgoing.append(req)])
    with pytest.raises(adapter.EvidenceCallError, match="ENDPOINT_CHANGED_AFTER_PREFLIGHT"):
        call(client, request, evidence)
    assert not sent


@pytest.mark.parametrize("arguments", ['{"ok":1}}', '{"ok":1,"ok":2}', '[1]', '{"n":NaN}', '{"n":1e400}', '{"x":'])
def test_invalid_tool_json_is_preserved_not_repaired_or_redispatched(tmp_path, arguments):
    request, sent, raw = logical(), [], reply(arguments=arguments)
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=raw))
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == "STRUCTURED_TOOL_JSON_INVALID" and len(sent) == 1
    assert error.value.provider_outcome_known and error.value.response_received
    assert error.value.response_text == arguments and error.value.response_payload == json.loads(raw)
    assert error.value.response_metadata["total_tokens"] == 30 and error.value.response_metadata["strict_mode"]
    assert (evidence.root / "response_body.raw").read_bytes() == raw
    assert not any(row["phase"] == "strict_arguments_json_received" for row in evidence.events())


@pytest.mark.parametrize("tools,finish,model,code", [(False, "stop", None, "REQUIRED_TOOL_MISSING"),
    (False, "length", None, "RESPONSE_TRUNCATED"), (True, "length", None, "RESPONSE_TRUNCATED"),
    (True, "tool_calls", "other-model", "MODEL_MISMATCH"), (True, "unknown", None, "RESPONSE_NOT_COMPLETED")])
def test_old_evidenced_response_failure_order_is_retained(tmp_path, tools, finish, model, code):
    request, sent, raw = logical(), [], reply(tools=tools, finish=finish, model=model)
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=raw))
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == code and len(sent) == 1
    assert error.value.response_metadata["total_tokens"] == 30 and error.value.response_metadata["strict_mode"]
    assert (evidence.root / "response_body.raw").read_bytes() == raw


@pytest.mark.parametrize("usage", ["absent", {}, None, {"total_tokens": True}, {"total_tokens": -1}])
def test_unknown_usage_stays_unknown_for_runtime_without_zero_or_retry(tmp_path, usage):
    request, sent = logical(), []
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply(usage=usage)))
    result = call(client, request, evidence)
    assert "total_tokens" not in result.metadata and len(sent) == 1


@pytest.mark.parametrize("status", [400, 429, 500, 503])
def test_http_error_has_durable_original_body_and_no_retry(tmp_path, status):
    request, sent, raw = logical(), [], b'{"error":{"message":"offline strict schema rejection"}}'
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(status, content=raw))
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == "HTTP_ERROR_RESPONSE" and len(sent) == 1
    assert error.value.provider_outcome_known and error.value.response_received
    assert (evidence.root / "response_body.raw").read_bytes() == raw


def test_timeout_remains_unknown_and_client_instance_cannot_send_twice(tmp_path):
    request, sent = logical(), []
    def handler(outgoing):
        sent.append(outgoing.read())
        raise httpx.ReadTimeout("offline", request=outgoing)
    client, evidence, _ = setup(tmp_path, request, handler)
    with pytest.raises(adapter.EvidenceCallError) as error:
        call(client, request, evidence)
    assert error.value.code == "TRANSPORT_EXCEPTION" and error.value.provider_dispatch_started and not error.value.provider_outcome_known
    with pytest.raises(adapter.EvidenceCallError, match="CLIENT_ALREADY_USED"):
        call(client, request, evidence)
    assert len(sent) == 1 and (evidence.root / "request_body.raw").read_bytes() == sent[0]


def test_changed_identity_protocol_or_call_args_fail_before_send(tmp_path):
    request, sent = logical(), []
    handler = lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply())
    client, evidence, _ = setup(tmp_path, request, handler)
    evidence.identity["model"] = "other"
    with pytest.raises(adapter.EvidenceCallError, match="CALL_IDENTITY_MISMATCH"):
        call(client, request, evidence)
    client, evidence, _ = setup(tmp_path / "arguments", request, handler)
    with pytest.raises(adapter.EvidenceCallError, match="CALL_ARGUMENTS_MISMATCH"):
        call(client, request, evidence, max_tokens=6000)
    request["input_provenance"]["source_protocol_binding"] = {"function_strict": False}
    with pytest.raises(adapter.EvidenceCallError, match="PROTOCOL_BINDING_MISMATCH"):
        adapter.StrictDeepSeekSourceRoleClients(expected_request=request)
    assert not sent


def test_disk_failure_never_releases_request_to_provider(tmp_path, monkeypatch):
    request, sent = logical(), []
    def failed(*args, **kwargs):
        raise OSError("offline storage failure")
    monkeypatch.setattr(adapter.bounded, "save_request_body", failed)
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply()))
    with pytest.raises(adapter.EvidenceCallError, match="OUTBOUND_EVIDENCE_OR_WIRE_INVALID"):
        call(client, request, evidence)
    assert not sent


def test_factory_hooks_cannot_be_dropped_or_redirects_enabled(tmp_path):
    request, sent = logical(), []
    handler = lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply())
    client, evidence, _ = setup(tmp_path, request, handler, drop_hooks=True)
    call(client, request, evidence)
    assert len(sent) == 1 and (evidence.root / "DEEPSEEK_STRICT_WIRE_PREFLIGHT.json").exists()
    client, evidence, resources = setup(tmp_path / "redirect", request, handler, redirect=True)
    with pytest.raises(adapter.EvidenceCallError, match="HTTP_FACTORY_POLICY_MISMATCH"):
        call(client, request, evidence)
    assert len(sent) == 1 and resources[0].is_closed


def test_second_auth_dispatch_is_blocked_after_first_release(tmp_path):
    class Twice(httpx.Auth):
        def auth_flow(self, request):
            yield request
            yield request
    request, sent = logical(), []
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply()), auth=Twice())
    with pytest.raises(adapter.EvidenceCallError, match="MULTIPLE_OUTBOUND_REQUESTS_BLOCKED") as error:
        call(client, request, evidence)
    assert len(sent) == 1 and error.value.provider_dispatch_started and not error.value.provider_outcome_known


def test_weaker_service_result_is_still_rejected_by_unchanged_local_contract(tmp_path):
    request, sent = logical(), []
    arguments = json.dumps({"schema": adapter.SOURCE_VERSION, "payload_json": "more-than-eight-characters"})
    client, evidence, _ = setup(tmp_path, request,
        lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply(arguments=arguments)))
    result = call(client, request, evidence)
    native = json.loads(result.text)
    Draft202012Validator(adapter.expected_wire_request(request)["tools"][0]["function"]["parameters"]).validate(native)
    with pytest.raises(ValidationError):
        Draft202012Validator(request["structured_schema"]).validate(native)
    assert request["structured_schema"] == SCHEMA and len(sent) == 1


def test_source_only_selector_keeps_writer_and_other_reviews_on_old_client():
    for role in ("writer", "director"):
        request = logical(role)
        factory = adapter.make_client_factory(request, source_strict=False)
        client = factory()
        assert type(client) is adapter.ordinary.M31FlashRoleClients
        assert "strict" not in client._wire["tools"][0]["function"]
    with pytest.raises(adapter.EvidenceCallError, match="SOURCE_ROLE_REQUIRED"):
        adapter.make_client_factory(logical("writer"), source_strict=True)
    request = logical()
    request["structured_schema"]["properties"]["schema"]["const"] = "another-stage/v1"
    with pytest.raises(adapter.EvidenceCallError, match="SOURCE_CONTRACT_REQUIRED"):
        adapter.expected_wire_request(request)
    with pytest.raises(adapter.EvidenceCallError, match="SELECTOR_INVALID"):
        adapter.make_client_factory(logical(), source_strict="yes")


def test_factory_captures_detached_request_snapshot(tmp_path):
    request, sent, snapshot = logical(), [], logical()
    factory = adapter.make_client_factory(request, source_strict=True,
        http_client_factory=lambda **kwargs: httpx.Client(transport=httpx.MockTransport(
            lambda outgoing: sent.append(outgoing.read()) or httpx.Response(200, content=reply())), **kwargs))
    request["messages"][1]["content"] = "outside changed"
    evidence = CallEvidenceJournal(tmp_path / "call", {"request_sha256": digest(snapshot), "role": "director", "model": adapter.REVIEW_MODEL})
    call(factory(), snapshot, evidence)
    assert len(sent) == 1 and json.loads(sent[0])["messages"] == snapshot["messages"]


def test_original_source_v2_cannot_be_selected_as_new_compact_v3():
    request = logical()
    request["structured_schema"]["properties"]["schema"]["const"] = "creative_goal_legal_usage_source_audit/v2"
    with pytest.raises(adapter.EvidenceCallError, match="SOURCE_CONTRACT_REQUIRED"):
        adapter.expected_wire_request(request)


def test_future_lineage_keeps_old_strict_v1_proof_valid_without_promoting606():
    from src.content_factory import creative_flat_lineage_verifier_v4 as lineage
    root = Path(__file__).resolve().parents[1]
    parent = root / "data/production_trials/goal_context_text_production_20261013/round_19"
    ledger = json.loads((parent / "CALL_LEDGER.json").read_text(encoding="utf8"))
    cycle = lineage.VerificationCycle()
    original = lineage._receipt(cycle, root, parent, ledger["calls"][0], ledger["source_manifest"])
    assert original["ordinal"] == 606 and lineage._verified_length_failure(original)
    assert original.get("output") is None and original.get("validation") is None


def test_complete604_compact_source_actual_sdk_wire_is_under_bound_and_future_verifiable(tmp_path):
    from scripts import run_goal_context_text_production_v21 as runner
    from src.content_factory import creative_flat_lineage_verifier_v4 as lineage
    inputs=runner.read(runner.PREFLIGHT_PARENT/"INPUTS.json")
    goal=runner.read(runner.PREFLIGHT_PARENT/"INHERITED_NATIVE_GOAL.json")
    prepared=runner.prepare_source_audit(inputs,runner.read(runner.PROFILE),goal)
    request,sent=prepared["request"],[]
    client,evidence,_=setup(tmp_path,request,
        lambda outgoing:sent.append(outgoing.read()) or httpx.Response(200,content=reply()))
    returned=call(client,request,evidence)
    assert len(sent)==1 and len(sent[0])<200000
    actual=json.loads(sent[0])
    assert actual==prepared["wire"] and actual["max_tokens"]==24000
    proof=json.loads((evidence.root/"DEEPSEEK_STRICT_WIRE_PREFLIGHT.json").read_text(encoding="utf8"))
    assert proof["body_bytes"]==len(sent[0]) and proof["max_wire_utf8_bytes"]==600000
    assert proof["original_contract_sha256"]==digest(request["structured_schema"])
    assert proof["service_schema_sha256"]==digest(actual["tools"][0]["function"]["parameters"])
    assert lineage._outbound(lineage.VerificationCycle(),runner.PROJECT,evidence.root,request,evidence.identity_sha256)==actual
    # Mock success proves transport only; its deliberately incomplete document
    # remains rejected by the unchanged local full source-v3 contract.
    with pytest.raises(ValidationError):
        Draft202012Validator(request["structured_schema"]).validate(json.loads(returned.text))
