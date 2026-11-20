"""Read-only settled656 accounting. Both three-body scopes remain exhausted.

The original645/four-audit/650 native references are inherited unchanged.
No next scope, model request, claim, body adoption or media is authorized.
"""
from copy import deepcopy
from pathlib import Path
from scripts import creative_world_scene_live_session_v3 as session
from scripts import creative_world_scene_spend_anchor_v3 as parent653
from scripts import creative_session_spend_anchor_v1 as evidence

VERSION = "creative_world_scene_spend_anchor/v4"
ROOT = session.base.PROJECT / "data/production_trials/world_scene_live_20261015/round_03"
EXPECTED = {"calls_started": 656, "reported_tokens": 14061496, "calls_with_known_usage": 654,
    "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
NEW_COUNTS = {"goal_plan": 0, "goal_audit": 0, "complete_script": 3, "full_review": 0}
REMAINING = {"goal_plan": 0, "goal_audit": 0, "complete_script": 0, "full_review": 6}
digest, sha, require = session.digest, session.sha, parent653.require


def validate_accounting(parent, ledger, receipts, state):
    inherited = evidence._spend(parent["inherited"])
    require(inherited == parent653.EXPECTED and ledger.get("starting_spend") == inherited
        and parent.get("body_capacity_exhausted") is True and parent.get("complete_scripts_used") == 3
        and parent.get("remaining_complete_scripts") == 0, "original653 consumption/body exhaustion omitted")
    require(ledger.get("schema") == "authorized_creative_continuation/v3" and ledger.get("max_total_tokens") is None
        and all(ledger.get(k) is False for k in ("automatic_retry", "old_budget_reset", "old_governance_migrated")),
        "original no-retry/no-reset ledger required")
    calls = ledger.get("calls")
    require(type(calls) is list and len(calls) == len(receipts) == 3
        and [row.get("ordinal") for row in calls] == [654, 655, 656]
        and [row.get("label") for row in calls] == ["complete_script_04", "complete_script_05", "complete_script_06"],
        "exact original654--656 native attempts required")
    seen_ids, seen_requests = set(), set()
    for row, receipt in zip(calls, receipts):
        session.base.NativeSession.known(receipt, row["label"], require_valid=False)
        request, meta = receipt.get("request", {}), receipt.get("response_metadata", {})
        require(receipt.get("ordinal") == row["ordinal"] and receipt.get("label") == row["label"]
            and receipt.get("request_sha256") == digest(request)
            and receipt.get("source_binding_sha256") == digest(ledger["source_manifest"])
            and receipt.get("status") == "contract_rejected" and request.get("stage") == "complete_script"
            and request.get("role") == "writer" and receipt.get("automatic_retry") is False
            and receipt.get("semantic_approval") is False and bool(receipt.get("completed_at"))
            and not receipt.get("cached_response_read_only"), "known complete original rejected body identity differs")
        usage = receipt.get("response_payload", {}).get("usage", {})
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            require(type(meta.get(key)) is int and meta[key] >= 0 and type(usage.get(key)) is int and usage[key] == meta[key],
                "unknown/nontyped original usage cannot settle")
        require(meta["prompt_tokens"] + meta["completion_tokens"] == meta["total_tokens"], "original usage sum differs")
        rid, request_sha = meta.get("response_id"), receipt["request_sha256"]
        require(isinstance(rid, str) and bool(rid) and rid not in seen_ids and request_sha not in seen_requests,
            "duplicate response/request cannot be counted again")
        seen_ids.add(rid); seen_requests.add(request_sha)
    expected_summary = session.base.policy.accounting_summary(inherited, receipts, stage_limits=session.LIMITS, unknown_reservations=0)
    require(state.get("schema") == session.VERSION + "/state" and state.get("status") == "halt_live_script_capacity"
        and state.get("spend_verification_pending") is False and state.get("text_ready_for_director") is False
        and state.get("old_director_capacity") == session.base.DIRECTOR
        and state.get("new_body_scope_is_separate") is True and state.get("old_scope_stage_calls") == session.OLD_CONSUMED
        and state.get("new_stage_limits") == session.LIMITS and state.get("body_versions_available") == [4, 5, 6]
        and all(state.get(k) is False for k in ("human_quality_approved", "creative_quality_passed", "media_authorized"))
        and digest(state.get("spend")) == digest(expected_summary), "original terminal656 scope or spend differs")
    result = {"calls_started": expected_summary["effective_calls_started"], "reported_tokens": expected_summary["effective_reported_tokens"],
        "calls_with_known_usage": expected_summary["effective_calls_with_known_usage"],
        "pending_ordinals": deepcopy(inherited["pending_ordinals"]), "unknown_token_reservations": inherited["unknown_token_reservations"]}
    require(result == EXPECTED, "original cumulative656 spend differs")
    return result


def build_anchor():
    reader = evidence.Reader(); original = session.Session.open(ROOT); original._guard()
    config = reader.json(ROOT / "SESSION_CONFIG.json"); freeze = reader.json(ROOT / "PRODUCTION_FREEZE.json")
    parent = reader.json(config["parent_anchor_path"])
    parent_proof = parent653.verify_anchor(parent, expected_anchor_sha256=config["parent_anchor_sha256"])
    require(parent_proof.get("verified") is True and parent_proof.get("inherited") == parent["inherited"], "verified original653 required")
    ledger = reader.json(ROOT / "CALL_LEDGER.json"); state = reader.json(ROOT / "STATE.json")
    receipts = [evidence.verify_original_receipt(ROOT, row, ledger["source_manifest"], reader=reader) for row in ledger["calls"]]
    evidence._tasks(reader, ROOT, ledger, receipts, original.config.grant_id)
    inherited = validate_accounting(parent, ledger, receipts, state)
    require(state["spend"] == original.runtime().summary(), "original runtime accounting differs")
    run = reader.json(ROOT / "RUN_CLAIM.json")
    require(run.get("schema") == session.VERSION + "/run_claim" and run.get("root") == str(ROOT)
        and run.get("automatic_restart") is False and run.get("freeze_sha256") == sha(ROOT / "PRODUCTION_FREEZE.json")
        and state.get("run_claim_sha256") == sha(ROOT / "RUN_CLAIM.json"), "original unique RUN/freeze differs")
    reader.json(ROOT / "USER_SCOPE.json"); reader.json(ROOT / "AUTHORIZATION.json")
    new_refs = [{"path": str(ROOT / row["receipt"]), "file_sha256": row["receipt_sha256"], "ordinal": row["ordinal"],
        "label": row["label"], "request_sha256": receipt["request_sha256"], "native_sha256": digest(receipt["output"]),
        "status": receipt["status"], "original_validation_sha256": digest(receipt.get("validation"))}
        for row, receipt in zip(ledger["calls"], receipts)]
    old_refs = deepcopy(parent["rejected_body_receipts"])
    require([r["ordinal"] for r in old_refs] == [651, 652, 653] and all(r["status"] == "contract_rejected" for r in old_refs),
        "all old three rejected body receipts must remain")
    files = {**parent_proof["source_files"], **freeze["files"], **{path: value["sha256"] for path, value in reader.files.items()}}
    files[str(Path(__file__).resolve())] = sha(__file__)
    identity = {"root": str(ROOT), "end_ordinal": 656, "terminal_state_sha256": sha(ROOT / "STATE.json"),
        "native_ledger_sha256": sha(ROOT / "CALL_LEDGER.json"), "production_freeze_sha256": sha(ROOT / "PRODUCTION_FREEZE.json")}
    result = {"schema": VERSION, "verifier_code_sha256": sha(__file__), "root": str(ROOT),
        "parent_identity": identity, "parent_identity_sha256": digest(identity), "inherited": inherited,
        "parent_anchor_path": config["parent_anchor_path"], "parent_anchor_sha256": config["parent_anchor_sha256"], "source_files": files,
        "new_stage_calls": NEW_COUNTS, "new_scope_limits": deepcopy(session.LIMITS), "new_scope_remaining_stage_calls": REMAINING,
        "original_scope_accounting": {"limits": deepcopy(parent["original_scope_limits"]), "consumed": deepcopy(parent["consumed_stage_calls"]),
            "remaining": deepcopy(parent["remaining_scope_limits"]), "calls_used": 13, "calls_remaining": 13, "body_used": 3, "body_limit": 3},
        "additional_scope_accounting": {"limits": deepcopy(session.LIMITS), "consumed": NEW_COUNTS,
            "remaining": REMAINING, "calls_used": 3, "calls_remaining": 6, "body_used": 3, "body_limit": 3},
        "cumulative_body_attempts_used": 6, "cumulative_authorized_body_attempts": 6, "remaining_complete_scripts": 0,
        "old_body_capacity_exhausted": True, "additional_body_capacity_exhausted": True, "body_capacity_exhausted": True,
        "remaining_call_counts_are_accounting_not_new_grants": True,
        "rejected_body_receipts": old_refs + new_refs, "recent_rejected_body_receipts": new_refs,
        "old_director_capacity": deepcopy(session.base.DIRECTOR), "all_new_results_and_usage_known": True,
        "full_review_calls_started_in_either_body_run": 0, "text_ready_for_director": False,
        "body_or_full_review_approved": False, "old_budget_reset": False, "authorizes_dispatch": False,
        "source_freshness_for_next_production_certified": False, "counter_or_new_scope_admitted": False,
        "verification_scope": "Certified653 plus original654--656 complete SDK/wire/SQLite/STATE and frozen independent scope; all six native bodies remain rejected and spent. No automatic full-body continuation or semantic approval."}
    for key in ("native_goal_receipt", "native_goal_audit_receipts", "native_opening_setup_receipt",
                "original_goal_bundle_sha256", "same_source_goal_audit_decision_sha256"):
        result[key] = deepcopy(parent[key])
    return result


def verify_anchor(anchor, *, expected_anchor_sha256):
    require(type(anchor) is dict and digest(anchor) == expected_anchor_sha256, "settled656 anchor identity differs")
    require(build_anchor() == anchor, "original656 evidence changed")
    return {"verified": True, "anchor": deepcopy(anchor), "inherited": deepcopy(anchor["inherited"]),
        "source_files": deepcopy(anchor["source_files"]), "parent_identity": deepcopy(anchor["parent_identity"]),
        "body_capacity_exhausted": True, "authorizes_dispatch": False}
