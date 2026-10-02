from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.trend_intelligence.content_analysis.artifacts import sha256
from src.trend_intelligence.content_analysis.hierarchical import VisualBatchCheckpoint, synthesize_expression, _validate_summary


def _evidence(count=10, length=90):
    return [{"id": f"V{index:04d}", "channel": "visual", "start_seconds": float(index),
             "end_seconds": float(index), "text": f"原始画面{index}：" + "可见纸张" * length}
            for index in range(count)]


def _input_rows(text):
    marker = "{\"candidate_summaries\":"
    if marker in text:
        return json.JSONDecoder().raw_decode(text[text.index(marker):])[0]["raw_evidence"]
    marker = "原始媒体证据：\n" if "原始媒体证据：\n" in text else "媒体证据：\n"
    return json.JSONDecoder().raw_decode(text.split(marker, 1)[1])[0]


def _answer(rows):
    ref = rows[0]["id"]
    return {"schema": "video_expression_analysis/v1", "core_message": {"text": "展示纸张", "evidence_ids": [ref]},
            "expression_modes": [{"mode": "prop_demonstration", "evidence_ids": [ref]}],
            "visual_expression": [{"text": "纸张可见", "evidence_ids": [ref]}], "audio_expression": [],
            "conflict": {"status": "not_observed"}, "uncertainties": []}


def _infer_recorder(prompts):
    def infer(content):
        text = content[0]["text"]
        prompts.append(text)
        rows = _input_rows(text)
        if text.startswith("FINAL"):
            return _answer(rows)
        return {"claims": [{"text": "画面展示纸张", "evidence_ids": [rows[0]["id"]]}], "uncertainties": []}
    return infer


def test_long_video_synthesis_is_bounded_and_preserves_all_original_evidence(tmp_path):
    rows, prompts = _evidence(65, 40), []
    result, audit = synthesize_expression(rows, 80, infer=_infer_recorder(prompts), synthesis_prompt="FINAL",
                                         checkpoint_dir=tmp_path, binding={"source": "original"}, max_input_chars=2400)
    assert audit["strategy"] == "chronological_hierarchical"
    assert audit["leaf_count"] > 10
    assert audit["merge_levels"] >= 1
    assert max(map(len, prompts)) <= 2400
    assert result["evidence"] == rows
    assert audit["leaf_covered_evidence_ids"] == [row["id"] for row in rows]
    assert any("分层" in item for item in result["uncertainties"])
    leaf_ids = [ref for stage in audit["stages"] if stage["stage"].startswith("leaf") for ref in stage["input_evidence_ids"]]
    assert set(leaf_ids) == {row["id"] for row in rows}
    assert len(leaf_ids) == len(rows)


def test_completed_synthesis_stages_resume_without_model_calls(tmp_path):
    rows, prompts = _evidence(15, 30), []
    kwargs = dict(synthesis_prompt="FINAL", checkpoint_dir=tmp_path, binding={"source": "original"}, max_input_chars=2400)
    first, _ = synthesize_expression(rows, 30, infer=_infer_recorder(prompts), **kwargs)
    second, audit = synthesize_expression(rows, 30, infer=lambda _: pytest.fail("completed stage was rerun"), **kwargs)
    assert first == second
    assert all(stage["reused"] for stage in audit["stages"])


def test_partial_synthesis_failure_resumes_only_unfinished_stages(tmp_path):
    rows, prompts = _evidence(15, 30), []
    good = _infer_recorder(prompts)
    def fail_later(content):
        if len(prompts) == 2:
            raise RuntimeError("simulated interruption")
        return good(content)
    kwargs = dict(synthesis_prompt="FINAL", checkpoint_dir=tmp_path, binding={}, max_input_chars=2400)
    with pytest.raises(RuntimeError, match="interruption"):
        synthesize_expression(rows, 30, infer=fail_later, **kwargs)
    _, audit = synthesize_expression(rows, 30, infer=good, **kwargs)
    assert sum(stage["reused"] for stage in audit["stages"]) == 2


