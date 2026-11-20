"""Bind existing explicit text authority to a new independent repaired run."""
from scripts import run_goal_context_text_production_v13 as run


def main():
    run.prior_guard()
    authority = run.read(run.previous.APPROVAL)
    if authority.get("user_quote") != "minimax随便追加" or authority.get("human_authorized") is not True:
        raise ValueError("existing explicit human text authorization required")
    terminal = run.read(run.TERMINAL_CERT)
    if terminal["schema"] != "known_local_repair_build_stop/v1":
        raise ValueError("completed original parent run required; do not restart its claim")
    if (terminal["parent_spend"]["effective_calls_started"], terminal["parent_spend"]["effective_reported_tokens"],
            terminal["inherited_goal_candidates_used"]) != (570, 11068061, 16):
        raise ValueError("parent cumulative spend/candidate evidence differs")
    row = next(row for row in run.read(run.PREFLIGHT_PARENT / "CALL_LEDGER.json")["calls"] if row["ordinal"] == 568)
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
        "parent_goal_candidates_used": 16, "old_ledger_reset": False,
        "parent_script_submissions": 0, "parent_setup_submissions": 0,
        "seed_native_identity": identity, "media_authorized": False, "publish_authorized": False,
        "automatic_transport_retry": False, "writer_total_call_user_limit": None,
        "purpose": "Use the remaining one whole planning revision with typed audit scope evidence and bounded feedback projection, then same-source native setup/body/full review; no old capacity reset"}
    # Recover only local immutable preparation, never a provider or run claim.
    if run.APPROVAL.exists():
        existing = run.read(run.APPROVAL)
        binding["created_at"] = existing.get("created_at")
        if binding != existing or not binding["created_at"]:
            raise ValueError("existing text authorization differs; never replace or regrant")
    run.write(run.PROJECT / "data/qa/creative_review_feedback_20261014/REVIEW_FEEDBACK_REQUEST_PREVIEW_v1.json",
        {"seed_native_identity": identity, "prepared": preview, "provider_calls": 0,
         "creative_quality_approved": False, "old_review_not_converted": True}, True)
    run.write(run.APPROVAL, binding, True)
    print("Existing text authority bound and actual new planning preview saved; zero provider calls.")


if __name__ == "__main__":
    main()
