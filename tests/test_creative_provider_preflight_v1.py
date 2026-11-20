"""Capability mismatches must fail before a provider operation can occur."""
from copy import deepcopy
import hashlib
import json

import pytest

from src.content_factory import creative_provider_preflight_v1 as gate


ENVELOPE = {"title": "submit_creative_json", "type": "object", "additionalProperties": False,
    "required": ["payload_json"], "properties": {"payload_json": {"type": "string"}}}


def logical(model="MiniMax-M3", role="writer"):
    return {"model": model, "role": role, "parameters": {"thinking": "disabled", "max_completion_tokens": 10000},
        "messages": [{"role": "system", "content": "完整正文审查"},
            {"role": "user", "content": '{"full_current_script":"不可回填","reference_fulltext":"参考全文"}'}],
        "structured_schema": deepcopy(ENVELOPE), "inner_document_schema": {"type": "object"}}


def wire(model="deepseek-flash"):
    return {"model": model, "messages": [{"role": "user", "content": "完整原生稿"}],
        "thinking": {"type": "disabled"}, "max_tokens": 6500,
        "tools": [{"type": "function", "function": {"name": "submit_creative_json", "parameters": deepcopy(ENVELOPE)}}],
        "tool_choice": {"type": "function", "function": {"name": "submit_creative_json"}}}


def media(refs=()):
    return {"model": "doubao-seedance-2-0-mini-260615", "duration": 10,
        "resolution": "480p", "ratio": "9:16", "generate_audio": True,
        "return_last_frame": True, "watermark": False,
        "content": [{"type": "text", "text": "小林留坐，周姐独自离开。"}, *deepcopy(refs)]}


def reference(kind="image", role="reference_image", index=1):
    return {"type": kind + "_url", kind + "_url": {"url": f"https://example.invalid/native{index}"}, "role": role}


def rejected(code, function, *args, **kwargs):
    with pytest.raises(gate.ProviderPreflightError) as caught:
        function(*args, **kwargs)
    assert caught.value.code == code
    assert caught.value.detail["blocked"] is True
    assert caught.value.detail["dispatch_started"] is False
    assert caught.value.detail["automatic_retry"] is False
    assert caught.value.detail["calls_authorized"] is False


def test_logical_and_wire_have_distinct_evidence_and_preserve_input():
    request = logical()
    saved = deepcopy(request)
    report = gate.preflight_text_request(request)
    assert request == saved
    assert report["input_shape"] == "logical_request"
    assert report["actual_wire_verified"] is False
    assert report["facts"]["output_limit_field"] == "max_completion_tokens"
    assert report["registry_file_sha256"] == hashlib.sha256(gate.REGISTRY_PATH.read_bytes()).hexdigest()
    wire_report = gate.preflight_text_request(wire())
    assert wire_report["input_shape"] == "serialized_wire"
    assert wire_report["actual_wire_verified"] is True
    assert wire_report["wire_send_or_provider_receipt_verified"] is False
    assert wire_report["evidence_levels"]["real_interface_acceptance"]["status"] == "unknown"


@pytest.mark.parametrize("candidate,provider,code", [
    (logical("MiniMax-M3.1"), None, "MODEL_NOT_REGISTERED"),
    (logical(), "deepseek", "PROVIDER_MODEL_MISMATCH"),
    (logical("doubao-seedance-2-0-mini-260615"), None, "TEXT_PROVIDER_UNSUPPORTED"),
])
def test_exact_model_provider_mismatch_blocks(candidate, provider, code):
    rejected(code, gate.preflight_text_request, candidate, provider_id=provider)


def test_exact_protocol_is_not_inferred_from_an_arbitrary_name():
    rejected("PROTOCOL_MISMATCH", gate.preflight_text_request, logical(), protocol="OpenAI")
    rejected("PROTOCOL_MISMATCH", gate.preflight_media_request, media(), protocol="BytePlus Comfy API")


def test_explicit_identity_cannot_mask_a_conflicting_request_declaration():
    candidate = logical()
    candidate["provider"] = "deepseek"
    rejected("DECLARED_IDENTITY_CONFLICT", gate.preflight_text_request, candidate, provider_id="minimax")
    candidate = logical()
    candidate["protocol"] = "other protocol"
    rejected("DECLARED_IDENTITY_CONFLICT", gate.preflight_text_request, candidate,
        protocol=gate.TEXT_PROTOCOLS["minimax"])


def test_empty_explicit_identity_cannot_silently_fall_back_to_model_lookup():
    rejected("DECLARED_IDENTITY_INVALID", gate.preflight_text_request, logical(), provider_id="")


