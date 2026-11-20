"""One fixed685 source-contract thinking/auto diagnostic over frozen v5 HTTP.

The shared client/request-manifest named-tool labels are legacy templates.
Actual serialized bytes plus this separate effective-policy witness govern the
new mode. Raw model results, local domain checks and usage stay distinct.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from scripts import creative_isolated_claims_strict_role_clients_v1 as prior
from scripts.creative_call_evidence_v1 import atomic_create, digest
from src.content_factory.creative_workflow_roles import RoleResult

core, evidence_reader = prior.core, prior.evidence_reader
VERSION = "creative_isolated_claims_thinking_role_clients/v1"
NATIVE_VERSION = prior.NATIVE_VERSION
ORIGINAL_REQUEST_SHA256 = "c63ad915df754faa35fcec4b77dfdb58d4e03a226592b0352a52b653128cc730"
REVIEW_BASE_URL, MAX_BODY_BYTES, TOOL_NAME = prior.REVIEW_BASE_URL, prior.MAX_BODY_BYTES, prior.TOOL_NAME
EvidenceCallError = core.EvidenceCallError
LEGACY_POLICY = "existing_forced_function"


def _original(request):
    value = deepcopy(request)
    provenance = value.get("input_provenance", {})
    if (type(provenance) is not dict or provenance.get("thinking_probe_version") != VERSION
            or provenance.get("thinking_probe_original_request_sha256") != ORIGINAL_REQUEST_SHA256
            or provenance.get("stage_kind") != "source_claims" or value.get("parameters", {}).get("thinking") != "enabled"):
        raise core._error("THINKING_CLAIMS_FIXED_SOURCE_PROBE_REQUIRED")
    value["parameters"]["thinking"] = "disabled"
    provenance.pop("thinking_probe_version"); provenance.pop("thinking_probe_original_request_sha256")
    provenance["source_protocol_binding"] = prior.protocol_binding(value)
    if digest(value) != ORIGINAL_REQUEST_SHA256:
        raise core._error("THINKING_CLAIMS_ORIGINAL685_SOURCE_CHANGED")
    return value


def expected_wire_request(request):
    wire = prior.expected_wire_request(_original(request))
    wire["thinking"] = {"type": "enabled"}; wire["tool_choice"] = "auto"
    return wire


def schema_compilation_manifest(request, *, review_base_url=REVIEW_BASE_URL):
    base = prior.schema_compilation_manifest(_original(request), review_base_url=review_base_url)
    wire = expected_wire_request(request)
    return {**base, "client_policy_version": VERSION, "selector_policy_version": VERSION,
        "original_selector_policy_version": prior.VERSION, "original_request_sha256": ORIGINAL_REQUEST_SHA256,
        "expected_wire_sha256": digest(wire), "expected_wire_bytes": len(json.dumps(wire,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()),
        "requested_thinking_mode": "enabled", "effective_tool_choice_policy": "auto",
        "shared_tool_choice_labels_are_legacy_templates": True, "reasoning_effort": "not_sent_provider_default",
        "thinking_output_shares_16000_completion_cap": True}


def protocol_binding(request, *, review_base_url=REVIEW_BASE_URL):
    manifest = schema_compilation_manifest(request, review_base_url=review_base_url)
    return {"schema": VERSION + "/protocol_binding", **{k: manifest[k] for k in (
        "selector_policy_version", "native_protocol_version", "stage_kind", "shared_strict_transport_version",
        "original_request_sha256", "original_contract_sha256", "service_schema_sha256", "expected_wire_sha256", "endpoint_sha256",
        "function_name", "function_strict", "model", "base_url", "endpoint", "SDK_max_retries", "HTTP_follow_redirects",
        "original_local_contract_validation_required", "service_schema_is_weaker_than_local_contract",
        "requested_thinking_mode", "effective_tool_choice_policy", "shared_tool_choice_labels_are_legacy_templates")}}


def bind_request(original_request):
    if digest(original_request) != ORIGINAL_REQUEST_SHA256 or not prior.is_strict_claims_request(original_request):
        raise core._error("THINKING_CLAIMS_REGISTERED685_REQUEST_REQUIRED")
    value = deepcopy(original_request); value["parameters"]["thinking"] = "enabled"
    value["input_provenance"].update(thinking_probe_version=VERSION, thinking_probe_original_request_sha256=ORIGINAL_REQUEST_SHA256)
    value["input_provenance"]["source_protocol_binding"] = protocol_binding(value)
    return value


def _selection(request, identity_sha):
    return {"schema": VERSION + "/selection", "identity_sha256": identity_sha, "logical_request_sha256": digest(request),
        "binding": protocol_binding(request), "original_request_sha256": ORIGINAL_REQUEST_SHA256,
        "shared_outbound_proof_schema": core.VERSION + "/outbound_proof", "source6_admission_used": False,
        "effective_policy": {"thinking": "enabled", "tool_choice": "auto", "function_strict": True,
            "max_tokens": 16000, "temperature_wire_value": .4, "temperature_effect_in_thinking": "ignored",
            "reasoning_effort_sent": False, "server_schema_guarantee": False},
        "legacy_non_authoritative_fields": {"client_configured.tool_choice_policy": LEGACY_POLICY,
            "REQUEST_BODY_MANIFEST.tool_choice_policy": LEGACY_POLICY}, "actual_wire_is_policy_authority": True}


def _extra(payload):
    usage = payload.get("usage") if type(payload) is dict else None
    details = usage.get("completion_tokens_details") if type(usage) is dict else None
    count = details.get("reasoning_tokens") if type(details) is dict else None
    return {"selector_policy_version": VERSION, "native_protocol_version": NATIVE_VERSION,
        "effective_tool_choice_policy": "auto", "shared_named_policy_labels_are_legacy": True,
        "provider_reasoning_tokens_known": type(count) is int and count >= 0,
        "provider_reasoning_tokens": count if type(count) is int and count >= 0 else None,
        "private_reasoning_content_interpreted": False}


class StrictThinkingClaimsRoleClients(core.StrictDeepSeekSourceRoleClients):
    def __init__(self, *, expected_request, review_base_url=REVIEW_BASE_URL, max_wire_utf8_bytes=MAX_BODY_BYTES, http_client_factory=None):
        if type(max_wire_utf8_bytes) is not int or not 0 < max_wire_utf8_bytes <= MAX_BODY_BYTES:
            raise core._error("THINKING_CLAIMS_WIRE_LIMIT_INVALID")
        self._request = deepcopy(expected_request); self._wire = expected_wire_request(expected_request)
        self._request_sha256, self._wire_sha256 = digest(expected_request), digest(self._wire)
        self._review_base_url = core._official_endpoint(review_base_url); self._max_wire_utf8_bytes = max_wire_utf8_bytes
        self._schema_manifest = schema_compilation_manifest(expected_request, review_base_url=review_base_url)
        self._protocol_binding = protocol_binding(expected_request, review_base_url=review_base_url)
        if expected_request["input_provenance"].get("source_protocol_binding") != self._protocol_binding:
            raise core._error("THINKING_CLAIMS_BINDING_MISMATCH")
        self._http_client_factory, self._used = http_client_factory or core.httpx.Client, False

    def call(self, role, messages, *, max_tokens=12000, temperature=.4, thinking=None, structured_schema=None, writer_model=None, evidence=None):
        if self._used: raise core._error("THINKING_CLAIMS_CLIENT_ALREADY_USED", started=True, outcome_known=False)
        if evidence is None or evidence.identity.get("request_sha256") != self._request_sha256:
            raise core._error("THINKING_CLAIMS_IDENTITY_REQUIRED")
        selection = _selection(self._request, evidence.identity_sha256)
        atomic_create(evidence.root / "THINKING_CLAIMS_STRICT_SELECTION.json", json.dumps(selection,ensure_ascii=False,indent=2).encode())
        evidence.record("thinking_claims_effective_policy", selection)
        try:
            result = super().call(role, messages, max_tokens=max_tokens, temperature=temperature, thinking=thinking,
                structured_schema=structured_schema, writer_model=writer_model, evidence=evidence)
        except EvidenceCallError as exc:
            if exc.response_metadata is not None: exc.response_metadata.update(_extra(exc.response_payload))
            evidence.record("thinking_claims_result_bound", {"selector_policy_version": VERSION,
                "shared_transport_version": core.VERSION, "failure_code": exc.code, "metadata": exc.response_metadata})
            raise
        metadata = {**result.metadata, **_extra(result.response_payload)}
        evidence.record("thinking_claims_result_bound", {"selector_policy_version": VERSION,
            "shared_transport_version": core.VERSION, "metadata": metadata})
        return RoleResult(text=result.text, metadata=metadata, response_payload=result.response_payload)


def make_client_factory(expected_request, *, review_base_url=REVIEW_BASE_URL, max_wire_utf8_bytes=MAX_BODY_BYTES, http_client_factory=None):
    frozen = deepcopy(expected_request); expected_wire_request(frozen); core._official_endpoint(review_base_url)
    return lambda: StrictThinkingClaimsRoleClients(expected_request=frozen, review_base_url=review_base_url,
        max_wire_utf8_bytes=max_wire_utf8_bytes, http_client_factory=http_client_factory)


def verify_original_receipt(root, row, manifest, *, reader=None):
    """New enabled/auto wire proof; legacy requests use original fixed readers."""
    reader = reader or evidence_reader.Reader(); root = Path(root).resolve(); require = evidence_reader._require
    name = row.get("receipt"); require(type(name) is str and re.fullmatch(r"call_[0-9]+_[a-zA-Z0-9_]{1,90}\.json",name), "safe original receipt required")
    path = evidence_reader._inside(root / name,root); reader.verify(path,row["receipt_sha256"]); receipt = reader.json(path); request = receipt["request"]
    if request.get("input_provenance",{}).get("thinking_probe_version") != VERSION:
        return prior.verify_original_receipt(root,row,manifest,reader=reader)
    wire, compilation, binding = expected_wire_request(request), schema_compilation_manifest(request), protocol_binding(request)
    require(request["input_provenance"].get("source_protocol_binding") == binding and receipt.get("ordinal") == row.get("ordinal")
        and receipt.get("label") == row.get("label") and receipt.get("request_sha256") == digest(request)
        and receipt.get("source_binding_sha256") == digest(manifest) and receipt.get("token_reservation") == row.get("token_reservation"), "thinking receipt/source binding differs")
    call = receipt["call_evidence"]; directory = Path(call["directory"])
    directory = evidence_reader._inside(directory if directory.is_absolute() else root/directory,root/"call_evidence")
    identity = {"ordinal":receipt["ordinal"],"label":receipt["label"],"request_sha256":digest(request),
        "source_binding_sha256":receipt["source_binding_sha256"],"role":request["role"],"model":request["model"]}; identity_sha=digest(identity)
    require(reader.json(directory/"IDENTITY.json") == {"schema":"creative_call_evidence/v1","identity":identity,"identity_sha256":identity_sha}
        and call.get("identity_sha256") == identity_sha, "thinking original SDK identity differs")
    actual, raw, request_body = evidence_reader._body(reader,directory,"request",identity_sha)
    proof = reader.json(directory/"DEEPSEEK_STRICT_WIRE_PREFLIGHT.json")
    require(actual == wire and reader.json(directory/"THINKING_CLAIMS_STRICT_SELECTION.json") == _selection(request,identity_sha)
        and request_body.get("tool_choice_policy") == LEGACY_POLICY
        and reader.json(directory/"DEEPSEEK_STRICT_SCHEMA_MANIFEST.json") == compilation
        and proof.get("schema") == core.VERSION+"/outbound_proof" and proof.get("identity_sha256") == identity_sha
        and proof.get("logical_request_sha256") == digest(request) and proof.get("status") == "wire_verified_before_send"
        and proof.get("actual_request_body_sha256") == hashlib.sha256(raw).hexdigest()
        and proof.get("actual_wire_sha256") == proof.get("expected_wire_sha256") == digest(wire)
        and proof.get("messages_sha256") == digest(request["messages"]) and proof.get("structured_schema_sha256") == digest(request["structured_schema"])
        and proof.get("source_protocol_binding_sha256") == digest(binding) and proof.get("schema_compilation_manifest_sha256") == digest(compilation)
        and proof.get("original_contract_sha256") == compilation["original_contract_sha256"] and proof.get("service_schema_sha256") == compilation["service_schema_sha256"]
        and proof.get("endpoint_method") == "POST" and proof.get("endpoint_path") == "/beta/chat/completions" and proof.get("provider_endpoint_host") == "api.deepseek.com"
        and proof.get("verified_endpoint_sha256") == compilation["endpoint_sha256"] and proof.get("body_bytes") == len(raw)
        and type(proof.get("max_wire_utf8_bytes")) is int and len(raw) <= proof["max_wire_utf8_bytes"] <= MAX_BODY_BYTES
        and proof.get("mapped_fields") == sorted(wire) and type(proof.get("SDK_max_retries")) is int and proof["SDK_max_retries"] == 0
        and proof.get("function_strict") is True and proof.get("full_wire_equals_mapped_logical_request") is True
        and proof.get("writer_reasoning_effort") is None and proof.get("provider_received_request") is None
        and proof.get("server_strict_schema_requested") is True and proof.get("original_local_contract_validation_required") is True
        and proof.get("service_schema_is_weaker_than_local_contract") is compilation["service_schema_is_weaker_than_local_contract"]
        and all(proof.get(k) is False for k in ("HTTP_follow_redirects","server_stream_requested","server_schema_guarantee","automatic_retry","new_provider_acceptance_verified","calls_authorized_by_proof")), "thinking actual wire/policy proof differs")
    payload, raw, body = evidence_reader._body(reader,directory,"response",identity_sha); meta = receipt["response_metadata"]
    require(payload == receipt.get("response_payload") and meta.get("raw_body_sha256") == hashlib.sha256(raw).hexdigest()
        and meta.get("response_body_complete") is True and body["http_metadata"].get("http_status_code") == meta.get("http_status_code") == 200
        and meta.get("thinking_mode") == "enabled" and meta.get("transport_version") == core.VERSION
        and meta.get("strict_mode") is True and meta.get("server_strict_schema_requested") is True and meta.get("server_schema_guarantee") is False
        and meta.get("original_contract_sha256") == compilation["original_contract_sha256"] and meta.get("service_schema_sha256") == compilation["service_schema_sha256"]
        and meta.get("original_local_contract_validation_required") is True
        and meta.get("service_schema_is_weaker_than_local_contract") is compilation["service_schema_is_weaker_than_local_contract"]
        and all(meta.get(k)==v for k,v in _extra(payload).items()) and meta.get("response_fault_code") is None
        and receipt.get("automatic_retry") is False, "thinking original response/metadata differs")
    choices=payload.get("choices");require(type(choices)is list and len(choices)==1,"one original response required")
    message=choices[0].get("message",{});tools=message.get("tool_calls")
    require(message.get("role")=="assistant" and type(tools)is list and len(tools)==1 and tools[0].get("type")=="function"
        and tools[0].get("function",{}).get("name")==TOOL_NAME
        and tools[0]["function"].get("arguments")==receipt.get("response_text")
        and core.evidenced.strict_envelope(receipt["response_text"].encode())==receipt.get("output")
        and meta.get("requested_model")==meta.get("response_model")==payload.get("model")==request["model"]
        and meta.get("response_id")==payload.get("id") and type(payload.get("id"))is str and bool(payload["id"])
        and meta.get("finish_reason")==choices[0].get("finish_reason")=="tool_calls", "thinking target tool/model/JSON differs")
    usage=payload.get("usage",{})
    require(all(type(usage.get(k))is int and usage[k]>=0 and type(meta.get(k))is int and meta[k]==usage[k]
        for k in ("prompt_tokens","completion_tokens","total_tokens")) and usage["prompt_tokens"]+usage["completion_tokens"]==usage["total_tokens"],"known typed original usage required")
    if meta["provider_reasoning_tokens_known"]: require(meta["provider_reasoning_tokens"]<=meta["completion_tokens"],"reasoning detail exceeds completion usage")
    events=[]
    for i,path in enumerate(sorted(directory.glob("event_*.json")),1):
        event=reader.json(path);require(event.get("sequence")==i and event.get("identity_sha256")==identity_sha,"thinking SDK journal differs");events.append(event)
    phases=[e.get("phase") for e in events]
    require(all(phases.count(k)==1 for k in ("dispatch_attempt_started","request_body_saved","response_body_saved","result_ready","model_wire_verified","thinking_claims_effective_policy","thinking_claims_result_bound","strict_arguments_json_received","client_configured")),"single thinking SDK dispatch required")
    find=lambda p:next(e["details"] for e in events if e["phase"]==p)
    require(find("thinking_claims_effective_policy")==_selection(request,identity_sha)
        and find("client_configured").get("tool_choice_policy")==LEGACY_POLICY
        and find("client_configured").get("logical_thinking_mode")=="enabled"
        and find("thinking_claims_result_bound")=={"selector_policy_version":VERSION,"shared_transport_version":core.VERSION,"metadata":meta}
        and find("strict_arguments_json_received").get("metadata")=={k:v for k,v in meta.items() if k not in _extra(payload)}, "thinking effective/legacy metadata binding differs")
    return receipt
