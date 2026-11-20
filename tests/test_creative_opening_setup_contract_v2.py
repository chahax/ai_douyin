"""Explicit physical-position contracts; no model, network or media calls."""
from copy import deepcopy
import json

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_opening_setup_contract_v2 as setup
from tests.test_creative_goal_source_contract_v4 import native_goal as static_goal
from tests.test_creative_opening_setup_contract_v1 import native_setup as old_setup


def native_goal():
    goal = static_goal()
    goal["whole_plan"]["props"].extend([
        {"id": "pen", "description": "员工的笔，静态归属不代表当前手持", "owner_character_id": "worker"},
        {"id": "bag", "description": "负责人携带的文件包", "owner_character_id": "hr"}])
    return goal


def native_setup(goal=None):
    goal = goal or native_goal()
    return {"schema": setup.VERSION, "goal_sha256": setup.digest(goal),
        "characters": {actor["id"]: deepcopy(actor["initial_state"])
                       for actor in goal["whole_plan"]["characters"]},
        "props": {
            "book": {"kind": "scene", "scene_id": "room", "location": "柜内搁板上", "orientation": "封面朝上"},
            "paper": {"kind": "absent", "orientation": None},
            "pen": {"kind": "prop", "container_prop_id": "book", "location": "封面内侧夹着", "orientation": None},
            "bag": {"kind": "actor", "actor_id": "hr", "mode": "carried", "location": "负责人右臂下", "orientation": None}}}


def reject(document, goal=None, *, schema_failure=True, code=None):
    goal = goal or native_goal()
    before, source = deepcopy(document), deepcopy(goal)
    errors = list(Draft202012Validator(setup.build_schema(goal)).iter_errors(document))
    assert bool(errors) == schema_failure
    with pytest.raises(setup.OpeningSetupContractError) as error:
        setup.validate(document, goal)
    diagnosis = error.value.detail
    assert diagnosis["valid"] is False
    if code is not None:
        assert any(item["code"] == code for item in diagnosis["findings"])
    assert document == before and goal == source
    with pytest.raises(setup.OpeningSetupContractError):
        setup.project_legacy_prop_states(document, goal)
    return diagnosis


def test_four_exclusive_position_kinds_validate_without_prose_or_owner_inference():
    goal, document = native_goal(), native_setup()
    before, source = deepcopy(document), deepcopy(goal)
    accepted = setup.validate(document, goal)
    assert accepted == before and accepted is not document
    assert document == before and goal == source
    assert not list(Draft202012Validator(setup.build_schema(goal)).iter_errors(document))
    assert setup.diagnose(document, goal)["semantic_quality_approved"] is False


@pytest.mark.parametrize("mode", ["handheld", "worn", "carried"])
def test_explicit_actor_modes_are_preserved_in_legacy_expected_state(mode):
    goal, document = native_goal(), native_setup()
    document["props"]["bag"]["mode"] = mode
    projected = {row["id"]: row for row in setup.project_legacy_prop_states(document, goal)}
    assert projected["bag"]["holder_character_id"] == "hr"
    assert projected["bag"]["support"] == {"entity_type": "actor", "entity_id": "hr"}
    assert json.loads(projected["bag"]["expected_state"]) == document["props"]["bag"]


def test_scene_and_nested_container_have_no_holder_despite_shared_static_owner():
    goal, document = native_goal(), native_setup()
    projected = {row["id"]: row for row in setup.project_legacy_prop_states(document, goal)}
    for identifier, support in [("book", {"entity_type": "scene", "entity_id": "room"}),
                                ("pen", {"entity_type": "prop", "entity_id": "book"})]:
        assert projected[identifier]["owner_character_id"] == "worker"
        assert projected[identifier]["holder_character_id"] is None
        assert projected[identifier]["support"] == support
        assert projected[identifier]["location"] == document["props"][identifier]["location"]
    assert projected["paper"]["presence_at_start"] == "absent"
    assert all(projected["paper"][key] is None for key in
               ("holder_character_id", "support", "location", "orientation", "anchor", "facing"))


