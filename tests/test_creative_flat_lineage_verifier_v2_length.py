"""Exact native length-failure consumption; no task adoption or provider retry."""
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest
from src.content_factory import creative_flat_lineage_verifier_v2 as flat
from tests.test_creative_flat_lineage_verifier_v2 import (
    native_parent, prohibit_network, dump, sha, certificate, verify)


def rewrite_synthetic_response(data,receipt,result_changes=None,sql_changes=None):
    """Only alter new synthetic test evidence, never historical records."""
    raw=json.dumps(receipt["response_payload"],ensure_ascii=False).encode("utf-8")
    raw_sha=hashlib.sha256(raw).hexdigest()
    (data["evidence"]/"response_body.raw").write_bytes(raw)
    manifest=json.loads((data["evidence"]/"RESPONSE_BODY_MANIFEST.json").read_text("utf-8"))
    manifest.update(stored_sha256=raw_sha,original_sha256=raw_sha,bytes=len(raw))
    manifest["http_metadata"]["http_status_code"]=receipt["response_metadata"]["http_status_code"]
    dump(data["evidence"]/"RESPONSE_BODY_MANIFEST.json",manifest)
    receipt["response_metadata"]["raw_body_sha256"]=raw_sha
    dump(data["receipt"],receipt)
    ledger=json.loads((data["root"]/"CALL_LEDGER.json").read_text("utf-8"))
    ledger["calls"][0]["receipt_sha256"]=sha(data["receipt"])
    dump(data["root"]/"CALL_LEDGER.json",ledger)
    with sqlite3.connect(data["root"]/"TASKS.sqlite3") as db:
        result=json.loads(db.execute("SELECT result FROM attempts").fetchone()[0])
        result["raw_receipt"].update(body=base64.b64encode(raw).decode(),sha256=raw_sha,
            http_status=receipt["response_metadata"]["http_status_code"])
        result.update(result_changes or {})
        db.execute("UPDATE attempts SET result=?,result_sha=?",(json.dumps(result,ensure_ascii=False),flat.digest(result)))
        for key,value in (sql_changes or {}).items():
            assert key in {"status","service_task_id","provider_id"}
            db.execute("UPDATE attempts SET "+key+"=?",(value,))


