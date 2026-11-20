from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.trend_intelligence.content_analysis.artifacts import sha256, write_json
from src.trend_intelligence.content_analysis.hierarchical import VisualBatchCheckpoint
from src.trend_intelligence.content_analysis.visual_response_import import (
    LEGACY_INFERENCE_CONFIGURATION, import_visual_responses, read_visual_responses,
    read_visual_response_plan,
)


def _fixture(tmp_path, *, count=5):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source fixture")
    frames = []
    for index in range(count):
        path = tmp_path / f"frame_{index}.jpg"
        path.write_bytes(f"frame {index}".encode())
        frames.append({"id": f"V{index + 1:04d}", "path": str(path.resolve()), "sha256": sha256(path),
                       "time_seconds": float(index), "decoded_frame_index": index * 24, "sampling_reason": "interval"})
    manifest = {"schema": "local_video_frame_manifest/v2", "source_video_path": str(source.resolve()),
                "source_video_sha256": sha256(source), "duration_seconds": count, "frames": frames}
    model_path, prompt = tmp_path / "model", "只观察画面，不推断声音。"
    cache = VisualBatchCheckpoint(tmp_path / "cache", binding={"source_sha256": sha256(source),
             "model": str(model_path.resolve()), "visual_prompt": prompt, "max_images": 2})
    directory = tmp_path / "responses"
    directory.mkdir()

    def raw(chunk, number=1):
        inputs = []
        for frame in chunk:
            inputs.extend([{"type": "text", "text": f"{frame['id']}，{frame['time_seconds']:.3f}秒"},
                           {"type": "image", "image": frame["path"]}])
        inputs.append({"type": "text", "text": prompt})
        value = {"model": str(model_path.resolve()), "input": inputs,
                 "answer": json.dumps({"observations": [{"frame_id": frame["id"], "event": "静态画面。"} for frame in chunk]}, ensure_ascii=False),
                 "created_at": "2026-09-09T13:00:00+00:00"}
        path = directory / f"qwen_response_{number:03d}.json"
        write_json(path, value)
        return path, value

    return manifest, cache, directory, model_path, prompt, raw


def _run(manifest, cache, directory, model_path, prompt):
    return import_visual_responses(directory, manifest, cache, model_path=model_path, prompt=prompt, max_images=2)


def test_plan_preserves_original_prompt_when_missing_frames_use_revised_prompt(tmp_path):
    manifest, cache, directory, model_path, prompt, raw = _fixture(tmp_path)
    path, payload = raw(manifest["frames"][:2])
    original_digest = sha256(path)
    prompt_file = tmp_path / "original_prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")
    plans = [{"directory": str(directory), "batch_size": 2, "prompt_file": str(prompt_file)}]
    rows = read_visual_response_plan(plans, manifest, model_path=model_path, prompt="新的帧编号要求")
    assert rows[0]["result"] == json.loads(payload["answer"])
    assert rows[0]["provenance"]["original_prompt_file"] == str(prompt_file.resolve())
    assert rows[0]["provenance"]["original_prompt_sha256"] == sha256(prompt_file)
    assert sha256(path) == original_digest
    assert cache.load(manifest["frames"][:2]) is None
    prompt_file.write_text("不能伪改原推理提示", encoding="utf-8")
    with pytest.raises(ValueError):
        read_visual_response_plan(plans, manifest, model_path=model_path, prompt=prompt)


def test_partial_completed_chunks_import_without_fusion_or_source_mutation(tmp_path):
    manifest, cache, directory, model_path, prompt, raw = _fixture(tmp_path)
    path, payload = raw(manifest["frames"][:2])
    final_path, final_payload = raw(manifest["frames"][4:], 3)
    fusion_path = directory / "qwen_response_004.json"
    write_json(fusion_path, {"input": [{"type": "text", "text": "failed synthesis input"}],
                             "answer": "unfinished fusion JSON", "model": "irrelevant text model"})
    hashes = {str(item): sha256(item) for item in directory.glob("*.json")}
    provenance = _run(manifest, cache, directory, model_path, prompt)
    assert len(provenance) == 2
    assert provenance[0] == {"path": str(path.resolve()), "sha256": hashes[str(path)],
                              "frame_ids": ["V0001", "V0002"], "original_created_at": payload["created_at"]}
    assert cache.load(manifest["frames"][:2]) == json.loads(payload["answer"])
    assert cache.load(manifest["frames"][2:4]) is None
    assert cache.load(manifest["frames"][4:]) == json.loads(final_payload["answer"])
    assert hashes == {str(item): sha256(item) for item in directory.glob("*.json")}
    assert _run(manifest, cache, directory, model_path, prompt) == provenance


