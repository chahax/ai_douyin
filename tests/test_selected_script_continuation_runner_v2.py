"""Current source/channel revision handoff and spend; no provider effects."""
from copy import deepcopy
import json
import socket

import pytest

from scripts import run_selected_script_continuation_v2 as trial
from tests.test_creative_continuation_probe_contract_v2 import wire as valid_native


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("current-source regression must stay offline")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def test_actual499500_complete_spend_and_approved_tail_are_retained():
    p = trial.PARENT / "CALL_LEDGER.json"
    before = p.read_bytes()
    inherited, receipts = trial.previous.inherited_known_parent(trial.control.read(p), trial.PARENT)
    assert [(r["ordinal"], r["status"], r["response_metadata"]["total_tokens"]) for r in receipts] == [
        (499, "contract_valid", 4369), (500, "contract_valid", 21027)]
    assert inherited["calls_started"] == 500 and inherited["reported_tokens"] == 7695316
    assert inherited["calls_with_known_usage"] == 498
    assert inherited["unknown_token_reservations"] == 93117 and inherited["pending_ordinals"] == [70, 160]
    assert p.read_bytes() == before
    assert trial.approved_frame()["source_task_id"] == "cgt-20261011192956-wrdkg"
    assert trial.approved_frame()["sha256"] == "89c712fd8c2fdb1696d9a3ba62726b04b47ba5958da074866edd450239bda365"


@pytest.mark.parametrize("review_status", ["pass", "fail", "unknown"])
def test_model_revision_and_independent_eight_item_review_are_same_source(
        monkeypatch, tmp_path, review_status):
    x = trial.control.read(trial.PARENT / "INPUT.json")
    ledger = trial.control.read(trial.PARENT / "CALL_LEDGER.json")
    old_writer, old_review = [trial.control.read(trial.PARENT / r["receipt"]) for r in ledger["calls"]]
    x["prior_current_content_revision"] = {
        "writer_ordinal": 499, "review_ordinal": 500,
        "complete_known_native_performance": trial.previous.received_document(old_writer),
        "original_review": old_review["output"],
        "required_repairs": ["S03听签字要求；S04看纸上的原因；不得倒置渠道。", "本段动作须完成。"],
        "repair_is_complete_model_content_revision": True,
        "old_native_and_review_unchanged": True, "media_calls_from_prior_candidate": 0}
    (tmp_path / "INPUT.json").write_text(json.dumps(x, ensure_ascii=False), encoding="utf-8")
    requests = []
    class Runtime:
        models = {"writer": {"model": "MiniMax-M3"}, "director": {"model": "DeepSeek"}}
        def dispatch(self, label, request, validator):
            requests.append((label, deepcopy(request)))
            if label == "continuation_performance":
                doc = valid_native(x["full_current_script"])
                raw = trial.transport.encode_envelope(doc, request["inner_document_schema"])
                receipt = {"ordinal": 501, "request": request, "response_text": raw, "output": json.loads(raw)}
            else:
                doc = {"script_sha256": trial.SOURCE_SHA,
                    "checks": [{"check": name, "status": "pass", "source_refs": trial.REFS,
                        "reason": "offline current-source evidence"} for name in trial.REVIEW_CHECKS],
                    "revision_requirements": []}
                doc["checks"][-1]["status"] = review_status
                receipt = {"ordinal": 502, "request": request, "output": doc}
            return trial.control.ContinuationRuntime._validate_output(self, receipt, request, validator)
        def summary(self): return {"offline_provider_calls": 0}
    monkeypatch.setattr(trial, "ROOT", tmp_path)
    monkeypatch.setattr(trial, "prepare", lambda: None)
    monkeypatch.setattr(trial, "runtime", Runtime)
    result = trial.text()
    assert len(requests) == 2
    writer_req, review_req = requests[0][1], requests[1][1]
    writer_input = json.loads(writer_req["messages"][1]["content"])
    review_input = json.loads(review_req["messages"][1]["content"])
    assert writer_req["output_transport"] == trial.transport.VERSION
    assert writer_input["prior_current_content_revision"]["complete_known_native_performance"] == x["prior_current_content_revision"]["complete_known_native_performance"]
    assert "full_current_script" not in writer_input
    assert writer_input["current_source_catalog"] == {q: trial.source_contract.catalog(x["full_current_script"])[q] for q in trial.REFS}
    assert "output_transport" not in review_req
    assert "prior_current_content_revision" not in review_input
    assert "original_review" not in review_input and "original_automatic_decision_retained" not in review_input
    assert review_input["known_source_repair_requirements"] == x["prior_current_content_revision"]["required_repairs"]
    assert review_input["full_current_script"] == x["full_current_script"]
    assert review_input["current_source_catalog"] == writer_input["current_source_catalog"]
    schema_rows = review_req["structured_schema"]["properties"]["checks"]["prefixItems"]
    assert [q["properties"]["check"]["const"] for q in schema_rows] == trial.REVIEW_CHECKS
    assert len(schema_rows) == 8
    compiled = trial.control.read(tmp_path / "PERFORMANCE_COMPILED.json")
    assert compiled["requires_independent_current_review_criteria_count"] == 8
    assert review_input["current_native_direction_and_performance"] == compiled["native"]
    assert review_input["actual_video_prompt"] == trial.contract.render_prompt(compiled, x["full_current_script"], x["actor_names"])
    assert review_input["actual_video_prompt"].count(writer_input["current_source_catalog"]["B1.S03"]["text"]) == 1
    assert trial.source_contract.catalog(x["full_current_script"])["B2.S01"]["text"] not in review_input["actual_video_prompt"]
    assert not review_input["whole_film_direction_accepted"]
    if review_status == "pass":
        assert result["status"] == "production_text_ready_for_single_continuation"
        h = trial.control.read(tmp_path / "VIDEO_TEXT_HANDOFF.json")
        assert not h["whole_film_direction_accepted"] and not h["actual_video_quality_passed"]
    else:
        assert result["status"] == "production_text_needs_attention"
        assert not (tmp_path / "VIDEO_TEXT_HANDOFF.json").exists()

