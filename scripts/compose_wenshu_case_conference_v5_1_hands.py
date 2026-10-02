from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = (
    ROOT
    / "data"
    / "qa"
    / "wenshu_lawyer_brand_v1"
    / "v2_debate"
    / "v4_case_conference"
)
SOURCE = PROJECT / "case_conference_v5_sadtalker_joined.mp4"
SUBTITLES = PROJECT / "subtitles_v5_sadtalker.ass"
HANDS = PROJECT / "hand_cutaways_ltx"


CUTAWAYS = [
    {
        "id": "xu_align_materials",
        "path": HANDS / "h_xu_align_cards.mp4",
        "source_start": 0.35,
        "source_end": 1.55,
        "timeline_start": 14.15,
        "speaker_audio": "顾承",
    },
    {
        "id": "gu_open_folder",
        "path": HANDS / "h_gu_open_folder.mp4",
        "source_start": 0.75,
        "source_end": 2.00,
        "timeline_start": 22.30,
        "speaker_audio": "许安",
    },
]


def run(args: list[str]) -> None:
    print(subprocess.list2cmdline(args), flush=True)
    subprocess.run(args, check=True)


def main() -> int:
    escaped = SUBTITLES.as_posix().replace(":", r"\:").replace("'", r"\'")
    inputs = ["-i", str(SOURCE)]
    for item in CUTAWAYS:
        inputs.extend(["-i", str(item["path"])])

    graph: list[str] = ["[0:v]setpts=PTS-STARTPTS[base]"]
    previous = "base"
    for index, item in enumerate(CUTAWAYS, start=1):
        duration = float(item["source_end"]) - float(item["source_start"])
        start = float(item["timeline_start"])
        end = start + duration
        cut = f"cut{index}"
        output = f"v{index}"
        graph.append(
            f"[{index}:v]trim=start={item['source_start']}:end={item['source_end']},"
            f"setpts=PTS-STARTPTS+{start}/TB,scale=704:1248:flags=lanczos,"
            f"fps=25,format=yuv420p[{cut}]"
        )
        graph.append(
            f"[{previous}][{cut}]overlay=x=0:y=0:eof_action=pass:repeatlast=0:"
            f"enable='between(t,{start},{end})'[{output}]"
        )
        previous = output
    graph.append(f"[{previous}]subtitles=filename='{escaped}',format=yuv420p[outv]")

    native = PROJECT / "wenshu_case_conference_v5_1_hands_native25.mp4"
    run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            *inputs,
            "-filter_complex",
            ";".join(graph),
            "-map",
            "[outv]",
            "-map",
            "0:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-r",
            "25",
            "-c:a",
            "copy",
            "-t",
            "120.820000",
            "-movflags",
            "+faststart",
            str(native),
        ]
    )

    safe50 = PROJECT / "wenshu_case_conference_v5_1_hands_safe50.mp4"
    run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(native),
            "-vf",
            "fps=50,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-r",
            "50",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(safe50),
        ]
    )

    manifest = {
        "source": str(SOURCE.resolve()),
        "native_25fps": str(native.resolve()),
        "safe_50fps": str(safe50.resolve()),
        "cutaways": [
            {
                **item,
                "path": str(Path(item["path"]).resolve()),
                "duration": round(float(item["source_end"]) - float(item["source_start"]), 3),
            }
            for item in CUTAWAYS
        ],
        "policy": (
            "Only listener cutaways are added. Dialogue audio remains untouched. "
            "The Zhou paper clip was rejected because its source contains an off-screen third hand "
            "and the nominally safe tail still has excessive hand motion blur."
        ),
    }
    (PROJECT / "timeline_v5_1_hands.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(native)
    print(safe50)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
