"""Pure capability gates over the documented provider registry.

This checks a logical request or the *already serialized* wire shape. It does
not serialize an SDK request, contact a provider, grant a call, prove native
asset eligibility, or approve video content. The report keeps those evidence
layers separate instead of promoting documentation into a production receipt.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator, SchemaError

VERSION = "creative_provider_preflight/v1"
REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config/creative_provider_capabilities_20261012.json"
EVIDENCE_LEVELS = (
    "official_documentation", "generic_client", "selected_production_adapter",
    "real_interface_acceptance", "human_content_approval",
)
TEXT_PROTOCOLS = {
    "minimax": "OpenAI-compatible Chat Completions",
    "deepseek": "OpenAI-compatible Chat Completions /v1",
}
MEDIA_PROTOCOL = "POST /api/v3/contents/generations/tasks; GET by original task id"


class ProviderPreflightError(ValueError):
    """A known pre-dispatch incompatibility; no provider operation occurred."""

    def __init__(self, code, message, *, path="", diagnostics=None):
        super().__init__(message)
        self.code = code
        self.failure_kind = "capability_preflight"
        self.detail = {
            "schema": VERSION + "/failure", "code": code, "path": path,
            "blocked": True, "diagnostics": deepcopy(diagnostics or []),
            "failure_kind": self.failure_kind, "dispatch_started": False,
            "automatic_retry": False, "calls_authorized": False,
            "dispatch_authorized": False,
        }


def _fail(code, message, path=""):
    raise ProviderPreflightError(code, message, path=path)


def _json_bytes(value):
    def validate(item, path=""):
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    _fail("NON_JSON_INPUT", "JSON keys must be strings", path)
                validate(child, path + "." + key)
        elif type(item) is list:
            for index, child in enumerate(item):
                validate(child, path + "." + str(index))
        elif type(item) not in (str, int, float, bool, type(None)):
            _fail("NON_JSON_INPUT", "request and registry must preserve JSON types", path)
        elif type(item) is float and not math.isfinite(item):
            _fail("NON_JSON_INPUT", "JSON numbers must be finite", path)
    validate(value)
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, UnicodeEncodeError):
        _fail("NON_JSON_INPUT", "JSON input must be valid UTF-8")


def _sha(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _registry(value):
    file_sha = None
    if value is None:
        raw = REGISTRY_PATH.read_bytes()
        file_sha = hashlib.sha256(raw).hexdigest()
        value = json.loads(raw.decode("utf-8"))
    if type(value) is not dict or value.get("schema") != "creative_provider_capability_registry/v1":
        _fail("REGISTRY_INVALID", "expected the versioned provider registry")
    _json_bytes(value)
    if value.get("evidence_levels") != list(EVIDENCE_LEVELS):
        _fail("REGISTRY_EVIDENCE_LEVELS_INVALID", "all five evidence layers must remain explicit")
    if value.get("this_registry_grants_calls") is not False:
        _fail("REGISTRY_AUTHORIZATION_INVALID", "a capability registry cannot grant calls")
    if type(value.get("providers")) is not list or not value["providers"]:
        _fail("REGISTRY_INVALID", "registry providers must be a nonempty list")
    if type(value.get("sources")) is not dict:
        _fail("REGISTRY_INVALID", "registry must retain its official sources")
    return deepcopy(value), file_sha


def _provider(model, provider_id, registry):
    if type(model) is not str or not model:
        _fail("MODEL_REQUIRED", "an exact documented model id is required", "model")
    candidates = [entry for entry in registry["providers"]
        if type(entry) is dict and entry.get("model") == model]
    if not candidates:
        _fail("MODEL_NOT_REGISTERED", "the exact model id has no documented capability record", "model")
    if provider_id is not None:
        candidates = [entry for entry in candidates if entry.get("provider") == provider_id]
        if not candidates:
            _fail("PROVIDER_MODEL_MISMATCH", "provider and exact model do not match", "provider")
    if len(candidates) != 1:
        _fail("PROVIDER_MODEL_AMBIGUOUS", "model must identify one exact provider record", "model")
    entry = candidates[0]
    if type(entry.get("official")) is not dict:
        _fail("REGISTRY_INVALID", "provider official capability record is missing")
    return entry


def _protocol(entry, explicit, expected):
    if entry.get("protocol") != expected:
        _fail("REGISTERED_PROTOCOL_UNSUPPORTED", "this preflight does not implement the registered protocol")
    if explicit is not None and explicit != expected:
        _fail("PROTOCOL_MISMATCH", "request protocol does not match the exact provider record", "protocol")
    return expected


def _object_schema(schema, path):
    if type(schema) is not dict or schema.get("type") != "object":
        _fail("TOOL_SCHEMA_INVALID", "function parameters must be an object schema", path)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError:
        _fail("TOOL_SCHEMA_INVALID", "function parameters must be a valid JSON Schema", path)


def _string_envelope(schema):
    properties = schema.get("properties", {})
    payload = properties.get("payload_json", {}) if type(properties) is dict else {}
    return type(payload) is dict and payload.get("type") == "string"


def _report(request, registry, file_sha, entry, input_shape, facts, unverified):
    # Registry assertions remain registry assertions. There is no new response,
    # current-account GET, chosen-adapter dispatch or human approval in this call.
    source_keys = entry.get("official_sources", [])
    if type(source_keys) is not list or any(key not in registry["sources"] for key in source_keys):
        _fail("REGISTRY_SOURCE_MISSING", "provider source references must resolve in the registry")
    evidence = {
        "official_documentation": {
            "status": "documented_registry_match", "checked_on": registry.get("checked_on"),
            "sources": {key: registry["sources"][key] for key in source_keys},
        },
        "generic_client": {
            "status": "registry_declaration_only",
            "declared_support": deepcopy(entry.get("generic_client_support")),
            "request_shape_checked_offline": True, "client_execution_verified": False,
        },
        "selected_production_adapter": {
            "status": "not_attested_by_preflight",
            "registry_entry": deepcopy(entry.get("selected_new_shared_entry")),
            "actor_asset_bindings_approved": False, "voice_bound": False,
        },
        "real_interface_acceptance": {"status": "unknown", "verified": False},
        "human_content_approval": {"status": "unknown", "approved": False},
    }
    return {
        "schema": VERSION + "/report", "status": "capability_preflight_passed", "blocked": False,
        "provider": entry["provider"], "model": entry["model"], "protocol": entry["protocol"],
        "input_shape": input_shape, "request_sha256": _sha(request),
        "registry_sha256": _sha(registry), "registry_file_sha256": file_sha,
        "provider_record_sha256": _sha(entry), "facts": deepcopy(facts), "diagnostics": [],
        "unverified_requirements": list(dict.fromkeys(unverified)), "evidence_levels": evidence,
        "documentation_is_call_authorization": False, "fresh_service_response_verified": False,
        "validated_scope": "documented_subset_of_request_shape",
        "complete_wire_field_validation": False,
        "checked_fields": [], "unchecked_fields": [],
        "actual_wire_verified": input_shape == "serialized_wire",
        "wire_send_or_provider_receipt_verified": False, "automatic_retry": False,
        "calls_authorized": False, "dispatch_authorized": False, "media_content_passed": False,
    }


def _thinking(value, shape, allowed):
    if value is None:
        return None
    if shape == "logical_request":
        if type(value) is not str:
            _fail("THINKING_SHAPE_INVALID", "logical thinking must be a mode string", "parameters.thinking")
        mode = value
    else:
        if type(value) is not dict or set(value) != {"type"} or type(value["type"]) is not str:
            _fail("THINKING_SHAPE_INVALID", "serialized thinking must be an object with type", "thinking")
        mode = value["type"]
    if mode not in allowed:
        _fail("THINKING_MODE_UNSUPPORTED", "thinking mode is not documented for this exact provider/model", "thinking")
    return mode


def _text_messages(messages, entry):
    if type(messages) is not list or not messages:
        _fail("MESSAGES_INVALID", "nonempty chat messages are required", "messages")
    kinds = Counter()
    allowed = set(entry["official"].get("multimodal_input", ["text"]))
    for index, message in enumerate(messages):
        path = f"messages.{index}"
        if type(message) is not dict or message.get("role") not in {"system", "user", "assistant", "tool", "developer"}:
            _fail("MESSAGE_ROLE_INVALID", "chat message role is invalid", path)
        content = message.get("content")
        if type(content) is str:
            kinds["text"] += 1
            continue
        if content is None and message.get("role") == "assistant" and type(message.get("tool_calls")) is list:
            continue
        if type(content) is not list or not content:
            _fail("MESSAGE_CONTENT_INVALID", "content must be text or nonempty typed multimodal items", path + ".content")
        for item_index, item in enumerate(content):
            item_path = path + f".content.{item_index}"
            if type(item) is not dict or item.get("type") not in allowed:
                _fail("TEXT_INPUT_MODALITY_UNSUPPORTED", "input modality is not registered for this model", item_path)
            kind = item["type"]
            if kind == "text":
                if type(item.get("text")) is not str:
                    _fail("MESSAGE_CONTENT_INVALID", "text item must contain original text", item_path)
            else:
                _media_url(item, kind, item_path)
                if kind == "video_url" and entry.get("video_understanding_allowed_by_current_user") is False:
                    _fail("VIDEO_UNDERSTANDING_NOT_AUTHORIZED", "current user boundary forbids model video inspection", item_path)
            kinds[kind] += 1
    return dict(kinds)


def _tool_policy(request, params, shape, provider):
    strict = False
    envelope_string = False
    names = []
    if shape == "logical_request":
        schema = request.get("structured_schema")
        if schema is not None:
            _object_schema(schema, "structured_schema")
            names = [schema.get("title") or "submit_creative_json"]
            if "strict" in params and type(params["strict"]) is not bool:
                _fail("STRICT_PARAMETER_INVALID", "strict must be a JSON boolean")
            strict = params.get("strict") is True
            envelope_string = _string_envelope(schema)
        choice = params.get("tool_choice")
        # This is the selected bounded-role adapter's documented mapping, not an
        # assertion that the HTTP request has already contained the tool_choice.
        if choice is None and schema is not None and request.get("role") == "director":
            choice = {"type": "function", "function": {"name": names[0]}}
    else:
        tools = request.get("tools", [])
        if type(tools) is not list:
            _fail("TOOLS_INVALID", "wire tools must be a list", "tools")
        for index, tool in enumerate(tools):
            if type(tool) is not dict or tool.get("type") != "function" or type(tool.get("function")) is not dict:
                _fail("TOOLS_INVALID", "only documented function tools are supported", f"tools.{index}")
            function = tool["function"]
            if type(function.get("name")) is not str or not function["name"]:
                _fail("TOOLS_INVALID", "tool name must be nonempty", f"tools.{index}.function.name")
            _object_schema(function.get("parameters"), f"tools.{index}.function.parameters")
            if "strict" in function and type(function["strict"]) is not bool:
                _fail("STRICT_PARAMETER_INVALID", "strict must be a JSON boolean", f"tools.{index}.function.strict")
            names.append(function["name"])
            strict = strict or function.get("strict") is True
            envelope_string = envelope_string or _string_envelope(function["parameters"])
        choice = params.get("tool_choice")
    forced = choice == "required" or type(choice) is dict
    if choice is not None and choice not in ("auto", "none", "required"):
        if type(choice) is not dict or choice.get("type") != "function" or type(choice.get("function")) is not dict:
            _fail("TOOL_CHOICE_INVALID", "tool_choice must be a documented choice or named function", "tool_choice")
        if choice["function"].get("name") not in names:
            _fail("TOOL_CHOICE_NOT_DECLARED", "forced function must be one of the supplied tools", "tool_choice")
    if forced and not names:
        _fail("TOOL_CHOICE_WITHOUT_TOOLS", "a required tool choice needs declared function tools", "tool_choice")
    if strict:
        if provider == "deepseek":
            _fail("STRICT_BETA_ADAPTER_NOT_VERIFIED", "strict beta/schema-subset integration requires an independently registered protocol")
        _fail("STRICT_PROVIDER_ADAPTER_NOT_VERIFIED", "strict provider/schema guarantees require an independently verified adapter")
    return {"tools_present": bool(names), "tool_names": names, "forced_tool_requested": forced,
        "logical_adapter_policy_inferred": shape == "logical_request" and forced,
        "strict_requested": strict, "inner_schema_is_string_envelope": envelope_string}


def preflight_text_request(request, registry=None, *, provider_id=None, protocol=None):
    """Validate current logical or wire Chat Completions shape without dispatch.

    Logical requests use ``parameters.thinking`` as a string and a
    ``structured_schema``. Wire requests have top-level ``thinking`` objects and
    ``tools``. Mixing the two representations is rejected rather than silently
    giving one precedence. Exact model matching supplies a missing provider;
    explicit provider/protocol declarations must agree with the registry.
    """
    if type(request) is not dict:
        _fail("REQUEST_OBJECT_REQUIRED", "text request must be a JSON object")
    _json_bytes(request)
    for name, explicit in (("provider", provider_id), ("protocol", protocol)):
        declared = request.get(name)
        if declared is not None and (type(declared) is not str or not declared):
            _fail("DECLARED_IDENTITY_INVALID", "provider/protocol declarations must be nonempty strings", name)
        if explicit is not None and (type(explicit) is not str or not explicit):
            _fail("DECLARED_IDENTITY_INVALID", "explicit provider/protocol must be a nonempty string", name)
        if explicit is not None and declared is not None and explicit != declared:
            _fail("DECLARED_IDENTITY_CONFLICT", "explicit and request provider/protocol disagree", name)
    registry, file_sha = _registry(registry)
    entry = _provider(request.get("model"), provider_id or request.get("provider"), registry)
    provider = entry["provider"]
    if provider not in TEXT_PROTOCOLS:
        _fail("TEXT_PROVIDER_UNSUPPORTED", "registered provider is not a supported text protocol")
    _protocol(entry, protocol or request.get("protocol"), TEXT_PROTOCOLS[provider])
    shape = "logical_request" if "parameters" in request else "serialized_wire"
    if shape == "logical_request":
        params = request["parameters"]
        if type(params) is not dict:
            _fail("PARAMETERS_INVALID", "logical parameters must be an object")
        mixed = set(request) & {"thinking", "max_tokens", "max_completion_tokens", "temperature", "tool_choice", "tools", "extra_body"}
        if mixed:
            _fail("LOGICAL_AND_WIRE_MIXED", "logical and serialized parameters cannot be mixed")
    else:
        params = request
        if "extra_body" in request or "structured_schema" in request:
            _fail("WIRE_NOT_SERIALIZED", "SDK extra_body/structured_schema is not an actual serialized wire body")
    modes = entry["official"].get("thinking_types", ["disabled", "enabled"])
    mode = _thinking(params.get("thinking"), shape, modes)
    limits = [name for name in ("max_tokens", "max_completion_tokens") if name in params]
    if len(limits) > 1:
        _fail("OUTPUT_LIMIT_FIELDS_CONFLICT", "use one output-limit field, not both")
    if limits and (type(params[limits[0]]) is not int or params[limits[0]] <= 0):
        _fail("OUTPUT_LIMIT_INVALID", "output limit must be a positive original integer")
    tools = _tool_policy(request, params, shape, provider)
    if provider == "deepseek" and tools["forced_tool_requested"] and mode != "disabled":
        _fail("DEEPSEEK_FORCED_TOOL_THINKING_CONFLICT", "named/required tools require explicitly disabled thinking", "thinking")
    kinds = _text_messages(request.get("messages"), entry)
    unverified = ["actual_provider_acceptance", "same_source_full_content_review"]
    if shape == "logical_request":
        unverified.append("SDK_serialized_wire_coverage")
    if provider == "minimax" and tools["tools_present"]:
        unverified.extend(["required_tool_response_not_server_guaranteed", "inner_schema_requires_local_validation"])
    if tools["inner_schema_is_string_envelope"]:
        unverified.append("strict_outer_schema_does_not_validate_payload_json_document")
    if mode is None:
        unverified.append("thinking_default_enabled_output_consumption")
    if limits:
        unverified.append("output_limit_model_directory_bound_not_registered")
    report = _report(request, registry, file_sha, entry, shape,
        {"thinking": mode, "output_limit_field": limits[0] if limits else None,
         "output_limit": params[limits[0]] if limits else None, "message_input_counts": kinds,
         **tools}, unverified)
    checked_top = {"model", "provider", "protocol", "messages"}
    checked_parameters = {"thinking", "max_tokens", "max_completion_tokens", "tool_choice", "strict"}
    if shape == "logical_request":
        checked_top.update({"parameters", "structured_schema"})
        report["checked_fields"] = sorted((set(request) & checked_top)
            | {"parameters." + key for key in set(params) & checked_parameters})
        report["unchecked_fields"] = sorted((set(request) - checked_top)
            | {"parameters." + key for key in set(params) - checked_parameters})
    else:
        checked_top.update({"tools", *checked_parameters})
        report["checked_fields"] = sorted(set(request) & checked_top)
        report["unchecked_fields"] = sorted(set(request) - checked_top)
    report["checked_nested_constraints"] = ["messages role/content type and registered media modality/URL shape",
        "tools function name/object JSON Schema/strict/tool_choice compatibility"]
    if report["unchecked_fields"]:
        report["unverified_requirements"].append("remaining_request_fields_require_adapter_validation")
    return report


def _media_url(item, kind, path):
    wrapped = item.get(kind)
    if type(wrapped) is not dict or type(wrapped.get("url")) is not str or not wrapped["url"]:
        _fail("MEDIA_URL_INVALID", "media URL must be supplied under its typed URL object", path)
    url = wrapped["url"]
    prefixes = ("https://", "http://", "asset://")
    media = kind.removesuffix("_url")
    if not url.startswith(prefixes) and not url.startswith(f"data:{media}/"):
        _fail("MEDIA_URL_INVALID", "local paths are not provider media URLs", path)
    if kind == "video_url" and url.startswith("data:"):
        _fail("VIDEO_BASE64_UNSUPPORTED", "video references do not support base64 data URLs", path)


def _reference_metadata(value, content):
    if value is None:
        return {}
    if type(value) is dict:
        rows = []
        for index, metadata in value.items():
            if type(index) is str and index.isdecimal():
                index = int(index)
            if type(metadata) is not dict:
                _fail("REFERENCE_METADATA_INVALID", "metadata rows must be objects")
            if "content_index" in metadata and metadata["content_index"] != index:
                _fail("REFERENCE_METADATA_INDEX_CONFLICT", "metadata key and content_index disagree")
            rows.append({**metadata, "content_index": index})
    elif type(value) is list:
        rows = value
    else:
        _fail("REFERENCE_METADATA_INVALID", "reference metadata must be indexed rows or a mapping")
    result = {}
    for row in rows:
        if type(row) is not dict:
            _fail("REFERENCE_METADATA_INVALID", "metadata rows must be objects")
        index = row.get("content_index")
        if type(index) is not int or not 0 <= index < len(content) or content[index].get("type") == "text":
            _fail("REFERENCE_METADATA_INDEX_INVALID", "metadata must identify an actual media content position")
        if index in result:
            _fail("REFERENCE_METADATA_DUPLICATE", "metadata content_index must be unique")
        result[index] = row
    return result


def preflight_media_request(payload, provider_id="ark_api", registry=None, reference_metadata=None, *, protocol=None):
    """Check exact Seedance wire fields; unknown metadata never becomes verified.

    ``reference_metadata`` is indexed by actual ``content_index`` (including
    text items), each row optionally supplies known ``duration_seconds``. This
    accepts technical metadata only; it neither opens nor inspects media.
    Native provenance, current-account GET and approval must be handled by the
    reference compiler, independently of this structural capability result.
    """
    if type(payload) is not dict:
        _fail("REQUEST_OBJECT_REQUIRED", "video payload must be a JSON object")
    _json_bytes(payload)
    registry, file_sha = _registry(registry)
    entry = _provider(payload.get("model"), provider_id, registry)
    if entry["provider"] != "ark_api":
        _fail("MEDIA_PROVIDER_UNSUPPORTED", "this preflight supports the registered Ark wire protocol")
    _protocol(entry, protocol, MEDIA_PROTOCOL)
    if payload.get("provider") is not None and payload["provider"] != provider_id:
        _fail("PROVIDER_MODEL_MISMATCH", "payload provider declaration disagrees with preflight provider")
    if payload.get("protocol") is not None and payload["protocol"] != entry["protocol"]:
        _fail("PROTOCOL_MISMATCH", "payload protocol declaration disagrees with registered protocol")
    official = entry["official"]
    duration = payload.get("duration")
    minimum, maximum = official["generation_seconds"]
    if type(duration) is not int or not minimum <= duration <= maximum:
        _fail("GENERATION_DURATION_UNSUPPORTED", "generation duration is outside the documented integer range", "duration")
    if payload.get("resolution") not in official["resolutions"]:
        _fail("RESOLUTION_UNSUPPORTED", "resolution is not registered for the exact model", "resolution")
    ratios = official.get("ratios")
    if type(ratios) is not list or not ratios or any(type(ratio) is not str for ratio in ratios):
        _fail("RATIO_CAPABILITY_NOT_REGISTERED", "the exact model's documented ratios must be registered before media preflight", "ratio")
    if type(payload.get("ratio")) is not str or payload["ratio"] not in ratios:
        _fail("RATIO_UNSUPPORTED", "an explicit documented aspect ratio is required for this production contract", "ratio")
    if payload.get("omni_reference_task_type") is not None and not official.get("omni_reference_task_type_supported"):
        _fail("OMNI_TASK_TYPE_UNSUPPORTED", "this exact Mini model does not support omni_reference_task_type")
    for name in ("generate_audio", "return_last_frame", "watermark"):
        if name in payload and type(payload[name]) is not bool:
            _fail("BOOLEAN_PARAMETER_INVALID", "media switches must be original JSON booleans", name)
    if payload.get("return_last_frame") is True and not official.get("return_last_frame"):
        _fail("LAST_FRAME_RETURN_UNSUPPORTED", "model does not support original last-frame return")
    content = payload.get("content")
    if type(content) is not list or not content:
        _fail("MEDIA_CONTENT_INVALID", "wire content must be a nonempty list", "content")
    counts, roles = Counter(), Counter()
    text_count = 0
    for index, item in enumerate(content):
        path = f"content.{index}"
        if type(item) is not dict:
            _fail("MEDIA_CONTENT_INVALID", "content items must preserve their original object type", path)
        kind = item.get("type")
        if kind == "text":
            if type(item.get("text")) is not str or not item["text"].strip():
                _fail("MEDIA_TEXT_INVALID", "text prompt must be nonempty", path)
            if "role" in item:
                _fail("MEDIA_ROLE_INVALID", "text prompt must not carry a media role", path)
            text_count += 1
            continue
        allowed_roles = {"image_url": {"first_frame", "last_frame", "reference_image"},
            "video_url": {"reference_video"}, "audio_url": {"reference_audio"}}
        if kind not in allowed_roles:
            _fail("MEDIA_INPUT_MODALITY_UNSUPPORTED", "unsupported typed media input", path)
        if item.get("role") not in allowed_roles[kind]:
            _fail("MEDIA_ROLE_INVALID", "media role does not match the typed input", path)
        _media_url(item, kind, path)
        counts[kind.removesuffix("_url")] += 1
        roles[item["role"]] += 1
    if text_count != 1:
        _fail("MEDIA_TEXT_COUNT_INVALID", "the selected production request requires exactly one text prompt")
    limits = official["reference_counts"]
    if sum(counts.values()) > limits["total"] or any(counts[kind] > limits[kind] for kind in ("image", "video", "audio")):
        _fail("REFERENCE_COUNT_EXCEEDED", "reference count exceeds the exact model limits")
    framed = bool(roles["first_frame"] or roles["last_frame"])
    if framed:
        if roles["first_frame"] != 1 or roles["last_frame"] > 1:
            _fail("FORMAL_FRAME_ROLE_INVALID", "formal frame mode requires one first frame and at most one last frame")
        if roles["reference_image"] or roles["reference_video"] or roles["reference_audio"]:
            _fail("FORMAL_FRAME_MULTIMODAL_CONFLICT", "formal frames and multimodal references are mutually exclusive")
        mode = "first_last_frame" if roles["last_frame"] else "first_frame"
    else:
        mode = "multimodal_reference" if counts else "text"
    if mode not in official["input_modes"]:
        _fail("INPUT_MODE_UNSUPPORTED", "inferred input mode is not registered for the exact model")
    if counts["audio"] and not (counts["image"] or counts["video"]) and not official["audio_only_reference"]:
        _fail("AUDIO_ONLY_REFERENCE_UNSUPPORTED", "audio references require an image or video reference")
    metadata = _reference_metadata(reference_metadata, content)
    durations, unknown_video = {}, []
    for index, item in enumerate(content):
        if item["type"] not in ("video_url", "audio_url"):
            continue
        known = metadata.get(index, {}).get("duration_seconds")
        if known is None:
            if item["type"] == "video_url":
                unknown_video.append(index)
            continue
        if type(known) not in (int, float) or not math.isfinite(known) or known <= 0:
            _fail("REFERENCE_DURATION_INVALID", "known reference duration must be a positive finite number", f"reference_metadata.{index}")
        if item["type"] == "video_url":
            lo, hi = official["reference_video_seconds_each"]
            if not lo <= known <= hi:
                _fail("REFERENCE_VIDEO_DURATION_EXCEEDED", "video reference duration is outside the documented per-reference limits", f"reference_metadata.{index}")
            durations[index] = known
    if sum(durations.values()) > official["reference_video_seconds_total_max"]:
        _fail("REFERENCE_VIDEO_TOTAL_DURATION_EXCEEDED", "known video reference durations exceed the documented combined limit")
    unverified = ["current_account_original_asset_eligibility", "actual_provider_acceptance", "human_video_content_approval"]
    if counts:
        unverified.extend(["actor_to_asset_subject_mapping", "native_asset_provenance_and_approval", "media_url_current_accessibility"])
    if unknown_video:
        unverified.append("reference_video_duration_metadata_missing")
    if payload.get("generate_audio") is True and not counts["audio"]:
        unverified.append("voice_identity_unbound_without_real_audio_reference")
    report = _report(payload, registry, file_sha, entry, "serialized_wire",
        {"input_mode": mode, "reference_counts": dict(counts), "media_roles": dict(roles),
         "duration_seconds": duration, "resolution": payload["resolution"],
         "ratio": payload["ratio"],
         "known_video_reference_duration_total": sum(durations.values()),
         "unknown_video_duration_content_indexes": unknown_video,
         "video_reference_duration_bounds_fully_checked": not unknown_video,
         "formal_first_frame": framed,
         "reference_metadata_sha256": _sha([metadata[index] for index in sorted(metadata)]) if reference_metadata is not None else None},
        unverified)
    if unknown_video:
        report.update(status="capability_preflight_incomplete", blocked=True,
            diagnostics=[{"code": "REFERENCE_VIDEO_DURATION_METADATA_MISSING",
                "content_indexes": unknown_video, "blocks_dispatch": True}])
    report["media_dispatch_ready"] = False
    report["metadata_is_native_origin_or_approval_evidence"] = False
    checked = {"model", "provider", "protocol", "content", "duration", "resolution", "ratio",
        "generate_audio", "watermark", "return_last_frame", "omni_reference_task_type"}
    report["checked_fields"] = sorted(set(payload) & checked)
    report["unchecked_fields"] = sorted(set(payload) - checked)
    report["checked_nested_constraints"] = ["content type/role/URL shape and frame/reference mutual exclusion",
        "reference count by kind and known video duration by actual content index"]
    if report["unchecked_fields"]:
        report["unverified_requirements"].append("remaining_request_fields_require_adapter_validation")
    return report
