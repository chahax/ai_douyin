"""Offline provider evidence import and exact, typed tool request previews.

No network client or dispatch API exists here. LibTV's authenticated tools/list
must be supplied as original UTF-8 bytes; a local declaration binds parameter
and result paths to that exact snapshot. A session's natural-language message
cannot satisfy model, mode, reference or lifecycle capabilities.

Public APIs:
  import_mcp_snapshot(raw_tools_list, *, capture, expected_sha256=None)
  inspect_provider_gate(snapshot=None, declaration=None)
  build_media_request_preview(snapshot, declaration, request)
  build_query_request_preview(snapshot, declaration, original_task_id, parameters=None)
  inspect_query_result(snapshot, declaration, response, *, original_task_id)
  preview_text_request(request, registry=None)

Capture is {kind: "authenticated_tools_list" | "offline_fixture",
provider: "libtv_official_remote_mcp", endpoint: "https://mcp.liblib.tv/mcp",
captured_at: an ISO-8601 timestamp with timezone, authenticated: bool}.
It is metadata supplied by the importer, not verified account authorization.

The versioned declaration uses ordinary JSON value pointers, e.g. "/model",
not pointers into JSON Schema. See the test fixture for a complete example.
Declarations are local mapping attestations; their SHA binding and schema
validation do not prove provider behavior, billing, native-tail provenance,
reference image eligibility or visual quality.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import re
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker, SchemaError

VERSION = "creative_studio_provider_bridge/v1"
SNAPSHOT_SCHEMA = "creative_studio_mcp_snapshot/v1"
DECLARATION_SCHEMA = "creative_studio_provider_declaration/v1"
OFFICIAL_PROVIDER = "libtv_official_remote_mcp"
OFFICIAL_ENDPOINT = "https://mcp.liblib.tv/mcp"
SHA_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REFERENCE_ROLES = {"character", "environment", "product", "first_frame", "last_frame"}
MODES = {"general_reference", "first_last_frames"}


class ProviderBridgeError(ValueError):
    """A known offline incompatibility; it never represents a submitted task."""

    def __init__(self, code, message, *, path=""):
        super().__init__(message)
        self.code = code
        self.detail = {"schema": VERSION + "/failure", "code": code, "path": path,
            "blocked": True, "dispatch_enabled": False, "dispatch_started": False,
            "calls_authorized": False, "automatic_retry": False}


def _fail(code, message, path=""):
    raise ProviderBridgeError(code, message, path=path)


def _json_bytes(value):
    def walk(item):
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                _fail("NON_JSON_INPUT", "JSON object keys must be strings")
            for child in item.values():
                walk(child)
        elif type(item) is list:
            for child in item:
                walk(child)
        elif type(item) not in (str, int, float, bool, type(None)):
            _fail("NON_JSON_INPUT", "only original JSON types are supported")
        elif type(item) is float and not math.isfinite(item):
            _fail("NON_JSON_INPUT", "JSON numbers must be finite")
    walk(value)
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, UnicodeError):
        _fail("NON_JSON_INPUT", "JSON must have valid UTF-8 strings")


def _sha(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _load(raw):
    if type(raw) is not bytes or not raw or len(raw) > 8_000_000:
        _fail("SNAPSHOT_BYTES_INVALID", "tools/list must be original UTF-8 bytes within 8 MB")
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                _fail("SNAPSHOT_DUPLICATE_KEY", "duplicate JSON keys cannot be accepted")
            obj[key] = value
        return obj
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
            parse_constant=lambda _: _fail("NON_JSON_INPUT", "nonfinite JSON constants"))
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, ProviderBridgeError):
            raise
        _fail("SNAPSHOT_JSON_INVALID", "tools/list must be a complete JSON object")
    _json_bytes(value)
    return value


def _parts(pointer):
    if type(pointer) is not str or not pointer.startswith("/") or pointer == "/":
        _fail("CAPABILITY_POINTER_INVALID", "a non-root JSON value pointer is required")
    if re.search(r"~(?![01])", pointer):
        _fail("CAPABILITY_POINTER_INVALID", "JSON pointer escapes must be ~0 or ~1")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _get(value, pointer):
    node = value
    for part in _parts(pointer):
        if type(node) is not dict or part not in node:
            _fail("CAPABILITY_VALUE_MISSING", "mapped value is absent", pointer)
        node = node[part]
    return node


def _set(value, pointer, new_value):
    parts = _parts(pointer)
    node = value
    for part in parts[:-1]:
        if part not in node:
            node[part] = {}
        if type(node[part]) is not dict:
            _fail("CAPABILITY_ARGUMENT_CONFLICT", "mapped path conflicts with supplied arguments", pointer)
        node = node[part]
    leaf = parts[-1]
    if leaf in node and node[leaf] != new_value:
        _fail("CAPABILITY_ARGUMENT_CONFLICT", "supplied value conflicts with the explicit mapping", pointer)
    node[leaf] = deepcopy(new_value)


def _check_schema(schema, path):
    if type(schema) is not dict:
        _fail("TOOL_SCHEMA_INVALID", "tool schema must be a JSON object", path)
    def local_refs(value):
        if type(value) is dict:
            for key, child in value.items():
                if key in ("$ref", "$dynamicRef"):
                    if type(child) is not str or (child != "#" and not child.startswith("#/")):
                        _fail("REMOTE_SCHEMA_REF_BLOCKED", "offline validation never resolves remote schema references", path)
                if key == "$id" and type(child) is str and not child.startswith("#"):
                    _fail("REMOTE_SCHEMA_ID_BLOCKED", "external schema base IDs are not accepted offline", path)
                local_refs(child)
        elif type(value) is list:
            for child in value:
                local_refs(child)
    local_refs(schema)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError:
        _fail("TOOL_SCHEMA_INVALID", "tool schema is not valid JSON Schema", path)


def _resolve(schema, root):
    seen = set()
    while "$ref" in schema:
        ref = schema["$ref"]
        if ref in seen:
            _fail("SCHEMA_REFERENCE_CYCLE", "capability path has cyclic schema references")
        seen.add(ref)
        # A recursive whole-root schema may be valid, but it cannot attest an
        # unambiguous typed field in this deliberately bounded adapter.
        schema = root if ref == "#" else _get(root, ref[1:])
        if type(schema) is not dict:
            _fail("TOOL_SCHEMA_INVALID", "local schema reference must identify a schema")
    return schema


def _schema_at(schema, pointer):
    root = schema
    node = schema
    for part in _parts(pointer):
        node = _resolve(node, root)
        if node.get("type") != "object" or part not in node.get("properties", {}):
            _fail("CAPABILITY_PATH_NOT_DECLARED", "path is not a direct typed property of the captured schema", pointer)
        node = node["properties"][part]
    return _resolve(node, root)


def _typed(schema, pointer, expected):
    node = _schema_at(schema, pointer)
    if node.get("type") != expected:
        _fail("CAPABILITY_TYPE_INVALID", "captured capability type does not match the mapping", pointer)
    return node


def _enumerated(schema, pointer, value):
    node = _typed(schema, pointer, "string")
    values = [node["const"]] if "const" in node else node.get("enum")
    if type(value) is not str or not value or type(values) is not list or value not in values:
        _fail("CAPABILITY_VALUE_NOT_ATTESTED", "exact model/mode/role/state must be enumerated in the captured schema", pointer)


def _validate(schema, value, *, code="TOOL_ARGUMENTS_INVALID"):
    _json_bytes(value)
    try:
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = sorted(validator.iter_errors(value), key=lambda error: str(list(error.path)))
    except Exception as exc:
        if isinstance(exc, ProviderBridgeError):
            raise
        _fail("TOOL_SCHEMA_VALIDATION_FAILED", "captured schema could not be evaluated offline")
    if errors:
        error = errors[0]
        _fail(code, "value violates the captured tool schema: " + error.validator,
            "/" + "/".join(str(part) for part in error.path))


def _tools(payload):
    if type(payload) is not dict:
        _fail("TOOLS_LIST_INVALID", "tools/list response must be an object")
    if "jsonrpc" in payload:
        if payload.get("jsonrpc") != "2.0" or "error" in payload or "result" not in payload:
            _fail("TOOLS_LIST_INVALID", "tools/list must contain a successful JSON-RPC result")
        payload = payload["result"]
    if type(payload) is not dict or type(payload.get("tools")) is not list:
        _fail("TOOLS_LIST_INVALID", "tools/list must supply the actual tool array")
    if payload.get("nextCursor"):
        _fail("TOOLS_LIST_INCOMPLETE", "a paginated tool list must be completed before import")
    names = set()
    for index, tool in enumerate(payload["tools"]):
        if type(tool) is not dict or type(tool.get("name")) is not str or not tool["name"] or tool["name"] in names:
            _fail("TOOL_IDENTITY_INVALID", "tool names must be present and unique")
        names.add(tool["name"])
        _check_schema(tool.get("inputSchema"), f"tools/{index}/inputSchema")
        if tool["inputSchema"].get("type") != "object":
            _fail("TOOL_SCHEMA_INVALID", "MCP inputSchema must describe object arguments")
        if "outputSchema" in tool:
            _check_schema(tool["outputSchema"], f"tools/{index}/outputSchema")
    return deepcopy(payload["tools"])


def import_mcp_snapshot(raw_tools_list, *, capture, expected_sha256=None):
    """Import raw tools/list bytes, retaining their SHA and source distinction.

    ``authenticated_tools_list`` is the supplying client's claimed capture
    provenance, not authorization verified by this offline importer. Fixtures
    never become evidence of current authenticated model/service availability.
    """
    payload = _load(raw_tools_list)
    if type(capture) is not dict or set(capture) != {"kind", "provider", "endpoint", "captured_at", "authenticated"}:
        _fail("CAPTURE_METADATA_INVALID", "capture requires exact provenance fields")
    _json_bytes(capture)
    if capture["kind"] not in ("authenticated_tools_list", "offline_fixture"):
        _fail("CAPTURE_METADATA_INVALID", "unsupported source kind")
    if capture["provider"] != OFFICIAL_PROVIDER or capture["endpoint"] != OFFICIAL_ENDPOINT:
        _fail("OFFICIAL_ENDPOINT_MISMATCH", "snapshot does not bind the researched official LibTV endpoint")
    if type(capture["authenticated"]) is not bool or capture["authenticated"] != (capture["kind"] == "authenticated_tools_list"):
        _fail("CAPTURE_AUTHENTICATION_INVALID", "fixture and claimed authenticated capture must remain distinct")
    try:
        captured = datetime.fromisoformat(capture["captured_at"].replace("Z", "+00:00"))
        if captured.tzinfo is None:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        _fail("CAPTURE_TIMESTAMP_INVALID", "capture needs an ISO timestamp with timezone")
    raw_sha = hashlib.sha256(raw_tools_list).hexdigest()
    if expected_sha256 is not None and expected_sha256 != raw_sha:
        _fail("SNAPSHOT_RAW_SHA_MISMATCH", "original tools/list bytes changed")
    result = {"schema": SNAPSHOT_SCHEMA, "capture": deepcopy(capture),
        "raw_tools_list_utf8": raw_tools_list.decode("utf-8"), "raw_tools_list_sha256": raw_sha,
        "tools": _tools(payload), "tools_sha256": _sha(_tools(payload)),
        "capture_authentication_independently_verified": False,
        "actual_provider_acceptance_verified": False, "dispatch_enabled": False,
        "calls_authorized": False}
    result["snapshot_sha256"] = _sha(result)
    return result


def _checked_snapshot(snapshot):
    if type(snapshot) is not dict or snapshot.get("schema") != SNAPSHOT_SCHEMA:
        _fail("LIVE_SCHEMA_UNAVAILABLE", "no imported actual tools/list schema is available")
    sealed = deepcopy(snapshot)
    expected = sealed.pop("snapshot_sha256", None)
    if not isinstance(expected, str) or not SHA_PATTERN.fullmatch(expected) or _sha(sealed) != expected:
        _fail("SNAPSHOT_SHA_MISMATCH", "imported snapshot changed")
    try:
        rebuilt = import_mcp_snapshot(snapshot["raw_tools_list_utf8"].encode("utf-8"),
            capture=snapshot["capture"], expected_sha256=snapshot["raw_tools_list_sha256"])
    except (KeyError, AttributeError):
        _fail("SNAPSHOT_INVALID", "imported snapshot has no complete original receipt")
    if rebuilt != snapshot:
        _fail("SNAPSHOT_BINDING_MISMATCH", "captured schema does not match its original receipt")
    return snapshot


def _contract(snapshot, declaration):
    snapshot = _checked_snapshot(snapshot)
    if type(declaration) is not dict or declaration.get("schema") != DECLARATION_SCHEMA:
        _fail("CAPABILITY_DECLARATION_MISSING", "an explicit typed capability declaration is required")
    _json_bytes(declaration)
    if declaration.get("snapshot_sha256") != snapshot["snapshot_sha256"]:
        _fail("DECLARATION_SNAPSHOT_MISMATCH", "capabilities must bind the exact imported schema snapshot")
    tool_map = {tool["name"]: tool for tool in snapshot["tools"]}
    try:
        submit = tool_map[declaration["submit_tool"]]
        query = tool_map[declaration["query_tool"]]
    except (KeyError, TypeError):
        _fail("CAPABILITY_TOOL_UNAVAILABLE", "declared submit/query tools are absent from the captured list")
    if submit["name"] == query["name"]:
        _fail("CAPABILITY_OPERATIONS_NOT_ISOLATED", "query and generation must use distinct tools")
    for tool in (submit, query):
        if type(tool.get("outputSchema")) is not dict or tool["outputSchema"].get("type") != "object":
            _fail("CAPABILITY_OUTPUT_SCHEMA_MISSING", "job/result capabilities need captured output schemas")
    try:
        model = declaration["model"]
        mode = declaration["mode"]
        references = declaration["references"]
        job = declaration["job"]
        result = declaration["result"]
        if any(type(value) is not dict for value in (model, mode, references, job, result)):
            raise KeyError()
        _enumerated(submit["inputSchema"], model["input_pointer"], model["value"])
        if mode["value"] not in MODES:
            _fail("INPUT_MODE_UNSUPPORTED", "the workbench only maps explicit reference or frame mode")
        _enumerated(submit["inputSchema"], mode["input_pointer"], mode["value"])
        reference_schema = _typed(submit["inputSchema"], references["input_pointer"], "array")
        item = reference_schema.get("items")
        if type(item) is not dict or item.get("type") != "object":
            _fail("CAPABILITY_REFERENCE_SCHEMA_INVALID", "references must be explicitly typed object items")
        fields = references["item_fields"]
        if type(fields) is not dict or set(fields) != {"subject_id", "role", "uri", "index"}:
            _fail("REFERENCE_MAPPING_INCOMPLETE", "reference subject, role, URI and ordinal mappings are required")
        if references.get("ordinal_origin") != 1 or type(references["ordinal_origin"]) is not int:
            _fail("REFERENCE_MAPPING_INCOMPLETE", "reference numbering starts at one in actual request order")
        for field in ("subject_id", "role", "uri"):
            _typed(item, fields[field], "string")
        _typed(item, fields["index"], "integer")
        role_values = references["role_values"]
        if type(role_values) is not dict or not role_values or set(role_values) - REFERENCE_ROLES:
            _fail("REFERENCE_MAPPING_INCOMPLETE", "role mapping must enumerate supported source responsibilities")
        for value in role_values.values():
            _enumerated(item, fields["role"], value)
        if len(set(role_values.values())) != len(role_values):
            _fail("REFERENCE_ROLE_AMBIGUOUS", "different source responsibilities cannot collapse to one role")
        for key, schema in (("submit_output_pointer", submit["outputSchema"]),
            ("query_input_pointer", query["inputSchema"]), ("query_output_pointer", query["outputSchema"])):
            _typed(schema, job[key], "string")
        _typed(query["outputSchema"], result["state_output_pointer"], "string")
        complete, failure = result["complete_values"], result["failure_values"]
        if (type(complete) is not list or not complete or type(failure) is not list or not failure
                or len(set(complete + failure)) != len(complete + failure)):
            _fail("TERMINAL_STATE_INVALID", "distinct explicit completion and failure states are required")
        for value in complete + failure:
            _enumerated(query["outputSchema"], result["state_output_pointer"], value)
        _typed(query["outputSchema"], result["usage_output_pointer"], "integer")
        for key in ("media_url_output_pointer", "original_last_frame_output_pointer"):
            _typed(query["outputSchema"], result[key], "string")
        input_paths = [model["input_pointer"], mode["input_pointer"], references["input_pointer"]]
        item_paths = list(fields.values())
        output_paths = [job["query_output_pointer"], *[result[key] for key in
            ("state_output_pointer", "usage_output_pointer", "media_url_output_pointer", "original_last_frame_output_pointer")]]
        for paths in (input_paths, item_paths, output_paths):
            if any(a == b or a.startswith(b + "/") or b.startswith(a + "/")
                for index, a in enumerate(paths) for b in paths[index + 1:]):
                _fail("CAPABILITY_PATHS_OVERLAP", "distinct capability fields cannot overwrite one another")
    except (KeyError, TypeError):
        _fail("CAPABILITY_DECLARATION_INCOMPLETE", "model/mode/reference/job/terminal/usage/original-tail capability is incomplete")
    return submit, query


def _report(snapshot, declaration, *, eligible=False, diagnostics=()):
    capture = snapshot.get("capture") if type(snapshot) is dict else None
    source_kind = capture.get("kind") if type(capture) is dict else None
    source_kind = source_kind if type(source_kind) is str else None
    # Invalid declaration types are themselves a gate failure. Reporting that
    # failure must not try to serialize the same invalid object a second time.
    try:
        declaration_sha = _sha(declaration) if type(declaration) is dict else None
    except ProviderBridgeError:
        declaration_sha = None
    return {"schema": VERSION + "/gate", "provider": OFFICIAL_PROVIDER,
        "status": "schema_contract_ready_for_offline_preview" if eligible else "blocked",
        "blocked": True, "schema_contract_eligible": eligible,
        "dispatch_enabled": False, "dispatch_started": False, "calls_authorized": False,
        "automatic_retry": False, "new_provider_calls": 0,
        "snapshot_sha256": snapshot.get("snapshot_sha256") if type(snapshot) is dict
            and type(snapshot.get("snapshot_sha256")) is str else None,
        "declaration_sha256": declaration_sha, "schema_source_kind": source_kind,
        "current_authenticated_live_schema_verified": False,
        "actual_provider_acceptance_verified": False,
        "media_content_passed": False, "diagnostics": list(diagnostics),
        "unverified_requirements": ["capture_authentication_and_current_account_availability",
            "provider_model_mode_and_reference_semantics", "native_reference_asset_eligibility",
            "provider_usage_billing_semantics", "provider_original_last_frame_provenance",
            "human_video_content_approval"],
        "dispatch_block_reason": "OFFLINE_DEVELOPMENT_NO_NETWORK_DISPATCH" if eligible else
            (diagnostics[0]["code"] if diagnostics else "LIVE_SCHEMA_UNAVAILABLE")}


def inspect_provider_gate(snapshot=None, declaration=None):
    """Return concrete missing/invalid capabilities, never a generation grant."""
    try:
        _contract(snapshot, declaration)
    except ProviderBridgeError as exc:
        # Invalid evidence is not reclassified as service transport failure.
        return _report(snapshot, declaration, diagnostics=[deepcopy(exc.detail)])
    return _report(snapshot, declaration, eligible=True)


def _https_uri(value, path):
    if type(value) is not str:
        _fail("REFERENCE_URI_INVALID", "reference URI must be a nonempty HTTPS URI", path)
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and bool(parsed.hostname)
            and not parsed.username and not parsed.password and not parsed.fragment)
        # Force port parsing too; malformed ports are otherwise ignored by
        # urlsplit until requested and must not escape the offline classifier.
        _ = parsed.port
    except ValueError:
        valid = False
    if not valid:
        _fail("REFERENCE_URI_INVALID", "reference URI requires HTTPS without credentials or fragments", path)


def build_media_request_preview(snapshot, declaration, request):
    """Map exact typed references into captured tool parameters and validate all.

    Reference qualification/approval remains upstream; this method only maps
    their declared identities, roles, hashes and actual array order. It does
    not upload, fetch, inspect or create any reference media.
    """
    submit, _ = _contract(snapshot, declaration)
    if type(request) is not dict or set(request) != {"model", "mode", "parameters", "references"}:
        _fail("MEDIA_REQUEST_INVALID", "request needs exact model/mode/parameters/references fields")
    _json_bytes(request)
    if request["model"] != declaration["model"]["value"]:
        _fail("EXACT_MODEL_MISMATCH", "requested model differs from captured capability declaration")
    if request["mode"] != declaration["mode"]["value"]:
        _fail("INPUT_MODE_MISMATCH", "requested reference/frame mode differs from declaration")
    if type(request["parameters"]) is not dict or type(request["references"]) is not list or not request["references"]:
        _fail("MEDIA_REQUEST_INVALID", "actual parameters and nonempty references are required")
    mapping = declaration["references"]
    roles = []
    projected = []
    evidence = []
    for index, ref in enumerate(request["references"], 1):
        if type(ref) is not dict or set(ref) != {"subject_id", "role", "uri", "asset_sha256", "index"}:
            _fail("REFERENCE_INVALID", "each reference needs exact subject, role, URI, hash and index")
        if type(ref["index"]) is not int or ref["index"] != index:
            _fail("REFERENCE_ORDER_MISMATCH", "reference ordinals must match actual request array order")
        if type(ref["subject_id"]) is not str or not ref["subject_id"]:
            _fail("REFERENCE_SUBJECT_MISSING", "every reference needs an explicit stable subject ID")
        if type(ref["asset_sha256"]) is not str or not SHA_PATTERN.fullmatch(ref["asset_sha256"]):
            _fail("REFERENCE_ASSET_HASH_INVALID", "reference requires its original asset SHA256")
        role = ref["role"]
        if type(role) is not str or role not in mapping["role_values"]:
            _fail("REFERENCE_ROLE_UNSUPPORTED", "source responsibility has no captured role mapping")
        _https_uri(ref["uri"], f"references/{index - 1}/uri")
        row = {}
        for field, pointer in mapping["item_fields"].items():
            _set(row, pointer, mapping["role_values"][role] if field == "role" else ref[field])
        projected.append(row)
        roles.append(role)
        evidence.append({"index": index, "subject_id": ref["subject_id"], "source_role": role,
            "provider_role": mapping["role_values"][role], "asset_sha256": ref["asset_sha256"],
            "uri_sha256": hashlib.sha256(ref["uri"].encode("utf-8")).hexdigest(),
            "content_inspected": False, "native_eligibility_or_approval_proved": False})
    if request["mode"] == "general_reference" and any(role in ("first_frame", "last_frame") for role in roles):
        _fail("REFERENCE_AND_FRAME_MODE_MIXED", "general references cannot be formal first/last frames")
    if request["mode"] == "first_last_frames" and roles not in (["first_frame"], ["first_frame", "last_frame"]):
        _fail("REFERENCE_AND_FRAME_MODE_MIXED", "frame mode requires first, or first then last, exclusively")
    args = deepcopy(request["parameters"])
    _set(args, declaration["model"]["input_pointer"], request["model"])
    _set(args, declaration["mode"]["input_pointer"], request["mode"])
    _set(args, mapping["input_pointer"], projected)
    _validate(submit["inputSchema"], args)
    return {"schema": VERSION + "/media_request_preview", "gate": _report(snapshot, declaration, eligible=True),
        "tool_call_preview": {"name": submit["name"], "arguments": args},
        "arguments_sha256": _sha(args), "request_sha256": _sha(request),
        "ordered_reference_mapping": evidence, "parameters_validated_against_captured_schema": True,
        "provider_received_request": False, "actual_model_or_role_enforcement_verified": False,
        "dispatch_enabled": False, "new_provider_calls": 0}


def build_query_request_preview(snapshot, declaration, original_task_id, parameters=None):
    """Prepare a read-only original task ID query, without actually querying."""
    _, query = _contract(snapshot, declaration)
    if type(original_task_id) is not str or not original_task_id.strip():
        _fail("ORIGINAL_TASK_ID_REQUIRED", "unknown results cannot be queried with a guessed task ID")
    if parameters is None:
        parameters = {}
    if type(parameters) is not dict:
        _fail("QUERY_PARAMETERS_INVALID", "query parameters must be an object")
    args = deepcopy(parameters)
    _set(args, declaration["job"]["query_input_pointer"], original_task_id)
    _validate(query["inputSchema"], args)
    return {"schema": VERSION + "/query_request_preview",
        "tool_call_preview": {"name": query["name"], "arguments": args},
        "arguments_sha256": _sha(args), "snapshot_sha256": snapshot["snapshot_sha256"],
        "declaration_sha256": _sha(declaration), "read_only_intent": True,
        "query_read_only_semantics_verified": False, "dispatch_enabled": False,
        "new_provider_calls": 0, "generation_redispatch_permitted": False}


def inspect_query_result(snapshot, declaration, response, *, original_task_id):
    """Inspect a structured existing result, never keywords from progress text.

    This does not import a task into the production store, download a video,
    verify provider-origin media, or record a human content approval.
    """
    _, query = _contract(snapshot, declaration)
    if type(original_task_id) is not str or not original_task_id.strip():
        _fail("ORIGINAL_TASK_ID_REQUIRED", "result must bind the original task ID")
    if type(response) is not dict:
        _fail("QUERY_RESULT_INVALID", "result must be a complete structured JSON object")
    _validate(query["outputSchema"], response, code="QUERY_RESULT_INVALID")
    job = declaration["job"]
    if _get(response, job["query_output_pointer"]) != original_task_id:
        _fail("ORIGINAL_TASK_ID_MISMATCH", "result belongs to another original task")
    result = declaration["result"]
    state = _get(response, result["state_output_pointer"])
    base = {"schema": VERSION + "/query_result_check", "response_sha256": _sha(response),
        "original_task_id_sha256": hashlib.sha256(original_task_id.encode("utf-8")).hexdigest(),
        "snapshot_sha256": snapshot["snapshot_sha256"], "declaration_sha256": _sha(declaration),
        "state": state, "provider_original_last_frame_provenance_verified": False,
        "media_file_saved_verified": False, "media_content_passed": False,
        "human_review_record_created": False, "dispatch_enabled": False,
        "generation_redispatch_permitted": False}
    if state not in result["complete_values"] + result["failure_values"]:
        return {**base, "status": "in_progress", "terminal": False,
            "service_result_complete": False, "usage_known": False}
    usage = _get(response, result["usage_output_pointer"])
    if type(usage) is not int or usage < 0:
        _fail("USAGE_UNKNOWN_OR_INVALID", "terminal result requires explicit nonnegative integer usage")
    if state in result["failure_values"]:
        return {**base, "status": "known_service_failure", "terminal": True,
            "service_result_complete": True, "usage_known": True, "reported_usage": usage}
    media = _get(response, result["media_url_output_pointer"])
    tail = _get(response, result["original_last_frame_output_pointer"])
    _https_uri(media, result["media_url_output_pointer"])
    _https_uri(tail, result["original_last_frame_output_pointer"])
    return {**base, "status": "complete_result_present_files_not_verified",
        "terminal": True, "service_result_complete": True, "usage_known": True,
        "reported_usage": usage, "media_uri_sha256": hashlib.sha256(media.encode("utf-8")).hexdigest(),
        "original_last_frame_uri_sha256": hashlib.sha256(tail.encode("utf-8")).hexdigest(),
        "after_successful_file_save_required_status": "awaiting_human_review"}


def preview_text_request(request, registry=None):
    """Keep MiniMax/DeepSeek's existing exact-model preflight and wire mapping."""
    from scripts.creative_capability_role_clients_v2 import expected_wire_request
    from src.content_factory.creative_provider_preflight_v1 import preflight_text_request
    logical = preflight_text_request(request, registry)
    wire = expected_wire_request(request, registry)
    wire_report = preflight_text_request(wire, registry)
    return {"schema": VERSION + "/text_request_preview", "logical_preflight": logical,
        "wire_preflight": wire_report, "expected_wire_body": wire, "wire_sha256": _sha(wire),
        "dispatch_enabled": False, "new_provider_calls": 0, "SDK_request_sent": False,
        "actual_provider_acceptance_verified": False}
