"""Targeted patch boundaries and artifact trace, without model/media loading."""
from copy import deepcopy
from pathlib import Path

import pytest

from src.trend_intelligence.content_analysis.artifacts import read_json, sha256, transcript_evidence, write_json
from src.trend_intelligence.content_analysis.targeted_revision import (
    PATCH_SCHEMA, apply_targeted_patch, build_revision_context, repair_source_expression,
)


def expression():
    empty = {"text": "", "evidence_ids": []}
    return {
        "schema": "video_expression_analysis/v1",
        "core_message": {"text": "来源陈述者向法官提出质疑", "evidence_ids": ["A0001"]},
        "expression_modes": [{"mode": "direct_explanation", "evidence_ids": ["A0001"]}],
        "visual_expression": [{"text": "字幕叠在静态背景上", "evidence_ids": ["V0001"]}],
        "audio_expression": [{"text": "以法官不耐烦开场；随后提出质疑", "evidence_ids": ["A0001"]}],
        "conflict": {"status": "not_observed", "characters": [], **{key: deepcopy(empty) for key in
                     ("trigger", "opposition", "stakes", "turning_point", "resolution")}},
        "uncertainties": ["未听音，没有可信说话人分离"],
        "evidence": [{"id": "V0001", "channel": "visual", "start_seconds": 0, "end_seconds": 0,
                      "text": "字幕叠在静态背景上"},
                     {"id": "A0001", "channel": "asr", "start_seconds": .2, "end_seconds": 1.8,
                      "text": "法官我实在听不下去了"}],
    }


def patch(path="/audio_expression/0/text", value="陈述者向法官说自己听不下去了；随后提出质疑"):
    return {"schema": PATCH_SCHEMA, "replacements": [{"path": path, "value": value}]}


def test_only_allowlisted_text_changes_and_original_is_immutable():
    original = expression()
    saved = deepcopy(original)
    revised = apply_targeted_patch(original, patch(), ["/audio_expression/0/text"], duration=2)
    assert original == saved
    assert revised["audio_expression"][0]["evidence_ids"] == original["audio_expression"][0]["evidence_ids"]
    revised["audio_expression"][0]["text"] = original["audio_expression"][0]["text"]
    assert revised == original


@pytest.mark.parametrize("path", ["/evidence/0/text", "/core_message/text", "/audio_expression/1/text",
                                   "/audio_expression/00/text", "/audio_expression", "/schema", ""])
def test_unauthorized_nonexistent_or_noncanonical_paths_rejected(path):
    with pytest.raises(ValueError):
        apply_targeted_patch(expression(), patch(path), ["/audio_expression/0/text"], duration=2)


def test_authorized_field_still_cannot_cite_unknown_evidence():
    with pytest.raises(ValueError, match="invalid or duplicate evidence"):
        apply_targeted_patch(expression(), patch("/audio_expression/0/evidence_ids", ["A9999"]),
                             ["/audio_expression/0/evidence_ids"], duration=2)


def test_replacement_cannot_add_fields_or_change_mode_enumeration():
    with pytest.raises(ValueError, match="structure"):
        apply_targeted_patch(expression(), patch("/audio_expression/0", {
            "text": "陈述者的陈述", "evidence_ids": ["A0001"], "hidden": "extra"}),
            ["/audio_expression/0"], duration=2)
    with pytest.raises(ValueError, match="invalid expression mode"):
        apply_targeted_patch(expression(), patch("/expression_modes/0/mode", "invented_mode"),
                             ["/expression_modes/0/mode"], duration=2)


def test_overlapping_paths_full_rewrite_and_wrong_type_are_rejected():
    with pytest.raises(ValueError, match="overlapping"):
        apply_targeted_patch(expression(), patch(), ["/audio_expression/0", "/audio_expression/0/text"], duration=2)
    with pytest.raises(ValueError, match="only the patch"):
        apply_targeted_patch(expression(), {**patch(), "expression": expression()}, ["/audio_expression/0/text"], duration=2)
    with pytest.raises(ValueError, match="field type"):
        apply_targeted_patch(expression(), patch(value={}), ["/audio_expression/0/text"], duration=2)


