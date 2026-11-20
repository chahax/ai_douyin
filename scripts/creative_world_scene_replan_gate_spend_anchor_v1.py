"""Read-only v5 known seven-stage source-gate settlement, never text admission.

The original rejected source-state decision is retained, including its old
observe/completion diagnostic. Its existence is not proof of a story defect.
Historical identity checks do not demand an active old counter or certify the
source freshness required by a future run.
"""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from scripts import creative_session_spend_anchor_v1 as evidence
from scripts import creative_world_scene_typed_audit_spend_anchor_v1 as parent_bridge
from scripts import creative_world_scene_live_session_v5 as session

VERSION = "creative_world_scene_replan_gate_spend_anchor/v1"
read, digest, sha = session.read, session.digest, session.sha
require = parent_bridge.require
LABELS = ("whole_plan_01", "scope_audit_01", "source_audit_01", "commitment_audit_01", "drama_audit_01",
    "opening_setup_01_01", "source_state_audit_01")
COUNTS = {"goal_plan": 2, "goal_audit": 5, "complete_script": 0, "full_review": 0}
PRESERVED = (*parent_bridge.PRESERVED, "rejected_body_receipts", "cumulative_body_attempts_used",
    "cumulative_authorized_body_attempts", "registered_diagnostic_receipts", "diagnostic_scope_accounting",
    "creative_source_root", "original_creation_root", "original_inputs_path", "original_inputs_file_sha256",
    "original_inputs_sha256", "original_profile_path", "original_profile_file_sha256",
    "source_state_audit_receipts", "latest_source_state_audit_receipt", "latest_source_state_audit_decision_ref",
    "source_state_audit_profile_path", "source_state_audit_profile_file_sha256", "source_state_audit_profile_sha256",
    "source_state_audit_scope_accounting", "prior_source_state_audit_scope_accounting",
    "cumulative_source_state_audit_calls_used", "source_state_audit_contract_valid", "source_state_audit_semantically_accepted")


