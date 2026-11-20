"""Read-only v7 settlement: structural body validity is never text admission.

The fixed v7 protocol is replayed from original SDK/SQL/intent evidence. Its
invalid semantic report stays invalid, including its original all-pass claims.
Historical settlement grants no calls, media, current freshness or new scope.
"""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from scripts import creative_session_spend_anchor_v1 as evidence
from scripts import creative_world_scene_continued_text_spend_anchor_v1 as parent_bridge
from scripts import creative_world_scene_source_audit_spend_anchor_v1 as decisions
from scripts import creative_world_scene_live_session_v7 as session
from scripts import creative_world_scene_derived_context_script_v1 as contract

VERSION = "creative_world_scene_derived_text_spend_anchor/v1"
read, digest, sha, require = session.read, session.digest, session.sha, parent_bridge.require
LABELS = (*[f"complete_script_{n:02}" for n in session.BODY_VERSIONS],
    f"full_review_semantic_{session.BODY_VERSIONS[-1]:02}")
COUNTS = {"goal_plan": 0, "goal_audit": 0, "complete_script": 3, "full_review": 1}


def validate_records(parent, ledger, receipts, state, scope, *, expected_end):
    """Pure accounting/typed outcomes; SDK and recomputation are build duties."""
    inherited = evidence._spend(parent["inherited"])
    require(type(expected_end) is int and expected_end == inherited["calls_started"] + len(LABELS), "four contiguous original calls required")
    previous = parent.get("current_text_scope_accounting", {})
    require(parent.get("schema") == parent_bridge.VERSION and previous.get("limits") == session.PARENT_LIMITS
        and previous.get("consumed") == session.PARENT_USED and previous.get("remaining") == session.PARENT_REMAINING
        and previous.get("calls_used") == 4 and previous.get("calls_remaining") == 6
        and previous.get("body_used") == 3 and previous.get("body_limit") == 3
        and parent.get("current_body_versions_unused") == []
        and len(parent.get("rejected_body_receipts", [])) == 11
        and len(parent.get("registered_diagnostic_receipts", [])) == 4
        and parent.get("current_source_state_audit_contract_valid") is True
        and parent.get("current_source_state_audit_accepted") is True, "original exhausted11-body accepted-source parent required")
    require(ledger.get("schema") == "authorized_creative_continuation/v3" and ledger.get("starting_spend") == inherited
        and ledger.get("max_total_tokens") is None
        and all(ledger.get(k) is False for k in ("automatic_retry", "old_budget_reset", "old_governance_migrated")), "original inherited no-retry ledger required")
    require(scope.get("schema") == session.VERSION + "/derived_authorization" and scope.get("inherited") == inherited
        and scope.get("stage_limits") == session.LIMITS and all(type(v) is int for v in scope["stage_limits"].values())
        and type(scope.get("total_new_calls_limit")) is int and scope["total_new_calls_limit"] == session.TOTAL
        and scope.get("complete_script_versions") == session.BODY_VERSIONS and scope.get("complete_script_limit_shared_across_plans") == 3
        and scope.get("old_complete_body_calls_used") == scope.get("old_complete_body_capacity") == 11
        and scope.get("parent_scope_calls_used") == 4 and scope.get("parent_scope_calls_remaining") == 6
        and scope.get("new_source_state_audit_limit") == 0 and scope.get("reuses_accepted_source_state") is True
        and scope.get("native_derived_script_identities_required") is True
        and all(scope.get(k) is False for k in ("automatic_retry", "old_budget_reset", "media_authorized", "publish_authorized")), "original v7 nine-call scope required")
    calls = ledger.get("calls")
    require(type(calls) is list and len(calls) == len(receipts) == len(LABELS)
        and [r.get("label") for r in calls] == list(LABELS)
        and [r.get("ordinal") for r in calls] == list(range(inherited["calls_started"] + 1, expected_end + 1)), "original three-body/semantic sequence differs")
    ids, requests = set(), set()
    for index, (row, receipt) in enumerate(zip(calls, receipts)):
        session.native_proof.known_native(receipt)
        request, meta = receipt["request"], receipt["response_metadata"]
        require(receipt.get("ordinal") == row["ordinal"] and receipt.get("label") == row["label"]
            and receipt.get("request_sha256") == digest(request) and receipt.get("source_binding_sha256") == digest(ledger["source_manifest"])
            and receipt.get("token_reservation") == row.get("token_reservation") and receipt.get("automatic_retry") is False
            and receipt.get("semantic_approval") is False and bool(receipt.get("completed_at"))
            and request.get("stage") == ("full_review" if index == 3 else "complete_script")
            and request.get("role") == ("director" if index == 3 else "writer")
            and receipt.get("status") == ("contract_valid" if index == 2 else "contract_rejected"), "original native stage/identity differs")
        decision = receipt.get("validation")
        if index < 2:
            diagnostic = receipt.get("validation_error", {}).get("detail", {})
            require(decision is None and diagnostic.get("valid") is False and bool(diagnostic.get("findings")), "two original body structural refusals required")
        elif index == 2:
            require(type(decision) is dict and decision.get("valid") is True
                and decision.get("provider_native") == receipt["output"] and decision.get("necessary_conditions_only") is True
                and decision.get("creative_quality_passed") is False, "body structure validity is not creative/text approval")
        else:
            require(type(decision) is dict and decision.get("valid") is False and decision.get("accepted") is False
                and bool(decision.get("findings")) and decision.get("content_checks_satisfied") is False
                and decision.get("new_scope_admitted") is False and decision.get("native_review_values_rewritten") is False,
                "original invalid semantic opinion cannot be adopted")
        if index != 2:
            failure = receipt.get("failure", {})
            require(failure.get("category") in ("validation", "state_contract", "compilation")
                and failure.get("response_received") is True and failure.get("automatic_retry") is False, "complete known contract refusal required")
        usage = receipt.get("response_payload", {}).get("usage", {})
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            require(type(meta.get(key)) is int and meta[key] >= 0 and type(usage.get(key)) is int and usage[key] == meta[key], "unknown/nontyped usage cannot settle")
        require(meta["prompt_tokens"] + meta["completion_tokens"] == meta["total_tokens"], "usage sum differs")
        rid = meta.get("response_id")
        require(type(rid) is str and bool(rid) and rid not in ids and receipt["request_sha256"] not in requests, "duplicate original response/request")
        ids.add(rid); requests.add(receipt["request_sha256"])
    expected = session.base.policy.accounting_summary(inherited, receipts, stage_limits=session.LIMITS, unknown_reservations=0)
    require(state.get("schema") == session.VERSION + "/state" and state.get("flow_version") == session.VERSION
        and state.get("status") == "halt_review_contract" and state.get("stage") == "semantic"
        and state.get("decision") == receipts[-1]["validation"] and state.get("spend_verification_pending") is False
        and state.get("spend") == expected and expected["stage_calls"] == COUNTS
        and state.get("new_stage_limits") == session.LIMITS and state.get("old_director_capacity") == session.base.DIRECTOR
        and all(state.get(k) is False for k in ("text_ready_for_director", "human_quality_approved", "creative_quality_passed", "media_authorized")), "original semantic-contract halt/accounting differs")
    return {"calls_started": expected["effective_calls_started"], "reported_tokens": expected["effective_reported_tokens"],
        "calls_with_known_usage": expected["effective_calls_with_known_usage"], "pending_ordinals": deepcopy(inherited["pending_ordinals"]),
        "unknown_token_reservations": inherited["unknown_token_reservations"]}


