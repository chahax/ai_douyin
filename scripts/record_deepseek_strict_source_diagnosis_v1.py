"""Retain the exact known605 protocol fault without adopting its arguments."""
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def build_diagnosis():
    from scripts import run_goal_context_text_production_v20 as run
    from src.content_factory.creative_flat_lineage_verifier_v3 import _verified_invalid_json_failure
    root = run.PREFLIGHT_PARENT
    ledger = run.read(root / "CALL_LEDGER.json")
    if [row["ordinal"] for row in ledger["calls"]] != [604, 605]:
        raise ValueError("exact original604/605 ledger required")
    source = run.read(root / ledger["calls"][-1]["receipt"])
    if not _verified_invalid_json_failure(source):
        raise ValueError("known605 complete malformed arguments required")
    goal = run.read(root / "goals/native_01.json")
    identity = run.verify_seed_native(goal)
    paths = {root / name for name in ("CALL_LEDGER.json", "STATE.json", "USER_SCOPE.json",
             "RUN_CLAIM.json", "PRODUCTION_FREEZE.json", "INPUTS.json", "goals/native_01.json")}
    for row in ledger["calls"]:
        receipt_path = root / row["receipt"]
        receipt = run.read(receipt_path)
        if run.sha_file(receipt_path) != row["receipt_sha256"]:
            raise ValueError("original receipt SHA changed")
        paths.add(receipt_path)
        evidence = Path(receipt["call_evidence"]["directory"])
        if not evidence.is_absolute():
            evidence = root / evidence
        paths.update(p for p in evidence.iterdir() if p.is_file())
    return {"schema": run.VERSION + "/known_protocol_diagnosis",
            "source_file_sha256": {str(p.resolve()): run.sha_file(p) for p in sorted(paths)},
            "parent_root": str(root), "parent_spend": run.read(root / "STATE.json")["spend"],
            "native_goal_identity": identity, "failure_ordinal": 605,
            "failure_code": "INVALID_JSON_RESPONSE", "failure_category": "interface",
            "complete_original_response_known": True, "reported_tokens": 38266,
            "argument_characters": 23896, "json_error_position": 23895,
            "unconsumed_original_suffix": "}",
            "original_arguments_sha256": "eb033bd54c0fd44631a2c11b73695cde5c23434dcb623a989807f15d1a3ded48",
            "original605_report_not_repaired_or_adopted": True,
            "known_invalid_json_failure_consumption_only": True,
            "original_claim_not_restarted": True, "new_first_action": "complete_new_native_source_audit",
            "old_unused_goal_capacity_stays_closed": True, "media_authorized": False,
            "semantic_quality_approved": False}


def main():
    from scripts import run_goal_context_text_production_v20 as run
    run.prior_guard()
    run.write(run.CONTENT_DIAGNOSIS, build_diagnosis(), True)
    print(str(run.CONTENT_DIAGNOSIS))


if __name__ == "__main__":
    main()
