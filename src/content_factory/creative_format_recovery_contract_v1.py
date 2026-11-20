"""Pure evidence gate for one explicitly authorized missing-tool revision.

The caller must obtain expected_identity from the frozen ledger/anchor, never
from the receipt under review. This gate does not dispatch, convert content to
tool output, modify evidence, reset spend or grant semantic/media approval.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import re

VERSION = "creative_format_recovery_contract/v1"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY_FIELDS = ("ordinal", "label", "request_sha256", "source_binding_sha256", "role", "model")


def _require(condition, message):
    if not condition:
        raise ValueError("format recovery seed rejected: " + message)


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _strict_object(raw):
    _require(type(raw) is bytes and bool(raw), "original nonempty bytes required")
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate original JSON key")
            result[key] = value
        return result
    def constant(_):
        raise ValueError("format recovery seed rejected: nonfinite original JSON")
    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("format recovery seed rejected: incomplete original JSON") from exc
    _require(isinstance(value, dict), "original body must be a complete JSON object")
    def finite(item):
        if isinstance(item, float): _require(math.isfinite(item), "nonfinite original JSON")
        elif isinstance(item, dict):
            for child in item.values(): finite(child)
        elif isinstance(item, list):
            for child in item: finite(child)
    finite(value)
    return value


def validate_format_recovery_seed(receipt, expected_source_sha, *, expected_identity,
        receipt_bytes, response_body, response_manifest, evidence_identity,
        prior_recovery_count=0, media_submission_exists=False):
    """Return evidence binding for one new identity, or raise ValueError.

    expected_identity requires ordinal/label/request_sha256/source_binding_sha256/
    role/model and the original receipt_sha256, independently read from frozen
    ledger/anchor. Raw message.content is opaque and is never decoded as output.
    Concurrency, immutable reservation of that one identity, and full downstream
    validation remain runner responsibilities.
    """
    _require(type(prior_recovery_count) is int and prior_recovery_count == 0, "one format revision maximum")
    _require(media_submission_exists is False, "prior media submission exists or is unknown")
    _require(isinstance(expected_source_sha, str) and bool(_SHA.fullmatch(expected_source_sha)), "independent selected source SHA required")
    _require(isinstance(receipt, dict) and isinstance(expected_identity, dict), "receipt and independent identity required")
    _require(set(expected_identity) == set(_IDENTITY_FIELDS) | {"receipt_sha256"}, "independent identity fields incomplete or extra")
    _require(_integer(expected_identity["ordinal"], 1), "known original ordinal required")
    for key in ("label", "role", "model"):
        _require(isinstance(expected_identity[key], str) and bool(expected_identity[key].strip()), "known original " + key + " required")
    for key in ("request_sha256", "source_binding_sha256", "receipt_sha256"):
        _require(isinstance(expected_identity[key], str) and bool(_SHA.fullmatch(expected_identity[key])), "independent " + key + " required")
    original_receipt = _strict_object(receipt_bytes)
    _require(hashlib.sha256(receipt_bytes).hexdigest() == expected_identity["receipt_sha256"], "original receipt byte SHA changed")
    _require(original_receipt == receipt, "receipt differs from original bytes")
    _require(receipt.get("status") == "interface_rejected", "only original interface rejection is eligible")
    _require("output" not in receipt and "document_output" not in receipt, "original rejected content must not be converted or adopted")
    request = receipt.get("request")
    _require(isinstance(request, dict), "complete original request required")
    _require(_integer(receipt.get("ordinal"), 1), "original receipt ordinal must be an integer")
    actual_identity = {key: receipt.get(key) if key not in ("role", "model") else request.get(key) for key in _IDENTITY_FIELDS}
    _require(actual_identity == {key: expected_identity[key] for key in _IDENTITY_FIELDS}, "original receipt identity changed")
    _require(_digest(request) == expected_identity["request_sha256"], "original request SHA changed")
    source_schema = request.get("inner_document_schema", request.get("structured_schema", {}))
    _require(isinstance(source_schema, dict), "selected-source output schema required")
    bound_source = _mapping(_mapping(source_schema.get("properties")).get("script_sha256")).get("const")
    _require(bound_source == expected_source_sha, "selected source binding changed or unknown")
    _require(isinstance(evidence_identity, dict), "original call evidence identity required")
    identity_sha = _digest(actual_identity)
    _require(evidence_identity.get("schema") == "creative_call_evidence/v1"
        and evidence_identity.get("identity") == actual_identity
        and evidence_identity.get("identity_sha256") == identity_sha
        and _mapping(receipt.get("call_evidence")).get("identity_sha256") == identity_sha,
        "call evidence identity mismatch")
    failure = receipt.get("failure", {})
    metadata = receipt.get("response_metadata", {})
    _require(isinstance(failure, dict) and isinstance(metadata, dict), "known failure metadata required")
    _require(failure.get("code") == "REQUIRED_TOOL_MISSING" and failure.get("category") == "interface"
        and failure.get("response_received") is True and failure.get("provider_outcome_known") is True,
        "only known received missing-tool failure is eligible")
    _require(failure.get("cause_code", "REQUIRED_TOOL_MISSING") == "REQUIRED_TOOL_MISSING"
        and metadata.get("response_fault_code") == "REQUIRED_TOOL_MISSING", "other fault cannot be format recovery")
    _require(metadata.get("http_status_code") == 200 and type(metadata.get("http_status_code")) is int
        and failure.get("http_status_code") == 200, "HTTP success must be known")
    _require(type(metadata.get("provider_status_code")) is int and metadata["provider_status_code"] == 0,
        "provider success must be known")
    _require(metadata.get("response_body_complete") is True and metadata.get("finish_reason") in ("stop", "tool_calls"),
        "truncated or uncertain completion cannot be revised")
    _require(_integer(metadata.get("total_tokens")), "known nonnegative total usage required")
    body = _strict_object(response_body)
    body_sha = hashlib.sha256(response_body).hexdigest()
    _require(isinstance(response_manifest, dict)
        and response_manifest.get("schema") == "creative_call_evidence/v1"
        and response_manifest.get("identity_sha256") == identity_sha
        and response_manifest.get("stored_sha256") == body_sha
        and response_manifest.get("original_sha256") == body_sha
        and metadata.get("raw_body_sha256") == body_sha
        and response_manifest.get("body_complete") is True
        and response_manifest.get("raw_bytes_preserved") is True
        and response_manifest.get("credential_redacted") is False
        and _integer(response_manifest.get("bytes"), 1) and response_manifest["bytes"] == len(response_body)
        and _mapping(response_manifest.get("http_metadata")).get("http_status_code") == 200,
        "original complete response body/manifest binding mismatch")
    _require(receipt.get("response_payload") == body, "receipt payload differs from original response bytes")
    provider = _mapping(body.get("base_resp")).get("status_code")
    _require(type(provider) is int and provider == 0, "original provider outcome was not success")
    total_tokens = _mapping(body.get("usage")).get("total_tokens")
    _require(_integer(total_tokens) and total_tokens == metadata["total_tokens"], "original usage unknown or inconsistent")
    choices = body.get("choices")
    _require(isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], dict), "unique complete original response required")
    _require(choices[0].get("finish_reason") == metadata["finish_reason"], "original completion reason mismatch")
    message = choices[0].get("message")
    _require(isinstance(message, dict) and ("tool_calls" not in message or message["tool_calls"] in (None, []))
        and message.get("function_call") is None,
        "original response actually contains tool output or ambiguous message")
    # Do not parse message.content, even when it looks like valid inner JSON.
    return {"schema": VERSION, "status": "format_recovery_seed_valid", "expected_source_sha256": expected_source_sha,
        "original_identity": deepcopy(actual_identity), "original_receipt_sha256": expected_identity["receipt_sha256"],
        "original_body_sha256": body_sha, "original_evidence_identity_sha256": identity_sha,
        "original_reported_total_tokens": total_tokens, "original_status_retained": "interface_rejected",
        "original_fault_retained": "REQUIRED_TOOL_MISSING", "max_new_format_requests": 1,
        "next_recovery_count": 1, "requires_new_request_identity": True, "source_binding_must_remain_unchanged": True,
        "old_message_content_adopted": False, "automatic_retry": False, "budget_reset": False,
        "semantic_approval": False, "media_submission_authorized_by_this_contract": False}
