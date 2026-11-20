"""Read-only known-text accounting, with explicitly supported session protocols.

The first supported protocol is the v4 exhausted two-body continuation. Adding
another protocol requires a new explicit handler; roots cannot select imports.
Original native failures remain failures and accounting never grants dispatch.
"""
from copy import deepcopy
from pathlib import Path

from scripts import creative_session_spend_anchor_v1 as evidence
from scripts import creative_world_scene_array_probe_spend_anchor_v1 as parent_bridge
from scripts import creative_world_scene_live_session_v4 as v4

VERSION = "creative_world_scene_known_text_spend_anchor/v1"
SUPPORTED = {v4.VERSION + "/state": v4}
digest, sha, require = v4.digest, v4.sha, parent_bridge.require
PRESERVED = (*parent_bridge.PRESERVED, "registered_diagnostic_receipts", "diagnostic_scope_accounting",
    "creative_source_root", "original_creation_root", "original_inputs_path", "original_inputs_file_sha256",
    "original_inputs_sha256", "original_profile_path", "original_profile_file_sha256")


def _handler(state):
    require(type(state) is dict and state.get("schema") in SUPPORTED, "unsupported known-text session protocol")
    return SUPPORTED[state["schema"]]


def validate_records(parent, ledger, receipts, state, scope, *, expected_end):
    """Pure typed accounting. No SDK/claim or original-record mutation."""
    module = _handler(state)
    inherited = evidence._spend(parent["inherited"])
    require(type(expected_end) is int and expected_end > 0, "explicit typed expected end ordinal required")
    require(parent.get("schema") == parent_bridge.VERSION and inherited == parent_bridge.EXPECTED
        and parent.get("cumulative_body_attempts_used") == parent.get("cumulative_authorized_body_attempts") == 6
        and parent.get("body_capacity_exhausted") is True and parent.get("remaining_complete_scripts") == 0
        and [r["ordinal"] for r in parent.get("rejected_body_receipts", [])] == list(range(651, 657))
        and [r["ordinal"] for r in parent.get("registered_diagnostic_receipts", [])] == list(range(657, 661)),
        "certified parent consumption, six body failures and four diagnostics required")
    require(ledger.get("starting_spend") == inherited and scope.get("inherited") == inherited
        and ledger.get("schema") == "authorized_creative_continuation/v3" and ledger.get("max_total_tokens") is None
        and all(ledger.get(k) is False for k in ("automatic_retry", "old_budget_reset", "old_governance_migrated")),
        "original inherited no-retry/no-reset ledger required")
    require(scope.get("schema") == module.VERSION + "/derived_authorization" and scope.get("stage_limits") == module.LIMITS
        and all(type(v) is int for v in scope["stage_limits"].values()) and scope.get("total_new_calls_limit") == module.TOTAL
        and scope.get("body_versions_available") == module.BODY_VERSIONS and scope.get("old_complete_body_calls_used") == 6
        and scope.get("old_complete_body_capacity") == 6 and scope.get("diagnostic_calls_previously_used") == 4
        and scope.get("new_body_scope_is_separate") is True
        and all(scope.get(k) is False for k in ("automatic_retry", "old_budget_reset", "media_authorized", "publish_authorized")),
        "original v4 independent two-body scope required")
    calls = ledger.get("calls")
    labels = [f"complete_script_{n:02}" for n in module.BODY_VERSIONS]
    require(type(calls) is list and len(calls) == len(receipts) == len(labels)
        and [row.get("label") for row in calls] == labels
        and [row.get("ordinal") for row in calls] == list(range(inherited["calls_started"] + 1, expected_end + 1)),
        "complete contiguous original rejected body attempts required")
    ids, requests = set(), set()
    for row, receipt in zip(calls, receipts):
        module.base.NativeSession.known(receipt, row["label"], require_valid=False)
        request, meta, failure = receipt.get("request", {}), receipt.get("response_metadata", {}), receipt.get("failure", {})
        require(receipt.get("ordinal") == row["ordinal"] and receipt.get("label") == row["label"]
            and receipt.get("request_sha256") == digest(request) and receipt.get("source_binding_sha256") == digest(ledger["source_manifest"])
            and receipt.get("token_reservation") == row.get("token_reservation")
            and receipt.get("status") == "contract_rejected" and request.get("stage") == "complete_script" and request.get("role") == "writer"
            and receipt.get("automatic_retry") is False and receipt.get("semantic_approval") is False and bool(receipt.get("completed_at"))
            and not receipt.get("cached_response_read_only")
            and failure.get("category") in ("validation", "state_contract", "compilation")
            and failure.get("response_received") is True and failure.get("automatic_retry") is False,
            "known complete original content rejection required; protocol/unknown cannot settle")
        usage = receipt.get("response_payload", {}).get("usage", {})
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            require(type(meta.get(key)) is int and meta[key] >= 0 and type(usage.get(key)) is int
                and usage[key] == meta[key], "unknown or nontyped usage cannot settle")
        require(meta["prompt_tokens"] + meta["completion_tokens"] == meta["total_tokens"], "original usage sum differs")
        rid, request_sha = meta.get("response_id"), receipt["request_sha256"]
        require(type(rid) is str and bool(rid) and rid not in ids and request_sha not in requests, "duplicate original response/request")
        ids.add(rid); requests.add(request_sha)
    expected = module.base.policy.accounting_summary(inherited, receipts, stage_limits=module.LIMITS, unknown_reservations=0)
    require(state.get("status") == "halt_live_script_capacity" and state.get("spend_verification_pending") is False
        and state.get("spend") == expected and state.get("old_director_capacity") == module.base.DIRECTOR
        and state.get("new_stage_limits") == module.LIMITS and state.get("body_versions_available") == module.BODY_VERSIONS
        and state.get("old_complete_body_calls_used") == 6 and state.get("diagnostic_calls_previously_used") == 4
        and state.get("new_body_scope_is_separate") is True
        and all(state.get(k) is False for k in ("human_quality_approved", "creative_quality_passed", "media_authorized", "text_ready_for_director")),
        "known terminal exhausted-body scope/state differs")
    result = {"calls_started": expected["effective_calls_started"], "reported_tokens": expected["effective_reported_tokens"],
        "calls_with_known_usage": expected["effective_calls_with_known_usage"], "pending_ordinals": deepcopy(inherited["pending_ordinals"]),
        "unknown_token_reservations": inherited["unknown_token_reservations"]}
    require(result["calls_started"] == expected_end and expected["stage_calls"]["complete_script"] == module.LIMITS["complete_script"]
        and expected["stage_calls"]["full_review"] == 0, "supported v4 body-only terminal scope exhausted")
    return result


