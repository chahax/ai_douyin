"""Bind existing continuous text authority to a new native pragmatic repair run."""
from pathlib import Path
import sys

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from scripts import run_goal_context_text_production_v19 as run


def build_binding():
    if run.CLAIM.exists() or run.ROOT.exists():
        raise RuntimeError("existing grant/root cannot be reclaimed or restarted")
    run.prior_guard()
    authority=run.read(run.previous.APPROVAL)
    if authority.get("human_authorized") is not True or authority.get("user_quote")!="minimax随便追加":
        raise ValueError("original continuing text authority required")
    inputs=run.read(run.PREFLIGHT_PARENT/"INPUTS.json")
    run.verify_inherited_direction_inputs(inputs)
    seed=run.read(run.PREFLIGHT_PARENT/"goals/native_01.json")
    identity=run.verify_seed_native(seed)
    diagnostic=run.build_revision_diagnostics(seed)
    prepared=run.workflow.prepare_goal_request(run.revision_planning_inputs(inputs,seed,diagnostic),run.read(run.PROFILE))
    binding={"schema":run.VERSION+"/derived_authorization_binding","created_at":run.now(),
        "human_authorized":True,"user_quote":authority["user_quote"],
        "authority_source":str(run.previous.APPROVAL),"authority_source_sha256":run.sha_file(run.previous.APPROVAL),
        "parent_root":str(run.PREFLIGHT_PARENT),"parent_ledger_sha256":run.sha_file(run.PREFLIGHT_PARENT/"CALL_LEDGER.json"),
        "parent_state_sha256":run.sha_file(run.PARENT_STATE),**run.authorization_request_identity(diagnostic,prepared),
        "parent_goal_candidates_used":25,"parent_whole_plan_maximum":26,"parent_whole_plan_unused_capacity":1,
        "parent_unused_capacity_stays_in_closed_run":True,"new_local_bound_from_existing_authority":2,
        "new_cumulative_goal_candidates_maximum":27,"old_ledger_reset":False,
        "parent_script_submissions":0,"parent_setup_submissions":0,"seed_native_identity":identity,
        "input_supplement_authorization_sha256":run.sha_file(run.INPUT_SUPPLEMENT_AUTHORIZATION),
        "human_direction_confirmation_sha256":run.sha_file(run.USER_DIRECTION_CONFIRMATION),
        "media_authorized":False,"publish_authorized":False,"automatic_transport_retry":False,
        "writer_total_call_user_limit":None,
        "purpose":"Two new complete602 planning revisions under continuous text authority, source v2 speech-act/legal assertions followed by focused/drama, native setup/body and same-source full reviews. Old closed max26 unused1 is not reused; new25+2=max27. Original603 report is rejected, not locally patched or converted; pending602 content risks require new source/drama decisions, and original594/595/601 evidence remains unchanged. No media or old request retries."}
    if run.APPROVAL.exists():
        existing=run.read(run.APPROVAL);binding["created_at"]=existing.get("created_at")
        if not binding["created_at"] or binding!=existing:
            raise ValueError("existing local authorization differs; no replacement or regrant")
    return binding,prepared


def main():
    binding,prepared=build_binding()
    run.write(run.REQUEST_PREVIEW,{"prepared":prepared,"seed_native_identity":binding["seed_native_identity"],
        "provider_calls":0,"media_calls":0,"creative_quality_approved":False,
        "old_source603_not_converted":True,"pending_content_risks_not_native_judgments":True},True)
    run.write(run.APPROVAL,binding,True)
    print(str(run.REQUEST_PREVIEW))


if __name__=="__main__":main()
