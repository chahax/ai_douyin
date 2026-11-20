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
from scripts import preview_goal_context_workflow_v3 as preview
from scripts import run_goal_context_text_production_v4 as previous
from src.content_factory import creative_goal_context_workflow_v4 as workflow
from src.content_factory import creative_goal_source_contract_v3 as goals
from src.content_factory import creative_full_review_contract_v3 as reviews
from src.content_factory import creative_fresh_legal_text_pipeline_v1 as legacy
from src.content_factory import creative_studio_task_store_v1 as tasks

VERSION = "goal_context_text_production/v5"
ROOT = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_04"
GRANT = "goal_audit_citation_continuation_20261013"
PREFLIGHT_PARENT = previous.ROOT
CLAIM = PROJECT / "data/creative_fresh_background_claims" / GRANT / "CLAIM.json"
APPROVAL = CLAIM.parent / "USER_CONTINUATION.json"
PROFILE = PROJECT / "config/creative_goal_context_model_profile_v2.json"
PLAN = PROJECT / "docs/CREATIVE_GOAL_AUDIT_CITATION_REPAIR_PLAN_20261013.md"
read, write, digest, sha_file, now = control.read, control.write, control.digest, control.sha_file, control.now


def prior_guard():
    previous.prior_guard()
    prior_runtime = previous.get_runtime()
    prior_runtime.inherited_guard()
    ledger = read(prior_runtime.ledger)
    prior_runtime.check(ledger)
    if [r["ordinal"] for r in ledger["calls"]] != [534, 535, 536, 537]:
        raise ValueError("spent parent ledger does not match reconciled calls 534-537")
    for row in ledger["calls"]:
        if sha_file(PREFLIGHT_PARENT / row["receipt"]) != row["receipt_sha256"]:
            raise ValueError("previous native response changed")
        receipt = read(PREFLIGHT_PARENT / row["receipt"])
        if not original.classify_receipt(receipt)[0]:
            raise ValueError("parent response must be known; never redispatch")
    summary = prior_runtime.summary()
    if summary["stage_calls"] != {"goal_plan": 3, "goal_audit": 1, "complete_script": 0, "full_review": 0}:
        raise ValueError("unexpected parent stage consumption")
    if read(PREFLIGHT_PARENT / "STATE.json")["status"] != "halt_goal_audit_contract_requires_pipeline_diagnosis":
        raise ValueError("parent run must be terminal, not concurrently active")
    return summary


def models(profile):
    return {role: {key: profile[role][key] for key in ("provider", "model", "base_url")}
            for role in ("writer", "director")}


def verify_seed_native(seed):
    ledger = read(PREFLIGHT_PARENT / "CALL_LEDGER.json")
    rows = [row for row in ledger["calls"] if row["ordinal"] == 536]
    if len(rows) != 1:
        raise ValueError("single original 536 receipt required")
    row = rows[0]
    path = PREFLIGHT_PARENT / row["receipt"]
    if sha_file(path) != row["receipt_sha256"]:
        raise ValueError("original 536 receipt changed")
    receipt = read(path)
    if (receipt["status"] != "contract_valid" or not repairable(receipt)
            or receipt.get("request", {}).get("stage") != "goal_plan"
            or seed != receipt.get("output")):
        raise ValueError("seed differs from complete contract-valid native 536 output")
    return {"ordinal": 536, "receipt_path": str(path), "receipt_sha256": sha_file(path),
            "native_goal_sha256": digest(seed), "semantic_approved": False}