def test_nested_container_does_not_inherit_its_carriers_holder():
    document = native_setup()
    document["props"]["book"] = {"kind": "actor", "actor_id": "hr", "mode": "handheld",
                                  "location": "负责人手里", "orientation": None}
    projected = {row["id"]: row for row in setup.project_legacy_prop_states(document, native_goal())}
    assert projected["book"]["owner_character_id"] == "worker"
    assert projected["book"]["holder_character_id"] == "hr"
    assert projected["pen"]["holder_character_id"] is None
    assert projected["pen"]["support"] == {"entity_type": "prop", "entity_id": "book"}


@pytest.mark.parametrize("kind,key,value", [
    ("book", "actor_id", "worker"), ("book", "holder_character_id", "worker"),
    ("book", "mode", "handheld"), ("book", "container_prop_id", "bag"),
    ("pen", "actor_id", "worker"), ("pen", "holder_character_id", "worker"),
    ("pen", "scene_id", "room"), ("bag", "scene_id", "room"),
    ("bag", "container_prop_id", "book"), ("paper", "location", None),
    ("paper", "holder_character_id", None), ("paper", "scene_id", "room"),
    ("paper", "actor_id", "worker"), ("paper", "container_prop_id", "book"),
    ("paper", "mode", "carried"), ("book", "owner_character_id", "worker"),
    ("book", "support", {"entity_type": "actor", "entity_id": "worker"})])
def test_position_fields_cannot_mix_or_reintroduce_holder_owner_aliases(kind, key, value):
    document = native_setup()
    document["props"][kind][key] = value
    reject(document)


@pytest.mark.parametrize("identifier,key,value", [
    ("bag", "actor_id", "missing"), ("bag", "actor_id", "room"),
    ("bag", "actor_id", "book"), ("bag", "mode", "owned"),
    ("book", "scene_id", "worker"), ("book", "scene_id", "missing"),
    ("book", "scene_id", "pen"), ("pen", "container_prop_id", "worker"),
    ("pen", "container_prop_id", "room"), ("pen", "container_prop_id", "missing"),
    ("pen", "container_prop_id", "pen"), ("paper", "orientation", "朝上"),
    ("book", "location", None), ("book", "location", "  "),
    ("bag", "location", "\n\t"), ("pen", "orientation", " "),
    ("bag", "mode", {}), ("bag", "actor_id", []),
    ("pen", "container_prop_id", {}), ("book", "kind", {}),
    ("book", "orientation", []), ("paper", "kind", "unknown")])
def test_wrong_type_or_identity_cannot_be_locally_repaired(identifier, key, value):
    document = native_setup()
    document["props"][identifier][key] = value
    reject(document)


@pytest.mark.parametrize("identifier,field", [
    ("book", "kind"), ("book", "scene_id"), ("book", "location"), ("book", "orientation"),
    ("pen", "kind"), ("pen", "container_prop_id"), ("pen", "location"), ("pen", "orientation"),
    ("bag", "kind"), ("bag", "actor_id"), ("bag", "mode"), ("bag", "location"), ("bag", "orientation"),
    ("paper", "kind"), ("paper", "orientation")])
def test_native_required_fields_are_not_backfilled(identifier, field):
    document = native_setup()
    document["props"][identifier].pop(field)
    diagnosis = reject(document)
    assert any(row["path"] == f"/props/{identifier}/{field}" for row in diagnosis["findings"])


def test_absent_container_is_rejected_by_strict_validator_and_projection():
    document = native_setup()
    document["props"]["pen"]["container_prop_id"] = "paper"
    reject(document, schema_failure=False, code="OPENING_SETUP_CONTAINER_ABSENT")


