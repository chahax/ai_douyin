"""Read-only settlement of the fixed typed source-audit v2 protocol.

Known diagnostic acceptance/failure/uncertainty is preserved exactly. No such
diagnostic grants screenplay, production, media or a fresh call allowance.
"""
from copy import deepcopy
from pathlib import Path

from scripts import creative_session_spend_anchor_v1 as evidence
from scripts import creative_world_scene_source_audit_spend_anchor_v1 as parent_bridge
from scripts import creative_world_scene_source_state_audit_session_v2 as session

VERSION = "creative_world_scene_typed_audit_spend_anchor/v1"
digest, sha, require = session.digest, session.sha, parent_bridge.require
PRESERVED = (*parent_bridge.PRESERVED, "source_state_audit_profile_path", "source_state_audit_profile_file_sha256",
    "source_state_audit_profile_sha256")


def diagnostic_outcome(decision):
    require(type(decision) is dict and type(decision.get("valid")) is bool and type(decision.get("accepted")) is bool
        and all(type(decision.get(key)) is list for key in ("findings", "contract_findings", "uncertainties", "typed_replay")),
        "typed complete original v2 decision required")
    if not decision["valid"]:
        require(not decision["accepted"] and bool(decision["contract_findings"])
            and decision.get("status") == "source_state_contract_rejected", "invalid decision cannot be accepted")
        return "contract_rejected", "halt_source_state_audit_contract"
    require(not decision["contract_findings"], "valid decision cannot hide contract findings")
    if decision["uncertainties"]:
        require(not decision["accepted"] and decision.get("status") == "source_state_unknown", "unknown diagnostic cannot be accepted")
        return "uncertain", "halt_source_state_audit_uncertain"
    if decision["findings"]:
        require(not decision["accepted"] and decision.get("status") == "source_state_fail", "known content failure cannot be accepted")
        return "content_failure", "diagnostic_completed_known_content_failure"
    require(decision["accepted"] and decision.get("status") == "source_state_pass", "empty/nonaccepted diagnostic is inconsistent")
    return "accepted_diagnostic_only", "diagnostic_completed_not_creative"


