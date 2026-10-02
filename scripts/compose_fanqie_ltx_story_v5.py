from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


P0_ROOT = Path(r"D:\IT\ai_douyin_p0")
if str(P0_ROOT) not in sys.path:
    sys.path.insert(0, str(P0_ROOT))

from src.content_factory.story_video import compose_story_video  # noqa: E402
from src.novel_promotion.live_action_flow import load_live_action_flow  # noqa: E402
from src.novel_promotion.scene_provider import SceneAsset  # noqa: E402
from src.novel_promotion.video_generation_service import _build_manifest  # noqa: E402


DEFAULT_FLOW = Path(
    r"D:\IT\ai_douyin\data\fanqie_promotion\scene_plans\task1_story_v5_live_action_flow_ready.json"
)
DEFAULT_PROGRESS = Path(
    r"D:\IT\ai_douyin\data\fanqie_promotion\renders\task1_story_v5_full\batch_progress.json"
)
DEFAULT_OUTPUT = Path(
    r"D:\IT\ai_douyin\data\fanqie_promotion\renders\task1_story_v5_full\task1_story_v5_review.mp4"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _srt_time(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _wrap_zh(text: str, width: int = 22) -> str:
    """Wrap Chinese at nearby punctuation without leading punctuation lines."""
    remaining = "".join(text.split())
    punctuation = "，。！？；：、,.!?;:"
    lines: list[str] = []
    while len(remaining) > width:
        minimum = max(1, width // 2)
        cut = 0
        for position in range(width, minimum - 1, -1):
            if remaining[position - 1] in punctuation:
                cut = position
                break
        if cut == 0:
            cut = width
            while cut < len(remaining) and remaining[cut] in punctuation:
                cut += 1
        lines.append(remaining[:cut])
        remaining = remaining[cut:]
    if remaining:
        lines.append(remaining)
    return "\n".join(lines)


def _write_subtitles(path: Path, plans) -> None:
    cursor = 0.0
    blocks = []
    for index, plan in enumerate(plans, start=1):
        duration = float(plan.estimated_duration_s)
        text = str(
            plan.metadata.get("narration_text")
            or plan.metadata.get("dialogue")
            or ""
        ).strip()
        if not text:
            raise ValueError(f"Scene {plan.scene_id} has no subtitle text")
        blocks.append(
            f"{index}\n{_srt_time(cursor)} --> {_srt_time(cursor + duration)}\n"
            f"{_wrap_zh(text)}\n"
        )
        cursor += duration
    path.write_text("\n".join(blocks), encoding="utf-8-sig")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compose the audited Fanqie task-1 LTX shot set."
    )
    parser.add_argument("--flow", type=Path, default=DEFAULT_FLOW)
    parser.add_argument("--progress", type=Path, default=DEFAULT_PROGRESS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    flow = load_live_action_flow(args.flow.resolve())
    plans = flow.to_scene_plans()
    progress = json.loads(args.progress.read_text(encoding="utf-8"))
    if not progress.get("success") or len(progress.get("shots", [])) != len(plans):
        raise RuntimeError("Batch progress does not prove all flow shots succeeded")

    assets = []
    for shot in progress["shots"]:
        if shot.get("missing") or len(shot.get("assets", [])) != 1:
            raise RuntimeError(f"Shot {shot.get('scene_id')} is not complete")
        item = shot["assets"][0]
        assets.append(
            SceneAsset(
                scene_id=item["scene_id"],
                video_path=item["video_path"],
                duration_s=float(item["duration_s"]),
                provider_name=item["provider_name"],
                metadata=item.get("metadata", {}),
            )
        )

    story_manifest = _build_manifest(
        title=f"{flow.book_name}｜{flow.promotion_alias}",
        scene_plans=plans,
        assets=assets,
        script=SimpleNamespace(generation_params_json={}),
    )
    story_manifest["output_fps"] = 50
    story_manifest["responsibilities"] = {
        "visuals": "comfyui_ltx_i2v",
        "spoken_closeups": "musetalk_v15",
        "interpolation": "rife_v4.26",
        "audio": "audited_explicit_audio_paths",
        "subtitles": "ffmpeg_libass",
        "approval": "human_required",
    }

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = output.with_suffix(".story_manifest.json")
    manifest_path.write_text(
        json.dumps(story_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    raw_output = output.with_name(f"{output.stem}_raw.mp4")
    compose_story_video(manifest_path, raw_output)

    subtitle_path = output.with_suffix(".srt")
    _write_subtitles(subtitle_path, plans)
    subtitle_filter = (
        f"subtitles={subtitle_path.name}:"
        "force_style='FontName=Microsoft YaHei,FontSize=13,"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        "BorderStyle=1,Outline=1.5,Shadow=0,Alignment=2,"
        "MarginL=30,MarginR=30,MarginV=45'"
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(raw_output),
            "-vf", subtitle_filter,
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", "50",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart",
            str(output),
        ],
        cwd=str(output.parent),
        check=True,
        shell=False,
    )

    probe = json.loads(
        subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-show_entries",
                "stream=index,codec_type,codec_name,width,height,pix_fmt,"
                "r_frame_rate,avg_frame_rate,sample_rate,channels,duration,nb_frames",
                "-show_entries", "format=duration,size,bit_rate",
                "-of", "json", str(output),
            ],
            text=True,
            encoding="utf-8",
        )
    )
    audit = {
        "schema_version": "fanqie_story_review_audit/v1",
        "publish_allowed": False,
        "human_review_required": True,
        "flow_manifest": str(args.flow.resolve()),
        "flow_manifest_sha256": _sha256(args.flow.resolve()),
        "batch_progress": str(args.progress.resolve()),
        "batch_progress_sha256": _sha256(args.progress.resolve()),
        "story_manifest": str(manifest_path),
        "raw_output": str(raw_output),
        "subtitle_path": str(subtitle_path),
        "output": str(output),
        "output_sha256": _sha256(output),
        "probe": probe,
    }
    audit_path = output.with_suffix(".audit.json")
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