def _historical_identity(original, parent, reader, freeze, scope):
    """Frozen original protocol, without inactive counter or freshness gates."""
    root, config = original.root, original.config; inputs = reader.json(root / "INPUTS.json")
    require(freeze.get("schema") == session.VERSION + "/freeze" and freeze.get("stage_limits") == session.LIMITS
        and freeze.get("total_new_calls_limit") == session.TOTAL and freeze.get("inherited") == parent["inherited"]
        and freeze.get("inputs_sha256") == digest(inputs) and digest(reader.json(root / "SESSION_CONFIG.json")) == digest(asdict(config)), "original v7 freeze/config differs")
    expected_scope = original.authorization_template({"preparation_identity_sha256": scope["preparation_identity_sha256"],
        "inherited": freeze["inherited"], "inputs_sha256": freeze["inputs_sha256"], "creative_source_root": scope["creative_source_root"], "inputs": inputs})
    require(scope == expected_scope and reader.json(config.authorization_path) == scope, "original exact v7 authorization differs")
    for path, expected in freeze["files"].items(): reader.verify(session.base._inside(path), expected)
    require(digest(parent) == config.parent_anchor_sha256 and freeze["binding"] == original._binding(parent), "original parent identity differs")
    paths = session.base.policy.successor_paths(session.base.PROJECT, parent, config.parent_anchor_sha256)
    require(freeze["successor_claim_paths"] == [str(path) for path in paths], "original dual successor paths differ")
    for path in paths: require(reader.json(path) == freeze["binding"], "original unique successor differs")
    require(sha(original.claim) == freeze["claim_sha256"] and reader.json(original.claim) == {**freeze["binding"], "schema": session.VERSION + "/grant_claim"}, "original grant differs")
    run = reader.json(root / "RUN_CLAIM.json")
    require(run.get("schema") == session.VERSION + "/run_claim" and run.get("root") == str(root) and type(run.get("pid")) is int
        and run["pid"] > 0 and run.get("automatic_restart") is False and run.get("freeze_sha256") == sha(root / "PRODUCTION_FREEZE.json"), "original RUN differs")
    auth = reader.json(root / "AUTHORIZATION.json")
    require(auth.get("schema") == "authorized_creative_continuation/v3" and auth.get("starting_spend") == parent["inherited"]
        and auth.get("max_total_tokens") is None and auth.get("old_budget_reset") is False
        and auth.get("old_governance_migrated") is False and auth.get("media_calls_authorized") is False, "original runtime authorization differs")
    original._profile_gate()
    require(inputs == reader.json(parent["current_inputs_path"]) and digest(inputs) == parent["current_inputs_sha256"], "original current creative authority changed")
    return inputs


