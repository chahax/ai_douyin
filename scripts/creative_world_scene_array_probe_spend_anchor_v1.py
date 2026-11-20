"""Read-only accounting for the four registered657--660 interface diagnostics.

This certificate preserves all six rejected screenplay attempts. Diagnostic
calls do not become screenplay attempts, creative approvals, or a new grant.
"""
from copy import deepcopy
import json
from pathlib import Path

from scripts import creative_session_spend_anchor_v1 as evidence
from scripts import creative_world_scene_array_probe_session_v1 as session
from scripts import creative_world_scene_spend_anchor_v4 as parent656

VERSION = "creative_world_scene_array_probe_spend_anchor/v1"
ROOT = session.base.PROJECT / "data/production_trials/world_scene_array_probe_20261016/round_01"
EXPECTED = {"calls_started": 660, "reported_tokens": 14073608, "calls_with_known_usage": 658,
    "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
digest, sha, require = session.digest, session.sha, parent656.require
PRESERVED = ("native_goal_receipt", "native_goal_audit_receipts", "native_opening_setup_receipt",
    "original_goal_bundle_sha256", "same_source_goal_audit_decision_sha256", "rejected_body_receipts",
    "original_scope_accounting", "additional_scope_accounting")


def _validation_identity(value):
    """A diagnostic list has no ordering claim; preserve every complete row."""
    require(type(value) is dict and type(value.get("findings")) is list, "complete original diagnostic findings required")
    header = {key: item for key, item in value.items() if key != "findings"}
    findings = sorted(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        for row in value["findings"])
    return header, findings


def validate_accounting(parent, ledger, receipts, state, summary, cases, *, root=ROOT):
    """Pure original-record checks; no SDK, source refresh, or claim is made."""
    inherited = evidence._spend(parent["inherited"])
    require(inherited == parent656.EXPECTED and ledger.get("starting_spend") == inherited
        and parent.get("cumulative_body_attempts_used") == parent.get("cumulative_authorized_body_attempts") == 6
        and parent.get("remaining_complete_scripts") == 0 and parent.get("body_capacity_exhausted") is True
        and [r["ordinal"] for r in parent.get("rejected_body_receipts", [])] == list(range(651, 657)),
        "certified656 consumption and all six spent bodies required")
    require(ledger.get("schema") == "authorized_creative_continuation/v3" and ledger.get("max_total_tokens") is None
        and all(ledger.get(k) is False for k in ("automatic_retry", "old_budget_reset", "old_governance_migrated")),
        "original no-reset/no-retry ledger required")
    calls = ledger.get("calls")
    require(type(calls) is list and len(calls) == len(receipts) == len(cases) == 4
        and [r.get("ordinal") for r in calls] == [657, 658, 659, 660]
        and [c.get("id") for c in cases] == session.CASE_IDS
        and [r.get("label") for r in calls] == ["array_probe_" + cid for cid in session.CASE_IDS],
        "exact four ordered registered diagnostics required")
    rows, ids, requests = [], set(), set()
    cases_module = session.importlib.import_module("scripts.creative_world_scene_array_probe_cases_v1")
    for row, receipt, case in zip(calls, receipts, cases):
        native = session.known_native(receipt)
        meta, request = receipt.get("response_metadata", {}), receipt.get("request", {})
        require(receipt.get("ordinal") == row["ordinal"] and receipt.get("label") == row["label"]
            and request == case["request"] and receipt.get("request_sha256") == digest(request)
            and receipt.get("source_binding_sha256") == digest(ledger["source_manifest"])
            and receipt.get("status") == "contract_rejected" and receipt.get("automatic_retry") is False
            and receipt.get("semantic_approval") is False and bool(receipt.get("completed_at")),
            "original complete rejected diagnostic identity differs")
        usage = receipt.get("response_payload", {}).get("usage", {})
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            require(type(meta.get(key)) is int and meta[key] >= 0 and type(usage.get(key)) is int
                and usage[key] == meta[key], "unknown or nontyped usage cannot settle")
        require(meta["prompt_tokens"] + meta["completion_tokens"] == meta["total_tokens"], "original usage sum differs")
        rid, request_sha = meta.get("response_id"), receipt["request_sha256"]
        require(isinstance(rid, str) and bool(rid) and rid not in ids and request_sha not in requests,
            "duplicate original response or request")
        ids.add(rid); requests.add(request_sha)
        validation = cases_module.validate(native, case)
        require(validation.get("valid") is False
            and _validation_identity(receipt.get("validation")) == _validation_identity(validation),
            "original diagnostic rejection changed")
        rows.append({"id": case["id"], "representation": case["representation"], "context_variant": case["context_variant"],
            "context_sha256": case["context_sha256"], "ordinal": receipt["ordinal"], "receipt_status": receipt["status"],
            "receipt_path": str(root / row["receipt"]), "native_sha256": digest(native),
            "request_sha256": request_sha, "validation": deepcopy(receipt["validation"])})
    expected_summary = session.base.policy.accounting_summary(inherited, receipts,
        stage_limits=session.LIMITS, unknown_reservations=0)
    require(state.get("schema") == session.VERSION + "/state" and summary.get("schema") == session.VERSION + "/summary"
        and state.get("status") == summary.get("status") == "diagnostic_completed_not_creative"
        and state.get("complete_factorial") is summary.get("complete_factorial") is True
        and state.get("diagnostic_only") is summary.get("diagnostic_only") is True
        and state.get("spend_verification_pending") is summary.get("spend_verification_pending") is False
        and state.get("spend") == summary.get("spend") == expected_summary
        and state.get("summary_sha256") == digest(summary) and summary.get("completed_known_cases") == rows
        and summary.get("ordered_case_ids") == session.CASE_IDS and summary.get("stop_details") == {}
        and summary.get("old_complete_body_calls_used") == summary.get("old_complete_body_capacity") == 6
        and state.get("creative_body_capacity_regranted") is False and state.get("old_director_capacity") == session.base.DIRECTOR
        and all(state.get(k) is False for k in ("human_quality_approved", "creative_quality_passed", "media_authorized", "text_ready_for_director"))
        and all(summary.get(k) is False for k in ("human_quality_approved", "creative_quality_passed", "media_submitted", "text_ready_for_director")),
        "original terminal diagnostic status/accounting/native rows differ")
    result = {"calls_started": expected_summary["effective_calls_started"], "reported_tokens": expected_summary["effective_reported_tokens"],
        "calls_with_known_usage": expected_summary["effective_calls_with_known_usage"],
        "pending_ordinals": deepcopy(inherited["pending_ordinals"]), "unknown_token_reservations": inherited["unknown_token_reservations"]}
    require(result == EXPECTED, "cumulative660 accounting differs")
    return result


def build_anchor():
    reader = evidence.Reader()
    original = session.Session.open(ROOT); original._guard()
    config = reader.json(ROOT / "SESSION_CONFIG.json"); freeze = reader.json(ROOT / "PRODUCTION_FREEZE.json")
    parent = reader.json(config["parent_anchor_path"])
    proof = parent656.verify_anchor(parent, expected_anchor_sha256=config["parent_anchor_sha256"])
    require(proof.get("verified") is True and proof.get("inherited") == parent["inherited"], "verified original656 required")
    ledger = reader.json(ROOT / "CALL_LEDGER.json"); state = reader.json(ROOT / "STATE.json")
    summary = reader.json(ROOT / "SUMMARY.json"); cases = original._cases()
    receipts = [evidence.verify_original_receipt(ROOT, row, ledger["source_manifest"], reader=reader) for row in ledger["calls"]]
    evidence._tasks(reader, ROOT, ledger, receipts, config["grant_id"])
    inherited = validate_accounting(parent, ledger, receipts, state, summary, cases)
    require(state["spend"] == original.runtime().summary(), "original runtime accounting differs")
    for left, right in ((0, 1), (2, 3)):
        wires = [deepcopy(session.base.clients.expected_wire_request(cases[index]["request"])) for index in (left, right)]
        for wire in wires: wire["tools"][0]["function"].pop("parameters")
        require(wires[0] == wires[1], "same-context actual wire differs beyond registered schema")
    run = reader.json(ROOT / "RUN_CLAIM.json")
    require(run.get("schema") == session.VERSION + "/run_claim" and run.get("root") == str(ROOT)
        and run.get("automatic_restart") is False and run.get("freeze_sha256") == sha(ROOT / "PRODUCTION_FREEZE.json")
        and state.get("run_claim_sha256") == sha(ROOT / "RUN_CLAIM.json"), "original RUN/freeze differs")
    reader.json(ROOT / "USER_SCOPE.json"); reader.json(ROOT / "AUTHORIZATION.json")
    creative_root = session.base._inside(parent["root"])
    creative_inputs = reader.json(creative_root / "INPUTS.json")
    creative_config = reader.json(creative_root / "SESSION_CONFIG.json")
    profile_path = session.base._inside(creative_config["profile_path"])
    for path in (creative_root / "INPUTS.json", creative_root / "SESSION_CONFIG.json", profile_path):
        require(proof["source_files"].get(str(path)) == sha(path), "original creative inputs/profile not certified by parent656")
    reader.bytes(profile_path)
    files = {**proof["source_files"], **freeze["files"], **{p: v["sha256"] for p, v in reader.files.items()}}
    files[str(Path(__file__).resolve())] = sha(__file__)
    identity = {"root": str(ROOT), "end_ordinal": 660, "terminal_state_sha256": sha(ROOT / "STATE.json"),
        "native_ledger_sha256": sha(ROOT / "CALL_LEDGER.json"), "production_freeze_sha256": sha(ROOT / "PRODUCTION_FREEZE.json")}
    result = {"schema": VERSION, "verifier_code_sha256": sha(__file__), "root": str(ROOT),
        "parent_identity": identity, "parent_identity_sha256": digest(identity), "inherited": inherited,
        "parent_anchor_path": config["parent_anchor_path"], "parent_anchor_sha256": config["parent_anchor_sha256"], "source_files": files,
        "creative_source_root": str(creative_root), "original_creation_root": str(creative_root),
        "original_inputs_path": str(creative_root / "INPUTS.json"), "original_inputs_file_sha256": sha(creative_root / "INPUTS.json"),
        "original_inputs_sha256": digest(creative_inputs), "original_profile_path": str(profile_path), "original_profile_file_sha256": sha(profile_path),
        "registered_diagnostic_receipts": [{"path": str(ROOT / row["receipt"]), "file_sha256": row["receipt_sha256"],
            "ordinal": row["ordinal"], "label": row["label"], "request_sha256": receipt["request_sha256"],
            "native_sha256": digest(receipt["output"]), "status": receipt["status"], "original_validation_sha256": digest(receipt["validation"])}
            for row, receipt in zip(ledger["calls"], receipts)],
        "diagnostic_scope_accounting": {"used": 4, "limit": 4, "remaining": 0, "reported_tokens": 12112,
            "runtime_stage_calls": deepcopy(session.LIMITS), "creative_body_attempts_added": 0},
        "cumulative_body_attempts_used": 6, "cumulative_authorized_body_attempts": 6, "remaining_complete_scripts": 0,
        "body_capacity_exhausted": True, "old_body_capacity_exhausted": True, "additional_body_capacity_exhausted": True,
        "old_director_capacity": deepcopy(session.base.DIRECTOR), "all_new_results_and_usage_known": True,
        "remaining_call_counts_are_accounting_not_new_grants": True, "old_budget_reset": False,
        "diagnostic_only": True, "diagnostic_scope_regranted": False, "text_ready_for_director": False,
        "body_or_full_review_approved": False, "creative_body_capacity_regranted": False, "authorizes_dispatch": False,
        "source_freshness_for_next_production_certified": False, "counter_or_new_scope_admitted": False,
        "verification_scope": "Certified656 plus original657--660 raw SDK/wire/SQLite/freeze/RUN/summary; four registered interface rejections, not screenplay approval. Original645/four audits/650 references and six spent rejected bodies preserved. Future source freshness, active round and new scope require independent admission."}
    for key in PRESERVED: result[key] = deepcopy(parent[key])
    return result


def verify_anchor(anchor, *, expected_anchor_sha256):
    require(type(anchor) is dict and digest(anchor) == expected_anchor_sha256, "settled660 anchor identity differs")
    require(build_anchor() == anchor, "original660 evidence changed")
    return {"verified": True, "anchor": deepcopy(anchor), "inherited": deepcopy(anchor["inherited"]),
        "source_files": deepcopy(anchor["source_files"]), "parent_identity": deepcopy(anchor["parent_identity"]),
        "creative_source_root": anchor["creative_source_root"], "body_capacity_exhausted": True, "authorizes_dispatch": False}
