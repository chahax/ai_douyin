"""Separate immutable historical diagnostics from current planning obligations.

This is a pure compiler/request preview, not a receipt/raw-SDK verifier, semantic
review, dispatch grant or capacity reset. Historical bytes remain the caller's
frozen evidence; full JSON artifacts returned here reconstruct the supplied data.
"""
from __future__ import annotations
from copy import deepcopy
import json

from . import creative_goal_context_workflow_v24 as current_workflow

VERSION="creative_goal_feedback_applicability/v1"
digest=current_workflow.digest
STRUCTURAL_CODES=frozenset({"GOAL_USER_REQUIREMENT_UNCOVERED","GOAL_DRAMATIC_CHOICE_UNTRACED",
    "GOAL_ORIGIN_CLASS_MISMATCH","GOAL_SCHEMA_INVALID"})
RULE=(
    "跨合同返修以revision_diagnostics.current_structural_revision_obligations为当前结构修订清单。"
    "historical_feedback_reference仅保存旧诊断身份与适用性，不是额外待办；旧合同的missing要求不可覆盖当前Schema和ownership。"
    "标记execution_only_no_narrative_obligation的来源继续由执行证据负责，不新增叙事claim来补旧错误。"
    "读取未改的previous_complete_document后提交完整原生新计划，不在本地补引用或拼接。"
    "结构诊断及其适用性不证明语义通过，旧语义失败或不确定不得因结构合法删除或改为passed。"
)


class ApplicabilityError(ValueError):
    pass


def _require(value,message):
    if not value:raise ApplicabilityError(message)


def _payload(request):
    _require(type(request) is dict and len(request.get("messages",[]))==2,"exact two-message native planning request required")
    value=json.loads(request["messages"][1]["content"])
    _require(type(value) is dict,"planning payload must be an object")
    return value


def _identity(prepared):
    request=prepared["request"];payload=_payload(request);manifest=prepared["manifest"];provenance=request["input_provenance"]
    _require(prepared["request_sha256"]==digest(request),"prepared request canonical identity changed")
    _require(provenance["context_manifest_sha256"]==digest(manifest),"prepared manifest identity changed")
    _require(manifest.get("workflow_version")==provenance.get("workflow_version"),"workflow identity differs between request and manifest")
    _require(manifest.get("payload_identity")==current_workflow.contexts._measure(payload),"actual payload differs from manifest identity")
    if "structured_schema_sha256" in manifest:
        _require(manifest["structured_schema_sha256"]==digest(request["structured_schema"]),"actual schema differs from manifest identity")
    catalog=payload["origin_catalog"];ownership=payload["user_goal_contract"].get("requirement_ownership")
    return {"workflow_version":provenance["workflow_version"],"request_sha256":digest(request),
        "context_manifest_sha256":digest(manifest),"structured_schema_sha256":digest(request["structured_schema"]),
        "native_contract_version":request["structured_schema"]["properties"]["contract_version"]["const"],
        "origin_catalog_sha256":digest(catalog),"user_goal_contract_sha256":digest(payload["user_goal_contract"]),
        "ownership_present":ownership is not None,"ownership_sha256":digest(ownership) if ownership is not None else None,
        "source_packet_sha256":digest(payload["source_packet"]),"verified_legal_context_sha256":digest(payload["verified_legal_context"]),
        "reference_fulltext_sha256":digest(payload["reference_fulltext"])}


def effective_contract_identity(identity):
    """Request/revision text and manifest hashes are not contract-equality keys."""
    return {key:deepcopy(identity[key]) for key in ("workflow_version","structured_schema_sha256",
        "origin_catalog_sha256","ownership_present","ownership_sha256","native_contract_version")}


