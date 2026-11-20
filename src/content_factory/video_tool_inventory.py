"""Detect local AI-video tools and the assets required to run them."""

from __future__ import annotations

import importlib.util
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class VideoToolCapability:
    tool: str
    status: str
    detected: tuple[str, ...]
    missing: tuple[str, ...]
    modes: tuple[str, ...]
    notes: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class VideoToolInventory:
    comfyui_root: str
    framepack_root: str
    liveportrait_root: str
    sadtalker_root: str
    capabilities: tuple[VideoToolCapability, ...]

    def find(self, tool: str) -> VideoToolCapability | None:
        return next((item for item in self.capabilities if item.tool == tool), None)

    def ready_tools(self) -> tuple[str, ...]:
        return tuple(item.tool for item in self.capabilities if item.ready)

    def to_dict(self) -> dict[str, object]:
        return {
            "roots": {
                "comfyui": self.comfyui_root,
                "framepack": self.framepack_root,
                "liveportrait": self.liveportrait_root,
                "sadtalker": self.sadtalker_root,
            },
            "summary": {
                "ready": list(self.ready_tools()),
                "partial": [
                    item.tool for item in self.capabilities if item.status == "partial"
                ],
                "missing": [
                    item.tool for item in self.capabilities if item.status == "missing"
                ],
            },
            "capabilities": [item.to_dict() for item in self.capabilities],
        }


