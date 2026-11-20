"""Read-only v6 accepted source / exhausted three-body settlement.

Only the explicit original v6 protocol is supported. Current native creative
references stay distinct from older645/650; accounting grants no dispatch.
"""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from scripts import creative_session_spend_anchor_v1 as evidence
from scripts import creative_world_scene_replan_gate_spend_anchor_v1 as parent_bridge
from scripts import creative_world_scene_source_audit_spend_anchor_v1 as diagnostic_identity
from scripts import creative_world_scene_live_session_v6 as session
from scripts import creative_world_scene_script_contract_v2 as script_contract

VERSION = "creative_world_scene_continued_text_spend_anchor/v1"
read, digest, sha, require = session.read, session.digest, session.sha, parent_bridge.require
LABELS = ("source_state_audit_01", "complete_script_09", "complete_script_10", "complete_script_11")
COUNTS = {"goal_plan": 0, "goal_audit": 1, "complete_script": 3, "full_review": 0}


def validate_records(parent, ledger, receipts, state, scope, *, expected_end):
    inherited = evidence._spend(parent["inherited"])
    require(type(expected_end) is int and expected_end == inherited["calls_started"] + len(LABELS), "four original contiguous calls required")
    previous = parent.get("current_text_scope_accounting", {})
    require(parent.get("schema") == parent_bridge.VERSION and previous.get("consumed") == session.PARENT_USED
        and previous.get("remaining") == session.PARENT_REMAINING and previous.get("calls_used") == 7
        and previous.get("calls_remaining") == 26 and previous.get("body_used") == 0
        and parent.get("current_body_versions_unused") == session.BODY_VERSIONS
        and len(parent.get("rejected_body_receipts", [])) == 8
        and len(parent.get("registered_diagnostic_receipts", [])) == 4
        and parent.get("current_source_state_audit_contract_valid") is False,
        "original source-refusal parent with unused09-11 required")
    require(ledger.get("schema") == "authorized_creative_continuation/v3" and ledger.get("starting_spend") == inherited
        and ledger.get("max_total_tokens") is None
        and all(ledger.get(k) is False for k in ("automatic_retry", "old_budget_reset", "old_governance_migrated")), "original inherited ledger required")
    require(scope.get("schema") == session.VERSION + "/derived_authorization" and scope.get("inherited") == inherited
        and scope.get("stage_limits") == session.LIMITS and all(type(v) is int for v in scope["stage_limits"].values())
        and type(scope.get("total_new_calls_limit")) is int and scope["total_new_calls_limit"] == session.TOTAL
        and scope.get("complete_script_versions") == session.BODY_VERSIONS and scope.get("complete_script_limit_shared_across_plans") == 3
        and scope.get("old_complete_body_calls_used") == scope.get("old_complete_body_capacity") == 8
        and scope.get("parent_scope_calls_used") == 7 and scope.get("parent_scope_calls_remaining") == 26
        and scope.get("no_replanning") is True and scope.get("consumes_parent_unused_planning") is False
        and scope.get("diagnostic_calls_previously_used") == 4 and scope.get("old_source_state_diagnostics_used") == 2
        and all(scope.get(k) is False for k in ("automatic_retry", "old_budget_reset", "media_authorized", "publish_authorized")), "original v6/10 scope required")
    calls = ledger.get("calls")
    require(type(calls) is list and len(calls) == len(receipts) == len(LABELS)
        and [row.get("label") for row in calls] == list(LABELS)
        and [row.get("ordinal") for row in calls] == list(range(inherited["calls_started"] + 1, expected_end + 1)), "original source/three-body sequence differs")
    ids, requests = set(), set()
    for index, (row, receipt) in enumerate(zip(calls, receipts)):
        session.native_proof.known_native(receipt)
        request, meta = receipt["request"], receipt["response_metadata"]
        require(receipt.get("ordinal") == row["ordinal"] and receipt.get("label") == row["label"]
            and receipt.get("request_sha256") == digest(request) and receipt.get("source_binding_sha256") == digest(ledger["source_manifest"])
            and receipt.get("token_reservation") == row.get("token_reservation") and receipt.get("automatic_retry") is False
            and receipt.get("semantic_approval") is False and bool(receipt.get("completed_at"))
            and request.get("stage") == ("goal_audit" if index == 0 else "complete_script")
            and request.get("role") == ("director" if index == 0 else "writer")
            and receipt.get("status") == ("contract_valid" if index == 0 else "contract_rejected"), "original native stage status/identity differs")
        if index == 0:
            decision = receipt.get("validation", {})
            require(decision.get("valid") is True and decision.get("accepted") is True
                and decision.get("findings") == decision.get("contract_findings") == decision.get("uncertainties") == []
                and decision.get("status") == "source_state_pass"
                and decision.get("native_goal_sha256") == parent["current_native_goal_receipt"]["native_sha256"]
                and decision.get("native_setup_sha256") == parent["current_native_opening_setup_receipt"]["native_sha256"],
                "original accepted same-current-source v4 review required")
        else:
            failure = receipt.get("failure", {}); diagnostic = receipt.get("validation_error", {}).get("detail", {})
            require(receipt.get("validation") is None and diagnostic.get("valid") is False and bool(diagnostic.get("findings"))
                and failure.get("category") in ("validation", "state_contract", "compilation")
                and failure.get("response_received") is True and failure.get("automatic_retry") is False,
                "original complete native body contract refusal required")
        usage = receipt.get("response_payload", {}).get("usage", {})
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            require(type(meta.get(key)) is int and meta[key] >= 0 and type(usage.get(key)) is int and usage[key] == meta[key], "unknown/nontyped usage cannot settle")
        require(meta["prompt_tokens"] + meta["completion_tokens"] == meta["total_tokens"], "original usage sum differs")
        rid = meta.get("response_id")
        require(type(rid) is str and bool(rid) and rid not in ids and receipt["request_sha256"] not in requests, "duplicate response/request identity")
        ids.add(rid); requests.add(receipt["request_sha256"])
    expected = session.base.policy.accounting_summary(inherited, receipts, stage_limits=session.LIMITS, unknown_reservations=0)
    require(state.get("schema") == session.VERSION + "/state" and state.get("flow_version") == session.VERSION
        and state.get("status") == "halt_live_shared_script_capacity" and state.get("shared_body_calls_used") == 3
        and state.get("spend_verification_pending") is False and state.get("spend") == expected
        and expected["stage_calls"] == COUNTS and state.get("new_stage_limits") == session.LIMITS
        and state.get("parent_scope_calls_used") == 7 and state.get("parent_scope_calls_remaining") == 26
        and state.get("no_replanning") is True and state.get("old_director_capacity") == session.base.DIRECTOR
        and all(state.get(k) is False for k in ("text_ready_for_director", "human_quality_approved", "creative_quality_passed", "media_authorized")), "known exhausted-body terminal/accounting differs")
    return {"calls_started": expected["effective_calls_started"], "reported_tokens": expected["effective_reported_tokens"],
        "calls_with_known_usage": expected["effective_calls_with_known_usage"], "pending_ordinals": deepcopy(inherited["pending_ordinals"]),
        "unknown_token_reservations": inherited["unknown_token_reservations"]}


