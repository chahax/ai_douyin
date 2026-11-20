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
from scripts import run_goal_context_text_production_v18 as previous
from src.content_factory import creative_goal_context_workflow_v18 as workflow
from src.content_factory import creative_goal_drama_audit_contract_v11 as drama_contract
from src.content_factory import creative_goal_source_contract_v4 as goals
from src.content_factory import creative_opening_setup_contract_v3 as setups
from src.content_factory import creative_split_full_review_contract_v4 as reviews
from src.content_factory import creative_full_review_contract_v5 as complete_reviews
from src.content_factory import creative_fresh_legal_text_pipeline_v1 as legacy
from src.content_factory import creative_studio_task_store_v1 as tasks

VERSION = "goal_context_text_production/v19"
ROOT = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_18"
GRANT = "legal_pragmatics_repair_20261014"
PREFLIGHT_PARENT = previous.ROOT
CLAIM = PROJECT / "data/creative_fresh_background_claims" / GRANT / "CLAIM.json"
APPROVAL = CLAIM.parent / "USER_CONTINUATION.json"
PROFILE = PROJECT / "config/creative_goal_context_model_profile_v3.json"
PLAN = PROJECT / "docs/CREATIVE_LEGAL_PRAGMATICS_REPAIR_PLAN_20261014.md"
PARENT_STATE = PREFLIGHT_PARENT / "STATE.json"
CONTENT_DIAGNOSIS = PROJECT / "data/qa/creative_legal_pragmatics_20261014/ROUND17_LEGAL_PRAGMATICS_DIAGNOSIS_v2.json"
CERTIFICATE = ROOT / "CERTIFIED_PARENT_LINEAGE.json"
USER_DIRECTION_CONFIRMATION = previous.USER_DIRECTION_CONFIRMATION
INPUT_SUPPLEMENT_AUTHORIZATION = previous.INPUT_SUPPLEMENT_AUTHORIZATION
SUPPLEMENTED_INPUTS = previous.SUPPLEMENTED_INPUTS
SUPPLEMENTED_PREVIEW = previous.SUPPLEMENTED_PREVIEW
REQUEST_PREVIEW = PROJECT / "data/qa/creative_legal_pragmatics_20261014/LEGAL_PRAGMATICS_REQUEST_PREVIEW_v1.json"
read, write, digest, sha_file, now = control.read, control.write, control.digest, control.sha_file, control.now


def prior_guard():
    prior_runtime = previous.get_runtime()
    prior_runtime.inherited_guard()
    summary = prior_runtime.summary()
    ledger = read(prior_runtime.ledger)
    if [row["ordinal"] for row in ledger["calls"]] != [602,603]:
        raise ValueError("parent must preserve exact closed calls602 and603")
    for row in ledger["calls"]:
        path=PREFLIGHT_PARENT/row["receipt"]
        receipt=read(path)
        expected="contract_valid" if row["ordinal"]==602 else "contract_rejected"
        if sha_file(path)!=row["receipt_sha256"] or receipt.get("status")!=expected:
            raise ValueError("parent original receipt identity or contract status changed")
        original.verify_receipt_evidence(prior_runtime,receipt,receipt["request"])
        if not repairable(receipt):
            raise ValueError("602/603 must remain complete known native results; unknown never redispatched")
        if receipt["request"]["stage"]!=("goal_plan" if row["ordinal"]==602 else "goal_audit"):
            raise ValueError("exact parent stage identity required")
        if row["ordinal"]==603 and (receipt.get("validation") is not None
                or receipt.get("failure",{}).get("code")!="MODULE_SCHEMA_INVALID"):
            raise ValueError("603 is original source contract rejection, not an accepted audit")
    terminal=read(PARENT_STATE)
    if (terminal.get("status")!="halt_goal_audit_contract_requires_pipeline_diagnosis"
            or terminal.get("receipt_ordinal")!=603 or terminal.get("audit_kind")!="source"
            or terminal.get("text_ready_for_director") is not False
            or terminal.get("spend")!=summary or terminal.get("cumulative_goal_candidates_used")!=25
            or terminal.get("opening_setup_calls")!=0
            or summary["stage_calls"]!={"goal_plan":1,"goal_audit":1,"complete_script":0,"full_review":0}
            or (summary["effective_calls_started"],summary["effective_reported_tokens"],
                summary["effective_calls_with_known_usage"])!=(603,12073493,601)
            or summary.get("new_unknown_token_reservations")!=0
            or summary.get("historical_pending_ordinals")!=[70,160]
            or summary.get("unknown_token_reservations")!=93117):
        raise ValueError("exact603 known terminal, spend and stage counts required")
    scope=read(PREFLIGHT_PARENT/"USER_SCOPE.json")
    if (scope.get("inherited_goal_candidates_used")!=24 or scope.get("local_goal_candidates_limit")!=2
            or scope.get("local_opening_setup_limit")!=2
            or scope.get("cumulative_goal_candidates_this_run_maximum")!=26
            or summary["stage_limits"]!=scope["stage_limits"]
            or summary["stage_limits"]!={"goal_plan":4,"goal_audit":6,"complete_script":3,"full_review":6}):
        raise ValueError("parent used25/max26/unused1 stays in closed run; no regrant")
    return summary


