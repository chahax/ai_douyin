"""Source-only DeepSeek beta strict tool transport with durable wire evidence.

Writer and all non-source reviewer calls use the unchanged frozen M31 client.
A strict service Schema is a capability projection; local source-v4 validation
remains mandatory. No recovery, retry, usage invention, or content approval.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import httpx

from scripts import creative_m31_flash_role_clients_v1 as ordinary
from scripts import creative_bounded_format_role_clients_v1 as bounded
from scripts import creative_evidenced_role_clients_v1 as evidenced
from scripts.creative_call_evidence_v1 import atomic_create, digest
from src.content_factory.creative_deepseek_strict_schema_v1 import compile_source_schema_with_manifest, StrictSchemaError
from src.content_factory.creative_goal_legal_usage_source_audit_v4 import VERSION as SOURCE_VERSION
from src.content_factory.creative_workflow_roles import role_config, RoleResult
from src.shared.config import settings

VERSION = "creative_deepseek_strict_role_clients/v3"
WRITER_MODEL = ordinary.WRITER_MODEL
WRITER_BASE_URL = ordinary.WRITER_BASE_URL
WRITER_REASONING_EFFORT = ordinary.WRITER_REASONING_EFFORT
REVIEW_MODEL = ordinary.REVIEW_MODEL
REVIEW_BASE_URL = "https://api.deepseek.com/beta"
TOOL_NAME = evidenced.TOOL_NAME
EvidenceCallError = evidenced.EvidenceCallError
MAX_BODY_BYTES = 600_000
PROVIDER_HOSTS = {"api.deepseek.com"}


def _error(code, *, started=False, outcome_known=True, cause_type=None):
    return EvidenceCallError(code, started=started, outcome_known=outcome_known, cause_type=cause_type)


def _endpoint(value, paths):
    try:
        url = httpx.URL(value)
        valid = (url.scheme == "https" and url.host in PROVIDER_HOSTS and
                 url.path.rstrip("/") in paths and url.port in (None, 443) and
                 not url.query and not url.fragment and not url.username and not url.password)
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise _error("DEEPSEEK_STRICT_REVIEW_ENDPOINT_NOT_VERIFIED")
    return str(url).rstrip("/")


def _official_endpoint(value):
    return _endpoint(value, {"/beta"})


def _credential_endpoint(value):
    # Read the existing role's credential only; never trust a changed provider
    # target. The new explicitly selected endpoint is independently beta-bound.
    return _endpoint(value, {"/v1", "/beta"})


def _compile_request(request):
    if type(request) is not dict or request.get("role") != "director":
        raise _error("DEEPSEEK_STRICT_SOURCE_ROLE_REQUIRED")
    if request.get("stage") != "goal_audit":
        raise _error("DEEPSEEK_STRICT_SOURCE_STAGE_REQUIRED")
    wire = ordinary.expected_wire_request(request)
    if wire["max_tokens"] > 24000:
        raise _error("DEEPSEEK_STRICT_SOURCE_OUTPUT_LIMIT_EXCEEDED")
    schema = request["structured_schema"]
    if schema.get("properties", {}).get("schema") != {"const": SOURCE_VERSION}:
        raise _error("DEEPSEEK_STRICT_SOURCE_CONTRACT_REQUIRED")
    try:
        service, manifest = compile_source_schema_with_manifest(schema)
    except StrictSchemaError:
        raise
    wire["tools"][0]["function"].update(parameters=service, strict=True)
    digest(wire)
    return wire, manifest


def expected_wire_request(request, *, source_strict=True):
    """Explicit mapping; ordinary stages retain the frozen wire exactly."""
    if type(source_strict) is not bool:
        raise _error("DEEPSEEK_STRICT_SELECTOR_INVALID")
    if not source_strict:
        return ordinary.expected_wire_request(request)
    return _compile_request(request)[0]


def schema_compilation_manifest(request, *, review_base_url=REVIEW_BASE_URL):
    wire, manifest = _compile_request(request)
    base = _official_endpoint(review_base_url)
    schema = wire["tools"][0]["function"]["parameters"]
    return {**manifest, "client_policy_version": VERSION,
            "model": REVIEW_MODEL, "function_name": TOOL_NAME, "function_strict": True,
            "base_url": base, "endpoint": base + "/chat/completions",
            "endpoint_sha256": digest(["POST", base + "/chat/completions"]),
            "expected_wire_sha256": digest(wire),
            "service_schema_bytes": len(json.dumps(schema, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")),
            "expected_wire_bytes": len(json.dumps(wire, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")),
            "SDK_max_retries": 0, "HTTP_follow_redirects": False,
            "server_strict_schema_requested": True, "server_schema_guarantee": False,
            "new_provider_acceptance_verified": False, "calls_authorized_by_proof": False}


def protocol_binding(request, *, review_base_url=REVIEW_BASE_URL):
    """Small logical provenance binding; full transformations stay in evidence."""
    manifest = schema_compilation_manifest(request, review_base_url=review_base_url)
    fields = ("client_policy_version", "original_contract_sha256", "service_schema_sha256",
              "endpoint_sha256", "function_name", "function_strict", "model", "base_url", "endpoint",
              "expected_wire_sha256", "service_schema_bytes", "expected_wire_bytes", "SDK_max_retries",
              "HTTP_follow_redirects", "original_local_contract_validation_required",
              "service_schema_is_weaker_than_local_contract")
    return {"schema": VERSION + "/protocol_binding", **{key: manifest[key] for key in fields}}


def parse_strict_saved_response(raw, manifest, role, model, thinking, structured_schema, evidence, protocol_binding):
    """Retain the frozen parser's raw/usage faults, then strict JSON arguments.

    JSON/schema service success is not native semantic or human quality success.
    The complete original schema is passed unchanged to the local runtime.
    """
    extra = {"strict_mode": True, "server_strict_schema_requested": True,
             "server_schema_guarantee": False, "transport_version": VERSION,
             "original_contract_sha256": protocol_binding["original_contract_sha256"],
             "service_schema_sha256": protocol_binding["service_schema_sha256"],
             "original_local_contract_validation_required": True,
             "service_schema_is_weaker_than_local_contract": protocol_binding["service_schema_is_weaker_than_local_contract"]}
    try:
        result = evidenced.parse_saved_response(raw, manifest, role, model, thinking, structured_schema, evidence)
    except EvidenceCallError as exc:
        if exc.response_metadata is not None:
            exc.response_metadata.update(extra)
        raise
    metadata = {**result.metadata, **extra}
    try:
        evidenced.strict_envelope(result.text.encode("utf-8"))
    except (ValueError, UnicodeError, TypeError):
        metadata["response_fault_code"] = "STRUCTURED_TOOL_JSON_INVALID"
        evidence.record("strict_arguments_rejected", {"code": "STRUCTURED_TOOL_JSON_INVALID", "metadata": metadata})
        raise EvidenceCallError("STRUCTURED_TOOL_JSON_INVALID", started=True, received=True,
                                outcome_known=True, metadata=metadata, payload=result.response_payload,
                                text=result.text) from None
    evidence.record("strict_arguments_json_received", {"metadata": metadata,
        "local_contract_validation_pending": True, "human_quality_approved": False})
    return RoleResult(text=result.text, metadata=metadata, response_payload=result.response_payload)


class StrictDeepSeekSourceRoleClients:
    """SDK-compatible stage interface; expected request captured per instance."""

    def __init__(self, *, expected_request, review_base_url=REVIEW_BASE_URL,
                 max_wire_utf8_bytes=MAX_BODY_BYTES, http_client_factory=None):
        if type(max_wire_utf8_bytes) is not int or not 0 < max_wire_utf8_bytes <= MAX_BODY_BYTES:
            raise _error("DEEPSEEK_STRICT_WIRE_LIMIT_INVALID")
        self._max_wire_utf8_bytes = max_wire_utf8_bytes
        self._wire = expected_wire_request(expected_request)
        self._request = deepcopy(expected_request)
        self._request_sha256 = digest(self._request)
        self._wire_sha256 = digest(self._wire)
        self._review_base_url = _official_endpoint(review_base_url)
        self._schema_manifest = schema_compilation_manifest(expected_request, review_base_url=review_base_url)
        self._protocol_binding = protocol_binding(expected_request, review_base_url=review_base_url)
        provenance = expected_request.get("input_provenance", {})
        if type(provenance) is not dict:
            raise _error("DEEPSEEK_STRICT_SOURCE_PROVENANCE_INVALID")
        if "source_protocol_binding" in provenance and provenance["source_protocol_binding"] != self._protocol_binding:
            raise _error("DEEPSEEK_STRICT_SOURCE_PROTOCOL_BINDING_MISMATCH")
        self._http_client_factory = http_client_factory or httpx.Client
        self._used = False

    def call(self, role, messages, *, max_tokens=12000, temperature=.4, thinking=None,
             structured_schema=None, writer_model=None, evidence=None):
        if self._used:
            raise _error("DEEPSEEK_STRICT_CLIENT_ALREADY_USED", started=True, outcome_known=False)
        self._used = True
        if evidence is None or digest(self._request) != self._request_sha256:
            raise _error("DEEPSEEK_STRICT_EXPECTED_REQUEST_CHANGED")
        identity = evidence.identity
        if digest(identity) != evidence.identity_sha256 or identity.get("request_sha256") != self._request_sha256 or identity.get("role") != role or identity.get("model") != self._request["model"]:
            raise _error("DEEPSEEK_STRICT_CALL_IDENTITY_MISMATCH")
        expected_args = {"role": self._request["role"], "messages": self._request["messages"],
            "max_tokens": self._request["parameters"]["max_completion_tokens"],
            "temperature": self._request["parameters"]["temperature"],
            "thinking": self._request["parameters"].get("thinking"),
            "structured_schema": self._request["structured_schema"]}
        args = {"role": role, "messages": messages, "max_tokens": max_tokens,
                "temperature": temperature, "thinking": thinking, "structured_schema": structured_schema}
        try:
            match = digest(args) == digest(expected_args)
        except (TypeError, ValueError, UnicodeError):
            raise _error("DEEPSEEK_STRICT_CALL_ARGUMENTS_INVALID") from None
        if not match or writer_model not in (None, WRITER_MODEL) or (role != "writer" and writer_model is not None):
            raise _error("DEEPSEEK_STRICT_CALL_ARGUMENTS_MISMATCH")
        started = received = released = False
        metadata = None
        client = http_client = None
        outbound_manifest = None
        count = 0
        verified_raw_sha = verified_endpoint = None

        def blocked(raw, code):
            protected, redacted = evidence.protect(raw)
            atomic_create(evidence.root / "BLOCKED_OUTBOUND_BODY.raw", protected)
            proof = {"schema": VERSION + "/blocked_wire", "identity_sha256": evidence.identity_sha256,
                "logical_request_sha256": self._request_sha256, "code": code,
                "original_body_sha256": hashlib.sha256(raw).hexdigest(),
                "stored_body_sha256": hashlib.sha256(protected).hexdigest(),
                "credential_redacted": redacted, "provider_dispatch_started": False,
                "provider_received_request": None, "automatic_retry": False}
            atomic_create(evidence.root / "BLOCKED_OUTBOUND_MANIFEST.json",
                evidence.protect(json.dumps(proof, ensure_ascii=False, indent=2).encode())[0])
            evidence.record("model_wire_blocked", {"code": code, "provider_dispatch_started": False})

        def guard(request):
            nonlocal count, verified_raw_sha, verified_endpoint, outbound_manifest, released
            count += 1
            if count != 1:
                raise _error("DEEPSEEK_STRICT_MULTIPLE_OUTBOUND_REQUESTS_BLOCKED",
                             started=released, outcome_known=not released)
            raw = b""
            try:
                raw = request.read()
                if len(raw) > self._max_wire_utf8_bytes:
                    raise _error("DEEPSEEK_STRICT_BODY_SIZE_EXCEEDED")
                wire = evidenced.strict_envelope(raw)
                if digest(wire) != self._wire_sha256:
                    raise _error("DEEPSEEK_STRICT_SERIALIZED_WIRE_MISMATCH")
                if request.method != "POST" or request.url.path.rstrip("/") != "/beta/chat/completions":
                    raise _error("DEEPSEEK_STRICT_ENDPOINT_OPERATION_MISMATCH")
                if request.url.scheme != "https" or request.url.host not in PROVIDER_HOSTS or request.url.port not in (None, 443) or request.url.query or request.url.fragment or request.url.username or request.url.password:
                    raise _error("DEEPSEEK_STRICT_ENDPOINT_PROTOCOL_MISMATCH")
                verified_raw_sha = hashlib.sha256(raw).hexdigest()
                verified_endpoint = (request.method, str(request.url))
                proof = {"schema": VERSION + "/outbound_proof", "status": "wire_verified_before_send",
                    "identity_sha256": evidence.identity_sha256,
                    "logical_request_sha256": self._request_sha256,
                    "expected_wire_sha256": self._wire_sha256, "actual_wire_sha256": digest(wire),
                    "actual_request_body_sha256": verified_raw_sha,
                    "full_wire_equals_mapped_logical_request": True, "body_bytes": len(raw),
                    "max_wire_utf8_bytes": self._max_wire_utf8_bytes,
                    "mapped_fields": sorted(wire), "messages_sha256": digest(wire["messages"]),
                    "structured_schema_sha256": digest(structured_schema),
                    "original_contract_sha256": self._schema_manifest["original_contract_sha256"],
                    "service_schema_sha256": self._schema_manifest["service_schema_sha256"],
                    "source_protocol_binding_sha256": digest(self._protocol_binding),
                    "schema_compilation_manifest_sha256": digest(self._schema_manifest),
                    "service_schema_is_weaker_than_local_contract": self._schema_manifest["service_schema_is_weaker_than_local_contract"],
                    "original_local_contract_validation_required": True, "function_strict": True,
                    "server_strict_schema_requested": True,
                    "endpoint_method": request.method, "endpoint_path": request.url.path,
                    "provider_endpoint_host": request.url.host,
                    "verified_endpoint_sha256": digest(list(verified_endpoint)),
                    "writer_reasoning_effort": WRITER_REASONING_EFFORT if role == "writer" else None,
                    "SDK_max_retries": 0, "HTTP_follow_redirects": False,
                    "server_stream_requested": False, "server_schema_guarantee": False,
                    "new_provider_acceptance_verified": False, "provider_received_request": None,
                    "calls_authorized_by_proof": False, "automatic_retry": False}
                atomic_create(evidence.root / "DEEPSEEK_STRICT_SCHEMA_MANIFEST.json",
                    evidence.protect(json.dumps(self._schema_manifest, ensure_ascii=False, indent=2, allow_nan=False).encode())[0])
                atomic_create(evidence.root / "DEEPSEEK_STRICT_WIRE_PREFLIGHT.json",
                    evidence.protect(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False).encode())[0])
                evidence.record("model_wire_verified", {"actual_request_body_sha256": verified_raw_sha,
                    "logical_request_sha256": self._request_sha256, "provider_received_request": None})
                outbound_manifest = bounded.save_request_body(evidence, raw, role=role)
                # Capture is a separate operation: recheck target and bytes after
                # persistence, and verify the persisted manifest before transport.
                if (request.method, str(request.url)) != verified_endpoint:
                    raise _error("DEEPSEEK_STRICT_ENDPOINT_CHANGED_AFTER_PREFLIGHT")
                if hashlib.sha256(request.read()).hexdigest() != verified_raw_sha:
                    raise _error("DEEPSEEK_STRICT_WIRE_CHANGED_AFTER_PREFLIGHT")
                stored = json.loads((evidence.root / "REQUEST_BODY_MANIFEST.json").read_text(encoding="utf-8"))
                if stored.get("identity_sha256") != evidence.identity_sha256 or stored.get("original_sha256") != verified_raw_sha:
                    raise _error("DEEPSEEK_STRICT_CAPTURE_BINDING_MISMATCH")
                released = True
            except Exception as exc:
                code = exc.code if isinstance(exc, EvidenceCallError) else "DEEPSEEK_STRICT_OUTBOUND_EVIDENCE_OR_WIRE_INVALID"
                try:
                    blocked(raw, code)
                except Exception as storage_exc:
                    raise _error("DEEPSEEK_STRICT_BLOCK_EVIDENCE_SAVE_FAILED", cause_type=type(storage_exc).__name__) from None
                raise _error(code, cause_type=type(exc).__name__) from None

        try:
            from openai import OpenAI
            # Inherit only the validated existing review credential. The beta
            # target comes from this independently selected source-only mode.
            config = role_config(role)
            evidence.register_secrets(config.api_key)
            _credential_endpoint(config.base_url)
            base_url = self._review_base_url
            if role == "director" and config.model != REVIEW_MODEL:
                raise _error("DEEPSEEK_STRICT_REVIEW_CONFIG_MODEL_MISMATCH")
            http_client = self._http_client_factory(timeout=settings.SCRIPT_LLM_TIMEOUT_SECONDS,
                event_hooks={"request": [guard]}, follow_redirects=False)
            if not isinstance(http_client, httpx.Client) or http_client.follow_redirects:
                raise _error("DEEPSEEK_STRICT_HTTP_FACTORY_POLICY_MISMATCH")
            # Offline factories cannot discard the mandatory final hook or put
            # mutation hooks after it. Production uses the standard httpx client.
            extras = [hook for hook in http_client.event_hooks.get("request", []) if hook is not guard]
            http_client.event_hooks = {**http_client.event_hooks, "request": [*extras, guard]}
            client = OpenAI(api_key=config.api_key, base_url=base_url,
                timeout=settings.SCRIPT_LLM_TIMEOUT_SECONDS, max_retries=0, http_client=http_client)
            parameters = deepcopy(self._wire)
            if "thinking" in parameters:
                parameters["extra_body"] = {"thinking": parameters.pop("thinking")}
            evidence.record("client_configured", {"role": role, "model": self._request["model"],
                "base_url": base_url, "timeout_seconds": settings.SCRIPT_LLM_TIMEOUT_SECONDS,
                "max_retries": 0, "follow_redirects": False, "server_stream_requested": False,
                "client_policy_version": VERSION, "strict_response_parser": VERSION + "/arguments",
                "logical_thinking_mode": thinking,
                "reasoning_effort": WRITER_REASONING_EFFORT if role == "writer" else None,
                "tool_choice_policy": bounded.tool_choice_policy(role), "server_schema_guarantee": False,
                "function_strict": True, "server_strict_schema_requested": True,
                "original_contract_sha256": self._schema_manifest["original_contract_sha256"],
                "service_schema_sha256": self._schema_manifest["service_schema_sha256"],
                "source_protocol_binding_sha256": digest(self._protocol_binding),
                "schema_compilation_manifest_sha256": digest(self._schema_manifest)})
            evidence.record("dispatch_attempt_started", {"meaning": "SDK method about to be called; not a server acknowledgement"})
            started = True
            with client.chat.completions.with_streaming_response.create(**parameters) as response:
                received = True
                metadata = evidenced.http_metadata(response.status_code, response.headers)
                metadata = json.loads(evidence.protect(json.dumps(metadata).encode())[0])
                evidence.record("http_headers_received", metadata)
                protected, manifest = evidence.save_body(response.read(), metadata)
            return parse_strict_saved_response(protected, manifest, role, self._request["model"],
                                                  thinking, structured_schema, evidence, self._schema_manifest)
        except EvidenceCallError:
            raise
        except Exception as exc:
            cause = getattr(exc, "__cause__", None)
            if isinstance(cause, EvidenceCallError):
                raise cause from None
            response, status = getattr(exc, "response", None), getattr(exc, "status_code", None)
            if response is not None and type(status) is int:
                received = True
                metadata = evidenced.http_metadata(status, response.headers, extra_request_id=getattr(exc, "request_id", None))
                metadata = json.loads(evidence.protect(json.dumps(metadata).encode())[0])
                try:
                    evidence.record("http_error_headers_received", metadata)
                    raw = response.read()
                except Exception as capture_exc:
                    raise EvidenceCallError("HTTP_ERROR_BODY_UNAVAILABLE", started=started, received=True,
                        outcome_known=True, metadata=metadata, cause_type=type(capture_exc).__name__) from None
                try:
                    protected, manifest = evidence.save_body(raw, metadata)
                except Exception as capture_exc:
                    raise EvidenceCallError("HTTP_ERROR_EVIDENCE_SAVE_FAILED", started=started, received=True,
                        outcome_known=True, metadata=metadata, cause_type=type(capture_exc).__name__) from None
                return parse_strict_saved_response(protected, manifest, role, self._request["model"],
                                                       thinking, structured_schema, evidence, self._schema_manifest)
            code = "RESPONSE_CAPTURE_INTERRUPTED" if received else ("TRANSPORT_EXCEPTION" if started else "CLIENT_PREFLIGHT_FAILED")
            try:
                evidence.record("call_interrupted", {"code": code, "cause_type": type(exc).__name__,
                    "headers_received": received, "outbound_body_saved": outbound_manifest is not None})
            except Exception:
                pass
            raise EvidenceCallError(code, started=started, received=received, outcome_known=not started,
                metadata=metadata, cause_type=type(exc).__name__) from None
        finally:
            for resource in (client, http_client):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception:
                        pass



def make_client_factory(expected_request, *, source_strict=False, writer_base_url=WRITER_BASE_URL,
                        review_base_url=REVIEW_BASE_URL, max_wire_utf8_bytes=MAX_BODY_BYTES,
                        http_client_factory=None):
    """Explicit selector. Ordinary roles keep the unchanged frozen transport."""
    if type(source_strict) is not bool:
        raise _error("DEEPSEEK_STRICT_SELECTOR_INVALID")
    if not source_strict:
        return ordinary.make_client_factory(expected_request, writer_base_url=writer_base_url,
                                             http_client_factory=http_client_factory)
    frozen = deepcopy(expected_request)
    # Preview validates before the runtime creates its provider claim/client.
    expected_wire_request(frozen)
    _official_endpoint(review_base_url)
    def factory():
        return StrictDeepSeekSourceRoleClients(expected_request=frozen, review_base_url=review_base_url,
                                               max_wire_utf8_bytes=max_wire_utf8_bytes,
                                               http_client_factory=http_client_factory)
    return factory
