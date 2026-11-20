"""New native goal -> audited full screenplay, preserving the spent old lineage.

Only this new text grant is dispatched. No media, publication or old-call retry.
"""
from __future__ import annotations
import argparse
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import creative_m31_flash_role_clients_v1 as clients
from scripts import run_m31_flash_script_test_v1 as parent
from scripts import run_fresh_legal_full_flow_v1 as original
from scripts import preview_goal_context_workflow_v2 as preview
from src.content_factory import creative_goal_context_workflow_v2 as workflow
from src.content_factory import creative_goal_source_contract_v2 as goals
from src.content_factory import creative_full_review_contract_v2 as reviews
from src.content_factory import creative_fresh_legal_text_pipeline_v1 as legacy
from src.content_factory import creative_studio_task_store_v1 as tasks

VERSION = "goal_context_text_production/v2"
ROOT = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_01"
GRANT = "goal_context_new_complete_text_20261013"
CLAIM = PROJECT / "data/creative_fresh_background_claims" / GRANT / "CLAIM.json"
PROFILE = PROJECT / "config/creative_goal_context_model_profile_v2.json"
PLAN = PROJECT / "docs/CREATIVE_GOAL_CONTEXT_PRODUCTION_PLAN_20261013.md"
read, write, digest, sha_file, now = control.read, control.write, control.digest, control.sha_file, control.now


def prior_guard():
    parent.old_guard()
    freeze = read(parent.ROOT / "TEST_FREEZE.json")
    for path, expected in freeze["files"].items():
        if sha_file(path) != expected:
            raise ValueError("previous frozen file changed: " + path)
    ledger = read(parent.ROOT / "CALL_LEDGER.json")
    if len(ledger["calls"]) != 2 or [r["ordinal"] for r in ledger["calls"]] != [529, 530]:
        raise ValueError("previous M31 ledger changed")
    for row in ledger["calls"]:
        if sha_file(parent.ROOT / row["receipt"]) != row["receipt_sha256"]:
            raise ValueError("previous native response changed")
        receipt = read(parent.ROOT / row["receipt"])
        if not original.classify_receipt(receipt)[0]:
            raise ValueError("previous M31 response must be known; never redispatch")
    return ledger


def models(profile):
    return {role: {key: profile[role][key] for key in ("provider", "model", "base_url")}
            for role in ("writer", "director")}


def get_runtime():
    from scripts.creative_goal_context_dispatch_v2 import GoalContextRuntime
    freeze = read(ROOT / "PRODUCTION_FREEZE.json")
    profile = read(PROFILE)
    def guard():
        prior_guard()
        parent.source_gate()
        if sha_file(parent.ROOT / "CALL_LEDGER.json") != freeze["parent_ledger_sha256"]:
            raise ValueError("parent consumption ledger changed")
        if read(CLAIM)["root"] != str(ROOT) or sha_file(CLAIM) != freeze["global_claim_sha256"]:
            raise ValueError("global authorization claim changed")
        for path, expected in freeze["files"].items():
            if sha_file(path) != expected:
                raise ValueError("new independent frozen input changed: " + path)
    return GoalContextRuntime(PROJECT, ROOT, [Path(path) for path in freeze["sources"]],
        freeze["inherited"], freeze["models"], inherited_guard=guard, profile=profile,
        stage_limits=read(ROOT / "USER_SCOPE.json")["stage_limits"], quota_state=None,
        shared_lock=PROJECT / "data/creative_fresh_background_claims/DISPATCH.lock")


