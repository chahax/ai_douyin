"""Independent fresh-reconception coordinator; native synthetic service only."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import run_goal_context_text_production_v18 as runner
from scripts import record_legal_usage_continuation_v1 as authorizer
from scripts import creative_goal_context_dispatch_v7 as adapter
from scripts import creative_bounded_format_role_clients_v1 as bounded
from scripts import creative_evidenced_role_clients_v1 as evidenced
from tests import test_goal_context_text_production_v4 as helpers
from tests.test_creative_split_full_review_contract_v4 import synthetic_consistency
from tests.test_creative_goal_legal_usage_source_audit_v1 import synthetic_source, add_usage
from scripts import record_legal_usage_diagnosis_v1 as diagnosis_records
from src.content_factory import creative_goal_legal_usage_source_audit_v1 as legal_audit
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests.test_creative_goal_commitment_audit_v1 import synthetic as synthetic_commitment

INHERITED = {"calls_started": 601, "reported_tokens": 12004575, "calls_with_known_usage": 599,
    "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
PRIOR_GUARD, PREPARE = runner.prior_guard, runner.prepare

@pytest.fixture(autouse=True)
def no_real_network_or_runtime(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("independent v18 test cannot contact provider or acquire real parent runtime")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(runner.previous, "get_runtime", deny)
    monkeypatch.setattr(runner, "prior_guard", deny)


def phase(request):
    provenance = request["input_provenance"]
    if provenance.get("substage") == "opening_setup":
        return "opening_setup"
    if request["stage"] == "goal_audit":
        properties = request["structured_schema"]["properties"]
        return "source" if "claim_checks" in properties else "drama" if "goal_checks" in properties else "commitment"
    return provenance.get("review_part", request["stage"])

def native_commitment_response(body, schema, goal, mode):
    """Build a new source-bound focused fixture, never reuse a drama review."""
    value = synthetic_commitment(goal)
    for key in ("schema", "goal_sha256", "audit_context_sha256"):
        value[key] = schema["properties"][key]["const"]
    for check in value["commitment_checks"].values():
        for usage in check["actual_usages"].values():
            usage.update(requirement_scope="local_event", comparison_refs=[])
    if mode in ("fail", "unknown", "masked_fail"):
        row = next(iter(value["commitment_checks"].values()))
        usage = next(iter(row["actual_usages"].values()))
        usage["relationship"] = "unknown" if mode == "unknown" else "not_demonstrated"
        row.update(status="unknown" if mode == "unknown" else "pass" if mode == "masked_fail" else "fail",
            required_revision="Complete native current-goal revision" if mode == "fail" else "")
    elif mode == "missing_commitments":
        value.pop("commitment_checks")
    elif mode == "mixed_context":
        value["audit_context_sha256"] = "f" * 64
    elif mode == "mixed_goal":
        value["goal_sha256"] = "e" * 64
    elif mode in ("missing_scope", "c_as_comparison"):
        row = next(iter(value["commitment_checks"].values()))
        usage = next(iter(row["actual_usages"].values()))
        if mode == "missing_scope":
            usage.pop("requirement_scope")
        else:
            usage["comparison_refs"] = [row["claim_ref"]]
    assert "native_goal_document" not in body and "native_goal_evidence_view" in body
    assert "reference_fulltext" not in body
    return value


def replay(tmp_path, monkeypatch, causal_scenario, modes=None):
    inputs, profile, goal, opening, bundle, ids, native = deepcopy(causal_scenario)
    bundle["native_drama_audit"]["closed_scope_findings"] = []
    bundle["native_drama_audit"].pop("commitment_checks", None)
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
                elif current == "commitment":
                    current_goal = runner.read(sorted((root / "goals").glob("native_*.json"))[-1])
                    value = native_commitment_response(body, structured_schema, current_goal, mode)
                elif current == "source":
                    current_goal = runner.read(sorted((root / "goals").glob("native_*.json"))[-1])
                    authority = {key:deepcopy(body[key]) for key in ("verified_legal_context","origin_catalog")}
                    value = synthetic_source(current_goal,authority,structured_schema["properties"]["audit_context_sha256"]["const"])
                    assert "native_goal_evidence_view" in body and "native_goal_claims" not in body
                    assert "reference_fulltext" not in body
                    if mode in ("fail","unknown"):
                        next(iter(value["claim_checks"].values())).update(status=mode,
                            required_revision="Complete native whole plan" if mode=="fail" else "")
                    elif mode in ("legal_fail","legal_unknown","masked_legal_fail"):
                        ref=next(iter(value["legal_usage_scan"]))
                        usage=add_usage(value,current_goal,ref,relation="unknown" if mode=="legal_unknown" else "contradicts",
                            status="unknown" if mode=="legal_unknown" else "pass" if mode=="masked_legal_fail" else "fail")
                        if mode!="legal_unknown":
                            usage["authority_refs"]=[next(iter(legal_audit.build_authority_catalog(authority)))]
                    elif mode=="missing_scan":
                        value["legal_usage_scan"].pop(next(iter(value["legal_usage_scan"])))
                    elif mode=="mixed_authority":
                        value["authority_context_sha256"]="b"*64
                    elif mode=="legacy_schema":
                        value["schema"]="creative_goal_context_workflow/v7/source_audit"
                elif current == "drama":
                    value = deepcopy(bundle["native_" + current + "_audit"])
                    for field in ("goal_sha256", "audit_context_sha256"):
                        value[field] = structured_schema["properties"][field]["const"]
                    value["schema"] = structured_schema["properties"]["schema"]["const"]
                    if current == "drama":
                        current_goal = runner.read(sorted((root / "goals").glob("native_*.json"))[-1])
                        value["scope_observations"] = {ref: {"audible_speakers": [], "operated_props": []}
                            for ref in structured_schema["properties"]["scope_observations"]["properties"]}
                        if mode in ("goal_fail", "goal_unknown"):
                            row = next(row for key, row in value["goal_checks"].items() if key != "closed_production_scope")
                            row.update(status="fail" if mode == "goal_fail" else "unknown",
                                required_revision="Complete current native planning revision" if mode == "goal_fail" else "")
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
                    value["schema"] = structured_schema["properties"]["schema"]["const"]
                    value["props"] = {key: {"kind": "absent"} if row["kind"] == "absent" else row
                        for key, row in value["props"].items()}
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
                        row["status"]="fail"
                        child.update(status="fail", required_revision="模型必须提交完整新正文兑现当前目标。")
                        value["revision_target"] = "script"
                message = {"role": "assistant", "content": None, "tool_calls": [{"id": "offline",
                    "type": "function", "function": {"name": runner.clients.TOOL_NAME, "arguments": json.dumps(value, ensure_ascii=False)}}]}
                if mode == "missing_tool":
                    message.pop("tool_calls")
                    message["content"] = json.dumps(value, ensure_ascii=False)
                response = {"id": "offline-" + str(evidence.identity["ordinal"]), "model": request["model"],
                    "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls"}],
                    "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}}
                if mode == "usage_unknown":
                    response.pop("usage")
                elif mode == "truncated":
                    response["choices"][0]["finish_reason"] = "length"
                elif mode == "missing_tool":
                    response["choices"][0]["finish_reason"] = "stop"
                saved, manifest = evidence.save_body(json.dumps(response, ensure_ascii=False).encode(), evidenced.http_metadata(200, {}))
                return evidenced.parse_saved_response(saved, manifest, role, request["model"], thinking, structured_schema, evidence)
        return lambda: Fake()

    runtime = adapter.GoalContextRuntime(project, root, [source], deepcopy(INHERITED), profile=profile,
        stage_limits={"goal_plan": 4, "goal_audit": 6, "complete_script": 3, "full_review": 6},
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


def assert_no_reentry(runtime, root, sends):
    ledger, sent = runtime.ledger.read_bytes(), len(sends)
    db_path = root / "TASKS.sqlite3"
    if db_path.exists():
        with sqlite3.connect(db_path) as db:
            claims = db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
    else:
        claims = None
    with pytest.raises(FileExistsError):
        runner.run()
    assert runtime.ledger.read_bytes() == ledger and len(sends) == sent
    if claims is None:
        assert not db_path.exists()
    else:
        with sqlite3.connect(db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == claims


def test_first_request_revises_complete_native_source_then_current_failure_revises_whole_goal(
        tmp_path, monkeypatch, causal_scenario):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario, {("drama", 1): "goal_fail"})
    result = runner.run()
    assert result["status"] == "text_ready_for_director", result
    assert [phase(r) for r in sends] == ["goal_plan", "source", "commitment", "drama", "goal_plan", "source", "commitment", "drama",
        "opening_setup", "complete_script", "semantic", "physical"]
    first = json.loads(sends[0]["messages"][1]["content"])
    assert first["previous_complete_document"] == runner.read(root / "INHERITED_NATIVE_GOAL.json")
    assert first["revision_diagnostics"] == runner.read(root / "INHERITED_DIAGNOSTICS.json")
    assert "fresh_reconception_context" not in first
    assert first["reference_fulltext"] == runner.read(root / "INPUTS.json")["reference_fulltext"]
    second = json.loads(sends[4]["messages"][1]["content"])
    first_goal = runner.read(root / "goals/native_01.json")
    assert second["previous_complete_document"] == first_goal
    assert "fresh_reconception_context" not in second
    assert second["revision_diagnostics"]["complete_same_source_goal_audits"][2]["accepted"] is False
    assert result["inherited_goal_candidates_used"] == 24 and result["cumulative_goal_candidates_used"] == 26
    assert [row["label"] for row in runner.read(runtime.ledger)["calls"] if row["label"].startswith("goal_plan_")] == ["goal_plan_25", "goal_plan_26"]
    spend = runtime.summary()
    assert spend["effective_calls_started"] == 613 and spend["effective_reported_tokens"] == 12005775
    assert spend["effective_calls_with_known_usage"] == 611
    assert spend["unknown_token_reservations"] == 93117 and spend["historical_pending_ordinals"] == [70, 160]
    assert not spend["old_budget_reset"]
    assert result["old_director_capacity"] == {"used": 7, "limit": 7, "remaining": 0}
    assert result["parent_whole_plan_unused_capacity"] == 0
    assert result["parent_unused_capacity_stays_in_closed_run"] is True
    handoff = runner.read(root / "TEXT_HANDOFF.json")
    assert handoff["native_goal"] == runner.read(root / "goals/native_02.json")
    assert handoff["native_goal_audit"]["native_commitment_audit"] == runner.read(root / "goals/commitment_native_audit_02.json")
    assert handoff["native_full_review_bundle"]["schema"] == runner.reviews.BUNDLE_VERSION
    assert runner.reviews.VERSION == "creative_split_full_review_part/v4"
    assert sends[-2]["structured_schema"]["properties"]["schema"]["const"] == runner.reviews.VERSION
    assert not handoff["media_authorized"] and not handoff["production_dispatch_eligible"]
    assert not result["human_quality_approved"] and not result["creative_quality_passed"]
    assert_no_reentry(runtime, root, sends)


def test_new_scope_bounds_two_plans_two_setups_three_bodies_six_reviews_without_reset(
        tmp_path, monkeypatch, causal_scenario):
    modes = {("drama", 1): "goal_fail", ("opening_setup", 1): "contract_fail",
        ("physical", 1): "fail", ("physical", 2): "fail"}
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario, modes)
    result = runner.run()
    assert result["status"] == "text_ready_for_director", result
    spend = runtime.summary()
    assert spend["stage_calls"] == {"goal_plan": 4, "goal_audit": 6, "complete_script": 3, "full_review": 6}
    assert spend["effective_calls_started"] == 620 and spend["effective_reported_tokens"] == 12006475
    assert runner.read(runtime.ledger)["starting_spend"] == INHERITED
    assert result["cumulative_goal_candidates_used"] == 26 and result["opening_setup_calls"] == 2
    assert not (root / "goals/native_03.json").exists() and not (root / "scripts/version_04").exists()
    assert result["old_director_capacity"]["remaining"] == 0
    assert_no_reentry(runtime, root, sends)


@pytest.mark.parametrize("part,mode", [
    ("goal_plan", "transport_unknown"), ("goal_plan", "usage_unknown"), ("goal_plan", "truncated"),
    ("drama", "transport_unknown"), ("drama", "goal_unknown"),
])
def test_unknown_or_incomplete_new_result_does_not_use_second_goal_or_restart(tmp_path, monkeypatch, causal_scenario, part, mode):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario, {(part, 1): mode})
    result = runner.run()
    assert [phase(r) for r in sends] == (["goal_plan"] if part == "goal_plan" else ["goal_plan", "source", "commitment", "drama"])
    assert result["status"] in {"halt_goal_interface_or_unknown", "halt_goal_audit_interface_or_unknown", "halt_goal_audit_uncertain"}
    assert result["cumulative_goal_candidates_used"] == 25
    assert not (root / "goals/native_02.json").exists() and not (root / "TEXT_HANDOFF.json").exists()
    assert_no_reentry(runtime, root, sends)


def test_two_known_complete_goal_contract_failures_exhaust_only_new_bound(tmp_path, monkeypatch, causal_scenario):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario,
        {("goal_plan", 1): "contract_fail", ("goal_plan", 2): "contract_fail"})
    result = runner.run()
    assert result["status"] == "halt_goal_content_capacity_exhausted"
    assert [phase(r) for r in sends] == ["goal_plan", "goal_plan"]
    assert result["cumulative_goal_candidates_used"] == 26
    assert not (root / "goals/native_03.json").exists()
    assert_no_reentry(runtime, root, sends)


@pytest.mark.parametrize("part", ["goal_plan", "commitment"])
def test_complete_known_plain_content_without_required_tool_is_preserved_and_stopped_without_conversion_or_retry(
        tmp_path, monkeypatch, causal_scenario, part):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario, {(part, 1): "missing_tool"})
    result = runner.run()
    assert [phase(row) for row in sends] == (["goal_plan"] if part == "goal_plan" else ["goal_plan", "source", "commitment"])
    assert result["status"] in {"halt_goal_interface_or_unknown", "halt_goal_audit_interface_or_unknown"}, result
    ledger = runner.read(runtime.ledger)
    receipt = runtime.effective_receipt(ledger["calls"][-1])
    assert receipt["response_metadata"]["total_tokens"] == 100
    assert receipt["response_metadata"]["response_body_complete"] is True
    assert receipt["response_metadata"]["finish_reason"] == "stop"
    assert not receipt.get("output")
    assert not (root / "TEXT_HANDOFF.json").exists() and not (root / "goals/native_02.json").exists()
    assert runtime.summary()["new_unknown_token_reservations"] == 0
    assert result["parent_whole_plan_unused_capacity"] == 0
    assert_no_reentry(runtime, root, sends)


@pytest.mark.parametrize("mode", ["unknown", "masked_fail", "missing_commitments", "mixed_context",
    "mixed_goal", "usage_unknown", "truncated", "missing_scope", "c_as_comparison"])
def test_focused_package_uncertainty_missing_masking_cross_context_or_incomplete_stops_before_drama_and_author(
        tmp_path, monkeypatch, causal_scenario, mode):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario, {("commitment", 1): mode})
    result = runner.run()
    assert [phase(r) for r in sends] == ["goal_plan", "source", "commitment"]
    assert result["status"] in {"halt_goal_audit_uncertain", "halt_goal_audit_contract_requires_pipeline_diagnosis",
        "halt_goal_audit_interface_or_unknown"}, result
    assert result.get("audit_kind") == "commitment"
    assert not (root / "setups").exists() and not (root / "scripts").exists()
    assert not (root / "TEXT_HANDOFF.json").exists() and not (root / "goals/native_02.json").exists()
    assert_no_reentry(runtime, root, sends)


def test_fresh_input_omits_legacy_template_without_mutating_source_or_allowing_mixed_modes(causal_scenario):
    inputs, profile, goal, *_ = deepcopy(causal_scenario)
    original_source = deepcopy(inputs)
    dirty = {**inputs, "previous_complete_document": {"old_story": "must not appear"},
        "revision_diagnostics": {"old_revision": "must not appear"},
        "complete_script_feasibility_diagnostics": {"old_details": "must not appear"},
        "fresh_reconception_context": {"stale": "must not appear"}}
    diagnostic = {"qualified_failed_mechanisms": ["inconsistent deadline, not a retained plot"]}
    fresh = runner.fresh_planning_inputs(dirty, diagnostic)
    assert fresh["fresh_reconception_context"] == diagnostic
    assert not {"previous_complete_document", "revision_diagnostics", "complete_script_feasibility_diagnostics"} & set(fresh)
    for key in ("source_packet", "verified_legal_context", "user_goal_contract", "reference_fulltext"):
        assert fresh[key] == original_source[key]
    assert inputs == original_source and dirty["previous_complete_document"] == {"old_story": "must not appear"}
    with pytest.raises(ValueError, match="mutually exclusive"):
        runner.workflow.prepare_goal_request({**fresh, "previous_complete_document": goal}, profile)
    with pytest.raises(ValueError, match="mutually exclusive"):
        runner.workflow.prepare_goal_request({**fresh, "revision_diagnostics": diagnostic}, profile)
    revised = runner.revision_planning_inputs(fresh, goal, {"current_native_failure": True})
    assert revised["previous_complete_document"] == goal and "fresh_reconception_context" not in revised


def parent_fixture(tmp_path, monkeypatch):
    parent=tmp_path/"known601-parent"
    limits={"goal_plan":4,"goal_audit":6,"complete_script":3,"full_review":6}
    summary={"stage_calls":{"goal_plan":3,"goal_audit":5,"complete_script":2,"full_review":1},
        "stage_limits":limits,"effective_calls_started":601,"effective_reported_tokens":12004575,
        "effective_calls_with_known_usage":599,"new_unknown_token_reservations":0,
        "historical_pending_ordinals":[70,160],"unknown_token_reservations":93117}
    rows=[]
    for ordinal in range(591,602):
        path=parent/f"native{ordinal}.json"
        model="deepseek-flash" if ordinal==601 else "MiniMax-M3.1-Flash-Preview"
        data={"status":"interface_rejected" if ordinal==601 else "contract_rejected" if ordinal==599 else "contract_valid",
            "ordinal":ordinal,"output":None if ordinal==601 else {"native":ordinal},
            "request":{"stage":"full_review" if ordinal==601 else "goal_plan","model":model},
            "validation":None,
            "response_metadata":{"http_status_code":200,"response_body_complete":True,
                "finish_reason":"length" if ordinal==601 else "tool_calls",
                "total_tokens":90219 if ordinal==601 else 1,
                "output_mode":"unusable_response" if ordinal==601 else "tool_call",
                "response_fault_code":"RESPONSE_TRUNCATED" if ordinal==601 else None,
                "requested_model":model,"response_model":model}}
        if ordinal in (595,596,597):
            data["validation"]={"valid":True,"accepted":True,"uncertainties":[]}
        if ordinal==601:
            data["response_payload"]={"choices":[{"finish_reason":"length","message":{}}],
                "usage":{"prompt_tokens":58219,"completion_tokens":32000,"total_tokens":90219}}
        runner.write(path,data)
        rows.append({"ordinal":ordinal,"receipt":path.name,"receipt_sha256":runner.sha_file(path)})
    runner.write(parent/"CALL_LEDGER.json",{"calls":rows})
    runner.write(parent/"USER_SCOPE.json",{"local_goal_candidates_limit":2,
        "local_opening_setup_limit":2,"inherited_goal_candidates_used":22,
        "cumulative_goal_candidates_this_run_maximum":24,"stage_limits":limits})
    runner.write(parent/"STATE.json",{"status":"halt_review_interface_or_unknown","receipt_ordinal":601,
        "review_part":"semantic","text_ready_for_director":False,"spend":deepcopy(summary),
        "cumulative_goal_candidates_used":24,"opening_setup_calls":1})
    monkeypatch.setattr(runner,"PREFLIGHT_PARENT",parent)
    monkeypatch.setattr(runner,"PARENT_STATE",parent/"STATE.json")
    runtime=SimpleNamespace(ledger=parent/"CALL_LEDGER.json",summary=Mock(return_value=deepcopy(summary)),inherited_guard=Mock())
    monkeypatch.setattr(runner.previous,"get_runtime",Mock(return_value=runtime))
    monkeypatch.setattr(runner.original,"verify_receipt_evidence",Mock(return_value=parent))
    return parent,summary,runtime


def test_known_usage_truncated601_is_consumed_but_never_adopted_or_changed(tmp_path,monkeypatch):
    parent,summary,runtime=parent_fixture(tmp_path,monkeypatch)
    before={p:p.read_bytes() for p in parent.glob("*.json")}
    assert PRIOR_GUARD()==summary
    assert runtime.inherited_guard.call_count==1
    assert runner.known_truncated_review(runner.read(parent/"native601.json"))
    assert not runner.repairable(runner.read(parent/"native601.json"))
    assert {p:p.read_bytes() for p in before}==before
    assert runner.original.verify_receipt_evidence.call_count==11


@pytest.mark.parametrize("change",["state_status","receipt_identity","adopted_review","unknown_usage",
    "wrong_finish","wrong_outer_usage","inherited_unknown","candidate_count","missing_call","sdk_identity"])
def test_changed_unknown_or_nonterminal601_cannot_authorize_new_claim(tmp_path,monkeypatch,change):
    parent,_,runtime=parent_fixture(tmp_path,monkeypatch)
    if change=="sdk_identity":
        monkeypatch.setattr(runner.original,"verify_receipt_evidence",Mock(side_effect=ValueError("SDK identity changed")))
    elif change in ("receipt_identity","adopted_review","unknown_usage","wrong_finish","wrong_outer_usage"):
        path=parent/"native601.json"
        data=runner.read(path)
        if change=="receipt_identity": data["output"]={"patched_review":True}
        elif change=="adopted_review": data["validation"]={"accepted":True}
        elif change=="unknown_usage": data["response_metadata"]["total_tokens"]=None
        elif change=="wrong_finish": data["response_metadata"]["finish_reason"]="stop"
        else: data["response_payload"]["usage"]["total_tokens"]-=1
        runner.write(path,data)
        if change!="receipt_identity":
            ledger=runner.read(runtime.ledger)
            ledger["calls"][-1]["receipt_sha256"]=runner.sha_file(path)
            runner.write(runtime.ledger,ledger)
    elif change=="missing_call":
        ledger=runner.read(runtime.ledger); ledger["calls"].pop(); runner.write(runtime.ledger,ledger)
    else:
        state=runner.read(parent/"STATE.json")
        if change=="state_status": state["status"]="review_received"
        elif change=="candidate_count": state["cumulative_goal_candidates_used"]=23
        else:
            state["spend"]["unknown_token_reservations"]=0
            runtime.summary.return_value=deepcopy(state["spend"])
        runner.write(parent/"STATE.json",state)
    with pytest.raises(ValueError): PRIOR_GUARD()
    assert not (parent/"NEW_RUN_CLAIM.json").exists()


@pytest.mark.parametrize("change",["inputs","profile","diagnosis","actual_request","saved_preview"])
def test_four_authorization_identities_and_preview_reject_drift_before_claim(tmp_path,monkeypatch,change):
    from scripts import creative_flat_lineage_guard_v2 as lineage
    project,parent=tmp_path/"bind",tmp_path/"bind/parent"
    root,claim,approval=project/"run",project/"grant/CLAIM.json",project/"grant/USER_CONTINUATION.json"
    authority,profile_path=project/"authority.json",project/"profile.json"
    preview_path=project/"data/qa/creative_legal_usage_20261014/LEGAL_USAGE_REQUEST_PREVIEW_v1.json"
    for key,value in {"PROJECT":project,"PREFLIGHT_PARENT":parent,"ROOT":root,"CLAIM":claim,
            "APPROVAL":approval,"PROFILE":profile_path,"PARENT_STATE":parent/"STATE.json"}.items():
        monkeypatch.setattr(runner,key,value)
    monkeypatch.setattr(runner.previous,"APPROVAL",authority)
    seed,diagnostic,prepared={"exact":"native594"},{"qualified":"actual law/source + length"},{"request":{"source":"same"}}
    runner.write(authority,{"human_authorized":True,"user_quote":"minimax随便追加"})
    runner.write(parent/"STATE.json",{"spend":{"effective_calls_started":601}})
    runner.write(parent/"receipt594.json",{"output":seed})
    runner.write(parent/"CALL_LEDGER.json",{"calls":[{"ordinal":594,"receipt":"receipt594.json"}]})
    runner.write(parent/"INPUTS.json",{"source":"unchanged authoritative input"})
    runner.write(profile_path,{"model":"same"})
    runner.write(approval,{"human_authorized":True,"user_quote":"minimax随便追加",
        "parent_ledger_sha256":runner.sha_file(parent/"CALL_LEDGER.json"),"parent_goal_candidates_used":24,
        "authority_source_sha256":runner.sha_file(authority),**runner.authorization_request_identity(diagnostic,prepared)})
    runner.write(preview_path,{"prepared":prepared})
    diag_mock,request_mock=Mock(return_value=deepcopy(diagnostic)),Mock(return_value=deepcopy(prepared))
    if change=="inputs":runner.write(parent/"INPUTS.json",{"source":"drift"})
    elif change=="profile":runner.write(profile_path,{"model":"drift"})
    elif change=="diagnosis":diag_mock.return_value["qualified"]="drift"
    elif change=="actual_request":request_mock.return_value["request"]["source"]="drift"
    else:runner.write(preview_path,{"prepared":{"request":"drift"}})
    before={p:p.read_bytes() for p in project.rglob("*.json")}
    monkeypatch.setattr(lineage,"build_lineage_certificate",Mock(return_value={"local":"certificate"}))
    monkeypatch.setattr(runner,"verify_seed_native",Mock(return_value={"ordinal":594}))
    monkeypatch.setattr(runner,"build_revision_diagnostics",diag_mock)
    monkeypatch.setattr(runner.parent,"source_gate",Mock(return_value={"offline":True}))
    monkeypatch.setattr(runner.workflow,"prepare_goal_request",request_mock)
    writes=Mock(side_effect=AssertionError("drift must reject before all writes/claims"))
    monkeypatch.setattr(runner,"write",writes)
    with pytest.raises(ValueError,match="authorization.*changed"):PREPARE()
    assert writes.call_count==0 and not root.exists() and not claim.exists()
    assert {p:p.read_bytes() for p in before}==before


@pytest.fixture
def local_authority_binding(tmp_path,monkeypatch):
    project,parent=tmp_path/"authorizer",tmp_path/"authorizer/parent"
    authority,approval,claim=project/"authority.json",project/"grant/USER_CONTINUATION.json",project/"grant/CLAIM.json"
    profile,root=project/"profile.json",project/"newrun"
    for key,value in {"PROJECT":project,"PREFLIGHT_PARENT":parent,"ROOT":root,"CLAIM":claim,
            "APPROVAL":approval,"PROFILE":profile,"PARENT_STATE":parent/"STATE.json"}.items():
        monkeypatch.setattr(runner,key,value)
    monkeypatch.setattr(runner.previous,"APPROVAL",authority)
    runner.write(authority,{"human_authorized":True,"user_quote":"minimax随便追加"})
    runner.write(parent/"STATE.json",{"status":"halt_review_interface_or_unknown","cumulative_goal_candidates_used":24,
        "spend":{"effective_calls_started":601,"effective_reported_tokens":12004575}})
    runner.write(parent/"receipt594.json",{"output":{"native":"original594"}})
    runner.write(parent/"CALL_LEDGER.json",{"calls":[{"ordinal":594,"receipt":"receipt594.json"}]})
    runner.write(parent/"INPUTS.json",{"source":"original immutable authority"})
    runner.write(profile,{"model":"same"})
    monkeypatch.setattr(runner,"prior_guard",Mock(return_value={"closed":True}))
    monkeypatch.setattr(runner,"verify_seed_native",Mock(return_value={"ordinal":594,"semantic_approved":False}))
    diagnosis=Mock(return_value={"qualified":"actual source false positive and truncated review"})
    prepared=Mock(return_value={"request":{"source":"original native594 complete revision"}})
    monkeypatch.setattr(runner,"build_revision_diagnostics",diagnosis)
    monkeypatch.setattr(runner.workflow,"prepare_goal_request",prepared)
    return project,root,claim,approval,diagnosis,prepared


def test_authorizer_binds_only_local_scope_and_recovers_identical_missing_preview(local_authority_binding):
    project,root,claim,approval,_,_=local_authority_binding
    authorizer.main()
    original=approval.read_bytes()
    binding=runner.read(approval)
    assert binding["parent_goal_candidates_used"]==24 and binding["parent_whole_plan_maximum"]==24
    assert binding["parent_whole_plan_unused_capacity"]==0
    assert binding["parent_script_submissions"]==2 and binding["parent_setup_submissions"]==1
    assert not binding["old_ledger_reset"] and not binding["media_authorized"]
    preview=project/"data/qa/creative_legal_usage_20261014/LEGAL_USAGE_REQUEST_PREVIEW_v1.json"
    saved=preview.read_bytes();preview.unlink()
    authorizer.main()
    assert approval.read_bytes()==original and preview.read_bytes()==saved
    assert not root.exists() and not claim.exists()


@pytest.mark.parametrize("change",["diagnosis","request","existing_claim"])
def test_authorizer_cannot_regain_claim_or_bind_drift_while_restoring_preview(local_authority_binding,change):
    project,root,claim,approval,diagnosis,prepared=local_authority_binding
    authorizer.main()
    before=approval.read_bytes()
    preview=project/"data/qa/creative_legal_usage_20261014/LEGAL_USAGE_REQUEST_PREVIEW_v1.json"
    preview.unlink()
    if change=="diagnosis":diagnosis.return_value["qualified"]="changed"
    elif change=="request":prepared.return_value["request"]["source"]="changed"
    else:runner.write(claim,{"root":"old claim must remain"})
    with pytest.raises((ValueError,RuntimeError)):authorizer.main()
    assert approval.read_bytes()==before and not preview.exists() and not root.exists()


@pytest.fixture
def cloned_diagnosis(tmp_path,monkeypatch):
    import shutil
    actual_parent=runner.previous.ROOT
    diagnosis=diagnosis_records.build_diagnosis(actual_parent)
    cloned=tmp_path/"closed16"
    for absolute in diagnosis["source_file_sha256"]:
        source=Path(absolute)
        target=cloned/source.relative_to(actual_parent)
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    monkeypatch.setattr(runner,"PREFLIGHT_PARENT",cloned)
    monkeypatch.setattr(runner,"PARENT_STATE",cloned/"STATE.json")
    path=tmp_path/"qualified_diag.json"
    monkeypatch.setattr(runner,"CONTENT_DIAGNOSIS",path)
    new=diagnosis_records.build_diagnosis(cloned)
    runner.write(path,new)
    seed=runner.read(cloned/"goals/native_02.json")
    return cloned,path,new,seed


def test_exact_source_false_positive_and_length_witnesses_preserve_original_quotes(cloned_diagnosis):
    parent,path,diagnosis,seed=cloned_diagnosis
    before={p:p.read_bytes() for p in parent.rglob("*") if p.is_file()}
    projected=runner.build_revision_diagnostics(seed)
    sent=projected["verified_pipeline_diagnosis"]
    assert sent["complete_local_diagnosis_sha256"]==runner.digest(diagnosis)
    assert sent["complete_local_source_manifest_sha256"]==runner.digest(diagnosis["source_file_sha256"])
    assert "source_file_sha256" not in sent and "parent_spend" not in sent
    assert sent["verified_failures"][0]["exact_claims"]==diagnosis["verified_failures"][0]["exact_claims"]
    chain=sent["verified_failures"][0]["prior_feedback_chain"]
    assert chain["native_focused_593_cc6_judgment"]["status"]=="fail"
    assert sent["verified_failures"][0]["native_focused_596_cc6_judgment"]["status"]=="pass"
    assert chain["former_required_revision_is_fault_evidence_not_current_instruction"] is True
    assert projected["native_goal_ordinal"]==594
    assert len(diagnosis["source_file_sha256"])==30
    failure,length=diagnosis["verified_failures"]
    assert failure["native_source_cc6_judgment"]["status"]=="pass"
    assert failure["native_focused_cc6_judgment"]["status"]=="pass"
    assert "非本表法律结论" in failure["native_source_cc6_judgment"]["reason"]
    assert length["argument_prefix_characters"]==77774
    assert length["response_metadata"]["completion_tokens"]==32000
    assert projected["previous_complete_script_sent_to_planner"] is False
    assert projected["native_text_locally_patched"] is False
    assert {p:p.read_bytes() for p in before}==before


@pytest.mark.parametrize("fault",["missing_source","native_seed","source_judgment","framing",
    "601_adopted","usage","argument_statistics","spend"])
def test_changed_diagnosis_or_original_witness_cannot_become_revision_authority(cloned_diagnosis,fault):
    parent,path,diagnosis,seed=cloned_diagnosis
    if fault=="missing_source":diagnosis["source_file_sha256"].pop(next(iter(diagnosis["source_file_sha256"])))
    elif fault=="native_seed":seed["claims"][0]["text"]="manually changed native"
    elif fault=="source_judgment":diagnosis["verified_failures"][0]["native_source_cc6_judgment"]["status"]="fail"
    elif fault=="framing":diagnosis["creative_risks"][0]["diagnosis"]="pretend proven no compensation"
    elif fault=="601_adopted":diagnosis["truncated_full_review_not_adopted"]=False
    elif fault=="usage":diagnosis["verified_failures"][1]["response_metadata"]["total_tokens"]-=1
    elif fault=="argument_statistics":diagnosis["verified_failures"][1]["argument_prefix_characters"]-=1
    else:diagnosis["parent_spend"]["effective_reported_tokens"]=0
    runner.write(path,diagnosis)
    with pytest.raises(ValueError):runner.build_revision_diagnostics(seed)
    assert not (parent/"NEW_CLAIM.json").exists()


@pytest.mark.parametrize("mode",["legal_unknown","masked_legal_fail","missing_scan","mixed_authority","legacy_schema"])
def test_source_legal_usage_unknown_incomplete_or_masked_stops_before_focused_and_author(
        tmp_path,monkeypatch,causal_scenario,mode):
    runtime,root,sends=replay(tmp_path,monkeypatch,causal_scenario,{("source",1):mode})
    result=runner.run()
    assert result["status"] in ("halt_goal_audit_uncertain","halt_goal_audit_contract_requires_pipeline_diagnosis"),result
    assert [phase(r) for r in sends]==["goal_plan","source"]
    assert not (root/"TEXT_HANDOFF.json").exists()
    assert_no_reentry(runtime,root,sends)


def test_source_legal_failure_causes_complete_native_plan_revision_before_downstream(
        tmp_path,monkeypatch,causal_scenario):
    runtime,root,sends=replay(tmp_path,monkeypatch,causal_scenario,{("source",1):"legal_fail"})
    result=runner.run()
    assert result["status"]=="text_ready_for_director",result
    assert [phase(r) for r in sends[:4]]==["goal_plan","source","goal_plan","source"]
    second=json.loads(sends[2]["messages"][1]["content"])
    assert second["previous_complete_document"]==runner.read(root/"goals/native_01.json")
    assert second["revision_diagnostics"]["complete_same_source_goal_audits"][0]["accepted"] is False
    assert result["cumulative_goal_candidates_used"]==26
    assert_no_reentry(runtime,root,sends)

