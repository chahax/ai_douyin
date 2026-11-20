"""Bind existing explicit text authority to a new independent repaired run."""
from scripts import run_goal_context_text_production_v9 as run


def main():
    authority = run.read(run.previous.APPROVAL)
    if authority.get("user_quote") != "minimax随便追加" or authority.get("human_authorized") is not True:
        raise ValueError("existing explicit human text authorization required")
    terminal = run.read(run.PREFLIGHT_PARENT / "STATE.json")
    if terminal["status"] != "halt_full_review_contract_requires_pipeline_diagnosis":
        raise ValueError("completed original parent run required; do not restart its claim")
    if (terminal["spend"]["effective_calls_started"], terminal["spend"]["effective_reported_tokens"],
            terminal["cumulative_goal_candidates_used"]) != (552, 10626112, 10):
        raise ValueError("parent cumulative spend/candidate evidence differs")
    row = next(row for row in run.read(run.PREFLIGHT_PARENT / "CALL_LEDGER.json")["calls"] if row["ordinal"] == 547)
    seed = run.read(run.PREFLIGHT_PARENT / row["receipt"])["output"]
    identity = run.verify_seed_native(seed)
    diagnostic = run.build_revision_diagnostics(seed)
    run.write(run.APPROVAL, {"schema": run.VERSION + "/derived_authorization_binding",
        "created_at": run.now(), "human_authorized": True, "user_quote": authority["user_quote"],
        "authority_source": str(run.previous.APPROVAL), "authority_source_sha256": run.sha_file(run.previous.APPROVAL),
        "parent_root": str(run.PREFLIGHT_PARENT),
        "parent_ledger_sha256": run.sha_file(run.PREFLIGHT_PARENT / "CALL_LEDGER.json"),
        "parent_goal_candidates_used": 10, "old_ledger_reset": False,
        "parent_script_submissions": 1, "parent_setup_submissions": 1,
        "seed_native_identity": identity, "media_authorized": False, "publish_authorized": False,
        "automatic_transport_retry": False, "writer_total_call_user_limit": None,
        "purpose": "fresh complete native plan and typed opening setup, then whole screenplay and separate same-source semantic/physical review"}, True)
    inputs, profile = run.read(run.PREFLIGHT_PARENT / "INPUTS.json"), run.read(run.PROFILE)
    preview = run.workflow.prepare_goal_request(run.fresh_planning_inputs(inputs, diagnostic), profile)
    run.write(run.PROJECT / "data/qa/goal_context_production_repair_20261013/SPLIT_FULL_REVIEW_REQUEST_PREVIEW_v1.json",
        {"seed_native_identity": identity, "prepared": preview, "provider_calls": 0,
         "creative_quality_approved": False, "old_review_not_converted": True}, True)
    print("Existing text authority bound and actual new planning preview saved; zero provider calls.")


if __name__ == "__main__":
    main()
