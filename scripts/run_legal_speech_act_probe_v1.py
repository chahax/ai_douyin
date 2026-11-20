"""One historical speech-act probe, preserving619 consumption; no fresh-story admission."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import random
import sys

from jsonschema import Draft202012Validator

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from scripts import run_goal_context_text_production_v27 as production
from scripts import creative_goal_context_dispatch_v7 as adapter
from scripts import creative_m31_flash_role_clients_v1 as clients
from src.content_factory import creative_flat_lineage_verifier_v6 as verifier
from src.content_factory.creative_counted_execution_v1 import CountedExecution

VERSION="creative_legal_speech_act_probe/v1"
ROOT=PROJECT/"data/production_trials/legal_speech_act_probe_20261015/round_01"
GRANT="historical_legal_speech_act_probe_20261015"
CLAIM=PROJECT/"data/creative_fresh_background_claims"/GRANT/"CLAIM.json"
APPROVAL=CLAIM.parent/"USER_CONTINUATION_v1.json"
PROFILE=PROJECT/"config/creative_legal_speech_act_probe_profile_v1.json"
CASES=PROJECT/"data/qa/creative_speech_act_20261015/SEMANTIC_CASES_v1.json"
PREVIEW=PROJECT/"data/qa/creative_speech_act_producer_20261015/HISTORICAL_PROBE_REQUEST_PREVIEW_v2.json"
COUNTED_ROOT=production.COUNTED_EXECUTION_ROOT
COUNTED_KEY=production.COUNTED_ROUND_KEY
CADENCE_AUTH=COUNTED_ROOT/"AUTHORIZATION_AND_CADENCE_v1.json"
CADENCE_CONFIRMATION=COUNTED_ROOT/"USER_COUNT_UNIT_CONFIRMATION_v1.json"
PLAN=production.PLAN
PARENT_ROOT=production.PREFLIGHT_PARENT
PARENT_STATE=PARENT_ROOT/"STATE.json"
STAGE_LIMITS={"goal_plan":0,"goal_audit":1,"complete_script":0,"full_review":0}
INHERITED={"calls_started":619,"reported_tokens":12930923,"calls_with_known_usage":617,
    "pending_ordinals":[70,160],"unknown_token_reservations":93117}
read,write,digest,sha_file,now=production.read,production.write,production.digest,production.sha_file,production.now


def historical_parent_guard():
    """Historical integrity at the saved sampling date is NOT current freshness."""
    parent_freeze=read(PARENT_ROOT/"PRODUCTION_FREEZE.json")
    for path,expected in parent_freeze["files"].items():
        if sha_file(path)!=expected:raise ValueError("historical frozen dependency changed: "+path)
    source_packet=read(production.parent.OLD_ROOT/"source/SOURCE_PACKET.json")
    recorded_time=datetime.fromisoformat(source_packet["prepared_at"].replace("Z","+00:00"))
    verifier.verify_lineage_certificate(read(production.previous.CERTIFICATE),
        expected_certificate_sha256=parent_freeze["parent_certificate_sha256"],
        fresh_source_gate=lambda:production.parent.source_gate(recorded_time),
        expected_inherited=parent_freeze["inherited"])
    ledger=read(PARENT_ROOT/"CALL_LEDGER.json")
    if [row["ordinal"] for row in ledger["calls"]]!=[618,619]:raise ValueError("closed native618/619 ledger required")
    cycle=verifier.VerificationCycle()
    for row in ledger["calls"]:
        receipt=verifier._receipt(cycle,PROJECT,PARENT_ROOT,row,ledger["source_manifest"])
        if (receipt["status"]!=("contract_valid" if row["ordinal"]==618 else "contract_rejected")
                or receipt["response_metadata"]["total_tokens"]!={618:50377,619:47390}[row["ordinal"]]
                or not production.repairable(receipt)):
            raise ValueError("historical native outputs/status/known usage changed")
    terminal=read(PARENT_STATE);summary=terminal["spend"]
    if (terminal.get("status")!="halt_goal_audit_contract_requires_pipeline_diagnosis"
            or terminal.get("receipt_ordinal")!=619 or terminal.get("audit_kind")!="source"
            or terminal.get("text_ready_for_director") is not False
            or terminal.get("cumulative_goal_candidates_used")!=29
            or (summary["effective_calls_started"],summary["effective_reported_tokens"],summary["effective_calls_with_known_usage"])!=(619,12930923,617)
            or summary.get("historical_pending_ordinals")!=[70,160] or summary.get("unknown_token_reservations")!=93117
            or summary.get("new_unknown_token_reservations")!=0):
        raise ValueError("historical619 consumption and unknown history changed")
    production.verify_seed_native(read(PARENT_ROOT/"goals/native_01.json"))
    return {"historical_integrity_verified":True,"historical_sampling_time":source_packet["prepared_at"],
        "current_source_freshness_checked":False,"current_source_freshness_passed":False,
        "purpose":"historical_diagnostic_only","inherited":deepcopy(INHERITED)}


def verify_cases():
    document=read(CASES)
    refs=set()
    for row in document["cases"]:
        identity=row["original"]
        goal_path=PROJECT/identity["original_goal_path"]
        receipt_path=PROJECT/identity["receipt_path"]
        if (sha_file(goal_path)!=identity["original_goal_file_sha256"]
                or sha_file(receipt_path)!=identity["receipt_file_sha256"]):
            raise ValueError("historical case original bytes changed")
        goal=read(goal_path)
        catalog=production.workflow.source_audit.build_evidence_catalog(goal)
        ref=identity["source_ref"]
        if (digest(goal)!=identity["native_goal_sha256"] or ref not in catalog
                or identity["quote"]!=catalog[ref]["quote"]
                or identity["document_path"]!=catalog[ref]["document_path"]):
            raise ValueError("historical case native quote/reference changed")
        for context in row["context"]:
            if (context["source_ref"] not in catalog or any(context[key]!=catalog[context["source_ref"]][key]
                    for key in ("quote","document_path"))):
                raise ValueError("historical same-goal context changed")
        if row["case_id"] in refs:raise ValueError("duplicate historical case")
        refs.add(row["case_id"])
    if len(refs)!=12:raise ValueError("exact12 historical cases required")
    return document


def prepare_probe():
    """Blind order/IDs; expected labels and prior audit judgments never go on wire."""
    bank=verify_cases()
    rows=deepcopy(bank["cases"])
    random.Random(int(sha_file(CASES)[:16],16)).shuffle(rows)
    payload_cases={};mapping={}
    for index,row in enumerate(rows,1):
        opaque="T"+format(index,"02d")
        payload_cases[opaque]={"target":{"quote":row["original"]["quote"],
            "source_ref":row["original"]["source_ref"],"document_path":row["original"]["document_path"]},
            "same_goal_context":deepcopy(row["context"])}
        mapping[opaque]=row["case_id"]
    meanings=production.workflow.source_audit.SPEECH_ACT_MEANINGS
    payload={"purpose":"historical utterance classification only; no legal outcome or whole-plan approval",
        "speech_act_meanings":meanings,"cases":payload_cases}
    context=digest(payload)
    schema={"type":"object","additionalProperties":False,"properties":{
        "schema":{"const":VERSION},"context_sha256":{"const":context},
        "classifications":{"type":"object","additionalProperties":False,"properties":{
            key:{"type":"object","additionalProperties":False,"properties":{
                "speech_act":{"type":"string","enum":list(meanings)},
                "asserted_legal_proposition":{"type":"string","maxLength":600},
                "reason":{"type":"string","minLength":1,"maxLength":600}},
                "required":["speech_act","asserted_legal_proposition","reason"]} for key in payload_cases},
            "required":list(payload_cases)}},"required":["schema","context_sha256","classifications"]}
    profile=read(PROFILE)
    params={**deepcopy(profile["director"]["parameters"]),**profile["stage_parameters"]["goal_audit"]}
    rule=("本次是历史语句的语用分类诊断，只提交指定工具Schema要求的完整对象。"
        "每项target与same_goal_context独立阅读，不把另一项的人物、事件或法律前提套入当前项。"
        "依据输入speech_act_meanings的七类定义填写一个短码；理由简短说明原句实际断言或预设的命题。"
        "一句包含多种语用时，明示或预设的法律规则、权利义务、法定成立条件或法律效果优先选L；"
        "是否含此类命题或含义不清选U。混合句不能因人物立场、引用、虚构或否定形式而漏掉法律前提。"
        "不含法律断言的事实、请求、条件承诺、管理动机和叙事意图，按原句实际功能选F/R/P/M/N；"
        "不因劳动话题或相关人物物件就发明法律结论。"
        "asserted_legal_proposition仅填写原句实际断言或预设的法律命题，没有则空串；不替原句补论证。"
        "不裁决法律正确性、现实争议结果、完整来源或作品是否通过；不输出本次Schema以外的审查表。")
    request={"role":"director","model":profile["director"]["model"],"stage":"goal_audit",
        "parameters":params,"messages":[{"role":"system","content":rule},
            {"role":"user","content":json.dumps(payload,ensure_ascii=False,separators=(",",":"))}],
        "structured_schema":schema,"input_provenance":{"historical_diagnostic_only":True,
            "historical_casebank_sha256":sha_file(CASES),"source_context_sha256":context}}
    wire=clients.expected_wire_request(request)
    serialized=json.dumps(wire,ensure_ascii=False,separators=(",",":"))
    forbidden=("accepted_speech_acts","requires_detailed_legal_or_uncertain_review","historical_observation","benchmark_design","contrast_kind")
    if any(key in serialized for key in forbidden):raise ValueError("expected label or QA leaked into actual wire")
    return {"request":request,"request_sha256":digest(request),"wire":wire,"context_sha256":context,
        "blind_case_mapping":mapping,"historical_diagnostic_only":True,"provider_calls":0,
        "full_historical_guard_not_certified_by_preview":True,
        "expected_labels_in_wire":False,"media_calls":0,"whole_plan_approved":False}


def evaluate(document,prepared):
    Draft202012Validator(prepared["request"]["structured_schema"]).validate(document)
    bank={row["case_id"]:row for row in verify_cases()["cases"]}
    meanings=production.workflow.source_audit.SPEECH_ACT_MEANINGS
    outcomes=[]
    for opaque,case_id in prepared["blind_case_mapping"].items():
        actual=document["classifications"][opaque]
        expected=bank[case_id]["expected"]
        act=meanings[actual["speech_act"]]
        detailed=act in ("legal_assertion","uncertain")
        wants=expected["requires_detailed_legal_or_uncertain_review"]
        # Positive cases require the explicitly accepted conservative branch;
        # ordinary F/R/P/M/N differences remain separate descriptive accuracy.
        routing_ok=(detailed==wants and (not wants or act in expected["accepted_speech_acts"]))
        if wants and not actual["asserted_legal_proposition"].strip():routing_ok=False
        invented=not wants and bool(actual["asserted_legal_proposition"].strip())
        if invented:routing_ok=False
        outcomes.append({"opaque_id":opaque,"historical_case_id":case_id,"actual":act,
            "expected_detailed_routing":wants,"actual_detailed_routing":detailed,"routing_correct":routing_ok,
            "nonlegal_with_asserted_legal_proposition":invented,
            "fine_class_correct":act in expected["accepted_speech_acts"],"native_classification":deepcopy(actual)})
    positives=[row for row in outcomes if row["expected_detailed_routing"]]
    negatives=[row for row in outcomes if not row["expected_detailed_routing"]]
    accepted=all(row["routing_correct"] for row in outcomes)
    return {"valid":True,"accepted":accepted,"historical_diagnostic_only":True,"results":outcomes,
        "positive_total":len(positives),"positive_routing_correct":sum(row["routing_correct"] for row in positives),
        "negative_total":len(negatives),"nonlegal_false_positives":sum(row["actual_detailed_routing"] for row in negatives),
        "nonlegal_proposition_contradictions":sum(row["nonlegal_with_asserted_legal_proposition"] for row in negatives),
        "fine_class_correct":sum(row["fine_class_correct"] for row in outcomes),
        "current_source_freshness_passed":False,"source618_approved":False,"creative_quality_passed":False}


def build_binding(prepared):
    authority=read(production.previous.APPROVAL)
    if authority.get("human_authorized") is not True or authority.get("user_quote")!="minimax随便追加":
        raise ValueError("continuing user text authority required for historical diagnostic")
    return {"schema":VERSION+"/derived_authorization","created_at":now(),"human_authorized":True,
        "user_quote":"minimax随便追加","authority_source_sha256":sha_file(production.previous.APPROVAL),
        "parent_root":str(PARENT_ROOT),"parent_state_sha256":sha_file(PARENT_STATE),
        "parent_ledger_sha256":sha_file(PARENT_ROOT/"CALL_LEDGER.json"),"starting_spend":INHERITED,
        "casebank_sha256":sha_file(CASES),"profile_sha256":sha_file(PROFILE),"prepared_sha256":digest(prepared),
        "counted_execution_root":str(COUNTED_ROOT),"counted_round_key":COUNTED_KEY,
        "cadence_authorization_sha256":sha_file(CADENCE_AUTH),"count_unit_confirmation_sha256":sha_file(CADENCE_CONFIRMATION),
        "historical_diagnostic_only":True,"new_deepseek_calls_limit":1,"writer_calls_limit":0,
        "source_report_recovery_claimed":False,"old_ledger_reset":False,"automatic_transport_retry":False,
        "media_authorized":False,"publish_authorized":False,"current_source_freshness_passed":False}


def prepare():
    if ROOT.exists() or CLAIM.exists():raise FileExistsError("historical probe root/claim already exists; do not restart")
    history=historical_parent_guard();prepared=prepare_probe()
    expected=build_binding(prepared);approval=read(APPROVAL)
    if any(approval.get(key)!=value for key,value in expected.items() if key!="created_at"):
        raise ValueError("probe authority, historical identity, profile or actual request changed")
    if read(PREVIEW)!=prepared:raise ValueError("probe preview changed before claim")
    paths=set(read(PARENT_ROOT/"PRODUCTION_FREEZE.json")["files"])
    paths.update(str(path.resolve()) for path in (Path(__file__),PROFILE,CASES,APPROVAL,PREVIEW,PLAN,
        CADENCE_AUTH,CADENCE_CONFIRMATION,PARENT_STATE,PARENT_ROOT/"CALL_LEDGER.json",PARENT_ROOT/"RUN_CLAIM.json",
        Path(production.__file__),PROJECT/"src/content_factory/creative_counted_execution_v1.py",
        PROJECT/"src/content_factory/creative_goal_legal_usage_source_audit_v6.py",
        PROJECT/"src/content_factory/creative_goal_context_workflow_v23.py",Path(clients.__file__)))
    # Case611 is not part of parent25's immediate ledger, so pin all original
    # benchmark sources explicitly as well as their native semantic identities.
    for row in read(CASES)["cases"]:
        paths.add(str((PROJECT/row["original"]["original_goal_path"]).resolve()))
        paths.add(str((PROJECT/row["original"]["receipt_path"]).resolve()))
    write(CLAIM,{"schema":VERSION+"/claim","grant_id":GRANT,"root":str(ROOT),"created_at":now(),
        "historical_diagnostic_only":True,"authorization_sha256":sha_file(APPROVAL),"old_ledger_reset":False},True)
    ROOT.mkdir(parents=True)
    write(ROOT/"PREPARED_PROBE.json",prepared,True)
    write(ROOT/"HISTORICAL_INTEGRITY.json",history,True)
    write(ROOT/"USER_SCOPE.json",{"schema":VERSION+"/scope","stage_limits":STAGE_LIMITS,"starting_spend":INHERITED,
        "historical_diagnostic_only":True,"media_authorized":False,"writer_calls_limit":0,"new_deepseek_calls_limit":1,
        "old_director_capacity":{"used":7,"limit":7,"remaining":0}},True)
    freeze={"schema":VERSION+"/freeze","inherited":INHERITED,"models":production.models(read(PROFILE)),
        "files":{path:sha_file(path) for path in sorted(paths)},"sources":sorted(paths),"claim_sha256":sha_file(CLAIM)}
    write(ROOT/"PRODUCTION_FREEZE.json",freeze,True)
    runtime=get_runtime();runtime.prepare()
    return save_state(runtime,"prepared_historical_diagnostic")


def get_runtime():
    freeze=read(ROOT/"PRODUCTION_FREEZE.json")
    def guard():
        if read(CLAIM)["root"]!=str(ROOT) or sha_file(CLAIM)!=freeze["claim_sha256"]:raise ValueError("probe claim changed")
        for path,expected in freeze["files"].items():
            if sha_file(path)!=expected:raise ValueError("probe frozen dependency changed: "+path)
        historical_parent_guard()
    return adapter.GoalContextRuntime(PROJECT,ROOT,[Path(path) for path in freeze["sources"]],freeze["inherited"],
        freeze["models"],inherited_guard=guard,profile=read(PROFILE),stage_limits=STAGE_LIMITS,quota_state=None,
        shared_lock=PROJECT/"data/creative_fresh_background_claims/DISPATCH.lock",
        admission=lambda label,request,ledger:CountedExecution(COUNTED_ROOT).assert_dispatch_allowed(COUNTED_KEY),
        client_factory_builder=lambda request:clients.make_client_factory(request))


def save_state(runtime,status,**extra):
    value={"schema":VERSION+"/state","status":status,"updated_at":now(),"historical_diagnostic_only":True,
        "text_ready_for_director":False,"current_source_freshness_passed":False,"media_authorized":False,
        "source618_approved":False,"creative_quality_passed":False,"spend":runtime.summary(),**extra}
    write(ROOT/"STATE.json",value)
    return value


def run():
    runtime=get_runtime();runtime.inherited_guard()
    if (ROOT/"RUN_CLAIM.json").exists():raise FileExistsError("original probe run claim exists; no replay")
    CountedExecution(COUNTED_ROOT).assert_dispatch_allowed(COUNTED_KEY)
    prepared=prepare_probe()
    if prepared!=read(ROOT/"PREPARED_PROBE.json"):raise ValueError("actual probe differs from freeze")
    if read(runtime.ledger)["calls"]:raise RuntimeError("old probe calls must not be replayed")
    write(ROOT/"RUN_CLAIM.json",{"schema":VERSION+"/run_claim","pid":os.getpid(),"created_at":now(),"automatic_restart":False},True)
    # Reuse the production dispatcher shell with this module's exact root and
    # ordinary client, not by replacing globals on a shared frozen module.
    CountedExecution(COUNTED_ROOT).assert_dispatch_allowed(COUNTED_KEY)
    write(ROOT/"REQUEST_PREVIEW.json",prepared,True)
    receipt=runtime.dispatch("historical_speech_act_probe_01",prepared["request"],lambda value:evaluate(value,prepared))
    evidence=production.original.verify_receipt_evidence(runtime,receipt,prepared["request"])
    if (evidence/"request_body.raw").exists():
        verifier._outbound(verifier.VerificationCycle(),PROJECT,evidence,prepared["request"],
            receipt["call_evidence"]["identity_sha256"])
    elif receipt.get("response_metadata",{}).get("response_body_complete") is True:
        raise ValueError("complete probe result lacks captured outbound request")
    if receipt.get("cached_response_read_only"):return save_state(runtime,"halt_cached_probe_no_new_claim",receipt_ordinal=receipt["ordinal"])
    if not production.repairable(receipt):return save_state(runtime,"halt_probe_interface_or_unknown",receipt_ordinal=receipt["ordinal"])
    if receipt["status"]!="contract_valid":return save_state(runtime,"halt_probe_contract_requires_diagnosis",receipt_ordinal=receipt["ordinal"])
    decision=receipt["validation"]
    write(ROOT/"NATIVE_PROBE.json",receipt["output"],True)
    write(ROOT/"PROBE_DECISION.json",decision,True)
    return save_state(runtime,"historical_probe_routing_passed_not_production" if decision["accepted"] else "halt_historical_probe_routing_failed",
        receipt_ordinal=receipt["ordinal"],decision=decision,
        next_production_must_inherit_probe_consumption=True,new_production_automatically_dispatched=False)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("preview","register","prepare","run","status"))
    args=parser.parse_args(argv)
    if args.command in ("preview","register"):
        if args.command=="register":historical_parent_guard()
        prepared=prepare_probe()
        if PREVIEW.exists():
            if read(PREVIEW)!=prepared:raise ValueError("saved historical probe preview differs")
        else:write(PREVIEW,prepared,True)
        if args.command=="register":write(APPROVAL,build_binding(prepared),True)
        result={"preview":str(PREVIEW),"provider_calls":0,"historical_diagnostic_only":True}
    elif args.command=="prepare":result=prepare()
    elif args.command=="status":result=read(ROOT/"STATE.json")
    else:
        try:result=run()
        except Exception as exc:
            write(ROOT/"EXECUTION_ERROR.json",{"status":"stopped_original_probe_requires_reconciliation",
                "error_type":type(exc).__name__,"error":str(exc),"new_request_dispatched_by_recovery":False},True)
            raise
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return 0


if __name__=="__main__":raise SystemExit(main())