def test_missing_declared_container_is_not_hidden_by_reference_enum():
    document = native_setup()
    document["props"].pop("book")
    reject(document, code="OPENING_SETUP_CONTAINER_UNKNOWN")


@pytest.mark.parametrize("cycle", [["book", "pen"], ["book", "pen", "bag"],
                                  ["paper", "book", "pen", "bag"]])
def test_arbitrary_length_container_cycles_block_validate_and_projection(cycle):
    document = native_setup()
    for index, identifier in enumerate(cycle):
        document["props"][identifier] = {"kind": "prop",
            "container_prop_id": cycle[(index + 1) % len(cycle)],
            "location": "另一道具内", "orientation": None}
    diagnosis = reject(document, schema_failure=False, code="OPENING_SETUP_CONTAINER_CYCLE")
    found = next(row for row in diagnosis["findings"] if row["code"] == "OPENING_SETUP_CONTAINER_CYCLE")
    assert set(found["cycle_prop_ids"]) == set(cycle)


def test_valid_container_chain_reaches_explicit_scene_without_inventing_holder():
    document = native_setup()
    document["props"]["bag"] = {"kind": "scene", "scene_id": "room",
                                 "location": "桌面上", "orientation": None}
    document["props"]["book"] = {"kind": "prop", "container_prop_id": "bag",
                                  "location": "文件包内", "orientation": None}
    projected = setup.project_legacy_prop_states(document, native_goal())
    assert all(row["holder_character_id"] is None for row in projected)
    assert {row["id"]: row["support"] for row in projected} == {
        "bag": {"entity_type": "scene", "entity_id": "room"},
        "book": {"entity_type": "prop", "entity_id": "bag"},
        "pen": {"entity_type": "prop", "entity_id": "book"}, "paper": None}


@pytest.mark.parametrize("group,identifier", [("characters", "worker"), ("props", "book")])
@pytest.mark.parametrize("action", ["missing", "extra"])
def test_native_actor_and_prop_coverage_is_exact(group, identifier, action):
    document = native_setup()
    if action == "missing":
        document[group].pop(identifier)
    else:
        document[group]["new"] = deepcopy(document[group][identifier])
    reject(document)


@pytest.mark.parametrize("field,value", [("scene_id", "room2"), ("posture", "站着"), ("location", "门口")])
def test_actor_initial_atoms_cannot_change_for_script(field, value):
    document = native_setup()
    document["characters"]["worker"][field] = value
    reject(document)


@pytest.mark.parametrize("value", [None, [], "bad", 1])
def test_malformed_document_is_rejected_without_type_crash(value):
    reject(value)


@pytest.mark.parametrize("value", [None, [], "bad", 1])
def test_malformed_prop_state_is_rejected_without_type_crash(value):
    document = native_setup()
    document["props"]["book"] = value
    reject(document)


@pytest.mark.parametrize("field,value", [("schema", "creative_opening_setup/v1"),
                                       ("goal_sha256", "0" * 64)])
def test_version_and_exact_goal_identity_are_not_migrated(field, value):
    document = native_setup()
    document[field] = value
    reject(document)


def test_old_v1_owner_as_holder_example_cannot_become_v2_by_version_change():
    goal = static_goal()
    document = old_setup(goal)
    document["schema"] = setup.VERSION
    document["props"]["book"]["location"] = "柜内搁板上"
    reject(document, goal)


def test_goal_change_invalidates_setup_even_when_its_ids_stay_the_same():
    goal, document = native_goal(), native_setup()
    goal["whole_plan"]["props"][0]["description"] = "改写静态描述，不能复用旧SHA"
    reject(document, goal)


def test_empty_native_prop_inventory_keeps_exact_empty_mapping_and_projection():
    goal, document = native_goal(), native_setup()
    goal["whole_plan"]["props"] = []
    document["props"] = {}
    document["goal_sha256"] = setup.digest(goal)
    assert setup.validate(document, goal)["props"] == {}
    assert setup.project_legacy_prop_states(document, goal) == []