def _historical_identity(original, parent, reader, freeze, scope):
    """Pure frozen identity, not the inactive counter/current freshness gate."""
    root, config = original.root, original.config; inputs = reader.json(root / "INPUTS.json")
    require(freeze.get("schema") == session.VERSION + "/freeze" and freeze.get("stage_limits") == session.LIMITS
        and freeze.get("total_new_calls_limit") == session.TOTAL and freeze.get("inherited") == parent["inherited"]
        and freeze.get("inputs_sha256") == digest(inputs) and digest(reader.json(root / "SESSION_CONFIG.json")) == digest(asdict(config)), "original v6 freeze/config differs")
    expected_scope = original.authorization_template({"preparation_identity_sha256": scope["preparation_identity_sha256"],
        "inherited": freeze["inherited"], "inputs_sha256": freeze["inputs_sha256"], "creative_source_root": scope["creative_source_root"], "inputs": inputs})
    require(scope == expected_scope and reader.json(config.authorization_path) == scope, "original exact v6 authorization differs")
    for path, expected in freeze["files"].items(): reader.verify(session.base._inside(path), expected)
    require(digest(parent) == config.parent_anchor_sha256 and freeze["binding"] == original._binding(parent), "parent identity differs")
    paths = session.base.policy.successor_paths(session.base.PROJECT, parent, config.parent_anchor_sha256)
    require(freeze["successor_claim_paths"] == [str(path) for path in paths], "original dual successor paths differ")
    for path in paths: require(reader.json(path) == freeze["binding"], "unique parent claim differs")
    require(sha(original.claim) == freeze["claim_sha256"] and reader.json(original.claim) == {**freeze["binding"], "schema": session.VERSION + "/grant_claim"}, "original grant differs")
    run = reader.json(root / "RUN_CLAIM.json")
    require(run.get("schema") == session.VERSION + "/run_claim" and run.get("root") == str(root) and type(run.get("pid")) is int
        and run["pid"] > 0 and run.get("automatic_restart") is False and run.get("freeze_sha256") == sha(root / "PRODUCTION_FREEZE.json"), "original RUN differs")
    runtime_auth = reader.json(root / "AUTHORIZATION.json")
    require(runtime_auth.get("schema") == "authorized_creative_continuation/v3" and runtime_auth.get("starting_spend") == parent["inherited"]
        and runtime_auth.get("max_total_tokens") is None and runtime_auth.get("old_budget_reset") is False
        and runtime_auth.get("old_governance_migrated") is False and runtime_auth.get("media_calls_authorized") is False, "runtime authorization differs")
    original._profile_gate()
    require(inputs == reader.json(parent["current_inputs_path"]) and digest(inputs) == parent["current_inputs_sha256"], "original creative authority changed")
    return inputs