def bound_inputs(tmp_path):
    source, frame = tmp_path / "source.mp4", tmp_path / "frame.jpg"
    source.write_bytes(b"opaque source for hash validation, never decoded")
    frame.write_bytes(b"opaque frame, never decoded")
    manifest = {"schema": "local_video_frame_manifest/v2", "source_video_path": str(source),
        "source_video_sha256": sha256(source), "duration_seconds": 2,
        "frames": [{"id": "V0001", "time_seconds": 0, "path": str(frame), "sha256": sha256(frame)}]}
    transcript = {"result": [{"sentence_info": [{"start": 200, "end": 1800, "text": "法官我实在听不下去了"}]}]}
    manifest_path, transcript_path = tmp_path / "manifest.json", tmp_path / "transcript.json"
    write_json(manifest_path, manifest)
    write_json(transcript_path, transcript)
    expr = expression()
    expr["evidence"][1] = transcript_evidence(transcript)[0]
    qwen = {"schema": "local_qwen_frame_analysis/v2", "created_at": "2026-09-09T00:00:00+00:00",
            "source_video_sha256": sha256(source), "frame_manifest_sha256": sha256(manifest_path),
            "transcript_sha256": sha256(transcript_path), "observation_review": None,
            "batches": [{"observations": [{"frame_id": "V0001", "event": "字幕叠在静态背景上"}]}],
            "answer": {"summary": expr["core_message"]["text"], "expression_analysis": expr,
                       "uncertainties": expr["uncertainties"], "visual_timeline": [{"event": "保留原始"}]}}
    qwen_path = tmp_path / "old_qwen.json"
    write_json(qwen_path, qwen)
    review_path = tmp_path / "semantic_review.json"
    write_json(review_path, {"schema": "source_expression_semantic_review/v1", "artifact_sha256": sha256(qwen_path),
                             "source_video_sha256": sha256(source), "decision": "failed"})
    feedback = tmp_path / "feedback.md"
    feedback.write_text("只修复开场称呼对象，不得把第一人称归给法官。", encoding="utf-8")
    return [qwen_path, manifest_path, transcript_path, review_path, feedback, tmp_path / "revision/qwen.json"]


class CapturedTestInference:
    identity = {"provider": "unit_test_only", "model": "no_model_loaded"}

    def __init__(self, response):
        self.response, self.calls = response, 0

    def __call__(self, content):
        self.calls += 1
        assert all(set(row) == {"type", "text"} and row["type"] == "text" for row in content)
        return deepcopy(self.response)


@pytest.mark.parametrize("review_decision", ["failed", "passed_with_limits"])
def test_one_call_trace_and_candidate_preserve_observations(tmp_path, review_decision):
    paths = bound_inputs(tmp_path)
    review = read_json(paths[3])
    review["decision"] = review_decision
    write_json(paths[3], review)
    infer = CapturedTestInference(patch())
    before_sha = sha256(paths[0])
    trace = repair_source_expression(*paths, ["/audio_expression/0/text"], infer=infer)
    old, new = read_json(paths[0]), read_json(paths[-1])
    assert infer.calls == 1
    assert sha256(paths[0]) == before_sha
    assert trace["input_bindings"]["qwen"]["sha256"] == before_sha
    assert trace["output_sha256"] == sha256(paths[-1])
    assert trace["semantic_review_status"] == "not_performed"
    assert new["semantic_status"] == "model_candidate_unreviewed"
    assert new["batches"] == old["batches"]
    assert new["observation_review"] == old["observation_review"]
    assert new["answer"]["visual_timeline"] == old["answer"]["visual_timeline"]
    assert new["answer"]["expression_analysis"]["evidence"] == old["answer"]["expression_analysis"]["evidence"]
    assert not paths[-1].with_name("semantic_review.json").exists()


def test_invalid_candidate_is_preserved_but_not_published_as_qwen(tmp_path):
    paths = bound_inputs(tmp_path)
    invalid = patch("/core_message/text", "越权修改")
    with pytest.raises(ValueError, match="allowlist"):
        repair_source_expression(*paths, ["/audio_expression/0/text"], infer=CapturedTestInference(invalid))
    assert not paths[-1].exists()
    assert read_json(paths[-1].with_name("targeted_revision_patch.json")) == invalid
    assert read_json(paths[-1].with_name("targeted_revision_trace.json"))["status"] == "failed_candidate_preserved"


def test_wrong_bound_review_or_source_stops_before_model(tmp_path):
    paths = bound_inputs(tmp_path)
    review = read_json(paths[3])
    review["artifact_sha256"] = "0" * 64
    write_json(paths[3], review)
    infer = CapturedTestInference(patch())
    with pytest.raises(ValueError, match="binding differs"):
        repair_source_expression(*paths, ["/audio_expression/0/text"], infer=infer)
    assert infer.calls == 0


def test_explicit_context_preserves_whole_rows_declares_omissions_and_original_digest():
    original = expression()
    original["evidence"][0]["text"] = "未选择的完整视觉观察" * 10000
    context, scope = build_revision_context(original, ["/audio_expression/0/text"], ["A0001"])
    assert "expression" not in context
    assert context["evidence"] == [original["evidence"][1]]
    assert context["target_fields"][0]["current_value"] == original["audio_expression"][0]["text"]
    assert scope["mode"] == "explicit_fields_and_selected_evidence"
    assert scope["included_evidence_count"] == 1
    assert scope["omitted_evidence_count"] == 1
    assert scope["evidence_text_truncated"] is False
    assert scope["complete_source_evidence_supplied"] is False
    complete, full_scope = build_revision_context(original, ["/audio_expression/0/text"])
    assert complete["expression"] == original
    assert full_scope["original_expression_sha256"] == scope["original_expression_sha256"]
    assert full_scope["omitted_evidence_count"] == 0


