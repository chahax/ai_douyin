"""Apply human-audited hard-gate staging to the eight benchmark shots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


FIXES = {
    "001": {
        "composition_en": "Full-body tracking frame on a sign-free night street. Exactly three adult women walk abreast toward camera; the lead is centered and both friends remain fully visible on opposite sides. Show hips, knees and both feet.",
        "start_pose_en": "All three women are in different natural phases of a walking stride. The lead still looks forward. The blonde friend looks toward the lead. The black-haired friend holds her own single lit phone low at waist height and looks down at it.",
        "visible_scene_en": "Three visibly different adult friends are walking together on wet pavement under pink-purple practical light; there are no readable storefronts or signs.",
        "motion_en": "The three women continue forward for two natural alternating steps. During the second step the lead turns her eyes and head toward the blonde friend while the black-haired friend keeps walking and briefly glances down at her own phone. Legs never freeze and nobody changes lane.",
    },
    "015": {
        "composition_en": "Tight facial close-up of the adult male operator in the cold-lit workroom, eyes, mouth and jaw fully visible; no phone blocks his face.",
        "start_pose_en": "He looks downward with a small self-satisfied smile and a relaxed jaw.",
        "visible_scene_en": "The adult male operator is reacting to the lead woman across the workroom; shelves and phones remain soft, dark background detail.",
        "motion_en": "His small smile gradually disappears, his jaw tightens once, then his eyes lift to meet the woman. His head and shoulders remain still and no new gesture occurs.",
    },
    "017": {
        "composition_en": "Stable medium two-shot in the cramped workroom. The adult man stands behind an empty office chair with both hands on the chair back; the adult woman stands half a step in front of the seat. Both bodies, the full chair and the floor contact points are visible.",
        "start_pose_en": "The chair is stationary. The woman is upright with straight knees and both feet planted. The man is upright behind the chair, hands gripping only the chair back.",
        "visible_scene_en": "The man is ordering the woman to work and has positioned an empty chair directly behind her; the phone-covered desk remains beside them, not between their bodies.",
        "motion_en": "The man pushes the empty chair forward a short distance and stops it behind the woman. Only after the chair stops, the woman bends naturally at hips and knees and lowers onto the seat. She never crouches before contact and the chair never intersects either body.",
    },
    "032": {
        "composition_en": "Bedroom bedside medium shot. The adult woman lies fully on her side on the bed under one stable blanket; her head, torso, supporting elbow and both hands are visible.",
        "start_pose_en": "Her eyes are open and her upper palm already rests naturally across her forehead while the other arm supports her side-lying pose. The blanket is already fixed and does not move.",
        "visible_scene_en": "A staged fake-illness photo is being prepared in a modest messy bedroom; only the woman is visible and the unseen male gives directions from off camera.",
        "motion_en": "Keeping the same palm gently on her forehead, she removes the hint of a smile, tightens her brow slightly, then closes both eyes once. Her body stays side-lying, the blanket remains fixed and she does not sit or stand.",
    },
    "039": {
        "composition_en": "Medium-wide workroom frame with the adult man and adult woman behind a desk. At least six separate blank blue-white phone screens form a stable array in the foreground; both faces, hands and upper bodies remain visible.",
        "start_pose_en": "The man is seated with one hand open near his thigh. The woman is seated separately and looking at the glowing phone array with a neutral face.",
        "visible_scene_en": "Multiple payment alerts have just arrived across the phone array and both scammers are about to react; phones remain separate and contain no readable text.",
        "motion_en": "The man rises halfway from his chair and makes one short clenched-fist celebration at chest height. The woman turns her head toward him and forms one restrained smile. His fist then begins to lower; phones remain stationary and lit.",
    },
    "049": {
        "composition_en": "Wide full-body rooftop-pool shot. The adult male operator is at the near pool edge with both legs visible. At least four background adult guests have different faces, outfits and independent poses: two converse, one drinks water, and one swims.",
        "start_pose_en": "The man is beginning a forward walking stride with one heel raised and arms relaxed. Each guest is already engaged in a different activity and nobody looks toward camera.",
        "visible_scene_en": "A sunny luxury pool gathering with cyan water; the operator approaches along the deck while independent adult guests socialize and swim.",
        "motion_en": "The man takes exactly two natural forward steps along the pool edge and settles with both feet planted. Background guests continue small independent actions at different rhythms; they never synchronize, duplicate or change identity.",
    },
    "058": {
        "composition_en": "Low-angle medium-wide frame from inside the workroom facing a closed plain door. Exactly two visibly different adult male officers are outside: the broad square-faced front officer at the handle and the lean narrow-faced rear officer one step behind. Show both sets of feet and the doorway.",
        "start_pose_en": "The front officer has one hand on the closed door handle and his leading foot just behind the threshold. The rear officer waits one full step behind with both feet planted; neither officer is yet inside.",
        "visible_scene_en": "Exactly two plain-uniformed officers are starting a controlled police entry into the phone workroom; uniforms contain no badges, letters or readable patches.",
        "motion_en": "The front officer opens the door and takes one complete step across the threshold, transferring weight onto the leading foot. The rear officer follows only to the doorway and stops there. They remain two distinct people and never overlap or duplicate.",
    },
    "064f": {
        "composition_en": "Intimate tight close-up of elderly Uncle Chen in his dim apartment. One modern black cordless smartphone is already pressed flat to his right ear with its black back casing facing camera; face and both shoulders are visible. No cable and no visible screen.",
        "start_pose_en": "The elderly man leans slightly forward with the same modern smartphone firmly against his ear, lips just beginning to part, eyes focused into the distance and shoulders tense. The phone has no cord and its screen faces inward against his ear.",
        "visible_scene_en": "Uncle Chen is waiting for an absent friend to answer a call after hearing the fraud news; cool television light touches his worried face and there is no readable screen or background text.",
        "motion_en": "Keeping the same phone sealed to his ear, he quietly asks his question, stops moving to listen, then exhales slowly. His shoulders gradually collapse and his gaze lowers slightly; he never presents the phone to camera.",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="+", type=Path)
    args = parser.parse_args()
    for project_path in args.project:
        path = project_path.resolve()
        project = json.loads(path.read_text(encoding="utf-8"))
        shots = {str(shot["id"]): shot for shot in project["shots"]}
        for shot_id, item in FIXES.items():
            shot = shots[shot_id]
            prefix = str(shot["prompt"]).split("Composition contract:", 1)[0].rstrip()
            shot["visual_translation"] = dict(item)
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
                "Do not add gestures, crouching, watch-checking or new objects. Preserve identities, clothes, lighting and scene."
            )
            shot["ip_scale"] = 0.40 if len(shot.get("participants") or []) > 1 else 0.46
            shot["benchmark_human_gate_fix"] = True
        path.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"event": "updated", "path": str(path), "shots": sorted(FIXES)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