@pytest.mark.parametrize("mutation", ["source_bytes", "frame_bytes", "image_path", "frame_time", "model", "prompt",
                                     "ids", "duplicate_ids", "reorder", "rechunk", "extra_input", "missing_input"])
def test_changed_or_unbound_visual_inputs_are_rejected_before_cache_mutation(tmp_path, mutation):
    manifest, cache, directory, model_path, prompt, raw = _fixture(tmp_path)
    raw(manifest["frames"][:2], 1)  # Earlier valid chunk must not commit on later validation failure.
    path, payload = raw(manifest["frames"][2:4], 2)
    if mutation == "source_bytes":
        Path(manifest["source_video_path"]).write_bytes(b"changed source")
    elif mutation == "frame_bytes":
        Path(manifest["frames"][2]["path"]).write_bytes(b"changed frame")
    elif mutation == "image_path":
        replacement = tmp_path / "copied_frame.jpg"
        replacement.write_bytes(Path(manifest["frames"][2]["path"]).read_bytes())
        payload["input"][1]["image"] = str(replacement.resolve())
    elif mutation == "frame_time":
        payload["input"][0]["text"] = "V0003，9.000秒"
    elif mutation == "model":
        payload["model"] = str((tmp_path / "different_model").resolve())
    elif mutation == "prompt":
        payload["input"][-1]["text"] = "Changed visual prompt"
    elif mutation == "ids":
        payload["answer"] = json.dumps({"observations": [{"frame_id": "V9999", "event": "Wrong frame"}]})
    elif mutation == "duplicate_ids":
        payload["answer"] = json.dumps({"observations": [{"frame_id": "V0003", "event": "Duplicate"}] * 2})
    elif mutation == "reorder":
        payload["input"][:4] = payload["input"][2:4] + payload["input"][:2]
    elif mutation == "rechunk":
        payload["input"] = payload["input"][:2] + payload["input"][-1:]
    elif mutation == "extra_input":
        payload["input"].insert(0, {"type": "audio", "audio": "unapproved.wav"})
    else:
        del payload["input"]
    write_json(path, payload)
    with pytest.raises(ValueError):
        _run(manifest, cache, directory, model_path, prompt)
    assert not list(cache.directory.glob("*.json"))


def test_duplicate_chunk_and_conflicting_existing_checkpoint_fail_closed(tmp_path):
    manifest, cache, directory, model_path, prompt, raw = _fixture(tmp_path)
    path, payload = raw(manifest["frames"][:2], 1)
    duplicate, _ = raw(manifest["frames"][:2], 2)
    with pytest.raises(ValueError, match="duplicate"):
        _run(manifest, cache, directory, model_path, prompt)
    duplicate.unlink()
    existing = json.loads(payload["answer"])
    existing["observations"][0]["event"] = "已有的不同观测"
    cache.save(manifest["frames"][:2], existing)
    with pytest.raises(ValueError, match="disagrees"):
        _run(manifest, cache, directory, model_path, prompt)
    assert cache.load(manifest["frames"][:2]) == existing


@pytest.mark.parametrize("binding_key", ["source_sha256", "model", "visual_prompt", "max_images"])
def test_import_cannot_publish_into_a_differently_bound_cache(tmp_path, binding_key):
    manifest, cache, directory, model_path, prompt, raw = _fixture(tmp_path)
    raw(manifest["frames"][:2])
    cache.binding[binding_key] = 7 if binding_key == "max_images" else "different"
    with pytest.raises(ValueError, match="cache binding"):
        _run(manifest, cache, directory, model_path, prompt)


def test_absent_completion_timestamp_stays_unknown_and_is_not_inferred_from_mtime(tmp_path):
    manifest, cache, directory, model_path, prompt, raw = _fixture(tmp_path)
    path, payload = raw(manifest["frames"][:2])
    del payload["created_at"]
    write_json(path, payload)
    assert _run(manifest, cache, directory, model_path, prompt)[0]["original_created_at"] is None