def get_runtime():
    from scripts.creative_goal_context_dispatch_v3 import GoalContextRuntime
    freeze = read(ROOT / "PRODUCTION_FREEZE.json")
    profile = read(PROFILE)
    def guard():
        prior_guard()
        parent.source_gate()
        if sha_file(PREFLIGHT_PARENT / "CALL_LEDGER.json") != freeze["parent_ledger_sha256"]:
            raise ValueError("parent consumption ledger changed")
        if verify_seed_native(read(ROOT / "INHERITED_NATIVE_GOAL.json")) != freeze["seed_native_identity"]:
            raise ValueError("seed native receipt binding changed")
        if (read(CLAIM)["root"] != str(ROOT)
                or sha_file(APPROVAL) != freeze["continuation_authorization_sha256"]
                or sha_file(CLAIM) != freeze["global_claim_sha256"]):
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
    consumed = prior_guard()
    approval = read(APPROVAL)
    if (approval.get("human_authorized") is not True or approval.get("user_quote") != "minimax随便追加"
            or approval.get("parent_ledger_sha256") != sha_file(PREFLIGHT_PARENT / "CALL_LEDGER.json")
            or approval.get("parent_goal_candidates_used") != 6
            or approval.get("authority_source_sha256") != sha_file(previous.APPROVAL)):
        raise ValueError("explicit continuing user authorization and unchanged spent lineage required")
    inputs = read(PREFLIGHT_PARENT / "INPUTS.json")
    seed = read(PREFLIGHT_PARENT / "goals/native_03.json")
    seed_identity = verify_seed_native(seed)
    workflow._validate_planning_input(inputs, seed)
    source_check = parent.source_gate()
    inherited = {"calls_started": consumed["effective_calls_started"],
        "reported_tokens": consumed["effective_reported_tokens"],
        "calls_with_known_usage": consumed["effective_calls_with_known_usage"],
        "unknown_token_reservations": consumed["unknown_token_reservations"],
        "pending_ordinals": consumed["historical_pending_ordinals"]}
    scope = {"schema": VERSION + "/user_scope", "grant_id": GRANT,
        "user_quote": approval["user_quote"], "writer_total_call_user_limit": None,
        "stage_limits": {"goal_plan": 2, "goal_audit": 3, "complete_script": 3, "full_review": 3},
        "stage_limits_are_local_run_safety_bounds": True,
        "inherited_goal_candidates_used": 6, "local_goal_candidates_limit": 2,
        "cumulative_goal_candidates_this_run_maximum": 8,
        "seed_goal_ordinal": 536, "seed_goal_semantic_approved": False,
        "old_goal_allowance_reset": False, "deepseek_scope": "few necessary source and whole-text reviews",
        "content_revision_limit": 2, "old_m31_one_writer_one_review_used": 2,
        "old_director_candidates_used": 7, "old_director_candidates_limit": 7,
        "additional_director_candidates": 0, "media_authorized": False, "publish_authorized": False,
        "automatic_transport_retry": False, "new_format_recovery_claimed": False,
        "max_total_tokens": None, "starting_spend": inherited,
        "parent_ledger_sha256": sha_file(PREFLIGHT_PARENT / "CALL_LEDGER.json")}
    write(CLAIM, {"schema": VERSION + "/continuation_claim", "grant_id": GRANT,
        "root": str(ROOT), "created_at": now(), "parent_root": str(PREFLIGHT_PARENT),
        "authorization_sha256": sha_file(APPROVAL),
        "parent_ledger_sha256": scope["parent_ledger_sha256"], "inherited_goal_candidates_used": 6,
        "old_allowance_reset": False}, True)
    ROOT.mkdir(parents=True)
    write(ROOT / "USER_SCOPE.json", scope, True)
    write(ROOT / "INPUTS.json", inputs, True)
    write(ROOT / "INHERITED_NATIVE_GOAL.json", seed, True)
    write(ROOT / "SOURCE_GATE.json", source_check, True)
    # Freeze every old production dependency plus all new independent modules.
    paths = set(read(PREFLIGHT_PARENT / "PRODUCTION_FREEZE.json")["files"])
    paths.update(str(p.resolve()) for p in (Path(__file__), PROFILE, PLAN,
        Path(workflow.__file__), Path(goals.__file__), Path(reviews.__file__),
        PROJECT / "src/content_factory/creative_stage_context_v3.py", APPROVAL,
        PROJECT / "src/content_factory/creative_goal_audit_citation_contract_v1.py",
        PROJECT / "scripts/creative_goal_context_dispatch_v3.py", Path(clients.__file__),
        PREFLIGHT_PARENT / "RUN_CLAIM.json", PREFLIGHT_PARENT / "CALL_LEDGER.json",
        ROOT / "USER_SCOPE.json", ROOT / "INPUTS.json", ROOT / "INHERITED_NATIVE_GOAL.json", ROOT / "SOURCE_GATE.json"))
    freeze = {"schema": VERSION + "/freeze", "inherited": inherited,
        "seed_native_identity": seed_identity,
        "models": models(read(PROFILE)), "global_claim_sha256": sha_file(CLAIM),
        "continuation_authorization_sha256": sha_file(APPROVAL),
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
    # Cached native response is read-only, before any SQLite service attempt.
    # It is never charged or claimed twice under a new label.
    for row in read(runtime.ledger)["calls"]:
        original_receipt = runtime.effective_receipt(row)
        if original_receipt["request_sha256"] == digest(request):
            return runtime.dispatch(label, request, validator)
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


def script_source_inputs(inputs):
    """A goal revision is not a previous screenplay for the author to repair."""
    return {key: deepcopy(value) for key, value in inputs.items()
        if key not in ("previous_complete_document", "revision_diagnostics",
                       "revision_requirements", "complete_script_feasibility_diagnostics")}


def state(runtime, status, **extra):
    result = {"schema": VERSION + "/state", "status": status, "updated_at": now(),
        "text_ready_for_director": False, "human_quality_approved": False, "creative_quality_passed": False,
        "media_authorized": False, "old_director_capacity": {"used": 7, "limit": 7, "remaining": 0},
        "spend": runtime.summary(), **extra}
    result["inherited_goal_candidates_used"] = 6
    result["cumulative_goal_candidates_used"] = 6 + result["spend"]["stage_calls"]["goal_plan"]
    write(ROOT / "STATE.json", result)
    return result


def run():
    runtime = get_runtime()
    runtime.inherited_guard()
    if (ROOT / "RUN_CLAIM.json").exists():
        raise FileExistsError("existing run claim; inspect without provider restart")
    write(ROOT / "RUN_CLAIM.json", {"schema": VERSION + "/claim", "started_at": now(),
        "pid": os.getpid(), "automatic_restart": False}, True)
    # A completed run claim is not a new authorization. No cached-stage replay run.
    if read(ROOT / "RUN_CLAIM.json")["pid"] != os.getpid() or read(runtime.ledger)["calls"]:
        raise RuntimeError("run already claimed; inspect original receipts")
    inputs, profile = read(ROOT / "INPUTS.json"), read(PROFILE)
    ids = workflow.origin_ids(inputs)
    goal_inputs = deepcopy(inputs)
    goal = read(ROOT / "INHERITED_NATIVE_GOAL.json")
    workflow._validate_planning_input(inputs, goal)
    audit = None
    goal_ordinal = 536
    prepared_seed = workflow.prepare_goal_audit_request(inputs, profile, goal)
    seed_context_sha = prepared_seed["request"]["structured_schema"]["properties"]["audit_context_sha256"]["const"]
    seed_review = invoke(runtime, "goal_audit_seed_536", prepared_seed,
        lambda value: workflow.validate_goal_audit(value, goal, context_sha256=seed_context_sha))
    if seed_review.get("cached_response_read_only"):
        return state(runtime, "halt_cached_seed_audit_no_new_claim", receipt_ordinal=seed_review["ordinal"])
    if not repairable(seed_review):
        return state(runtime, "halt_seed_audit_interface_or_unknown", receipt_ordinal=seed_review["ordinal"])
    if seed_review["status"] != "contract_valid":
        return state(runtime, "halt_seed_audit_contract_requires_pipeline_diagnosis", receipt_ordinal=seed_review["ordinal"])
    seed_decision = seed_review["validation"]
    write(ROOT / "goals/seed_audit_decision_536.json", seed_decision, True)
    if seed_decision["uncertainties"]:
        return state(runtime, "halt_seed_audit_uncertain", goal_decision=seed_decision)
    if seed_decision["accepted"]:
        audit = seed_review["output"]
    else:
        goal_inputs = {**deepcopy(inputs), "previous_complete_document": goal,
            "revision_diagnostics": {"complete_same_source_goal_audit": seed_decision}}
    for index in ([] if audit is not None else range(1, 3)):
        planned = workflow.prepare_goal_request(goal_inputs, profile)
        def goal_validator(value):
            return workflow._validate_planning_input(inputs, value)
        receipt = invoke(runtime, f"goal_plan_{index+6:02}", planned,
            goal_validator)
        if receipt.get("cached_response_read_only"):
            return state(runtime, "halt_no_new_native_goal_progress", receipt_ordinal=receipt["ordinal"])
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
        if audited.get("cached_response_read_only"):
            return state(runtime, "halt_cached_goal_audit_no_new_claim", receipt_ordinal=audited["ordinal"])
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
    base_script_inputs = script_source_inputs(inputs)
    script_inputs = deepcopy(base_script_inputs)
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
        if receipt.get("cached_response_read_only"):
            return state(runtime, "halt_no_new_native_script_progress", receipt_ordinal=receipt["ordinal"])
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
            script_inputs = {**deepcopy(base_script_inputs), "previous_complete_document": native,
                "revision_diagnostics": diagnosis(receipt)}
            continue
        prepared_review = workflow.prepare_full_review_request(inputs, profile, native, views)
        reviewed = invoke(runtime, f"full_review_{index:02}", prepared_review,
            lambda v: reviews.validate_full_review(v, compiled, views["brief"], views["plan"],
                prepared_review["review_legal_context"], goal_contract=goal))
        if reviewed.get("cached_response_read_only"):
            return state(runtime, "halt_cached_full_review_no_new_claim", receipt_ordinal=reviewed["ordinal"])
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
        script_inputs = {**deepcopy(base_script_inputs), "previous_complete_document": native,
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
