"""Bind a logical stage request to the real SDK body before HTTP submission.

Composition preserves the frozen bounded client's response parser, original
body journal and zero SDK retries. No globals in that client are replaced.
Each instance belongs to one complete logical request and one call; a runtime
must close its zero-argument client factory over that request before dispatch.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json

import httpx

from scripts import creative_bounded_format_role_clients_v1 as bounded
from scripts.creative_call_evidence_v1 import atomic_create, digest
from src.content_factory.creative_provider_preflight_v1 import (
    ProviderPreflightError, preflight_text_request,
)

VERSION = "creative_capability_role_clients/v2"
EvidenceCallError = bounded.EvidenceCallError
TOOL_NAME = bounded.TOOL_NAME
role_config = bounded.role_config
# Conservative decimal-byte limits from MiniMax's current compatibility guide.
# Counting bytes does not inspect images or verify remote URL accessibility.
MAX_BODY_BYTES = 64_000_000
MAX_IMAGE_BYTES = 10_000_000
IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
IMAGE_LIMIT_SOURCE = "https://platform.minimax.io/docs/api-reference/text-openai-api"
PROVIDER_HOSTS = {"writer": {"api.minimaxi.com", "api.minimax.io"},
    "director": {"api.deepseek.com"}}


def _error(code, *, started=False, outcome_known=True, cause_type=None):
    return EvidenceCallError(code, started=started, outcome_known=outcome_known,
        cause_type=cause_type)


def expected_wire_request(request, registry=None):
    """Pure, exact mapping of the selected frozen bounded-role adapter.

    This is an expected body, not an SDK serialization or a provider receipt.
    Unknown logical parameters are rejected rather than silently dropped.
    """
    if type(request) is not dict or request.get("role") not in ("writer", "director"):
        raise _error("CAPABILITY_LOGICAL_REQUEST_INVALID")
    logical_report = preflight_text_request(request, registry)
    if logical_report["input_shape"] != "logical_request" or logical_report["blocked"]:
        raise _error("CAPABILITY_LOGICAL_REQUEST_INVALID")
    parameters = request["parameters"]
    if set(parameters) - {"temperature", "thinking", "max_completion_tokens"}:
        raise _error("CAPABILITY_LOGICAL_PARAMETERS_NOT_MAPPED")
    cap = parameters.get("max_completion_tokens")
    if type(cap) is not int or not 0 < cap <= 32000:
        raise _error("CAPABILITY_OUTPUT_LIMIT_NOT_MAPPED")
    if type(parameters.get("temperature")) not in (int, float) or parameters["temperature"] != .4:
        raise _error("CAPABILITY_TEMPERATURE_NOT_MAPPED")
    role = request["role"]
    mode = parameters.get("thinking")
    if mode not in (None, "disabled", "adaptive") or (role == "director" and mode == "adaptive"):
        raise _error("CAPABILITY_THINKING_NOT_MAPPED")
    if request["model"] != ("MiniMax-M3" if role == "writer" else "deepseek-flash"):
        raise _error("CAPABILITY_ROLE_MODEL_MISMATCH")
    wire = {"model": request["model"], "messages": deepcopy(request["messages"]),
        "temperature": parameters["temperature"],
        "max_completion_tokens" if role == "writer" else "max_tokens": cap}
    if mode in ("disabled", "adaptive"):
        wire["thinking"] = {"type": mode}
        if mode == "adaptive":
            wire["reasoning_split"] = True
    schema = request.get("structured_schema")
    if role == "director" and not schema:
        raise _error("CAPABILITY_REVIEW_SCHEMA_REQUIRED")
    if schema is not None:
        description = "提交本阶段完整结构化创作结果" if role == "writer" else "提交本阶段完整文本审核结果，保留所有结论及真实证据"
        wire["tools"] = [{"type": "function", "function": {
            "name": TOOL_NAME, "description": description, "parameters": deepcopy(schema)}}]
        if role == "director":
            wire["tool_choice"] = {"type": "function", "function": {"name": TOOL_NAME}}
    preflight_text_request(wire, registry)
    return wire


def _image_constraints(wire):
    rows = []
    for message_index, message in enumerate(wire["messages"]):
        content = message.get("content")
        if type(content) is not list:
            continue
        for content_index, item in enumerate(content):
            if item.get("type") != "image_url":
                continue
            url = item["image_url"]["url"]
            row = {"message_index": message_index, "content_index": content_index,
                "url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
                "image_content_inspected": False}
            if url.startswith("data:"):
                try:
                    header, encoded = url.split(",", 1)
                    mime, encoding = header[5:].split(";", 1)
                    if mime not in IMAGE_MIME_TYPES or encoding != "base64":
                        raise ValueError("unsupported data image format")
                    original = base64.b64decode(encoded, validate=True)
                    if not original or len(original) > MAX_IMAGE_BYTES:
                        raise ValueError("data image size outside bounds")
                except (ValueError, TypeError):
                    raise _error("CAPABILITY_IMAGE_FORMAT_OR_SIZE_INVALID") from None
                row.update(format=mime, size_bytes=len(original),
                    original_image_bytes_sha256=hashlib.sha256(original).hexdigest(),
                    format_and_size_checked=True, decoded_image_format_verified=False)
            else:
                row.update(format_and_size_checked=False,
                    unverified="remote_image_format_size_and_accessibility")
            rows.append(row)
    return {"source": IMAGE_LIMIT_SOURCE, "max_image_bytes": MAX_IMAGE_BYTES,
        "max_body_bytes": MAX_BODY_BYTES, "limits_use_conservative_decimal_bytes": True,
        "images": rows, "remote_images_not_fetched": True,
        "human_image_approval_verified": False}


class CapabilityRoleClients:
    """Drop-in ``call`` interface, explicitly bound to a complete stage request."""

    def __init__(self, *, expected_request, registry=None, http_client_factory=None):
        self._request = deepcopy(expected_request)
        self._request_sha256 = digest(self._request)
        self._registry = deepcopy(registry)
        self._logical_report = preflight_text_request(self._request, self._registry)
        self._wire = expected_wire_request(self._request, self._registry)
        self._wire_sha256 = digest(self._wire)
        self._http_client_factory = http_client_factory or httpx.Client
        self._used = False

    def call(self, role, messages, *, max_tokens=12000, temperature=.4, thinking=None,
             structured_schema=None, writer_model=None, evidence=None):
        if self._used:
            raise _error("CAPABILITY_CLIENT_ALREADY_USED", started=True, outcome_known=False)
        self._used = True
        if evidence is None or digest(self._request) != self._request_sha256:
            raise _error("CAPABILITY_EXPECTED_REQUEST_CHANGED")
        identity = evidence.identity
        if digest(identity) != evidence.identity_sha256 or identity.get("request_sha256") != self._request_sha256 or identity.get("role") != role or identity.get("model") != self._request["model"]:
            raise _error("CAPABILITY_CALL_IDENTITY_MISMATCH")
        expected_args = {"role": self._request["role"], "messages": self._request["messages"],
            "max_tokens": self._request["parameters"]["max_completion_tokens"],
            "temperature": self._request["parameters"]["temperature"],
            "thinking": self._request["parameters"].get("thinking"),
            "structured_schema": self._request.get("structured_schema")}
        args = {"role": role, "messages": messages, "max_tokens": max_tokens,
            "temperature": temperature, "thinking": thinking, "structured_schema": structured_schema}
        try:
            arguments_match = digest(args) == digest(expected_args)
        except (TypeError, ValueError, UnicodeError):
            raise _error("CAPABILITY_CALL_ARGUMENTS_INVALID") from None
        if not arguments_match or writer_model not in (None, "MiniMax-M3") or (role != "writer" and writer_model is not None):
            raise _error("CAPABILITY_CALL_ARGUMENTS_MISMATCH")
        count = 0
        verified_raw_sha = None
        verified_endpoint = None
        released_for_send = False
        factory_count = 0

        def save_block(raw, code):
            # A rejected outgoing body is not a sent request or server result.
            # No header, token, URL or response metadata is consulted here.
            protected, redacted = evidence.protect(raw)
            atomic_create(evidence.root / "BLOCKED_OUTBOUND_BODY.raw", protected)
            proof = {"schema": VERSION + "/blocked_wire", "identity_sha256": evidence.identity_sha256,
                "logical_request_sha256": self._request_sha256, "code": code,
                "original_body_sha256": hashlib.sha256(raw).hexdigest(),
                "stored_body_sha256": hashlib.sha256(protected).hexdigest(),
                "credential_redacted": redacted, "provider_dispatch_started": False,
                "provider_received_request": None, "automatic_retry": False}
            atomic_create(evidence.root / "BLOCKED_OUTBOUND_MANIFEST.json",
                evidence.protect(json.dumps(proof, ensure_ascii=False, indent=2).encode("utf-8"))[0])
            evidence.record("capability_wire_blocked", {"code": code,
                "original_body_sha256": proof["original_body_sha256"], "provider_dispatch_started": False})

        def guard(request):
            nonlocal count, verified_raw_sha, verified_endpoint
            count += 1
            if count != 1:
                raise _error("CAPABILITY_MULTIPLE_OUTBOUND_REQUESTS_BLOCKED",
                    started=released_for_send, outcome_known=not released_for_send)
            raw = request.read()
            try:
                if len(raw) > MAX_BODY_BYTES:
                    raise _error("CAPABILITY_BODY_SIZE_EXCEEDED")
                wire = bounded.prior.strict_envelope(raw)
                wire_report = preflight_text_request(wire, self._registry)
                if wire_report["blocked"]:
                    raise _error("CAPABILITY_SERIALIZED_WIRE_BLOCKED")
                if wire_report["registry_sha256"] != self._logical_report["registry_sha256"]:
                    raise _error("CAPABILITY_REGISTRY_CHANGED")
                if digest(wire) != self._wire_sha256:
                    raise _error("CAPABILITY_SERIALIZED_WIRE_MISMATCH")
                if request.method != "POST" or request.url.path.rstrip("/") != "/v1/chat/completions":
                    raise _error("CAPABILITY_ENDPOINT_OPERATION_MISMATCH")
                if request.url.scheme != "https" or request.url.host not in PROVIDER_HOSTS[role] or request.url.port not in (None, 443) or request.url.query or request.url.fragment or request.url.username or request.url.password:
                    raise _error("CAPABILITY_ENDPOINT_PROTOCOL_MISMATCH")
                verified_endpoint = (request.method, str(request.url))
                images = _image_constraints(wire)
                verified_raw_sha = hashlib.sha256(raw).hexdigest()
                proof = {"schema": VERSION + "/outbound_capability_proof",
                    "status": "capability_preflight_passed", "dispatch_before_verify": False,
                    "identity_sha256": evidence.identity_sha256,
                    "logical_request_sha256": self._request_sha256,
                    "expected_wire_sha256": self._wire_sha256,
                    "actual_wire_sha256": digest(wire), "original_body_sha256": verified_raw_sha,
                    "actual_request_body_sha256": verified_raw_sha,
                    "body_bytes": len(raw), "full_wire_equals_mapped_logical_request": True,
                    "mapped_fields": sorted(self._wire),
                    "messages_sha256": digest(wire["messages"]),
                    "structured_schema_sha256": digest(structured_schema),
                    "logical_capability_report": self._logical_report,
                    "wire_capability_report": wire_report, "image_constraints": images,
                    "SDK_max_retries": 0, "HTTP_follow_redirects": False,
                    "capture_boundary": "httpx_request_hook_before_original_capture_and_send",
                    "endpoint_method": "POST", "endpoint_path": "/v1/chat/completions",
                    "verified_endpoint_sha256": digest(list(verified_endpoint)),
                    "provider_endpoint_host_matched": True,
                    "provider_received_request": None, "new_provider_acceptance_verified": False,
                    "calls_authorized_by_proof": False, "automatic_retry": False}
                atomic_create(evidence.root / "CAPABILITY_PREFLIGHT.json",
                    evidence.protect(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8"))[0])
                evidence.record("capability_wire_verified", {
                    "logical_request_sha256": self._request_sha256,
                    "original_body_sha256": verified_raw_sha,
                    "registry_sha256": wire_report["registry_sha256"],
                    "provider_received_request": None})
            except Exception as exc:
                code = exc.code if isinstance(exc, (EvidenceCallError, ProviderPreflightError)) else "CAPABILITY_SERIALIZED_WIRE_INVALID"
                try:
                    save_block(raw, code)
                except Exception as storage_exc:
                    raise _error("CAPABILITY_BLOCK_EVIDENCE_SAVE_FAILED", cause_type=type(storage_exc).__name__) from None
                raise _error(code, cause_type=type(exc).__name__) from None

        def final_guard(request):
            nonlocal released_for_send
            try:
                if verified_endpoint is None or (request.method, str(request.url)) != verified_endpoint:
                    raise _error("CAPABILITY_ENDPOINT_CHANGED_AFTER_PREFLIGHT")
                if verified_raw_sha is None or hashlib.sha256(request.read()).hexdigest() != verified_raw_sha:
                    raise _error("CAPABILITY_WIRE_CHANGED_AFTER_PREFLIGHT")
                # The frozen capture already saved raw bytes and its manifest.
                manifest = json.loads((evidence.root / "REQUEST_BODY_MANIFEST.json").read_text(encoding="utf-8"))
                if manifest.get("identity_sha256") != evidence.identity_sha256 or manifest.get("original_sha256") != verified_raw_sha:
                    raise _error("CAPABILITY_CAPTURE_BINDING_MISMATCH")
                released_for_send = True
            except EvidenceCallError:
                raise
            except Exception as exc:
                raise _error("CAPABILITY_FINAL_CAPTURE_CHECK_FAILED", cause_type=type(exc).__name__) from None

        def guarded_factory(**kwargs):
            nonlocal factory_count
            factory_count += 1
            if factory_count != 1 or kwargs.get("follow_redirects") is not False:
                raise _error("CAPABILITY_HTTP_FACTORY_POLICY_MISMATCH")
            old_hooks = list(kwargs.get("event_hooks", {}).get("request", []))
            client = self._http_client_factory(**kwargs)
            if not isinstance(client, httpx.Client) or client.follow_redirects:
                if isinstance(client, httpx.Client):
                    client.close()
                raise _error("CAPABILITY_HTTP_FACTORY_POLICY_MISMATCH")
            # Injectable fixture hooks run first; the actual final guard remains
            # last. A factory cannot bypass the checks by dropping supplied hooks.
            actual_hooks = list(client.event_hooks.get("request", []))
            external = [hook for hook in actual_hooks if hook not in old_hooks]
            client.event_hooks = {**client.event_hooks,
                "request": [*external, guard, *old_hooks, final_guard]}
            return client

        delegate = bounded.BoundedFormatRoleClients(http_client_factory=guarded_factory)
        return delegate.call(role, messages, max_tokens=max_tokens, temperature=temperature,
            thinking=thinking, structured_schema=structured_schema, writer_model=writer_model, evidence=evidence)


def make_client_factory(expected_request, *, registry=None, http_client_factory=None):
    """Return a zero-argument factory for ContinuationRuntime, no global context."""
    frozen_request = deepcopy(expected_request)
    frozen_registry = deepcopy(registry)

    def factory():
        return CapabilityRoleClients(expected_request=frozen_request,
            registry=frozen_registry, http_client_factory=http_client_factory)
    return factory
