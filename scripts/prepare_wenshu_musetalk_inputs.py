from __future__ import annotations

import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = PROJECT_ROOT / "data" / "qa" / "wenshu_lawyer_brand_v1"


def duration(path: Path) -> float:
    result = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        text=True,
    )
    return float(result.strip())


def try_duration(path: Path) -> float | None:
    try:
        return duration(path)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None


def main() -> int:
    timeline = json.loads((PROJECT_DIR / "audio" / "timeline.json").read_text(encoding="utf-8"))
    stretched_dir = PROJECT_DIR / "clips_stretched"
    stretched_dir.mkdir(parents=True, exist_ok=True)
    config_lines: list[str] = []
    report: list[dict] = []

    for item in timeline["timeline"]:
        shot_id = item["id"]
        source = PROJECT_DIR / "clips_ltx" / f"{shot_id}.mp4"
        audio = Path(item["file"])
        target_duration = float(item["duration"])
        source_duration = duration(source)
        ratio = target_duration / source_duration
        output = stretched_dir / f"{shot_id}.mp4"
        existing_duration = try_duration(output) if output.is_file() else None
        if existing_duration is not None and abs(existing_duration - target_duration) < 0.12:
            print(f"reused {shot_id}: {existing_duration:.3f}s", flush=True)
        else:
            video_filter = (
                f"setpts={ratio:.10f}*PTS,"
                "minterpolate=fps=25:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,"
                "scale=704:1248:flags=lanczos,format=yuv420p"
            )
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-t", f"{target_duration:.3f}",
                    "-vf", video_filter, "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17",
                    "-movflags", "+faststart", str(output),
                ],
                check=True,
            )
        config_lines.extend(
            [
                f"task_{shot_id}:",
                f'  video_path: "{output.as_posix()}"',
                f'  audio_path: "{audio.as_posix()}"',
                f'  result_name: "{shot_id}_lipsync.mp4"',
            ]
        )
        report.append(
            {
                "id": shot_id,
                "source": str(source),
                "source_duration": round(source_duration, 3),
                "target_duration": round(target_duration, 3),
                "stretch_ratio": round(ratio, 5),
                "output": str(output),
            }
        )
        print(f"prepared {shot_id}: {source_duration:.3f}s -> {target_duration:.3f}s", flush=True)

    (PROJECT_DIR / "musetalk_full.yaml").write_text("\n".join(config_lines) + "\n", encoding="utf-8")
    (stretched_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
