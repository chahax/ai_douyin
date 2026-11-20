"""Continuation authorization and immediate source progression guard paid work."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from scripts import prepare_legal_seedance_segment_v1 as renderer
from src.content_factory.creative_stage_contracts import persist
from src.content_factory.creative_segment_execution import read,sha

@pytest.fixture
def setup(tmp_path,monkeypatch):
    c=read(renderer.BUNDLE/"COMPILED_PERFORMANCE.json")
    p=tmp_path/"receipt.json"
    prior={"segment_id":"SH03A","plan_snapshot":{"logical_task_id":renderer.LOGICAL_TASK,
           "source_refs":["B1.S03"],"segment_order":["SH01","SH02","SH03A"]}}
    persist(p,prior)
    persist(tmp_path/"receipt.human_review.json",{"offline_fixture":True})
    frame=tmp_path/"raw.png";frame.write_bytes(b"\xff\xd8\xff"+b"original-provider-bytes")
    monkeypatch.setattr(renderer,"validate_approved_tail",lambda _:{"path":str(frame),"sha256":sha(frame)})
    context={"user_statement":"下一段","authorized_segment":"SH03B",
             "authorized_source_refs":["B1.S04"],"new_video_submissions_authorized":1}
    persist(tmp_path/"CONTINUATION_USER_CONTEXT.json",context)
    base={"sources":{},"model":"doubao-seedance-2-0-mini-260615","historical_campaign":{}}
    return c,p,prior,context,base

def test_adopted_dialogue_once_and_after_window_preserved(setup):
    c,p,prior,context,base=setup
    plan=renderer.build_plan(base,c,p,"SH03B",["B1.S04"])
    row=next(x for x in c["schedule"] if x["source_ref"]=="B1.S04")
    assert plan["duration_seconds"]==10 and plan["timing_projection"]["source_seconds"]==9.2
    assert plan["source_performances"]==[row]
    assert plan["prompt"].count(row["original_text"])==1
    assert plan["original_phase_seconds"]==[{"source_ref":"B1.S04","before":1.2,"active":6.0,"after":2.0}]
    assert plan["segment_order"]==["SH01","SH02","SH03A","SH03B"]
    assert plan["authorization"]["max_new_submissions"]==1

def test_mismatching_user_segment_is_blocked(setup):
    c,p,prior,context,base=setup
    with pytest.raises(ValueError,match="one-segment user instruction"):
        renderer.build_plan(base,c,p,"SH04",["B1.S04"])

def test_skipping_next_source_step_is_blocked_even_with_matching_context(setup):
    c,p,prior,context,base=setup
    context["authorized_source_refs"]=["B1.S06"]
    persist(p.with_name("CONTINUATION_USER_CONTEXT.json"),context)
    with pytest.raises(ValueError,match="immediately following"):
        renderer.build_plan(base,c,p,"SH03B",["B1.S06"])

def test_other_story_tail_is_not_adopted(setup):
    c,p,prior,context,base=setup
    prior["plan_snapshot"]["logical_task_id"]="another-story"
    persist(p,prior)
    with pytest.raises(ValueError,match="another story"):
        renderer.build_plan(base,c,p,"SH03B",["B1.S04"])

def test_one_segment_instruction_cannot_expand_to_multiple_submissions(setup):
    c,p,prior,context,base=setup
    context["new_video_submissions_authorized"]=2
    persist(p.with_name("CONTINUATION_USER_CONTEXT.json"),context)
    with pytest.raises(ValueError,match="one-segment user instruction"):
        renderer.build_plan(base,c,p,"SH03B",["B1.S04"])