def test_stage_cannot_cite_real_id_from_another_segment(tmp_path):
    rows, calls = _evidence(20, 30), []
    def bad(content):
        calls.append(content)
        return {"claims": [{"text": "内容", "evidence_ids": [rows[-1]["id"]]}]}
    with pytest.raises(ValueError, match="not in its input"):
        synthesize_expression(rows, 30, infer=bad, synthesis_prompt="FINAL", checkpoint_dir=tmp_path,
                              binding={}, max_input_chars=2400)
    assert len(calls) == 2
    assert not list(tmp_path.glob("*.json"))


def test_final_cannot_cite_evidence_absent_from_its_actual_reduced_input(tmp_path):
    rows, calls = _evidence(20, 30), []
    good = _infer_recorder(calls)
    def bad_final(content):
        if content[0]["text"].startswith("FINAL"):
            visible = {row["id"] for row in _input_rows(content[0]["text"])}
            absent = next(row for row in rows if row["id"] not in visible)
            return _answer([absent])
        return good(content)
    with pytest.raises(ValueError, match="not in its input"):
        synthesize_expression(rows, 30, infer=bad_final, synthesis_prompt="FINAL", checkpoint_dir=tmp_path,
                              binding={}, max_input_chars=2400)


def test_direct_short_synthesis_does_not_add_summarization(tmp_path):
    rows, prompts = _evidence(2, 1), []
    expression, audit = synthesize_expression(rows, 10, infer=_infer_recorder(prompts), synthesis_prompt="FINAL",
                                             checkpoint_dir=tmp_path, binding={})
    assert len(prompts) == 1
    assert audit["strategy"] == "direct"
    assert expression["evidence"] == rows


