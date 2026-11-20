"""Bind existing explicit text authority to a new independent repaired run."""
from scripts import run_goal_context_text_production_v10 as run


def main():
    authority = run.read(run.previous.APPROVAL)
    if authority.get("user_quote") != "minimax随便追加" or authority.get("human_authorized") is not True:
        raise ValueError("existing explicit human text authorization required")
    terminal = run.read(run.PREFLIGHT_PARENT / "STATE.json")
    if terminal["status"] != "halt_goal_audit_contract_requires_pipeline_diagnosis":
        raise ValueError("completed original parent run required; do not restart its claim")
    if (terminal["spend"]["effective_calls_started"], terminal["spend"]["effective_reported_tokens"],
            terminal["cumulative_goal_candidates_used"]) != (556, 10706510, 12):
        raise ValueError("parent cumulative spend/candidate evidence differs")
    row = next(row for row in run.read(run.PREFLIGHT_PARENT / "CALL_LEDGER.json")["calls"] if row["ordinal"] == 554)
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
        "parent_goal_candidates_used": 12, "old_ledger_reset": False,
        "parent_script_submissions": 0, "parent_setup_submissions": 0,
        "seed_native_identity": identity, "media_authorized": False, "publish_authorized": False,
        "automatic_transport_retry": False, "writer_total_call_user_limit": None,
        "purpose": "complete native554 revision and new source/drama audit, then typed opening setup, whole screenplay and separate same-source semantic/physical review"}
    # Recover only local immutable preparation, never a provider or run claim.
    if run.APPROVAL.exists():
        existing = run.read(run.APPROVAL)
        binding["created_at"] = existing.get("created_at")
        if binding != existing or not binding["created_at"]:
            raise ValueError("existing text authorization differs; never replace or regrant")
    run.write(run.PROJECT / "data/qa/goal_context_production_repair_20261013/DRAMA_REFERENCE_SCOPE_REQUEST_PREVIEW_v1.json",
        {"seed_native_identity": identity, "prepared": preview, "provider_calls": 0,
         "creative_quality_approved": False, "old_review_not_converted": True}, True)
    run.write(run.APPROVAL, binding, True)
    print("Existing text authority bound and actual new planning preview saved; zero provider calls.")


if __name__ == "__main__":
    main()
