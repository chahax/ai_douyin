"""Independent M3.1 Flash transport, bound to one logical request and one send.

The old M3 adapter/configuration remains untouched. Credentials are read from
its writer role, while the exact new model and official domestic endpoint are
selected here. This adapter does not authorize calls, retry content, or decide
creative quality; the caller owns those policies and usage acceptance.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import httpx

from scripts import creative_bounded_format_role_clients_v1 as bounded
from scripts import creative_evidenced_role_clients_v1 as evidenced
from scripts.creative_call_evidence_v1 import atomic_create, digest
from src.content_factory.creative_workflow_roles import role_config
from src.shared.config import settings

VERSION = "creative_m31_flash_role_clients/v1"
WRITER_MODEL = "MiniMax-M3.1-Flash-Preview"
WRITER_BASE_URL = "https://api.minimax.cn/v1"
WRITER_REASONING_EFFORT = "medium"
WRITER_MAX_COMPLETION_TOKENS = 16000
REVIEW_MODEL = "deepseek-flash"
TOOL_NAME = evidenced.TOOL_NAME
EvidenceCallError = evidenced.EvidenceCallError
MAX_BODY_BYTES = 64_000_000
PROVIDER_HOSTS = {"writer": {"api.minimax.cn"}, "director": {"api.deepseek.com"}}


def _error(code, *, started=False, outcome_known=True, cause_type=None):
    return EvidenceCallError(code, started=started, outcome_known=outcome_known,
                             cause_type=cause_type)


def expected_wire_request(request):
    """Pure mapping of this verified, text-only experiment. No SDK or secrets."""
    if type(request) is not dict or request.get("role") not in ("writer", "director"):
        raise _error("M31_LOGICAL_REQUEST_INVALID")
    # Provenance/stage remain in the logical identity, never invented wire fields.
    if set(request) - {"role", "model", "messages", "parameters", "structured_schema",
                       "input_provenance", "stage"}:
        raise _error("M31_LOGICAL_FIELDS_NOT_MAPPED")
    role = request["role"]
    model = WRITER_MODEL if role == "writer" else REVIEW_MODEL
    if request.get("model") != model:
        raise _error("M31_ROLE_MODEL_MISMATCH")
    parameters = request.get("parameters")
    if type(parameters) is not dict or set(parameters) - {
            "temperature", "thinking", "max_completion_tokens", "reasoning_effort"}:
        raise _error("M31_LOGICAL_PARAMETERS_NOT_MAPPED")
    cap = parameters.get("max_completion_tokens")
    if type(cap) is not int or not 0 < cap <= 32000:
        raise _error("M31_OUTPUT_LIMIT_INVALID")
    if type(parameters.get("temperature")) not in (int, float) or parameters["temperature"] != .4:
        raise _error("M31_TEMPERATURE_INVALID")
    mode = parameters.get("thinking")
    if role == "writer":
        if mode != "adaptive" or parameters.get("reasoning_effort", WRITER_REASONING_EFFORT) != WRITER_REASONING_EFFORT:
            raise _error("M31_REASONING_MODE_INVALID")
        if cap != WRITER_MAX_COMPLETION_TOKENS:
            raise _error("M31_WRITER_OUTPUT_LIMIT_NOT_VERIFIED")
    elif mode != "disabled" or "reasoning_effort" in parameters:
        raise _error("M31_REVIEW_MODE_INVALID")
    messages = request.get("messages")
    if type(messages) is not list or not messages:
        raise _error("M31_TEXT_MESSAGES_REQUIRED")
    for message in messages:
        if type(message) is not dict or set(message) - {"role", "content"} or message.get("role") not in {
                "system", "user", "assistant"} or not isinstance(message.get("content"), str):
            raise _error("M31_TEXT_MESSAGES_REQUIRED")
    schema = request.get("structured_schema")
    if type(schema) is not dict or not schema:
        raise _error("M31_STRUCTURED_SCHEMA_REQUIRED")
    wire = {"model": model, "messages": deepcopy(messages), "temperature": .4,
            "max_completion_tokens" if role == "writer" else "max_tokens": cap}
    description = "提交本阶段完整结构化创作结果" if role == "writer" else "提交本阶段完整文本审核结果，保留所有结论及真实证据"
    wire["tools"] = [{"type": "function", "function": {
        "name": TOOL_NAME, "description": description, "parameters": deepcopy(schema)}}]
    if role == "writer":
        wire["reasoning_effort"] = WRITER_REASONING_EFFORT
        # M3.1 thinking is mandatory. The old disabled/adaptive extra-body fields
        # and undocumented forced tool/strict claims are deliberately absent.
    else:
        wire["thinking"] = {"type": "disabled"}
        wire["tool_choice"] = {"type": "function", "function": {"name": TOOL_NAME}}
    try:
        digest(wire)
    except (TypeError, ValueError, UnicodeError):
        raise _error("M31_LOGICAL_REQUEST_NOT_JSON") from None
    return wire


def _official_endpoint(value, role):
    try:
        url = httpx.URL(value)
        valid = (url.scheme == "https" and url.host in PROVIDER_HOSTS[role] and
                 url.path.rstrip("/") == "/v1" and url.port in (None, 443) and
                 not url.query and not url.fragment and not url.username and not url.password)
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise _error("M31_WRITER_ENDPOINT_NOT_VERIFIED" if role == "writer" else "M31_REVIEW_ENDPOINT_NOT_VERIFIED")
    return str(url).rstrip("/")


class M31FlashRoleClients:
    """SDK-compatible stage interface; expected request captured per instance."""

    def __init__(self, *, expected_request, writer_base_url=WRITER_BASE_URL,
                 http_client_factory=None):
        self._wire = expected_wire_request(expected_request)
        self._request = deepcopy(expected_request)
        self._request_sha256 = digest(self._request)
        self._wire_sha256 = digest(self._wire)
        self._writer_base_url = _official_endpoint(writer_base_url, "writer")
        self._http_client_factory = http_client_factory or httpx.Client
        self._used = False

    def call(self, role, messages, *, max_tokens=12000, temperature=.4, thinking=None,
             structured_schema=None, writer_model=None, evidence=None):
        if self._used:
            raise _error("M31_CLIENT_ALREADY_USED", started=True, outcome_known=False)
        self._used = True
        if evidence is None or digest(self._request) != self._request_sha256:
            raise _error("M31_EXPECTED_REQUEST_CHANGED")
        identity = evidence.identity
        if digest(identity) != evidence.identity_sha256 or identity.get("request_sha256") != self._request_sha256 or identity.get("role") != role or identity.get("model") != self._request["model"]:
            raise _error("M31_CALL_IDENTITY_MISMATCH")
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
            raise _error("M31_CALL_ARGUMENTS_INVALID") from None
        if not match or writer_model not in (None, WRITER_MODEL) or (role != "writer" and writer_model is not None):
            raise _error("M31_CALL_ARGUMENTS_MISMATCH")
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
                raise _error("M31_MULTIPLE_OUTBOUND_REQUESTS_BLOCKED",
                             started=released, outcome_known=not released)
            raw = b""
            try:
                raw = request.read()
                if len(raw) > MAX_BODY_BYTES:
                    raise _error("M31_BODY_SIZE_EXCEEDED")
                wire = evidenced.strict_envelope(raw)
                if digest(wire) != self._wire_sha256:
                    raise _error("M31_SERIALIZED_WIRE_MISMATCH")
                if request.method != "POST" or request.url.path.rstrip("/") != "/v1/chat/completions":
                    raise _error("M31_ENDPOINT_OPERATION_MISMATCH")
                if request.url.scheme != "https" or request.url.host not in PROVIDER_HOSTS[role] or request.url.port not in (None, 443) or request.url.query or request.url.fragment or request.url.username or request.url.password:
                    raise _error("M31_ENDPOINT_PROTOCOL_MISMATCH")
                verified_raw_sha = hashlib.sha256(raw).hexdigest()
                verified_endpoint = (request.method, str(request.url))
                proof = {"schema": VERSION + "/outbound_proof", "status": "wire_verified_before_send",
                    "identity_sha256": evidence.identity_sha256,
                    "logical_request_sha256": self._request_sha256,
                    "expected_wire_sha256": self._wire_sha256, "actual_wire_sha256": digest(wire),
                    "actual_request_body_sha256": verified_raw_sha,
                    "full_wire_equals_mapped_logical_request": True, "body_bytes": len(raw),
                    "mapped_fields": sorted(wire), "messages_sha256": digest(wire["messages"]),
                    "structured_schema_sha256": digest(structured_schema),
                    "endpoint_method": request.method, "endpoint_path": request.url.path,
                    "provider_endpoint_host": request.url.host,
                    "verified_endpoint_sha256": digest(list(verified_endpoint)),
                    "writer_reasoning_effort": WRITER_REASONING_EFFORT if role == "writer" else None,
                    "SDK_max_retries": 0, "HTTP_follow_redirects": False,
                    "server_stream_requested": False, "server_schema_guarantee": False,
                    "new_provider_acceptance_verified": False, "provider_received_request": None,
                    "calls_authorized_by_proof": False, "automatic_retry": False}
                atomic_create(evidence.root / "M31_WIRE_PREFLIGHT.json",
                    evidence.protect(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False).encode())[0])
                evidence.record("model_wire_verified", {"actual_request_body_sha256": verified_raw_sha,
                    "logical_request_sha256": self._request_sha256, "provider_received_request": None})
                outbound_manifest = bounded.save_request_body(evidence, raw, role=role)
                # Capture is a separate operation: recheck target and bytes after
                # persistence, and verify the persisted manifest before transport.
                if (request.method, str(request.url)) != verified_endpoint:
                    raise _error("M31_ENDPOINT_CHANGED_AFTER_PREFLIGHT")
                if hashlib.sha256(request.read()).hexdigest() != verified_raw_sha:
                    raise _error("M31_WIRE_CHANGED_AFTER_PREFLIGHT")
                stored = json.loads((evidence.root / "REQUEST_BODY_MANIFEST.json").read_text(encoding="utf-8"))
                if stored.get("identity_sha256") != evidence.identity_sha256 or stored.get("original_sha256") != verified_raw_sha:
                    raise _error("M31_CAPTURE_BINDING_MISMATCH")
                released = True
            except Exception as exc:
                code = exc.code if isinstance(exc, EvidenceCallError) else "M31_OUTBOUND_EVIDENCE_OR_WIRE_INVALID"
                try:
                    blocked(raw, code)
                except Exception as storage_exc:
                    raise _error("M31_BLOCK_EVIDENCE_SAVE_FAILED", cause_type=type(storage_exc).__name__) from None
                raise _error(code, cause_type=type(exc).__name__) from None

        try:
            from openai import OpenAI
            # Only the key is inherited for the writer; its frozen M3 model and
            # endpoint are not silently changed, reused as aliases, or patched.
            config = role_config(role)
            evidence.register_secrets(config.api_key)
            base_url = self._writer_base_url if role == "writer" else _official_endpoint(config.base_url, "director")
            if role == "director" and config.model != REVIEW_MODEL:
                raise _error("M31_REVIEW_CONFIG_MODEL_MISMATCH")
            http_client = self._http_client_factory(timeout=settings.SCRIPT_LLM_TIMEOUT_SECONDS,
                event_hooks={"request": [guard]}, follow_redirects=False)
            if not isinstance(http_client, httpx.Client) or http_client.follow_redirects:
                raise _error("M31_HTTP_FACTORY_POLICY_MISMATCH")
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
                "client_policy_version": VERSION, "strict_response_parser": evidenced.VERSION,
                "logical_thinking_mode": thinking,
                "reasoning_effort": WRITER_REASONING_EFFORT if role == "writer" else None,
                "tool_choice_policy": bounded.tool_choice_policy(role), "server_schema_guarantee": False})
            evidence.record("dispatch_attempt_started", {"meaning": "SDK method about to be called; not a server acknowledgement"})
            started = True
            with client.chat.completions.with_streaming_response.create(**parameters) as response:
                received = True
                metadata = evidenced.http_metadata(response.status_code, response.headers)
                metadata = json.loads(evidence.protect(json.dumps(metadata).encode())[0])
                evidence.record("http_headers_received", metadata)
                protected, manifest = evidence.save_body(response.read(), metadata)
            return evidenced.parse_saved_response(protected, manifest, role, self._request["model"],
                                                  thinking, structured_schema, evidence)
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
                return evidenced.parse_saved_response(protected, manifest, role, self._request["model"],
                                                       thinking, structured_schema, evidence)
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


def make_client_factory(expected_request, *, writer_base_url=WRITER_BASE_URL,
                        http_client_factory=None):
    """Zero-argument runtime factory, with an immutable per-request snapshot."""
    frozen = deepcopy(expected_request)
    def factory():
        return M31FlashRoleClients(expected_request=frozen, writer_base_url=writer_base_url,
                                  http_client_factory=http_client_factory)
    return factory
