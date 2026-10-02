from copy import deepcopy
import json
import pytest
from src.content_factory.creative_modular_contract import (
    DIRECTION,LOCAL,build_direction_schema,build_local_schema,build_local_input,
    compile_complete,invalidation_scope)
from src.content_factory.creative_stage_contracts import digest
from src.content_factory.creative_workflow_contract import CreativeContractError
from tests.test_creative_action_plan_v2 import sample


def fixture():
    p,s,m=sample()
    context={"script":s,"static_visual_manifest":m,
        "references":[{"id":"R01","text":"离线样例：先给刺激，再留下可读反应窗口。"}],
        "selected_assets":[{"id":"fixture_character","file_sha256":"0"*64,"source":"offline_fixture_only"}]}
    direction={"schema":DIRECTION,"context_sha256":digest(context),
        "duration_policy":"floating_local_allocation",
        "emotional_arc":"从迟疑到缓和，最终留在对方的反应上",
        "causal_chain":["拿起文件夹使对方察觉离开","告别后的停顿让态度变化可见"],
        "ending_intent":"关系变化可读，具体感染力待全文审查",
        "initial_state":deepcopy(p["initial_state"]),"spatial_contract":deepcopy(p["spatial_contract"]),"beats":[]}
    for i,b in enumerate(p["beats"]):
        row={k:deepcopy(b[k]) for k in ("beat_id","purpose","composition","camera","dialogue_mode","cut_reason")}
        row.update(new_information="对方的态度有了变化",observation_object="C01的可见反应",
            stimulus=s["beats"][i]["event"],audience_feeling="由紧张转为缓和",performance_requirements=[])
        if i==0:
            row["performance_requirements"]=[{"id":"W_"+relation,"subject":"C01",
                "stimulus_source":"script.beats.0.dialogue.0.text","relation":relation,
                "minimum_seconds":1 if relation!="after" else 2} for relation in ("before","during","after")]
        direction["beats"].append(row)
    locals_=[]
    for i,b in enumerate(p["beats"]):
        item={k:deepcopy(b[k]) for k in ("beat_id","groups","dialogue_performance","reaction",
            "cut_after_event_id","completion_condition")}
        item.update(schema=LOCAL,duration_seconds=10,source_event_anchor=b["groups"][0]["id"],
            performance_windows=[])
        if i==0:
            for gid,slot,seconds in (("PRE","before",1),("POST","after",2)):
                item["groups"].append({"id":gid,"script_slot":slot,"kind":"hold","duration_seconds":seconds,
                    "hold_subject":"C01","performance":"停留于可见的表情变化","operations":[]})
            item["cut_after_event_id"]="POST";item["reaction"]["anchor"]="POST"
            item["performance_windows"]=[{"requirement_id":"W_before","anchor":"PRE"},
                {"requirement_id":"W_during","anchor":"dialogue_0"},
                {"requirement_id":"W_after","anchor":"POST"}]
        item["input_sha256"]=digest(build_local_input(context,direction,locals_))
        locals_.append(item)
    return context,direction,locals_


def rebind(context,direction,locals_):
    direction["context_sha256"]=digest(context)
    for i,local in enumerate(locals_):
        local["input_sha256"]=digest(build_local_input(context,direction,locals_[:i]))
    return locals_


def test_split_schema_excludes_competing_authorities():
    from jsonschema import Draft202012Validator
    c,d,l=fixture()
    Draft202012Validator.check_schema(build_direction_schema(c))
    for bid in ("B1","B2"):
        Draft202012Validator.check_schema(build_local_schema(c,d,bid))
    assert "groups" not in build_direction_schema(c)["properties"]["beats"]["prefixItems"][0]["properties"]
    fields=build_local_schema(c,d,"B1")["properties"]
    assert all(k not in fields for k in ("initial_state","start_state","end_state","dialogue","purpose","camera"))


def test_complete_compiler_preserves_source_and_cross_beat_state_and_windows():
    c,d,l=fixture();before=deepcopy((c,d,l))
    result=compile_complete(c,d,l)
    a,b=result["storyboard"]["shots"]
    assert a["end_state"]==b["start_state"]
    assert json.loads(b["start_state"])["P01(文件夹)"]["holder"]=="C02"
    assert a["dialogue_lock"]==c["script"]["beats"][0]["dialogue"]
    assert {v["relation"] for v in result["performance_checks"]}=={"before","during","after"}
    assert result["semantic_approval"] is False and result["requires_complete_model_plan_and_full_review"]
    assert (c,d,l)==before


