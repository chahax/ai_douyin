"""Translate the detailed 404263 shot contracts into Flux-friendly English.

The source projects intentionally keep the audited Chinese wording.  This
utility asks the configured project LLM only for a literal visual translation,
then appends the translation to both style projects without changing timings,
characters, dialogue, release locks, or the original Chinese audit fields.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.shared.llm_client import LLMClient


def _extract_visual_contract(prompt: str) -> tuple[str, str]:
    composition_marker = "Composition contract: "
    action_marker = ". Visible story action at the first frame: "
    end_marker = ". No background establishing shot"
    if composition_marker not in prompt or action_marker not in prompt:
        raise ValueError("project prompt is missing visual-contract markers")
    tail = prompt.split(composition_marker, 1)[1]
    composition, tail = tail.split(action_marker, 1)
    action = tail.split(end_marker, 1)[0]
    return composition.strip(), action.strip()


def _request_batch(client: LLMClient, rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    payload = json.dumps(rows, ensure_ascii=False)
    response = client.chat_completion_tracked(
        [
            {
                "role": "system",
                "content": (
                    "You translate Chinese film shot instructions into precise English prompts for a still-image "
                    "generator. Return strict JSON only with top-level key 'shots'. For every input id return "
                    "composition_en, start_pose_en, visible_scene_en, and motion_en. composition_en must specify shot size, "
                    "camera angle, subject placement, and all visible people/props. start_pose_en must describe a "
                    "physically possible FIRST FRAME immediately before the action begins, never the whole motion. "
                    "visible_scene_en must clearly stage the story situation. Do not add text, logos, glamour poses, "
                    "new characters, new props, crouching, looking at a watch, or background exposition. Preserve "
                    "every concrete detail and adult age. For actions that cannot be visible in a still, stage the "
                    "recognizable anticipation pose. motion_en must be one physically coherent start-to-end micro-action "
                    "for video animation, preserving every stated hand, foot, gaze, prop and body-weight detail. English only."
                ),
            },
            {
                "role": "user",
                "content": "Translate these audited shot contracts:\n" + payload,
            },
        ],
        caller="scene_plan",
        temperature=0.1,
        json_mode=True,
        use_cache=False,
    )
    if not response:
        raise RuntimeError("configured LLM returned an empty translation")
    parsed = json.loads(response)
    output: dict[str, dict[str, str]] = {}
    for row in parsed.get("shots", []):
        shot_id = str(row["id"])
        output[shot_id] = {
            "composition_en": str(row["composition_en"]).strip(),
            "start_pose_en": str(row["start_pose_en"]).strip(),
            "visible_scene_en": str(row["visible_scene_en"]).strip(),
            "motion_en": str(row["motion_en"]).strip(),
        }
    missing = {row["id"] for row in rows} - set(output)
    if missing:
        raise ValueError(f"translation batch missed ids: {sorted(missing)}")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("semireal_project", type=Path)
    parser.add_argument("bighead_project", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=18)
    args = parser.parse_args()

    semireal_path = args.semireal_project.resolve()
    bighead_path = args.bighead_project.resolve()
    projects = {
        "semireal": json.loads(semireal_path.read_text(encoding="utf-8")),
        "bighead3d": json.loads(bighead_path.read_text(encoding="utf-8")),
    }
    source_rows: list[dict[str, str]] = []
    for shot in projects["semireal"]["shots"]:
        composition, action = _extract_visual_contract(str(shot.get("prompt_zh_audit") or shot["prompt"]))
        source_rows.append({"id": str(shot["id"]), "composition_zh": composition, "action_zh": action})

    client = LLMClient()
    translated: dict[str, dict[str, str]] = {}
    for start in range(0, len(source_rows), args.batch_size):
        batch = source_rows[start : start + args.batch_size]
        translated.update(_request_batch(client, batch))
        print(json.dumps({"event": "translated", "count": len(translated)}, ensure_ascii=False), flush=True)

    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps({"schema": "reference_404263_visual_translation/v1", "shots": translated}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    for style, project in projects.items():
        for shot in project["shots"]:
            shot_id = str(shot["id"])
            item = translated[shot_id]
            original = str(shot.get("prompt_zh_audit") or shot["prompt"])
            prefix = original.split("Composition contract:", 1)[0].rstrip()
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
                f"Perform exactly this single micro-action: {item['motion_en']} "
                "Use one clear start pose, one natural physically possible path and one settled end pose. "
                "Keep feet, hands, gaze, props and body weight coherent. Do not add gestures, crouching, "
                "watch-checking or new objects. Preserve identities, clothes, lighting and scene."
            )
            shot["ip_scale"] = 0.42 if len(shot.get("participants") or []) > 1 else 0.48
        target = semireal_path if style == "semireal" else bighead_path
        target.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"event": "updated_project", "style": style, "path": str(target)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
