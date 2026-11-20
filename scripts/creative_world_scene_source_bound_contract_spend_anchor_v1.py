"""Settle one known v10 extraction rejection, preserving a pinned v9 certificate.

Uses the existing raw SDK/SQL readers, original frozen flow and accounting.
Only the new call is replayed; all historical certificate bytes remain frozen.
This module does not repair missing constants, dispatch or regrant capacity.
"""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from scripts import creative_world_scene_isolated_contract_spend_anchor_v1 as prior
from scripts import creative_world_scene_live_session_v10 as session

VERSION = "creative_world_scene_source_bound_contract_spend_anchor/v1"
PARENT_SHA256 = "480aea91dca059b7071d1ad187504b4ce3f0e8c9d6441191386e99ced604dbad"
PARENT_VERIFIER_SHA256 = "fba83a7a03ddb9bfd6f7aa154a953db703c527a73ba93dac4911632a89733e97"
LABEL, COUNTS = prior.LABEL, deepcopy(prior.COUNTS)
read, digest, sha, require, evidence = prior.read, prior.digest, prior.sha, prior.require, prior.evidence


def validate_parent_certificate(parent, freeze, *, expected_parent_sha256):
    require(expected_parent_sha256 == PARENT_SHA256 and digest(parent) == expected_parent_sha256
        and parent.get("schema") == prior.VERSION and parent.get("verifier_code_sha256") == PARENT_VERIFIER_SHA256
        and sha(prior.__file__) == PARENT_VERIFIER_SHA256, "registered681 certificate/schema/verifier differs")
    files = parent.get("source_files")
    require(type(files) is dict and bool(files) and type(freeze.get("files")) is dict
        and all(type(value) is str and freeze["files"].get(path) == value for path, value in files.items()),
        "entire681 certificate source-file set must remain identically frozen")


def validate_records(parent, ledger, receipts, state, scope, *, expected_end):
    inherited = evidence._spend(parent["inherited"]); accounting = parent["current_text_scope_accounting"]
    require(type(expected_end) is int and expected_end == inherited["calls_started"] + 1
        and accounting["remaining"] == session.LIMITS and accounting["calls_remaining"] == session.TOTAL
        and accounting["body_used"] == 0 and parent["current_body_versions_unused"] == session.BODY_VERSIONS
        and parent.get("creative_body_capacity_regranted") is False
        and parent.get("observable_events_contract_valid") is False, "one known call and original2body7review parent required")
    require(ledger.get("schema") == "authorized_creative_continuation/v3" and ledger.get("starting_spend") == inherited
        and ledger.get("max_total_tokens") is None
        and all(ledger.get(k) is False for k in ("automatic_retry", "old_budget_reset", "old_governance_migrated")), "original inherited ledger differs")
    require(scope.get("schema") == session.VERSION + "/remaining_capacity_authorization"
        and scope.get("inherited") == inherited and scope.get("stage_limits") == session.LIMITS
        and all(type(v) is int for v in scope["stage_limits"].values())
        and type(scope.get("total_new_calls_limit")) is int and scope["total_new_calls_limit"] == session.TOTAL
        and scope.get("complete_script_versions") == session.BODY_VERSIONS
        and scope.get("continuation_of_original_grant") == parent["continuation_of_original_grant"]
        and scope.get("creative_body_capacity_regranted") is False
        and all(scope.get(k) is False for k in ("automatic_retry", "old_budget_reset", "media_authorized", "publish_authorized")), "original unused capacity differs")
    rows = ledger.get("calls")
    require(type(rows) is list and len(rows) == len(receipts) == 1 and rows[0].get("label") == LABEL
        and rows[0].get("ordinal") == expected_end, "only the original one extraction call can settle")
    receipt = receipts[0]; session.native_proof.known_native(receipt); decision = receipt.get("validation", {})
    require(receipt.get("ordinal") == expected_end and receipt.get("label") == LABEL and receipt.get("status") == "contract_rejected"
        and receipt.get("request_sha256") == digest(receipt["request"])
        and receipt.get("source_binding_sha256") == digest(ledger["source_manifest"])
        and receipt.get("token_reservation") == rows[0].get("token_reservation") and bool(receipt.get("completed_at"))
        and receipt.get("automatic_retry") is False and receipt.get("semantic_approval") is False
        and receipt["request"].get("stage") == "full_review" and decision.get("valid") is False
        and decision.get("accepted") is False and decision.get("ledger_usable") is False
        and decision.get("status") == "halt_isolated_contract" and decision.get("isolated_stage") == "actual_events"
        and bool(decision.get("findings")), "known contract rejection must remain invalid and unusable")
    require(receipt.get("failure") == {"schema": "creative_failure/v1", "code": "MODULE_SCHEMA_INVALID", "category": "state_contract",
        "next_action": "complete_new_response_then_full_validation", "response_received": True, "automatic_retry": False, "blocks_handoff": True}, "complete schema rejection envelope required")
    meta, usage = receipt["response_metadata"], receipt["response_payload"]["usage"]
    require(all(type(meta.get(k)) is int and meta[k] >= 0 and type(usage.get(k)) is int and meta[k] == usage[k]
        for k in ("prompt_tokens", "completion_tokens", "total_tokens"))
        and meta["prompt_tokens"] + meta["completion_tokens"] == meta["total_tokens"], "unknown or noninteger usage cannot settle")
    expected = session.base.policy.accounting_summary(inherited, receipts, stage_limits=session.LIMITS, unknown_reservations=0)
    require(state.get("schema") == session.VERSION + "/state" and state.get("flow_version") == session.VERSION
        and state.get("status") == "halt_review_contract" and state.get("stage") == "observable_events" and state.get("decision") == decision
        and state.get("spend_verification_pending") is False and state.get("spend") == expected and expected["stage_calls"] == COUNTS
        and state.get("new_stage_limits") == session.LIMITS and state.get("old_director_capacity") == session.base.DIRECTOR
        and all(state.get(k) is False for k in ("text_ready_for_director", "human_quality_approved", "creative_quality_passed", "media_authorized")), "original rejection/state/accounting differs")
    return {"calls_started": expected["effective_calls_started"], "reported_tokens": expected["effective_reported_tokens"],
        "calls_with_known_usage": expected["effective_calls_with_known_usage"], "pending_ordinals": deepcopy(inherited["pending_ordinals"]),
        "unknown_token_reservations": inherited["unknown_token_reservations"]}


