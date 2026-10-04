"""Select a controllable video workflow from explicit shot intent."""

from __future__ import annotations

from dataclasses import asdict, dataclass


MOTION_LEVELS = {"none", "micro", "subject", "action", "free"}
FRAMING_TYPES = {"detail", "head_shoulders", "medium", "full"}
CAMERA_TYPES = {"locked", "moving"}
BACKGROUND_TYPES = {"static", "dynamic"}
VISUAL_STYLES = {"generic", "anime", "realistic"}


@dataclass(frozen=True, slots=True)
class VideoShotIntent:
    motion: str
    framing: str = "medium"
    camera: str = "locked"
    background: str = "static"
    preserve_reference: bool = True
    contains_hands: bool = False
    contains_phone: bool = False
    multi_person: bool = False
    replacement: bool = False
    relight: bool = False
    audio_driven: bool = False
    visual_style: str = "generic"
    lip_sync_required: bool = True

    @classmethod
    def from_dict(cls, value: object) -> "VideoShotIntent":
        if not isinstance(value, dict):
            raise ValueError("intent must be an object")
        motion = _choice(value, "motion", MOTION_LEVELS)
        framing = _choice(value, "framing", FRAMING_TYPES, default="medium")
        camera = _choice(value, "camera", CAMERA_TYPES, default="locked")
        background = _choice(value, "background", BACKGROUND_TYPES, default="static")
        visual_style = _choice(
            value,
            "visual_style",
            VISUAL_STYLES,
            default="generic",
        )
        audio_driven = _boolean(value, "audio_driven", False)
        return cls(
            motion=motion,
            framing=framing,
            camera=camera,
            background=background,
            preserve_reference=_boolean(value, "preserve_reference", True),
            contains_hands=_boolean(value, "contains_hands", False),
            contains_phone=_boolean(value, "contains_phone", False),
            multi_person=_boolean(value, "multi_person", False),
            replacement=_boolean(value, "replacement", False),
            relight=_boolean(value, "relight", False),
            audio_driven=audio_driven,
            visual_style=visual_style,
            lip_sync_required=_boolean(
                value,
                "lip_sync_required",
                audio_driven,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class VideoControlRecommendation:
    mode: str
    tool: str
    risk: str
    required_assets: tuple[str, ...]
    postprocess: tuple[str, ...]
    warnings: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "tool": self.tool,
            "risk": self.risk,
            "required_assets": list(self.required_assets),
            "postprocess": list(self.postprocess),
            "warnings": list(self.warnings),
            "reason": self.reason,
        }


def recommend_video_control(intent: VideoShotIntent) -> VideoControlRecommendation:
    if intent.replacement or intent.relight:
        return VideoControlRecommendation(
            mode="replacement_relight",
            tool="wan_animate_replacement",
            risk="medium",
            required_assets=(
                "reference_image",
                "background_video",
                "subject_mask",
                "WanAnimate_relight_lora",
            ),
            postprocess=(
                "ColorMatchV2",
                "static_background_composite",
                "reference_appearance_lock",
                "deflicker",
            ),
            warnings=(
                "Use the official Wan Animate relighting LoRA only in Replacement mode.",
                "Reject chroma drift; use reference_appearance_lock when the source "
                "frame already has the desired lighting.",
            ),
            reason="The subject must inherit lighting from an existing background.",
        )

    if (
        intent.motion == "none"
        and intent.camera == "moving"
        and intent.background == "static"
    ):
        return VideoControlRecommendation(
            mode="free",
            tool="deterministic_camera",
            risk="low",
            required_assets=("reference_image",),
            postprocess=(
                "video_control/v1",
                "video_review_packet/v1",
            ),
            warnings=(
                "Use only bounded push, pull, or pan declared in "
                "deterministic_camera/v1.",
                "Do not use this route when new background areas or physical "
                "parallax must be revealed.",
            ),
            reason=(
                "The approved still needs whole-frame camera motion without "
                "generative redrawing."
            ),
        )

    if intent.motion == "none" and intent.camera == "locked":
        return VideoControlRecommendation(
            mode="pixel_locked",
            tool="deterministic_2d_compositor",
            risk="low",
            required_assets=("reference_image",),
            postprocess=("ffmpeg_encode",),
            warnings=(),
            reason="No generative motion is needed, so source pixels should remain locked.",
        )

    if intent.motion == "micro":
        if intent.contains_hands or intent.contains_phone:
            return VideoControlRecommendation(
                mode="pixel_locked",
                tool="deterministic_2d_compositor",
                risk="low",
                required_assets=("reference_image",),
                postprocess=("localized_light_or_particle_effect", "ffmpeg_encode"),
                warnings=(
                    "Do not ask I2V to freeze a visible hand or phone with prompt text alone.",
                    "Crop hands and phone out before using LivePortrait for facial motion.",
                ),
                reason="Visible hands or phones make generative micro-motion unstable.",
            )
        if intent.framing in {"detail", "head_shoulders"} and not intent.multi_person:
            if intent.audio_driven:
                if not intent.lip_sync_required:
                    return VideoControlRecommendation(
                        mode="micro_motion",
                        tool="liveportrait",
                        risk="low",
                        required_assets=(
                            "reference_image",
                            "face_driver_or_motion_template",
                            "voiceover_audio",
                        ),
                        postprocess=("ColorMatchV2", "deflicker", "audio_mux"),
                        warnings=(
                            "Voiceover is present but exact lip synchronization is "
                            "intentionally disabled for stability.",
                        ),
                        reason="The shot prioritizes stable anime motion over exact lip sync.",
                    )
                if intent.visual_style == "anime":
                    return VideoControlRecommendation(
                        mode="micro_motion",
                        tool="sonic",
                        risk="high",
                        required_assets=("reference_image", "driven_audio"),
                        postprocess=(
                            "ColorMatchV2",
                            "deflicker",
                            "quality_gate",
                            "visual_review_packet",
                        ),
                        warnings=(
                            "Anime Sonic output is experimental and must never bypass "
                            "candidate comparison and visual review.",
                            "Block the shot when Sonic weights are unavailable; do not "
                            "silently fall back to SadTalker.",
                        ),
                        reason="Exact anime lip sync requires a dedicated audio portrait model.",
                    )
                return VideoControlRecommendation(
                    mode="micro_motion",
                    tool="sadtalker",
                    risk="medium",
                    required_assets=("reference_image", "driven_audio"),
                    postprocess=("ColorMatchV2", "deflicker", "quality_gate"),
                    warnings=(
                        "Use only as a square talking-head source; never stretch it "
                        "into a full-body layer.",
                        "Prefer a front or mild three-quarter face without visible hands.",
                    ),
                    reason="The close portrait needs audio-synchronized mouth motion.",
                )
            return VideoControlRecommendation(
                mode="micro_motion",
                tool="liveportrait",
                risk="low",
                required_assets=("reference_image", "face_driver_or_motion_template"),
                postprocess=("ColorMatchV2", "deflicker"),
                warnings=(),
                reason="A single close portrait can be animated without regenerating the body.",
            )
        return VideoControlRecommendation(
            mode="micro_motion",
            tool="framepack",
            risk="medium",
            required_assets=("reference_image",),
            postprocess=("ColorMatchV2", "deflicker"),
            warnings=("Reject any hand, identity, or camera drift before interpolation.",),
            reason="The shot needs restrained body motion without a moving camera.",
        )

    if (
        intent.motion in {"subject", "action"}
        and intent.camera == "locked"
        and intent.background == "static"
    ):
        warnings: list[str] = []
        if intent.multi_person:
            warnings.append("Animate one primary subject per pass and composite with separate masks.")
        if intent.contains_hands or intent.contains_phone:
            warnings.append("Use a clean hand-visible driver; inspect fingers and object contact every pass.")
        return VideoControlRecommendation(
            mode="subject_only",
            tool="wan_animate_move",
            risk="high" if warnings else "medium",
            required_assets=("reference_image", "driver_video", "subject_mask"),
            postprocess=(
                "ColorMatchV2",
                "static_background_composite",
                "reference_appearance_lock",
                "deflicker",
            ),
            warnings=tuple(warnings),
            reason="Only the masked subject may move while the source background is restored.",
        )

    return VideoControlRecommendation(
        mode="free",
        tool="wan_or_ltx_i2v",
        risk="high",
        required_assets=("reference_image",),
        postprocess=("ColorMatchV2", "deflicker", "quality_gate"),
        warnings=(
            "Free generation cannot guarantee identity, hands, object position, or camera lock.",
        ),
        reason="Moving camera, dynamic background, or unrestricted action requires free generation.",
    )


def _choice(
    value: dict[str, object],
    key: str,
    choices: set[str],
    *,
    default: str | None = None,
) -> str:
    raw = value.get(key, default)
    if not isinstance(raw, str) or raw not in choices:
        options = ", ".join(sorted(choices))
        raise ValueError(f"intent.{key} must be one of: {options}")
    return raw


def _boolean(value: dict[str, object], key: str, default: bool) -> bool:
    raw = value.get(key, default)
    if not isinstance(raw, bool):
        raise ValueError(f"intent.{key} must be a boolean")
    return raw
