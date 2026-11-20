"""Actual failed native receipts are never changed into accepted fixtures."""
from copy import deepcopy
import json
from pathlib import Path
import socket

from jsonschema import Draft202012Validator
import pytest

from scripts import creative_world_scene_script_contract_v2 as m
from tests.test_creative_world_scene_context_v1 import case as synthetic_case

ROOT = Path(__file__).resolve().parents[1]
ACTUAL = ROOT / "data/production_trials/world_scene_live_20261015/round_02"


def read(name): return json.loads((ACTUAL / name).read_text("utf-8-sig"))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **k): raise AssertionError("schema/diagnostics are pure and offline")
    monkeypatch.setattr(socket.socket, "connect", deny); monkeypatch.setattr(socket, "create_connection", deny)


def test_actual651_old_wire_zero_errors_new_wire_rejects_all_nine_steps_objects_without_mutation(tmp_path):
    receipt = read("call_651_complete_script_01.json")
    goal = read("call_645_whole_plan_02.json")["output"]
    old, native = receipt["request"]["structured_schema"], receipt["output"]
    before = deepcopy(old), deepcopy(native), deepcopy(goal)
    assert list(Draft202012Validator(old).iter_errors(native)) == []
    new = m.refine_schema(old)
    errors = list(Draft202012Validator(new).iter_errors(native))
    assert {tuple(e.absolute_path) for e in errors} >= {("beats", i, "steps") for i in range(9)}
    diagnosis = m.diagnose(native, goal, base_schema=old)
    assert not diagnosis["valid"]
    assert {f["path"] for f in diagnosis["findings"]} >= {f"/beats/{i}/steps" for i in range(9)}
    for f in diagnosis["findings"]:
        if f["path"].endswith("/steps"):
            assert f["expected"] == "array" and f["actual"]["json_type"] == "object"
    assert (old, native, goal) == before
    assert len(new["properties"]["beats"]["allOf"][0]["items"]["properties"]) >= 7
    assert len(json.dumps(new)) < len(json.dumps(old)) + 3500
    assert '"$ref"' not in json.dumps(new)
    with pytest.raises(m.ScriptContractError) as exc: m.validate(native, goal, old)
    assert exc.value.detail == diagnosis
    (tmp_path / "ACTUAL651_DIAGNOSIS.json").write_text(json.dumps(diagnosis, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.parametrize("ordinal", [652, 653])
def test_actual652_653_collect_first_null_and_b02_scene_mismatch_together(ordinal, tmp_path):
    receipt = read(f"call_{ordinal}_complete_script_{ordinal-650:02}.json")
    goal = read("call_645_whole_plan_02.json")["output"]
    native = receipt["output"]; before = deepcopy(native)
    assert list(Draft202012Validator(receipt["request"]["structured_schema"]).iter_errors(native)) == []
    diagnosis = m.diagnose(native, goal, receipt["request"]["structured_schema"])
    exact = {(f["path"], json.dumps(f["expected"]), json.dumps(f["actual"])) for f in diagnosis["findings"]}
    assert ("/scene_contexts/0/previous_context_id", "null", '""') in exact
    assert ("/scene_contexts/1/scene_id", '"SC2"', '"SC1"') in exact
    assert any(f.get("beat_id") == "B02" and f["code"] == "BEAT_PLANNED_SCENE_MISMATCH" for f in diagnosis["findings"])
    # The repaired full beat contract reveals further item-wrapped ensemble
    # rows that the old prefix hole also skipped. Do not pretend two fixes pass.
    paths = {f["path"] for f in diagnosis["findings"]}
    assert "/beats/0/ensemble/CH_GF/0/item" in paths
    assert {f"/beats/0/ensemble/CH_GF/0/{field}" for field in ("action_step_indexes", "expression", "mode")} <= paths
    assert len(diagnosis["findings"]) > 2
    assert native == before and not diagnosis["semantic_quality_approved"]
    (tmp_path / f"ACTUAL{ordinal}_DIAGNOSIS.json").write_text(json.dumps(diagnosis, ensure_ascii=False, indent=2), encoding="utf-8")


def test_legal_synthetic_native_wire_local_agree_and_first_full_context_cannot_escape_fields():
    goal, native = synthetic_case.__wrapped__(); before = deepcopy(native)
    schema = m.refine_schema(m.world.build_script_schema(goal))
    assert list(Draft202012Validator(schema).iter_errors(native)) == []
    assert m.validate(native, goal)["valid"] and m.validate(native, goal, schema)["valid"]
    bad = deepcopy(native); bad["scene_contexts"][0].pop("present_character_ids")
    assert list(Draft202012Validator(schema).iter_errors(bad))
    bad = deepcopy(native); bad["scene_contexts"][0]["story_time"]["relation"] = "later"
    assert list(Draft202012Validator(schema).iter_errors(bad))
    assert native == before and m.refine_schema(schema) == schema


def test_collects_context_chain_ensemble_speaker_indexes_and_parallel_errors_without_guessing_time():
    goal, native = synthetic_case.__wrapped__()
    bad = deepcopy(native); beat = bad["beats"][0]; cast = list(beat["ensemble"])
    actions = [i for i, step in enumerate(beat["steps"]) if step["kind"] == "action"]
    dialogues = [i for i, step in enumerate(beat["steps"]) if step["kind"] == "dialogue"]
    assert actions and dialogues
    missing_actor = cast[0]; beat["ensemble"].pop(missing_actor)
    beat["steps"][dialogues[0]]["speaker"] = missing_actor
    beat["ensemble"][cast[1]][0]["action_step_indexes"] = [dialogues[0], 999]
    beat["parallel_with"] = [{"action_step_index": dialogues[0], "dialogue_step_index": 999}] * 2
    bad["scene_contexts"][0]["previous_context_id"] = "unexpected"
    result = m.diagnose(bad, goal)
    codes = {r["code"] for r in result["findings"]}
    assert {"ENSEMBLE_PARTICIPANT_COVERAGE", "DIALOGUE_SPEAKER_NOT_PRESENT", "ENSEMBLE_ACTION_INDEX", "PARALLEL_TYPED_INDEX", "PARALLEL_PAIR_DUPLICATE"} <= codes
    assert not result["document_order_is_performance_time"] and not result["valid"]
