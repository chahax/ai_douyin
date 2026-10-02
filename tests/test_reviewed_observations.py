from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.trend_intelligence.content_analysis.artifacts import (
    read_json, sha256, transcript_evidence, verify_expression_evidence, write_json,
)
from src.trend_intelligence.content_analysis.reviewed_observations import apply_reviewed_observations


def _fixture(tmp_path):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"test source bytes")
    frames = []
    for index in range(1, 4):
        frame = tmp_path / f"frame_{index}.jpg"
        frame.write_bytes(f"test frame {index}".encode())
        frames.append({"id": f"V{index:04d}", "path": str(frame.resolve()), "sha256": sha256(frame),
                       "time_seconds": float(index - 1)})
    manifest = {"schema": "local_video_frame_manifest/v2", "source_video_path": str(video.resolve()),
                "source_video_sha256": sha256(video), "duration_seconds": 2, "frames": frames}
    manifest_path = tmp_path / "frame_manifest.json"
    write_json(manifest_path, manifest)
    batches = [{"observations": [{"frame_id": frame["id"], "event": "讲解者正在操作纸张。"} for frame in frames]}]
    original_path = tmp_path / "original_qwen.json"
    write_json(original_path, {"schema": "local_qwen_frame_analysis/v2", "source_video_sha256": sha256(video),
                               "frame_manifest_sha256": sha256(manifest_path), "batches": batches})
    review = {
        "schema": "source_visual_observation_review/v1", "source_video_sha256": sha256(video),
        "frame_manifest": {"path": str(manifest_path.resolve()), "sha256": sha256(manifest_path)},
        "original_artifacts": [{"kind": "qwen_analysis", "path": str(original_path.resolve()), "sha256": sha256(original_path)}],
        "corrections": [{"frame_id": "V0002", "frame_sha256": frames[1]["sha256"], "time_seconds": 1.0,
                         "original_text": "讲解者正在操作纸张。", "corrected_text": "插入特写中一只手接触纸张，无法归属给主画面讲解者。",
                         "review_reason": "实际查看帧，需区分主画面与插入画面。", "reviewer": "agent:frame_reviewer",
                         "reviewed_at": "2026-09-09T18:30:00+08:00"}],
        "scope_limitations": ["只检查列明的单帧可见事实；不证明连续动作、声音或核心结论。"],
    }
    review_path = tmp_path / "observation_review.json"
    write_json(review_path, review)
    return manifest, batches, review, review_path


def test_review_changes_only_effective_text_and_preserves_raw_artifacts(tmp_path):
    manifest, batches, review, review_path = _fixture(tmp_path)
    raw_before = copy.deepcopy(batches)
    artifact_path = review["original_artifacts"][0]["path"]
    artifact_hash = sha256(artifact_path)
    result = apply_reviewed_observations(manifest, batches, review_path)
    assert result["evidence"][1]["text"] == review["corrections"][0]["corrected_text"]
    assert result["evidence"][0]["text"] == batches[0]["observations"][0]["event"]
    assert [item["id"] for item in result["evidence"]] == ["V0001", "V0002", "V0003"]
    assert [(item["start_seconds"], item["end_seconds"]) for item in result["evidence"]] == [(0, 0), (1, 1), (2, 2)]
    assert result["review"] == {"path": str(review_path.resolve()), "sha256": sha256(review_path)}
    assert batches == raw_before and sha256(artifact_path) == artifact_hash
    assert apply_reviewed_observations(manifest, batches, result["review"]) == result


def test_corrected_evidence_requires_explicit_review_and_asr_is_still_immutable(tmp_path):
    manifest, batches, review, review_path = _fixture(tmp_path)
    result = apply_reviewed_observations(manifest, batches, review_path)
    transcript = {"result": [{"text": "合同", "timestamp": [[100, 300], [300, 500]]}]}
    expression = {"evidence": result["evidence"] + transcript_evidence(transcript)}
    with pytest.raises(ValueError, match="observation"):
        verify_expression_evidence(expression, manifest, transcript, visual_batches=batches)
    verify_expression_evidence(expression, manifest, transcript, visual_batches=batches, observation_review=result["review"])
    expression["evidence"][-1]["text"] = "不属于原片的对白"
    with pytest.raises(ValueError, match="ASR evidence"):
        verify_expression_evidence(expression, manifest, transcript, visual_batches=batches, observation_review=result["review"])


@pytest.mark.parametrize("mutation", ["source_sha", "manifest_sha", "manifest_body", "frame_sha", "frame_time",
                                     "original_text", "asr_id", "new_frame_id", "duplicate", "extra_channel",
                                     "missing_reason", "naive_time", "empty_limitations", "raw_batch_text"])
