"""Read-only settled653 bridge; three exhausted native body attempts stay spent.

No claim, runtime dispatch, client, media or file write is provided by this API.
The parent644 certificate is verified by its original independent verifier.
Historical integrity is not new source freshness or new dispatch authority.
"""
from copy import deepcopy
from pathlib import Path

from scripts import creative_world_scene_live_session_v2 as session
from scripts import creative_world_scene_spend_anchor_v2 as parent644
from scripts import creative_session_spend_anchor_v1 as evidence

VERSION = "creative_world_scene_spend_anchor/v3"
ROOT = session.base.PROJECT / "data/production_trials/world_scene_live_20261015/round_02"
EXPECTED = {"calls_started": 653, "reported_tokens": 13948653, "calls_with_known_usage": 651,
    "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
LABELS = ["whole_plan_02", "scope_audit_02", "source_audit_02", "commitment_audit_02", "drama_audit_02",
    "opening_setup_01", "complete_script_01", "complete_script_02", "complete_script_03"]
NEW_COUNTS = {"goal_plan": 2, "goal_audit": 4, "complete_script": 3, "full_review": 0}
CONSUMED = {"goal_plan": 3, "goal_audit": 7, "complete_script": 3, "full_review": 0}
REMAINING = {"goal_plan": 2, "goal_audit": 5, "complete_script": 0, "full_review": 6}
digest, sha = session.digest, session.sha


def require(value, message):
    if not value: raise ValueError(message)


def validate_accounting(parent, ledger, receipts, state):
    """Pure exact accounting after original SDK, frozen bytes and SQL verification."""
    inherited = evidence._spend(parent["inherited"])
    require(inherited == parent644.EXPECTED and ledger.get("starting_spend") == inherited,
        "original644 cumulative spend omitted/reset")
    require(ledger.get("schema") == "authorized_creative_continuation/v3"
        and ledger.get("max_total_tokens") is None
        and all(ledger.get(k) is False for k in ("automatic_retry", "old_budget_reset", "old_governance_migrated")),
        "original no-retry/no-reset text ledger required")
    calls = ledger.get("calls")
    require(type(calls) is list and len(calls) == len(receipts) == len(LABELS)
        and [r.get("ordinal") for r in calls] == list(range(645, 654))
        and [r.get("label") for r in calls] == LABELS, "exact original645--653 calls required")
    counts = dict.fromkeys(NEW_COUNTS, 0); seen_ids = set(); seen_requests = set()
    for index, (row, receipt) in enumerate(zip(calls, receipts)):
        request, meta = receipt.get("request", {}), receipt.get("response_metadata", {})
        session.base.NativeSession.known(receipt, row["label"], require_valid=False)
        expected_status = "contract_valid" if index < 6 else "contract_rejected"
        require(receipt.get("ordinal") == row["ordinal"] and receipt.get("label") == row["label"]
            and receipt.get("request_sha256") == digest(request)
            and receipt.get("source_binding_sha256") == digest(ledger["source_manifest"])
            and receipt.get("status") == expected_status and receipt.get("automatic_retry") is False
            and receipt.get("semantic_approval") is False and bool(receipt.get("completed_at"))
            and not receipt.get("cached_response_read_only"), "original known accepted/rejected native identity differs")
        stage = request.get("stage")
        expected_stage = ("goal_plan" if index in (0, 5) else "goal_audit" if index < 5 else "complete_script")
        require(stage == expected_stage and request.get("role") == evidence.STAGES[stage], "original stage/role changed")
        counts[stage] += 1
        usage = receipt.get("response_payload", {}).get("usage", {})
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            require(type(meta.get(key)) is int and meta[key] >= 0 and type(usage.get(key)) is int
                and usage[key] == meta[key], "unknown, negative or nontyped original usage")
        require(meta["prompt_tokens"] + meta["completion_tokens"] == meta["total_tokens"], "original usage arithmetic differs")
        rid, request_sha = meta.get("response_id"), receipt["request_sha256"]
        require(isinstance(rid, str) and bool(rid) and rid not in seen_ids and request_sha not in seen_requests,
            "duplicate native response/request cannot be counted again")
        seen_ids.add(rid); seen_requests.add(request_sha)
    require(counts == NEW_COUNTS, "original consumed stage counts differ")
    expected_summary = session.base.policy.accounting_summary(inherited, receipts,
        stage_limits=session.REMAINING, unknown_reservations=0)
    require(state.get("schema") == session.VERSION + "/state" and state.get("status") == "halt_live_script_capacity"
        and state.get("spend_verification_pending") is False and state.get("text_ready_for_director") is False
        and state.get("old_director_capacity") == session.DIRECTOR
        and all(state.get(k) is False for k in ("human_quality_approved", "creative_quality_passed", "media_authorized"))
        and digest(state.get("spend")) == digest(expected_summary), "original terminal653 state/spend differs")
    cumulative = {key: counts[key] + session.CONSUMED[key] for key in counts}
    remaining = {key: session.ORIGINAL_LIMITS[key] - cumulative[key] for key in counts}
    require(cumulative == CONSUMED and remaining == REMAINING and sum(cumulative.values()) == 13
        and sum(remaining.values()) == 13 and remaining["complete_script"] == 0,
        "three whole bodies already exhausted; remaining calls cannot regrant that stage")
    result = {"calls_started": expected_summary["effective_calls_started"],
        "reported_tokens": expected_summary["effective_reported_tokens"],
        "calls_with_known_usage": expected_summary["effective_calls_with_known_usage"],
        "pending_ordinals": deepcopy(inherited["pending_ordinals"]),
        "unknown_token_reservations": inherited["unknown_token_reservations"]}
    require(result == EXPECTED, "original653 cumulative spend differs")
    return result


def build_anchor():
    reader = evidence.Reader(); original = session.Session.open(ROOT)
    # Original scope/source and frozen-byte gates, with no active-round check.
    original._guard()
    config = reader.json(ROOT / "SESSION_CONFIG.json"); freeze = reader.json(ROOT / "PRODUCTION_FREEZE.json")
    parent = reader.json(config["parent_anchor_path"])
    parent_proof = parent644.verify_anchor(parent, expected_anchor_sha256=config["parent_anchor_sha256"])
    require(parent_proof.get("verified") is True and parent_proof.get("inherited") == parent["inherited"], "verified644 parent required")
    ledger = reader.json(ROOT / "CALL_LEDGER.json"); state = reader.json(ROOT / "STATE.json")
    receipts = [evidence.verify_original_receipt(ROOT, row, ledger["source_manifest"], reader=reader) for row in ledger["calls"]]
    evidence._tasks(reader, ROOT, ledger, receipts, original.config.grant_id)
    inherited = validate_accounting(parent, ledger, receipts, state)
    require(state["spend"] == original.runtime().summary(), "current original runtime accounting differs")
    run = reader.json(ROOT / "RUN_CLAIM.json")
    require(run.get("schema") == session.VERSION + "/run_claim" and run.get("automatic_restart") is False
        and run.get("freeze_sha256") == sha(ROOT / "PRODUCTION_FREEZE.json")
        and state.get("run_claim_sha256") == sha(ROOT / "RUN_CLAIM.json"), "original unique RUN/freeze identity differs")
    reader.json(ROOT / "USER_SCOPE.json"); reader.json(ROOT / "AUTHORIZATION.json")
    inputs = reader.json(ROOT / "INPUTS.json")
    goal, setup = receipts[0]["output"], receipts[5]["output"]
    session.workflow.validate_goal_document(goal, inputs=inputs)
    session.workflow.validate_opening_setup_document(setup, goal)
    reports = [r["output"] for r in receipts[1:5]]
    bundle = session.workflow.build_goal_audit_bundle(*reports)
    checked = session.workflow.validate_goal_audit(bundle, goal, inputs=inputs)
    session._require_accepted(checked, "settled653_original_goal_audits")
    def reference(index):
        row, receipt = ledger["calls"][index], receipts[index]
        return {"path": str(ROOT / row["receipt"]), "file_sha256": row["receipt_sha256"],
            "ordinal": row["ordinal"], "label": row["label"], "request_sha256": receipt["request_sha256"],
            "native_sha256": digest(receipt["output"]), "status": receipt["status"],
            "original_validation_sha256": digest(receipt.get("validation"))}
    files = {**parent_proof["source_files"], **freeze["files"],
        **{path: row["sha256"] for path, row in reader.files.items()}}
    files[str(Path(__file__).resolve())] = sha(__file__)
    identity = {"root": str(ROOT), "end_ordinal": 653,
        "terminal_state_sha256": sha(ROOT / "STATE.json"), "native_ledger_sha256": sha(ROOT / "CALL_LEDGER.json"),
        "production_freeze_sha256": sha(ROOT / "PRODUCTION_FREEZE.json")}
    return {"schema": VERSION, "verifier_code_sha256": sha(__file__), "root": str(ROOT), "parent_identity": identity,
        "parent_identity_sha256": digest(identity), "inherited": inherited,
        "parent_anchor_path": config["parent_anchor_path"], "parent_anchor_sha256": config["parent_anchor_sha256"],
        "source_files": files, "original_scope_limits": deepcopy(session.ORIGINAL_LIMITS),
        "previous_scope_consumed_stage_calls": deepcopy(session.CONSUMED), "new_stage_calls": NEW_COUNTS,
        "consumed_stage_calls": CONSUMED, "remaining_scope_limits": REMAINING,
        "total_original_scope": 26, "consumed_calls": 13, "remaining_calls": 13,
        "whole_plans_used": 2, "whole_plans_remaining": 1, "opening_setups_used": 1,
        "complete_scripts_used": 3, "complete_script_limit": 3, "remaining_complete_scripts": 0,
        "body_capacity_exhausted": True, "remaining_calls_do_not_regrant_body_capacity": True,
        "old_director_capacity": session.DIRECTOR,
        "native_goal_receipt": reference(0), "native_goal_audit_receipts": {kind: reference(i + 1) for i, kind in enumerate(session.workflow.AUDITS)},
        "native_opening_setup_receipt": reference(5), "rejected_body_receipts": [reference(i) for i in range(6, 9)],
        "original_goal_bundle_sha256": digest(bundle), "same_source_goal_audit_decision_sha256": digest(checked),
        "all_new_results_and_usage_known": True, "text_ready_for_director": False,
        "body_or_full_review_approved": False, "old_budget_reset": False, "authorizes_dispatch": False,
        "source_freshness_for_next_production_certified": False, "counter_or_new_scope_admitted": False,
        "verification_scope": "Original644 certificate plus645--653 raw SDK/wire/SQLite/native usage and frozen v2 scope; original goal four-audit and setup binding rechecked. Historical verification is not new production authorization."}


def verify_anchor(anchor, *, expected_anchor_sha256):
    require(type(anchor) is dict and digest(anchor) == expected_anchor_sha256, "settled653 anchor identity differs")
    require(build_anchor() == anchor, "original653 source/SDK/SQL/accounting evidence changed")
    return {"verified": True, "anchor": deepcopy(anchor), "inherited": deepcopy(anchor["inherited"]),
        "source_files": deepcopy(anchor["source_files"]), "parent_identity": deepcopy(anchor["parent_identity"]),
        "body_capacity_exhausted": True, "authorizes_dispatch": False}
