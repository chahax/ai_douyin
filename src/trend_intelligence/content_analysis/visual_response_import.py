"""Import verified, completed visual calls without rerunning vision or audio.

This recovers raw image observations only. It does not import later text-only
fusion output, correct model facts, or grant semantic approval.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
from pathlib import Path

from .artifacts import parse_model_json, read_json, sha256
from .hierarchical import VisualBatchCheckpoint, _visual_result


LEGACY_INFERENCE_CONFIGURATION = {
    "quantization": "none",
    "image_pixels": {"shortest_edge": 65536, "longest_edge": 262144},
    "max_new_tokens": 4000,
}


def read_visual_response_plan(plans: list[dict], frame_manifest: dict, *, model_path: str | Path,
                              prompt: str) -> list[dict]:
    """Reuse each captured run under its own exact prompt and inference identity."""
    if not isinstance(plans, list) or not plans:
        raise ValueError("visual response plan must be a nonempty list")
    result = []
    for plan in plans:
        if not isinstance(plan, dict) or not {"directory", "batch_size"} <= set(plan):
            raise ValueError("visual response plan needs directory and original batch size")
        original_prompt = prompt
        prompt_file = Path(plan["prompt_file"]).resolve() if plan.get("prompt_file") else None
        if prompt_file:
            original_prompt = prompt_file.read_text(encoding="utf-8")
        captured = read_visual_responses(plan["directory"], frame_manifest, model_path=model_path,
            prompt=original_prompt, max_images=plan["batch_size"],
            inference_configuration=plan.get("inference_configuration"))
        for row in captured:
            row["provenance"]["original_prompt_sha256"] = hashlib.sha256(original_prompt.encode("utf-8")).hexdigest()
            if prompt_file:
                row["provenance"]["original_prompt_file"] = str(prompt_file)
        result.extend(captured)
    return result


def _configuration(value: dict | None) -> dict:
    if value is None:
        return deepcopy(LEGACY_INFERENCE_CONFIGURATION)
    if not isinstance(value, dict):
        raise ValueError("inference_configuration must be a dictionary")
    pixels = value.get("image_pixels")
    if (not isinstance(value.get("quantization"), str) or not value["quantization"].strip() or
            not isinstance(pixels, dict) or
            any(type(pixels.get(key)) is not int or pixels[key] <= 0 for key in ("shortest_edge", "longest_edge")) or
            type(value.get("max_new_tokens")) is not int or value["max_new_tokens"] < 1):
        raise ValueError("inference_configuration needs quantization, image pixel limits, and max_new_tokens")
    return deepcopy(value)


def read_visual_responses(directory: str | Path, frame_manifest: dict, *,
                          model_path: str | Path, prompt: str, max_images: int,
                          inference_configuration: dict | None = None) -> list[dict]:
    """Read verified original calls without publishing them into another cache.

    ``max_images`` and ``inference_configuration`` describe the captured calls,
    not a subsequent model run. Six-frame bf16 observations can therefore be
    retained as six-frame bf16 evidence while a caller separately infers only
    missing frames with a different configuration. Results are not rewritten.

    Missing chunk files are allowed. Every present image call must be valid;
    the complete validated list is returned only after every file is checked.
    A legacy response with no recorded configuration is accepted solely as the
    original standard bf16 configuration, never relabelled as NF4.
    """
    if isinstance(max_images, bool) or not isinstance(max_images, int) or max_images < 1:
        raise ValueError("max_images must be a positive integer")
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise ValueError("visual response import directory does not exist")
    model_path = Path(model_path).resolve()
    expected_configuration = _configuration(inference_configuration)
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("visual response import needs the exact nonempty prompt")
    if (frame_manifest.get("schema") != "local_video_frame_manifest/v2" or
            sha256(frame_manifest["source_video_path"]) != frame_manifest.get("source_video_sha256")):
        raise ValueError("visual response import source video differs from its manifest")
    frames = frame_manifest.get("frames") or []
    if not frames or any(not isinstance(frame, dict) for frame in frames):
        raise ValueError("visual response import needs source frames")
    frame_ids = [frame["id"] for frame in frames]
    frame_paths = [str(Path(frame["path"]).resolve()) for frame in frames]
    if len(set(frame_ids)) != len(frames) or len(set(frame_paths)) != len(frames):
        raise ValueError("visual response manifest frame IDs and paths must be unique")
    chunks = [frames[offset:offset + max_images] for offset in range(0, len(frames), max_images)]
    chunk_by_paths = {tuple(str(Path(frame["path"]).resolve()) for frame in chunk): chunk for chunk in chunks}
    responses, seen_chunks = [], set()
    for path in sorted(directory.glob("qwen_response_*.json")):
        digest = sha256(path)
        payload = read_json(path)
        inputs = payload.get("input")
        if not isinstance(inputs, list) or not inputs or any(not isinstance(item, dict) for item in inputs):
            raise ValueError(f"invalid captured visual response input: {path.name}")
        if all(item.get("type") == "text" for item in inputs):
            continue  # Fusion may have failed; its answer/model/prompt is irrelevant here.
        if (not isinstance(payload.get("model"), str) or not Path(payload["model"]).is_absolute() or
                str(Path(payload["model"]).resolve()) != str(model_path)):
            raise ValueError(f"visual response model differs from current model: {path.name}")
        if "inference_configuration" in payload:
            if not isinstance(payload["inference_configuration"], dict):
                raise ValueError(f"visual response inference_configuration must be a dictionary: {path.name}")
            captured_configuration = _configuration(payload["inference_configuration"])
            configuration_source = "recorded_response"
        else:
            captured_configuration = _configuration(None)
            configuration_source = "legacy_bf16_default"
        if captured_configuration != expected_configuration:
            raise ValueError(f"visual response inference configuration differs from requested original configuration: {path.name}")
        if inputs[-1] != {"type": "text", "text": prompt}:
            raise ValueError(f"visual response prompt differs from current visual prompt: {path.name}")
        if (len(inputs) < 3 or len(inputs) % 2 != 1 or
                any(inputs[index].get("type") != "text" or
                    set(inputs[index + 1]) != {"type", "image"} or inputs[index + 1]["type"] != "image" or
                    not isinstance(inputs[index + 1]["image"], str) or
                    not Path(inputs[index + 1]["image"]).is_absolute()
                    for index in range(0, len(inputs) - 1, 2))):
            raise ValueError(f"visual response captured input is not ordered frame/text pairs: {path.name}")
        captured_paths = tuple(str(Path(inputs[index]["image"]).resolve()) for index in range(1, len(inputs) - 1, 2))
        chunk = chunk_by_paths.get(captured_paths)
        if chunk is None:
            raise ValueError(f"visual response image paths/order differ from one current regular chunk: {path.name}")
        chunk_ids = tuple(frame["id"] for frame in chunk)
        if chunk_ids in seen_chunks:
            raise ValueError(f"duplicate visual response chunk: {path.name}")
        for index, frame in enumerate(chunk):
            expected = {"type": "text", "text": f"{frame['id']}，{frame['time_seconds']:.3f}秒"}
            if inputs[index * 2] != expected:
                raise ValueError(f"visual response frame ID/decoded time differs from manifest: {path.name}")
            if sha256(frame["path"]) != frame["sha256"]:
                raise ValueError(f"visual response frame bytes differ from manifest: {path.name}")
        result = parse_model_json(payload.get("answer") or "")
        _visual_result(result, chunk)
        created_at = payload.get("created_at")
        if created_at is not None:
            if not isinstance(created_at, str):
                raise ValueError("original response created_at must be a timestamp or absent")
            try:
                parsed = datetime.fromisoformat(created_at)
            except ValueError as exc:
                raise ValueError("original response created_at is invalid") from exc
            if parsed.utcoffset() is None:
                raise ValueError("original response created_at requires an explicit timezone")
        if sha256(path) != digest:
            raise ValueError("raw visual response changed during import validation")
        seen_chunks.add(chunk_ids)
        responses.append({"chunk": chunk, "result": result,
                          "provenance": {"path": str(path.resolve()), "sha256": digest, "frame_ids": list(chunk_ids),
                                         "original_created_at": created_at, "original_model": str(model_path),
                                         "original_max_images": max_images,
                                         "inference_configuration": captured_configuration,
                                         "configuration_source": configuration_source}})
    return responses


def import_visual_responses(directory: str | Path, frame_manifest: dict, cache: VisualBatchCheckpoint, *,
                            model_path: str | Path, prompt: str, max_images: int) -> list[dict]:
    """Populate only the cache matching the captured call's exact configuration.

    The existing interface/return fields remain unchanged. Cross-configuration
    continuation must use ``read_visual_responses`` and keep its provenance,
    rather than writing old observations into a differently labelled cache.
    """
    binding = cache.binding
    if (binding.get("source_sha256") != frame_manifest.get("source_video_sha256") or
            str(Path(binding.get("model") or "").resolve()) != str(Path(model_path).resolve()) or
            binding.get("visual_prompt") != prompt or binding.get("max_images") != max_images):
        raise ValueError("visual response cache binding differs from import inputs")
    responses = read_visual_responses(directory, frame_manifest, model_path=model_path, prompt=prompt,
                                      max_images=max_images,
                                      inference_configuration=binding.get("inference_configuration"))
    for response in responses:
        existing = cache.load(response["chunk"])
        if existing is not None and existing != response["result"]:
            raise ValueError("existing visual checkpoint disagrees with captured response")
    for response in responses:
        cache.save(response["chunk"], response["result"])
    # Preserve the old import API's output contract; new read callers receive
    # the full original inference-configuration provenance above.
    return [{key: response["provenance"][key] for key in
             ("path", "sha256", "frame_ids", "original_created_at")} for response in responses]