@pytest.mark.parametrize("mode", [None, "enabled", "adaptive"])
def test_deepseek_named_tool_requires_explicit_disabled_thinking(mode):
    request = logical("deepseek-flash", "director")
    request["parameters"]["thinking"] = mode
    code = "THINKING_MODE_UNSUPPORTED" if mode == "adaptive" else "DEEPSEEK_FORCED_TOOL_THINKING_CONFLICT"
    rejected(code, gate.preflight_text_request, request)


def test_deepseek_required_wire_tool_missing_thinking_is_rejected():
    request = wire()
    request.pop("thinking")
    request["tool_choice"] = "required"
    rejected("DEEPSEEK_FORCED_TOOL_THINKING_CONFLICT", gate.preflight_text_request, request)


def test_inner_string_envelope_is_not_strict_document_guarantee():
    report = gate.preflight_text_request(logical())
    assert "strict_outer_schema_does_not_validate_payload_json_document" in report["unverified_requirements"]
    request = wire()
    request["tools"][0]["function"]["strict"] = True
    rejected("STRICT_BETA_ADAPTER_NOT_VERIFIED", gate.preflight_text_request, request)


@pytest.mark.parametrize("shape", ["logical", "wire"])
def test_minimax_unverified_strict_cannot_be_promoted_to_passed(shape):
    candidate = logical() if shape == "logical" else wire("MiniMax-M3")
    if shape == "logical":
        candidate["parameters"]["strict"] = True
    else:
        candidate["tools"][0]["function"]["strict"] = True
    rejected("STRICT_PROVIDER_ADAPTER_NOT_VERIFIED", gate.preflight_text_request, candidate)


def test_typed_schema_errors_do_not_escape_as_attribute_errors():
    request = logical()
    request["structured_schema"]["properties"] = []
    rejected("TOOL_SCHEMA_INVALID", gate.preflight_text_request, request)


def test_director_selected_image_is_real_input_without_changing_fulltext_prefix():
    request = logical()
    prefix = deepcopy(request["messages"])
    request["messages"].append({"role": "user", "content": [
        {"type": "text", "text": "image1对应明确批准的小林脸与服装"},
        {"type": "image_url", "image_url": {"url": "https://example.invalid/approved_native.png"}}]})
    report = gate.preflight_text_request(request)
    assert request["messages"][:len(prefix)] == prefix
    assert report["facts"]["message_input_counts"]["image_url"] == 1
    assert report["evidence_levels"]["human_content_approval"]["approved"] is False
    assert report["evidence_levels"]["selected_production_adapter"]["actor_asset_bindings_approved"] is False
    assert report["calls_authorized"] is False


def test_current_video_human_review_boundary_blocks_minimax_video_inspection():
    request = logical()
    request["messages"].append({"role": "user", "content": [reference("video", "reference_video")]})
    rejected("VIDEO_UNDERSTANDING_NOT_AUTHORIZED", gate.preflight_text_request, request)


def test_deepseek_image_is_not_assumed_from_chat_compatibility():
    request = wire()
    request["messages"][0]["content"] = [reference()]
    rejected("TEXT_INPUT_MODALITY_UNSUPPORTED", gate.preflight_text_request, request)


def test_logical_and_actual_wire_parameter_shapes_are_never_merged():
    request = logical()
    request["thinking"] = {"type": "disabled"}
    rejected("LOGICAL_AND_WIRE_MIXED", gate.preflight_text_request, request)
    request = wire()
    request["extra_body"] = {"thinking": {"type": "disabled"}}
    rejected("WIRE_NOT_SERIALIZED", gate.preflight_text_request, request)
    request = wire()
    request["thinking"] = "disabled"
    rejected("THINKING_SHAPE_INVALID", gate.preflight_text_request, request)


@pytest.mark.parametrize("limit", [True, 0, -1, 10000.0, "10000"])
def test_output_limit_preserves_integer_type(limit):
    request = logical()
    request["parameters"]["max_completion_tokens"] = limit
    rejected("OUTPUT_LIMIT_INVALID", gate.preflight_text_request, request)


def test_conflicting_output_limits_and_tools_are_blocked():
    request = wire()
    request["max_completion_tokens"] = 10000
    rejected("OUTPUT_LIMIT_FIELDS_CONFLICT", gate.preflight_text_request, request)
    request = wire()
    request["tool_choice"]["function"]["name"] = "another_tool"
    rejected("TOOL_CHOICE_NOT_DECLARED", gate.preflight_text_request, request)


