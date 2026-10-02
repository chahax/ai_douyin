"""Build the reviewed-anchor V6.1 plan without modifying the V6 source plan."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


PROJECT = Path(r"D:\IT\ai_douyin")
SOURCE = PROJECT / "data/fanqie_promotion/scene_plans/task1_story_v6_performance_driven_ready.json"
OUTPUT = PROJECT / "data/fanqie_promotion/scene_plans/task1_story_v61_reviewed_anchors.json"
ANCHOR_DIR = PROJECT / "data/fanqie_promotion/assets/task1_story_v6/shot_anchors"

ANCHORS = {
    "b01_boast": "01_walk_phone_anchor_v3.png",
    "b02_grab_reaction": "02_wrist_pull_action_anchor_v2.png",
    "b03_object_question": "03_direct_question_anchor_v3.png",
    "b04_confused_answer": "04_self_point_anchor_v3.png",
    "b05_age_burst": "05_watch_glance_anchor_v3.png",
    "b06_pull_away": "06_reach_stride_anchor_v3.png",
    "b07_protest": "07_guard_retreat_anchor_v3.png",
    "b08_offer_one": "08_one_finger_anchor_v3.png",
    "b09_offer_two": "09_two_fingers_anchor_v3.png",
    "b10_offer_three": "10_three_fingers_anchor_v3.png",
    "b11_flip": "11_phone_eager_anchor_v3.png",
    "b12_car_reveal": "12_car_arrived_anchor_v3.png",
    "b13_registry_reveal": "13_civic_shock_anchor_v3.png",
    "b14_certificate": "14_blank_red_booklet_anchor_v3.png",
    "b15_terms": "15_terms_booklet_anchor_v3.png",
    "b16_escape": "16_escape_pivot_anchor_v3.png",
    "b17a_kiss_reaction": "17a_lip_touch_anchor_v3.png",
    "b17b_hunt_order": "17b_phone_order_anchor_v3.png",
    "b18_cta": "18_gate_chase_anchor_v3.png",
}

MOTIONS = {
    "b01_boast": "Continue one brisk step, finish pocketing the phone, open the free hand once, then raise one eyebrow into a smug grin. Never wave.",
    "b02_grab_reaction": "Keep the reviewed wrist grip fixed while the woman pulls once toward camera-right; the man lurches one step and shows clear surprise.",
    "b03_object_question": "Maintain the locked eye-line, lift the chin a few centimeters, and articulate one short question with minimal head motion.",
    "b04_confused_answer": "Blink once, keep the index finger pointing at his own chest, and lean back a few centimeters in confusion.",
    "b05_age_burst": "Snap the eyes from the wristwatch to the off-screen man, then lift exactly one impatient index finger once. Keep one body and one face only.",
    "b06_pull_away": "Close the extended hand on an off-screen adult hand and take one decisive step to camera-right. Keep the frame limited to the reviewed woman and that off-screen adult hand.",
    "b07_protest": "Retreat one short step while both hands remain guarding the waist; scan the off-screen woman with alarm.",
    "b08_offer_one": "Keep exactly one index finger raised, hold the body steady, and deliver the one-word offer without blinking.",
    "b09_offer_two": "Keep exactly two fingers raised, step forward only a few centimeters, and sharpen the impatient eye-line.",
    "b10_offer_three": "Keep exactly three fingers raised and perform one precise eyebrow lift; no other body motion.",
    "b11_flip": "Finish pulling out the phone, lean closer once, and brighten into an eager flattering smile.",
    "b12_car_reveal": "Keep the woman and already-stopped sedan stable; lower the signaling hand slightly into a faint confident smile. No people appear in the car.",
    "b13_registry_reveal": "Freeze, crane the neck upward a little more, and widen the eyes into a short shocked exclamation.",
    "b14_certificate": "Close the blank red booklet once, look up, and widen the eyes into a disbelieving half-smile. Never add text or an emblem.",
    "b15_terms": "Move the blank red booklet toward the handbag once, tilt the head slightly, and hold a cool challenging look.",
    "b16_escape": "Complete the pivot and sprint down the steps for one stride while keeping the quick goodbye wave readable.",
    "b17a_kiss_reaction": "Keep eyes open and fingertips touching the lower lip; tighten exactly one mouth corner into a subtle dangerous smile. No blink, open mouth, or hand withdrawal.",
    "b17b_hunt_order": "Keep the phone at the ear, speak with controlled authority, then turn the eyes sharply back on the final name.",
    "b18_cta": "Continue the sprint for one stride, look back over the shoulder once, and accelerate as the distant sedan remains behind at a safe scale.",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> None:
    plan = json.loads(SOURCE.read_text(encoding="utf-8"))
    seen = set()
    for beat in plan["beats"]:
        scene_id = beat["id"]
        if scene_id not in ANCHORS:
            raise RuntimeError(f"No reviewed anchor mapped for {scene_id}")
        anchor = ANCHOR_DIR / ANCHORS[scene_id]
        if not anchor.is_file():
            raise FileNotFoundError(anchor)
        beat["shot_anchor_image"] = anchor.as_posix()
        beat["shot_anchor_sha256"] = sha256(anchor)
        beat["visible_action"] = MOTIONS[scene_id]
        beat["anchor_review_status"] = "approved_for_video_smoke"
        if scene_id == "b18_cta":
            beat["beat_type"] = "promotional_cta"
            beat["delivery_mode"] = "on_camera_character"
            beat["text"] = "搜“我闭着眼睛玩”，看我们的后续。"
            beat["instruct"] = (
                "边跑边说，呼吸略急但字清楚；推广短句自然直接，"
                "重读“我闭着眼睛玩”和“后续”，避免播音腔。"
            )
        seen.add(scene_id)
    if seen != set(ANCHORS):
        raise RuntimeError(f"Plan/mapping mismatch: {sorted(set(ANCHORS) - seen)}")
    plan["schema_version"] = "fanqie_performance_story_plan/v1"
    plan["plan_revision"] = "v6.1-reviewed-action-anchors"
    plan["status"] = "reviewed_anchor_smoke_ready"
    plan["publish_allowed"] = False
    plan["creative_contract"]["cta_delivery_mode"] = "on_camera_character"
    plan["creative_contract"]["voiceover_allowed"] = False
    plan["cast"]["lin_xia"]["voice_reference_sha256"] = sha256(
        Path(plan["cast"]["lin_xia"]["voice_reference"])
    )
    plan["cast"]["luo_xuewei"]["voice_reference_sha256"] = sha256(
        Path(plan["cast"]["luo_xuewei"]["voice_reference"])
    )
    plan["source_plan_sha256"] = sha256(SOURCE)
    plan["visual_review_evidence"] = (
        "D:/IT/ai_douyin/data/qa/task1_story_v6_partial_visual_review.json"
    )
    plan["next_gate"] = (
        "Render failed-scene smoke tests first; machine and human review are required "
        "before full assembly. Publishing remains forbidden."
    )
    OUTPUT.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT),
        "sha256": sha256(OUTPUT),
        "scene_count": len(plan["beats"]),
        "publish_allowed": plan["publish_allowed"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
