"""Known v11 cost handoff: valid actual ledger plus invalid comparison JSON.

Pinned682 history is retained by exact certificate/frozen-file bytes. Only this
original run's two SDK/SQL/intent/replay records are revalidated. No JSON repair,
new grant, current freshness decision or text/media approval is produced.
"""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from scripts import creative_world_scene_source_bound_contract_spend_anchor_v1 as prior
from scripts import creative_world_scene_live_session_v11 as session
from scripts import creative_scope_probe_spend_anchor_v1 as known_evidence

VERSION = "creative_world_scene_invalid_comparison_spend_anchor/v1"
PARENT_SHA256 = "835c8ac6ec732a352f6b7cbf1195e87ece0ab7b72ff19fd95f1c78813fb36f27"
PARENT_VERIFIER_SHA256 = "bf39fc82f375be6c0639418df4a74ed534104b686aafdffbf77291b966189b0f"
LABELS = ("observable_events_calibration_14", "event_entailment_calibration_14")
COUNTS = {"goal_plan": 0, "goal_audit": 0, "complete_script": 0, "full_review": 2}
read, digest, sha, require, evidence = prior.read, prior.digest, prior.sha, prior.require, prior.evidence


def validate_parent_certificate(parent, freeze, *, expected_parent_sha256):
    require(expected_parent_sha256 == PARENT_SHA256 and digest(parent) == expected_parent_sha256
        and parent.get("schema") == prior.VERSION and parent.get("verifier_code_sha256") == PARENT_VERIFIER_SHA256
        and sha(prior.__file__) == PARENT_VERIFIER_SHA256, "registered682 certificate/schema/verifier differs")
    require(type(parent.get("source_files")) is dict and bool(parent["source_files"]) and type(freeze.get("files")) is dict
        and all(type(value) is str and freeze["files"].get(path) == value for path, value in parent["source_files"].items()),
        "entire682 certificate source-file set must remain identically frozen")


def validate_invalid_json(receipt):
    """Known protocol failure only; never parse/adopt a prefix or special suffix."""
    meta, payload = receipt.get("response_metadata", {}), receipt.get("response_payload", {})
    choices = payload.get("choices", [])
    require(receipt.get("status") == "interface_rejected" and receipt.get("output") is None and receipt.get("validation") is None
        and receipt.get("document_output") is None and receipt.get("failure") == {"schema": "creative_failure/v1",
            "code": "INVALID_JSON_RESPONSE", "category": "interface", "next_action": "diagnose_output_protocol",
            "response_received": True, "automatic_retry": False, "blocks_handoff": True}
        and len(choices) == 1 and choices[0].get("message", {}).get("role") == "assistant"
        and meta.get("finish_reason") == choices[0].get("finish_reason") == "tool_calls", "original known invalid JSON must remain unadopted")
    tools = choices[0]["message"].get("tool_calls")
    require(type(tools) is list and len(tools) == 1 and tools[0].get("type") == "function"
        and tools[0].get("function", {}).get("name") == evidence.ordinary.evidenced.TOOL_NAME
        and type(receipt.get("response_text")) is str and tools[0]["function"].get("arguments") == receipt["response_text"],
        "complete original target tool arguments required for JSON diagnosis")
    try: session.base.io.strict_json(receipt["response_text"])
    except (ValueError, TypeError): pass
    else: raise ValueError("claimed invalid JSON is a complete legal document")


