"""Translate only the 69 audited micro-actions and merge with visual v1."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.shared.llm_client import LLMClient


def request(client: LLMClient, rows: list[dict[str, str]]) -> dict[str, str]:
    response = client.chat_completion_tracked(
        [
            {
                "role": "system",
                "content": (
                    "Translate Chinese film micro-actions into exact English image-to-video motion instructions. "
                    "Return strict JSON only: {'shots':[{'id':'...', 'motion_en':'...'}]}. Preserve the exact "
                    "start, natural physical path, end, hand, foot, gaze, prop and body-weight details. One action "
                    "only. Do not add gestures, people, props, crouching, watch-checking, camera movement, readable "
                    "text or scene changes. English only."
                ),
            },
            {"role": "user", "content": json.dumps(rows, ensure_ascii=False)},
        ],
        caller="scene_plan", temperature=0.1, json_mode=True, use_cache=False,
    )
    if not response:
        raise RuntimeError("configured LLM returned no motion translation")
    payload = json.loads(response)
    result_rows = payload if isinstance(payload, list) else payload.get("shots", [])
    output = {str(row["id"]): str(row["motion_en"]).strip() for row in result_rows}
    missing = {row["id"] for row in rows} - set(output)
    if missing:
        raise ValueError(f"motion translation missed ids: {sorted(missing)}")
    return output


def checkpoint(path: Path, visual: dict[str, dict[str, str]], motions: dict[str, str]) -> None:
    merged = {shot_id: {**item, **({"motion_en": motions[shot_id]} if shot_id in motions else {})} for shot_id, item in visual.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": "reference_404263_visual_translation/v2", "shots": merged}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("semireal_project", type=Path)
    parser.add_argument("bighead_project", type=Path)
    parser.add_argument("--visual-v1", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=12)
    args = parser.parse_args()

    semireal_path = args.semireal_project.resolve()
    bighead_path = args.bighead_project.resolve()
    projects = {
        "semireal": json.loads(semireal_path.read_text(encoding="utf-8")),
        "bighead3d": json.loads(bighead_path.read_text(encoding="utf-8")),
    }
    visual = json.loads(args.visual_v1.resolve().read_text(encoding="utf-8"))["shots"]
    output_path = args.output.resolve()
    motions: dict[str, str] = {}
    if output_path.is_file():
        saved = json.loads(output_path.read_text(encoding="utf-8"))["shots"]
        motions = {shot_id: item["motion_en"] for shot_id, item in saved.items() if item.get("motion_en")}

    source_rows = [
        {"id": str(shot["id"]), "action_zh": str(shot["source_action"])}
        for shot in projects["semireal"]["shots"] if str(shot["id"]) not in motions
    ]
    client = LLMClient()
    for start in range(0, len(source_rows), args.batch_size):
        batch = source_rows[start:start + args.batch_size]
        motions.update(request(client, batch))
        checkpoint(output_path, visual, motions)
        print(json.dumps({"event": "translated_motion", "count": len(motions)}, ensure_ascii=False), flush=True)

    if set(motions) != set(visual):
        raise ValueError("motion translation is incomplete")
    merged = json.loads(output_path.read_text(encoding="utf-8"))["shots"]
    for style, project in projects.items():
        for shot in project["shots"]:
            shot_id = str(shot["id"])
            item = merged[shot_id]
            original = str(shot.get("prompt_zh_audit") or shot["prompt"])
            prefix = str(shot["prompt"]).split("Composition contract:", 1)[0].rstrip()
            shot["prompt_zh_audit"] = original
            shot["motion_zh_audit"] = str(shot.get("motion_zh_audit") or shot["motion"])
            shot["visual_translation"] = item
            shot["prompt"] = (
                f"{prefix} Composition contract: {item['composition_en']} "
                f"Recognizable story situation: {item['visible_scene_en']} "
                f"FIRST FRAME pose immediately before the single action: {item['start_pose_en']} "
                "Show the complete physical setup needed for the next motion. This is a narrative film frame, "
                "not a portrait, fashion photo, character sheet or promotional poster. No background establishing "
                "shot, no readable text, no signboard, no logo and no watermark."
            )
            shot["motion"] = (
                f"Perform exactly this single micro-action: {item['motion_en']} Use one clear start pose, one natural "
                "physically possible path and one settled end pose. Keep feet, hands, gaze, props and body weight "
                "coherent. Do not add gestures, crouching, watch-checking or new objects. Preserve identities, clothes, lighting and scene."
            )
            shot["ip_scale"] = 0.42 if len(shot.get("participants") or []) > 1 else 0.48
        target = semireal_path if style == "semireal" else bighead_path
        target.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"event": "updated_project", "style": style, "path": str(target)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
