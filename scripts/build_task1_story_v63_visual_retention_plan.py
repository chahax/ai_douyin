from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_PLAN = ROOT / r"data\fanqie_promotion\scene_plans\task1_story_v62_microshot_workflow.json"
ANCHOR_ROOT = ROOT / r"data\qa\task1_story_v63_reference_style_rebuild_20260822\original_style_keyframes"
OUTPUT = ROOT / r"data\fanqie_promotion\scene_plans\task1_story_v63_visual_retention_workflow_v1.json"

ACTION_SCENES = {
    "b01_boast",
    "b02_grab_reaction",
    "b03_object_question",
    "b04_confused_answer",
    "b05_age_burst",
    "b06_pull_away",
    "b07_protest",
    "b11_flip",
    "b12_car_reveal",
    "b16_escape",
    "b18_cta",
}
STABLE_SCENES = {
    "b08_offer_one",
    "b09_offer_two",
    "b10_offer_three",
    "b13_registry_reveal",
    "b14_certificate",
    "b15_terms",
    "b17a_kiss_reaction",
    "b17b_hunt_order",
}

ANCHORS = {
    "b01_boast": "b01_boast_black_original.png",
    "b02_grab_reaction": "b02_natural_wrist_contact_v2.png",
    "b03_object_question": "b03_object_question_original.png",
    "b04_confused_answer": "b04_confused_answer_original.png",
    "b05_age_burst": "b05_direct_age_question_v2.png",
    "b06_pull_away": "b06_natural_wrist_lead_v2.png",
    "b07_protest": "b07_upright_protest_v2.png",
    "b08_offer_one": "b08_offer_one_original.png",
    "b09_offer_two": "b09_offer_two_original.png",
    "b10_offer_three": "b10_offer_three_original.png",
    "b11_flip": "b11_flip_original.png",
    "b12_car_reveal": "b12_car_reveal_original.png",
    "b13_registry_reveal": "b13_registry_reveal_original.png",
    "b14_certificate": "b14_certificate_original.png",
    "b15_terms": "b15_terms_original.png",
    "b16_escape": "b16_escape_original.png",
    "b17a_kiss_reaction": "b17a_kiss_reaction_original.png",
    "b17b_hunt_order": "b17b_hunt_order_original.png",
    "b18_cta": "b18_cta_original.png",
}

PROMPTS = {
    "b01_boast": "The man completes one large confident walking stride toward camera. The lifted shoe plants, rear leg pushes, hips and shoulders transfer weight, free arm counter-swings, jacket reacts and his face turns into a smug micro-smile. Keep identity, wet neon street and low wide camera stable.",
    "b02_grab_reaction": "Both keep a natural upright walking posture. The woman gently touches the outside of the man's wrist to get his attention; he turns his eyes toward her and they settle into one ordinary half-step. Keep their hand contact, identities, eyelines and wet neon street stable.",
    "b03_object_question": "The woman holds direct eye contact, leans a few centimeters closer, lifts her chin and articulates one short pointed question. Add a subtle shoulder turn and living breath while preserving her face, ponytail, neon street and over-shoulder framing.",
    "b04_confused_answer": "The man snaps his gaze toward the off-screen woman, blinks once, turns his head and shoulders farther, then shifts from surprise to wary confusion. Preserve his face, black jacket and vivid wet neon background.",
    "b05_age_burst": "The woman keeps steady eye contact with the man and asks one direct question. Her open hand makes a small questioning gesture near waist height while her head and torso remain upright. Preserve her natural stance, face, cream blazer and wet neon street; no counting and no watch interaction.",
    "b06_pull_away": "The upright woman keeps a light hold on the man's wrist, turns her shoulders toward the direction of travel and begins one ordinary short step. The man follows with a natural half-step while looking at her. Preserve their exact contact, standing height, identities and wet neon street.",
    "b07_protest": "The man slows his step, looks directly at the woman and raises only his free hand to chest height in a small relaxed wait gesture. Both remain upright and keep the same wrist contact. Preserve identities, eyelines, normal walking balance and the wet neon street.",
    "b11_flip": "The man quickly raises the plain unbranded phone, leans toward it, taps once and changes from confusion into a crooked eager grin. One readable phone-hand action, active shoulders, stable face, jacket and neon street; no readable screen.",
    "b12_car_reveal": "The woman takes one elegant full stride beside the already-opening unbranded sedan door, sweeps one hand toward the interior and turns a confident glance toward the off-screen man. Hair, blazer, heels and door move naturally; warm hotel entrance stays stable.",
    "b16_escape": "The man completes one explosive running stride down the wet steps, arms pump, jacket flies open and he looks back once in alarm. Both feet and weight transfer remain readable while the red-blue background streaks slightly.",
    "b18_cta": "The man continues one powerful sprint toward and past camera, reaches one hand toward lens, drives the opposite arm back and completes a large airborne stride while delivering the final hook. Keep his face, limbs, wet road and distant unbranded sedan stable.",
}