@pytest.mark.parametrize("ids,reason", [(["A9999"], "unknown IDs"),
                                       (["V0001"], "omits original citations"),
                                       (["A0001", "A0001"], "unique"), ([], "nonempty")])
def test_explicit_context_rejects_unknown_missing_original_and_duplicate_ids(ids, reason):
    with pytest.raises(ValueError, match=reason):
        build_revision_context(expression(), ["/audio_expression/0/text"], ids)


def test_projected_revision_cannot_cite_existing_evidence_not_supplied(tmp_path):
    paths = bound_inputs(tmp_path)
    replacement = patch("/audio_expression/0", {"text": "只读指定证据", "evidence_ids": ["V0001"]})
    with pytest.raises(ValueError, match="outside its explicit input context"):
        repair_source_expression(*paths, ["/audio_expression/0"],
            context_evidence_ids=["A0001"], infer=CapturedTestInference(replacement))
    assert not paths[-1].exists()
    trace = read_json(paths[-1].with_name("targeted_revision_trace.json"))
    assert trace["context_scope"]["included_evidence_ids"] == ["A0001"]
    assert trace["status"] == "failed_candidate_preserved"


def test_large_input_requires_explicit_scope_and_omitted_evidence_is_unchanged(tmp_path):
    paths = bound_inputs(tmp_path)
    old = read_json(paths[0])
    large_text = "未经截断的视觉观察。" * 10000
    old["batches"][0]["observations"][0]["event"] = large_text
    old["answer"]["expression_analysis"]["evidence"][0]["text"] = large_text
    write_json(paths[0], old)
    review = read_json(paths[3])
    review["artifact_sha256"] = sha256(paths[0])
    write_json(paths[3], review)
    infer = CapturedTestInference(patch())
    with pytest.raises(ValueError, match="exceeds the full-evidence text budget"):
        repair_source_expression(*paths, ["/audio_expression/0/text"], infer=infer)
    assert infer.calls == 0
    trace = repair_source_expression(*paths, ["/audio_expression/0/text"], infer=infer,
                                     context_evidence_ids=["A0001"])
    new = read_json(paths[-1])
    assert infer.calls == 1
    assert new["batches"] == old["batches"]
    assert new["answer"]["expression_analysis"]["evidence"] == old["answer"]["expression_analysis"]["evidence"]
    assert trace["context_scope"]["omitted_evidence_count"] == 1
    assert trace["input_bindings"]["qwen"]["sha256"] == sha256(paths[0])


def test_explicit_whole_mode_list_can_remove_wrong_mode_but_nothing_else():
    old = expression()
    old["expression_modes"].append({"mode": "text_cards", "evidence_ids": ["V0001"]})
    replacement = [old["expression_modes"][0]]
    revised = apply_targeted_patch(old, patch("/expression_modes", replacement), ["/expression_modes"], duration=2)
    assert revised["expression_modes"] == replacement
    revised["expression_modes"] = old["expression_modes"]
    assert revised == old
    for invalid in ([], replacement * 2, [{"mode": "invented", "evidence_ids": ["A0001"]}]):
        with pytest.raises(ValueError):
            apply_targeted_patch(old, patch("/expression_modes", invalid), ["/expression_modes"], duration=2)
    with pytest.raises(ValueError):
        apply_targeted_patch(old, patch("/evidence", []), ["/evidence"], duration=2)


def test_fresh_visual_parent_is_recorded_as_reused_not_new_inference(tmp_path):
    paths = bound_inputs(tmp_path)
    original = read_json(paths[0])
    original.update(visual_inference_performed=True, visual_inference_batch_count=7,
                    inference_configuration={"quantization": "none", "max_images": 4}, prompt="original visual prompt")
    write_json(paths[0], original)
    review = read_json(paths[3])
    review["artifact_sha256"] = sha256(paths[0])
    write_json(paths[3], review)
    parent_sha = sha256(paths[0])
    repair_source_expression(*paths, ["/audio_expression/0/text"], infer=CapturedTestInference(patch()))
    candidate = read_json(paths[-1])
    assert candidate["visual_inference_performed"] is False
    assert candidate["visual_inference_batch_count"] == 0
    assert candidate["reused_visual_analysis"]["path"] == str(paths[0].resolve())
    assert candidate["reused_visual_analysis"]["sha256"] == parent_sha
    assert candidate["reused_visual_analysis"]["original_inference_configuration"] == original["inference_configuration"]
    assert candidate["batches"] == original["batches"]
    assert sha256(paths[0]) == parent_sha
