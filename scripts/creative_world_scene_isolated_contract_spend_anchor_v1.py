"""Read-only v9 known-contract accounting, with a pinned historical certificate.

The already verified 680 certificate is preserved through a complete identical
source-file set in the original v9 freeze. Historical SDK/replay is not repeated;
the new original call is checked against raw SDK, SQL, intent and fixed v9 replay.
No malformed event endpoint is repaired or adopted by this accounting module.
"""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from scripts import creative_session_spend_anchor_v1 as evidence
from scripts import creative_world_scene_calibration_spend_anchor_v1 as parent_bridge
from scripts import creative_world_scene_live_session_v9 as session

VERSION = "creative_world_scene_isolated_contract_spend_anchor/v1"
LABEL = "observable_events_calibration_14"
COUNTS = {"goal_plan": 0, "goal_audit": 0, "complete_script": 0, "full_review": 1}
REGISTERED_PARENT_SHA256 = "32b950833ae3ed9e8d14da482179abf3737ae510c18bb975d6ee5b4ec65dcf37"
REGISTERED_PARENT_VERIFIER_SHA256 = "507d1da982294366a9894e77256ae59f1c78d01ce70a7a3cd2b4ea6d2c71bea0"
read, digest, sha, require = session.read, session.digest, session.sha, parent_bridge.require


def validate_parent_certificate(parent, freeze, *, expected_parent_sha256):
    """Identity/set inclusion only; file bytes are checked once by the caller."""
    require(expected_parent_sha256 == REGISTERED_PARENT_SHA256 and digest(parent) == expected_parent_sha256
        and parent.get("schema") == parent_bridge.VERSION
        and parent.get("verifier_code_sha256") == REGISTERED_PARENT_VERIFIER_SHA256
        and sha(parent_bridge.__file__) == REGISTERED_PARENT_VERIFIER_SHA256,
        "registered historical calibration certificate/schema/verifier changed")
    files = parent.get("source_files")
    require(type(files) is dict and bool(files) and type(freeze.get("files")) is dict
        and all(type(value) is str and freeze["files"].get(path) == value for path, value in files.items()),
        "complete historical certificate source files must remain identically frozen")


