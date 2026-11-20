"""Synthetic source/report controls; none are actual model judgements."""
from copy import deepcopy
import json
from pathlib import Path
import socket

import pytest

from scripts import creative_world_scene_source_state_audit_v1 as m

ROOT=Path(__file__).resolve().parents[1]
SCENARIO=ROOT/"data/qa/creative_world_scene_workflow28_20261015/SCENARIO_HAPPY_v1.json"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a,**k):raise AssertionError("pure source audit has no network authorization")
    monkeypatch.setattr(socket.socket,"connect",deny);monkeypatch.setattr(socket,"create_connection",deny)


def synthetic_context(resource_conflict=False, quiet_hold=False):
    scenario=json.loads(SCENARIO.read_text("utf-8-sig"));docs=scenario["documents"]
    inputs,profile=deepcopy(scenario["inputs"]),deepcopy(scenario["profile"])
    profile.setdefault("stage_parameters",{}).setdefault("goal_audit",{})["max_completion_tokens"]=32000
    goal=deepcopy(docs["whole_plan_01"]["output"]);setup=deepcopy(docs["opening_setup_01"]["output"])
    goal["whole_plan"]["beats"][0]["visible_change"]="OFFLINE合成：柜台有2个箱子，未有增减操作。"
    goal["whole_plan"]["beats"][1]["visible_change"]=("OFFLINE合成：没有新增、移入或派生，柜台变成3个箱子。" if resource_conflict else "OFFLINE合成：柜台仍有2个箱子，没有增减操作。")
    if quiet_hold:goal["whole_plan"]["beats"][1]["visible_change"]="OFFLINE合成：对方安静听完，神情收紧，没有新增物件操作。"
    setup["goal_sha256"]=m.digest(goal)
    return inputs,profile,goal,setup


def _beat_proof(goal,index):
    path=f"/whole_plan/beats/{index}/visible_change"
    return {"source":"goal","path":path,"quote":goal["whole_plan"]["beats"][index]["visible_change"][:160]}


def synthetic_report(prepared,overall_status="fail"):
    """Only an OFFLINE fake-SDK fixture, never evidence about an actual plan."""
    if overall_status not in m.STATUSES:raise ValueError("test status required")
    goal=prepared["views"]["goal"];setup=prepared["views"]["setup"];beats=goal["whole_plan"]["beats"]
    rows=[{"beat_id":b["id"],"coverage_summary":"OFFLINE合成覆盖，不能当作真实审查结论。",
        "source_evidence":[_beat_proof(goal,i)],"observations":[]} for i,b in enumerate(beats)]
    report={"schema":m.VERSION,"native_goal_sha256":m.digest(goal),"native_setup_sha256":m.digest(setup),
        "context_sha256":prepared["context_sha256"],"beat_reviews":rows,"issues":[],
        "checks":{name:{"status":"pass","reason":"OFFLINE合成正控，非真实语义证明。","issue_ids":[]} for name in m.CHECKS},"overall_status":overall_status}
    if overall_status!="pass":
        entity=goal["whole_plan"]["props"][0]["id"]
        for i in range(2):
            rows[i]["observations"]=[{"id":f"O{i+1:03}","entity_id":entity,"aspect":"quantity",
                "reading":"unknown" if i==0 and overall_status=="unknown" else "occurred",
                "value":f"OFFLINE合成数量读法{i+1}，仅fixture。","evidence":[_beat_proof(goal,i)]}]
        issue={"id":"I001","check_id":"resource_quantity","scope":"cross_beat","beat_ids":[b["id"] for b in beats[:2]],
            "observation_ids":["O001","O002"],"status":overall_status,"summary":"OFFLINE合成资源矛盾/未决fixture，不是对真实规划的判断。",
            "evidence":[_beat_proof(goal,i) for i in range(2)],"revision_target":"goal","required_revision":"OFFLINE合成：从真实来源完整重建，不手填本fixture答案。"}
        report["issues"]=[issue]
        report["checks"]["resource_quantity"]={"status":overall_status,"reason":"OFFLINE合成，保持本fixture问题状态。","issue_ids":["I001"]}
    return report


def test_request_complete_sources_once_no_preseeded_answers_and_same_profile_stage_cap():
    inputs,profile,goal,setup=synthetic_context();before=deepcopy((inputs,profile,goal,setup));p=m.prepare(inputs,profile,goal,setup)
    payload=json.loads(p["request"]["messages"][1]["content"])
    authority=m.workflow._base(inputs,goal)["payload"]
    assert payload=={"authority_inputs":authority,"native_goal_document":goal,"native_opening_setup_document":setup}
    assert p["views"]["inputs"]==inputs and p["views"]["authority_inputs"]==authority
    assert sum(s.count(inputs["reference_fulltext"]) for s in m._string_leaves(payload))==1
    assert p["request"]["role"]=="director" and p["request"]["stage"]=="goal_audit"
    assert p["request"]["parameters"]["max_completion_tokens"]==32000
    assert p["request"]["parameters"]["temperature"]==.4 and p["request"]["parameters"]["thinking"]=="disabled"
    assert "issues" not in payload and "beat_reviews" not in payload
    assert not p["manifest"]["manual_expected_findings_in_request"]
    assert (inputs,profile,goal,setup)==before