def models(profile):
    return {role: {key: profile[role][key] for key in ("provider", "model", "base_url")}
            for role in ("writer", "director")}


def verify_seed_native(seed):
    rows=[row for row in read(PREFLIGHT_PARENT/"CALL_LEDGER.json")["calls"] if row["ordinal"]==602]
    if len(rows)!=1:raise ValueError("unique original602 complete native required")
    row=rows[0];path=PREFLIGHT_PARENT/row["receipt"]
    receipt=read(path)
    if (sha_file(path)!=row["receipt_sha256"] or not repairable(receipt)
            or receipt.get("output")!=seed or receipt.get("status")!="contract_valid"
            or receipt["request"]["stage"]!="goal_plan"
            or read(PREFLIGHT_PARENT/"goals/native_01.json")!=seed):
        raise ValueError("complete exact602 native is revision template only; source603 not approved")
    return {"ordinal":602,"receipt_path":str(path),"receipt_sha256":row["receipt_sha256"],
        "native_sha256":digest(seed),"contract_valid":True,"semantic_approved":False,
        "used_only_for_complete_model_revision":True,"sent_as_first_request_template":True}


def get_runtime():
    from scripts.creative_goal_context_dispatch_v7 import GoalContextRuntime
    from scripts import creative_flat_lineage_guard_v2 as lineage
    from src.content_factory import creative_flat_lineage_verifier_v2 as verifier
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
                or sha_file(INPUT_SUPPLEMENT_AUTHORIZATION) != freeze["input_supplement_authorization_sha256"]
                or sha_file(CLAIM) != freeze["global_claim_sha256"]):
            raise ValueError("global authorization claim changed")
        for path, expected in freeze["files"].items():
            if sha_file(path) != expected:
                raise ValueError("new independent frozen input changed: " + path)
    return GoalContextRuntime(PROJECT, ROOT, [Path(path) for path in freeze["sources"]],
        freeze["inherited"], freeze["models"], inherited_guard=guard, profile=profile,
        stage_limits=read(ROOT / "USER_SCOPE.json")["stage_limits"], quota_state=None,
        shared_lock=PROJECT / "data/creative_fresh_background_claims/DISPATCH.lock")


def authorization_request_identity(diagnostic, prepared):
    """Pin local recovery and dispatch preparation to one actual text request."""
    return {
        "source_inputs_sha256": sha_file(PREFLIGHT_PARENT / "INPUTS.json"),
        "model_profile_sha256": sha_file(PROFILE),
        "derived_revision_diagnostics_sha256": digest(diagnostic),
        "actual_prepared_preview_sha256": digest(prepared),
    }


