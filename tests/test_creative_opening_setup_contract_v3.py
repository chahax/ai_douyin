"""New native absent shape, unchanged present branches; no provider dispatch."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_opening_setup_contract_v2 as frozen
from src.content_factory import creative_opening_setup_contract_v3 as setup
from tests.test_creative_opening_setup_contract_v2 import native_goal


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError("opening v3 is offline only")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def native_setup(goal=None):
    goal = goal or native_goal()
    return {"schema": setup.VERSION, "goal_sha256": setup.digest(goal),
        "characters": {row["id"]: deepcopy(row["initial_state"]) for row in goal["whole_plan"]["characters"]},
        "props": {"book": {"kind": "scene", "scene_id": "room", "location": "柜内搁板上", "orientation": "封面朝上"},
            "paper": {"kind": "absent"},
            "pen": {"kind": "prop", "container_prop_id": "book", "location": "封面内侧夹着", "orientation": None},
            "bag": {"kind": "actor", "actor_id": "hr", "mode": "carried", "location": "负责人右臂下", "orientation": None}}}


def test_absent_has_only_kind_and_only_compiled_projection_has_null_physical_atoms():
    goal, native = native_goal(), native_setup()
    before = deepcopy((goal, native))
    accepted = setup.validate(native, goal)
    assert accepted == native and accepted is not native
    projected = {row["id"]: row for row in setup.project_legacy_prop_states(native, goal)}
    assert native["props"]["paper"] == {"kind": "absent"}
    assert json.loads(projected["paper"]["expected_state"]) == native["props"]["paper"]
    assert projected["paper"]["presence_at_start"] == "absent"
    assert all(projected["paper"][key] is None for key in
        ("holder_character_id", "support", "location", "orientation", "anchor", "facing"))
    assert (goal, native) == before and setup.digest(accepted) == setup.digest(native)
    assert not setup.diagnose(native, goal)["semantic_quality_approved"]


@pytest.mark.parametrize("field,value", [("orientation", None), ("orientation", ""), ("orientation", "正面"),
    ("location", None), ("actor_id", "worker"), ("scene_id", "room"), ("container_prop_id", "book"),
    ("holder_character_id", None), ("support", None), ("mode", "carried")])
def test_absent_extra_native_fields_are_rejected_not_normalized(field, value):
    goal, native = native_goal(), native_setup()
    native["props"]["paper"][field] = value
    before = deepcopy(native)
    with pytest.raises(setup.OpeningSetupContractError): setup.validate(native, goal)
    with pytest.raises(setup.OpeningSetupContractError): setup.project_legacy_prop_states(native, goal)
    assert native == before


@pytest.mark.parametrize("identifier,field,value", [("book", "orientation", ""), ("book", "orientation", "  "),
    ("book", "location", None), ("book", "scene_id", "missing"), ("pen", "container_prop_id", "missing"),
    ("pen", "container_prop_id", "pen"), ("pen", "actor_id", "worker"), ("bag", "actor_id", "room"),
    ("bag", "mode", "owner"), ("bag", "location", " ")])
def test_present_type_identity_and_exclusive_position_rules_remain(identifier, field, value):
    native = native_setup()
    native["props"][identifier][field] = value
    with pytest.raises(setup.OpeningSetupContractError): setup.validate(native, native_goal())


@pytest.mark.parametrize("identifier", ["book", "pen", "bag"])
def test_present_orientation_is_still_required(identifier):
    native = native_setup()
    native["props"][identifier].pop("orientation")
    with pytest.raises(setup.OpeningSetupContractError): setup.validate(native, native_goal())


@pytest.mark.parametrize("cycle", [["book", "pen"], ["book", "pen", "bag"], ["paper", "book", "pen", "bag"]])
def test_container_cycles_and_absent_container_still_block_compilation(cycle):
    native = native_setup()
    for index, identifier in enumerate(cycle):
        native["props"][identifier] = {"kind": "prop", "container_prop_id": cycle[(index + 1) % len(cycle)],
            "location": "另一道具内", "orientation": None}
    with pytest.raises(setup.OpeningSetupContractError) as exc: setup.project_legacy_prop_states(native, native_goal())
    assert any(row["code"] == "OPENING_SETUP_CONTAINER_CYCLE" for row in exc.value.detail["findings"])
    native = native_setup()
    native["props"]["pen"]["container_prop_id"] = "paper"
    with pytest.raises(setup.OpeningSetupContractError) as exc: setup.project_legacy_prop_states(native, native_goal())
    assert any(row["code"] == "OPENING_SETUP_CONTAINER_ABSENT" for row in exc.value.detail["findings"])


@pytest.mark.parametrize("field", ["characters", "props"])
@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_exact_coverage_and_native_source_identity_are_preserved(field, mutation):
    native = native_setup()
    identifier = next(iter(native[field]))
    if mutation == "missing": native[field].pop(identifier)
    else: native[field]["extra"] = deepcopy(native[field][identifier])
    with pytest.raises(setup.OpeningSetupContractError): setup.validate(native, native_goal())


def test_new_schema_changes_only_absent_branch_and_version_keeps_present_branches_exact():
    goal = native_goal()
    old, new = frozen.build_schema(goal), setup.build_schema(goal)
    assert new["properties"]["goal_sha256"] == old["properties"]["goal_sha256"]
    assert new["properties"]["characters"] == old["properties"]["characters"]
    for identifier in new["properties"]["props"]["properties"]:
        old_branches = {b["properties"]["kind"]["const"]: b for b in old["properties"]["props"]["properties"][identifier]["oneOf"]}
        new_branches = {b["properties"]["kind"]["const"]: b for b in new["properties"]["props"]["properties"][identifier]["oneOf"]}
        assert set(new_branches) == set(old_branches)
        for kind in set(new_branches) - {"absent"}: assert new_branches[kind] == old_branches[kind]
        assert new_branches["absent"] == {"type": "object", "properties": {"kind": {"const": "absent"}},
            "required": ["kind"], "additionalProperties": False}
    Draft202012Validator.check_schema(new)


@pytest.mark.parametrize("ordinal", [589, 590])
def test_real_old_rejected_setup_is_not_converted_or_reaccepted_as_new_native(ordinal):
    root = Path(__file__).resolve().parents[1] / "data/production_trials/goal_context_text_production_20261013/round_15"
    paths = list(root.glob(f"call_{ordinal}_*.json"))
    if not paths: pytest.skip("read-only old setup fixture absent")
    path = paths[0]
    raw = path.read_bytes()
    receipt = json.loads(raw)
    goal = json.loads((root / "call_585_goal_plan_22.json").read_text(encoding="utf-8"))["output"]
    assert receipt["status"] == "contract_rejected" and receipt["output"]["schema"] == frozen.VERSION
    with pytest.raises(setup.OpeningSetupContractError): setup.validate(receipt["output"], goal)
    assert path.read_bytes() == raw