def scan_video_tool_inventory(
    *,
    comfyui_root: str | Path,
    framepack_root: str | Path,
    liveportrait_root: str | Path,
    sadtalker_root: str | Path,
    ffmpeg_path: str | None = None,
) -> VideoToolInventory:
    comfy = Path(comfyui_root)
    framepack = Path(framepack_root)
    liveportrait = Path(liveportrait_root)
    sadtalker = Path(sadtalker_root)
    ffmpeg = ffmpeg_path or shutil.which("ffmpeg")
    pillow_ready = importlib.util.find_spec("PIL") is not None

    capabilities = (
        _capability(
            "deterministic_2d_compositor",
            {
                "deterministic motion executor": _file(
                    Path(__file__).with_name("deterministic_motion.py")
                ),
                "ffmpeg": ffmpeg,
                "Pillow": "python:PIL" if pillow_ready else None,
            },
            modes=("pixel_locked",),
            notes=(
                "Preferred for visible hands or phones that must remain unchanged.",
                "Runs deterministic_motion/v1 light pulses and particles with a "
                "pixel-locked machine gate.",
            ),
        ),
        _capability(
            "deterministic_camera",
            {
                "deterministic camera executor": _file(
                    Path(__file__).with_name("deterministic_camera.py")
                ),
                "ffmpeg": ffmpeg,
                "Pillow": "python:PIL" if pillow_ready else None,
            },
            modes=("free",),
            notes=(
                "Creates full-frame push, pull, or pan motion without generative "
                "redrawing.",
                "Preferred for approved stills that need visible whole-frame motion.",
            ),
        ),
        _capability(
            "reference_appearance_lock",
            {
                "ffmpeg": ffmpeg,
                "Pillow": "python:PIL" if pillow_ready else None,
            },
            modes=("micro_motion", "subject_only", "replacement_relight"),
            notes=(
                "Transfers temporal changes onto the reference appearance to lock "
                "lighting and color.",
            ),
        ),
        _capability(
            "keyframe_relight",
            {
                "keyframe relight executor": _file(
                    Path(__file__).with_name("keyframe_relight.py")
                ),
                "Pillow": "python:PIL" if pillow_ready else None,
            },
            modes=("pixel_locked", "micro_motion", "subject_only"),
            notes=(
                "Corrects local light direction on an approved still before video "
                "generation.",
                "Changes only the approved mask and rejects any unmasked pixel change.",
            ),
        ),
        _capability(
            "temporal_repair",
            {
                "temporal repair executor": _file(
                    Path(__file__).with_name("video_temporal_repair.py")
                ),
                "ffmpeg deflicker": ffmpeg,
            },
            modes=("pixel_locked", "micro_motion", "subject_only", "free"),
            notes=(
                "Repairs exposure flicker only after structural failures are excluded.",
                "Uses reference-anchored Y-plane gain or FFmpeg deflicker, then reruns "
                "the original control gate.",
            ),
        ),
        _capability(
            "smoothness_repair",
            {
                "smoothness executor": _file(
                    Path(__file__).with_name("video_smoothness.py")
                ),
                "ffmpeg minterpolate": ffmpeg,
            },
            modes=("micro_motion", "subject_only", "free"),
            notes=(
                "Interpolates only videos that already passed structural control.",
                "Measures duplicate cadence, normalized jerk, and motion retention "
                "before accepting a higher-frame-rate output.",
            ),
        ),
        _capability(
            "lighting_consistency_gate",
            {
                "lighting gate executor": _file(
                    Path(__file__).with_name("video_lighting_gate.py")
                ),
                "ffmpeg": ffmpeg,
                "Pillow": "python:PIL" if pillow_ready else None,
            },
            modes=("pixel_locked", "micro_motion", "subject_only", "free"),
            notes=(
                "Compares exposure, color cast, contrast, low-frequency light "
                "direction, and temporal lighting drift against one reference.",
                "Video candidates must already have a passing structural control "
                "report.",
            ),
        ),
        _capability(
            "style_consistency_gate",
            {
                "style gate executor": _file(
                    Path(__file__).with_name("video_style_gate.py")
                ),
                "ffmpeg": ffmpeg,
                "Pillow": "python:PIL" if pillow_ready else None,
            },
            modes=("pixel_locked", "micro_motion", "subject_only", "free"),
            notes=(
                "Compares palette, line density, tone, and temporal style drift "
                "against one approved reference.",
                "Video candidates must already have a passing structural control "
                "report.",
            ),
        ),
        _capability(
            "color_match_v2",
            {
                "ComfyUI-KJNodes": _directory(comfy / "custom_nodes" / "ComfyUI-KJNodes"),
                "color-matcher": _directory(
                    comfy / ".venv" / "Lib" / "site-packages" / "color_matcher"
                ),
            },
            modes=("micro_motion", "subject_only", "replacement_relight", "free"),
        ),
        _capability(
            "ltx_i2v",
            {
                "ComfyUI-LTXVideo": _directory(
                    comfy / "custom_nodes" / "ComfyUI-LTXVideo"
                ),
                "LTX transformer": _first(
                    comfy,
                    (
                        "models/unet/LTX2/*ltx*transformer*.safetensors",
                        "models/checkpoints/ltx-2.3-22b-dev.safetensors",
                    ),
                ),
                "LTX video VAE": _first(
                    comfy,
                    ("models/vae/LTX-Kijai/*video*vae*.safetensors",),
                ),
                "LTX text encoder": _first(
                    comfy,
                    (
                        "models/text_encoders/ltx*.safetensors",
                        "models/clip/gemma*.safetensors",
                    ),
                ),
            },
            modes=("micro_motion", "free"),
            notes=("Use for scene motion, not pixel locking.",),
        ),
        _capability(
            "wan_animate_move",
            _wan_requirements(comfy),
            modes=("subject_only",),
            notes=("Requires a clean single-person driver and a subject mask.",),
        ),
        _capability(
            "wan_animate_replacement",
            {
                **_wan_requirements(comfy),
                "Relighting LoRA": _first(
                    comfy,
                    ("models/loras/**/*relight*.safetensors",),
                ),
            },
            modes=("replacement_relight",),
        ),
        _capability(
            "sam2_mask",
            {
                "SAM2 node": _directory(
                    comfy / "custom_nodes" / "ComfyUI-segment-anything-2"
                ),
                "SAM2 model": _first(
                    comfy,
                    ("models/sam2/*.safetensors", "models/sam2/*.pt"),
                ),
            },
            modes=("subject_only", "replacement_relight"),
        ),
        _capability(
            "framepack",
            {
                "FramePack launcher": _first(
                    framepack,
                    ("demo_gradio.py", "run.bat"),
                ),
                "FramePack model shard 1": _first(
                    framepack,
                    (
                        "hf_download/hub/models--lllyasviel--FramePackI2V_HY/"
                        "snapshots/*/diffusion_pytorch_model-00001-of-00003.safetensors",
                    ),
                ),
                "FramePack model shard 3": _first(
                    framepack,
                    (
                        "hf_download/hub/models--lllyasviel--FramePackI2V_HY/"
                        "snapshots/*/diffusion_pytorch_model-00003-of-00003.safetensors",
                    ),
                ),
            },
            modes=("micro_motion",),
        ),
        _capability(
            "liveportrait",
            {
                "LivePortrait runtime": _first(
                    comfy,
                    ("custom_nodes/ComfyUI-LivePortraitKJ/nodes.py",),
                )
                or _first(
                    liveportrait,
                    ("inference.py", "app.py", "run_windows.bat"),
                ),
                "LivePortrait appearance model": _first(
                    comfy,
                    ("models/liveportrait/appearance_feature_extractor.safetensors",),
                )
                or _first(liveportrait, ("**/*appearance_feature_extractor*.pth",)),
                "LivePortrait motion model": _first(
                    comfy,
                    ("models/liveportrait/motion_extractor.safetensors",),
                )
                or _first(liveportrait, ("**/*motion_extractor*.pth",)),
                "LivePortrait warping model": _first(
                    comfy,
                    ("models/liveportrait/warping_module.safetensors",),
                )
                or _first(liveportrait, ("**/*warping_module*.pth",)),
                "LivePortrait generator": _first(
                    comfy,
                    ("models/liveportrait/spade_generator.safetensors",),
                )
                or _first(liveportrait, ("**/*spade_generator*.pth",)),
                "LivePortrait retargeting model": _first(
                    comfy,
                    ("models/liveportrait/stitching_retargeting_module.safetensors",),
                )
                or _first(liveportrait, ("**/*stitching_retargeting*.pth",)),
                "LivePortrait landmark model": _first(
                    comfy,
                    ("models/liveportrait/landmark.onnx",),
                )
                or _first(liveportrait, ("**/landmark.onnx",)),
            },
            modes=("micro_motion",),
            notes=("Best fit for hand-free head-and-shoulders expression shots.",),
        ),
        _capability(
            "sadtalker",
            {
                "SadTalker launcher": _file(sadtalker / "inference.py"),
                "SadTalker 256 checkpoint": _file(
                    sadtalker / "checkpoints" / "SadTalker_V0.0.2_256.safetensors"
                ),
                "SadTalker crop mapping": _file(
                    sadtalker / "checkpoints" / "mapping_00229-model.pth.tar"
                ),
                "SadTalker face alignment": _file(
                    sadtalker / "gfpgan" / "weights" / "alignment_WFLW_4HG.pth"
                ),
                "SadTalker face detector": _file(
                    sadtalker / "gfpgan" / "weights" / "detection_Resnet50_Final.pth"
                ),
            },
            modes=("micro_motion",),
            notes=(
                "Audio-driven square talking-head source only.",
                "Do not stretch or alpha-merge it as a full-body character layer.",
            ),
        ),
        _capability(
            "sonic",
            {
                "ComfyUI Sonic node": _directory(
                    comfy / "custom_nodes" / "ComfyUI_Sonic"
                ),
                "Sonic UNet": _file(comfy / "models" / "sonic" / "unet.pth"),
                "Sonic audio2token": _file(
                    comfy / "models" / "sonic" / "audio2token.pth"
                ),
                "Sonic audio2bucket": _file(
                    comfy / "models" / "sonic" / "audio2bucket.pth"
                ),
                "Sonic face detector": _file(
                    comfy / "models" / "sonic" / "yoloface_v5m.pt"
                ),
                "Sonic Whisper": _file(
                    comfy
                    / "models"
                    / "sonic"
                    / "whisper-tiny"
                    / "model.safetensors"
                ),
                "SVD checkpoint": _first(
                    comfy,
                    ("models/checkpoints/svd_xt*.safetensors",),
                ),
            },
            modes=("micro_motion",),
            notes=(
                "Experimental audio-driven portrait route.",
                "Anime output requires visual review; do not infer readiness from old outputs.",
            ),
        ),
        _capability(
            "rife",
            {
                "RIFE implementation": _first(
                    comfy,
                    (
                        "comfy_extras/nodes_frame_interpolation.py",
                        "custom_nodes/ComfyUI-Frame-Interpolation/**/*RIFE*.py",
                        "custom_nodes/ComfyUI_Sonic/**/RIFE*.py",
                    ),
                ),
                "RIFE weights": _first(
                    comfy,
                    (
                        "models/frame_interpolation/*rife*.safetensors",
                        "models/frame_interpolation/**/*rife*",
                        "models/sonic/**/*flownet*",
                    ),
                ),
            },
            modes=("micro_motion", "subject_only", "free"),
            notes=(
                "Interpolation is allowed only after motion and lighting pass.",
                "Benchmark against FFmpeg minterpolate; neural interpolation can "
                "shift color or appearance.",
            ),
        ),
        _capability(
            "ffmpeg_minterpolate",
            {"ffmpeg": ffmpeg},
            modes=("micro_motion", "subject_only", "free"),
            notes=("Fast fallback; inspect hands for interpolated deformation.",),
        ),
    )
    return VideoToolInventory(
        comfyui_root=str(comfy),
        framepack_root=str(framepack),
        liveportrait_root=str(liveportrait),
        sadtalker_root=str(sadtalker),
        capabilities=capabilities,
    )


