"""Fixed isolated-claim beta selector over the frozen v5 transport mechanism.

The shared HTTP proof/parser remain honestly v5. A separate selector witness
binds this new stage/schema policy; the old source6 verifier is never reused as
its admission. Ordinary calls retain the original client, without fallback.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from scripts import creative_deepseek_strict_role_clients_v5 as core
from scripts import creative_session_spend_anchor_v1 as evidence_reader
from scripts.creative_call_evidence_v1 import atomic_create, digest
from src.content_factory.creative_deepseek_strict_schema_v1 import compile_source_schema_with_manifest
from src.content_factory.creative_workflow_roles import RoleResult

VERSION = "creative_isolated_claims_strict_role_clients/v1"
NATIVE_VERSION = "creative_isolated_source_claims/v1"
REVIEW_BASE_URL, MAX_BODY_BYTES, TOOL_NAME = core.REVIEW_BASE_URL, core.MAX_BODY_BYTES, core.TOOL_NAME
EvidenceCallError = core.EvidenceCallError


def _compile(request):
    provenance = request.get("input_provenance", {}) if type(request) is dict else {}
    schema = request.get("structured_schema", {}) if type(request) is dict else {}
    kind = provenance.get("stage_kind") if type(provenance) is dict else None
    keys = {"units"} if kind == "source_claims" else {"checks", "revision_target"} if kind == "claims_comparison" else None
    if not (type(provenance) is dict and provenance.get("isolated_source_claims_version") == NATIVE_VERSION
            and request.get("role") == "director" and request.get("model") == core.REVIEW_MODEL
            and request.get("stage") == "full_review" and keys is not None
            and type(schema) is dict and set(schema.get("properties", {})) == keys
            and set(schema.get("required", [])) == keys and schema.get("additionalProperties") is False):
        raise core._error("ISOLATED_CLAIMS_STRICT_FIXED_CONTRACT_REQUIRED")
    params = request.get("parameters", {})
    if not (type(params.get("max_completion_tokens")) is int and params["max_completion_tokens"] == 16000
            and params.get("temperature") == .4 and params.get("thinking") == "disabled"):
        raise core._error("ISOLATED_CLAIMS_STRICT_FIXED_PARAMETERS_REQUIRED")
    wire = core.ordinary.expected_wire_request(request)
    service, manifest = compile_source_schema_with_manifest(schema)
    wire["tools"][0]["function"].update(parameters=service, strict=True)
    return wire, {**manifest, "selector_policy_version": VERSION, "native_protocol_version": NATIVE_VERSION,
        "stage_kind": kind, "shared_strict_transport_version": core.VERSION}


def is_strict_claims_request(request):
    provenance = request.get("input_provenance") if type(request) is dict else None
    marked = type(provenance) is dict and provenance.get("isolated_source_claims_version") == NATIVE_VERSION
    if marked: _compile(request)
    return marked


def expected_wire_request(request, *, strict_claims=True):
    if type(strict_claims) is not bool: raise core._error("ISOLATED_CLAIMS_STRICT_SELECTOR_INVALID")
    if strict_claims: return _compile(request)[0]
    if is_strict_claims_request(request): raise core._error("ISOLATED_CLAIMS_STRICT_REQUIRED_NO_FALLBACK")
    return core.ordinary.expected_wire_request(request)


def schema_compilation_manifest(request, *, review_base_url=REVIEW_BASE_URL):
    wire, manifest = _compile(request); base = core._official_endpoint(review_base_url)
    compact = lambda value: len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode())
    return {**manifest, "client_policy_version": VERSION, "model": core.REVIEW_MODEL, "function_name": TOOL_NAME,
        "function_strict": True, "base_url": base, "endpoint": base + "/chat/completions",
        "endpoint_sha256": digest(["POST", base + "/chat/completions"]), "expected_wire_sha256": digest(wire),
        "service_schema_bytes": compact(wire["tools"][0]["function"]["parameters"]), "expected_wire_bytes": compact(wire),
        "SDK_max_retries": 0, "HTTP_follow_redirects": False, "server_strict_schema_requested": True,
        "server_schema_guarantee": False, "new_provider_acceptance_verified": False, "calls_authorized_by_proof": False}


def protocol_binding(request, *, review_base_url=REVIEW_BASE_URL):
    manifest = schema_compilation_manifest(request, review_base_url=review_base_url)
    return {"schema": VERSION + "/protocol_binding", **{k: manifest[k] for k in (
        "selector_policy_version", "native_protocol_version", "stage_kind", "shared_strict_transport_version",
        "original_contract_sha256", "service_schema_sha256", "expected_wire_sha256", "endpoint_sha256",
        "function_name", "function_strict", "model", "base_url", "endpoint", "SDK_max_retries", "HTTP_follow_redirects",
        "original_local_contract_validation_required", "service_schema_is_weaker_than_local_contract")}}


def bind_request(request):
    """Pure logical binding; provenance is not sent or part of the wire hash."""
    result = deepcopy(request)
    binding = protocol_binding(result)
    existing = result["input_provenance"].get("source_protocol_binding")
    if existing is not None and existing != binding:
        raise core._error("ISOLATED_CLAIMS_STRICT_BINDING_MISMATCH")
    result["input_provenance"]["source_protocol_binding"] = binding
    return result


class StrictIsolatedClaimsRoleClients(core.StrictDeepSeekSourceRoleClients):
    def __init__(self, *, expected_request, review_base_url=REVIEW_BASE_URL, max_wire_utf8_bytes=MAX_BODY_BYTES, http_client_factory=None):
        if type(max_wire_utf8_bytes) is not int or not 0 < max_wire_utf8_bytes <= MAX_BODY_BYTES:
            raise core._error("ISOLATED_CLAIMS_STRICT_WIRE_LIMIT_INVALID")
        self._max_wire_utf8_bytes = max_wire_utf8_bytes; self._request = deepcopy(expected_request)
        self._wire = expected_wire_request(expected_request); self._request_sha256 = digest(expected_request); self._wire_sha256 = digest(self._wire)
        self._review_base_url = core._official_endpoint(review_base_url)
        self._schema_manifest = schema_compilation_manifest(expected_request, review_base_url=review_base_url)
        self._protocol_binding = protocol_binding(expected_request, review_base_url=review_base_url)
        binding = expected_request["input_provenance"].get("source_protocol_binding")
        if binding != self._protocol_binding: raise core._error("ISOLATED_CLAIMS_STRICT_BINDING_MISMATCH")
        self._http_client_factory = http_client_factory or core.httpx.Client; self._used = False

    def call(self, role, messages, *, max_tokens=12000, temperature=.4, thinking=None, structured_schema=None, writer_model=None, evidence=None):
        if self._used: raise core._error("ISOLATED_CLAIMS_STRICT_CLIENT_ALREADY_USED", started=True, outcome_known=False)
        if evidence is None or evidence.identity.get("request_sha256") != self._request_sha256:
            raise core._error("ISOLATED_CLAIMS_STRICT_IDENTITY_REQUIRED")
        selection = {"schema": VERSION + "/selection", "identity_sha256": evidence.identity_sha256,
            "logical_request_sha256": self._request_sha256, "binding": self._protocol_binding,
            "shared_outbound_proof_schema": core.VERSION + "/outbound_proof", "source6_admission_used": False}
        atomic_create(evidence.root / "ISOLATED_CLAIMS_STRICT_SELECTION.json", json.dumps(selection, ensure_ascii=False, indent=2).encode())
        evidence.record("isolated_claims_strict_policy_selected", selection)
        try:
            result = super().call(role, messages, max_tokens=max_tokens, temperature=temperature, thinking=thinking,
                structured_schema=structured_schema, writer_model=writer_model, evidence=evidence)
        except EvidenceCallError as exc:
            if exc.response_metadata is not None:
                exc.response_metadata.update(selector_policy_version=VERSION, native_protocol_version=NATIVE_VERSION)
            evidence.record("isolated_claims_strict_result_bound", {"selector_policy_version": VERSION,
                "shared_transport_version": core.VERSION, "failure_code": exc.code, "metadata": exc.response_metadata})
            raise
        metadata = {**result.metadata, "selector_policy_version": VERSION, "native_protocol_version": NATIVE_VERSION}
        # Shared result_ready is retained; this extra event binds the explicitly
        # added selector metadata instead of rewriting that original journal.
        evidence.record("isolated_claims_strict_result_bound", {"selector_policy_version": VERSION,
            "shared_transport_version": core.VERSION, "metadata": metadata})
        return RoleResult(text=result.text, metadata=metadata, response_payload=result.response_payload)


def make_client_factory(expected_request, *, strict_claims=False, review_base_url=REVIEW_BASE_URL, max_wire_utf8_bytes=MAX_BODY_BYTES, http_client_factory=None):
    if type(strict_claims) is not bool: raise core._error("ISOLATED_CLAIMS_STRICT_SELECTOR_INVALID")
    if not strict_claims:
        expected_wire_request(expected_request, strict_claims=False)
        return core.ordinary.make_client_factory(expected_request, http_client_factory=http_client_factory)
    frozen = deepcopy(expected_request); expected_wire_request(frozen); core._official_endpoint(review_base_url)
    return lambda: StrictIsolatedClaimsRoleClients(expected_request=frozen, review_base_url=review_base_url,
        max_wire_utf8_bytes=max_wire_utf8_bytes, http_client_factory=http_client_factory)


def _wire(reader, directory, request, identity_sha):
    actual, raw, _ = evidence_reader._body(reader, directory, "request", identity_sha)
    proof = reader.json(directory / "DEEPSEEK_STRICT_WIRE_PREFLIGHT.json")
    manifest, binding = schema_compilation_manifest(request), protocol_binding(request); expected = expected_wire_request(request)
    require = evidence_reader._require
    require(reader.json(directory / "ISOLATED_CLAIMS_STRICT_SELECTION.json") == {"schema": VERSION + "/selection",
        "identity_sha256": identity_sha, "logical_request_sha256": digest(request), "binding": binding,
        "shared_outbound_proof_schema": core.VERSION + "/outbound_proof", "source6_admission_used": False}, "new strict selector binding differs")
    require(request["input_provenance"].get("source_protocol_binding") == binding
        and not (directory / "M31_WIRE_PREFLIGHT.json").exists()
        and reader.json(directory / "DEEPSEEK_STRICT_SCHEMA_MANIFEST.json") == manifest and actual == expected
        and proof.get("schema") == core.VERSION + "/outbound_proof" and proof.get("identity_sha256") == identity_sha
        and proof.get("logical_request_sha256") == digest(request) and proof.get("status") == "wire_verified_before_send"
        and proof.get("actual_request_body_sha256") == hashlib.sha256(raw).hexdigest()
        and proof.get("actual_wire_sha256") == proof.get("expected_wire_sha256") == digest(expected)
        and proof.get("messages_sha256") == digest(request["messages"]) and proof.get("structured_schema_sha256") == digest(request["structured_schema"])
        and proof.get("source_protocol_binding_sha256") == digest(binding) and proof.get("schema_compilation_manifest_sha256") == digest(manifest)
        and proof.get("original_contract_sha256") == manifest["original_contract_sha256"] and proof.get("service_schema_sha256") == manifest["service_schema_sha256"]
        and proof.get("endpoint_method") == "POST" and proof.get("endpoint_path") == "/beta/chat/completions"
        and proof.get("provider_endpoint_host") == "api.deepseek.com" and proof.get("verified_endpoint_sha256") == manifest["endpoint_sha256"]
        and proof.get("body_bytes") == len(raw) and type(proof.get("max_wire_utf8_bytes")) is int
        and len(raw) <= proof["max_wire_utf8_bytes"] <= MAX_BODY_BYTES and proof.get("mapped_fields") == sorted(expected)
        and type(proof.get("SDK_max_retries")) is int and proof["SDK_max_retries"] == 0
        and proof.get("function_strict") is True and proof.get("full_wire_equals_mapped_logical_request") is True
        and proof.get("writer_reasoning_effort") is None and proof.get("provider_received_request") is None
        and proof.get("server_strict_schema_requested") is True and proof.get("original_local_contract_validation_required") is True
        and proof.get("service_schema_is_weaker_than_local_contract") is manifest["service_schema_is_weaker_than_local_contract"]
        and all(proof.get(k) is False for k in ("HTTP_follow_redirects", "server_stream_requested", "server_schema_guarantee",
            "automatic_retry", "new_provider_acceptance_verified", "calls_authorized_by_proof")), "new strict actual SDK wire differs")
    return expected


def verify_original_receipt(root, row, manifest, *, reader=None):
    """Explicit new-selector reader; ordinary calls keep the original verifier."""
    reader = reader or evidence_reader.Reader(); root = Path(root).resolve(); name = row.get("receipt")
    evidence_reader._require(type(name) is str and re.fullmatch(r"call_[0-9]+_[a-zA-Z0-9_]{1,90}\.json", name), "safe receipt name required")
    path = evidence_reader._inside(root / name, root); reader.verify(path, row["receipt_sha256"]); receipt = reader.json(path)
    request = receipt.get("request", {})
    marked = is_strict_claims_request(request)
    if not marked:
        evidence_reader._require(receipt.get("response_metadata", {}).get("selector_policy_version") != VERSION, "selector metadata on a different contract")
        return evidence_reader.verify_original_receipt(root, row, manifest, reader=reader)
    require = evidence_reader._require
    require(receipt.get("ordinal") == row.get("ordinal") and receipt.get("label") == row.get("label")
        and receipt.get("request_sha256") == digest(request) and receipt.get("source_binding_sha256") == digest(manifest)
        and receipt.get("token_reservation") == row.get("token_reservation"), "original new strict receipt/source differs")
    call = receipt["call_evidence"]; directory = Path(call["directory"])
    directory = evidence_reader._inside(directory if directory.is_absolute() else root / directory, root / "call_evidence")
    identity = {"ordinal": receipt["ordinal"], "label": receipt["label"], "request_sha256": digest(request),
        "source_binding_sha256": receipt["source_binding_sha256"], "role": request["role"], "model": request["model"]}; identity_sha = digest(identity)
    require(reader.json(directory / "IDENTITY.json") == {"schema": "creative_call_evidence/v1", "identity": identity, "identity_sha256": identity_sha}
        and call.get("identity_sha256") == identity_sha, "new strict SDK identity differs")
    wire = _wire(reader, directory, request, identity_sha)
    payload, raw, body = evidence_reader._body(reader, directory, "response", identity_sha); meta = receipt["response_metadata"]
    compilation = schema_compilation_manifest(request)
    require(meta.get("response_body_complete") is True and meta.get("raw_body_sha256") == hashlib.sha256(raw).hexdigest()
        and payload == receipt.get("response_payload") and meta.get("strict_mode") is True and meta.get("transport_version") == core.VERSION
        and meta.get("selector_policy_version") == VERSION and meta.get("native_protocol_version") == NATIVE_VERSION
        and body["http_metadata"].get("http_status_code") == meta.get("http_status_code") == 200
        and meta.get("response_fault_code") is None and receipt.get("automatic_retry") is False
        and meta.get("server_strict_schema_requested") is True and meta.get("server_schema_guarantee") is False
        and meta.get("original_local_contract_validation_required") is True
        and meta.get("original_contract_sha256") == compilation["original_contract_sha256"]
        and meta.get("service_schema_sha256") == compilation["service_schema_sha256"]
        and meta.get("service_schema_is_weaker_than_local_contract") is compilation["service_schema_is_weaker_than_local_contract"],
        "new strict original response differs")
    choices = payload.get("choices"); require(type(choices) is list and len(choices) == 1, "one response choice required")
    message = choices[0].get("message", {})
    tools = message.get("tool_calls"); require(message.get("role") == "assistant" and type(tools) is list and len(tools) == 1
        and tools[0].get("type") == "function", "one original tool required")
    function = tools[0].get("function", {})
    require(function.get("name") == wire["tools"][0]["function"]["name"] and function.get("arguments") == receipt.get("response_text")
        and core.evidenced.strict_envelope(function["arguments"].encode()) == receipt.get("output")
        and meta.get("requested_model") == meta.get("response_model") == payload.get("model") == request["model"]
        and meta.get("response_id") == payload.get("id") and type(payload.get("id")) is str and bool(payload["id"])
        and meta.get("finish_reason") == choices[0].get("finish_reason") == "tool_calls", "new strict native arguments/model/finish differs")
    usage = payload.get("usage", {})
    require(all(type(usage.get(k)) is int and usage[k] >= 0 and type(meta.get(k)) is int and meta[k] == usage[k]
        for k in ("prompt_tokens", "completion_tokens", "total_tokens")) and usage["prompt_tokens"] + usage["completion_tokens"] == usage["total_tokens"], "known typed usage required")
    phases, bound, shared = [], [], []
    for i, event_path in enumerate(sorted(directory.glob("event_*.json")), 1):
        event = reader.json(event_path); require(event.get("sequence") == i and event.get("identity_sha256") == identity_sha, "new strict SDK journal differs")
        phases.append(event.get("phase"))
        if event.get("phase") == "isolated_claims_strict_result_bound": bound.append(event)
        if event.get("phase") == "strict_arguments_json_received": shared.append(event)
    require(all(phases.count(k) == 1 for k in ("dispatch_attempt_started", "request_body_saved", "response_body_saved", "result_ready", "isolated_claims_strict_policy_selected", "model_wire_verified"))
        and len(bound) == len(shared) == 1 and bound[0]["details"] == {"selector_policy_version": VERSION,
            "shared_transport_version": core.VERSION, "metadata": meta}
        and shared[0]["details"].get("metadata") == {k: v for k, v in meta.items() if k not in ("selector_policy_version", "native_protocol_version")},
        "new strict original journal/selector metadata differs")
    return receipt
