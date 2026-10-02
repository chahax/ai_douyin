from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator

from scripts.modular_shot_bridge_v2 import (
    make_offline_case,build_shot_direction_schema,validate_shot_direction,
    build_shot_local_input,build_shot_local_schema,build_shot_local_messages,
    build_direction_messages,compile_shot_prefix,compile_shot_complete,
)
from src.content_factory.creative_stage_contracts import digest
from src.content_factory.creative_workflow_contract import CreativeContractError

def test_two_narrative_beats_compile_to_four_shots_without_rewriting():
    c,d,l=make_offline_case();before=deepcopy((c,d,l))
    r=compile_shot_complete(c,d,l)
    assert r["source_narrative_beat_count"]==2 and r["execution_shot_count"]==4
    assert r["source_script"]==c["script"] and len(r["source_script"]["beats"])==2
    assert len(r["derived_execution_script"]["beats"])==4
    assert [x for b in r["derived_execution_script"]["beats"] for x in b["dialogue"]]==[
        x for b in c["script"]["beats"] for x in b["dialogue"]]
    shots=r["storyboard"]["shots"]
    assert all(a["end_state"]==b["start_state"] for a,b in zip(shots,shots[1:]))
    assert json.loads(shots[1]["start_state"])["P01(文件夹)"]["holder"]=="C02"
    assert len(r["performance_checks"])==2
    assert all(x["end"]-x["start"]==2 for x in r["performance_checks"])
    assert not r["semantic_approval"] and not r["automatic_media_submit"]
    assert (c,d,l)==before

@pytest.mark.parametrize("case",["duplicate","omitted","reordered"])
def test_dialogue_assignment_is_exactly_once_and_ordered(case):
    c,d,l=make_offline_case()
    c["script"]["beats"][0]["dialogue"].append({"speaker":"乙","text":"别等我。"})
    d["context_sha256"]=digest(c)
    shots=d["beats"][0]["shots"]
    for shot in shots:shot["source_refs"].append("script.beats.0.dialogue.1.text")
    if case=="duplicate":shots[0]["dialogue_indices"]=[0,1];shots[1]["dialogue_indices"]=[0]
    elif case=="omitted":shots[0]["dialogue_indices"]=[0];shots[1]["dialogue_indices"]=[]
    else:shots[0]["dialogue_indices"]=[1];shots[1]["dialogue_indices"]=[0]
    with pytest.raises(CreativeContractError,match="BRIDGE_DIALOGUE_COVERAGE"):
        validate_shot_direction(d,c)

@pytest.mark.parametrize("case",["event_during","cross_shot_during"])
def test_unsupported_parallelism_is_explicit_and_does_not_rewrite_source(case):
    c,d,l=make_offline_case();before=deepcopy(c)
    r=d["beats"][0]["shots"][1]["performance_requirements"][0]
    r["relation"]="during"
    if case=="event_during":r["stimulus_source"]="script.beats.0.event"
    with pytest.raises(CreativeContractError,match="BRIDGE_UNSUPPORTED"):
        validate_shot_direction(d,c)
    assert c==before

def test_event_cannot_be_split_into_multiple_action_shots_by_local_output():
    c,d,l=make_offline_case()
    l[1]["groups"][0].update(kind="action",hold_subject="",operations=[
        {"kind":"gaze","actor":"C01","target":"","value":"门口"}])
    before=deepcopy((c,d,l))
    with pytest.raises(CreativeContractError,match="BRIDGE_UNSUPPORTED"):
        compile_shot_prefix(c,d,l[:2])
    assert (c,d,l)==before

@pytest.mark.parametrize("case",["short","tail","wrong_subject","missing_anchor"])
def test_cross_shot_reaction_checks_real_hold_not_unused_tail(case):
    c,d,l=make_offline_case()
    if case in ("short","tail"):
        l[1]["groups"][0]["duration_seconds"]=0.5
        if case=="tail":l[1]["duration_seconds"]=10
        code="BRIDGE_WINDOW_TOO_SHORT"
    elif case=="wrong_subject":
        l[1]["groups"][0]["hold_subject"]="C02";code="BRIDGE_WINDOW_SUBJECT"
    else:
        l[1]["performance_windows"][0]["anchor"]="invented";code="BRIDGE_WINDOW_ANCHOR"
    with pytest.raises(CreativeContractError,match=code):
        compile_shot_prefix(c,d,l[:2])

