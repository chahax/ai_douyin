"""Repair three provider encoding artifacts in the generated English contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


FIXES = {
    "023": {
        "motion_en": "The locked high-angle night city frame remains still while many independent windows glow steadily; no people, camera movement or scene transition occurs."
    },
    "025": {
        "composition_en": "Extreme close-up of one phone screen and one rough calloused adult hand touching it."
    },
    "064e": {
        "motion_en": "Uncle Chen lifts the same phone from chest height to his right ear in one smooth arc, inclines his upper body slightly forward, then pauses with the phone sealed to his ear."
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("translation", type=Path)
    parser.add_argument("project", nargs="+", type=Path)
    args = parser.parse_args()
    translation_path = args.translation.resolve()
    payload = json.loads(translation_path.read_text(encoding="utf-8"))
    for shot_id, patch in FIXES.items():
        payload["shots"][shot_id].update(patch)
    translation_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for project_arg in args.project:
        path = project_arg.resolve()
        project = json.loads(path.read_text(encoding="utf-8"))
        for shot in project["shots"]:
            shot_id = str(shot["id"])
            if shot_id not in FIXES:
                continue
            shot["visual_translation"].update(FIXES[shot_id])
            item = shot["visual_translation"]
            prefix = str(shot["prompt"]).split("Composition contract:", 1)[0].rstrip()
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
        path.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"event": "repaired", "path": str(path), "ids": sorted(FIXES)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
