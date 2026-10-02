from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator

from scripts.modular_step_shot_contract_v3 import (
    make_offline_case,source_catalog,build_direction_schema,validate_direction,
    build_local_input,build_local_schema,validate_local,build_direction_messages,
    build_local_messages,project_complete,
)
from src.content_factory.creative_stage_contracts import digest
from src.content_factory.creative_workflow_contract import CreativeContractError

def test_raw_action_dialogue_reaction_action_order_survives_two_shots():
    c,d,l=make_offline_case();before=deepcopy((c,d,l))
    r=project_complete(c,d,l)
    refs=[x["ref"] for x in source_catalog(c)]
    assert [x["source_step_ref"] for x in r["ordered_execution"]]==refs
    assert [x["source_step"]["kind"] for x in r["ordered_execution"]]==["action","dialogue","action","action"]
    assert [x["shot_id"] for x in r["ordered_execution"]]==["S1","S1","S2","S2"]
    assert r["ordered_execution"][2]["source_step"]["kind"]=="action"
    assert r["ordered_execution"][2]["groups"][0]["semantic_role"]=="reaction"
    assert [x["source_step"] for x in r["ordered_execution"]]==c["raw_linear_script"]["beats"][0]["steps"]
    assert r["source_coverage_passed"] and r["source_order_passed"]
    assert r["dialogue_once_in_original_order"]
    assert not r["event_summary_used_as_action"] and not r["source_text_rewritten"]
    assert not r["physical_compile_attempted"] and not r["physical_state_verified"]
    assert not r["action_semantics_verified"] and not r["reaction_timing_verified"]
    assert not r["production_ready"] and not r["semantic_approval"]
    assert (c,d,l)==before

@pytest.mark.parametrize("case",["duplicate","omitted","reversed_shots","noncontiguous"])
def test_director_cannot_copy_delete_or_reorder_raw_steps(case):
    c,d,l=make_offline_case();shots=d["beats"][0]["shots"]
    if case=="duplicate":shots[1]["source_step_refs"].insert(0,shots[0]["source_step_refs"][-1])
    elif case=="omitted":shots[0]["source_step_refs"].pop()
    elif case=="reversed_shots":shots.reverse()
    else:
        a=shots[0]["source_step_refs"][1];b=shots[1]["source_step_refs"][0]
        shots[0]["source_step_refs"][1]=b;shots[1]["source_step_refs"][0]=a
    before=deepcopy(c)
    with pytest.raises(CreativeContractError,match="STEP_SOURCE_COVERAGE|STEP_NONCONTIGUOUS"):
        validate_direction(d,c)
    assert c==before

def test_local_action_groups_cannot_bind_other_original_action():
    c,d,l=make_offline_case()
    l[1]["step_units"][0]["groups"][0]["action_ref"]=l[1]["step_units"][1]["source_step_ref"]
    with pytest.raises(CreativeContractError,match="STEP_ACTION_BINDING"):
        validate_local(l[1],c,d)

def test_local_step_units_cannot_swap_reaction_and_following_action():
    c,d,l=make_offline_case();l[1]["step_units"].reverse()
    with pytest.raises(CreativeContractError,match="STEP_LOCAL_COVERAGE"):
        validate_local(l[1],c,d)

def test_dialogue_unit_only_references_original_line_and_never_carries_action():
    c,d,l=make_offline_case()
    l[0]["step_units"][1]["groups"]=deepcopy(l[0]["step_units"][0]["groups"])
    with pytest.raises(CreativeContractError,match="STEP_DIALOGUE_BINDING"):
        validate_local(l[0],c,d)

@pytest.mark.parametrize("field,value",[
    ("text","新编出来的动作"),("speaker","另一个人物"),("operations",[{"kind":"take"}])])
def test_local_output_cannot_add_source_text_or_fake_physical_compile(field,value):
    c,d,l=make_offline_case()
    l[0]["step_units"][0][field]=value
    with pytest.raises(CreativeContractError,match="STEP_SCHEMA_INVALID"):
        validate_local(l[0],c,d)

def test_reaction_is_original_action_not_a_new_source_kind():
    c,d,l=make_offline_case()
    c["raw_linear_script"]["beats"][0]["steps"][2]["kind"]="reaction"
    with pytest.raises(CreativeContractError,match="STEP_SOURCE_INVALID"):
        source_catalog(c)

