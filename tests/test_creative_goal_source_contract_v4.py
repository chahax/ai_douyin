"""Static plan fixtures; never translate a historical native production result."""
from copy import deepcopy
from pathlib import Path
import json

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_goal_source_contract_v4 as goals
from tests.test_creative_goal_source_contract_v2 import native_goal as old_fixture, CATALOGS


def native_goal():
    # This is a new synthetic fixture, not a migrated production response.
    document = old_fixture()
    document["contract_version"] = goals.VERSION
    document["whole_plan"]["props"] = [
        {key: prop[key] for key in ("id", "description", "owner_character_id")}
        for prop in document["whole_plan"]["props"]]
    return document


def validate(document, **kwargs):
    return goals.validate_goal_document(document, **{**CATALOGS, **kwargs})


def rejected(document, code, **kwargs):
    before = deepcopy(document)
    with pytest.raises(goals.GoalContractError) as error:
        validate(document, **kwargs)
    assert any(row["code"] == code for row in error.value.detail["findings"])
    assert document == before


def test_static_props_remove_opening_states_without_changing_characters():
    document = native_goal()
    before = deepcopy(document)
    assert validate(document) == document
    assert document == before
    prop_schema = goals.build_goal_request_schema()["properties"]["whole_plan"]["properties"]["props"]["items"]
    assert set(prop_schema["properties"]) == {"id", "description", "owner_character_id"}
    assert document["whole_plan"]["characters"] == old_fixture()["whole_plan"]["characters"]


@pytest.mark.parametrize("field,value", [
    ("presence_at_start", "absent"), ("holder_character_id", None),
    ("initial_state", "尚未打印"), ("location", None), ("support", {}),
    ("orientation", None)])
def test_current_or_future_initial_states_cannot_leak_into_static_prop(field, value):
    document = native_goal()
    document["whole_plan"]["props"][0][field] = value
    rejected(document, "GOAL_SCHEMA_INVALID")


@pytest.mark.parametrize("index", [4, 5])
def test_creative_and_inference_empty_origins_can_be_native_omissions(index):
    document = native_goal()
    document["claims"][index].pop("origin_ids")
    accepted = validate(document)
    assert "origin_ids" not in accepted["claims"][index]
    assert "origin_ids" not in document["claims"][index]


@pytest.mark.parametrize("index", [0, 1, 2, 3])
@pytest.mark.parametrize("missing", [True, False])
def test_external_authorities_still_need_nonempty_exact_native_origins(index, missing):
    document = native_goal()
    if missing:
        document["claims"][index].pop("origin_ids")
    else:
        document["claims"][index]["origin_ids"] = []
    rejected(document, "GOAL_SCHEMA_INVALID")


@pytest.mark.parametrize("origins", [["LAW1"], ["P1"]])
def test_omission_permission_does_not_allow_promoting_creative_claims(origins):
    document = native_goal()
    document["claims"][4]["origin_ids"] = origins
    rejected(document, "GOAL_SCHEMA_INVALID")


@pytest.mark.parametrize("basis", [None, [], ["missing"]])
def test_inference_basis_remains_native_required_and_exact(basis):
    document = native_goal()
    if basis is None:
        document["claims"][5].pop("basis_claim_refs")
    else:
        document["claims"][5]["basis_claim_refs"] = basis
    rejected(document, "GOAL_REFERENCE_UNKNOWN" if basis == ["missing"] else "GOAL_SCHEMA_INVALID")


def test_noninference_basis_can_be_omitted_but_supplied_references_remain_validated():
    document = native_goal()
    for claim in document["claims"][:-1]:
        claim.pop("basis_claim_refs")
    assert validate(document) == document
    document["claims"][4]["basis_claim_refs"] = ["missing"]
    rejected(document, "GOAL_REFERENCE_UNKNOWN")


