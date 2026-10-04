"""Offline correspondence tests; fabricated reviews never imply model approval."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from scripts import creative_joint_source_binding_v9 as v9
from scripts import step_index_physical_adapter_v4 as physical
from scripts import creative_linear_script_v2 as linear
from scripts.creative_script_review_sources_v7 import validate_review_v7
from scripts import creative_compact_review_transport_v8 as compact
from tests.test_run_creative_resume_v1 import complete_joint_review
from tests.test_step_index_physical_adapter_v4 import face_case

QA=Path("data/qa/step_index_physical_adapter_v4_20261004")


def full_context(context,direction,locals_):
    compiled=physical.compile_complete(context,direction,locals_)
    ctx=deepcopy(context)
    ctx["script"]=linear.accept_linear_script(context["raw_linear_script"],context["raw_linear_script"],
        character_names=[c["name"] for c in context["static_visual_manifest"]["characters"]])
    ctx["script"].pop("screenplay_markdown")
    ctx.update(shots=deepcopy(compiled["storyboard"]),state_plan=deepcopy(compiled["derived_action_plan"]),
        whole_film_direction=deepcopy(direction),execution_script=deepcopy(compiled["derived_execution_script"]),
        execution_bindings=[{k:deepcopy(t[k]) for k in ("shot_id","source_ref","anchor","kind","start","end")}
                            for t in compiled["source_trace"]],declared_performance_window_checks=deepcopy(compiled["performance_checks"]))
    return ctx


@pytest.fixture
def context():
    case=json.loads((QA/"fixture_two_beats_four_shots_case.json").read_text(encoding="utf-8"))
    return full_context(case["context"],case["direction"],case["locals"])


def ref(ctx,path):
    value=ctx
    for key in path.split("."):value=value[int(key)] if isinstance(value,list) else value[key]
    return {"path":path,"quote":value if isinstance(value,str) else json.dumps(value)}


def review_for(ctx):
    review=complete_joint_review(ctx)
    for row,m in zip(review["coverage"],v9.preflight(ctx)["mapping"]):
        timing=row["checks"]["timing"]["evidence_refs"]
        timing += [ref(ctx,f"script.beats.{m['narrative_beat_index']}.duration_seconds"),
                   ref(ctx,f"execution_script.beats.{m['execution_index']}.duration_seconds")]
        row["checks"]["continuity"]["evidence_refs"] += [ref(ctx,p) for p in m["continuity_source_leaves"]]
        if m["dialogue_text_leaves"]:
            row["checks"]["dialogue_timing"]["evidence_refs"] += [
                ref(ctx,m["dialogue_text_leaves"][0]),ref(ctx,m["dialogue_window_leaves"][0])]
    return review


def test_preflight_maps_three_id_kinds_and_does_not_mutate(context):
    before=deepcopy(context);proof=v9.preflight(context)
    assert context==before
    assert [(m["narrative_beat_id"],m["execution_shot_id"],m["storyboard_id"]) for m in proof["mapping"]]==[
        ("B1","S1","SH01"),("B1","S2","SH02"),("B2","S3","SH03"),("B2","S4","SH04")]
    assert proof["physical_projection_recomputed"] is True
    assert proof["semantic_approval"] is False


def test_valid_corresponding_complete_review_accepted_without_rewriting(context):
    review=review_for(context);before=deepcopy(review)
    raw=compact.encode_review(review,context)
    effective=compact.expand_review(raw,context)
    result=v9.validate_joint_review(effective,context)
    assert effective==review==before
    assert result["semantic_approval"] is False
    assert result["review_source_binding_checked"] is True


@pytest.mark.parametrize("mutation,code",[
    (lambda c:c["shots"]["shots"][2].update(beat_id="UNMAPPED"),"JOINT_SOURCE_ID_MISMATCH"),
    (lambda c:c["execution_script"]["beats"][2].update(id="S1"),"JOINT_SOURCE_ID_MISMATCH"),
    (lambda c:c["script"]["beats"][1].update(before="手补原稿动作"),"JOINT_SOURCE_PROJECTION_INVALID"),
    (lambda c:c["execution_script"]["beats"][2]["dialogue"][0].update(text="改写台词"),"JOINT_SOURCE_DIALOGUE_MISMATCH"),
    (lambda c:c["execution_bindings"][0].update(source_ref="raw_linear_script.beats.1.steps.0"),"JOINT_SOURCE_BINDING_INVALID"),
    (lambda c:c["execution_bindings"][0].update(start=.1),"JOINT_SOURCE_BINDING_INVALID"),
    (lambda c:c["execution_bindings"][0].update(anchor="G_TAKE"),"JOINT_SOURCE_BINDING_INVALID"),
    (lambda c:c["declared_performance_window_checks"][0].update(start=7.25,end=8),"JOINT_SOURCE_WINDOW_INVALID"),
    (lambda c:c["state_plan"]["beats"][0].update(camera="另一个机位"),"JOINT_SOURCE_DIRECTION_MISMATCH"),
    (lambda c:c["shots"]["shots"][1].update(start_state="{}"),"JOINT_SOURCE_COMPILED_MISMATCH"),
    (lambda c:c["execution_bindings"].reverse(),"JOINT_SOURCE_BINDING_INVALID")])
def test_mapping_faults_fail_preflight_before_review_dispatch(context,mutation,code):
    mutation(context)
    with pytest.raises(v9.JointSourceBindingError,match=code):v9.build_messages_addendum(context)


def test_old_v7_wrong_narrative_beat_timing_evidence_is_rejected_by_v9(context):
    review=review_for(context)
    check=review["coverage"][2]["checks"]["timing"]
    check["evidence_refs"]=[ref(context,"shots.shots.2.id"),ref(context,"script.beats.0.duration_seconds"),
                           ref(context,"execution_script.beats.2.duration_seconds")]
    validate_review_v7(review,context)
    with pytest.raises(v9.JointSourceBindingError,match="JOINT_TIMING_SOURCE_MISSING"):
        v9.validate_joint_review(review,context)


def test_original_id_or_event_summary_cannot_replace_actual_text_or_duration(context):
    review=review_for(context)
    check=review["coverage"][2]["checks"]["timing"]
    check["evidence_refs"]=[ref(context,"shots.shots.2.id"),ref(context,"script.beats.1.event"),
                           ref(context,"execution_script.beats.2.duration_seconds")]
    validate_review_v7(review,context)
    with pytest.raises(v9.JointSourceBindingError,match="JOINT_TIMING_SOURCE_MISSING"):
        v9.validate_joint_review(review,context)


@pytest.mark.parametrize("actual_path",["execution_script.beats.2.id","execution_script.beats.0.duration_seconds"])
def test_execution_id_or_another_shot_duration_cannot_replace_actual_window(context,actual_path):
    review=review_for(context)
    review["coverage"][2]["checks"]["timing"]["evidence_refs"]=[ref(context,"shots.shots.2.id"),
        ref(context,"script.beats.1.duration_seconds"),ref(context,actual_path)]
    validate_review_v7(review,context)
    with pytest.raises(v9.JointSourceBindingError,match="JOINT_TIMING_EXECUTION_MISSING"):
        v9.validate_joint_review(review,context)


def test_mapped_raw_step_text_and_actual_binding_window_are_allowed(context):
    review=review_for(context)
    review["coverage"][2]["checks"]["timing"]["evidence_refs"]=[ref(context,"shots.shots.2.id"),
        ref(context,"script.beats.1.duration_seconds"),ref(context,"raw_linear_script.beats.1.steps.0.text"),
        ref(context,"execution_bindings.5.end")]
    v9.validate_joint_review(review,context)


@pytest.mark.parametrize("status",["pass","not_applicable"])
def test_actual_dialogue_needs_text_and_delivery_window(context,status):
    review=review_for(context)
    check=review["coverage"][0]["checks"]["dialogue_timing"]
    check.update(status=status,evidence_refs=[ref(context,"shots.shots.0.id")])
    validate_review_v7(review,context)
    with pytest.raises(v9.JointSourceBindingError,match="JOINT_DIALOGUE_SOURCE_MISSING"):
        v9.validate_joint_review(review,context)


def test_previous_id_cannot_replace_actual_previous_end_state(context):
    review=review_for(context)
    check=review["coverage"][1]["checks"]["continuity"]
    check["evidence_refs"]=[r for r in check["evidence_refs"] if r["path"]!="shots.shots.0.end_state"]
    check["evidence_refs"].append(ref(context,"shots.shots.0.id"))
    validate_review_v7(review,context)
    with pytest.raises(v9.JointSourceBindingError,match="JOINT_CONTINUITY_SOURCE_MISSING"):
        v9.validate_joint_review(review,context)


def test_face_projection_and_actual_cross_shot_facing_remain_valid():
    ctx=full_context(*face_case())
    assert v9.preflight(ctx)["physical_projection_recomputed"] is True
    v9.validate_joint_review(review_for(ctx),ctx)


def test_addendum_plain_rules_mapping_without_duplicate_context_or_fake_approval(context):
    before=deepcopy(context);text=v9.build_messages_addendum(context)
    assert context==before
    assert "timing_source_leaves" in text and "execution_timing_leaves" in text
    assert "SH03" in text and "S3" in text and "B2" in text
    assert "不替换既有完整审核或结论" in text
    assert context["raw_linear_script"]["title"] not in text
    assert '"raw_linear_script":' not in text


def test_complete_blocking_issue_evidence_and_statuses_are_never_repaired(context):
    review=review_for(context)
    review["story_preserved"]=False
    review["issues"]=[{"id":"I_FIXTURE","owner":"director","location":"SH03","severity":"major",
        "rule":"离线问题保存合同测试","evidence":"测试对象，不是实际模型判断",
        "contradiction":"验证来源wrapper不得改审查结论","impact":"禁止把问题删为通过",
        "proposal":"保留完整问题以供实际复核","evidence_refs":[ref(context,"shots.shots.2.visible_performance")]}]
    review["coverage"][2]["checks"]["requirements"].update(status="fail",issue_ids=["I_FIXTURE"])
    before=deepcopy(review)
    v9.validate_joint_review(review,context)
    assert review==before
    assert review["issues"] and review["story_preserved"] is False


@pytest.mark.parametrize("missing",["raw_linear_script","static_visual_manifest","execution_bindings"])
def test_missing_input_is_typed_preflight_failure(context,missing):
    context.pop(missing)
    with pytest.raises(v9.JointSourceBindingError):v9.preflight(context)