def test_single_prop_has_no_possible_prop_container_branch():
    goal, document = static_goal(), old_setup()
    goal["whole_plan"]["props"] = goal["whole_plan"]["props"][:1]
    document = {"schema": setup.VERSION, "goal_sha256": setup.digest(goal),
                "characters": document["characters"],
                "props": {"book": {"kind": "scene", "scene_id": "room",
                                     "location": "桌面", "orientation": None}}}
    assert setup.validate(document, goal) == document
    document["props"]["book"] = {"kind": "prop", "container_prop_id": "book",
                                  "location": "自己内部", "orientation": None}
    reject(document, goal, code="OPENING_SETUP_CONTAINER_SELF")


@pytest.mark.parametrize("mutation", [
    lambda goal: goal.update(contract_version="creative_goal_source_v3"),
    lambda goal: goal["whole_plan"]["characters"][1].update(id="worker"),
    lambda goal: goal["whole_plan"]["props"][0].update(id="worker"),
    lambda goal: goal["whole_plan"]["scenes"][0].update(id="book"),
    lambda goal: goal["whole_plan"]["props"][0].update(owner_character_id="missing"),
    lambda goal: goal["whole_plan"]["characters"][0]["initial_state"].update(scene_id="missing"),
])
def test_invalid_static_goal_is_not_an_opening_binding(mutation):
    goal = native_goal()
    mutation(goal)
    before = deepcopy(goal)
    with pytest.raises(setup.OpeningSetupContractError) as error:
        setup.build_schema(goal)
    assert error.value.code == "OPENING_SETUP_GOAL_INVALID"
    diagnosis = setup.diagnose(native_setup(), goal)
    assert diagnosis["valid"] is False
    assert goal == before


def test_projection_order_is_native_inventory_order_and_does_not_mutate_either_source():
    goal, document = native_goal(), native_setup()
    source, before = deepcopy(goal), deepcopy(document)
    projected = setup.project_legacy_prop_states(document, goal)
    assert [row["id"] for row in projected] == [row["id"] for row in goal["whole_plan"]["props"]]
    assert goal == source and document == before
    projected[0]["support"]["entity_id"] = "changed"
    accepted = setup.validate(document, goal)
    accepted["props"]["book"]["location"] = "changed"
    assert document == before


def test_location_prose_is_preserved_not_used_to_guess_new_support_or_holder():
    document = native_setup()
    document["props"]["book"]["location"] = "原文位置含员工名字，不得猜成worker手持"
    document["props"]["book"]["orientation"] = None
    projected = setup.project_legacy_prop_states(document, native_goal())[0]
    assert projected["location"] == document["props"]["book"]["location"]
    assert projected["holder_character_id"] is None
    assert projected["support"] == {"entity_type": "scene", "entity_id": "room"}
    assert projected["orientation"] is None


def test_maximum_24_prop_request_schema_avoids_cross_prop_availability_expansion():
    # A legal inventory at the whole-plan contract limit must fit a practical
    # request context.  The earlier quadratic cross-object if expansion was
    # 177897 characters for this fixture, despite availability being locally
    # decidable without asking the model to reproduce that expansion.
    goal = native_goal()
    goal["whole_plan"]["props"].extend(
        {"id": f"additional_{index}", "description": "静态合成道具", "owner_character_id": None}
        for index in range(20))
    schema = setup.build_schema(goal)
    assert len(json.dumps(schema, ensure_ascii=False, separators=(",", ":"))) < 50000
    document = native_setup(goal)
    document["props"].update({f"additional_{index}": {"kind": "absent", "orientation": None}
                              for index in range(20)})
    assert setup.validate(document, goal) == document
    document["props"]["pen"]["container_prop_id"] = "additional_19"
    reject(document, goal, schema_failure=False, code="OPENING_SETUP_CONTAINER_ABSENT")