def _historical(receipt,prepared):
    from scripts import creative_m31_flash_role_clients_v1 as ordinary
    _require(type(receipt) is dict and receipt.get("status")=="contract_rejected","known rejected native planning receipt required")
    request=receipt["request"];meta=receipt.get("response_metadata",{});usage=receipt.get("response_payload",{}).get("usage",{})
    _require(request==prepared["request"] and receipt.get("request_sha256")==digest(request),"historical receipt/prepared request mismatch")
    _require(prepared.get("wire")==ordinary.expected_wire_request(request),"historical prepared wire differs from exact target tool request")
    _require(request.get("stage")=="goal_plan" and request.get("role")=="writer","only whole planning feedback is supported")
    failure=receipt.get("failure",{})
    _require(receipt.get("automatic_retry") is False and failure.get("automatic_retry") is False
        and failure.get("response_received") is True and prepared.get("sdk_max_retries")==0,
        "original known receipt and no-retry metadata required")
    _require(type(receipt.get("output")) is dict and receipt["output"],"complete native planning object required")
    _require(type(meta.get("http_status_code")) is int and 200<=meta["http_status_code"]<300
        and meta.get("response_body_complete") is True and meta.get("finish_reason") in ("stop","tool_calls")
        and not meta.get("response_fault_code")
        and meta.get("output_mode")=="tool_call"
        and meta.get("requested_model")==meta.get("response_model")==request["model"],"unknown/incomplete/protocol response cannot become content feedback")
    for key in ("prompt_tokens","completion_tokens","total_tokens"):
        _require(type(meta.get(key)) is int and meta[key]>=0 and type(usage.get(key)) is int and usage[key]==meta[key],"known original typed usage required")
    _require(meta["prompt_tokens"]+meta["completion_tokens"]==meta["total_tokens"],"historical usage totals differ")
    choices=receipt["response_payload"].get("choices",[])
    _require(type(choices) is list and len(choices)==1 and type(choices[0]) is dict
        and choices[0].get("index")==0 and choices[0].get("finish_reason")==meta["finish_reason"],"one complete original provider choice required")
    message=choices[0].get("message",{});calls=message.get("tool_calls",[])
    _require(message.get("role")=="assistant" and type(calls) is list and len(calls)==1
        and calls[0].get("type")=="function" and calls[0].get("function",{}).get("name")==ordinary.TOOL_NAME
        and json.loads(calls[0]["function"]["arguments"])==receipt["output"],"historical native object differs from exact provider target tool arguments")
    diagnostics={key:deepcopy(receipt[key]) for key in ("failure","validation_error","validation") if key in receipt}
    detail=diagnostics.get("validation_error",{}).get("detail",{})
    _require(type(detail.get("findings")) is list and detail.get("valid") is False,"complete original structural diagnostic report required")
    return diagnostics,deepcopy(detail)


