
import copy
from pathlib import Path
import pytest
from scripts.run_legal_seedance_batch_v1 import prepare,build_plan,ANCHOR
from src.content_factory.creative_legal_video_batch_v1 import split_row,project_remaining,validate_deferred_tail
from src.content_factory.creative_segment_execution import read,sha,validate
from src.content_factory.creative_stage_contracts import persist

@pytest.fixture
def prepared():
    base,manifest,auth,report=prepare()
    plan=build_plan(base,manifest,manifest["segments"][0],ANCHOR)
    return base,manifest,auth,report,plan

def test_all_source_text_and_phase_seconds_preserved(prepared):
    base,manifest,_,report,_=prepared
    compiled=read(base["sources"]["COMPILED_PERFORMANCE.json"]["path"])
    assert len(manifest["segments"])==21
    assert sum(d["source_seconds"] for d in manifest["segments"])==pytest.approx(197.0)
    assert all(4<=d["duration_seconds"]<=15 for d in manifest["segments"])
    for r in compiled["schedule"][4:]:
        pieces=[p for d in manifest["segments"] for p in d["pieces"] if p["row"]["source_ref"]==r["source_ref"]]
        assert "".join(p["row"]["original_text"] for p in pieces)==r["original_text"]
        for lo,hi in [("start","active_start"),("active_start","active_end"),("active_end","end")]:
            assert sum(p["row"][hi]-p["row"][lo] for p in pieces)==pytest.approx(r[hi]-r[lo])

def test_long_action_never_clamped_or_split(prepared):
    base,*_=prepared
    row=read(base["sources"]["COMPILED_PERFORMANCE.json"]["path"])["schedule"][4]
    row["end"]=row["start"]+20
    with pytest.raises(ValueError,match="long action"):
        split_row(row)

def test_dialogue_with_state_transition_not_split(prepared):
    base,*_=prepared
    rows=read(base["sources"]["COMPILED_PERFORMANCE.json"]["path"])["schedule"]
    row=copy.deepcopy(next(r for r in rows if r["end"]-r["start"]>15))
    row["end_state"]["paper_signed"]="signed"
    with pytest.raises(ValueError,match="state transition"):
        split_row(row)

def test_batch_tail_acceptance_never_approves_anchor(prepared,tmp_path):
    *_,plan=prepared
    before=ANCHOR.read_bytes()
    validate_deferred_tail(plan,Path(plan["first_frame"]["path"]))
    p=tmp_path/"plan.json";persist(p,plan)
    validate(p)
    assert ANCHOR.read_bytes()==before
    assert read(ANCHOR)["content_status"]=="awaiting_human_review"

@pytest.mark.parametrize("field,value",[
    ("model","different-model"),
    ("prompt","changed content"),
    ("duration_seconds",15),
    ("segment_id","LG02"),
    ("logical_task_id","another-film"),
    ("segment_order",["SH03B","LG02","LG01"]),
])
def test_batch_cannot_expand_or_change_source_projection(prepared,field,value):
    *_,plan=prepared
    plan[field]=value
    with pytest.raises((ValueError,KeyError)):
        validate_deferred_tail(plan,Path(plan["first_frame"]["path"]))

def test_frame_must_be_provider_exact_tail(prepared,tmp_path):
    *_,plan=prepared
    other=tmp_path/"substitute.png";other.write_bytes(Path(plan["first_frame"]["path"]).read_bytes())
    with pytest.raises(ValueError,match="service original"):
        validate_deferred_tail(plan,other)

def test_default_still_requires_approved_review(prepared,tmp_path):
    *_,plan=prepared
    plan["opening_frame_source"]="preceding_approved_raw_tail"
    fake=tmp_path/"review.json"
    persist(fake,{"schema":"media_user_review/v1","decision":"pending"})
    plan["predecessor_review"]={"path":str(fake),"sha256":sha(fake)}
    p=tmp_path/"plan.json";persist(p,plan)
    with pytest.raises(ValueError,match="explicit approved"):
        validate(p)



def test_whole_shot_dialogue_not_leaked_into_current_request(prepared):
    from src.content_factory.creative_legal_video_batch_v1 import render_prompt
    _,manifest,_,_,_=prepared
    prompt=render_prompt(manifest["segments"][0])
    assert "同时报出" not in prompt
    assert '你看完没问题就签一下' not in prompt
    for d in manifest["segments"]:
        prompt=render_prompt(d)
        for p in d["pieces"]:
            r=p["row"]
            if r["source_kind"]=="dialogue":
                assert prompt.count(r["original_text"])==1

def test_existing_submitted_v1_prompt_and_request_kept():
    from src.content_factory.media_review_policy import validate_source_bindings
    from scripts.run_legal_seedance_batch_v1 import OUT
    path=OUT/"LG01/receipt.json"
    if path.exists():
        record=read(path)
        validate_source_bindings(record)
        assert record["task_id"]=="cgt-20261008223323-dlm24"
        assert "同时报出" in record["plan_snapshot"]["prompt"]

