from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def build_clip(
    *,
    action: Path,
    lipsync: Path,
    output: Path,
    lead_seconds: float,
    crop_y: int,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if lead_seconds <= 0:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(lipsync),
                "-map",
                "0:v",
                "-map",
                "0:a?",
                "-c",
                "copy",
                str(output),
            ],
            check=True,
        )
        return

    filter_value = (
        f"[0:v]trim=duration={lead_seconds:.3f},setpts=PTS-STARTPTS,"
        "scale=704:1248:flags=lanczos,gblur=sigma=24,"
        "eq=brightness=-0.10:saturation=0.72[abg];"
        f"[0:v]trim=duration={lead_seconds:.3f},setpts=PTS-STARTPTS,"
        f"crop=704:600:0:{crop_y},scale=640:546:flags=lanczos,"
        "setsar=1[ahands];"
        "[abg][ahands]overlay=32:342:shortest=1,"
        "drawbox=x=24:y=334:w=656:h=562:color=black@0.38:t=8,"
        "fps=25,format=yuv420p[action];"
        f"[1:v]trim=start={lead_seconds:.3f},setpts=PTS-STARTPTS,"
        "fps=25,scale=704:1248:flags=lanczos,format=yuv420p[talk];"
        "[action][talk]concat=n=2:v=1:a=0[outv]"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(action),
            "-i",
            str(lipsync),
            "-filter_complex",
            filter_value,
            "-map",
            "[outv]",
            "-map",
            "1:a?",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(output),
        ],
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cut controlled hand/prop inserts into audio-driven talking scenes."
    )
    parser.add_argument("config")
    parser.add_argument("action_dir")
    parser.add_argument("lipsync_dir")
    parser.add_argument("output_dir")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    action_dir = Path(args.action_dir).resolve()
    lipsync_dir = Path(args.lipsync_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report: list[dict[str, object]] = []
    for scene_id, settings in config["scenes"].items():
        action = action_dir / f"{scene_id}.mp4"
        lipsync = lipsync_dir / f"{scene_id}.mp4"
        output = output_dir / f"{scene_id}.mp4"
        if not action.is_file():
            raise FileNotFoundError(f"action clip is missing: {action}")
        if not lipsync.is_file():
            raise FileNotFoundError(f"lip-sync clip is missing: {lipsync}")
        lead = float(settings.get("lead_seconds", 0.0))
        crop_y = int(settings.get("crop_y", 648))
        if not 0 <= crop_y <= 648:
            raise ValueError(f"{scene_id}.crop_y must be between 0 and 648")
        build_clip(
            action=action,
            lipsync=lipsync,
            output=output,
            lead_seconds=lead,
            crop_y=crop_y,
        )
        report.append(
            {
                "id": scene_id,
                "action": str(action),
                "lipsync": str(lipsync),
                "output": str(output),
                "lead_seconds": lead,
                "crop_y": crop_y,
                "phone_screen_policy": "back_or_side_only",
            }
        )
        print(f"built {scene_id}", flush=True)

    report_path = output_dir.parent / "hybrid_run_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(report_path)


if __name__ == "__main__":
    main()
