"""Bind existing human text authority to an unchanged spent parent; no calls."""
from scripts import run_goal_context_text_production_v5 as run


def main():
    authority = run.read(run.previous.APPROVAL)
    assert authority["user_quote"] == "minimax随便追加" and authority["human_authorized"]
    run.prior_guard()
    seed = run.read(run.PREFLIGHT_PARENT / "goals/native_03.json")
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
    preview = run.workflow.prepare_goal_audit_request(inputs, profile, seed)
    run.write(run.PROJECT / "data/qa/goal_context_production_repair_20261013/GOAL_AUDIT_CITATION_PREVIEW_v2.json",
        {"seed_native_identity": identity, "prepared": preview,
         "production_calls": 0, "creative_quality_approved": False}, True)
    print("Derived existing authorization and exact request preview saved; zero provider calls.")


if __name__ == "__main__":
    main()
