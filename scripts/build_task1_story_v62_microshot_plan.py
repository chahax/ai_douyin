"""Build the task-1 V6.2 micro-shot workflow manifest.

V6.2 does not change the approved story, dialogue, cast, or publication
boundary.  It changes only the visual execution: long beats are cut into short
action/reaction inserts and two explicitly different reference branches are
kept separate.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PLAN = ROOT / (
    r"data\fanqie_promotion\scene_plans\task1_story_v61_reviewed_anchors.json"
)
OUTPUT = ROOT / (
    r"data\fanqie_promotion\scene_plans\task1_story_v62_microshot_workflow.json"
)
QA = ROOT / r"data\qa\task1_story_v62_microshot_20260821"
ORIGINAL = QA / "original_anchors"
REFERENCE = QA / "reference_frames"
EXPECTED_SOURCE_SHA256 = (
    "D2C15C86B0AC57BE8CD26EF687C65C049D64B2069568707C8B699AE6D5828CB4"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _unit(
    scene_id: str,
    anchor: Path,
    duration: float,
    seed: int,
    prompt: str,
) -> dict[str, object]:
    return {
        "scene_id": scene_id,
        "anchor_path": str(anchor.resolve()),
        "anchor_sha256": _sha256(anchor),
        "target_duration_seconds": duration,
        "seed": seed,
        "prompt": prompt,
        "negative_prompt": (
            "identity change, face morph, extra person, extra limb, malformed "
            "hands, extra fingers, fused fingers, background replacement, scene "
            "cut, readable text, logo, subtitle, watermark, anime, cartoon, chibi"
        ),
        "renderer": "local_framepack_i2v",
        "delivery_fps": 30,
        "publish_allowed": False,
    }


def _a_units() -> list[dict[str, object]]:
    rows = [
        (
            "b01_boast",
            "a01_b01_walk_original.png",
            2.8,
            86220101,
            "The adult male continues one brisk natural walking step, finishes "
            "pocketing the phone, opens his free hand once, then raises one "
            "eyebrow into a smug grin. Handheld tracking follows beside him; "
            "identity, blue overshirt and blue-hour campus remain stable.",
        ),
        (
            "b02_grab_reaction",
            "a02_b02_wrist_pull_original.png",
            1.4,
            86220201,
            "The adult woman keeps the visible wrist grip anatomically correct "
            "and pulls once to camera-right. The adult man lurches one step and "
            "turns a startled face toward her. Short lateral camera track; no "
            "new person, no hand fusion, stable campus background.",
        ),
        (
            "b03_object_question",
            "a03_b03_object_question_original.png",
            1.8,
            86220301,
            "The adult woman maintains the locked eye-line, lifts her chin only "
            "a few centimeters and articulates one short direct question with "
            "minimal head motion. Preserve her face, ponytail, night bokeh and "
            "the blurred off-screen-man shoulder framing.",
        ),
        (
            "b04_confused_answer",
            "a04_b04_confused_original.png",
            1.5,
            86220401,
            "The adult man blinks once, turns his head a few centimeters farther "
            "over his shoulder and shifts from shock to wary confusion. Subtle "
            "backward camera drift; keep face, clothing and night campus stable.",
        ),
        (
            "b05_age_burst",
            "a05_b05_watch_original.png",
            2.4,
            86220501,
            "The adult woman snaps her eyes from the plain wristwatch to an "
            "off-screen man, raises exactly one impatient index finger once and "
            "leans forward a few centimeters. Watch, hands, face, clothes and "
            "campus stay stable; controlled close camera.",
        ),
        (
            "b06_pull_away",
            "a06_b06_reach_stride_original.png",
            2.0,
            86220601,
            "The adult woman completes one decisive stride toward camera-left "
            "and extends the visible hand a few centimeters farther without "
            "grabbing an invented limb. Lateral follow camera; natural arm swing "
            "and stable face, heels, clothing and campus architecture.",
        ),
        (
            "b07_protest",
            "a07_b07_retreat_original.png",
            2.3,
            86220701,
            "The adult man retreats one short step, brings both open hands toward "
            "the sides of his waist without touching or fusing, scans the off-screen "
            "woman with alarm, then settles into a guarded stance. Stable identity "
            "and campus; short retreating camera move.",
        ),
        (
            "b08_offer_one",
            "a08_b08_offer_one_original.png",
            1.3,
            86220801,
            "The adult woman keeps exactly one index finger raised beside her "
            "face, holds her body steady and delivers one terse word without "
            "blinking. Preserve correct folded fingers, face, clothing and bokeh.",
        ),
        (
            "b09_offer_two",
            "a09_b09_offer_two_original.png",
            1.5,
            86220901,
            "The adult woman keeps exactly two fingers raised, completes one "
            "short forward step and sharpens her impatient eye-line toward the "
            "off-screen man. Preserve hand count, face, clothing and night campus.",
        ),
        (
            "b10_offer_three",
            "a10_b10_offer_three_original.png",
            1.2,
            86221001,
            "The adult woman keeps exactly three fingers raised and performs one "
            "precise eyebrow lift. Keep hand anatomy, face and jewel-toned night "
            "bokeh stable; controlled dramatic punch-in only.",
        ),
        (
            "b11_flip",
            "a09_b11_phone_eager_original.png",
            3.3,
            86221101,
            "The adult man finishes pulling out the plain black phone, glances at "
            "it, leans closer once and brightens into an eager flattering smile. "
            "One readable phone-hand action and one expression change; stable face, "
            "blue overshirt and campus, no readable screen.",
        ),
        (
            "b12_car_reveal",
            "a10_b12_car_original.png",
            2.2,
            86221201,
            "The adult woman keeps one hand on the already-open sedan door, turns "
            "a faint confident smile toward the off-screen man and gestures inward "
            "once with the other hand. The car remains stationary and unbranded; "
            "camera widens gently without inventing passengers.",
        ),
        (
            "b13_registry_reveal",
            "a11_b13_civic_original.png",
            1.6,
            86221301,
            "The adult man cranes his neck upward a little more, freezes for one "
            "beat, widens his eyes and gives a short shocked reaction. Low-angle "
            "camera settles; generic civic facade and identity stay stable.",
        ),
        (
            "b14_certificate",
            "a12_b14_booklet_original.png",
            2.5,
            86221401,
            "The adult man closes the completely blank red booklet once, lowers it "
            "slightly, then looks up into a disbelieving half-smile. Both hands, "
            "booklet geometry, face and civic background remain stable; no text.",
        ),
        (
            "b15_terms",
            "a13_b15_terms_original.png",
            3.2,
            86221501,
            "The adult woman moves the completely blank red booklet toward the "
            "open cream handbag once, tilts her head slightly and holds a cool "
            "challenging look. Hands, handbag opening, booklet, face and building "
            "remain stable; slow controlled camera push.",
        ),
        (
            "b16_escape",
            "a16_b16_escape_original.png",
            1.8,
            86221601,
            "The adult man completes the airborne push-off into one running stride "
            "down the wet steps while keeping the quick open-palm goodbye wave "
            "readable. Lateral tracking; preserve face, limbs, clothes and building.",
        ),
        (
            "b17a_kiss_reaction",
            "a17a_b17a_kiss_reaction_original.png",
            1.4,
            86221701,
            "The adult woman keeps her eyes open and fingertips gently touching "
            "the lower lip while one mouth corner tightens into a subtle dangerous "
            "smile. No hand withdrawal; stable close-up and controlled push-in.",
        ),
        (
            "b17b_hunt_order",
            "a17b_b17b_hunt_order_original.png",
            2.7,
            86221801,
            "The adult woman keeps the plain black phone at her ear, speaks with "
            "controlled authority, then turns her eyes sharply toward the escape "
            "direction. Preserve phone grip, face, clothing and night bokeh.",
        ),
        (
            "b18_cta",
            "a18_b18_cta_original.png",
            3.9,
            86221901,
            "The adult man continues one running stride, looks back over his "
            "shoulder once and articulates the final spoken hook while the distant "
            "dark sedan remains safely behind. Low trailing camera; preserve face, "
            "limbs, wet road, building and vehicle scale.",
        ),
    ]
    return [
        _unit(scene, ORIGINAL / name, duration, seed, prompt)
        for scene, name, duration, seed, prompt in rows
    ]


def _b_units() -> list[dict[str, object]]:
    rows = [
        ("ref01_street_hook", "r01_street_hook.png", "The adult group walks forward naturally while comparing phones; small hand gestures and one laugh, stable faces, street and camera."),
        ("ref02_phone_close", "r02_phone_close.png", "The visible adult hand lifts and tilts the phone once while the background subject shifts weight naturally; keep screen geometry and scene stable."),
        ("ref03_phone_array", "r03_phone_array.png", "One adult hand reaches across the organized phone array and taps one screen once; cables, phones and tabletop remain stable."),
        ("ref04_room_entry", "r04_room_entry.png", "The adult woman takes two natural steps into the corridor and reaches toward the door; forward tracking camera, stable identity and architecture."),
        ("ref05_operator_close", "r05_operator_close.png", "The adult operator glances from one phone to another, lifts one phone and reacts with a quick expression change; stable room and devices."),
        ("ref06_chat_close", "r06_chat_close.png", "The adult woman types one short message, glances up and changes from concern to a small controlled smile; subtle camera move, stable phones and face."),
        ("ref07_elder_transfer", "r07_elder_transfer.png", "The elderly adult raises the phone closer, taps once and exhales; stable hands, face, room and readable device shape, no new text."),
        ("ref08_multi_payment", "r08_multi_payment.png", "An adult hand moves across the phone array and selects one device while the seated adult reacts; stable table, devices and background."),
        ("ref09_staged_poverty", "r09_staged_poverty.png", "The adult woman sits up from the bed, lifts the food cup and turns toward the phone camera; stable bedding, face, hands and room."),
        ("ref10_jewelry", "r10_jewelry.png", "The adult reaches toward one jewelry tray and points once while turning with excitement; stable hands, glass counter and store lighting."),
        ("ref11_spa_shopping", "r11_spa_shopping.png", "The adult woman walks one step through the bright shop, reaches toward one item and smiles; stable identity, arms and shelves."),
        ("ref12_luxury_dinner", "r12_luxury_dinner.png", "The two adults lift utensils and share one quick celebratory reaction; stable tableware, faces, hands and dining room."),
        ("ref13_pool_party", "r13_pool_party.png", "The adults take one lively poolside step and raise one arm in celebration; stable faces, limbs, water and architecture."),
        ("ref14_night_crisis", "r14_night_crisis.png", "The night subject turns sharply toward the phone alert as the camera moves forward slightly; stable darkness, water and device."),
        ("ref15_arrest", "r15_arrest.png", "The restrained adult lowers both hands to the table while officers hold position; one readable body reaction, stable arms, faces and room."),
        ("ref16_victim_aftermath", "r16_victim_aftermath.png", "The elderly adult lowers the phone slowly, blinks and settles back with a hurt expression; stable face, hands, chair and room."),
    ]
    return [
        _unit(scene, REFERENCE / name, 2.55, 86222001 + index, prompt)
        for index, (scene, name, prompt) in enumerate(rows)
    ]


def _microshot(
    shot_id: str,
    beat_id: str,
    source_unit: str,
    start: float,
    duration: float,
    crop: str,
) -> dict[str, object]:
    return {
        "shot_id": shot_id,
        "beat_id": beat_id,
        "source_unit": source_unit,
        "source_start_seconds": start,
        "duration_seconds": duration,
        "crop": crop,
        "cut": "hard_cut_on_action",
    }


def _a_microshots() -> list[dict[str, object]]:
    rows = [
        ("m01", "b01_boast", 0.0, 0.6, "lower_detail"),
        ("m02", "b01_boast", 0.6, 1.2, "full"),
        ("m03", "b01_boast", 1.8, 1.0, "upper_close"),
        ("m04", "b02_grab_reaction", 0.0, 0.5, "lower_detail"),
        ("m05", "b02_grab_reaction", 0.5, 0.9, "full"),
        ("m06", "b03_object_question", 0.0, 1.2, "upper_close"),
        ("m07", "b03_object_question", 1.2, 0.6, "eye_close"),
        ("m08", "b04_confused_answer", 0.0, 1.5, "upper_close"),
        ("m09", "b05_age_burst", 0.0, 0.5, "lower_detail"),
        ("m10", "b05_age_burst", 0.5, 1.3, "upper_close"),
        ("m11", "b05_age_burst", 1.8, 0.6, "hand_close"),
        ("m12", "b06_pull_away", 0.0, 0.5, "hand_close"),
        ("m13", "b06_pull_away", 0.5, 1.5, "full"),
        ("m14", "b07_protest", 0.0, 0.8, "lower_detail"),
        ("m15", "b07_protest", 0.8, 1.5, "upper_close"),
        ("m16", "b08_offer_one", 0.0, 1.3, "hand_close"),
        ("m17", "b09_offer_two", 0.0, 1.5, "full"),
        ("m18", "b10_offer_three", 0.0, 1.2, "upper_close"),
        ("m19", "b11_flip", 0.0, 0.6, "hand_close"),
        ("m20", "b11_flip", 0.6, 2.7, "upper_close"),
        ("m21", "b12_car_reveal", 0.0, 0.7, "background_detail"),
        ("m22", "b12_car_reveal", 0.7, 1.5, "full"),
        ("m23", "b13_registry_reveal", 0.0, 0.6, "background_detail"),
        ("m24", "b13_registry_reveal", 0.6, 1.0, "upper_close"),
        ("m25", "b14_certificate", 0.0, 0.7, "hand_close"),
        ("m26", "b14_certificate", 0.7, 1.8, "upper_close"),
        ("m27", "b15_terms", 0.0, 0.8, "lower_detail"),
        ("m28", "b15_terms", 0.8, 2.4, "upper_close"),
        ("m29", "b16_escape", 0.0, 1.8, "full"),
        ("m30", "b17a_kiss_reaction", 0.0, 1.4, "upper_close"),
        ("m31", "b17b_hunt_order", 0.0, 2.7, "upper_close"),
        ("m32", "b18_cta", 0.0, 3.9, "full"),
    ]
    return [
        _microshot(shot, beat, beat, start, duration, crop)
        for shot, beat, start, duration, crop in rows
    ]


def build() -> dict[str, object]:
    if _sha256(SOURCE_PLAN) != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("V6.1 source plan hash changed; refusing implicit rebind")
    a_units = _a_units()
    b_units = _b_units()
    microshots_a = _a_microshots()
    microshots_b = []
    for index, unit in enumerate(b_units, start=1):
        scene_id = str(unit["scene_id"])
        microshots_b.extend(
            [
                _microshot(
                    f"r{index:02d}a", scene_id, scene_id, 0.0, 1.275, "full"
                ),
                _microshot(
                    f"r{index:02d}b",
                    scene_id,
                    scene_id,
                    1.275,
                    1.275,
                    "upper_close" if index % 2 else "lower_detail",
                ),
            ]
        )
    return {
        "schema_version": "fanqie_v62_microshot_workflow/v2",
        "task_id": 1,
        "source_story_plan": str(SOURCE_PLAN.resolve()),
        "source_story_plan_sha256": EXPECTED_SOURCE_SHA256,
        "story_contract_unchanged": True,
        "audio_source": str(
            (
                ROOT
                / r"data\qa\task1_story_v61_full_candidate_20260821_1820_fullonly\candidate.mp4"
            ).resolve()
        ),
        "subtitle_source": str(
            (
                ROOT
                / r"data\qa\task1_story_v61_full_candidate_20260821_1820_fullonly\candidate.srt"
            ).resolve()
        ),
        "delivery": {
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "target_duration_seconds": 40.8,
            "hard_cut_only": True,
        },
        "motion_gate": {
            "maximum_duplicate_ratio": 0.20,
            "minimum_mean_frame_distance": 0.50,
            "minimum_smoothness_score": 65.0,
            "maximum_failed_microshots": 0,
            "interpolation_cannot_replace_missing_motion": True,
        },
        "variants": {
            "original_recomposed": {
                "role": "publishable_candidate_after_human_and_platform_gates",
                "reference_frames_are_internal_only": True,
                "all_story_beats_use_new_original_anchors": True,
                "new_framepack_units": a_units,
                "reuse_sources": {},
                "microshots": microshots_a,
                "publish_allowed": False,
                "fanqie_backfill_allowed": False,
            },
            "direct_reference_i2v": {
                "role": "internal_motion_reference",
                "contains_reference_people_or_watermark": True,
                "new_framepack_units": b_units,
                "reuse_sources": {},
                "microshots": microshots_b,
                "publish_allowed": False,
                "fanqie_backfill_allowed": False,
                "frontend_approval_cannot_authorize_publication": True,
            },
        },
    }


def main() -> int:
    payload = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(OUTPUT)
    print(_sha256(OUTPUT))
    print(len(payload["variants"]["original_recomposed"]["microshots"]))
    print(len(payload["variants"]["direct_reference_i2v"]["microshots"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
