"""Offline schema evidence never grants dispatch or promotes progress to done."""
from copy import deepcopy
import hashlib
import json

import pytest

from src.content_factory import creative_studio_provider_bridge_v1 as bridge


def _string(**kwargs):
    return {"type": "string", **kwargs}


def fixture():
    """Illustrative tools, deliberately not claims about LibTV's real names."""
    reference = {"type": "object", "additionalProperties": False,
        "required": ["subject", "responsibility", "url", "ordinal"], "properties": {
            "subject": _string(minLength=1), "responsibility": _string(enum=[
                "person_reference", "room_reference", "product_reference", "start", "end"]),
            "url": _string(format="uri"), "ordinal": {"type": "integer", "minimum": 1}}}
    payload = {"jsonrpc": "2.0", "id": "fixture-only", "result": {"tools": [
        {"name": "illustrative_create_not_a_real_tool", "inputSchema": {
            "type": "object", "additionalProperties": False,
            "required": ["settings", "refs", "prompt", "duration"], "properties": {
                "settings": {"type": "object", "additionalProperties": False,
                    "required": ["model", "mode"], "properties": {
                        "model": _string(enum=["fixture-model-only"]),
                        "mode": _string(enum=["general_reference", "first_last_frames"])}},
                "refs": {"type": "array", "minItems": 1, "maxItems": 5, "items": reference},
                "prompt": _string(minLength=1), "duration": {"type": "integer", "minimum": 4, "maximum": 15}}},
            "outputSchema": {"type": "object", "properties": {"original_job": _string(minLength=1)},
                "required": ["original_job"]}},
        {"name": "illustrative_query_not_a_real_tool", "inputSchema": {
            "type": "object", "additionalProperties": False, "properties": {
                "original_job": _string(minLength=1)}, "required": ["original_job"]},
            "outputSchema": {"type": "object", "additionalProperties": False,
                "required": ["original_job", "state"], "properties": {
                    "original_job": _string(minLength=1), "state": _string(enum=["pending", "ready", "failed"]),
                    "usage_units": {"type": "integer", "minimum": 0},
                    "movie_url": _string(format="uri"), "service_tail_url": _string(format="uri"),
                    "message": _string()}}}]}}
    capture = {"kind": "offline_fixture", "provider": bridge.OFFICIAL_PROVIDER,
        "endpoint": bridge.OFFICIAL_ENDPOINT, "captured_at": "2026-10-12T09:00:00+08:00", "authenticated": False}
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    snapshot = bridge.import_mcp_snapshot(raw, capture=capture)
    declaration = {"schema": bridge.DECLARATION_SCHEMA, "snapshot_sha256": snapshot["snapshot_sha256"],
        "submit_tool": "illustrative_create_not_a_real_tool", "query_tool": "illustrative_query_not_a_real_tool",
        "model": {"input_pointer": "/settings/model", "value": "fixture-model-only"},
        "mode": {"input_pointer": "/settings/mode", "value": "general_reference"},
        "references": {"input_pointer": "/refs", "ordinal_origin": 1,
            "item_fields": {"subject_id": "/subject", "role": "/responsibility", "uri": "/url", "index": "/ordinal"},
            "role_values": {"character": "person_reference", "environment": "room_reference",
                "product": "product_reference", "first_frame": "start", "last_frame": "end"}},
        "job": {"submit_output_pointer": "/original_job", "query_input_pointer": "/original_job",
            "query_output_pointer": "/original_job"},
        "result": {"state_output_pointer": "/state", "complete_values": ["ready"], "failure_values": ["failed"],
            "usage_output_pointer": "/usage_units", "media_url_output_pointer": "/movie_url",
            "original_last_frame_output_pointer": "/service_tail_url"}}
    return snapshot, declaration


def request(roles=("character", "environment")):
    return {"model": "fixture-model-only", "mode": "general_reference",
        "parameters": {"prompt": "两个人留在同一房间，当前行动。", "duration": 10},
        "references": [{"subject_id": f"subject{index}", "role": role,
            "uri": f"https://example.invalid/asset{index}.png", "asset_sha256": str(index) * 64,
            "index": index} for index, role in enumerate(roles, 1)]}


