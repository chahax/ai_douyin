from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts.creative_direction_source_schema import constrain_direction_sources
from src.content_factory.creative_modular_contract import build_direction_schema
from tests.test_creative_modular_contract import fixture


PROJECT = Path(__file__).resolve().parents[1]
DIAGNOSTIC_ROOT = PROJECT / "data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299"


def constrained(context):
    return constrain_direction_sources(build_direction_schema(context), context)


def test_existing_legal_fixture_passes_without_mutating_inputs():
    context, direction, _ = fixture()
    original = build_direction_schema(context)
    before = deepcopy((original, context, direction))
    schema = constrain_direction_sources(original, context)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(direction)
    assert (original, context, direction) == before
    beats = schema["properties"]["beats"]
    assert beats["items"] is False
    assert beats["minItems"] == beats["maxItems"] == len(context["script"]["beats"])
    assert [unit["properties"]["beat_id"]["const"] for unit in beats["prefixItems"]] == ["B1", "B2"]


@pytest.mark.parametrize("relation", ["before", "after"])
def test_event_accepts_existing_supported_relations(relation):
    context, direction, _ = fixture()
    direction["beats"][0]["performance_requirements"][0].update(
        stimulus_source="script.beats.0.event", relation=relation)
    Draft202012Validator(constrained(context)).validate(direction)


def test_event_during_is_rejected_before_local_compilation():
    context, direction, _ = fixture()
    direction["beats"][0]["performance_requirements"][0].update(
        stimulus_source="script.beats.0.event", relation="during")
    errors = list(Draft202012Validator(constrained(context)).iter_errors(direction))
    assert any(list(error.absolute_path)[-1] == "relation" for error in errors)


@pytest.mark.parametrize("relation", ["before", "during", "after"])
def test_dialogue_accepts_all_three_relations(relation):
    context, direction, _ = fixture()
    direction["beats"][0]["performance_requirements"][0]["relation"] = relation
    Draft202012Validator(constrained(context)).validate(direction)


@pytest.mark.parametrize("source", [
    "人物抬头后的可见反应", "script.beats.1.event", "script.beats.0.dialogue.999.text"])
def test_description_or_another_beat_or_missing_dialogue_is_rejected(source):
    context, direction, _ = fixture()
    direction["beats"][0]["performance_requirements"][0]["stimulus_source"] = source
    errors = list(Draft202012Validator(constrained(context)).iter_errors(direction))
    assert any(error.validator == "enum" and list(error.absolute_path)[-1] == "stimulus_source" for error in errors)


def test_beat_order_and_complete_coverage_are_constrained():
    context, direction, _ = fixture()
    schema = constrained(context)
    swapped = deepcopy(direction)
    swapped["beats"].reverse()
    assert list(Draft202012Validator(schema).iter_errors(swapped))
    omitted = deepcopy(direction)
    omitted["beats"].pop()
    assert list(Draft202012Validator(schema).iter_errors(omitted))
    extra = deepcopy(direction)
    extra["beats"].append(deepcopy(direction["beats"][0]))
    assert list(Draft202012Validator(schema).iter_errors(extra))


def test_requirement_ids_remain_ordinary_strings():
    context, direction, _ = fixture()
    direction["beats"][0]["performance_requirements"][0]["id"] = "本拍可见反应"
    Draft202012Validator(constrained(context)).validate(direction)


def test_real_call23_chinese_source_paths_are_rejected_without_changing_receipt():
    receipt_path = DIAGNOSTIC_ROOT / "call_023_direction.json"
    if not receipt_path.exists():
        pytest.skip("historical real-service receipt is not installed in this checkout")
    before = receipt_path.read_bytes()
    receipt = json.loads(before.decode("utf-8"))
    context = json.loads((DIAGNOSTIC_ROOT / "CONTEXT.json").read_text(encoding="utf-8"))
    output = json.loads(receipt["response_text"])
    errors = list(Draft202012Validator(constrained(context)).iter_errors(output))
    invalid_sources = [error for error in errors if error.validator == "enum"
                       and list(error.absolute_path)[-1] == "stimulus_source"]
    assert invalid_sources
    assert {list(error.absolute_path)[1] for error in invalid_sources} == {0, 1, 2, 3, 4}
    assert receipt_path.read_bytes() == before


def test_real_b5_schema_rejects_event_during_even_with_a_valid_source():
    # This is a synthetic counterexample based on a read-only diagnostic copy.
    # It is never saved or adopted as a repaired model draft.
    receipt_path = DIAGNOSTIC_ROOT / "call_023_direction.json"
    if not receipt_path.exists():
        pytest.skip("historical real-service receipt is not installed in this checkout")
    before = receipt_path.read_bytes()
    receipt = json.loads(before.decode("utf-8"))
    context = json.loads((DIAGNOSTIC_ROOT / "CONTEXT.json").read_text(encoding="utf-8"))
    output = json.loads(receipt["response_text"])
    assert context["script"]["beats"][4]["dialogue"] == []
    for index, beat in enumerate(output["beats"]):
        for requirement in beat["performance_requirements"]:
            requirement.update(stimulus_source=f"script.beats.{index}.event", relation="after")
    output["beats"][4]["performance_requirements"][0]["relation"] = "during"
    errors = list(Draft202012Validator(constrained(context)).iter_errors(output))
    assert any(list(error.absolute_path) == ["beats", 4, "performance_requirements", 0, "relation"] for error in errors)
    assert receipt_path.read_bytes() == before

def test_adapter_is_idempotent_and_preserves_each_prefix_schema():
    context, direction, _ = fixture()
    first = constrained(context)
    before = deepcopy(first)
    second = constrain_direction_sources(first, context)
    assert second == first == before
    Draft202012Validator(second).validate(direction)
    # Per-beat schema extensions must survive an additional pure application.
    first["properties"]["beats"]["prefixItems"][0]["properties"]["purpose"]["maxLength"] = 999
    third = constrain_direction_sources(first, context)
    assert third["properties"]["beats"]["prefixItems"][0]["properties"]["purpose"]["maxLength"] == 999
    assert len(third["properties"]["beats"]["prefixItems"][0]["properties"]["performance_requirements"]["items"]["allOf"]) == 1