"""Independent v12 coordinator and new native drama gate; fake service only."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from jsonschema import ValidationError

from scripts import run_goal_context_text_production_v12 as runner
from scripts import creative_goal_context_dispatch_v6 as adapter
from scripts import creative_bounded_format_role_clients_v1 as bounded
from scripts import creative_evidenced_role_clients_v1 as evidenced
from tests import test_goal_context_text_production_v4 as helpers
from tests.test_creative_split_full_review_contract_v2 import synthetic_consistency
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario

INHERITED={"calls_started":567,"reported_tokens":10983919,"calls_with_known_usage":565,
    "pending_ordinals":[70,160],"unknown_token_reservations":93117}
PRIOR_GUARD = runner.prior_guard
PREPARE = runner.prepare

@pytest.fixture(autouse=True)
def no_provider_or_old_guard(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("independent v12 coordinator may not contact provider or old runtime")
    monkeypatch.setattr(socket.socket,"connect",deny)
    monkeypatch.setattr(socket.socket,"connect_ex",deny)
    monkeypatch.setattr(socket,"create_connection",deny)
    monkeypatch.setattr(runner.previous,"get_runtime",deny)
    monkeypatch.setattr(runner,"prior_guard",deny)

def phase(request):
    provenance = request["input_provenance"]
    if provenance.get("substage") == "opening_setup":
        return "opening_setup"
    if request["stage"] == "goal_audit":
        return "source" if "claim_checks" in request["structured_schema"]["properties"] else "drama"
    return provenance.get("review_part", request["stage"])


def replay(tmp_path, monkeypatch, causal_scenario, modes=None):
    inputs, profile, goal, opening, bundle, ids, native = deepcopy(causal_scenario)
    profile = runner.read(runner.PROFILE)
    project, root = tmp_path / "synthetic_project", tmp_path / "synthetic_project/run"
    project.mkdir()
    source = project / "source.txt"
    source.write_text("仅独立离线来源", encoding="utf-8")
    profile_path = project / "profile.json"
    profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(runner, "PROJECT", project)
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "PROFILE", profile_path)
    sends, counts = [], {}
    modes = modes or {}

    def factory(request):
        current = phase(request)
        counts[current] = counts.get(current, 0) + 1
        mode = modes.get((current, counts[current]), "valid")

        class Fake:
            def call(self, role, messages, *, max_tokens, temperature, thinking, structured_schema, evidence):
                sends.append(deepcopy(request))
                assert runner.read(runtime.ledger)["calls"][-1]["ordinal"] == evidence.identity["ordinal"]
                with sqlite3.connect(root / "TASKS.sqlite3") as db:
                    assert db.execute("SELECT COUNT(*) FROM attempts WHERE status='claimed'").fetchone()[0] == 1
                bounded.save_request_body(evidence, json.dumps(runner.clients.expected_wire_request(request), ensure_ascii=False).encode(), role=role)
                if mode == "transport_unknown":
                    raise evidenced.EvidenceCallError("TRANSPORT_EXCEPTION", started=True, outcome_known=False)
                body = json.loads(messages[1]["content"])
                if current in ("goal_plan", "drama"):
                    assert body["stage_responsibility_contract"] == runner.workflow.STAGE_RESPONSIBILITY_CONTRACT
                if current == "goal_plan":
                    value = deepcopy(goal)
                    value["whole_plan"]["premise"] = "合成新原生整片规划" + str(counts[current])
                    if mode == "contract_fail":
                        value["whole_plan"].pop("ending")
                elif current in ("source", "drama"):
                    value = deepcopy(bundle["native_" + current + "_audit"])
                    for field in ("goal_sha256", "audit_context_sha256"):
                        value[field] = structured_schema["properties"][field]["const"]
                    value["schema"] = structured_schema["properties"]["schema"]["const"]
                    if current == "drama":
                        current_goal = body["native_goal_document"]
                        value["scope_observations"] = {row["id"]: {"audible_speakers": [], "operated_props": []}
                            for row in current_goal["whole_plan"]["beats"]}
                        reference = next(iter(runner.drama_contract.citations.build_evidence_catalog(current_goal)))
                        judgment = {"status": "pass", "reason": "合成原生承诺检查，不证明中文语义或创作质量。",
                            "required_revision": "", "counterevidence_refs": [],
                            "counterexample_analysis": "合成逐项比较承诺与使用拍，测试同源覆盖。"}
                        value["commitment_checks"] = {identifier: {**deepcopy(judgment),
                            "claim_ref": usage["claim_ref"], "evidence_refs": [usage["claim_ref"], reference],
                            "checked_usages": {key: deepcopy(item["evidence_refs"])
                                for key, item in usage["usages"].items()}}
                            for identifier, usage in runner.drama_contract.build_commitment_usage_catalog(current_goal).items()}
                        if mode in ("commitment_fail", "commitment_unknown"):
                            row = next(iter(value["commitment_checks"].values()))
                            row.update(status="fail" if mode == "commitment_fail" else "unknown",
                                required_revision="提交完整新原生整片规划。" if mode == "commitment_fail" else "")
                        elif mode == "missing_commitments":
                            value.pop("commitment_checks")
                    if mode in ("fail", "unknown", "scope_fail", "null_scope_pass", "legacy_schema"):
                        row = next(iter(value["claim_checks"].values())) if current == "source" else value["goal_checks"]["closed_production_scope"]
                        if mode in ("fail", "unknown", "scope_fail"):
                            row.update(status="fail" if mode == "scope_fail" else mode,
                                required_revision="Complete new native whole plan" if mode != "unknown" else "")
                        if mode in ("scope_fail", "null_scope_pass"):
                            scopes = runner.drama_contract.build_production_scope_catalog(current_goal)
                            bid = next(iter(scopes["beat_scopes"]))
                            ref = scopes["beat_scopes"][bid]["evidence_refs"][0]
                            quote = runner.drama_contract.citations.build_evidence_catalog(current_goal)[ref]["quote"]
                            value["scope_observations"][bid]["audible_speakers"] = [{"source_ref": ref,"quote":quote,"declared_character_id":None}]
                        if mode == "legacy_schema":
                            value["schema"] = "creative_goal_context_workflow/v7/drama_audit"
                elif current == "opening_setup":
                    value = deepcopy(opening)
                    value["goal_sha256"] = body["native_goal_sha256"]
                    if mode == "contract_fail":
                        value["props"].pop("pen")
                elif current == "complete_script":
                    value = deepcopy(native)
                    value["title"] = "合成完整正文" + str(counts[current])
                    if mode == "contract_fail":
                        value.pop("premise")
                else:
                    assert current in ("semantic", "physical")
                    views = runner.workflow.compile_native_views(body["native_goal_document"], body["native_opening_setup_document"], **ids)
                    compiled = runner.legacy.contract.compile_script(body["native_script_document"], views["brief"])
                    legal = runner.workflow.prepare_full_review_part_request(inputs, profile, body["native_script_document"], views, current)["review_legal_context"]
                    # Private synthetic response construction only. Compiler
                    # duplicates are not inserted into the actual wire body.
                    local_payload = {"full_current_script": compiled, "brief": views["brief"],
                        "creative_scene_plan": views["plan"], "native_goal_document": views["goal"],
                        "verified_legal_context": legal}
                    synthetic_full = helpers.full_review(local_payload)
                    synthetic_full.update(opening_setup_sha256=runner.digest(views["opening_setup"]))
                    if current == "semantic":
                        synthetic_full.update(synthetic_consistency(compiled, views["brief"], views["plan"],
                            goal_contract=views["goal"]))
                    value = {key: deepcopy(synthetic_full[key]) for key in structured_schema["properties"] if key in synthetic_full}
                    for key in ("schema", "part", "context_sha256"):
                        value[key] = structured_schema["properties"][key]["const"]
                    if "revision_target" in structured_schema["properties"]:
                        value["revision_target"] = "none"
                    if mode in ("fail", "unknown", "plan_fail"):
                        table = "goal_checks" if current == "semantic" else "action_checks"
                        next(iter(value[table].values())).update(status="fail" if mode == "plan_fail" else mode,
                            required_revision="提交完整新原生规划。" if mode == "plan_fail" else "完整新稿修复功能缺口。" if mode == "fail" else "")
                        if "revision_target" in value and mode != "unknown":
                            value["revision_target"] = "plan" if mode == "plan_fail" else "script"
                    elif mode == "extra_zero_table":
                        value["plan_support"] = {}
                    elif mode == "mixed_script":
                        value["script_sha256"] = "c" * 64
                    elif mode == "missing_semantic_table":
                        value.pop("dialogue_role_checks")
                    elif mode in ("role_fail", "intent_fail"):
                        row = next(iter(value["dialogue_role_checks" if mode == "role_fail" else "beat_intent_checks"].values()))
                        child = row["checks"]["purpose_alignment"] if mode == "role_fail" else next(iter(row["target_checks"].values()))
                        for item in (row, child):
                            item.update(status="fail", required_revision="模型必须提交完整新正文兑现当前目标。")
                        value["revision_target"] = "script"
                message = {"role": "assistant", "content": None, "tool_calls": [{"id": "offline",
                    "type": "function", "function": {"name": runner.clients.TOOL_NAME, "arguments": json.dumps(value, ensure_ascii=False)}}]}
                response = {"id": "offline-" + str(evidence.identity["ordinal"]), "model": request["model"],
                    "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls"}],
                    "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}}
                if mode == "usage_unknown":
                    response.pop("usage")
                elif mode == "truncated":
                    response["choices"][0]["finish_reason"] = "length"
                saved, manifest = evidence.save_body(json.dumps(response, ensure_ascii=False).encode(), evidenced.http_metadata(200, {}))
                return evidenced.parse_saved_response(saved, manifest, role, request["model"], thinking, structured_schema, evidence)
        return lambda: Fake()

    runtime = adapter.GoalContextRuntime(project, root, [source], deepcopy(INHERITED), profile=profile,
        stage_limits={"goal_plan": 4, "goal_audit": 4, "complete_script": 3, "full_review": 6},
        client_factory_builder=factory, quota_state=None)
    runtime.prepare()
    runner.write(root / "INPUTS.json", inputs, True)
    runner.write(root / "USER_SCOPE.json", {"stage_limits": runtime.stage_limits}, True)
    runner.write(root / "INHERITED_NATIVE_GOAL.json", goal, True)
    runner.write(root / "INHERITED_DIAGNOSTICS.json", {"independent_failure_quotes": "合成失败机制，不含旧整篇剧情"}, True)
    prepared = runner.workflow.prepare_goal_request(runner.revision_planning_inputs(inputs, goal,
        runner.read(root / "INHERITED_DIAGNOSTICS.json")), profile)
    runner.write(root / "FIRST_GOAL_REQUEST_PREVIEW.json", prepared, True)
    monkeypatch.setattr(runner, "get_runtime", lambda: runtime)
    return runtime, root, sends


def phases(sends):
    return [phase(request) for request in sends]


def assert_no_handoff_or_reentry(runtime, root, sends, expected):
    assert phases(sends)==expected
    assert not (root/"TEXT_HANDOFF.json").exists()
    before=runtime.ledger.read_bytes()
    with pytest.raises(FileExistsError):
        runner.run()
    assert runtime.ledger.read_bytes()==before and phases(sends)==expected
    assert not runtime.summary()["old_budget_reset"]


def test_new_native_drama_bundle_handoff_preview_and_inherited_history_are_exact(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends=replay(tmp_path,monkeypatch,causal_scenario)
    seed=runner.read(root/"INHERITED_NATIVE_GOAL.json")
    preview=runner.read(root/"FIRST_GOAL_REQUEST_PREVIEW.json")
    result=runner.run()
    assert result["status"]=="text_ready_for_director",result
    assert sends[0]==preview["request"]
    assert json.loads(sends[0]["messages"][1]["content"])["previous_complete_document"]==seed
    assert phases(sends)==["goal_plan","source","drama","opening_setup","complete_script","semantic","physical"]
    assert sends[2]["structured_schema"]["properties"]["schema"]["const"]==runner.drama_contract.DRAMA_AUDIT_VERSION
    handoff=runner.read(root/"TEXT_HANDOFF.json")
    audits=handoff["native_goal_audit"]
    assert audits["schema"]==runner.drama_contract.BUNDLE_VERSION
    assert audits["native_drama_audit"]==runner.read(root/"goals/drama_native_audit_01.json")
    assert audits["native_source_audit"]==runner.read(root/"goals/source_native_audit_01.json")
    assert not handoff["media_authorized"] and not handoff["production_dispatch_eligible"]
    spend=runtime.summary()
    assert spend["effective_calls_started"]==574 and spend["effective_reported_tokens"]==10984619
    assert spend["effective_calls_with_known_usage"]==572 and spend["historical_pending_ordinals"]==[70,160]
    assert spend["unknown_token_reservations"]==93117 and not spend["old_budget_reset"]
    assert result["inherited_goal_candidates_used"]==15 and result["cumulative_goal_candidates_used"]==16
    assert runner.read(runtime.ledger)["starting_spend"]==INHERITED
    for path in (root/"requests").glob("*.json"):
        prepared=runner.read(path)
        assert prepared["request"]["input_provenance"]["context_manifest_sha256"]==runner.digest(prepared["manifest"])
        assert prepared["wire"]==runner.clients.expected_wire_request(prepared["request"])
        assert prepared["request_sha256"]==runner.digest(prepared["request"])
    # Old contracts stay distinct; current author recomputes the actual new
    # commitment context rather than accepting old all-pass audit headers.
    from src.content_factory import creative_goal_context_workflow_v10 as frozen
    inputs,profile=runner.read(root/"INPUTS.json"),runner.read(runner.PROFILE)
    stale=deepcopy(audits)
    old=frozen.prepare_goal_drama_audit_request(inputs,profile,handoff["native_goal"])
    old_source=frozen.prepare_goal_source_audit_request(inputs,profile,handoff["native_goal"])
    assert sends[1]["structured_schema"]==old_source["request"]["structured_schema"]
    drama_schema=sends[2]["structured_schema"]
    assert drama_schema["properties"]["schema"]["const"] == "creative_goal_drama_audit/v9"
    assert "commitment_checks" in drama_schema["required"]
    assert "commitment_checks" not in old["request"]["structured_schema"]["properties"]
    goal_catalog=runner.drama_contract.build_evidence_catalog(handoff["native_goal"])
    finite_refs=sends[2]["structured_schema"]["$defs"]["evidence_refs"]
    assert finite_refs["items"]["enum"]==list(goal_catalog)
    assert finite_refs["maxItems"]==len(goal_catalog)
    assert any(ref.startswith("C:") for ref in finite_refs["items"]["enum"])
    assert set(audits["native_drama_audit"]["commitment_checks"]) == set(
        runner.drama_contract.build_commitment_usage_catalog(handoff["native_goal"]))
    assert sends[2]["parameters"]["max_completion_tokens"] == 16000
    for request in sends[-2:]:
        assert request["structured_schema"]["properties"]["schema"]["const"] == "creative_split_full_review_part/v2"
        assert request["parameters"]["max_completion_tokens"] == 32000
        assert runner.clients.expected_wire_request(request)["thinking"] == {"type": "disabled"}
    assert {"beat_intent_checks", "dialogue_role_checks"} <= set(sends[-2]["structured_schema"]["required"])
    assert not {"beat_intent_checks", "dialogue_role_checks"} & set(sends[-1]["structured_schema"]["properties"])
    assert result["old_director_capacity"] == {"used": 7, "limit": 7, "remaining": 0}
    assert not result["human_quality_approved"] and not result["creative_quality_passed"]
    for prepared in (runner.read(root/"requests/goal_plan_16.json"),
        runner.read(root/"requests/goal_drama_audit_01.json")):
        body=json.loads(prepared["request"]["messages"][1]["content"])
        assert body["reference_fulltext"]==inputs["reference_fulltext"]
        proof=prepared["manifest"].get("reference_proof")
        occurrences=proof["payload_occurrences"] if proof is not None else prepared["manifest"]["reference_occurrences"]
        assert occurrences==1
    old_context=old["request"]["structured_schema"]["properties"]["audit_context_sha256"]["const"]
    assert old_context!=stale["native_drama_audit"]["audit_context_sha256"]
    stale["native_drama_audit"]["audit_context_sha256"]=old_context
    with pytest.raises(ValidationError):
        runner.workflow.prepare_script_request(inputs,profile,handoff["native_goal"],stale,
            opening_setup=handoff["native_opening_setup"],**runner.workflow.origin_ids(inputs))
    before=runtime.ledger.read_bytes()
    with pytest.raises(FileExistsError): runner.run()
    assert runtime.ledger.read_bytes()==before and len(sends)==7


def test_unknown_at_native_audit_or_full_part_never_dispatches_later_stage_or_restarts(tmp_path,monkeypatch,causal_scenario):
    for index,(part,mode) in enumerate((("drama","unknown"),("drama","transport_unknown"),("semantic","unknown"))):
        case=tmp_path/str(index)
        case.mkdir()
        runtime,root,sends=replay(case,monkeypatch,causal_scenario,{(part,1):mode})
        result=runner.run()
        assert result["status"] in {"halt_goal_audit_uncertain","halt_goal_audit_interface_or_unknown",
            "halt_full_review_uncertain","halt_review_interface_or_unknown"},result
        expected=["goal_plan","source","drama","opening_setup","complete_script","semantic","physical"]
        expected=expected[:expected.index(part)+1]
        assert_no_handoff_or_reentry(runtime,root,sends,expected)
        assert not (root/"scripts/version_02").exists()
        if mode=="transport_unknown":
            assert len(runner.read(runtime.ledger)["calls"])==3
            assert runner.read(runtime.ledger)["calls"][-1]["ordinal"]==570


@pytest.mark.parametrize("mode",["null_scope_pass"])
def test_known_malformed_drama_response_stops_without_converting567_or_dispatching_setup(tmp_path,monkeypatch,causal_scenario,mode):
    runtime,root,sends=replay(tmp_path,monkeypatch,causal_scenario,{("drama",1):mode})
    result=runner.run()
    assert result["status"]=="halt_goal_audit_contract_requires_pipeline_diagnosis",result
    assert_no_handoff_or_reentry(runtime,root,sends,["goal_plan","source","drama"])
    assert not (root/"setups").exists() and not (root/"goals/native_02.json").exists()


def test_complete_native_scope_failure_revises_entire_goal_and_reaudits_before_author(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends=replay(tmp_path,monkeypatch,causal_scenario,{("drama",1):"scope_fail"})
    result=runner.run()
    assert result["status"]=="text_ready_for_director",result
    assert phases(sends)==["goal_plan","source","drama","goal_plan","source","drama","opening_setup","complete_script","semantic","physical"]
    first=runner.read(root/"goals/native_01.json")
    second=runner.read(root/"goals/native_02.json")
    repaired=json.loads(sends[3]["messages"][1]["content"])
    assert repaired["previous_complete_document"]==first and first!=second
    assert repaired["revision_diagnostics"]["complete_same_source_goal_audits"][1]["accepted"] is False
    assert runner.read(root/"TEXT_HANDOFF.json")["native_goal"]==second
    assert result["cumulative_goal_candidates_used"]==17 and result["inherited_goal_candidates_used"]==15
    assert runtime.summary()["effective_calls_started"]==577 and not runtime.summary()["old_budget_reset"]


def test_frozen_first_preview_mismatch_stops_before_any_provider_claim(tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends=replay(tmp_path,monkeypatch,causal_scenario)
    preview=runner.read(root/"FIRST_GOAL_REQUEST_PREVIEW.json")
    preview["request_sha256"]="f"*64
    (root/"FIRST_GOAL_REQUEST_PREVIEW.json").write_text(json.dumps(preview,ensure_ascii=False),encoding="utf-8")
    with pytest.raises(ValueError,match="exact preview"):
        runner.run()
    assert sends==[] and runner.read(runtime.ledger)["calls"]==[]
    with pytest.raises(FileExistsError): runner.run()
    assert sends==[]


@pytest.mark.parametrize("mode,status", [
    ("commitment_unknown", "halt_goal_audit_uncertain"),
    ("missing_commitments", "halt_goal_audit_contract_requires_pipeline_diagnosis"),
    ("legacy_schema", "halt_goal_audit_contract_requires_pipeline_diagnosis"),
])
def test_new_drama_claim_gate_blocks_setup_for_uncertain_missing_or_old_native_contract(
        tmp_path, monkeypatch, causal_scenario, mode, status):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario, {("drama", 1): mode})
    result = runner.run()
    assert result["status"] == status, result
    assert_no_handoff_or_reentry(runtime, root, sends, ["goal_plan", "source", "drama"])
    assert not (root / "setups").exists()
    assert result["cumulative_goal_candidates_used"] == 16


@pytest.mark.parametrize("mode", ["transport_unknown", "usage_unknown", "truncated"])
@pytest.mark.parametrize("part", ["goal_plan", "opening_setup", "semantic", "physical"])
def test_unknown_or_incomplete_result_stops_original_identity_without_repair(
        tmp_path, monkeypatch, causal_scenario, part, mode):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario, {(part, 1): mode})
    result = runner.run()
    expected_status = {"goal_plan": "halt_goal_interface_or_unknown",
        "opening_setup": "halt_opening_setup_interface_or_unknown",
        "semantic": "halt_review_interface_or_unknown", "physical": "halt_review_interface_or_unknown"}
    assert result["status"] == expected_status[part], result
    stages = ["goal_plan", "source", "drama", "opening_setup", "complete_script", "semantic", "physical"]
    assert_no_handoff_or_reentry(runtime, root, sends, stages[:stages.index(part) + 1])
    ledger = runner.read(runtime.ledger)
    assert [row["ordinal"] for row in ledger["calls"]] == list(range(568, 568 + len(sends)))
    assert not (root / "goals/native_02.json").exists()
    assert not (root / "scripts/version_02").exists()
    assert ledger["starting_spend"] == INHERITED


@pytest.mark.parametrize("mode", ["missing_semantic_table", "mixed_script", "extra_zero_table"])
def test_native_full_review_contract_failure_stops_instead_of_converting_or_revising_body(
        tmp_path, monkeypatch, causal_scenario, mode):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario, {("semantic", 1): mode})
    result = runner.run()
    assert result["status"] == "halt_full_review_contract_requires_pipeline_diagnosis", result
    assert_no_handoff_or_reentry(runtime, root, sends,
        ["goal_plan", "source", "drama", "opening_setup", "complete_script", "semantic"])
    assert not (root / "scripts/version_02").exists()


@pytest.mark.parametrize("mode", ["role_fail", "intent_fail"])
def test_complete_new_semantic_failure_revises_whole_native_body_and_reaudits_both_parts(
        tmp_path, monkeypatch, causal_scenario, mode):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario, {("semantic", 1): mode})
    result = runner.run()
    assert result["status"] == "text_ready_for_director", result
    assert phases(sends) == ["goal_plan", "source", "drama", "opening_setup", "complete_script", "semantic",
        "complete_script", "semantic", "physical"]
    first = runner.read(root / "scripts/version_01/NATIVE_SCRIPT.json")
    second = runner.read(root / "scripts/version_02/NATIVE_SCRIPT.json")
    repaired = json.loads(sends[6]["messages"][1]["content"])
    assert repaired["previous_complete_document"] == first and first != second
    native_reviews = repaired["revision_diagnostics"]["native_part_reviews"]
    assert native_reviews["semantic"] == runner.read(root / "scripts/version_01/NATIVE_SEMANTIC_REVIEW.json")
    assert "physical" not in native_reviews
    assert runner.read(root / "TEXT_HANDOFF.json")["native_script"] == second
    assert result["cumulative_goal_candidates_used"] == 16
    assert not result["human_quality_approved"] and not result["creative_quality_passed"]


def test_two_new_goals_two_native_setups_three_bodies_and_six_full_parts_are_all_bounded(
        tmp_path, monkeypatch, causal_scenario):
    modes = {("drama", 1): "commitment_fail", ("opening_setup", 1): "contract_fail",
        ("physical", 1): "fail", ("physical", 2): "fail"}
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario, modes)
    result = runner.run()
    assert result["status"] == "text_ready_for_director", result
    assert phases(sends) == ["goal_plan", "source", "drama", "goal_plan", "source", "drama",
        "opening_setup", "opening_setup", "complete_script", "semantic", "physical",
        "complete_script", "semantic", "physical", "complete_script", "semantic", "physical"]
    assert runtime.summary()["stage_calls"] == {"goal_plan": 4, "goal_audit": 4, "complete_script": 3, "full_review": 6}
    assert result["inherited_goal_candidates_used"] == 15 and result["cumulative_goal_candidates_used"] == 17
    assert result["opening_setup_calls"] == 2
    assert runtime.summary()["effective_calls_started"] == 584
    assert runtime.summary()["effective_reported_tokens"] == 10985619
    assert result["old_director_capacity"] == {"used": 7, "limit": 7, "remaining": 0}
    assert not (root / "goals/native_03.json").exists()
    assert not (root / "setups/native_03.json").exists()
    assert not (root / "scripts/version_04").exists()
    led = runner.read(runtime.ledger)
    assert [row["label"] for row in led["calls"] if row["label"].startswith("goal_plan_")] == ["goal_plan_16", "goal_plan_17"]


@pytest.mark.parametrize("phase_name,status,expected", [
    ("goal_plan", "halt_goal_content_capacity_exhausted", ["goal_plan", "goal_plan"]),
    ("opening_setup", "halt_opening_setup_content_capacity_exhausted", ["goal_plan", "source", "drama", "opening_setup", "opening_setup"]),
    ("complete_script", "halt_script_content_capacity_exhausted", ["goal_plan", "source", "drama", "opening_setup", "complete_script", "complete_script", "complete_script"]),
])
def test_known_complete_contract_failure_uses_only_local_bounded_full_document_revisions(
        tmp_path, monkeypatch, causal_scenario, phase_name, status, expected):
    maximum = 3 if phase_name == "complete_script" else 2
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario,
        {(phase_name, i): "contract_fail" for i in range(1, maximum + 1)})
    result = runner.run()
    assert result["status"] == status, result
    assert_no_handoff_or_reentry(runtime, root, sends, expected)
    assert result["cumulative_goal_candidates_used"] <= 17


def test_same_request_reentry_returns_read_only_native_response_without_paid_or_sqlite_claim(
        tmp_path, monkeypatch, causal_scenario):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario)
    assert runner.run()["status"] == "text_ready_for_director"
    ledger_before = runtime.ledger.read_bytes()
    with sqlite3.connect(root / "TASKS.sqlite3") as db:
        attempts_before = db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
    prepared = runner.read(root / "requests/goal_plan_16.json")
    cached = runner.invoke(runtime, "different_local_label", prepared,
        lambda value: (_ for _ in ()).throw(AssertionError("cached native must not be revalidated as a new result")))
    assert cached["cached_response_read_only"] and cached["ordinal"] == 568
    assert runtime.ledger.read_bytes() == ledger_before and len(sends) == 7
    assert not (root / "requests/different_local_label.json").exists()
    with sqlite3.connect(root / "TASKS.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == attempts_before


def native_seed_fixture(tmp_path, monkeypatch):
    parent = tmp_path / "known-parent"
    seed = {"schema": "offline-complete-goal", "whole_plan": {"premise": "完整原生561"}}
    request = {"stage": "goal_plan", "model": "MiniMax-M3.1-Flash-Preview"}
    receipt = {"status": "contract_valid", "output": seed, "request": request,
        "response_metadata": {"http_status_code": 200, "response_body_complete": True, "finish_reason": "tool_calls",
            "total_tokens": 100, "output_mode": "tool_call", "requested_model": request["model"], "response_model": request["model"]}}
    path = parent / "receipt561.json"
    runner.write(path, receipt)
    runner.write(parent / "CALL_LEDGER.json", {"calls": [{"ordinal": 561, "receipt": path.name, "receipt_sha256": runner.sha_file(path)}]})
    monkeypatch.setattr(runner, "PREFLIGHT_PARENT", parent)
    return seed, receipt, path


def test_seed561_is_exact_known_native_receipt_used_only_for_complete_revision(tmp_path, monkeypatch):
    seed, _, path = native_seed_fixture(tmp_path, monkeypatch)
    identity = runner.verify_seed_native(seed)
    assert identity["ordinal"] == 561 and identity["receipt_sha256"] == runner.sha_file(path)
    assert identity["contract_valid"] and not identity["semantic_approved"]
    assert identity["used_only_for_complete_model_revision"]
    changed = deepcopy(seed)
    changed["whole_plan"]["premise"] = "本地更改不得采用"
    with pytest.raises(ValueError, match="exact complete known native561"):
        runner.verify_seed_native(changed)


@pytest.mark.parametrize("field,value", [("total_tokens", None), ("total_tokens", -1),
    ("total_tokens", True), ("response_body_complete", False), ("finish_reason", "length"),
    ("output_mode", "text"), ("response_model", "different-model")])
def test_seed561_unknown_usage_truncation_or_wrong_identity_is_never_repairable(
        tmp_path, monkeypatch, field, value):
    seed, receipt, path = native_seed_fixture(tmp_path, monkeypatch)
    receipt["response_metadata"][field] = value
    runner.write(path, receipt)
    ledger = runner.read(runner.PREFLIGHT_PARENT / "CALL_LEDGER.json")
    ledger["calls"][0]["receipt_sha256"] = runner.sha_file(path)
    runner.write(runner.PREFLIGHT_PARENT / "CALL_LEDGER.json", ledger)
    with pytest.raises(ValueError, match="exact complete known native561"):
        runner.verify_seed_native(seed)


@pytest.mark.parametrize("change", ["duplicate", "missing", "changed_hash", "wrong_stage", "rejected_seed"])
def test_seed561_ambiguous_or_changed_receipt_cannot_enter_planning(tmp_path, monkeypatch, change):
    seed, receipt, path = native_seed_fixture(tmp_path, monkeypatch)
    ledger_path = runner.PREFLIGHT_PARENT / "CALL_LEDGER.json"
    ledger = runner.read(ledger_path)
    if change == "duplicate":
        ledger["calls"].append(deepcopy(ledger["calls"][0]))
    elif change == "missing":
        ledger["calls"][0]["ordinal"] = 562
    elif change == "changed_hash":
        receipt["output"]["whole_plan"]["premise"] = "changed receipt after frozen SHA"
        runner.write(path, receipt)
    else:
        if change == "wrong_stage":
            receipt["request"]["stage"] = "complete_script"
        else:
            receipt["status"] = "contract_rejected"
        runner.write(path, receipt)
        ledger["calls"][0]["receipt_sha256"] = runner.sha_file(path)
    runner.write(ledger_path, ledger)
    with pytest.raises(ValueError):
        runner.verify_seed_native(seed)


@pytest.mark.parametrize("change", [None, "ordinal", "receipt_hash", "usage_unknown", "stage_consumption", "active_state"])
def test_certified_parent_guard_requires_exact_terminal_known_561_through_567(
        tmp_path, monkeypatch, change):
    parent = tmp_path / "synthetic-terminal-parent"
    summary = {"stage_calls": {"goal_plan": 2, "goal_audit": 2, "complete_script": 1, "full_review": 2},
        "effective_calls_started": 567, "effective_reported_tokens": 10983919}
    rows = []
    for ordinal in range(561, 568):
        path = parent / (str(ordinal) + ".json")
        runner.write(path, {"status": "contract_valid", "output": {"native": ordinal},
            "response_metadata": {"http_status_code": 200, "response_body_complete": True,
                "finish_reason": "tool_calls", "total_tokens": 1}})
        rows.append({"ordinal": ordinal, "receipt": path.name, "receipt_sha256": runner.sha_file(path)})
    state_value = {"status": "halt_full_review_contract_requires_pipeline_diagnosis"}
    if change == "ordinal":
        rows[-1]["ordinal"] = 568
    elif change in ("receipt_hash", "usage_unknown"):
        path = parent / rows[-1]["receipt"]
        value = runner.read(path)
        value["response_metadata"]["total_tokens"] = None
        runner.write(path, value)
        if change == "usage_unknown":
            rows[-1]["receipt_sha256"] = runner.sha_file(path)
    elif change == "stage_consumption":
        summary["stage_calls"]["full_review"] = 1
    elif change == "active_state":
        state_value["status"] = "dispatching"
    runner.write(parent / "CALL_LEDGER.json", {"calls": rows})
    runner.write(parent / "STATE.json", state_value)
    monkeypatch.setattr(runner, "PREFLIGHT_PARENT", parent)
    fake_runtime = SimpleNamespace(ledger=parent / "CALL_LEDGER.json", summary=Mock(return_value=deepcopy(summary)))
    monkeypatch.setattr(runner.previous, "get_runtime", Mock(return_value=fake_runtime))
    # Call the original pure guard against this mocked parent only. The
    # default fixture still denies every real old-runtime acquisition.
    if change is None:
        assert PRIOR_GUARD() == summary
    else:
        with pytest.raises(ValueError):
            PRIOR_GUARD()
    assert fake_runtime.summary.call_count == 1


@pytest.mark.parametrize("change", ["inputs", "profile", "diagnosis", "actual_request", "saved_preview"])
def test_mock_preparation_rejects_authorized_identity_drift_before_any_root_or_claim_write(
        tmp_path, monkeypatch, change):
    from scripts import creative_flat_lineage_guard_v1 as lineage
    project = tmp_path / "isolated-prepare"
    parent = project / "parent"
    root = project / "new-run"
    approval = project / "new-grant/USER_CONTINUATION.json"
    claim = project / "new-grant/CLAIM.json"
    profile_path = project / "profile.json"
    authority = project / "previous-USER_CONTINUATION.json"
    preview_path = project / "data/qa/goal_context_production_repair_20261013/CONSISTENCY_EVIDENCE_REQUEST_PREVIEW_v1.json"
    seed = {"native_seed": "exact-complete561"}
    diagnostic = {"complete_known_failure": "original native diagnosis"}
    inputs, profile = {"source": "frozen original"}, {"writer": "frozen profile"}
    prepared = {"request": {"source": "original actual compiled request"}, "wire": {"source": "same"}}
    for key, value in {"PROJECT": project, "PREFLIGHT_PARENT": parent, "ROOT": root,
            "APPROVAL": approval, "CLAIM": claim, "PROFILE": profile_path}.items():
        monkeypatch.setattr(runner, key, value)
    monkeypatch.setattr(runner.previous, "APPROVAL", authority)
    runner.write(authority, {"human_authorized": True, "user_quote": "minimax随便追加"})
    runner.write(parent / "STATE.json", {"spend": {"effective_calls_started": 567,
        "effective_reported_tokens": 10983919, "effective_calls_with_known_usage": 565,
        "historical_pending_ordinals": [70, 160], "unknown_token_reservations": 93117}})
    runner.write(parent / "receipt561.json", {"output": seed})
    runner.write(parent / "CALL_LEDGER.json", {"calls": [{"ordinal": 561, "receipt": "receipt561.json"}]})
    runner.write(parent / "INPUTS.json", inputs)
    runner.write(profile_path, profile)
    runner.write(approval, {"human_authorized": True, "user_quote": "minimax随便追加",
        "parent_ledger_sha256": runner.sha_file(parent / "CALL_LEDGER.json"), "parent_goal_candidates_used": 15,
        "authority_source_sha256": runner.sha_file(authority),
        **runner.authorization_request_identity(diagnostic, prepared)})
    runner.write(preview_path, {"prepared": prepared})
    prepare_request = Mock(return_value=deepcopy(prepared))
    diag_mock = Mock(return_value=deepcopy(diagnostic))
    if change == "inputs":
        runner.write(parent / "INPUTS.json", {"source": "changed before preparation"})
    elif change == "profile":
        runner.write(profile_path, {"writer": "different model profile"})
    elif change == "diagnosis":
        diag_mock.return_value = {"complete_known_failure": "different diagnosed content"}
    elif change == "actual_request":
        prepare_request.return_value["request"]["source"] = "changed actual request"
    else:
        runner.write(preview_path, {"prepared": {"request": "changed saved authorization preview"}})
    before = {path: path.read_bytes() for path in project.rglob("*.json")}
    monkeypatch.setattr(lineage, "build_lineage_certificate", Mock(return_value={"mocked_certificate": True}))
    monkeypatch.setattr(runner, "verify_seed_native", Mock(return_value={"ordinal": 561, "semantic_approved": False}))
    monkeypatch.setattr(runner, "build_revision_diagnostics", diag_mock)
    monkeypatch.setattr(runner.parent, "source_gate", Mock(return_value={"mocked_source_gate": True}))
    monkeypatch.setattr(runner.workflow, "prepare_goal_request", prepare_request)
    writer = Mock(side_effect=AssertionError("authorization drift must reject before every new artifact"))
    monkeypatch.setattr(runner, "write", writer)
    runtime_factory = Mock(side_effect=AssertionError("drift must never prepare a production runtime"))
    monkeypatch.setattr(runner, "get_runtime", runtime_factory)
    with pytest.raises(ValueError, match="authorization.*changed"):
        PREPARE()
    assert not root.exists() and not claim.exists()
    assert writer.call_count == runtime_factory.call_count == 0
    assert {path: path.read_bytes() for path in before} == before