def build_anchor(root, *, expected_end):
    root = session.base._inside(root); reader = evidence.Reader(); state = reader.json(root / "STATE.json")
    require(state.get("schema") == session.VERSION + "/state", "unsupported original derived-text protocol")
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
            and intent.get("ledger_prefix_sha256") == digest(ledger["calls"][:index]), "original exact request/intent/prefix differs")
    try: original._replay(ledger, verify_validations=True)
    except session.base.stages.OfflineStop as stopped:
        require(stopped.status == "halt_review_contract" and stopped.details.get("stage") == "semantic"
            and stopped.details.get("decision") == state["decision"], "original replay reached a different terminal")
    else: raise ValueError("expected original invalid semantic report, never text ready")
    goal = original.source_material(original._workflow())["goal"]
    for receipt in receipts[:2]:
        diagnostic = contract.diagnose(receipt["output"], goal)
        require(not diagnostic["valid"] and decisions._decision_identity(diagnostic)
            == decisions._decision_identity(receipt["validation_error"]["detail"]), "complete original body diagnostic differs")
    prepared = intents[2]["prepared"]; compiled = contract.compile_document(receipts[2]["output"], goal, prepared["views"]["brief"])
    require(compiled == receipts[2]["validation"], "original raw/derived/compiled structure proof differs")
    reviewed = intents[-1]["prepared"]; views = prepared["views"]; reviews = original._workflow().full_reviews()
    checked = reviews.validate_part(receipts[-1]["output"], "semantic", compiled["script"], views["brief"], views["plan"],
        reviewed["review_legal_context"], context_sha256=reviewed["part_context_sha256"], goal_contract=goal,
        opening_setup=views["opening_setup"], prior_story_scope=inputs["production_preferences"].get("prior_story_scope"))
    require(checked == receipts[-1]["validation"] and not checked["valid"], "original semantic contract refusal changed")
    files = {**proof["source_files"], **freeze["files"], **{path: value["sha256"] for path, value in reader.files.items()}}
    files[str(Path(__file__).resolve())] = sha(__file__)
    identity = {"root": str(root), "end_ordinal": expected_end, "terminal_state_sha256": sha(root / "STATE.json"),
        "native_ledger_sha256": sha(root / "CALL_LEDGER.json"), "production_freeze_sha256": sha(root / "PRODUCTION_FREEZE.json")}
    def ref(index):
        row, receipt = ledger["calls"][index], receipts[index]
        return {"path": str(root / row["receipt"]), "file_sha256": row["receipt_sha256"], "ordinal": row["ordinal"], "label": row["label"],
            "request_sha256": receipt["request_sha256"], "native_sha256": digest(receipt["output"]), "status": receipt["status"],
            "original_validation_sha256": digest(receipt.get("validation"))}
    body_ref, review_ref = ref(2), ref(3)
    def embedded(ref_value, pointer, value):
        return {"path": ref_value["path"], "file_sha256": ref_value["file_sha256"], "json_pointer": pointer,
            "native_sha256": digest(value), "receipt_ordinal": ref_value["ordinal"]}
    remaining = {key: session.LIMITS[key] - COUNTS[key] for key in COUNTS}
    result = {"schema": VERSION, "session_schema": session.VERSION, "root": str(root), "verifier_code_sha256": sha(__file__),
        "inherited": inherited, "parent_identity": identity, "parent_identity_sha256": digest(identity), "source_files": files,
        "parent_anchor_path": config["parent_anchor_path"], "parent_anchor_sha256": config["parent_anchor_sha256"],
        "current_inputs_path": str(root / "INPUTS.json"), "current_inputs_file_sha256": sha(root / "INPUTS.json"), "current_inputs_sha256": digest(inputs),
        "current_profile_path": parent["current_profile_path"], "current_profile_file_sha256": parent["current_profile_file_sha256"], "current_profile_sha256": parent["current_profile_sha256"],
        **{key: deepcopy(parent[key]) for key in session.REF_KEYS},
        "current_source_state_audit_contract_valid": True, "current_source_state_audit_accepted": True,
        "current_source_state_audit_context_sha256": parent["current_source_state_audit_context_sha256"],
        "current_valid_body_receipt": body_ref,
        "current_valid_body_validation_ref": embedded(body_ref, "/validation", compiled),
        "current_valid_body_derived_ref": embedded(body_ref, "/validation/derived_script", compiled["derived_script"]),
        "current_valid_body_compiled_ref": embedded(body_ref, "/validation/script", compiled["script"]),
        "current_valid_body_source_descriptor_ref": embedded(body_ref, "/validation/source_descriptor", compiled["source_descriptor"]),
        "current_valid_body_compiler_manifest_ref": embedded(body_ref, "/validation/compiler_manifest", compiled["compiler_manifest"]),
        "current_valid_body_source_descriptor": deepcopy(compiled["source_descriptor"]),
        "current_valid_body_structure_valid": True, "current_valid_body_text_qualified": False,
        "latest_full_review_receipt": review_ref,
        "latest_full_review_decision_ref": embedded(review_ref, "/validation", checked),
        "latest_full_review_prepared_ref": {"path": str(root / "call_intents" / (LABELS[-1] + ".json")),
            "file_sha256": sha(root / "call_intents" / (LABELS[-1] + ".json")), "json_pointer": "/prepared",
            "native_sha256": digest(reviewed), "context_sha256": reviewed["part_context_sha256"], "request_sha256": review_ref["request_sha256"]},
        "latest_full_review_contract_valid": False, "latest_full_review_accepted": False,
        "current_text_scope_accounting": {"limits": deepcopy(session.LIMITS), "consumed": deepcopy(COUNTS), "remaining": remaining,
            "calls_used": 4, "calls_remaining": sum(remaining.values()), "body_used": 3, "body_limit": 3, "body_versions_spent": deepcopy(session.BODY_VERSIONS)},
        "current_body_versions_unused": [], "remaining_complete_scripts": 0, "body_capacity_exhausted": True,
        "old_body_capacity_exhausted": True, "creative_body_capacity_regranted": False,
        "cumulative_body_attempts_used": parent["cumulative_body_attempts_used"] + 3,
        "cumulative_authorized_body_attempts": parent["cumulative_authorized_body_attempts"] + 3,
        "rejected_body_receipts": [*deepcopy(parent["rejected_body_receipts"]), ref(0), ref(1)],
        "recent_rejected_body_receipts": [ref(0), ref(1)], "last_known_rejected_body_receipt": ref(1),
        "structurally_valid_unqualified_body_receipts": [body_ref],
        "old_director_capacity": deepcopy(session.base.DIRECTOR), "all_new_results_and_usage_known": True,
        "old_budget_reset": False, "authorizes_dispatch": False, "media_authorized": False, "text_ready_for_director": False,
        "human_quality_approved": False, "creative_quality_passed": False,
        "remaining_call_counts_are_accounting_not_new_grants": True, "source_freshness_for_next_production_certified": False,
        "counter_or_new_scope_admitted": False,
        "verification_scope": "Fixed v7 four known calls: original SDK/wire/SQL/freeze/RUN/intents and full native replay. Fourteen bodies remain spent: thirteen structural refusals and one structurally valid but unqualified body. Original invalid semantic all-pass report remains rejected; no physical review or text/media admission. Five unused reviews are accounting only."}
    return parent_bridge.parent_bridge._inherit_original_lineage(result, parent)


def verify_anchor(anchor, *, expected_anchor_sha256):
    require(type(anchor) is dict and anchor.get("schema") == VERSION and digest(anchor) == expected_anchor_sha256, "derived-text anchor identity differs")
    require(build_anchor(anchor["root"], expected_end=anchor["parent_identity"]["end_ordinal"]) == anchor, "original v7 evidence changed")
    return {"verified": True, "anchor": deepcopy(anchor), "inherited": deepcopy(anchor["inherited"]),
        "source_files": deepcopy(anchor["source_files"]), "parent_identity": deepcopy(anchor["parent_identity"]),
        "creative_source_root": anchor["creative_source_root"], "current_inputs_path": anchor["current_inputs_path"],
        "current_profile_path": anchor["current_profile_path"], "current_text_scope_accounting": deepcopy(anchor["current_text_scope_accounting"]),
        "current_valid_body_receipt": deepcopy(anchor["current_valid_body_receipt"]), "authorizes_dispatch": False}
