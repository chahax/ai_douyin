"""Consumption bridge regressions; no new provider, task, claim or old-key gate."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import socket

import pytest

from scripts import creative_probe_spend_anchor_v1 as bridge
from src.content_factory.creative_counted_execution_v1 import CountedExecution


@pytest.fixture(autouse=True)
def read_only_offline(monkeypatch):
    def deny(*a,**kw):raise AssertionError("consumption bridge must not dispatch or require an old active round")
    monkeypatch.setattr(socket.socket,"connect",deny)
    monkeypatch.setattr(socket,"create_connection",deny)
    monkeypatch.setattr(CountedExecution,"assert_dispatch_allowed",deny)
    monkeypatch.setattr(bridge.probe,"get_runtime",deny)


@pytest.fixture
def records():
    root=bridge.ROOT
    ledger=bridge.read(root/"CALL_LEDGER.json")
    return [ledger,bridge.read(root/ledger["calls"][0]["receipt"]),bridge.read(root/"STATE.json"),
        bridge.read(root/"PRODUCTION_FREEZE.json"),bridge.read(root/"USER_SCOPE.json"),bridge.read(root/"AUTHORIZATION.json")]


def test_actual_known620_accounting_is_consumption_not_freshness_or_adoption(records):
    result=bridge.validate_records(*records)
    assert result==bridge.INHERITED
    assert result["calls_started"]==620 and result["reported_tokens"]==12941524
    assert result["calls_with_known_usage"]==618
    assert result["pending_ordinals"]==[70,160] and result["unknown_token_reservations"]==93117


@pytest.mark.parametrize("fault",["missing620","duplicate620","ordinal619","omit620_spend","reset_unknown",
    "old_reset","unknown_usage","bool_usage","wrong_total","wrong_sum","truncated","missing_tool",
    "wrong_model","unknown_status","changed_terminal","false_freshness","extra_writer","director_reset"])
def test_missing_duplicate_unknown_reset_or_false_approval_rejected(records,fault):
    ledger,receipt,terminal,freeze,scope,auth=records
    if fault=="missing620":ledger["calls"]=[]
    elif fault=="duplicate620":ledger["calls"].append(deepcopy(ledger["calls"][0]))
    elif fault=="ordinal619":ledger["calls"][0]["ordinal"]=619
    elif fault=="omit620_spend":terminal["spend"]["effective_calls_started"]=619
    elif fault=="reset_unknown":freeze["inherited"]["pending_ordinals"]=[]
    elif fault=="old_reset":ledger["old_budget_reset"]=True
    elif fault=="unknown_usage":receipt["response_metadata"]["total_tokens"]=None
    elif fault=="bool_usage":receipt["response_metadata"]["total_tokens"]=True
    elif fault=="wrong_total":receipt["response_metadata"]["total_tokens"]=10600
    elif fault=="wrong_sum":
        receipt["response_metadata"]["prompt_tokens"]-=1;receipt["response_payload"]["usage"]["prompt_tokens"]-=1
    elif fault=="truncated":receipt["response_metadata"]["finish_reason"]="length"
    elif fault=="missing_tool":receipt["response_metadata"]["output_mode"]="body"
    elif fault=="wrong_model":receipt["response_metadata"]["response_model"]="another-model"
    elif fault=="unknown_status":receipt["status"]="outcome_unknown"
    elif fault=="changed_terminal":terminal["spend"]["effective_reported_tokens"]=12930923
    elif fault=="false_freshness":terminal["current_source_freshness_passed"]=True
    elif fault=="extra_writer":scope["writer_calls_limit"]=1
    elif fault=="director_reset":scope["old_director_capacity"]["used"]=0
    with pytest.raises(ValueError):bridge.validate_records(*records)


def copied_native(tmp_path,records):
    ledger,receipt,*_=records
    root=tmp_path/"original_probe_copy";root.mkdir()
    relative=Path(receipt["call_evidence"]["directory"])
    assert not relative.is_absolute()
    shutil.copytree(bridge.ROOT/relative,root/relative)
    path=root/ledger["calls"][0]["receipt"]
    path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding="utf-8")
    ledger["calls"][0]["receipt_sha256"]=bridge.sha_file(path)
    return root,ledger,receipt,path


def test_generic_native_verifier_accepts_exact_copied_original_sdk_evidence(tmp_path,records):
    root,ledger,receipt,_=copied_native(tmp_path,records)
    result=bridge.verify_original_receipt(root,ledger)
    assert result==receipt and result["response_metadata"]["total_tokens"]==10601


@pytest.mark.parametrize("fault",["outbound_bytes","response_bytes","metadata_usage","request_identity"])
def test_actual_original_raw_or_request_usage_tampering_rejected(tmp_path,records,fault):
    root,ledger,receipt,path=copied_native(tmp_path,records)
    evidence=root/receipt["call_evidence"]["directory"]
    if fault in ("outbound_bytes","response_bytes"):
        raw=evidence/("request_body.raw" if fault=="outbound_bytes" else "response_body.raw")
        raw.write_bytes(raw.read_bytes()+b" ")
    elif fault=="metadata_usage":receipt["response_metadata"]["total_tokens"]=10600
    else:
        receipt["request"]["messages"][1]["content"]+=" altered"
        receipt["request_sha256"]=bridge.digest(receipt["request"])
    path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding="utf-8")
    ledger["calls"][0]["receipt_sha256"]=bridge.sha_file(path)
    with pytest.raises(bridge.native.LineageVerificationError):bridge.verify_original_receipt(root,ledger)


def test_frozen_anchor_cannot_omit620_or_be_rebound(monkeypatch):
    anchor={"schema":bridge.VERSION,"inherited":deepcopy(bridge.INHERITED)}
    monkeypatch.setattr(bridge,"build_anchor",lambda:deepcopy(anchor))
    expected=bridge.digest(anchor)
    assert bridge.verify_anchor(anchor,expected_anchor_sha256=expected)["inherited"]==bridge.INHERITED
    altered=deepcopy(anchor);altered["inherited"]["calls_started"]=619
    with pytest.raises(ValueError,match="anchor SHA changed"):bridge.verify_anchor(altered,expected_anchor_sha256=expected)
    with pytest.raises(ValueError,match="changed since anchor freeze"):
        bridge.verify_anchor(altered,expected_anchor_sha256=bridge.digest(altered))


def test_actual_original_bridge_reverifies_history_after_old_round_completed():
    identities={name:bridge.sha_file(bridge.ROOT/name) for name in ("PRODUCTION_FREEZE.json","CALL_LEDGER.json","STATE.json")}
    anchor=bridge.build_anchor()
    assert anchor["inherited"]==bridge.INHERITED and anchor["new_calls"]==[620]
    assert anchor["historical_integrity_verified"] and anchor["old_dispatch_round_key_is_history_only"]
    assert not anchor["current_source_freshness_verified"] and not anchor["authorizes_new_dispatch"]
    assert anchor["old_director_capacity"]=={"used":7,"limit":7,"remaining":0}
    assert identities=={name:bridge.sha_file(bridge.ROOT/name) for name in identities}