def terminal(state="ready"):
    return {"original_job": "original-123", "state": state, "usage_units": 0,
        "movie_url": "https://example.invalid/movie.mp4", "service_tail_url": "https://example.invalid/tail.png"}


def changed_snapshot(snapshot, transform):
    payload = json.loads(snapshot["raw_tools_list_utf8"])
    transform(payload["result"]["tools"])
    return bridge.import_mcp_snapshot(json.dumps(payload).encode("utf-8"), capture=snapshot["capture"])


def reject(code, function, *args, **kwargs):
    with pytest.raises(bridge.ProviderBridgeError) as caught:
        function(*args, **kwargs)
    assert caught.value.code == code
    assert caught.value.detail["dispatch_started"] is False
    assert caught.value.detail["calls_authorized"] is False


def test_current_missing_live_schema_blocks_without_guessing_tools():
    result = bridge.inspect_provider_gate()
    assert result["schema_contract_eligible"] is False
    assert result["diagnostics"][0]["code"] == "LIVE_SCHEMA_UNAVAILABLE"
    assert result["dispatch_enabled"] is False
    assert result["new_provider_calls"] == 0
    assert result["current_authenticated_live_schema_verified"] is False


@pytest.mark.parametrize("snapshot", [[], True, {"capture": []}, {"capture": "bad"}])
def test_malformed_missing_snapshot_remains_a_known_offline_block(snapshot):
    result = bridge.inspect_provider_gate(snapshot)
    assert result["blocked"] is True
    assert result["diagnostics"][0]["code"] == "LIVE_SCHEMA_UNAVAILABLE"


def test_non_json_declaration_error_reporting_does_not_escape_classifier():
    snapshot, declaration = fixture()
    declaration["not_json"] = {1, 2}
    result = bridge.inspect_provider_gate(snapshot, declaration)
    assert result["diagnostics"][0]["code"] == "NON_JSON_INPUT"
    assert result["declaration_sha256"] is None


def test_import_retains_original_receipt_and_fixture_layers():
    snapshot, declaration = fixture()
    assert snapshot["raw_tools_list_sha256"] == hashlib.sha256(snapshot["raw_tools_list_utf8"].encode()).hexdigest()
    before = deepcopy((snapshot, declaration))
    gate = bridge.inspect_provider_gate(snapshot, declaration)
    assert gate["schema_contract_eligible"] is True
    assert gate["blocked"] is True
    assert gate["schema_source_kind"] == "offline_fixture"
    assert gate["actual_provider_acceptance_verified"] is False
    assert gate["media_content_passed"] is False
    assert (snapshot, declaration) == before


def test_authenticated_capture_claim_is_not_independently_verified():
    snapshot, declaration = fixture()
    capture = {**snapshot["capture"], "kind": "authenticated_tools_list", "authenticated": True}
    snapshot = bridge.import_mcp_snapshot(snapshot["raw_tools_list_utf8"].encode(), capture=capture)
    declaration["snapshot_sha256"] = snapshot["snapshot_sha256"]
    result = bridge.inspect_provider_gate(snapshot, declaration)
    assert result["schema_source_kind"] == "authenticated_tools_list"
    assert result["current_authenticated_live_schema_verified"] is False
    assert result["dispatch_enabled"] is False


@pytest.mark.parametrize("raw,code", [
    (b'{"tools":[],"tools":[]}', "SNAPSHOT_DUPLICATE_KEY"),
    (b'{"tools":', "SNAPSHOT_JSON_INVALID"),
    (b'{"tools":[],"x":NaN}', "NON_JSON_INPUT"),
    (b'{"tools":[],"nextCursor":"not-finished"}', "TOOLS_LIST_INCOMPLETE"),
    (b'{"jsonrpc":"2.0","id":1,"error":{"message":"unauthorized"}}', "TOOLS_LIST_INVALID")])
def test_incomplete_and_ambiguous_imports_are_rejected(raw, code):
    snapshot, _ = fixture()
    reject(code, bridge.import_mcp_snapshot, raw, capture=snapshot["capture"])


