"""Independent v10 coordinator and new native drama gate; fake service only."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import sqlite3

import pytest

from scripts import run_goal_context_text_production_v10 as runner
from scripts import creative_goal_context_dispatch_v6 as adapter
from scripts import creative_bounded_format_role_clients_v1 as bounded
from scripts import creative_evidenced_role_clients_v1 as evidenced
from tests import test_goal_context_text_production_v4 as helpers
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario

INHERITED={"calls_started":556,"reported_tokens":10706510,"calls_with_known_usage":554,
    "pending_ordinals":[70,160],"unknown_token_reservations":93117}

@pytest.fixture(autouse=True)
def no_provider_or_old_guard(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("independent v10 coordinator may not contact provider or old runtime")
    monkeypatch.setattr(socket.socket,"connect",deny)
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
                if current == "goal_plan":
                    value = deepcopy(goal)
                    value["whole_plan"]["premise"] = "合成新原生整片规划" + str(counts[current])
                elif current in ("source", "drama"):
                    value = deepcopy(bundle["native_" + current + "_audit"])
                    for field in ("goal_sha256", "audit_context_sha256"):
                        value[field] = structured_schema["properties"][field]["const"]
                    value["schema"] = structured_schema["properties"]["schema"]["const"]
                    if current == "drama":
                        current_goal = body["native_goal_document"]
                        value["scope_observations"] = {row["id"]: {"audible_speakers": [], "operated_props": []}
                            for row in current_goal["whole_plan"]["beats"]}
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
                elif current == "complete_script":
                    value = deepcopy(native)
                    value["title"] = "合成完整正文" + str(counts[current])
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
                message = {"role": "assistant", "content": None, "tool_calls": [{"id": "offline",
                    "type": "function", "function": {"name": runner.clients.TOOL_NAME, "arguments": json.dumps(value, ensure_ascii=False)}}]}
                response = {"id": "offline-" + str(evidence.identity["ordinal"]), "model": request["model"],
                    "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls"}],
                    "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}}
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
    assert spend["effective_calls_started"]==563 and spend["effective_reported_tokens"]==10707210
    assert spend["effective_calls_with_known_usage"]==561 and spend["historical_pending_ordinals"]==[70,160]
    assert spend["unknown_token_reservations"]==93117 and not spend["old_budget_reset"]
    assert result["inherited_goal_candidates_used"]==12 and result["cumulative_goal_candidates_used"]==13
    assert runner.read(runtime.ledger)["starting_spend"]==INHERITED
    before=runtime.ledger.read_bytes()
    with pytest.raises(FileExistsError): runner.run()
    assert runtime.ledger.read_bytes()==before and len(sends)==7


@pytest.mark.parametrize("part,mode",[("drama","unknown")])
def test_unknown_at_native_audit_or_full_part_never_dispatches_later_stage_or_restarts(tmp_path,monkeypatch,causal_scenario,part,mode):
    runtime,root,sends=replay(tmp_path,monkeypatch,causal_scenario,{(part,1):mode})
    result=runner.run()
    assert result["status"] in {"halt_goal_audit_uncertain","halt_goal_audit_interface_or_unknown",
        "halt_full_review_uncertain","halt_review_interface_or_unknown"},result
    expected=["goal_plan","source","drama","opening_setup","complete_script","semantic","physical"]
    expected=expected[:expected.index(part)+1]
    assert_no_handoff_or_reentry(runtime,root,sends,expected)
    assert not (root/"scripts/version_02").exists()


@pytest.mark.parametrize("mode",["null_scope_pass"])
def test_known_malformed_drama_response_stops_without_converting556_or_dispatching_setup(tmp_path,monkeypatch,causal_scenario,mode):
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
    assert result["cumulative_goal_candidates_used"]==14 and result["inherited_goal_candidates_used"]==12
    assert runtime.summary()["effective_calls_started"]==566 and not runtime.summary()["old_budget_reset"]


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


def test_actual554_complete_plan_enters_exact_revision_preview_once_without_provider():
    root=Path("data/production_trials/goal_context_text_production_20261013/round_08")
    inputs=runner.read(root/"INPUTS.json")
    seed=runner.read(root/"call_554_goal_plan_12.json")["output"]
    diagnosis=runner.read(runner.CONTENT_DIAGNOSIS)
    profile=runner.read(runner.PROFILE)
    before={p:p.read_bytes() for p in [root/"call_554_goal_plan_12.json",root/"call_556_goal_drama_audit_02.json"]}
    request=runner.workflow.prepare_goal_request(runner.revision_planning_inputs(inputs,seed,diagnosis),profile)
    actual=json.loads(request["request"]["messages"][1]["content"])
    assert actual["previous_complete_document"]==seed
    assert actual["revision_diagnostics"]==diagnosis
    assert "fresh_reconception_context" not in actual
    assert request["wire"]==runner.clients.expected_wire_request(request["request"])
    assert request["request_sha256"]==runner.digest(request["request"])
    assert request["manifest"]["reference_proof"]["payload_occurrences"]==1
    assert not request["dispatch_performed"] and request["sdk_max_retries"]==0
    assert {p:p.read_bytes() for p in before}==before
