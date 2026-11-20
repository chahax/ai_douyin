"""Offline explicit-orientation contract regressions; no old report conversion."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_opening_setup_contract_v3 as frozen
from src.content_factory import creative_opening_setup_contract_v4 as setup
from tests.test_creative_opening_setup_contract_v3 import native_setup as fixture_v3
from tests.test_creative_opening_setup_contract_v2 import native_goal

PROJECT = Path(__file__).resolve().parents[1]
ACTUAL = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_23"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError("setup4 is offline only")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def synthetic_v4(old_fixture_native_setup):
    """Construct new synthetic fixtures, never repair known bad native receipts."""
    native = deepcopy(old_fixture_native_setup)
    native["schema"] = setup.VERSION
    for state in native["props"].values():
        if state["kind"] == "absent":
            state.pop("orientation", None)
            continue
        value = state["orientation"]
        if value is None:
            state["orientation"] = {"status": "unspecified", "text": ""}
        elif isinstance(value, str) and value.strip():
            state["orientation"] = {"status": "specified", "text": value}
        else:
            raise ValueError("fixture has no valid original orientation")
    return native


def native_setup(goal=None):
    return synthetic_v4(fixture_v3(goal))


def test_explicit_state_is_lossless_and_only_specified_text_projects():
    goal, native = native_goal(), native_setup()
    native["props"]["bag"]["orientation"] = {"status": "unspecified", "text": "朝向未指定，后续动作不能证明初态"}
    before = deepcopy((goal, native))
    accepted = setup.validate(native, goal)
    projected = {row["id"]: row for row in setup.project_legacy_prop_states(native, goal)}
    assert accepted == native and accepted is not native
    assert projected["book"]["orientation"] == "封面朝上"
    assert projected["pen"]["orientation"] is None and projected["bag"]["orientation"] is None
    assert projected["paper"]["orientation"] is None
    for identifier, row in projected.items():
        assert json.loads(row["expected_state"]) == native["props"][identifier]
    assert all(projected["paper"][key] is None for key in ("holder_character_id", "support", "location", "anchor", "facing"))
    assert (goal, native) == before
    assert not setup.diagnose(native, goal)["semantic_quality_approved"]


@pytest.mark.parametrize("value", [None, "", "正面朝上", {"null": ""}, {}, {"status": "specified"},
    {"text": "向上"}, {"status": "specified", "text": ""}, {"status": "specified", "text": " \n\t"},
    {"status": "specified", "text": None}, {"status": "unspecified", "text": None},
    {"status": "unknown", "text": ""}, {"status": "unspecified", "text": "", "direction": "朝上"}])
@pytest.mark.parametrize("identifier", ["book", "pen", "bag"])
def test_present_orientation_requires_closed_explicit_object(value, identifier):
    native = native_setup()
    native["props"][identifier]["orientation"] = value
    before = deepcopy(native)
    diagnosis = setup.diagnose(native, native_goal())
    assert not diagnosis["valid"]
    assert any(row["path"].startswith(f"/props/{identifier}/orientation") for row in diagnosis["findings"])
    with pytest.raises(setup.OpeningSetupContractError): setup.project_legacy_prop_states(native, native_goal())
    assert native == before


@pytest.mark.parametrize("identifier", ["book", "pen", "bag"])
def test_orientation_is_required_for_each_present_kind(identifier):
    native = native_setup()
    native["props"][identifier].pop("orientation")
    with pytest.raises(setup.OpeningSetupContractError): setup.validate(native, native_goal())


def test_schema_changes_only_present_orientation_and_version():
    old, new = frozen.build_schema(native_goal()), setup.build_schema(native_goal())
    assert new["properties"]["goal_sha256"] == old["properties"]["goal_sha256"]
    assert new["properties"]["characters"] == old["properties"]["characters"]
    assert new["properties"]["schema"] == {"const": setup.VERSION}
    for identifier, field in new["properties"]["props"]["properties"].items():
        old_branches = old["properties"]["props"]["properties"][identifier]["oneOf"]
        assert len(field["oneOf"]) == len(old_branches)
        for prior, current in zip(old_branches, field["oneOf"]):
            kind = current["properties"]["kind"]["const"]
            prior, current = deepcopy(prior), deepcopy(current)
            if kind != "absent":
                orientation = current["properties"].pop("orientation")
                prior["properties"].pop("orientation")
                assert orientation["type"] == "object" and orientation["additionalProperties"] is False
                assert set(orientation["required"]) == {"status", "text"}
                assert orientation["properties"]["text"]["type"] == "string"
                assert "anyOf" not in orientation
            assert prior == current
    Draft202012Validator.check_schema(new)


@pytest.mark.parametrize("mutation", ["cycle", "absent_container", "unknown_container", "self", "actor_id", "scene_id",
    "actor_mode", "blank_location", "absent_extra", "missing_prop", "extra_prop", "changed_actor", "wrong_goal", "old_version"])
def test_other_positions_source_identity_and_container_gates_remain(mutation):
    native = native_setup()
    if mutation == "cycle":
        native["props"]["book"] = {"kind": "prop", "container_prop_id": "pen", "location": "笔旁", "orientation": {"status": "unspecified", "text": ""}}
    elif mutation == "absent_container": native["props"]["pen"]["container_prop_id"] = "paper"
    elif mutation == "unknown_container": native["props"]["pen"]["container_prop_id"] = "missing"
    elif mutation == "self": native["props"]["pen"]["container_prop_id"] = "pen"
    elif mutation == "actor_id": native["props"]["bag"]["actor_id"] = "room"
    elif mutation == "scene_id": native["props"]["book"]["scene_id"] = "worker"
    elif mutation == "actor_mode": native["props"]["bag"]["mode"] = "owner"
    elif mutation == "blank_location": native["props"]["book"]["location"] = " "
    elif mutation == "absent_extra": native["props"]["paper"]["orientation"] = {"status": "unspecified", "text": ""}
    elif mutation == "missing_prop": native["props"].pop("bag")
    elif mutation == "extra_prop": native["props"]["extra"] = {"kind": "absent"}
    elif mutation == "changed_actor": native["characters"]["worker"]["location"] = "另一处"
    elif mutation == "wrong_goal": native["goal_sha256"] = "0" * 64
    else: native["schema"] = frozen.VERSION
    with pytest.raises(setup.OpeningSetupContractError): setup.validate(native, native_goal())


@pytest.mark.parametrize("ordinal", [614, 615])
def test_actual_rejected_receipt_stays_rejected_even_if_only_version_is_restamped(ordinal):
    path = next(ACTUAL.glob(f"call_{ordinal}_*.json"))
    original = path.read_bytes()
    receipt = json.loads(original)
    goal = json.loads((ACTUAL / "INHERITED_NATIVE_GOAL.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "contract_rejected" and receipt["output"]["schema"] == frozen.VERSION
    for document in (receipt["output"], {**deepcopy(receipt["output"]), "schema": setup.VERSION}):
        with pytest.raises(setup.OpeningSetupContractError): setup.validate(document, goal)
    assert path.read_bytes() == original
