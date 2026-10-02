from copy import deepcopy
import pytest
from src.trend_intelligence.narrative_workflow import expand_script_delta

def fixture():
    parent = {"characters": [{"id": "C1"}], "short": {"events": [{"event_id": "E01"}]}}
    shot = {"shot_id":"S1", "event_id":"E01", "scene_id":"L1", "duration_seconds":2, "participants":["C1"], "action":"take", "result":"held", "dialogue":[], "changes":{"characters":{"C1":"holding P1"}, "props":{"P1":"C1 hand"}}}
    raw = {"short":{"scenes":[], "props":[{"id":"P1","name":"phone"}], "initial_state":{"characters":{"C1":"by table"},"props":{"P1":"table"}}, "shots":[shot, {**deepcopy(shot), "shot_id":"S2", "changes":{"characters":{},"props":{}}}]}}
    return raw, parent

def test_carry_forward_and_frozen_copy():
    raw, parent = fixture(); old = deepcopy(raw)
    result = expand_script_delta(raw, parent, "short")["short"]
    assert result["event_spine"] == parent["short"]["events"]
    assert result["shots"][0]["state_after"] == result["shots"][1]["state_before"]
    assert result["shots"][1]["state_after"]["props"]["P1"] == "C1 hand"
    assert result["shots"][0]["dialogue"] == raw["short"]["shots"][0]["dialogue"]
    result["event_spine"][0]["event_id"] = "changed"
    assert parent["short"]["events"][0]["event_id"] == "E01"
    assert raw == old

@pytest.mark.parametrize("fault", ["unknown", "missing", "empty", "extra"])
def test_bad_delta_rejected(fault):
    raw, parent = fixture()
    if fault == "unknown": raw["short"]["shots"][0]["changes"]["props"]["P2"] = "table"
    if fault == "missing": raw["short"]["initial_state"]["props"] = {}
    if fault == "empty": raw["short"]["shots"][0]["changes"]["props"]["P1"] = ""
    if fault == "extra": raw["short"]["shots"][0]["state_before"] = {}
    with pytest.raises(ValueError): expand_script_delta(raw,parent,"short")
