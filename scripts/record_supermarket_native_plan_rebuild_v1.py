"""Bind continuous text authority to independent complete native supermarket plan rebuild."""
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import run_goal_context_text_production_v23 as run


def build_binding():
    if run.CLAIM.exists() or run.ROOT.exists():
        raise RuntimeError("existing root or claim cannot be reclaimed")
    run.prior_guard()
    authority = run.read(run.previous.APPROVAL)
    if authority.get("human_authorized") is not True or authority.get("user_quote") != "minimax随便追加":
        raise ValueError("original continuous text authority required")
    inputs = run.read(run.PREFLIGHT_PARENT / "INPUTS.json")
    run.verify_inherited_direction_inputs(inputs)
    seed = run.read(run.PREFLIGHT_PARENT / "INHERITED_NATIVE_GOAL.json")
    identity = run.verify_seed_native(seed)
    diagnostic = run.build_revision_diagnostics(seed)
    prepared = run.prepare_first_goal_request(inputs, run.read(run.PROFILE), seed, diagnostic)
    binding = {"schema": run.VERSION + "/derived_authorization_binding", "created_at": run.now(),
        "human_authorized": True, "user_quote": authority["user_quote"],
        "authority_source": str(run.previous.APPROVAL), "authority_source_sha256": run.sha_file(run.previous.APPROVAL),
        "parent_root": str(run.PREFLIGHT_PARENT), "parent_ledger_sha256": run.sha_file(run.PREFLIGHT_PARENT / "CALL_LEDGER.json"),
        "parent_state_sha256": run.sha_file(run.PARENT_STATE), **run.authorization_request_identity(diagnostic, prepared),
        "parent_goal_candidates_used": 26, "parent_whole_plan_maximum": 28, "parent_whole_plan_unused_capacity": 2,
        "parent_unused_capacity_stays_in_closed_run": True, "new_local_bound_from_existing_authority": 2,
        "new_cumulative_goal_candidates_maximum": 28, "old_ledger_reset": False,
        "first_action_is_source_audit":False,"first_action_is_native_plan_rebuild":True,
        "old_report_revision_claim_reopened":False,"source_only_strict_protocol":True,
        "known_complete_source_fail_allows_bounded_native_goal_revision": True,
        "source_interface_unknown_or_protocol_failure_stops_new_run":True,
        "known_native_goal_audit_content_uncertainty_allows_bounded_plan_revision":True,
        "body_requires_all_three_audits_accepted_without_uncertainty":True,
        "parent_script_submissions": 0, "parent_setup_submissions": 0, "seed_native_identity": identity,
        "input_supplement_authorization_sha256": run.sha_file(run.INPUT_SUPPLEMENT_AUTHORIZATION),
        "human_direction_confirmation_sha256": run.sha_file(run.USER_DIRECTION_CONFIRMATION),
        "media_authorized": False, "publish_authorized": False, "automatic_transport_retry": False,
        "writer_total_call_user_limit": None,
        "purpose": "First MiniMax complete native plan27 using entire original604, original human/source input and full R01, exact608 schema errors and bound pending rebuild QA. At most two new whole native plans27/28 and six total goal audits; valid native content failure or uncertainty permits bounded whole-plan revision, interface/usage unknown stops. Only three accepted uncertainty-free current-plan audits permit native setup/body and full same-source double review. Preserve all prior consumption, closed report-revision claim and unused capacity; no media or publication."}

    return binding, prepared


def main():
    binding, prepared = build_binding()
    run.write(run.REQUEST_PREVIEW, {"prepared": prepared, "seed_native_identity": binding["seed_native_identity"],
        "provider_calls": 0, "media_calls": 0, "creative_quality_approved": False,
        "old_source608_not_converted": True, "pending_content_risks_not_native_judgments": True}, True)
    run.write(run.APPROVAL, binding, True)
    print(str(run.REQUEST_PREVIEW))


if __name__ == "__main__":
    main()
