"""Offline regression of the real 2026-09-27 production failure."""
import json
from copy import deepcopy
from pathlib import Path
import pytest
from test_creative_workflow import FakeClients, _answers
from src.content_factory.creative_workflow import (
    CreativeWorkflow, _apply_writer_revision_patch, _writer_revision_schema,
)
from src.content_factory.creative_workflow_contract import CreativeContractError, WRITER_TOOL_SCHEMAS


def workflow(tmp_path, answers):
    result = CreativeWorkflow(tmp_path, clients=FakeClients(answers))
    result.state = {
        "calls_started": 0, "max_calls": 5, "max_total_tokens": 100000,
        "budget_policy_version": "v4_20260923", "max_contract_repairs": 3,
        "contract_repairs_used": 0, "format_repairs_used": 0,
        "revision_rounds": 0, "stages": [],
    }
    return result


def test_real_missing_b04_is_identified_without_filling_parent_content():
    raw = json.loads((Path(__file__).parent / "fixtures/reusable_missing_beat_20260927.json").read_text(encoding="utf-8"))
    before = deepcopy(raw)
    with pytest.raises(CreativeContractError, match="缺失节拍:.*B04.*清单外 item 节拍: B05"):
        _apply_writer_revision_patch({}, raw, ["B01", "B02", "B03", "B04", "B05"])
    assert raw == before


def test_missing_beat_repair_receives_original_issues_and_exact_schema(tmp_path):
    script = _answers()[2]
    valid = {"replace_beats": [{"beat_id": b["id"], "beat": b} for b in script["beats"]]}
    invalid = {"replace_beats": valid["replace_beats"][:1]}
    payload = {"previous_script": script, "affected_beat_ids": [b["id"] for b in script["beats"]],
               "issues": [{"proposal": "补充具体可见反应"}]}
    wf = workflow(tmp_path, [valid])
    corrected = wf._validate_or_repair("writer_revise__test", "writer", payload, invalid,
        lambda value: _apply_writer_revision_patch(script, value, payload["affected_beat_ids"]))
    assert corrected == valid
    request = json.loads(wf.clients.calls[0][1][-1]["content"])
    assert request["original_request"] == payload
    assert request["invalid_response"] == invalid
    schema = wf.clients.call_kwargs[0]["structured_schema"]
    assert schema["properties"]["replace_beats"]["minItems"] == len(script["beats"])
    assert wf.state["calls_started"] == 1
    assert wf.state["contract_repairs_used"] == 1
    assert wf.state["revision_rounds"] == 0


def test_missing_beat_noop_still_stops_without_a_second_call(tmp_path):
    script = _answers()[2]
    invalid = {"replace_beats": []}
    payload = {"previous_script": script, "affected_beat_ids": [b["id"] for b in script["beats"]]}
    wf = workflow(tmp_path, [invalid])
    with pytest.raises(CreativeContractError, match="修复未改变"):
        wf._validate_or_repair("writer_revise__test", "writer", payload, invalid,
            lambda value: _apply_writer_revision_patch(script, value, payload["affected_beat_ids"]))
    assert len(wf.clients.calls) == 1


def test_revision_schema_is_scoped_without_mutating_shared_contract():
    original = deepcopy(WRITER_TOOL_SCHEMAS["writer_revise"])
    rows = _writer_revision_schema(["B01", "B04"])["properties"]["replace_beats"]
    assert rows["minItems"] == rows["maxItems"] == 2
    assert rows["items"]["properties"]["beat_id"]["enum"] == ["B01", "B04"]
    assert WRITER_TOOL_SCHEMAS["writer_revise"] == original


def test_oversize_director_shot_is_repaired_before_becoming_valid(tmp_path):
    good = deepcopy(_answers()[3])
    bad = deepcopy(good)
    bad["shots"][0]["duration_seconds"] = 16
    patch = {"replace_beats": [{"beat_id": good["shots"][0]["beat_id"], "shots": [good["shots"][0]]}]}
    wf = workflow(tmp_path, [bad, patch])
    wf._reusable_generation = True
    result = wf._stage("director_shots__limits_test", "director", {"script": _answers()[2]}, lambda _: None)
    assert result == good
    assert len(wf.clients.calls) == 2
    first_payload = json.loads(wf.clients.calls[0][1][-1]["content"])
    assert first_payload["executor_constraints"]["duration_max"] == 15
    repair = json.loads((tmp_path / "director_shots__limits_test__contract_repair.json").read_text(encoding="utf-8"))
    assert "视频执行时长超限" in repair["error"]
    assert "16秒" in repair["error"]
    assert repair["repair_protocol"] == "director_beat_contract_patch/v1"
    request = json.loads(repair["request"][-1]["content"])
    assert request["executor_constraints"]["duration_max"] == 15
    assert request["target_beat_ids"] == [good["shots"][0]["beat_id"]]


def test_long_beat_is_split_without_shrinking_or_scaling_back(tmp_path):
    good = deepcopy(_answers()[3])
    script = deepcopy(_answers()[2])
    first = good["shots"][0]
    bid = first["beat_id"]
    script["beats"][0]["duration_seconds"] = 23
    bad = deepcopy(good)
    bad["shots"][0]["duration_seconds"] = 23
    a, b = deepcopy(first), deepcopy(first)
    a.update(id="SH01A", duration_seconds=12)
    b.update(id="SH01B", duration_seconds=11, start_state=a["end_state"])
    b["dialogue_lock"] = []
    patch = {"replace_beats": [{"beat_id": bid, "shots": [a, b]}]}
    wf = workflow(tmp_path, [bad, patch])
    wf._reusable_generation = True
    result = wf._stage("director_shots__split_test", "director", {"script": script}, lambda _: None)
    assert [s["duration_seconds"] for s in result["shots"][:2]] == [12, 11]
    assert sum(s["duration_seconds"] for s in result["shots"] if s["beat_id"] == bid) == 23
    assert len(wf.clients.calls) == 2
    request = json.loads(wf.clients.calls[-1][1][-1]["content"])
    assert request["script_beats"][0]["duration_seconds"] == 23
    assert request["executor_constraints"]["duration_min"] == 4
    assert not list(tmp_path.glob("*local_duration_scale*"))
