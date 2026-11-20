"""Independent workflow19/source3 routing and current native gates, offline only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

from jsonschema import Draft202012Validator, ValidationError
import pytest

from scripts.creative_m31_flash_role_clients_v1 import M31FlashRoleClients, expected_wire_request
from src.content_factory import creative_goal_context_workflow_v19 as workflow
from src.content_factory import creative_opening_setup_contract_v2 as old_setups
from src.content_factory import creative_opening_setup_contract_v3 as setups
from src.content_factory import creative_goal_drama_audit_contract_v10 as old_drama
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests.test_creative_goal_context_workflow_v15 import synthetic_focused
from tests.test_creative_split_full_review_contract_v4 import synthetic_consistency
from tests import test_goal_context_text_production_v4 as review_helpers

PROJECT = Path(__file__).resolve().parents[1]
ACTUAL = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_15"


def read(p): return json.loads(p.read_text(encoding="utf-8-sig"))
def payload(p): return json.loads(p["request"]["messages"][1]["content"])
def profile(): return read(PROJECT / "config/creative_goal_context_model_profile_v3.json")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError("workflow19 tests may not create clients or contact providers")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(M31FlashRoleClients, "__init__", deny)


def new_case(causal_scenario):
    inputs, _, goal, old_shape, _, ids, native = deepcopy(causal_scenario)
    # Fresh synthetic v3 document; no original589/590 response is rewritten.
    opening = {"schema": setups.VERSION, "goal_sha256": workflow.digest(goal),
        "characters": deepcopy(old_shape["characters"]),
        "props": {key: {"kind": "absent"} if row["kind"] == "absent" else deepcopy(row)
                  for key, row in old_shape["props"].items()}}
    return inputs, goal, opening, ids, native


def fresh_bundle(inputs, goal):
    judgement = {"status": "pass", "reason": "Synthetic shape-only judgment, not semantic gold", "required_revision": ""}
    source_request = workflow.prepare_goal_source_audit_request(inputs, profile(), goal)
    drama_request = workflow.prepare_goal_drama_audit_request(inputs, profile(), goal)
    first = next(ref for ref in workflow.drama_contract.build_evidence_catalog(goal) if ref.startswith("G"))
    row = {**judgement, "evidence_refs": [first], "counterexample_analysis": "Synthetic full comparison field",
           "counterevidence_refs": []}
    # New v3 fake-service constructor, not a converted603 or v1 source report.
    from tests.test_creative_goal_legal_usage_source_audit_v3 import synthetic_source
    source = synthetic_source(goal, source_request["source_authority_context"], workflow.digest(payload(source_request)))
    drama = {"schema": workflow.DRAMA_AUDIT_VERSION, "goal_sha256": workflow.digest(goal),
        "audit_context_sha256": workflow.digest(payload(drama_request)),
        "goal_checks": {key: deepcopy(row) for key in workflow.GOAL_CHECKS},
        "scope_observations": {ref: {"audible_speakers": [], "operated_props": []}
            for ref in workflow.drama_contract.build_scope_source_catalog(goal)}, "closed_scope_findings": []}
    focused = synthetic_focused(inputs, goal)
    focused["audit_context_sha256"] = workflow.digest(payload(workflow.prepare_goal_commitment_audit_request(inputs, profile(), goal)))
    return workflow.build_goal_audit_bundle(source, drama, focused)


def final_wire(prepared):
    actual = payload(prepared)
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    assert prepared["request_sha256"] == workflow.digest(prepared["request"])
    assert prepared["manifest"]["payload_identity"] == workflow.contexts._measure(actual)
    assert prepared["request"]["input_provenance"]["context_manifest_sha256"] == workflow.digest(prepared["manifest"])
    assert prepared["manifest"]["workflow_version"] == workflow.VERSION
    assert prepared["sdk_max_retries"] == 0 and not prepared["dispatch_performed"]
    return actual


def test_setup_wire_consumes_exact_new_native_rule_and_absent_kind_only(causal_scenario):
    inputs, goal, opening, _, _ = new_case(causal_scenario)
    prepared = workflow.prepare_opening_setup_request(inputs, profile(), goal)
    actual = final_wire(prepared)
    assert actual["native_goal_document"] == goal
    assert prepared["request"]["structured_schema"] == setups.build_schema(goal)
    assert setups.OPENING_SETUP_RULE in prepared["wire"]["messages"][0]["content"]
    assert "absent只填kind，不填写orientation" in prepared["wire"]["messages"][0]["content"]
    assert workflow.validate_opening_setup_document(opening, goal) == opening
    assert workflow.contexts._reference_occurrences(actual, inputs["reference_fulltext"]) == 0


def test_new_v3_full_compile_author_body_and_both_review_paths_never_call_v2(causal_scenario, monkeypatch):
    inputs, goal, opening, ids, native = new_case(causal_scenario)
    before = deepcopy((inputs, goal, opening, native))
    def forbid(*a, **kw): raise AssertionError("hidden opening_v2 call is forbidden in the v19 chain")
    for name in ("validate", "build_schema", "project_legacy_prop_states"):
        monkeypatch.setattr(old_setups, name, forbid)
    workflow.prepare_opening_setup_request(inputs, profile(), goal)
    views = workflow.compile_native_views(goal, opening, **ids)
    props = {row["id"]: row for row in views["brief"]["initial_state"]["prop_states"]}
    assert json.loads(props["paper"]["expected_state"]) == {"kind": "absent"}
    assert all(props["paper"][key] is None for key in ("orientation", "location", "support", "holder_character_id"))
    bundle = fresh_bundle(inputs, goal)
    assert workflow.validate_goal_audit(bundle, goal, inputs=inputs)["accepted"]
    authored = workflow.prepare_script_request(inputs, profile(), goal, bundle, opening_setup=opening, **ids)
    assert authored["views"] == views
    assert final_wire(authored)["native_opening_setup_document"] == opening
    compiled = workflow.validate_script_document(native, views, inputs["production_preferences"])["script"]
    prepared = {part: workflow.prepare_full_review_part_request(inputs, profile(), native, views, part)
                for part in ("semantic", "physical")}
    reports = {}
    full = review_helpers.full_review({"full_current_script": compiled, "brief": views["brief"],
        "creative_scene_plan": views["plan"], "native_goal_document": goal,
        "verified_legal_context": prepared["semantic"]["review_legal_context"]})
    full.update(schema=workflow.reviews.VERSION, opening_setup_sha256=workflow.digest(opening))
    for part, request in prepared.items():
        actual = final_wire(request)
        assert actual["native_opening_setup_document"] == opening
        assert actual["initial_evidence_catalog"]["initial:prop:paper"]["value"] == {"kind": "absent"}
        assert actual["compiled_initial_atoms"]["initial:prop:paper"]["presence"] == "absent"
        assert actual["same_source_sha256"]["opening_setup_sha256"] == workflow.digest(opening)
        assert request["request"]["structured_schema"]["properties"]["opening_setup_sha256"]["const"] == workflow.digest(opening)
        assert request["request"]["input_provenance"]["native_opening_setup_sha256"] == workflow.digest(opening)
        report = {key: deepcopy(full[key]) for key in request["request"]["structured_schema"]["properties"] if key in full}
        report.update(schema=workflow.split_reviews.VERSION, part=part, context_sha256=request["context_sha256"], revision_target="none")
        if part == "semantic": report.update(synthetic_consistency(compiled, views["brief"], views["plan"], goal_contract=goal))
        reports[part] = report
        result = workflow.split_reviews.validate_part(report, part, compiled, views["brief"], views["plan"],
            request["review_legal_context"], context_sha256=request["context_sha256"], goal_contract=goal, opening_setup=opening)
        assert result["valid"] and result["accepted"], result
        assert workflow.contexts._reference_occurrences(actual, inputs["reference_fulltext"]) == (1 if part == "semantic" else 0)
    result = workflow.split_reviews.validate_bundle(workflow.split_reviews.build_review_bundle(reports["semantic"], reports["physical"]),
        compiled, views["brief"], views["plan"], prepared["semantic"]["review_legal_context"],
        semantic_context_sha256=prepared["semantic"]["context_sha256"], physical_context_sha256=prepared["physical"]["context_sha256"],
        goal_contract=goal, opening_setup=opening)
    assert result["valid"] and result["accepted"] and not result["creative_quality_passed"], result
    assert (inputs, goal, opening, native) == before


@pytest.mark.parametrize("fault", ["missing_source", "missing_drama", "missing_commitment", "old_drama", "old_bundle",
    "cross_drama_context", "cross_drama_goal", "missing_scope_G", "focus_fail", "focus_unknown"])
def test_three_native_current_audits_remain_required_and_do_not_use_v10_bundle(causal_scenario, fault):
    inputs, goal, opening, ids, _ = new_case(causal_scenario)
    bundle = fresh_bundle(inputs, goal)
    if fault.startswith("missing_") and fault != "missing_scope_G": bundle.pop("native_" + fault[8:] + "_audit")
    elif fault == "old_drama": bundle["native_drama_audit"]["schema"] = old_drama.VERSION
    elif fault == "old_bundle": bundle["schema"] = old_drama.BUNDLE_VERSION
    elif fault == "cross_drama_context": bundle["native_drama_audit"]["audit_context_sha256"] = "0" * 64
    elif fault == "cross_drama_goal": bundle["native_drama_audit"]["goal_sha256"] = "0" * 64
    elif fault == "missing_scope_G": bundle["native_drama_audit"]["scope_observations"].pop(next(iter(bundle["native_drama_audit"]["scope_observations"])))
    else:
        row = next(iter(bundle["native_commitment_audit"]["commitment_checks"].values()))
        usage = next(iter(row["actual_usages"].values()))
        status = fault[6:]
        row.update(status=status, required_revision="Complete new native plan" if status == "fail" else "")
        usage["relationship"] = "contradicts" if status == "fail" else "unknown"
    with pytest.raises((ValueError, ValidationError)):
        workflow.prepare_script_request(inputs, profile(), goal, bundle, opening_setup=opening, **ids)


def test_actual585_scope_all_beat_and_ending_G_and_commitments_only_in_focused_packet():
    if not ACTUAL.exists(): pytest.skip("read-only actual585 fixture absent")
    inputs, goal = read(ACTUAL / "INPUTS.json"), read(ACTUAL / "call_585_goal_plan_22.json")["output"]
    drama_request = workflow.prepare_goal_drama_audit_request(inputs, profile(), goal)
    actual = final_wire(drama_request)
    schema = drama_request["request"]["structured_schema"]
    scopes = workflow.drama_contract.build_scope_source_catalog(goal)
    assert set(schema["properties"]["scope_observations"]["properties"]) == set(scopes)
    assert "G083" in scopes and "G107" in scopes and any(row["source_scope"] == "ending" for row in scopes.values())
    assert "commitment_checks" not in schema["properties"] and "commitment_checks" not in schema["required"]
    assert "creative_commitment_usage_catalog" not in actual
    assert "commitment_checks" not in drama_request["wire"]["messages"][0]["content"]
    shared = schema["$defs"]["scope_source_observations"]["properties"]
    for table in ("audible_speakers", "operated_props"):
        definition = workflow.STAGE_RESPONSIBILITY_CONTRACT["scope_observation_definitions"][table]
        assert shared[table]["description"] == definition["include"] + "；不包括" + definition["exclude"]
    assert workflow.contexts._reference_occurrences(actual, inputs["reference_fulltext"]) == 1
    focus = workflow.prepare_goal_commitment_audit_request(inputs, profile(), goal)
    assert "commitment_checks" in focus["request"]["structured_schema"]["required"]
    assert payload(focus)["creative_commitment_usage_catalog"] == workflow.commitment_audit.build_commitment_usage_catalog(goal)


@pytest.mark.parametrize("target", ["native_version", "native_sha", "compiled_holder", "compiled_expected_state", "fact_projection"])
def test_opening_or_compiler_tamper_blocks_current_request_before_dispatch(causal_scenario, target):
    inputs, goal, opening, ids, native = new_case(causal_scenario)
    views = workflow.compile_native_views(goal, opening, **ids)
    if target == "native_version": views["opening_setup"]["schema"] = old_setups.VERSION
    elif target == "native_sha": views["opening_setup"]["goal_sha256"] = "0" * 64
    elif target == "compiled_holder": views["brief"]["initial_state"]["prop_states"][0]["holder_character_id"] = "worker"
    elif target == "compiled_expected_state": views["brief"]["initial_state"]["prop_states"][1]["expected_state"] = '{"kind":"absent","orientation":null}'
    else: views["fact_projection"]["policy"] = "manual_patch"
    with pytest.raises(ValueError): workflow.prepare_full_review_part_request(inputs, profile(), native, views, "semantic")


def test_actual_setup_request_has_new_absent_branch_and_rule_without_old_receipt_conversion():
    if not ACTUAL.exists(): pytest.skip("read-only actual585 fixture absent")
    paths = [ACTUAL / name for name in ("call_585_goal_plan_22.json", "call_589_opening_setup_01.json",
        "call_590_opening_setup_02.json", "STATE.json", "CALL_LEDGER.json", "PRODUCTION_FREEZE.json")]
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    inputs, goal = read(ACTUAL / "INPUTS.json"), read(paths[0])["output"]
    prepared = workflow.prepare_opening_setup_request(inputs, profile(), goal)
    final_wire(prepared)
    assert prepared["request"]["structured_schema"]["properties"]["schema"]["const"] == setups.VERSION
    assert setups.OPENING_SETUP_RULE in prepared["request"]["messages"][0]["content"]
    branches = prepared["request"]["structured_schema"]["properties"]["props"]["properties"]["pr_water"]["oneOf"]
    absent = next(row for row in branches if row["properties"]["kind"]["const"] == "absent")
    assert set(absent["properties"]) == {"kind"}
    for p in paths[1:3]:
        with pytest.raises(setups.OpeningSetupContractError): workflow.validate_opening_setup_document(read(p)["output"], goal)
    assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


@pytest.mark.parametrize("entry",["prepare_goal_audit_request","build_goal_audit_schema","prepare_full_review_request"])
def test_old_combined_public_entries_are_disabled(entry):
    with pytest.raises(ValueError,match="disabled"):
        getattr(workflow,entry)()


def test_hidden_old_source_and_bundle_gate_cannot_run_anywhere_in_new_chain(causal_scenario,monkeypatch):
    from src.content_factory import creative_goal_context_workflow_v7 as old_source
    from src.content_factory import creative_goal_context_workflow_v17 as old_workflow
    def forbid(*a,**kw): raise AssertionError("Frozen old-source admission must not execute")
    monkeypatch.setattr(old_source,"validate_goal_source_audit",forbid)
    from src.content_factory import creative_goal_legal_usage_source_audit_v1 as source_v1
    monkeypatch.setattr(source_v1,"validate_source",forbid)
    monkeypatch.setattr(old_workflow,"validate_goal_audit",forbid)
    monkeypatch.setattr(old_workflow,"validate_goal_source_audit",forbid)
    monkeypatch.setattr(old_workflow,"prepare_goal_source_audit_request",forbid)
    monkeypatch.setattr(workflow.drama_contract,"validate_bundle",forbid)
    # Includes source -> three native bundle -> opening3 -> author -> both native reviews and bundle.
    test_new_v3_full_compile_author_body_and_both_review_paths_never_call_v2(causal_scenario,monkeypatch)


def test_source_contains_one_whole_lossless_goal_and_complete_authority_with_no_R01(causal_scenario):
    inputs,goal,_,_,_=new_case(causal_scenario); before=deepcopy((inputs,goal))
    prepared=workflow.prepare_goal_source_audit_request(inputs,profile(),goal)
    actual=final_wire(prepared)
    assert workflow.source_audit.SOURCE_REVIEW_RULE in prepared["wire"]["messages"][0]["content"]
    assert "只提交claim_checks" not in prepared["wire"]["messages"][0]["content"]
    assert "native_goal_document" not in actual and "native_goal_claims" not in actual
    assert "goal_evidence_catalog" not in actual
    assert workflow.evidence_view.reconstruct_goal(actual["native_goal_evidence_view"])==goal
    original=workflow.audit_contexts._base_context(inputs,goal)["payload"]
    for key in ("source_packet","verified_legal_context","user_goal_contract","origin_catalog"):
        assert actual[key]==original[key]
    authority={key:actual[key] for key in ("verified_legal_context","origin_catalog")}
    assert prepared["source_authority_context"]==authority
    assert prepared["authority_context_sha256"]==workflow.digest(authority)
    assert prepared["source_context_sha256"]==workflow.digest(actual)
    assert prepared["request"]["structured_schema"]==workflow.source_audit.build_source_schema(goal,authority,context_sha256=workflow.digest(actual))
    assert workflow.contexts._reference_occurrences(actual,inputs["reference_fulltext"])==0
    native=fresh_bundle(inputs,goal)["native_source_audit"]
    assert workflow.validate_goal_source_audit(native,goal,context_sha256=prepared["source_context_sha256"],authority_context=authority)["accepted"]
    assert workflow.validate_goal_source_audit(native,goal,context_sha256=prepared["source_context_sha256"],inputs=inputs)["accepted"]
    with pytest.raises(ValueError,match="authority_context"):
        workflow.validate_goal_source_audit(native,goal,context_sha256=prepared["source_context_sha256"])
    assert (inputs,goal)==before


@pytest.mark.parametrize("fault",["old_source","missing_scan","missing_G","source_unknown","source_fail","authority_drift","source_context_drift"])
def test_new_legal_source_gate_cannot_be_bypassed_before_author(causal_scenario,fault):
    inputs,goal,opening,ids,_=new_case(causal_scenario)
    audits=fresh_bundle(inputs,goal); source=audits["native_source_audit"]
    if fault=="old_source": source["schema"]=workflow.audit_contexts.SOURCE_AUDIT_VERSION
    elif fault=="missing_scan": source.pop("source_observations")
    elif fault=="missing_G": source["source_observations"].pop(next(i for i,x in enumerate(source["source_observations"]) if x["source_ref"].startswith("G")))
    elif fault=="authority_drift": source["authority_context_sha256"]="0"*64
    elif fault=="source_context_drift": source["audit_context_sha256"]="0"*64
    else:
        row=next(iter(source["claim_checks"].values())); status=fault[7:]
        row.update(status=status,required_revision="Complete native plan" if status=="fail" else "")
    with pytest.raises((ValueError,ValidationError)):
        workflow.prepare_script_request(inputs,profile(),goal,audits,opening_setup=opening,**ids)


def test_current_full_review_system_schema_and_E_paths_all_use_compact_v4(causal_scenario):
    inputs,goal,opening,ids,native=new_case(causal_scenario)
    views=workflow.compile_native_views(goal,opening,**ids)
    semantic=workflow.prepare_full_review_part_request(inputs,profile(),native,views,"semantic")
    actual=final_wire(semantic)
    assert workflow.split_reviews.REVIEW_RULE in semantic["wire"]["messages"][0]["content"]
    assert "逐个真实对白E，speaker_id固定" not in semantic["wire"]["messages"][0]["content"]
    assert semantic["request"]["structured_schema"]["properties"]["schema"]["const"]==workflow.split_reviews.VERSION
    assert actual["native_script_document"]==native and actual["native_goal_document"]==goal
    assert all(row=={"evidence_catalog_ref":ref} for ref,row in actual["consistency_evidence_catalog"]["actual_steps"].items())
    assert all("quote" not in row for row in actual["consistency_evidence_catalog"]["target_assertions"].values())
    assert "unresolved_issues" in semantic["request"]["structured_schema"]["required"]


def test_explicit_smaller_context_limits_reject_without_native_truncation(causal_scenario):
    inputs,goal,opening,ids,native=new_case(causal_scenario)
    old_policy=deepcopy(workflow.audit_contexts._base_context(inputs,goal)["manifest"]["context_policy"])
    source=workflow.prepare_goal_source_audit_request(inputs,profile(),goal)
    assert source["manifest"]["context_policy"]==old_policy
    inputs["context_policy"]={"max_payload_characters":10,"max_payload_utf8_bytes":20}
    with pytest.raises(ValueError): workflow.prepare_goal_source_audit_request(inputs,profile(),goal)


def test_actual594_and600_complete_native_sources_prepare_new_packets_without_old595_or601_adoption():
    root=PROJECT/"data/production_trials/goal_context_text_production_20261013/round_16"
    if not root.exists(): pytest.skip("actual594/600 fixture absent")
    paths=[root/name for name in ("INPUTS.json","call_594_goal_plan_24.json","call_595_goal_source_audit_02.json",
        "call_598_opening_setup_01.json","call_600_complete_script_02.json","call_601_full_review_semantic_02.json",
        "STATE.json","CALL_LEDGER.json","PRODUCTION_FREEZE.json")]
    raw={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    inputs=read(paths[0]); goal=read(paths[1])["output"]; opening=read(paths[3])["output"]; native=read(paths[4])["output"]
    source=workflow.prepare_goal_source_audit_request(inputs,profile(),goal)
    actual=final_wire(source)
    assert workflow.evidence_view.reconstruct_goal(actual["native_goal_evidence_view"])==goal
    assert set(source["request"]["structured_schema"]["$defs"]["source_observation"]["properties"]["source_ref"]["enum"])==set(actual["native_goal_evidence_view"]["evidence_catalog"])
    with pytest.raises((ValueError,ValidationError)):
        workflow.validate_goal_source_audit(read(paths[2])["output"],goal,context_sha256=source["source_context_sha256"],authority_context=source["source_authority_context"])
    views=workflow.compile_native_views(goal,opening,**workflow.origin_ids(inputs))
    for part in ("semantic","physical"):
        prepared=workflow.prepare_full_review_part_request(inputs,profile(),native,views,part)
        p=final_wire(prepared)
        assert p["native_script_document"]==native and p["native_goal_document"]==goal and p["native_opening_setup_document"]==opening
        assert workflow.contexts._reference_occurrences(p,inputs["reference_fulltext"])==(1 if part=="semantic" else 0)
        assert prepared["wire"]["max_tokens"]==profile()["stage_parameters"]["full_review"]["max_completion_tokens"]
    assert raw=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


ACTUAL602=PROJECT/"data/production_trials/goal_context_text_production_20261013/round_17"


def test_actual602_three_complete_current_planning_packets_bind_new_source3_without_adopting603():
    if not ACTUAL602.exists(): pytest.skip("actual602 read-only source absent")
    paths=[ACTUAL602/name for name in ("INPUTS.json","call_602_goal_plan_25.json","call_603_goal_source_audit_01.json","PRODUCTION_FREEZE.json","STATE.json","CALL_LEDGER.json")]
    original={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in paths}
    inputs=read(paths[0]);goal=read(paths[1])["output"]
    before=deepcopy((inputs,goal))
    requests={kind:getattr(workflow,"prepare_goal_"+kind+"_audit_request")(inputs,profile(),goal)
              for kind in ("source","commitment","drama")}
    for kind,request in requests.items():
        actual=final_wire(request)
        assert workflow.evidence_view.reconstruct_goal(actual["native_goal_evidence_view"])==goal
        assert actual["native_goal_evidence_view"]["native_goal_sha256"]==workflow.digest(goal)
        assert workflow.contexts._reference_occurrences(actual,inputs["reference_fulltext"])==(1 if kind=="drama"else 0)
    source=requests["source"];s=payload(source)
    base=workflow.audit_contexts._base_context(inputs,goal)["payload"]
    for name in ("source_packet","verified_legal_context","user_goal_contract","origin_catalog"):
        assert s[name]==base[name]
    assert source["request"]["structured_schema"]["properties"]["schema"]["const"]==workflow.SOURCE_AUDIT_VERSION
    assert source["request"]["input_provenance"]["native_source_audit_version"]==workflow.source_audit.VERSION
    assert workflow.source_audit.SOURCE_REVIEW_RULE in source["wire"]["messages"][0]["content"]
    # The complete old603 native is rejected unchanged; no relabeling/conversion.
    with pytest.raises((ValueError,ValidationError)):
        workflow.validate_goal_source_audit(read(paths[2])["output"],goal,
            context_sha256=source["source_context_sha256"],authority_context=source["source_authority_context"])
    assert (inputs,goal)==before
    assert original=={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in paths}


def test_native_v17_bundle_is_not_a_v19_current_three_pack_admission(causal_scenario):
    from src.content_factory import creative_goal_context_workflow_v17 as frozen17
    inputs,goal,opening,ids,_=new_case(causal_scenario)
    audits=fresh_bundle(inputs,goal);audits["schema"]=frozen17.BUNDLE_VERSION
    with pytest.raises(ValueError):workflow.prepare_script_request(inputs,profile(),goal,audits,opening_setup=opening,**ids)


def test_v19_does_not_mutate_frozen18_module_globals_or_sources(causal_scenario):
    from src.content_factory import creative_goal_context_workflow_v18 as frozen17
    from src.content_factory import creative_goal_legal_usage_source_audit_v2 as source1
    old_paths=[Path(frozen17.__file__),Path(source1.__file__)]
    byte_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in old_paths}
    before=(frozen17.VERSION,frozen17.SOURCE_AUDIT_VERSION,frozen17.source_audit,
        frozen17.validate_goal_source_audit,frozen17.validate_goal_audit)
    inputs,goal,opening,ids,native=new_case(causal_scenario)
    requests=[workflow.prepare_goal_source_audit_request(inputs,profile(),goal),
        workflow.prepare_goal_drama_audit_request(inputs,profile(),goal),
        workflow.prepare_goal_commitment_audit_request(inputs,profile(),goal)]
    assert all(p["manifest"]["workflow_version"]==workflow.VERSION for p in requests)
    assert workflow.validate_goal_audit(fresh_bundle(inputs,goal),goal,inputs=inputs)["accepted"]
    assert (frozen17.VERSION,frozen17.SOURCE_AUDIT_VERSION,frozen17.source_audit,
        frozen17.validate_goal_source_audit,frozen17.validate_goal_audit)==before
    assert frozen17.source_audit is source1 and workflow.source_audit is not source1
    assert byte_hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in old_paths}


@pytest.mark.parametrize("mode",["nonlegal","uncertain","not_covered","contradicts","supported_case_without_evidence"])
def test_source3_native_pragmatic_gate_drives_three_pack_and_author_not_a_usage_status(causal_scenario,mode):
    from tests.test_creative_goal_legal_usage_source_audit_v3 import add_nonlegal_usage,add_uncertain_usage,add_legal_usage,source_usages
    inputs,goal,opening,ids,_=new_case(causal_scenario);audits=fresh_bundle(inputs,goal)
    source=audits["native_source_audit"]
    ref=next(x["source_ref"] for x in source["source_observations"]if x["source_ref"].startswith("G"))
    if mode=="nonlegal":add_nonlegal_usage(source,goal,ref)
    elif mode=="uncertain":add_uncertain_usage(source,goal,ref)
    elif mode=="supported_case_without_evidence":add_legal_usage(source,goal,ref,scope="case_application")
    else:add_legal_usage(source,goal,ref,relation=mode)
    assert all("status"not in row for row in source_usages(source,ref))
    if mode=="nonlegal":
        result=workflow.validate_goal_audit(audits,goal,inputs=inputs)
        assert result["accepted"] and result["source_decision"]["gate_origin"]=="explicit_native_relation_policy"
        assert workflow.prepare_script_request(inputs,profile(),goal,audits,opening_setup=opening,**ids)["views"]["goal"]==goal
    else:
        with pytest.raises((ValueError,ValidationError)):
            workflow.prepare_script_request(inputs,profile(),goal,audits,opening_setup=opening,**ids)


def synthetic_current_setup(goal):
    """Offline mock native shape only; no provider setup or production approval.

    Detail/location choices are intentionally not asserted as semantic truth.
    This constructor never reads/relabels a previous native setup598/589/590.
    """
    return {"schema":setups.VERSION,"goal_sha256":workflow.digest(goal),
        "characters":{row["id"]:deepcopy(row["initial_state"])for row in goal["whole_plan"]["characters"]},
        "props":{row["id"]:{"kind":"absent"}for row in goal["whole_plan"]["props"]}}


def test_actual602_author_context_prepares_only_with_new_v3_offline_audits_and_current_mock_setup():
    if not ACTUAL602.exists():pytest.skip("actual602 source absent")
    inputs=read(ACTUAL602/"INPUTS.json");goal=read(ACTUAL602/"call_602_goal_plan_25.json")["output"]
    before=deepcopy((inputs,goal));opening=synthetic_current_setup(goal)
    audits=fresh_bundle(inputs,goal)
    result=workflow.validate_goal_audit(audits,goal,inputs=inputs)
    assert result["accepted"] and not result["semantic_truth_deterministically_proven"]
    prepared=workflow.prepare_script_request(inputs,profile(),goal,audits,opening_setup=opening,**workflow.origin_ids(inputs))
    actual=final_wire(prepared)
    assert actual["native_goal_document"]==goal and actual["native_opening_setup_document"]==opening
    base=workflow.audit_contexts._base_context(inputs,goal)["payload"]
    assert actual["user_goal_contract"]==base["user_goal_contract"]
    assert actual["verified_legal_context"]==base["verified_legal_context"]
    assert workflow.contexts._reference_occurrences(actual,inputs["reference_fulltext"])==1
    provenance=prepared["request"]["input_provenance"]
    assert provenance["native_source_audit_sha256"]==workflow.digest(audits["native_source_audit"])
    assert provenance["native_drama_audit_sha256"]==workflow.digest(audits["native_drama_audit"])
    assert provenance["native_commitment_audit_sha256"]==workflow.digest(audits["native_commitment_audit"])
    assert provenance["native_goal_audit_bundle_version"]==workflow.BUNDLE_VERSION
    assert (inputs,goal)==before


def test_v18_and_source2_native_schema_admission_are_never_called_in_v19(causal_scenario, monkeypatch):
    from src.content_factory import creative_goal_context_workflow_v18 as frozen18
    from src.content_factory import creative_goal_legal_usage_source_audit_v2 as frozen_source2
    def forbid(*a, **kw): raise AssertionError("old v18/source2 native admission invoked")
    for name in ("prepare_goal_source_audit_request", "build_goal_source_audit_schema", "validate_goal_source_audit", "validate_goal_audit"):
        monkeypatch.setattr(frozen18, name, forbid)
    for name in ("build_source_schema", "validate_source"):
        monkeypatch.setattr(frozen_source2, name, forbid)
    test_new_v3_full_compile_author_body_and_both_review_paths_never_call_v2(causal_scenario, monkeypatch)


def test_only_source_output_allowance_changes_with_explicit_profile(causal_scenario):
    from src.content_factory import creative_goal_context_workflow_v18 as frozen18
    inputs, goal, opening, ids, native = new_case(causal_scenario)
    selected = read(PROJECT / "config/creative_goal_context_model_profile_v5.json")
    before = deepcopy(selected)
    source = workflow.prepare_goal_source_audit_request(inputs, selected, goal)
    assert source["request"]["parameters"]["max_completion_tokens"] == selected["source_strict"]["max_completion_tokens"] == 24000
    assert source["wire"]["max_tokens"] == 24000
    old_source = frozen18.prepare_goal_source_audit_request(inputs, selected, goal)
    assert old_source["wire"]["max_tokens"] == 16000
    assert payload(source) == payload(old_source)
    for method, args in [("prepare_goal_request", (inputs, selected)),
                         ("prepare_goal_drama_audit_request", (inputs, selected, goal)),
                         ("prepare_goal_commitment_audit_request", (inputs, selected, goal)),
                         ("prepare_opening_setup_request", (inputs, selected, goal))]:
        fresh = getattr(workflow, method)(*args)
        prior = getattr(frozen18, method)(*args)
        assert fresh["request"]["parameters"] == prior["request"]["parameters"]
        assert fresh["request"]["structured_schema"] == prior["request"]["structured_schema"]
        assert payload(fresh) == payload(prior)
    authored = workflow.prepare_script_request(inputs, selected, goal, fresh_bundle(inputs, goal), opening_setup=opening, **ids)
    assert authored["wire"]["max_completion_tokens"] == 16000
    for part in ("semantic", "physical"):
        request = workflow.prepare_full_review_part_request(inputs, selected, native, authored["views"], part)
        assert request["wire"]["max_tokens"] == 32000
        old = frozen18.prepare_full_review_part_request(inputs, selected, native, authored["views"], part)
        assert request["request"]["parameters"] == old["request"]["parameters"]
        assert payload(request) == payload(old)
        assert request["request"]["structured_schema"] == old["request"]["structured_schema"]
    assert selected == before


@pytest.mark.parametrize("cap", [16000, 32000, 24000.0, True, None])
def test_source_allowance_drift_does_not_silently_change_this_diagnostic(causal_scenario, cap):
    inputs, goal, _, _, _ = new_case(causal_scenario)
    selected = profile(); selected["source_strict"] = {"max_completion_tokens": cap}
    with pytest.raises(ValueError, match="24000"):
        workflow.prepare_goal_source_audit_request(inputs, selected, goal)


def test_actual604_compact_schema_has_one_scan_definition_and_full_three_sha_context():
    from src.content_factory.creative_deepseek_strict_schema_v1 import compile_source_schema_with_manifest
    from scripts.creative_deepseek_strict_role_clients_v2 import schema_compilation_manifest
    root = PROJECT / "data/production_trials/goal_context_text_production_20261013"
    paths = [root / "round_18" / "INPUTS.json", root / "round_18" / "call_604_goal_plan_26.json",
             root / "round_19" / "call_606_goal_source_audit_00.json",
             root / "round_19" / "INITIAL_STRICT_SCHEMA_COMPILATION_MANIFEST.json"]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    inputs, goal = read(paths[0]), read(paths[1])["output"]
    selected = read(PROJECT / "config/creative_goal_context_model_profile_v5.json")
    source = workflow.prepare_goal_source_audit_request(inputs, selected, goal)
    actual = final_wire(source)
    assert workflow.evidence_view.reconstruct_goal(actual["native_goal_evidence_view"], expected_native_goal_sha256=workflow.digest(goal)) == goal
    schema = source["request"]["structured_schema"]
    refs = schema["$defs"]["source_observation"]["properties"]["source_ref"]["enum"]
    assert set(refs) == set(actual["native_goal_evidence_view"]["evidence_catalog"])
    assert schema["properties"]["source_observations"]["minItems"] == schema["properties"]["source_observations"]["maxItems"] == len(refs)
    assert schema["properties"]["goal_sha256"]["const"] == workflow.digest(goal)
    assert schema["properties"]["audit_context_sha256"]["const"] == workflow.digest(actual)
    assert schema["properties"]["authority_context_sha256"]["const"] == workflow.digest(source["source_authority_context"])
    service, compiled_manifest = compile_source_schema_with_manifest(schema)
    size = len(json.dumps(service, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))
    old = read(paths[3])
    assert old["service_schema_bytes"] == 402758
    assert size < 40000 and size < old["service_schema_bytes"] / 10
    actual_manifest = schema_compilation_manifest(source["request"])
    assert actual_manifest["service_schema_bytes"] == size
    assert actual_manifest["expected_wire_bytes"] < 150000
    assert actual_manifest["original_contract_sha256"] == workflow.digest(schema)
    assert actual_manifest["service_schema_sha256"] == compiled_manifest["service_schema_sha256"]
    assert actual_manifest["original_local_contract_validation_required"]
    assert not actual_manifest["semantic_gate_changed"] and not actual_manifest["server_schema_guarantee"]
    # The606 length receipt is original evidence, never a partial report seed.
    truncated = read(paths[2])
    assert truncated["status"] == "interface_rejected" and truncated["response_metadata"]["finish_reason"] == "length"
    assert truncated["response_metadata"]["total_tokens"] == 181138 and "output" not in truncated
    with pytest.raises((ValueError, ValidationError)):
        workflow.validate_goal_source_audit(truncated.get("output"), goal, context_sha256=source["source_context_sha256"], authority_context=source["source_authority_context"])
    assert before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def test_native_source3_finding_and_unknown_enter_complete_goal_revision_verbatim(causal_scenario, tmp_path):
    from tests.test_creative_goal_legal_usage_source_audit_v3 import add_legal_usage
    inputs, goal, _, _, _ = new_case(causal_scenario)
    bundle = fresh_bundle(inputs, goal)
    source = bundle["native_source_audit"]
    refs = [row["source_ref"] for row in source["source_observations"] if row["source_ref"].startswith("G")]
    add_legal_usage(source, goal, refs[0], relation="contradicts")
    add_legal_usage(source, goal, refs[1], relation="not_covered")
    decision = workflow.validate_goal_audit(bundle, goal, inputs=inputs)
    source_decision = decision["source_decision"]
    assert not decision["accepted"]
    diagnostics = {"complete_same_source_goal_audits": [source_decision, decision["drama_decision"], decision["commitment_decision"]]}
    evidence = tmp_path / "source3_original_diagnostics.json"
    evidence.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
    raw_before = evidence.read_bytes()
    revision = {**inputs, "previous_complete_document": deepcopy(goal), "revision_diagnostics": diagnostics,
                "goal_revision_feedback_evidence_path": str(evidence)}
    before = deepcopy(revision)
    prepared = workflow.prepare_goal_request(revision, profile())
    actual = final_wire(prepared)
    retained = actual["revision_diagnostics"]["complete_same_source_goal_audits"][0]
    for table in ("findings", "uncertainties"):
        assert retained[table] == source_decision[table]
    for table in workflow.SOURCE3_COMPILED_FEEDBACK_TABLES:
        reference = retained[table]
        assert reference["original_value_sha256"] == workflow.digest(source_decision[table])
        assert reference["original_diagnostics_sha256"] == workflow.digest(diagnostics)
        assert workflow.feedback._resolve_pointer(diagnostics, reference["original_json_pointer"]) == source_decision[table]
    for table, gate in (("findings", "fail"), ("uncertainties", "unknown")):
        finding = retained[table][0]
        assert finding["table"] == "source_observations" and finding["gate"] == gate
        assert finding["source_ref"] in refs and type(finding["source_observation_index"]) is int
        assert finding["native_usage"] and finding["evidence"]["source_ref"] == finding["source_ref"]
        assert finding["reason"] == finding["native_usage"]["reason"]
        assert finding["required_revision"] == finding["native_usage"]["required_revision"]
    assert actual["previous_complete_document"] == goal
    assert actual["verified_legal_context"] == workflow.audit_contexts._base_context(inputs, goal)["payload"]["verified_legal_context"]
    assert prepared["manifest"]["revision_feedback_projection"]["original_artifact"]["local_json_verified"]
    assert prepared["request"]["input_provenance"]["workflow_version"] == workflow.VERSION
    assert revision == before and evidence.read_bytes() == raw_before


def test_actual604_author_reads_full_goal_after_three_new_shape_only_native_audits():
    root = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_18"
    inputs, goal = read(root / "INPUTS.json"), read(root / "call_604_goal_plan_26.json")["output"]
    before = deepcopy((inputs, goal))
    audits = fresh_bundle(inputs, goal)
    decision = workflow.validate_goal_audit(audits, goal, inputs=inputs)
    assert decision["accepted"] and not decision["semantic_truth_deterministically_proven"]
    assert audits["native_source_audit"]["schema"] == "creative_goal_legal_usage_source_audit/v3"
    opening = synthetic_current_setup(goal)
    prepared = workflow.prepare_script_request(inputs, profile(), goal, audits, opening_setup=opening, **workflow.origin_ids(inputs))
    actual = final_wire(prepared)
    assert actual["native_goal_document"] == goal and actual["native_opening_setup_document"] == opening
    original = workflow.audit_contexts._base_context(inputs, goal)["payload"]
    assert actual["verified_legal_context"] == original["verified_legal_context"]
    assert actual["user_goal_contract"] == original["user_goal_contract"]
    assert workflow.contexts._reference_occurrences(actual, inputs["reference_fulltext"]) == 1
    provenance = prepared["request"]["input_provenance"]
    for kind in ("source", "drama", "commitment"):
        assert provenance["native_" + kind + "_audit_sha256"] == workflow.digest(audits["native_" + kind + "_audit"])
    assert (inputs, goal) == before


def test_actual604_dense_source3_feedback_fits_without_omitting_native_findings_or_full_goal(tmp_path):
    from tests.test_creative_goal_legal_usage_source_audit_v3 import add_nonlegal_usage, add_legal_usage, source_usages
    root = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_18"
    inputs, goal = read(root / "INPUTS.json"), read(root / "call_604_goal_plan_26.json")["output"]
    bundle = fresh_bundle(inputs, goal)
    native = bundle["native_source_audit"]
    for observation in native["source_observations"]:
        if not observation["usages"]:
            add_nonlegal_usage(native, goal, observation["source_ref"])
    ref = next(row["source_ref"] for row in native["source_observations"] if row["source_ref"].startswith("G"))
    source_usages(native, ref).clear(); add_legal_usage(native, goal, ref, relation="contradicts")
    decision = workflow.validate_goal_audit(bundle, goal, inputs=inputs)
    diagnostics = {"complete_same_source_goal_audits": [decision["source_decision"], decision["drama_decision"], decision["commitment_decision"]]}
    assert workflow.contexts._measure(diagnostics)["characters"] > 100000
    evidence = tmp_path / "source3_dense_original_diagnostics.json"
    evidence.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
    raw_before = evidence.read_bytes()
    revision = {**inputs, "previous_complete_document": goal, "revision_diagnostics": diagnostics}
    with pytest.raises(workflow.contexts.ContextError, match="exceeds explicit safety budget"):
        workflow.prior.prepare_goal_request(revision, profile())
    prepared = workflow.prepare_goal_request({**revision, "goal_revision_feedback_evidence_path": str(evidence)}, profile())
    actual = final_wire(prepared)
    source = actual["revision_diagnostics"]["complete_same_source_goal_audits"][0]
    assert source["findings"] == decision["source_decision"]["findings"]
    assert source["uncertainties"] == decision["source_decision"]["uncertainties"]
    assert actual["previous_complete_document"] == goal and actual["reference_fulltext"] == inputs["reference_fulltext"]
    manifest = prepared["manifest"]["revision_feedback_projection"]
    assert len(manifest["source3_compiled_tables_externalized"]) == 2
    assert prepared["manifest"]["payload_identity"]["characters"] < 100000
    for table in workflow.SOURCE3_COMPILED_FEEDBACK_TABLES:
        reference = source[table]
        assert reference["local_path"] == str(evidence.resolve()) and not reference["local_binding_pending"]
        original = workflow.feedback._resolve_pointer(diagnostics, reference["original_json_pointer"])
        assert reference["original_value_sha256"] == workflow.digest(original)
    assert evidence.read_bytes() == raw_before


@pytest.mark.parametrize("fault", ["schema", "goal", "context", "authority", "audit_sha", "extra_field", "missing_source_ref", "unmatched_failed_gate"])
def test_unrecognized_cross_source_or_incomplete_feedback_keeps_new_compiled_tables(causal_scenario, fault):
    from tests.test_creative_goal_legal_usage_source_audit_v3 import add_legal_usage
    inputs, goal, _, _, _ = new_case(causal_scenario)
    bundle = fresh_bundle(inputs, goal)
    ref = next(row["source_ref"] for row in bundle["native_source_audit"]["source_observations"] if row["source_ref"].startswith("G"))
    add_legal_usage(bundle["native_source_audit"], goal, ref, relation="contradicts")
    source = workflow.validate_goal_audit(bundle, goal, inputs=inputs)["source_decision"]
    if fault == "schema": source["schema"] = "unrecognized/decision"
    elif fault in ("goal", "context", "authority"):
        key = {"goal": "native_goal_sha256", "context": "audit_context_sha256", "authority": "authority_context_sha256"}[fault]
        source[key] = "0" * 64
    elif fault == "audit_sha": source["audit_sha256"] = "invalid"
    elif fault == "extra_field": source["future_unknown_field"] = {"error": "retain original"}
    elif fault == "missing_source_ref": source["legal_usage_citations"].pop(ref)
    else: source["findings"] = []; source["accepted"] = True
    diagnostics = {"complete_same_source_goal_audits": [source]}
    original = deepcopy(diagnostics)
    projected = workflow._project_goal_revision_feedback(diagnostics, inputs=inputs, native_goal=goal)
    retained = projected["projected_diagnostics"]["complete_same_source_goal_audits"][0]
    for table in workflow.SOURCE3_COMPILED_FEEDBACK_TABLES + ("findings", "uncertainties"):
        assert retained[table] == source[table]
    assert projected["projection_manifest"]["source3_compiled_tables_externalized"] == []
    assert diagnostics == original


def test_source3_unknown_compiled_citation_field_is_retained(causal_scenario):
    inputs, goal, _, _, _ = new_case(causal_scenario)
    source = workflow.validate_goal_audit(fresh_bundle(inputs, goal), goal, inputs=inputs)["source_decision"]
    ref = next(key for key, rows in source["legal_usage_citations"].items() if rows)
    source["legal_usage_citations"][ref][0]["unknown_new_field"] = "Unknown compiler evidence remains original"
    diagnostics = {"complete_same_source_goal_audits": [source]}
    projected = workflow._project_goal_revision_feedback(diagnostics, inputs=inputs, native_goal=goal)
    assert projected["projected_diagnostics"]["complete_same_source_goal_audits"][0]["legal_usage_citations"] == source["legal_usage_citations"]