@pytest.mark.parametrize("change",["script","references","selected_assets","direction"])
def test_changed_upstream_cannot_reuse_local_inputs(change):
    c,d,l=fixture()
    if change=="script":c["script"]["beats"][1]["event"]="新的因果结果"
    elif change=="references":c["references"][0]["text"]+="变化"
    elif change=="selected_assets":c["selected_assets"][0]["file_sha256"]="1"*64
    else:d["beats"][1]["audience_feeling"]="不同的观众感受"
    d["context_sha256"]=digest(c)
    with pytest.raises(CreativeContractError,match="MODULE_STALE_INPUT"):
        compile_complete(c,d,l)


def test_text_only_local_revision_invalidates_next_input_even_with_same_state():
    c,d,l=fixture();l[0]["dialogue_performance"]+="；迟疑更明显"
    with pytest.raises(CreativeContractError,match="MODULE_STALE_INPUT"):
        compile_complete(c,d,l)
    scope=invalidation_scope(c,"local_performance",beat_id="B1")
    assert scope["local_inputs_invalid"]==["B1","B2"] and scope["budget_reset"] is False


def test_last_local_revision_preserves_earlier_prefix_but_invalidates_full_review():
    c,d,l=fixture();scope=invalidation_scope(c,"local_performance",beat_id="B2")
    assert scope["reusable_local_prefix"]==["B1"]
    assert scope["local_inputs_invalid"]==["B2"] and scope["complete_plan_full_review_invalid"]
    assert scope["existing_media_receipts_preserved"]


def test_holding_prop_precondition_from_previous_beat_is_enforced():
    c,d,l=fixture()
    l[1]["groups"][0]["operations"].append({"kind":"take","actor":"C01","target":"P01","value":"右手"})
    with pytest.raises(CreativeContractError,match="PLAN_GROUP_PRECONDITION_INVALID"):
        compile_complete(c,d,l)


def test_reaction_before_stimulus_is_rejected():
    c,d,l=fixture();l[0]["performance_windows"][-1]["anchor"]="PRE"
    with pytest.raises(CreativeContractError,match="MODULE_STIMULUS_REACTION_ORDER"):
        compile_complete(c,d,l)


def test_unused_tail_time_cannot_substitute_for_short_reaction():
    c,d,l=fixture();l[0]["groups"][-1]["duration_seconds"]=0.5
    with pytest.raises(CreativeContractError,match="MODULE_WINDOW_TOO_SHORT"):
        compile_complete(c,d,l)


def test_missing_during_dialogue_window_is_rejected():
    c,d,l=fixture();l[0]["performance_windows"].pop(1)
    with pytest.raises(CreativeContractError,match="MODULE_WINDOW_COVERAGE"):
        compile_complete(c,d,l)


def test_floating_duration_changes_only_derived_timing_script():
    c,d,l=fixture();l[0]["duration_seconds"]=8
    l[1]["input_sha256"]=digest(build_local_input(c,d,l[:1]))
    result=compile_complete(c,d,l)
    assert result["derived_timing_script"]["beats"][0]["duration_seconds"]==8
    assert c["script"]["beats"][0]["duration_seconds"]==10
    assert result["storyboard"]["shots"][0]["dialogue_lock"]==c["script"]["beats"][0]["dialogue"]


def test_partial_plan_is_not_complete_delivery():
    c,d,l=fixture()
    with pytest.raises(CreativeContractError,match="MODULE_INCOMPLETE"):
        compile_complete(c,d,l[:1])


def test_local_module_cannot_set_start_state_or_change_original_dialogue():
    c,d,l=fixture();l[0]["start_state"]={}
    with pytest.raises(CreativeContractError,match="MODULE_SCHEMA_INVALID"):
        compile_complete(c,d,l)


def test_unimplemented_parallel_expression_stops_without_rewriting_source():
    c,d,l=fixture();c["script"]["beats"][0]["execution_requirements"]=[{"kind":"simultaneous_dialogue_action"}]
    d["context_sha256"]=digest(c);l[0]["input_sha256"]=digest(build_local_input(c,d,[]))
    before=deepcopy(c)
    with pytest.raises(CreativeContractError,match="EXPRESSION_UNSUPPORTED"):
        compile_complete(c,d,l)
    assert c==before


@pytest.mark.parametrize("case",["unknown_seat","duplicate_seat"])
def test_direction_seat_identity_blocks_before_any_local(case):
    context,direction,locals_=fixture()
    seats=direction["spatial_contract"]["seats"]
    if case=="unknown_seat":
        seats[0]["seat_id"]="invented_seat"
    else:
        seats.append(deepcopy(seats[0]))
    with pytest.raises(CreativeContractError,match="PLAN_SEAT_ACCESS_INVALID"):
        build_local_input(context,direction,[])
