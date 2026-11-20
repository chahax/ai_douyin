"""Bind existing human text authority to an unchanged spent parent; no calls."""
from scripts import run_goal_context_text_production_v6 as run


def main():
    authority = run.read(run.previous.APPROVAL)
    assert authority["user_quote"] == "minimax随便追加" and authority["human_authorized"]
    run.prior_guard()
    seed = run.read(run.PREFLIGHT_PARENT / "INHERITED_NATIVE_GOAL.json")
    identity = run.verify_seed_native(seed)
    run.write(run.APPROVAL, {"schema": run.VERSION + "/derived_authorization_binding",
        "created_at": run.now(), "human_authorized": True, "user_quote": authority["user_quote"],
        "authority_source": str(run.previous.APPROVAL), "authority_source_sha256": run.sha_file(run.previous.APPROVAL),
        "parent_root": str(run.PREFLIGHT_PARENT),
        "parent_ledger_sha256": run.sha_file(run.PREFLIGHT_PARENT / "CALL_LEDGER.json"),
        "parent_goal_candidates_used": 6, "old_ledger_reset": False,
        "seed_native_identity": identity, "media_authorized": False, "publish_authorized": False,
        "automatic_transport_retry": False, "writer_total_call_user_limit": None,
        "purpose": "new source-bound audit of unchanged native536, then whole-script production and full review"}, True)
    inputs, profile = run.read(run.PREFLIGHT_PARENT / "INPUTS.json"), run.read(run.PROFILE)
    preview = {"source": run.workflow.prepare_goal_source_audit_request(inputs, profile, seed),
        "drama": run.workflow.prepare_goal_drama_audit_request(inputs, profile, seed),
        "new_goal_revision": run.workflow.prepare_goal_request({**inputs,
            "previous_complete_document": seed, "revision_diagnostics": run.read(run.DIAGNOSTICS)}, profile)}
    run.write(run.PROJECT / "data/qa/goal_context_production_repair_20261013/GOAL_SPLIT_AUDIT_PREVIEW_v1.json",
        {"seed_native_identity": identity, "prepared": preview,
         "production_calls": 0, "creative_quality_approved": False}, True)
    print("Derived existing authorization and exact request preview saved; zero provider calls.")


if __name__ == "__main__":
    main()