def validate_records(parent, ledger, receipts, state, scope, *, expected_end):
    inherited = evidence._spend(parent["inherited"])
    require(type(expected_end) is int and expected_end == inherited["calls_started"] + 1,
        "one contiguous known actual-events call required")
    prior = parent.get("current_text_scope_accounting", {})
    require(prior.get("limits") == session.PARENT_LIMITS and prior.get("consumed") == session.PARENT_USED
        and prior.get("remaining") == session.LIMITS and prior.get("calls_used") == 1
        and prior.get("calls_remaining") == 10 and prior.get("body_used") == 0
        and parent.get("current_body_versions_unused") == session.BODY_VERSIONS
        and parent.get("unused_capacity_is_original_grant_balance_only") is True
        and parent.get("creative_body_capacity_regranted") is False
        and parent.get("native_focus_contract_valid") is True and parent.get("native_focus_model_accepted") is True
        and parent.get("calibration_missed") is True and parent.get("text_ready_for_director") is False,
        "original model opinion/local calibration miss/unused grant identity differs")
    require(ledger.get("schema") == "authorized_creative_continuation/v3" and ledger.get("starting_spend") == inherited
        and ledger.get("max_total_tokens") is None
        and all(ledger.get(k) is False for k in ("automatic_retry", "old_budget_reset", "old_governance_migrated")),
        "original inherited no-retry ledger required")
    require(scope.get("schema") == session.VERSION + "/remaining_capacity_authorization"
        and scope.get("inherited") == inherited and scope.get("stage_limits") == session.LIMITS
        and all(type(v) is int for v in scope["stage_limits"].values())
        and type(scope.get("total_new_calls_limit")) is int and scope["total_new_calls_limit"] == session.TOTAL
        and scope.get("complete_script_versions") == session.BODY_VERSIONS
        and scope.get("continuation_of_original_grant") == parent["continuation_of_original_grant"]
        and scope.get("unused_capacity_is_original_grant_balance_only") is True
        and scope.get("creative_body_capacity_regranted") is False and scope.get("isolated_events_before_entailment") is True
        and all(scope.get(k) is False for k in ("automatic_retry", "old_budget_reset", "media_authorized", "publish_authorized")),
        "original unused two-body/eight-review scope required")
    calls = ledger.get("calls")
    require(type(calls) is list and len(calls) == len(receipts) == 1 and calls[0].get("label") == LABEL
        and calls[0].get("ordinal") == expected_end, "one actual-events call; no hidden entailment/body/review")
    row, receipt = calls[0], receipts[0]
    session.native_proof.known_native(receipt)
    decision = receipt.get("validation", {})
    require(receipt.get("ordinal") == expected_end and receipt.get("label") == LABEL
        and receipt.get("request_sha256") == digest(receipt["request"])
        and receipt.get("source_binding_sha256") == digest(ledger["source_manifest"])
        and receipt.get("token_reservation") == row.get("token_reservation")
        and receipt.get("automatic_retry") is False and receipt.get("semantic_approval") is False
        and bool(receipt.get("completed_at"))
        and receipt["request"].get("stage") == "full_review" and receipt["request"].get("role") == "director"
        and receipt.get("status") == "contract_rejected" and decision.get("valid") is False
        and decision.get("accepted") is False and decision.get("ledger_usable") is False
        and decision.get("status") == "halt_isolated_contract" and bool(decision.get("findings"))
        and decision.get("isolated_stage") == "actual_events", "known complete contract rejection cannot be adopted")
    require(receipt.get("failure") == {"schema": "creative_failure/v1", "code": "MODULE_SCHEMA_INVALID",
        "category": "state_contract", "next_action": "complete_new_response_then_full_validation",
        "response_received": True, "automatic_retry": False, "blocks_handoff": True},
        "original complete schema-failure envelope required; protocol/transport faults cannot masquerade")
    meta, usage = receipt["response_metadata"], receipt.get("response_payload", {}).get("usage", {})
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        require(type(meta.get(key)) is int and meta[key] >= 0 and type(usage.get(key)) is int and usage[key] == meta[key],
            "unknown or noninteger usage cannot settle")
    require(meta["prompt_tokens"] + meta["completion_tokens"] == meta["total_tokens"], "usage sum differs")
    expected = session.base.policy.accounting_summary(inherited, receipts, stage_limits=session.LIMITS, unknown_reservations=0)
    require(state.get("schema") == session.VERSION + "/state" and state.get("flow_version") == session.VERSION
        and state.get("status") == "halt_review_contract" and state.get("stage") == "observable_events"
        and state.get("decision") == decision and state.get("spend_verification_pending") is False
        and state.get("spend") == expected and expected["stage_calls"] == COUNTS
        and state.get("new_stage_limits") == session.LIMITS and state.get("old_director_capacity") == session.base.DIRECTOR
        and all(state.get(k) is False for k in ("text_ready_for_director", "human_quality_approved", "creative_quality_passed", "media_authorized")),
        "original contract stop/accounting must remain separate from semantic approval")
    return {"calls_started": expected["effective_calls_started"], "reported_tokens": expected["effective_reported_tokens"],
        "calls_with_known_usage": expected["effective_calls_with_known_usage"], "pending_ordinals": deepcopy(inherited["pending_ordinals"]),
        "unknown_token_reservations": inherited["unknown_token_reservations"]}