def validate_records(parent, ledger, receipts, state, scope, *, expected_end):
    inherited = evidence._spend(parent["inherited"]); account = parent["current_text_scope_accounting"]
    require(type(expected_end) is int and expected_end == inherited["calls_started"] + 2
        and account["remaining"] == session.LIMITS and account["calls_remaining"] == session.TOTAL
        and account["body_used"] == 0 and parent["current_body_versions_unused"] == session.BODY_VERSIONS
        and parent.get("creative_body_capacity_regranted") is False, "exact original two-body/six-review parent required")
    require(ledger.get("schema") == "authorized_creative_continuation/v3" and ledger.get("starting_spend") == inherited
        and ledger.get("max_total_tokens") is None
        and all(ledger.get(k) is False for k in ("automatic_retry", "old_budget_reset", "old_governance_migrated")), "inherited ledger differs")
    require(scope.get("schema") == session.VERSION + "/remaining_capacity_authorization" and scope.get("inherited") == inherited
        and scope.get("stage_limits") == session.LIMITS and all(type(v) is int for v in scope["stage_limits"].values())
        and type(scope.get("total_new_calls_limit")) is int and scope["total_new_calls_limit"] == session.TOTAL
        and scope.get("complete_script_versions") == session.BODY_VERSIONS
        and scope.get("continuation_of_original_grant") == parent["continuation_of_original_grant"]
        and scope.get("creative_body_capacity_regranted") is False
        and all(scope.get(k) is False for k in ("automatic_retry", "old_budget_reset", "media_authorized", "publish_authorized")), "original unused capacity differs")
    rows = ledger.get("calls")
    require(type(rows) is list and len(rows) == len(receipts) == 2
        and [row.get("label") for row in rows] == list(LABELS)
        and [row.get("ordinal") for row in rows] == [expected_end - 1, expected_end], "only the original two-call prefix can settle")
    for row, receipt in zip(rows, receipts):
        meta, usage = receipt.get("response_metadata", {}), receipt.get("response_payload", {}).get("usage", {})
        require(receipt.get("ordinal") == row["ordinal"] and receipt.get("label") == row["label"]
            and receipt.get("request_sha256") == digest(receipt["request"]) and receipt.get("source_binding_sha256") == digest(ledger["source_manifest"])
            and receipt.get("token_reservation") == row.get("token_reservation") and bool(receipt.get("completed_at"))
            and receipt.get("automatic_retry") is False and receipt.get("semantic_approval") is False
            and receipt["request"].get("stage") == "full_review" and meta.get("http_status_code") == 200
            and meta.get("response_body_complete") is True and meta.get("finish_reason") == "tool_calls"
            and all(type(meta.get(k)) is int and meta[k] >= 0 and type(usage.get(k)) is int and meta[k] == usage[k]
                for k in ("prompt_tokens", "completion_tokens", "total_tokens"))
            and meta["prompt_tokens"] + meta["completion_tokens"] == meta["total_tokens"], "unknown/truncated/changed result cannot settle")
    session.prior.native_proof.known_native(receipts[0]); first = receipts[0].get("validation", {})
    require(receipts[0].get("status") == "contract_valid" and first.get("valid") is True and first.get("accepted") is True
        and first.get("ledger_usable") is True and first.get("findings") == first.get("uncertainties") == [], "original683 actual ledger must remain exactly valid")
    validate_invalid_json(receipts[1])
    expected = session.base.policy.accounting_summary(inherited, receipts, stage_limits=session.LIMITS, unknown_reservations=0)
    require(state.get("schema") == session.VERSION + "/state" and state.get("flow_version") == session.VERSION
        and state.get("status") == "halt_protocol_requires_diagnosis" and state.get("receipt_ordinal") == expected_end
        and state.get("spend_verification_pending") is False and state.get("spend") == expected and expected["stage_calls"] == COUNTS
        and state.get("new_stage_limits") == session.LIMITS and state.get("old_director_capacity") == session.base.DIRECTOR
        and all(state.get(k) is False for k in ("text_ready_for_director", "human_quality_approved", "creative_quality_passed", "media_authorized")), "original protocol terminal/accounting differs")
    return {"calls_started": expected["effective_calls_started"], "reported_tokens": expected["effective_reported_tokens"],
        "calls_with_known_usage": expected["effective_calls_with_known_usage"], "pending_ordinals": deepcopy(inherited["pending_ordinals"]),
        "unknown_token_reservations": inherited["unknown_token_reservations"]}