def test_reader_retains_six_frame_bf16_call_without_rechunking_or_writing_target_cache(tmp_path):
    manifest, cache, directory, model_path, prompt, raw = _fixture(tmp_path, count=8)
    path, payload = raw(manifest["frames"][:6])
    digest = sha256(path)
    rows = read_visual_responses(directory, manifest, model_path=model_path, prompt=prompt, max_images=6)
    assert len(rows) == 1
    assert rows[0]["chunk"] == manifest["frames"][:6]
    assert rows[0]["result"] == json.loads(payload["answer"])
    assert rows[0]["provenance"]["inference_configuration"] == LEGACY_INFERENCE_CONFIGURATION
    assert rows[0]["provenance"]["configuration_source"] == "legacy_bf16_default"
    assert rows[0]["provenance"]["original_created_at"] == payload["created_at"]
    assert sha256(path) == digest
    assert not cache.directory.exists()
    with pytest.raises(ValueError, match="regular chunk"):
        read_visual_responses(directory, manifest, model_path=model_path, prompt=prompt, max_images=2)


@pytest.mark.parametrize("field", ["quantization", "image_pixels", "max_new_tokens"])
def test_reader_cannot_relabel_legacy_bf16_call_with_another_inference_configuration(tmp_path, field):
    manifest, _, directory, model_path, prompt, raw = _fixture(tmp_path)
    raw(manifest["frames"][:2])
    configuration = json.loads(json.dumps(LEGACY_INFERENCE_CONFIGURATION))
    configuration[field] = {"quantization": "nf4", "image_pixels": {"shortest_edge": 16384, "longest_edge": 65536},
                            "max_new_tokens": 2048}[field]
    with pytest.raises(ValueError, match="inference configuration differs"):
        read_visual_responses(directory, manifest, model_path=model_path, prompt=prompt, max_images=2,
                              inference_configuration=configuration)


def test_explicit_nf4_response_requires_matching_original_configuration(tmp_path):
    manifest, cache, directory, model_path, prompt, raw = _fixture(tmp_path)
    path, payload = raw(manifest["frames"][:2])
    nf4 = {"quantization": "nf4", "image_pixels": {"shortest_edge": 16384, "longest_edge": 65536}, "max_new_tokens": 2048}
    payload["inference_configuration"] = nf4
    write_json(path, payload)
    with pytest.raises(ValueError, match="inference configuration differs"):
        read_visual_responses(directory, manifest, model_path=model_path, prompt=prompt, max_images=2)
    rows = read_visual_responses(directory, manifest, model_path=model_path, prompt=prompt, max_images=2,
                                 inference_configuration=nf4)
    assert rows[0]["provenance"]["inference_configuration"] == nf4
    assert rows[0]["provenance"]["configuration_source"] == "recorded_response"
    assert rows[0]["result"] == json.loads(payload["answer"])
    with pytest.raises(ValueError, match="inference configuration differs"):
        _run(manifest, cache, directory, model_path, prompt)
    assert not cache.directory.exists()


def test_import_rejects_legacy_calls_for_an_explicitly_nf4_cache(tmp_path):
    manifest, cache, directory, model_path, prompt, raw = _fixture(tmp_path)
    raw(manifest["frames"][:2])
    cache.binding["inference_configuration"] = {"quantization": "nf4",
        "image_pixels": {"shortest_edge": 16384, "longest_edge": 65536}, "max_new_tokens": 2048}
    with pytest.raises(ValueError, match="inference configuration differs"):
        _run(manifest, cache, directory, model_path, prompt)
    assert not cache.directory.exists()


@pytest.mark.parametrize("invalid", [None, [], "nf4", {"quantization": "nf4"}])
def test_present_invalid_configuration_is_not_treated_as_legacy(tmp_path, invalid):
    manifest, _, directory, model_path, prompt, raw = _fixture(tmp_path)
    path, payload = raw(manifest["frames"][:2])
    payload["inference_configuration"] = invalid
    write_json(path, payload)
    with pytest.raises(ValueError, match="inference_configuration"):
        read_visual_responses(directory, manifest, model_path=model_path, prompt=prompt, max_images=2)