def test_official_endpoint_and_exact_original_raw_sha_must_match():
    snapshot, _ = fixture()
    raw = snapshot["raw_tools_list_utf8"].encode()
    reject("SNAPSHOT_RAW_SHA_MISMATCH", bridge.import_mcp_snapshot, raw,
        capture=snapshot["capture"], expected_sha256="a" * 64)
    reject("OFFICIAL_ENDPOINT_MISMATCH", bridge.import_mcp_snapshot, raw,
        capture={**snapshot["capture"], "endpoint": "https://third-party.invalid/mcp"})


def test_snapshot_mutation_and_declaration_from_other_snapshot_do_not_pass():
    snapshot, declaration = fixture()
    declaration["snapshot_sha256"] = "a" * 64
    reject("DECLARATION_SNAPSHOT_MISMATCH", bridge.build_media_request_preview, snapshot, declaration, request())
    snapshot["tools"][0]["inputSchema"]["properties"]["duration"]["maximum"] = 40
    assert bridge.inspect_provider_gate(snapshot, declaration)["diagnostics"][0]["code"] == "SNAPSHOT_SHA_MISMATCH"


def test_resealed_schema_cannot_diverge_from_original_receipt():
    snapshot, declaration = fixture()
    snapshot["tools"][0]["inputSchema"]["properties"]["duration"]["maximum"] = 40
    unsealed = {key: value for key, value in snapshot.items() if key != "snapshot_sha256"}
    snapshot["snapshot_sha256"] = bridge._sha(unsealed)
    declaration["snapshot_sha256"] = snapshot["snapshot_sha256"]
    reject("SNAPSHOT_BINDING_MISMATCH", bridge.build_media_request_preview, snapshot, declaration, request())


@pytest.mark.parametrize("part", ["model", "mode", "references", "job", "result"])
def test_capability_declaration_requires_every_lifecycle_contract(part):
    snapshot, declaration = fixture()
    declaration.pop(part)
    result = bridge.inspect_provider_gate(snapshot, declaration)
    assert result["schema_contract_eligible"] is False
    assert result["diagnostics"][0]["code"] == "CAPABILITY_DECLARATION_INCOMPLETE"


def test_session_prompt_only_cannot_claim_model_and_role_enforcement():
    snapshot, declaration = fixture()
    snapshot = changed_snapshot(snapshot, lambda tools: tools[0].update(inputSchema={"type": "object",
        "properties": {"message": {"type": "string"}}, "required": ["message"]}))
    declaration["snapshot_sha256"] = snapshot["snapshot_sha256"]
    reject("CAPABILITY_PATH_NOT_DECLARED", bridge.build_media_request_preview, snapshot, declaration, request())


def test_free_form_model_string_and_missing_output_schema_are_insufficient():
    snapshot, declaration = fixture()
    snapshot = changed_snapshot(snapshot, lambda tools: tools[0]["inputSchema"]["properties"]["settings"]["properties"]["model"].pop("enum"))
    declaration["snapshot_sha256"] = snapshot["snapshot_sha256"]
    reject("CAPABILITY_VALUE_NOT_ATTESTED", bridge.build_media_request_preview, snapshot, declaration, request())
    snapshot = changed_snapshot(snapshot, lambda tools: tools[1].pop("outputSchema"))
    declaration["snapshot_sha256"] = snapshot["snapshot_sha256"]
    assert bridge.inspect_provider_gate(snapshot, declaration)["diagnostics"][0]["code"] == "CAPABILITY_OUTPUT_SCHEMA_MISSING"


def test_no_external_schema_reference_can_trigger_network_resolution():
    snapshot, _ = fixture()
    reject("REMOTE_SCHEMA_REF_BLOCKED", changed_snapshot, snapshot,
        lambda tools: tools[0]["inputSchema"]["properties"].update(prompt={"$ref": "https://example.invalid/schema"}))