def build_anchor(root, *, expected_end):
    root = session.base._inside(root); reader = evidence.Reader(); original = session.Session.open(root)
    config, state, freeze, scope, inputs, ledger = [reader.json(root / (n + ".json")) for n in
        ("SESSION_CONFIG", "STATE", "PRODUCTION_FREEZE", "USER_SCOPE", "INPUTS", "CALL_LEDGER")]
    parent = reader.json(config["parent_anchor_path"]); validate_parent_certificate(parent, freeze, expected_parent_sha256=config["parent_anchor_sha256"])
    require(freeze.get("schema") == session.VERSION + "/freeze" and freeze.get("stage_limits") == session.LIMITS
        and freeze.get("total_new_calls_limit") == session.TOTAL and freeze.get("inherited") == parent["inherited"]
        and freeze.get("inputs_sha256") == digest(inputs) and config == asdict(original.config), "original fixedv11 freeze/config differs")
    for path, expected in freeze["files"].items(): reader.verify(session.base._inside(path), expected)
    require(ledger["source_manifest"] == {Path(path).resolve().relative_to(session.base.PROJECT).as_posix(): value for path, value in freeze["files"].items()}, "runtime source inventory differs from frozen files")
    require(scope == original.authorization_template({"preparation_identity_sha256": scope["preparation_identity_sha256"],
        "inherited": freeze["inherited"], "inputs_sha256": digest(inputs), "creative_source_root": scope["creative_source_root"], "inputs": inputs})
        and reader.json(config["authorization_path"]) == scope and freeze["binding"] == original._binding(parent), "scope/successor binding differs")
    successors = session.base.policy.successor_paths(session.base.PROJECT, parent, config["parent_anchor_sha256"])
    require(freeze["successor_claim_paths"] == [str(p) for p in successors] and all(reader.json(p) == freeze["binding"] for p in successors)
        and sha(original.claim) == freeze["claim_sha256"]
        and reader.json(original.claim) == {**freeze["binding"], "schema": session.VERSION + "/grant_claim"}, "dual unique successor/original grant differs")
    run, authorization = reader.json(root / "RUN_CLAIM.json"), reader.json(root / "AUTHORIZATION.json")
    require(run.get("schema") == session.VERSION + "/run_claim" and run.get("root") == str(root) and type(run.get("pid")) is int and run["pid"] > 0
        and run.get("automatic_restart") is False and run.get("freeze_sha256") == sha(root / "PRODUCTION_FREEZE.json")
        and state.get("run_claim_sha256") == sha(root / "RUN_CLAIM.json"), "original single RUN differs")
    require(authorization.get("schema") == "authorized_creative_continuation/v3" and authorization.get("starting_spend") == parent["inherited"]
        and authorization.get("max_total_tokens") is None and all(authorization.get(k) is False for k in ("old_budget_reset", "old_governance_migrated", "media_calls_authorized"))
        and ledger.get("authorization_sha256") == sha(root / "AUTHORIZATION.json"), "original runtime authority differs")
    original._profile_gate(); require(inputs == reader.json(parent["current_inputs_path"]) and digest(inputs) == parent["current_inputs_sha256"], "raw creative input changed")
    receipts = [known_evidence.verify_known_receipt(root, row, ledger["source_manifest"], reader) for row in ledger["calls"]]
    known_evidence._verify_tasks(reader, root, ledger, receipts, config["grant_id"])
    inherited = validate_records(parent, ledger, receipts, state, scope, expected_end=expected_end)
    prepared, intent_paths = [], []
    for index, (row, receipt) in enumerate(zip(ledger["calls"], receipts)):
        path = root / "call_intents" / (row["label"] + ".json"); intent = reader.json(path); item = intent["prepared"]
        require(intent == {"schema": session.VERSION + "/call_intent", "label": row["label"], "prepared": item,
            "request_sha256": receipt["request_sha256"], "ledger_prefix_sha256": digest(ledger["calls"][:index]),
            "inputs_sha256": digest(inputs), "automatic_retry": False} and item["request"] == receipt["request"], "original request intent/prefix differs")
        prepared.append(item); intent_paths.append(path)
    try: original._replay(ledger, verify_validations=True)
    except session.base.Halt as stopped:
        require(stopped.status == state["status"] and stopped.details == {"receipt_ordinal": expected_end}, "original invalid-JSON replay stop differs")
    else: raise ValueError("original protocol rejection must stop replay")
    require(original._workflow().validate_observable_events(receipts[0]["output"], prepared[0]) == receipts[0]["validation"], "original valid ledger decision differs")
    identity = {"root": str(root), "end_ordinal": expected_end, **{key: sha(root / name) for key, name in
        (("terminal_state_sha256", "STATE.json"), ("native_ledger_sha256", "CALL_LEDGER.json"), ("production_freeze_sha256", "PRODUCTION_FREEZE.json"))}}
    refs = [{"path": str(root / row["receipt"]), "file_sha256": row["receipt_sha256"], "ordinal": row["ordinal"], "label": row["label"],
        "request_sha256": receipt["request_sha256"], "native_sha256": digest(receipt["output"]) if receipt.get("output") is not None else None,
        "status": receipt["status"]} for row, receipt in zip(ledger["calls"], receipts)]
    return {**deepcopy(parent), "schema": VERSION, "session_schema": session.VERSION, "root": str(root), "verifier_code_sha256": sha(__file__),
        "inherited": inherited, "parent_identity": identity, "parent_identity_sha256": digest(identity),
        "source_files": {**freeze["files"], **{p: x["sha256"] for p, x in reader.files.items()}, str(Path(__file__).resolve()): sha(__file__)},
        "parent_anchor_path": config["parent_anchor_path"], "parent_anchor_sha256": config["parent_anchor_sha256"],
        "current_inputs_path": str(root / "INPUTS.json"), "current_inputs_file_sha256": sha(root / "INPUTS.json"), "current_inputs_sha256": digest(inputs),
        "prior_text_scope_accounting": deepcopy(parent["current_text_scope_accounting"]), "current_text_scope_accounting": {
            "limits": deepcopy(session.LIMITS), "consumed": deepcopy(COUNTS), "remaining": {k: session.LIMITS[k] - COUNTS[k] for k in COUNTS},
            "calls_used": 2, "calls_remaining": session.TOTAL - 2, "body_used": 0, "body_limit": 2, "body_versions_spent": []},
        "accepted_observable_events_receipt": refs[0], "latest_observable_events_receipt": refs[0],
        "accepted_observable_events_decision_ref": {"path": refs[0]["path"], "file_sha256": refs[0]["file_sha256"], "json_pointer": "/validation",
            "native_sha256": digest(receipts[0]["validation"]), "receipt_ordinal": expected_end - 1},
        "accepted_observable_events_prepared_ref": {"path": str(intent_paths[0]), "file_sha256": sha(intent_paths[0]), "json_pointer": "/prepared",
            "native_sha256": digest(prepared[0]), "context_sha256": prepared[0]["context_sha256"], "request_sha256": receipts[0]["request_sha256"]},
        "latest_invalid_comparison_receipt": refs[1], "latest_invalid_comparison_failure_ref": {"path": refs[1]["path"], "file_sha256": refs[1]["file_sha256"],
            "json_pointer": "/failure", "native_sha256": digest(receipts[1]["failure"]), "response_text_sha256": digest(receipts[1]["response_text"])},
        "observable_events_contract_valid": True, "comparison_contract_valid": False, "comparison_native_adopted": False,
        "authorizes_dispatch": False, "text_ready_for_director": False, "media_authorized": False,
        "historical_verification_basis": {"registered_parent_canonical_sha256": PARENT_SHA256, "all_parent_source_files_identically_frozen": True,
            "parent_source_file_count": len(parent["source_files"]), "frozen_source_bytes_verified_this_build": True,
            "recursive_historical_sdk_or_semantic_revalidation_performed": False},
        "verification_scope": "Fixed v11 original683/684 SDK/wire/SQL/freeze/RUN/intents/replay; pinned682 certificate and all identical source bytes retain history. Valid683 is a fallible actual ledger, not semantic approval. Invalid684 remains original text without JSON repair/adoption. Original unused2body4review is accounting only, no regrant/freshness/media authority."}


def verify_anchor(anchor, *, expected_anchor_sha256):
    require(type(anchor) is dict and anchor.get("schema") == VERSION and digest(anchor) == expected_anchor_sha256, "invalid-comparison anchor identity differs")
    require(build_anchor(anchor["root"], expected_end=anchor["parent_identity"]["end_ordinal"]) == anchor, "original fixedv11 evidence changed")
    return {"verified": True, "anchor": deepcopy(anchor), **{key: deepcopy(anchor[key]) for key in
        ("inherited", "source_files", "parent_identity", "creative_source_root", "current_inputs_path", "current_profile_path", "current_text_scope_accounting",
            "current_valid_body_receipt", "accepted_observable_events_receipt", "accepted_observable_events_prepared_ref", "accepted_observable_events_decision_ref")}, "authorizes_dispatch": False}