@pytest.fixture
def length_parent(native_parent):
    data=native_parent
    with sqlite3.connect(data["root"]/"TASKS.sqlite3") as db:
        db.execute("ALTER TABLE attempts ADD COLUMN service_task_id")
        db.execute("ALTER TABLE attempts ADD COLUMN provider_id")
    receipt=json.loads(data["receipt"].read_text("utf-8"))
    receipt.update(status="interface_rejected",error="RESPONSE_TRUNCATED",automatic_retry=False,
        semantic_approval=False,completed_at="2026-10-14T04:02:46+00:00",output=None,validation=None,response_text="")
    receipt["failure"]={"code":"RESPONSE_TRUNCATED","cause_code":"RESPONSE_TRUNCATED","category":"interface",
        "response_received":True,"provider_outcome_known":True,"blocks_handoff":True,"automatic_retry":False,
        "http_status_code":200}
    receipt["response_payload"]["usage"]={"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}
    choice=receipt["response_payload"]["choices"][0]
    choice["finish_reason"]="length"
    choice["message"]["tool_calls"][0]["function"]["arguments"]='{"text":'
    receipt["response_metadata"].update(finish_reason="length",output_mode="unusable_response",
        response_fault_code="RESPONSE_TRUNCATED",prompt_tokens=3,completion_tokens=2,total_tokens=5)
    rewrite_synthetic_response(data,receipt,{"outcome":"unknown","result_known":False,"complete_end":False,
        "schema_tool_status":"unknown","contract_valid":None,"service_task_id":None,
        "output":{"ordinal":539,"native_output":None}},
        {"status":"result_unknown","service_task_id":None,"provider_id":receipt["request"]["model"]})
    return data


def test_length_consumption_retains_pending_task_and_does_not_adopt_native_document(length_parent):
    data=length_parent
    before={p:p.read_bytes() for p in data["root"].rglob("*") if p.is_file()}
    value=certificate(data);result=verify(value)
    assert result["inherited"]=={"calls_started":539,"reported_tokens":10247612,
        "calls_with_known_usage":537,"unknown_token_reservations":93117,"pending_ordinals":[70,160]}
    assert value["known_length_failure_consumption_only"] is True
    assert value["original_task_pending_identity_preserved"] is True
    assert value["original_request_retry_authorized"] is False
    assert value["native_document_approval_from_certificate"] is False
    assert {p:p.read_bytes() for p in before}==before


@pytest.mark.parametrize("field",["error","failure.code","failure.cause_code","failure.category",
    "failure.response_received","failure.provider_outcome_known","failure.blocks_handoff","failure.automatic_retry",
    "response_metadata.response_fault_code","response_metadata.response_body_complete","response_metadata.requested_model",
    "response_metadata.response_model","output","document_output","validation","semantic_approval","automatic_retry",
    "completed_at","response_metadata.prompt_tokens","response_metadata.completion_tokens","response_metadata.total_tokens"])
def test_length_predicate_rejects_each_weak_or_adopted_condition(length_parent,field):
    data=length_parent;receipt=json.loads(data["receipt"].read_text("utf-8"))
    target=receipt;keys=field.split(".")
    for key in keys[:-1]:target=target[key]
    old=target.get(keys[-1])
    target[keys[-1]]={"adopted":True} if keys[-1] in ("output","document_output","validation") else (
        not old if type(old) is bool else None if type(old) is int or field=="completed_at" else "different")
    rewrite_synthetic_response(data,receipt)
    with pytest.raises(flat.LineageVerificationError):certificate(data)


@pytest.mark.parametrize("change",["ordinary_unknown","missing_usage","negative_usage","bool_usage","float_usage",
    "unequal_usage","bad_sum","multi_choice","raw_model","raw_id"])
def test_raw_length_or_usage_mismatch_does_not_create_general_unknown_exception(length_parent,change):
    data=length_parent;receipt=json.loads(data["receipt"].read_text("utf-8"))
    payload=receipt["response_payload"];meta=receipt["response_metadata"]
    if change=="ordinary_unknown":payload["choices"][0]["finish_reason"]=meta["finish_reason"]=None
    elif change=="missing_usage":payload.pop("usage")
    elif change in ("negative_usage","bool_usage","float_usage"):
        value=-1 if change=="negative_usage" else True if change=="bool_usage" else 3.0
        payload["usage"]["prompt_tokens"]=meta["prompt_tokens"]=value
    elif change=="unequal_usage":payload["usage"]["completion_tokens"]+=1
    elif change=="bad_sum":payload["usage"]["prompt_tokens"]=meta["prompt_tokens"]=4
    elif change=="multi_choice":payload["choices"].append(deepcopy(payload["choices"][0]))
    elif change=="raw_model":payload["model"]="different"
    else:payload["id"]="different"
    rewrite_synthetic_response(data,receipt)
    with pytest.raises(flat.LineageVerificationError):certificate(data)


@pytest.mark.parametrize("field,value",[("outcome","completed"),("result_known",True),("usage_known",False),
    ("complete",False),("complete_end",True),("schema_tool_status","accepted"),("contract_valid",True),
    ("output",{"ordinal":539,"native_output":{"adopted":True}}),("service_task_id","in_flight")])
def test_length_task_result_preserves_each_exact_original_failure_flag(length_parent,field,value):
    data=length_parent;receipt=json.loads(data["receipt"].read_text("utf-8"))
    rewrite_synthetic_response(data,receipt,{field:value})
    with pytest.raises(flat.LineageVerificationError):certificate(data)


@pytest.mark.parametrize("field,value",[("status","claimed"),("status","completed"),
    ("service_task_id","in_flight"),("provider_id","different_model")])
def test_length_attempt_cannot_have_unsettled_service_or_false_completed_identity(length_parent,field,value):
    data=length_parent;receipt=json.loads(data["receipt"].read_text("utf-8"))
    rewrite_synthetic_response(data,receipt,sql_changes={field:value})
    with pytest.raises(flat.LineageVerificationError):certificate(data)


@pytest.fixture(scope="module")
def real_round16_certificate(tmp_path_factory):
    from scripts import run_goal_context_text_production_v18 as runner
    from scripts import creative_flat_lineage_guard_v2 as guard
    db=runner.PREFLIGHT_PARENT/"TASKS.sqlite3"
    before={str(db):sha(db),str(runner.APPROVAL):sha(runner.APPROVAL)}
    original_task=flat.VerificationCycle().read_bytes(db)
    value=guard.build_lineage_certificate(runner.PROJECT,runner.PREFLIGHT_PARENT,
        certified_check=runner.prior_guard,expected_summary=runner.read(runner.PARENT_STATE)["spend"],
        dependency_paths=[runner.PARENT_STATE],guard_code_paths=[Path(runner.__file__),Path(guard.__file__),Path(flat.__file__)])
    # Every test invocation gets its own genuine certificate. The separately
    # saved QA checkpoint stays immutable and is not rewritten by a rerun.
    path=tmp_path_factory.mktemp("real601_certificate")/"CERTIFICATE.json"
    runner.write(path,value,True)
    return runner,guard,value,path,before,original_task


def test_real601_certificate_build_readback_preserves_db_claim_and_authorization(real_round16_certificate):
    runner,guard,value,path,before,task_bytes=real_round16_certificate
    result=guard.verify_lineage_certificate(path,expected_certificate_sha256=sha(path),
        fresh_source_gate=runner.parent.source_gate,expected_inherited=value["inherited"])
    assert result["inherited"]=={"calls_started":601,"reported_tokens":12004575,"calls_with_known_usage":599,
        "unknown_token_reservations":93117,"pending_ordinals":[70,160]}
    assert all(sha(Path(p))==v for p,v in before.items())
    assert (runner.PREFLIGHT_PARENT/"TASKS.sqlite3").read_bytes()==task_bytes
    assert not runner.ROOT.exists() and not runner.CLAIM.exists()
    seed=runner.read(runner.PREFLIGHT_PARENT/"goals/native_02.json")
    first=runner.workflow.prepare_goal_request(runner.revision_planning_inputs(
        runner.read(runner.PREFLIGHT_PARENT/"INPUTS.json"),seed,runner.build_revision_diagnostics(seed)),runner.read(runner.PROFILE))
    assert runner.digest(first)==runner.read(runner.APPROVAL)["actual_prepared_preview_sha256"]


@pytest.mark.parametrize("flag",["known_length_failure_consumption_only","original_task_pending_identity_preserved",
    "original_request_retry_authorized","native_document_approval_from_certificate"])
def test_real_certificate_cannot_waive_pending_identity_or_claim_native_approval(real_round16_certificate,flag):
    runner,guard,value,_,_,_=real_round16_certificate
    bad=deepcopy(value);bad[flag]=not bad[flag]
    with pytest.raises(flat.LineageVerificationError,match="policy differs"):
        guard.verify_lineage_certificate(bad,expected_certificate_sha256=guard.digest(bad),fresh_source_gate=runner.parent.source_gate)
