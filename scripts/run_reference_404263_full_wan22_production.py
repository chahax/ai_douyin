"""Render the approved 404263 full visual timeline with real pose-driven motion.

This is the post-review production runner.  It deliberately does not read any
previous 69-shot candidate video or its visual segments.  Character shots are
rendered by Wan2.2 Animate Move with DWPose extracted from the reference video;
the source RGB and face video are never passed to Wan.  Script-designated UI,
prop and evidence inserts are rendered as explicit deterministic animations.

The final approved 064b-064f review clips are reused byte-for-byte.  They are
already the accepted Wan/DWPose continuity chain (plus the deterministic 064c
phone insert), not material from an old candidate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from run_reference_404263_bighead_move_review import (
    copy_sequence,
    encode_sequence,
    graph,
    output_images,
    request_json,
    wait_history,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_VIDEO = ROOT / "40426344181-1-192.mp4"
PROJECT = (
    ROOT
    / "data/qa/reference_404263_detailed_two_style_full_20260826/bighead3d"
    / "story_project.json"
)
KEYFRAME_DIR = (
    ROOT
    / "data/qa/reference_404263_detailed_two_style_full_20260826/bighead3d"
    / "full_keyframes/keyframes"
)
MASTER_DIR = (
    ROOT
    / "data/qa/reference_404263_detailed_two_style_full_20260826/bighead3d"
    / "character_masters_selected/keyframes"
)
APPROVED_064_DIR = (
    ROOT / "data/qa/reference_404263_bighead_move_review_20260827_v5_script_064"
)
DEFAULT_OUTPUT = ROOT / "data/qa/reference_404263_full_wan22_production_20260827"
DEFAULT_COMFY_ROOT = Path(r"D:\IT\AI_vido\ComfyUI")
INPUT_NAMESPACE = "reference_404263_full_wan22_production_20260827"


DETERMINISTIC_IDS = {
    "003", "005", "011", "016", "019", "023", "025", "028", "029", "035",
    "037", "042", "044", "046", "048", "052", "055", "056", "057", "061",
    "063", "064c",
}

# Run these before the ordinary performance coverage.  They are the actions
# most likely to reveal pose, hand, multi-person or contact failures.
PRIORITY_IDS = {
    "001", "015", "017", "032", "039", "049", "058", "059", "060",
}

HAND_IDS = {
    "002", "004", "006", "007", "009", "014", "017", "018", "020",
    "022", "024", "027", "031", "032", "033", "036", "038", "039",
    "040", "041", "043", "045", "047", "050", "051", "053", "058",
    "059", "060", "062", "064a",
}

# Shot-specific seed alternatives selected only after a visual rejection.  A
# seed bump never changes the locked prompt, role assets, pose path or style.
SEED_BUMPS = {"014": 311}

APPROVED_REUSE = {
    "064b": APPROVED_064_DIR / "shots/064b_chen_confused/064b_chen_confused_wan22_animate_move.mp4",
    "064c": APPROVED_064_DIR / "review_shots/064c_cracked_phone_insert.mp4",
    "064d": APPROVED_064_DIR / "shots/064d_chen_reaches_phone/064d_chen_reaches_phone_approved.mp4",
    "064e": APPROVED_064_DIR / "shots/064e_chen_phone_to_ear/064e_chen_phone_to_ear_wan22_animate_move.mp4",
    "064f": APPROVED_064_DIR / "shots/064f_chen_waits_shoulders_sink/064f_chen_waits_shoulders_sink_wan22_animate_move.mp4",
}

# The adaptation timeline is an edit timeline, not a direct timestamp map into
# the source.  These ranges were selected by the visible physical action in the
# source, never by matching clock time alone.
SOURCE_RANGES = {
    "001": (0.00, 1.40), "002": (1.00, 2.80), "004": (4.05, 5.20),
    "006": (5.20, 6.55), "007": (5.70, 6.45), "008": (7.00, 8.20),
    "009": (9.10, 9.75), "010": (9.65, 11.60), "012": (12.70, 14.10),
    # Keep 015 entirely inside the operator reaction setup. The old range
    # crossed a doorway-to-operator source edit and caused an internal cut.
    "013": (16.00, 17.40), "014": (17.10, 18.30), "015": (15.20, 16.45),
    "016": (17.00, 18.20),
    "018": (21.80, 24.80), "020": (20.00, 21.70), "021": (21.00, 23.90),
    "022": (29.00, 31.50), "024": (37.00, 38.60), "026": (38.00, 39.40),
    "027": (40.00, 41.70), "030": (46.00, 47.20), "031": (29.00, 30.25),
    "032": (52.00, 54.30), "033": (53.20, 55.30), "034": (52.20, 54.30),
    "036": (54.00, 55.30), "038": (58.80, 59.80), "039": (46.00, 48.50),
    "040": (63.00, 64.20), "041": (64.00, 65.30), "043": (67.20, 68.60),
    "045": (68.80, 70.30), "047": (72.00, 73.40), "049": (73.72, 74.34),
    "050": (75.30, 76.60), "051": (76.20, 77.50), "053": (77.40, 78.60),
    "054": (79.00, 79.90), "058": (84.50, 85.70), "059": (87.00, 87.66),
    "060": (87.72, 88.82), "062": (87.50, 88.50), "064a": (90.00, 91.10),
}

# 017 is a continuity bridge absent from the source edit.  This local pose-map
# clip was itself produced by DWPose and contains two independent figures with
# a controlled lowering/kneeling path.  Wan sees pose pixels only.
PRECOMPUTED_POSE_DRIVERS = {
    "014": ROOT / "data/qa/hospital_video/shot014_pose_driver_point_two_person_320x576_16fps.mp4",
    "016": ROOT / "data/qa/hospital_video/shot016_pose_driver_eye_closeup_320x576_16fps.mp4",
    "017": ROOT / "data/qa/hospital_video/shot017_pose_driver_chair_sit_reviewed_320x576_16fps.mp4",
    "018": ROOT / "data/qa/hospital_video/shot018_pose_driver_bow_point_two_person_320x576_16fps.mp4",
    # Reversed and horizontally mirrored from the same genuine two-person
    # DWPose sequence: the larger operator on camera-right rises while the
    # smaller lead on camera-left remains seated.
    "039": ROOT / "data/qa/hospital_video/shot039_pose_driver_rise_two_person_320x576_16fps.mp4",
    "049": ROOT / "data/qa/hospital_video/shot049_pose_driver_two_steps_320x576_16fps.mp4",
    "059": ROOT / "data/qa/hospital_video/shot059_pose_driver_reaction_two_person_320x576_16fps.mp4",
    "060": ROOT / "data/qa/hospital_video/shot060_pose_driver_control_two_person_320x576_16fps.mp4",
}

NEGATIVE = (
    "photorealistic, live action, real actor, realistic skin pores, controlled v4 "
    "visual style, child, minor, mascot, doll, identity drift, face replacement, "
    "shared face, duplicate person, character merging, hairstyle change, clothing "
    "change, extra person, missing person, extra arm, extra hand, giant hand, extra "
    "fingers, fused fingers, broken wrist, floating limb, malformed body, phone fused "
    "to hand, phone changing shape, duplicate phone, readable generated text, subtitle, "
    "logo, watermark, camera push in, zoom, pan, internal cut, scene rebuild, background "
    "jump, body teleport, frozen body, repeated beginning, loop, exposure pumping"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def run(command: list[str], timeout: int = 900) -> None:
    completed = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=timeout,
    )
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            + completed.stderr[-5000:]
        )


def wan_length(seconds: float) -> int:
    """Smallest 4n+1 length covering the timeline duration at 16 fps."""
    requested = max(17, int(math.ceil(seconds * 16.0)))
    return int(math.ceil((requested - 1) / 4.0) * 4 + 1)


def centered_reference(image: Path, destination: Path) -> None:
    frame = cv2.imread(str(image), cv2.IMREAD_COLOR)
    if frame is None:
        raise FileNotFoundError(image)
    height, width = frame.shape[:2]
    target_ratio = 320 / 576
    if width / height > target_ratio:
        crop_width = round(height * target_ratio)
        left = max(0, (width - crop_width) // 2)
        frame = frame[:, left:left + crop_width]
    else:
        crop_height = round(width / target_ratio)
        top = max(0, (height - crop_height) // 2)
        frame = frame[top:top + crop_height, :]
    frame = cv2.resize(frame, (320, 576), interpolation=cv2.INTER_LANCZOS4)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(destination), frame):
        raise RuntimeError(f"failed to write {destination}")


def prepare_driver(shot: dict[str, object], destination: Path, length: int) -> None:
    shot_id = str(shot["id"])
    start, end = SOURCE_RANGES.get(
        shot_id,
        (float(shot["timeline_start_seconds"]), float(shot["timeline_end_seconds"])),
    )
    # The reviewed ending used safer pose excerpts; those accepted clips are
    # reused and therefore never reach this path.
    duration = max(0.20, end - start)
    # Keep the complete native 9:16 frame.  A center crop was acceptable for
    # the reviewed Chen close-ups but incorrectly removed feet from full-body
    # walking and arrest actions in the full timeline.
    # Re-time the selected semantic action to the exact Wan conditioning
    # length. This prevents short, clean source actions from ending early and
    # being internally repeated, while still preserving their complete A-to-B
    # pose path.
    target_duration = length / 16.0
    speed_ratio = target_duration / duration
    vf = (
        f"setpts={speed_ratio:.10f}*PTS,"
        "scale=320:576:flags=lanczos,fps=16,setsar=1"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    run([
        "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}",
        "-t", f"{duration:.3f}", "-i", str(SOURCE_VIDEO), "-vf", vf,
        "-frames:v", str(length), "-an", "-c:v", "libx264", "-pix_fmt",
        "yuv420p", "-crf", "16", str(destination),
    ])


def positive_prompt(shot: dict[str, object], project: dict[str, object]) -> str:
    participants = list(shot.get("participants") or [])
    bible = dict(project["character_bible"])
    identities = "; ".join(
        str(bible[name]["prompt"]) for name in participants if name in bible
    )
    visual = dict(shot.get("visual_translation") or {})
    composition = str(visual.get("composition_en") or shot.get("composition_contract") or "")
    situation = str(visual.get("visible_scene_en") or "")
    motion = str(visual.get("motion_en") or shot.get("motion") or "")
    identity_clause = (
        f"The only recurring characters in this shot are: {identities}. "
        if identities else "No recurring character identity is required in this shot. "
    )
    return (
        "Vertical 9:16 premium cinematic stylized 3D adult animation in the exact "
        "approved 404263 bighead-adult style, never photorealistic. Chinese adults "
        "with moderately oversized individually shaped mature heads, anatomically "
        "adult compact bodies, expressive mature eyes, softly modeled stylized skin, "
        "detailed hair and cloth, feature-film lighting and shallow depth of field. "
        + identity_clause
        + f"Preserve the supplied reference composition and every existing person, prop, "
        f"costume, light source and camera axis. Composition: {composition}. "
        f"Situation: {situation}. Animate exactly this continuous physical action: {motion}. "
        "Use the DWPose path as body-motion guidance only. Natural adult weight and "
        "inertia, coherent feet and hands, stable identity, stable prop count, one clear "
        "action path, locked camera, no internal cut, no invented gesture."
    )


def deterministic_base(keyframe: Path) -> np.ndarray:
    frame = cv2.imread(str(keyframe), cv2.IMREAD_COLOR)
    if frame is None:
        raise FileNotFoundError(keyframe)
    height, width = frame.shape[:2]
    crop_width = round(height * 320 / 576)
    if crop_width <= width:
        left = max(0, (width - crop_width) // 2)
        frame = frame[:, left:left + crop_width]
    else:
        crop_height = round(width * 576 / 320)
        top = max(0, (height - crop_height) // 2)
        frame = frame[top:top + crop_height, :]
    return cv2.resize(frame, (320, 576), interpolation=cv2.INTER_LANCZOS4)


def cyan_components(frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([75, 65, 90]), np.array([115, 255, 255]))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    boxes: list[tuple[int, int, int, int]] = []
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if 30 <= area <= 30000 and width >= 5 and height >= 5:
            boxes.append((int(x), int(y), int(width), int(height)))
    boxes.sort(key=lambda box: (box[1], box[0]))
    return boxes[:12]


def overlay_alpha(frame: np.ndarray, overlay: np.ndarray, alpha: float) -> np.ndarray:
    return cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0.0)


def render_deterministic(shot: dict[str, object], output: Path) -> None:
    """Create shot-specific on-screen motion; never apply a generic camera push."""
    shot_id = str(shot["id"])
    if shot_id == "064c":
        source = APPROVED_REUSE[shot_id]
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output)
        return
    seconds = float(shot["duration"])
    frames = max(2, round(seconds * 16))
    override = output.parents[2] / "reference_overrides" / f"{shot_id}.png"
    base_source = override if override.is_file() else KEYFRAME_DIR / f"{shot_id}.png"
    base = deterministic_base(base_source)
    boxes = cyan_components(base)
    temp_dir = output.parent / f".{shot_id}_deterministic_frames"
    temp_dir.mkdir(parents=True, exist_ok=True)
    for index in range(frames):
        t = index / max(1, frames - 1)
        frame = base.copy()
        layer = frame.copy()
        if shot_id in {"005", "011", "029"}:
            if not boxes:
                boxes = [(55, 150, 70, 110), (170, 210, 75, 115), (105, 350, 75, 115)]
            active = max(1, min(len(boxes), int(t * len(boxes) + 0.999)))
            for box in boxes[:active]:
                x, y, width, height = box
                cv2.rectangle(layer, (x, y), (x + width, y + height), (255, 245, 150), -1)
            frame = overlay_alpha(frame, layer, 0.20)
            if shot_id == "011":
                x = round(45 + 220 * t)
                y = round(420 - 130 * math.sin(math.pi * t))
                cv2.circle(frame, (x, y), 10, (205, 220, 230), -1, cv2.LINE_AA)
        elif shot_id in {"003", "019", "025", "028"}:
            start_y, end_y = (220, 360) if shot_id == "019" else (260, 330)
            y = round(start_y + (end_y - start_y) * min(1.0, t * 1.5))
            x = 160
            cv2.circle(frame, (x, y), 10, (218, 230, 238), -1, cv2.LINE_AA)
            pulse = max(0.0, 1.0 - abs(t - 0.72) * 8.0)
            cv2.circle(frame, (x, y), round(12 + 18 * pulse), (255, 235, 110), 2, cv2.LINE_AA)
            if t > 0.74 and shot_id in {"025", "028"}:
                cv2.circle(frame, (160, 330), 22, (85, 185, 100), -1, cv2.LINE_AA)
                cv2.line(frame, (149, 330), (158, 339), (255, 255, 255), 3, cv2.LINE_AA)
                cv2.line(frame, (158, 339), (174, 320), (255, 255, 255), 3, cv2.LINE_AA)
        elif shot_id == "016":
            # Shot-specific eyelid descent on the locked extreme close-up.
            # Only the upper lash curve and moist lower-lid highlights change;
            # the camera, face geometry and all other pixels stay fixed.
            closure = t * t * (3.0 - 2.0 * t)
            for center_x in (108, 211):
                center_y = 224
                layer = frame.copy()
                lid_points = []
                for delta_x in range(-30, 31, 3):
                    lid_y = round(
                        center_y - 13 + 3.5 * closure
                        + 0.006 * delta_x * delta_x
                    )
                    lid_points.append((center_x + delta_x, lid_y))
                cv2.polylines(
                    layer, [np.array(lid_points, dtype=np.int32)], False,
                    (35, 28, 32), 2, cv2.LINE_AA,
                )
                wet_alpha = 0.18 + 0.22 * math.sin(math.pi * t) ** 2
                cv2.ellipse(
                    layer, (center_x, center_y + 12), (20, 3), 0, 12, 168,
                    (225, 225, 220), 1, cv2.LINE_AA,
                )
                frame = overlay_alpha(frame, layer, 0.36 + wet_alpha)
        elif shot_id == "023":
            # The script explicitly specifies a locked still city frame.
            pass
        elif shot_id == "035":
            if 0.58 < t < 0.72:
                white = np.full_like(frame, 255)
                frame = overlay_alpha(frame, white, 0.75 * (1.0 - abs(t - 0.65) / 0.07))
            cv2.circle(frame, (276, 520), 18, (245, 245, 245), 2, cv2.LINE_AA)
        elif shot_id == "037":
            thumb = cv2.resize(base[180:330, 95:225], (74, 92))
            for slot in range(min(3, int(t * 4))):
                x = 25 + slot * 93
                y = 245 + (slot % 2) * 38
                frame[y:y + 92, x:x + 74] = thumb
                cv2.rectangle(frame, (x - 2, y - 2), (x + 76, y + 94), (230, 245, 255), 2)
        elif shot_id == "042":
            x = round(-80 + 480 * t)
            shine = np.zeros_like(frame)
            cv2.line(shine, (x, 0), (x - 130, 576), (255, 255, 255), 24, cv2.LINE_AA)
            frame = cv2.add(frame, (shine * 0.42).astype(np.uint8))
        elif shot_id == "044":
            top = round(-150 + 360 * min(1.0, t * 1.2))
            cv2.rectangle(frame, (92, top), (232, top + 210), (235, 238, 236), -1)
            for line_y in range(top + 25, top + 180, 24):
                cv2.line(frame, (110, line_y), (214, line_y), (150, 160, 160), 2)
        elif shot_id == "046":
            x = round(35 + 155 * min(1.0, t * 1.25))
            y = round(410 - 125 * min(1.0, t * 1.25))
            cv2.rectangle(frame, (x, y), (x + 92, y + 55), (75, 120, 175), -1)
            if t > 0.72:
                cv2.circle(frame, (230, 290), 18 + round(12 * (t - 0.72)), (120, 245, 255), 2)
        elif shot_id == "048":
            values = ["+500", "+1200", "+8000", "+36000"]
            value = values[min(len(values) - 1, int(t * len(values)))]
            cv2.rectangle(frame, (58, 230), (262, 344), (25, 44, 58), -1)
            cv2.putText(frame, value, (84, 303), cv2.FONT_HERSHEY_DUPLEX, 1.25, (130, 245, 190), 2, cv2.LINE_AA)
        elif shot_id == "052":
            ease = 1.0 - (1.0 - min(1.0, t * 2.2)) ** 3
            top = round(-90 + 155 * ease)
            cv2.rectangle(frame, (35, top), (285, top + 76), (225, 245, 250), -1)
            cv2.circle(frame, (68, top + 38), 18, (90, 185, 225), -1, cv2.LINE_AA)
            cv2.line(frame, (100, top + 28), (255, top + 28), (90, 110, 120), 4)
            cv2.line(frame, (100, top + 48), (220, top + 48), (150, 165, 170), 3)
        elif shot_id == "055":
            center = (160, 360)
            growth = min(1.0, t * 1.4)
            cv2.ellipse(frame, center, (round(25 + 115 * growth), round(8 + 42 * growth)), 0, 180, 360, (205, 235, 250), 4, cv2.LINE_AA)
            for arm in range(7):
                angle = math.radians(195 + arm * 25)
                length = 35 + 135 * growth
                end = (round(center[0] + math.cos(angle) * length), round(center[1] + math.sin(angle) * length))
                cv2.line(frame, center, end, (205, 235, 250), max(1, round(5 * (1.0 - t * 0.4))), cv2.LINE_AA)
        elif shot_id == "056":
            center = (160, 300)
            for phase in (0.0, 0.22, 0.44):
                radius = int(18 + 185 * max(0.0, t - phase))
                if radius > 18:
                    cv2.ellipse(frame, center, (radius, max(5, radius // 3)), 0, 0, 360, (185, 220, 235), 2, cv2.LINE_AA)
        elif shot_id == "057":
            pulse = 0.65 + 0.35 * math.sin(t * math.pi * 4) ** 2
            cv2.circle(frame, (160, 300), 44, (35, 45, 180), -1, cv2.LINE_AA)
            cv2.line(frame, (145, 285), (175, 315), (255, 255, 255), max(2, round(5 * pulse)), cv2.LINE_AA)
            cv2.line(frame, (175, 285), (145, 315), (255, 255, 255), max(2, round(5 * pulse)), cv2.LINE_AA)
        elif shot_id == "061":
            gap = round(42 * (1.0 - min(1.0, t * 1.4)))
            cv2.ellipse(frame, (130 - gap, 315), (38, 55), 0, 0, 360, (190, 200, 210), 5, cv2.LINE_AA)
            cv2.ellipse(frame, (190 + gap, 315), (38, 55), 0, 0, 360, (190, 200, 210), 5, cv2.LINE_AA)
            cv2.line(frame, (155 - gap, 315), (165 + gap, 315), (190, 200, 210), 6)
        elif shot_id == "063":
            bag_top = round(430 - 125 * min(1.0, t * 1.3))
            translucent = frame.copy()
            cv2.rectangle(translucent, (72, bag_top), (248, 525), (190, 210, 205), -1)
            frame = overlay_alpha(frame, translucent, 0.28)
            zipper_x = round(72 + 176 * min(1.0, max(0.0, (t - 0.55) * 2.2)))
            cv2.line(frame, (72, bag_top), (zipper_x, bag_top), (235, 240, 238), 4)
        else:
            raise ValueError(f"unimplemented deterministic shot: {shot_id}")
        cv2.imwrite(str(temp_dir / f"frame_{index:04d}.png"), frame)
    output.parent.mkdir(parents=True, exist_ok=True)
    run([
        "ffmpeg", "-y", "-loglevel", "error", "-framerate", "16", "-i",
        str(temp_dir / "frame_%04d.png"), "-c:v", "libx264", "-pix_fmt",
        "yuv420p", "-crf", "18", "-movflags", "+faststart", str(output),
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--comfy-root", type=Path, default=DEFAULT_COMFY_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--steps", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--priority-only", action="store_true")
    parser.add_argument("--shot", action="append", help="render only an exact shot id")
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()

    for path in (SOURCE_VIDEO, PROJECT, KEYFRAME_DIR, MASTER_DIR):
        if not path.exists():
            raise FileNotFoundError(path)
    for path in APPROVED_REUSE.values():
        if not path.is_file():
            raise FileNotFoundError(path)

    project = json.loads(PROJECT.read_text(encoding="utf-8"))
    shots = list(project["shots"])
    if len(shots) != 69 or abs(float(project["duration_seconds"]) - 104.3) > 0.001:
        raise ValueError("production requires the locked 69-segment / 104.3-second project")
    requested = set(args.shot or [])
    known = {str(shot["id"]) for shot in shots}
    if requested - known:
        raise ValueError(f"unknown shots: {sorted(requested - known)}")
    if requested:
        shots = [shot for shot in shots if str(shot["id"]) in requested]
    elif args.priority_only:
        shots = [shot for shot in shots if str(shot["id"]) in PRIORITY_IDS]

    output_dir = args.output_dir.resolve()
    comfy_root = args.comfy_root.resolve()
    comfy_input = comfy_root / "input"
    comfy_output = comfy_root / "output"
    input_dir = comfy_input / INPUT_NAMESPACE
    if not comfy_input.is_dir() or not comfy_output.is_dir():
        raise FileNotFoundError("ComfyUI input/output directory is unavailable")
    output_dir.mkdir(parents=True, exist_ok=True)
    input_dir.mkdir(parents=True, exist_ok=True)

    object_info = request_json(f"{args.base_url}/object_info")
    required = {"WanAnimateToVideo", "DWPreprocessor", "LoadVideo", "SaveImage"}
    missing = sorted(required - set(object_info))
    if missing:
        raise RuntimeError(f"ComfyUI is missing required nodes: {missing}")

    master_hashes = {
        path.stem: sha256(path) for path in sorted(MASTER_DIR.glob("*.png"))
    }
    rows: list[dict[str, object]] = []
    for shot in shots:
        shot_id = str(shot["id"])
        clip_dir = output_dir / "clips" / shot_id
        clip_dir.mkdir(parents=True, exist_ok=True)
        clip = clip_dir / f"{shot_id}.mp4"
        report_path = clip_dir / "render.report.json"
        if args.skip_existing and clip.is_file() and report_path.is_file():
            rows.append(json.loads(report_path.read_text(encoding="utf-8")))
            print(json.dumps({"event": "skipped", "shot": shot_id}), flush=True)
            continue

        if shot_id in APPROVED_REUSE:
            shutil.copy2(APPROVED_REUSE[shot_id], clip)
            row = {
                "id": shot_id,
                "status": "approved_review_clip_reused",
                "renderer": "Wan2.2 Animate Move + DWPose" if shot_id != "064c" else "deterministic_UI",
                "source": str(APPROVED_REUSE[shot_id]),
                "source_sha256": sha256(APPROVED_REUSE[shot_id]),
                "video": str(clip),
                "video_sha256": sha256(clip),
                "old_candidate_visual_used": False,
            }
        elif shot_id in DETERMINISTIC_IDS:
            render_deterministic(shot, clip)
            deterministic_override = output_dir / "reference_overrides" / f"{shot_id}.png"
            deterministic_reference = (
                deterministic_override
                if deterministic_override.is_file()
                else KEYFRAME_DIR / f"{shot_id}.png"
            )
            row = {
                "id": shot_id,
                "status": "generated",
                "renderer": "deterministic_shot_specific_animation",
                "reference_keyframe": str(deterministic_reference),
                "reference_keyframe_sha256": sha256(deterministic_reference),
                "generic_camera_push_used": False,
                "video": str(clip),
                "video_sha256": sha256(clip),
                "old_candidate_visual_used": False,
            }
        else:
            length = wan_length(float(shot["duration"]))
            driver = output_dir / "drivers" / f"{shot_id}_dwpose_source_16fps.mp4"
            reference = output_dir / "references" / f"{shot_id}_scene_reference.png"
            precomputed_pose = PRECOMPUTED_POSE_DRIVERS.get(shot_id)
            if precomputed_pose is not None:
                if not precomputed_pose.is_file():
                    raise FileNotFoundError(precomputed_pose)
                driver.parent.mkdir(parents=True, exist_ok=True)
                run([
                    "ffmpeg", "-y", "-loglevel", "error", "-i", str(precomputed_pose),
                    "-vf", "scale=320:576:flags=neighbor,fps=16,setsar=1", "-frames:v",
                    str(length), "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", "10", str(driver),
                ])
            else:
                prepare_driver(shot, driver, length)
            override = output_dir / "reference_overrides" / f"{shot_id}.png"
            participants = list(shot.get("participants") or [])
            single_master = (
                MASTER_DIR / f"{participants[0]}.png"
                if len(participants) == 1
                else None
            )
            if override.is_file():
                reference_source = override
                reference_kind = "identity_corrected_from_locked_character_masters"
            elif single_master is not None and single_master.is_file():
                # For one-person shots the selected master is the strongest
                # identity lock.  Wan/DWPose and the shot prompt reconstruct the
                # scene, as in the user-approved Chen ending chain.
                reference_source = single_master
                reference_kind = "locked_character_master_direct"
            else:
                reference_source = KEYFRAME_DIR / f"{shot_id}.png"
                reference_kind = "Flux_IPAdapter_from_locked_character_master"
            centered_reference(reference_source, reference)
            reference_input = input_dir / f"{shot_id}_reference.png"
            driver_input = input_dir / f"{shot_id}_driver.mp4"
            shutil.copy2(reference, reference_input)
            shutil.copy2(driver, driver_input)
            seed_value = int(shot["seed"]) + 20000 + SEED_BUMPS.get(shot_id, 0)
            workflow = graph(
                image_name=f"{INPUT_NAMESPACE}/{reference_input.name}",
                driver_name=f"{INPUT_NAMESPACE}/{driver_input.name}",
                prefix=f"{INPUT_NAMESPACE}/{shot_id}/generated",
                seed=seed_value,
                width=320,
                height=576,
                length=length,
                steps=args.steps,
                positive=positive_prompt(shot, project),
                negative=NEGATIVE,
                include_face_video=False,
            )
            workflow["14"]["inputs"]["detect_hand"] = "enable" if shot_id in HAND_IDS else "disable"
            workflow["14"]["inputs"]["detect_face"] = "disable"
            if precomputed_pose is not None:
                workflow["15"]["inputs"]["pose_video"] = ["13", 0]
            workflow["21"] = {
                "class_type": "SaveImage",
                "inputs": {
                    "images": ["13", 0] if precomputed_pose is not None else ["14", 0],
                    "filename_prefix": f"{INPUT_NAMESPACE}/{shot_id}/pose",
                },
            }
            workflow_path = clip_dir / "workflow.api.json"
            workflow_path.write_text(
                json.dumps(workflow, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            response = request_json(
                f"{args.base_url}/prompt",
                {"prompt": workflow, "client_id": str(uuid.uuid4())},
            )
            prompt_id = str(response["prompt_id"])
            print(json.dumps({"event": "queued", "shot": shot_id, "prompt_id": prompt_id}), flush=True)
            history = wait_history(args.base_url, prompt_id, args.timeout)
            generated = output_images(history, "20", comfy_output)
            poses = output_images(history, "21", comfy_output)
            if len(generated) != length:
                raise RuntimeError(f"{shot_id}: expected {length} frames, got {len(generated)}")
            frame_dir = clip_dir / "generated_frames"
            pose_dir = clip_dir / "dwpose_frames"
            copy_sequence(generated, frame_dir, "frame")
            copy_sequence(poses, pose_dir, "pose")
            encode_sequence(frame_dir, "frame_%04d.png", clip)
            pose_clip = clip_dir / f"{shot_id}_dwpose_preview.mp4"
            if poses:
                encode_sequence(pose_dir, "pose_%04d.png", pose_clip, even_dimensions=True)
            row = {
                "id": shot_id,
                "status": "generated_pending_full_timeline_qa",
                "renderer": "Wan2.2 Animate Move 14B + DWPose",
                "approved_style": "cinematic_3d_bighead_adult",
                "forbidden_style": "controlled_v4_photorealistic",
                "participants": participants,
                "approved_character_master_hashes": {
                    name: master_hashes[name] for name in participants if name in master_hashes
                },
                "reference_keyframe": str(reference_source),
                "reference_keyframe_sha256": sha256(reference_source),
                "reference_keyframe_provenance": reference_kind,
                "source_video_used_for_dwpose_only": True,
                "source_video_pixels_directly_included": False,
                "source_face_video_used": False,
                "source_audio_used": False,
                "old_candidate_visual_used": False,
                "timeline_seconds": [shot["timeline_start_seconds"], shot["timeline_end_seconds"]],
                "motion_contract": shot.get("visual_translation", {}).get("motion_en"),
                "prompt_id": prompt_id,
                "seed": seed_value,
                "steps": args.steps,
                "width": 320,
                "height": 576,
                "fps": 16,
                "frame_count": length,
                "driver": str(driver),
                "driver_sha256": sha256(driver),
                "driver_kind": (
                    "precomputed_DWPose_map" if precomputed_pose is not None
                    else "source_RGB_to_DWPose_inside_ComfyUI"
                ),
                "workflow": str(workflow_path),
                "workflow_sha256": sha256(workflow_path),
                "video": str(clip),
                "video_sha256": sha256(clip),
                "dwpose_preview": str(pose_clip) if poses else None,
            }
        report_path.write_text(
            json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        rows.append(row)
        print(json.dumps({"event": "generated", "shot": shot_id, "renderer": row["renderer"]}), flush=True)

    packet = {
        "schema": "reference_404263_full_wan22_production/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "visual_generation_in_progress" if len(shots) < 69 else "visual_generation_complete_pending_qa",
        "approved_style": "cinematic_3d_bighead_adult",
        "forbidden_style": "controlled_v4_photorealistic",
        "locked_character_master_hashes": master_hashes,
        "old_69_candidate_video_used": False,
        "old_69_candidate_visual_segments_used": False,
        "old_69_used_for_script_and_composition_reference_only": True,
        "reference_source_used_for_dwpose_only": True,
        "reference_source_rgb_directly_included": False,
        "generic_first_frame_push_used": False,
        "rendered_shots": rows,
    }
    packet_path = output_dir / "production.packet.json"
    packet_path.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"event": "batch_complete", "packet": str(packet_path)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
