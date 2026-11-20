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
from scripts import run_goal_context_text_production_v6 as previous
from src.content_factory import creative_goal_context_workflow_v6 as workflow
from src.content_factory import creative_goal_source_contract_v4 as goals
from src.content_factory import creative_opening_setup_contract_v1 as setups
from src.content_factory import creative_full_review_contract_v3 as reviews
from src.content_factory import creative_fresh_legal_text_pipeline_v1 as legacy
from src.content_factory import creative_studio_task_store_v1 as tasks

VERSION = "goal_context_text_production/v7"
ROOT = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_06"
GRANT = "goal_setup_separation_continuation_20261013"
PREFLIGHT_PARENT = previous.ROOT
CLAIM = PROJECT / "data/creative_fresh_background_claims" / GRANT / "CLAIM.json"
APPROVAL = CLAIM.parent / "USER_CONTINUATION.json"
PROFILE = PROJECT / "config/creative_goal_context_model_profile_v2.json"
PLAN = PROJECT / "docs/CREATIVE_PLAN_SETUP_SEPARATION_PLAN_20261013.md"
CERTIFICATE = ROOT / "CERTIFIED_PARENT_LINEAGE.json"
read, write, digest, sha_file, now = control.read, control.write, control.digest, control.sha_file, control.now


def prior_guard():
    prior_runtime = previous.get_runtime()
    summary = prior_runtime.summary()  # One complete certified parent check, not four recursive checks.
    ledger = read(prior_runtime.ledger)
    if [r["ordinal"] for r in ledger["calls"]] != [539, 540]:
        raise ValueError("spent parent ledger does not match reconciled calls 539/540")
    for row in ledger["calls"]:
        if sha_file(PREFLIGHT_PARENT / row["receipt"]) != row["receipt_sha256"]:
            raise ValueError("previous native response changed")
        receipt = read(PREFLIGHT_PARENT / row["receipt"])
        if not original.classify_receipt(receipt)[0]:
            raise ValueError("parent response must be known; never redispatch")
    if summary["stage_calls"] != {"goal_plan": 2, "goal_audit": 0, "complete_script": 0, "full_review": 0}:
        raise ValueError("unexpected parent stage consumption")
    if read(PREFLIGHT_PARENT / "STATE.json")["status"] != "halt_goal_content_capacity_exhausted":
        raise ValueError("parent run must be terminal, not concurrently active")
    return summary


def models(profile):
    return {role: {key: profile[role][key] for key in ("provider", "model", "base_url")}
            for role in ("writer", "director")}


def verify_seed_native(seed):
    matches = [row for row in read(PREFLIGHT_PARENT / "CALL_LEDGER.json")["calls"] if row["ordinal"] == 540]
    if len(matches) != 1:
        raise ValueError("unique complete native540 receipt required")
    row = matches[0]
    receipt_path = PREFLIGHT_PARENT / row["receipt"]
    if sha_file(receipt_path) != row["receipt_sha256"]:
        raise ValueError("native540 receipt changed")
    receipt = read(receipt_path)
    if not repairable(receipt) or receipt.get("output") != seed or receipt["request"]["stage"] != "goal_plan":
        raise ValueError("seed must be exact complete known native540, never a converted accepted plan")
    return {"ordinal": 540, "receipt_path": str(receipt_path),
        "receipt_sha256": row["receipt_sha256"], "native_sha256": digest(seed),
        "contract_valid": False, "used_only_for_complete_model_revision": True}