def build_anchor(root, *, expected_end):
    root = v4.base._inside(root); reader = evidence.Reader()
    state = reader.json(root / "STATE.json"); module = _handler(state)
    original = module.Session.open(root); original._guard()
    config = reader.json(root / "SESSION_CONFIG.json"); freeze = reader.json(root / "PRODUCTION_FREEZE.json")
    scope = reader.json(root / "USER_SCOPE.json"); reader.json(root / "AUTHORIZATION.json")
    parent = reader.json(config["parent_anchor_path"])
    proof = parent_bridge.verify_anchor(parent, expected_anchor_sha256=config["parent_anchor_sha256"])
    require(proof.get("verified") is True and proof.get("inherited") == parent["inherited"], "verified original parent required")
    ledger = reader.json(root / "CALL_LEDGER.json")
    receipts = [evidence.verify_original_receipt(root, row, ledger["source_manifest"], reader=reader) for row in ledger["calls"]]
    evidence._tasks(reader, root, ledger, receipts, config["grant_id"])
    inherited = validate_records(parent, ledger, receipts, state, scope, expected_end=expected_end)
    require(state["spend"] == original.runtime().summary(), "original runtime accounting differs")
    run = reader.json(root / "RUN_CLAIM.json")
    require(run.get("schema") == module.VERSION + "/run_claim" and run.get("root") == str(root)
        and run.get("automatic_restart") is False and run.get("freeze_sha256") == sha(root / "PRODUCTION_FREEZE.json")
        and state.get("run_claim_sha256") == sha(root / "RUN_CLAIM.json"), "original unique RUN/freeze differs")
    inputs = reader.json(root / "INPUTS.json")
    require(digest(inputs) == parent["original_inputs_sha256"] and inputs == reader.json(parent["original_inputs_path"]),
        "original clean creative authority changed")
    goal_ref = parent["native_goal_receipt"]; reader.verify(goal_ref["path"], goal_ref["file_sha256"])
    goal = reader.json(goal_ref["path"])["output"]
    references = []
    for index, (row, receipt) in enumerate(zip(ledger["calls"], receipts)):
        intent_path = root / "call_intents" / (row["label"] + ".json"); intent = reader.json(intent_path)
        require(intent.get("schema") == module.VERSION + "/call_intent" and intent.get("label") == row["label"]
            and intent["prepared"]["request"] == receipt["request"] and intent.get("request_sha256") == receipt["request_sha256"]
            and intent.get("ledger_prefix_sha256") == digest(ledger["calls"][:index]) and intent.get("inputs_sha256") == digest(inputs)
            and intent.get("automatic_retry") is False, "original request/prerequisite call intent differs")
        diagnostic = module.contract.diagnose(receipt["output"], goal)
        original_diagnostic = receipt.get("validation_error", {}).get("detail")
        require(diagnostic.get("valid") is False
            and parent_bridge._validation_identity(diagnostic) == parent_bridge._validation_identity(original_diagnostic),
            "original native structural diagnostic differs")
        references.append({"path": str(root / row["receipt"]), "file_sha256": row["receipt_sha256"], "ordinal": row["ordinal"],
            "label": row["label"], "request_sha256": receipt["request_sha256"], "native_sha256": digest(receipt["output"]),
            "status": receipt["status"], "original_validation_sha256": digest(receipt.get("validation")),
            "diagnostic_json_pointer": "/validation_error/detail", "original_diagnostic_sha256": digest(original_diagnostic)})
    files = {**proof["source_files"], **freeze["files"], **{path: value["sha256"] for path, value in reader.files.items()}}
    files[str(Path(__file__).resolve())] = sha(__file__)
    identity = {"root": str(root), "end_ordinal": expected_end, "terminal_state_sha256": sha(root / "STATE.json"),
        "native_ledger_sha256": sha(root / "CALL_LEDGER.json"), "production_freeze_sha256": sha(root / "PRODUCTION_FREEZE.json")}
    counts = state["spend"]["stage_calls"]; remaining = {k: module.LIMITS[k] - counts[k] for k in module.LIMITS}
    result = {"schema": VERSION, "session_schema": module.VERSION, "verifier_code_sha256": sha(__file__),
        "root": str(root), "parent_identity": identity, "parent_identity_sha256": digest(identity), "inherited": inherited,
        "parent_anchor_path": config["parent_anchor_path"], "parent_anchor_sha256": config["parent_anchor_sha256"], "source_files": files,
        "current_text_scope_accounting": {"limits": deepcopy(module.LIMITS), "consumed": deepcopy(counts), "remaining": remaining,
            "calls_used": len(receipts), "calls_remaining": sum(remaining.values()), "body_used": len(receipts), "body_limit": module.LIMITS["complete_script"]},
        "cumulative_body_attempts_used": parent["cumulative_body_attempts_used"] + len(receipts),
        "cumulative_authorized_body_attempts": parent["cumulative_authorized_body_attempts"] + module.LIMITS["complete_script"],
        "remaining_complete_scripts": 0, "body_capacity_exhausted": True, "old_body_capacity_exhausted": True,
        "additional_body_capacity_exhausted": True, "all_new_results_and_usage_known": True,
        "old_director_capacity": deepcopy(module.base.DIRECTOR), "old_budget_reset": False,
        "recent_rejected_body_receipts": references, "last_known_rejected_body_receipt": deepcopy(references[-1]),
        "body_or_full_review_approved": False, "text_ready_for_director": False, "authorizes_dispatch": False,
        "remaining_call_counts_are_accounting_not_new_grants": True, "creative_body_capacity_regranted": False,
        "source_freshness_for_next_production_certified": False, "counter_or_new_scope_admitted": False,
        "inherited_goal_audits_are_historical_not_new_source_state_approval": True,
        "verification_scope": "Explicit supported v4 exhausted-body protocol: original raw SDK/wire/SQLite/freeze/RUN/call intents and unchanged structural diagnostics. Historical original goal/audits/setup retained; no current source-state semantic approval or new dispatch scope."}
    for key in PRESERVED: result[key] = deepcopy(parent[key])
    result["rejected_body_receipts"] += references
    return result


def verify_anchor(anchor, *, expected_anchor_sha256):
    require(type(anchor) is dict and anchor.get("schema") == VERSION and digest(anchor) == expected_anchor_sha256,
        "known-text anchor identity differs")
    require(build_anchor(anchor["root"], expected_end=anchor["parent_identity"]["end_ordinal"]) == anchor, "original known-text evidence changed")
    return {"verified": True, "anchor": deepcopy(anchor), "inherited": deepcopy(anchor["inherited"]),
        "source_files": deepcopy(anchor["source_files"]), "parent_identity": deepcopy(anchor["parent_identity"]),
        "creative_source_root": anchor["creative_source_root"], "body_capacity_exhausted": True, "authorizes_dispatch": False}