def validate_records(parent, ledger, receipts, state, scope, *, expected_end):
    """Pure typed accounting and terminal protocol; raw SDK checked by builder."""
    inherited = evidence._spend(parent["inherited"])
    require(type(expected_end) is int and expected_end == inherited["calls_started"] + len(LABELS),
        "explicit expected end must match seven contiguous original calls")
    require(parent.get("schema") == parent_bridge.VERSION
        and len(parent.get("rejected_body_receipts", [])) == 8
        and len(parent.get("registered_diagnostic_receipts", [])) == 4
        and len(parent.get("source_state_audit_receipts", [])) == 2
        and parent.get("source_state_audit_contract_valid") is False
        and parent.get("source_state_audit_semantically_accepted") is False,
        "original eight-body/four-toy/two-refused-audit history required")
    require(ledger.get("schema") == "authorized_creative_continuation/v3" and ledger.get("starting_spend") == inherited
        and ledger.get("max_total_tokens") is None
        and all(ledger.get(k) is False for k in ("automatic_retry", "old_budget_reset", "old_governance_migrated")),
        "original inherited no-reset/no-retry ledger required")
    require(scope.get("schema") == session.VERSION + "/derived_authorization"
        and scope.get("stage_limits") == session.LIMITS and all(type(v) is int for v in scope["stage_limits"].values())
        and type(scope.get("total_new_calls_limit")) is int and scope["total_new_calls_limit"] == session.TOTAL
        and scope.get("inherited") == inherited and scope.get("complete_script_versions") == session.BODY_VERSIONS
        and scope.get("complete_script_limit_shared_across_plans") == 3
        and scope.get("old_complete_body_calls_used") == scope.get("old_complete_body_capacity") == 8
        and scope.get("diagnostic_calls_previously_used") == 4 and scope.get("old_source_state_diagnostics_used") == 2
        and scope.get("old_director_capacity") == session.base.DIRECTOR
        and all(scope.get(k) is False for k in ("automatic_retry", "old_budget_reset", "media_authorized", "publish_authorized")),
        "original bounded v5 scope required; unused capacity is not a new grant")
    calls = ledger.get("calls")
    require(type(calls) is list and len(calls) == len(receipts) == len(LABELS)
        and [row.get("label") for row in calls] == list(LABELS)
        and [row.get("ordinal") for row in calls] == list(range(inherited["calls_started"] + 1, expected_end + 1)),
        "exact original first-plan/four-audit/opening/refused-source sequence required")
    ids, requests = set(), set()
    for index, (row, receipt) in enumerate(zip(calls, receipts)):
        session.native_proof.known_native(receipt)
        request, meta = receipt["request"], receipt["response_metadata"]
        expected_stage = "goal_plan" if index in (0, 5) else "goal_audit"
        status = "contract_rejected" if index == len(LABELS) - 1 else "contract_valid"
        require(receipt.get("ordinal") == row["ordinal"] and receipt.get("label") == row["label"]
            and receipt.get("request_sha256") == digest(request) and receipt.get("source_binding_sha256") == digest(ledger["source_manifest"])
            and receipt.get("token_reservation") == row.get("token_reservation")
            and request.get("stage") == expected_stage and receipt.get("status") == status
            and request.get("role") == ("writer" if expected_stage == "goal_plan" else "director")
            and receipt.get("automatic_retry") is False and receipt.get("semantic_approval") is False and bool(receipt.get("completed_at")),
            "original known native stage identity/status differs")
        validation = receipt.get("validation")
        require(type(validation) is dict and validation.get("valid") is (index != len(LABELS) - 1), "original decision validity differs")
        if 1 <= index <= 4:
            require(validation.get("accepted") is True and validation.get("findings") == []
                and validation.get("uncertainties") == [], "original four audits must actually be accepted")
        if status == "contract_rejected":
            failure = receipt.get("failure", {})
            require(failure.get("category") in ("validation", "state_contract", "compilation")
                and failure.get("response_received") is True and failure.get("automatic_retry") is False
                and validation.get("accepted") is False and validation.get("contract_findings")
                and validation.get("status") == "source_state_contract_rejected",
                "known source-review contract refusal required, not creative-source failure")
        usage = receipt.get("response_payload", {}).get("usage", {})
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            require(type(meta.get(key)) is int and meta[key] >= 0 and type(usage.get(key)) is int and usage[key] == meta[key],
                "unknown or nontyped usage cannot settle")
        require(meta["prompt_tokens"] + meta["completion_tokens"] == meta["total_tokens"], "original usage sum differs")
        rid = meta.get("response_id")
        require(type(rid) is str and bool(rid) and rid not in ids and receipt["request_sha256"] not in requests,
            "duplicate original response/request identity")
        ids.add(rid); requests.add(receipt["request_sha256"])
    expected = session.base.policy.accounting_summary(inherited, receipts, stage_limits=session.LIMITS, unknown_reservations=0)
    require(state.get("schema") == session.VERSION + "/state" and state.get("flow_version") == session.VERSION
        and state.get("status") == "halt_review_contract" and state.get("stage") == "source_state"
        and state.get("spend_verification_pending") is False and state.get("spend") == expected
        and expected["stage_calls"] == COUNTS and state.get("new_stage_limits") == session.LIMITS
        and state.get("decision") == receipts[-1]["validation"]
        and state.get("old_complete_body_calls_used") == 8 and state.get("diagnostic_calls_previously_used") == 4
        and state.get("old_source_state_diagnostics_used") == 2 and state.get("old_director_capacity") == session.base.DIRECTOR
        and all(state.get(k) is False for k in ("text_ready_for_director", "human_quality_approved", "creative_quality_passed", "media_authorized")),
        "original known halted state/accounting differs; rejected audit is not admitted")
    return {"calls_started": expected["effective_calls_started"], "reported_tokens": expected["effective_reported_tokens"],
        "calls_with_known_usage": expected["effective_calls_with_known_usage"], "pending_ordinals": deepcopy(inherited["pending_ordinals"]),
        "unknown_token_reservations": inherited["unknown_token_reservations"]}


def _inherit_original_lineage(result, parent):
    # An ancestor's `current_*` accounting describes that ancestor, not v5.
    # Keep it under an explicit historical name and never overwrite this run.
    result["prior_text_scope_accounting"] = deepcopy(parent.get("current_text_scope_accounting"))
    for key in dict.fromkeys(PRESERVED):
        if key not in result: result[key] = deepcopy(parent[key])
    return result