def _historical_identity(original, parent, reader, freeze, scope):
    root, config = original.root, original.config
    inputs = reader.json(root / "INPUTS.json")
    require(freeze.get("schema") == session.VERSION + "/freeze" and freeze.get("stage_limits") == session.LIMITS
        and freeze.get("total_new_calls_limit") == session.TOTAL and freeze.get("inherited") == parent["inherited"]
        and freeze.get("inputs_sha256") == digest(inputs)
        and digest(reader.json(root / "SESSION_CONFIG.json")) == digest(asdict(config)), "original v9 freeze/config differs")
    validate_parent_certificate(parent, freeze, expected_parent_sha256=config.parent_anchor_sha256)
    # Exactly one complete frozen-source pass; no recursive historical SDK replay.
    for path, expected in freeze["files"].items(): reader.verify(session.base._inside(path), expected)
    require(scope == original.authorization_template({"preparation_identity_sha256": scope["preparation_identity_sha256"],
        "inherited": freeze["inherited"], "inputs_sha256": freeze["inputs_sha256"],
        "creative_source_root": scope["creative_source_root"], "inputs": inputs})
        and reader.json(config.authorization_path) == scope, "original exact v9 authorization differs")
    require(freeze["binding"] == original._binding(parent), "original parent/grant binding differs")
    paths = session.base.policy.successor_paths(session.base.PROJECT, parent, config.parent_anchor_sha256)
    require(freeze["successor_claim_paths"] == [str(path) for path in paths], "original dual successor paths differ")
    for path in paths: require(reader.json(path) == freeze["binding"], "original unique successor differs")
    require(sha(original.claim) == freeze["claim_sha256"]
        and reader.json(original.claim) == {**freeze["binding"], "schema": session.VERSION + "/grant_claim"}, "original grant differs")
    run = reader.json(root / "RUN_CLAIM.json")
    require(run.get("schema") == session.VERSION + "/run_claim" and run.get("root") == str(root)
        and type(run.get("pid")) is int and run["pid"] > 0 and run.get("automatic_restart") is False
        and run.get("freeze_sha256") == sha(root / "PRODUCTION_FREEZE.json"), "original RUN differs")
    auth = reader.json(root / "AUTHORIZATION.json")
    require(auth.get("schema") == "authorized_creative_continuation/v3" and auth.get("starting_spend") == parent["inherited"]
        and auth.get("max_total_tokens") is None and auth.get("old_budget_reset") is False
        and auth.get("old_governance_migrated") is False and auth.get("media_calls_authorized") is False,
        "original runtime authorization differs")
    original._profile_gate()
    require(inputs == reader.json(parent["current_inputs_path"]) and digest(inputs) == parent["current_inputs_sha256"],
        "original creative authority changed")
    return inputs