def prepare():
    if ROOT.exists() or CLAIM.exists():
        raise RuntimeError("existing global grant/root; inspect original, never regrant")
    ledger = prior_guard()
    inputs, _, _, _, source_check = preview.production_inputs()
    inherited = deepcopy(ledger["starting_spend"])
    inherited.update(calls_started=530, reported_tokens=10025612, calls_with_known_usage=528,
                     unknown_token_reservations=93117, pending_ordinals=[70, 160])
    scope = {"schema": VERSION + "/user_scope", "grant_id": GRANT,
        "user_quote": "生成新的和之前的流程一样，你再次审核，不对就继续修",
        "stage_limits": {stage: 3 for stage in ("goal_plan", "goal_audit", "complete_script", "full_review")},
        "content_revision_limit": 2, "old_m31_one_writer_one_review_used": 2,
        "old_director_candidates_used": 7, "old_director_candidates_limit": 7,
        "additional_director_candidates": 0, "media_authorized": False, "publish_authorized": False,
        "automatic_transport_retry": False, "new_format_recovery_claimed": False,
        "max_total_tokens": None, "starting_spend": inherited,
        "parent_ledger_sha256": sha_file(parent.ROOT / "CALL_LEDGER.json")}
    CLAIM.parent.mkdir(parents=True, exist_ok=True)
    write(CLAIM, {"schema": VERSION + "/global_grant_claim", "grant_id": GRANT,
                  "root": str(ROOT), "created_at": now(), "scope_sha256": digest(scope)}, True)
    ROOT.mkdir(parents=True)
    write(ROOT / "USER_SCOPE.json", scope, True)
    write(ROOT / "INPUTS.json", inputs, True)
    write(ROOT / "SOURCE_GATE.json", source_check, True)
    # Freeze every old production dependency plus all new independent modules.
    paths = set(read(parent.ROOT / "TEST_FREEZE.json")["files"])
    paths.update(str(p.resolve()) for p in (Path(__file__), PROFILE, PLAN,
        Path(workflow.__file__), Path(goals.__file__), Path(reviews.__file__),
        PROJECT / "src/content_factory/creative_stage_context_v2.py",
        PROJECT / "scripts/creative_goal_context_dispatch_v2.py", Path(clients.__file__),
        ROOT / "USER_SCOPE.json", ROOT / "INPUTS.json", ROOT / "SOURCE_GATE.json"))
    freeze = {"schema": VERSION + "/freeze", "inherited": inherited,
        "models": models(read(PROFILE)), "global_claim_sha256": sha_file(CLAIM),
        "parent_ledger_sha256": scope["parent_ledger_sha256"], "sources": sorted(paths),
        "files": {path: sha_file(path) for path in sorted(paths)}, "media_authorized": False}
    write(ROOT / "PRODUCTION_FREEZE.json", freeze, True)
    result = get_runtime().prepare()
    write(ROOT / "STATE.json", {"status": "prepared", "text_ready_for_director": False,
        "human_quality_approved": False, "creative_quality_passed": False, "spend": result})
    return result


def invoke(runtime, label, prepared, validator):
    request = prepared["request"]
    clients.expected_wire_request(request)
    write(ROOT / "requests" / (label + ".json"), prepared, True)
    store = tasks.TaskStore(ROOT / "TASKS.sqlite3")
    gid = "call_" + digest({"grant": GRANT, "label": label})[:24]
    store.register_graph({"schema_version": tasks.GRAPH_SCHEMA, "graph_id": gid, "nodes": [
        {"node_id": "source", "kind": "source", "input": {"source_manifest": digest(read(runtime.ledger)["source_manifest"]),
         "request_sha256": digest(request)}, "depends_on": []},
        {"node_id": "result", "kind": "text", "input": {"label": label, "stage": request["stage"]}, "depends_on": ["source"]}]})
    scope_path = ROOT / "USER_SCOPE.json"
    auth = {"schema_version": tasks.AUTH_SCHEMA, "authorization_id": gid + ":scope", "graph_id": gid,
        "node_ids": ["result"], "scope": "text", "purpose": "dispatch",
        "source_sha256": store.snapshot(gid)["source_sha256"],
        "max_attempts": read(scope_path)["stage_limits"][request["stage"]], "prior_attempts": 0,
        "allows_content_revision": False, "evidence_ref": str(scope_path) + "#" + request["stage"],
        "evidence_sha256": sha_file(scope_path)}
    attempt = store.claim(gid, "result", {"provider_id": request["model"], "payload": request}, auth)
    receipt = runtime.dispatch(label, request, validator)
    evidence = original.verify_receipt_evidence(runtime, receipt, request)
    outbound = evidence / "request_body.raw"
    if outbound.exists() and control.strict_json(outbound.read_text(encoding="utf-8")) != clients.expected_wire_request(request):
        raise ValueError("actual request differs from verified exact mapping")
    raw_path = evidence / "response_body.raw"
    raw = raw_path.read_bytes() if raw_path.exists() else b""
    known, outcome, tool_status = original.classify_receipt(receipt)
    meta = receipt.get("response_metadata", {})
    total, http = meta.get("total_tokens"), meta.get("http_status_code")
    store.accept_result(attempt["claim_id"], {"schema_version": tasks.RESULT_SCHEMA,
        "claim_id": attempt["claim_id"], "request_sha256": attempt["request_sha256"], "service_task_id": None,
        "outcome": outcome, "result_known": known, "usage_known": type(total) is int and total >= 0,
        "usage": {"unit": "reported_tokens", "amount": total} if type(total) is int and total >= 0 else None,
        "complete": meta.get("response_body_complete") is True, "complete_end": meta.get("finish_reason") in ("stop", "tool_calls"),
        "schema_tool_status": tool_status, "contract_valid": receipt["status"] == "contract_valid" if known else None,
        "raw_receipt": {"encoding": "base64", "body": base64.b64encode(raw).decode(),
            "sha256": hashlib.sha256(raw).hexdigest(), "http_status": http if type(http) is int else None},
        "output": {"ordinal": receipt["ordinal"], "native_output": receipt.get("output")}})
    return receipt