@pytest.mark.parametrize("mutation,code", [
    (lambda d: d["whole_plan"]["props"][0].update(owner_character_id="missing"), "GOAL_REFERENCE_UNKNOWN"),
    (lambda d: d["whole_plan"]["characters"][0]["initial_state"].update(scene_id="missing"), "GOAL_REFERENCE_UNKNOWN"),
    (lambda d: d["whole_plan"]["beats"][0].update(actor_id="missing"), "GOAL_REFERENCE_UNKNOWN"),
    (lambda d: d["whole_plan"]["beats"][0].update(scene_id="missing"), "GOAL_REFERENCE_UNKNOWN"),
    (lambda d: d["whole_plan"]["beats"][0].update(claim_refs=["missing"]), "GOAL_REFERENCE_UNKNOWN"),
    (lambda d: d["whole_plan"]["props"][0].update(id="worker"), "GOAL_ENTITY_ID_COLLISION"),
    (lambda d: d["claims"][1].update(id="U1"), "GOAL_DUPLICATE_ID"),
    (lambda d: d["whole_plan"]["beats"][0].update(claim_refs=["L1"]), "GOAL_DRAMATIC_CHOICE_UNTRACED"),
    (lambda d: d["whole_plan"]["ending"].update(evidence_beat_ids=["B1"]), "GOAL_ENDING_UNTRACED"),
    (lambda d: d["whole_plan"]["beats"][1]["strategy"].update(effect="maintains"), "GOAL_STRATEGY_SHIFT_MISSING"),
])
def test_existing_identity_dramatic_reference_and_strategy_gates_remain(mutation, code):
    document = native_goal()
    mutation(document)
    rejected(document, code)


def test_claim_cycles_and_cast_bound_are_not_lost_with_static_props():
    document = native_goal()
    document["claims"][4]["basis_claim_refs"] = ["I1"]
    document["claims"][5]["basis_claim_refs"] = ["C1"]
    rejected(document, "GOAL_REFERENCE_CYCLE")
    document = native_goal()
    actor = deepcopy(document["whole_plan"]["characters"][0])
    actor["id"] = "extra"
    document["whole_plan"]["characters"].append(actor)
    rejected(document, "GOAL_SCHEMA_INVALID", max_characters=2)


def test_source_class_mismatch_and_user_coverage_cannot_be_normalized():
    document = native_goal()
    document["claims"][3]["origin_ids"] = ["P1"]
    rejected(document, "GOAL_ORIGIN_CLASS_MISMATCH")
    document = native_goal()
    document["claims"][0]["origin_ids"] = ["UG1"]
    rejected(document, "GOAL_USER_REQUIREMENT_UNCOVERED")


def test_outgoing_enums_retain_short_catalog_alias_authority():
    catalog = {"platform_metadata": {"S001": {"original_id": "edge:opaque", "path": "source.0"}},
        "verified_legal": {"L001": {"original_id": "law", "path": "law.0"}},
        "user": {"UC1": {"original_id": "UC1", "path": "goals.0", "authority": "user_constraint"},
                 "UG1": {"original_id": "UG1", "path": "goals.1", "authority": "user_audience_goal"}}}
    schema = goals.build_goal_request_schema(max_characters=2, origin_catalog=catalog)
    assert schema["properties"]["claims"]["items"]["properties"]["origin_ids"]["items"]["enum"] == ["L001", "S001", "UC1", "UG1"]
    document = native_goal()
    document["claims"][0]["origin_ids"] = ["UG1"]
    diagnosis = goals.diagnose_goal_document(document, origin_catalog=catalog)
    assert any(row["code"] == "GOAL_ORIGIN_CLASS_MISMATCH" for row in diagnosis["findings"])


def test_legacy_real_native_536_is_rejected_unchanged_and_not_migrated():
    path = Path(__file__).resolve().parents[1] / "data/production_trials/goal_context_text_production_20261013/round_03/goals/native_03.json"
    original = path.read_bytes()
    document = json.loads(original)
    diagnosis = goals.diagnose_goal_document(document)
    assert not diagnosis["valid"]
    assert any(row["path"] == "/contract_version" for row in diagnosis["findings"])
    assert path.read_bytes() == original


def test_schema_validation_and_validation_return_do_not_claim_semantic_quality():
    document = native_goal()
    assert not list(Draft202012Validator(goals.build_goal_request_schema()).iter_errors(document))
    diagnosis = goals.diagnose_goal_document(document, **CATALOGS)
    assert diagnosis["valid"] and diagnosis["semantic_quality_approved"] is False
    result = validate(document)
    result["whole_plan"]["premise"] = "changed"
    assert document["whole_plan"]["premise"] != "changed"
