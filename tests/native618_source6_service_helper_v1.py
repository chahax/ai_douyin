"""Independent fresh-reconception coordinator; native synthetic service only."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import run_goal_context_text_production_v27 as runner
from scripts import record_legal_usage_continuation_v1 as authorizer
from scripts import creative_goal_context_dispatch_v11 as adapter
from scripts import creative_bounded_format_role_clients_v1 as bounded
from scripts import creative_evidenced_role_clients_v1 as evidenced
from tests import test_goal_context_text_production_v4 as helpers
from tests.test_creative_split_full_review_contract_v4 import synthetic_consistency
from tests.test_creative_goal_legal_usage_source_audit_v6 import synthetic_source, add_legal_usage as add_usage
from scripts import record_legal_usage_diagnosis_v1 as diagnosis_records
from src.content_factory import creative_goal_legal_usage_source_audit_v6 as legal_audit
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests.test_creative_goal_commitment_audit_v1 import synthetic as synthetic_commitment

INHERITED = {"calls_started": 619, "reported_tokens": 12930923, "calls_with_known_usage": 617,
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
    fixed_catalog=runner.workflow.fixed_legal_claim_catalog(inputs)
    for claim in goal["claims"]:
        if claim["kind"]=="verified_legal":
            selected=next(ref for ref in claim["origin_ids"] if ref in fixed_catalog)
            claim.update(origin_ids=[selected],text=fixed_catalog[selected]["text"])
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
                    if mode == "unchanged_original":
                        value = deepcopy(goal)
                    if mode == "fixed_text_drift":
                        next(row for row in value["claims"] if row["kind"]=="verified_legal")["text"] += " added premise"
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
                        ref=value["source_observations"][0]["source_ref"]
                        usage=add_usage(value,current_goal,ref,relation="unknown" if mode=="legal_unknown" else "contradicts")
                        if mode!="legal_unknown":
                            usage["authority_refs"]=[next(iter(legal_audit.build_authority_catalog(authority)))]
                    elif mode=="negative_overlap":
                        value["speech_act_by_ref"][value["source_observations"][0]["source_ref"]]="factual_description"
                    elif mode=="missing_scan":
                        value["source_observations"].pop(0)
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
                    from tests.test_creative_opening_setup_contract_v4 import synthetic_v4
                    value = synthetic_v4(value)
                    if mode == "null_orientation":
                        next(row for row in value["props"].values() if row["kind"] != "absent")["orientation"] = None
                    elif mode == "contract_fail":
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
        stage_limits={"goal_plan": 2, "goal_audit": 3, "complete_script": 3, "full_review": 6},
        client_factory_builder=factory, quota_state=None)
    runtime.prepare()
    runner.write(root / "INPUTS.json", inputs, True)
    runner.write(root / "USER_SCOPE.json", {"stage_limits": runtime.stage_limits}, True)
    runner.write(root / "INHERITED_NATIVE_GOAL.json", goal, True)
    runner.write(root / "goals/native_01.json", goal, True)
    prepared = runner.prepare_source_audit(inputs, profile, goal)
    runner.write(root / "FIRST_NATIVE_SOURCE_REQUEST_PREVIEW.json", prepared, True)
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