def test_unknown_tool_and_overlapping_tail_mapping_are_rejected():
    snapshot, declaration = fixture()
    declaration["submit_tool"] = "not-in-snapshot"
    reject("CAPABILITY_TOOL_UNAVAILABLE", bridge.build_media_request_preview, snapshot, declaration, request())
    snapshot, declaration = fixture()
    declaration["result"]["original_last_frame_output_pointer"] = "/movie_url"
    reject("CAPABILITY_PATHS_OVERLAP", bridge.build_media_request_preview, snapshot, declaration, request())


def test_actual_request_contains_typed_roles_model_and_reference_order():
    snapshot, declaration = fixture()
    original = request()
    before = deepcopy(original)
    preview = bridge.build_media_request_preview(snapshot, declaration, original)
    args = preview["tool_call_preview"]["arguments"]
    assert args["settings"] == {"model": original["model"], "mode": original["mode"]}
    assert args["refs"] == [{"subject": "subject1", "responsibility": "person_reference",
        "url": "https://example.invalid/asset1.png", "ordinal": 1},
        {"subject": "subject2", "responsibility": "room_reference", "url": "https://example.invalid/asset2.png", "ordinal": 2}]
    assert preview["ordered_reference_mapping"][0]["asset_sha256"] == "1" * 64
    assert preview["actual_model_or_role_enforcement_verified"] is False
    assert original == before


@pytest.mark.parametrize("changes,code", [
    ({"duration": "10"}, "TOOL_ARGUMENTS_INVALID"),
    ({"duration": 16}, "TOOL_ARGUMENTS_INVALID"),
    ({"duration": True}, "TOOL_ARGUMENTS_INVALID"),
    ({"prompt": ""}, "TOOL_ARGUMENTS_INVALID"),
    ({"invented": 1}, "TOOL_ARGUMENTS_INVALID"),
    ({"settings": {"model": "wrong-model"}}, "CAPABILITY_ARGUMENT_CONFLICT")])
def test_complete_actual_arguments_validate_types_ranges_required_and_unknown_fields(changes, code):
    snapshot, declaration = fixture()
    candidate = request()
    candidate["parameters"].update(changes)
    reject(code, bridge.build_media_request_preview, snapshot, declaration, candidate)


def test_required_arguments_are_not_assumed_from_capability_path_exists():
    snapshot, declaration = fixture()
    candidate = request()
    candidate["parameters"].pop("prompt")
    reject("TOOL_ARGUMENTS_INVALID", bridge.build_media_request_preview, snapshot, declaration, candidate)


@pytest.mark.parametrize("field,value,code", [
    ("index", 2, "REFERENCE_ORDER_MISMATCH"), ("index", True, "REFERENCE_ORDER_MISMATCH"),
    ("subject_id", "", "REFERENCE_SUBJECT_MISSING"),
    ("asset_sha256", "fake", "REFERENCE_ASSET_HASH_INVALID"),
    ("uri", "C:/assets/photo.png", "REFERENCE_URI_INVALID"),
    ("uri", "https://[broken", "REFERENCE_URI_INVALID"),
    ("uri", "https://example.invalid:broken/x.png", "REFERENCE_URI_INVALID"),
    ("role", "unmapped-role", "REFERENCE_ROLE_UNSUPPORTED")])
def test_wrong_identity_mapping_and_local_paths_are_not_projected(field, value, code):
    snapshot, declaration = fixture()
    candidate = request()
    candidate["references"][0][field] = value
    reject(code, bridge.build_media_request_preview, snapshot, declaration, candidate)


def test_frames_mode_exclusive_and_ordered():
    snapshot, declaration = fixture()
    reject("REFERENCE_AND_FRAME_MODE_MIXED", bridge.build_media_request_preview, snapshot, declaration,
        request(("first_frame",)))
    declaration["mode"]["value"] = "first_last_frames"
    candidate = request(("first_frame", "last_frame"))
    candidate["mode"] = "first_last_frames"
    preview = bridge.build_media_request_preview(snapshot, declaration, candidate)
    assert [item["responsibility"] for item in preview["tool_call_preview"]["arguments"]["refs"]] == ["start", "end"]
    candidate = request(("last_frame", "first_frame"))
    candidate["mode"] = "first_last_frames"
    reject("REFERENCE_AND_FRAME_MODE_MIXED", bridge.build_media_request_preview, snapshot, declaration, candidate)