def test_registry_cannot_promote_itself_to_call_authorization():
    registry = json.loads(gate.REGISTRY_PATH.read_text(encoding="utf-8"))
    registry["this_registry_grants_calls"] = True
    rejected("REGISTRY_AUTHORIZATION_INVALID", gate.preflight_text_request, logical(), registry)


def test_five_evidence_layers_cannot_be_omitted():
    registry = json.loads(gate.REGISTRY_PATH.read_text(encoding="utf-8"))
    registry["evidence_levels"].pop()
    rejected("REGISTRY_EVIDENCE_LEVELS_INVALID", gate.preflight_text_request, logical(), registry)


def test_media_formal_first_frame_is_not_reference_mode_or_human_approval():
    request = media([reference(role="first_frame")])
    original = deepcopy(request)
    report = gate.preflight_media_request(request)
    assert request == original
    assert report["facts"]["input_mode"] == "first_frame"
    assert report["media_dispatch_ready"] is False
    assert report["evidence_levels"]["selected_production_adapter"]["registry_entry"]["actor_asset_bindings"] == "unknown"
    assert report["evidence_levels"]["human_content_approval"]["approved"] is False


@pytest.mark.parametrize("additional", [reference(), reference("video", "reference_video"), reference("audio", "reference_audio")])
def test_formal_first_frame_cannot_mix_with_any_multimodal_reference(additional):
    rejected("FORMAL_FRAME_MULTIMODAL_CONFLICT", gate.preflight_media_request,
        media([reference(role="first_frame"), additional]))


def test_last_frame_without_first_or_multiple_first_frames_is_rejected():
    rejected("FORMAL_FRAME_ROLE_INVALID", gate.preflight_media_request, media([reference(role="last_frame")]))
    rejected("FORMAL_FRAME_ROLE_INVALID", gate.preflight_media_request,
        media([reference(role="first_frame"), reference(role="first_frame", index=2)]))


@pytest.mark.parametrize("kind,role,number", [("image", "reference_image", 10), ("video", "reference_video", 4), ("audio", "reference_audio", 4)])
def test_per_kind_reference_limit(kind, role, number):
    rejected("REFERENCE_COUNT_EXCEEDED", gate.preflight_media_request,
        media([reference(kind, role, index) for index in range(number)]))


def test_audio_reference_needs_actual_image_or_video_and_not_claimed_voice_text():
    rejected("AUDIO_ONLY_REFERENCE_UNSUPPORTED", gate.preflight_media_request, media([reference("audio", "reference_audio")]))
    report = gate.preflight_media_request(media())
    assert "voice_identity_unbound_without_real_audio_reference" in report["unverified_requirements"]
    assert report["evidence_levels"]["selected_production_adapter"]["voice_bound"] is False


@pytest.mark.parametrize("url,code", [("D:/video.mp4", "MEDIA_URL_INVALID"), ("data:video/mp4;base64,dGVzdA==", "VIDEO_BASE64_UNSUPPORTED")])
def test_video_reference_is_not_local_path_or_base64(url, code):
    ref = reference("video", "reference_video")
    ref["video_url"]["url"] = url
    rejected(code, gate.preflight_media_request, media([ref]))


def test_known_video_durations_bind_actual_content_positions_and_total():
    request = media([reference("video", "reference_video"), reference("video", "reference_video", 2)])
    report = gate.preflight_media_request(request,
        reference_metadata=[{"content_index": 1, "duration_seconds": 7}, {"content_index": 2, "duration_seconds": 8}])
    assert report["status"] == "capability_preflight_passed"
    assert report["facts"]["known_video_reference_duration_total"] == 15
    assert report["facts"]["reference_metadata_sha256"]
    assert report["metadata_is_native_origin_or_approval_evidence"] is False
    rejected("REFERENCE_VIDEO_TOTAL_DURATION_EXCEEDED", gate.preflight_media_request, request,
        reference_metadata=[{"content_index": 1, "duration_seconds": 8}, {"content_index": 2, "duration_seconds": 8}])


@pytest.mark.parametrize("duration", [1.9, 15.1])
def test_known_individual_video_bounds(duration):
    rejected("REFERENCE_VIDEO_DURATION_EXCEEDED", gate.preflight_media_request, media([reference("video", "reference_video")]),
        reference_metadata=[{"content_index": 1, "duration_seconds": duration}])