def compile_applicability(receipt,historical_prepared,current_inputs,profile,*,workflow_adapter=current_workflow,semantic_feedback=None):
    """Return a lossless local artifact plus explicit current-only obligations.

    Unknown structural codes and every supplied semantic result are retained and
    block this structural-only request path. No prose is relabelled passed, and
    no version-string comparison substitutes for schema/catalog/ownership SHA.
    """
    native=deepcopy(receipt.get("output"));input_sha=digest(current_inputs)
    diagnostics,historical_report=_historical(receipt,historical_prepared)
    _require(not any(key in current_inputs for key in ("previous_complete_document","revision_diagnostics")),"clean original current inputs required")
    current_prepared=workflow_adapter.prepare_goal_request(current_inputs,profile)
    historical_identity,current_identity=_identity(historical_prepared),_identity(current_prepared)
    _require(all(historical_identity[key]==current_identity[key] for key in
        ("source_packet_sha256","verified_legal_context_sha256","reference_fulltext_sha256")),"source/law/reference changes require a different authorized route")
    current_report=workflow_adapter.diagnose_goal_document(native,inputs=current_inputs)
    _require(type(current_report) is dict and type(current_report.get("findings")) is list,"complete current native diagnostic report required")
    ownership=workflow_adapter.ownership_evidence(current_inputs)
    execution_only={row["id"] for row in ownership["mappings"] if row["owner"]=="execution"}
    active_by_key={(row.get("code"),row.get("path")):index for index,row in enumerate(current_report["findings"]) if type(row) is dict}
    applicability=[];blockers=[]
    if diagnostics.get("failure",{}).get("category") not in ("validation","state_contract","compilation"):
        blockers.append({"code":"UNSUPPORTED_HISTORICAL_FAILURE_CATEGORY","original_failure":deepcopy(diagnostics.get("failure"))})
    if (diagnostics.get("failure",{}).get("code")!="GOAL_NATIVE_PLANNING_INVALID"
            or diagnostics.get("validation_error",{}).get("code")!="GOAL_NATIVE_PLANNING_INVALID"):
        blockers.append({"code":"UNSUPPORTED_HISTORICAL_DIAGNOSTIC_FAMILY","original_failure":deepcopy(diagnostics.get("failure"))})
    for index,row in enumerate(historical_report["findings"]):
        code,path=(row.get("code"),row.get("path")) if type(row) is dict else (None,None)
        entry={"original_finding_pointer":f"/historical_diagnostics/validation_error/detail/findings/{index}",
            "original_finding_sha256":digest(row),"code":code,"path":path,"semantic_passed":False}
        if code not in STRUCTURAL_CODES:
            entry["disposition"]="unrecognized_diagnostic_retained_stop";blockers.append({"code":"UNSUPPORTED_HISTORICAL_DIAGNOSTIC","finding":deepcopy(row)})
        elif code=="GOAL_USER_REQUIREMENT_UNCOVERED" and row.get("missing_origin_ids") and set(row["missing_origin_ids"])<=execution_only:
            entry.update(disposition="execution_only_no_narrative_obligation",origin_ids=deepcopy(row["missing_origin_ids"]),
                reason="current explicit ownership assigns these original requirements to execution; original requirements remain in frozen inputs")
        elif (code,path) in active_by_key:
            entry.update(disposition="still_current_structural_obligation",current_finding_pointer=f"/current_diagnostics/findings/{active_by_key[(code,path)]}")
        else:
            entry["disposition"]="not_reproduced_applicability_unresolved_stop";blockers.append({"code":"HISTORICAL_APPLICABILITY_UNRESOLVED","finding":deepcopy(row)})
        applicability.append(entry)
    for row in current_report["findings"]:
        if type(row) is not dict or row.get("code") not in STRUCTURAL_CODES:blockers.append({"code":"UNSUPPORTED_CURRENT_DIAGNOSTIC","finding":deepcopy(row)})
    retained_semantic=deepcopy(semantic_feedback)
    if semantic_feedback not in (None,{},[]):blockers.append({"code":"SEMANTIC_FEEDBACK_REQUIRES_EXPLICIT_CURRENT_REVIEW","original_semantic_feedback_sha256":digest(semantic_feedback)})
    # A semantic/audit decision embedded in a receipt is not a schema diagnosis.
    if diagnostics.get("validation") is not None and (type(diagnostics["validation"]) is not dict
            or any(key in diagnostics["validation"] for key in ("accepted","uncertainties","audit_kind"))):
        blockers.append({"code":"EMBEDDED_SEMANTIC_FEEDBACK_RETAINED_STOP","original_validation_sha256":digest(diagnostics["validation"])})
    _require(digest(current_inputs)==input_sha and receipt["output"]==native,"compiler changed original inputs/native")
    old_effective,new_effective=effective_contract_identity(historical_identity),effective_contract_identity(current_identity)
    return {"schema":VERSION,"historical_artifacts":{"receipt":deepcopy(receipt),"prepared_request":deepcopy(historical_prepared)},
        "historical_identity":historical_identity,"current_identity":current_identity,
        "historical_effective_contract_identity":old_effective,"current_effective_contract_identity":new_effective,
        "effective_contract_changed":old_effective!=new_effective,
        "historical_diagnostics":diagnostics,"historical_diagnostics_sha256":digest(diagnostics),
        "historical_applicability":applicability,"current_diagnostics":deepcopy(current_report),
        "current_structural_revision_obligations":deepcopy(current_report["findings"]),
        "ownership_evidence":ownership,"retained_semantic_feedback":retained_semantic,"blockers":blockers,
        "status":"halt_feedback_applicability_requires_diagnosis" if blockers else "ready_for_current_structural_revision_preview",
        "native_goal_sha256":digest(native),"current_inputs_sha256":input_sha,
        "same_native_contract_version_is_not_same_contract":historical_identity["native_contract_version"]==current_identity["native_contract_version"] and old_effective!=new_effective,
        "native_document_modified":False,"legal_sources_modified":False,"semantic_feedback_marked_passed":False,
        "human_approved":False,"dispatch_authorized":False,"provider_calls":0}