def verify_inherited_direction_inputs(inputs):
    """Latest ten human rows are inherited exactly, never appended or reauthorized."""
    if inputs!=read(SUPPLEMENTED_INPUTS) or inputs!=read(PREFLIGHT_PARENT/"INPUTS.json"):
        raise ValueError("latest direction supplemented source inputs changed")
    proof=read(PREFLIGHT_PARENT/"USER_DIRECTION_INPUT_SUPPLEMENT.json")
    if proof!=read(INPUT_SUPPLEMENT_AUTHORIZATION):
        raise ValueError("original direction supplement binding changed")
    if (proof.get("supplemented_inputs_sha256")!=digest(inputs)
            or proof.get("human_direction_confirmation_sha256")!=sha_file(USER_DIRECTION_CONFIRMATION)
            or proof.get("appended_user_ids")!=["UC_CONFIRMED_SUPERMARKET_DIRECTION","UG_INTENSIFIED_EMOTIONAL_EXCHANGE"]
            or proof.get("append_only_user_rows") is not True
            or proof.get("confirmation_is_direction_not_manuscript_adoption") is not True
            or proof.get("media_authorized") is not False or proof.get("publish_authorized") is not False
            or proof.get("old_ledger_reset") is not False or proof.get("automatic_transport_retry") is not False
            or read(SUPPLEMENTED_PREVIEW).get("input_supplement_binding")!=proof):
        raise ValueError("original exact direction identity and no-adoption boundary required")
    return proof