def test_synthetic_explicit_resource_conflict_can_be_contract_valid_content_fail_without_program_interpreting_numbers():
    prepared=m.prepare(*synthetic_context(resource_conflict=True));native=synthetic_report(prepared,"fail");before=deepcopy(native)
    checked=m.validate(native,prepared)
    assert checked["valid"] and not checked["accepted"] and checked["status"]=="source_state_fail"
    assert checked["findings"]==native["issues"] and checked["uncertainties"]==[] and checked["contract_findings"]==[]
    assert not checked["program_proves_semantic_state"] and native==before


def test_quiet_hold_requires_no_fabricated_operation_and_unknown_never_passes():
    prepared=m.prepare(*synthetic_context(quiet_hold=True));native=synthetic_report(prepared,"pass")
    assert native["beat_reviews"][1]["observations"]==[]
    checked=m.validate(native,prepared)
    assert checked["valid"] and checked["accepted"] and not checked["text_ready_for_director"]
    uncertain=synthetic_report(prepared,"unknown");checked=m.validate(uncertain,prepared)
    assert checked["valid"] and not checked["accepted"] and checked["uncertainties"]==uncertain["issues"]


def test_missing_beat_and_fabricated_quote_are_rejected_with_exact_paths():
    p=m.prepare(*synthetic_context());native=synthetic_report(p,"pass");native["beat_reviews"].pop()
    checked=m.validate(native,p)
    assert not checked["valid"] and any(f["path"]=="/beat_reviews" for f in checked["findings"])
    native=synthetic_report(p,"pass");native["beat_reviews"][0]["source_evidence"][0]["quote"]="NOT PRESENT IN ORIGINAL SOURCE"
    checked=m.validate(native,p)
    assert not checked["valid"] and any(f["code"]=="SOURCE_QUOTE_INVALID" and f["path"]=="/beat_reviews/0/source_evidence/0" for f in checked["findings"])


def test_issue_check_cross_beat_unknown_and_initial_source_consistency_are_not_optional():
    p=m.prepare(*synthetic_context(resource_conflict=True));native=synthetic_report(p,"fail")
    native["checks"]["resource_quantity"]["status"]="pass";native["issues"][0]["evidence"].pop()
    checked=m.validate(native,p);codes={f["code"] for f in checked["contract_findings"]}
    assert not checked["valid"] and {"CHECK_STATUS_CONFLICT","ISSUE_BEAT_EVIDENCE_MISSING","OVERALL_STATUS_CONFLICT"}<=codes
    native=synthetic_report(p,"pass");base=synthetic_report(p,"unknown")["beat_reviews"][0]["observations"][0]
    native["beat_reviews"][0]["observations"]=[base]
    checked=m.validate(native,p);assert not checked["valid"] and any(f["code"]=="UNKNOWN_READING_HIDDEN" for f in checked["contract_findings"])
    base["reading"]="initial";checked=m.validate(native,p)
    assert not checked["valid"] and any(f["code"]=="INITIAL_SETUP_EVIDENCE_MISSING" for f in checked["contract_findings"])


def test_prepared_context_and_native_identities_cannot_be_rebound_or_hand_normalized():
    p=m.prepare(*synthetic_context());native=synthetic_report(p,"pass");original=deepcopy(native)
    native["native_goal_sha256"]="0"*64;assert not m.validate(native,p)["valid"]
    assert native["native_goal_sha256"]=="0"*64
    modified=deepcopy(p);modified["request"]["messages"][1]["content"]="{}"
    with pytest.raises(ValueError,match="bindings changed"):m.validate(original,modified)


def test_actual_authority_projection_omits_prior_full_script_and_evidence_cannot_cite_unsent_original_fields():
    root=ROOT/"data/production_trials/world_scene_live_20261015/round_02"
    inputs=json.loads((root/"INPUTS.json").read_text("utf-8-sig"))
    goal=json.loads((root/"call_645_whole_plan_02.json").read_text("utf-8-sig"))["output"]
    setup=json.loads((root/"call_650_opening_setup_01.json").read_text("utf-8-sig"))["output"]
    profile=json.loads((ROOT/"data/qa/creative_world_scene_live_20261015/LIVE_PROFILE_v1.json").read_text("utf-8-sig"))
    profile["stage_parameters"]["goal_audit"]["max_completion_tokens"]=32000
    before=deepcopy(inputs);prepared=m.prepare(inputs,profile,goal,setup)
    payload=json.loads(prepared["request"]["messages"][1]["content"])
    raw_scope=inputs["production_preferences"]["prior_story_scope"]
    assert "full_prior_script" in raw_scope
    projected=payload["authority_inputs"]["production_preferences"]["prior_story_scope"]
    assert "full_prior_script" not in projected and projected["prior_script_sha256"]==raw_scope["prior_script_sha256"]
    assert sum(s.count(inputs["reference_fulltext"]) for s in m._string_leaves(payload))==1
    assert prepared["views"]["inputs"]==inputs==before
    assert prepared["manifest"]["authority_inputs_sha256"]==m.digest(payload["authority_inputs"])
    report=synthetic_report(prepared,"pass")
    report["beat_reviews"][0]["source_evidence"].append({"source":"inputs",
        "path":"/production_preferences/prior_story_scope/full_prior_script/title",
        "quote":raw_scope["full_prior_script"]["title"][:160]})
    checked=m.validate(report,prepared)
    assert not checked["valid"] and any(f["code"]=="SOURCE_QUOTE_INVALID" for f in checked["contract_findings"])