def validate_records(parent, ledger, receipts, state, scope, summary, decision, *, expected_end):
    """Pure typed accounting; SDK evidence and frozen bytes are checked outside."""
    require(type(expected_end) is int and expected_end > 0, "typed expected end ordinal required")
    inherited = evidence._spend(parent["inherited"])
    old_scope = parent.get("source_state_audit_scope_accounting", {})
    require(parent.get("schema") == parent_bridge.VERSION and old_scope.get("used") == old_scope.get("limit") == 1
        and old_scope.get("remaining") == 0 and parent.get("source_state_audit_contract_valid") is False
        and parent.get("source_state_audit_semantically_accepted") is False
        and parent.get("cumulative_body_attempts_used") == parent.get("cumulative_authorized_body_attempts") == 8
        and parent.get("body_capacity_exhausted") is True and parent.get("remaining_complete_scripts") == 0
        and len(parent.get("rejected_body_receipts", [])) == 8 and len(parent.get("registered_diagnostic_receipts", [])) == 4,
        "original refused source audit and spent eight-body/four-diagnostic history required")
    require(ledger.get("schema") == "authorized_creative_continuation/v3" and ledger.get("starting_spend") == inherited
        and ledger.get("max_total_tokens") is None
        and all(ledger.get(k) is False for k in ("automatic_retry", "old_budget_reset", "old_governance_migrated")),
        "original inherited no-reset/no-retry ledger required")
    require(scope.get("schema") == session.VERSION + "/derived_authorization" and scope.get("native_audit_version") == session.AUDIT_VERSION
        and scope.get("inherited") == inherited and scope.get("stage_limits") == session.LIMITS
        and all(type(v) is int for v in scope["stage_limits"].values())
        and type(scope.get("total_new_calls_limit")) is int and scope["total_new_calls_limit"] == 1
        and scope.get("diagnostic_only") is True and scope.get("creative_stage_authorized") is False
        and scope.get("old_complete_body_calls_used") == scope.get("old_complete_body_capacity") == 8
        and scope.get("diagnostic_calls_previously_used") == 4 and scope.get("old_director_capacity") == session.base.DIRECTOR
        and scope.get("prior_source_state_diagnostics_used") == scope.get("prior_source_state_diagnostics_limit") == 1
        and scope.get("prior_source_state_contract_accepted") is False
        and scope.get("profile_changed_from_parent_audit") is False and scope.get("prior_audit_in_model_payload") is False
        and scope.get("previous_audit_is_not_repaired") is True
        and all(scope.get(k) is False for k in ("automatic_retry", "old_budget_reset", "media_authorized", "publish_authorized")),
        "original independent one-call v2 diagnostic scope required")
    calls = ledger.get("calls")
    require(type(calls) is list and len(calls) == len(receipts) == 1
        and calls[0].get("label") == session.LABEL and calls[0].get("ordinal") == expected_end == inherited["calls_started"] + 1,
        "one contiguous original typed-audit receipt required")
    row, receipt = calls[0], receipts[0]
    native = session.prior.native_proof.known_native(receipt)
    request, meta = receipt.get("request", {}), receipt.get("response_metadata", {})
    outcome, terminal = diagnostic_outcome(decision)
    expected_status = "contract_valid" if decision["valid"] else "contract_rejected"
    require(receipt.get("ordinal") == expected_end and receipt.get("label") == session.LABEL
        and receipt.get("request_sha256") == digest(request) and receipt.get("source_binding_sha256") == digest(ledger["source_manifest"])
        and receipt.get("token_reservation") == row.get("token_reservation") and request.get("stage") == "goal_audit"
        and request.get("role") == "director" and request.get("input_provenance", {}).get("source_state_audit_version") == session.AUDIT_VERSION
        and receipt.get("status") == expected_status and receipt.get("automatic_retry") is False
        and receipt.get("semantic_approval") is False and bool(receipt.get("completed_at")), "complete known original typed-audit result required")
    if expected_status == "contract_rejected":
        failure = receipt.get("failure", {})
        require(failure.get("category") in ("validation", "state_contract", "compilation")
            and failure.get("response_received") is True and failure.get("automatic_retry") is False,
            "known native contract refusal required")
    usage = receipt.get("response_payload", {}).get("usage", {})
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        require(type(meta.get(key)) is int and meta[key] >= 0 and type(usage.get(key)) is int and usage[key] == meta[key],
            "unknown or nontyped original usage cannot settle")
    require(meta["prompt_tokens"] + meta["completion_tokens"] == meta["total_tokens"], "original usage sum differs")
    expected = session.base.policy.accounting_summary(inherited, receipts, stage_limits=session.LIMITS, unknown_reservations=0)
    require(state.get("schema") == session.VERSION + "/state" and summary.get("schema") == session.VERSION + "/summary"
        and state.get("native_audit_version") == summary.get("native_audit_version") == session.AUDIT_VERSION
        and state.get("new_stage_limits") == session.LIMITS and state.get("old_complete_body_calls_used") == 8
        and state.get("diagnostic_calls_previously_used") == 4
        and state.get("status") == summary.get("status") == terminal
        and state.get("spend_verification_pending") is summary.get("spend_verification_pending") is False
        and state.get("spend") == summary.get("spend") == expected and state.get("summary_sha256") == digest(summary)
        and summary.get("receipt_ordinal") == expected_end and summary.get("native_audit_sha256") == digest(native)
        and summary.get("derived_decision_sha256") == digest(decision)
        and parent_bridge._decision_identity(receipt.get("validation")) == parent_bridge._decision_identity(decision)
        and decision.get("schema") == session.AUDIT_VERSION + "/decision" and decision.get("native_report_sha256") == digest(native)
        and decision.get("native_report_modified") is False
        and decision.get("native_goal_sha256") == parent["native_goal_receipt"]["native_sha256"]
        and decision.get("native_setup_sha256") == parent["native_opening_setup_receipt"]["native_sha256"]
        and state.get("old_director_capacity") == session.base.DIRECTOR
        and state.get("diagnostic_only") is summary.get("diagnostic_only") is True
        and state.get("prior_source_state_diagnostics_used") == summary.get("prior_source_state_diagnostics_used") == 1
        and state.get("prior_source_state_contract_accepted") is summary.get("prior_source_state_contract_accepted") is False
        and all(state.get(k) is False for k in ("human_quality_approved", "creative_quality_passed", "media_authorized", "text_ready_for_director"))
        and all(summary.get(k) is False for k in ("human_quality_approved", "creative_quality_passed", "media_submitted", "text_ready_for_director")),
        "original typed diagnostic/decision/summary/state differ; diagnostic pass is not text ready")
    return {"inherited": {"calls_started": expected["effective_calls_started"], "reported_tokens": expected["effective_reported_tokens"],
        "calls_with_known_usage": expected["effective_calls_with_known_usage"], "pending_ordinals": deepcopy(inherited["pending_ordinals"]),
        "unknown_token_reservations": inherited["unknown_token_reservations"]}, "diagnostic_outcome": outcome}