def prepare():
    if ROOT.exists() or CLAIM.exists():
        raise RuntimeError("existing global grant/root; inspect original, never regrant")
    from scripts import creative_flat_lineage_guard_v2 as lineage
    from src.content_factory import creative_flat_lineage_verifier_v2 as verifier
    expected = read(PARENT_STATE)["spend"]
    certificate = lineage.build_lineage_certificate(PROJECT, PREFLIGHT_PARENT,
        certified_check=prior_guard, expected_summary=expected,
        dependency_paths=[PARENT_STATE],
        guard_code_paths=[Path(__file__), Path(lineage.__file__), Path(verifier.__file__)])
    consumed = expected
    approval = read(APPROVAL)
    if (approval.get("human_authorized") is not True or approval.get("user_quote") != "minimax随便追加"
            or approval.get("parent_ledger_sha256") != sha_file(PREFLIGHT_PARENT / "CALL_LEDGER.json")
            or approval.get("parent_goal_candidates_used") != 25
            or approval.get("parent_whole_plan_maximum") != 26
            or approval.get("parent_whole_plan_unused_capacity") != 1
            or approval.get("authority_source_sha256") != sha_file(previous.APPROVAL)
            or approval.get("input_supplement_authorization_sha256") != sha_file(INPUT_SUPPLEMENT_AUTHORIZATION)
            or approval.get("human_direction_confirmation_sha256") != sha_file(USER_DIRECTION_CONFIRMATION)):
        raise ValueError("explicit continuing user authorization and unchanged spent lineage required")
    inputs = read(PREFLIGHT_PARENT / "INPUTS.json")
    input_supplement = verify_inherited_direction_inputs(inputs)
    seed_row = [row for row in read(PREFLIGHT_PARENT / "CALL_LEDGER.json")["calls"] if row["ordinal"] == 602][0]
    seed = read(PREFLIGHT_PARENT / seed_row["receipt"])["output"]
    seed_identity = verify_seed_native(seed)
    diagnostic = build_revision_diagnostics(seed)
    source_check = parent.source_gate()
    first_request = workflow.prepare_goal_request(revision_planning_inputs(inputs, seed, diagnostic), read(PROFILE))
    if (any(approval.get(key) != value for key, value in authorization_request_identity(diagnostic, first_request).items())
            or approval.get("schema")!=VERSION+"/derived_authorization_binding"
            or approval.get("parent_root")!=str(PREFLIGHT_PARENT)
            or approval.get("parent_state_sha256")!=sha_file(PARENT_STATE)
            or approval.get("seed_native_identity")!=seed_identity
            or approval.get("new_local_bound_from_existing_authority")!=2
            or approval.get("new_cumulative_goal_candidates_maximum")!=27
            or approval.get("parent_unused_capacity_stays_in_closed_run") is not True
            or approval.get("old_ledger_reset") is not False
            or approval.get("automatic_transport_retry") is not False
            or approval.get("media_authorized") is not False or approval.get("publish_authorized") is not False):
        raise ValueError("continuing authorization inputs, profile, diagnosis or actual request changed")
    saved_preview=read(REQUEST_PREVIEW)
    if (saved_preview.get("prepared") != first_request or saved_preview.get("seed_native_identity")!=seed_identity
            or type(saved_preview.get("provider_calls")) is not int or saved_preview.get("provider_calls")!=0
            or type(saved_preview.get("media_calls")) is not int or saved_preview.get("media_calls")!=0
            or saved_preview.get("creative_quality_approved") is not False
            or saved_preview.get("old_source603_not_converted") is not True
            or saved_preview.get("pending_content_risks_not_native_judgments") is not True):
        raise ValueError("actual authorization preview changed; no new run claim created")
    inherited = {"calls_started": consumed["effective_calls_started"],
        "reported_tokens": consumed["effective_reported_tokens"],
        "calls_with_known_usage": consumed["effective_calls_with_known_usage"],
        "unknown_token_reservations": consumed["unknown_token_reservations"],
        "pending_ordinals": consumed["historical_pending_ordinals"]}
    scope = {"schema": VERSION + "/user_scope", "grant_id": GRANT,
        "user_quote": approval["user_quote"], "writer_total_call_user_limit": None,
        "stage_limits": {"goal_plan": 4, "goal_audit": 6, "complete_script": 3, "full_review": 6},
        "stage_limits_are_local_run_safety_bounds": True,
        "inherited_goal_candidates_used": 25, "local_goal_candidates_limit": 2,
        "local_opening_setup_limit": 2, "cumulative_goal_candidates_this_run_maximum": 27,
        "seed_goal_ordinal": 602, "seed_goal_semantic_approved": False,
        "seed_used_only_for_complete_model_revision": True, "first_request_is_fresh_reconception": False,
        "parent_whole_plan_maximum": 26, "parent_whole_plans_used": 25,
        "parent_whole_plan_unused_capacity": 1, "parent_unused_capacity_stays_in_closed_run": True,
        "new_local_bound_from_existing_authority": 2,
        "old_goal_allowance_reset": False, "deepseek_scope": "few necessary source and whole-text reviews",
        "content_revision_limit": 2, "old_m31_one_writer_one_review_used": 2,
        "old_director_candidates_used": 7, "old_director_candidates_limit": 7,
        "additional_director_candidates": 0, "media_authorized": False, "publish_authorized": False,
        "automatic_transport_retry": False, "new_format_recovery_claimed": False,
        "human_direction_confirmation_sha256":sha_file(USER_DIRECTION_CONFIRMATION),
        "input_supplement_authorization_sha256":sha_file(INPUT_SUPPLEMENT_AUTHORIZATION),
        "max_total_tokens": None, "starting_spend": inherited,
        "parent_ledger_sha256": sha_file(PREFLIGHT_PARENT / "CALL_LEDGER.json")}
    write(CLAIM, {"schema": VERSION + "/continuation_claim", "grant_id": GRANT,
        "root": str(ROOT), "created_at": now(), "parent_root": str(PREFLIGHT_PARENT),
        "authorization_sha256": sha_file(APPROVAL),
        "input_supplement_authorization_sha256":sha_file(INPUT_SUPPLEMENT_AUTHORIZATION),
        "parent_ledger_sha256": scope["parent_ledger_sha256"], "inherited_goal_candidates_used": 25,
        "old_allowance_reset": False}, True)
    ROOT.mkdir(parents=True)
    write(CERTIFICATE, certificate, True)
    write(ROOT / "USER_SCOPE.json", scope, True)
    write(ROOT / "INPUTS.json", inputs, True)
    write(ROOT / "ORIGINAL_PARENT_INPUTS.json", read(PREFLIGHT_PARENT/"INPUTS.json"), True)
    write(ROOT / "USER_DIRECTION_INPUT_SUPPLEMENT.json", input_supplement, True)
    write(ROOT / "INHERITED_NATIVE_GOAL.json", seed, True)
    write(ROOT / "INHERITED_DIAGNOSTICS.json", diagnostic, True)
    write(ROOT / "SOURCE_GATE.json", source_check, True)
    write(ROOT / "FIRST_GOAL_REQUEST_PREVIEW.json", first_request, True)
    # Freeze every old production dependency plus all new independent modules.
    paths = set(read(PREFLIGHT_PARENT / "PRODUCTION_FREEZE.json")["files"])
    paths.update(str(p.resolve()) for p in (Path(__file__), PROFILE, PLAN, CONTENT_DIAGNOSIS,
        PARENT_STATE, PROJECT / "src/content_factory/creative_goal_revision_feedback_v1.py",
        Path(workflow.__file__), PROJECT / "src/content_factory/creative_goal_evidence_view_v1.py", PROJECT / "src/content_factory/creative_goal_legal_usage_source_audit_v2.py", PROJECT / "src/content_factory/creative_goal_commitment_audit_v2.py", Path(drama_contract.__file__), Path(goals.__file__), Path(reviews.__file__), Path(complete_reviews.__file__), Path(setups.__file__),
        PROJECT / "src/content_factory/creative_stage_context_v3.py", APPROVAL, CERTIFICATE,
        USER_DIRECTION_CONFIRMATION,INPUT_SUPPLEMENT_AUTHORIZATION,SUPPLEMENTED_INPUTS,SUPPLEMENTED_PREVIEW,
        REQUEST_PREVIEW,
        PROJECT / "src/content_factory/creative_goal_audit_citation_contract_v1.py",
        PROJECT / "scripts/record_legal_pragmatics_continuation_v1.py",
        PROJECT / "scripts/record_legal_pragmatics_diagnosis_v1.py",
        PROJECT / "scripts/creative_goal_context_dispatch_v7.py", Path(lineage.__file__), Path(verifier.__file__), Path(clients.__file__),
        PREFLIGHT_PARENT / "RUN_CLAIM.json", PREFLIGHT_PARENT / "CALL_LEDGER.json",
        ROOT / "USER_SCOPE.json", ROOT / "INPUTS.json", ROOT / "INHERITED_NATIVE_GOAL.json",
        ROOT / "ORIGINAL_PARENT_INPUTS.json",ROOT / "USER_DIRECTION_INPUT_SUPPLEMENT.json",
        ROOT / "INHERITED_DIAGNOSTICS.json", ROOT / "SOURCE_GATE.json",
        ROOT / "FIRST_GOAL_REQUEST_PREVIEW.json"))
    paths.update(read(CONTENT_DIAGNOSIS)["source_file_sha256"])
    freeze = {"schema": VERSION + "/freeze", "inherited": inherited,
        "parent_certificate_sha256": digest(certificate),
        "seed_native_identity": seed_identity,
        "models": models(read(PROFILE)), "global_claim_sha256": sha_file(CLAIM),
        "continuation_authorization_sha256": sha_file(APPROVAL),
        "input_supplement_authorization_sha256":sha_file(INPUT_SUPPLEMENT_AUTHORIZATION),
        "parent_ledger_sha256": scope["parent_ledger_sha256"], "sources": sorted(paths),
        "files": {path: sha_file(path) for path in sorted(paths)}, "media_authorized": False}
    write(ROOT / "PRODUCTION_FREEZE.json", freeze, True)
    result = get_runtime().prepare()
    write(ROOT / "STATE.json", {"status": "prepared", "text_ready_for_director": False,
        "human_quality_approved": False, "creative_quality_passed": False, "spend": result})
    return result