def repairable(receipt):
    meta = receipt.get("response_metadata", {})
    return (original.classify_receipt(receipt)[0] and meta.get("output_mode") == "tool_call"
        and meta.get("requested_model") == receipt["request"]["model"]
        and meta.get("response_model") == receipt["request"]["model"]
        and isinstance(receipt.get("output"), dict) and bool(receipt["output"]))


def diagnosis(receipt):
    return {key: deepcopy(receipt[key]) for key in ("failure", "validation_error", "validation") if key in receipt}


def state(runtime, status, **extra):
    result = {"schema": VERSION + "/state", "status": status, "updated_at": now(),
        "text_ready_for_director": False, "human_quality_approved": False, "creative_quality_passed": False,
        "media_authorized": False, "old_director_capacity": {"used": 7, "limit": 7, "remaining": 0},
        "spend": runtime.summary(), **extra}
    write(ROOT / "STATE.json", result)
    return result


def run():
    runtime = get_runtime()
    runtime.inherited_guard()
    write(ROOT / "RUN_CLAIM.json", {"schema": VERSION + "/claim", "started_at": now(),
        "pid": os.getpid(), "automatic_restart": False}, True)
    # A completed run claim is not a new authorization. No cached-stage replay run.
    if read(ROOT / "RUN_CLAIM.json")["pid"] != os.getpid() or read(runtime.ledger)["calls"]:
        raise RuntimeError("run already claimed; inspect original receipts")
    inputs, profile = read(ROOT / "INPUTS.json"), read(PROFILE)
    ids = workflow.origin_ids(inputs)
    goal_inputs = deepcopy(inputs)
    goal = audit = None
    goal_ordinal = None
    for index in range(1, 4):
        planned = workflow.prepare_goal_request(goal_inputs, profile)
        def goal_validator(value):
            workflow._validate_planning_input(inputs, value)
            return goals.validate_goal_document(value, **ids)
        receipt = invoke(runtime, f"goal_plan_{index:02}", planned,
            goal_validator)
        state(runtime, "goal_received", goal_ordinal=receipt["ordinal"], goal_status=receipt["status"])
        if not repairable(receipt):
            return state(runtime, "halt_goal_interface_or_unknown", receipt_ordinal=receipt["ordinal"])
        goal = receipt["output"]
        goal_ordinal = receipt["ordinal"]
        write(ROOT / "goals" / f"native_{index:02}.json", goal, True)
        if receipt["status"] != "contract_valid":
            goal_inputs = {**deepcopy(inputs), "previous_complete_document": goal,
                "revision_diagnostics": diagnosis(receipt)}
            continue
        prepared = workflow.prepare_goal_audit_request(inputs, profile, goal)
        context_sha = prepared["request"]["structured_schema"]["properties"]["audit_context_sha256"]["const"]
        audited = invoke(runtime, f"goal_audit_{index:02}", prepared,
            lambda v: workflow.validate_goal_audit(v, goal, context_sha256=context_sha))
        if not repairable(audited):
            return state(runtime, "halt_goal_audit_interface_or_unknown", receipt_ordinal=audited["ordinal"])
        if audited["status"] != "contract_valid":
            return state(runtime, "halt_goal_audit_contract_requires_pipeline_diagnosis", receipt_ordinal=audited["ordinal"])
        verdict = audited["validation"]
        write(ROOT / "goals" / f"audit_decision_{index:02}.json", verdict, True)
        if verdict["uncertainties"]:
            return state(runtime, "halt_goal_audit_uncertain", goal_decision=verdict)
        if verdict["accepted"]:
            audit = audited["output"]
            break
        goal_inputs = {**deepcopy(inputs), "previous_complete_document": goal,
            "revision_diagnostics": {"complete_same_source_goal_audit": verdict}}
    if audit is None:
        return state(runtime, "halt_goal_content_capacity_exhausted")
    script_inputs = deepcopy(inputs)
    for index in range(1, 4):
        prepared = workflow.prepare_script_request(script_inputs, profile, goal, audit, **ids)
        views = prepared["views"]
        def script_validator(value):
            result = workflow.validate_script_document(value, views, inputs["production_preferences"])
            if not result["necessary_conditions_only"]:
                exc = ValueError("necessary timing conditions failed; complete native revision required")
                exc.detail = result["diagnostic"]
                raise exc
            return result
        receipt = invoke(runtime, f"complete_script_{index:02}", prepared, script_validator)
        if not repairable(receipt):
            return state(runtime, "halt_script_interface_or_unknown", receipt_ordinal=receipt["ordinal"])
        native = receipt["output"]
        folder = ROOT / "scripts" / f"version_{index:02}"
        write(folder / "NATIVE_SCRIPT.json", native, True)
        try:
            compiled = legacy.contract.compile_script(native, views["brief"])
            with (folder / "FULL_SCRIPT.md").open("x", encoding="utf-8") as handle:
                handle.write("完整模型原生正文，验收结论见本目录DECISION及本轮STATE；未获用户采用。\n\n" + legacy.render_script(compiled, views["brief"]))
        except (ValueError, KeyError, TypeError):
            compiled = None
        if receipt["status"] != "contract_valid":
            script_inputs = {**deepcopy(inputs), "previous_complete_document": native,
                "revision_diagnostics": diagnosis(receipt)}
            continue
        prepared_review = workflow.prepare_full_review_request(inputs, profile, native, views)
        reviewed = invoke(runtime, f"full_review_{index:02}", prepared_review,
            lambda v: reviews.validate_full_review(v, compiled, views["brief"], views["plan"],
                inputs["verified_legal_context"], goal_contract=goal))
        if not repairable(reviewed):
            return state(runtime, "halt_review_interface_or_unknown", script_path=str(folder / "FULL_SCRIPT.md"), receipt_ordinal=reviewed["ordinal"])
        if reviewed["status"] != "contract_valid":
            return state(runtime, "halt_full_review_contract_requires_pipeline_diagnosis", script_path=str(folder / "FULL_SCRIPT.md"), receipt_ordinal=reviewed["ordinal"])
        decision = reviewed["validation"]
        write(folder / "FULL_REVIEW.json", reviewed["output"], True)
        write(folder / "DECISION.json", decision, True)
        if decision["uncertainties"]:
            return state(runtime, "halt_full_review_uncertain", decision=decision, script_path=str(folder / "FULL_SCRIPT.md"))
        if decision["accepted"]:
            write(ROOT / "TEXT_HANDOFF.json", {"schema": VERSION + "/text_handoff", "native_goal": goal,
                "native_goal_audit": audit, "native_script": native, "views": views,
                "native_full_review": reviewed["output"], "decision": decision,
                "script_path": str(folder / "FULL_SCRIPT.md"), "script_ordinal": receipt["ordinal"],
                "review_ordinal": reviewed["ordinal"], "production_dispatch_eligible": False,
                "next_stage_requires_reconciled_director_lineage": True, "media_authorized": False}, True)
            return state(runtime, "text_ready_for_director", text_ready_for_director=True,
                script_path=str(folder / "FULL_SCRIPT.md"), native_goal_ordinal=goal_ordinal,
                script_ordinal=receipt["ordinal"], review_ordinal=reviewed["ordinal"], decision=decision)
        script_inputs = {**deepcopy(inputs), "previous_complete_document": native,
            "revision_diagnostics": {"complete_same_source_full_review": decision}}
    return state(runtime, "halt_script_content_capacity_exhausted")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "status"))
    args = parser.parse_args(argv)
    if args.command == "prepare":
        result = prepare()
    elif args.command == "status":
        result = read(ROOT / "STATE.json")
    else:
        try:
            result = run()
        except Exception as exc:
            write(ROOT / "EXECUTION_ERROR.json", {"status": "stopped_original_request_requires_reconciliation",
                "error_type": type(exc).__name__, "error": str(exc), "new_request_dispatched_by_recovery": False}, True)
            raise
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
