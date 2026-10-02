"""Build a stability-first scene set with deterministic phone UI inserts.

Low-motion scenes use approved original anchors with a restrained push-in.
Only three scenes that need body motion use already reviewed LTX clips. Phone
screens are composited deterministically so text and notification state cannot
flicker or disappear between generated frames.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
QA_ROOT = ROOT / r"data\qa\reference_404263_multiflow_20260825"
PLAN_PATH = ROOT / r"data\fanqie_promotion\scene_plans\reference_404263_original_multiflow_v1.json"
ANCHORS = QA_ROOT / "anchors"
OUTPUT_ROOT = QA_ROOT / "renders" / "stability"
ASSETS = OUTPUT_ROOT / "assets"
CLIPS = OUTPUT_ROOT / "clips_raw"
WORK = OUTPUT_ROOT / "work"
FONT_REGULAR = Path(r"C:\Windows\Fonts\msyh.ttc")
FONT_BOLD = Path(r"C:\Windows\Fonts\msyhbd.ttc")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_BOLD if bold else FONT_REGULAR), size=size)


def rounded_panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int,
    fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int] | None = None,
    width: int = 1,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def screen_canvas(
    *,
    title: str,
    value: str,
    detail: str,
    accent: tuple[int, int, int],
    size: tuple[int, int] = (360, 720),
) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size, (8, 18, 27, 255))
    pixels = image.load()
    for y in range(height):
        ratio = y / max(height - 1, 1)
        for x in range(width):
            glow = max(0.0, 1.0 - abs(x - width * 0.5) / (width * 0.8))
            pixels[x, y] = (
                int(8 + 8 * glow),
                int(18 + 18 * (1.0 - ratio) + 8 * glow),
                int(27 + 28 * (1.0 - ratio) + 12 * glow),
                255,
            )
    draw = ImageDraw.Draw(image, "RGBA")
    draw.text((28, 22), "02:00", font=font(24, bold=True), fill=(232, 243, 248, 255))
    draw.ellipse((width - 75, 30, width - 61, 44), fill=(220, 238, 245, 230))
    draw.ellipse((width - 53, 30, width - 39, 44), fill=(220, 238, 245, 190))
    rounded_panel(
        draw,
        (22, 88, width - 22, 330),
        30,
        (*accent, 238),
        (255, 255, 255, 65),
        2,
    )
    draw.ellipse((48, 120, 116, 188), fill=(255, 255, 255, 235))
    draw.line((68, 155, 84, 171), fill=(*accent, 255), width=8)
    draw.line((84, 171, 102, 139), fill=(*accent, 255), width=8)
    draw.text((136, 118), title, font=font(29, bold=True), fill=(255, 255, 255, 255))
    draw.text((48, 210), value, font=font(43, bold=True), fill=(255, 255, 255, 255))
    draw.text((48, 278), detail, font=font(21), fill=(246, 252, 255, 235))
    draw.text((30, height - 90), "安全提醒：请核实收款人与用途", font=font(19), fill=(166, 190, 204, 220))
    return image


def composite_perspective(base: Image.Image, overlay: Image.Image, quad: list[tuple[int, int]]) -> Image.Image:
    base_array = cv2.cvtColor(np.asarray(base.convert("RGB")), cv2.COLOR_RGB2BGRA)
    overlay_array = cv2.cvtColor(np.asarray(overlay.convert("RGBA")), cv2.COLOR_RGBA2BGRA)
    overlay_height, overlay_width = overlay_array.shape[:2]
    source = np.asarray(
        [(0, 0), (overlay_width - 1, 0), (overlay_width - 1, overlay_height - 1), (0, overlay_height - 1)],
        dtype=np.float32,
    )
    destination = np.asarray(quad, dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(source, destination)
    warped = cv2.warpPerspective(
        overlay_array,
        matrix,
        (base_array.shape[1], base_array.shape[0]),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )
    alpha = warped[:, :, 3:4].astype(np.float32) / 255.0
    composed = base_array[:, :, :3].astype(np.float32) * (1.0 - alpha)
    composed += warped[:, :, :3].astype(np.float32) * alpha
    return Image.fromarray(cv2.cvtColor(composed.astype(np.uint8), cv2.COLOR_BGR2RGB))


def build_anchor_ui_assets() -> dict[str, Path]:
    results: dict[str, Path] = {}
    s01 = Image.open(ANCHORS / "s01_hook_phones.png").convert("RGB")
    notification = screen_canvas(
        title="到账提醒",
        value="¥ 2,000.00",
        detail="收款成功",
        accent=(20, 160, 112),
    )
    s01_quads = [
        [(99, 1120), (294, 1094), (416, 1274), (183, 1336)],
        [(363, 1119), (514, 1101), (681, 1270), (474, 1317)],
        [(587, 1116), (713, 1110), (873, 1231), (711, 1263)],
    ]
    for quad in s01_quads:
        s01 = composite_perspective(s01, notification, quad)
    s01_path = ASSETS / "s01_hook_phones_ui.png"
    s01.save(s01_path, quality=95)
    results["s01_hook_phones"] = s01_path

    s05 = Image.open(ANCHORS / "s05_batch_harvest.png").convert("RGB")
    labels = ["A12", "B07", "C19", "D03", "E11", "F08"]
    quads = [
        [(212, 506), (339, 506), (339, 757), (212, 757)],
        [(405, 504), (527, 504), (527, 758), (405, 758)],
        [(592, 514), (718, 510), (718, 758), (592, 758)],
        [(210, 835), (340, 835), (340, 1098), (210, 1098)],
        [(402, 835), (527, 835), (527, 1097), (402, 1097)],
        [(590, 834), (718, 834), (718, 1098), (590, 1098)],
    ]
    for label, quad in zip(labels, quads, strict=True):
        panel = screen_canvas(
            title="到账",
            value=label,
            detail="记录成功",
            accent=(13, 122, 150),
        )
        s05 = composite_perspective(s05, panel, quad)
    s05_path = ASSETS / "s05_batch_harvest_ui.png"
    s05.save(s05_path, quality=95)
    results["s05_batch_harvest"] = s05_path
    return results


def phone_insert(
    *,
    output: Path,
    theme: str,
) -> None:
    width, height = 1080, 1920
    warm = theme == "transfer"
    top = (51, 35, 21) if warm else (22, 34, 49)
    bottom = (19, 16, 14) if warm else (10, 18, 29)
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y in range(height):
        ratio = y / (height - 1)
        color = tuple(int(top[index] * (1.0 - ratio) + bottom[index] * ratio) for index in range(3))
        for x in range(width):
            distance = abs(x - width / 2) / (width / 2)
            shade = max(0.72, 1.0 - 0.18 * distance)
            pixels[x, y] = tuple(int(value * shade) for value in color)
    draw = ImageDraw.Draw(image, "RGBA")
    rounded_panel(draw, (150, 165, 930, 1725), 82, (4, 7, 10, 255), (110, 125, 134, 180), 5)
    rounded_panel(draw, (182, 220, 898, 1668), 55, (239, 244, 246, 255))
    draw.rounded_rectangle((430, 188, 650, 214), radius=12, fill=(28, 32, 35, 255))

    if warm:
        draw.text((235, 295), "转账确认", font=font(44, bold=True), fill=(34, 42, 46, 255))
        draw.ellipse((420, 455, 660, 695), fill=(22, 166, 111, 255))
        draw.line((474, 578, 532, 638), fill=(255, 255, 255, 255), width=23)
        draw.line((530, 638, 612, 516), fill=(255, 255, 255, 255), width=23)
        draw.text((382, 755), "转账成功", font=font(49, bold=True), fill=(23, 101, 72, 255))
        draw.text((311, 865), "¥ 3,000.00", font=font(67, bold=True), fill=(25, 33, 37, 255))
        rounded_panel(draw, (245, 1035, 835, 1245), 28, (220, 231, 227, 255))
        draw.text((295, 1080), "对方已收款", font=font(36, bold=True), fill=(42, 67, 59, 255))
        draw.text((295, 1150), "交易时间  02:00", font=font(27), fill=(92, 109, 103, 255))
        draw.text((300, 1485), "转账前请再次核实对方身份", font=font(27), fill=(112, 123, 127, 255))
    else:
        draw.text((235, 295), "消息", font=font(44, bold=True), fill=(34, 42, 46, 255))
        rounded_panel(draw, (250, 450, 780, 700), 40, (218, 231, 242, 255))
        draw.text((300, 500), "我住院了，急用钱。", font=font(34), fill=(31, 44, 55, 255))
        draw.text((300, 570), "能把钱还给我吗？", font=font(34), fill=(31, 44, 55, 255))
        draw.ellipse((439, 815, 641, 1017), fill=(210, 61, 68, 255))
        draw.text((502, 825), "!", font=font(120, bold=True), fill=(255, 255, 255, 255))
        draw.text((383, 1075), "发送失败", font=font(54, bold=True), fill=(177, 43, 49, 255))
        draw.text((315, 1170), "对方已无法接收消息", font=font(32), fill=(91, 104, 113, 255))
        rounded_panel(draw, (310, 1360, 770, 1485), 30, (220, 226, 230, 255))
        draw.text((445, 1393), "重试", font=font(34, bold=True), fill=(55, 72, 82, 255))
    image.save(output, quality=95)


def render_still(image: Path, destination: Path, seconds: float, *, zoom: float = 0.012) -> None:
    frames = max(1, int(round(seconds * 30)))
    zoom_step = zoom / frames
    run([
        "ffmpeg", "-y", "-loop", "1", "-framerate", "30", "-i", str(image),
        "-vf",
        (
            f"zoompan=z='min(zoom+{zoom_step:.9f},1.02)':"
            "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d=1:s=1080x1920:fps=30,trim=duration={seconds:.3f},"
            "setpts=PTS-STARTPTS,format=yuv420p"
        ),
        "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-g", "60",
        "-video_track_timescale", "90000", str(destination),
    ])


def normalize_motion(source: Path, destination: Path, seconds: float) -> None:
    run([
        "ffmpeg", "-y", "-i", str(source), "-vf",
        (
            "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
            f"fps=30,tpad=stop_mode=clone:stop_duration=2,trim=duration={seconds:.3f},"
            "setpts=PTS-STARTPTS,format=yuv420p"
        ),
        "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-g", "60",
        "-video_track_timescale", "90000", str(destination),
    ])


def concat(parts: list[Path], destination: Path) -> None:
    listing = destination.with_suffix(".concat.txt")
    listing.write_text(
        "\n".join(f"file '{part.as_posix()}'" for part in parts) + "\n",
        encoding="utf-8",
    )
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(destination)])


def main() -> int:
    for directory in (ASSETS, CLIPS, WORK):
        directory.mkdir(parents=True, exist_ok=True)
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    durations = {str(scene["id"]): float(scene["duration_seconds"]) for scene in plan["scenes"]}
    ui_anchors = build_anchor_ui_assets()
    transfer_ui = ASSETS / "s03_transfer_success_ui.png"
    failed_ui = ASSETS / "s07_send_failed_ui.png"
    phone_insert(output=transfer_ui, theme="transfer")
    phone_insert(output=failed_ui, theme="failed")

    motion_scenes = {"s04_escalation", "s06a_luxury", "s08a_raid"}
    ui_insert_scenes = {
        "s03_true_transfer": (2.1, transfer_ui),
        "s07_blocked_request": (2.25, failed_ui),
    }
    rows: list[dict[str, object]] = []
    for scene in plan["scenes"]:
        scene_id = str(scene["id"])
        seconds = durations[scene_id]
        destination = CLIPS / f"{scene_id}.mp4"
        sources: list[Path] = []
        mode: str
        if scene_id in motion_scenes:
            source = QA_ROOT / "renders" / "ltx" / "clips_raw" / f"{scene_id}.mp4"
            normalize_motion(source, destination, seconds)
            sources = [source]
            mode = "reviewed_ltx_motion"
        elif scene_id in ui_insert_scenes:
            anchor_seconds, ui_path = ui_insert_scenes[scene_id]
            anchor_part = WORK / f"{scene_id}_anchor.mp4"
            ui_part = WORK / f"{scene_id}_ui.mp4"
            anchor = ANCHORS / f"{scene_id}.png"
            render_still(anchor, anchor_part, anchor_seconds, zoom=0.008)
            render_still(ui_path, ui_part, seconds - anchor_seconds, zoom=0.006)
            concat([anchor_part, ui_part], destination)
            sources = [anchor, ui_path]
            mode = "anchor_plus_deterministic_phone_ui"
        else:
            anchor = ui_anchors.get(scene_id, ANCHORS / f"{scene_id}.png")
            render_still(anchor, destination, seconds, zoom=0.008 if scene_id != "s01_hook_phones" else 0.012)
            sources = [anchor]
            mode = "deterministic_phone_ui_anchor" if scene_id in ui_anchors else "approved_anchor_push_in"
        rows.append({
            "scene_id": scene_id,
            "mode": mode,
            "duration_seconds": seconds,
            "sources": [
                {"path": str(source), "sha256": sha256(source)}
                for source in sources
            ],
            "output": str(destination),
            "output_sha256": sha256(destination),
        })
        print(json.dumps({"event": "built", "scene_id": scene_id, "mode": mode}, ensure_ascii=False), flush=True)

    report = {
        "template": "reference_404263_stability_scenes/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "plan_path": str(PLAN_PATH),
        "plan_sha256": sha256(PLAN_PATH),
        "reference_video_pixels_used": False,
        "reference_video_audio_used": False,
        "publish_allowed": False,
        "scenes": rows,
    }
    manifest = OUTPUT_ROOT / "render_manifest.json"
    manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"event": "complete", "manifest": str(manifest)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
