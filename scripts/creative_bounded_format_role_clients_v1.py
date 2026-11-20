"""Explicit bounded-format policy; strict response acceptance and no SDK retries.

MiniMax's documented tools example does not promise forced tool_choice. Writer
requests therefore omit it; this does not guarantee a tool response. Director
requests keep the existing forced-function policy. Scope/call limits belong to
the injected runtime, never to this transport adapter.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import httpx

from scripts import creative_evidenced_role_clients_v1 as prior
from scripts.creative_call_evidence_v1 import atomic_create
from src.shared.config import settings

VERSION = "creative_bounded_format_role_clients/v1"
TOOL_NAME = prior.TOOL_NAME
EvidenceCallError = prior.EvidenceCallError
role_config = prior.role_config


def tool_choice_policy(role):
    return "omitted_provider_default" if role == "writer" else "existing_forced_function"


def save_request_body(evidence, raw, *, role):
    """Persist body only, after SDK serialization and before HTTP send.

    The outgoing request is not modified. A redacted stored body is explicitly
    marked and cannot be mistaken for preserved original bytes. No request
    headers, cookies, URL, or Authorization value are read or persisted here.
    """
    if not isinstance(raw, bytes):
        raise TypeError("serialized request bytes required")
    prior.strict_envelope(raw)
    protected, redacted = evidence.protect(raw)
    manifest = {
        "schema": VERSION + "/request_body",
        "identity_sha256": evidence.identity_sha256,
        "body_file": "request_body.raw",
        "stored_sha256": hashlib.sha256(protected).hexdigest(),
        "original_sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(protected),
        "original_bytes": len(raw),
        "body_complete": True,
        "raw_bytes_preserved": not redacted,
        "credential_redacted": redacted,
        "capture_boundary": "httpx_request_hook_before_send",
        "provider_received_request": None,
        "contains_request_headers": False,
        "role": role,
        "tool_choice_policy": tool_choice_policy(role),
    }
    atomic_create(evidence.root / "request_body.raw", protected)
    serialized = json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8") + b"\n"
    atomic_create(evidence.root / "REQUEST_BODY_MANIFEST.json", evidence.protect(serialized)[0])
    evidence.record("request_body_saved", {
        "stored_sha256": manifest["stored_sha256"],
        "original_sha256": manifest["original_sha256"],
        "body_complete": True,
        "credential_redacted": redacted,
        "capture_boundary": manifest["capture_boundary"],
        "provider_received_request": None,
    })
    return manifest


class BoundedFormatRoleClients:
    def __init__(self, *, http_client_factory=None):
        # Injection is only for offline transports; production uses httpx.
        self.http_client_factory = http_client_factory or httpx.Client

    def call(self, role, messages, *, max_tokens=12000, temperature=.4, thinking=None,
             structured_schema=None, writer_model=None, evidence=None):
        if evidence is None or role not in ("writer", "director") or writer_model not in (None, "MiniMax-M3"):
            raise EvidenceCallError("INVALID_EVIDENCE_PREFLIGHT", started=False, outcome_known=True)
        if type(max_tokens) is not int or not 0 < max_tokens <= 32000 or type(temperature) not in (int, float) or temperature != .4:
            raise EvidenceCallError("INVALID_REQUEST_PARAMETERS", started=False, outcome_known=True)
        if thinking not in (None, "disabled", "adaptive") or (role == "director" and thinking == "adaptive") or (role == "director" and writer_model is not None):
            raise EvidenceCallError("UNVERIFIED_MODEL_MODE", started=False, outcome_known=True)
        if role == "director" and (not isinstance(structured_schema, dict) or not structured_schema):
            raise EvidenceCallError("REVIEW_SCHEMA_REQUIRED", started=False, outcome_known=True)
        started = False
        received = False
        metadata = None
        client = None
        http_client = None
        outgoing_manifest = None
        capture_count = 0

        def capture(request):
            nonlocal outgoing_manifest, capture_count
            capture_count += 1
            if capture_count != 1:
                # A redirect or an unexpected SDK resend must not dispatch again.
                raise EvidenceCallError("MULTIPLE_OUTBOUND_REQUESTS_BLOCKED", started=True,
                                        outcome_known=False)
            try:
                outgoing_manifest = save_request_body(evidence, request.read(), role=role)
            except Exception as exc:
                # The hook has not returned, so this HTTP request was not sent.
                raise EvidenceCallError("OUTBOUND_EVIDENCE_CAPTURE_FAILED", started=False,
                                        outcome_known=True, cause_type=type(exc).__name__) from None

        try:
            from openai import OpenAI
            config = role_config(role)
            evidence.register_secrets(config.api_key)
            http_client = self.http_client_factory(
                timeout=settings.SCRIPT_LLM_TIMEOUT_SECONDS,
                event_hooks={"request": [capture]},
                follow_redirects=False,
            )
            client = OpenAI(api_key=config.api_key, base_url=config.base_url,
                            timeout=settings.SCRIPT_LLM_TIMEOUT_SECONDS, max_retries=0,
                            http_client=http_client)
            parameters = {
                "model": config.model, "messages": deepcopy(messages), "temperature": temperature,
                "max_completion_tokens" if role == "writer" else "max_tokens": max_tokens,
            }
            if thinking in ("disabled", "adaptive"):
                parameters["extra_body"] = {"thinking": {"type": thinking}}
                if thinking == "adaptive":
                    parameters["extra_body"]["reasoning_split"] = True
            if structured_schema is not None:
                description = "提交本阶段完整结构化创作结果" if role == "writer" else "提交本阶段完整文本审核结果，保留所有结论及真实证据"
                parameters["tools"] = [{"type": "function", "function": {
                    "name": TOOL_NAME, "description": description,
                    "parameters": deepcopy(structured_schema),
                }}]
                if role == "director":
                    parameters["tool_choice"] = {"type": "function", "function": {"name": TOOL_NAME}}
            evidence.record("client_configured", {
                "role": role, "model": config.model, "base_url": config.base_url,
                "timeout_seconds": settings.SCRIPT_LLM_TIMEOUT_SECONDS,
                "max_retries": 0, "follow_redirects": False,
                "server_stream_requested": False, "client_policy_version": VERSION,
                "tool_choice_policy": tool_choice_policy(role),
                "strict_response_parser": prior.VERSION,
                "server_schema_guarantee": False,
            })
            evidence.record("dispatch_attempt_started", {
                "meaning": "SDK method about to be called; not a server acknowledgement",
            })
            started = True
            # This defers local parsing only; it does not send stream=True.
            with client.chat.completions.with_streaming_response.create(**parameters) as response:
                received = True
                metadata = prior.http_metadata(response.status_code, response.headers)
                metadata = json.loads(evidence.protect(json.dumps(metadata).encode())[0])
                evidence.record("http_headers_received", metadata)
                raw = response.read()
                protected, manifest = evidence.save_body(raw, metadata)
            return prior.parse_saved_response(protected, manifest, role, config.model, thinking,
                                              structured_schema, evidence)
        except EvidenceCallError:
            raise
        except Exception as exc:
            # The SDK wraps hook exceptions in APIConnectionError. Preserve the
            # known local pre-send guard instead of reporting a sent/unknown call.
            cause = getattr(exc, "__cause__", None)
            if isinstance(cause, EvidenceCallError):
                raise cause from None
            response = getattr(exc, "response", None)
            status = getattr(exc, "status_code", None)
            if response is not None and type(status) is int:
                received = True
                metadata = prior.http_metadata(status, response.headers, extra_request_id=getattr(exc, "request_id", None))
                metadata = json.loads(evidence.protect(json.dumps(metadata).encode())[0])
                try:
                    evidence.record("http_error_headers_received", metadata)
                except Exception as storage_exc:
                    raise EvidenceCallError("HTTP_ERROR_EVIDENCE_SAVE_FAILED", started=started, received=True,
                                            outcome_known=True, metadata=metadata, cause_type=type(storage_exc).__name__) from None
                try:
                    raw = response.read()
                except Exception:
                    raise EvidenceCallError("HTTP_ERROR_BODY_UNAVAILABLE", started=started, received=True,
                                            outcome_known=True, metadata=metadata, cause_type=type(exc).__name__) from None
                try:
                    protected, manifest = evidence.save_body(raw, metadata)
                except Exception as storage_exc:
                    raise EvidenceCallError("HTTP_ERROR_EVIDENCE_SAVE_FAILED", started=started, received=True,
                                            outcome_known=True, metadata=metadata, cause_type=type(storage_exc).__name__) from None
                return prior.parse_saved_response(protected, manifest, role, config.model, thinking,
                                                  structured_schema, evidence)
            code = "RESPONSE_CAPTURE_INTERRUPTED" if received else ("TRANSPORT_EXCEPTION" if started else "CLIENT_PREFLIGHT_FAILED")
            try:
                evidence.record("call_interrupted", {
                    "code": code, "cause_type": type(exc).__name__, "headers_received": received,
                    "outbound_body_saved": outgoing_manifest is not None,
                })
            except Exception:
                pass
            raise EvidenceCallError(code, started=started, received=received,
                                    outcome_known=not started, metadata=metadata, cause_type=type(exc).__name__) from None
        finally:
            for resource in (client, http_client):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception:
                        pass