def recommendation_readiness(
    tool: str,
    inventory: VideoToolInventory,
) -> dict[str, object]:
    virtual_groups = {
        "wan_or_ltx_i2v": ("ltx_i2v", "wan_animate_move", "framepack"),
    }
    virtual_candidates = virtual_groups.get(tool, ())
    resolved_tool = next(
        (
            candidate
            for candidate in virtual_candidates
            if (capability := inventory.find(candidate)) is not None
            and capability.ready
        ),
        None,
    )
    selected = inventory.find(resolved_tool or tool)
    companion_names = {
        "ltx_i2v": ("color_match_v2",),
        "liveportrait": ("color_match_v2",),
        "sadtalker": ("color_match_v2",),
        "sonic": ("color_match_v2",),
        "wan_animate_move": (
            "sam2_mask",
            "color_match_v2",
            "reference_appearance_lock",
        ),
        "wan_animate_replacement": (
            "sam2_mask",
            "color_match_v2",
            "reference_appearance_lock",
        ),
        "framepack": ("color_match_v2",),
    }.get(resolved_tool or tool, ())
    companions = [
        capability
        for name in companion_names
        if (capability := inventory.find(name)) is not None
    ]
    pipeline_missing = list(selected.missing) if selected else ["tool is not inventoried"]
    pipeline_missing.extend(
        f"{capability.tool}: {item}"
        for capability in companions
        for item in capability.missing
    )
    if selected is None:
        pipeline_status = "unknown"
    elif not selected.ready:
        pipeline_status = selected.status
    elif any(not capability.ready for capability in companions):
        pipeline_status = "partial"
    else:
        pipeline_status = "ready"
    fallbacks = {
        "liveportrait": (
            "deterministic_2d_compositor",
            "framepack",
            "sadtalker",
        ),
        "framepack": ("ltx_i2v", "deterministic_2d_compositor"),
        "wan_animate_move": ("framepack", "ltx_i2v"),
        "wan_animate_replacement": ("wan_animate_move", "ltx_i2v"),
        "wan_or_ltx_i2v": ("ltx_i2v", "wan_animate_move", "framepack"),
    }.get(tool, ())
    ready_fallbacks = [
        fallback
        for fallback in fallbacks
        if (capability := inventory.find(fallback)) is not None and capability.ready
    ]
    return {
        "selected_tool": tool,
        "resolved_tool": resolved_tool or (tool if selected else None),
        "selected_tool_status": (
            "virtual_ready"
            if resolved_tool
            else selected.status
            if selected
            else "unknown"
        ),
        "pipeline_status": pipeline_status,
        "companions": [
            {
                "tool": capability.tool,
                "status": capability.status,
            }
            for capability in companions
        ],
        "missing": pipeline_missing,
        "ready_fallbacks": ready_fallbacks,
    }