def build_anchor(root, *, expected_end):
    root = session.base._inside(root); reader = evidence.Reader(); original = session.Session.open(root)
    config, state, freeze, scope, inputs, ledger = [reader.json(root / (name + ".json")) for name in
        ("SESSION_CONFIG", "STATE", "PRODUCTION_FREEZE", "USER_SCOPE", "INPUTS", "CALL_LEDGER")]
    parent = reader.json(config["parent_anchor_path"])
    validate_parent_certificate(parent, freeze, expected_parent_sha256=config["parent_anchor_sha256"])
    require(freeze.get("schema") == session.VERSION + "/freeze" and freeze.get("stage_limits") == session.LIMITS
        and freeze.get("total_new_calls_limit") == session.TOTAL and freeze.get("inherited") == parent["inherited"]
        and freeze.get("inputs_sha256") == digest(inputs) and config == asdict(original.config), "fixed original v10 freeze/config differs")
    for path, expected in freeze["files"].items(): reader.verify(session.base._inside(path), expected)
    require(scope == original.authorization_template({"preparation_identity_sha256": scope["preparation_identity_sha256"],
        "inherited": freeze["inherited"], "inputs_sha256": digest(inputs), "creative_source_root": scope["creative_source_root"], "inputs": inputs})
        and reader.json(config["authorization_path"]) == scope and freeze["binding"] == original._binding(parent), "original scope/binding differs")
    successors = session.base.policy.successor_paths(session.base.PROJECT, parent, config["parent_anchor_sha256"])
    require(freeze["successor_claim_paths"] == [str(p) for p in successors]
        and all(reader.json(p) == freeze["binding"] for p in successors), "dual unique successor differs")
    require(sha(original.claim) == freeze["claim_sha256"] and reader.json(original.claim) == {**freeze["binding"], "schema": session.VERSION + "/grant_claim"}, "original grant differs")
    run = reader.json(root / "RUN_CLAIM.json"); authorization = reader.json(root / "AUTHORIZATION.json")
    require(run.get("schema") == session.VERSION + "/run_claim" and run.get("root") == str(root) and type(run.get("pid")) is int
        and run["pid"] > 0 and run.get("automatic_restart") is False and run.get("freeze_sha256") == sha(root / "PRODUCTION_FREEZE.json")
        and state.get("run_claim_sha256") == sha(root / "RUN_CLAIM.json"), "original single RUN differs")
    require(authorization.get("schema") == "authorized_creative_continuation/v3" and authorization.get("starting_spend") == parent["inherited"]
        and authorization.get("max_total_tokens") is None and all(authorization.get(k) is False for k in ("old_budget_reset", "old_governance_migrated", "media_calls_authorized"))
        and ledger.get("authorization_sha256") == sha(root / "AUTHORIZATION.json"), "original runtime authorization differs")
    original._profile_gate()
    require(inputs == reader.json(parent["current_inputs_path"]) and digest(inputs) == parent["current_inputs_sha256"], "original creative input changed")
    receipts = [evidence.verify_original_receipt(root, row, ledger["source_manifest"], reader=reader) for row in ledger["calls"]]
    evidence._tasks(reader, root, ledger, receipts, config["grant_id"])
    inherited = validate_records(parent, ledger, receipts, state, scope, expected_end=expected_end)
    row, receipt = ledger["calls"][0], receipts[0]; intent_path = root / "call_intents" / (LABEL + ".json")
    intent = reader.json(intent_path); prepared = intent["prepared"]
    require(intent == {"schema": session.VERSION + "/call_intent", "label": LABEL, "prepared": prepared,
        "request_sha256": receipt["request_sha256"], "ledger_prefix_sha256": digest([]), "inputs_sha256": digest(inputs), "automatic_retry": False}
        and prepared["request"] == receipt["request"], "original frozen request intent differs")
    try: original._replay(ledger, verify_validations=True)
    except session.base.stages.OfflineStop as stopped:
        require(stopped.status == "halt_review_contract" and stopped.details == {"stage": "observable_events", "decision": receipt["validation"]}, "original replay stop differs")
    else: raise ValueError("original contract rejection required")
    require(original._workflow().validate_observable_events(receipt["output"], prepared) == receipt["validation"], "original invalid report decision changed")
    identity = {"root": str(root), "end_ordinal": expected_end, **{key: sha(root / name) for key, name in
        (("terminal_state_sha256", "STATE.json"), ("native_ledger_sha256", "CALL_LEDGER.json"), ("production_freeze_sha256", "PRODUCTION_FREEZE.json"))}}
    ref = {"path": str(root / row["receipt"]), "file_sha256": row["receipt_sha256"], "ordinal": expected_end, "label": LABEL,
        "request_sha256": receipt["request_sha256"], "native_sha256": digest(receipt["output"]), "status": receipt["status"], "original_validation_sha256": digest(receipt["validation"])}
    result = {**deepcopy(parent), "schema": VERSION, "session_schema": session.VERSION, "root": str(root), "verifier_code_sha256": sha(__file__),
        "inherited": inherited, "parent_identity": identity, "parent_identity_sha256": digest(identity),
        "source_files": {**freeze["files"], **{p: x["sha256"] for p, x in reader.files.items()}, str(Path(__file__).resolve()): sha(__file__)},
        "parent_anchor_path": config["parent_anchor_path"], "parent_anchor_sha256": config["parent_anchor_sha256"],
        "current_inputs_path": str(root / "INPUTS.json"), "current_inputs_file_sha256": sha(root / "INPUTS.json"), "current_inputs_sha256": digest(inputs),
        "prior_text_scope_accounting": deepcopy(parent["current_text_scope_accounting"]), "current_text_scope_accounting": {
            "limits": deepcopy(session.LIMITS), "consumed": deepcopy(COUNTS), "remaining": {k: session.LIMITS[k] - COUNTS[k] for k in COUNTS},
            "calls_used": 1, "calls_remaining": session.TOTAL - 1, "body_used": 0, "body_limit": 2, "body_versions_spent": []},
        "latest_observable_events_receipt": ref, "latest_observable_events_decision_ref": {"path": ref["path"], "file_sha256": ref["file_sha256"],
            "json_pointer": "/validation", "native_sha256": digest(receipt["validation"]), "receipt_ordinal": expected_end},
        "latest_observable_events_prepared_ref": {"path": str(intent_path), "file_sha256": sha(intent_path), "json_pointer": "/prepared",
            "native_sha256": digest(prepared), "context_sha256": prepared["context_sha256"], "request_sha256": receipt["request_sha256"]},
        "historical_verification_basis": {"registered_parent_canonical_sha256": PARENT_SHA256, "all_parent_source_files_identically_frozen": True,
            "parent_source_file_count": len(parent["source_files"]), "frozen_source_bytes_verified_this_build": True,
            "recursive_historical_sdk_or_semantic_revalidation_performed": False},
        "verification_scope": "Fixed v10 one known original SDK/wire/SQL/freeze/RUN/intent/replay. Pinned681 certificate and complete identical frozen source bytes retain history without repeating historical SDK/replay. Original missing-schema native remains invalid/unusable; no checking-envelope repair or comparison. Two bodies15/16 and six reviews are original balance only, not authorization."}
    return result


def verify_anchor(anchor, *, expected_anchor_sha256):
    require(type(anchor) is dict and anchor.get("schema") == VERSION and digest(anchor) == expected_anchor_sha256, "source-bound contract anchor identity differs")
    require(build_anchor(anchor["root"], expected_end=anchor["parent_identity"]["end_ordinal"]) == anchor, "original fixedv10 evidence changed")
    return {"verified": True, "anchor": deepcopy(anchor), **{key: deepcopy(anchor[key]) for key in
        ("inherited", "source_files", "parent_identity", "creative_source_root", "current_inputs_path", "current_profile_path", "current_text_scope_accounting", "current_valid_body_receipt")}, "authorizes_dispatch": False}