def _historical_identity(original, parent, reader, freeze, scope):
    """Frozen identity only; no old round admission or fresh-source assertion."""
    root = original.root; config = original.config; inputs = reader.json(root / "INPUTS.json")
    require(freeze.get("schema") == session.VERSION + "/freeze" and freeze.get("stage_limits") == session.LIMITS
        and freeze.get("total_new_calls_limit") == session.TOTAL and freeze.get("inherited") == parent["inherited"]
        and freeze.get("inputs_sha256") == digest(inputs), "original v5 freeze policy differs")
    require(digest(reader.json(root / "SESSION_CONFIG.json")) == digest(asdict(config)), "original config differs")
    require(scope == original.authorization_template({"preparation_identity_sha256": scope["preparation_identity_sha256"],
        "inherited": freeze["inherited"], "inputs_sha256": freeze["inputs_sha256"],
        "creative_source_root": scope["creative_source_root"], "inputs": inputs}), "original exact v5 authorization differs")
    for path, expected in freeze["files"].items(): reader.verify(session.base._inside(path), expected)
    require(reader.json(config.authorization_path) == scope, "original saved scope authorization differs")
    runtime_auth = reader.json(root / "AUTHORIZATION.json")
    require(runtime_auth.get("schema") == "authorized_creative_continuation/v3"
        and runtime_auth.get("starting_spend") == parent["inherited"] and runtime_auth.get("max_total_tokens") is None
        and runtime_auth.get("media_calls_authorized") is False and runtime_auth.get("old_budget_reset") is False
        and runtime_auth.get("old_governance_migrated") is False, "original runtime accounting authorization differs")
    require(digest(parent) == config.parent_anchor_sha256 and freeze["binding"] == original._binding(parent), "parent binding differs")
    paths = session.base.policy.successor_paths(session.base.PROJECT, parent, config.parent_anchor_sha256)
    require(freeze["successor_claim_paths"] == [str(path) for path in paths], "original dual successor paths differ")
    for path in paths: require(reader.json(path) == freeze["binding"], "original unique parent claim differs")
    require(sha(original.claim) == freeze["claim_sha256"]
        and reader.json(original.claim) == {**freeze["binding"], "schema": session.VERSION + "/grant_claim"}, "original grant differs")
    run = reader.json(root / "RUN_CLAIM.json")
    require(run.get("schema") == session.VERSION + "/run_claim" and run.get("root") == str(root)
        and type(run.get("pid")) is int and run["pid"] > 0 and run.get("automatic_restart") is False
        and run.get("freeze_sha256") == sha(root / "PRODUCTION_FREEZE.json"), "original RUN differs")
    original._profile_gate()
    require(inputs == reader.json(parent["original_inputs_path"]) and digest(inputs) == parent["original_inputs_sha256"],
        "original creative authority changed")
    return inputs


