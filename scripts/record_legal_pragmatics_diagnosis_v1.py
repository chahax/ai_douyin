"""Record complete603 relation conflicts and pending602 risks; zero providers."""
from copy import deepcopy
from pathlib import Path
import sys

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))


def build_diagnosis(root=None):
    from scripts import run_goal_context_text_production_v19 as run
    root=Path(root) if root is not None else run.PREFLIGHT_PARENT
    ledger,terminal,scope=(run.read(root/name) for name in ("CALL_LEDGER.json","STATE.json","USER_SCOPE.json"))
    if ([r["ordinal"] for r in ledger["calls"]]!=[602,603]
            or terminal.get("status")!="halt_goal_audit_contract_requires_pipeline_diagnosis"
            or terminal.get("receipt_ordinal")!=603 or terminal.get("audit_kind")!="source"
            or terminal.get("cumulative_goal_candidates_used")!=25 or terminal.get("opening_setup_calls")!=0
            or scope.get("cumulative_goal_candidates_this_run_maximum")!=26
            or (terminal["spend"]["effective_calls_started"],terminal["spend"]["effective_reported_tokens"],
                terminal["spend"]["effective_calls_with_known_usage"])!=(603,12073493,601)):
        raise ValueError("exact602/603 closed terminal and used25/max26/unused1 required")
    paths=set();receipts={}
    for row in ledger["calls"]:
        path=root/row["receipt"];receipt=run.read(path)
        if run.sha_file(path)!=row["receipt_sha256"] or not run.repairable(receipt):
            raise ValueError("original complete602/603 response changed")
        expected="contract_valid" if row["ordinal"]==602 else "contract_rejected"
        if receipt.get("status")!=expected:raise ValueError("original contract results changed")
        receipts[row["ordinal"]]=receipt;paths.add(path)
    native=receipts[602]["output"];audit=receipts[603]["output"]
    if run.read(root/"goals/native_01.json")!=native:
        raise ValueError("exact602 native source required")
    if (receipts[603].get("validation") is not None
            or receipts[603].get("failure",{}).get("code")!="MODULE_SCHEMA_INVALID"
            or audit.get("goal_sha256")!=run.digest(native)):
        raise ValueError("603 remains rejected original source report, never a valid review")
    request=run.read(root/"requests/goal_source_audit_01.json")
    if request["request"]!=receipts[603]["request"]:
        raise ValueError("603 original prepared request changed")
    context=run.control.strict_json(request["request"]["messages"][1]["content"])
    if (request["source_authority_context"]!={key:context[key] for key in ("verified_legal_context","origin_catalog")}
            or audit.get("audit_context_sha256")!=run.digest(context)
            or audit.get("authority_context_sha256")!=run.digest(request["source_authority_context"])):
        raise ValueError("603 original goal/source/user authority context identity required")
    catalog=run.drama_contract.build_evidence_catalog(native)
    if set(audit["legal_usage_scan"])!=set(catalog):raise ValueError("603 original complete C/G directory changed")
    conflicts=[]
    for ref,rows in audit["legal_usage_scan"].items():
        for index,row in enumerate(rows):
            if row["quote"] not in catalog[ref]["quote"]:raise ValueError("original603 exact own-source quote changed")
            if (row["basis_relation"],row["portrayal"],row["status"])==("not_covered","open_or_question","pass"):
                conflicts.append({"source_ref":ref,"usage_index":index,"native_row":deepcopy(row),
                    "source_evidence":deepcopy(catalog[ref])})
    if len(conflicts)!=20:raise ValueError("exact20 original relation/status conflicts required")
    examples={key:next(c for c in conflicts if c["source_ref"]==key) for key in ("G007","G022","G030")}
    if "不构成法律命题" not in examples["G022"]["native_row"]["reason"]:
        raise ValueError("original603 non-legal speech-act diagnosis witness changed")
    if "未纠正" not in examples["G030"]["native_row"]["reason"]:
        raise ValueError("original603 notebook uncorrected judgment witness changed")
    for ordinal in (602,603):
        for name in ("IDENTITY.json","request_body.raw","REQUEST_BODY_MANIFEST.json","response_body.raw","RESPONSE_BODY_MANIFEST.json"):
            path=root/f"call_evidence/call_{ordinal}"/name;paths.add(path)
        raw=run.read(root/f"call_evidence/call_{ordinal}/RESPONSE_BODY_MANIFEST.json")
        if (raw.get("stored_sha256")!=run.sha_file(root/f"call_evidence/call_{ordinal}/response_body.raw")
                or raw.get("stored_sha256")!=raw.get("original_sha256") or raw.get("body_complete") is not True
                or run.control.strict_json((root/f"call_evidence/call_{ordinal}/response_body.raw").read_text("utf8"))!=receipts[ordinal]["response_payload"]):
            raise ValueError("original complete HTTP response bytes changed")
    for name in ("STATE.json","CALL_LEDGER.json","USER_SCOPE.json","RUN_CLAIM.json","PRODUCTION_FREEZE.json",
            "INPUTS.json","USER_DIRECTION_INPUT_SUPPLEMENT.json","goals/native_01.json",
            "requests/goal_plan_25.json","requests/goal_source_audit_01.json"):
        paths.add(root/name)
    old_path=run.previous.CONTENT_DIAGNOSIS
    old=run.read(old_path)
    for absolute,expected_sha in old["source_file_sha256"].items():
        if run.sha_file(absolute)!=expected_sha:raise ValueError("historical594/595/601 evidence changed")
        paths.add(Path(absolute))
    paths.update((old_path,run.USER_DIRECTION_CONFIRMATION,run.INPUT_SUPPLEMENT_AUTHORIZATION,
        run.SUPPLEMENTED_INPUTS,run.SUPPLEMENTED_PREVIEW))
    independent_path=run.PROJECT/"data/qa/creative_legal_usage_20261014/ACTUAL602_WIRE_AND_INDEPENDENT_READING_v1.json"
    independent=run.read(independent_path)
    if (independent.get("complete602_receipt",{}).get("native_goal_sha256")!=run.digest(native)
            or independent.get("complete602_receipt",{}).get("native_goal_modified") is not False):
        raise ValueError("independent602 reading must bind unchanged exact native planning")
    for absolute,expected_sha in independent["source_files_before"].items():
        if run.sha_file(absolute)!=expected_sha:raise ValueError("independent actual602 reading source changed")
        paths.add(Path(absolute))
    paths.add(independent_path)
    old_failure=old["verified_failures"][0]
    return {"schema":"verified_legal_pragmatics_diagnosis/v2","source_root":str(root),
        "source_file_sha256":{str(p.resolve()):run.sha_file(p) for p in sorted(paths)},
        "native_goal_ordinal":602,"native_goal_sha256":run.digest(native),
        "native_source_audit_ordinal":603,"native_source_audit_sha256":run.digest(audit),
        "complete_original603_conflicts":deepcopy(conflicts),
        "verified_failures":[{"kind":"legal_relation_status_conflict_and_speech_act_conflation",
            "conflict_count":20,"source_refs":[r["source_ref"] for r in conflicts],
            "exact_examples":deepcopy(examples),"native_source_report_valid":False,
            "diagnosis":"Original603 has20 not_covered/open_or_question/pass rows rejected by source v1. G022's reason says this is not a legal proposition, while G030 says the notebook-value denial is uncorrected and not judged legally true. These are verified native relationship/status conflicts, not20 proven illegal plot lines. Source v2 must first distinguish contextual speech acts from asserted legal rules/applications and compile explicit native relations without a redundant usage.status; new native source/drama review must decide actual meaning."}],
        "pending_content_risks":[
            {"kind":"proposed_versus_agreed_termination","status":"pending_model_source_and_drama_review",
             "evidence":{k:deepcopy(catalog[k]) for k in ("C:CC6","C:CC9","G047","G071","G104","G106")},
             "risk":"She declines to sign or agree, but the proposed written result still says协商一致. It may conflate identifying the employer's proposal with an agreement already reached; the new full native plan and audits must distinguish these without changing law."},
            {"kind":"manager_risk_change_causal_trigger","status":"pending_model_drama_review",
             "evidence":{k:deepcopy(catalog[k]) for k in ("C:IF2","C:IF6","G039","G047","G071","G097","G103")},
             "risk":"The manager's transfer/compliance pressure is declared, but why that pressure makes him accept written responsibility rather than resist remains unclear. A new native revision must show a credible change in his risk calculation driven by their exchange, rather than treating a declared motive as performed causality."},
            {"kind":"unqualified_notebook_value_denial","status":"pending_model_source_and_drama_review",
             "evidence":{"G030":deepcopy(catalog["G030"]),"C:IF3":deepcopy(catalog["C:IF3"])},
             "risk":"G030 broadly says本子上写的不算数. It may be a self-interested character response or a misleading claim of legal/evidentiary worth; fiction classification alone does not decide it. New source/drama must evaluate actual narrative framing and any correction, not mechanically pass or demand law exposition."},
            {"kind":"cooler_sequence_and_folder_state_preconditions","status":"pending_model_drama_and_downstream_physical_review",
             "evidence":{k:deepcopy(catalog[k]) for k in ("G079","G083","G107","C:CC11","G111")},
             "risk":"G079 explicitly closes the cooler glass door before putting bins back inside, without establishing a valid intervening access state. G083/G107 place the folder back in the office while later physical use must have a legal support/access state. This is an independently observed sequence/precondition risk, not an adopted model fail judgment. New whole-plan/drama must remove already written sequence conflicts; opening and body then establish current support/access before physical review. Do not prescribe fixed gestures or require planning to fill every downstream hand detail."}],
        "prior_legal_fault_evidence":{"complete_prior_diagnosis_sha256":run.digest(old),
            "original594_cc6_vl2":{key:deepcopy(old_failure["exact_claims"][key]) for key in ("CC6","VL2")},
            "original594_G047":deepcopy(old_failure["beat_evidence"]["G047"]),
            "original595_cc6_judgment":deepcopy(old_failure["native_source_cc6_judgment"]),
            "original596_cc6_status":old_failure["native_focused_cc6_judgment"]["status"],
            "diagnosis":"Original594 article38 framing was exempted as fictional by claims-only595 and literally accepted by596; correct VL2/L002 authority remained present. Preserve this regression and its original qualified diagnosis; do not claim the line literally says no compensation. Prior601 is a known-usage length failure without an adopted review and its task remains PENDING."},
        "stage_ownership_direction":["Source owns origin provenance, speech-act classification and actual legal rules/application against authoritative conditions.",
            "Focused owns creative commitments and comparison scope, never legal truth by fiction type.",
            "Drama owns emotional exchange, credible strategy/risk changes, performed causality and production scope.",
            "Opening owns native positions/support; complete body and same-source semantic/physical reviews execute and judge performance."],
        "forwarding_boundary":{"original603_report_not_patched_or_adopted":True,
            "pending_risks_are_not_completed_native_judgments":True,"no_manual_native_patch":True,
            "full_original_receipts_retained":True,"new_complete_native_revision_required":True},
        "parent_spend":deepcopy(terminal["spend"]),"parent_goal_candidates_used":25,
        "parent_goal_candidates_maximum":26,"parent_unused_goal_candidates":1,
        "parent_unused_capacity_stays_in_closed_run":True,"parent_claim_not_restarted":True,"media_calls":0}


def main():
    from scripts import run_goal_context_text_production_v19 as run
    run.prior_guard();diagnosis=build_diagnosis()
    run.write(run.CONTENT_DIAGNOSIS,diagnosis,True)
    print(str(run.CONTENT_DIAGNOSIS))


if __name__=="__main__":main()
