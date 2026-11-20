"""Bind existing explicit text authority to a new independent repaired run."""
from scripts import run_goal_context_text_production_v16 as run


def main():
    run.prior_guard()
    authority = run.read(run.previous.APPROVAL)
    if authority.get("user_quote") != "minimax随便追加" or authority.get("human_authorized") is not True:
        raise ValueError("existing explicit human text authorization required")
    terminal = run.read(run.PARENT_STATE)
    if (terminal["status"] != "halt_goal_content_capacity_exhausted"
            or (terminal["spend"]["effective_calls_started"],terminal["spend"]["effective_reported_tokens"],
                terminal["cumulative_goal_candidates_used"]) != (584,11463121,21)):
        raise ValueError("known closed parent terminal state required; never restart584 claim")
    row = next(row for row in run.read(run.PREFLIGHT_PARENT / "CALL_LEDGER.json")["calls"] if row["ordinal"] == 582)
    seed = run.read(run.PREFLIGHT_PARENT / row["receipt"])["output"]
    identity = run.verify_seed_native(seed)
    diagnostic = run.build_revision_diagnostics(seed)
    inputs, profile = run.read(run.PREFLIGHT_PARENT / "INPUTS.json"), run.read(run.PROFILE)
    preview = run.workflow.prepare_goal_request(run.fresh_planning_inputs(inputs, diagnostic), profile)
    binding = {"schema": run.VERSION + "/derived_authorization_binding",
        "created_at": run.now(), "human_authorized": True, "user_quote": authority["user_quote"],
        "authority_source": str(run.previous.APPROVAL), "authority_source_sha256": run.sha_file(run.previous.APPROVAL),
        "parent_root": str(run.PREFLIGHT_PARENT),
        "parent_ledger_sha256": run.sha_file(run.PREFLIGHT_PARENT / "CALL_LEDGER.json"),
        **run.authorization_request_identity(diagnostic, preview),
        "parent_goal_candidates_used": 21, "old_ledger_reset": False,
        "parent_script_submissions": 0, "parent_setup_submissions": 0,
        "seed_native_identity": identity, "media_authorized": False, "publish_authorized": False,
        "automatic_transport_retry": False, "writer_total_call_user_limit": None,
        "purpose": "Use up to two new whole reconceptions under existing unlimited text authority, then native setup/body/same-source review; no old allowance reset, no director/media. Focused requirement-scope and whole-goal comparison review, with per-dialogue schema candidates; fresh request sends causes, not old plan/body template"}
    # Recover only local immutable preparation, never a provider or run claim.
    if run.APPROVAL.exists():
        existing = run.read(run.APPROVAL)
        binding["created_at"] = existing.get("created_at")
        if binding != existing or not binding["created_at"]:
            raise ValueError("existing text authorization differs; never replace or regrant")
    run.write(run.PROJECT / "data/qa/creative_commitment_scope_20261014/COMMITMENT_SCOPE_REQUEST_PREVIEW_v1.json",
        {"seed_native_identity": identity, "prepared": preview, "provider_calls": 0,
         "creative_quality_approved": False, "old_review_not_converted": True}, True)
    run.write(run.APPROVAL, binding, True)
    print("Existing text authority bound and actual new planning preview saved; zero provider calls.")


if __name__ == "__main__":
    main()