NEGATIVE_PROMPT = (
    "identity change, face morphing, hairstyle change, clothing change, scene replacement, muted grade, frozen pose, "
    "frozen legs, foot sliding, moonwalk, tiny idle motion, duplicated person, extra limbs, missing limbs, extra fingers, "
    "fused fingers, malformed hands, disappearing prop, readable screen, text, subtitle, watermark, logo, anime, cartoon, "
    "camera shake, scene cut, flicker, exposure pumping"
)

NATURAL_ACTION_NEGATIVE = (
    "crouch, half squat, deep bent knees, lunge, wide stance, backward arch, torso pitching, "
    "martial arts pose, theatrical overacting, hard pulling, palm toward lens, looking at watch, wristwatch gesture"
)

NATURAL_ACTION_SCENES = {
    "b02_grab_reaction",
    "b05_age_burst",
    "b06_pull_away",
    "b07_protest",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def build() -> dict[str, object]:
    base = json.loads(BASE_PLAN.read_text(encoding="utf-8"))
    base_branch = base["variants"]["original_recomposed"]
    if set(ANCHORS) != ACTION_SCENES | STABLE_SCENES:
        raise ValueError("V6.3 scene partition is incomplete")

    units: list[dict[str, object]] = []
    for source in base_branch["new_framepack_units"]:
        scene_id = str(source["scene_id"])
        anchor = (ANCHOR_ROOT / ANCHORS[scene_id]).resolve()
        if not anchor.is_file():
            raise FileNotFoundError(anchor)
        unit = copy.deepcopy(source)
        unit.update(
            {
                "anchor_path": str(anchor),
                "anchor_sha256": _sha256(anchor),
                "seed": 86330000 + len(units) + 1,
                "prompt": PROMPTS.get(
                    scene_id,
                    "Preserve the exact original character, prop, composition and color design. Add only a subtle premium camera push, natural breathing, blinking, hair and fabric response without changing finger counts or object geometry.",
                ),
                "negative_prompt": (
                    f"{NEGATIVE_PROMPT}, {NATURAL_ACTION_NEGATIVE}"
                    if scene_id in NATURAL_ACTION_SCENES
                    else NEGATIVE_PROMPT
                ),
                "renderer": (
                    "local_framepack_i2v"
                    if scene_id in ACTION_SCENES
                    else "deterministic_camera_motion_candidate_only"
                ),
                "publish_allowed": False,
            }
        )
        units.append(unit)

    branch = {
        "role": "complete_visual_retention_candidate_after_human_and_platform_gates",
        "style_variant": "original_high_saturation_live_action_microdrama",
        "reference_video_is_internal_analysis_only": True,
        "reference_video_pixels_allowed": False,
        "reference_people_allowed": False,
        "reference_watermark_allowed": False,
        "all_story_beats_use_unique_original_anchors": True,
        "action_direction_contract": {
            "one_primary_action_per_scene": True,
            "start_force_chain_end_pose_required": True,
            "natural_standing_height_unless_story_requires_otherwise": True,
            "eye_target_must_match_scene_partner": True,
            "props_forbidden_unless_required_by_story": True,
            "wrist_lead_requires_upright_posture_and_normal_half_step": True,
            "questioning_or_counting_must_not_invent_watch_check": True,
            "theatrical_crouch_lunge_or_recoil_forbidden": True,
            "local_prompt_review_model": "ollama/qwen2.5:7b",
            "external_minimax_used": False,
        },
        "visual_phases": [
            {"range": "0.0-18.0", "look": "cyan_magenta_red_wet_neon_confrontation"},
            {"range": "18.0-30.0", "look": "warm_gold_luxury_car_and_registry_reversal"},
            {"range": "30.0-40.8", "look": "red_blue_escape_and_chase_climax"},
        ],
        "action_scene_ids": sorted(ACTION_SCENES),
        "stable_insert_scene_ids": sorted(STABLE_SCENES),
        "new_framepack_units": units,
        "reuse_sources": {},
        "microshots": copy.deepcopy(base_branch["microshots"]),
        "publish_allowed": False,
        "fanqie_backfill_allowed": False,
        "human_full_video_review_required": True,
    }
    payload = {
        "schema_version": "fanqie_v63_visual_retention_workflow/v1",
        "task_id": 1,
        "source_story_plan": base["source_story_plan"],
        "source_story_plan_sha256": base["source_story_plan_sha256"],
        "story_contract_unchanged": True,
        "audio_source": base["audio_source"],
        "subtitle_source": base["subtitle_source"],
        "delivery": copy.deepcopy(base["delivery"]),
        "motion_gate": {
            "action_maximum_duplicate_ratio": 0.12,
            "action_minimum_mean_frame_distance": 0.5,
            "stable_insert_maximum_duplicate_ratio": 0.28,
            "whole_video_minimum_mean_frame_distance": 4.5,
            "minimum_smoothness_score": 65.0,
            "maximum_failed_scenes": 0,
            "interpolation_cannot_replace_missing_motion": True,
        },
        "variants": {"visual_retention_v1": branch},
    }
    return payload


def main() -> int:
    payload = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pending = OUTPUT.with_suffix(".pending.json")
    pending.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(OUTPUT)
    print(OUTPUT)
    print(_sha256(OUTPUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