def build_revision_diagnostics(seed):
    from scripts import record_legal_pragmatics_diagnosis_v1 as recorder
    verify_seed_native(seed)
    verified=read(CONTENT_DIAGNOSIS)
    expected=recorder.build_diagnosis()
    if verified!=expected:raise ValueError("exact602/603 pragmatic conflict diagnosis changed")
    for path,expected_sha in verified["source_file_sha256"].items():
        if sha_file(path)!=expected_sha:raise ValueError("original pragmatic diagnosis witness changed")
    model_diagnosis={"schema":VERSION+"/content_owned_diagnosis_projection",
        "complete_local_diagnosis_sha256":digest(verified),
        "complete_local_source_manifest_sha256":digest(verified["source_file_sha256"]),
        "full_original_diagnosis_and_receipts_retained_locally":True,
        "verified_failures":deepcopy(verified["verified_failures"]),
        "pending_content_risks":deepcopy(verified["pending_content_risks"]),
        "prior_legal_fault_evidence":deepcopy(verified["prior_legal_fault_evidence"]),
        "stage_ownership_direction":deepcopy(verified["stage_ownership_direction"]),
        "diagnosis_is_human_reading_not_automated_semantic_proof":True}
    return {"schema":VERSION+"/qualified_revision_diagnostics","native_goal_ordinal":602,
        "native_goal_sha256":digest(seed),"verified_pipeline_diagnosis":model_diagnosis,
        "workflow_change":"Submit a complete new native revision of original602. Preserve current supermarket story direction, intensified emotional exchange, all legal conditions and R01 mechanism. Source v2 separates non-legal speech acts from actual legal assertions, and compiles only explicit native relations; do not turn factual guesses, offers or wishes into legal rules, or exempt legal meaning by a character/fiction label. Pending story risks are not completed model judgments: make proposed versus agreed termination unambiguous, show what changes the manager's risk calculation, and avoid unqualified dismissal of the notebook's legal value. New source and drama audits must decide these risks from the complete new native plan. Original603 is a complete rejected old-contract audit, never a report to patch or adopt; historical594/595 legal leak and601 length failure remain evidence. Keep source/commitment/drama responsibilities distinct, then native setup/body and same-source full semantic/physical review. No local screenplay patch or cached old review adoption.",
        "previous_complete_script_sent_to_planner":False,"old_complete_documents_retained":True,
        "native_text_locally_patched":False}


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
                       "revision_requirements", "complete_script_feasibility_diagnostics",
                       "fresh_reconception_context")}


