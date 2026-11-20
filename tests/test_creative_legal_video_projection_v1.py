"""Keep complete legal source steps when an observation shot exceeds API time."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from src.content_factory.creative_legal_video_projection_v1 import select_complete_rows

@pytest.fixture
def compiled():
    root=Path(__file__).resolve().parents[1]
    return json.loads((root/"data/production_revisions/legal_director_performance_20261008/round_06/DELIVERABLE_d1/COMPILED_PERFORMANCE.json").read_text(encoding="utf-8"))

def test_full_15_2_second_shot_is_rejected_instead_of_clamped(compiled):
    with pytest.raises(ValueError,match="split at a complete row boundary"):
        select_complete_rows(compiled,["B1.S03","B1.S04"])

def test_split_preserves_dialogue_performance_and_both_reaction_windows(compiled):
    old=deepcopy(compiled)
    a=select_complete_rows(compiled,["B1.S03"])
    b=select_complete_rows(compiled,["B1.S04"])
    assert a["service_seconds"]==6
    assert b["source_seconds"]==9.2 and b["service_seconds"]==10
    assert a["end_state"]==b["start_state"]
    assert a["rows"][0]==compiled["schedule"][2]
    assert b["rows"][0]==compiled["schedule"][3]
    assert a["rows"][0]["active_start"]-a["rows"][0]["start"]==pytest.approx(1.5)
    assert a["rows"][0]["end"]-a["rows"][0]["active_end"]==pytest.approx(1.5)
    assert compiled==old

def test_skipped_step_is_not_hidden_by_segment_projection(compiled):
    with pytest.raises(ValueError,match="skip a source row"):
        select_complete_rows(compiled,["B1.S02","B1.S04"])

def test_predecessor_state_mismatch_is_rejected(compiled):
    compiled["schedule"][2]["start_state"]["paper_facing"]="face_up"
    with pytest.raises(ValueError,match="preceding source end state mismatch"):
        select_complete_rows(compiled,["B1.S03"])

def test_reversed_or_unknown_refs_do_not_produce_a_request(compiled):
    for refs in (["B1.S04","B1.S03"],["B9.S99"]):
        with pytest.raises(ValueError,match="complete ordered rows"):
            select_complete_rows(compiled,refs)

