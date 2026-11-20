"""Native setup atoms and source identity; zero service or media dispatch."""
from copy import deepcopy

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_opening_setup_contract_v1 as setup
from tests.test_creative_goal_source_contract_v4 import native_goal


def native_setup(goal=None):
    goal = goal or native_goal()
    return {"schema": setup.VERSION, "goal_sha256": setup.digest(goal),
        "characters": {actor["id"]: deepcopy(actor["initial_state"])
                       for actor in goal["whole_plan"]["characters"]},
        "props": {"book": {"presence": "present", "holder_character_id": "worker",
                           "location": "员工手中", "orientation": None},
                  "paper": {"presence": "absent", "holder_character_id": None,
                            "location": None, "orientation": None}}}


def reject(document, goal=None):
    goal = goal or native_goal()
    original, source = deepcopy(document), deepcopy(goal)
    assert list(Draft202012Validator(setup.build_schema(goal)).iter_errors(document))
    with pytest.raises(setup.OpeningSetupContractError) as error:
        setup.validate(document, goal)
    assert error.value.detail["valid"] is False
    assert document == original and goal == source
    return error.value.detail


def test_valid_setup_preserves_explicit_state_and_does_not_rewrite_plan():
    goal, document = native_goal(), native_setup()
    before_goal, before_doc = deepcopy(goal), deepcopy(document)
    result = setup.validate(document, goal)
    assert result == document and result is not document
    assert goal == before_goal and document == before_doc
    assert setup.diagnose(document, goal)["semantic_quality_approved"] is False


@pytest.mark.parametrize("group,identifier", [("characters", "worker"), ("props", "paper")])
@pytest.mark.parametrize("alteration", ["missing", "extra"])
def test_identity_coverage_is_exact_in_schema_and_validator(group, identifier, alteration):
    document = native_setup()
    if alteration == "missing":
        document[group].pop(identifier)
    else:
        document[group]["unexpected"] = deepcopy(document[group][identifier])
    reject(document)


@pytest.mark.parametrize("field,value", [("scene_id", "other"), ("posture", "站着"), ("location", "桌子右侧")])
def test_actor_initial_state_is_bound_exactly_not_changed_for_script(field, value):
    document = native_setup()
    document["characters"]["worker"][field] = value
    reject(document)


@pytest.mark.parametrize("field,value", [("holder_character_id", "hr"), ("location", "桌面"), ("orientation", "朝向员工")])
def test_absent_prop_cannot_declare_current_holder_location_or_orientation(field, value):
    document = native_setup()
    document["props"]["paper"][field] = value
    diagnosis = reject(document)
    assert any(row["code"] == "OPENING_SETUP_ABSENT_PROP_HAS_CURRENT_STATE" for row in diagnosis["findings"])


def test_owner_and_future_prose_do_not_imply_current_state_or_holder():
    goal = native_goal()
    goal["whole_plan"]["props"][1]["owner_character_id"] = "hr"
    goal["whole_plan"]["props"][1]["description"] = "负责人将在中段拿来的一张纸；现在不存在"
    document = native_setup(goal)
    accepted = setup.validate(document, goal)
    assert accepted["props"]["paper"]["holder_character_id"] is None
    assert accepted["props"]["paper"]["presence"] == "absent"
    assert "owner_character_id" not in accepted["props"]["paper"]


@pytest.mark.parametrize("field,value", [("holder_character_id", "missing"), ("presence", "unknown"),
                                       ("location", " "), ("orientation", {}), ("presence", {})])
def test_invalid_state_atoms_do_not_trigger_local_type_crashes(field, value):
    document = native_setup()
    document["props"]["book"][field] = value
    reject(document)


@pytest.mark.parametrize("field", ["presence", "holder_character_id", "location", "orientation"])
def test_required_state_fields_are_not_locally_backfilled(field):
    document = native_setup()
    document["props"]["paper"].pop(field)
    reject(document)


@pytest.mark.parametrize("holder", [None, "hr"])
def test_present_prop_owner_can_differ_from_holder_without_inference(holder):
    document = native_setup()
    document["props"]["book"].update(holder_character_id=holder, location=None)
    assert setup.validate(document, native_goal())["props"]["book"]["holder_character_id"] == holder


@pytest.mark.parametrize("mutation", [
    lambda doc: doc.update(schema="legacy"),
    lambda doc: doc.update(goal_sha256="0" * 64),
    lambda doc: doc["props"]["book"].update(owner_character_id="worker"),
    lambda doc: doc["props"]["book"].update(support={"entity_type": "actor", "entity_id": "worker"}),
])
def test_exact_native_setup_version_goal_digest_and_field_boundary(mutation):
    document = native_setup()
    mutation(document)
    reject(document)


def test_empty_static_prop_list_requires_empty_native_setup_prop_object():
    goal = native_goal()
    goal["whole_plan"]["props"] = []
    document = native_setup(goal)
    document["props"] = {}
    assert setup.validate(document, goal)["props"] == {}


@pytest.mark.parametrize("mutation", [
    lambda goal: goal.update(contract_version="creative_goal_source_v3"),
    lambda goal: goal["whole_plan"]["characters"][1].update(id="worker"),
    lambda goal: goal["whole_plan"]["props"][0].update(id="worker"),
    lambda goal: goal["whole_plan"]["props"][0].update(owner_character_id="missing"),
    lambda goal: goal["whole_plan"]["characters"][0]["initial_state"].update(scene_id="missing"),
])
def test_invalid_goal_cannot_become_setup_schema_or_silent_goal_migration(mutation):
    goal = native_goal()
    mutation(goal)
    before = deepcopy(goal)
    with pytest.raises(setup.OpeningSetupContractError) as error:
        setup.build_schema(goal)
    assert error.value.code == "OPENING_SETUP_GOAL_INVALID"
    assert goal == before


def test_validated_setup_is_an_independent_native_deep_copy():
    goal, document = native_goal(), native_setup()
    result = setup.validate(document, goal)
    result["characters"]["worker"]["posture"] = "changed"
    assert document["characters"]["worker"]["posture"] == "坐着"