def get_runtime():
    from scripts.creative_goal_context_dispatch_v5 import GoalContextRuntime
    from scripts import creative_flat_lineage_guard_v1 as lineage
    from src.content_factory import creative_flat_lineage_verifier_v1 as verifier
    freeze = read(ROOT / "PRODUCTION_FREEZE.json")
    profile = read(PROFILE)
    def guard():
        lineage.verify_lineage_certificate(read(CERTIFICATE),
            expected_certificate_sha256=freeze["parent_certificate_sha256"],
            fresh_source_gate=parent.source_gate, expected_inherited=freeze["inherited"])
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
    from scripts import creative_flat_lineage_guard_v1 as lineage
    from src.content_factory import creative_flat_lineage_verifier_v1 as verifier
    expected = read(PREFLIGHT_PARENT / "STATE.json")["spend"]
    certificate = lineage.build_lineage_certificate(PROJECT, PREFLIGHT_PARENT,
        certified_check=prior_guard, expected_summary=expected,
        dependency_paths=[PREFLIGHT_PARENT / "STATE.json"],
        guard_code_paths=[Path(__file__), Path(lineage.__file__), Path(verifier.__file__)])
    consumed = expected
    approval = read(APPROVAL)
    if (approval.get("human_authorized") is not True or approval.get("user_quote") != "minimax随便追加"
            or approval.get("parent_ledger_sha256") != sha_file(PREFLIGHT_PARENT / "CALL_LEDGER.json")
            or approval.get("parent_goal_candidates_used") != 8
            or approval.get("authority_source_sha256") != sha_file(previous.APPROVAL)):
        raise ValueError("explicit continuing user authorization and unchanged spent lineage required")
    inputs = read(PREFLIGHT_PARENT / "INPUTS.json")
    seed_row = [row for row in read(PREFLIGHT_PARENT / "CALL_LEDGER.json")["calls"] if row["ordinal"] == 540][0]
    seed = read(PREFLIGHT_PARENT / seed_row["receipt"])["output"]
    seed_identity = verify_seed_native(seed)
    diagnostic = {"native_goal_ordinal": 540, "native_goal_sha256": digest(seed),
        "known_complete_contract_failure": diagnosis(read(PREFLIGHT_PARENT / seed_row["receipt"])),
        "workflow_change": "New v4 whole plan declares only static inventory; opening states are a separate native setup after audits. The old full document is revision evidence, never an accepted v4 conversion.",
        "content_requirements": read(PREFLIGHT_PARENT / "INHERITED_DIAGNOSTICS.json")}
    source_check = parent.source_gate()
    inherited = {"calls_started": consumed["effective_calls_started"],
        "reported_tokens": consumed["effective_reported_tokens"],
        "calls_with_known_usage": consumed["effective_calls_with_known_usage"],
        "unknown_token_reservations": consumed["unknown_token_reservations"],
        "pending_ordinals": consumed["historical_pending_ordinals"]}
    scope = {"schema": VERSION + "/user_scope", "grant_id": GRANT,
        "user_quote": approval["user_quote"], "writer_total_call_user_limit": None,
        "stage_limits": {"goal_plan": 4, "goal_audit": 4, "complete_script": 3, "full_review": 3},
        "stage_limits_are_local_run_safety_bounds": True,
        "inherited_goal_candidates_used": 8, "local_goal_candidates_limit": 2,
        "local_opening_setup_limit": 2, "cumulative_goal_candidates_this_run_maximum": 10,
        "seed_goal_ordinal": 540, "seed_goal_semantic_approved": False,
        "seed_used_only_for_complete_model_revision": True,
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
        "parent_ledger_sha256": scope["parent_ledger_sha256"], "inherited_goal_candidates_used": 8,
        "old_allowance_reset": False}, True)
    ROOT.mkdir(parents=True)
    write(CERTIFICATE, certificate, True)
    write(ROOT / "USER_SCOPE.json", scope, True)
    write(ROOT / "INPUTS.json", inputs, True)
    write(ROOT / "INHERITED_NATIVE_GOAL.json", seed, True)
    write(ROOT / "INHERITED_DIAGNOSTICS.json", diagnostic, True)
    write(ROOT / "SOURCE_GATE.json", source_check, True)
    first_request = workflow.prepare_goal_request({**deepcopy(inputs),
        "previous_complete_document": seed, "revision_diagnostics": diagnostic}, read(PROFILE))
    write(ROOT / "FIRST_GOAL_REQUEST_PREVIEW.json", first_request, True)
    # Freeze every old production dependency plus all new independent modules.
    paths = set(read(PREFLIGHT_PARENT / "PRODUCTION_FREEZE.json")["files"])
    paths.update(str(p.resolve()) for p in (Path(__file__), PROFILE, PLAN,
        Path(workflow.__file__), Path(goals.__file__), Path(reviews.__file__), Path(setups.__file__),
        PROJECT / "src/content_factory/creative_stage_context_v3.py", APPROVAL, CERTIFICATE,
        PROJECT / "src/content_factory/creative_goal_audit_citation_contract_v1.py",
        PROJECT / "scripts/creative_goal_context_dispatch_v5.py", Path(lineage.__file__), Path(verifier.__file__), Path(clients.__file__),
        PREFLIGHT_PARENT / "RUN_CLAIM.json", PREFLIGHT_PARENT / "CALL_LEDGER.json",
        ROOT / "USER_SCOPE.json", ROOT / "INPUTS.json", ROOT / "INHERITED_NATIVE_GOAL.json",
        ROOT / "INHERITED_DIAGNOSTICS.json", ROOT / "SOURCE_GATE.json",
        ROOT / "FIRST_GOAL_REQUEST_PREVIEW.json"))
    freeze = {"schema": VERSION + "/freeze", "inherited": inherited,
        "parent_certificate_sha256": digest(certificate),
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


def validate_opening_setup(value, goal):
    """Known complete setup gaps require native revision, never local placement."""
    native = workflow.validate_opening_setup_document(value, goal)
    return {"valid": True, "native_setup_sha256": digest(native),
        "native_goal_sha256": digest(goal), "state_fields_inferred": False,
        "semantic_quality_approved": False}


def state(runtime, status, **extra):
    result = {"schema": VERSION + "/state", "status": status, "updated_at": now(),
        "text_ready_for_director": False, "human_quality_approved": False, "creative_quality_passed": False,
        "media_authorized": False, "old_director_capacity": {"used": 7, "limit": 7, "remaining": 0},
        "spend": runtime.summary(), **extra}
    result["inherited_goal_candidates_used"] = 8
    labels = [row.get("label", "") for row in read(runtime.ledger)["calls"]]
    # Setup writer calls consume the same stage, but are not new whole-film candidates.
    result["cumulative_goal_candidates_used"] = 8 + sum(label.startswith("goal_plan_") for label in labels)
    result["opening_setup_calls"] = sum(label.startswith("opening_setup_") for label in labels)
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
    goal = read(ROOT / "INHERITED_NATIVE_GOAL.json")
    goal_inputs = {**deepcopy(inputs), "previous_complete_document": goal,
        "revision_diagnostics": read(ROOT / "INHERITED_DIAGNOSTICS.json")}
    audit = None
    goal_ordinal = None
    for index in range(1, 3):
        planned = workflow.prepare_goal_request(goal_inputs, profile)
        if index == 1 and (ROOT / "FIRST_GOAL_REQUEST_PREVIEW.json").exists():
            if planned != read(ROOT / "FIRST_GOAL_REQUEST_PREVIEW.json"):
                raise ValueError("first actual goal request differs from frozen exact preview")
        def goal_validator(value):
            return workflow._validate_planning_input(inputs, value)
        receipt = invoke(runtime, f"goal_plan_{index+8:02}", planned,
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
        bundle, decisions = {}, []
        for kind in ("source", "drama"):
            prepare_audit = getattr(workflow, f"prepare_goal_{kind}_audit_request")
            validate_audit = getattr(workflow, f"validate_goal_{kind}_audit")
            prepared = prepare_audit(inputs, profile, goal)
            context_sha = prepared["request"]["structured_schema"]["properties"]["audit_context_sha256"]["const"]
            audited = invoke(runtime, f"goal_{kind}_audit_{index:02}", prepared,
                lambda value: validate_audit(value, goal, context_sha256=context_sha))
            if audited.get("cached_response_read_only"):
                return state(runtime, "halt_cached_goal_audit_no_new_claim", receipt_ordinal=audited["ordinal"])
            if not repairable(audited):
                return state(runtime, "halt_goal_audit_interface_or_unknown", receipt_ordinal=audited["ordinal"], audit_kind=kind)
            if audited["status"] != "contract_valid":
                return state(runtime, "halt_goal_audit_contract_requires_pipeline_diagnosis", receipt_ordinal=audited["ordinal"], audit_kind=kind)
            verdict = audited["validation"]
            write(ROOT / "goals" / f"{kind}_audit_decision_{index:02}.json", verdict, True)
            write(ROOT / "goals" / f"{kind}_native_audit_{index:02}.json", audited["output"], True)
            if verdict["uncertainties"]:
                return state(runtime, "halt_goal_audit_uncertain", goal_decision=verdict, audit_kind=kind)
            decisions.append(verdict)
            bundle[f"native_{kind}_audit"] = audited["output"]
            if not verdict["accepted"]:
                break
        if len(bundle) == 2 and all(decision["accepted"] for decision in decisions):
            audit = workflow.build_goal_audit_bundle(bundle["native_source_audit"], bundle["native_drama_audit"])
            break
        goal_inputs = {**deepcopy(inputs), "previous_complete_document": goal,
            "revision_diagnostics": {"complete_same_source_goal_audits": decisions}}
    if audit is None:
        return state(runtime, "halt_goal_content_capacity_exhausted")
    opening_setup = None
    setup_inputs = deepcopy(script_source_inputs(inputs))
    for index in range(1, 3):
        prepared_setup = workflow.prepare_opening_setup_request(setup_inputs, profile, goal)
        setup_receipt = invoke(runtime, f"opening_setup_{index:02}", prepared_setup,
            lambda value: validate_opening_setup(value, goal))
        if setup_receipt.get("cached_response_read_only"):
            return state(runtime, "halt_no_new_opening_setup_progress", receipt_ordinal=setup_receipt["ordinal"])
        if not repairable(setup_receipt):
            return state(runtime, "halt_opening_setup_interface_or_unknown", receipt_ordinal=setup_receipt["ordinal"])
        native_setup = setup_receipt["output"]
        write(ROOT / "setups" / f"native_{index:02}.json", native_setup, True)
        if setup_receipt["status"] == "contract_valid":
            opening_setup = native_setup
            break
        setup_inputs = {**deepcopy(script_source_inputs(inputs)), "previous_opening_setup": native_setup,
            "opening_setup_diagnostics": diagnosis(setup_receipt)}
    if opening_setup is None:
        return state(runtime, "halt_opening_setup_content_capacity_exhausted")
    base_script_inputs = script_source_inputs(inputs)
    script_inputs = deepcopy(base_script_inputs)
    for index in range(1, 4):
        prepared = workflow.prepare_script_request(script_inputs, profile, goal, audit,
            opening_setup=opening_setup, **ids)
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
                "native_opening_setup": opening_setup,
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
