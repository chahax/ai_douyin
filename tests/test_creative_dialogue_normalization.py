from copy import deepcopy
import pytest
from src.content_factory.creative_dialogue_normalization import normalize_dialogue_lock_timing


def sample():
    script = {"beats": [{"id": "B03", "dialogue": [
        {"speaker": "林遥", "text": "今天我先回去。"},
        {"speaker": "陈禾", "text": "好。"}]}]}
    value = {"shots": [{"id": "SH03", "beat_id": "B03", "duration_seconds": 8,
                       "visible_performance": "原有表演正文",
                       "dialogue_lock": [
                           {"speaker": "林遥", "text": "今天我先回去。", "start": 1, "end": 3.5},
                           {"speaker": "陈禾", "text": "好。", "start": 4, "end": 5}]}]}
    return value, script


def test_exact_dialogue_strips_only_timing_and_preserves_audit():
    value, script = sample()
    before = deepcopy(value)
    result, changes = normalize_dialogue_lock_timing(value, script)
    assert value == before
    assert result["shots"][0]["dialogue_lock"] == script["beats"][0]["dialogue"]
    assert result["shots"][0]["visible_performance"] == "原有表演正文"
    assert changes == [
        {"path": "shots.0.dialogue_lock.0", "removed_timing": {"start": 1, "end": 3.5}},
        {"path": "shots.0.dialogue_lock.1", "removed_timing": {"start": 4, "end": 5}}]
    again, changes = normalize_dialogue_lock_timing(result, script)
    assert again == result and changes == []


@pytest.mark.parametrize("mutation", ["speaker", "text", "order", "extra", "start_only", "negative", "reverse", "bool", "nan", "beyond_duration"])
def test_not_normalized_if_content_or_timing_is_not_exact(mutation):
    value, script = sample()
    line = value["shots"][0]["dialogue_lock"][0]
    if mutation == "speaker":
        line["speaker"] = "陈禾"
    elif mutation == "text":
        line["text"] = "我不回去。"
    elif mutation == "order":
        value["shots"][0]["dialogue_lock"].reverse()
    elif mutation == "extra":
        line["emotion"] = "伤心"
    elif mutation == "start_only":
        del line["end"]
    elif mutation == "negative":
        line["start"] = -1
    elif mutation == "reverse":
        line["start"] = 4
    elif mutation == "bool":
        line["start"] = True
    elif mutation == "nan":
        line["start"] = float("nan")
    else:
        line["end"] = 9
    result, changes = normalize_dialogue_lock_timing(value, script)
    assert changes == []
    assert result["shots"][0]["dialogue_lock"] == value["shots"][0]["dialogue_lock"]


def test_multi_shot_beat_combines_without_reordering():
    value, script = sample()
    first = value["shots"][0]
    second = deepcopy(first)
    first["dialogue_lock"] = first["dialogue_lock"][:1]
    second["dialogue_lock"] = second["dialogue_lock"][1:]
    value["shots"].append(second)
    result, changes = normalize_dialogue_lock_timing(value, script)
    assert len(changes) == 2
    assert [d for s in result["shots"] for d in s["dialogue_lock"]] == script["beats"][0]["dialogue"]
