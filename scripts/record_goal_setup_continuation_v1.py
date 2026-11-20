"""Bind current broad MiniMax text authorization; never dispatch or reset spend."""
from scripts import run_goal_context_text_production_v7 as run


def main():
    authority = run.read(run.previous.APPROVAL)
    if authority.get("user_quote") != "minimax随便追加" or authority.get("human_authorized") is not True:
        raise ValueError("existing explicit human text authorization required")
    terminal = run.read(run.PREFLIGHT_PARENT / "STATE.json")
    if terminal["status"] != "halt_goal_content_capacity_exhausted":
        raise ValueError("completed original parent run required, never restart its claim")
    if (terminal["spend"]["effective_calls_started"], terminal["spend"]["effective_reported_tokens"],
            terminal["cumulative_goal_candidates_used"]) != (540, 10308368, 8):
        raise ValueError("parent cumulative spend/candidate evidence differs")
    row = [row for row in run.read(run.PREFLIGHT_PARENT / "CALL_LEDGER.json")["calls"] if row["ordinal"] == 540][0]
    seed = run.read(run.PREFLIGHT_PARENT / row["receipt"])["output"]
    identity = run.verify_seed_native(seed)
    run.write(run.APPROVAL, {"schema": run.VERSION + "/derived_authorization_binding",
        "created_at": run.now(), "human_authorized": True, "user_quote": authority["user_quote"],
        "authority_source": str(run.previous.APPROVAL), "authority_source_sha256": run.sha_file(run.previous.APPROVAL),
        "parent_root": str(run.PREFLIGHT_PARENT),
        "parent_ledger_sha256": run.sha_file(run.PREFLIGHT_PARENT / "CALL_LEDGER.json"),
        "parent_goal_candidates_used": 8, "old_ledger_reset": False,
        "seed_native_identity": identity, "media_authorized": False, "publish_authorized": False,
        "automatic_transport_retry": False, "writer_total_call_user_limit": None,
        "purpose": "new static whole-plan and separate native opening setup, then complete screenplay and full review"}, True)
    inputs, profile = run.read(run.PREFLIGHT_PARENT / "INPUTS.json"), run.read(run.PROFILE)
    revision = {"native_goal_ordinal": 540, "known_complete_failure": run.diagnosis(run.read(run.PREFLIGHT_PARENT / row["receipt"])),
        "workflow_change": "New whole-plan v4 uses static prop inventory only; opening physical states are generated independently after accepted source/drama audits.",
        "content_requirements": run.read(run.PREFLIGHT_PARENT / "INHERITED_DIAGNOSTICS.json")}
    preview = run.workflow.prepare_goal_request({**inputs, "previous_complete_document": seed,
        "revision_diagnostics": revision}, profile)
    run.write(run.PROJECT / "data/qa/goal_context_production_repair_20261013/PLAN_SETUP_REQUEST_PREVIEW_v1.json",
        {"seed_native_identity": identity, "prepared": preview, "provider_calls": 0,
         "creative_quality_approved": False, "next_setup_request_requires_accepted_new_native_goal": True}, True)
    print("Derived authorization and static-plan request preview saved; zero model calls.")


if __name__ == "__main__":
    main()