def restore_historical(artifact):
    """Losslessly restore supplied receipt, request and diagnostics from artifact."""
    _require(artifact.get("schema")==VERSION,"unsupported feedback artifact")
    receipt=deepcopy(artifact["historical_artifacts"]["receipt"])
    prepared=deepcopy(artifact["historical_artifacts"]["prepared_request"])
    diagnostics,_=_historical(receipt,prepared)
    _require(diagnostics==artifact["historical_diagnostics"] and digest(diagnostics)==artifact["historical_diagnostics_sha256"],"original diagnostic reconstruction mismatch")
    _require(digest(receipt["output"])==artifact["native_goal_sha256"] and _identity(prepared)==artifact["historical_identity"],"historical native/contract identity changed")
    return {"receipt":receipt,"prepared_request":prepared,"diagnostics":diagnostics}


def prepare_revision_request(receipt,historical_prepared,current_inputs,profile,*,workflow_adapter=current_workflow,semantic_feedback=None):
    """Preview a real next planning request; never instantiate a client or claim."""
    from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
    artifact=compile_applicability(receipt,historical_prepared,current_inputs,profile,
        workflow_adapter=workflow_adapter,semantic_feedback=semantic_feedback)
    if artifact["blockers"]:return {"artifact":artifact,"prepared":None,"dispatch_authorized":False}
    feedback={"schema":VERSION+"/request_feedback","current_structural_revision_obligations":artifact["current_structural_revision_obligations"],
        "current_diagnostics_identity":{"sha256":digest(artifact["current_diagnostics"]),"contract_identity":artifact["current_identity"]},
        "historical_feedback_reference":{"artifact_canonical_sha256":digest(artifact),
            "original_receipt_sha256":digest(receipt),"original_diagnostics_sha256":artifact["historical_diagnostics_sha256"],
            "original_contract_identity":artifact["historical_identity"],"applicability":artifact["historical_applicability"],
            "historical_findings_are_not_additional_obligations":True,"complete_original_artifacts_returned_locally":True},
        "semantic_quality_approved":False,"requires_fresh_same_source_semantic_reviews":True}
    revision={**deepcopy(current_inputs),"previous_complete_document":deepcopy(receipt["output"]),"revision_diagnostics":feedback}
    prepared=workflow_adapter.prepare_goal_request(revision,profile)
    prepared["request"]["messages"][0]["content"]+=RULE
    payload=_payload(prepared["request"])
    _require(payload["previous_complete_document"]==receipt["output"] and payload["revision_diagnostics"]==feedback,"actual planning payload changed complete native/feedback")
    prepared["manifest"].update(feedback_applicability_version=VERSION,feedback_artifact_sha256=digest(artifact),
        feedback_current_contract_identity=artifact["current_identity"],historical_diagnostics_nonoperative=True,
        feedback_artifact_local_binding_pending=True)
    prepared["request"]["input_provenance"].update(feedback_applicability_version=VERSION,feedback_artifact_sha256=digest(artifact),
        context_manifest_sha256=digest(prepared["manifest"]))
    prepared["request_sha256"]=digest(prepared["request"]);prepared["wire"]=expected_wire_request(prepared["request"])
    return {"artifact":artifact,"prepared":prepared,"dispatch_authorized":False,"provider_calls":0}
