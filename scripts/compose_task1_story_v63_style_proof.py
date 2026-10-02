from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = ROOT / r"data\qa\task1_story_v63_reference_style_rebuild_20260822"
MALE = WORK_ROOT / r"framepack_style_proof_v1\male_walk_framepack.mp4"
FEMALE = WORK_ROOT / r"framepack_style_proof_v1\female_block_framepack.mp4"
AUDIO_SOURCE = ROOT / r"data\qa\task1_story_v62_full_candidate_20260822_framepack_wrist_bridge_v3\candidate.mp4"
OUTPUT_DIR = WORK_ROOT / "opening_style_proof_v1"
OUTPUT = OUTPUT_DIR / "task1_story_v63_opening_style_proof_v1.mp4"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def probe(path: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "stream=codec_type,codec_name,width,height,r_frame_rate:format=duration,size,bit_rate",
            "-of", "json", str(path),
        ], capture_output=True, text=True, timeout=30,
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:])
    payload = json.loads(result.stdout)
    video = next(row for row in payload["streams"] if row["codec_type"] == "video")
    return {
        "width": int(video["width"]), "height": int(video["height"]),
        "fps": str(video["r_frame_rate"]), "video_codec": str(video["codec_name"]),
        "duration_seconds": round(float(payload["format"]["duration"]), 3),
        "size_bytes": int(payload["format"]["size"]),
    }


def main() -> int:
    for required in (MALE, FEMALE, AUDIO_SOURCE):
        if not required.is_file():
            raise FileNotFoundError(required)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pending = OUTPUT.with_suffix(".pending.mp4")
    filter_complex = (
        "[0:v]split=3[m_phone][m_full][m_face];"
        "[m_phone]trim=start=0:end=0.55,setpts=PTS-STARTPTS,"
        "crop=180:320:270:95,scale=1080:1920:flags=lanczos,fps=30,format=yuv420p[s01];"
        "[m_full]trim=start=0.20:end=1.65,setpts=PTS-STARTPTS,"
        "scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,"
        "crop=1080:1920,fps=30,format=yuv420p[s02];"
        "[m_face]trim=start=1.65:end=2.15,setpts=PTS-STARTPTS,"
        "crop=270:480:100:0,scale=1080:1920:flags=lanczos,fps=30,format=yuv420p[s03];"
        "[1:v]reverse,setpts=PTS-STARTPTS,split=3[f_heel][f_full][f_face];"
        "[f_heel]trim=start=0:end=0.45,setpts=PTS-STARTPTS,"
        "crop=240:426:145:400,scale=1080:1920:flags=lanczos,fps=30,format=yuv420p[s04];"
        "[f_full]trim=start=0.45:end=2.15,setpts=PTS-STARTPTS,"
        "scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,"
        "crop=1080:1920,fps=30,format=yuv420p[s05];"
        "[f_face]trim=start=1.60:end=2.25,setpts=PTS-STARTPTS,"
        "crop=270:480:70:0,scale=1080:1920:flags=lanczos,fps=30,format=yuv420p[s06];"
        "[s01][s02][s03][s04][s05][s06]concat=n=6:v=1:a=0[v];"
        "[2:a]atrim=start=0:end=5.30,asetpts=PTS-STARTPTS,"
        "aresample=48000,volume=1.0[a]"
    )
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(MALE), "-i", str(FEMALE), "-i", str(AUDIO_SOURCE),
            "-filter_complex", filter_complex, "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(pending),
        ], capture_output=True, text=True, timeout=600,
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-6000:])
    pending.replace(OUTPUT)
    output_probe = probe(OUTPUT)
    if (output_probe["width"], output_probe["height"], output_probe["fps"]) != (1080, 1920, "30/1"):
        raise ValueError(f"unexpected proof delivery: {output_probe}")

    audit = {
        "schema_version": "task1_story_v63_opening_style_proof/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "visual-retention proof before rebuilding the complete V6.3 candidate",
        "reference_video_pixels_used": False,
        "publish_allowed": False,
        "fanqie_backfill_allowed": False,
        "sources": {
            "male_framepack": {"path": str(MALE), "sha256": sha256(MALE)},
            "female_framepack": {"path": str(FEMALE), "sha256": sha256(FEMALE), "playback_reversed": True},
            "audio_only_from_previous_internal_candidate": {"path": str(AUDIO_SOURCE), "sha256": sha256(AUDIO_SOURCE)},
        },
        "microshots": [
            {"id": "s01_phone_macro", "duration": 0.55, "source": "male_framepack", "crop": "phone_macro"},
            {"id": "s02_male_stride", "duration": 1.45, "source": "male_framepack", "crop": "full"},
            {"id": "s03_male_reaction", "duration": 0.50, "source": "male_framepack", "crop": "face_close"},
            {"id": "s04_heel_plant", "duration": 0.45, "source": "female_framepack_reversed", "crop": "heel_macro"},
            {"id": "s05_female_block", "duration": 1.70, "source": "female_framepack_reversed", "crop": "full"},
            {"id": "s06_female_reaction", "duration": 0.65, "source": "female_framepack_reversed", "crop": "face_hand_close"},
        ],
        "output": {"path": str(OUTPUT), "sha256": sha256(OUTPUT), "probe": output_probe},
        "human_visual_review_required": True,
    }
    audit_path = OUTPUT_DIR / "compose_audit.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
