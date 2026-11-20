"""Bind existing explicit text authority to a new independent repaired run."""
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import run_goal_context_text_production_v18 as run


def main():
    if run.CLAIM.exists() or run.ROOT.exists():
        raise RuntimeError("existing global grant/run; inspect original, never regrant")
    run.prior_guard()
    authority = run.read(run.previous.APPROVAL)
    if authority.get("user_quote") != "minimax随便追加" or authority.get("human_authorized") is not True:
        raise ValueError("existing explicit human text authorization required")
    terminal = run.read(run.PARENT_STATE)
    if (terminal["status"] != "halt_review_interface_or_unknown"
            or (terminal["spend"]["effective_calls_started"],terminal["spend"]["effective_reported_tokens"],
                terminal["cumulative_goal_candidates_used"]) != (601,12004575,24)):
        raise ValueError("known closed parent terminal state required; never restart601 claim")
    row = next(row for row in run.read(run.PREFLIGHT_PARENT / "CALL_LEDGER.json")["calls"] if row["ordinal"] == 594)
    seed = run.read(run.PREFLIGHT_PARENT / row["receipt"])["output"]
    identity = run.verify_seed_native(seed)
    diagnostic = run.build_revision_diagnostics(seed)
    inputs, profile = run.read(run.PREFLIGHT_PARENT / "INPUTS.json"), run.read(run.PROFILE)
    preview = run.workflow.prepare_goal_request(run.revision_planning_inputs(inputs, seed, diagnostic), profile)
    binding = {"schema": run.VERSION + "/derived_authorization_binding",
        "created_at": run.now(), "human_authorized": True, "user_quote": authority["user_quote"],
        "authority_source": str(run.previous.APPROVAL), "authority_source_sha256": run.sha_file(run.previous.APPROVAL),
        "parent_root": str(run.PREFLIGHT_PARENT),
        "parent_ledger_sha256": run.sha_file(run.PREFLIGHT_PARENT / "CALL_LEDGER.json"),
        **run.authorization_request_identity(diagnostic, preview),
        "parent_goal_candidates_used": 24, "parent_whole_plan_maximum": 24,
        "parent_whole_plan_unused_capacity": 0, "parent_unused_capacity_stays_in_closed_run": True,
        "old_ledger_reset": False,
        "parent_script_submissions": 2, "parent_setup_submissions": 1,
        "seed_native_identity": identity, "media_authorized": False, "publish_authorized": False,
        "automatic_transport_retry": False, "writer_total_call_user_limit": None,
        "purpose": "Use up to two complete native planning revisions under existing unlimited text authority, then native setup/body/same-source review; no old allowance reset, no director/media. Complete C/G legal usage and compact same-source full semantic/physical review; first request revises complete original594 with exact qualified source leak/601 truncation evidence, no local native patch or adopting old review; parent601 remains closed"}
    # Recover only local immutable preparation, never a provider or run claim.
    if run.APPROVAL.exists():
        existing = run.read(run.APPROVAL)
        binding["created_at"] = existing.get("created_at")
        if binding != existing or not binding["created_at"]:
            raise ValueError("existing text authorization differs; never replace or regrant")
    run.write(run.PROJECT / "data/qa/creative_legal_usage_20261014/LEGAL_USAGE_REQUEST_PREVIEW_v1.json",
        {"seed_native_identity": identity, "prepared": preview, "provider_calls": 0,
         "creative_quality_approved": False, "old_review_not_converted": True}, True)
    run.write(run.APPROVAL, binding, True)
    print("Existing text authority bound and actual new planning preview saved; zero provider calls.")


if __name__ == "__main__":
    main()