def test_unknown_duration_is_incomplete_and_blocks_future_dispatch_gate():
    report = gate.preflight_media_request(media([reference("video", "reference_video")]))
    assert report["status"] == "capability_preflight_incomplete"
    assert report["blocked"] is True
    assert report["facts"]["unknown_video_duration_content_indexes"] == [1]
    assert report["facts"]["video_reference_duration_bounds_fully_checked"] is False
    assert report["diagnostics"][0]["blocks_dispatch"] is True
    assert report["dispatch_authorized"] is False


@pytest.mark.parametrize("row,code", [
    ({"content_index": 0, "duration_seconds": 4}, "REFERENCE_METADATA_INDEX_INVALID"),
    ({"content_index": 1, "duration_seconds": True}, "REFERENCE_DURATION_INVALID"),
    ({"content_index": 2, "duration_seconds": 4}, "REFERENCE_METADATA_INDEX_INVALID"),
])
def test_metadata_cannot_point_to_text_or_wrong_position(row, code):
    rejected(code, gate.preflight_media_request, media([reference("video", "reference_video")]), reference_metadata=[row])


def test_metadata_mapping_preserves_index_identity():
    request = media([reference("video", "reference_video")])
    report = gate.preflight_media_request(request, reference_metadata={1: {"duration_seconds": 4}})
    assert report["facts"]["known_video_reference_duration_total"] == 4
    rejected("REFERENCE_METADATA_INDEX_CONFLICT", gate.preflight_media_request, request,
        reference_metadata={1: {"content_index": 2, "duration_seconds": 4}})


@pytest.mark.parametrize("value", [True, 3, 16, 10.0])
def test_generation_duration_type_and_current_exact_model_bounds(value):
    request = media()
    request["duration"] = value
    rejected("GENERATION_DURATION_UNSUPPORTED", gate.preflight_media_request, request)


def test_unsupported_resolution_and_omni_controls_are_blocked():
    request = media()
    request["resolution"] = "1080p"
    rejected("RESOLUTION_UNSUPPORTED", gate.preflight_media_request, request)
    request = media()
    request["omni_reference_task_type"] = "extend"
    rejected("OMNI_TASK_TYPE_UNSUPPORTED", gate.preflight_media_request, request)


@pytest.mark.parametrize("ratio", ["banana", True, ["9:16"], {"ratio": "9:16"}, None])
def test_media_ratio_must_be_an_explicit_documented_original_string(ratio):
    candidate = media()
    candidate["ratio"] = ratio
    rejected("RATIO_UNSUPPORTED", gate.preflight_media_request, candidate)


@pytest.mark.parametrize("ratio", ["16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "adaptive"])
def test_registered_official_media_ratios(ratio):
    candidate = media([reference(role="first_frame")])
    candidate["ratio"] = ratio
    report = gate.preflight_media_request(candidate)
    assert report["facts"]["ratio"] == ratio
    assert "ratio" in report["checked_fields"]


def test_missing_ratio_capability_cannot_be_assumed_from_old_client_constants():
    registry = json.loads(gate.REGISTRY_PATH.read_text(encoding="utf-8"))
    ark = next(row for row in registry["providers"] if row["provider"] == "ark_api")
    ark["official"].pop("ratios", None)
    rejected("RATIO_CAPABILITY_NOT_REGISTERED", gate.preflight_media_request, media(), registry=registry)


def test_unchecked_extras_do_not_become_complete_wire_support():
    candidate = media()
    candidate["made_up_parameter"] = True
    report = gate.preflight_media_request(candidate)
    assert report["complete_wire_field_validation"] is False
    assert report["validated_scope"] == "documented_subset_of_request_shape"
    assert report["unchecked_fields"] == ["made_up_parameter"]
    assert "remaining_request_fields_require_adapter_validation" in report["unverified_requirements"]
    candidate = logical()
    candidate["parameters"]["made_up_parameter"] = True
    report = gate.preflight_text_request(candidate)
    assert "parameters.made_up_parameter" in report["unchecked_fields"]
    assert "parameters.thinking" in report["checked_fields"]
    assert report["dispatch_authorized"] is False


def test_report_hash_changes_when_actual_request_content_or_registry_changes():
    request = logical()
    first = gate.preflight_text_request(request)
    request["messages"][1]["content"] += " changed"
    second = gate.preflight_text_request(request)
    assert first["request_sha256"] != second["request_sha256"]
    registry = json.loads(gate.REGISTRY_PATH.read_text(encoding="utf-8"))
    registry["checked_on"] = "2026-10-13"
    third = gate.preflight_text_request(request, registry)
    assert second["registry_sha256"] != third["registry_sha256"]
    assert third["registry_file_sha256"] is None