def test_unbound_or_out_of_scope_corrections_are_rejected(tmp_path, mutation):
    manifest, batches, review, review_path = _fixture(tmp_path)
    row = review["corrections"][0]
    if mutation == "source_sha":
        review["source_video_sha256"] = "0" * 64
    elif mutation == "manifest_sha":
        review["frame_manifest"]["sha256"] = "0" * 64
    elif mutation == "manifest_body":
        manifest["frames"][1]["time_seconds"] = 1.5
    elif mutation == "frame_sha":
        row["frame_sha256"] = "0" * 64
    elif mutation == "frame_time":
        row["time_seconds"] = 1.5
    elif mutation == "original_text":
        row["original_text"] = "替换原始模型观测"
    elif mutation == "asr_id":
        row["frame_id"] = "A0001"
    elif mutation == "new_frame_id":
        row["frame_id"] = "V9999"
    elif mutation == "duplicate":
        review["corrections"].append(copy.deepcopy(row))
    elif mutation == "extra_channel":
        row["channel"] = "asr"
    elif mutation == "missing_reason":
        row["review_reason"] = ""
    elif mutation == "naive_time":
        row["reviewed_at"] = "2026-09-09T18:30:00"
    elif mutation == "empty_limitations":
        review["scope_limitations"] = []
    else:
        batches[0]["observations"][1]["event"] = "篡改的原始观测"
    write_json(review_path, review)
    with pytest.raises(ValueError):
        apply_reviewed_observations(manifest, batches, review_path)


@pytest.mark.parametrize("target", ["source", "frame", "original", "persisted_review"])
def test_post_review_artifact_tampering_is_rejected(tmp_path, target):
    manifest, batches, review, review_path = _fixture(tmp_path)
    result = apply_reviewed_observations(manifest, batches, review_path)
    path = {"source": manifest["source_video_path"], "frame": manifest["frames"][1]["path"],
            "original": review["original_artifacts"][0]["path"], "persisted_review": str(review_path)}[target]
    Path(path).write_bytes(Path(path).read_bytes() + b" ")
    with pytest.raises(ValueError):
        apply_reviewed_observations(manifest, batches, result["review"])


def test_individual_raw_qwen_response_can_anchor_reviewed_frames(tmp_path):
    manifest, batches, review, review_path = _fixture(tmp_path)
    original_path = tmp_path / "qwen_response_001.json"
    raw = {"answer": json.dumps(batches[0], ensure_ascii=False), "input": []}
    for frame in manifest["frames"]:
        raw["input"].extend([{"type": "text", "text": f"{frame['id']}，{frame['time_seconds']:.3f}秒"},
                             {"type": "image", "image": frame["path"]}])
    raw["input"].append({"type": "text", "text": "Observe only visible facts"})
    write_json(original_path, raw)
    review["original_artifacts"] = [{"kind": "qwen_visual_response", "path": str(original_path.resolve()), "sha256": sha256(original_path)}]
    write_json(review_path, review)
    assert apply_reviewed_observations(manifest, batches, review_path)["evidence"][1]["text"] == review["corrections"][0]["corrected_text"]
    raw["input"][0]["text"] = "V0002，9.000秒"
    write_json(original_path, raw)
    review["original_artifacts"][0]["sha256"] = sha256(original_path)
    write_json(review_path, review)
    with pytest.raises(ValueError, match="image/time binding"):
        apply_reviewed_observations(manifest, batches, review_path)


def test_raw_response_subset_cannot_self_certify_other_observations(tmp_path):
    manifest, batches, review, review_path = _fixture(tmp_path)
    frame = manifest["frames"][1]
    original_path = tmp_path / "qwen_response_001.json"
    write_json(original_path, {"answer": json.dumps({"observations": [batches[0]["observations"][1]]}),
               "input": [{"type": "text", "text": "V0002，1.000秒"}, {"type": "image", "image": frame["path"]}]})
    review["original_artifacts"] = [{"kind": "qwen_visual_response", "path": str(original_path.resolve()), "sha256": sha256(original_path)}]
    write_json(review_path, review)
    with pytest.raises(ValueError, match="every raw frame observation"):
        apply_reviewed_observations(manifest, batches, review_path)


def test_review_cannot_disable_visual_timestamp_or_id_validation(tmp_path):
    manifest, batches, review, review_path = _fixture(tmp_path)
    effective = apply_reviewed_observations(manifest, batches, review_path)
    expression = {"evidence": effective["evidence"]}
    expression["evidence"][1]["start_seconds"] = 1.1
    with pytest.raises(ValueError, match="timestamp"):
        verify_expression_evidence(expression, manifest, {}, visual_batches=batches, observation_review=effective["review"])
    with pytest.raises(ValueError, match="original visual batches"):
        verify_expression_evidence(expression, manifest, {}, observation_review=effective["review"])
