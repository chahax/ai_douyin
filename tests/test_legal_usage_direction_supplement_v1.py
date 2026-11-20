"""Append-only human direction and exact production input identities; no dispatch."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock
import json
import socket

import pytest
from scripts import run_goal_context_text_production_v18 as runner
from scripts import record_legal_usage_direction_supplement_v1 as supplement
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests.test_creative_goal_commitment_audit_v1 import synthetic as commitment_response
from tests.test_creative_goal_legal_usage_source_audit_v1 import synthetic_source


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*args,**kwargs):raise AssertionError("input supplement tests cannot call providers")
    monkeypatch.setattr(socket.socket,"connect",deny)
    monkeypatch.setattr(socket.socket,"connect_ex",deny)
    monkeypatch.setattr(socket,"create_connection",deny)


@pytest.fixture
def actual_inputs():
    inputs=runner.read(runner.PREFLIGHT_PARENT/"INPUTS.json")
    confirmation=runner.read(runner.USER_DIRECTION_CONFIRMATION)
    return inputs,confirmation


def test_only_two_rows_append_without_changing_old_eight_user_rows_or_any_other_source(actual_inputs):
    original,confirmation=actual_inputs;before=deepcopy(original)
    changed=runner.build_direction_supplemented_inputs(original,confirmation)
    assert original==before
    old,new=original["user_goal_contract"],changed["user_goal_contract"]
    assert sum(len(old[t]) for t in ("constraints","audience_goals"))==8
    assert new["constraints"][:-1]==old["constraints"]
    assert new["audience_goals"][:-1]==old["audience_goals"]
    for key in original:
        if key!="user_goal_contract":assert changed[key]==original[key]
    for key in old:
        if key not in ("constraints","audience_goals"):assert new[key]==old[key]
    ids=runner.workflow.origin_ids(changed)["user_constraint_ids"]
    assert "UC_CONFIRMED_SUPERMARKET_DIRECTION" in ids and "UG_INTENSIFIED_EMOTIONAL_EXCHANGE" in ids
    assert set(ids)==set(runner.workflow.origin_ids(original)["user_constraint_ids"])|{
        "UC_CONFIRMED_SUPERMARKET_DIRECTION","UG_INTENSIFIED_EMOTIONAL_EXCHANGE"}


@pytest.mark.parametrize("field",["schema","user_quote","confirms_story_direction",
    "adopts_current_unreviewed_script","media_or_publish_authorized","changes_frozen_old_inputs",
    "applies_to_new_unfrozen_run","question_context"])
def test_invalid_confirmation_cannot_become_new_goal_or_manuscript_adoption(actual_inputs,field):
    inputs,confirmation=actual_inputs;bad=deepcopy(confirmation)
    bad[field]=not bad[field] if type(bad[field]) is bool else "" if field=="question_context" else "wrong"
    with pytest.raises(ValueError):runner.build_direction_supplemented_inputs(inputs,bad)


def test_second_append_is_rejected_instead_of_replacing_or_duplicating_users(actual_inputs):
    inputs,confirmation=actual_inputs
    changed=runner.build_direction_supplemented_inputs(inputs,confirmation)
    with pytest.raises(ValueError):runner.build_direction_supplemented_inputs(changed,confirmation)


def test_same_quote_with_different_nonempty_confirmation_question_cannot_gain_story_authority(actual_inputs):
    inputs,confirmation=actual_inputs
    confirmation=deepcopy(confirmation)
    confirmation["question_context"]="是否采用当前未经审查的正文？"
    assert confirmation["user_quote"]==runner.USER_DIRECTION_QUOTE
    with pytest.raises(ValueError):runner.build_direction_supplemented_inputs(inputs,confirmation)


def test_actual_first_planning_context_receives_explicit_direction_and_old594_is_only_template(actual_inputs):
    inputs,confirmation=actual_inputs
    changed=runner.build_direction_supplemented_inputs(inputs,confirmation)
    goal=runner.read(runner.PREFLIGHT_PARENT/"goals/native_02.json")
    diagnostic=runner.build_revision_diagnostics(goal)
    prepared=runner.workflow.prepare_goal_request(runner.revision_planning_inputs(changed,goal,diagnostic),runner.read(runner.PROFILE))
    body=json.loads(prepared["request"]["messages"][1]["content"])
    assert body["previous_complete_document"]==goal
    assert body["reference_fulltext"]==inputs["reference_fulltext"]
    assert confirmation["user_quote"] in body["user_goal_contract"]["constraints"][-1]["text"]
    assert body["origin_catalog"]["user"]["UC_CONFIRMED_SUPERMARKET_DIRECTION"]["authority"]=="user_constraint"
    assert body["origin_catalog"]["user"]["UG_INTENSIFIED_EMOTIONAL_EXCHANGE"]["authority"]=="user_audience_goal"
    with pytest.raises(ValueError):runner.workflow._validate_planning_input(changed,goal)


def test_synthetic_new_goal_carries_supplement_through_three_audits_author_and_semantic_review(causal_scenario,actual_inputs):
    inputs,profile,goal,opening,bundle,ids,native=deepcopy(causal_scenario)
    _,confirmation=actual_inputs
    changed=runner.build_direction_supplemented_inputs(inputs,confirmation)
    new_claims=[]
    for table,kind in (("constraints","user_constraint"),("audience_goals","user_audience_goal")):
        row=changed["user_goal_contract"][table][-1]
        new_claims.append({"id":"ADDED_UC" if kind=="user_constraint" else "ADDED_UG", "kind":kind,
            "text":row["text"],"origin_ids":[row["id"]]})
    goal["claims"].extend(new_claims)
    goal["whole_plan"]["audience_path"]["claim_refs"].append("ADDED_UG")
    profile=runner.read(runner.PROFILE)
    source=runner.workflow.prepare_goal_source_audit_request(changed,profile,goal)
    drama=runner.workflow.prepare_goal_drama_audit_request(changed,profile,goal)
    focused=runner.workflow.prepare_goal_commitment_audit_request(changed,profile,goal)
    src_report=synthetic_source(goal,source["source_authority_context"],source["source_context_sha256"])
    src_decision=runner.workflow.validate_goal_source_audit(src_report,goal,context_sha256=source["source_context_sha256"],
        authority_context=source["source_authority_context"])
    assert src_decision["accepted"] is True # synthetic structure only, not a legal gold label
    drama_report=deepcopy(bundle["native_drama_audit"])
    for key in ("schema","goal_sha256","audit_context_sha256"):
        drama_report[key]=drama["request"]["structured_schema"]["properties"][key]["const"]
    drama_report.pop("commitment_checks",None)
    drama_report["closed_scope_findings"]=[]
    drama_report["scope_observations"]={key:{"audible_speakers":[],"operated_props":[]}
        for key in drama["request"]["structured_schema"]["properties"]["scope_observations"]["properties"]}
    focused_report=commitment_response(goal)
    for key in ("schema","goal_sha256","audit_context_sha256"):
        focused_report[key]=focused["request"]["structured_schema"]["properties"][key]["const"]
    for check in focused_report["commitment_checks"].values():
        for usage in check["actual_usages"].values():usage.update(requirement_scope="local_event",comparison_refs=[])
    audits=runner.workflow.build_goal_audit_bundle(src_report,drama_report,focused_report)
    opening.update(schema=runner.setups.VERSION,goal_sha256=runner.digest(goal))
    opening["props"]={key:{"kind":"absent"} if row["kind"]=="absent" else row for key,row in opening["props"].items()}
    author=runner.workflow.prepare_script_request(changed,profile,goal,audits,opening_setup=opening,
        **runner.workflow.origin_ids(changed))
    semantic=runner.workflow.prepare_full_review_part_request(changed,profile,native,author["views"],"semantic")
    expected_quote=confirmation["user_quote"]
    for request in (source,drama,author,semantic):
        body=json.loads(request["request"]["messages"][1]["content"])
        assert expected_quote in body["user_goal_contract"]["constraints"][-1]["text"]
        assert body["user_goal_contract"]["audience_goals"][-1]["id"]=="UG_INTENSIFIED_EMOTIONAL_EXCHANGE"
    assert "user_goal_contract" not in json.loads(focused["request"]["messages"][1]["content"])
    physical=runner.workflow.prepare_full_review_part_request(changed,profile,native,author["views"],"physical")
    assert physical["request"]["input_provenance"]["native_goal_sha256"]==runner.digest(goal)


@pytest.fixture
def supplement_binding(tmp_path,monkeypatch,actual_inputs):
    project,parent=tmp_path/"supplement",tmp_path/"supplement/parent"
    original,confirmation=actual_inputs
    paths={"PROJECT":project,"PREFLIGHT_PARENT":parent,"ROOT":project/"run","CLAIM":project/"grant/CLAIM.json",
        "APPROVAL":project/"grant/USER_CONTINUATION.json","PROFILE":project/"profile.json",
        "USER_DIRECTION_CONFIRMATION":project/"confirmation.json","INPUT_SUPPLEMENT_AUTHORIZATION":project/"grant/AUTHORIZE_INPUT_SUPPLEMENT_v1.json",
        "SUPPLEMENTED_INPUTS":project/"INPUTS_v2.json","SUPPLEMENTED_PREVIEW":project/"PREVIEW_v2.json"}
    for key,value in paths.items():monkeypatch.setattr(runner,key,value)
    seed,diagnostic={"exact":"native594"},{"qualified":"specific error"}
    runner.write(parent/"INPUTS.json",original)
    runner.write(parent/"CALL_LEDGER.json",{"closed":True})
    runner.write(parent/"goals/native_02.json",seed)
    runner.write(runner.PROFILE,{"model":"same"})
    runner.write(runner.USER_DIRECTION_CONFIRMATION,confirmation)
    identity={"ordinal":594,"semantic_approved":False}
    monkeypatch.setattr(runner,"prior_guard",Mock(return_value={"closed":True}))
    monkeypatch.setattr(runner,"verify_seed_native",Mock(return_value=identity))
    monkeypatch.setattr(runner,"build_revision_diagnostics",Mock(return_value=diagnostic))
    def fake_prepare(inputs,profile):return {"request":{"inputs":deepcopy(inputs)}}
    monkeypatch.setattr(runner.workflow,"prepare_goal_request",fake_prepare)
    old=fake_prepare(runner.revision_planning_inputs(original,seed,diagnostic),runner.read(runner.PROFILE))
    runner.write(runner.APPROVAL,{"human_authorized":True,"user_quote":"minimax随便追加","parent_root":str(parent),
        "parent_ledger_sha256":runner.sha_file(parent/"CALL_LEDGER.json"),**runner.authorization_request_identity(diagnostic,old)})
    runner.write(project/"data/qa/creative_legal_usage_20261014/LEGAL_USAGE_REQUEST_PREVIEW_v1.json",{"prepared":old})
    supplement.main()
    return project,original,seed,diagnostic


def test_local_supplement_registration_is_idempotent_without_new_production_claim(supplement_binding):
    project,original,seed,diagnostic=supplement_binding
    before={p:p.read_bytes() for p in project.rglob("*.json")}
    supplement.main()
    changed,prepared,binding=runner.verify_input_supplement(original,seed,diagnostic)
    assert binding["append_only_user_rows"] is True and not binding["old_ledger_reset"]
    assert not runner.ROOT.exists() and not runner.CLAIM.exists()
    assert {p:p.read_bytes() for p in before}==before


@pytest.mark.parametrize("target",["approval","confirmation","inputs","actual_preview","binding"])
def test_supplement_four_identities_and_actual_request_drift_cannot_create_claim(supplement_binding,target):
    project,original,seed,diagnostic=supplement_binding
    path={"approval":runner.APPROVAL,"confirmation":runner.USER_DIRECTION_CONFIRMATION,"inputs":runner.SUPPLEMENTED_INPUTS,
        "actual_preview":runner.SUPPLEMENTED_PREVIEW,"binding":runner.INPUT_SUPPLEMENT_AUTHORIZATION}[target]
    value=runner.read(path)
    if target=="approval":value["user_quote"]="changed"
    elif target=="confirmation":value["question_context"]+=" changed"
    elif target=="inputs":value["user_goal_contract"]["constraints"][0]["text"]="old goal changed"
    elif target=="actual_preview":value["prepared"]["request"]["inputs"]["reference_fulltext"]="changed"
    else:value["actual_prepared_preview_sha256"]="0"*64
    runner.write(path,value)
    with pytest.raises(ValueError):runner.verify_input_supplement(original,seed,diagnostic)
    assert not runner.ROOT.exists() and not runner.CLAIM.exists()


@pytest.mark.parametrize("field",["original_preview_sha256","appended_user_ids","append_only_user_rows",
    "original_law_collection_reference_and_user_rows_unchanged","confirmation_user_quote",
    "confirmation_is_direction_not_manuscript_adoption","existing_text_authority_only",
    "old_ledger_reset","media_authorized","publish_authorized","automatic_transport_retry"])
def test_supplement_binding_declarations_cannot_contradict_actual_inputs_even_when_preview_agrees(supplement_binding,field):
    project,original,seed,diagnostic=supplement_binding
    binding=runner.read(runner.INPUT_SUPPLEMENT_AUTHORIZATION)
    binding[field]=not binding[field] if type(binding[field]) is bool else ["UC_AUTONOMOUS_NATIVE"] if field=="appended_user_ids" else "wrong"
    runner.write(runner.INPUT_SUPPLEMENT_AUTHORIZATION,binding)
    preview=runner.read(runner.SUPPLEMENTED_PREVIEW)
    preview["input_supplement_binding"]=deepcopy(binding)
    runner.write(runner.SUPPLEMENTED_PREVIEW,preview)
    with pytest.raises(ValueError):runner.verify_input_supplement(original,seed,diagnostic)
    assert not runner.ROOT.exists() and not runner.CLAIM.exists()


@pytest.mark.parametrize("field",["input_supplement_binding","provider_calls","media_calls",
    "creative_quality_approved","old_preview_preserved"])
def test_preview_binding_and_no_provider_or_adoption_flags_are_read_back(supplement_binding,field):
    project,original,seed,diagnostic=supplement_binding
    preview=runner.read(runner.SUPPLEMENTED_PREVIEW)
    preview[field]={"wrong":"binding"} if field=="input_supplement_binding" else not preview[field] if type(preview[field]) is bool else 1
    runner.write(runner.SUPPLEMENTED_PREVIEW,preview)
    with pytest.raises(ValueError):runner.verify_input_supplement(original,seed,diagnostic)
    assert not runner.ROOT.exists() and not runner.CLAIM.exists()
