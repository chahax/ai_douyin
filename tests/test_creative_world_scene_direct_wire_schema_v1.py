"""Request-only transformation; real failed native responses remain rejected."""
from copy import deepcopy
import json
from pathlib import Path
import socket

import pytest
from jsonschema import Draft202012Validator

from scripts import creative_world_scene_direct_wire_schema_v1 as m
from tests.test_creative_world_scene_context_v1 import case as synthetic_case

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "data/production_trials/world_scene_live_20261015/round_02"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError("pure provider representation cannot access network")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def read(path): return json.loads(path.read_text("utf-8-sig"))


def test_complete_synthetic_native_satisfies_both_direct_and_unchanged_canonical_without_mutation():
    goal,native=synthetic_case.__wrapped__();source=m.canonical.refine_schema(m.canonical.world.build_script_schema(goal))
    before=deepcopy(goal),deepcopy(native),deepcopy(source)
    result=m.prepare_schema(goal,source);wire=result["schema"]
    assert "$comment" not in wire
    assert not list(m._keyword_paths(wire))
    assert not list(Draft202012Validator(wire).iter_errors(native))
    assert m.canonical.diagnose(native,goal)["valid"]
    assert result["manifest"]["canonical_schema_sha256"]==m.canonical.world.digest(source)
    assert result["manifest"]["provider_schema_sha256"]==m.canonical.world.digest(wire)
    assert not result["manifest"]["provider_wire_alone_equivalent_to_canonical"]
    assert result["manifest"]["full_same_source_semantic_and_physical_reviews_required"]
    assert (goal,native,source)==before


def test_actual645_direct_items_keep_all_complete_fields_and_optional_actor_arrays_once():
    goal=read(OLD/"call_645_whole_plan_02.json")["output"]
    source=m.canonical.refine_schema(m.canonical.world.build_script_schema(goal));wire=m.build_schema(goal)
    oldbeat=source["properties"]["beats"]["allOf"][0]["items"]
    beat=wire["properties"]["beats"]["items"]
    assert set(beat["properties"])==set(oldbeat["properties"])
    assert beat["required"]==oldbeat["required"]
    assert wire["properties"]["beats"]["minItems"]==wire["properties"]["beats"]["maxItems"]==9
    assert beat["properties"]["id"]==oldbeat["properties"]["id"]
    actors=[row["id"] for row in goal["whole_plan"]["characters"]]
    ensemble=beat["properties"]["ensemble"]
    assert set(ensemble["properties"])==set(actors) and ensemble["additionalProperties"] is False
    assert "required" not in ensemble and ensemble["minProperties"]==1
    assert all(v==oldbeat["properties"]["ensemble"]["additionalProperties"] for v in ensemble["properties"].values())
    assert wire["properties"]["scene_contexts"]["items"]==source["properties"]["scene_contexts"]["allOf"][0]["items"]
    assert not list(m._keyword_paths(wire)) and len(json.dumps(wire))<len(json.dumps(source))+1500


def test_direct_wire_never_substitutes_for_exact_order_first_null_speaker_and_local_index_checks():
    goal,native=synthetic_case.__wrapped__();wire=m.build_schema(goal);bad=deepcopy(native)
    bad["beats"].reverse();bad["scene_contexts"][0]["previous_context_id"]=""
    beat=bad["beats"][0];actor=next(iter(beat["ensemble"]))
    action=next(i for i,s in enumerate(beat["steps"]) if s["kind"]=="action")
    dialogue=next(i for i,s in enumerate(beat["steps"]) if s["kind"]=="dialogue")
    beat["steps"][action]["speaker"]=actor
    beat["ensemble"][actor][0]["action_step_indexes"]=[dialogue]
    beat["parallel_with"]=[{"action_step_index":999,"dialogue_step_index":dialogue}]
    assert not list(Draft202012Validator(wire).iter_errors(bad))
    before=deepcopy(bad);checked=m.canonical.diagnose(bad,goal)
    assert not checked["valid"] and not checked["semantic_quality_approved"]
    # The existing canonical collector deduplicates matching path/value
    # findings, so a schema const may represent the same local order rule.
    paths={f["path"] for f in checked["findings"]}
    assert {"/beats/0/id","/scene_contexts/0/previous_context_id",f"/beats/0/ensemble/{actor}/0/action_step_indexes/0","/beats/0/parallel_with/0/action_step_index"}<=paths
    assert any(f["path"]==f"/beats/0/steps/{action}/speaker" for f in checked["findings"])
    assert bad==before


def test_actual654_stays_rejected_and_foreign_or_modified_canonical_schema_is_not_silently_stripped():
    goal=read(OLD/"call_645_whole_plan_02.json")["output"]
    path=ROOT/"data/production_trials/world_scene_live_20261015/round_03/call_654_complete_script_04.json"
    native=read(path)["output"];before=deepcopy(native);wire=m.build_schema(goal)
    assert list(Draft202012Validator(wire).iter_errors(native))
    assert not m.canonical.diagnose(native,goal)["valid"] and native==before
    source=m.canonical.refine_schema(m.canonical.world.build_script_schema(goal))
    source["properties"]["beats"]["allOf"][0]["items"]["properties"].pop("steps")
    with pytest.raises(ValueError,match="exact native-goal contract"):m.build_schema(goal,source)
    with pytest.raises(ValueError,match="exact native-goal contract"):m.build_schema(goal,wire)
