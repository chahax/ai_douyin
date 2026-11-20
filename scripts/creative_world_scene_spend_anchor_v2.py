"""Read-only known644 accounting from the immutable v1 world-scene live run."""
from copy import deepcopy
from pathlib import Path

from scripts import creative_world_scene_live_session_v1 as session
from scripts import creative_world_scene_spend_anchor_v1 as parent640
from scripts import creative_session_spend_anchor_v1 as evidence

VERSION = "creative_world_scene_spend_anchor/v2"
ROOT = session.PROJECT / "data/production_trials/world_scene_live_20261015/round_01"
EXPECTED = {"calls_started": 644, "reported_tokens": 13668077, "calls_with_known_usage": 642,
    "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
digest = session.digest


def require(condition, reason):
    if not condition: raise ValueError(reason)


def build_anchor():
    original = session.Session.open(ROOT)
    original._guard()
    reader = evidence.Reader()
    freeze = reader.json(ROOT / "PRODUCTION_FREEZE.json")
    config = reader.json(ROOT / "SESSION_CONFIG.json")
    parent = reader.json(config["parent_anchor_path"])
    parent640.verify_anchor(parent, expected_anchor_sha256=config["parent_anchor_sha256"])
    ledger = reader.json(ROOT / "CALL_LEDGER.json")
    state = reader.json(ROOT / "STATE.json")
    require(state.get("status") == "halt_execution_reconciliation" and state.get("spend_verification_pending") is False
        and state.get("text_ready_for_director") is False, "original known terminal644 state required")
    require([row["ordinal"] for row in ledger["calls"]] == [641, 642, 643, 644]
        and [row["label"] for row in ledger["calls"]] == ["whole_plan_01", "scope_audit_01", "source_audit_01", "commitment_audit_01"]
        and ledger["starting_spend"] == parent["inherited"], "original four-call lineage differs")
    receipts = [evidence.verify_original_receipt(ROOT, row, ledger["source_manifest"], reader=reader) for row in ledger["calls"]]
    evidence._tasks(reader, ROOT, ledger, receipts, original.config.grant_id)
    for receipt in receipts: session.NativeSession.known(receipt, receipt["label"], require_valid=False)
    require(receipts[-1]["validation"]["valid"] is True and receipts[-1]["validation"]["accepted"] is False
        and len(receipts[-1]["validation"]["findings"]) == 2, "known native commitment failure required")
    inherited = deepcopy(parent["inherited"])
    inherited["calls_started"] += len(receipts)
    inherited["calls_with_known_usage"] += len(receipts)
    inherited["reported_tokens"] += sum(row["response_metadata"]["total_tokens"] for row in receipts)
    require(inherited == EXPECTED and state["spend"] == original.runtime().summary()
        and state["spend"]["new_unknown_token_reservations"] == 0, "644 original known spend differs")
    for name in ("RUN_CLAIM.json", "USER_SCOPE.json", "EXECUTION_ERROR.json"):
        reader.json(ROOT / name)
    files = {**freeze["files"], **{path: value["sha256"] for path, value in reader.files.items()}}
    identity = {"root": str(ROOT), "end_ordinal": 644, "terminal_state_sha256": session.sha(ROOT / "STATE.json"),
        "native_ledger_sha256": session.sha(ROOT / "CALL_LEDGER.json"), "production_freeze_sha256": session.sha(ROOT / "PRODUCTION_FREEZE.json")}
    return {"schema": VERSION, "root": str(ROOT), "parent_identity": identity, "inherited": inherited,
        "parent_anchor_path": config["parent_anchor_path"], "parent_anchor_sha256": config["parent_anchor_sha256"],
        "source_files": files, "original_scope_limits": session.LIMITS,
        "consumed_stage_calls": {"goal_plan": 1, "goal_audit": 3, "complete_script": 0, "full_review": 0},
        "remaining_scope_limits": {"goal_plan": 4, "goal_audit": 9, "complete_script": 3, "full_review": 6},
        "total_original_scope": 26, "consumed_calls": 4, "remaining_calls": 22,
        "whole_plans_used": 1, "whole_plans_remaining": 2, "old_director_capacity": session.DIRECTOR,
        "native_goal_receipt": {"path": str(ROOT / ledger["calls"][0]["receipt"]), "file_sha256": ledger["calls"][0]["receipt_sha256"],
            "native_sha256": digest(receipts[0]["output"])},
        "failed_audit_receipt": {"path": str(ROOT / ledger["calls"][-1]["receipt"]), "file_sha256": ledger["calls"][-1]["receipt_sha256"],
            "native_sha256": digest(receipts[-1]["output"])},
        "all_new_results_and_usage_known": True, "old_budget_reset": False, "authorizes_dispatch": False,
        "verification_scope": "Certified640 then complete641--644 original SDK/wire/SQL/native usage and v1 frozen dependency bytes; no new API requests"}


def verify_anchor(anchor, *, expected_anchor_sha256):
    require(type(anchor) is dict and digest(anchor) == expected_anchor_sha256, "settled644 anchor identity differs")
    require(build_anchor() == anchor, "original644 known evidence changed")
    return {"verified": True, "anchor": deepcopy(anchor), "inherited": deepcopy(anchor["inherited"]),
        "source_files": deepcopy(anchor["source_files"]), "authorizes_dispatch": False}
