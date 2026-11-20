"""Native goal diagnostics against synthetic atoms and unchanged real failures."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from src.content_factory import creative_goal_source_contract_v3 as goal
from src.content_factory import creative_stage_context_v3 as context
from tests.test_creative_goal_source_contract_v2 import native_goal as old_fixture, CATALOGS


def native_goal():
    value = old_fixture()
    value["contract_version"] = goal.VERSION
    for prop in value["whole_plan"]["props"]:
        prop["presence_at_start"] = "present"
    return value


def diagnose(value, **kwargs):
    return goal.diagnose_goal_document(value, **{**CATALOGS, **kwargs})


def test_noninference_empty_basis_is_optional_without_mutating_native():
    value = native_goal()
    for row in value["claims"]:
        if row["kind"] != "inference":
            row.pop("basis_claim_refs")
    before = deepcopy(value)
    Draft202012Validator(goal.build_goal_request_schema()).validate(value)
    accepted = goal.validate_goal_document(value, **CATALOGS)
    assert accepted == value == before
    assert "basis_claim_refs" not in accepted["claims"][0]


@pytest.mark.parametrize("basis", [None, [], ["UNKNOWN"]])
def test_inference_still_requires_explicit_valid_nonempty_basis(basis):
    value = native_goal()
    row = value["claims"][-1]
    row.pop("basis_claim_refs")
    if basis is not None:
        row["basis_claim_refs"] = basis
    result = diagnose(value)
    assert not result["valid"]
    assert any("/claims/5/basis_claim_refs" in item["path"] for item in result["findings"])


def test_all_safe_errors_are_reported_in_one_pass_and_native_is_unchanged():
    value = native_goal()
    value["whole_plan"]["beats"][0].pop("strategy")
    value["whole_plan"]["props"][0]["support"] = {"entity_type": "scene", "entity_id": "room"}
    third = deepcopy(value["whole_plan"]["characters"][0])
    third["id"] = "third"
    value["whole_plan"]["characters"].append(third)
    value["claims"][2]["origin_ids"] = ["NOT_IN_CATALOG"]
    before = deepcopy(value)
    result = diagnose(value, max_characters=2)
    paths = {row["path"] for row in result["findings"]}
    assert {"/whole_plan/beats/0/strategy", "/whole_plan/characters", "/whole_plan/props/0/support", "/claims/2/origin_ids/0"} <= paths
    assert value == before and result["native_document_modified"] is False


@pytest.mark.parametrize("field,value", [("holder_character_id", "worker"), ("support", {"entity_type": "scene", "entity_id": "room"})])
def test_explicit_absent_prop_cannot_have_physical_holder_or_support(field, value):
    document = native_goal()
    prop = document["whole_plan"]["props"][1]
    prop.update(presence_at_start="absent", holder_character_id=None, support=None)
    prop[field] = value
    assert not diagnose(document)["valid"]


def test_absent_prop_can_have_conceptual_owner_without_current_holder():
    document = native_goal()
    prop = document["whole_plan"]["props"][1]
    prop.update(presence_at_start="absent", holder_character_id=None, support=None, owner_character_id="worker")
    assert diagnose(document)["valid"]


def test_free_prose_is_not_guessed_into_presence_or_support_atoms():
    document = native_goal()
    prop = document["whole_plan"]["props"][0]
    prop.update(presence_at_start="unknown", initial_state="未来也许才会存在，中文不能作为程序原子", support=None)
    assert diagnose(document)["valid"]


@pytest.mark.parametrize("field,value", [("kind", {}), ("kind", []), ("support_type", []), ("support_type", {})])
def test_malformed_schema_types_are_diagnostics_not_local_crashes(field, value):
    document = native_goal()
    if field == "kind":
        document["claims"][0]["kind"] = value
    else:
        document["whole_plan"]["props"][0]["support"]["entity_type"] = value
    result = diagnose(document)
    assert not result["valid"] and result["findings"]


def test_real_531_533_remain_failed_without_native_field_or_id_repair():
    root = Path(__file__).resolve().parents[1] / "data/production_trials/goal_context_text_production_20261013/round_02"
    inputs = json.loads((root / "INPUTS.json").read_text(encoding="utf-8"))
    catalog = context.build_stage_context("goal_plan", inputs)["payload"]["origin_catalog"]
    for index in (1, 2, 3):
        path = root / "goals" / f"native_{index:02}.json"
        original = path.read_bytes()
        native = json.loads(original)
        result = goal.diagnose_goal_document(native, **context.alias_origin_ids(catalog), origin_catalog=catalog, max_characters=2)
        assert not result["valid"]
        assert any(row["path"] == "/whole_plan/characters" for row in result["findings"])
        assert any(row["code"] == "GOAL_INITIAL_HOLDER_SUPPORT_CONFLICT" for row in result["findings"])
        assert path.read_bytes() == original


def test_user_constraint_and_audience_aliases_cannot_trade_authority_classes():
    catalog = {"platform_metadata": {"P1": {"original_id": "source", "path": "source.0"}},
        "verified_legal": {"LAW1": {"original_id": "law", "path": "law.0"}},
        "user": {"UC1": {"original_id": "UC1", "path": "goals.0", "authority": "user_constraint"},
                 "UG1": {"original_id": "UG1", "path": "goals.1", "authority": "user_audience_goal"}}}
    document = native_goal()
    assert diagnose(document, origin_catalog=catalog)["valid"]
    document["claims"][0]["origin_ids"] = ["UG1"]
    result = diagnose(document, origin_catalog=catalog)
    assert not result["valid"]
    assert any(row["code"] == "GOAL_ORIGIN_CLASS_MISMATCH" for row in result["findings"])


def test_compile_count_bound_and_exact_alias_enum_are_in_outgoing_schema():
    catalog = {"platform_metadata": {"S001": {"original_id": "edge:opaque", "path": "source.0"}},
        "verified_legal": {"L001": {"original_id": "L001", "path": "law.0"}},
        "user": {"UC1": {"original_id": "UC1", "path": "goals.0", "authority": "user_constraint"}}}
    schema = goal.build_goal_request_schema(max_characters=2, origin_catalog=catalog)
    assert schema["properties"]["whole_plan"]["properties"]["characters"]["maxItems"] == 2
    assert schema["properties"]["claims"]["items"]["properties"]["origin_ids"]["items"]["enum"] == ["L001", "S001", "UC1"]