def test_checkpoint_result_tampering_is_not_silently_reused(tmp_path):
    rows = _evidence(2, 1)
    kwargs = dict(synthesis_prompt="FINAL", checkpoint_dir=tmp_path, binding={})
    synthesize_expression(rows, 10, infer=_infer_recorder([]), **kwargs)
    path = next(tmp_path.glob("*.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["result"]["core_message"]["text"] = "伪造"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="hash changed"):
        synthesize_expression(rows, 10, infer=lambda _: pytest.fail("tampering triggered inference"), **kwargs)


def test_huge_single_asr_evidence_is_rejected_without_truncation(tmp_path):
    with pytest.raises(ValueError, match="split at real ASR timestamps"):
        synthesize_expression(_evidence(1, 3000), 10, infer=lambda _: pytest.fail("oversized input inferred"),
                              synthesis_prompt="FINAL", checkpoint_dir=tmp_path, binding={})


def _frame(tmp_path):
    path = tmp_path / "frame.jpg"
    path.write_bytes(b"fixture image bytes")
    return {"id": "V0001", "path": str(path), "sha256": sha256(path), "time_seconds": 0.0}


def test_visual_checkpoint_reuses_only_unchanged_bound_bytes(tmp_path):
    frame = _frame(tmp_path)
    cache = VisualBatchCheckpoint(tmp_path / "cache", binding={"prompt": "v1", "source_sha256": "source"})
    result = {"observations": [{"frame_id": "V0001", "event": "桌上纸张"}]}
    assert cache.load([frame]) is None
    cache.save([frame], result)
    assert cache.load([frame]) == result
    other = VisualBatchCheckpoint(tmp_path / "cache", binding={"prompt": "v2", "source_sha256": "source"})
    assert other.load([frame]) is None
    Path(frame["path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="bytes changed"):
        cache.load([frame])


def test_visual_checkpoint_rejects_duplicate_ids_even_if_dict_would_hide_them(tmp_path):
    frame = _frame(tmp_path)
    cache = VisualBatchCheckpoint(tmp_path / "cache", binding={})
    with pytest.raises(ValueError, match="exactly once"):
        cache.save([frame], {"observations": [{"frame_id": "V0001", "event": "一"},
                                               {"frame_id": "V0001", "event": "二"}]})


def test_visual_checkpoint_reuses_same_decoded_content_at_new_attempt_path(tmp_path):
    frame = _frame(tmp_path)
    frame.update(decoded_frame_index=20, sampling_reason="interval")
    cache = VisualBatchCheckpoint(tmp_path / "cache", binding={"source_sha256": "source", "prompt": "v1"})
    result = {"observations": [{"frame_id": "V0001", "event": "桌上纸张"}]}
    cache.save([frame], result)
    copied_path = tmp_path / "next_attempt" / "frame.jpg"
    copied_path.parent.mkdir()
    copied_path.write_bytes(Path(frame["path"]).read_bytes())
    copied = {**frame, "path": str(copied_path)}
    assert cache.load([copied]) == result
    assert cache.load([{**copied, "decoded_frame_index": 21}]) is None
    assert cache.load([{**copied, "time_seconds": 1.0}]) is None
    copied_path.write_bytes(b"changed copied image")
    with pytest.raises(ValueError, match="bytes changed"):
        cache.load([copied])


def test_configured_claim_reference_budget_accepts_four_real_refs_without_clipping(tmp_path):
    rows, prompts = _evidence(40, 1), []
    def infer(content):
        text = content[0]["text"]
        prompts.append(text)
        visible = _input_rows(text)
        if text.startswith("FINAL"):
            return _answer(visible)
        return {"claims": [{"text": "纸张各步骤连续展示", "evidence_ids": [row["id"] for row in visible[:4]]}], "uncertainties": []}
    kwargs = dict(synthesis_prompt="FINAL", max_input_chars=2400, binding={})
    with pytest.raises(ValueError, match="too many references"):
        synthesize_expression(rows, 50, infer=infer, checkpoint_dir=tmp_path / "default", **kwargs)
    assert len(prompts) == 2
    prompts.clear()
    expression, audit = synthesize_expression(rows, 50, infer=infer, checkpoint_dir=tmp_path / "configured",
                                             max_claim_refs=8, **kwargs)
    assert audit["strategy"] == "chronological_hierarchical"
    assert max(map(len, prompts)) <= 2400
    assert expression["evidence"] == rows
    assert any("最多8个不同evidence_ids" in prompt for prompt in prompts)
    leaf = json.loads(Path(audit["stages"][0]["checkpoint_path"]).read_text(encoding="utf-8"))
    assert len(leaf["result"]["claims"][0]["evidence_ids"]) == 4
    assert leaf["identity"]["binding"]["max_claim_refs"] == 8


def test_configured_claim_character_limit_accepts_full_text_without_clipping():
    value = {"claims": [{"text": "甲" * 360, "evidence_ids": ["V0001"]}], "uncertainties": []}
    assert _validate_summary(value, {"V0001"}, max_claim_chars=360) is value
    assert len(value["claims"][0]["text"]) == 360
    assert value["claims"][0]["evidence_ids"] == ["V0001"]
    with pytest.raises(ValueError, match="1 to 120 characters"):
        _validate_summary(value, {"V0001"})
    value["claims"][0]["text"] += "乙"
    with pytest.raises(ValueError, match="1 to 360 characters"):
        _validate_summary(value, {"V0001"}, max_claim_chars=360)


def test_claim_character_budget_reaches_leaf_merge_validation_and_checkpoint(tmp_path):
    rows, prompts = _evidence(65, 40), []

    def infer(content):
        text = content[0]["text"]
        prompts.append(text)
        visible = _input_rows(text)
        if text.startswith("FINAL"):
            return _answer(visible)
        return {"claims": [{"text": "完整保留候选主张" * 30, "evidence_ids": [visible[0]["id"]]}], "uncertainties": []}

    result, audit = synthesize_expression(rows, 80, infer=infer, synthesis_prompt="FINAL", checkpoint_dir=tmp_path,
                                         binding={}, max_input_chars=3000, max_claim_chars=360)
    assert audit["strategy"] == "chronological_hierarchical"
    assert audit["merge_levels"] >= 1
    assert result["evidence"] == rows
    assert max(map(len, prompts)) <= 3000
    assert all("最多360字" in prompt and "最多120字" not in prompt for prompt in prompts if not prompt.startswith("FINAL"))
    for stage in audit["stages"]:
        payload = json.loads(Path(stage["checkpoint_path"]).read_text(encoding="utf-8"))
        assert payload["identity"]["binding"]["max_claim_chars"] == 360
        if stage["stage"] != "final":
            assert payload["result"]["claims"][0]["text"] == "完整保留候选主张" * 30
