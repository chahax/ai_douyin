"""Render the original 404263-inspired story with local LTX or Wan workflows.

The reference video is never submitted to either renderer.  Both workflows
consume only the reviewed original anchors under the QA package.  Outputs are
non-publishable, resumable, and accompanied by workflow/evidence manifests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / r"data\fanqie_promotion\scene_plans\reference_404263_original_multiflow_v1.json"
DEFAULT_QA_ROOT = ROOT / r"data\qa\reference_404263_multiflow_20260825"
DEFAULT_P0_ROOT = ROOT.parent / "ai_douyin_p0"
DEFAULT_CAST_MASTER = (
    ROOT
    / r"data\qa\reference_404263_multiflow_20260825\anchors\cast_master_v1.png"
)
COMFY_INPUT = Path(r"D:\IT\AI_vido\ComfyUI\input")
COMFY_OUTPUT = Path(r"D:\IT\AI_vido\ComfyUI\output")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def preserve_unselected_shots(
    report: dict[str, object],
    prior: dict[str, dict[str, object]],
    selected_ids: set[str],
) -> None:
    """Keep auditable rows for scenes not touched by an incremental render."""
    report["shots"] = [row for scene_id, row in prior.items() if scene_id not in selected_ids]


def scene_fingerprint(*, workflow: str, scene: dict[str, object], anchor: Path) -> str:
    """Bind a cached clip to its workflow, full scene contract, and anchor bytes."""
    payload = {
        "workflow": workflow,
        "scene": scene,
        "anchor_sha256": sha256(anchor),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest().upper()


def scene_anchor(scene: dict[str, object], anchors: Path) -> Path:
    """Resolve a generation-specific anchor before the edit/deterministic anchor."""
    explicit = str(scene.get("generation_anchor") or scene.get("anchor") or "").strip()
    if explicit:
        candidate = Path(explicit)
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        return candidate.resolve()
    return (anchors / f"{scene['id']}.png").resolve()


def scene_duration(scene: dict[str, object]) -> float:
    value = scene.get("duration", scene.get("duration_seconds"))
    if value is None:
        raise ValueError(f"scene {scene.get('id')} has no duration")
    return float(value)


def generation_duration(scene: dict[str, object], workflow: str) -> float:
    """Keep native clips inside reviewed frame profiles; edits fill long beats."""
    requested = scene_duration(scene)
    ceiling = 5.0 if workflow == "ltx" else 6.0
    return min(requested, ceiling)


def scene_positive(scene: dict[str, object]) -> str:
    legacy = str(scene.get("visual_prompt") or "").strip()
    if legacy:
        return legacy
    return " ".join(
        [
            "Photorealistic original Chinese anti-fraud streaming drama, vertical 9:16.",
            "Start from the supplied approved keyframe and preserve every character identity, clothing, prop count and room geometry.",
            f"Action path: {scene.get('action', '')}.",
            f"Expression path: {scene.get('expression', '')}.",
            f"Gaze path: {scene.get('gaze', '')}.",
            f"Required final pose: {scene.get('end_pose', '')}.",
            "Keep the exact initial framing for the entire generated clip: locked camera, no zoom, no crop, no reframing and no close-up.",
            "Keep exposure, practical lights, white balance, contrast and color temperature exactly constant from first frame to last frame.",
            "The plan's edit-cut list belongs to post-production and must never be performed inside this generated shot.",
            "Perform one continuous physically plausible action at natural speed; restrained acting; no internal cuts.",
        ]
    )


def scene_negative(scene: dict[str, object], global_negative: str) -> str:
    legacy = str(scene.get("negative_prompt") or "").strip()
    hard = ", ".join(str(value).replace("_", " ") for value in scene.get("hard_reject", []))
    return ", ".join(value for value in [legacy, global_negative, hard] if value)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def probe(path: Path) -> dict[str, object]:
    import subprocess

    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,avg_frame_rate,nb_frames:format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    payload = json.loads(result.stdout)
    stream = payload["streams"][0]
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": stream["avg_frame_rate"],
        "frame_count": int(stream.get("nb_frames") or 0),
        "duration_seconds": float(payload["format"]["duration"]),
    }


def request_json(url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())


def wait_history(base_url: str, prompt_id: str, timeout_seconds: int) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        result = request_json(f"{base_url}/history/{prompt_id}")
        if prompt_id in result:
            item = result[prompt_id]
            status = item.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(json.dumps(status, ensure_ascii=False))
            return item
        time.sleep(3)
    raise TimeoutError(prompt_id)


def wan_frame_count(duration_seconds: float) -> int:
    if duration_seconds <= 3.4:
        return 49
    if duration_seconds <= 4.5:
        return 65
    return 97


def wan_graph(
    *,
    image_name: str,
    positive: str,
    negative: str,
    seed: int,
    length: int,
    prefix: str,
) -> dict[str, object]:
    return {
        "1": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 0], "text": positive}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 0], "text": negative}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "wan2.2_vae.safetensors"}},
        "5": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "8": {"class_type": "Wan22ImageToVideoLatent", "inputs": {"vae": ["4", 0], "width": 416, "height": 736, "length": length, "batch_size": 1, "start_image": ["5", 0]}},
        "9": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.2_ti2v_5B_fp16.safetensors", "weight_dtype": "default"}},
        "15": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["9", 0], "shift": 8.0}},
        "10": {"class_type": "KSampler", "inputs": {"model": ["15", 0], "seed": seed, "steps": 20, "cfg": 4.0, "sampler_name": "uni_pc", "scheduler": "simple", "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["8", 0], "denoise": 1.0}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["4", 0]}},
        "13": {"class_type": "CreateVideo", "inputs": {"images": ["12", 0], "fps": 16.0}},
        "14": {"class_type": "SaveVideo", "inputs": {"video": ["13", 0], "filename_prefix": prefix, "format": "mp4", "codec": "h264"}},
    }


def wan_animate_frame_count(duration_seconds: float) -> int:
    """Return a reviewed 16fps 4n+1 profile capped for a 16GB GPU."""
    raw = min(81, max(17, int(round(duration_seconds * 16.0))))
    return max(17, ((raw - 1) // 4) * 4 + 1)


def wan_animate_graph(
    *,
    image_name: str,
    driver_name: str,
    positive: str,
    negative: str,
    seed: int,
    length: int,
    prefix: str,
    width: int = 320,
    height: int = 576,
) -> dict[str, object]:
    """Native Wan2.2 Animate Move graph; reference face pixels are disconnected."""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors", "strength_model": 1.0}},
        "3": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["2", 0], "shift": 8.0}},
        "4": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": positive}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": negative}},
        "7": {"class_type": "VAELoader", "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
        "8": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": "clip_vision_h.safetensors"}},
        "9": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "10": {"class_type": "CLIPVisionEncode", "inputs": {"clip_vision": ["8", 0], "image": ["9", 0], "crop": "none"}},
        "11": {"class_type": "LoadVideo", "inputs": {"file": driver_name}},
        "12": {"class_type": "GetVideoComponents", "inputs": {"video": ["11", 0]}},
        "13": {"class_type": "ImageScale", "inputs": {"image": ["12", 0], "upscale_method": "lanczos", "width": width, "height": height, "crop": "disabled"}},
        "14": {"class_type": "DWPreprocessor", "inputs": {"image": ["13", 0], "detect_hand": "enable", "detect_body": "enable", "detect_face": "enable", "resolution": max(width, height), "bbox_detector": "yolox_l.onnx", "pose_estimator": "dw-ll_ucoco_384_bs5.torchscript.pt", "scale_stick_for_xinsr_cn": "disable"}},
        "15": {"class_type": "WanAnimateToVideo", "inputs": {"positive": ["5", 0], "negative": ["6", 0], "vae": ["7", 0], "width": width, "height": height, "length": length, "batch_size": 1, "continue_motion_max_frames": 5, "video_frame_offset": 0, "clip_vision_output": ["10", 0], "reference_image": ["9", 0], "pose_video": ["14", 0]}},
        "16": {"class_type": "KSampler", "inputs": {"model": ["3", 0], "seed": seed, "steps": 6, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "positive": ["15", 0], "negative": ["15", 1], "latent_image": ["15", 2], "denoise": 1.0}},
        "17": {"class_type": "TrimVideoLatent", "inputs": {"samples": ["16", 0], "trim_amount": ["15", 3]}},
        "18": {"class_type": "VAEDecode", "inputs": {"samples": ["17", 0], "vae": ["7", 0]}},
        "19": {"class_type": "ImageFromBatch", "inputs": {"image": ["18", 0], "batch_index": ["15", 4], "length": 4096}},
        "20": {"class_type": "SaveImage", "inputs": {"images": ["19", 0], "filename_prefix": prefix}},
    }


def wan_animate_positive(scene: dict[str, object], action: str) -> str:
    return " ".join(
        [
            "Photorealistic original Chinese anti-fraud streaming drama, vertical 9:16.",
            "Animate only the single dominant actor shown in the supplied original keyframe.",
            f"One continuous action: {action}.",
            f"Expression remains restrained: {scene.get('expression', '')}.",
            "Follow the supplied pose driver for body timing only; do not copy its face, clothing, background, props, text or identity.",
            "Preserve the keyframe actor identity, clothing, anatomy, room geometry and prop count.",
            "Locked camera, constant exposure and white balance, physically plausible weight transfer, no internal cut.",
        ]
    )


def ltx_frame_count(duration_seconds: float) -> int:
    if duration_seconds <= 2.56:
        return 65
    if duration_seconds <= 3.84:
        return 97
    return 129


def ltx_graph(
    *,
    image_name: str,
    positive: str,
    negative: str,
    seed: int,
    length: int,
    prefix: str,
) -> dict[str, object]:
    """Project-local LTX graph with no unrelated provider prompt prefix."""
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "LTX2\\ltx-2.3-22b-distilled-1.1_transformer_only_fp8_scaled.safetensors",
                "weight_dtype": "default",
            },
        },
        "2": {
            "class_type": "ModelSamplingLTXV",
            "inputs": {"model": ["1", 0], "max_shift": 2.05, "base_shift": 0.95, "latent": ["9", 2]},
        },
        "3": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "LTX-Kijai\\LTX23_video_vae_bf16.safetensors"},
        },
        "4": {
            "class_type": "LTXAVTextEncoderLoader",
            "inputs": {
                "text_encoder": "gemma_3_12B_it.safetensors",
                "ckpt_name": "ltx-2.3-text-proj-only.safetensors",
                "device": "default",
            },
        },
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": positive}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": negative}},
        "7": {
            "class_type": "LTXVConditioning",
            "inputs": {"positive": ["5", 0], "negative": ["6", 0], "frame_rate": 25.0},
        },
        "8": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "9": {
            "class_type": "LTXVImgToVideo",
            "inputs": {
                "positive": ["7", 0],
                "negative": ["7", 1],
                "vae": ["3", 0],
                "image": ["8", 0],
                "width": 704,
                "height": 1248,
                "length": length,
                "batch_size": 1,
                "strength": 0.85,
            },
        },
        "10": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["2", 0],
                "positive": ["9", 0],
                "negative": ["9", 1],
                "latent_image": ["9", 2],
                "seed": seed,
                "steps": 8,
                "cfg": 1.0,
                "sampler_name": "euler_ancestral_cfg_pp",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        "11": {
            "class_type": "LTXVTiledVAEDecode",
            "inputs": {
                "vae": ["3", 0],
                "latents": ["10", 0],
                "horizontal_tiles": 1,
                "vertical_tiles": 2,
                "overlap": 2,
                "last_frame_fix": False,
                "working_device": "auto",
                "working_dtype": "auto",
            },
        },
        "12": {"class_type": "SaveImage", "inputs": {"images": ["11", 0], "filename_prefix": prefix}},
    }


def render_wan(
    *,
    scenes: list[dict[str, object]],
    anchors: Path,
    output_root: Path,
    base_url: str,
    timeout: int,
    force: bool,
    global_negative: str = "",
) -> None:
    clips = output_root / "clips_raw"
    workflows = output_root / "workflows"
    clips.mkdir(parents=True, exist_ok=True)
    workflows.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "render_manifest.json"
    report = {
        "schema": "reference_404263_wan22_5b_i2v/v5",
        "created_at": utc_now(),
        "renderer": "local_comfyui_wan22_5b_official_native_i2v",
        "model": "wan2.2_ti2v_5B_fp16.safetensors",
        "publish_allowed": False,
        "reference_video_pixels_used": False,
        "shots": [],
    }
    prior = {}
    if report_path.is_file():
        old = json.loads(report_path.read_text(encoding="utf-8"))
        prior = {str(row["scene_id"]): row for row in old.get("shots", [])}
    preserve_unselected_shots(report, prior, {str(scene["id"]) for scene in scenes})

    for index, scene in enumerate(scenes, start=1):
        scene_id = str(scene["id"])
        anchor = scene_anchor(scene, anchors)
        destination = clips / f"{scene_id}.mp4"
        if not anchor.is_file():
            raise FileNotFoundError(anchor)
        fingerprint = scene_fingerprint(
            workflow="wan22_5b_native_i2v_v5_steps20_cfg4_denoise1_constant_camera",
            scene=scene,
            anchor=anchor,
        )
        cached = prior.get(scene_id)
        if (
            not force
            and cached
            and cached.get("status") == "rendered"
            and cached.get("scene_fingerprint") == fingerprint
            and destination.is_file()
            and cached.get("video_sha256") == sha256(destination)
        ):
            report["shots"].append(cached)
            print(json.dumps({"event": "cache_hit", "workflow": "wan", "scene_id": scene_id}), flush=True)
            continue
        image_name = f"reference_404263_{scene_id}_{uuid.uuid4().hex[:8]}.png"
        shutil.copy2(anchor, COMFY_INPUT / image_name)
        prefix = f"reference_404263_wan/{scene_id}_{uuid.uuid4().hex[:8]}"
        length = wan_frame_count(generation_duration(scene, "wan"))
        workflow = wan_graph(
            image_name=image_name,
            positive=scene_positive(scene),
            negative=scene_negative(scene, global_negative),
            seed=825100 + index,
            length=length,
            prefix=prefix,
        )
        workflow_path = workflows / f"{scene_id}.api.json"
        write_json(workflow_path, workflow)
        response = request_json(
            f"{base_url}/prompt",
            {"prompt": workflow, "client_id": str(uuid.uuid4())},
        )
        prompt_id = str(response["prompt_id"])
        print(json.dumps({"event": "queued", "workflow": "wan", "scene_id": scene_id, "prompt_id": prompt_id}), flush=True)
        history = wait_history(base_url, prompt_id, timeout)
        candidates: list[Path] = []
        for node_output in history.get("outputs", {}).values():
            for video in node_output.get("videos", []):
                name = str(video.get("filename") or "")
                subfolder = str(video.get("subfolder") or "")
                path = COMFY_OUTPUT / subfolder / name
                if path.is_file():
                    candidates.append(path)
        if not candidates:
            candidates = list((COMFY_OUTPUT / "reference_404263_wan").glob(f"{scene_id}_*.mp4"))
        if not candidates:
            raise FileNotFoundError(f"ComfyUI saved no Wan video for {scene_id}")
        source = max(candidates, key=lambda item: item.stat().st_mtime)
        shutil.copy2(source, destination)
        row = {
            "scene_id": scene_id,
            "scene_fingerprint": fingerprint,
            "status": "rendered",
            "completed_at": utc_now(),
            "prompt_id": prompt_id,
            "seed": 825100 + index,
            "length": length,
            "anchor_path": str(anchor),
            "anchor_sha256": sha256(anchor),
            "workflow_path": str(workflow_path),
            "workflow_sha256": sha256(workflow_path),
            "video_path": str(destination),
            "video_sha256": sha256(destination),
            "probe": probe(destination),
            "comfy_output_source": str(source),
        }
        report["shots"].append(row)
        write_json(report_path, report)
        print(json.dumps({"event": "rendered", "workflow": "wan", "scene_id": scene_id, "output": str(destination)}), flush=True)


def render_wan_animate(
    *,
    scenes: list[dict[str, object]],
    policy: dict[str, object],
    reference_video: Path,
    output_root: Path,
    base_url: str,
    timeout: int,
    force: bool,
    global_negative: str,
) -> None:
    clips = output_root / "clips_raw"
    workflows = output_root / "workflows"
    frames_root = output_root / "frames"
    drivers = output_root / "motion_drivers_internal_only"
    for directory in (clips, workflows, frames_root, drivers):
        directory.mkdir(parents=True, exist_ok=True)
    if not reference_video.is_file():
        raise FileNotFoundError(reference_video)

    ranges = dict(policy.get("move_scene_ranges") or {})
    driver_sources = dict(policy.get("move_scene_driver_sources") or {})
    anchors = dict(policy.get("move_scene_anchors") or {})
    actions = dict(policy.get("move_actions") or {})
    selected = [scene for scene in scenes if str(scene["id"]) in ranges]
    if not selected:
        raise ValueError("motion_control_policy selected no Animate Move scenes")

    object_info = request_json(f"{base_url}/object_info")
    required = {
        "WanAnimateToVideo", "DWPreprocessor", "LoadVideo", "GetVideoComponents",
        "CLIPVisionEncode", "TrimVideoLatent", "ImageFromBatch", "SaveImage",
    }
    missing = sorted(required - set(object_info))
    if missing:
        raise RuntimeError(f"ComfyUI is missing Wan Animate Move nodes: {missing}")

    report_path = output_root / "render_manifest.json"
    report = {
        "schema": "reference_404263_wan22_animate_move/v1",
        "created_at": utc_now(),
        "renderer": "native_comfyui_wan22_animate_move_pose_only",
        "model": "Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors",
        "reference_pose_signal_used": True,
        "reference_face_video_connected": False,
        "reference_pixels_allowed_in_delivery": False,
        "publish_allowed": False,
        "shots": [],
    }
    prior: dict[str, dict[str, object]] = {}
    if report_path.is_file():
        old = json.loads(report_path.read_text(encoding="utf-8"))
        prior = {str(row["scene_id"]): row for row in old.get("shots", [])}
    preserve_unselected_shots(report, prior, {str(scene["id"]) for scene in selected})

    for index, scene in enumerate(selected, start=1):
        scene_id = str(scene["id"])
        driver_spec = dict(driver_sources.get(scene_id) or {})
        source_value = str(driver_spec.get("path") or "").strip()
        source_video = Path(source_value) if source_value else reference_video
        if not source_video.is_absolute():
            source_video = (ROOT / source_video).resolve()
        if not source_video.is_file():
            raise FileNotFoundError(source_video)
        source_range = [float(value) for value in driver_spec.get("range", ranges[scene_id])]
        if len(source_range) != 2 or source_range[1] <= source_range[0]:
            raise ValueError(f"invalid Move driver range for {scene_id}: {source_range}")
        crop_filter = str(driver_spec.get("crop_filter") or "").strip()
        anchor = Path(str(anchors[scene_id]))
        if not anchor.is_absolute():
            anchor = (ROOT / anchor).resolve()
        if not anchor.is_file():
            raise FileNotFoundError(anchor)
        action = str(actions.get(scene_id) or scene.get("action") or "").strip()
        if not action:
            raise ValueError(f"missing Move action for {scene_id}")
        driver_seconds = source_range[1] - source_range[0]
        length = wan_animate_frame_count(driver_seconds)
        driver = drivers / f"{scene_id}_{length}f_16fps.mp4"
        if force or not driver.is_file():
            video_filters = []
            if crop_filter:
                video_filters.append(crop_filter)
            video_filters.extend(
                [
                    "fps=16",
                    "scale=320:576:force_original_aspect_ratio=decrease",
                    "pad=320:576:(ow-iw)/2:(oh-ih)/2:black",
                ]
            )
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{source_range[0]:.3f}",
                    "-i", str(source_video), "-vf", ",".join(video_filters),
                    "-frames:v", str(length), "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(driver),
                ],
                check=True,
                timeout=600,
            )

        destination = clips / f"{scene_id}.mp4"
        fingerprint_payload = {
            "workflow": "wan22_animate_move_pose_only_v1_320x576_6step",
            "scene": scene,
            "move_action": action,
            "source_video_sha256": sha256(source_video),
            "source_range": source_range,
            "crop_filter": crop_filter,
            "anchor_sha256": sha256(anchor),
            "driver_sha256": sha256(driver),
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest().upper()
        cached = prior.get(scene_id)
        if (
            not force and cached and cached.get("status") == "rendered"
            and cached.get("scene_fingerprint") == fingerprint and destination.is_file()
            and cached.get("video_sha256") == sha256(destination)
        ):
            report["shots"].append(cached)
            print(json.dumps({"event": "cache_hit", "workflow": "wan_animate", "scene_id": scene_id}), flush=True)
            continue

        token = uuid.uuid4().hex[:8]
        image_name = f"reference_404263_move_anchor_{scene_id}_{token}.png"
        driver_name = f"reference_404263_move_driver_{scene_id}_{token}.mp4"
        shutil.copy2(anchor, COMFY_INPUT / image_name)
        shutil.copy2(driver, COMFY_INPUT / driver_name)
        prefix = f"reference_404263_full_move/{scene_id}_{token}"
        workflow = wan_animate_graph(
            image_name=image_name,
            driver_name=driver_name,
            positive=wan_animate_positive(scene, action),
            negative=scene_negative(scene, global_negative),
            seed=827000 + index,
            length=length,
            prefix=prefix,
        )
        workflow_path = workflows / f"{scene_id}.api.json"
        write_json(workflow_path, workflow)
        response = request_json(
            f"{base_url}/prompt",
            {"prompt": workflow, "client_id": str(uuid.uuid4())},
        )
        prompt_id = str(response["prompt_id"])
        print(json.dumps({"event": "queued", "workflow": "wan_animate", "scene_id": scene_id, "prompt_id": prompt_id}), flush=True)
        history = wait_history(base_url, prompt_id, timeout)
        saved: list[Path] = []
        for node_output in history.get("outputs", {}).values():
            for image in node_output.get("images", []):
                source = COMFY_OUTPUT / str(image.get("subfolder") or "") / str(image.get("filename") or "")
                if source.is_file():
                    saved.append(source)
        if not saved:
            raise FileNotFoundError(f"ComfyUI saved no Wan Animate frames for {scene_id}")
        saved.sort(key=lambda path: path.name)
        run_frames = frames_root / f"{scene_id}_{token}"
        run_frames.mkdir(parents=True, exist_ok=True)
        for frame_index, source in enumerate(saved):
            shutil.copy2(source, run_frames / f"frame_{frame_index:04d}.png")
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-framerate", "16",
                "-i", str(run_frames / "frame_%04d.png"), "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-crf", "18", str(destination),
            ],
            check=True,
            timeout=600,
        )
        row = {
            "scene_id": scene_id,
            "scene_fingerprint": fingerprint,
            "status": "rendered",
            "completed_at": utc_now(),
            "prompt_id": prompt_id,
            "seed": 827000 + index,
            "length": length,
            "motion_source_path": str(source_video),
            "motion_source_sha256": sha256(source_video),
            "motion_source_range_seconds": source_range,
            "motion_source_crop_filter": crop_filter or None,
            "motion_driver_internal_only": str(driver),
            "motion_driver_sha256": sha256(driver),
            "reference_face_video_connected": False,
            "anchor_path": str(anchor),
            "anchor_sha256": sha256(anchor),
            "workflow_path": str(workflow_path),
            "workflow_sha256": sha256(workflow_path),
            "video_path": str(destination),
            "video_sha256": sha256(destination),
            "probe": probe(destination),
        }
        report["shots"].append(row)
        write_json(report_path, report)
        print(json.dumps({"event": "rendered", "workflow": "wan_animate", "scene_id": scene_id, "output": str(destination)}), flush=True)


def render_ltx_direct(
    *,
    scenes: list[dict[str, object]],
    anchors: Path,
    output_root: Path,
    base_url: str,
    timeout: int,
    force: bool,
    global_negative: str = "",
) -> None:
    """Render LTX clips directly so unrelated legacy prompt prefixes cannot leak in."""
    clips = output_root / "clips_raw"
    workflows = output_root / "workflows"
    frames_root = output_root / "frames"
    for directory in (clips, workflows, frames_root):
        directory.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "render_manifest.json"
    report = {
        "schema": "reference_404263_ltx23_direct_i2v/v3",
        "created_at": utc_now(),
        "renderer": "project_local_comfyui_ltx23_direct_i2v",
        "model": "LTX2/ltx-2.3-22b-distilled-1.1_transformer_only_fp8_scaled.safetensors",
        "legacy_provider_prompt_prefix_used": False,
        "publish_allowed": False,
        "reference_video_pixels_used": False,
        "shots": [],
    }
    prior: dict[str, dict[str, object]] = {}
    if report_path.is_file():
        old = json.loads(report_path.read_text(encoding="utf-8"))
        prior = {str(row["scene_id"]): row for row in old.get("shots", [])}
    preserve_unselected_shots(report, prior, {str(scene["id"]) for scene in scenes})

    object_info = request_json(f"{base_url}/object_info")
    required = {"LTXVImgToVideo", "LTXVTiledVAEDecode", "LTXAVTextEncoderLoader", "SaveImage"}
    missing = sorted(required - set(object_info))
    if missing:
        raise RuntimeError(f"ComfyUI is missing LTX nodes: {missing}")

    for index, scene in enumerate(scenes, start=1):
        scene_id = str(scene["id"])
        anchor = scene_anchor(scene, anchors)
        destination = clips / f"{scene_id}.mp4"
        if not anchor.is_file():
            raise FileNotFoundError(anchor)
        fingerprint = scene_fingerprint(
            workflow="ltx23_direct_i2v_v3_strength085_constant_camera",
            scene=scene,
            anchor=anchor,
        )
        cached = prior.get(scene_id)
        if (
            not force
            and cached
            and cached.get("status") == "rendered"
            and cached.get("scene_fingerprint") == fingerprint
            and destination.is_file()
            and cached.get("video_sha256") == sha256(destination)
        ):
            report["shots"].append(cached)
            print(json.dumps({"event": "cache_hit", "workflow": "ltx", "scene_id": scene_id}), flush=True)
            continue

        token = uuid.uuid4().hex[:8]
        image_name = f"reference_404263_full_ltx_{scene_id}_{token}.png"
        shutil.copy2(anchor, COMFY_INPUT / image_name)
        prefix = f"reference_404263_full_ltx/{scene_id}_{token}"
        length = ltx_frame_count(generation_duration(scene, "ltx"))
        workflow = ltx_graph(
            image_name=image_name,
            positive=scene_positive(scene),
            negative=scene_negative(scene, global_negative),
            seed=826000 + index,
            length=length,
            prefix=prefix,
        )
        workflow_path = workflows / f"{scene_id}.api.json"
        write_json(workflow_path, workflow)
        response = request_json(
            f"{base_url}/prompt",
            {"prompt": workflow, "client_id": str(uuid.uuid4())},
        )
        prompt_id = str(response["prompt_id"])
        print(json.dumps({"event": "queued", "workflow": "ltx_direct", "scene_id": scene_id, "prompt_id": prompt_id}), flush=True)
        history = wait_history(base_url, prompt_id, timeout)
        saved: list[Path] = []
        for node_output in history.get("outputs", {}).values():
            for image in node_output.get("images", []):
                source = COMFY_OUTPUT / str(image.get("subfolder") or "") / str(image.get("filename") or "")
                if source.is_file():
                    saved.append(source)
        if not saved:
            raise FileNotFoundError(f"ComfyUI saved no LTX frames for {scene_id}")
        saved.sort(key=lambda path: path.name)
        run_frames = frames_root / f"{scene_id}_{token}"
        run_frames.mkdir(parents=True, exist_ok=True)
        for frame_index, source in enumerate(saved):
            shutil.copy2(source, run_frames / f"frame_{frame_index:04d}.png")
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-framerate", "25",
                "-i", str(run_frames / "frame_%04d.png"), "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-crf", "18", str(destination),
            ],
            check=True,
            timeout=600,
        )
        row = {
            "scene_id": scene_id,
            "scene_fingerprint": fingerprint,
            "status": "rendered",
            "completed_at": utc_now(),
            "prompt_id": prompt_id,
            "seed": 826000 + index,
            "length": length,
            "anchor_path": str(anchor),
            "anchor_sha256": sha256(anchor),
            "workflow_path": str(workflow_path),
            "workflow_sha256": sha256(workflow_path),
            "frames_dir": str(run_frames),
            "saved_frame_count": len(saved),
            "video_path": str(destination),
            "video_sha256": sha256(destination),
            "probe": probe(destination),
        }
        report["shots"].append(row)
        write_json(report_path, report)
        print(json.dumps({"event": "rendered", "workflow": "ltx_direct", "scene_id": scene_id, "output": str(destination)}), flush=True)


def render_ltx(
    *,
    scenes: list[dict[str, object]],
    anchors: Path,
    cast_master: Path,
    output_root: Path,
    evidence_root: Path,
    p0_root: Path,
    base_url: str,
    force: bool,
    global_negative: str = "",
) -> None:
    sys.path.insert(0, str(p0_root))
    from src.novel_promotion.comfy_ltx_video_provider import ComfyLTXVideoSceneProvider
    from src.novel_promotion.scene_provider import ScenePlan

    plans = []
    anchor_by_id: dict[str, Path] = {}
    fingerprint_by_id: dict[str, str] = {}
    for index, scene in enumerate(scenes, start=1):
        scene_id = str(scene["id"])
        anchor = scene_anchor(scene, anchors)
        if not anchor.is_file():
            raise FileNotFoundError(anchor)
        character_ids = [str(value) for value in scene.get("characters", [])]
        # The v2 performance contract binds identity through a reviewed
        # composite anchor rather than legacy per-scene character IDs.  The
        # provider still requires a non-empty identity key for hashing.
        if not character_ids:
            character_ids = ["approved_cast_master"]
        master_paths = (
            {cid: str(cast_master) for cid in character_ids}
            if character_ids and cast_master.is_file()
            else {}
        )
        master_hashes = (
            {cid: sha256(cast_master) for cid in character_ids}
            if master_paths
            else {}
        )
        plans.append(
            ScenePlan(
                scene_id=scene_id,
                description="Original 404263-inspired anti-fraud microshot",
                visual_prompt=scene_positive(scene),
                estimated_duration_s=generation_duration(scene, "ltx"),
                metadata={
                    "character_ids": character_ids,
                    "master_image_paths": master_paths,
                    "master_image_sha256s": master_hashes,
                    "shot_anchor_image": str(anchor),
                    "shot_anchor_sha256": sha256(anchor),
                    "seed": 825000 + index,
                    "negative_prompt": scene_negative(scene, global_negative),
                    "spoken_closeup": False,
                    "dialogue_audio_path": "",
                    "publish_allowed": False,
                },
            )
        )
        anchor_by_id[scene_id] = anchor
        fingerprint_by_id[scene_id] = scene_fingerprint(
            workflow="ltx23_i2v",
            scene=scene,
            anchor=anchor,
        )

    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "render_manifest.json"
    report = {
        "schema": "reference_404263_ltx23_i2v/v1",
        "created_at": utc_now(),
        "renderer": "local_comfyui_ltx23_i2v",
        "publish_allowed": False,
        "reference_video_pixels_used": False,
        "shots": [],
    }
    prior = {}
    if report_path.is_file():
        old = json.loads(report_path.read_text(encoding="utf-8"))
        prior = {str(row["scene_id"]): row for row in old.get("shots", [])}
    preserve_unselected_shots(report, prior, {str(plan.scene_id) for plan in plans})

    provider = ComfyLTXVideoSceneProvider(
        base_url=base_url,
        comfy_input=str(COMFY_INPUT),
        comfy_output=str(COMFY_OUTPUT),
        evidence_root=str(evidence_root),
        timeout_seconds=7200,
        musetalk_available=False,
    )
    preflight = provider.preflight(plans, require_dialogue_audio=False)
    if not preflight.ok:
        raise RuntimeError(f"LTX preflight failed: {preflight.error}")

    clips = output_root / "clips_raw"
    clips.mkdir(parents=True, exist_ok=True)
    for plan in plans:
        destination = clips / f"{plan.scene_id}.mp4"
        cached = prior.get(plan.scene_id)
        if (
            not force
            and cached
            and cached.get("status") == "rendered"
            and cached.get("scene_fingerprint") == fingerprint_by_id[plan.scene_id]
            and destination.is_file()
            and cached.get("video_sha256") == sha256(destination)
        ):
            report["shots"].append(cached)
            print(json.dumps({"event": "cache_hit", "workflow": "ltx", "scene_id": plan.scene_id}), flush=True)
            continue
        print(json.dumps({"event": "queued", "workflow": "ltx", "scene_id": plan.scene_id}), flush=True)
        result = provider.provide_scenes([plan], clips)
        if result.missing or len(result.assets) != 1:
            reasons = [item.reason for item in result.missing]
            raise RuntimeError(f"LTX failed for {plan.scene_id}: {reasons}")
        path = Path(result.assets[0].video_path)
        if path.resolve() != destination.resolve():
            shutil.copy2(path, destination)
        row = {
            "scene_id": plan.scene_id,
            "scene_fingerprint": fingerprint_by_id[plan.scene_id],
            "status": "rendered",
            "completed_at": utc_now(),
            "seed": plan.metadata["seed"],
            "anchor_path": str(anchor_by_id[plan.scene_id]),
            "anchor_sha256": sha256(anchor_by_id[plan.scene_id]),
            "video_path": str(destination),
            "video_sha256": sha256(destination),
            "probe": probe(destination),
            "provider_metadata": result.assets[0].metadata,
        }
        report["shots"].append(row)
        write_json(report_path, report)
        print(json.dumps({"event": "rendered", "workflow": "ltx", "scene_id": plan.scene_id, "output": str(destination)}), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow", choices=("ltx", "wan", "wan-animate"), required=True)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--qa-root", type=Path, default=DEFAULT_QA_ROOT)
    parser.add_argument("--p0-root", type=Path, default=DEFAULT_P0_ROOT)
    parser.add_argument("--cast-master", type=Path, default=DEFAULT_CAST_MASTER)
    parser.add_argument("--base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--scene-id", action="append", default=[])
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    plan_path = args.plan.resolve()
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    schema = payload.get("schema_version")
    if schema not in {
        "reference_404263_original_multiflow/v1",
        "reference_404263_full_workflows/v2",
    }:
        raise ValueError("unexpected plan schema")
    if payload["delivery"].get("publish_allowed") is not False:
        raise ValueError("render plan must remain non-publishable")
    scenes = list(payload["scenes"] if schema.endswith("/v1") else payload["beats"])
    scenes = [scene for scene in scenes if str(scene.get("kind", "generated")) == "generated"]
    if args.scene_id:
        wanted = set(args.scene_id)
        known = {str(scene["id"]) for scene in scenes}
        unknown = wanted - known
        if unknown:
            raise ValueError(f"unknown scene ids: {', '.join(sorted(unknown))}")
        scenes = [scene for scene in scenes if scene["id"] in wanted]

    qa_root = args.qa_root.resolve()
    anchors = qa_root / "anchors"
    output_folder = "wan_animate" if args.workflow == "wan-animate" else args.workflow
    output_root = qa_root / "renders" / output_folder
    if args.workflow == "ltx":
        render_ltx_direct(
            scenes=scenes,
            anchors=anchors,
            output_root=output_root,
            base_url=args.base_url,
            timeout=args.timeout,
            force=args.force,
            global_negative=str(payload.get("global_negative") or ""),
        )
    elif args.workflow == "wan":
        render_wan(
            scenes=scenes,
            anchors=anchors,
            output_root=output_root,
            base_url=args.base_url,
            timeout=args.timeout,
            force=args.force,
            global_negative=str(payload.get("global_negative") or ""),
        )
    else:
        reference_value = str(payload.get("reference_policy", {}).get("reference_video") or "").strip()
        if not reference_value:
            raise ValueError("reference_policy.reference_video is required for Wan Animate Move")
        reference_video = Path(reference_value)
        if not reference_video.is_absolute():
            reference_video = (ROOT / reference_video).resolve()
        render_wan_animate(
            scenes=scenes,
            policy=dict(payload.get("motion_control_policy") or {}),
            reference_video=reference_video,
            output_root=output_root,
            base_url=args.base_url,
            timeout=args.timeout,
            force=args.force,
            global_negative=str(payload.get("global_negative") or ""),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