def test_event_summary_never_substitutes_for_missing_raw_steps():
    c,d,l=make_offline_case()
    del c["raw_linear_script"]["beats"][0]["steps"]
    with pytest.raises(CreativeContractError,match="STEP_SOURCE_INVALID"):
        build_direction_schema(c)
    del c["raw_linear_script"]
    with pytest.raises(CreativeContractError,match="STEP_SOURCE_REQUIRED"):
        build_direction_schema(c)

def test_upstream_asset_change_invalidates_local_identity_even_with_same_steps():
    c,d,l=make_offline_case()
    c["selected_assets"]=[{"id":"selected_image","file_sha256":"1"*64}]
    d["context_sha256"]=digest(c)
    with pytest.raises(CreativeContractError,match="STEP_SCHEMA_INVALID"):
        project_complete(c,d,l)

def test_partial_source_projection_is_not_complete_output():
    c,d,l=make_offline_case()
    with pytest.raises(CreativeContractError,match="STEP_LOCAL_COVERAGE"):
        project_complete(c,d,l[:1])

def test_all_tools_use_plain_arrays_enums_and_no_conditions():
    c,d,l=make_offline_case()
    schemas=[build_direction_schema(c),build_local_schema(c,d,"S1"),build_local_schema(c,d,"S2")]
    def keys(x):
        if isinstance(x,dict):return set(x).union(*(keys(v) for v in x.values()))
        if isinstance(x,list):return set().union(*(keys(v) for v in x))
        return set()
    for schema in schemas:
        Draft202012Validator.check_schema(schema)
        assert not {"prefixItems","if","then","allOf"}&keys(schema)
    Draft202012Validator(schemas[0]).validate(d)

def test_messages_transmit_full_context_reference_and_identity_without_duplicating_context():
    c,d,l=make_offline_case()
    m=build_direction_messages(c);p=json.loads(m[-1]["content"])
    assert p["context"]==c and p["context"]["references"]==c["references"]
    assert "raw_linear_script" not in p
    i=build_local_input(c,d,"S2");p=json.loads(build_local_messages(i)[-1]["content"])
    assert p["local_input"]["context"]==c
    assert p["request_identity"]["input_sha256"]==digest(i)
    assert "context" not in p


def test_cross_beat_reference_is_rejected_even_when_globally_enumerated():
    c,d,l=make_offline_case()
    second=deepcopy(c["raw_linear_script"]["beats"][0]);second["id"]="B2"
    c["raw_linear_script"]["beats"].append(second)
    d["context_sha256"]=digest(c);d["raw_linear_script_sha256"]=digest(c["raw_linear_script"])
    second_direction=deepcopy(d["beats"][0]);second_direction["beat_id"]="B2"
    for shot in second_direction["shots"]:
        shot["shot_id"]+="SECOND"
        shot["source_step_refs"]=[r.replace(".beats.0.",".beats.1.") for r in shot["source_step_refs"]]
    d["beats"].append(second_direction)
    d["beats"][0]["shots"][0]["source_step_refs"][0]="raw_linear_script.beats.1.steps.0"
    with pytest.raises(CreativeContractError,match="STEP_CROSS_BEAT"):
        validate_direction(d,c)

def test_completed_real_call46_can_be_catalogued_without_rewriting_receipt():
    from pathlib import Path
    import hashlib
    path=Path(__file__).resolve().parents[1]/"data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/call_046_linear_draft_v3.json"
    if not path.exists():pytest.skip("historical response not installed in this checkout")
    before=path.read_bytes();receipt=json.loads(before.decode("utf-8"))
    if receipt.get("status")!="contract_valid":pytest.skip("do not inspect an unfinished receipt as a final source")
    raw=receipt["output"];catalog=source_catalog({"raw_linear_script":raw})
    assert len(catalog)==sum(len(b["steps"]) for b in raw["beats"])
    assert [x["kind"] for x in catalog]==[s["kind"] for b in raw["beats"] for s in b["steps"]]
    assert len({x["ref"] for x in catalog})==len(catalog)
    assert hashlib.sha256(path.read_bytes()).digest()==hashlib.sha256(before).digest()
