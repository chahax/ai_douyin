from pathlib import Path
import json
from copy import deepcopy
import pytest
from scripts import evaluate_minimax_scripts as ev
from src.content_factory.creative_writer_prompt_pack import build_writer_prompt


def valid(case):
    return {"title":"测试", "premise":"两人相遇", "selected_candidate_id":"C01", "duration_seconds":27,
            "beats":[{"id":bid,"duration_seconds":9,"event":"相遇","trigger":"看见对方","before":"两人站定","during":"一人侧身","after":"另一人通过","dialogue":[]} for bid in case["required_beat_ids"]]}


def test_modules_are_selected_and_deduplicated():
    text=build_writer_prompt(["silent","silent"])
    assert text.count("【silent】")==1
    assert "【ensemble】" not in text
    assert "【contract】" in text
    with pytest.raises(ValueError,match="未知"):
        build_writer_prompt(["missing"])


def test_real_malformed_outputs_remain_errors():
    root=Path(__file__).resolve().parents[1]/"data/model_evaluations/minimax_scripts_20260927"
    cases=json.loads(ev.CASES.read_text(encoding="utf-8"))["cases"]
    for index in (0,2):
        case=cases[index]
        value=json.loads((root/"baseline"/case["id"]/"script.json").read_text(encoding="utf-8"))
        snapshot=deepcopy(value)
        assert ev.structural_errors(value,case)
        assert value==snapshot


def test_machine_gate_catches_forbidden_dialogue_and_duration(monkeypatch):
    monkeypatch.setattr(ev,"validate_script",lambda *a:None)
    case=json.loads(ev.CASES.read_text(encoding="utf-8"))["cases"][3]
    value=valid(case)
    assert not ev.machine_review(value,case)["structural_errors"]
    value["beats"][0]["dialogue"]=[{"speaker":"江遥","text":"请进"}]
    value["duration_seconds"]=99
    result=ev.machine_review(value,case)
    assert set(result["requirement_errors"])=={"declared_duration_not_sum","silent_case_has_dialogue"}
    value["beats"][0]["dialogue"]=""
    assert "beat_0_dialogue_type" in ev.structural_errors(value,case)


def test_call_budget_and_pending_receipt_never_send(monkeypatch,tmp_path):
    def forbidden():
        raise AssertionError("must not instantiate remote client")
    monkeypatch.setattr(ev,"CreativeRoleClients",forbidden)
    with pytest.raises(RuntimeError,match="上限"):
        ev.request_once(tmp_path/"call.json","writer",[],None,0,tmp_path)
    pending={"status":"pending_response","request":{"role_route":"writer","messages":[],"schema":None,"temperature":0.2,"max_tokens":6000,"thinking":"disabled"}}
    path=tmp_path/"call.json"
    path.write_text(json.dumps(pending),encoding="utf-8")
    with pytest.raises(RuntimeError,match="未决"):
        ev.request_once(path,"writer",[],None,14,tmp_path)
