import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("workbench", ROOT / "scripts/build_director_workbench.py")
workbench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workbench)


def card():
    return json.loads((ROOT / "config/director_card.example.json").read_text(encoding="utf-8"))


def test_export_replays_comfy_graph_and_keeps_pending(tmp_path):
    output = tmp_path / "candidate"
    workbench.export(card(), output)
    graph = json.loads((output / "workflow.api.json").read_text(encoding="utf-8"))
    prompt, packet = workbench.node.DouyinDirectorCard().build(**graph["1"]["inputs"])
    assert prompt == (output / "prompt.txt").read_text(encoding="utf-8")
    assert json.loads(packet)["media_review"] == "pending"
    assert json.loads(packet)["production_authorized"] is False
    assert prompt.count("你说的保证，合同里怎么没有？") == 1
    with pytest.raises(FileExistsError):
        workbench.export(card(), output)


@pytest.mark.parametrize("key,value", [("duration_seconds", True), ("duration_seconds", 16),
                                      ("performance", ""), ("continuity", "passed")])
def test_invalid_card_rejected(key, value):
    candidate = card()
    candidate[key] = value
    with pytest.raises(ValueError):
        workbench.node.compile_card(candidate)


def test_continuation_does_not_claim_approval():
    candidate = card()
    candidate["continuity"] = "raw_tail_continuation"
    prompt, packet = workbench.node.compile_card(candidate)
    assert "不复位" in prompt
    assert json.loads(packet)["text_review"] == "pending"
