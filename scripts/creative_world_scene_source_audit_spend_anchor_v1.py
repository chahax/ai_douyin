"""Known-complete source-audit accounting; native opinions are not admission.

Only the fixed v1 source-audit protocol and its contract-rejected terminal are
supported here. Unknown transport/usage, unsupported protocols and restart are
never settled or granted another call by this read-only adapter.
"""
from copy import deepcopy
import json
from pathlib import Path

from scripts import creative_session_spend_anchor_v1 as evidence
from scripts import creative_world_scene_known_text_spend_anchor_v1 as parent_text
from scripts import creative_world_scene_source_state_audit_session_v1 as session

VERSION = "creative_world_scene_source_audit_spend_anchor/v1"
digest, sha, require = session.digest, session.sha, parent_text.require
PRESERVED = (*parent_text.PRESERVED, "current_text_scope_accounting", "recent_rejected_body_receipts",
    "last_known_rejected_body_receipt", "cumulative_body_attempts_used", "cumulative_authorized_body_attempts")


def _decision_identity(value):
    require(type(value) is dict and type(value.get("findings")) is list, "complete original derived decision required")
    result = deepcopy(value)
    for key in ("findings", "contract_findings"):
        if key in result:
            require(type(result[key]) is list, "complete original diagnostic rows required")
            result[key] = sorted(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
                for row in result[key])
    return result


def validate_records(parent, ledger, receipts, state, scope, summary, decision, *, expected_end):
    """Pure original accounting and refusal checks; does not infer semantics."""
    require(type(expected_end) is int and expected_end > 0, "typed expected end ordinal required")
    inherited = evidence._spend(parent["inherited"])
    require(parent.get("schema") == parent_text.VERSION and parent.get("body_capacity_exhausted") is True
        and parent.get("remaining_complete_scripts") == 0
        and parent.get("cumulative_body_attempts_used") == parent.get("cumulative_authorized_body_attempts") == 8
        and [r["ordinal"] for r in parent.get("rejected_body_receipts", [])] == [651, 652, 653, 654, 655, 656, 661, 662]
        and [r["ordinal"] for r in parent.get("registered_diagnostic_receipts", [])] == [657, 658, 659, 660],
        "verified original eight bodies/four diagnostics must remain spent")
    require(ledger.get("schema") == "authorized_creative_continuation/v3" and ledger.get("starting_spend") == inherited
        and ledger.get("max_total_tokens") is None
        and all(ledger.get(k) is False for k in ("automatic_retry", "old_budget_reset", "old_governance_migrated")),
        "original inherited no-reset/no-retry ledger required")
    require(scope.get("schema") == session.VERSION + "/derived_authorization" and scope.get("inherited") == inherited
        and scope.get("stage_limits") == session.LIMITS and all(type(v) is int for v in scope["stage_limits"].values())
        and type(scope.get("total_new_calls_limit")) is int and scope["total_new_calls_limit"] == 1
        and scope.get("diagnostic_only") is True and scope.get("creative_stage_authorized") is False
        and scope.get("old_complete_body_calls_used") == scope.get("old_complete_body_capacity") == 8
        and scope.get("diagnostic_calls_previously_used") == 4 and scope.get("old_director_capacity") == session.base.DIRECTOR
        and all(scope.get(k) is False for k in ("automatic_retry", "old_budget_reset", "media_authorized", "publish_authorized")),
        "original one-call source-audit scope required")
    calls = ledger.get("calls")
    require(type(calls) is list and len(calls) == len(receipts) == 1
        and calls[0].get("label") == session.LABEL and calls[0].get("ordinal") == expected_end == inherited["calls_started"] + 1,
        "one contiguous original source-audit receipt required")
    row, receipt = calls[0], receipts[0]
    native = session.native_proof.known_native(receipt)
    request, meta, failure = receipt.get("request", {}), receipt.get("response_metadata", {}), receipt.get("failure", {})
    require(receipt.get("ordinal") == expected_end and receipt.get("label") == session.LABEL
        and receipt.get("request_sha256") == digest(request) and receipt.get("source_binding_sha256") == digest(ledger["source_manifest"])
        and receipt.get("token_reservation") == row.get("token_reservation") and request.get("stage") == "goal_audit"
        and request.get("role") == "director" and receipt.get("status") == "contract_rejected"
        and receipt.get("automatic_retry") is False and receipt.get("semantic_approval") is False and bool(receipt.get("completed_at"))
        and failure.get("category") in ("validation", "state_contract", "compilation")
        and failure.get("response_received") is True and failure.get("automatic_retry") is False,
        "known original complete tool/contract rejection required")
    usage = receipt.get("response_payload", {}).get("usage", {})
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        require(type(meta.get(key)) is int and meta[key] >= 0 and type(usage.get(key)) is int and usage[key] == meta[key],
            "unknown or nontyped original usage cannot settle")
    require(meta["prompt_tokens"] + meta["completion_tokens"] == meta["total_tokens"], "original usage sum differs")
    expected = session.base.policy.accounting_summary(inherited, receipts, stage_limits=session.LIMITS, unknown_reservations=0)
    require(state.get("schema") == session.VERSION + "/state" and summary.get("schema") == session.VERSION + "/summary"
        and state.get("status") == summary.get("status") == "halt_source_state_audit_contract"
        and state.get("spend_verification_pending") is summary.get("spend_verification_pending") is False
        and state.get("spend") == summary.get("spend") == expected
        and state.get("summary_sha256") == digest(summary) and summary.get("receipt_ordinal") == expected_end
        and summary.get("native_audit_sha256") == digest(native) and summary.get("derived_decision_sha256") == digest(decision)
        and _decision_identity(receipt.get("validation")) == _decision_identity(decision)
        and decision.get("valid") is False and decision.get("accepted") is False
        and decision.get("native_report_sha256") == digest(native) and decision.get("native_report_modified") is False
        and state.get("old_director_capacity") == session.base.DIRECTOR
        and state.get("diagnostic_only") is summary.get("diagnostic_only") is True
        and state.get("old_complete_body_calls_used") == 8 and state.get("diagnostic_calls_previously_used") == 4
        and all(state.get(k) is False for k in ("human_quality_approved", "creative_quality_passed", "media_authorized", "text_ready_for_director"))
        and all(summary.get(k) is False for k in ("human_quality_approved", "creative_quality_passed", "media_submitted", "text_ready_for_director")),
        "original contract refusal/summary/state differs; native pass is never admission")
    return {"calls_started": expected["effective_calls_started"], "reported_tokens": expected["effective_reported_tokens"],
        "calls_with_known_usage": expected["effective_calls_with_known_usage"], "pending_ordinals": deepcopy(inherited["pending_ordinals"]),
        "unknown_token_reservations": inherited["unknown_token_reservations"]}


