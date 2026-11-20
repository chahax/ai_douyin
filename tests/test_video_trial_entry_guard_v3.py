"""Selected487 JSON-document wire upgrade; focused and entirely offline."""
from copy import deepcopy
import hashlib
import json
import socket
from types import SimpleNamespace

import pytest

from scripts import run_selected_script_video_trial_v3 as trial


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("transport integration tests cannot access providers")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.fixture
def schema():
    return {"type": "object", "additionalProperties": False,
            "required": ["steps"], "properties": {"steps": {
                "type": "array", "items": {"type": "string"}, "minItems": 1}}}


def make_receipt(schema, payload=' {"steps": ["完整原文"]} '):
    raw = json.dumps({"payload_json": payload}, ensure_ascii=False)
    return {"request": {"output_transport": trial.document_transport.VERSION,
                        "inner_document_schema": deepcopy(schema)},
            "response_text": raw, "output": {"payload_json": payload}}


def test_writer_envelope_retains_complete_whole_schema_and_original_inputs(monkeypatch):
    monkeypatch.setattr(trial, "runtime", lambda: SimpleNamespace(
        models={"writer": {"model": "MiniMax-M3"}, "director": {"model": "DeepSeek"}}))
    x = trial.control.read(trial.ROOT / "INPUT.json")
    before = deepcopy(x)
    whole, _ = trial.stage_inputs(x)
    schema = trial.whole_wire_schema(x["full_current_script"])
    before_schema = deepcopy(schema)
    request = trial.wire("writer", "完整整片规划", whole, schema, 12000)
    assert request["output_transport"] == trial.document_transport.VERSION
    envelope = request["structured_schema"]
    assert envelope["required"] == ["payload_json"]
    assert list(envelope["properties"]) == ["payload_json"]
    assert envelope["properties"]["payload_json"]["type"] == "string"
    assert envelope["additionalProperties"] is False
    assert request["inner_document_schema"] == schema == before_schema
    assert len(schema["properties"]["source_assignments"]["prefixItems"]) == 25
    assert json.loads(request["messages"][-1]["content"])["inner_document_schema"] == schema
    assert json.loads(request["messages"][1]["content"]) == whole
    assert all(k not in whole for k in (
        "current_scope", "source_acceptance_scope", "original_automatic_decision_retained"))
    assert whole["reference_fulltext"] == x["reference_fulltext"]
    assert whole["prior_complete_direction_failure"]["ordinal"] == 493
    assert x == before


def test_director_keeps_ordinary_tool_without_document_transport(monkeypatch, schema):
    monkeypatch.setattr(trial, "runtime", lambda: SimpleNamespace(
        models={"director": {"model": "DeepSeek"}}))
    value = {"steps": ["待审全文"]}
    request = trial.wire("director", "独立全文审查", value, schema, 4000)
    assert "output_transport" not in request
    assert "inner_document_schema" not in request
    assert request["structured_schema"] == schema
    assert len(request["messages"]) == 2
    assert json.loads(request["messages"][1]["content"]) == value


def test_received_document_preserves_original_hashes_and_derived_identity(schema):
    receipt = make_receipt(schema)
    raw, native = receipt["response_text"], deepcopy(receipt["output"])
    runtime = object.__new__(trial.control.ContinuationRuntime)
    seen = []
    result = runtime._validate_output(receipt, receipt["request"], lambda doc: seen.append(doc))
    assert result["status"] == "contract_valid"
    assert seen == [{"steps": ["完整原文"]}]
    assert result["response_text"] == raw and result["output"] == native
    assert trial.received_document(result) == result["document_output"] == seen[0]
    evidence = result["document_transport_validation"]
    assert evidence["payload_sha256"] == hashlib.sha256(native["payload_json"].encode()).hexdigest()
    assert evidence["document_sha256"] == trial.control.digest(seen[0])
    assert evidence["metadata"]["outer_argument_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert evidence["metadata"]["outer_duplicate_keys_verified"] is True
    assert evidence["metadata"]["source_string_modified"] is False
    assert evidence["original_wire_output_preserved"] is True
    assert evidence["model_document_repaired"] is False
    changed = deepcopy(result)
    changed["document_output"]["steps"][0] = "人工篡改"
    with pytest.raises(ValueError, match="differs"):
        trial.received_document(changed)
    changed = deepcopy(result)
    changed["response_text"] = json.dumps({"payload_json": '{"steps":["原文被替换"]}'}, ensure_ascii=False)
    with pytest.raises(ValueError, match="differs"):
        trial.received_document(changed)


@pytest.mark.parametrize("raw", [
    '{"payload_json":"{\\"steps\\":[\\"a\\"]}","payload_json":"{\\"steps\\":[\\"b\\"]}"}',
    json.dumps({"payload_json": '{"steps":["a"],"steps":["b"]}'}),
    json.dumps({"payload_json": '["a"]'}),
    json.dumps({"payload_json": '{"steps":{"item":"a"}}'}),
    json.dumps({"payload_json": '{"item":{"steps":["a"]}}'}),
])
def test_duplicates_top_level_array_and_item_wrappers_are_not_repaired(schema, raw):
    receipt = make_receipt(schema)
    receipt["response_text"] = raw
    receipt["document_output"] = {"steps": ["a"]}
    before = deepcopy(receipt)
    with pytest.raises(trial.document_transport.DocTransportError):
        trial.received_document(receipt)
    assert receipt == before


def test_real_complete493_schema_failure_is_spend_not_a_retry():
    ledger_path = trial.KNOWN_PARENT / "CALL_LEDGER.json"
    before = ledger_path.read_bytes()
    ledger = trial.control.read(ledger_path)
    inherited, receipts = trial.inherited_known_parent(ledger, trial.KNOWN_PARENT)
    assert ledger_path.read_bytes() == before
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt["ordinal"] == 493 and receipt["status"] == "contract_rejected"
    assert receipt["failure"]["category"] == "state_contract"
    assert receipt["response_metadata"]["response_body_complete"] is True
    assert receipt["response_metadata"]["finish_reason"] == "tool_calls"
    assert receipt["response_metadata"]["total_tokens"] == 20754
    assert inherited["calls_started"] == 493
    assert inherited["reported_tokens"] == 7616322
    assert inherited["calls_with_known_usage"] == 491
    assert inherited["unknown_token_reservations"] == 93117
    assert inherited["pending_ordinals"] == [70, 160]
    assert inherited["parent_ledger_sha256"] == trial.control.sha_file(ledger_path)

