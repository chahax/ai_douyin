"""Fixed same685-schema wire probe; no real sockets or private reasoning use."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import httpx
import pytest

from scripts import creative_isolated_claims_thinking_role_clients_v1 as adapter
from scripts.creative_call_evidence_v1 import CallEvidenceJournal, digest

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "data/production_trials/world_scene_live_20261016/round_08/call_685_source_claims_calibration_14.json"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args,**kwargs):raise AssertionError("no real network")
    monkeypatch.setattr(socket.socket,"connect",deny);monkeypatch.setattr(socket,"create_connection",deny)
    monkeypatch.setattr(adapter.core,"role_config",lambda role:SimpleNamespace(model=adapter.core.REVIEW_MODEL,
        api_key="offline-thinking-key",base_url="https://api.deepseek.com/v1"))


def original():return json.loads(ORIGINAL.read_text(encoding="utf-8"))


def response(*,fault=None):
    message={"role":"assistant","content":None,"reasoning_content":"OFFLINE_PRIVATE_REASONING_DO_NOT_INTERPRET"}
    if fault=="missing_tool":message["content"]="ordinary content must not become a tool"
    else:message["tool_calls"]=[{"id":"offline-tool","type":"function","function":{"name":adapter.TOOL_NAME,"arguments":json.dumps(original()["output"],ensure_ascii=False)}}]
    return json.dumps({"id":"offline-response","model":adapter.core.REVIEW_MODEL,"choices":[{"index":0,"message":message,
        "finish_reason":"length" if fault=="truncated" else "stop" if fault=="missing_tool" else "tool_calls"}],
        "usage":{"prompt_tokens":19,"completion_tokens":11,"total_tokens":30,"completion_tokens_details":{"reasoning_tokens":7}}},ensure_ascii=False).encode()


def setup(tmp_path,*,fault=None,mutation=None):
    request=adapter.bind_request(original()["request"]);manifest={"offline_source":"same685"};sent=[]
    journal=CallEvidenceJournal(tmp_path/"call_evidence/call_001",{"ordinal":1,"label":"source_reasoning_diagnostic_01",
        "request_sha256":digest(request),"source_binding_sha256":digest(manifest),"role":"director","model":request["model"]})
    def handler(outgoing):
        sent.append(outgoing.read())
        if fault=="unknown":raise httpx.ReadTimeout("offline unknown, no retry",request=outgoing)
        return httpx.Response(200,content=response(fault=fault))
    def factory(**kwargs):
        if mutation:
            def mutate(outgoing):
                body=json.loads(outgoing.read());mutation(body);raw=json.dumps(body,ensure_ascii=False).encode()
                outgoing.stream=httpx.ByteStream(raw);outgoing._content=raw;outgoing.headers["content-length"]=str(len(raw))
            kwargs["event_hooks"]["request"].insert(0,mutate)
        return httpx.Client(transport=httpx.MockTransport(handler),**kwargs)
    client=adapter.make_client_factory(request,http_client_factory=factory)()
    def call():return client.call("director",request["messages"],max_tokens=16000,temperature=.4,thinking="enabled",structured_schema=request["structured_schema"],evidence=journal)
    return request,manifest,sent,journal,call


def test_same_original685_messages_schema_and_only_two_wire_fields_change():
    request=original()["request"];before=deepcopy(request);new=adapter.bind_request(request)
    oldwire=adapter.prior.expected_wire_request(request);newwire=adapter.expected_wire_request(new)
    assert request==before and new["messages"]==request["messages"] and new["structured_schema"]==request["structured_schema"]
    assert {k for k in set(oldwire)|set(newwire) if oldwire.get(k)!=newwire.get(k)}=={"thinking","tool_choice"}
    assert newwire["thinking"]=={"type":"enabled"} and newwire["tool_choice"]=="auto"
    assert newwire["tools"]==oldwire["tools"] and newwire["max_tokens"]==16000 and newwire["temperature"]==.4
    assert adapter.schema_compilation_manifest(new)["service_schema_sha256"]==adapter.prior.schema_compilation_manifest(request)["service_schema_sha256"]
    changed=deepcopy(new);changed["messages"][1]["content"]+=" changed"
    with pytest.raises(adapter.EvidenceCallError,match="SOURCE_CHANGED"):adapter.expected_wire_request(changed)
    changed=deepcopy(request);changed["parameters"]["max_completion_tokens"]=16001
    with pytest.raises(adapter.EvidenceCallError,match="REGISTERED685"):adapter.bind_request(changed)


def test_actual_sdk_auto_wire_raw_usage_new_reader_and_legacy_labels(tmp_path):
    request,manifest,sent,journal,call=setup(tmp_path);result=call()
    assert len(sent)==1 and json.loads(sent[0])==adapter.expected_wire_request(request)
    assert result.metadata["thinking_mode"]=="enabled" and result.metadata["effective_tool_choice_policy"]=="auto"
    assert result.metadata["provider_reasoning_tokens"]==7 and result.metadata["total_tokens"]==30
    assert result.metadata["transport_version"]==adapter.core.VERSION and not result.metadata["server_schema_guarantee"]
    assert "OFFLINE_PRIVATE_REASONING" not in json.dumps(result.metadata) and "OFFLINE_PRIVATE_REASONING" not in result.text
    receipt={"ordinal":1,"label":"source_reasoning_diagnostic_01","request":request,"request_sha256":digest(request),
        "source_binding_sha256":digest(manifest),"token_reservation":16000,"response_text":result.text,"response_payload":result.response_payload,
        "response_metadata":result.metadata,"status":"contract_valid","automatic_retry":False,"output":json.loads(result.text),
        "call_evidence":{"directory":str(journal.root),"identity_sha256":journal.identity_sha256}}
    path=tmp_path/"call_001_source_reasoning_diagnostic_01.json";path.write_text(json.dumps(receipt,ensure_ascii=False),encoding="utf-8")
    row={"ordinal":1,"label":receipt["label"],"receipt":path.name,"receipt_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"token_reservation":16000}
    assert adapter.verify_original_receipt(tmp_path,row,manifest)==receipt
    selection=json.loads((journal.root/"THINKING_CLAIMS_STRICT_SELECTION.json").read_text(encoding="utf-8"))
    assert selection["effective_policy"]["tool_choice"]=="auto" and selection["actual_wire_is_policy_authority"]
    assert set(selection["legacy_non_authoritative_fields"])=={"client_configured.tool_choice_policy","REQUEST_BODY_MANIFEST.tool_choice_policy"}
    selection["effective_policy"]["tool_choice"]="required"
    (journal.root/"THINKING_CLAIMS_STRICT_SELECTION.json").write_text(json.dumps(selection),encoding="utf-8")
    with pytest.raises(ValueError,match="wire/policy"):adapter.verify_original_receipt(tmp_path,row,manifest)
    with pytest.raises(adapter.EvidenceCallError,match="ALREADY_USED"):call()


@pytest.mark.parametrize("fault,code",[("unknown","TRANSPORT_EXCEPTION"),("truncated","RESPONSE_TRUNCATED"),("missing_tool","REQUIRED_TOOL_MISSING")])
def test_unknown_truncation_or_auto_without_tool_stops_once(tmp_path,fault,code):
    _,_,sent,journal,call=setup(tmp_path,fault=fault)
    with pytest.raises(adapter.EvidenceCallError,match=code) as caught:call()
    assert len(sent)==1
    if fault!="unknown":
        assert caught.value.response_metadata["total_tokens"]==30 and (journal.root/"response_body.raw").is_file()
    else:assert not caught.value.provider_outcome_known
    with pytest.raises(adapter.EvidenceCallError,match="ALREADY_USED"):call()


def test_serialized_named_policy_drift_blocked_before_send(tmp_path):
    _,_,sent,journal,call=setup(tmp_path,mutation=lambda wire:wire.update(tool_choice="required"))
    with pytest.raises(adapter.EvidenceCallError,match="SERIALIZED_WIRE_MISMATCH"):call()
    assert sent==[] and (journal.root/"BLOCKED_OUTBOUND_MANIFEST.json").is_file()