def build_anchor(root, *, expected_end):
    root = session.base._inside(root); reader = evidence.Reader(); state = reader.json(root / "STATE.json")
    require(state.get("schema") == session.VERSION + "/state", "unsupported replan-gate session protocol")
    original = session.Session.open(root); config = reader.json(root / "SESSION_CONFIG.json")
    freeze = reader.json(root / "PRODUCTION_FREEZE.json"); scope = reader.json(root / "USER_SCOPE.json")
    parent = reader.json(config["parent_anchor_path"])
    proof = parent_bridge.verify_anchor(parent, expected_anchor_sha256=config["parent_anchor_sha256"])
    require(proof.get("verified") is True and proof.get("inherited") == parent["inherited"], "verified original parent required")
    inputs = _historical_identity(original, parent, reader, freeze, scope)
    ledger = reader.json(root / "CALL_LEDGER.json")
    require(ledger.get("authorization_sha256") == sha(root / "AUTHORIZATION.json"), "original accounting authorization SHA differs")
    receipts = [evidence.verify_original_receipt(root, row, ledger["source_manifest"], reader=reader) for row in ledger["calls"]]
    evidence._tasks(reader, root, ledger, receipts, config["grant_id"])
    inherited = validate_records(parent, ledger, receipts, state, scope, expected_end=expected_end)
    require(state.get("run_claim_sha256") == sha(root / "RUN_CLAIM.json"), "original state/RUN binding differs")
    for index, (row, receipt) in enumerate(zip(ledger["calls"], receipts)):
        intent = reader.json(root / "call_intents" / (row["label"] + ".json"))
        require(intent.get("schema") == session.VERSION + "/call_intent" and intent.get("label") == row["label"]
            and intent.get("automatic_retry") is False and intent.get("prepared", {}).get("request") == receipt["request"]
            and intent.get("request_sha256") == receipt["request_sha256"] and intent.get("inputs_sha256") == digest(inputs)
            and intent.get("ledger_prefix_sha256") == digest(ledger["calls"][:index])
            and intent.get("prerequisite_receipts") == [{k: old[k] for k in ("ordinal", "label", "receipt", "receipt_sha256")}
                for old in ledger["calls"][:index]], "original exact request/prefix/prerequisite intent differs")
    # The frozen driver replays each request and every valid native decision.
    # Its original invalid final decision remains invalid, never converted.
    try: original._replay(ledger, verify_validations=True)
    except session.base.stages.OfflineStop as stopped:
        require(stopped.status == "halt_review_contract" and stopped.details.get("stage") == "source_state"
            and stopped.details.get("decision") == state["decision"], "original same-source replay reached a different terminal")
    else: raise ValueError("expected original refused source audit, not text ready")
    final_prepared = reader.json(root / "call_intents" / (LABELS[-1] + ".json"))["prepared"]
    require(original._workflow().validate_source_state_audit(receipts[-1]["output"], final_prepared) == receipts[-1]["validation"],
        "original source-audit contract diagnosis changed")
    files = {**proof["source_files"], **freeze["files"], **{path: value["sha256"] for path, value in reader.files.items()}}
    files[str(Path(__file__).resolve())] = sha(__file__)
    identity = {"root": str(root), "end_ordinal": expected_end, "terminal_state_sha256": sha(root / "STATE.json"),
        "native_ledger_sha256": sha(root / "CALL_LEDGER.json"), "production_freeze_sha256": sha(root / "PRODUCTION_FREEZE.json")}
    def ref(index):
        row, receipt = ledger["calls"][index], receipts[index]
        return {"path": str(root / row["receipt"]), "file_sha256": row["receipt_sha256"], "ordinal": row["ordinal"],
            "label": row["label"], "request_sha256": receipt["request_sha256"], "native_sha256": digest(receipt["output"]),
            "status": receipt["status"], "original_validation_sha256": digest(receipt["validation"])}
    profile_path = session.base._inside(config["profile_path"]); profile = reader.json(profile_path)
    files[str(profile_path)] = sha(profile_path)
    remaining = {key: session.LIMITS[key] - COUNTS[key] for key in COUNTS}; decision = receipts[-1]["validation"]
    result = {"schema": VERSION, "session_schema": session.VERSION, "root": str(root), "verifier_code_sha256": sha(__file__),
        "inherited": inherited, "parent_identity": identity, "parent_identity_sha256": digest(identity), "source_files": files,
        "parent_anchor_path": config["parent_anchor_path"], "parent_anchor_sha256": config["parent_anchor_sha256"],
        "current_inputs_path": str(root / "INPUTS.json"), "current_inputs_file_sha256": sha(root / "INPUTS.json"),
        "current_inputs_sha256": digest(inputs), "current_profile_path": str(profile_path),
        "current_profile_file_sha256": sha(profile_path), "current_profile_sha256": digest(profile),
        "current_native_goal_receipt": ref(0), "current_native_goal_audit_receipts": {kind: ref(i + 1) for i, kind in enumerate(session.base.workflow.AUDITS)},
        "current_native_opening_setup_receipt": ref(5), "current_source_state_audit_receipt": ref(6),
        "current_source_state_audit_decision_ref": {"path": ref(6)["path"], "file_sha256": ref(6)["file_sha256"],
            "json_pointer": "/validation", "native_sha256": digest(decision), "receipt_ordinal": expected_end,
            "valid": False, "accepted": False, "status": decision["status"]},
        "current_source_state_audit_contract_valid": False, "current_source_state_audit_accepted": False,
        "current_source_state_audit_is_not_source_defect_proof": True,
        "current_text_scope_accounting": {"limits": deepcopy(session.LIMITS), "consumed": deepcopy(COUNTS), "remaining": remaining,
            "calls_used": len(receipts), "calls_remaining": sum(remaining.values()), "body_used": 0, "body_limit": 3,
            "body_versions_available": deepcopy(session.BODY_VERSIONS)},
        "current_body_versions_unused": deepcopy(session.BODY_VERSIONS), "remaining_complete_scripts": 3,
        "old_body_capacity_exhausted": True, "body_capacity_exhausted": False, "creative_body_capacity_regranted": False,
        "old_director_capacity": deepcopy(session.base.DIRECTOR), "all_new_results_and_usage_known": True,
        "old_budget_reset": False, "authorizes_dispatch": False, "media_authorized": False,
        "text_ready_for_director": False, "human_quality_approved": False, "creative_quality_passed": False,
        "remaining_call_counts_are_accounting_not_new_grants": True,
        "source_freshness_for_next_production_certified": False, "counter_or_new_scope_admitted": False,
        "verification_scope": "Fixed v5 original seven-stage known halt_review_contract: original rawSDK/SQL/freeze/RUN/intents and native replay. Source refusal is retained, including observed-program diagnostics; no claim of a real story defect. Original645/650 references and all spent history retained separately from current665/four audits/670 and unused body09-11."}
    return _inherit_original_lineage(result, parent)


def verify_anchor(anchor, *, expected_anchor_sha256):
    require(type(anchor) is dict and anchor.get("schema") == VERSION and digest(anchor) == expected_anchor_sha256,
        "replan-gate anchor identity differs")
    require(build_anchor(anchor["root"], expected_end=anchor["parent_identity"]["end_ordinal"]) == anchor,
        "original v5 source-gate evidence changed")
    return {"verified": True, "anchor": deepcopy(anchor), "inherited": deepcopy(anchor["inherited"]),
        "source_files": deepcopy(anchor["source_files"]), "parent_identity": deepcopy(anchor["parent_identity"]),
        "creative_source_root": anchor["creative_source_root"], "current_inputs_path": anchor["current_inputs_path"],
        "current_profile_path": anchor["current_profile_path"], "current_text_scope_accounting": deepcopy(anchor["current_text_scope_accounting"]),
        "authorizes_dispatch": False}
