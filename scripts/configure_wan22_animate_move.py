"""Prepare a project-pinned Wan2.2 Animate Move workflow without starting ComfyUI.

The upstream Kijai workflow is treated as read-only.  This script validates the
installed nodes/models, rewrites only known node widgets, and installs the
adapted workflow into ComfyUI's user workflow directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "comfyui_wan22_animate_move.json"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _resolve(root: Path, relative: str) -> Path:
    return (root / Path(relative)).resolve()


def _required_paths(root: Path, config: dict[str, Any]) -> dict[str, Path]:
    models = config["models"]
    return {
        "wan_video_wrapper": root / "custom_nodes" / "ComfyUI-WanVideoWrapper",
        "kj_nodes": root / "custom_nodes" / "ComfyUI-KJNodes",
        "video_helper_suite": root / "custom_nodes" / "ComfyUI-VideoHelperSuite",
        "controlnet_aux": root / "custom_nodes" / "comfyui_controlnet_aux",
        "sam2_nodes": root / "custom_nodes" / "ComfyUI-segment-anything-2",
        "wan_animate_preprocess": root / "custom_nodes" / "ComfyUI-WanAnimatePreprocess",
        "diffusion": root / "models" / "diffusion_models" / models["diffusion"],
        "text_encoder": root / "models" / "text_encoders" / models["text_encoder"],
        "vae": root / "models" / "vae" / models["vae"],
        "clip_vision": root / "models" / "clip_vision" / models["clip_vision"],
        "sam2": root / "models" / "sam2" / models["sam2"],
        "vitpose": root / "models" / "detection" / models["vitpose"],
        "yolo": root / "models" / "detection" / models["yolo"],
        "relight_lora": root / "models" / "loras" / models["relight_lora"],
        "lightx2v_lora": root / "models" / "loras" / models["lightx2v_lora"],
    }


def _disconnect_input(workflow: dict[str, Any], node: dict[str, Any], input_name: str) -> None:
    target_input = next((item for item in node.get("inputs", []) if item.get("name") == input_name), None)
    if target_input is None or target_input.get("link") is None:
        return

    link_id = target_input["link"]
    link = next((item for item in workflow.get("links", []) if item[0] == link_id), None)
    if link is not None:
        source_node_id, source_slot = link[1], link[2]
        source_node = next((item for item in workflow.get("nodes", []) if item.get("id") == source_node_id), None)
        if source_node is not None and source_slot < len(source_node.get("outputs", [])):
            output_links = source_node["outputs"][source_slot].get("links")
            if isinstance(output_links, list):
                source_node["outputs"][source_slot]["links"] = [item for item in output_links if item != link_id]
        workflow["links"] = [item for item in workflow.get("links", []) if item[0] != link_id]
    target_input["link"] = None


def _patch_workflow(workflow: dict[str, Any], config: dict[str, Any]) -> list[str]:
    models = config["models"]
    runtime = config["runtime"]
    touched: list[str] = []

    for node in workflow.get("nodes", []):
        node_type = node.get("type")
        widgets = node.get("widgets_values")
        node_id = node.get("id")

        if node_type == "WanVideoModelLoader" and isinstance(widgets, list):
            widgets[0] = models["diffusion"]
            widgets[2] = "disabled"
            widgets[3] = runtime["load_device"]
            widgets[4] = runtime["attention"]
        elif node_type == "WanVideoVAELoader" and isinstance(widgets, list):
            widgets[0] = models["vae"]
        elif node_type == "WanVideoTextEncodeCached" and isinstance(widgets, list):
            widgets[0] = models["text_encoder"]
        elif node_type == "DownloadAndLoadSAM2Model" and isinstance(widgets, list):
            widgets[0] = models["sam2"]
        elif node_type == "OnnxDetectionModelLoader" and isinstance(widgets, list):
            widgets[0] = models["vitpose"]
            widgets[1] = models["yolo"]
            widgets[2] = runtime["pose_execution_provider"]
        elif node_type == "WanVideoAnimateEmbeds" and isinstance(widgets, list):
            if runtime["mode"] == "move":
                _disconnect_input(workflow, node, "bg_images")
                _disconnect_input(workflow, node, "mask")
            widgets[0] = runtime["width"]
            widgets[1] = runtime["height"]
            widgets[2] = runtime["frame_count"]
            widgets[4] = runtime["frame_window"]
        elif node_type == "WanVideoContextOptions" and isinstance(widgets, list):
            widgets[1] = runtime["context_window"]
        elif node_type == "WanVideoBlockSwap" and isinstance(widgets, list):
            widgets[0] = runtime["block_swap"]
        elif node_type == "ImageResizeKJv2" and isinstance(widgets, list):
            widgets[0] = runtime["width"]
            widgets[1] = runtime["height"]
        elif node_type in {"PoseAndFaceDetection", "DrawViTPose"} and isinstance(widgets, list):
            widgets[0] = runtime["width"]
            widgets[1] = runtime["height"]
        elif node_type == "INTConstant" and node.get("title") == "Width":
            node["widgets_values"] = runtime["width"]
        elif node_type == "INTConstant" and node.get("title") == "Height":
            node["widgets_values"] = runtime["height"]
        elif node_type == "WanVideoLoraSelectMulti" and isinstance(widgets, list):
            widgets[0] = models["relight_lora"]
            widgets[2] = models["lightx2v_lora"]
        elif node_type == "VHS_LoadVideo" and isinstance(widgets, dict):
            widgets["force_rate"] = runtime["fps"]
            widgets["custom_width"] = runtime["width"]
            widgets["custom_height"] = runtime["height"]
            widgets["frame_load_cap"] = runtime["frame_count"]
            preview = widgets.get("videopreview", {}).get("params", {})
            preview["force_rate"] = runtime["fps"]
            preview["custom_width"] = runtime["width"]
            preview["custom_height"] = runtime["height"]
            preview["frame_load_cap"] = runtime["frame_count"]
        else:
            continue

        touched.append(f"{node_id}:{node_type}")

    expected_types = {
        "WanVideoModelLoader",
        "WanVideoVAELoader",
        "WanVideoTextEncodeCached",
        "WanVideoAnimateEmbeds",
        "WanVideoContextOptions",
        "WanVideoBlockSwap",
        "VHS_LoadVideo",
        "PoseAndFaceDetection",
        "OnnxDetectionModelLoader",
    }
    touched_types = {item.split(":", 1)[1] for item in touched}
    missing_types = sorted(expected_types - touched_types)
    if missing_types:
        raise ValueError(f"Upstream workflow is missing expected nodes: {missing_types}")

    return touched


def configure(config_path: Path, *, check_only: bool, force: bool) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    root = Path(config["comfyui_root"]).resolve()
    source = _resolve(root, config["source_workflow"])
    target = _resolve(root, config["target_workflow"])

    checks = _required_paths(root, config)
    checks["source_workflow"] = source
    missing = {name: str(path) for name, path in checks.items() if not path.exists()}
    if missing:
        raise FileNotFoundError(json.dumps(missing, ensure_ascii=False, indent=2))

    integrity_errors: dict[str, dict[str, str]] = {}
    for name, expected in config.get("integrity", {}).items():
        actual = _sha256(checks[name].read_bytes())
        if actual.lower() != expected.lower():
            integrity_errors[name] = {"expected": expected.lower(), "actual": actual.lower()}
    if integrity_errors:
        raise ValueError(f"Integrity check failed: {json.dumps(integrity_errors, ensure_ascii=False)}")

    workflow = json.loads(source.read_text(encoding="utf-8"))
    touched = _patch_workflow(workflow, config)
    payload = (json.dumps(workflow, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    result: dict[str, Any] = {
        "status": "validated" if check_only else "installed",
        "comfyui_started": False,
        "source": str(source),
        "target": str(target),
        "source_sha256": _sha256(source.read_bytes()),
        "target_sha256": _sha256(payload),
        "patched_nodes": touched,
        "settings": config["runtime"],
    }

    if check_only:
        return result

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        existing = target.read_bytes()
        if existing == payload:
            result["status"] = "already_installed"
            return result
        if not force:
            raise FileExistsError(f"Target exists with different content: {target}; pass --force to replace it")
    target.write_bytes(payload)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = configure(args.config.resolve(), check_only=args.check_only, force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