def build_anchor(root, *, expected_end):
    root = session.base._inside(root)
    reader = evidence.Reader()
    state = reader.json(root / "STATE.json")
    require(state.get("schema") == session.VERSION + "/state", "unsupported original isolated-event session protocol")
    original = session.Session.open(root)
    config = reader.json(root / "SESSION_CONFIG.json")
    freeze, scope = reader.json(root / "PRODUCTION_FREEZE.json"), reader.json(root / "USER_SCOPE.json")
    parent = reader.json(config["parent_anchor_path"])
    inputs = _historical_identity(original, parent, reader, freeze, scope)
    ledger = reader.json(root / "CALL_LEDGER.json")
    require(ledger.get("authorization_sha256") == sha(root / "AUTHORIZATION.json"), "runtime authorization SHA differs")
    receipts = [evidence.verify_original_receipt(root, row, ledger["source_manifest"], reader=reader) for row in ledger["calls"]]
    evidence._tasks(reader, root, ledger, receipts, config["grant_id"])
    inherited = validate_records(parent, ledger, receipts, state, scope, expected_end=expected_end)
    require(state.get("run_claim_sha256") == sha(root / "RUN_CLAIM.json"), "original state/RUN differs")
    row, receipt = ledger["calls"][0], receipts[0]
    intent_path = root / "call_intents" / (LABEL + ".json")
    intent = reader.json(intent_path)
    prepared = intent["prepared"]
    require(intent.get("schema") == session.VERSION + "/call_intent" and intent.get("label") == LABEL
        and intent.get("automatic_retry") is False and prepared["request"] == receipt["request"]
        and intent.get("request_sha256") == receipt["request_sha256"] and intent.get("inputs_sha256") == digest(inputs)
        and intent.get("ledger_prefix_sha256") == digest([]), "original exact isolated-events intent differs")
    try: original._replay(ledger, verify_validations=True)
    except session.base.stages.OfflineStop as stopped:
        require(stopped.status == "halt_review_contract" and stopped.details.get("stage") == "observable_events"
            and stopped.details.get("decision") == receipt["validation"], "original replay reached a different contract terminal")
    else: raise ValueError("expected original contract rejection, never creative acceptance")
    require(original._workflow().validate_observable_events(receipt["output"], prepared) == receipt["validation"],
        "original invalid native report/local decision changed")
    files = {**freeze["files"], **{path: value["sha256"] for path, value in reader.files.items()}}
    files[str(Path(__file__).resolve())] = sha(__file__)
    identity = {"root": str(root), "end_ordinal": expected_end, "terminal_state_sha256": sha(root / "STATE.json"),
        "native_ledger_sha256": sha(root / "CALL_LEDGER.json"), "production_freeze_sha256": sha(root / "PRODUCTION_FREEZE.json")}
    ref = {"path": str(root / row["receipt"]), "file_sha256": row["receipt_sha256"], "ordinal": row["ordinal"],
        "label": row["label"], "request_sha256": receipt["request_sha256"], "native_sha256": digest(receipt["output"]),
        "status": receipt["status"], "original_validation_sha256": digest(receipt["validation"])}
    remaining = {key: session.LIMITS[key] - COUNTS[key] for key in COUNTS}
    return {**deepcopy(parent), "schema": VERSION, "session_schema": session.VERSION, "root": str(root),
        "verifier_code_sha256": sha(__file__), "inherited": inherited, "parent_identity": identity,
        "parent_identity_sha256": digest(identity), "source_files": files,
        "parent_anchor_path": config["parent_anchor_path"], "parent_anchor_sha256": config["parent_anchor_sha256"],
        "current_inputs_path": str(root / "INPUTS.json"), "current_inputs_file_sha256": sha(root / "INPUTS.json"),
        "current_inputs_sha256": digest(inputs), "prior_text_scope_accounting": deepcopy(parent["current_text_scope_accounting"]),
        "current_text_scope_accounting": {"limits": deepcopy(session.LIMITS), "consumed": deepcopy(COUNTS), "remaining": remaining,
            "calls_used": 1, "calls_remaining": sum(remaining.values()), "body_used": 0, "body_limit": 2, "body_versions_spent": []},
        "current_body_versions_unused": deepcopy(session.BODY_VERSIONS), "remaining_complete_scripts": 2,
        "body_capacity_exhausted": False, "old_body_capacity_exhausted": True, "creative_body_capacity_regranted": False,
        "unused_capacity_is_original_grant_balance_only": True,
        "continuation_of_original_grant": parent["continuation_of_original_grant"],
        "latest_observable_events_receipt": ref,
        "latest_observable_events_decision_ref": {"path": ref["path"], "file_sha256": ref["file_sha256"],
            "json_pointer": "/validation", "native_sha256": digest(receipt["validation"]), "receipt_ordinal": expected_end},
        "latest_observable_events_prepared_ref": {"path": str(intent_path), "file_sha256": sha(intent_path),
            "json_pointer": "/prepared", "native_sha256": digest(prepared), "context_sha256": prepared["context_sha256"],
            "request_sha256": ref["request_sha256"]},
        "observable_events_contract_valid": False, "observable_events_ledger_usable": False,
        "observable_events_semantic_comparison_performed": False, "observable_events_original_report_preserved": True,
        "old_budget_reset": False, "authorizes_dispatch": False, "media_authorized": False, "text_ready_for_director": False,
        "human_quality_approved": False, "creative_quality_passed": False,
        "remaining_call_counts_are_accounting_not_new_grants": True, "source_freshness_for_next_production_certified": False,
        "counter_or_new_scope_admitted": False,
        "historical_verification_basis": {"registered_parent_canonical_sha256": REGISTERED_PARENT_SHA256,
            "all_parent_source_files_identically_frozen": True, "parent_source_file_count": len(parent["source_files"]),
            "frozen_source_bytes_verified_this_build": True, "recursive_historical_sdk_or_semantic_revalidation_performed": False},
        "verification_scope": "Fixed v9 one known raw SDK/wire/SQL/freeze/RUN/intent/replay and original invalid event report. Historical680 certificate identity plus its entire identical frozen source-file bytes are retained; historical SDK/replay is not repeated. No endpoint repair, usable ledger, comparison, text approval, new grant or media authorization. Two bodies15/16 and seven reviews are only the original grant balance."}


def verify_anchor(anchor, *, expected_anchor_sha256):
    require(type(anchor) is dict and anchor.get("schema") == VERSION and digest(anchor) == expected_anchor_sha256,
        "isolated-contract accounting anchor identity differs")
    require(build_anchor(anchor["root"], expected_end=anchor["parent_identity"]["end_ordinal"]) == anchor,
        "original v9 known evidence changed")
    return {"verified": True, "anchor": deepcopy(anchor), "inherited": deepcopy(anchor["inherited"]),
        "source_files": deepcopy(anchor["source_files"]), "parent_identity": deepcopy(anchor["parent_identity"]),
        "creative_source_root": anchor["creative_source_root"], "current_inputs_path": anchor["current_inputs_path"],
        "current_profile_path": anchor["current_profile_path"], "current_text_scope_accounting": deepcopy(anchor["current_text_scope_accounting"]),
        "current_valid_body_receipt": deepcopy(anchor["current_valid_body_receipt"]), "authorizes_dispatch": False}