def build_anchor(root, *, expected_end):
    root = session.base._inside(root); reader = evidence.Reader()
    state = reader.json(root / "STATE.json")
    require(state.get("schema") == session.VERSION + "/state", "unsupported source-audit session protocol")
    original = session.Session.open(root); original._guard()
    config = reader.json(root / "SESSION_CONFIG.json"); freeze = reader.json(root / "PRODUCTION_FREEZE.json")
    scope = reader.json(root / "USER_SCOPE.json"); reader.json(root / "AUTHORIZATION.json")
    parent = reader.json(config["parent_anchor_path"])
    proof = parent_text.verify_anchor(parent, expected_anchor_sha256=config["parent_anchor_sha256"])
    require(proof.get("verified") is True and proof.get("inherited") == parent["inherited"], "verified original known-text parent required")
    ledger = reader.json(root / "CALL_LEDGER.json"); summary = reader.json(root / "SUMMARY.json")
    receipts = [evidence.verify_original_receipt(root, row, ledger["source_manifest"], reader=reader) for row in ledger["calls"]]
    evidence._tasks(reader, root, ledger, receipts, config["grant_id"])
    required_paths = {"native_audit": str(root / "NATIVE_SOURCE_STATE_AUDIT.json"), "derived_decision": str(root / "SOURCE_STATE_AUDIT_DECISION.json")}
    require(summary.get("paths") == required_paths, "original native/decision artifact paths differ")
    require(set(summary.get("artifact_file_sha256", {})) == set(required_paths.values()), "original exact source-audit artifacts required")
    for path, expected in summary["artifact_file_sha256"].items(): reader.verify(path, expected)
    native, decision = (reader.json(required_paths[key]) for key in ("native_audit", "derived_decision"))
    inherited = validate_records(parent, ledger, receipts, state, scope, summary, decision, expected_end=expected_end)
    require(native == receipts[0]["output"] and state["spend"] == original.runtime().summary(), "original native/runtime differs")
    run = reader.json(root / "RUN_CLAIM.json")
    require(run.get("schema") == session.VERSION + "/run_claim" and run.get("root") == str(root) and run.get("automatic_restart") is False
        and run.get("freeze_sha256") == sha(root / "PRODUCTION_FREEZE.json") and state.get("run_claim_sha256") == sha(root / "RUN_CLAIM.json"),
        "original single RUN/freeze differs")
    inputs = reader.json(root / "INPUTS.json")
    require(digest(inputs) == parent["original_inputs_sha256"] and inputs == reader.json(parent["original_inputs_path"]), "original creative input authority changed")
    prepared = original._request(inputs); receipt, row = receipts[0], ledger["calls"][0]
    intent = reader.json(root / "call_intents" / (session.LABEL + ".json"))
    require(intent.get("schema") == session.VERSION + "/call_intent" and intent.get("label") == session.LABEL
        and intent.get("automatic_retry") is False and intent.get("request") == prepared["request"] == receipt["request"]
        and intent.get("request_sha256") == receipt["request_sha256"] and intent.get("ledger_prefix_sha256") == digest([]),
        "original exact source-audit request/intent differs")
    require(_decision_identity(original.audit.validate(native, prepared)) == _decision_identity(decision), "original source-audit refusal recomputation differs")
    profile_path = session.base._inside(config["profile_path"]); profile = reader.json(profile_path)
    old_profile = reader.json(parent["original_profile_path"])
    expected_profile = deepcopy(old_profile); expected_profile.setdefault("stage_parameters", {}).setdefault("goal_audit", {})["max_completion_tokens"] = 32000
    require(profile == expected_profile, "original creative16k and audit32k profiles must remain separate")
    files = {**proof["source_files"], **freeze["files"], **{path: value["sha256"] for path, value in reader.files.items()}}
    files[str(Path(__file__).resolve())] = sha(__file__)
    identity = {"root": str(root), "end_ordinal": expected_end, "terminal_state_sha256": sha(root / "STATE.json"),
        "native_ledger_sha256": sha(root / "CALL_LEDGER.json"), "production_freeze_sha256": sha(root / "PRODUCTION_FREEZE.json")}
    reference = {"path": str(root / row["receipt"]), "file_sha256": row["receipt_sha256"], "ordinal": row["ordinal"],
        "label": row["label"], "request_sha256": receipt["request_sha256"], "native_sha256": digest(native), "status": receipt["status"],
        "original_validation_sha256": digest(receipt["validation"])}
    decision_ref = {"path": required_paths["derived_decision"], "file_sha256": sha(required_paths["derived_decision"]), "native_sha256": digest(decision),
        "receipt_ordinal": expected_end, "valid": decision["valid"], "accepted": decision["accepted"], "status": decision["status"]}
    result = {"schema": VERSION, "session_schema": session.VERSION, "verifier_code_sha256": sha(__file__), "root": str(root),
        "parent_identity": identity, "parent_identity_sha256": digest(identity), "inherited": inherited,
        "parent_anchor_path": config["parent_anchor_path"], "parent_anchor_sha256": config["parent_anchor_sha256"], "source_files": files,
        "latest_source_state_audit_receipt": reference, "latest_source_state_audit_decision_ref": decision_ref,
        "source_state_audit_receipts": [deepcopy(reference)], "source_state_audit_profile_path": str(profile_path),
        "source_state_audit_profile_file_sha256": sha(profile_path), "source_state_audit_profile_sha256": digest(profile),
        "source_state_audit_scope_accounting": {"used": 1, "limit": 1, "remaining": 0, "reported_tokens": state["spend"]["new_reported_tokens"],
            "stage_calls": deepcopy(session.LIMITS), "creative_body_attempts_added": 0},
        "source_state_audit_native_semantic_status": native.get("overall_status"), "source_state_audit_contract_valid": False,
        "source_state_audit_semantically_accepted": False, "native_semantic_status_is_not_admission": True,
        "remaining_complete_scripts": 0, "body_capacity_exhausted": True, "old_body_capacity_exhausted": True,
        "additional_body_capacity_exhausted": True, "old_director_capacity": deepcopy(session.base.DIRECTOR),
        "all_new_results_and_usage_known": True, "old_budget_reset": False, "authorizes_dispatch": False,
        "remaining_call_counts_are_accounting_not_new_grants": True, "body_or_full_review_approved": False,
        "text_ready_for_director": False, "source_freshness_for_next_production_certified": False, "counter_or_new_scope_admitted": False,
        "verification_scope": "Fixed v1 source-audit contract rejection: original SDK/wire/SQLite/freeze/RUN/request/native/derived-refusal/SUMMARY. Eight body failures and four interface diagnostics preserved. Native semantic opinion is not admitted and original creative16k/audit32k profiles remain distinct."}
    for key in PRESERVED: result[key] = deepcopy(parent[key])
    return result


def verify_anchor(anchor, *, expected_anchor_sha256):
    require(type(anchor) is dict and anchor.get("schema") == VERSION and digest(anchor) == expected_anchor_sha256, "source-audit anchor identity differs")
    require(build_anchor(anchor["root"], expected_end=anchor["parent_identity"]["end_ordinal"]) == anchor, "original source-audit evidence changed")
    return {"verified": True, "anchor": deepcopy(anchor), "inherited": deepcopy(anchor["inherited"]),
        "source_files": deepcopy(anchor["source_files"]), "parent_identity": deepcopy(anchor["parent_identity"]),
        "creative_source_root": anchor["creative_source_root"], "body_capacity_exhausted": True, "authorizes_dispatch": False}
