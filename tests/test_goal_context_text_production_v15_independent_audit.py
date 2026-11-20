"""Independent fresh-reconception coordinator; native synthetic service only."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import run_goal_context_text_production_v15 as runner
from scripts import record_review_relation_focus_continuation_v1 as authorizer
from scripts import creative_goal_context_dispatch_v7 as adapter
from scripts import creative_bounded_format_role_clients_v1 as bounded
from scripts import creative_evidenced_role_clients_v1 as evidenced
from tests import test_goal_context_text_production_v4 as helpers
from tests.test_creative_split_full_review_contract_v2 import synthetic_consistency
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests.test_creative_goal_commitment_audit_v1 import synthetic as synthetic_commitment

INHERITED = {"calls_started": 580, "reported_tokens": 11370905, "calls_with_known_usage": 578,
    "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
PRIOR_GUARD, PREPARE = runner.prior_guard, runner.prepare

@pytest.fixture(autouse=True)
def no_real_network_or_runtime(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("independent v15 test cannot contact provider or acquire real parent runtime")
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
    assert "native_goal_document" not in body and "native_goal_evidence_view" in body
    assert "reference_fulltext" not in body
    return value


def replay(tmp_path, monkeypatch, causal_scenario, modes=None):
    inputs, profile, goal, opening, bundle, ids, native = deepcopy(causal_scenario)
    bundle["native_drama_audit"]["closed_scope_findings"] = []
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
                elif current in ("source", "drama"):
                    value = deepcopy(bundle["native_" + current + "_audit"])
                    for field in ("goal_sha256", "audit_context_sha256"):
                        value[field] = structured_schema["properties"][field]["const"]
                    value["schema"] = structured_schema["properties"]["schema"]["const"]
                    if current == "drama":
                        current_goal = runner.read(sorted((root / "goals").glob("native_*.json"))[-1])
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
        stage_limits={"goal_plan": 4, "goal_audit": 6, "complete_script": 3, "full_review": 6},
        client_factory_builder=factory, quota_state=None)
    runtime.prepare()
    runner.write(root / "INPUTS.json", inputs, True)
    runner.write(root / "USER_SCOPE.json", {"stage_limits": runtime.stage_limits}, True)
    runner.write(root / "INHERITED_NATIVE_GOAL.json", goal, True)
    runner.write(root / "INHERITED_DIAGNOSTICS.json", {"independent_failure_quotes": "合成失败机制，不含旧整篇剧情"}, True)
    prepared = runner.workflow.prepare_goal_request(runner.fresh_planning_inputs(inputs,
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


def test_fresh_first_request_has_no_old_goal_template_then_current_native_failure_revises_whole_goal(
        tmp_path, monkeypatch, causal_scenario):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario, {("drama", 1): "commitment_fail"})
    result = runner.run()
    assert result["status"] == "text_ready_for_director", result
    assert [phase(r) for r in sends] == ["goal_plan", "source", "commitment", "drama", "goal_plan", "source", "commitment", "drama",
        "opening_setup", "complete_script", "semantic", "physical"]
    first = json.loads(sends[0]["messages"][1]["content"])
    assert "fresh_reconception_context" in first
    assert not {"previous_complete_document", "revision_diagnostics"} & set(first)
    assert first["reference_fulltext"] == runner.read(root / "INPUTS.json")["reference_fulltext"]
    second = json.loads(sends[4]["messages"][1]["content"])
    first_goal = runner.read(root / "goals/native_01.json")
    assert second["previous_complete_document"] == first_goal
    assert "fresh_reconception_context" not in second
    assert second["revision_diagnostics"]["complete_same_source_goal_audits"][2]["accepted"] is False
    assert result["inherited_goal_candidates_used"] == 19 and result["cumulative_goal_candidates_used"] == 21
    assert [row["label"] for row in runner.read(runtime.ledger)["calls"] if row["label"].startswith("goal_plan_")] == ["goal_plan_20", "goal_plan_21"]
    spend = runtime.summary()
    assert spend["effective_calls_started"] == 592 and spend["effective_reported_tokens"] == 11372105
    assert spend["effective_calls_with_known_usage"] == 590
    assert spend["unknown_token_reservations"] == 93117 and spend["historical_pending_ordinals"] == [70, 160]
    assert not spend["old_budget_reset"]
    assert result["old_director_capacity"] == {"used": 7, "limit": 7, "remaining": 0}
    handoff = runner.read(root / "TEXT_HANDOFF.json")
    assert handoff["native_goal"] == runner.read(root / "goals/native_02.json")
    assert handoff["native_goal_audit"]["native_commitment_audit"] == runner.read(root / "goals/commitment_native_audit_02.json")
    assert handoff["native_full_review_bundle"]["schema"] == runner.reviews.BUNDLE_VERSION
    assert runner.reviews.VERSION == "creative_split_full_review_part/v3"
    assert sends[-2]["structured_schema"]["properties"]["schema"]["const"] == runner.reviews.VERSION
    assert not handoff["media_authorized"] and not handoff["production_dispatch_eligible"]
    assert not result["human_quality_approved"] and not result["creative_quality_passed"]
    assert_no_reentry(runtime, root, sends)


def test_new_scope_bounds_two_plans_two_setups_three_bodies_six_reviews_without_reset(
        tmp_path, monkeypatch, causal_scenario):
    modes = {("drama", 1): "commitment_fail", ("opening_setup", 1): "contract_fail",
        ("physical", 1): "fail", ("physical", 2): "fail"}
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario, modes)
    result = runner.run()
    assert result["status"] == "text_ready_for_director", result
    spend = runtime.summary()
    assert spend["stage_calls"] == {"goal_plan": 4, "goal_audit": 6, "complete_script": 3, "full_review": 6}
    assert spend["effective_calls_started"] == 599 and spend["effective_reported_tokens"] == 11372805
    assert runner.read(runtime.ledger)["starting_spend"] == INHERITED
    assert result["cumulative_goal_candidates_used"] == 21 and result["opening_setup_calls"] == 2
    assert not (root / "goals/native_03.json").exists() and not (root / "scripts/version_04").exists()
    assert result["old_director_capacity"]["remaining"] == 0
    assert_no_reentry(runtime, root, sends)


@pytest.mark.parametrize("part,mode", [
    ("goal_plan", "transport_unknown"), ("goal_plan", "usage_unknown"), ("goal_plan", "truncated"),
    ("drama", "transport_unknown"), ("drama", "commitment_unknown"),
])
def test_unknown_or_incomplete_new_result_does_not_use_second_goal_or_restart(tmp_path, monkeypatch, causal_scenario, part, mode):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario, {(part, 1): mode})
    result = runner.run()
    assert [phase(r) for r in sends] == (["goal_plan"] if part == "goal_plan" else ["goal_plan", "source", "commitment", "drama"])
    assert result["status"] in {"halt_goal_interface_or_unknown", "halt_goal_audit_interface_or_unknown", "halt_goal_audit_uncertain"}
    assert result["cumulative_goal_candidates_used"] == 20
    assert not (root / "goals/native_02.json").exists() and not (root / "TEXT_HANDOFF.json").exists()
    assert_no_reentry(runtime, root, sends)


def test_two_known_complete_goal_contract_failures_exhaust_only_new_bound(tmp_path, monkeypatch, causal_scenario):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario,
        {("goal_plan", 1): "contract_fail", ("goal_plan", 2): "contract_fail"})
    result = runner.run()
    assert result["status"] == "halt_goal_content_capacity_exhausted"
    assert [phase(r) for r in sends] == ["goal_plan", "goal_plan"]
    assert result["cumulative_goal_candidates_used"] == 21
    assert not (root / "goals/native_03.json").exists()
    assert_no_reentry(runtime, root, sends)


@pytest.mark.parametrize("mode", ["unknown", "masked_fail", "missing_commitments", "mixed_context",
    "mixed_goal", "usage_unknown", "truncated"])
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
    parent = tmp_path / "known580-parent"
    limits = {"goal_plan": 4, "goal_audit": 4, "complete_script": 3, "full_review": 6}
    summary = {"stage_calls": {"goal_plan": 3, "goal_audit": 2, "complete_script": 1, "full_review": 1},
        "stage_limits": limits, "effective_calls_started": 580,
        "effective_reported_tokens": 11370905, "effective_calls_with_known_usage": 578,
        "new_unknown_token_reservations": 0, "historical_pending_ordinals": [70, 160],
        "unknown_token_reservations": 93117}
    rows = []
    model = "MiniMax-M3.1-Flash-Preview"
    stages = {574: "goal_plan", 575: "goal_plan", 576: "goal_audit", 577: "goal_audit",
        578: "goal_plan", 579: "complete_script", 580: "full_review"}
    for ordinal in range(574, 581):
        path = parent / f"native{ordinal}.json"
        runner.write(path, {"status": "contract_rejected" if ordinal in (574, 580) else "contract_valid",
            "ordinal": ordinal, "output": {"native": ordinal}, "request": {"stage": stages[ordinal], "model": model},
            "response_metadata": {"http_status_code": 200, "response_body_complete": True,
                "finish_reason": "tool_calls", "total_tokens": 1, "output_mode": "tool_call",
                "requested_model": model, "response_model": model}})
        rows.append({"ordinal": ordinal, "receipt": path.name, "receipt_sha256": runner.sha_file(path)})
    runner.write(parent / "CALL_LEDGER.json", {"calls": rows})
    runner.write(parent / "USER_SCOPE.json", {"local_goal_candidates_limit": 2,
        "local_opening_setup_limit": 2, "inherited_goal_candidates_used": 17,
        "cumulative_goal_candidates_this_run_maximum": 19, "stage_limits": limits})
    runner.write(parent / "STATE.json", {"status": "halt_full_review_contract_requires_pipeline_diagnosis",
        "review_part": "semantic", "receipt_ordinal": 580, "spend": deepcopy(summary),
        "cumulative_goal_candidates_used": 19, "opening_setup_calls": 1})
    monkeypatch.setattr(runner, "PREFLIGHT_PARENT", parent)
    monkeypatch.setattr(runner, "PARENT_STATE", parent / "STATE.json")
    runtime = SimpleNamespace(ledger=parent / "CALL_LEDGER.json", summary=Mock(return_value=deepcopy(summary)))
    monkeypatch.setattr(runner.previous, "get_runtime", Mock(return_value=runtime))
    return parent, summary, runtime


def test_parent_known_terminal580_is_verified_without_changing_raw_receipts_or_state(tmp_path, monkeypatch):
    parent, summary, runtime = parent_fixture(tmp_path, monkeypatch)
    before = {path: path.read_bytes() for path in parent.glob("*.json")}
    assert PRIOR_GUARD() == summary
    assert runtime.summary.call_count == 1
    assert {path: path.read_bytes() for path in before} == before
    assert runner.read(parent / "native580.json")["status"] == "contract_rejected"


@pytest.mark.parametrize("change", ["ordinal", "state_status", "receipt_identity", "spend", "candidate_count", "usage_unknown", "truncation"])
def test_parent_unknown_changed_or_nonterminal580_cannot_authorize_fresh_new_scope(tmp_path, monkeypatch, change):
    parent, _, runtime = parent_fixture(tmp_path, monkeypatch)
    if change == "ordinal":
        ledger = runner.read(runtime.ledger)
        ledger["calls"][-1]["ordinal"] = 581
        runner.write(runtime.ledger, ledger)
    elif change in ("receipt_identity", "usage_unknown", "truncation"):
        path = parent / "native580.json"
        receipt = runner.read(path)
        if change == "receipt_identity":
            receipt["output"] = {"manually_patched_audit": True}
        elif change == "usage_unknown":
            receipt["response_metadata"]["total_tokens"] = None
        else:
            receipt["response_metadata"]["finish_reason"] = "length"
        runner.write(path, receipt)
        if change != "receipt_identity":
            ledger = runner.read(runtime.ledger)
            ledger["calls"][-1]["receipt_sha256"] = runner.sha_file(path)
            runner.write(runtime.ledger, ledger)
    else:
        state = runner.read(parent / "STATE.json")
        if change == "state_status":
            state["status"] = "goal_received"
        elif change == "spend":
            state["spend"]["effective_reported_tokens"] -= 1
        else:
            state["cumulative_goal_candidates_used"] = 18
        runner.write(parent / "STATE.json", state)
    with pytest.raises(ValueError):
        PRIOR_GUARD()
    assert not (parent / "NEW_RUN_CLAIM.json").exists()


@pytest.mark.parametrize("change", ["inputs", "profile", "diagnosis", "actual_request", "saved_preview"])
def test_fresh_authorization_four_identities_and_saved_preview_reject_drift_before_claim(tmp_path, monkeypatch, change):
    from scripts import creative_flat_lineage_guard_v1 as lineage
    project, parent, root = tmp_path / "project", tmp_path / "project/parent", tmp_path / "project/new-run"
    authority, approval, claim = project / "old-authority.json", project / "grant/USER_CONTINUATION.json", project / "grant/CLAIM.json"
    profile_path = project / "profile.json"
    preview_path = project / "data/qa/creative_review_relation_focus_20261014/REVIEW_RELATION_REQUEST_PREVIEW_v1.json"
    seed, diagnostic = {"native": "exact575-local-only"}, {"qualified_mechanisms": "original failure evidence"}
    inputs, profile = {"source": "original authority"}, {"writer": "same exact model"}
    prepared = {"request": {"source": "exact fresh compiled preview"}, "wire": {"source": "exact fresh compiled preview"}}
    for key, value in {"PROJECT": project, "PREFLIGHT_PARENT": parent, "ROOT": root,
            "APPROVAL": approval, "CLAIM": claim, "PROFILE": profile_path,
            "PARENT_STATE": parent / "STATE.json"}.items():
        monkeypatch.setattr(runner, key, value)
    monkeypatch.setattr(runner.previous, "APPROVAL", authority)
    runner.write(authority, {"human_authorized": True, "user_quote": "minimax随便追加"})
    runner.write(parent / "STATE.json", {"status": "halt_full_review_contract_requires_pipeline_diagnosis",
        "review_part": "semantic", "receipt_ordinal": 580, "cumulative_goal_candidates_used": 19,
        "spend": {"effective_calls_started": 580, "effective_reported_tokens": 11370905,
        "effective_calls_with_known_usage": 578, "historical_pending_ordinals": [70, 160], "unknown_token_reservations": 93117}})
    runner.write(parent / "receipt575.json", {"output": seed})
    runner.write(parent / "CALL_LEDGER.json", {"calls": [{"ordinal": 575, "receipt": "receipt575.json"}]})
    runner.write(parent / "INPUTS.json", inputs)
    runner.write(profile_path, profile)
    runner.write(approval, {"human_authorized": True, "user_quote": "minimax随便追加",
        "parent_ledger_sha256": runner.sha_file(parent / "CALL_LEDGER.json"), "parent_goal_candidates_used": 19,
        "authority_source_sha256": runner.sha_file(authority), **runner.authorization_request_identity(diagnostic, prepared)})
    runner.write(preview_path, {"prepared": prepared})
    diag_mock, request_mock = Mock(return_value=deepcopy(diagnostic)), Mock(return_value=deepcopy(prepared))
    if change == "inputs":
        runner.write(parent / "INPUTS.json", {"source": "different frozen authority"})
    elif change == "profile":
        runner.write(profile_path, {"writer": "changed model profile"})
    elif change == "diagnosis":
        diag_mock.return_value["qualified_mechanisms"] = "changed qualified evidence"
    elif change == "actual_request":
        request_mock.return_value["request"]["source"] = "different actual fresh request"
    else:
        runner.write(preview_path, {"prepared": {"request": "changed saved fresh preview"}})
    before = {path: path.read_bytes() for path in project.rglob("*.json")}
    monkeypatch.setattr(lineage, "build_lineage_certificate", Mock(return_value={"offline_certificate": True}))
    monkeypatch.setattr(runner, "verify_seed_native", Mock(return_value={"ordinal": 575}))
    monkeypatch.setattr(runner, "build_revision_diagnostics", diag_mock)
    monkeypatch.setattr(runner.parent, "source_gate", Mock(return_value={"offline_gate": True}))
    monkeypatch.setattr(runner.workflow, "prepare_goal_request", request_mock)
    writes = Mock(side_effect=AssertionError("fresh drift must reject before every claim or artifact write"))
    runtimes = Mock(side_effect=AssertionError("drift cannot acquire production runtime"))
    monkeypatch.setattr(runner, "write", writes)
    monkeypatch.setattr(runner, "get_runtime", runtimes)
    with pytest.raises(ValueError, match="authorization.*changed"):
        PREPARE()
    assert writes.call_count == runtimes.call_count == 0
    assert not root.exists() and not claim.exists()
    assert {path: path.read_bytes() for path in before} == before


@pytest.fixture
def local_binding(tmp_path, monkeypatch):
    project, parent = tmp_path / "binding-project", tmp_path / "binding-project/parent"
    authority, approval, claim = project / "authority.json", project / "grant/USER_CONTINUATION.json", project / "grant/CLAIM.json"
    profile = project / "profile.json"
    preview = project / "data/qa/creative_review_relation_focus_20261014/REVIEW_RELATION_REQUEST_PREVIEW_v1.json"
    seed, diagnostic = {"native": "exact575-local-only"}, {"qualified_failed_mechanisms": "known exact native evidence"}
    for key, value in {"PROJECT": project, "PREFLIGHT_PARENT": parent, "APPROVAL": approval, "CLAIM": claim,
            "ROOT": project / "run", "PROFILE": profile, "PARENT_STATE": parent / "STATE.json"}.items():
        monkeypatch.setattr(runner, key, value)
    monkeypatch.setattr(runner.previous, "APPROVAL", authority)
    runner.write(authority, {"human_authorized": True, "user_quote": "minimax随便追加"})
    runner.write(parent / "STATE.json", {"status": "halt_full_review_contract_requires_pipeline_diagnosis",
        "review_part": "semantic", "receipt_ordinal": 580, "cumulative_goal_candidates_used": 19,
        "spend": {"effective_calls_started": 580, "effective_reported_tokens": 11370905}})
    runner.write(parent / "receipt575.json", {"output": seed})
    runner.write(parent / "CALL_LEDGER.json", {"calls": [{"ordinal": 575, "receipt": "receipt575.json"}]})
    runner.write(parent / "INPUTS.json", {"source": "original authority"})
    runner.write(profile, {"writer": "same exact model"})
    prepared = {"request": {"stage": "goal_plan", "fresh_input": "same fresh compiled prompt"}, "local_manifest": "same"}
    guard, diagnosis, prepare = Mock(return_value={"known": True}), Mock(return_value=deepcopy(diagnostic)), Mock(return_value=deepcopy(prepared))
    monkeypatch.setattr(runner, "prior_guard", guard)
    monkeypatch.setattr(runner, "verify_seed_native", Mock(return_value={"ordinal": 575, "semantic_approved": False}))
    monkeypatch.setattr(runner, "build_revision_diagnostics", diagnosis)
    monkeypatch.setattr(runner.workflow, "prepare_goal_request", prepare)
    monkeypatch.setattr(runner, "get_runtime", Mock(side_effect=AssertionError("authorizer cannot dispatch")))
    monkeypatch.setattr(runner, "now", Mock(side_effect=["first-local-time", "later-local-time"] * 3))
    originals = {path: path.read_bytes() for path in project.rglob("*.json")}
    return {"project": project, "approval": approval, "claim": claim, "preview": preview,
        "originals": originals, "guard": guard, "diagnosis": diagnosis, "prepare": prepare}


def test_fresh_authorizer_reentry_preserves_binding_and_restores_only_missing_local_preview(local_binding):
    local = local_binding
    authorizer.main()
    approval_bytes, preview_bytes = local["approval"].read_bytes(), local["preview"].read_bytes()
    authorizer.main()
    assert local["approval"].read_bytes() == approval_bytes and local["preview"].read_bytes() == preview_bytes
    local["preview"].unlink()  # Synthetic artifact, not an original production record.
    authorizer.main()
    assert local["approval"].read_bytes() == approval_bytes and local["preview"].read_bytes() == preview_bytes
    bound = runner.read(local["approval"])
    assert bound["parent_goal_candidates_used"] == 19
    assert not bound["old_ledger_reset"] and not bound["media_authorized"] and not bound["publish_authorized"]
    assert bound["writer_total_call_user_limit"] is None and not bound["automatic_transport_retry"]
    assert local["guard"].call_count == 3 and not local["claim"].exists() and not runner.ROOT.exists()
    assert {path: path.read_bytes() for path in local["originals"]} == local["originals"]


@pytest.mark.parametrize("drift", ["diagnosis", "request"])
def test_fresh_authorizer_missing_preview_recovery_rejects_changed_diagnosis_or_actual_request(local_binding, drift):
    local = local_binding
    authorizer.main()
    original = local["approval"].read_bytes()
    local["preview"].unlink()
    if drift == "diagnosis":
        local["diagnosis"].return_value = {"qualified_failed_mechanisms": "changed native evidence"}
    else:
        local["prepare"].return_value["request"]["fresh_input"] = "different fresh actual request"
    with pytest.raises(ValueError, match="existing text authorization differs"):
        authorizer.main()
    assert local["approval"].read_bytes() == original and not local["preview"].exists()
    assert not local["claim"].exists() and not runner.ROOT.exists()
    assert {path: path.read_bytes() for path in local["originals"]} == local["originals"]