def _wan_requirements(comfy: Path) -> dict[str, str | None]:
    return {
        "ComfyUI-WanVideoWrapper": _directory(
            comfy / "custom_nodes" / "ComfyUI-WanVideoWrapper"
        ),
        "Wan Animate model": _first(
            comfy,
            ("models/diffusion_models/*Animate*.safetensors",),
        ),
        "Wan VAE": _first(
            comfy,
            ("models/vae/wan*.safetensors",),
        ),
        "UMT5 encoder": _first(
            comfy,
            ("models/text_encoders/umt5*.safetensors",),
        ),
        "CLIP Vision": _first(
            comfy,
            ("models/clip_vision/*.safetensors",),
        ),
    }


def _capability(
    tool: str,
    requirements: dict[str, str | None],
    *,
    modes: tuple[str, ...],
    notes: tuple[str, ...] = (),
) -> VideoToolCapability:
    detected = tuple(
        f"{name}: {value}"
        for name, value in requirements.items()
        if value is not None
    )
    missing = tuple(name for name, value in requirements.items() if value is None)
    if not missing:
        status = "ready"
    elif detected:
        status = "partial"
    else:
        status = "missing"
    return VideoToolCapability(
        tool=tool,
        status=status,
        detected=detected,
        missing=missing,
        modes=modes,
        notes=notes,
    )


def _directory(path: Path) -> str | None:
    return str(path) if path.is_dir() else None


def _file(path: Path) -> str | None:
    return str(path) if path.is_file() and path.stat().st_size > 0 else None


def _first(root: Path, patterns: tuple[str, ...]) -> str | None:
    if not root.exists():
        return None
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file() and path.stat().st_size > 0:
                return str(path)
    return None