def build_anchor(root, *, expected_end):
    root = session.base._inside(root); reader = evidence.Reader(); state = reader.json(root / "STATE.json")
    require(state.get("schema") == session.VERSION + "/state", "unsupported continued-text session protocol")
    original = session.Session.open(root); config = reader.json(root / "SESSION_CONFIG.json")
    freeze, scope = reader.json(root / "PRODUCTION_FREEZE.json"), reader.json(root / "USER_SCOPE.json")
    parent = reader.json(config["parent_anchor_path"])
    proof = parent_bridge.verify_anchor(parent, expected_anchor_sha256=config["parent_anchor_sha256"])
    require(proof.get("verified") is True and proof.get("inherited") == parent["inherited"], "verified original parent required")
    inputs = _historical_identity(original, parent, reader, freeze, scope)
    ledger = reader.json(root / "CALL_LEDGER.json")
    require(ledger.get("authorization_sha256") == sha(root / "AUTHORIZATION.json"), "runtime authorization SHA differs")
    receipts = [evidence.verify_original_receipt(root, row, ledger["source_manifest"], reader=reader) for row in ledger["calls"]]
    evidence._tasks(reader, root, ledger, receipts, config["grant_id"])
    inherited = validate_records(parent, ledger, receipts, state, scope, expected_end=expected_end)
    require(state.get("run_claim_sha256") == sha(root / "RUN_CLAIM.json"), "original state/RUN differs")
    intents = []
    for index, (row, receipt) in enumerate(zip(ledger["calls"], receipts)):
        intent = reader.json(root / "call_intents" / (row["label"] + ".json")); intents.append(intent)
        require(intent.get("schema") == session.VERSION + "/call_intent" and intent.get("label") == row["label"]
            and intent.get("automatic_retry") is False and intent["prepared"]["request"] == receipt["request"]
            and intent.get("request_sha256") == receipt["request_sha256"] and intent.get("inputs_sha256") == digest(inputs)
            and intent.get("ledger_prefix_sha256") == digest(ledger["calls"][:index])
            and intent.get("prerequisite_receipts") == [{key: old[key] for key in ("ordinal", "label", "receipt", "receipt_sha256")}
                for old in ledger["calls"][:index]], "original exact trusted request/prerequisites differ")
    try: original._replay(ledger, verify_validations=True)
    except session.base.Halt as stopped:
        require(stopped.status == "halt_live_shared_script_capacity" and stopped.details.get("shared_body_calls_used") == 3,
            "original native replay reached a different terminal")
    else: raise ValueError("expected original exhausted three-body run, not text ready")
    seed = original.source_material(original._workflow()); goal = seed["goal"]
    for receipt in receipts[1:]:
        diagnostic = script_contract.diagnose(receipt["output"], goal)
        require(not diagnostic["valid"] and diagnostic_identity._decision_identity(diagnostic)
            == diagnostic_identity._decision_identity(receipt["validation_error"]["detail"]), "complete original body diagnostic differs")
    files = {**proof["source_files"], **freeze["files"], **{path: value["sha256"] for path, value in reader.files.items()}}
    files[str(Path(__file__).resolve())] = sha(__file__)
    identity = {"root": str(root), "end_ordinal": expected_end, "terminal_state_sha256": sha(root / "STATE.json"),
        "native_ledger_sha256": sha(root / "CALL_LEDGER.json"), "production_freeze_sha256": sha(root / "PRODUCTION_FREEZE.json")}
    def ref(index):
        row, receipt = ledger["calls"][index], receipts[index]
        return {"path": str(root / row["receipt"]), "file_sha256": row["receipt_sha256"], "ordinal": row["ordinal"], "label": row["label"],
            "request_sha256": receipt["request_sha256"], "native_sha256": digest(receipt["output"]), "status": receipt["status"],
            "original_validation_sha256": digest(receipt.get("validation")),
            **({"original_diagnostic_sha256": digest(receipt["validation_error"]["detail"]), "diagnostic_json_pointer": "/validation_error/detail"} if index else {})}
    prepared = intents[0]["prepared"]; decision = receipts[0]["validation"]; source_ref = ref(0)
    decision_ref = {"path": source_ref["path"], "file_sha256": source_ref["file_sha256"], "json_pointer": "/validation",
        "native_sha256": digest(decision), "receipt_ordinal": receipts[0]["ordinal"], "valid": True, "accepted": True, "status": decision["status"]}
    prepared_path = root / "call_intents" / (LABELS[0] + ".json")
    prepared_ref = {"path": str(prepared_path), "file_sha256": sha(prepared_path), "json_pointer": "/prepared",
        "native_sha256": digest(prepared), "context_sha256": prepared["context_sha256"], "request_sha256": receipts[0]["request_sha256"]}
    rejected = [ref(i) for i in (1, 2, 3)]; remaining = {key: session.LIMITS[key] - COUNTS[key] for key in COUNTS}
    result = {"schema": VERSION, "session_schema": session.VERSION, "root": str(root), "verifier_code_sha256": sha(__file__),
        "inherited": inherited, "parent_identity": identity, "parent_identity_sha256": digest(identity), "source_files": files,
        "parent_anchor_path": config["parent_anchor_path"], "parent_anchor_sha256": config["parent_anchor_sha256"],
        "current_inputs_path": str(root / "INPUTS.json"), "current_inputs_file_sha256": sha(root / "INPUTS.json"), "current_inputs_sha256": digest(inputs),
        "current_profile_path": parent["current_profile_path"], "current_profile_file_sha256": parent["current_profile_file_sha256"], "current_profile_sha256": parent["current_profile_sha256"],
        "current_native_goal_receipt": deepcopy(parent["current_native_goal_receipt"]),
        "current_native_goal_audit_receipts": deepcopy(parent["current_native_goal_audit_receipts"]),
        "current_native_opening_setup_receipt": deepcopy(parent["current_native_opening_setup_receipt"]),
        "current_source_state_audit_receipt": source_ref, "current_source_state_audit_decision_ref": decision_ref,
        "accepted_source_state_audit_receipt": source_ref, "accepted_source_state_prepared_ref": prepared_ref,
        "accepted_source_state_decision_ref": decision_ref, "current_source_state_prepared_ref": prepared_ref,
        "current_source_state_audit_contract_valid": True, "current_source_state_audit_accepted": True,
        "current_source_state_audit_context_sha256": prepared["context_sha256"],
        "prior_source_state_audit_receipt": deepcopy(parent["current_source_state_audit_receipt"]),
        "prior_source_state_audit_decision_ref": deepcopy(parent["current_source_state_audit_decision_ref"]),
        "current_text_scope_accounting": {"limits": deepcopy(session.LIMITS), "consumed": deepcopy(COUNTS), "remaining": remaining,
            "calls_used": 4, "calls_remaining": sum(remaining.values()), "body_used": 3, "body_limit": 3, "body_versions_spent": deepcopy(session.BODY_VERSIONS)},
        "current_body_versions_unused": [], "remaining_complete_scripts": 0, "body_capacity_exhausted": True,
        "old_body_capacity_exhausted": True, "creative_body_capacity_regranted": False,
        "cumulative_body_attempts_used": parent["cumulative_body_attempts_used"] + 3,
        "cumulative_authorized_body_attempts": parent["cumulative_authorized_body_attempts"] + 3,
        "rejected_body_receipts": [*deepcopy(parent["rejected_body_receipts"]), *rejected],
        "recent_rejected_body_receipts": rejected, "last_known_rejected_body_receipt": rejected[-1],
        "old_director_capacity": deepcopy(session.base.DIRECTOR), "all_new_results_and_usage_known": True,
        "old_budget_reset": False, "authorizes_dispatch": False, "media_authorized": False, "text_ready_for_director": False,
        "human_quality_approved": False, "creative_quality_passed": False,
        "remaining_call_counts_are_accounting_not_new_grants": True,
        "source_freshness_for_next_production_certified": False, "counter_or_new_scope_admitted": False,
        "verification_scope": "Fixed v6 known accepted source4 and three rejected bodies: original rawSDK/SQL/freeze/RUN/intents/native replay and complete structural diagnostics. Original665/four audits/670, prior671 refusal and old645/650 remain separate. Eleven rejected bodies, four toy diagnostics and exhausted09-11 are retained. Six unused reviews confer no new scope."}
    return parent_bridge._inherit_original_lineage(result, parent)


def verify_anchor(anchor, *, expected_anchor_sha256):
    require(type(anchor) is dict and anchor.get("schema") == VERSION and digest(anchor) == expected_anchor_sha256, "continued-text anchor identity differs")
    require(build_anchor(anchor["root"], expected_end=anchor["parent_identity"]["end_ordinal"]) == anchor, "original v6 known evidence changed")
    return {"verified": True, "anchor": deepcopy(anchor), "inherited": deepcopy(anchor["inherited"]),
        "source_files": deepcopy(anchor["source_files"]), "parent_identity": deepcopy(anchor["parent_identity"]),
        "creative_source_root": anchor["creative_source_root"], "current_inputs_path": anchor["current_inputs_path"],
        "current_profile_path": anchor["current_profile_path"], "current_text_scope_accounting": deepcopy(anchor["current_text_scope_accounting"]),
        "authorizes_dispatch": False}