def test_query_preserves_original_id_and_cannot_generate():
    snapshot, declaration = fixture()
    preview = bridge.build_query_request_preview(snapshot, declaration, "original-123")
    assert preview["tool_call_preview"]["name"] == declaration["query_tool"]
    assert preview["tool_call_preview"]["arguments"] == {"original_job": "original-123"}
    assert preview["generation_redispatch_permitted"] is False
    reject("ORIGINAL_TASK_ID_REQUIRED", bridge.build_query_request_preview, snapshot, declaration, "")
    reject("CAPABILITY_ARGUMENT_CONFLICT", bridge.build_query_request_preview, snapshot, declaration,
        "original-123", {"original_job": "replacement-456"})


def test_progress_keywords_and_urls_never_indicate_completion():
    snapshot, declaration = fixture()
    result = bridge.inspect_query_result(snapshot, declaration, {"original_job": "original-123",
        "state": "pending", "message": "正在生成，将完成。https://example.invalid/progress"}, original_task_id="original-123")
    assert result["status"] == "in_progress"
    assert result["terminal"] is False
    assert result["service_result_complete"] is False
    assert result["generation_redispatch_permitted"] is False


def test_completed_result_still_requires_save_and_human_review():
    snapshot, declaration = fixture()
    result = bridge.inspect_query_result(snapshot, declaration, terminal(), original_task_id="original-123")
    assert result["service_result_complete"] is True
    assert result["reported_usage"] == 0
    assert result["media_file_saved_verified"] is False
    assert result["media_content_passed"] is False
    assert result["after_successful_file_save_required_status"] == "awaiting_human_review"
    assert result["provider_original_last_frame_provenance_verified"] is False


def test_completed_and_failed_results_require_known_nonnegative_usage_and_original_identity():
    snapshot, declaration = fixture()
    candidate = terminal()
    candidate["original_job"] = "some-other-task"
    reject("ORIGINAL_TASK_ID_MISMATCH", bridge.inspect_query_result, snapshot, declaration, candidate,
        original_task_id="original-123")
    candidate = terminal("failed")
    candidate["usage_units"] = -1
    reject("QUERY_RESULT_INVALID", bridge.inspect_query_result, snapshot, declaration, candidate, original_task_id="original-123")
    candidate = {"original_job": "original-123", "state": "failed", "usage_units": 3}
    result = bridge.inspect_query_result(snapshot, declaration, candidate, original_task_id="original-123")
    assert result["status"] == "known_service_failure"
    assert result["generation_redispatch_permitted"] is False
    candidate.pop("usage_units")
    reject("CAPABILITY_VALUE_MISSING", bridge.inspect_query_result, snapshot, declaration, candidate,
        original_task_id="original-123")


def test_terminal_media_needs_original_tail_field_without_fabricating_it():
    snapshot, declaration = fixture()
    candidate = terminal()
    candidate.pop("service_tail_url")
    reject("CAPABILITY_VALUE_MISSING", bridge.inspect_query_result, snapshot, declaration, candidate,
        original_task_id="original-123")


def test_text_preview_keeps_existing_preflight_models_and_no_call(monkeypatch):
    import httpx
    def forbid_network(*args, **kwargs):
        raise AssertionError("no HTTP client may be constructed")
    monkeypatch.setattr(httpx, "Client", forbid_network)
    request = {"model": "MiniMax-M3", "role": "writer",
        "parameters": {"temperature": .4, "thinking": "disabled", "max_completion_tokens": 10000},
        "messages": [{"role": "user", "content": "原生全文与参考全文"}],
        "structured_schema": {"type": "object", "properties": {"payload_json": _string()}, "required": ["payload_json"]}}
    before = deepcopy(request)
    result = bridge.preview_text_request(request)
    assert result["expected_wire_body"]["model"] == "MiniMax-M3"
    assert result["new_provider_calls"] == 0
    assert result["SDK_request_sent"] is False
    assert request == before
    request["model"] = "MiniMax-invented"
    with pytest.raises(ValueError):
        bridge.preview_text_request(request)
