"""Bind an explicit human direction supplement; no provider or production claim."""
from copy import deepcopy
from pathlib import Path
import sys

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from scripts import run_goal_context_text_production_v18 as run


def build_supplement():
    if run.ROOT.exists() or run.CLAIM.exists():
        raise RuntimeError("existing production root/claim; do not replace inputs or regrant")
    run.prior_guard()
    approval=run.read(run.APPROVAL)
    inputs=run.read(run.PREFLIGHT_PARENT/"INPUTS.json")
    seed=run.read(run.PREFLIGHT_PARENT/"goals/native_02.json")
    identity=run.verify_seed_native(seed)
    diagnostic=run.build_revision_diagnostics(seed)
    profile=run.read(run.PROFILE)
    original=run.workflow.prepare_goal_request(run.revision_planning_inputs(inputs,seed,diagnostic),profile)
    preview_v1=run.PROJECT/"data/qa/creative_legal_usage_20261014/LEGAL_USAGE_REQUEST_PREVIEW_v1.json"
    if (approval.get("human_authorized") is not True or approval.get("user_quote")!="minimax随便追加"
            or approval.get("parent_root")!=str(run.PREFLIGHT_PARENT)
            or approval.get("parent_ledger_sha256")!=run.sha_file(run.PREFLIGHT_PARENT/"CALL_LEDGER.json")
            or any(approval.get(key)!=value for key,value in run.authorization_request_identity(diagnostic,original).items())
            or run.read(preview_v1).get("prepared")!=original):
        raise ValueError("original authorization or preview identity changed; not a replacement grant")
    confirmation=run.read(run.USER_DIRECTION_CONFIRMATION)
    supplemented=run.build_direction_supplemented_inputs(inputs,confirmation)
    prepared=run.workflow.prepare_goal_request(run.revision_planning_inputs(supplemented,seed,diagnostic),profile)
    binding={"schema":run.VERSION+"/user_direction_input_supplement","created_at":run.now(),
        **run.input_supplement_identity(supplemented,prepared),
        "original_preview_sha256":run.sha_file(preview_v1),
        "parent_root":str(run.PREFLIGHT_PARENT),"parent_ledger_sha256":run.sha_file(run.PREFLIGHT_PARENT/"CALL_LEDGER.json"),
        "model_profile_sha256":run.sha_file(run.PROFILE),"derived_revision_diagnostics_sha256":run.digest(diagnostic),
        "appended_user_ids":["UC_CONFIRMED_SUPERMARKET_DIRECTION","UG_INTENSIFIED_EMOTIONAL_EXCHANGE"],
        "append_only_user_rows":True,"original_law_collection_reference_and_user_rows_unchanged":True,
        "confirmation_user_quote":confirmation["user_quote"],"confirmation_is_direction_not_manuscript_adoption":True,
        "existing_text_authority_only":True,"old_ledger_reset":False,"media_authorized":False,"publish_authorized":False,
        "automatic_transport_retry":False,"seed_native_identity":identity}
    if run.INPUT_SUPPLEMENT_AUTHORIZATION.exists():
        old=run.read(run.INPUT_SUPPLEMENT_AUTHORIZATION)
        binding["created_at"]=old.get("created_at")
        if not binding["created_at"] or old!=binding:
            raise ValueError("existing input supplement differs; never replace authorization or regrant")
    return supplemented,prepared,binding


def main():
    inputs,prepared,binding=build_supplement()
    run.write(run.SUPPLEMENTED_INPUTS,inputs,True)
    run.write(run.SUPPLEMENTED_PREVIEW,{"prepared":prepared,"input_supplement_binding":deepcopy(binding),
        "provider_calls":0,"media_calls":0,"creative_quality_approved":False,"old_preview_preserved":True},True)
    run.write(run.INPUT_SUPPLEMENT_AUTHORIZATION,binding,True)
    print(str(run.SUPPLEMENTED_PREVIEW))


if __name__=="__main__":
    main()