def test_prefix_is_available_but_never_counts_as_complete_delivery():
    c,d,l=make_offline_case()
    r=compile_shot_prefix(c,d,l[:2])
    assert r["execution_shot_count"]==2 and r["prefix_only"] and not r["all_shots_complete"]
    with pytest.raises(CreativeContractError,match="BRIDGE_LOCAL_COVERAGE"):
        compile_shot_complete(c,d,l[:2])
    next_input=build_shot_local_input(c,d,l[:2])
    assert next_input["shot_id"]=="B2_S1"
    assert next_input["start_state"]["P01"]["holder"]=="C02"

def test_prior_text_change_invalidates_downstream_shot_identity():
    c,d,l=make_offline_case()
    l[0]["dialogue_performance"]+="，更迟疑"
    with pytest.raises(CreativeContractError,match="BRIDGE_STALE_INPUT"):
        compile_shot_prefix(c,d,l[:2])

def test_existing_v2_seating_precondition_remains_enforced():
    c,d,l=make_offline_case()
    l[2]["groups"][0]["operations"][0]["actor"]="C01"
    with pytest.raises(CreativeContractError,match="PLAN_SEAT_ACCESS_INVALID"):
        compile_shot_prefix(c,d,l[:3])

def test_director_and_local_tools_use_plain_arrays_and_no_condition_keywords():
    c,d,l=make_offline_case()
    schemas=[build_shot_direction_schema(c)]+[build_shot_local_schema(c,d,x["shot_id"]) for x in l]
    def keys(x):
        if isinstance(x,dict):return set(x).union(*(keys(v) for v in x.values()))
        if isinstance(x,list):return set().union(*(keys(v) for v in x))
        return set()
    for schema in schemas:
        Draft202012Validator.check_schema(schema)
        assert not {"prefixItems","allOf","if","then","else"}&keys(schema)
    Draft202012Validator(schemas[0]).validate(d)
    for s,x in zip(schemas[1:],l):Draft202012Validator(s).validate(x)

def test_messages_keep_original_context_reference_and_assets_once():
    c,d,l=make_offline_case()
    c["selected_assets"]=[{"id":"actual_selected_ref","file_sha256":"f"*64}]
    d["context_sha256"]=digest(c)
    m=build_direction_messages(c);payload=json.loads(m[-1]["content"])
    assert payload["context"]==c
    i=build_shot_local_input(c,d,[])
    p=json.loads(build_shot_local_messages(i)[-1]["content"])
    assert p["local_input"]["context"]==c
    assert p["request_identity"]["input_sha256"]==digest(i)
    assert "context" not in p


def test_fixture_raw_action_dialogue_order_and_camera_order_are_preserved():
    c,d,l=make_offline_case()
    r=compile_shot_complete(c,d,l)
    actual=[]
    for source,execution in zip(r["derived_execution_script"]["beats"],r["scheduled_execution"]["beats"]):
        # Read the actual deterministic schedule, never assume groups precede dialogue.
        for event in execution["events"]:
            for op in event["operations"]:
                actual.append(["action",op["kind"]])
            if event["script_slot"]=="dialogue_performance":
                actual.append(["dialogue",source["dialogue"][event["dialogue_index"]]["text"]])
    assert actual==c["fixture_action_dialogue_order"]
    assert [x["source_beat_id"] for x in r["source_map"]]==["B1","B1","B2","B2"]
    assert [x["shot_id"] for x in r["source_map"]]==["B1_S1","B1_S2","B2_S1","B2_S2"]

@pytest.mark.parametrize("case",["raw_steps","source_steps","detailed_source","simultaneous"])
def test_known_complex_sources_stop_before_director_schema_or_request(case):
    c,d,l=make_offline_case()
    if case=="raw_steps":
        c["raw_linear_script"]={"beats":[{"id":"B1","steps":[
            {"kind":"action","text":"取物"},{"kind":"dialogue","text":"说话"},{"kind":"action","text":"动笔"}]}]}
    elif case=="source_steps":c["script"]["beats"][0]["steps"]=[{"kind":"action","text":"取物"}]
    elif case=="detailed_source":c["script"]["beats"][0]["during"]="说完对白后又动笔"
    else:c["script"]["beats"][0]["execution_requirements"]=[{"kind":"simultaneous_dialogue_action"}]
    before=deepcopy(c)
    for prepare in (build_shot_direction_schema,build_direction_messages):
        with pytest.raises(CreativeContractError,match="BRIDGE_UNSUPPORTED"):
            prepare(c)
    assert c==before
