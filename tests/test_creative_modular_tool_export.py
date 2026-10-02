from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator

from src.content_factory.creative_modular_contract import (
    build_direction_schema, build_local_input, build_local_schema, compile_complete, validate_direction,
)
from src.content_factory.creative_modular_tool_export import (
    build_direction_request_messages, build_direction_tool_schema,
    build_local_request_messages, build_local_tool_schema, source_catalog,
)
from src.content_factory.creative_stage_contracts import digest
from src.content_factory.creative_workflow_contract import CreativeContractError
from tests.test_creative_modular_contract import fixture


def schema_keywords(value):
    if isinstance(value, dict):
        return set(value).union(*(schema_keywords(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(schema_keywords(v) for v in value))
    return set()


def test_direction_export_is_simple_and_preserves_inputs_and_local_schema():
    context, direction, _ = fixture()
    strong = build_direction_schema(context)
    before = deepcopy((context, direction, strong))
    exported = build_direction_tool_schema(context)
    Draft202012Validator.check_schema(exported)
    Draft202012Validator(exported).validate(direction)
    assert not {"prefixItems", "allOf", "if", "then", "else", "const"} & schema_keywords(exported)
    beats = exported["properties"]["beats"]
    assert beats["minItems"] == beats["maxItems"] == 2
    assert beats["items"]["properties"]["beat_id"]["enum"] == ["B1", "B2"]
    assert (context, direction, build_direction_schema(context)) == before


@pytest.mark.parametrize("case", ["cross_beat_source", "event_during", "swapped_beats", "duplicate_requirement"])
def test_looser_tool_encoding_never_weakens_deterministic_adoption(case):
    context, direction, _ = fixture()
    if case == "cross_beat_source":
        direction["beats"][0]["performance_requirements"][0]["stimulus_source"] = "script.beats.1.event"
        code = "MODULE_REQUIREMENT_SOURCE"
    elif case == "event_during":
        direction["beats"][0]["performance_requirements"][0].update(
            stimulus_source="script.beats.0.event", relation="during")
        code = "EXPRESSION_UNSUPPORTED"
    elif case == "swapped_beats":
        direction["beats"].reverse()
        code = "MODULE_BEAT_ORDER"
    else:
        direction["beats"][0]["performance_requirements"][1]["id"] = direction["beats"][0]["performance_requirements"][0]["id"]
        code = "MODULE_REQUIREMENT_SOURCE"
    before = deepcopy(direction)
    Draft202012Validator(build_direction_tool_schema(context)).validate(direction)
    with pytest.raises(CreativeContractError, match=code):
        validate_direction(direction, context)
    assert direction == before


def test_missing_beat_and_wrapped_array_still_reject_tool_shape():
    context, direction, _ = fixture()
    validator = Draft202012Validator(build_direction_tool_schema(context))
    omitted = deepcopy(direction)
    omitted["beats"].pop()
    assert not validator.is_valid(omitted)
    wrapped = deepcopy(direction)
    wrapped["beats"][0]["performance_requirements"] = {
        "item": wrapped["beats"][0]["performance_requirements"],
    }
    assert not validator.is_valid(wrapped)


def test_unknown_canonical_source_and_invented_seat_reject_simple_enum():
    context, direction, _ = fixture()
    validator = Draft202012Validator(build_direction_tool_schema(context))
    direction["beats"][0]["performance_requirements"][0]["stimulus_source"] = "人物看见动作"
    assert not validator.is_valid(direction)
    context, direction, _ = fixture()
    direction["spatial_contract"]["seats"][0]["seat_id"] = "invented_seat"
    assert not validator.is_valid(direction)


def test_direction_messages_preserve_reference_fulltext_and_selected_assets():
    context, direction, _ = fixture()
    before = deepcopy(context)
    messages = build_direction_request_messages(context)
    payload = json.loads(messages[-1]["content"])
    assert payload["context"] == context == before
    assert payload["context"]["references"][0]["text"] == context["references"][0]["text"]
    assert payload["context"]["selected_assets"] == context["selected_assets"]
    assert payload["request_identity"]["context_sha256"] == digest(context)
    assert payload["source_catalog"] == source_catalog(context)
    assert payload["entity_catalog"]["characters"][0]["id"] == "C01"
    assert "owner_id是归属，不等于holder" in messages[0]["content"]
    assert "事件只能before/after" in messages[0]["content"]
    assert "initial_state只描述第一拍事件发生前" in messages[0]["content"]


def test_full_story_remains_visible_but_prefix_schema_only_covers_current_beats():
    context, direction, _ = fixture()
    context["full_story_script"] = deepcopy(context["script"])
    context["script"]["beats"] = context["script"]["beats"][:1]
    messages = build_direction_request_messages(context)
    payload = json.loads(messages[-1]["content"])
    assert len(payload["context"]["full_story_script"]["beats"]) == 2
    schema = build_direction_tool_schema(context)
    assert schema["properties"]["beats"]["minItems"] == schema["properties"]["beats"]["maxItems"] == 1
    assert schema["properties"]["beats"]["items"]["properties"]["beat_id"]["enum"] == ["B1"]
    allowed = schema["properties"]["beats"]["items"]["properties"]["performance_requirements"]["items"]["properties"]["stimulus_source"]["enum"]
    assert all(path.startswith("script.beats.0.") for path in allowed)
    assert len(payload["source_catalog"]) == 1


def test_local_export_is_simple_and_does_not_change_core_local_schema():
    context, direction, locals_ = fixture()
    original = build_local_schema(context, direction, "B1")
    before = deepcopy((context, direction, locals_[0], original))
    exported = build_local_tool_schema(context, direction, "B1")
    Draft202012Validator.check_schema(exported)
    Draft202012Validator(exported).validate(locals_[0])
    assert not {"prefixItems", "allOf", "if", "then", "else", "const"} & schema_keywords(exported)
    fields = exported["properties"]
    assert not {"initial_state", "start_state", "end_state", "dialogue", "camera"} & set(fields)
    assert fields["groups"]["items"]["properties"]["operations"]["items"]["properties"]["target"]["enum"] == ["", "P01", "E01", "E02"]
    assert (context, direction, locals_[0], build_local_schema(context, direction, "B1")) == before


def test_local_tool_looser_hold_encoding_does_not_allow_physical_action_in_hold():
    context, direction, locals_ = fixture()
    locals_[0]["groups"][0]["kind"] = "hold"
    locals_[0]["groups"][0]["hold_subject"] = "C01"
    before = deepcopy(locals_)
    Draft202012Validator(build_local_tool_schema(context, direction, "B1")).validate(locals_[0])
    with pytest.raises(CreativeContractError, match="MODULE_SCHEMA_INVALID"):
        compile_complete(context, direction, locals_)
    assert locals_ == before


def test_local_messages_include_compiler_state_identity_references_and_assets():
    context, direction, locals_ = fixture()
    local_input = build_local_input(context, direction, locals_[:1])
    before = deepcopy(local_input)
    messages = build_local_request_messages(local_input)
    payload = json.loads(messages[-1]["content"])
    assert payload["local_input"] == local_input == before
    assert payload["request_identity"]["input_sha256"] == digest(local_input)
    assert payload["local_input"]["start_state"]["P01"]["holder"] == "C02"
    assert payload["local_input"]["context"]["references"] == context["references"]
    assert payload["local_input"]["context"]["selected_assets"] == context["selected_assets"]
    assert "during在第一句完整说完后" in messages[0]["content"]
    assert "不是说话期间" in messages[0]["content"]
    assert "动作结束才改变状态" in messages[0]["content"]


def test_revision_feedback_requests_whole_new_draft_without_mutating_feedback():
    context, direction, _ = fixture()
    feedback = {"code": "MODULE_REQUIREMENT_SOURCE", "prior_draft": deepcopy(direction)}
    before = deepcopy(feedback)
    messages = build_direction_request_messages(context, revision_feedback=feedback)
    assert json.loads(messages[-1]["content"])["revision_feedback"] == feedback == before
    assert "生成完整新稿" in messages[0]["content"]
    assert "全文重新校验和复审" in messages[0]["content"]


def test_invalid_direction_blocks_local_request_before_dispatch():
    context, direction, _ = fixture()
    local_input = build_local_input(context, direction, [])
    local_input["direction"]["beats"][0]["performance_requirements"][0].update(
        stimulus_source="script.beats.0.event", relation="during")
    with pytest.raises(CreativeContractError, match="EXPRESSION_UNSUPPORTED"):
        build_local_request_messages(local_input)
    local_input["schema"] = "manual_input"
    with pytest.raises(ValueError, match="build_local_input"):
        build_local_request_messages(local_input)
