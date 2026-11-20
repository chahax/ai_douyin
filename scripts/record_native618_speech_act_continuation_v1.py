"""Preview, or explicitly register, a derived source6 native618 text binding.

Preview writes QA only. Neither command creates a production claim or calls a
provider. `prepare` is a distinct producer command and remains single-use.
"""
import argparse
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from scripts import run_goal_context_text_production_v27 as run


def build_binding():
    if run.ROOT.exists() or run.CLAIM.exists():
        raise RuntimeError("existing production root/claim cannot be regranted")
    run.prior_guard()
    authority = run.read(run.previous.APPROVAL)
    if authority.get("human_authorized") is not True or authority.get("user_quote")!="minimax随便追加":
        raise ValueError("continuing user text authority required")
    inputs = run.read(run.PREFLIGHT_PARENT/"INPUTS.json")
    seed = run.read(run.PREFLIGHT_PARENT/"goals/native_01.json")
    identity = run.verify_seed_native(seed)
    prepared = run.prepare_source_audit(inputs,run.read(run.PROFILE),seed)
    binding = {"schema":run.VERSION+"/derived_authorization_binding", "created_at":run.now(),
        "human_authorized":True,"user_quote":authority["user_quote"],
        "authority_source":str(run.previous.APPROVAL),"authority_source_sha256":run.sha_file(run.previous.APPROVAL),
        "parent_root":str(run.PREFLIGHT_PARENT),"parent_ledger_sha256":run.sha_file(run.PREFLIGHT_PARENT/"CALL_LEDGER.json"),
        "parent_state_sha256":run.sha_file(run.PARENT_STATE),"seed_native_identity":identity,
        **run.authorization_request_identity(prepared),
        "whole_plan_candidates_authorized":0,"inherited_goal_candidates_used":29,
        "stage_limits":run.STAGE_LIMITS,"source619_locally_converted":False,
        "first_action_is_native618_source_readmission":True,"source_interface_or_semantic_failure_stops":True,
        "new_format_or_report_recovery_claimed":False,"old_ledger_reset":False,
        "automatic_transport_retry":False,"media_authorized":False,"publish_authorized":False,
        "writer_total_call_user_limit":None,
        "purpose":"Reuse exact complete native618; first source6, then same-source commitment/drama, setup2, body3 and split full reviews6. No new whole plan, old619 conversion, report recovery, video or publication. Inherit619/12930923/617 known, unknown70/160 and93117 reservation, old director7/7. An active counted repair round is required before each real provider dispatch."}
    run.verify_authorization(binding,prepared,identity)
    return binding,prepared


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("preview","register"))
    args=parser.parse_args(argv)
    binding,prepared=build_binding()
    preview={"prepared":prepared,"seed_native_identity":binding["seed_native_identity"],
        "provider_calls":0,"media_calls":0,"creative_quality_approved":False,"source619_locally_converted":False}
    if run.REQUEST_PREVIEW.exists():
        if run.read(run.REQUEST_PREVIEW)!=preview:raise ValueError("saved preview differs; do not overwrite")
    else:run.write(run.REQUEST_PREVIEW,preview,True)
    if args.command=="register":run.write(run.APPROVAL,binding,True)
    print(str(run.REQUEST_PREVIEW),flush=True)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