def build_anchor(root, *, expected_end):
    root = session.base._inside(root); reader = evidence.Reader()
    state = reader.json(root / "STATE.json")
    require(state.get("schema") == session.VERSION + "/state", "unsupported typed-audit session protocol")
    original = session.Session.open(root); original._guard()
    config = reader.json(root / "SESSION_CONFIG.json"); freeze = reader.json(root / "PRODUCTION_FREEZE.json")
    scope = reader.json(root / "USER_SCOPE.json"); reader.json(root / "AUTHORIZATION.json")
    parent = reader.json(config["parent_anchor_path"])
    proof = parent_bridge.verify_anchor(parent, expected_anchor_sha256=config["parent_anchor_sha256"])
    require(proof.get("verified") is True and proof.get("inherited") == parent["inherited"], "verified original refused source-audit parent required")
    ledger = reader.json(root / "CALL_LEDGER.json"); summary = reader.json(root / "SUMMARY.json")
    receipts = [evidence.verify_original_receipt(root, row, ledger["source_manifest"], reader=reader) for row in ledger["calls"]]
    evidence._tasks(reader, root, ledger, receipts, config["grant_id"])
    paths = {"native_audit": str(root / "NATIVE_SOURCE_STATE_AUDIT.json"), "derived_decision": str(root / "SOURCE_STATE_AUDIT_DECISION.json")}
    require(summary.get("paths") == paths and set(summary.get("artifact_file_sha256", {})) == set(paths.values()), "original exact audit artifacts required")
    for path, expected in summary["artifact_file_sha256"].items(): reader.verify(path, expected)
    native, decision = (reader.json(paths[key]) for key in ("native_audit", "derived_decision"))
    checked = validate_records(parent, ledger, receipts, state, scope, summary, decision, expected_end=expected_end)
    require(native == receipts[0]["output"] and state["spend"] == original.runtime().summary(), "original native/runtime differs")
    run = reader.json(root / "RUN_CLAIM.json")
    require(run.get("schema") == session.VERSION + "/run_claim" and run.get("root") == str(root) and run.get("automatic_restart") is False
        and run.get("freeze_sha256") == sha(root / "PRODUCTION_FREEZE.json") and state.get("run_claim_sha256") == sha(root / "RUN_CLAIM.json"), "original RUN/freeze differs")
    inputs = reader.json(root / "INPUTS.json")
    require(digest(inputs) == parent["original_inputs_sha256"] and inputs == reader.json(parent["original_inputs_path"]), "original creative authority changed")
    prepared = original._request(inputs); receipt, row = receipts[0], ledger["calls"][0]
    intent = reader.json(root / "call_intents" / (session.LABEL + ".json"))
    require(intent.get("schema") == session.VERSION + "/call_intent" and intent.get("label") == session.LABEL
        and intent.get("automatic_retry") is False and intent.get("request") == prepared["request"] == receipt["request"]
        and intent.get("request_sha256") == receipt["request_sha256"] and intent.get("ledger_prefix_sha256") == digest([]), "original exact typed request/intent differs")
    require(parent_bridge._decision_identity(original.audit.validate(native, prepared)) == parent_bridge._decision_identity(decision), "original typed audit decision recomputation differs")
    profile_path = session.base._inside(config["profile_path"]); profile = reader.json(profile_path)
    require(profile == reader.json(parent["source_state_audit_profile_path"])
        and digest(profile) == parent["source_state_audit_profile_sha256"], "original exact32k audit profile changed")
    files = {**proof["source_files"], **freeze["files"], **{path: value["sha256"] for path, value in reader.files.items()}}
    files[str(Path(__file__).resolve())] = sha(__file__)
    identity = {"root": str(root), "end_ordinal": expected_end, "terminal_state_sha256": sha(root / "STATE.json"),
        "native_ledger_sha256": sha(root / "CALL_LEDGER.json"), "production_freeze_sha256": sha(root / "PRODUCTION_FREEZE.json")}
    reference = {"path": str(root / row["receipt"]), "file_sha256": row["receipt_sha256"], "ordinal": row["ordinal"],
        "label": row["label"], "request_sha256": receipt["request_sha256"], "native_sha256": digest(native),
        "status": receipt["status"], "original_validation_sha256": digest(receipt["validation"])}
    decision_ref = {"path": paths["derived_decision"], "file_sha256": sha(paths["derived_decision"]), "native_sha256": digest(decision),
        "receipt_ordinal": expected_end, "valid": decision["valid"], "accepted": decision["accepted"], "status": decision["status"]}
    result = {"schema": VERSION, "session_schema": session.VERSION, "verifier_code_sha256": sha(__file__), "root": str(root),
        "parent_identity": identity, "parent_identity_sha256": digest(identity), "inherited": checked["inherited"],
        "parent_anchor_path": config["parent_anchor_path"], "parent_anchor_sha256": config["parent_anchor_sha256"], "source_files": files,
        "latest_source_state_audit_receipt": reference, "latest_source_state_audit_decision_ref": decision_ref,
        "prior_source_state_audit_receipt": deepcopy(parent["latest_source_state_audit_receipt"]),
        "prior_source_state_audit_decision_ref": deepcopy(parent["latest_source_state_audit_decision_ref"]),
        "source_state_audit_receipts": [*deepcopy(parent["source_state_audit_receipts"]), reference],
        "prior_source_state_audit_scope_accounting": deepcopy(parent["source_state_audit_scope_accounting"]),
        "source_state_audit_scope_accounting": {"used": 1, "limit": 1, "remaining": 0, "reported_tokens": state["spend"]["new_reported_tokens"],
            "stage_calls": deepcopy(session.LIMITS), "creative_body_attempts_added": 0}, "cumulative_source_state_audit_calls_used": 2,
        "source_state_audit_diagnostic_outcome": checked["diagnostic_outcome"],
        "source_state_audit_contract_valid": decision["valid"], "source_state_audit_accepted": decision["accepted"],
        "source_state_audit_semantically_accepted": decision["accepted"], "diagnostic_accepted_is_not_text_ready": True,
        "remaining_complete_scripts": 0, "body_capacity_exhausted": True, "old_body_capacity_exhausted": True,
        "additional_body_capacity_exhausted": True, "old_director_capacity": deepcopy(session.base.DIRECTOR),
        "all_new_results_and_usage_known": True, "old_budget_reset": False, "authorizes_dispatch": False,
        "remaining_call_counts_are_accounting_not_new_grants": True, "body_or_full_review_approved": False,
        "text_ready_for_director": False, "source_freshness_for_next_production_certified": False, "counter_or_new_scope_admitted": False,
        "verification_scope": "Fixed typed-source-audit v2 known settlement: original SDK/wire/SQLite/freeze/RUN/request/report/derived-decision/SUMMARY. Exact diagnostic outcome and prior refused663 preserved; no text-ready, body, production, media or new allowance."}
    for key in PRESERVED: result[key] = deepcopy(parent[key])
    return result


def verify_anchor(anchor, *, expected_anchor_sha256):
    require(type(anchor) is dict and anchor.get("schema") == VERSION and digest(anchor) == expected_anchor_sha256, "typed-audit anchor identity differs")
    require(build_anchor(anchor["root"], expected_end=anchor["parent_identity"]["end_ordinal"]) == anchor, "original typed-audit evidence changed")
    return {"verified": True, "anchor": deepcopy(anchor), "inherited": deepcopy(anchor["inherited"]),
        "source_files": deepcopy(anchor["source_files"]), "parent_identity": deepcopy(anchor["parent_identity"]),
        "creative_source_root": anchor["creative_source_root"], "body_capacity_exhausted": True, "authorizes_dispatch": False}