def revision_planning_inputs(inputs, seed, diagnostic):
    """Only this new run's known complete native version is a revision template."""
    return {**script_source_inputs(inputs), "previous_complete_document": deepcopy(seed),
        "revision_diagnostics": deepcopy(diagnostic)}


def fresh_planning_inputs(inputs, diagnostic):
    return {**script_source_inputs(inputs), "fresh_reconception_context":deepcopy(diagnostic)}


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
    result["inherited_goal_candidates_used"] = 25
    labels = [row.get("label", "") for row in read(runtime.ledger)["calls"]]
    # Setup writer calls consume the same stage, but are not new whole-film candidates.
    result["cumulative_goal_candidates_used"] = 25 + sum(label.startswith("goal_plan_") for label in labels)
    result["opening_setup_calls"] = sum(label.startswith("opening_setup_") for label in labels)
    result["parent_whole_plan_unused_capacity"] = 1
    result["parent_unused_capacity_stays_in_closed_run"] = True
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
    goal_inputs = revision_planning_inputs(inputs, goal, read(ROOT / "INHERITED_DIAGNOSTICS.json"))
    audit = None
    goal_ordinal = None
    for index in range(1, 3):
        planned = workflow.prepare_goal_request(goal_inputs, profile)
        if index == 1 and (ROOT / "FIRST_GOAL_REQUEST_PREVIEW.json").exists():
            if planned != read(ROOT / "FIRST_GOAL_REQUEST_PREVIEW.json"):
                raise ValueError("first actual goal request differs from frozen exact preview")
        def goal_validator(value):
            return workflow._validate_planning_input(inputs, value)
        receipt = invoke(runtime, f"goal_plan_{index+25:02}", planned,
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
            goal_inputs = revision_planning_inputs(inputs, goal, diagnosis(receipt))
            continue
        bundle, decisions = {}, []
        for kind in ("source", "commitment", "drama"):
            prepare_audit = getattr(workflow, f"prepare_goal_{kind}_audit_request")
            validate_audit = getattr(workflow, f"validate_goal_{kind}_audit")
            prepared = prepare_audit(inputs, profile, goal)
            context_sha = prepared["request"]["structured_schema"]["properties"]["audit_context_sha256"]["const"]
            validate_args = {"context_sha256": context_sha}
            if kind == "source":
                validate_args["authority_context"] = deepcopy(prepared["source_authority_context"])
            audited = invoke(runtime, f"goal_{kind}_audit_{index:02}", prepared,
                lambda value, validate=validate_audit, args=validate_args: validate(value, goal, **args))
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
        if len(bundle) == 3 and all(decision["accepted"] for decision in decisions):
            audit = workflow.build_goal_audit_bundle(bundle["native_source_audit"], bundle["native_drama_audit"], bundle["native_commitment_audit"])
            break
        goal_inputs = revision_planning_inputs(inputs, goal, {"complete_same_source_goal_audits": decisions})
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
        part_documents, part_decisions, part_contexts, part_ordinals = {}, {}, {}, {}
        failed_part_decision = None
        review_legal_context = None
        for part in ("semantic", "physical"):
            prepared_review = workflow.prepare_full_review_part_request(inputs, profile, native, views, part)
            context_sha = prepared_review["part_context_sha256"]
            if review_legal_context is not None and review_legal_context != prepared_review["review_legal_context"]:
                raise ValueError("split review parts must bind the exact same legal context")
            review_legal_context = prepared_review["review_legal_context"]
            reviewed = invoke(runtime, f"full_review_{part}_{index:02}", prepared_review,
                lambda v: reviews.validate_part(v, part, compiled, views["brief"], views["plan"],
                    review_legal_context, context_sha256=context_sha,
                    goal_contract=goal, opening_setup=opening_setup))
            if reviewed.get("cached_response_read_only"):
                return state(runtime, "halt_cached_full_review_no_new_claim", review_part=part,
                    receipt_ordinal=reviewed["ordinal"])
            if not repairable(reviewed):
                return state(runtime, "halt_review_interface_or_unknown", review_part=part,
                    script_path=str(folder / "FULL_SCRIPT.md"), receipt_ordinal=reviewed["ordinal"])
            if reviewed["status"] != "contract_valid":
                return state(runtime, "halt_full_review_contract_requires_pipeline_diagnosis", review_part=part,
                    script_path=str(folder / "FULL_SCRIPT.md"), receipt_ordinal=reviewed["ordinal"])
            part_decision = reviewed["validation"]
            write(folder / f"NATIVE_{part.upper()}_REVIEW.json", reviewed["output"], True)
            write(folder / f"{part.upper()}_DECISION.json", part_decision, True)
            if part_decision.get("status") in (
                    "halt_same_story_prior_allowance_exhausted", "halt_prior_story_relation_unknown"):
                return state(runtime, part_decision["status"], review_part=part, decision=part_decision,
                    script_path=str(folder / "FULL_SCRIPT.md"), receipt_ordinal=reviewed["ordinal"],
                    prior_story_guard_preserved=True, new_body_revision_dispatched=False)
            if part_decision.get("uncertainties"):
                return state(runtime, "halt_full_review_uncertain", review_part=part, decision=part_decision,
                    script_path=str(folder / "FULL_SCRIPT.md"), receipt_ordinal=reviewed["ordinal"])
            if (part_decision.get("requires_new_goal_plan")
                    or any(item.get("target") == "plan" for item in part_decision.get("findings", []))):
                return state(runtime, "halt_full_review_requires_new_complete_goal", review_part=part,
                    decision=part_decision, script_path=str(folder / "FULL_SCRIPT.md"),
                    receipt_ordinal=reviewed["ordinal"], upstream_goal_revision_required=True)
            part_documents[part] = reviewed["output"]
            part_decisions[part] = part_decision
            part_contexts[part] = context_sha
            part_ordinals[part] = reviewed["ordinal"]
            if not part_decision["accepted"]:
                failed_part_decision = part_decision
                break
        if failed_part_decision is not None:
            script_inputs = {**deepcopy(base_script_inputs), "previous_complete_document": native,
                "revision_diagnostics": {"complete_same_source_part_review": failed_part_decision,
                    "native_part_reviews": part_documents, "native_review_ordinals": part_ordinals}}
            continue
        bundle = reviews.build_review_bundle(part_documents["semantic"], part_documents["physical"])
        decision = reviews.validate_bundle(bundle, compiled, views["brief"], views["plan"], review_legal_context,
            semantic_context_sha256=part_contexts["semantic"], physical_context_sha256=part_contexts["physical"],
            goal_contract=goal, opening_setup=opening_setup)
        write(folder / "NATIVE_REVIEW_BUNDLE.json", bundle, True)
        write(folder / "DECISION.json", decision, True)
        if decision.get("valid") is not True:
            return state(runtime, "halt_full_review_bundle_contract_requires_pipeline_diagnosis",
                decision=decision, review_ordinals=part_ordinals, script_path=str(folder / "FULL_SCRIPT.md"))
        if decision.get("status") in (
                "halt_same_story_prior_allowance_exhausted", "halt_prior_story_relation_unknown"):
            return state(runtime, decision["status"], decision=decision, review_ordinals=part_ordinals,
                script_path=str(folder / "FULL_SCRIPT.md"), prior_story_guard_preserved=True,
                new_body_revision_dispatched=False)
        if decision["uncertainties"]:
            return state(runtime, "halt_full_review_uncertain", decision=decision, script_path=str(folder / "FULL_SCRIPT.md"))
        if (decision.get("requires_new_goal_plan")
                or any(finding.get("target") == "plan" for finding in decision["findings"])):
            return state(runtime, "halt_full_review_requires_new_complete_goal", decision=decision,
                script_path=str(folder / "FULL_SCRIPT.md"), review_ordinals=part_ordinals,
                upstream_goal_revision_required=True, native_script_locally_patched=False)
        if decision["accepted"]:
            write(ROOT / "TEXT_HANDOFF.json", {"schema": VERSION + "/text_handoff", "native_goal": goal,
                "native_opening_setup": opening_setup,
                "native_goal_audit": audit, "native_script": native, "views": views,
                "native_full_review_bundle": bundle, "decision": decision,
                "script_path": str(folder / "FULL_SCRIPT.md"), "script_ordinal": receipt["ordinal"],
                "review_ordinals": part_ordinals, "production_dispatch_eligible": False,
                "next_stage_requires_reconciled_director_lineage": True, "media_authorized": False}, True)
            return state(runtime, "text_ready_for_director", text_ready_for_director=True,
                script_path=str(folder / "FULL_SCRIPT.md"), native_goal_ordinal=goal_ordinal,
                script_ordinal=receipt["ordinal"], review_ordinals=part_ordinals, decision=decision)
        script_inputs = {**deepcopy(base_script_inputs), "previous_complete_document": native,
            "revision_diagnostics": {"complete_same_source_full_review_bundle": decision,
                "native_review_bundle": bundle, "native_review_ordinals": part_ordinals}}
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
